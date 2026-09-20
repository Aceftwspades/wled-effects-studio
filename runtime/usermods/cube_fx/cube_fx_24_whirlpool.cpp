#include "wled.h"
#include "cube_fx_common.h"
#include "cube_fx_bank.h"

// ===========================================================================
// 24. ACE 3-D WHIRLPOOL
// ===========================================================================
// The eye sits at the middle of the lid and the arms trail out of it, over the
// rim, and down all four walls.
//
// ---------------------------------------------------------------------------
// THE FLUID PART: A RANKINE VORTEX
// ---------------------------------------------------------------------------
// The arms are not drawn. Nothing in this file knows what a spiral is. They
// fall out of one classical result - the Rankine vortex, the textbook model of
// a whirlpool or a tornado:
//
//     r <= rc     omega = omega0                 solid-body core
//     r >  rc     omega = omega0 * (rc/r)^2      free vortex, v ~ 1/r
//
// Inside the core everything turns together at one rate. Outside, the further
// out you go the slower the angular rate, so a radial streak laid across the
// field is dragged into a spiral within a couple of turns purely because its
// inner end is going round faster than its outer end. Differential rotation IS
// the spiral; drawing one would have been the wrong solution to the problem.
//
// It also gives the EYE for free. The core rotates as a rigid body, so there
// is no shear inside it - dye put there stays whole and turns as a disc, which
// is exactly how the calm middle of a storm reads.
//
// ---------------------------------------------------------------------------
// WHAT WAS TAKEN FROM SOAP
// ---------------------------------------------------------------------------
// Not the noise - the DYE. Soap looks like a fluid because its colour lives in
// a buffer that is pushed around from frame to frame, rather than being
// recomputed from a function of position and time. Colour that is transported
// remembers where it has been; colour that is recomputed cannot, and always
// reads as a pattern playing rather than a substance moving.
//
// So there is a dye field here too, and each frame it is advected: for every
// cell, trace backwards along the velocity field to find where that parcel was
// one step ago, and sample the old field there. That is semi-Lagrangian
// advection, the standard stable-fluids method, and it is unconditionally
// stable - a large timestep degrades the picture instead of exploding it,
// which matters when the frame rate is whatever the cube can spare.
//
// ---------------------------------------------------------------------------
// WHY THE DYE LIVES IN (ANGLE, RADIUS) AND NOT IN PIXELS
// ---------------------------------------------------------------------------
// Advection needs to sample the field at an arbitrary point, and "which pixel
// is at this angle and radius" has no cheap answer on a folded net. Stored in
// polar grid space instead, the trace is a subtraction and the sample is a
// bilinear read, and the net only appears at the very end when each pixel looks
// up its own cell.
//
// The radius ruler runs from the middle of the lid, out to the rim, and on down
// the walls without a break - the same one cube_fx_20_matrix_rain uses - so an
// arm crossing the rim needs no special case. It simply keeps going.
//
// ---------------------------------------------------------------------------
// MUSIC
// ---------------------------------------------------------------------------
//   bass       spins it up. A loud passage tightens the arms, because winding
//              rate and arm pitch are the same quantity
//   beat       a pulse of fresh dye injected at the eye, which then spirals out
//              on its own - the storm answers a kick several seconds later, at
//              the rim, which is a nicer thing to watch than a flash
//   volume     overall level
//
// WITH NO AUDIO it still turns on its own clock.
// ===========================================================================

#define WP_Q       8                  // fixed point for the backward trace
// Integer truncation in the arm formula means the reachable maximum is
// (WP_ARMS_MAX - 2) - 1, so 6 here yields 2..5 arms, with 5 across the top
// quarter of the Arms slider.
#define WP_ARMS_MAX 6

#ifndef WP_FADE
  #define WP_FADE 2                   // dye lost per frame, so old dye cannot pile up
#endif
#ifndef WP_MAXCOL
  #define WP_MAXCOL 254               // 255 marks "not on the board" in col[]
#endif

struct WpState {
  uint8_t  mode;                      // cube/flat marker
  uint8_t  arms;
  uint16_t ang;                       // angular cells actually in use
  uint16_t rad;                       // radial cells actually in use
  uint16_t phase;                     // injection pattern rotation
  uint8_t  bassEnv;
  uint8_t  beatEnv;
  uint8_t  clk[2];                    // fx_dt8 store
};

