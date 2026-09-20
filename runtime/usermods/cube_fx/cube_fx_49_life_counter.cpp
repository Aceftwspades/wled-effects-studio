#include "wled.h"
#include "cube_fx_common.h"
#include "cube_fx_bank.h"

// ===========================================================================
// Ace 3-D Life Counter - a Magic: The Gathering life tracker on the cube
// ===========================================================================
// A utility, not a light show. The lid carries a mana symbol; the four walls
// each carry a player's life total as two big digits, upright from where that
// player sits. The four life totals ARE the first four sliders - Player 1 to
// Player 4, slider value = life, no scaling - so they read as plain numbers in
// the web UI and on the OLED's params page, and a knob turn is a point of
// life. Custom 3 picks the symbol.
//
// ---------------------------------------------------------------------------
// EVERY WALL IS UPRIGHT FOR THE PERSON FACING IT
// ---------------------------------------------------------------------------
// The net unfolds from the lid, so the walls do not share an orientation in
// pixel space: south is upright, north is upside down, west and east are on
// their sides in opposite directions. Each wall gets its own glyph-to-net
// mapping, derived from cfx_pos the same way the effects derive their
// geometry - the wall's "up" is +Z, its "right" is facing x up - so if a
// face is ever rewired in cfx_pos, the mapping here reads through the same
// five lines and follows. The lid is drawn with north at the top.
//
// ---------------------------------------------------------------------------
// DIGITS, AND NUMBERS OVER 99
// ---------------------------------------------------------------------------
// A 3 x 5 font, two digits with a two-pixel gap, edge to edge on an 8 x 8 face.
// Anything wider does not fit and anything smaller does not read. Life over
// 99 - it happens in Commander - keeps the two digits it can show and adds an
// OVERLINE across the top row for the hundred; over 199, an underline as well.
// A three-digit face was tried on paper: three 2-wide glyphs fit exactly and
// cannot tell a 6 from an 8, which for a counter is worse than a convention.
//
// Everything is authored at 8 x 8 and scaled to the face, so a 16-pixel cube
// gets the same glyphs at twice the size rather than a different design.
//
// ---------------------------------------------------------------------------
// WHAT THE CHECKBOXES DO
// ---------------------------------------------------------------------------
//   Low life   a wall at 5 life or under pulses slowly; at 0 it shows a dim
//              skull instead of the number, because a dead player's wall
//              should say so from across the table.
//   Breathe    the lid symbol breathes gently, so the cube reads as on rather
//              than frozen. Off, it is a static glyph.
//   Flat mode  a panel gets the four numbers in a 2 x 2 grid and no symbol.
// ===========================================================================

#define LC_NSYM 6

// The five mana symbols and colourless, 8 x 8, one byte a row, MSB left.
static const uint8_t LC_SYM[LC_NSYM][8] PROGMEM = {
  { 0x18, 0x5A, 0x3C, 0xE7, 0xE7, 0x3C, 0x5A, 0x18 },   // W  sun
  { 0x10, 0x10, 0x38, 0x38, 0x7C, 0x7C, 0x7C, 0x38 },   // U  drop
  { 0x3C, 0x7E, 0xFF, 0x99, 0x99, 0xFF, 0x24, 0x3C },   // B  skull
  { 0x08, 0x12, 0x34, 0x7C, 0x7E, 0xFE, 0x7C, 0x38 },   // R  flame
  { 0x18, 0x3C, 0x7E, 0xFF, 0x7E, 0x18, 0x18, 0x3C },   // G  tree
  { 0x18, 0x3C, 0x7E, 0xE7, 0xE7, 0x7E, 0x3C, 0x18 },   // C  diamond
};
static const uint8_t LC_SYMRGB[LC_NSYM][3] PROGMEM = {
  { 255, 214, 110 }, {  30, 120, 255 }, { 150, 140, 130 },
  { 255,  78,  10 }, {  40, 205,  60 }, { 170, 170, 195 },
};

