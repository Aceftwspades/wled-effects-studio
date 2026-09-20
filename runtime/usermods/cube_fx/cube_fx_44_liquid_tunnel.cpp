#include "wled.h"
#include "cube_fx_common.h"
#include "cube_fx_bank.h"

// ===========================================================================
// Ace 3-D Liquid Tunnel - Gray-Scott chemistry down a log-polar shaft
// ===========================================================================
// Four layers: a logarithmic tunnel mapping, a reaction-diffusion medium that
// actually grows the tendrils, a dihedral fold, and a heightfield lit with a
// fake normal and a Fresnel rim.
//
// ---------------------------------------------------------------------------
// THE TUNNEL IS ln(z), AND ON THIS SOLID THAT IS FREE
// ---------------------------------------------------------------------------
// A shader tunnel takes screen space to log-polar with w = ln(z), so that a
// constant scroll along Re(w) is an exponential zoom - r = a e^(b theta) is
// the same statement read the other way round.
//
// The cube hands that over already built. Stereographic projection from the
// bottom pole gives each pixel a radius r = tan(phi/2) about the middle of the
// lid, so ln(r) IS the real part of ln(z) - the Mercator coordinate - and the
// azimuth is the imaginary part. Conformal, so the tendrils keep their shape;
// periodic in azimuth, so there is no seam to handle anywhere; and singular
// only at the middle of the lid, which is exactly where a tunnel's vanishing
// point belongs.
//
// It has to be clamped there. ln(r) runs to minus infinity at the lid centre,
// so without a floor the innermost pixels sample an unbounded number of tunnel
// rings and alias into noise - the same trap as the rim in cube_fx_38.
//
// ---------------------------------------------------------------------------
// THE MEDIUM IS REAL CHEMISTRY, NOT A NOISE FIELD
// ---------------------------------------------------------------------------
// The branching, merging, dripping tendrils are a Gray-Scott reaction-
// diffusion system, integrated on a grid that lives in the log-polar chart:
//
//   U' = Du lap(U) - U V^2 + F (1 - U)
//   V' = Dv lap(V) + U V^2 - (F + k) V
//
// It is affordable because the grid is small and lives in tunnel space rather
// than on the cube - 48 by 24 cells, a couple of thousand integer operations a
// step, against evaluating noise per pixel per frame. It also does something
// no noise field does: the pattern has HISTORY, so tendrils that split stay
// split and the surface is never the same twice.
//
// Sixteen-bit state, not eight. A Gray-Scott step moves a cell by about a
// thousandth of full scale, which at 8 bits truncates to zero every time and
// the medium simply never develops.
//
// The grid wraps in the tunnel direction and MIRRORS across the wedge, so the
// dihedral symmetry is a property of the simulation rather than something
// imposed when sampling - every cell computed is a cell seen, n times over.
//
// ---------------------------------------------------------------------------
// LIGHTING A FIELD THAT HAS NO GEOMETRY
// ---------------------------------------------------------------------------
// V is read as a heightfield. Its gradient across the grid gives a surface
// normal, that normal takes a diffuse and a Blinn-Phong specular term, and a
// Fresnel factor - grazing angles reflect hardest - adds the wet blue rim.
// None of it is geometry; it is a 2-D field wearing a 3-D face.
// ===========================================================================

// Grid size is set by what the CUBE can show, not by what looks good in a
// shader. The dihedral fold multiplies the resolution the grid needs: with n
// wedges and a mirror in each, the pattern is sampled 2*n*NV times around a
// circumference of only about 64 pixels. At 6 wedges and NV = 24 that is 288
// samples for 64 pixels - four and a half pattern cells per pixel - and the
// medium aliased into a regular grid of dashes that looked nothing like
// chemistry. 2*n*NV near 64 is the constraint, and it is why both the grid and
// the default symmetry are small.
#define LT_NU        28         // cells along the tunnel (log-radius), wraps
#define LT_NV        14         // cells across one wedge, mirrored at both ends
#define LT_CELLS     (LT_NU * LT_NV)
#define LT_S         65535
#define LT_RMIN      0.145f     // the clamp at the vanishing point
#define LT_RMAX      2.42f      // the bottom rim, in stereographic radius

