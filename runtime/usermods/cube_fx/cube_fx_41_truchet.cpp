#include "wled.h"
#include "cube_fx_common.h"
#include "cube_fx_bank.h"

// ===========================================================================
// Ace 3-D Truchet - a curve network that rewires itself on the beat
// ===========================================================================
// Truchet tiling: cut a surface into squares, drop one tile into each at a
// random orientation, and because every tile meets its edges at the same
// places, the pieces join into continuous curves that meander over the whole
// thing. Sebastien Truchet did it with split squares in 1704; Cyril Smith's
// 1987 version with two quarter-circle arcs is the one everybody pictures.
//
// ---------------------------------------------------------------------------
// WHY THIS TILES A CUBE WITHOUT ANY SEAM WORK AT ALL
// ---------------------------------------------------------------------------
// The grid is the cube's own faces, divided N by N. Every face is the same
// size and gets the same division, so grid lines meet exactly along every
// fold, and every grid edge belongs to exactly two cells whichever faces those
// cells are on. Truchet tiles connect at edge MIDPOINTS, perpendicular to the
// edge - so a curve leaving one cell always finds the curve entering the next,
// across a fold as readily as within a face. Nothing has to be special-cased.
// The two faces do not even have to agree on which way their local coordinates
// run, because a midpoint is a midpoint.
//
// What the cube adds that a plane cannot: at each of the four TOP corners
// three cells meet where four would on a plane, and around the bottom rim the
// grid simply ends. Truchet curve networks on a plane close into loops; here
// the corners force junctions that no planar Truchet has, and the loops come
// out longer and stranger for it. That is the reason to put this on a cube
// rather than on a panel.
//
// ---------------------------------------------------------------------------
// THE BEAT REWIRES THE MAZE
// ---------------------------------------------------------------------------
// A tile has no state except its orientation, and flipping one instantly
// rewires every curve passing through it - two loops merge, or one splits in
// two. So a kick flips a handful of tiles.
//
// The tiles SPIN to get there. The first version snapped them, on the argument
// that a Truchet tile has no meaningful half-way rotation - which is wrong,
// and wrong in a way worth recording. The two arc states are exactly ninety
// degrees apart: rotating (x,y) about the cell centre by a quarter turn sends
// corner (0,0) to (1,0) and (1,1) to (0,1), which is precisely the other
// orientation. Two such turns come back to the first, so the tile has period
// 180 and a partial rotation is perfectly well defined. The sample point is
// rotated instead of the tile, which costs nothing and is exact at the ends.
//
// Mid-spin the arcs swing past the cell edges and stop meeting their
// neighbours, and that is the point - the network visibly comes apart and
// knits itself back together rather than cutting between two states.
//
// A flip also throws a PULSE: a ring expanding outward across the solid from
// that tile. The first version instead lit the flipped cell, which read as a
// bright square - the one shape a curve network should never show.
//
// ---------------------------------------------------------------------------
// LINE WIDTH IN PIXELS, AS EVER
// ---------------------------------------------------------------------------
// Distances are computed in CELL units and multiplied by the cell's size in
// pixels before being thresholded, so a stroke is the same weight whether
// there is one cell to a face or five. Four effects in this folder have now
// been broken by expressing a line width as a fraction of a cell; this one was
// written that way from the start.
// ===========================================================================

#define TR_NMAX      5          // cells per face edge, at most
// A panel is one grid three faces wide, so it needs more cells than the cube's
// five faces do - 225 against 125. The buffer is sized for the larger.
#define TR_CELLS     ((3 * TR_NMAX) * (3 * TR_NMAX))
#define TR_STYLES    4
#define TR_PULSES    6          // rings in flight at once

struct TrState {
  uint8_t  mode;
  uint8_t  clk[2];
  uint8_t  n;                   // cells per face edge currently built
  uint8_t  seed;                // which layout variant is built
  uint16_t flow;                // colour drift
  uint8_t  orient[TR_CELLS];    // 0 or 1 - the tile's orientation
  uint8_t  kind[TR_CELLS];      // for the mixed style: arc or diagonal
  uint8_t  spin[TR_CELLS];      // 255 just after a flip, decaying to 0
  float    pz[TR_PULSES][3];    // where each ring started, as a direction
  uint8_t  page[TR_PULSES];     // ring age, 0 = dead
  uint8_t  pnext;
};

// Face block positions in the net, so a cell index can be turned back into a
// point on the solid - which is what a pulse needs to know where it started.
static const uint8_t TR_FBX[5] = { 1, 1, 1, 0, 2 };
static const uint8_t TR_FBY[5] = { 1, 0, 2, 1, 1 };

