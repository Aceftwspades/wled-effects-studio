#include "wled.h"
#include "cube_fx_common.h"
#include "cube_fx_bank.h"

// ===========================================================================
// 27. ACE 3-D BLACK HOLE
// ===========================================================================
// A dark void at the middle of the lid, colour spiralling inward around it and
// vanishing at the edge, and one thin bright arc riding just outside the void.
//
// ---------------------------------------------------------------------------
// WHAT IT BORROWS, AND FROM WHERE
// ---------------------------------------------------------------------------
// The TRANSPORT is Soap's: colour lives in a buffer and is only ever moved, so
// it stretches and folds like a substance rather than reading as a pattern
// being played. Soap's two hard-won lessons come along with it - sample between
// cells and ease the blend weights (raw bilinear is a mixer, and anything that
// stirs goes uniform), and keep fresh colour arriving fast enough to outrun
// that mixing.
//
// The POLAR framing is what Octopus is usually credited with, but Octopus does
// not work like this at all: it builds an angle/radius map once and then
// RECOMPUTES every pixel from a closed-form sine expression each frame, with no
// buffer and no transport. Only the map idea is useful, and this folder already
// has a better version of it - the same lid-centre-to-wall-bottom ruler that
// matrix rain, whirlpool and fire share, which runs over the rim without a
// special case.
//
// ---------------------------------------------------------------------------
// WHY THE FLOW GOES THE OTHER WAY
// ---------------------------------------------------------------------------
// Whirlpool pushes dye OUT from an eye. This pulls it IN and destroys it, which
// changes the character completely:
//
//   * Rotation steepens toward the middle, so the inner disc laps the outer one
//     many times over and shears colour into ever-tighter spirals. Nothing
//     draws a spiral; differential rotation is the spiral.
//   * Everything inside the horizon radius is erased every frame. That is the
//     void, and it is a true hole rather than a dark patch painted on.
//   * Because colour is created at the rim and consumed at the centre, the
//     field is a THROUGH-flow. It cannot homogenise the way a closed surface
//     does - the mixed-up material is continually swallowed and replaced.
//
// ---------------------------------------------------------------------------
// THE THIN ARC
// ---------------------------------------------------------------------------
// A one-cell ring just outside the horizon, drawn additively over the disc. It
// is deliberately not uniform: real images of these things are far brighter on
// the side rotating toward the viewer, so the ring's brightness is modulated
// once around its circumference. That is what makes it read as one arc curving
// around the void rather than as a drawn circle.
//
// ---------------------------------------------------------------------------
// KEEPING IT LEGIBLE
// ---------------------------------------------------------------------------
// Everything here is injected at the rim and then rotated for its whole journey
// inward, and every rotation is a two-tap interpolation. Nothing adds detail
// after birth, so the disc is under a low-pass filter running hundreds of times
// over material that can only lose information. Left alone it collapses into a
// flat mid-tone band - measured, it sat between luma 16 and 63 with no black
// outside the void and no highlights anywhere, at a mean of 35 against 43-61
// for the effects worth standing next to.
//
// Four things hold it open, and each fixes a different failure:
//
//   Glow          feeds the rim at full level instead of a hardcoded 59%.
//   arm profile   a plain sine with real range, 6 arms rather than 3 - three
//                 arms over a 64-cell circumference are 21 cells wide, and no
//                 amount of shearing makes a blob that broad read as a lane.
//   bh_contrast   one smoothstep at readout, re-opening what the transit
//                 averaged together. One pass, not Soap's two: this field is
//                 dimmer, and down here a second pass is a gate, not a curve.
//   normalise     the palette sets HUE and the arms set BRIGHTNESS, with arm
//                 crests running toward white. Without that last part a hue
//                 band sitting somewhere blue has no luminance to modulate -
//                 blue tops out near luma 19 - and the disc switches itself off.
//
// ---------------------------------------------------------------------------
//   bass    feeds the disc and speeds the infall
//   beat    throws a flare of new material in at the rim
//   volume  overall level, in a narrow band so it never washes out
//
// WITH NO AUDIO it turns on its own clock.
// ===========================================================================

