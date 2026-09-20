#include "wled.h"
#include "cube_fx_audio.h"
#include "cube_fx_bank.h"

// ===========================================================================
// 20. ACE 3-D MATRIX RAIN
// ===========================================================================
// Falling code. On a flat panel that is the effect everybody has already seen.
// On the cube it needed one decision, and the decision is the whole file.
//
// ---------------------------------------------------------------------------
// WHAT "VERTICAL" MEANS ON A CLOSED NET
// ---------------------------------------------------------------------------
// The four walls are easy: a column of pixels IS a vertical line, and
// cfx_buildBand's fold order already gives 4B seamless columns around the ring
// with no doubled or missing column at any of the four corners. One stream per
// pixel column, exactly as crisp as the original.
//
// The top face is the problem. It is horizontal - nothing can fall down it. The
// three honest options are to leave it dark (looks unfinished on a cube you
// mostly look down at), to flicker it as unrelated noise (reads as a bug), or
// to accept what the geometry is telling you: the top face is the SOURCE. So
// every stream is born at the centre of the top face, runs outward to the rim,
// crosses the fold, and pours down whichever wall it arrives at. One depth
// ruler, measured in pixels, spanning all five faces:
//
//        depth 0 ......... centre of the top face
//        depth TOPD-1 .... the rim
//        depth TOPD ...... first wall row
//        depth DMAX ...... the open bottom edge
//
// Code pours out of a point above the cube and cascades down all four sides.
//
// ---------------------------------------------------------------------------
// THE ALIASING PROBLEM, AND WHY THERE IS A SPAN TABLE
// ---------------------------------------------------------------------------
// 4B columns converge on the top face. At half radius a pixel is worth two
// columns, at quarter radius four, and at the centre it is worth all of them.
// Ask "is column c's head at this depth?" and half the streams simply have no
// pixel to appear in at that radius - they blink into existence partway out,
// and a broken line is the one artefact the eye always catches.
//
// So each top-face pixel owns a GROUP of columns (a power of two, sized per
// radius ring at build time) and takes the brightest of them. The work that
// adds up to is tiny - about 4B lookups per radius ring, ~500 for the whole
// top face of a 48x48 net, against 2304 pixels - and the result is right:
// streams merge into fewer, brighter trunks as they approach the centre and
// fan apart on the way out, which is what convergence should look like.
//
// The groups are dimmed slightly with their size so the centre doesn't burn.
//
// ---------------------------------------------------------------------------
// MUSIC
// ---------------------------------------------------------------------------
//   fall speed     cfx_dropDt(): the whole downpour slows through a riser and
//                  surges under a held bass note
//   kick           a burst of new streams, count proportional to hit strength
//   hats           cfx_hiHit() releases one short, fast stream each - the
//                  flecks between the heavy columns
//   drop           cfx_drop().hit queues a full cascade, released over the
//                  next few frames rather than all in one, so it rolls in
//   build          thickens the rain while the bass is away
//   silence        the rain thins out and dies; cfx_silence().wake starts it
//                  again the frame the music returns
//   spectrum ring  with "Spectrum ring" on, a column's spawn chance is weighted
//                  by the FFT bin for its sector, so the ring becomes a
//                  circular spectrum that pours instead of a bar graph
//
// ---------------------------------------------------------------------------
// CONTROLS
// ---------------------------------------------------------------------------
//   Fall speed, Glow, Density (how many columns run at once), Trail (length),
//   Flicker (glyph change rate), Spawn on beat, Spectrum ring, Flat mode.
//
// Pick a green palette for the film. Anything else and it is rain made of
// light, which is arguably better on a cube.
// ---------------------------------------------------------------------------

#ifndef MX_TOPD_MAX
  #define MX_TOPD_MAX 64        // top-face radius rings we can hold a span for
#endif
#ifndef MX_MAXCOL
  #define MX_MAXCOL 254         // 255 is the gap marker in col[]
#endif
#ifndef MX_LEN_MIN
  #define MX_LEN_MIN 3          // shortest trail, rows
#endif
#ifndef MX_RATE_MIN
  #define MX_RATE_MIN 3         // streams/sec at Density 0, per 64 columns
#endif
#ifndef MX_RATE_SPAN
  #define MX_RATE_SPAN 60       // ...added at Density 255. A stream lives about
                                // two seconds, so ~30/sec is the rate that keeps
                                // most of the ring busy at the default setting.