static inline uint32_t tr_hash(uint32_t v) {
  v ^= v >> 15; v *= 2246822519u;
  v ^= v >> 13; v *= 3266489917u;
  v ^= v >> 16; return v;
}

static void tr_build(TrState *s, int n, uint8_t seed) {
  s->n = (uint8_t)n; s->seed = seed;
  for (int c = 0; c < TR_CELLS; c++) {
    const uint32_t h = tr_hash((uint32_t)c * 2654435761u + (uint32_t)seed * 40503u);
    s->orient[c] = (uint8_t)(h & 1u);
    s->kind[c]   = (uint8_t)((h >> 7) & 1u);
    s->spin[c]   = 0;
  }
  for (int k = 0; k < TR_PULSES; k++) s->page[k] = 0;
  s->pnext = 0;
}

static FX_RET mode_truchet() {
  if (!strip.isMatrix || !SEGMENT.is2D()) { SEGMENT.fill(SEGCOLOR(0)); FX_DONE; }
  const int cols = SEG_W, rows = SEG_H;
  if (cols < 8 || rows < 8) { SEGMENT.fill(SEGCOLOR(0)); FX_DONE; }

  const bool cube = cfx_isCube(cols, rows);
  const int  B    = cube ? (cols / 3) : 1;

  if (!SEGENV.allocateData(sizeof(TrState))) { SEGMENT.fill(SEGCOLOR(0)); FX_DONE; }
  TrState *s = (TrState *)SEGENV.data;

  const uint8_t want = (uint8_t)(cube ? 1 : 2);
  if (SEGENV.call == 0 || s->mode != want) {
    s->mode = want; s->clk[0] = s->clk[1] = 0;
    s->flow = 0; s->n = 0; s->seed = 0xFF;
  }

  uint16_t dt = fx_dt8(s->clk);
  if (dt > 60) dt = 60;

  // --- parameters -----------------------------------------------------------
  // Doubled internally so the default sits mid-slider. The square flash used
  // to carry a good part of the brightness; with it gone the same look needs
  // roughly twice the gain, and burying that here beats shipping a default
  // pinned near the top of its travel with nowhere to go.
  const int  fill    = (int)SEGMENT.intensity * 2;
  const int  weight  = (int)SEGMENT.custom2;
  const bool contour = SEGMENT.check2;
  // custom3 is five bits, and it carries two things: the tile STYLE in the top
  // two, and a layout seed in the bottom three. Sliding it therefore walks
  // through eight different random layouts of one style before changing style,
  // which is a better use of a 32-step control than four values and 28 gaps.
  const int  style   = ((int)SEGMENT.custom3 >> 3) & 3;
  const uint8_t seed = (uint8_t)(SEGMENT.custom3 & 7);
  int nWant = 1 + ((int)SEGMENT.custom1 * TR_NMAX) / 256;
  if (nWant < 1) nWant = 1; else if (nWant > TR_NMAX) nWant = TR_NMAX;
  if (nWant != (int)s->n || seed != s->seed) tr_build(s, nWant, seed);
  const int n = (int)s->n;
  // Cells per grid edge. On a panel the grid spans the whole 3B-wide net
  // rather than one B-wide face, so tripling it keeps a cell the same number
  // of pixels across and the flat fallback as dense as the cube.
  const int gridN = cube ? n : n * 3;
  const int nCell = (cube ? 5 : 1) * gridN * gridN;
  const float cellPx = (float)(cube ? B : cols) / (float)gridN;   // cell size, px

  // --- audio: flip tiles ----------------------------------------------------
  um_data_t     *um   = cfx_getAudioData();
  const float    vol  = *(float *)um->u_data[0];
  const uint8_t  beat = SEGMENT.check1 ? fx_lowBeat(um) : 0;
  if (beat) {
    // Enough tiles that the network visibly rewires, few enough that the
    // picture is still recognisably the one from a moment ago.
    int flips = 1 + (nCell * (int)beat) / 900;
    if (flips > nCell / 3) flips = nCell / 3;
    if (flips < 1) flips = 1;
    for (int k = 0; k < flips; k++) {
      const uint32_t h = tr_hash((uint32_t)strip.now * 2654435761u + (uint32_t)k * 97u);
      const int c = (int)(h % (uint32_t)nCell);
      s->orient[c] ^= 1u;
      s->spin[c] = 255;

      // and a ring from where it happened. Only the first couple of flips in a
      // kick throw one - six rings crossing at once is already a lot of light,
      // and a dozen would be a flash by another name.
      if (k < 2) {
        const int cf = cube ? (c / (gridN * gridN)) : 0;
        const int cj = (c / gridN) % gridN, ci = c % gridN;
        const int cx = (cube ? TR_FBX[cf] * B : 0) + (int)(((float)ci + 0.5f) * cellPx);
        const int cy = (cube ? TR_FBY[cf] * B : 0) + (int)(((float)cj + 0.5f) * cellPx);
        float X, Y, Z; cfx_pos(cx, cy, cols, rows, B, cube, X, Y, Z);
        const float L = sqrtf(X * X + Y * Y + Z * Z), iL = (L > 1e-6f) ? 1.0f / L : 1.0f;
        const int slot = s->pnext % TR_PULSES;
        s->pz[slot][0] = X * iL; s->pz[slot][1] = Y * iL; s->pz[slot][2] = Z * iL;
        s->page[slot] = 1;
        s->pnext = (uint8_t)(slot + 1);
      }
    }
  }
  { const int d = (int)fx_step(13, dt);
    for (int c = 0; c < nCell; c++)
      s->spin[c] = (uint8_t)((s->spin[c] > d) ? (s->spin[c] - d) : 0); }
  { const int d = (int)fx_step(9, dt);
    for (int k = 0; k < TR_PULSES; k++)
      if (s->page[k]) s->page[k] = (uint8_t)((s->page[k] + d > 255) ? 0 : (s->page[k] + d)); }

  s->flow = (uint16_t)(s->flow + ((uint32_t)dt * (uint32_t)SEGMENT.speed) / 40u);

  const uint8_t hueOff = (uint8_t)(s->flow >> 8);
  const uint8_t drive  = cfx_drive(vol, 0.5f, 200);
  const float   halfW  = 0.35f + (float)weight * (1.75f / 255.0f);  // stroke, px

  // --- paint ----------------------------------------------------------------
  CFX_NET_PREP();
  for (int y = 0; y < rows; y++) {
    CFX_NET_ROW(y);
    for (int x = 0; x < cols; x++) {
      CFX_NET_SKIP(x);

      // Which face, and where on it. Taken straight off the net rather than
      // through cfx_face(), because the net's block layout already is the face
      // decomposition and this needs no rounding.
      int face, lx, ly;
      if (cube) {
        const int bx = x / B, by = y / B;
        face = (bx == 1 && by == 1) ? 0 : (by == 0 ? 1 : (by == 2 ? 2 : (bx == 0 ? 3 : 4)));
        lx = x % B; ly = y % B;
      } else { face = 0; lx = x; ly = y; }

      float X, Y, Z; cfx_pos(x, y, cols, rows, B, cube, X, Y, Z);
      const float PL = sqrtf(X * X + Y * Y + Z * Z);
      const float PiL = (PL > 1e-6f) ? (1.0f / PL) : 1.0f;
      const float nx = X * PiL, ny = Y * PiL, nz = Z * PiL;

      const float fa = ((float)lx + 0.5f) / (float)(cube ? B : cols) * (float)gridN;
      const float fb = ((float)ly + 0.5f) / (float)(cube ? B : rows) * (float)gridN;
      int i = (int)fa, j = (int)fb;
      if (i >= gridN) i = gridN - 1;
      if (j >= gridN) j = gridN - 1;
      float u = fa - (float)i, v = fb - (float)j;

      const int c = (face * gridN + j) * gridN + i;
      const int o = (int)s->orient[c];

      // Spin. The sample point turns about the cell centre rather than the
      // tile, which is the same thing and exact at both ends: a quarter turn
      // maps one orientation onto the other. Eight-bit trig is plenty - the
      // error is under a hundredth of a cell.
      if (s->spin[c]) {
        const uint8_t t = (uint8_t)(((int)s->spin[c] * 64) / 255);
        const float ca = ((int)cos8_t(t) - 128) * (1.0f / 127.0f);
        const float sa = ((int)sin8_t(t) - 128) * (1.0f / 127.0f);
        const float du = u - 0.5f, dv = v - 0.5f;
        u = 0.5f + du * ca - dv * sa;
        v = 0.5f + du * sa + dv * ca;
      }

      // --- the tile ---------------------------------------------------------
      // d is a signed-ish distance in CELL units; sd is which side, for the
      // styles that fill rather than stroke.
      float d, sd = 0.0f, phase = 0.0f;
      int   useArc = (style == 0) || (style == 2 && s->kind[c]);
      if (style == 3) {
        // Truchet's own 1704 tile: the square split corner to corner, one half
        // lit. No stroke at all - the pattern is in the filled shapes.
        sd = o ? (u - v) : (u + v - 1.0f);
        d  = fabsf(sd) * 0.70710678f;
      } else if (useArc) {
        const float c1x = o ? 0.0f : 1.0f, c1y = 0.0f;
        const float c2x = o ? 1.0f : 0.0f, c2y = 1.0f;
        const float dx1 = u - c1x, dy1 = v - c1y;
        const float dx2 = u - c2x, dy2 = v - c2y;
        const float r1 = fabsf(sqrtf(dx1 * dx1 + dy1 * dy1) - 0.5f);
        const float r2 = fabsf(sqrtf(dx2 * dx2 + dy2 * dy2) - 0.5f);
        d = (r1 < r2) ? r1 : r2;
        // How far along the quarter arc this pixel sits, so colour can travel
        // ALONG a curve instead of only changing between tiles.
        phase = (r1 < r2) ? cfx_atan2f(dy1, dx1) : cfx_atan2f(dy2, dx2);
      } else {
        d = fabsf(o ? (u - v) : (u + v - 1.0f)) * 0.70710678f;
        phase = o ? (u + v) : (u - v);
      }
      const float dPx = d * cellPx;          // ... and now in pixels

      // --- colour and brightness -------------------------------------------
      // Rainbow, and most of it is SPATIAL rather than per-tile. Azimuth wraps
      // seamlessly all the way round the solid, so a full turn of hue closes
      // on itself with no seam; height adds a second axis; the arc phase makes
      // the colour travel along each curve; and the tile hash is kept small,
      // just enough to tell neighbouring cells apart. Before, hue came from
      // the tile hash alone and was divided by three, which is why the pattern
      // read as two or three colours rather than as a spectrum.
      const uint32_t h = tr_hash((uint32_t)c * 0x9E3779B9u + 12345u);
      const int az = (int)(cfx_atan2f(ny, nx) * (128.0f / 3.14159274f));
      const int el = (int)(nz * 84.0f);
      uint8_t idx = (uint8_t)(az + el + (int)(phase * 44.0f)
                              + ((int)(uint8_t)(h >> 11) >> 3) + hueOff);

      int lum;
      if (style == 3) {
        // filled halves: one side lit, the other black, with the cut inked
        lum = (sd > 0.0f) ? fill : (fill / 6);
        if (dPx < halfW) lum = (int)((float)lum * (dPx / halfW));
      } else if (contour) {
        // Not a stroke but a field: brightness falls off with distance from
        // the curve, so the tiling reads as banded terrain rather than line
        // art. Normalised by the cell, because a contour IS a fraction of a
        // cell - it is the stroke that has to be pixel-locked, not this.
        // Steep, and squared. A gentle falloff lit four fifths of every cell -
        // mean 74 against a target band topping out at 45 - which is a wash,
        // not a contour.
        float t = d * 6.0f; if (t > 1.0f) t = 1.0f;
        lum = (int)((float)fill * (1.0f - t) * (1.0f - t));
        idx = (uint8_t)(idx + (uint8_t)(int)(d * 300.0f));
      } else {
        const float t = dPx / halfW;
        lum = (t >= 1.0f) ? 0 : (int)((float)fill * (1.0f - t * t));
      }

      // Rings, not a lit square. Each expands from where a tile flipped and
      // fades as it grows, and it is drawn in the negative space as readily as
      // on a curve - so the pulse arrives from outside the pattern and sweeps
      // over it rather than filling one cell in.
      { int pulse = 0;
        for (int k = 0; k < TR_PULSES; k++) {
          if (!s->page[k]) continue;
          const float dx = nx - s->pz[k][0];
          const float dy = ny - s->pz[k][1];
          const float dz = nz - s->pz[k][2];
          const float dist = sqrtf(dx * dx + dy * dy + dz * dz);
          const float R = (float)s->page[k] * (2.30f / 255.0f);
          const float e = fabsf(dist - R);
          if (e < 0.17f) {
            const float t = 1.0f - e * (1.0f / 0.17f);
            pulse += (int)(t * t * 255.0f * (1.0f - (float)s->page[k] * (1.0f / 300.0f)));
          }
        }
        if (pulse) lum += (pulse * fill) >> 9; }
      if (lum < 0) lum = 0; else if (lum > 255) lum = 255;

      uint32_t col = 0;
      if (lum) {
        col = SEGMENT.color_from_palette(idx, false, true, 0);
        col = mq_scale(col, (uint8_t)lum);
      }
      SEGMENT.setPixelColorXY(x, y, mq_scale(col, drive));
    }
  }
  FX_DONE;
}

static const char _data_FX_MODE_TRUCHET[] PROGMEM =
  "Ace 3-D Truchet@Flow,Fill,Cells,Weight,Style,Rewire on beat,Contour,Flat mode;;!;2f;sx=90,ix=128,c1=60,c2=110,c3=3,o1=1,pal=11";


// ---------------------------------------------------------------------------
// Registration - joins the effect bank, which decides whether this effect
// claims one of the device's limited effect slots. See cube_fx_bank.h.
// ---------------------------------------------------------------------------
static CfxBankReg cube_fx_41_truchet_reg(&mode_truchet, _data_FX_MODE_TRUCHET);