#define BH_Q        8                 // fixed point for the backward trace
#define BH_MAXCOL 254                 // 255 marks "not on the board" in col[]

#ifndef BH_GRAD
  #define BH_GRAD 3                   // ring thickness, in eighths of a cell
#endif
#ifndef BH_ARMS
  // Luminance arms fed in at the rim. Six, not three: the circumference is 4*B
  // angular cells (64 on a 16-px face), so three arms are twenty-one cells wide
  // each and no amount of shearing turns a blob that broad into a lane you can
  // see - the disc read as a few soft quadrant blobs however well the flow
  // underneath was behaving. Halving the arm width is what makes the winding
  // legible as winding.
  #define BH_ARMS 6
#endif

struct BhState {
  uint8_t  mode;
  uint16_t ang, rad;
  uint16_t spin;                      // ring beaming phase
  uint16_t hue;                       // slow palette drift for injected colour
  uint8_t  bassEnv, beatEnv;
  uint8_t  clk[2];
};

// Same lid+walls mapping the other polar effects use.
static int bh_edge(int t, int den, int B) {
  int idx = ((t + den) * B) / (2 * den);
  if (idx < 0)     idx = 0;
  if (idx > B - 1) idx = B - 1;
  return idx;
}

// Two rulers, and they measure different things.
//
// dep[] is CHEBYSHEV - max(|x|,|y|) - because that is what makes the edge of
// the lid sit at exactly topd all the way round, so the ruler meets the top of
// the walls without a step and the flow crosses the rim seamlessly. Every other
// polar effect here relies on that.
//
// But Chebyshev contours are SQUARES. Testing "am I inside the horizon" against
// it therefore draws a square hole, which is what it did. rd[] is the ordinary
// Euclidean radius, used ONLY to decide what the void and the ring look like -
// so the hole is round while the flow underneath still runs on the ruler that
// keeps it continuous. On the walls the two agree.
static void bh_buildMap(uint8_t *col, uint8_t *dep, uint8_t *rd, int cols, int rows,
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
        rd[i]  = dep[i];                       // already round on a flat panel
        continue;
      }

      const int bx = x / B, by = y / B, lx = x % B, ly = y % B;

      if (bx == 1 && by == 1) {                               // LID: radial
        const int ax = 2 * lx - (B - 1), ay = 2 * ly - (B - 1);
        const int aax = (ax < 0) ? -ax : ax, aay = (ay < 0) ? -ay : ay;
        const int r2  = (aax > aay) ? aax : aay;
        dep[i] = (uint8_t)(r2 >> 1);
        const int re = (int)(sqrtf((float)(aax * aax + aay * aay)) * 0.5f);
        rd[i] = (uint8_t)(re > 254 ? 254 : re);
        if (r2 == 0) { col[i] = 0; continue; }
        int c;
        if (aay > aax) {
          const int idx = bh_edge(ax, aay, B);
          c = (ay < 0) ? idx : (2 * B + (B - 1 - idx));
        } else if (aax > aay) {
          const int idx = bh_edge(ay, aax, B);
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
      dep[i] = (uint8_t)(topd + bv);
      rd[i]  = dep[i];                         // off the lid the rulers agree
    }
  }
}

