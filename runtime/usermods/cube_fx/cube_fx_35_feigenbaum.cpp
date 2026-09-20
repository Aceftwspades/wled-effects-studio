#include "wled.h"
#include "cube_fx_common.h"
#include "cube_fx_bank.h"

// ===========================================================================
// Ace 3-D Feigenbaum - an endless zoom into the fig tree
// ===========================================================================
// The period-doubling cascade of x -> x^2 + c accumulates at the
// Myrberg-Feigenbaum point, and around that point the bifurcation diagram is
// SELF-SIMILAR: shrink the parameter window by delta = 4.6692 and the orbit
// window by alpha = 2.5029, and the picture maps onto itself with one more
// doubling. So this zooms for ever at constant precision: the phase wraps, the
// window resets by exactly one doubling, and the zoom never has to go deeper
// than a single step. Same trick as the Mandelbrot effect at a Misiurewicz
// point, except that here the two axes scale by DIFFERENT ratios, which is what
// makes it look unlike anything else in the family.
//
// Be precise about what the wrap does and does not do. It is SMOOTH but not
// invisible: measured over four consecutive wraps the frame-to-frame change was
// 0.67x, 0.94x, 1.70x and 2.02x a typical frame's, against a natural spread of
// 0.98 +/- 0.68 - so the worst wrap sits about one and a half standard
// deviations out. And the picture is not IDENTICAL a doubling later, only
// self-similar: correlation about 0.51 after one loop and 0.93 after four. That
// is the asymptotic nature of the scaling showing through at a finite window,
// and it is no bad thing - an endless zoom that repeated exactly every seven
// seconds would read as a loop rather than a descent.
//
// Above the point the tree splits toward you; below it the chaotic bands merge.
// Both converge on the thing you are flying into. Pastor, Romera, Alvarez and
// Montoya call that the "diabolic mirror" - the point transforms what is
// periodic into chaotic and back - and it is visible here because the window
// straddles it rather than sitting on one side.
//
// ---------------------------------------------------------------------------
// THE FLIP IS NOT OPTIONAL
// ---------------------------------------------------------------------------
// alpha is NEGATIVE. The self-similarity includes a reflection, so the orbit
// axis has to invert on every wrap. That is not a detail: measured over a
// +/-2.5 window the seam correlation is 0.67 with the flip and 0.03 without it,
// which is the difference between an endless zoom and a jump cut.
//
// Both ratios were checked against deliberately wrong controls, because a good
// seam score means nothing on its own - the Mandelbrot effect nearly shipped
// five real-axis loci that scored 1.00 and were frauds. Here the true (delta,
// alpha, flip) scores 0.67 against 0.07 for a wrong delta and 0.05 for a wrong
// alpha, a margin of +0.60, and it holds from a window of 0.02 down to 0.002.
//
// The Feigenbaum point was also tried as a locus for the Mandelbrot effect's
// own zoom, where it would have been a one-line change. It failed: margin
// +0.13, and negative at some depths. It is on the real axis, where that
// effect's orbit-trap colouring is nearly scale-invariant on its own, so the
// zoom would have been invisible. Different rendering, different answer - hence
// this being its own effect rather than a ninth row in that table.
//
// ---------------------------------------------------------------------------
// HOW IT IS DRAWN, AND WHY NOT AS RINGS
// ---------------------------------------------------------------------------
// STEREOGRAPHIC projection, borrowed from cube_fx_33. The parameter is one
// plane axis and the orbit value the other, and the plane is mapped onto the
// solid from the bottom pole: conformal, so branches keep their shape across a
// seam, and bounded, because the cube has no bottom face for the pole to sit
// on. An earlier version of this effect put the orbit on LATITUDE and time on
// azimuth, which is a perfectly good readout of the band structure and reads on
// the cube as nothing but circles. The figure has to be a figure.
//
// Density is measured, not drawn: each column iterates the map and records
// where the orbit actually goes, so bands, windows and merges appear because
// the dynamics put them there. The orbit is CARRIED between frames per column,
// which is what makes this cheap - the attractor is already converged, and a
// slowly shrinking window only nudges it. Only a wrap needs a real re-warm,
// and that is spread over the frames after it.
// ===========================================================================

#define FG_NC     64            // parameter columns across the plane
#define FG_NX     48            // orbit bins down it
#define FG_MF     (-1.4011551890f)
#define FG_LNDELTA  1.5410100f  // ln 4.6692016  - parameter axis
#define FG_LNALPHA  0.9174525f  // ln 2.5029079  - orbit axis
#define FG_SPAN   2.5f          // the plane half-span the projection reaches