// 3 x 5 digits, one byte a row, three low bits used, MSB of the three left.
static const uint8_t LC_DIG[10][5] PROGMEM = {
  { 7, 5, 5, 5, 7 }, { 2, 6, 2, 2, 7 }, { 7, 1, 7, 4, 7 }, { 7, 1, 7, 1, 7 },
  { 5, 5, 7, 1, 1 }, { 7, 4, 7, 1, 7 }, { 7, 4, 7, 5, 7 }, { 7, 1, 1, 1, 1 },
  { 7, 5, 7, 5, 7 }, { 7, 5, 7, 1, 7 },
};

struct LcState {
  uint8_t  mode;
  uint8_t  clk[2];
  uint16_t breath;
  uint16_t cycle;
};

// Is glyph pixel (gx, gy) of an 8 x 8 number face lit for this life total?
static inline bool lc_numberPix(int life, int gx, int gy) {
  if (life > 255) life = 255;
  const int hund = life / 100, rest = life % 100;
  if (hund >= 1 && gy == 0) return true;                 // overline: +100
  if (hund >= 2 && gy == 7) return true;                 // underline: +200
  if (gy < 2 || gy > 6) return false;
  const int row = gy - 2;
  const int tens = rest / 10, ones = rest % 10;
  if (tens == 0 && hund == 0) {                          // one digit, centred
    if (gx < 3 || gx > 5) return false;
    return (pgm_read_byte(&LC_DIG[ones][row]) >> (5 - gx)) & 1;
  }
  // Columns 0-2 and 5-7: a two-pixel gap and no margin, which is the only
  // symmetric way to put two 3-wide digits on eight pixels.
  if (gx <= 2)            return (pgm_read_byte(&LC_DIG[tens][row]) >> (2 - gx)) & 1;
  if (gx >= 5 && gx <= 7) return (pgm_read_byte(&LC_DIG[ones][row]) >> (7 - gx)) & 1;
  return false;
}

static inline bool lc_symPix(int sym, int gx, int gy) {
  return (pgm_read_byte(&LC_SYM[sym][gy]) >> (7 - gx)) & 1;
}

