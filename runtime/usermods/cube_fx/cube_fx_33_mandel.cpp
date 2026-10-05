#include "wled.h"
#include "cube_fx_common.h"
#include "cube_fx_bank.h"

// ===========================================================================
// Ace 3-D Mandelbrot - a genuinely endless zoom, on a cube
// ===========================================================================
// STEREOGRAPHIC projection, and it is the only sensible way to put a plane
// figure on a closed surface.
//
// Project each pixel's direction from the bottom pole onto the plane z = 0:
//
//     u = px / (1 + pz),   v = py / (1 + pz)
//
// The lid becomes the origin, the equator a unit circle, and the bottom edges
// run out to a radius of about two and a half. The map is CONFORMAL - it
// preserves angles, so a circle stays a circle and the set's filaments keep
// their shape as they cross a seam. Any of the obvious alternatives shear it:
// unwrapping the net puts four hard creases through the figure, and a polar
// map stretches everything into a fan. The whole appeal of this set is local
// structure, and a projection that does not preserve it is not worth drawing.
//
// The cube has no bottom face, so nothing ever reaches the pole and the
// projection stays bounded. That is luck rather than design, but it means no
// clamping and no special case at infinity.
//
// ---------------------------------------------------------------------------
// THE ZOOM: SELF-SIMILAR, SO IT NEVER HAS TO END
// ---------------------------------------------------------------------------
// A plain inward zoom cannot run for ever. Float32 holds about 22 octaves here
// before neighbouring cube pixels land on the same complex number and the set
// turns to mush, and the usual fixes - arbitrary precision, or cross-fading two
// levels an octave apart - cost either a software bignum or a second full
// iteration of every pixel. Neither is available on a cube already spending
// forty iterations on each of 1280 pixels.
//
// So this does not zoom deeper. It zooms in a LOOP.
//
// At a Misiurewicz point the critical orbit is pre-periodic: it falls onto a
// cycle without ever being on it. Around such a point the set is asymptotically
// SELF-SIMILAR, and the similarity has a known factor - multiply by lambda,
// the product of 2*z around the cycle, and the picture maps onto itself. So
// zooming in by |lambda| while turning by -arg(lambda) arrives back at the view
// it started from. The phase wraps, the scale resets, and nothing on screen
// moves: an endless dive built out of a few seconds of footage, at constant
// precision, for the cost of one extra rotate per pixel.
//
// Picking the points was the whole job, and two measurements shaped the table.
//
// FIRST: the loop only closes when the view is SMALL. Over the cube's full
// +/-2.5 span the seam correlation runs about 0.5 at a base scale of 0.04 and
// about 0.91 at 0.0015 - the similarity is asymptotic, so a wide view reaches
// out into where it has not converged yet. The base below is 0.0015, and the
// loop is centred on it geometrically, sqrt(|lambda|) out to 1/sqrt(|lambda|),
// so every entry sits at the same average depth however fast it travels. The
// deepest any of them reaches still leaves eight bits of float headroom.
//
// SECOND, and this one nearly shipped: five REAL-AXIS points scored 0.99-1.00,
// far better than anything off-axis. They were frauds. A control with the wrong
// lambda - scale off by 1.7x - also scored 1.00, because the trap field along
// the real axis is scale-invariant on its own, having no angular structure to
// disagree about. A perfect seam there means the zoom is invisible, not smooth.
// Every point in the table below is off-axis and beats its own wrong-lambda
// control by at least 0.57, which is the number that actually means anything.
//
// ---------------------------------------------------------------------------
// COLOURING: THE ORBIT TRAP, AND ONLY THAT
// ---------------------------------------------------------------------------
// Every point's orbit is followed and the NEAREST it ever passes to either
// axis is recorded. That number, logged, is the colour. It ignores escape time
// completely, which is what makes it look unlike a fractal poster: instead of
// bands parading round the boundary it draws filigree threaded through the
// whole exterior, and the structure carries out into regions escape time
// renders as flat colour.
//
// Three others were built and measured first - smooth escape time, a distance
// estimate, and the argument at escape. Smooth escape is the classic and reads
// cleanly, but at forty-eight pixels its outer regions go flat. The distance
// estimate is the highest-contrast method on paper and the worst here in
// practice: it wants resolution the cube does not have, and lands as a soft
// halo rather than the thin filaments it draws on a screen. The argument gives
// rays but little else. The trap won on looks, and taking the others out also
// removed the orbit DERIVATIVE that only the distance estimate needed - two
// multiplies and an add per iteration per pixel, on the one effect here whose
// arithmetic is heavy enough for that to matter.
//
// The palette scroll is one clean rotation per loop and nothing else. The trap
// field comes back to itself after a loop - measured, the median change in its
// log at a pixel from one end of the loop to the other is under 0.05 at every
// locus - so the colour needs no compensating slide. An earlier version added
// one (fil*log2|lambda| per loop, on the theory that trap distances grow with
// the structure), and it was the only visible seam in the loop: a palette jump
// of 128-237 at the wrap against 24-32 for an ordinary frame.
//
// AI: below section was generated by an AI
// ---------------------------------------------------------------------------
// SHADING: TRAP GLOW, CUT BY CONTOUR LINES
// ---------------------------------------------------------------------------
// The trap gives the hue. On its own, at one brightness, it fills the whole
// exterior with mid-level colour: measured over every locus at three Filigree
// settings, a mean of 106 with nothing dark, and a step of 6.6 between
// neighbouring pixels - the filaments are there in hue but hardly in light.
// So the brightness comes from the trap too:
//
//   glow     smoothstep(lo, lo + 4.25, L)^1.5, L = -log2(trap). The orbits
//            that came nearest an axis are the filaments themselves; they
//            light, and the open exterior between them falls to black.
//   contours a dark line wherever L crosses a multiple of 32/fil, which is
//            where the palette index crosses a 32-step band. Each filament
//            reads as a stack of separate strands rather than a smear.
//
// Six techniques were tried at the cube's own 48 x 48 in a numpy port before
// this one: relief lighting from the potential's normal, smooth escape depth,
// the stripe average, and relief crossed with each of the others. The relief
// family is the classic screen-resolution answer and fell flat here - its
// shading varies across a few pixels, and the cube only has a few pixels.
// Glow with contours measured a mean of 43, 44% of the surface dark, sigma 35,
// and a neighbour step of 21: three times the readable edge of the even light.
// Both terms depend on L alone, which the loop returns to itself, so neither
// can show the seam.
//
// The glow's lower edge is an AUTO-EXPOSURE, not a constant. The loci differ:
// the first sits in open exterior with a mean L near 3, the second nearer 5.4,
// and a fixed edge that suits the average left the first 83% black. So each
// frame counts how much of the surface came out dark - by its BRIGHTEST
// CHANNEL, not luma: a deep red at (35,0,4) has a luma of 7 and is plainly lit,
// and counting it dark pinned the edge low and washed the open exterior in a
// dim red - and slides the edge towards 35% dark, at a rate that settles in
// about a second. It cannot pump with the zoom: the field it measures is the
// same at both ends of the loop.
//
// "Even light" (checkbox 2) restores the uniform brightness.
// AI: end
// ===========================================================================