// Contrast restoration, the same trick Soap needed and for the same reason.
//
// Everything in the disc is injected at the rim and then rotated for its entire
// journey inward, and every rotation is a two-tap interpolation in angle. That
// is a low-pass filter running hundreds of times on material that never gets
// any new detail added to it, so what arrives near the middle is the angular
// AVERAGE of what set out. Measured on the lid, the disc had collapsed into a
// band from luma 16 to 63 - no black anywhere except the void itself, no
// highlights - and saturation sagged from ~124 to ~90 as neighbouring hues
// averaged toward grey.
//
// A double smoothstep is the cheap inverse. It is steep through the middle and
// flat at both ends, so mid values are pushed apart toward 0 and 255 while the
// extremes stay put. Applied per channel it does two jobs at once: it re-opens
// the dark lanes between the arms, and because the largest channel gets lifted
// while the smallest gets crushed, it pulls saturation back up as well.
// One pass, not two. Soap uses two, but Soap's field sits near full brightness
// and can afford it; this disc lives around a third of full, and down there a
// second pass is not a contrast curve, it is a gate - it took the lid from 24%
// black to 71% and dropped the mean below where it started. One pass moves the
// murk apart without eating it.
static inline uint8_t bh_contrast(uint8_t v) {
  return ease8InOutCubic(v);
}

