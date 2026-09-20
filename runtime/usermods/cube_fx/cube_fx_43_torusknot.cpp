#include "wled.h"
#include "cube_fx_common.h"
#include "cube_fx_bank.h"

// ===========================================================================
// Ace 3-D Torus Knot - a (p,q) knot, rendered from inside it
// ===========================================================================
// The cube is used here as what it physically is: a CUBEMAP. Every pixel's
// outward direction is a ray leaving the middle of the solid, so the five
// faces together are a panoramic viewport onto a scene that surrounds the
// viewer. A knot is hung in that space and the cube shows it from within.
// Seamless for the usual reason - a pixel's ray is a function of its surface
// direction, so the folds of the net never enter into it - and it is the one
// thing on this list a flat panel simply cannot do.
//
// ---------------------------------------------------------------------------
// WHY THERE IS NO RAY MARCHING HERE, AND WHY THAT IS NOT A SHORTCUT
// ---------------------------------------------------------------------------
// The brief asks for signed distance fields and sphere tracing, which is how
// you would do this in a fragment shader with a camera anywhere in the scene.
// Put the camera at the torus's own centre, though, and the problem collapses.
//
// A (p,q) torus knot is
//     r(t) = ( (R + r cos qt) cos pt, (R + r cos qt) sin pt, r sin qt )
// and the angle around the main axis, atan2(y,x), is CONSTANT along any ray
// through the origin. So a ray never leaves its meridian half-plane - and in
// that plane the entire knot is just p points, at tube angles
//     v_k = q (u + 2 pi k) / p,   k = 0 .. p-1.
//
// So the nearest surface along a ray is a closed-form ray-to-point distance,
// evaluated p times. No marching, no epsilon, no step count, no missed thin
// geometry: about thirty flops a pixel instead of twenty sphere-trace
// iterations of a transcendental distance estimate. The SDF is still what is
// being solved - it is just solved rather than searched.
//
// The Frenet-Serret frame the brief mentions goes the same way. A frame is
// needed to EXTRUDE a circle along a curve, which is the mesh approach; a
// tube defined as "within d of the curve" needs no frame at all, and cannot
// twist unnaturally because there is nothing to twist. The two bullets are
// alternative constructions of one shape, and the implicit one is free here.
//
// ---------------------------------------------------------------------------
// A FAT TORUS, BECAUSE THE POLES WOULD BE EMPTY OTHERWISE
// ---------------------------------------------------------------------------
// Seen from the middle of its own hole, a thin torus is a band round the
// equator and the lid shows nothing at all. The elevation it reaches is
// atan(r / (R-r)), so at the usual r/R of 0.42 that is 36 degrees and leaves
// a 54 degree cap dark at each pole. Hence a deliberately fat torus.
//
// It can go too far the other way, and did: at 0.74 the nearest strand sits
// 0.26 R from the viewer, where a tube of any useful thickness subtends 32
// degrees and the view is not a knot but the inside of a tangle of pipes.
// 0.58 puts the nearest strand at 0.42 R, reaches 54 degrees of elevation, and
// leaves caps the two-axis tumble carries round within a few seconds.
//
// ---------------------------------------------------------------------------
// SHADING
// ---------------------------------------------------------------------------
// The hit point's normal is the direction from the curve out to the surface,
// which the meridian construction hands over directly. Blinn-Phong on top of
// that: a diffuse term, a halfway-vector specular, and a little ambient so the
// unlit side is dark rather than black. Rings come from the curve parameter
// taken modulo a spacing - domain repetition, applied to the parameter rather
// than to space, so the bands ride the tube instead of cutting through it.
// ===========================================================================

#define TK_R       1.00f        // torus major radius
#define TK_r       0.68f        // minor radius - see the header
#define TK_TWOPI   6.28318531f

struct TkState {
  uint8_t  mode;
  uint8_t  clk[2];
  uint8_t  surge;
  uint16_t spinA, spinB;        // the tumble, on two axes
  uint16_t flow;                // the knot's own phase - tubes slide along themselves
  uint16_t kick;                // phase owed to flow but not yet delivered
  uint16_t drift;               // palette rotation
};

