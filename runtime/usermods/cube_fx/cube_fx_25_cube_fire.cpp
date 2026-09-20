#include "wled.h"
#include "cube_fx_audio.h"
#include "cube_fx_imu.h"
#include "cube_fx_bank.h"

// ===========================================================================
// 25. ACE 3-D CUBE FIRE
// ===========================================================================
// A fire burning inside an open-topped box. It smoulders at the bottom rim,
// climbs the four walls, curls over the top edge, and the four wall-fronts meet
// and pool above the middle of the lid. Bass makes it flare; transients throw
// coloured sparks that leap up the walls and over the rim.
//
// ---------------------------------------------------------------------------
// ONE HEAT FIELD, FLOWING INWARD
// ---------------------------------------------------------------------------
// The body is a classic cellular fire - a heat field that cools as it rises and
// copies from the hotter cell behind it, the Doom-fire method - laid over the
// same (angle, depth) ruler the other cube effects use:
//
//     d = 0        centre of the lid          the flame tips converge here
//     d = topd-1   the rim
//     d = dmax     the open bottom edge        the source: embers and bass
//
// "Rising" is therefore d decreasing, from the bottom edge up the walls and on
// to the lid centre - and that last part is the whole trick. Because every wall
// column's heat is carried toward the same centre cells, the four flame-fronts
// SUM there on their own. The lid is not drawn separately or fed a copy of the
// walls; it is simply where the one field converges, which is exactly what the
// top of a real fire in a box does. (This is the "lid carries the sum of the
// leading flame pixels" idea, falling out of the geometry instead of being
// bolted on.)
//
// The field lives in polar grid space, not in pixels, for the same reason the
// whirlpool's dye does: propagation and drift are cheap index arithmetic there,
// and the folded net only appears at the end when each pixel reads its cell.
//
// ---------------------------------------------------------------------------
// SPARKS - THE POPS, AND THE LEAPING
// ---------------------------------------------------------------------------
// A cellular field cannot throw a discrete ember, so the coloured pops are a
// second layer: a handful of particles born at the base on a transient, given
// upward speed and a little sideways drift, rendered bright and additive over
// the body. They rise, cross the rim, and scatter across the lid; nothing
// stops two crossing, because they do not interact - they are just lights.
// This is the "pixels leaping over the edges, paths allowed to cross" idea.
//
// ---------------------------------------------------------------------------
// MOTION
// ---------------------------------------------------------------------------
// With Motion lean on and an IMU present, gravity tilts both layers: the field
// drift and the sparks lean toward the down-slope, so tipping the cube makes
// the flames lick sideways and the sparks leap over one edge instead of
// straight up. Without a sensor, or with it off, fire just rises.
//
//   bass       flares the source - the whole base surges
//   beat       a burst of sparks
//   treble     sparkle rate and the spark colour spread
//   volume     overall brightness
//
// WITH NO AUDIO it idles as a low smoulder on the fake-sound generator.
// ===========================================================================

#define CF_MAXCOL 254
#define CF_SPARKS 28

#ifndef CF_SPARK_Q
  #define CF_SPARK_Q 6           // spark position fixed point (64 = one cell)
#endif

struct CfSpark {
  uint16_t u;                    // angle, Q6, wraps at ncol<<6
  uint16_t d;                    // depth, Q6, 0 = lid centre
  int8_t   vu, vd;               // velocity, Q6 per tick (vd < 0 rises)
  uint8_t  life;                 // 0 = dead
  uint8_t  hue;
};

struct CfState {
  uint8_t  mode;
  uint16_t ang, rad;
  uint16_t hue;                  // palette drift
  uint8_t  bassEnv;
  uint8_t  clk[2];
  CfSpark  sp[CF_SPARKS];
};

// Same lid+walls (angle, depth) map as matrix rain / whirlpool.
static int cf_edge(int t, int den, int B) {
  int idx = ((t + den) * B) / (2 * den);
  if (idx < 0)     idx = 0;
  if (idx > B - 1) idx = B - 1;
  return idx;
}

