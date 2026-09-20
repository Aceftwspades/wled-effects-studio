#include "wled.h"
#include "cube_fx_common.h"
#include "cube_fx_bank.h"

// ===========================================================================
// Ace 3-D Moire - two dot lattices, warped through each other
// ===========================================================================
// Four things stacked, in this order: a polar transform, a vector-field warp,
// two interfering dot grids, and a hue taken from the field itself.
//
// ---------------------------------------------------------------------------
// WHY THE GRIDS ARE BUILT IN 3-D AND NOT IN UV
// ---------------------------------------------------------------------------
// The natural way to write this is to warp a 2-D UV space and draw dots in it.
// On a cube that tears: any UV laid over the net is discontinuous at the folds,
// and a dot grid makes the tear obvious in a way a smooth field would hide.
//
// So every layer here is a function of the 3-D surface point instead, and the
// dots come from sampling a 3-D lattice. That is not a compromise - it is
// better than a UV, because each face of a cube is a PLANE, and a plane
// cutting a periodic 3-D lattice gives a perfectly regular 2-D grid. Every
// face gets a true dot grid, all five agree along every fold for free, and the
// grid direction changes across an edge exactly as a real lattice seen round a
// corner would.
//
// The two lattice directions cannot be picked by eye. What matters on a given
// face is the pair of IN-FACE gradients, and both things can go wrong: a
// direction close to the face normal projects to nearly nothing, so its bands
// go constant and the face shows a flat tint; and two directions that project
// nearly parallel give streaks instead of dots. The first pair here was chosen
// to look generic and produced 9 degrees between the band families on the east
// and west walls - clean dots on three faces and smeared lines on two.
//
// The measure that catches both at once is the DETERMINANT of the two in-face
// gradients, which is the area they span: it goes to zero if either shrinks or
// if they align. Searched over the three distinct face planes, the shipped
// pair holds a worst case of 0.576 where the eye-picked one managed 0.087.
//
// ---------------------------------------------------------------------------
// THE FOUR LAYERS
// ---------------------------------------------------------------------------
// POLAR. Cylindrical about the vertical axis, so the origin is the middle of
// the lid: radius takes a non-linear, travelling scaling and angle takes a
// twist that falls off with radius. That is the funnel - it pours into the top
// face, which is the one place on this solid a polar singularity belongs.
//
// VECTOR FIELD. The sample point is then displaced by a curl-shaped field
// built from layered sines - each component driven by the OTHER two axes, at
// two frequencies an octave apart. Superposing harmonics that do not share a
// period is what stops the distortion looking like a repeating ripple.
//
// MOIRE. Two dot lattices, the second a rotation of the first within their own
// plane plus a slight scale detune. Superposed, the eye reads the beat between
// them; the product term adds it to the brightness as well, so where the two
// coincide the surface genuinely brightens instead of merely looking busier.
//
// COLOUR. Hue is the warped coordinate itself, taken modulo the palette - the
// same wrap as mod 2 pi - so it is a continuous rainbow through the field
// rather than a per-dot lookup, and the two lattices can be split apart in hue
// so the layers stay legible where they cross.
//
// ---------------------------------------------------------------------------
// EIGHT-BIT TRIG, ON PURPOSE
// ---------------------------------------------------------------------------
// This evaluates about fifteen sines a pixel. At float precision that is the
// most expensive effect in the folder by a wide margin and buys nothing: the
// output is an 8-bit palette index and a dot either covers a pixel or does
// not. Everything but the one atan2 goes through WLED's own 8-bit tables.
// ===========================================================================

#define MO_TWOPI    6.28318531f

// Sine and cosine of an angle measured in 1/256ths of a turn, as -1..1.
static inline float mo_sin(float turns256) {
  return ((int)sin8_t((uint8_t)(int)turns256) - 128) * (1.0f / 128.0f);
}
static inline float mo_cos(float turns256) {
  return ((int)cos8_t((uint8_t)(int)turns256) - 128) * (1.0f / 128.0f);
}