static FX_RET mode_torusknot() {
  if (!strip.isMatrix || !SEGMENT.is2D()) { SEGMENT.fill(SEGCOLOR(0)); FX_DONE; }
  const int cols = SEG_W, rows = SEG_H;
  if (cols < 8 || rows < 8) { SEGMENT.fill(SEGCOLOR(0)); FX_DONE; }

  const bool cube = cfx_isCube(cols, rows);
  const int  B    = cube ? (cols / 3) : 1;

  if (!SEGENV.allocateData(sizeof(TkState))) { SEGMENT.fill(SEGCOLOR(0)); FX_DONE; }
  TkState *s = (TkState *)SEGENV.data;

  const uint8_t want = (uint8_t)(cube ? 1 : 2);
  if (SEGENV.call == 0 || s->mode != want) {
    s->mode = want; s->clk[0] = s->clk[1] = 0;
    s->spinA = 0; s->spinB = 11000; s->flow = 0; s->drift = 0; s->surge = 0;
    s->kick = 0;
  }

  uint16_t dt = fx_dt8(s->clk);
  if (dt > 60) dt = 60;

  // --- parameters -----------------------------------------------------------
  // Doubled internally so the default sits mid-slider. How much of the view
  // a knot covers is set mostly by P - the number of strands crossing each
  // meridian - not by thickness: measured, the whole Thickness range moves the
  // mean from 14 to 18, while going from the trefoil's two strands to five
  // takes it from 16 to 26. So the simple knots need the headroom.
  const int  fill   = (int)SEGMENT.intensity * 2;
  const int  thickI = (int)SEGMENT.custom1;
  const int  ringI  = (int)SEGMENT.custom2;
  const bool chrome = SEGMENT.check2;
  int P, Q; cfx_knotPQ(SEGMENT.custom3, P, Q);   // the table is in common.h

  // --- audio ----------------------------------------------------------------
  um_data_t     *um   = cfx_getAudioData();
  const float    vol  = *(float *)um->u_data[0];
  const uint8_t  beat = SEGMENT.check1 ? fx_lowBeat(um) : 0;
  if (beat > s->surge) s->surge = beat;
  { const int f = (int)s->surge - (int)fx_step(20, dt);
    s->surge = (uint8_t)(f < 0 ? 0 : f); }
  // A lurch along the tube, owed rather than applied - delivered instantly the
  // tubes cut to a new position and the travel is never drawn. A third of the
  // debt a frame puts most of it inside 140 ms and leaves the rush visible.
  if (beat) {
    uint32_t k = (uint32_t)s->kick + (uint32_t)beat;
    if (k > 620u) k = 620u;
    s->kick = (uint16_t)k;
  }
  if (s->kick) {
    uint32_t give = ((uint32_t)s->kick * (uint32_t)dt) / 70u;
    if (!give) give = 1;
    if (give > s->kick) give = s->kick;
    s->flow = (uint16_t)(s->flow + give * 36u);
    s->kick = (uint16_t)(s->kick - give);
  }

  // --- clocks ---------------------------------------------------------------
  { const uint32_t r = (uint32_t)(3 + (int)SEGMENT.speed / 2) * (uint32_t)dt / 23u;
    s->spinA = (uint16_t)(s->spinA + r);
    // The second axis is what carries the torus's polar gap off the lid, and
    // at 5/13 of the first it took 85 seconds to precess once - long enough
    // that the lid measured a third dimmer than the rest over a 25s run.
    s->spinB = (uint16_t)(s->spinB + (r * 4u) / 5u);
    s->flow  = (uint16_t)(s->flow + (r * 3u) / 7u); }
  s->drift = (uint16_t)(s->drift + ((uint32_t)dt * (uint32_t)SEGMENT.speed) / 90u);

  // Tumble, as one matrix built per frame rather than per pixel.
  float M[3][3];
  { const float a = (float)s->spinA * (TK_TWOPI / 65536.0f);
    const float b = (float)s->spinB * (TK_TWOPI / 65536.0f);
    const float ca = cfx_cosf16(a), sa = cfx_sinf16(a), cb = cfx_cosf16(b), sb = cfx_sinf16(b);
    M[0][0] =  ca;      M[0][1] = -sa;      M[0][2] = 0.0f;
    M[1][0] =  cb * sa; M[1][1] =  cb * ca; M[1][2] = -sb;
    M[2][0] =  sb * sa; M[2][1] =  sb * ca; M[2][2] =  cb; }

  const float tube  = 0.030f + (float)thickI * (0.125f / 255.0f);
  const float tube2 = tube * tube;
  // Bands per strand is rings * 2pi / P, so at 26 and P = 5 that is 32 bands
  // along a strand maybe thirty pixels long - about one band per pixel, which
  // aliases into speckle rather than reading as segmentation. 14 tops out at
  // 17 per strand, which still resolves.
  const float rings = (float)ringI * (14.0f / 255.0f);
  const float phase = (float)s->flow * (TK_TWOPI / 65536.0f);
  const float invP  = 1.0f / (float)P;

  // Light lives in the cube's frame, so highlights stay put on the solid while
  // the knot tumbles past them. Carried into knot space by the same matrix.
  float Lx, Ly, Lz;
  { const float lx = 0.40f, ly = -0.34f, lz = 0.85f;
    Lx = M[0][0]*lx + M[0][1]*ly + M[0][2]*lz;
    Ly = M[1][0]*lx + M[1][1]*ly + M[1][2]*lz;
    Lz = M[2][0]*lx + M[2][1]*ly + M[2][2]*lz; }

  const uint8_t hueOff = (uint8_t)(s->drift >> 8);
  const uint8_t drive  = cfx_drive(vol, 0.5f, 200);
  const float   glowK  = 0.030f + (float)s->surge * (0.055f / 255.0f);

  // --- paint ----------------------------------------------------------------
  CFX_NET_PREP();
  for (int y = 0; y < rows; y++) {
    CFX_NET_ROW(y);
    for (int x = 0; x < cols; x++) {
      CFX_NET_SKIP(x);

      float X, Y, Z; cfx_pos(x, y, cols, rows, B, cube, X, Y, Z);
      if (!cube) Z = 1.0f - (X * X + Y * Y) * 0.5f;      // a panel becomes a dome
      const float PL = sqrtf(X * X + Y * Y + Z * Z);
      const float iL = (PL > 1e-6f) ? (1.0f / PL) : 1.0f;

      // the ray, in knot space
      float nx = X * iL, ny = Y * iL, nz = Z * iL;
      { const float rx = M[0][0]*nx + M[0][1]*ny + M[0][2]*nz;
        const float ry = M[1][0]*nx + M[1][1]*ny + M[1][2]*nz;
        const float rz = M[2][0]*nx + M[2][1]*ny + M[2][2]*nz;
        nx = rx; ny = ry; nz = rz; }

      const float sxy = sqrtf(nx * nx + ny * ny);
      const float u   = cfx_atan2f(ny, nx);

      // --- the closed form: p points in this meridian, p ray-point tests ----
      float bestL = 1e9f, bestT = 0.0f, bestRho = 0.0f, bestZ = 0.0f;
      float nearest = 1e9f;
      for (int k = 0; k < P; k++) {
        const float t   = (u + TK_TWOPI * (float)k) * invP;
        const float v   = (float)Q * t + phase;
        const float rho = TK_R + TK_r * cfx_cosf16(v);
        const float zz  =        TK_r * cfx_sinf16(v);
        const float ell = rho * sxy + zz * nz;           // along the ray
        if (ell <= 0.0f) continue;                       // behind the viewer
        float d2 = rho * rho + zz * zz - ell * ell;      // perpendicular, squared
        if (d2 < 0.0f) d2 = 0.0f;
        if (d2 < nearest) nearest = d2;
        if (d2 < tube2) {
          const float hit = ell - sqrtf(tube2 - d2);
          if (hit > 0.0f && hit < bestL) {
            bestL = hit; bestT = t; bestRho = rho; bestZ = zz;
          }
        }
      }

      int lum = 0;
      uint8_t idx = hueOff;
      if (bestL < 1e8f) {
        // surface point and its normal: straight out from the curve
        const float qx = bestL * nx, qy = bestL * ny, qz = bestL * nz;
        const float cu = (sxy > 1e-6f) ? (nx / sxy) : 1.0f;
        const float su = (sxy > 1e-6f) ? (ny / sxy) : 0.0f;
        float Nx = qx - bestRho * cu, Ny = qy - bestRho * su, Nz = qz - bestZ;
        const float NL = sqrtf(Nx*Nx + Ny*Ny + Nz*Nz);
        const float iN = (NL > 1e-6f) ? (1.0f / NL) : 1.0f;
        Nx *= iN; Ny *= iN; Nz *= iN;

        // --- Blinn-Phong ---------------------------------------------------
        // Half-Lambert rather than clamped Lambert. A tube lit by one source
        // has half its visible surface facing away, and clamped at zero that
        // half drops to bare ambient - which measured as a mean of 18 and read
        // as murk. Wrapping the term keeps the dark side shaded instead of
        // black, and squaring it keeps the terminator from going flat.
        float diff = 0.5f + 0.5f * (Nx*Lx + Ny*Ly + Nz*Lz);
        diff *= diff;
        float hx = Lx - nx, hy = Ly - ny, hz = Lz - nz;   // view dir is -n
        const float hl = sqrtf(hx*hx + hy*hy + hz*hz);
        float spec = 0.0f;
        if (hl > 1e-6f) {
          spec = (Nx*hx + Ny*hy + Nz*hz) / hl;
          if (spec < 0.0f) spec = 0.0f;
          spec *= spec; spec *= spec; spec *= spec;        // ^8
          if (chrome) spec *= spec;                        // ^16, tighter and harder
        }

        float shade = 0.10f + 0.92f * diff + (chrome ? 1.6f : 0.80f) * spec;

        // --- domain repetition: rings along the curve parameter -------------
        if (rings > 0.35f) {
          float g = bestT * rings;
          g = g - floorf(g);
          const float band = (g < 0.5f) ? (g * 2.0f) : ((1.0f - g) * 2.0f);
          shade *= 0.42f + 0.58f * band;
        }

        // depth: nearer tube reads brighter, which separates the crossings
        const float dep = 1.35f - 0.32f * bestL;
        shade *= (dep < 0.35f) ? 0.35f : dep;

        lum = (int)((float)fill * shade);
        idx = (uint8_t)((int)(bestT * 23.0f) + hueOff);
      } else if (nearest < 1e8f) {
        // A miss still knows how far it missed by - the SDF is right there, so
        // the tubes get a halo instead of a hard silhouette on black.
        const float dd = sqrtf(nearest) - tube;
        if (dd < 0.55f) {
          float g = 1.0f - dd * (1.0f / 0.55f);
          g = g * g * g;
          lum = (int)((float)fill * g * glowK * 8.0f);
          idx = (uint8_t)(hueOff + 128);
        }
      }

      if (lum < 0) lum = 0; else if (lum > 255) lum = 255;
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

static const char _data_FX_MODE_TORUSKNOT[] PROGMEM =
  "Ace 3-D Torus Knot@Tumble,Fill,Thickness,Rings,Knot,Beat surge,Chrome,Flat mode;;!;2f;sx=90,ix=128,c1=170,c2=120,c3=9,o1=1,pal=11";


// ---------------------------------------------------------------------------
// Registration - joins the effect bank, which decides whether this effect
// claims one of the device's limited effect slots. See cube_fx_bank.h.
// ---------------------------------------------------------------------------
static CfxBankReg cube_fx_43_torusknot_reg(&mode_torusknot, _data_FX_MODE_TORUSKNOT);