static void cf_buildMap(uint8_t *col, uint8_t *dep, int cols, int rows,
                        bool cube, int B, int topd) {
  for (int y = 0; y < rows; y++) {
    for (int x = 0; x < cols; x++) {
      const size_t i = (size_t)y * cols + x;

      if (!cube) {                                     // flat: bottom-up fire
        col[i] = (uint8_t)(((uint32_t)x * 256u) / (uint32_t)cols);
        dep[i] = (uint8_t)(((uint32_t)(rows - 1 - y) * 255u) / (uint32_t)(rows > 1 ? rows - 1 : 1));
        continue;
      }

      const int bx = x / B, by = y / B, lx = x % B, ly = y % B;
      if (bx != 1 && by != 1) { col[i] = 255; dep[i] = 0; continue; }   // gap corner

      if (bx == 1 && by == 1) {                        // LID: radial, centre out
        const int ax = 2 * lx - (B - 1), ay = 2 * ly - (B - 1);
        const int aax = (ax < 0) ? -ax : ax, aay = (ay < 0) ? -ay : ay;
        const int r2  = (aax > aay) ? aax : aay;
        dep[i] = (uint8_t)(r2 >> 1);
        if (r2 == 0) { col[i] = 0; continue; }
        int c;
        if (aay > aax) {
          const int idx = cf_edge(ax, aay, B);
          c = (ay < 0) ? idx : (2 * B + (B - 1 - idx));
        } else if (aax > aay) {
          const int idx = cf_edge(ay, aax, B);
          c = (ax > 0) ? (B + idx) : (3 * B + (B - 1 - idx));
        } else {
          c = (ay < 0) ? ((ax < 0) ? 0 : B) : ((ax > 0) ? (2 * B) : (3 * B));
        }
        col[i] = (uint8_t)c;
        continue;
      }

      int bu, bv;                                      // walls, cfx_buildBand order
      if      (by == 0) { bu = lx;                 bv = B - 1 - ly; }
      else if (bx == 2) { bu = B + ly;             bv = lx;         }
      else if (by == 2) { bu = 2 * B + B - 1 - lx; bv = ly;         }
      else              { bu = 3 * B + B - 1 - ly; bv = B - 1 - lx; }
      col[i] = (uint8_t)bu;
      dep[i] = (uint8_t)(topd + bv);
    }
  }
}

