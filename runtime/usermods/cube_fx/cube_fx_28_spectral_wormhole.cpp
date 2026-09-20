#include "wled.h"
#include "cube_fx_common.h"
#include "cube_fx_bank.h"

// ===========================================================================
// 28. ACE 3-D SPECTRAL WORMHOLE
// ===========================================================================
// A spectrum analyser running around the bottom edge of the cube, pouring
// coloured water up the walls, and a swirling soap film on the lid that each
// band shoves at from its own side.
//
// Named for its parentage rather than its appearance. Structurally this is
// Black Hole with the sign of the flow reversed and the spectrum put in charge
// of it: the same polar chart, the same split between an interpolated angular
// pass and a whole-cell radial one, the same palette-normalisation and contrast
// work. Black Hole pulls colour in from the rim and destroys it at the centre;
// this pushes it up from the rim and lets it pile into a film. What it takes
// from Soap is character, not machinery - see below.
//
// NOT to be confused with Ace 2-D Spectral Wormhole, which is a flat-panel
// log-polar spiral and shares nothing with this but a taste in names.
//
// ---------------------------------------------------------------------------
// WHY THIS CHART
// ---------------------------------------------------------------------------
// Colour lives in a polar buffer of ANGLE around the cube by DEPTH from the lid
// centre - the same ruler matrix rain, whirlpool, fire and black hole share,
// which runs over the rim without a special case. Two things fall out of that
// for free, and they are the whole reason this effect is cheap:
//
//   * ANGLE IS THE GEQ AXIS. A spectrum analyser wrapped around a cube is
//     parameterised by position along the perimeter and nothing else, so "which
//     band is this pixel under" is not a lookup, it is the coordinate.
//
//   * DEPTH IS THE PUSH AXIS. Decreasing depth runs from the bottom edge of the
//     walls, up, over the rim and into the middle of the lid - exactly the path
//     a band's pulse should travel. Nothing has to be stitched at the fold
//     because the ruler was built not to have one.
//
// Soap's own chart (3-D surface positions plus a reverse table) is a better fit
// for isotropic flow over the whole solid, but it would cost a second copy of
// that machinery for no gain here, and the flash budget on an ESP32 has no room
// for sentiment about it.
//
// ---------------------------------------------------------------------------
// WHAT IS BORROWED FROM SOAP
// ---------------------------------------------------------------------------
// The character, which is three specific things and not the coordinate system:
//
//   curl noise      velocity as the curl of a scalar potential rather than
//                   independent noise per axis. Independent channels give a
//                   field with sources and sinks - colour pools and drains and
//                   the motion reads as blobby drift. A curl cannot diverge, so
//                   it can only ever fold and shear the colour around.
//   eased weights   the bilinear taps go through a smoothstep, because raw
//                   bilinear is a mixer and anything stirred by a mixer goes
//                   uniform in seconds.
//   contrast out    push the tones back apart on the way to the panel, since
//                   transport plus interpolation eats the extremes first and
//                   the extremes are what readability is made of.
//
// ---------------------------------------------------------------------------
// ROTATION IS CONFINED TO THE LID, ON PURPOSE
// ---------------------------------------------------------------------------
// The swirl ramps from nothing at the rim to full speed at the lid centre. If
// the walls rotated too, the bars would smear sideways and stop reading as a
// spectrum - the one thing this effect must not lose. So the walls carry only
// the vertical push and the curl's wobble, which keeps the bars upright and
// legible, and everything that spills over the rim lands in a film that is
// turning. The shear between the two IS the swirl.
//
// ---------------------------------------------------------------------------
// TWO WAYS TO WRAP SIXTEEN BANDS AROUND FOUR WALLS
// ---------------------------------------------------------------------------
// Mirrored off - WRAPPED. The sixteen bands run once around the whole
// perimeter, four angular cells each on a 16-px face. Every band appears once.
// Bass and treble end up adjacent at the single seam where the run closes.
//
// Mirrored on - MIRRORED. Every wall carries the whole spectrum, and alternate
// walls run backwards, so the spectrum reflects at each corner: bass meets bass
// at two opposite corners and treble meets treble at the other two. Each band
// then appears four times and pushes from four places at once, and the paired
// corners get double the shove - a bass hit drives two opposing jets straight
// at each other under the lid.
//
//   bands   each band's colour, how bright its water enters, and how fast it
//           climbs - which together are what you read as its height
//   beat    a flare of brightness and a harder shove
//   volume  overall level, in a narrow band so it never washes out
//
// The band levels are AUTO-RANGED against a slow-release peak, so the loudest
// band of the moment always drives the film whatever the source level is.
//
// WITH NO AUDIO it turns on its own clock.
// ===========================================================================