// The loci. Each row is { cx, cy, ln|lambda|, arg(lambda) in radians }.
//
// Found by Newton's method on f^(k+p)(0) - f^k(0) = 0 over k in 1..6, p in 1..4,
// then filtered: off-axis only, at least 0.05 apart, and required to beat both
// a wrong-scale and a wrong-rotation control. Ordered by |lambda|, so the
// slider runs from a slow wide breath to a hard fast dive.
//
// Later verified against the exact algebraic construction of Hutz & Towsley,
// "Misiurewicz points for polynomial maps and transversality" (Theorem 1.1),
// which builds a polynomial G_2(m,n) in c whose roots are PRECISELY the
// Misiurewicz points of exact preperiod m and period n. That construction was
// checked first against the paper's own counting formula (Corollary 3.3) - the
// degrees agree for every m <= 5, n <= 4 - and then every entry below was found
// among its roots to 3e-10, which is the precision of the nine decimals stored
// here rather than any error in the root. The (m,n) noted per row is each
// point's exact type, from that check.
#define MD_NLOCI 8
static const float MD_LOCI[MD_NLOCI][4] PROGMEM = {
  { -0.228155494f,  1.115142508f, 1.127166f, -0.403695f },  // |L| 3.09  seam .94  (3,1)
  { -1.283657575f,  0.347724691f, 2.013296f, -1.111600f },  // |L| 7.49  seam .88  (3,3)
  { -1.239225555f,  0.412602182f, 2.353303f,  1.293064f },  // |L|10.52  seam .87  (2,3)
  { -0.623993500f,  0.664465831f, 2.823479f, -1.529280f },  // |L|16.84  seam .84  (3,4)
  { -0.155788497f,  1.112217115f, 3.050113f,  0.484003f },  // |L|21.12  seam .90  (2,3)
  {  0.384063957f,  0.666805123f, 3.175282f,  0.780862f },  // |L|23.93  seam .88  (2,4)
  {  0.465211693f,  0.384107930f, 3.267340f,  0.427075f },  // |L|26.25  seam .92  (3,4)
  { -1.290653168f,  0.418007491f, 3.414660f, -1.321236f },  // |L|30.41  seam .94  (3,4)
};