// Gray-Scott regimes, as F and k in thousandths. Chosen to stay inside the
// region where the medium survives - much outside this and V dies to zero and
// the cube goes black, which is why they are a table and not a free slider.
// Third column is a display gain in percent. Different regimes settle at very
// different amounts of activator - measured at a common gain, these eight ran
// from a mean of 28 to a mean of 74 - so without it the Medium control is
// mostly a brightness slider with a pattern change attached. Normalised, it
// changes the pattern and leaves the exposure alone.
#define LT_NREG      8
static const uint8_t LT_FK[LT_NREG][3] PROGMEM = {
  { 30,  60, 105 },   // 0  drifting worms
  { 26,  55,  87 },   // 1  fat solitons
  { 34,  63,  92 },   // 2  maze
  { 35,  65, 115 },   // 3  classic mitosis
  { 30,  57,  46 },   // 4  branching coral
  { 38,  61,  56 },   // 5  holes
  { 22,  51,  91 },   // 6  slow blobs
  { 18,  51, 122 },   // 7  spreading waves
};

struct LtState {
  uint8_t  mode;
  uint8_t  clk[2];
  uint8_t  surge;
  uint8_t  regime;              // which F/k row is loaded
  uint16_t scroll;              // tunnel travel, wraps with the grid
  uint16_t kick;                // tunnel travel owed but not yet delivered
  uint16_t drift;
  uint16_t reseed;              // frames until the medium is checked again
  uint16_t U[LT_CELLS];
  uint16_t V[LT_CELLS];
};

static void lt_seed(LtState *s) {
  for (int i = 0; i < LT_CELLS; i++) { s->U[i] = LT_S; s->V[i] = 0; }
  for (int b = 0; b < 9; b++) {
    uint32_t h = (uint32_t)(b * 2654435761u + 12345u);
    h ^= h >> 13;
    const int cu = (int)(h % LT_NU), cv = (int)((h >> 8) % LT_NV);
    for (int du = -1; du <= 1; du++)
      for (int dv = -1; dv <= 1; dv++) {
        int u = (cu + du + LT_NU) % LT_NU, v = cv + dv;
        if (v < 0 || v >= LT_NV) continue;
        s->U[u * LT_NV + v] = LT_S / 2;
        s->V[u * LT_NV + v] = LT_S / 4;
      }
  }
}

// One Gray-Scott step. Wraps along the tunnel, mirrors across the wedge.
static void lt_step(LtState *s, int F, int K) {
  static uint16_t nu[LT_CELLS], nv[LT_CELLS];
  for (int u = 0; u < LT_NU; u++) {
    const int um = ((u - 1 + LT_NU) % LT_NU) * LT_NV;
    const int up = ((u + 1) % LT_NU) * LT_NV;
    const int uc = u * LT_NV;
    for (int v = 0; v < LT_NV; v++) {
      const int vm = (v == 0)          ? 1          : (v - 1);   // mirrored edge
      const int vp = (v == LT_NV - 1)  ? (LT_NV - 2) : (v + 1);
      const int c  = uc + v;
      const int32_t U = s->U[c], V = s->V[c];
      const int32_t lU = (int32_t)s->U[um + v] + s->U[up + v]
                       + s->U[uc + vm] + s->U[uc + vp] - 4 * U;
      const int32_t lV = (int32_t)s->V[um + v] + s->V[up + v]
                       + s->V[uc + vm] + s->V[uc + vp] - 4 * V;
      // U*V^2, kept inside 32 bits by shifting after each multiply
      const int32_t vv  = (int32_t)(((uint32_t)V * (uint32_t)V) >> 16);
      const int32_t uvv = (int32_t)(((uint32_t)U * (uint32_t)vv) >> 16);
      int32_t a = U + (41 * lU >> 8) - uvv + (F * (LT_S - U) / 1000);
      int32_t b = V + (21 * lV >> 8) + uvv - ((F + K) * V / 1000);
      if (a < 0) a = 0; else if (a > LT_S) a = LT_S;
      if (b < 0) b = 0; else if (b > LT_S) b = LT_S;
      nu[c] = (uint16_t)a; nv[c] = (uint16_t)b;
    }
  }
  memcpy(s->U, nu, sizeof(nu));
  memcpy(s->V, nv, sizeof(nv));
}