#define SW_Q      8                   // fixed point for the backward trace
#define SW_MAXCOL 254                 // 255 marks "not on the board" in col[]
#define SW_GRAD   10                  // finite-difference step for grad(psi)
#define SW_BANDS  16                  // GEQ channels, one per FFT bin

struct SwState {
  uint8_t  mode;
  uint16_t ang, rad;
  uint16_t spin;                      // lid rotation phase
  uint16_t drift;                     // noise field drift
  uint8_t  beatEnv;
  uint8_t  peak;                      // slow-release peak, for auto-ranging
  uint16_t fAccW, fAccL;              // sub-count fade carry, wall and lid
  uint8_t  spec[SW_BANDS];            // smoothed spectrum, fast attack
  uint8_t  clk[2];
};

static int sw_edge(int t, int den, int B) {
  int idx = ((t + den) * B) / (2 * den);
  if (idx < 0)     idx = 0;
  if (idx > B - 1) idx = B - 1;
  return idx;
}

// Which band is at this angular cell.
//
// `seg` is one wall's worth of angular cells, so this works unchanged on the
// flat panel, where there are no walls but the perimeter still divides into
// four equal runs.
static inline int sw_band(int a, int seg, bool mirrored) {
  if (!mirrored) return (a * SW_BANDS) / (seg * 4);      // once around
  const int face = a / seg, lx = a - face * seg;
  const int b = (lx * SW_BANDS) / seg;
  return (face & 1) ? (SW_BANDS - 1 - b) : b;            // reflect on odd walls
}

// Angle + depth for every lit pixel. Chebyshev on the lid so its edge sits at
// exactly topd all the way round and meets the top of the walls without a step.
static void sw_buildMap(uint8_t *col, uint8_t *dep, int cols, int rows,
                        bool cube, int B, int topd) {
  for (int y = 0; y < rows; y++) {
    for (int x = 0; x < cols; x++) {
      if (cube && cfx_gap(x, y, B)) continue;      // gap: no slot
      const size_t i = (size_t)cfx_cidx(x, y, cols, B, cube);

      if (!cube) {                                            // flat: honest polar
        const float dx = (float)x - (cols - 1) * 0.5f;
        const float dy = (float)y - (rows - 1) * 0.5f;
        const int a = (int)(atan2f(dy, dx) * (128.0f / 3.14159265f) + 256.5f);
        col[i] = (uint8_t)(a & 0xFF);
        const int rmax = ((cols < rows) ? cols : rows) / 2;
        const int r = (int)sqrtf(dx * dx + dy * dy);
        dep[i] = (uint8_t)((r > rmax) ? rmax : r);
        continue;
      }

      const int bx = x / B, by = y / B, lx = x % B, ly = y % B;

      if (bx == 1 && by == 1) {                               // LID: radial
        const int ax = 2 * lx - (B - 1), ay = 2 * ly - (B - 1);
        const int aax = (ax < 0) ? -ax : ax, aay = (ay < 0) ? -ay : ay;
        const int r2  = (aax > aay) ? aax : aay;
        dep[i] = (uint8_t)(r2 >> 1);
        if (r2 == 0) { col[i] = 0; continue; }
        int c;
        if (aay > aax) {
          const int idx = sw_edge(ax, aay, B);
          c = (ay < 0) ? idx : (2 * B + (B - 1 - idx));
        } else if (aax > aay) {
          const int idx = sw_edge(ay, aax, B);
          c = (ax > 0) ? (B + idx) : (3 * B + (B - 1 - idx));
        } else {
          c = (ay < 0) ? ((ax < 0) ? 0 : B) : ((ax > 0) ? (2 * B) : (3 * B));
        }
        col[i] = (uint8_t)c;
        continue;
      }

      int bu, bv;                                             // walls
      if      (by == 0) { bu = lx;                 bv = B - 1 - ly; }
      else if (bx == 2) { bu = B + ly;             bv = lx;         }
      else if (by == 2) { bu = 2 * B + B - 1 - lx; bv = ly;         }
      else              { bu = 3 * B + B - 1 - ly; bv = B - 1 - lx; }
      col[i] = (uint8_t)bu;
      dep[i] = (uint8_t)(topd + bv);                // bv = 0 at the rim
    }
  }
}