#endif
#ifndef MX_RELEASE
  #define MX_RELEASE 4          // queued spawns released per frame
#endif
#ifndef MX_GROUP_DIM
  #define MX_GROUP_DIM 30       // brightness lost per doubling of group size
#endif
#ifndef MX_EMERGE
  #define MX_EMERGE 120         // brightness at the top face's centre, of 255.
                                // All four walls' tails converge on the middle
                                // pixels, so without a ramp inward the centre
                                // sums into a hard dot. This fades it to a pool.
#endif
#ifndef MX_RIM_SLACK
  #define MX_RIM_SLACK 4        // columns a ring may leave unshown before its
                                // group size doubles - see mx_buildMap()
#endif
#ifndef MX_HUE_RATE
  #define MX_HUE_RATE 5         // palette drift
#endif

// ---------------------------------------------------------------------------
// GLYPHS
// ---------------------------------------------------------------------------
// A single LED has no internal shape, so "a character" can only exist by
// grouping several adjacent columns into one cell and using a tiny bitmap
// font to decide which of those pixels are lit. MX_GLYPH_W columns share one
// stream (same head position/speed/brightness - they have to, to draw one
// coherent glyph), and MX_GLYPH_H rows of the trail are one character tall.
//
// These are stylised strokes, not actual katakana - there is no readable
// font at 3x5, so this aims for "looks like falling code" rather than
// literal characters. Bit 2 is the left column, bit 0 the right column.
#ifndef MX_GLYPH_W
  #define MX_GLYPH_W 3
#endif
#ifndef MX_GLYPH_H
  #define MX_GLYPH_H 5
#endif
#ifndef MX_GLYPH_BG
  #define MX_GLYPH_BG 55        // brightness (of 255) for the non-ink part of a glyph cell
#endif
#define MX_GLYPH_COUNT 12
static const uint8_t MX_FONT[MX_GLYPH_COUNT][MX_GLYPH_H] PROGMEM = {
  {0b010, 0b010, 0b010, 0b010, 0b010},   // bar
  {0b101, 0b101, 0b101, 0b101, 0b111},   // legs
  {0b111, 0b010, 0b010, 0b010, 0b010},   // flag
  {0b010, 0b010, 0b010, 0b010, 0b111},   // foot
  {0b010, 0b111, 0b010, 0b010, 0b010},   // cross
  {0b111, 0b101, 0b101, 0b101, 0b111},   // box
  {0b100, 0b100, 0b010, 0b001, 0b001},   // zigzag
  {0b101, 0b000, 0b101, 0b000, 0b101},   // dots
  {0b111, 0b000, 0b000, 0b111, 0b000},   // two bars
  {0b100, 0b100, 0b111, 0b001, 0b001},   // step
  {0b111, 0b000, 0b111, 0b000, 0b111},   // three bars
  {0b000, 0b010, 0b111, 0b010, 0b000},   // diamond
};

#define MX_ST_MODE 0
#define MX_ST_CLK  1            // + 2, fx_dt8
#define MX_ST_ACC  3            // + 4, spawn accumulator (uint16)
#define MX_ST_HUE  5            // + 6, palette drift (uint16)
#define MX_ST_PEND 7            // queued spawns waiting to be released
#define MX_ST_LEN  8

// Per-column stream state, gathered so the spawn helper isn't eight arguments.
struct MxCols {
  int16_t *pos;                 // head depth, Q4 rows
  uint8_t *spd;                 // per-stream speed, 128 = nominal
  uint8_t *len;                 // trail length, rows
  uint8_t *bri;                 // 0 = idle, else stream brightness
  uint8_t *hue;                 // palette offset for this stream
  int      ncol;
};

// Cheap spatial hash for the glyph flicker. The casts to unsigned MUST happen
// before the multiply - signed overflow is undefined behaviour and the
// optimiser is entitled to do anything it likes with it.
static inline uint8_t mx_hash(int a, int b, int c) {
  uint32_t h = (uint32_t)a * 374761393u + (uint32_t)b * 668265263u
             + (uint32_t)c * 2246822519u;
  h = (h ^ (h >> 13)) * 1274126177u;
  return (uint8_t)(h >> 24);
}

