#include "wled.h"
#include "cube_fx_common.h"
#include "cube_fx_bank.h"

// Linear falloff around a signed boundary distance: full at d<=-soft, zero at
// d>=soft, a straight ramp between. Used for every soft edge in Split GEQ so
// the fill and inverse-fill logic is identical regardless of which side of
// the boundary "inside" is on - the caller only has to get the sign of d right.
static inline uint8_t cfx_edgeTaper(int d, int soft) {
  if (soft < 1) soft = 1;
  if (d <= -soft) return 255;
  if (d >=  soft) return 0;
  return (uint8_t)(255 - (((d + soft) * 255) / (2 * soft)));
}

// Per-face polar coordinates for a circular treatment on every face of the
// net: TOP plus all four walls, each with its own centre and its own
// inscribed circle. rad is 0 at a face's centre and 255 at the circle
// touching its edges (corners clamp to 255, so they read as rim rather than
// as an out-of-range value). ang is the usual 0..255 atan2 wrap.
// faceId: 0 top, 1 north, 2 south, 3 west, 4 east. Flat panels get one face.
static void cfx_buildFaceCircle(uint8_t *rad, uint8_t *ang, uint8_t *faceId,
                                int cols, int rows, bool cubeNet, int B) {
  for (int y = 0; y < rows; y++) {
    for (int x = 0; x < cols; x++) {
      const size_t i = (size_t)y * cols + x;
      float cxf, cyf, maxR;
      uint8_t fid;
      if (cubeNet) {
        const int bx = x / B, by = y / B;
        fid = (bx == 1 && by == 1) ? 0 : (uint8_t)(by == 0 ? 1 : (by == 2 ? 2 : (bx == 0 ? 3 : 4)));
        cxf = (float)(x % B) - (B - 1) * 0.5f;
        cyf = (float)(y % B) - (B - 1) * 0.5f;
        maxR = (B - 1) * 0.5f;
      } else {
        fid = 0;
        cxf = (float)x - (cols - 1) * 0.5f;
        cyf = (float)y - (rows - 1) * 0.5f;
        maxR = 0.5f * (float)((cols < rows) ? cols : rows);
      }
      float r = sqrtf(cxf * cxf + cyf * cyf) * (255.0f / (maxR > 0.5f ? maxR : 0.5f));
      rad[i] = (r > 255.0f) ? 255 : (uint8_t)r;
      ang[i] = (uint8_t)(int)(atan2f(cyf, cxf) * (128.0f / 3.14159265f) + 256.5f);
      faceId[i] = fid;
    }
  }
}

// ===========================================================================
// 14. ACE 3-D SPLIT GEQ
// ===========================================================================
// Baseline: the four walls run a GEQ split at the equator - bars grow away
// from the middle row toward the top and bottom rims together, the way a
// mirrored analyser normally works. The top face runs a CIRCULAR GEQ: each
// wedge grows from the centre OUTWARD as its band gets louder, exactly the
// treatment the walls take when Circles in all faces is on.
//
// Inverse edge EQ (o1) flips the fill direction everywhere, top face included:
// wall bars fill inward from each rim instead of outward from the equator, and
// the circles close from the rim toward their centres.
//
// Circles in all faces (o2) replaces the wall bars with the top face's own
// treatment - every wall becomes a small circular GEQ centred on itself.
//
// With BOTH on, every face is a circle running rim-inward, and a bright ring
// spawns on every beat and collapses from the rim to the centre across all
// five faces at once - the requested "circles pulsing inwards".
//
// ---------------------------------------------------------------------------
// SPIN
// ---------------------------------------------------------------------------
// The second slider is rotation, not brightness. 128 is locked; above that
// spins one way and below it the other, faster the further from centre. Each
// face turns about ITS OWN centre - the angular coordinate is built per face -
// so the whole net appears to rotate together rather than as one flat image
// being spun. In bar mode there is no angle to turn, so the same control walks
// the band assignment around the ring instead and the bars march around the
// cube.
// ---------------------------------------------------------------------------
#define SG_PULSE 2

// Slider counts either side of centre that still count as "locked". Without it
// a slider resting one step off centre creeps round over a few minutes, which
// looks like a bug rather than a very slow spin.
#define SG_SPIN_DEAD 2