// Bilinear read of the polar buffer. Angle wraps - it is a ring - depth clamps.
static inline void sw_sample(const uint8_t *f, int ang, int rad,
                             int32_t aQ, int32_t rQ, uint8_t *out) {
  int a0 = (int)(aQ >> SW_Q), r0 = (int)(rQ >> SW_Q);
  const uint8_t fa = ease8InOutCubic((uint8_t)(aQ & 255));
  const uint8_t fr = ease8InOutCubic((uint8_t)(rQ & 255));
  int a1 = a0 + 1, r1 = r0 + 1;
  a0 %= ang; if (a0 < 0) a0 += ang;
  a1 %= ang; if (a1 < 0) a1 += ang;
  if (r0 < 0) r0 = 0; else if (r0 > rad - 1) r0 = rad - 1;
  if (r1 < 0) r1 = 0; else if (r1 > rad - 1) r1 = rad - 1;

  const size_t i00 = ((size_t)r0 * ang + a0) * 3, i10 = ((size_t)r0 * ang + a1) * 3;
  const size_t i01 = ((size_t)r1 * ang + a0) * 3, i11 = ((size_t)r1 * ang + a1) * 3;
  for (int c = 0; c < 3; c++) {
    const int t0 = (int)f[i00 + c] + (((int)f[i10 + c] - (int)f[i00 + c]) * (int)fa) / 255;
    const int t1 = (int)f[i01 + c] + (((int)f[i11 + c] - (int)f[i01 + c]) * (int)fa) / 255;
    out[c] = (uint8_t)(t0 + ((t1 - t0) * (int)fr) / 255);
  }
}

// Push the tones back apart on the way out. One smoothstep, not Soap's two:
// this field is fed continuously at full level and has a short transit, so a
// single pass is enough. Black Hole is the cautionary tale in the other
// direction - a dimmer field put through two passes lost most of itself.
static inline uint8_t sw_contrast(uint8_t v) {
  return ease8InOutCubic(v);
}

// The colour for one band, at a brightness the eye can actually compare across
// the spectrum.
//
// A GEQ has a hard requirement that a decorative effect does not: every band
// has to be READABLE, because a bar you cannot see reads as a silent band. The
// palette does not care about that. Brightness is nowhere near linear in the
// channels - a fully saturated blue tops out at luma 19 while a yellow reaches
// 236 - so handing sixteen evenly spaced palette entries straight to the panel
// gives sixteen bars covering a twelvefold range of apparent brightness that
// has nothing whatever to do with the music. Measured on a flat spectrum, the
// wall showed a smooth hump peaking in the middle and nothing at all at either
// end: the shape of the palette's luminance, masquerading as a reading.
//
// So: normalise the chroma to full level, then lift toward white only as far as
// it takes to reach a common luma. Yellow is already past the target and is
// left alone; blue comes up to meet it and stays obviously blue. Hue still
// identifies the band, but no longer decides whether it is visible.
static inline uint32_t sw_bandColor(uint32_t pc, int target) {
  int r = (int)((pc >> 16) & 0xFF), g = (int)((pc >> 8) & 0xFF), b = (int)(pc & 0xFF);
  int mx = r > g ? r : g; if (b > mx) mx = b;
  // A black palette entry would render a loud band as a silent one, which is
  // the one lie this effect must not tell. Fall back to grey at the target
  // level: the band loses its hue but keeps its voice.
  if (mx < 8) return RGBW32(target, target, target, 0);
  r = (r * 255) / mx; g = (g * 255) / mx; b = (b * 255) / mx;
  const int L = (r * 54 + g * 183 + b * 19) >> 8;
  if (L < target && L < 255) {
    const int w = ((target - L) * 255) / (255 - L);   // 0..255 toward white
    r += ((255 - r) * w) / 255;
    g += ((255 - g) * w) / 255;
    b += ((255 - b) * w) / 255;
  }
  return RGBW32(r, g, b, 0);
}