// Where a ray from the top face's centre leaves through one edge: t/den in
// -1..1 mapped to a cell index along that edge.
static inline int mx_edge(int t, int den, int B) {
  int idx = ((t + den) * B) / (2 * den);
  if (idx < 0)      idx = 0;
  if (idx > B - 1)  idx = B - 1;
  return idx;
}

// ---------------------------------------------------------------------------
// Geometry: column and depth for every pixel, plus the per-ring group size for
// the top face. Walls follow cfx_buildBand's fold order exactly, so this ring
// agrees with every other effect that walks the band.
// ---------------------------------------------------------------------------
static void mx_buildMap(uint8_t *col, uint8_t *dep, uint8_t *tsp, uint8_t *lcol,
                        int cols, int rows, bool cube, int B,
                        int ncol, int topd, int depShift) {
  uint16_t cnt[MX_TOPD_MAX];
  for (int k = 0; k < MX_TOPD_MAX; k++) { cnt[k] = 0; tsp[k] = 1; }

  for (int y = 0; y < rows; y++) {
    for (int x = 0; x < cols; x++) {
      const size_t i = (size_t)y * cols + x;

      if (!cube) {                                   // flat: straight down
        int cg = x / MX_GLYPH_W;
        if (cg >= ncol) cg = ncol - 1;                // extremely wide panel: last group absorbs the remainder
        col[i]  = (uint8_t)cg;
        lcol[i] = (uint8_t)(x % MX_GLYPH_W);
        dep[i] = (uint8_t)(depShift ? ((y * 255) / (rows - 1)) : y);
        continue;
      }

      const int bx = x / B, by = y / B, lx = x % B, ly = y % B;
      if (bx != 1 && by != 1) { col[i] = 255; dep[i] = 0; lcol[i] = 0; continue; }   // gap corner

      if (bx == 1 && by == 1) {                      // TOP: radial, centre out
        const int ax = 2 * lx - (B - 1), ay = 2 * ly - (B - 1);
        const int aax = (ax < 0) ? -ax : ax, aay = (ay < 0) ? -ay : ay;
        const int r2  = (aax > aay) ? aax : aay;
        const int d   = r2 >> 1;
        dep[i] = (uint8_t)d;
        if (d < MX_TOPD_MAX) cnt[d]++;

        if (r2 == 0) { col[i] = 0; lcol[i] = 0; continue; }   // dead centre, odd B only

        // An exact diagonal leaves through a CORNER of the ring, and the tie
        // has to be broken by quadrant rather than folded into one of the two
        // edges. Fold it and both diagonals land on north/south - which on the
        // innermost ring, where all four pixels are diagonals, means east and
        // west are never named at all and half the ring goes dark in the
        // middle of the top face.
        int c;
        if (aay > aax) {
          const int idx = mx_edge(ax, aay, B);
          c = (ay < 0) ? idx                         // NORTH
                       : (2 * B + (B - 1 - idx));    // SOUTH
        } else if (aax > aay) {
          const int idx = mx_edge(ay, aax, B);
          c = (ax > 0) ? (B + idx)                   // EAST
                       : (3 * B + (B - 1 - idx));    // WEST
        } else {
          c = (ay < 0) ? ((ax < 0) ? 0 : B)          // NW / NE corner
                       : ((ax > 0) ? (2 * B) : (3 * B));  // SE / SW corner
        }
        // Reduce to the same grouped-stream space the walls use below, so a
        // stream born at the rim lines up with the wide column it pours into.
        col[i]  = (uint8_t)(c / MX_GLYPH_W);
        lcol[i] = 0;
        continue;
      }

      int bu, bv;                                    // walls, cfx_buildBand order
      if      (by == 0) { bu = lx;                     bv = B - 1 - ly; }  // NORTH
      else if (bx == 2) { bu = B + ly;                 bv = lx;         }  // EAST
      else if (by == 2) { bu = 2 * B + B - 1 - lx;     bv = ly;         }  // SOUTH
      else              { bu = 3 * B + B - 1 - ly;     bv = B - 1 - lx; }  // WEST
      col[i]  = (uint8_t)(bu / MX_GLYPH_W);
      lcol[i] = (uint8_t)(bu % MX_GLYPH_W);
      dep[i] = (uint8_t)(topd + bv);
    }
  }

  if (!cube) return;

  // Group size per radius ring: the smallest power of two that lets that ring's
  // pixels show every column. Rounding UP matters - round down and some columns
  // have no pixel at that radius, so those streams blink out for one row every
  // lap, always in the same directions, which reads as a dark spoke.
  //
  // MX_RIM_SLACK is the one concession. The outermost ring is a square border of
  // 4B-4 pixels but the fold it meets has 4B columns, so it is four short purely
  // from counting corners once. Without the slack that ring doubles to a group
  // of two, every rim pixel shows a column that isn't the one on the wall
  // directly below it, and every stream kinks sideways as it crosses the fold.
  for (int d = 0; d < topd && d < MX_TOPD_MAX; d++) {
    const int have = cnt[d] ? (int)cnt[d] : 1;
    int sp = 1;
    while (sp * have + MX_RIM_SLACK < ncol && sp < 128) sp <<= 1;
    tsp[d] = (uint8_t)sp;
  }

  // Snap each top-face pixel to its group's base column.
  for (int y = B; y < 2 * B; y++)
    for (int x = B; x < 2 * B; x++) {
      const size_t i = (size_t)y * cols + x;
      const int d = dep[i];
      if (d >= MX_TOPD_MAX) continue;
      const int sp = tsp[d];
      col[i] = (uint8_t)(col[i] & (uint8_t)~(sp - 1));
    }
}