// Rankine angular rate at radius r, in Q8 angular cells per tick.
// Constant in the core, falling as 1/r^2 outside it - the second half is what
// winds the arms.
static inline int32_t wp_omega(int r, int rc, int32_t w0) {
  if (r <= rc) return w0;
  const int32_t num = (int32_t)rc * rc;
  const int32_t den = (int32_t)r * r;
  return (w0 * num) / (den ? den : 1);
}

// Outward drift. Fastest near the eye and easing off with distance, so dye
// leaves the core briskly and then lingers where the arms are long enough to
// actually be seen.
static inline int32_t wp_vrad(int r, int rc, int32_t v0) {
  return (v0 * (int32_t)(rc + 1)) / (int32_t)(r + rc + 1);
}

// Bilinear sample of the dye field. Angle wraps - it is a circle - and radius
// clamps, because there is nothing past either end of the ruler.
static inline uint8_t wp_sample(const uint8_t *f, int ang, int rad,
                                int32_t aQ, int32_t rQ) {
  int a0 = (int)(aQ >> WP_Q), r0 = (int)(rQ >> WP_Q);
  const int af = (int)(aQ & ((1 << WP_Q) - 1)), rf = (int)(rQ & ((1 << WP_Q) - 1));
  int a1 = a0 + 1, r1 = r0 + 1;
  a0 %= ang; if (a0 < 0) a0 += ang;
  a1 %= ang; if (a1 < 0) a1 += ang;
  if (r0 < 0) r0 = 0; else if (r0 > rad - 1) r0 = rad - 1;
  if (r1 < 0) r1 = 0; else if (r1 > rad - 1) r1 = rad - 1;

  const int v00 = f[r0 * ang + a0], v10 = f[r0 * ang + a1];
  const int v01 = f[r1 * ang + a0], v11 = f[r1 * ang + a1];
  const int top = v00 + (((v10 - v00) * af) >> WP_Q);
  const int bot = v01 + (((v11 - v01) * af) >> WP_Q);
  return (uint8_t)(top + (((bot - top) * rf) >> WP_Q));
}

// (angle, radius) for every pixel. Lid is radial from its centre; the walls
// continue the same radius outward. Mirrors matrix rain's mapping so the two
// agree about which way the cube is wound.
static int wp_edge(int t, int den, int B) {
  int idx = ((t + den) * B) / (2 * den);
  if (idx < 0)     idx = 0;
  if (idx > B - 1) idx = B - 1;
  return idx;
}