// One dot lattice: two families of parallel bands crossing, so the peaks are
// isolated blobs. Squared twice, which turns broad humps into dots.
static inline int mo_grid(float pa, float pb) {
  const int ca = (int)cos8_t((uint8_t)(int)pa);
  const int cb = (int)cos8_t((uint8_t)(int)pb);
  int v = (ca * cb) >> 8;
  v = (v * v) >> 8;          // one squaring: dots with a soft edge, not needles
  return v;
}

struct MoState {
  uint8_t  mode;
  uint8_t  clk[2];
  uint8_t  surge;
  uint16_t t1, t2, t3;          // three clocks, deliberately incommensurate
  uint16_t kick;                // phase owed to the clocks but not yet delivered
  uint16_t drift;
};

// Generic lattice directions - not axis-aligned, see the header.
static const float MO_A[3] = { 0.8105f, 0.3137f, -0.4946f };
static const float MO_B[3] = { 0.1142f, 0.7584f,  0.6417f };

static FX_RET mode_moire() {
  if (!strip.isMatrix || !SEGMENT.is2D()) { SEGMENT.fill(SEGCOLOR(0)); FX_DONE; }
  const int cols = SEG_W, rows = SEG_H;
  if (cols < 8 || rows < 8) { SEGMENT.fill(SEGCOLOR(0)); FX_DONE; }

  const bool cube = cfx_isCube(cols, rows);
  const int  B    = cube ? (cols / 3) : 1;

  if (!SEGENV.allocateData(sizeof(MoState))) { SEGMENT.fill(SEGCOLOR(0)); FX_DONE; }
  MoState *s = (MoState *)SEGENV.data;

  const uint8_t want = (uint8_t)(cube ? 1 : 2);
  if (SEGENV.call == 0 || s->mode != want) {
    s->mode = want; s->clk[0] = s->clk[1] = 0;
    s->t1 = 0; s->t2 = 21000; s->t3 = 40000; s->drift = 0; s->surge = 0;
    s->kick = 0;
  }

  uint16_t dt = fx_dt8(s->clk);
  if (dt > 60) dt = 60;

  // --- parameters -----------------------------------------------------------
  const int  fill    = (int)SEGMENT.intensity;
  // Distort is CURVED, cubically. Measured on the real net, the lattice's
  // periodicity - the strength of its strongest off-origin autocorrelation
  // peak - runs 0.77 undistorted, 0.50 at 30, 0.30 at 55, and then flattens
  // out around 0.17 from 80 upward. Past 55 the grid is simply gone and more
  // distortion buys nothing but smear, so on a linear control four fifths of
  // the travel did the same thing and the readable region was a sliver at the
  // bottom. The cube law puts that sliver across the whole lower half and
  // still reaches full smear at the top: mid-slider now lands on 32.
  const int  distort = (((int)SEGMENT.custom1 * (int)SEGMENT.custom1) / 255)
                       * (int)SEGMENT.custom1 / 255;
  const int  scaleI  = (int)SEGMENT.custom2;
  const int  detune  = (int)cfx_c3full(SEGMENT.custom3);
  const bool split   = SEGMENT.check2;

  // --- audio ----------------------------------------------------------------
  um_data_t     *um   = cfx_getAudioData();
  const float    vol  = *(float *)um->u_data[0];
  const uint8_t  beat = SEGMENT.check1 ? fx_lowBeat(um) : 0;
  if (beat > s->surge) s->surge = beat;
  // Fast release - about a quarter of a second. At the old rate the envelope
  // took most of a second to let go, which spreads a kick into a swell: the
  // median frame-to-frame change rose as much as the peak did, and a surge
  // that lifts everything is not a surge.
  { const int f = (int)s->surge - (int)fx_step(24, dt);
    s->surge = (uint8_t)(f < 0 ? 0 : f); }

  // The kick is an offset in phase - gain alone cannot read as a jump however
  // hard it is driven, because it changes how fast the pattern is already
  // moving, not where it is. But DELIVERED instantly it is a cut: the frames
  // between the two states never exist, so the eye gets a discontinuity rather
  // than a lurch and none of the travel is visible.
  //
  // So the offset is owed, not applied. Each frame a third of the outstanding
  // debt is paid off, which lands about 90% of it inside 140 ms - fast enough
  // to still read as a hit, slow enough that four or five frames of the rush
  // actually get drawn. Three different rates so the layers arrive out of step
  // with each other rather than sliding together.
  if (beat) {
    uint32_t k = (uint32_t)s->kick + (uint32_t)beat;
    if (k > 620u) k = 620u;                     // a run of hits cannot pile up
    s->kick = (uint16_t)k;
  }
  if (s->kick) {
    uint32_t give = ((uint32_t)s->kick * (uint32_t)dt) / 70u;
    if (!give) give = 1;                        // never stall on integer truncation
    if (give > s->kick) give = s->kick;
    s->t1 = (uint16_t)(s->t1 + give * 44u);
    s->t2 = (uint16_t)(s->t2 - give * 31u);
    s->t3 = (uint16_t)(s->t3 + give * 57u);
    s->kick = (uint16_t)(s->kick - give);
  }

  // --- three clocks ---------------------------------------------------------
  // Different rates and no common period, which is what keeps the superposition
  // from settling into a visible loop.
  { const uint32_t r = (uint32_t)(4 + (int)SEGMENT.speed) * (uint32_t)dt
                       * (uint32_t)(100 + s->surge) / (23u * 100u);
    s->t1 = (uint16_t)(s->t1 + r);
    s->t2 = (uint16_t)(s->t2 + (r * 7u) / 11u);
    s->t3 = (uint16_t)(s->t3 + (r * 13u) / 29u); }
  s->drift = (uint16_t)(s->drift + ((uint32_t)dt * (uint32_t)SEGMENT.speed) / 70u);

  const float p1 = (float)s->t1 * (256.0f / 65536.0f);
  const float p2 = (float)s->t2 * (256.0f / 65536.0f);
  const float p3 = (float)s->t3 * (256.0f / 65536.0f);

  // EVERY frequency here is in 1/256ths of a turn per unit of surface, because
  // that is what the 8-bit tables take. A face spans two units, so a lattice of
  // N dots across a face needs N*128. The first draft wrote these as if the
  // argument were radians and came out at 39 - about half a period across the
  // whole solid - which drew no dots at all, just a smooth blob.
  const float gScale = 256.0f + (float)scaleI * (768.0f / 255.0f);  // 2..8 per face
  const float warpA  = (float)distort * (0.16f / 255.0f);           // in surface units
  const float twist  = (float)distort * (60.0f / 255.0f);           // 1/256 turns
  const float radA   = (float)distort * (0.22f / 255.0f);
  const float surgeF = 1.0f + (float)s->surge * (0.85f / 255.0f);

  // Second lattice: the first rotated within its own plane, plus a scale
  // detune. Both together are the moire control - angle alone beats too
  // slowly at small offsets, scale alone gives concentric rings rather than
  // the rosettes the interference is supposed to make.
  float a2[3], b2[3];
  // The range is small ON PURPOSE. A moire beat has wavelength about
  // spacing / (2 sin(d/2)), so for the interference to show as structure
  // spanning a face or three - rather than as a second grid sitting on top of
  // the first - d has to stay within a few degrees. At the 42 degrees the
  // first version reached, the beat wavelength collapses to the grid spacing
  // and there is nothing left to see.
  { const float d = (float)detune * (12.0f / 255.0f);      // 1/256 turns, i.e. 0..17 deg
    const float cd = mo_cos(d), sd = mo_sin(d);
    for (int k = 0; k < 3; k++) {
      a2[k] =  MO_A[k] * cd + MO_B[k] * sd;
      b2[k] = -MO_A[k] * sd + MO_B[k] * cd;
    } }
  const float gScale2 = gScale * (1.0f + (float)detune * (0.055f / 255.0f));

  const uint8_t hueOff = (uint8_t)(s->drift >> 8);
  const uint8_t drive  = cfx_drive(vol, 0.5f, 200);
  const int     sep    = split ? 96 : 0;

  // --- paint ----------------------------------------------------------------
  CFX_NET_PREP();
  for (int y = 0; y < rows; y++) {
    CFX_NET_ROW(y);
    for (int x = 0; x < cols; x++) {
      CFX_NET_SKIP(x);

      float X, Y, Z; cfx_pos(x, y, cols, rows, B, cube, X, Y, Z);

      // --- 1. polar transform, about the vertical axis ---------------------
      { const float r  = sqrtf(X * X + Y * Y);
        const float th = cfx_atan2f(Y, X) * (256.0f / MO_TWOPI);   // 1/256 turns
        // The funnel takes the surge too, so a kick twists the whole solid at
        // the same instant the warp field lurches.
        const float rr = r * (1.0f + radA * 3.0f * surgeF * mo_sin(r * 300.0f - p1))
                           + radA * 0.9f * surgeF * mo_sin(Z * 200.0f + p2);
        const float tt = th + twist * surgeF * (1.6f - r)
                            + twist * 0.5f * mo_sin(Z * 150.0f - p3);
        X = rr * mo_cos(tt);
        Y = rr * mo_sin(tt); }

      // --- 2. vector field: layered sines, each axis driven by the others ---
      { const float wx = mo_sin(Y * 118.0f + p1) + 0.5f * mo_sin(Z * 241.0f - p2);
        const float wy = mo_sin(Z * 109.0f + p2) + 0.5f * mo_sin(X * 263.0f - p3);
        const float wz = mo_sin(X * 101.0f + p3) + 0.5f * mo_sin(Y * 229.0f - p1);
        const float A  = warpA * surgeF;
        X += A * wx; Y += A * wy; Z += A * wz; }

      // --- 3. two lattices, and their interference -------------------------
      const float da = X * MO_A[0] + Y * MO_A[1] + Z * MO_A[2];
      const float db = X * MO_B[0] + Y * MO_B[1] + Z * MO_B[2];
      const float ea = X * a2[0]   + Y * a2[1]   + Z * a2[2];
      const float eb = X * b2[0]   + Y * b2[1]   + Z * b2[2];
      const int g1 = mo_grid(da * gScale  + p1, db * gScale  - p2);
      const int g2 = mo_grid(ea * gScale2 - p3, eb * gScale2 + p1);

      int m = (g1 > g2) ? g1 : g2;          // both layers are drawn ...
      m += (g1 * g2) >> 8;                  // ... and coincidence brightens
      if (m > 255) m = 255;

      // --- 4. hue from the field, wrapped ----------------------------------
      const uint8_t idx = (uint8_t)((int)((da + eb) * 44.0f)
                                    + ((g2 > g1) ? sep : 0) + hueOff);

      // Dots cover a small fraction of the surface, so the same Fill number
      // buys far less mean brightness here than in a filled effect. Gained up
      // internally so the default sits mid-slider rather than pinned at the top.
      int lum = (fill * m) / 96;
      if (lum > 255) lum = 255;

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

static const char _data_FX_MODE_MOIRE[] PROGMEM =
  "Ace 3-D Moire@Flow,Fill,Distort,Scale,Detune,Beat surge,Split hue,Flat mode;;!;2f;sx=70,ix=128,c1=128,c2=120,c3=20,o1=1,o2=1,pal=11";


// ---------------------------------------------------------------------------
// Registration - joins the effect bank, which decides whether this effect
// claims one of the device's limited effect slots. See cube_fx_bank.h.
// ---------------------------------------------------------------------------
static CfxBankReg cube_fx_42_moire_reg(&mode_moire, _data_FX_MODE_MOIRE);