// Brightness of one column at one depth. dist comes back as rows behind the
// head, which is what decides colour and how white the cell is.
static inline uint8_t mx_cell(int p, int ln, int br, int d, int &dist) {
  const int ip = p >> 4;                             // p is never negative
  const int k  = ip - d;
  dist = k;
  if (k < -1 || k >= ln) return 0;
  if (k == -1) return (uint8_t)((((p & 15) * br) >> 4));   // head easing in
  if (k == 0)  return (uint8_t)br;                         // the head itself
  int f = ((ln - k) * 255) / ln;
  f = (f * f) >> 8;                                        // tail falloff
  return (uint8_t)((f * br) >> 8);
}

// startD is the rim, not the centre of the top face. A stream born at the
// centre would put its HEAD there, and since every column converges on the
// middle pixels that welds them into a permanent white scribble. Born at the
// rim, the head falls straight down its wall - the classic thing - and it is
// the TAIL that reaches back over the fold and fades away inward, so the top
// face reads as the pool the code is being drawn out of.
static void mx_start(MxCols &C, int c, int startD, int lenBase, int power, bool fast) {
  if (c < 0 || c >= C.ncol || C.bri[c]) return;
  int v = lenBase + (int)(hw_random16(33)) - 16;
  if (fast) v = (v * 2) / 3;
  if (v < MX_LEN_MIN) v = MX_LEN_MIN;
  if (v > 200)        v = 200;
  C.pos[c] = (int16_t)(startD << 4);
  C.len[c] = (uint8_t)v;
  C.spd[c] = (uint8_t)(fast ? (150 + hw_random16(60)) : (90 + hw_random16(76)));
  C.bri[c] = (uint8_t)((power < 40) ? 40 : power);
  C.hue[c] = (uint8_t)hw_random8();
}

// Pick an idle column and start it. With the spectrum ring on, a column's
// chance is weighted by the FFT bin covering its sector, so loud bands pour
// more code down their side of the cube.
static void mx_pick(MxCols &C, const uint8_t *spec, bool ring,
                    int startD, int lenBase, int power, bool fast) {
  for (int t = 0; t < 8; t++) {
    const int c = (int)hw_random16((uint16_t)C.ncol);
    if (C.bri[c]) continue;
    if (ring) {
      const int bin = (c * 16) / C.ncol;
      if (hw_random8() > (uint8_t)qadd8(110, scale8(spec[bin], 145))) continue;
    }
    mx_start(C, c, startD, lenBase, power, fast);
    return;
  }
}

