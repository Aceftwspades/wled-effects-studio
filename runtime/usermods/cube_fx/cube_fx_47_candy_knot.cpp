#include "wled.h"
#include "cube_fx_common.h"
#include "cube_fx_bank.h"

// ===========================================================================
// Ace 3-D Candy Knot - Torus Knot's fat, banded sibling
// ===========================================================================
// The same (p,q) knot as Torus Knot, seen from inside by the same closed-form
// meridian construction - see that file for why there is no ray marching and
// why that is not a shortcut. Everything ABOUT the tubes is different, and it
// was set by a stage-screen reference: a braid of inflated tubes, each wrapped
// in hard black-and-pastel bands, the hue drifting along the tube through a
// whole rainbow, soft lighting, no gloss, black behind.
//
// ---------------------------------------------------------------------------
// FAT, AND WHAT THAT COSTS
// ---------------------------------------------------------------------------
// Torus Knot's tubes are thin so the knot reads as a curve. These are up to
// four times as thick, so the knot reads as a bundle of pipes crossing over
// each other - which from the middle of the hole means pipes passing close
// overhead and filling half the view. That is the reference: it is a picture
// of tubes, not of a curve.
//
// The geometry has to make room for it. Torus Knot puts the knot's own torus
// at r = 0.68 R, which leaves the nearest strand 0.32 R from the viewer - fine
// for a tube of 0.15, engulfing for one of 0.40. Here the torus is at 0.60 R,
// so the nearest strand is 0.40 R away and the fattest tube, 0.38, still
// clears the viewer. The curve itself reaches 56 degrees of elevation, but
// the tubes add their own radius to that, and the fattest reaches the pole.
//
// The meridian construction treats the tube's cut through the plane as a
// disc, which it is exactly only where the curve crosses the plane square-on.
// At Torus Knot's thickness the error is invisible; here it flattens the
// tubes a little where they run steeply. The reference tubes are not perfect
// cylinders either, and it is not worth a root-find per pixel to fix.
//
// ---------------------------------------------------------------------------
// BANDS, NOT RINGS
// ---------------------------------------------------------------------------
// Torus Knot's Rings modulate brightness gently along the curve. These are
// HARD: half the period pastel, half the period black, one pixel of edge. The
// band is the curve parameter modulo a spacing, so it wraps the tube as a
// cross-section - and because the meridian construction hands each pixel the
// parameter of the crossing it hit, the bands come out as the ellipses the
// reference shows, foreshortened where a tube runs toward the viewer.
//
// Black is most of the picture. The reference is about half black inside the
// tubes' own outline, and that is what makes a tube read as banded rather
// than as striped: the dark bands are gaps in the light, not a darker colour.
//
// ---------------------------------------------------------------------------
// PASTEL, AND THE SEAM
// ---------------------------------------------------------------------------
// The colour along a tube is the palette walked by the curve parameter, once
// or twice round the wheel per knot, then pulled a third of the way to white.
// Pastel is not a softer palette, it is the same palette with its brightness
// equalised - the dark palette entries come up to meet the light ones, so a
// blue band is as present as a yellow one. Lighting is a wide wrap with a
// heavy ambient, a darkening where the surface turns away, and a Blinn-Phong
// highlight that lands on the black bands as well as the pastel - a black
// band on a glossy tube still catches the light, and a highlight that only
// showed on every other band would stutter along the tube.
//
// The thin lines that run along the tubes in the reference - a red one, a
// green one, riding the crest - are the Seam: a stripe a few degrees wide
// where the tube's normal points along the knot's axis, drawn a half-wheel
// off the tube's hue, running the length of the tube UNDER the bands and
// showing only through the black ones. It is a cheap thing that adds a great
// deal, because it is the only line in the picture that follows the tube's
// LENGTH, and the eye uses it to read which way each tube is going.
// ===========================================================================

#define CK_R       1.00f        // torus major radius
#define CK_r       0.60f        // minor radius - see the header
#define CK_TWOPI   6.28318531f