// Where the loop sits. Small, because the self-similarity is asymptotic and a
// wide view reaches past it - see the header.
#define MD_BASE 0.0015f

struct MdState {
  uint8_t  mode;
  uint32_t tZoom;                   // zoom phase, Q16; wraps once per loop
  uint8_t  surge;                   // beat envelope
  uint8_t  clk[2];
  float    lo;                      // the glow's lower edge in L, auto-exposed
  float    darkShare;               // last frame's dark fraction of the surface
};

static FX_RET mode_mandel() {
  if (!strip.isMatrix || !SEGMENT.is2D()) { SEGMENT.fill(SEGCOLOR(0)); FX_DONE; }
  const int cols = SEG_W, rows = SEG_H;
  if (cols < 8 || rows < 8) { SEGMENT.fill(SEGCOLOR(0)); FX_DONE; }

  const bool cube = cfx_isCube(cols, rows);
  const int  B    = cube ? (cols / 3) : 1;
  const size_t m  = cfx_litCount(cols, rows, B, cube);

  // Two Q8 shorts per pixel: the projected plane position, which never changes.
  // The locus does not enter here, so moving that slider costs nothing.
  const size_t need = sizeof(MdState) + 4 * m;
  if (!SEGENV.allocateData(need)) { SEGMENT.fill(SEGCOLOR(0)); FX_DONE; }

  MdState *s  = (MdState *)SEGENV.data;
  int16_t *pu = (int16_t *)(s + 1);
  int16_t *pv = pu + m;

  const uint8_t want = (uint8_t)(cube ? 1 : 2);
  if (SEGENV.call == 0 || s->mode != want) {
    s->mode = want;
    s->tZoom = 0; s->surge = 0;
    s->clk[0] = s->clk[1] = 0;
    s->lo = 1.75f; s->darkShare = 0.35f;

    for (int y = 0; y < rows; y++) {
      for (int x = 0; x < cols; x++) {
        if (cube && cfx_gap(x, y, B)) continue;
        const size_t i = (size_t)cfx_cidx(x, y, cols, B, cube);
        float X, Y, Z;
        cfx_pos(x, y, cols, rows, B, cube, X, Y, Z);
        float u, v;
        if (cube) {
          const float L = sqrtf(X * X + Y * Y + Z * Z);
          const float nx = X / L, ny = Y / L, nz = Z / L;
          const float d = 1.0f + nz;
          u = (d > 0.05f) ? nx / d : nx * 20.0f;
          v = (d > 0.05f) ? ny / d : ny * 20.0f;
        } else {
          u = X; v = Y;                              // a panel IS the plane
        }
        // A quarter turn. The set's long axis ran across the net's arms, so
        // the busiest part of the figure sat on the seams and the lid held the
        // quiet interior. Turned, the structure lies along the faces instead.
        pu[i] = (int16_t)(-v * 256.0f);
        pv[i] = (int16_t)( u * 256.0f);
      }
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
  // How fast the trap distance turns into palette. Low is a few broad zones
  // of filigree, high is fine thread.
  const int fil   = 8 + ((int)SEGMENT.custom1 * 46) / 255;
  const int iters = 12 + ((int)cfx_c3full(SEGMENT.custom3) * 52) / 255;

  int loc = ((int)SEGMENT.custom2 * MD_NLOCI) / 256;
  if (loc > MD_NLOCI - 1) loc = MD_NLOCI - 1;
  const float ccx  = pgm_read_float(&MD_LOCI[loc][0]);
  const float ccy  = pgm_read_float(&MD_LOCI[loc][1]);
  const float lnL  = pgm_read_float(&MD_LOCI[loc][2]);
  const float argL = pgm_read_float(&MD_LOCI[loc][3]);
  const float lgL  = lnL * 1.442695f;               // log2|lambda|

  // Advance the phase at a constant OCTAVES PER SECOND, not a constant phase
  // rate. A loop is log2|lambda| octaves long and that varies three-fold across
  // the table, so a fixed phase rate would quietly make Locus a second speed
  // control - the last entry travelling three times harder than the first at
  // the same setting of Zoom.
  {
    const float octPerSec = 0.06f + (float)SEGMENT.speed * (0.75f / 255.0f);
    const float surgeMul  = 1.0f + (float)s->surge * (0.5f / 255.0f);
    const float adv = octPerSec * surgeMul * (float)dt * 0.001f / lgL;
    s->tZoom = (s->tZoom + (uint32_t)(adv * 65536.0f + 0.5f)) & 0xFFFF;
  }
  const float t = (float)s->tZoom * (1.0f / 65536.0f);

  // Centred on the base depth: out by sqrt(|lambda|), in by the same, so every
  // locus averages the same depth however far it travels in one loop.
  const float scale = MD_BASE * expf((0.5f - t) * lnL);
  const float rot   = -argL * t;
  const float co    = cosf(rot) * scale * (1.0f / 256.0f);
  const float si    = sinf(rot) * scale * (1.0f / 256.0f);

  // One rotation per loop: continuous across the wrap, since the trap field
  // returns to itself there (see the header).
  const uint8_t cs = (uint8_t)(((int)(t * 256.0f)) & 255);
  const bool even  = SEGMENT.check2;
  const float bandK = (float)fil * (1.0f / 32.0f);    // contours per unit of L

  // AI: below section was generated by an AI
  // Auto-exposure: move the glow's lower edge so about 35% of the surface is
  // dark. Too dark lowers it (more of the exterior lights), too bright raises it.
  if (!even) {
    s->lo -= (s->darkShare - 0.35f) * 4.0f * (float)dt * 0.001f;
    if (s->lo <  0.0f) s->lo =  0.0f;
    if (s->lo >  6.0f) s->lo =  6.0f;
  }
  const float lo = s->lo;
  int painted = 0, dark = 0;
  // AI: end

  const int   gainI = 40 + ((int)SEGMENT.intensity * 180) / 255;
  const uint8_t drive = cfx_drive(vol, 0.5f, 180);

  // --- paint --------------------------------------------------------------------
  CFX_NET_PREP();
  for (int y = 0; y < rows; y++) {
    CFX_NET_ROW(y);
    for (int x = 0; x < cols; x++) {
      CFX_NET_SKIP(x);
      const size_t i = (size_t)cfx_cidx(x, y, cols, B, cube);

      const float U = (float)pu[i], V = (float)pv[i];
      const float cr = ccx + U * co - V * si;
      const float ci = ccy + U * si + V * co;

      float zr = 0.0f, zi = 0.0f;
      float trap = 1e9f;
      int n = 0;
      for (; n < iters; n++) {
        const float zr2 = zr * zr, zi2 = zi * zi;
        if (zr2 + zi2 > 64.0f) break;
        const float nzr = zr2 - zi2 + cr;
        zi = 2.0f * zr * zi + ci;
        zr = nzr;
        const float a = zr < 0 ? -zr : zr, b = zi < 0 ? -zi : zi;
        const float tt = a < b ? a : b;
        if (tt < trap) trap = tt;
      }

      uint32_t c = 0;
      painted++;
      if (n >= iters) dark++;                         // the interior is black
      if (n < iters) {                                // escaped: the exterior
        const float tv = trap < 1e-5f ? 1e-5f : trap;
        const float L  = -log2f(tv);
        const int idx = (int)(L * (float)fil);
        int b = (gainI * 215) >> 8;
        if (!even) {
          // AI: below section was generated by an AI
          // glow: smoothstep(lo, lo + 4.25, L)^1.5 - the filaments light, the gaps go dark
          float g = (L - lo) * (1.0f / 4.25f);
          g = g < 0.0f ? 0.0f : (g > 1.0f ? 1.0f : g);
          g = g * g * (3.0f - 2.0f * g);
          g = g * g;
          // contour: distance to the nearest band edge, 0..0.5; dark within 0.1
          float fr = L * bandK;
          fr -= floorf(fr);
          float e = (fr < 0.5f ? fr : 1.0f - fr) * 10.0f;
          if (e > 1.0f) e = 1.0f;
          e = e * e * (3.0f - 2.0f * e);
          b = (int)((float)b * g * (0.3f + 0.7f * e));
          // AI: end
        }
        if (b > 0) {
          c = SEGMENT.color_from_palette((uint8_t)(idx + cs), false, true, 0);
          c = mq_scale(c, (uint8_t)b);
        }
        // AI: below section was generated by an AI
        // dark: no channel visibly on
        { const uint8_t r = R(c), g = G(c), bl = B(c);
          if ((r > g ? (r > bl ? r : bl) : (g > bl ? g : bl)) < 24) dark++; }
        // AI: end
      }
      SEGMENT.setPixelColorXY(x, y, mq_scale(c, drive));
    }
  }
  if (painted) s->darkShare = (float)dark / (float)painted;
  FX_DONE;
}

static const char _data_FX_MODE_MANDEL[] PROGMEM =
  "Ace 3-D Mandelbrot@Zoom,Brightness,Filigree,Locus,Detail,Beat surge,Even light,Flat mode;;!;2f;sx=110,ix=200,c1=100,c2=0,c3=18,o1=1,pal=11";


// ---------------------------------------------------------------------------
// Registration - joins the effect bank, which decides whether this effect
// claims one of the device's limited effect slots. See cube_fx_bank.h.
// ---------------------------------------------------------------------------
static CfxBankReg cube_fx_33_mandel_reg(&mode_mandel, _data_FX_MODE_MANDEL);