// Bilinear read of the RGB disc. Angle wraps - it is a circle - radius clamps.
// Weights are eased, which is the difference between motion that flows and a
// field that quietly averages itself into mush over a few seconds.
static inline void bh_sample(const uint8_t *f, int ang, int rad,
                             int32_t aQ, int32_t rQ, uint8_t *out) {
  int a0 = (int)(aQ >> BH_Q), r0 = (int)(rQ >> BH_Q);
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

static FX_RET mode_black_hole() {
  if (!strip.isMatrix || !SEGMENT.is2D()) { SEGMENT.fill(SEGCOLOR(0)); FX_DONE; }
  const int cols = SEG_W, rows = SEG_H;
  if (cols < 8 || rows < 8) { SEGMENT.fill(SEGCOLOR(0)); FX_DONE; }

  const bool cubeRaw = cfx_isCube(cols, rows);
  const int  B       = cubeRaw ? (cols / 3) : 1;
  const bool cube    = cubeRaw && (4 * B) <= BH_MAXCOL;

  const int ang  = cube ? (4 * B) : 256;
  const int topd = cube ? ((B + 1) / 2) : 0;
  const int rad  = cube ? (topd + B) : (((cols < rows) ? cols : rows) / 2 + 1);
  if (rad < 6 || ang < 8) { SEGMENT.fill(SEGCOLOR(0)); FX_DONE; }

  const size_t m     = cfx_litCount(cols, rows, B, cube);
  const size_t cells = (size_t)ang * rad;
  const size_t need  = sizeof(BhState) + 3 * m + 3 * cells + 3 * cells
                   + (size_t)rad * sizeof(uint16_t);
  if (!SEGENV.allocateData(need)) { SEGMENT.fill(SEGCOLOR(0)); FX_DONE; }

  BhState *s   = (BhState *)SEGENV.data;
  uint8_t *col = (uint8_t *)(s + 1);
  uint8_t *dep = col + m;
  uint8_t *rd  = dep + m;                       // Euclidean radius, for void+ring
  uint8_t *dye = rd  + m;                       // rgb per polar cell
  uint8_t *tmp = dye + 3 * cells;
  uint16_t *accum = (uint16_t *)(tmp + 3 * cells);   // sub-cell infall, per ring

  const uint8_t want = (uint8_t)(cube ? 1 : 2);
  if (SEGENV.call == 0 || s->mode != want || s->ang != (uint16_t)ang) {
    bh_buildMap(col, dep, rd, cols, rows, cube, B, topd);
    s->mode = want; s->ang = (uint16_t)ang; s->rad = (uint16_t)rad;
    s->spin = 0; s->hue = 0; s->bassEnv = 0; s->beatEnv = 0;
    s->clk[0] = s->clk[1] = 0;
    memset(dye, 0, 3 * cells);
    memset(accum, 0, (size_t)rad * sizeof(uint16_t));
  }

  uint16_t dt = fx_dt8(s->clk);
  if (dt > 60) dt = 60;

  // --- audio ------------------------------------------------------------------
  um_data_t     *um   = cfx_getAudioData();
  const uint8_t *fft  = (uint8_t *)um->u_data[2];
  const float    vol  = *(float *)um->u_data[0];
  const uint8_t  beat = SEGMENT.check2 ? fx_lowBeat(um) : 0;
  int bass, mid, treb;
  cfx_bands(fft, bass, mid, treb);
  s->bassEnv = fx_env(s->bassEnv, (uint8_t)bass, dt, 300);
  if (beat > s->beatEnv) s->beatEnv = beat;
  { const int f = (int)s->beatEnv - (int)fx_step(8, dt);
    s->beatEnv = (uint8_t)((f < 0) ? 0 : f); }

  // --- geometry of the hole -------------------------------------------------------
  // The horizon has to leave room for a ring outside it AND a disc outside that,
  // so it is capped well short of the rim rather than allowed to swallow the lid.
  int rH = 1 + (((int)SEGMENT.custom1 * (topd > 3 ? topd - 3 : 1)) >> 8);
  if (rH > rad - 4) rH = rad - 4;
  if (rH < 1) rH = 1;
  const int rRing = rH + 1;                     // the thin arc sits just outside

  // Orbital rate, Q8 angular cells per tick, steepening inward as 1/r^2 from a
  // reference at the ring. Clamped because the trace has to stay under a couple
  // of cells a frame to interpolate rather than teleport.
  // Orbit and Infall are really one control: what you see is their RATIO.
  //
  // Total winding on the way in is (w0/v0) * ref * ln(rMax/rMin) angular cells.
  // At the old scales that came to under two cells out of sixty-four - about 11
  // degrees - which is why the disc read as radial wedges no matter what the
  // rotation looked like on its own. Rotation is now roughly five times the
  // infall, giving somewhere over half a turn across the disc, and the sliders
  // move that ratio in both directions.
  int32_t w0 = ((int32_t)SEGMENT.speed * 400) / 255 + 40;
  if (SEGMENT.check1) w0 += ((int32_t)s->bassEnv * 60) / 255;
  w0 = (w0 * (int32_t)dt) / 23;

  // Infall. Modest out in the disc, quicker once material is close in.
  // Scaled up hard. The r^-1/2 SHAPE is what makes the outer disc linger, but
  // the absolute speed sets how many times a parcel gets resampled on the way
  // in - and every resample blurs it a little. At the old scale a parcel took
  // ~120 frames to reach the middle, which is 120 rounds of interpolation, and
  // it arrived as mush long before it got there. Faster transit keeps the same
  // profile while giving the colour far fewer chances to average itself away.
  // Slow on purpose, and only affordable because the infall no longer
  // interpolates: whole-cell copies cost nothing, so a parcel can take several
  // seconds to reach the middle and still arrive with its colour intact. That
  // long, unblurred journey is what there has to be for a spiral to form at all.
  int32_t v0 = ((int32_t)SEGMENT.custom2 * 70) / 255 + 8;
  if (SEGMENT.check1) v0 += ((int32_t)s->bassEnv * 50) / 255;
  v0 = (v0 * (int32_t)dt) / 23;

  s->spin = (uint16_t)(s->spin + fx_step(4, dt));
  s->hue  = (uint16_t)(s->hue  + fx_step(2, dt));

  // --- transport ------------------------------------------------------------------
  // Backward trace: this cell's contents came from BEHIND in angle and from
  // FURTHER OUT in radius, since everything is falling inward.
  for (int r = 0; r < rad; r++) {
    // Keplerian rotation and viscous infall - the profile a real accretion disc
    // has, and the reason it looks like one.
    //
    //     omega ~ r^-3/2      orbits, so the inside laps the outside
    //     v_r   ~ r^-1/2      falls inward, and SLOWER the further out you are
    //
    // The pairing is the important part, not either exponent alone. Tangential
    // speed is omega*r ~ r^-1/2, and radial speed is also ~ r^-1/2, so their
    // RATIO is the same at every radius - which is the definition of a
    // logarithmic spiral. The arms therefore keep one pitch angle from the rim
    // all the way in, instead of unwinding into spokes at the edge.
    //
    // That is exactly what the old law got wrong: omega ~ 1/r^2 falls off so
    // fast that the outer disc turned 36x slower than the inner one, so
    // material arrived long before rotation could wind it, and the infall was
    // near enough constant across the whole disc rather than easing off outward.
    //
    // Floats are fine here: this loop runs once per RADIUS (a couple of dozen
    // iterations a frame), not per pixel.
    const float fr  = (float)(r < 1 ? 1 : r);
    const float ref = (float)(rRing < 1 ? 1 : rRing);
    const float q   = ref / fr;                 // <1 outside the ring, >1 inside
    const float rq  = sqrtf(q);

    int32_t om = (int32_t)((float)w0 * q * rq); // r^-3/2
    if (om > 900) om = 900;                     // interpolation stays sane

    // Rotate only - one axis, two taps, and nothing radial happens here.
    for (int a = 0; a < ang; a++) {
      const int32_t aQ = ((int32_t)a << BH_Q) - om;
      uint8_t px[3];
      bh_sample(dye, ang, rad, aQ, (int32_t)r << BH_Q, px);
      const size_t o = ((size_t)r * ang + a) * 3;
      tmp[o + 0] = px[0]; tmp[o + 1] = px[1]; tmp[o + 2] = px[2];
    }
  }
  memcpy(dye, tmp, 3 * cells);

  // --- fall inward, in WHOLE cells -------------------------------------------------
  // Infall is deliberately not interpolated. It used to share the backward trace
  // with the rotation, which meant every ring was resampled a fraction of a cell
  // inward on every single frame - and a fraction of a cell is the worst case
  // for blur, because the result is always a mix of two neighbours.
  //
  // That put the whole effect in a bind. A convincing spiral needs many turns
  // during the infall, which needs the infall to be SLOW relative to the
  // rotation, which means a long journey - and a long journey was exactly what
  // the per-frame blur could not survive. Colour arrived as mush.
  //
  // So each ring carries a sub-cell accumulator instead. Nothing moves radially
  // until a whole cell has been earned, and then the ring is COPIED one step in.
  // A copy loses nothing at all, so the transit can now take as many frames as
  // the spiral needs. Rings accumulate at different rates, so they do not step
  // together and the motion still reads as continuous.
  for (int r = 0; r < rad - 1; r++) {
    const float fr  = (float)(r < 1 ? 1 : r);
    const float ref = (float)(rRing < 1 ? 1 : rRing);
    int32_t vr = (int32_t)((float)v0 * sqrtf(ref / fr));   // r^-1/2
    if (vr > 900) vr = 900;
    if (vr < 4)   vr = 4;                                  // never fully stalls

    uint32_t acc = (uint32_t)accum[r] + (uint32_t)vr;
    while (acc >= 256 && r + 1 < rad) {
      memmove(dye + (size_t)r * ang * 3, dye + (size_t)(r + 1) * ang * 3,
              (size_t)ang * 3);
      acc -= 256;
    }
    accum[r] = (uint16_t)(acc > 255 ? 255 : acc);
  }

  // --- feed the disc, and swallow what reaches the middle -------------------------
  // New material enters at the outermost ring, its colour varying around the
  // circumference so the disc never becomes one flat tone. A beat throws in a
  // brighter slug of it.
  //
  // ASSIGNED, not max-combined. Taking the brighter of old and new looks like a
  // reasonable way to "add" material, but it is a ratchet: a cell can only ever
  // get brighter, never change colour, so within a few seconds the feed ring
  // saturates to the brightest thing it has ever seen and then pumps that one
  // constant inward forever. That is what "no new colour is being injected"
  // looked like - the injection was running the whole time, it just had nothing
  // left to say. Crossfading hard toward the current colour instead means the
  // rim genuinely carries fresh material every frame.
  //
  // Two rings rather than one, so a visible amount of matter is entering rather
  // than a single cell's worth being stretched across the whole disc.
  {
    // Glow sets how hot the material arrives. This used to be a flat 150, which
    // meant the disc could never exceed 59% before the audio drive scaled it
    // again - and since the arms then modulated DOWN from there, the whole field
    // lived between luma 32 and 150 at birth and only narrowed from there. The
    // brightest thing on the lid measured 83. Feed the rim at full level and let
    // the arms carve the darks out instead.
    const int pk = 120 + ((int)SEGMENT.intensity * 135) / 255;  // 120..255
    const int pkb = pk + (s->beatEnv >> 1);
    const uint8_t punch = (uint8_t)(pkb > 255 ? 255 : pkb);
    const uint8_t mixIn = (uint8_t)(190 + (s->beatEnv >> 2));   // ~75%..100%
    for (int k = 0; k < 2 && k < rad; k++) {
      const int rOut = rad - 1 - k;
      for (int a = 0; a < ang; a++) {
        // Hue varies around the rim AND drifts, so successive arrivals differ.
        // Structure goes in as BRIGHTNESS, colour goes in slowly.
        //
        // These are two different jobs and they survive the journey very
        // differently. Averaging two hues gives grey - so a rim that sweeps the
        // palette several times greys out the moment anything interpolates it,
        // which is what turned the disc to mush. Averaging bright with dark just
        // gives mid, which still reads as contrast. So the arms are a luminance
        // pattern (they stay legible all the way in, winding as they go) while
        // the hue drifts slowly around the rim in broad sectors that neighbours
        // barely disagree about.
        // A NARROW hue band that drifts, not a full palette sweep around the
        // rim. The rim used to span all 256 palette indices over the
        // circumference, which meant the angular blur of the transit was
        // averaging colours from opposite ends of the palette together - and
        // the average of a whole palette is grey. Saturation measured 120
        // against 166-207 for the effects worth comparing to. Ninety-six
        // indices is still several distinct colours in view at once, but
        // neighbours now differ by about one step instead of four, so blurring
        // them lands on a real colour. The full palette is still seen; the
        // drift carries the band through it over time rather than all at once.
        const uint8_t idx = (uint8_t)(((a * 96) / ang) + (s->hue >> 4)
                                      + (uint8_t)(k * 10));
        // A plain sine, deliberately. Easing this profile as well was tried and
        // is the wrong place to do it: an eased sine sits near its extremes for
        // most of the period, so the dark lanes come out as wide as the arms and
        // the disc measured 62% black against a 28-43% reference. Carving the
        // lanes is bh_contrast's job, and it is better placed to do it because
        // it acts on the field AFTER the transit, where the blur it is
        // correcting for has actually happened. Here we only need the arms to
        // start with real range.
        const uint8_t arm = sin8_t((uint8_t)(((a * 256 * BH_ARMS) / ang)
                                             + (s->spin >> 4)));
        const uint8_t amp = (uint8_t)(20 + ((int)arm * 235) / 255);   // 20..255

        // Normalise the palette entry to full level before the arms scale it,
        // so the palette supplies HUE and the arms supply BRIGHTNESS - which is
        // the division this effect has been built around all along, and the one
        // place it was not being honoured.
        //
        // It matters more here than it would elsewhere because the hue band is
        // narrow. A band 96 indices wide can sit entirely inside a dark stretch
        // of a palette, and then the whole disc goes dark with it - over a
        // minute the mean fell to 4 and 96% of the surface was black, the disc
        // effectively switching itself off and back on as the drift carried the
        // band through. The old full-circumference sweep never showed this
        // because it always straddled the bright parts. Normalising decouples
        // the two: the palette's dark entries still read as their own colour,
        // they just arrive at the level the arm profile asked for.
        uint32_t pc = SEGMENT.color_from_palette(idx, false, true, 0);
        {
          int pr = (int)((pc >> 16) & 0xFF), pg = (int)((pc >> 8) & 0xFF),
              pb = (int)(pc & 0xFF);
          int mx = pr > pg ? pr : pg; if (pb > mx) mx = pb;
          if (mx > 8) {                       // pure black entries stay black
            pr = (pr * 255) / mx; pg = (pg * 255) / mx; pb = (pb * 255) / mx;
          }
          // Arm crests run toward white, and this is what lets the arms exist
          // at all when the hue band is sitting somewhere blue. Brightness is
          // not linear in the channels: a fully saturated blue tops out around
          // luma 19 while a yellow reaches 236, so scaling a blue up and down
          // gives a luminance pattern with nowhere to go - the disc measured a
          // spatial sigma of 20 in the blue phase against 45 in the yellow one,
          // and simply looked switched off. Blending the crest toward white
          // gives every hue the same luminance headroom, and it is what the
          // thing being depicted does anyway: the hot parts of an accretion
          // disc go white, they do not go to a brighter version of their own
          // colour.
          const int wht = ((int)arm * 92) / 255;          // up to ~36% at crest
          pr += ((255 - pr) * wht) / 255;
          pg += ((255 - pg) * wht) / 255;
          pb += ((255 - pb) * wht) / 255;
          pc = RGBW32(pr, pg, pb, 0);
        }
        uint32_t c = mq_scale(pc, scale8(punch, amp));
        const size_t o = ((size_t)rOut * ang + a) * 3;
        const uint8_t src[3] = { (uint8_t)((c >> 16) & 0xFF),
                                 (uint8_t)((c >>  8) & 0xFF),
                                 (uint8_t)( c        & 0xFF) };
        for (int ch = 0; ch < 3; ch++)
          dye[o + ch] = (uint8_t)(((int)dye[o + ch] * (255 - mixIn)
                                 + (int)src[ch] * mixIn + 127) / 255);
      }
    }
  }
  // Inside the horizon nothing survives - this is what makes the void a hole
  // rather than a dark disc drawn over the top of a full field.
  for (int r = 0; r < rH && r < rad; r++)
    memset(dye + (size_t)r * ang * 3, 0, (size_t)ang * 3);

  // --- render ---------------------------------------------------------------------
  const uint8_t drive = cfx_drive(vol, 0.35f, 110);
  const int ringAmt = cfx_c3full(SEGMENT.custom3);

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
      const int dr = rd[i];               // round ruler, for void + ring
      const int a = cube ? u : ((u * ang) >> 8);
      const size_t o = ((size_t)d * ang + (a % ang)) * 3;

      // Contrast is applied to the DISC only, and before the ring is added -
      // the arc is already a deliberate highlight and putting it through the
      // curve would only clip it.
      uint32_t c = mq_scale(RGBW32(bh_contrast(dye[o]),
                                   bh_contrast(dye[o + 1]),
                                   bh_contrast(dye[o + 2]), 0), drive);

      // The arc. One cell wide, and brightest on one side of its circumference -
      // an even ring reads as a drawn circle, a beamed one reads as light
      // curving around something.
      if (dr < rH) { SEGMENT.setPixelColorXY(x, y, 0); continue; }  // the hole
      if (ringAmt && dr == rRing) {
        const uint8_t beam = sin8_t((uint8_t)(((a * 256) / ang) + (s->spin >> 5)));
        const int lift = (ringAmt * (40 + ((int)beam * 215) / 255)) / 255;
        c = color_add(c, mq_scale(RGBW32(255, 245, 220, 0), (uint8_t)(lift > 255 ? 255 : lift)), true);
      }
      SEGMENT.setPixelColorXY(x, y, c);
    }
  }
  FX_DONE;
}

static const char _data_FX_MODE_BLACK_HOLE[] PROGMEM =
  "Ace 3-D Black Hole@Orbit,Glow,Horizon,Infall,Ring,Bass pull,Beat flare,Flat mode;;!;2f;sx=120,ix=180,c1=110,c2=130,c3=23,o1=1,o2=1,pal=35";


// ---------------------------------------------------------------------------
// Registration - joins the effect bank, which decides whether this effect
// claims one of the device's limited effect slots. See cube_fx_bank.h.
// ---------------------------------------------------------------------------
static CfxBankReg cube_fx_27_black_hole_reg(&mode_black_hole, _data_FX_MODE_BLACK_HOLE);