static FX_RET mode_spectral_wormhole() {
  if (!strip.isMatrix || !SEGMENT.is2D()) { SEGMENT.fill(SEGCOLOR(0)); FX_DONE; }
  const int cols = SEG_W, rows = SEG_H;
  if (cols < 8 || rows < 8) { SEGMENT.fill(SEGCOLOR(0)); FX_DONE; }

  const bool cubeRaw = cfx_isCube(cols, rows);
  const int  B       = cubeRaw ? (cols / 3) : 1;
  const bool cube    = cubeRaw && (4 * B) <= SW_MAXCOL;

  const int ang  = cube ? (4 * B) : 256;
  const int topd = cube ? ((B + 1) / 2) : 0;
  const int rad  = cube ? (topd + B) : (((cols < rows) ? cols : rows) / 2 + 1);
  if (rad < 6 || ang < 8) { SEGMENT.fill(SEGCOLOR(0)); FX_DONE; }
  const int seg  = ang >> 2;                    // one wall's worth of angle

  const size_t m     = cfx_litCount(cols, rows, B, cube);
  const size_t cells = (size_t)ang * rad;
  const size_t need  = sizeof(SwState) + 2 * m + 3 * (size_t)ang + 6 * cells
                     + cells * sizeof(uint16_t);
  if (!SEGENV.allocateData(need)) { SEGMENT.fill(SEGCOLOR(0)); FX_DONE; }

  SwState *s   = (SwState *)SEGENV.data;
  uint8_t *col = (uint8_t *)(s + 1);
  uint8_t *dep = col + m;
  int8_t  *ct  = (int8_t *)(dep + m);           // cos/sin of each angular cell,
  int8_t  *st  = ct + ang;                      // so the noise can wrap
  uint8_t *lvl = (uint8_t *)(st + ang);         // band level per angular cell
  uint8_t *dye = lvl + ang;
  uint8_t *tmp = dye + 3 * cells;
  uint16_t *accum = (uint16_t *)(tmp + 3 * cells);   // sub-cell climb, per cell

  const uint8_t want = (uint8_t)(cube ? 1 : 2);
  if (SEGENV.call == 0 || s->mode != want || s->ang != (uint16_t)ang) {
    sw_buildMap(col, dep, cols, rows, cube, B, topd);
    for (int a = 0; a < ang; a++) {
      const uint8_t th = (uint8_t)((a * 256) / ang);
      int c = (int)cos8_t(th) - 128, v = (int)sin8_t(th) - 128;
      ct[a] = (int8_t)(c < -127 ? -127 : c);
      st[a] = (int8_t)(v < -127 ? -127 : v);
    }
    s->mode = want; s->ang = (uint16_t)ang; s->rad = (uint16_t)rad;
    s->spin = 0; s->drift = 0; s->beatEnv = 0; s->peak = 0;
    s->fAccW = 0; s->fAccL = 0;
    memset(s->spec, 0, SW_BANDS);
    memset(s->clk, 0, sizeof(s->clk));
    memset(dye, 0, 3 * cells);
    memset(lvl, 0, ang);
    memset(accum, 0, cells * sizeof(uint16_t));
  }

  uint16_t dt = fx_dt8(s->clk);
  if (dt > 60) dt = 60;

  // --- audio ------------------------------------------------------------------
  um_data_t     *um   = cfx_getAudioData();
  const uint8_t *fft  = (uint8_t *)um->u_data[2];
  const float    vol  = *(float *)um->u_data[0];
  const uint8_t  beat = SEGMENT.check2 ? fx_lowBeat(um) : 0;

  // Fast attack, slow release - a bar must jump on the transient and sag back,
  // which is the whole visual grammar of a spectrum analyser.
  cfx_smoothSpec(s->spec, fft, 3);
  if (beat > s->beatEnv) s->beatEnv = beat;
  { const int f = (int)s->beatEnv - (int)fx_step(9, dt);
    s->beatEnv = (uint8_t)((f < 0) ? 0 : f); }

  const bool mirrored = SEGMENT.check1;

  // --- band level per angular cell ---------------------------------------------
  // Hard band edges, then one circular 3-tap smoothing pass. The hard edges are
  // what make the BARS read as bars; the smoothing is only so the velocity field
  // does not have a cliff at every band boundary, which shows up as a crease in
  // the water that has nothing to do with the music.
  // Auto-range against a slow-release peak, the way a spectrum analyser does.
  // Without it the display is at the mercy of however hot the source happens to
  // be: a perfectly ordinary spectrum topping out around 130 of 255 left every
  // band short of the rim, so nothing ever crossed onto the lid and the film it
  // is supposed to feed stayed black. Fast attack keeps a transient honest,
  // slow release means the scale does not pump on every beat, and the floor
  // stops silence from amplifying its own noise into a light show.
  {
    int mx = 0;
    for (int i = 0; i < SW_BANDS; i++) if (s->spec[i] > mx) mx = s->spec[i];
    if (mx > s->peak) s->peak = (uint8_t)mx;
    else { const int d = (int)s->peak - (int)fx_step(1, dt);
           s->peak = (uint8_t)((d < 0) ? 0 : d); }
  }
  const int pk = (s->peak < 40) ? 40 : (int)s->peak;

  {
    for (int a = 0; a < ang; a++) {
      const int v = ((int)s->spec[sw_band(a, seg, mirrored)] * 255) / pk;
      lvl[a] = (uint8_t)(v > 255 ? 255 : v);
    }
    uint8_t prev = lvl[ang - 1], first = lvl[0];
    for (int a = 0; a < ang; a++) {
      const uint8_t nxt = (a + 1 < ang) ? lvl[a + 1] : first;
      const uint8_t cur = lvl[a];
      lvl[a] = (uint8_t)(((int)prev + 2 * (int)cur + (int)nxt) >> 2);
      prev = cur;
    }
  }

  // --- rates --------------------------------------------------------------------
  // The lid only has topd rings to shear across - eight on a 16-px face - so
  // the rotation has to be brisk for the film to fold rather than merely drift
  // round as one plate. At the old scale the lid measured a spatial sigma of 20
  // against Soap's 46 and read as a converging fan of colour, which is the
  // arriving water made visible rather than a film with a life of its own.
  const int32_t w0    = (((int32_t)SEGMENT.speed * 620) / 255 + 70) * (int32_t)dt / 23;
  // Push is now a RATE - how fast water rises toward its band's level - rather
  // than a thing that also decides how far it gets. It sets response time: at
  // the default a loud band crosses the wall in about half a second.
  const int32_t pushG = ((int32_t)SEGMENT.intensity * 260) / 255 + 60;
  const int32_t curlG = (int32_t)SEGMENT.custom1;
  const int     sc    = 2 + ((int)cfx_c3full(SEGMENT.custom3) * 12) / 255;
  // Fade is carried in 1/256ths of a count per frame. The entire useful range
  // of this control lies between one and four counts a frame - above four the
  // water is gone before it clears the wall, below one it never leaves - and a
  // whole-number fade squeezes all of that into the top fifth of the slider,
  // where two thirds of the travel does nothing at all. The carry below spends
  // a fractional rate as a whole subtraction every few frames instead.
  // Scaled to the geometry. What the fade actually costs a parcel is its rate
  // times the TIME it spends crossing, so a smaller cube - fewer rings, shorter
  // trip - loses proportionally less at the same setting and floods. An 8-px
  // cube measured 3% black against the 16-px cube's 20% on identical settings.
  // Normalising to the 16-px radius makes one Trail setting mean the same thing
  // on every size.
  const int32_t fadeQ = (40 + ((255 - (int32_t)SEGMENT.custom2) * 8))
                        * 24 / (rad > 4 ? rad : 4);

  s->spin  = (uint16_t)(s->spin  + fx_step(3, dt));
  s->drift = (uint16_t)(s->drift + fx_step(2, dt));
  const uint16_t oz = s->drift;

  // The lid turns, the walls do not. swirlR is where the rotation dies out: the
  // rim on a cube, and the whole radius on a flat panel, which has no rim.
  const int swirlR = cube ? (topd > 0 ? topd : 1) : rad;

  // --- transport ------------------------------------------------------------------
  for (int r = 0; r < rad; r++) {
    // Differential rotation. Fastest in the middle of the lid, zero by the rim,
    // so the film shears against itself instead of turning as one plate.
    int32_t om = 0;
    if (r < swirlR) om = (w0 * (int32_t)(swirlR - r)) / swirlR;
    if (om > 700) om = 700;

    for (int a = 0; a < ang; a++) {
      // Curl of a scalar potential. psi is sampled on a CIRCLE embedded in the
      // noise rather than on the (angle, depth) rectangle directly - a
      // rectangle has a seam where the angle wraps, and a crease would sit
      // there forever. Going round a circle in the field closes on itself.
      const int px  = (r * (int)ct[a]) >> 4, py = (r * (int)st[a]) >> 4;
      const int a1  = (a + 1 < ang) ? a + 1 : 0;
      const int px1 = (r * (int)ct[a1]) >> 4, py1 = (r * (int)st[a1]) >> 4;
      const int r1  = r + 1;
      const int px2 = (r1 * (int)ct[a]) >> 4, py2 = (r1 * (int)st[a]) >> 4;

      const int p0 = (int)perlin8((uint16_t)(px  * sc + 8192), (uint16_t)(py  * sc + 8192), oz);
      const int pa = (int)perlin8((uint16_t)(px1 * sc + 8192), (uint16_t)(py1 * sc + 8192), oz);
      const int pr = (int)perlin8((uint16_t)(px2 * sc + 8192), (uint16_t)(py2 * sc + 8192), oz);

      // ANGULAR only. dpsi/dr varying with position is a shear, and shearing a
      // ring against its neighbours is what folds colour - it is the mechanism
      // Soap's swirl is actually made of. Confining the noise to one axis also
      // makes it exactly conservative for free: sliding cells around a ring
      // cannot create or destroy anything, whatever the profile looks like.
      // The curl is confined to the lid for exactly the reason the rotation is,
      // and it turned out to matter far more. A bar is a narrow bright column
      // standing next to columns that are EMPTY at the same height, so any
      // sideways blending bleeds it into that dark space - and a two-tap
      // interpolation running every frame is sideways blending. Measured, a
      // column lost about twelve counts per cell climbed against a fade of two:
      // the fade was never what was eating the bars, the swirl was. The walls
      // keep a sixth of it as a shimmer, enough to stop them looking like a
      // drawn bar chart, and the film above gets the whole thing.
      const int32_t curlHere = (r < swirlR)
          ? (curlG / 6 + (curlG * 5 * (int32_t)(swirlR - r)) / (6 * swirlR))
          : (curlG / 6);
      int32_t va = om + ((int32_t)(pr - p0) * curlHere) / 96;
      if (va > 900) va = 900; else if (va < -900) va = -900;

      // Radius is sampled EXACTLY, so fr eases to zero and no radial blending
      // happens in this pass at all. The climb is a separate pass below.
      uint8_t px3[3];
      sw_sample(dye, ang, rad, ((int32_t)a << SW_Q) - va, (int32_t)r << SW_Q, px3);
      const size_t o = ((size_t)r * ang + a) * 3;
      tmp[o + 0] = px3[0]; tmp[o + 1] = px3[1]; tmp[o + 2] = px3[2];
    }
  }
  memcpy(dye, tmp, 3 * cells);

  // --- the climb, in WHOLE cells --------------------------------------------------
  // The band pushes INWARD - always. An earlier version made this zero-mean,
  // pushing in where a band beat the spectrum average and out where it did not,
  // to stop colour piling up in the middle of the lid. That was guarding
  // against something that cannot happen: advection ASSIGNS each cell one
  // sampled value rather than adding to it, so a passive colour field cannot
  // accumulate however convergent the flow gets. What zero-mean forcing did do
  // was guarantee the average parcel never moved, so nothing climbed and the
  // whole effect rendered black.
  //
  // The climb is not interpolated, and that is not an optimisation - it is the
  // only way this works. A bilinear step with eased weights, which is right for
  // the shear above, is fatal here: easing squashes a small fractional shift
  // toward zero, so a slow band's water barely advances while the fade keeps
  // taking its cut, and in steady state each cell loses fade/weight of its
  // neighbour's brightness - tens of counts per cell once the weight drops
  // under a tenth. The bars died a third of the way up the wall no matter how
  // hard the push was turned up, because the harder push never actually moved
  // anything. An accumulator per cell instead: nothing moves until a whole cell
  // is earned, and then the cell is COPIED. A copy loses nothing, so a parcel's
  // brightness now falls only by the fade over the TIME it takes to climb,
  // which is what makes bar height mean something.
  //
  // Inner to outer, so each cell reads its neighbour before that neighbour is
  // itself overwritten - one cell of travel per step, cleanly.
  // The water flows all the way through - bottom edge, up the wall, over the
  // rim, into the film - and the band sets how FAST and how BRIGHT its own
  // column moves, not how far it gets.
  //
  // A version of this gated the climb at a water line proportional to the band,
  // so each wall read as a literal bar chart. It made a crisper spectrum and it
  // was the wrong thing: a band only crossed the rim on the frames it happened
  // to be the loudest in the mix, so the film was fed in occasional flickers
  // and measured black better than nine tenths of the time. The lid is supposed
  // to be a body of water that the spectrum leans on, which requires it to be
  // continuously supplied. Strength reads through brightness and through how
  // fast a streak travels, and the walls still show the spectrum plainly.
  {
    const int32_t dtn = (int32_t)dt;
    for (int a = 0; a < ang; a++) {
      // A floor under the speed matters as much as the gain over it. With none,
      // a quiet band's water does not merely rise slowly, it parks - and then
      // the fade takes it where it stands, leaving a permanently dead stripe up
      // that part of the wall.
      int32_t vr = (30 + ((int32_t)lvl[a] * pushG) / 255) * dtn / 23;
      if (vr > 1024) vr = 1024;
      for (int r = 0; r + 1 < rad; r++) {
        const size_t ci = (size_t)r * ang + a;
        uint32_t acc = (uint32_t)accum[ci] + (uint32_t)vr;
        while (acc >= 256 && r + 1 < rad) {
          uint8_t *d = dye + ci * 3, *sN = dye + ((size_t)(r + 1) * ang + a) * 3;
          d[0] = sN[0]; d[1] = sN[1]; d[2] = sN[2];
          acc -= 256;
        }
        accum[ci] = (uint16_t)(acc > 255 ? 255 : acc);
      }
    }
  }

  // --- the bars ---------------------------------------------------------------------
  // New water enters along the bottom edge only. Colour is the band's place in
  // the spectrum, brightness is its level, so the outermost ring alone already
  // reads as a spectrum analyser; everything above it is that same water after
  // the flow has had its way with it.
  {
    const uint8_t flare = s->beatEnv;
    for (int k = 0; k < 2 && k < rad; k++) {
      const int rOut = rad - 1 - k;
      for (int a = 0; a < ang; a++) {
        const int bnd = sw_band(a, seg, mirrored);

        // Brightness is the spectrum's main voice, so it gets most of the
        // range. Handing the RAW band level straight to brightness is the
        // obvious move and is wrong: a typical bin sits near 50 of 255, so
        // every bar entered at a fifth of full and the contrast curve then
        // crushed that to a fifteenth - the effect rendered black. But the
        // opposite, a near-constant 150 to 255, is barely a spectrum at all:
        // loud and quiet bands came out within a factor of 1.7 of each other
        // and the walls read as four smooth colour gradients. The level being
        // AUTO-RANGED is what makes a wide span safe here - the loudest band of
        // the moment always reaches the top of it, whatever the source level.
        // 100 is where the two failures meet. At 150 the bands were within a
        // factor of 1.7 and the walls read as four smooth gradients; at 55 the
        // spectrum was plain but the mean fell from 45 to 19 and the lid went
        // dark, because auto-ranging pins only the LOUDEST band at the top and
        // most of the rest sit well down the scale.
        const int amp = 100 + ((int)lvl[a] * 155) / 255 + (flare / 3);
        const uint8_t pb = (uint8_t)(amp > 255 ? 255 : amp);

        // Palette by band, level by amplitude - the same split Black Hole
        // needed: hue that survives being averaged, and structure carried as
        // brightness because brightness is the thing that stays legible when
        // two neighbours get mixed.
        // Bands are spread across an INSET slice of the palette, 20..235
        // rather than 0..255. A great many WLED palettes are black at one or
        // both endpoints, and mapping the end bands there put bass and top
        // treble - the two you most want to see - on the two entries most
        // likely to be unlit.
        uint32_t pc = sw_bandColor(
            SEGMENT.color_from_palette((uint8_t)(20 + (bnd * 215) / (SW_BANDS - 1)),
                                       false, true, 0), 120);
        pc = mq_scale(pc, pb);

        // Crossfade toward the new value rather than taking the brighter of the
        // two. Max-combining is a ratchet - a cell can only ever get brighter,
        // never change colour, so within seconds the feed ring saturates and
        // pumps one constant upward forever.
        const uint8_t mixIn = (uint8_t)(150 + (k ? 0 : 60) + (flare >> 3));
        const size_t o = ((size_t)rOut * ang + a) * 3;
        const uint8_t src[3] = { (uint8_t)((pc >> 16) & 0xFF),
                                 (uint8_t)((pc >>  8) & 0xFF),
                                 (uint8_t)( pc        & 0xFF) };
        for (int ch = 0; ch < 3; ch++)
          dye[o + ch] = (uint8_t)(((int)dye[o + ch] * (255 - mixIn)
                                 + (int)src[ch] * mixIn + 127) / 255);
      }
    }
  }

  // Water is poured in every frame, so there has to be a drain.
  //
  // The walls and the lid want opposite things from it, so they do not get the
  // same one. On the WALLS the fade is the thing that stops a bar: a parcel
  // lives 255/fade frames, travels at a speed its band chose, and dies where
  // those two meet - that IS the bar height, and it has to bite hard enough
  // that a quiet band's water visibly falls short of the rim. On the LID the
  // same fade would leave nothing but a smear of whatever crossed the rim in
  // the last half second, when what is wanted there is a body of water that
  // persists, turns, and gets shoved about by whichever band is loud. So the
  // lid fades at a third of the rate and holds a film.
  {
    const int32_t stepQ = fadeQ * dt / 23;
    s->fAccW = (uint16_t)(s->fAccW + stepQ);
    s->fAccL = (uint16_t)(s->fAccL + stepQ / 3);
    const uint8_t fWall = (uint8_t)(s->fAccW >> 8); s->fAccW &= 255;
    const uint8_t fLid  = (uint8_t)(s->fAccL >> 8); s->fAccL &= 255;
    const int lidTop = cube ? topd : (rad / 2);
    for (int r = 0; r < rad; r++) {
      const uint8_t f = (r < lidTop) ? fLid : fWall;
      if (!f) continue;
      uint8_t *p = dye + (size_t)r * ang * 3;
      for (size_t i = 0; i < (size_t)ang * 3; i++)
        p[i] = (p[i] > f) ? (uint8_t)(p[i] - f) : 0;
    }
  }

  // --- render ---------------------------------------------------------------------
  const uint8_t drive = cfx_drive(vol, 0.35f, 118);

  CFX_NET_PREP();
  size_t idx = 0;
  for (int y = 0; y < rows; y++) {
    CFX_NET_ROW(y);
    for (int x = 0; x < cols; x++, idx++) {
      CFX_NET_SKIP(x);
      const size_t i = (size_t)cfx_cidx(x, y, cols, B, cube);
      const int u = col[i];
      if (cube && u == 255) { SEGMENT.setPixelColorXY(x, y, 0); continue; }
      int d = dep[i]; if (d > rad - 1) d = rad - 1;
      const int a = cube ? u : ((u * ang) >> 8);
      const size_t o = ((size_t)d * ang + (a % ang)) * 3;

      SEGMENT.setPixelColorXY(x, y,
        mq_scale(RGBW32(sw_contrast(dye[o]),
                        sw_contrast(dye[o + 1]),
                        sw_contrast(dye[o + 2]), 0), drive));
    }
  }
  FX_DONE;
}

static const char _data_FX_MODE_SPECTRAL_WORMHOLE[] PROGMEM =
  "Ace 3-D Spectral Wormhole@Swirl speed,Push,Curl,Trail,Scale,Mirrored,Beat flare,Flat mode;;!;2f;sx=130,ix=150,c1=140,c2=225,c3=15,o1=1,o2=1,pal=11";


// ---------------------------------------------------------------------------
// Registration - joins the effect bank, which decides whether this effect
// claims one of the device's limited effect slots. See cube_fx_bank.h.
// ---------------------------------------------------------------------------
static CfxBankReg cube_fx_28_spectral_wormhole_reg(&mode_spectral_wormhole,
                                               _data_FX_MODE_SPECTRAL_WORMHOLE);