static FX_RET mode_matrix_rain() {
  if (!strip.isMatrix || !SEGMENT.is2D()) { SEGMENT.fill(SEGCOLOR(0)); FX_DONE; }
  const int cols = SEG_W, rows = SEG_H;
  if (cols < 4 || rows < 4) { SEGMENT.fill(SEGCOLOR(0)); FX_DONE; }
  const size_t n = (size_t)cols * rows;

  const bool cubeRaw = cfx_isCube(cols, rows);
  const int  B       = cubeRaw ? (cols / 3) : 1;
  const int  topd    = cubeRaw ? ((B + 1) / 2) : 0;
  // A net big enough to overrun the span table would break the top face, so
  // fall back to the flat mapping rather than mis-drawing it.
  const bool cube    = cubeRaw && topd <= MX_TOPD_MAX && (4 * B) <= MX_MAXCOL;

  const int depShift = (!cube && rows > 256) ? 1 : 0;
  // Grouped into MX_GLYPH_W-wide streams, so each stream can draw one whole
  // character rather than a single pixel - see the GLYPHS block up top.
  const int ncolPhys  = cube ? (4 * B) : cols;
  const int ncolGroup = (ncolPhys + MX_GLYPH_W - 1) / MX_GLYPH_W;
  const int ncol      = (ncolGroup > MX_MAXCOL) ? MX_MAXCOL : ncolGroup;
  const int dmax     = cube ? (topd + B - 1) : (depShift ? 255 : (rows - 1));

  if (!SEGENV.allocateData(6 * (size_t)ncol + 3 * n + MX_TOPD_MAX + 16 + MX_ST_LEN)) {
    SEGMENT.fill(SEGCOLOR(0)); FX_DONE;
  }

  MxCols C;
  C.pos  = (int16_t *)SEGENV.data;
  C.spd  = (uint8_t *)(C.pos + ncol);
  C.len  = C.spd + ncol;
  C.bri  = C.len + ncol;
  C.hue  = C.bri + ncol;
  C.ncol = ncol;
  uint8_t *col  = C.hue + ncol;
  uint8_t *dep  = col + n;
  uint8_t *lcol = dep + n;
  uint8_t *tsp  = lcol + n;
  uint8_t *spec = tsp + MX_TOPD_MAX;
  uint8_t *st   = spec + 16;

  const uint8_t want = (uint8_t)(cube ? 1 : 2);
  if (SEGENV.call == 0 || st[MX_ST_MODE] != want) {
    mx_buildMap(col, dep, tsp, lcol, cols, rows, cube, B, ncol, topd, depShift);
    for (int k = 0; k < ncol; k++) { C.pos[k] = 0; C.bri[k] = 0; C.len[k] = 0; }
    for (int k = 0; k < 16; k++)   spec[k] = 0;
    for (int k = 0; k < MX_ST_LEN; k++) st[k] = 0;
    st[MX_ST_MODE] = want;
  }

  // --- audio -----------------------------------------------------------------
  um_data_t     *um  = cfx_getAudioData();
  const uint8_t *fft = (uint8_t *)um->u_data[2];
  const float    vol = *(float *)um->u_data[0];
  const CfxTempoState  &tempo = cfx_tempo(um);
  const CfxDropState   &drop  = cfx_drop(um, tempo);
  const CfxSilenceState &sil  = cfx_silence(um);
  const uint8_t hat = cfx_hiHit(um);

  cfx_smoothSpec(spec, fft, 3);

  const uint16_t dtRaw = fx_dt8(st + MX_ST_CLK);
  const uint16_t dt    = cfx_dropDt(dtRaw, drop.speedScale);

  uint16_t hp = (uint16_t)st[MX_ST_HUE] | ((uint16_t)st[MX_ST_HUE + 1] << 8);
  hp = (uint16_t)(hp + (uint16_t)fx_step(MX_HUE_RATE * 8, dtRaw));
  st[MX_ST_HUE]     = (uint8_t)(hp & 0xFF);
  st[MX_ST_HUE + 1] = (uint8_t)(hp >> 8);
  const uint8_t hueBase = (uint8_t)(hp >> 8);

  const int lenBase = MX_LEN_MIN + (((int)SEGMENT.custom2 * 3 * dmax) >> 10);

  // --- advance every running stream ------------------------------------------
  const int rps   = 3 + (((int)SEGMENT.speed * 30) >> 8);       // rows per second
  int advQ4 = (rps * (int)dt * 16) / 1000;
  if (advQ4 < 1) advQ4 = 1;
  for (int c = 0; c < ncol; c++) {
    if (!C.bri[c]) continue;
    int adv = (advQ4 * (int)C.spd[c]) >> 7;
    if (adv < 1) adv = 1;
    C.pos[c] = (int16_t)(C.pos[c] + adv);
    if (((int)C.pos[c] >> 4) - (int)C.len[c] > dmax) C.bri[c] = 0;   // off the bottom
  }

  // --- spawning ---------------------------------------------------------------
  // A steady rate from the Density slider, thickened by a build, thinned by
  // silence; plus event-driven bursts that are QUEUED and released over the
  // next few frames, so a drop rolls in instead of appearing all at once.
  const bool ring = SEGMENT.check2;
  int rate = (MX_RATE_MIN + (((int)SEGMENT.custom1 * MX_RATE_SPAN) >> 8)) * ncol / 64;
  rate += ((int)drop.build * rate) >> 9;
  rate = (int)scale8((uint8_t)((rate > 255) ? 255 : rate), (uint8_t)(255 - sil.level));

  // Accumulated in 32 bits and clamped afterwards. A frame that stalls long
  // enough to earn more spawns than the guard will release would otherwise
  // wrap the 16-bit store and lose the lot - and a backlog of rain owed from
  // three seconds ago is not something to pay out anyway.
  uint32_t acc = (uint32_t)st[MX_ST_ACC] | ((uint32_t)st[MX_ST_ACC + 1] << 8);
  acc += (uint32_t)dtRaw * (uint32_t)rate;
  int guard = 0;
  while (acc >= 1000 && guard < 40) { acc -= 1000; guard++; mx_pick(C, spec, ring, topd, lenBase, 200, false); }
  if (acc > 999) acc = 999;
  st[MX_ST_ACC]     = (uint8_t)(acc & 0xFF);
  st[MX_ST_ACC + 1] = (uint8_t)(acc >> 8);

  if (hat) mx_pick(C, spec, ring, topd, lenBase, 130 + (hat >> 1), true);

  // Accent streams are the exception to the rule above: these start at depth 0,
  // so a kick erupts from the centre of the top face and fans out across it
  // before pouring over the rim. The steady rain still starts at the fold, so
  // the middle only lights when the music actually does something.
  int pend = st[MX_ST_PEND];
  if (SEGMENT.check1 && tempo.hit) pend += 2 + (tempo.hit >> 5);
  if (drop.hit)                    pend += ncol / 3;
  if (sil.wake)                    pend += ncol / 4;
  if (pend > 255) pend = 255;
  for (int k = 0; k < MX_RELEASE && pend > 0; k++, pend--)
    mx_pick(C, spec, ring, 0, lenBase, 255, false);
  st[MX_ST_PEND] = (uint8_t)pend;

  // --- levels ------------------------------------------------------------------
  const uint8_t drive  = cfx_drive(vol, 1.3f, 40 + (SEGMENT.intensity >> 1));
  const int      flickMs = 220 - (((int)cfx_c3full(SEGMENT.custom3) * 180) >> 8);  // 220 .. 40 ms
  // 32-bit on purpose: the staggered mutation below divides (tick + phase),
  // and letting an 8-bit tick wrap would jolt every glyph at once each wrap.
  const uint32_t tick    = strip.now / (uint32_t)flickMs;
  static const uint8_t MX_WHITE[2] = {130, 45};

  // Per-ring level for the top face: the group-overlap dim and the emergence
  // ramp folded together, once a frame instead of once a pixel.
  uint8_t tdim[MX_TOPD_MAX];
  for (int d = 0; d < topd && d < MX_TOPD_MAX; d++) {
    int v = 255;
    for (int q = tsp[d]; q > 1; q >>= 1) v -= MX_GROUP_DIM;
    if (v < 90) v = 90;
    const int ramp = MX_EMERGE + ((d * (255 - MX_EMERGE)) / ((topd > 1) ? (topd - 1) : 1));
    tdim[d] = (uint8_t)((v * ramp) / 255);
  }

  CFX_NET_PREP();
  size_t i = 0;
  for (int y = 0; y < rows; y++) {
    CFX_NET_ROW(y);
    for (int x = 0; x < cols; x++, i++) {
      CFX_NET_SKIP(x);
      const int c0 = col[i];
      if (c0 == 255) continue;                       // gap corner
      const int d = dep[i];

      uint8_t lum = 0;
      int dist = 0, cBest = c0, sp = 1;

      if (d < topd) {                                // top face: brightest of the group
        sp = tsp[d];
        for (int k = 0; k < sp; k++) {
          int cc = c0 + k;
          if (cc >= ncol) cc -= ncol;
          if (!C.bri[cc]) continue;
          int dk;
          const uint8_t l = mx_cell(C.pos[cc], C.len[cc], C.bri[cc], d, dk);
          if (l > lum) { lum = l; dist = dk; cBest = cc; }
        }
        if (lum) lum = scale8(lum, tdim[d]);
      } else if (C.bri[c0]) {
        lum = mx_cell(C.pos[c0], C.len[c0], C.bri[c0], d, dist);
      }

      if (!lum) { SEGMENT.setPixelColorXY(x, y, 0); continue; }

      // Glyph mask: on the walls (not the top-face pool), the surface is cut
      // into a fixed grid of MX_GLYPH_W x MX_GLYPH_H character cells, and each
      // cell renders one bitmap glyph.
      //
      // The grid is keyed off ABSOLUTE depth, so the characters stay put on
      // the wall and a falling stream simply lights the ones it passes over -
      // which is what the film does. Keying it off `dist` (distance behind the
      // head) instead tied the grid to the moving head, so the whole pattern
      // slid upward through the trail as the stream fell.
      //
      // The mask depends only on WHERE a pixel is, never on the stream, so the
      // head is masked too - a solid unmasked head would punch a blank block
      // through the character it is standing on.
      if (d >= topd) {
        const int wd       = d - topd;             // rows down the wall, 0 at the fold
        const int charIdx  = wd / MX_GLYPH_H;
        const int localRow = wd % MX_GLYPH_H;
        // Per-cell phase so cells do not all mutate on the same tick - hashing
        // straight off `tick` flipped every glyph on the cube simultaneously,
        // which reads as the whole field blinking rather than as code
        // churning. The /3 spreads them over three ticks (and slows mutation
        // to a third of the Glyph rate slider, which is about right for this).
        const uint32_t phase = (uint32_t)mx_hash(cBest, charIdx, 0);
        const uint32_t gSeq  = (tick + phase) / 3;
        const uint8_t  gId   = mx_hash(cBest, charIdx, (int)gSeq) % MX_GLYPH_COUNT;
        const uint8_t bits = pgm_read_byte(&MX_FONT[gId][localRow]);
        const int lc = lcol[i];
        const bool ink = (bits >> (MX_GLYPH_W - 1 - lc)) & 1;
        if (!ink) lum = scale8(lum, MX_GLYPH_BG);
      }

      const uint8_t idx = (uint8_t)(hueBase + (C.hue[cBest] >> 2)
                                  + (uint8_t)((dist > 0 ? dist : 0) * 3));
      uint32_t rgb = SEGMENT.color_from_palette(idx, false, false, 0);

      const int wi = (dist < 0) ? 0 : dist;
      if (wi < 2) {                                  // head lifted toward white, subtly
        const uint8_t amt = MX_WHITE[wi];
        const int r = (int)((rgb >> 16) & 0xFF), g = (int)((rgb >> 8) & 0xFF),
                  b = (int)(rgb & 0xFF);
        rgb = RGBW32((uint8_t)(r + (((255 - r) * (int)amt) >> 8)),
                     (uint8_t)(g + (((255 - g) * (int)amt) >> 8)),
                     (uint8_t)(b + (((255 - b) * (int)amt) >> 8)), 0);
      }

      SEGMENT.setPixelColorXY(x, y, mq_scale(rgb, scale8(lum, drive)));
    }
  }
  FX_DONE;
}

static const char _data_FX_MODE_MATRIX_RAIN[] PROGMEM =
  "Ace 3-D Matrix Rain@Fall speed,Glow,Density,Trail,Glyph rate,Spawn on beat,Spectrum ring,Flat mode;;!;2f;sx=130,ix=150,c1=120,c2=140,c3=15,o1=1,o2=1";



// ---------------------------------------------------------------------------
// Registration - joins the effect bank, which decides whether this effect
// claims one of the device's limited effect slots. See cube_fx_bank.h.
// ---------------------------------------------------------------------------
static CfxBankReg cube_fx_20_matrix_rain_reg(&mode_matrix_rain, _data_FX_MODE_MATRIX_RAIN);