static FX_RET mode_liquidtunnel() {
  if (!strip.isMatrix || !SEGMENT.is2D()) { SEGMENT.fill(SEGCOLOR(0)); FX_DONE; }
  const int cols = SEG_W, rows = SEG_H;
  if (cols < 8 || rows < 8) { SEGMENT.fill(SEGCOLOR(0)); FX_DONE; }

  const bool cube = cfx_isCube(cols, rows);
  const int  B    = cube ? (cols / 3) : 1;

  if (!SEGENV.allocateData(sizeof(LtState))) { SEGMENT.fill(SEGCOLOR(0)); FX_DONE; }
  LtState *s = (LtState *)SEGENV.data;

  const uint8_t want = (uint8_t)(cube ? 1 : 2);
  if (SEGENV.call == 0 || s->mode != want) {
    s->mode = want; s->clk[0] = s->clk[1] = 0;
    s->scroll = 0; s->kick = 0; s->drift = 0; s->surge = 0;
    s->regime = 0xFF; s->reseed = 200;
    lt_seed(s);
  }

  uint16_t dt = fx_dt8(s->clk);
  if (dt > 60) dt = 60;

  // --- parameters -----------------------------------------------------------
  // Doubled internally so the default sits mid-slider. Gating the light on
  // the chemical means only the tendrils are lit, which is the point, but it
  // also means the same Fill number buys about half the mean it would in a
  // filled effect.
  const int  fill  = (int)SEGMENT.intensity * 2;
  const int  gloss = (int)SEGMENT.custom2;
  const bool fres  = SEGMENT.check2;
  int nSym = 2 + ((int)SEGMENT.custom3 * 14) / 31;              // 2..16 wedges
  if (nSym < 1) nSym = 1;
  const uint8_t reg = (uint8_t)(((int)SEGMENT.custom1 * LT_NREG) / 256);
  if (reg != s->regime) { s->regime = reg; s->reseed = 160; }
  const int F = (int)pgm_read_byte(&LT_FK[reg][0]);
  const int K = (int)pgm_read_byte(&LT_FK[reg][1]);
  const float regGain = (float)pgm_read_byte(&LT_FK[reg][2]) * 0.01f;

  // --- audio ----------------------------------------------------------------
  um_data_t     *um   = cfx_getAudioData();
  const float    vol  = *(float *)um->u_data[0];
  const uint8_t  beat = SEGMENT.check1 ? fx_lowBeat(um) : 0;
  if (beat > s->surge) s->surge = beat;
  { const int f = (int)s->surge - (int)fx_step(9, dt);
    s->surge = (uint8_t)(f < 0 ? 0 : f); }

  // The beat lurches the viewer DOWN the shaft, rather than speeding the
  // scroll up. Raising the rate is a swell and measures like one: with the
  // beat on, the median frame change nearly doubled while the peak barely
  // moved, so peak-to-median actually FELL - the whole picture ran faster and
  // nothing landed. Owed rather than applied, a third of the debt paid off a
  // frame, so about 90% of the travel arrives inside 140 ms and the rush is
  // drawn instead of cut. Same mechanism as cube_fx_43; the thing being
  // kicked is tunnel depth rather than a knot's phase.
  if (beat) {
    uint32_t k = (uint32_t)s->kick + (uint32_t)beat;
    if (k > 620u) k = 620u;
    s->kick = (uint16_t)k;
  }
  if (s->kick) {
    uint32_t give = ((uint32_t)s->kick * (uint32_t)dt) / 70u;
    if (!give) give = 1;
    if (give > s->kick) give = s->kick;
    s->scroll = (uint16_t)(s->scroll + give * 44u);
    s->kick = (uint16_t)(s->kick - give);
  }

  // --- chemistry ------------------------------------------------------------
  // Three steps a frame. One is too slow to watch develop; much more and the
  // medium outruns the tunnel scroll and the tendrils stop reading as flow.
  lt_step(s, F, K);
  lt_step(s, F, K);
  lt_step(s, F, K);

  // Watchdog. Gray-Scott can die - V decays to nothing and the cube goes
  // black with no way back - so the total is checked periodically and the
  // medium reseeded if it has gone out. Cheap, and it is the difference
  // between an effect and an effect that sometimes stops.
  if (s->reseed) s->reseed--;
  else {
    uint32_t tot = 0;
    for (int i = 0; i < LT_CELLS; i += 7) tot += s->V[i];
    if (tot < (uint32_t)(LT_CELLS / 7) * 900u) lt_seed(s);
    s->reseed = 90;
  }

  { const uint32_t r = (uint32_t)(6 + (int)SEGMENT.speed) * (uint32_t)dt
                       * (uint32_t)(100 + s->surge / 3) / (23u * 100u);
    s->scroll = (uint16_t)(s->scroll + r); }
  s->drift = (uint16_t)(s->drift + ((uint32_t)dt * (uint32_t)SEGMENT.speed) / 80u);

  const float lnMin = logf(LT_RMIN), lnMax = logf(LT_RMAX);
  const float uSpan = (float)LT_NU / (lnMax - lnMin);
  const float uOff  = (float)s->scroll * (float)LT_NU / 65536.0f;
  const float symK  = (float)nSym * (1.0f / 6.28318531f);
  // How many grid cells a wedge is allowed to show, so that the total angular
  // sample count stays near the cube's ~64-pixel circumference whatever the
  // symmetry is. Without this, raising Symmetry does not add wedges so much as
  // multiply the aliasing: at 16 wedges the full grid would be sampled 448
  // times around 64 pixels. The control now trades detail per wedge against
  // number of wedges, which is the honest version of the same knob.
  int nvUse = 32 / nSym;
  if (nvUse < 3) nvUse = 3; else if (nvUse > LT_NV - 1) nvUse = LT_NV - 1;
  const uint8_t hueOff = (uint8_t)(s->drift >> 8);
  const uint8_t drive  = cfx_drive(vol, 0.5f, 200);
  const float   specK  = (float)gloss * (1.0f / 255.0f);

  // --- paint ----------------------------------------------------------------
  CFX_NET_PREP();
  for (int y = 0; y < rows; y++) {
    CFX_NET_ROW(y);
    for (int x = 0; x < cols; x++) {
      CFX_NET_SKIP(x);

      float X, Y, Z; cfx_pos(x, y, cols, rows, B, cube, X, Y, Z);
      float r, th;
      if (cube) {
        const float L = sqrtf(X * X + Y * Y + Z * Z);
        const float den = 1.0f + Z / L;
        r  = (den > 0.02f) ? (sqrtf(X * X + Y * Y) / L / den) : LT_RMAX;
        th = cfx_atan2f(Y, X);
      } else {
        r  = sqrtf(X * X + Y * Y) * 1.7f;
        th = cfx_atan2f(Y, X);
      }
      if (r < LT_RMIN) r = LT_RMIN;                 // the vanishing point clamp
      else if (r > LT_RMAX) r = LT_RMAX;

      // ln(z): radius becomes tunnel depth, azimuth becomes the wedge
      float gu = (logf(r) - lnMin) * uSpan + uOff;
      gu = gu - floorf(gu / (float)LT_NU) * (float)LT_NU;        // wraps

      float a = th * symK;
      a = a - floorf(a);                            // 0..1 inside a wedge
      if (a > 0.5f) a = 1.0f - a;                   // mirror -> D_n
      float gv = a * 2.0f * (float)nvUse;

      int iu = (int)gu, iv = (int)gv;
      if (iu < 0) iu = 0; else if (iu >= LT_NU) iu = LT_NU - 1;
      if (iv < 0) iv = 0; else if (iv >= nvUse) iv = nvUse - 1;
      const float fu = gu - (float)iu, fv = gv - (float)iv;
      const int iu2 = (iu + 1) % LT_NU;

      // bilinear height
      const float h00 = (float)s->V[iu  * LT_NV + iv];
      const float h10 = (float)s->V[iu2 * LT_NV + iv];
      const float h01 = (float)s->V[iu  * LT_NV + iv + 1];
      const float h11 = (float)s->V[iu2 * LT_NV + iv + 1];
      const float h = (h00 * (1.0f - fu) + h10 * fu) * (1.0f - fv)
                    + (h01 * (1.0f - fu) + h11 * fu) * fv;

      // --- heightfield to normal -------------------------------------------
      const int ium = (iu - 1 + LT_NU) % LT_NU;
      const int ivm = (iv > 0) ? (iv - 1) : 1;
      const int ivp = (iv < LT_NV - 1) ? (iv + 1) : (LT_NV - 2);
      const float dhu = (float)s->V[iu2 * LT_NV + iv] - (float)s->V[ium * LT_NV + iv];
      const float dhv = (float)s->V[iu  * LT_NV + ivp] - (float)s->V[iu * LT_NV + ivm];
      float Nx = -dhu * (1.0f / 26000.0f), Ny = -dhv * (1.0f / 26000.0f), Nz = 1.0f;
      { const float nl = sqrtf(Nx * Nx + Ny * Ny + 1.0f);
        const float inl = 1.0f / nl; Nx *= inl; Ny *= inl; Nz *= inl; }

      // --- shading ----------------------------------------------------------
      const float Lx = 0.45f, Ly = -0.36f, Lz = 0.82f;
      float diff = Nx * Lx + Ny * Ly + Nz * Lz;
      if (diff < 0.0f) diff = 0.0f;
      float spec = Nx * (Lx * 0.5f) + Ny * (Ly * 0.5f) + Nz * (Lz * 0.5f + 0.5f);
      if (spec < 0.0f) spec = 0.0f;
      spec *= spec; spec *= spec; spec *= spec;                  // ^8
      // Fresnel: the view is straight down at this chart, so grazing means a
      // normal tipped away from Nz - which is exactly where the tendril walls
      // are, and why the rim is what lights up.
      float frn = 1.0f - Nz; frn = frn * frn;

      // Everything is gated by the amount of chemical present, so where the
      // medium is empty the surface is BLACK rather than sitting on an ambient
      // floor. With a flat ambient the cube measured 4.4% dark at a sigma of
      // 24 - every pixel lit, nothing to see. The tendrils have to be the
      // light, not something drawn on top of a lit ground.
      // V never approaches full scale - in Gray-Scott the activator tops out
      // around 0.4 - so reading it as 0..1 throws away well over half the
      // range and the medium came out at a mean of 5. Normalised to what it
      // actually reaches, and clamped for the few cells that overshoot.
      float hv = h * (2.6f * regGain / (float)LT_S);
      if (hv > 1.0f) hv = 1.0f;
      const float hv2 = hv * hv;
      float lit = 0.95f * hv2 + 0.65f * diff * hv
                + specK * 2.6f * spec * hv
                + (fres ? (frn * 1.35f * hv) : 0.0f);

      int lum = (int)((float)fill * lit);
      if (lum < 0) lum = 0; else if (lum > 255) lum = 255;

      uint8_t idx = (uint8_t)((int)(hv * 150.0f) + (int)(gu * (140.0f / LT_NU)) + hueOff);
      if (fres) idx = (uint8_t)(idx + (int)(frn * 60.0f));       // the wet blue lift

      uint32_t c = 0;
      if (lum) {
        c = SEGMENT.color_from_palette(idx, false, true, 0);
        c = mq_scale(c, (uint8_t)lum);
      }
      SEGMENT.setPixelColorXY(x, y, mq_scale(c, drive));
    }
  }
  FX_DONE;
}

static const char _data_FX_MODE_LIQUIDTUNNEL[] PROGMEM =
  "Ace 3-D Liquid Tunnel@Flow,Fill,Medium,Gloss,Symmetry,Beat surge,Fresnel,Flat mode;;!;2f;sx=80,ix=128,c1=100,c2=150,c3=2,o1=1,o2=1,pal=11";


// ---------------------------------------------------------------------------
// Registration - joins the effect bank, which decides whether this effect
// claims one of the device's limited effect slots. See cube_fx_bank.h.
// ---------------------------------------------------------------------------
static CfxBankReg cube_fx_44_liquidtunnel_reg(&mode_liquidtunnel, _data_FX_MODE_LIQUIDTUNNEL);