static FX_RET mode_split_geq() {
  if (!strip.isMatrix || !SEGMENT.is2D()) { SEGMENT.fill(SEGCOLOR(0)); FX_DONE; }
  const int cols = SEG_W, rows = SEG_H;
  if (cols < 6 || rows < 6) { SEGMENT.fill(SEGCOLOR(0)); FX_DONE; }
  const size_t n = (size_t)cols * rows;
  if (!SEGENV.allocateData(5 * n + 16 + 16)) { SEGMENT.fill(SEGCOLOR(0)); FX_DONE; }

  uint8_t *bu  = SEGENV.data;
  uint8_t *bv  = bu + n;
  uint8_t *rad = bv + n;
  uint8_t *ang = rad + n;
  uint8_t *fid = ang + n;
  uint8_t *spec = fid + n;             // smoothed 16-band spectrum
  uint8_t *st   = spec + 16;
  // st: [0] built [1..2] clock [3] round robin, [4..11] SG_PULSE x (born lo,hi,
  //     strength,live), [12..13] rotation phase

  const bool cube = cfx_isCube(cols, rows);
  const int  B    = cube ? (cols / 3) : 1;
  if (SEGENV.call == 0 || st[0] != (uint8_t)(cube ? 1 : 2)) {
    cfx_buildBand(bu, bv, cols, rows, cube, B);
    cfx_buildFaceCircle(rad, ang, fid, cols, rows, cube, B);
    for (int k = 0; k < 16; k++) spec[k] = 0;
    for (int k = 1; k < 16; k++) st[k] = 0;
    st[0] = (uint8_t)(cube ? 1 : 2);
  }

  um_data_t     *um   = cfx_getAudioData();
  const uint8_t *fft  = (uint8_t *)um->u_data[2];
  const uint8_t  peak = fx_lowBeat(um);
  const float    vol  = *(float *)um->u_data[0];
  const uint16_t dtQ  = fx_dt8(st + 1);

  cfx_smoothSpec(spec, fft, (uint8_t)(2 + (SEGMENT.custom3 >> 2)));

  const bool invEdge  = SEGMENT.check1;
  const bool circWall = SEGMENT.check2;
  const bool combo    = invEdge && circWall;

  const int gain = 60 + (int)SEGMENT.custom1;              // fill amplitude
  const int soft = 6 + (SEGMENT.custom2 >> 2);              // edge / ring width, shared scale
  const int half = (cube ? B : rows) / 2;                   // equator row for bar mode

  // --- beat-triggered collapsing rings, combo only --------------------------
  const uint16_t nowT = (uint16_t)strip.now;
  if (combo && peak) {
    const int slot = st[3] % SG_PULSE; st[3] = (uint8_t)(st[3] + 1);
    uint8_t *e = st + 4 + slot * 4;
    e[0] = (uint8_t)(nowT & 0xFF); e[1] = (uint8_t)(nowT >> 8); e[2] = peak; e[3] = 1;
  }
  int pRing[SG_PULSE], pStr[SG_PULSE]; int pN = 0;
  const int growth = 2 + (SEGMENT.speed >> 3);
  for (int k = 0; k < SG_PULSE; k++) {
    uint8_t *e = st + 4 + k * 4;
    if (!e[3]) continue;
    const uint16_t born = (uint16_t)e[0] | ((uint16_t)e[1] << 8);
    const int travel = ((int)(uint16_t)(nowT - born) * growth) / 32;
    if (travel > 255 + soft) { e[3] = 0; continue; }
    const int life = 255 - (travel * 255) / (255 + soft);
    pRing[pN] = 255 - travel;
    pStr[pN]  = scale8(e[2], (uint8_t)life);
    pN++;
  }

  // --- face rotation ---------------------------------------------------------
  // Accumulated at 1/256 of an angle unit so the slowest settings still turn
  // smoothly instead of stepping a whole pixel at a time. st[12..13] are the
  // last two bytes of the state block, past the SG_PULSE ring slots.
  const int spin = (int)SEGMENT.intensity - 128;            // -128 locked-centre +127
  uint16_t rphase = (uint16_t)st[12] | ((uint16_t)st[13] << 8);
  if (spin > SG_SPIN_DEAD || spin < -SG_SPIN_DEAD)
    rphase = (uint16_t)((int32_t)rphase + fx_step((int32_t)spin * 24, dtQ));
  st[12] = (uint8_t)(rphase & 0xFF);
  st[13] = (uint8_t)(rphase >> 8);
  const uint8_t angOff = (uint8_t)(rphase >> 8);

  const int ringW   = cube ? (4 * B) : cols;
  const int ringOff = ((int)angOff * ringW) / 256;          // same turn, in ring columns

  const uint8_t drive = cfx_drive(vol, 1.0f, 170);
  const uint8_t hue   = (uint8_t)(strip.now >> 8);

  SEGMENT.fill(SEGCOLOR(0));
  CFX_NET_PREP();
  size_t i = 0;
  for (int y = 0; y < rows; y++) {
    CFX_NET_ROW(y);
    for (int x = 0; x < cols; x++, i++) {
      CFX_NET_SKIP(x);
      const bool isTop = (fid[i] == 0);
      const uint8_t angR = (uint8_t)(ang[i] + angOff);      // this face, turned
      uint8_t lum = 0;

      // Everything - top's fixed inverse circle, wall bars, wall circles when
      // toggled - reduces to one position 0..255 and one fill fraction 0..255,
      // taken from a "normal" (grow from 0 outward) or "inverse" (grow from
      // 255 inward) boundary. cfx_edgeTaper only needs a signed distance to
      // that boundary, so both directions share one formula.
      uint8_t pos, fillFrac; bool inv;
      if (isTop || circWall) {                              // circular GEQ
        const uint8_t bin = (uint8_t)(((uint16_t)angR * 16) >> 8);
        const int fillRaw = ((int)spec[bin] * gain) >> 8;
        fillFrac = (uint8_t)((fillRaw > 255) ? 255 : fillRaw);
        pos = rad[i];
        // Follows Inverse edge EQ like every other face. It used to be pinned
        // inverse, so the toggle appeared to do nothing to the top and the lid
        // was rim-inward while the walls grew centre-out - two different
        // treatments on one cube, with no way to line them up.
        inv = invEdge;
      } else {                                              // split bar around the equator
        int bcol = (int)bu[i] + ringOff;                    // spin walks the bands round
        if (bcol >= ringW) bcol -= ringW;
        const uint8_t bin = (uint8_t)(((uint16_t)bcol * 16) / ringW);
        const int fillRaw = ((int)spec[bin] * gain) >> 8;
        fillFrac = (uint8_t)((fillRaw > 255) ? 255 : fillRaw);
        const int dEq = (int)bv[i] - half;
        pos = (uint8_t)((((dEq < 0) ? -dEq : dEq) * 255) / half);   // 0 at equator, 255 at rim
        inv = invEdge;
      }

      const int boundary = inv ? (255 - (int)fillFrac) : (int)fillFrac;
      const int d = inv ? (boundary - (int)pos) : ((int)pos - boundary);
      lum = cfx_edgeTaper(d, soft);

      for (int k = 0; k < pN; k++) {                        // beat rings, any mode
        int po = (int)pos - pRing[k]; if (po < 0) po = -po;
        if (po >= soft) continue;
        lum = qadd8(lum, scale8((uint8_t)(255 - (po * 255) / soft), (uint8_t)pStr[k]));
      }

      if (!lum) continue;
      const uint32_t c = SEGMENT.color_from_palette((uint8_t)(fid[i] * 40 + (angR >> 2) + hue),
                                                    false, false, 0);
      SEGMENT.setPixelColorXY(x, y, mq_scale(c, scale8((uint8_t)lum, drive)));
    }
  }
  FX_DONE;
}

static const char _data_FX_MODE_SPLIT_GEQ[] PROGMEM =
  "Ace 3-D Split GEQ@Ring speed,Spin,Gain,Softness,Smoothing,Inverse edge EQ,Circles in all faces,Flat mode;;!;2f;sx=110,ix=128,c1=170,c2=110,c3=10,o1=0,o2=0";



// ---------------------------------------------------------------------------
// Registration - joins the effect bank, which decides whether this effect
// claims one of the device's limited effect slots. See cube_fx_bank.h.
// ---------------------------------------------------------------------------
static CfxBankReg cube_fx_14_split_geq_reg(&mode_split_geq, _data_FX_MODE_SPLIT_GEQ);