static FX_RET mode_lifecounter() {
  if (!strip.isMatrix || !SEGMENT.is2D()) { SEGMENT.fill(SEGCOLOR(0)); FX_DONE; }
  const int cols = SEG_W, rows = SEG_H;
  if (cols < 8 || rows < 8) { SEGMENT.fill(SEGCOLOR(0)); FX_DONE; }

  const bool cube = cfx_isCube(cols, rows);
  const int  B    = cube ? (cols / 3) : 1;

  if (!SEGENV.allocateData(sizeof(LcState))) { SEGMENT.fill(SEGCOLOR(0)); FX_DONE; }
  LcState *s = (LcState *)SEGENV.data;

  const uint8_t want = (uint8_t)(cube ? 1 : 2);
  if (SEGENV.call == 0 || s->mode != want) {
    s->mode = want; s->clk[0] = s->clk[1] = 0;
    s->breath = 0; s->cycle = 0;
  }
  uint16_t dt = fx_dt8(s->clk);
  if (dt > 60) dt = 60;
  s->breath = (uint16_t)(s->breath + dt * 14u);          // ~4.7 s a breath
  s->cycle  = (uint16_t)(s->cycle + dt * 4u);            // ~16 s round the six

  // --- the numbers ----------------------------------------------------------
  const int life[4] = { (int)SEGMENT.speed, (int)SEGMENT.intensity,
                        (int)SEGMENT.custom1, (int)SEGMENT.custom2 };
  const bool lowAlert = SEGMENT.check1;
  const bool breathe  = SEGMENT.check2;

  // Custom 3: 0-5 pick a symbol, anything above cycles through them.
  int sym = SEGMENT.custom3;
  if (sym >= LC_NSYM) sym = (s->cycle * LC_NSYM) >> 16;

  // Player colours from the palette, a quarter of the wheel apart. Static -
  // a counter that drifted colour would look like it was doing something.
  uint32_t pcol[4];
  for (int i = 0; i < 4; i++) pcol[i] = SEGMENT.color_from_palette((uint8_t)(i * 64 + 32), false, true, 0);

  const uint8_t br = (uint8_t)(128 + (int)((cfx_sinf16((float)s->breath * (6.28318531f / 65536.0f)) + 1.0f) * 63.5f));
  // low-life pulse: a slow full swing
  const uint8_t pulse = (uint8_t)(100 + (int)(cfx_sinf16((float)s->breath * (2.0f * 6.28318531f / 65536.0f)) * 77.0f + 77.0f));

  uint32_t srgb;
  { const uint8_t r = pgm_read_byte(&LC_SYMRGB[sym][0]), g = pgm_read_byte(&LC_SYMRGB[sym][1]),
                  b = pgm_read_byte(&LC_SYMRGB[sym][2]);
    srgb = RGBW32(r, g, b, 0); }
  const uint8_t symBri = breathe ? (uint8_t)(150 + (br * 105) / 255) : 255;

  // --- paint ----------------------------------------------------------------
  if (!cube) {
    // A panel: four numbers in a 2 x 2 grid, each cell scaled from 8 x 8.
    const int cw = cols / 2, ch = rows / 2;
    for (int y = 0; y < rows; y++) for (int x = 0; x < cols; x++) {
      const int qx = x / cw, qy = y / ch;
      const int p  = (qy * 2 + qx) & 3;
      const int gx = ((x % cw) * 8) / cw, gy = ((y % ch) * 8) / ch;
      uint32_t c = 0;
      if (lc_numberPix(life[p], gx, gy)) {
        c = pcol[p];
        if (lowAlert && life[p] <= 5) c = mq_scale(c, pulse);
      }
      SEGMENT.setPixelColorXY(x, y, c);
    }
    FX_DONE;
  }

  CFX_NET_PREP();
  for (int y = 0; y < rows; y++) {
    CFX_NET_ROW(y);
    for (int x = 0; x < cols; x++) {
      CFX_NET_SKIP(x);
      const int bx = x / B, by = y / B;
      const int lx = x % B, ly = y % B;
      // face-local pixel, scaled to the 8 x 8 design grid
      const int px = (lx * 8) / B, py = (ly * 8) / B;
      const int R  = 7;                                   // 8 - 1
      uint32_t c = 0;

      if (bx == 1 && by == 1) {
        // TOP: X = a (right = +x), Y = -b (north = -y). Drawn north-up.
        if (lc_symPix(sym, px, py)) c = mq_scale(srgb, symBri);
      } else {
        // Each wall: (gx right, gy down) for the viewer facing it, from the
        // cfx_pos frame. up = +Z, right = facing x up.
        int p, gx, gy;
        if      (bx == 1 && by == 2) { p = 0; gx = px;     gy = py;     }   // SOUTH: upright
        else if (bx == 2 && by == 1) { p = 1; gx = R - py; gy = px;     }   // EAST:  up = -x, right = -y
        else if (bx == 1 && by == 0) { p = 2; gx = R - px; gy = R - py; }   // NORTH: up = +y, right = -x
        else                         { p = 3; gx = py;     gy = R - px; }   // WEST:  up = +x, right = +y
        const int L = life[p];
        if (lowAlert && L <= 0) {
          // eliminated: a dim skull, so the wall says so from across the table
          if (lc_symPix(2, gx, gy)) c = mq_scale(pcol[p], 120);
        } else if (lc_numberPix(L, gx, gy)) {
          c = pcol[p];
          if (lowAlert && L <= 5) c = mq_scale(c, pulse);
        }
      }
      SEGMENT.setPixelColorXY(x, y, c);
    }
  }
  FX_DONE;
}

static const char _data_FX_MODE_LIFECOUNTER[] PROGMEM =
  "Ace 3-D Life Counter@Player 1,Player 2,Player 3,Player 4,Mana,Low life,Breathe,Flat mode;;!;2f;sx=20,ix=20,c1=20,c2=20,c3=6,o1=1,o2=1,pal=6";


// ---------------------------------------------------------------------------
// Registration - joins the effect bank, which decides whether this effect
// claims one of the device's limited effect slots. See cube_fx_bank.h.
// ---------------------------------------------------------------------------
static CfxBankReg cube_fx_49_lifecounter_reg(&mode_lifecounter, _data_FX_MODE_LIFECOUNTER);