struct FgState {
  uint8_t  mode;
  uint8_t  clk[2];
  uint32_t tZoom;               // zoom phase, Q16; wraps once per doubling
  uint8_t  flip;                // orbit axis inverted this loop
  uint8_t  rewarm;              // frames of extra warm-up owed after a wrap
  uint8_t  surge;
  uint16_t hueCyc;
  float    xs[FG_NC];           // each column's orbit, carried between frames
};

static FX_RET mode_feigenbaum() {
  if (!strip.isMatrix || !SEGMENT.is2D()) { SEGMENT.fill(SEGCOLOR(0)); FX_DONE; }
  const int cols = SEG_W, rows = SEG_H;
  if (cols < 8 || rows < 8) { SEGMENT.fill(SEGCOLOR(0)); FX_DONE; }

  const bool cube = cfx_isCube(cols, rows);
  const int  B    = cube ? (cols / 3) : 1;
  const size_t m  = cfx_litCount(cols, rows, B, cube);

  const size_t need = sizeof(FgState) + (size_t)FG_NC * FG_NX + 2 * m;
  if (!SEGENV.allocateData(need)) { SEGMENT.fill(SEGCOLOR(0)); FX_DONE; }

  FgState *s   = (FgState *)SEGENV.data;
  uint8_t *den = (uint8_t *)(s + 1);          // [column][bin] density
  uint8_t *pj  = den + (size_t)FG_NC * FG_NX; // which column each pixel reads
  uint8_t *pb  = pj + m;                      // and which bin

  const uint8_t want = (uint8_t)(cube ? 1 : 2);
  if (SEGENV.call == 0 || s->mode != want) {
    s->mode = want; s->clk[0] = s->clk[1] = 0;
    s->tZoom = 0; s->flip = 0; s->rewarm = 40; s->surge = 0; s->hueCyc = 0;
    for (int i = 0; i < FG_NC; i++) s->xs[i] = 0.0f;
    for (size_t i = 0; i < (size_t)FG_NC * FG_NX; i++) den[i] = 0;

    for (int y = 0; y < rows; y++)
      for (int x = 0; x < cols; x++) {
        if (cube && cfx_gap(x, y, B)) continue;
        const size_t ci = (size_t)cfx_cidx(x, y, cols, B, cube);
        float X, Y, Z; cfx_pos(x, y, cols, rows, B, cube, X, Y, Z);
        float u, v;
        if (cube) {
          const float L = sqrtf(X * X + Y * Y + Z * Z);
          const float nx = X / L, ny = Y / L, nz = Z / L;
          const float d = 1.0f + nz;
          u = (d > 0.05f) ? nx / d : nx * 20.0f;
          v = (d > 0.05f) ? ny / d : ny * 20.0f;
        } else {
          u = X * FG_SPAN; v = Y * FG_SPAN;      // a panel IS the plane
        }
        int j = (int)(((u / FG_SPAN) * 0.5f + 0.5f) * FG_NC);
        int b = (int)(((v / FG_SPAN) * 0.5f + 0.5f) * FG_NX);
        if (j < 0) j = 0; else if (j >= FG_NC) j = FG_NC - 1;
        if (b < 0) b = 0; else if (b >= FG_NX) b = FG_NX - 1;
        pj[ci] = (uint8_t)j; pb[ci] = (uint8_t)b;
      }
  }

  uint16_t dt = fx_dt8(s->clk);
  if (dt > 60) dt = 60;

  // --- audio ------------------------------------------------------------------
  um_data_t     *um  = cfx_getAudioData();
  const float    vol = *(float *)um->u_data[0];
  const uint8_t  beat = SEGMENT.check1 ? fx_lowBeat(um) : 0;
  if (beat > s->surge) s->surge = beat;
  { const int f = (int)s->surge - (int)fx_step(6, dt);
    s->surge = (uint8_t)(f < 0 ? 0 : f); }

  // --- parameters ---------------------------------------------------------------
  const int  gainI  = 40 + ((int)SEGMENT.intensity * 215) / 255;
  const int  spread = (int)SEGMENT.custom1;
  const int  trail  = (int)SEGMENT.custom2;
  const int  detail = (int)cfx_c3full(SEGMENT.custom3);
  const bool hold   = SEGMENT.check2;

  // --- the zoom ---------------------------------------------------------------
  // One wrap is one period doubling. The window resets by exactly delta, so the
  // phase can run for ever without the zoom ever going deep enough to exhaust
  // float - see the header for what the seam actually measures.
  if (!hold) {
    // Rate is set so one DOUBLING takes a few seconds. The first draft ran a
    // loop in 56 s, which is mathematically a zoom and visually a still frame.
    const int32_t step = ((40 + (int32_t)SEGMENT.speed * 2)
                          * (int32_t)dt * (100 + (int32_t)s->surge / 3)) / (23 * 100);
    const uint32_t nt = s->tZoom + (uint32_t)(step < 1 ? 1 : step);
    if (nt >= 65536u) {
      s->flip = s->flip ? 0 : 1;          // alpha is negative: invert on each wrap
      s->rewarm = 24;                     // the orbits have a long way to move
    }
    s->tZoom = nt & 0xFFFFu;
  }
  const float t  = (float)s->tZoom * (1.0f / 65536.0f);
  const float sc = 0.4f + (float)spread * (2.2f / 255.0f);
  const float Wc = 0.0075f * sc * expf(-t * FG_LNDELTA);
  const float Wx = 0.0500f * sc * expf(-t * FG_LNALPHA);

  // --- measure the attractor, column by column --------------------------------
  int warm = 6 + (detail * 26) / 255;
  const int keep = 20 + (detail * 46) / 255;
  if (s->rewarm) { warm += 90; s->rewarm--; }

  {
    const uint8_t f = fx_fade(6 + ((255 - trail) * 30) / 255, dt);
    if (f) for (size_t i = 0; i < (size_t)FG_NC * FG_NX; i++)
      den[i] = (den[i] > f) ? (uint8_t)(den[i] - f) : 0;
  }

  for (int j = 0; j < FG_NC; j++) {
    const float uu = ((float)j + 0.5f) / (float)FG_NC * 2.0f - 1.0f;   // -1..1
    const float c  = FG_MF + uu * FG_SPAN * Wc;
    float x = s->xs[j];
    if (!(x > -4.0f && x < 4.0f)) x = 0.0f;
    for (int k = 0; k < warm; k++) {
      x = x * x + c;
      if (!(x > -4.0f && x < 4.0f)) { x = 0.0f; break; }
    }
    uint8_t *cell = den + (size_t)j * FG_NX;
    for (int k = 0; k < keep; k++) {
      x = x * x + c;
      if (!(x > -4.0f && x < 4.0f)) { x = 0.0f; continue; }
      const float xv = s->flip ? -x : x;
      int b = (int)((xv / (FG_SPAN * Wx) * 0.5f + 0.5f) * (float)FG_NX);
      if (b < 0 || b >= FG_NX) continue;
      const int add = 40;
      int q = (int)cell[b] + add;             cell[b]   = (uint8_t)(q > 255 ? 255 : q);
      if (b > 0)         { q = (int)cell[b-1] + add/3; cell[b-1] = (uint8_t)(q > 255 ? 255 : q); }
      if (b < FG_NX - 1) { q = (int)cell[b+1] + add/3; cell[b+1] = (uint8_t)(q > 255 ? 255 : q); }
    }
    s->xs[j] = x;
  }

  s->hueCyc = (uint16_t)(s->hueCyc + (uint32_t)dt * 7u);
  const uint8_t drive = cfx_drive(vol, 0.5f, 200);

  // --- paint ----------------------------------------------------------------
  CFX_NET_PREP();
  for (int y = 0; y < rows; y++) {
    CFX_NET_ROW(y);
    for (int x = 0; x < cols; x++) {
      CFX_NET_SKIP(x);
      const size_t i = (size_t)cfx_cidx(x, y, cols, B, cube);
      const int b = s->flip ? (FG_NX - 1 - (int)pb[i]) : (int)pb[i];
      const uint8_t v = den[(size_t)pj[i] * FG_NX + b];

      uint32_t c = 0;
      if (v) {
        // Hue follows the orbit axis, so a branch keeps its colour as it splits.
        const uint8_t idx = (uint8_t)(((int)pb[i] * 255) / FG_NX
                                      + (uint8_t)(s->hueCyc >> 8));
        int q = ((int)v * gainI) >> 8;
        if (q > 255) q = 255;
        c = SEGMENT.color_from_palette(idx, false, true, 0);
        c = mq_scale(c, (uint8_t)q);
      }
      SEGMENT.setPixelColorXY(x, y, mq_scale(c, drive));
    }
  }
  FX_DONE;
}

static const char _data_FX_MODE_FEIGENBAUM[] PROGMEM =
  "Ace 3-D Feigenbaum@Zoom speed,Brightness,Spread,Trail,Detail,Beat surge,Hold depth,Flat mode;;!;2f;sx=90,ix=210,c1=120,c2=170,c3=18,o1=1,pal=11";


// ---------------------------------------------------------------------------
// Registration - joins the effect bank, which decides whether this effect
// claims one of the device's limited effect slots. See cube_fx_bank.h.
// ---------------------------------------------------------------------------
static CfxBankReg cube_fx_35_feigenbaum_reg(&mode_feigenbaum, _data_FX_MODE_FEIGENBAUM);