static void wp_buildMap(uint8_t *col, uint8_t *dep, int cols, int rows,
                        bool cube, int B, int topd) {
  for (int y = 0; y < rows; y++) {
    for (int x = 0; x < cols; x++) {
      const size_t i = (size_t)y * cols + x;

      if (!cube) {
        // Flat panels get honest polar coordinates about the middle - the
        // effect is a vortex, so a plane should show one seen from above.
        const float dx = (float)x - (cols - 1) * 0.5f;
        const float dy = (float)y - (rows - 1) * 0.5f;
        const float rr = sqrtf(dx * dx + dy * dy);
        int a = (int)(atan2f(dy, dx) * (128.0f / 3.14159265f) + 256.5f);
        col[i] = (uint8_t)(a & 0xFF);
        const int rmax = ((cols < rows) ? cols : rows) / 2;
        int r = (int)rr;
        dep[i] = (uint8_t)((r > rmax) ? rmax : r);
        continue;
      }

      const int bx = x / B, by = y / B, lx = x % B, ly = y % B;
      if (bx != 1 && by != 1) { col[i] = 255; dep[i] = 0; continue; }   // gap corner

      if (bx == 1 && by == 1) {                        // LID: radial, centre out
        const int ax = 2 * lx - (B - 1), ay = 2 * ly - (B - 1);
        const int aax = (ax < 0) ? -ax : ax, aay = (ay < 0) ? -ay : ay;
        const int r2  = (aax > aay) ? aax : aay;
        dep[i] = (uint8_t)(r2 >> 1);
        if (r2 == 0) { col[i] = 0; continue; }          // the eye itself

        int c;
        if (aay > aax) {
          const int idx = wp_edge(ax, aay, B);
          c = (ay < 0) ? idx : (2 * B + (B - 1 - idx));
        } else if (aax > aay) {
          const int idx = wp_edge(ay, aax, B);
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

static FX_RET mode_whirlpool() {
  if (!strip.isMatrix || !SEGMENT.is2D()) { SEGMENT.fill(SEGCOLOR(0)); FX_DONE; }
  const int cols = SEG_W, rows = SEG_H;
  if (cols < 8 || rows < 8) { SEGMENT.fill(SEGCOLOR(0)); FX_DONE; }
  const size_t n = (size_t)cols * rows;

  const bool cubeRaw = cfx_isCube(cols, rows);
  const int  B       = cubeRaw ? (cols / 3) : 1;
  const bool cube    = cubeRaw && (4 * B) <= WP_MAXCOL;

  const int ang  = cube ? (4 * B) : 256;               // angular cells around
  const int topd = cube ? ((B + 1) / 2) : 0;
  const int rad  = cube ? (topd + B) : (((cols < rows) ? cols : rows) / 2 + 1);
  if (rad < 4 || ang < 8) { SEGMENT.fill(SEGCOLOR(0)); FX_DONE; }

  const size_t cells = (size_t)ang * rad;
  const size_t need  = sizeof(WpState) + 2 * n + 2 * cells;
  if (!SEGENV.allocateData(need)) { SEGMENT.fill(SEGCOLOR(0)); FX_DONE; }

  WpState *s   = (WpState *)SEGENV.data;
  uint8_t *col = SEGENV.data + sizeof(WpState);
  uint8_t *dep = col + n;
  uint8_t *dye = dep + n;
  uint8_t *tmp = dye + cells;

  const uint8_t want = (uint8_t)(cube ? 1 : 2);
  if (SEGENV.call == 0 || s->mode != want || s->ang != (uint16_t)ang) {
    wp_buildMap(col, dep, cols, rows, cube, B, topd);
    s->mode = want; s->ang = (uint16_t)ang; s->rad = (uint16_t)rad;
    s->phase = 0; s->bassEnv = 0; s->beatEnv = 0;
    s->clk[0] = s->clk[1] = 0;
    memset(dye, 0, cells);
  }

  uint16_t dt = fx_dt8(s->clk);
  if (dt > 60) dt = 60;

  // --- audio ------------------------------------------------------------------
  um_data_t     *um   = cfx_getAudioData();
  const uint8_t *fft  = (uint8_t *)um->u_data[2];
  const float    vol  = *(float *)um->u_data[0];
  const uint8_t  beat = SEGMENT.check1 ? fx_lowBeat(um) : 0;
  int bass, mid, treb;
  cfx_bands(fft, bass, mid, treb);

  s->bassEnv = fx_env(s->bassEnv, (uint8_t)bass, dt, 320);
  if (beat > s->beatEnv) s->beatEnv = beat;
  { const int f = (int)s->beatEnv - (int)fx_step(9, dt);
    s->beatEnv = (uint8_t)((f < 0) ? 0 : f); }

  // --- vortex parameters --------------------------------------------------------
  const int rc = 1 + (((int)SEGMENT.custom1 * (rad / 3)) >> 8);   // core radius
  // Core angular rate, Q8 cells per tick. Winding rate and arm pitch are the
  // same number, so bass tightening the spiral and bass speeding it up are one
  // effect, not two. Scaled so default Speed turns the eye about once every
  // 2.5 s and full Speed nearer 1.2 s. The arms stay legible even at the top of
  // this range because more of them are thinner, distinct streams rather than
  // one smear. Only the CORE runs at this rate; wp_omega falls off as 1/r^2
  // outside it, so the arms still lag and wind however fast the eye spins.
  int32_t w0 = ((int32_t)SEGMENT.speed * 300) / 255 + 8;
  if (SEGMENT.check2) w0 += ((int32_t)s->bassEnv * 110) / 255;
  w0 = (w0 * (int32_t)dt) / 23;

  const int32_t v0 = (((int32_t)SEGMENT.custom2 * 300) / 255 + 20) * (int32_t)dt / 23;
  const int turb = cfx_c3full(SEGMENT.custom3);

  // --- advect the dye -----------------------------------------------------------
  // Backward trace: for each cell, ask where its contents were one step ago and
  // read the OLD field there. Tracing forwards would scatter into gaps and
  // leave holes; going backwards guarantees every cell gets exactly one answer.
  for (int r = 0; r < rad; r++) {
    const int32_t om = wp_omega(r, rc, w0);
    const int32_t vr = wp_vrad(r, rc, v0);
    for (int a = 0; a < ang; a++) {
      int32_t aQ = ((int32_t)a << WP_Q) - om;          // came from behind in angle
      int32_t rQ = ((int32_t)r << WP_Q) - vr;          // and from further in
      if (turb) {                                       // a little unsteadiness
        const uint8_t nz = perlin8((uint8_t)(a * 4), (uint8_t)(r * 9),
                                   (uint8_t)(strip.now >> 6));
        aQ += (((int32_t)nz - 128) * turb) >> 8;
      }
      uint8_t v = wp_sample(dye, ang, rad, aQ, rQ);
      v = (v > WP_FADE) ? (uint8_t)(v - WP_FADE) : 0;
      tmp[r * ang + a] = v;
    }
  }
  memcpy(dye, tmp, cells);

  // --- inject at the eye ---------------------------------------------------------
  // Fresh dye enters only at the middle, with an angular pattern of `arms`
  // lobes. The vortex does the rest: everything downstream of here is that
  // pattern being wound up by shear.
  const int arms = 2 + (((int)SEGMENT.intensity * (WP_ARMS_MAX - 2)) >> 8);
  s->phase = (uint16_t)(s->phase + fx_step(6, dt));
  const int inj = rc / 2 + 1;
  const uint8_t punch = (uint8_t)(150 + (s->beatEnv >> 1));
  for (int r = 0; r <= inj && r < rad; r++) {
    for (int a = 0; a < ang; a++) {
      const uint8_t th = (uint8_t)(((int32_t)a * 256 * arms) / ang + (s->phase >> 6));
      const uint8_t lobe = sin8_t(th);
      uint8_t v = scale8(lobe, punch);
      uint8_t &c = dye[r * ang + a];
      if (v > c) c = v;
    }
  }

  // --- render ---------------------------------------------------------------------
  const uint8_t drive = cfx_drive(vol, 1.1f, 150 + (SEGMENT.intensity >> 2));
  const uint8_t hue   = (uint8_t)(strip.now >> 7);

  size_t i = 0;
  for (int y = 0; y < rows; y++) {
    for (int x = 0; x < cols; x++, i++) {
      const int u = col[i];
      if (cube && u == 255) { SEGMENT.setPixelColorXY(x, y, 0); continue; }
      int d = dep[i];
      if (d > rad - 1) d = rad - 1;
      const int a = cube ? u : ((u * ang) >> 8);

      const uint8_t v = dye[d * ang + (a % ang)];
      if (!v) { SEGMENT.setPixelColorXY(x, y, 0); continue; }

      // Palette walks with radius as well as with the dye, so the arms change
      // colour along their length instead of being one flat ribbon.
      const uint8_t idx = (uint8_t)(hue + v + (d * 3));
      SEGMENT.setPixelColorXY(x, y,
        mq_scale(SEGMENT.color_from_palette(idx, false, false, 0), scale8(v, drive)));
    }
  }
  FX_DONE;
}

static const char _data_FX_MODE_WHIRLPOOL[] PROGMEM =
  "Ace 3-D Whirlpool@Spin,Arms,Eye size,Outflow,Turbulence,Beat pulses,Bass spin,Flat mode;;!;2f;sx=120,ix=90,c1=80,c2=120,c3=5,o1=1,o2=1";



// ---------------------------------------------------------------------------
// Registration - joins the effect bank, which decides whether this effect
// claims one of the device's limited effect slots. See cube_fx_bank.h.
// ---------------------------------------------------------------------------
static CfxBankReg cube_fx_24_whirlpool_reg(&mode_whirlpool, _data_FX_MODE_WHIRLPOOL);