static FX_RET mode_cube_fire() {
  if (!strip.isMatrix || !SEGMENT.is2D()) { SEGMENT.fill(SEGCOLOR(0)); FX_DONE; }
  const int cols = SEG_W, rows = SEG_H;
  if (cols < 8 || rows < 8) { SEGMENT.fill(SEGCOLOR(0)); FX_DONE; }
  const size_t n = (size_t)cols * rows;

  const bool cubeRaw = cfx_isCube(cols, rows);
  const int  B       = cubeRaw ? (cols / 3) : 1;
  const bool cube    = cubeRaw && (4 * B) <= CF_MAXCOL;

  const int ang  = cube ? (4 * B) : 256;
  const int topd = cube ? ((B + 1) / 2) : 0;
  const int rad  = cube ? (topd + B) : rows;
  if (rad < 4 || ang < 8) { SEGMENT.fill(SEGCOLOR(0)); FX_DONE; }
  const int dmax = rad - 1;                            // the source row (bottom edge)

  const size_t cells = (size_t)ang * rad;
  const size_t need  = sizeof(CfState) + 2 * n + cells;
  if (!SEGENV.allocateData(need)) { SEGMENT.fill(SEGCOLOR(0)); FX_DONE; }

  CfState *s   = (CfState *)SEGENV.data;
  uint8_t *col = SEGENV.data + sizeof(CfState);
  uint8_t *dep = col + n;
  uint8_t *H   = dep + n;                              // heat field, ang*rad

  const uint8_t want = (uint8_t)(cube ? 1 : 2);
  if (SEGENV.call == 0 || s->mode != want || s->ang != (uint16_t)ang) {
    cf_buildMap(col, dep, cols, rows, cube, B, topd);
    s->mode = want; s->ang = (uint16_t)ang; s->rad = (uint16_t)rad;
    s->hue = 0; s->bassEnv = 0; s->clk[0] = s->clk[1] = 0;
    memset(H, 0, cells);
    for (int k = 0; k < CF_SPARKS; k++) s->sp[k].life = 0;
  }

  uint16_t dt = fx_dt8(s->clk);
  if (dt > 60) dt = 60;

  // --- audio ------------------------------------------------------------------
  um_data_t     *um   = cfx_getAudioData();
  const uint8_t *fft  = (uint8_t *)um->u_data[2];
  const float    vol  = *(float *)um->u_data[0];
  int bass, mid, treb;
  cfx_bands(fft, bass, mid, treb);
  const CfxTempoState &tempo = cfx_tempo(um);
  const uint8_t hat = cfx_hiHit(um);
  s->bassEnv = fx_env(s->bassEnv, (uint8_t)bass, dt, 180);

  // --- motion lean ------------------------------------------------------------
  // A sideways bias, in eighths of a cell, applied to both the field drift and
  // the sparks. gx/gy are gravity in cube X/Y; mapped onto the ring so tipping a
  // wall down makes the fire lean that way. Off, or with no sensor, it is zero
  // and the fire rises straight.
  const CfxImuState &imu = cfx_imu();
  int lean = 0;
  if (SEGMENT.check2 && imu.valid) lean = ((int)imu.gx - (int)imu.gy) / 24;   // -~10..10

  // --- the source row ---------------------------------------------------------
  // A steady smoulder plus per-cell flicker, surged by bass when Bass flare is
  // on. This is the only heat the field ever gains; everything above is this,
  // cooled and carried up.
  const int glow   = 70 + (((int)SEGMENT.intensity * 120) >> 8);
  const int flare  = SEGMENT.check1 ? (((int)s->bassEnv * 150) >> 8) : 0;
  uint8_t *src = H + (size_t)dmax * ang;
  for (int a = 0; a < ang; a++) {
    int h = glow + flare + (int)(hw_random8() % 90) - 20;
    if (h < 0) h = 0; else if (h > 255) h = 255;
    if ((uint8_t)h > src[a]) src[a] = (uint8_t)h; else src[a] = (uint8_t)((src[a] * 3 + h) >> 2);
  }

  // --- rise + cool ------------------------------------------------------------
  // Doom fire: each cell copies the one BELOW it (further out, hotter) minus a
  // random cooling, with a small sideways drift for flicker and the motion
  // lean. Iterated tip-first (d ascending) so a cell reads the source-side
  // value from the previous frame - which is what makes the flame climb one
  // cell per frame instead of the whole height in one go.
  const int cool = 6 + (((int)SEGMENT.custom1 * 26) >> 8);     // higher = shorter flame
  for (int r = 0; r < dmax; r++) {
    uint8_t *dst = H + (size_t)r * ang;
    const uint8_t *below = H + (size_t)(r + 1) * ang;
    for (int a = 0; a < ang; a++) {
      int drift = (int)(hw_random8() % 3) - 1 + (lean >> 3);
      int sa = a + drift; sa %= ang; if (sa < 0) sa += ang;
      int decay = (int)(hw_random8() % cool);
      int v = (int)below[sa] - decay;
      dst[a] = (uint8_t)((v < 0) ? 0 : v);
    }
  }

  // --- sparks -----------------------------------------------------------------
  const int sparkRate = SEGMENT.custom2;                       // pops
  const uint8_t hueSpread = cfx_c3full(SEGMENT.custom3);
  s->hue = (uint16_t)(s->hue + fx_step(3, dt));

  int spawn = 0;
  if (tempo.hit) spawn += 2 + (sparkRate >> 6);
  if (hat)       spawn += 1;
  if ((int)hw_random8() < (sparkRate >> 3)) spawn += 1;        // a steady trickle
  for (int k = 0; k < CF_SPARKS && spawn > 0; k++) {
    if (s->sp[k].life) continue;
    CfSpark &p = s->sp[k];
    p.u    = (uint16_t)((uint32_t)hw_random16((uint16_t)ang) << CF_SPARK_Q);
    p.d    = (uint16_t)((uint32_t)dmax << CF_SPARK_Q);
    p.vd   = (int8_t)(-(20 + (int)hw_random8() / 5));           // upward (toward d=0)
    p.vu   = (int8_t)((int)(hw_random8() % 13) - 6 + lean);
    p.life = (uint8_t)(160 + hw_random8() % 80);
    p.hue  = (uint8_t)((s->hue >> 8) + (hw_random8() & hueSpread));
    spawn--;
  }
  const int32_t angQ = (int32_t)ang << CF_SPARK_Q;
  for (int k = 0; k < CF_SPARKS; k++) {
    CfSpark &p = s->sp[k];
    if (!p.life) continue;
    int32_t nu = (int32_t)p.u + (((int32_t)p.vu * dt) / 23);
    nu %= angQ; if (nu < 0) nu += angQ;
    p.u = (uint16_t)nu;
    int32_t nd = (int32_t)p.d + (((int32_t)p.vd * dt) / 23);
    if (nd < 0) nd = 0;                                         // reached the lid centre
    p.d = (uint16_t)nd;
    const int dec = 1 + (int)fx_step(2, dt);
    p.life = (uint8_t)(p.life > dec ? p.life - dec : 0);
  }

  // --- render -----------------------------------------------------------------
  const uint8_t drive = cfx_drive(vol, 1.0f, 30 + (SEGMENT.intensity >> 2));
  const uint8_t hueBase = (uint8_t)(s->hue >> 8);

  size_t i = 0;
  for (int y = 0; y < rows; y++) {
    for (int x = 0; x < cols; x++, i++) {
      const int u = col[i];
      if (cube && u == 255) { SEGMENT.setPixelColorXY(x, y, 0); continue; }
      int d = dep[i]; if (d > rad - 1) d = rad - 1;
      const int a = cube ? u : ((u * ang) >> 8);
      const uint8_t heat = H[(size_t)d * ang + (a % ang)];

      // Heat straight into the palette, so a fire palette burns like fire and
      // any other palette recolours it. Scaled by volume so a loud room burns
      // brighter without changing the shape.
      uint32_t c = heat ? mq_scale(SEGMENT.color_from_palette(heat, false, true, 0),
                                   scale8(heat, drive))
                        : 0;
      SEGMENT.setPixelColorXY(x, y, c);
    }
  }

  // Sparks last, additive, so they read as bright embers over the body. Drawn
  // by nearest pixel - the lid's columns converge, so an exact cell match would
  // drop sparks near the centre.
  for (int k = 0; k < CF_SPARKS; k++) {
    const CfSpark &p = s->sp[k];
    if (!p.life) continue;
    const int su = (int)(p.u >> CF_SPARK_Q), sd = (int)(p.d >> CF_SPARK_Q);
    int bestX = -1, bestY = 0; int32_t bestCost = INT32_MAX;
    size_t j = 0;
    for (int y = 0; y < rows; y++) {
      for (int x = 0; x < cols; x++, j++) {
        if (cube && col[j] == 255) continue;
        const int dd = (dep[j] > sd) ? (dep[j] - sd) : (sd - dep[j]);
        const int cu = cube ? col[j] : ((col[j] * ang) >> 8);
        int du = cu - su; if (du < 0) du = -du; if (du > ang - du) du = ang - du;
        const int32_t cost = (int32_t)dd * 1024 + du;
        if (cost < bestCost) { bestCost = cost; bestX = x; bestY = y; }
      }
    }
    if (bestX < 0) continue;
    const uint8_t lv = (uint8_t)((p.life > 200) ? 255 : (p.life + 55));
    uint32_t sc = SEGMENT.color_from_palette((uint8_t)(hueBase + p.hue), false, false, 0);
    sc = color_add(mq_scale(sc, lv), mq_scale(RGBW32(255, 255, 255, 0), (uint8_t)(lv >> 2)), true);
    SEGMENT.setPixelColorXY(bestX, bestY,
      color_add(SEGMENT.getPixelColorXY(bestX, bestY), sc, true));
  }
  FX_DONE;
}

static const char _data_FX_MODE_CUBE_FIRE[] PROGMEM =
  "Ace 3-D Cube Fire@Rise,Glow,Flame height,Sparks,Colour spread,Bass flare,Motion lean,Flat mode;;!;2f;sx=140,ix=150,c1=110,c2=140,c3=5,o1=1,o2=0,pal=35";


// ---------------------------------------------------------------------------
// Registration - joins the effect bank, which decides whether this effect
// claims one of the device's limited effect slots. See cube_fx_bank.h.
// ---------------------------------------------------------------------------
static CfxBankReg cube_fx_25_cube_fire_reg(&mode_cube_fire, _data_FX_MODE_CUBE_FIRE);