struct CkState {
  uint8_t  mode;
  uint8_t  clk[2];
  uint8_t  surge;
  uint16_t spinA, spinB;        // the tumble, on two axes
  uint16_t flow;                // the bands slide along the tubes
  uint16_t kick;                // flow owed but not yet delivered
  uint16_t drift;               // palette rotation
};

static FX_RET mode_candyknot() {
  if (!strip.isMatrix || !SEGMENT.is2D()) { SEGMENT.fill(SEGCOLOR(0)); FX_DONE; }
  const int cols = SEG_W, rows = SEG_H;
  if (cols < 8 || rows < 8) { SEGMENT.fill(SEGCOLOR(0)); FX_DONE; }

  const bool cube = cfx_isCube(cols, rows);
  const int  B    = cube ? (cols / 3) : 1;

  if (!SEGENV.allocateData(sizeof(CkState))) { SEGMENT.fill(SEGCOLOR(0)); FX_DONE; }
  CkState *s = (CkState *)SEGENV.data;

  const uint8_t want = (uint8_t)(cube ? 1 : 2);
  if (SEGENV.call == 0 || s->mode != want) {
    s->mode = want; s->clk[0] = s->clk[1] = 0;
    s->spinA = 0; s->spinB = 11000; s->flow = 0; s->drift = 0; s->surge = 0;
    s->kick = 0;
  }

  uint16_t dt = fx_dt8(s->clk);
  if (dt > 60) dt = 60;

  // --- parameters -----------------------------------------------------------
  const int  fill   = (int)SEGMENT.intensity * 2;
  const int  thickI = (int)SEGMENT.custom1;
  const int  bandI  = (int)SEGMENT.custom2;
  const bool seam   = SEGMENT.check2;
  int P, Q; cfx_knotPQ(SEGMENT.custom3, P, Q);

  // --- audio ----------------------------------------------------------------
  um_data_t     *um   = cfx_getAudioData();
  const float    vol  = *(float *)um->u_data[0];
  const uint8_t  beat = SEGMENT.check1 ? fx_lowBeat(um) : 0;
  if (beat > s->surge) s->surge = beat;
  { const int f = (int)s->surge - (int)fx_step(32, dt);
    s->surge = (uint8_t)(f < 0 ? 0 : f); }
  // The bands lurch along the tubes - owed rather than applied, a third of the
  // debt a frame, so the rush is drawn rather than cut to.
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
    s->spinB = (uint16_t)(s->spinB + (r * 4u) / 5u);
    s->flow  = (uint16_t)(s->flow + (r * 3u) / 7u); }
  s->drift = (uint16_t)(s->drift + ((uint32_t)dt * (uint32_t)SEGMENT.speed) / 90u);

  float M[3][3];
  { const float a = (float)s->spinA * (CK_TWOPI / 65536.0f);
    const float b = (float)s->spinB * (CK_TWOPI / 65536.0f);
    const float ca = cfx_cosf16(a), sa = cfx_sinf16(a), cb = cfx_cosf16(b), sb = cfx_sinf16(b);
    M[0][0] =  ca;      M[0][1] = -sa;      M[0][2] = 0.0f;
    M[1][0] =  cb * sa; M[1][1] =  cb * ca; M[1][2] = -sb;
    M[2][0] =  sb * sa; M[2][1] =  sb * ca; M[2][2] =  cb; }

  // Fat: 0.16 to 0.38 R. The ceiling is the nearest strand's distance, 0.40,
  // less a margin so the viewer is never inside a tube.
  const float tube  = 0.16f + (float)thickI * (0.22f / 255.0f);
  const float tube2 = tube * tube;
  // Bands per turn of the curve parameter. The reference has roughly one band
  // per tube radius; at the default thickness and P = 3 that is about 40.
  const float bands = 16.0f + (float)bandI * (80.0f / 255.0f);
  const float phase = (float)s->flow * (CK_TWOPI / 65536.0f);
  const float invP  = 1.0f / (float)P;

  // Light in the cube's frame, carried into knot space by the same matrix.
  float Lx, Ly, Lz;
  { const float lx = 0.30f, ly = -0.25f, lz = 0.92f;
    Lx = M[0][0]*lx + M[0][1]*ly + M[0][2]*lz;
    Ly = M[1][0]*lx + M[1][1]*ly + M[1][2]*lz;
    Lz = M[2][0]*lx + M[2][1]*ly + M[2][2]*lz; }

  const uint8_t hueOff = (uint8_t)(s->drift >> 8);
  const uint8_t drive  = cfx_drive(vol, 0.5f, 200);
  // The beat also fattens the bands for a moment - the light half grows - so
  // a hit reads on the tubes' surface as well as in their motion.
  const float duty = 0.50f + (float)s->surge * (0.16f / 255.0f);

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

      float nx = X * iL, ny = Y * iL, nz = Z * iL;
      { const float rx = M[0][0]*nx + M[0][1]*ny + M[0][2]*nz;
        const float ry = M[1][0]*nx + M[1][1]*ny + M[1][2]*nz;
        const float rz = M[2][0]*nx + M[2][1]*ny + M[2][2]*nz;
        nx = rx; ny = ry; nz = rz; }

      const float sxy = sqrtf(nx * nx + ny * ny);
      const float u   = cfx_atan2f(ny, nx);

      // --- the closed form: p crossings in this meridian --------------------
      float bestL = 1e9f, bestT = 0.0f, bestRho = 0.0f, bestZ = 0.0f;
      for (int k = 0; k < P; k++) {
        const float t   = (u + CK_TWOPI * (float)k) * invP;
        const float v   = (float)Q * t;
        const float rho = CK_R + CK_r * cfx_cosf16(v);
        const float zz  =        CK_r * cfx_sinf16(v);
        const float ell = rho * sxy + zz * nz;
        if (ell <= 0.0f) continue;
        float d2 = rho * rho + zz * zz - ell * ell;
        if (d2 < 0.0f) d2 = 0.0f;
        if (d2 < tube2) {
          const float hit = ell - sqrtf(tube2 - d2);
          if (hit > 0.0f && hit < bestL) {
            bestL = hit; bestT = t; bestRho = rho; bestZ = zz;
          }
        }
      }

      int lum = 0;
      uint8_t idx = hueOff;
      bool pastel = true;
      if (bestL < 1e8f) {
        const float qx = bestL * nx, qy = bestL * ny, qz = bestL * nz;
        const float cu = (sxy > 1e-6f) ? (nx / sxy) : 1.0f;
        const float su = (sxy > 1e-6f) ? (ny / sxy) : 0.0f;
        float Nx = qx - bestRho * cu, Ny = qy - bestRho * su, Nz = qz - bestZ;
        const float NL = sqrtf(Nx*Nx + Ny*Ny + Nz*Nz);
        const float iN = (NL > 1e-6f) ? (1.0f / NL) : 1.0f;
        Nx *= iN; Ny *= iN; Nz *= iN;

        // --- the band ------------------------------------------------------
        // Curve parameter, slid by the flow, modulo the spacing. Hard edge,
        // softened over about a pixel of parameter so it does not crawl.
        float g = (bestT + phase * 0.25f) * bands * (1.0f / CK_TWOPI);
        g -= floorf(g);
        const float edge = 0.06f;
        float on = (g < duty) ? (g / edge) : ((duty + edge - g) / edge);
        if (g > edge && g < duty) on = 1.0f;
        if (on < 0.0f) on = 0.0f; else if (on > 1.0f) on = 1.0f;
        on = on * on * (3.0f - 2.0f * on);

        // --- shading -------------------------------------------------------
        // Wide wrap and a heavy floor, darkening as the surface turns from the
        // viewer, and a Blinn-Phong highlight on top. The highlight is applied
        // to the black bands as well as the pastel ones - a black band on a
        // glossy tube still catches the light - so the gloss sweeps across the
        // whole tube instead of stuttering band to band.
        float diff = 0.5f + 0.5f * (Nx*Lx + Ny*Ly + Nz*Lz);
        float face = -(Nx*nx + Ny*ny + Nz*nz);           // 1 facing the viewer
        if (face < 0.0f) face = 0.0f;
        float shade = (0.30f + 0.58f * diff) * (0.50f + 0.50f * face);
        const float dep = 1.25f - 0.28f * bestL;         // nearer is brighter
        shade *= (dep < 0.45f) ? 0.45f : dep;

        float spec = 0.0f;
        { float hx = Lx - nx, hy = Ly - ny, hz = Lz - nz;   // view dir is -n
          const float hl = sqrtf(hx*hx + hy*hy + hz*hz);
          if (hl > 1e-6f) {
            spec = (Nx*hx + Ny*hy + Nz*hz) / hl;
            if (spec < 0.0f) spec = 0.0f;
            spec *= spec; spec *= spec; spec *= spec;      // ^8
          } }

        // --- the seam ------------------------------------------------------
        // A thin stripe where the normal points along the knot's axis: the
        // crest of the tube, drawn half a wheel away. It shows in the BLACK
        // bands and is covered by the pastel ones - a line that runs the
        // length of the tube underneath the bands and is only visible through
        // the gaps, which is how the reference's thin lines read.
        bool onSeam = false;
        if (seam && on < 0.5f) {
          const float c = Nz;                            // cos of angle to axis
          if (c > 0.90f) onSeam = true;
        }

        // Dark bands are near-black: the picture is half gap. The highlight is
        // added AFTER the band mask so it lands on both - but tighter on the
        // black bands (^16 against ^8), because at ^8 the lobe lifted whole
        // black bands to grey and the picture went from half dark to a third.
        // A black band should stay black except where the light actually
        // catches it.
        float lit = 0.05f + 0.95f * on;
        if (onSeam) lit = 0.80f;                         // the seam through the gap
        const float glos = spec * (on + (1.0f - on) * spec);
        lum = (int)((float)fill * (shade * lit + 0.60f * glos));

        // Hue walks the wheel along the tube - 1.5 turns round the whole
        // knot - so neighbouring crossings differ and one tube shades through
        // a rainbow on its way round.
        idx = (uint8_t)((int)(bestT * (1.5f * 256.0f / CK_TWOPI)) + hueOff);
        if (onSeam) { idx = (uint8_t)(idx + 128); pastel = false; }
      }

      if (lum < 0) lum = 0; else if (lum > 255) lum = 255;
      uint32_t c = 0;
      if (lum) {
        c = SEGMENT.color_from_palette(idx, false, true, 0);
        if (pastel) {
          // A third of the way to white, per channel, BEFORE the brightness
          // scale - so the pastel is in the colour, not in the level.
          const int r = (int)((c >> 16) & 255), g2 = (int)((c >> 8) & 255), b = (int)(c & 255);
          c = RGBW32((uint8_t)(r + ((255 - r) * 88) / 255),
                     (uint8_t)(g2 + ((255 - g2) * 88) / 255),
                     (uint8_t)(b + ((255 - b) * 88) / 255), 0);
        }
        c = mq_scale(c, (uint8_t)lum);
      }
      SEGMENT.setPixelColorXY(x, y, mq_scale(c, drive));
    }
  }
  FX_DONE;
}

static const char _data_FX_MODE_CANDYKNOT[] PROGMEM =
  "Ace 3-D Candy Knot@Tumble,Fill,Thickness,Bands,Knot,Beat surge,Seam,Flat mode;;!;2f;sx=80,ix=128,c1=170,c2=90,c3=9,o1=1,o2=1,pal=11";


// ---------------------------------------------------------------------------
// Registration - joins the effect bank, which decides whether this effect
// claims one of the device's limited effect slots. See cube_fx_bank.h.
// ---------------------------------------------------------------------------
static CfxBankReg cube_fx_47_candyknot_reg(&mode_candyknot, _data_FX_MODE_CANDYKNOT);
