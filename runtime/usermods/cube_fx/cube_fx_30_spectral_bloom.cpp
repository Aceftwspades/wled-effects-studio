#include "wled.h"
#include "cube_fx_common.h"
#include "cube_fx_bank.h"

// ===========================================================================
// 30. ACE 3-D SPECTRAL BLOOM
// ===========================================================================
// Soap's curls carrying Bloom's spectrum, over black.
//
// Cube Bloom's best idea is not its shells, it is where it puts them: it reads
// the spectral centroid at the moment of a hit and drops bright, treble-heavy
// blooms HIGH on the cube and bass-heavy ones LOW. Frequency becomes height.
// That idea does not need shells at all - it works on anything you can place.
//
// So: frequency is height, colour arrives in horizontal bands at the height its
// bin owns, Soap's curl-noise flow folds and shears it, and the whole field
// falls to black. Nothing persists. At rest the cube is dark; a hit prints a
// band at its own altitude and the flow immediately starts pulling it apart.
//
// ---------------------------------------------------------------------------
// WHAT IT TAKES FROM EACH
// ---------------------------------------------------------------------------
// From SOAP: the chart and the transport. 3-D surface positions with a
// fold-following reverse lookup, curl-of-a-potential velocity so the flow can
// only fold and never pool, and eased bilinear taps because raw bilinear is a
// mixer and anything stirred by a mixer goes uniform.
//
// From BLOOM: spectral placement, in two forms.
//
//   BANDS (default)  every bin owns a height and paints a horizontal band
//                    there, continuously, at whatever level it is running.
//
//   DRIP             the bins are read as a 4x4 grid - across the cube and up
//                    it - and a DROP is placed at a bin's cell the moment that
//                    bin onsets. This is Bloom's actual model: read the
//                    spectrum at the instant of a hit and print where it says,
//                    rather than painting a continuous function of it. The
//                    difference in how it looks is the difference between a
//                    snapshot and a meter.
//
// Drip exists because of a real weakness in Bands: a horizontal band only
// touches the LID when the music is bright enough to light the topmost one, so
// the top face sat dark most of the time. Measured, Bands puts 1% of its light
// on the lid where the lid is 20% of the surface; Drip puts 17%, because the
// top row of the grid IS the lid.
//
// It replaced a Centroid mode that put one band at the spectral centroid. That
// was the weakest thing here and for the same reason - it is still a band, so
// it still only reached the lid when the music happened to be bright.
//
// ---------------------------------------------------------------------------
// WHY IT FALLS TO BLACK, AND WHY THAT CHANGES THE RULES
// ---------------------------------------------------------------------------
// Soap must fight its own mixing: it is a closed surface with no edge for
// colour to enter through, so pigment has to arrive as fast as the stirring
// blends it away or the whole thing goes uniform grey. Spectral Fountain
// inherited that problem and solved it with wide overlapping nozzles.
//
// This effect does not have the problem at all, because it DECAYS. Colour that
// has been stirred long enough to lose its identity has also faded to nothing
// by then, so the mixer never gets to finish its work. That is what buys the
// freedom to inject in thin bands - which is what makes the spectrum legible as
// altitude rather than as a wash.
//
// ---------------------------------------------------------------------------
// THE HEIGHT TABLE
// ---------------------------------------------------------------------------
// Injection is not computed per pixel against sixteen bins. A 256-entry table
// is built once a frame mapping HEIGHT to (palette index, brightness), and each
// pixel is then a single lookup on its own z. Sixteen bins times twelve hundred
// pixels is twenty thousand distance tests a frame; the table is 256 and the
// per-pixel cost becomes one index.
//
// The table blends the bins' PALETTE POSITIONS, not their colours. Averaging
// the RGB of two bands lands on grey wherever they overlap - the same trap that
// cost Spectral Fountain its saturation - while averaging the index lands on
// whatever the palette itself puts between them.
//
//   bands    colour and brightness at the height each bin owns
//   beat     a flash across the whole field
//   volume   overall level, in a narrow band so it never washes out
//
// Gate the synthetic bands to the beat in the simulator to see this properly:
// with a steady tone it is a standing pattern, and only a transient shows what
// it is for.
// ===========================================================================

#ifndef SB_CURL
  #define SB_CURL 6                 // gain from the noise gradient to flow units
#endif
#define SB_LUT 256                  // height -> injection table

// Sixteen, so a beat can place one for every bin at once. At ten, a burst was
// silently truncated and the top bins - the ones that land on the lid - were
// the ones dropped, because the scan runs low to high.
#define SB_MAXDROP 16

// How many recent drops are remembered for spacing, how long each is remembered
// for, and how many positions are tried before a drop gives up and waits.
//
// The memory has to outlast the drop's own visible life or the rule does not
// bite: forgetting a position while its drop is still on the cube lets the next
// one land on top of it, which is exactly the case the spacing exists to stop.
// 900 ms is comfortably past the fade at the default rate.
#define SB_HIST     16
#define SB_HISTMS   900
#define SB_TRIES    12

struct SbState {
  uint8_t  mode;
  uint32_t nx, ny, nz;              // potential-field clocks, Q8
  uint8_t  splash;                  // beat envelope
  uint8_t  peak;                    // slow-release spectrum peak, for auto-range
  uint8_t  spec[16];
  uint8_t  env[16];                 // per-bin envelope, for onset detection
  uint8_t  bpk[16];                 // per-bin slow peak, for per-bin auto-range
  uint16_t hold[16];                // per-bin refractory, in ms remaining
  int8_t   hx[SB_HIST], hy[SB_HIST], hz[SB_HIST];   // recent drop positions
  uint16_t hms[SB_HIST];            // ms each of those is still remembered for
  uint8_t  hhead;
  uint8_t  clk[2];
};

// A point on one of the five lit faces, in the same coordinates the drops are
// painted in.
//
// This replaced a 4x4 grid that gave every bin one fixed cell - gx around the
// cube, gy up it, top row on the lid. The grid did put a drop on the lid, which
// was the point of it, but it also welded each bin to a sixteenth of the
// surface: red was thrown by a bin whose cell was on a wall, so red could never
// appear on the lid however long you watched. Every bin now reaches every pixel
// and the colour alone carries which bin threw it, which is a stronger cue
// anyway - you can read it without knowing the mapping.
//
// The five faces are equal in area and chosen uniformly, so the light spreads
// evenly over the surface by construction rather than by how the spectrum
// happens to be shaped.
static inline int sb_axis(uint8_t r) {             // 0..255 -> -127..127
  return ((int)r * 254) / 255 - 127;
}

static void sb_surfacePoint(uint8_t face, int u, int v, int &X, int &Y, int &Z) {
  switch (face) {
    case 0:  X =  u;   Y = -127; Z = v;   break;
    case 1:  X =  127; Y =  u;   Z = v;   break;
    case 2:  X = -u;   Y =  127; Z = v;   break;
    case 3:  X = -127; Y = -u;   Z = v;   break;
    default: X =  u;   Y =  v;   Z = 127; break;   // LID
  }
}

// A drop's colour, at a brightness that does not depend on which bin threw it.
//
// Palette brightness is nowhere near uniform - this simulator's Rainbow runs
// from black through deep purple to white and back to black - so mapping bins
// straight onto palette positions made low-bin drops almost invisible. Measured,
// the whole mode peaked at a raw value of 78 where a drop should be painting
// near 190, and with a bass-heavy spectrum those were the only drops firing.
//
// In BANDS mode that is survivable, because many bands overlap and the bright
// ones carry the picture. A drop is alone: it has to be visible on its own. Its
// HUE is the only thing saying which bin threw it now that position is free, so
// brightness carries no information and is free to be equalised - and it has to
// be, or half the palette is a bin you can never see fire. Normalise the chroma
// to full, then lift toward white only as far as it takes to reach a common
// luma.
static uint32_t sb_dropColor(uint32_t c, int target) {
  int r = (int)((c >> 16) & 0xFF), g = (int)((c >> 8) & 0xFF), b = (int)(c & 0xFF);
  int mx = r > g ? r : g; if (b > mx) mx = b;
  if (mx < 8) return RGBW32(target, target, target, 0);   // a black entry
  r = (r * 255) / mx; g = (g * 255) / mx; b = (b * 255) / mx;
  const int L = (r * 54 + g * 183 + b * 19) >> 8;
  if (L < target && L < 255) {
    const int w = ((target - L) * 255) / (255 - L);
    r += ((255 - r) * w) / 255;
    g += ((255 - g) * w) / 255;
    b += ((255 - b) * w) / 255;
  }
  return RGBW32(r, g, b, 0);
}

// One smoothstep, not Soap's two. Soap's field sits near full brightness and
// can afford two; this one is mostly black by design, and a second pass on a
// dim field is a gate rather than a curve - the lesson Black Hole paid for.
static inline uint8_t sb_contrast(uint8_t v) {
  return ease8InOutCubic(v);
}

static FX_RET mode_spectral_bloom() {
  if (!strip.isMatrix || !SEGMENT.is2D()) { SEGMENT.fill(SEGCOLOR(0)); FX_DONE; }
  const int cols = SEG_W, rows = SEG_H;
  if (cols < 8 || rows < 8) { SEGMENT.fill(SEGCOLOR(0)); FX_DONE; }
  const size_t n = (size_t)cols * rows;

  const bool cube = cfx_isCube(cols, rows);
  const int  B    = cube ? (cols / 3) : 1;
  const int  Bq   = cube ? B : 1;
  const size_t lut = cube ? (size_t)6 * Bq * Bq : 0;
  const size_t m   = cfx_litCount(cols, rows, B, cube);

  const size_t need = sizeof(SbState) + 3 * m + 3 * m + 3 * m
                    + lut * sizeof(uint16_t);
  if (!SEGENV.allocateData(need)) { SEGMENT.fill(SEGCOLOR(0)); FX_DONE; }

  SbState *s   = (SbState *)SEGENV.data;
  int8_t  *cx  = (int8_t *)(s + 1);
  int8_t  *cy  = cx + m;
  int8_t  *cz  = cy + m;
  uint8_t *pix = (uint8_t *)(cz + m);
  uint8_t *nxt = pix + 3 * m;
  uint16_t *rev = (uint16_t *)(nxt + 3 * m);

  const uint8_t want = (uint8_t)(cube ? 1 : 2);
  const bool init = (SEGENV.call == 0 || s->mode != want);
  if (init) {
    s->mode = want; s->splash = 0; s->peak = 0;
    s->clk[0] = s->clk[1] = 0;
    memset(s->spec, 0, sizeof(s->spec));
    memset(s->env, 0, sizeof(s->env));
    memset(s->hold, 0, sizeof(s->hold));
    s->nx = (uint32_t)hw_random16() << 8;
    s->ny = (uint32_t)hw_random16() << 8;
    s->nz = (uint32_t)hw_random16() << 8;

    if (cube) {
      // pix and nxt are adjacent and give 6m together, and 2m >= n always holds
      // for a net, so they stand in as scratch for the full-rectangle build
      // before either holds colour. Both are cleared below.
      int8_t *sc = (int8_t *)pix;
      cfx_buildCube(sc, sc + n, sc + 2 * n, nullptr, nullptr, cols, rows, cube);
      for (int y = 0; y < rows; y++)
        for (int x = 0; x < cols; x++) {
          if (cfx_gap(x, y, B)) continue;
          const size_t src = (size_t)y * cols + x;
          const size_t ci  = (size_t)cfx_cidx(x, y, cols, B, cube);
          cx[ci] = sc[src]; cy[ci] = sc[n + src]; cz[ci] = sc[2 * n + src];
        }
      for (size_t k = 0; k < lut; k++) rev[k] = 0xFFFF;
      for (int y = 0; y < rows; y++)
        for (int x = 0; x < cols; x++) {
          if (cfx_gap(x, y, B)) continue;
          const size_t ci = (size_t)cfx_cidx(x, y, cols, B, cube);
          int f, a, b; cfx_face(cx[ci], cy[ci], cz[ci], f, a, b);
          int ai = ((a + 128) * Bq) >> 8, bi = ((b + 128) * Bq) >> 8;
          if (ai < 0) ai = 0; else if (ai >= Bq) ai = Bq - 1;
          if (bi < 0) bi = 0; else if (bi >= Bq) bi = Bq - 1;
          rev[((size_t)f * Bq + bi) * Bq + ai] = (uint16_t)ci;
        }
    } else {
      cfx_buildCube(cx, cy, cz, nullptr, nullptr, cols, rows, cube);
    }
    memset(pix, 0, 3 * m);                       // opens black, as it should
  }

  uint16_t dt = fx_dt8(s->clk);
  if (dt > 60) dt = 60;

  // --- audio ------------------------------------------------------------------
  um_data_t     *um  = cfx_getAudioData();
  const float    vol = *(float *)um->u_data[0];
  const uint8_t *fft = (uint8_t *)um->u_data[2];
  const uint8_t beat = SEGMENT.check2 ? fx_lowBeat(um) : 0;
  if (beat > s->splash) s->splash = beat;
  { const int f = (int)s->splash - (int)fx_step(7, dt);
    s->splash = (uint8_t)(f < 0 ? 0 : f); }

  cfx_smoothSpec(s->spec, fft, 3);

  // Auto-range against a slow-release peak, so the bands play at the same
  // vigour whatever the source level is, and so silence stays silent rather
  // than being amplified into a light show.
  {
    int mx = 0;
    for (int i = 0; i < 16; i++) if (s->spec[i] > mx) mx = s->spec[i];
    if (mx > s->peak) s->peak = (uint8_t)mx;
    else { const int d = (int)s->peak - (int)fx_step(1, dt);
           s->peak = (uint8_t)((d < 0) ? 0 : d); }
  }
  const int pk = (s->peak < 40) ? 40 : (int)s->peak;

  // --- parameters ---------------------------------------------------------------
  const int sc = 6;                                          // noise scale, as Soap
  const int pixAmp = 2 + (((int)SEGMENT.custom1 * 12) >> 8);  // 2..14 pixels
  const int amp = cube ? ((254 / (B > 0 ? B : 1)) * pixAmp) : pixAmp;

  const int sp = SEGMENT.speed;
  int32_t flowQ;
  if (sp <= 128) flowQ = 32 + ((int32_t)(256 - 32) * sp) / 128;
  else { const int32_t t = sp - 128; flowQ = 256 + ((int32_t)3840 * t * t) / (127 * 127); }
  const int32_t adv = (flowQ * (int32_t)dt) / 23;
  s->nx += (uint32_t)adv;
  s->ny += (uint32_t)((adv * 3) / 4);
  s->nz += (uint32_t)((adv * 5) / 4);
  const uint16_t ox = (uint16_t)(s->nx >> 8), oy = (uint16_t)(s->ny >> 8),
                 oz = (uint16_t)(s->nz >> 8);

  // Squaring the bin level below sharpens the spectrum but throws away most of
  // the total energy - the loud band keeps its brightness while every quieter
  // one nearly vanishes, and the cube went to 90% black. Inject pays that back.
  const int inject = 40 + ((int)SEGMENT.intensity * 260) / 255;   // 40..300
  // Fall to black. This is the control that decides whether the cube is mostly
  // dark with brief prints, or holds a lingering veil.
  const int fade = 1 + (((255 - (int)SEGMENT.custom2) * 14) >> 8);
  // Band width in height units, from the FIVE-BIT custom3 - widened through
  // cfx_c3full, since the arithmetic below wants a full byte.
  const int spread = 14 + ((int)cfx_c3full(SEGMENT.custom3) * 90) / 255;
  // Drip reuses the same slider as a drop RADIUS. A drop wants to be a good
  // deal fatter than a band is thin, or it lands as a single lit pixel and the
  // flow erases it before the eye finds it.
  // Substantially fatter than the first attempt. A radius of 56 surface units
  // is three and a half pixels on a 16-px face, and a handful of three-pixel
  // discs on a 1280-pixel cube under a fast fade averaged out to nothing - the
  // whole mode measured a mean of 0.0.
  // Generous. A drop paints ONCE where a band repaints every frame, so to carry
  // comparable light it has to cover real area: at 8-9 pixels radius on a 16-px
  // face a burst of sixteen covers a good part of the cube, which is the point.
  const int dropR  = 92 + ((int)cfx_c3full(SEGMENT.custom3) * 150) / 255;
  const int dropR2 = dropR * dropR;

  // --- the height table ----------------------------------------------------------
  // height (0..255) -> palette index + brightness, built once and read once per
  // pixel. Indices are blended, not colours: averaging the RGB of two bands
  // lands on grey wherever they overlap.
  uint8_t lutIdx[SB_LUT], lutAmp[SB_LUT];
  memset(lutAmp, 0, sizeof(lutAmp));
  memset(lutIdx, 0, sizeof(lutIdx));

  // --- DRIP: drops placed on a grid the bins define ------------------------
  // Replaces the old Centroid mode, which put one band at the spectral centroid
  // and was the weakest thing here: it is still a band, so it still only ever
  // touched the lid when the music happened to be bright.
  //
  // A drop is placed when a BIN ONSETS - its level rises sharply above its own
  // envelope - and it lands at that bin's cell in the 4x4 grid. That is Bloom's
  // model, which reads the spectrum at the instant of a hit and prints where it
  // says, rather than painting a continuous function of the spectrum. The
  // difference in how it looks is the difference between a snapshot and a
  // meter.
  //
  // Onsets rather than a single global beat, because there is no helper for
  // per-bin transients - cfx_tempo gives a predicted beat and cfx_drop detects
  // an EDM breakdown, both of which are one event for the whole spectrum, and
  // one event cannot say WHERE on the grid to place anything. The tempo's beat
  // is still used, to widen the threshold so a real beat lands several drops at
  // once instead of one.
  int dropX[SB_MAXDROP], dropY[SB_MAXDROP], dropZ[SB_MAXDROP];
  uint8_t dropIdx[SB_MAXDROP], dropAmp[SB_MAXDROP];
  int nDrop = 0;

  if (SEGMENT.check1) {
    const CfxTempoState &tempo = cfx_tempo(um);
    // On a beat the bar is lowered, so a hit prints a spread of drops rather
    // than a single one. Confidence keeps that from firing on a stale
    // prediction once the bass drops out.
    const int onBeat = (tempo.beat && tempo.confidence > 90) || tempo.hit;
    // Permissive on purpose. At 26 the only things that cleared the bar were
    // kick transients on the bottom three bins, so drops landed at one height
    // and the lid - the reason this mode exists - never saw one.
    // Tuned against real music, not the synthetic generator. A steady
    // synthetic tone onsets almost never, so thresholds that looked right
    // there fired on every frame of actual programme material - twenty to
    // thirty drop frames a second out of forty-three.
    const int thresh = onBeat ? 10 : 22;

    // Minimum separation, as a fraction of the drop radius. Three quarters
    // leaves the discs just touching at their dim outer edge, which reads as
    // two drops meeting rather than as one merged shape. Larger and the surface
    // runs out of room and the drop rate falls away; smaller and the clumping
    // this exists to prevent comes back.
    const int minD  = (dropR * 3) / 4;
    const long minD2 = (long)minD * minD;
    for (int h = 0; h < SB_HIST; h++) {
      s->hms[h] = (dt >= s->hms[h]) ? 0 : (uint16_t)(s->hms[h] - dt);
    }

    for (int k = 0; k < 16 && nDrop < SB_MAXDROP; k++) {
      const int raw = s->spec[k];
      const int rise = raw - (int)s->env[k];
      // Refractory in MILLISECONDS, not frames. Counted in frames it was a
      // different length of time on every machine that ran it: the same twelve
      // frames is 280 ms at forty-three frames a second and 74 ms at a hundred
      // and sixty, so the drop rate moved with the render rate and no two
      // measurements were of the same effect.
      s->hold[k] = (dt >= s->hold[k]) ? 0 : (uint16_t)(s->hold[k] - dt);

      // Level relative to THIS BIN's own peak, not the spectrum's.
      //
      // Against the global peak the grid was unusable on real music. Music
      // tilts down about six dB an octave, so the treble bins sit an order of
      // magnitude below the bass ones and never cleared the gate - and the
      // treble bins are the top row, which is the lid. Measured: the lid took
      // 3.7% of the light while each wall took 25%, on a surface where every
      // face is a fifth of the area. Per-bin ranging asks "is this bin loud FOR
      // ITSELF", which is the question being posed, and every bin gets to throw
      // a drop regardless of where the music's energy sits. That still matters
      // now that position is free: it is what stops the bass bins doing all the
      // throwing and the palette collapsing to its low end.
      s->bpk[k] = (uint8_t)(raw > (int)s->bpk[k]
                            ? raw
                            : fx_env(s->bpk[k], (uint8_t)raw, dt, 3000));
      const int bref = s->bpk[k] < 24 ? 24 : s->bpk[k];   // floor: silence stays silent
      int lv = (raw * 255) / bref;
      if (lv > 255) lv = 255;
      // The rise is measured in the same normalised units, for the same
      // reason: a transient in a quiet band is a small number of levels and a
      // large fraction of that band.
      const int nrise = rise > 0 ? (rise * 255) / bref : 0;
      if (!s->hold[k] && nrise > thresh && lv > 35) {
        // Best of several candidates, keeping drops apart.
        //
        // Free placement on its own clumps: uniform random points are not
        // evenly spaced, they arrive in clusters with bare patches between, and
        // two drops landing on top of each other read as one shapeless blob
        // rather than as two bins hitting. Throwing a handful of candidates and
        // keeping whichever sits furthest from the recent ones is a cheap
        // Mitchell best-candidate sampling, and it turns the same random stream
        // into a well-spread one.
        //
        // The bar scales with the drop's own radius, so the Size slider carries
        // the spacing with it rather than leaving big drops overlapping and
        // small ones marooned.
        int bx = 0, by = 0, bz = 0;
        long best = -1;
        for (int t = 0; t < SB_TRIES; t++) {
          int cxx, cyy, czz;
          sb_surfacePoint(hw_random8() % 5,
                          sb_axis(hw_random8()), sb_axis(hw_random8()),
                          cxx, cyy, czz);
          long worst = 0x7FFFFFFFL;
          for (int h = 0; h < SB_HIST; h++) {
            if (!s->hms[h]) continue;
            const long ddx = cxx - (int)s->hx[h];
            const long ddy = cyy - (int)s->hy[h];
            const long ddz = czz - (int)s->hz[h];
            const long d2 = ddx * ddx + ddy * ddy + ddz * ddz;
            if (d2 < worst) worst = d2;
          }
          if (worst > best) { best = worst; bx = cxx; by = cyy; bz = czz; }
        }
        if (best < minD2) {
          // Nowhere with room. Wait a short while rather than the full
          // refractory - the cube clears quickly, and this is what makes the
          // drop rate self-limiting under a dense passage instead of piling
          // everything into the same few pixels.
          s->hold[k] = 60;
        } else {
          // A bin may land a drop about seven times a second on a beat and
          // three otherwise. Faster is not a drop landing, it is a hose.
          s->hold[k] = onBeat ? 140 : 300;
          dropX[nDrop] = bx; dropY[nDrop] = by; dropZ[nDrop] = bz;
          dropIdx[nDrop] = (uint8_t)(16 + (k * 223) / 15);
          int a = (lv * inject) >> 8;
          dropAmp[nDrop] = (uint8_t)(a > 255 ? 255 : a);
          nDrop++;
          const uint8_t h = s->hhead;
          s->hx[h] = (int8_t)bx; s->hy[h] = (int8_t)by; s->hz[h] = (int8_t)bz;
          s->hms[h] = SB_HISTMS;
          s->hhead = (uint8_t)((h + 1) % SB_HIST);
        }
      }
      // Envelope tracks the bin with a slow release, so a sustained tone stops
      // re-triggering while a transient over the top of it still does.
      s->env[k] = fx_env(s->env[k], (uint8_t)raw, dt, 260);
    }
  } else {
    // BANDS - every bin owns a height. Low bins at the bottom of the cube, high
    // ones at the top.
    for (int h = 0; h < SB_LUT; h++) {
      int acc = 0, wsum = 0, refI = -1, accD = 0;
      for (int k = 0; k < 16; k++) {
        const int hk = 8 + (k * 239) / 15;
        int d = h - hk; if (d < 0) d = -d;
        if (d >= spread) continue;
        const int t = 255 - (d * 255) / spread;
        const int w = (t * t) >> 8;                       // smooth, compact
        int lv = ((int)s->spec[k] * 255) / pk;
        if (lv > 255) lv = 255;
        // Squared, so a quiet bin contributes far less than a linear share.
        // Auto-ranging keeps every bin on the same scale, which is what makes
        // the display readable at any volume, but it also means a bin at a
        // tenth of the peak still lights its band at a tenth - and with sixteen
        // of them overlapping, the quiet ones washed the loud one out. Measured
        // on a bass-only spectrum the light sat at height -0.16 where the band
        // it should occupy is nearer -0.6.
        lv = (lv * lv) >> 8;
        const int contrib = (w * lv) >> 8;
        if (contrib <= 0) continue;
        const int idx = 16 + (k * 223) / 15;   // inset: palette ends are often black
        if (refI < 0) refI = idx;
        accD += (int)(int8_t)(idx - refI) * contrib;      // circular-safe average
        wsum += contrib;
        acc += contrib;
      }
      lutIdx[h] = (uint8_t)(wsum ? (refI + accD / wsum) : 0);
      const int a = (acc * inject) >> 8;
      lutAmp[h] = (uint8_t)(a > 255 ? 255 : a);
    }
  }

  const uint8_t flash = (uint8_t)(s->splash >> 2);

  // --- transport ------------------------------------------------------------------
  for (int y = 0; y < rows; y++) {
    for (int x = 0; x < cols; x++) {
      if (cube && cfx_gap(x, y, B)) continue;
      const size_t i = (size_t)cfx_cidx(x, y, cols, B, cube);
      uint8_t out[3];

      if (cube) {
        const int u = cx[i] + 128, v = cy[i] + 128, w = cz[i] + 128;
        const uint16_t ka = (uint16_t)((u * sc) >> 2), kb = (uint16_t)((v * sc) >> 2),
                       kc = (uint16_t)((w * sc) >> 2);
        const int p0  = (int)perlin8((uint16_t)(ka + ox), (uint16_t)(kb + oy), (uint16_t)(kc + oz));
        const int pdx = (int)perlin8((uint16_t)(ka + ox + CFX_GRAD), (uint16_t)(kb + oy), (uint16_t)(kc + oz));
        const int pdy = (int)perlin8((uint16_t)(ka + ox), (uint16_t)(kb + oy + CFX_GRAD), (uint16_t)(kc + oz));
        const int pdz = (int)perlin8((uint16_t)(ka + ox), (uint16_t)(kb + oy), (uint16_t)(kc + oz + CFX_GRAD));
        const int gx = pdx - p0, gy = pdy - p0, gz = pdz - p0;

        int nrx = 0, nry = 0, nrz = 0;
        switch (cfx_faceOnly(cx[i], cy[i], cz[i])) {
          case 0:  nrx =  1; break;   case 1:  nrx = -1; break;
          case 2:  nry =  1; break;   case 3:  nry = -1; break;
          case 4:  nrz =  1; break;   default: nrz = -1; break;
        }
        // n x grad(psi) is divergence-free, so the flow folds the bands into
        // each other and never pumps them into a corner.
        int vx = (nry * gz - nrz * gy) * SB_CURL;
        int vy = (nrz * gx - nrx * gz) * SB_CURL;
        int vz = (nrx * gy - nry * gx) * SB_CURL;
        if (vx >  127) vx =  127; else if (vx < -127) vx = -127;
        if (vy >  127) vy =  127; else if (vy < -127) vy = -127;
        if (vz >  127) vz =  127; else if (vz < -127) vz = -127;

        int qx = (int)cx[i] - (vx * amp) / 128;
        int qy = (int)cy[i] - (vy * amp) / 128;
        int qz = (int)cz[i] - (vz * amp) / 128;
        if (qx >  512) qx =  512; else if (qx < -512) qx = -512;
        if (qy >  512) qy =  512; else if (qy < -512) qy = -512;
        if (qz >  512) qz =  512; else if (qz < -512) qz = -512;

        int f, a, b; cfx_face(qx, qy, qz, f, a, b);
        const int aq = (a + 128) * Bq, bq = (b + 128) * Bq;
        const int ai = aq >> 8, bi = bq >> 8;
        const uint8_t fa = ease8InOutCubic((uint8_t)(aq & 255));
        const uint8_t fb = ease8InOutCubic((uint8_t)(bq & 255));

        uint16_t t00 = cfx_rev(rev, Bq, f, ai,     bi);
        uint16_t t10 = cfx_rev(rev, Bq, f, ai + 1, bi);
        uint16_t t01 = cfx_rev(rev, Bq, f, ai,     bi + 1);
        uint16_t t11 = cfx_rev(rev, Bq, f, ai + 1, bi + 1);
        if (t00 == 0xFFFF) t00 = (uint16_t)i;
        if (t10 == 0xFFFF) t10 = t00;
        if (t01 == 0xFFFF) t01 = t00;
        if (t11 == 0xFFFF) t11 = t10;

        for (int c = 0; c < 3; c++) {
          const uint8_t c0 = cfx_lerp8(pix[(size_t)t00 * 3 + c], pix[(size_t)t10 * 3 + c], fa);
          const uint8_t c1 = cfx_lerp8(pix[(size_t)t01 * 3 + c], pix[(size_t)t11 * 3 + c], fa);
          out[c] = cfx_lerp8(c0, c1, fb);
        }
      } else {
        // Flat: the same fluid in the plane, with height running up the panel.
        const int u = (x * 255) / (cols - 1), v = (y * 255) / (rows - 1);
        const uint16_t ka = (uint16_t)((u * sc) >> 2), kb = (uint16_t)((v * sc) >> 2);
        const int p0  = (int)perlin8((uint16_t)(ka + ox), (uint16_t)(kb + oy));
        const int pdx = (int)perlin8((uint16_t)(ka + ox + CFX_GRAD), (uint16_t)(kb + oy));
        const int pdy = (int)perlin8((uint16_t)(ka + ox), (uint16_t)(kb + oy + CFX_GRAD));
        int vx =  (pdy - p0) * SB_CURL;
        int vy = -(pdx - p0) * SB_CURL;
        if (vx >  127) vx =  127; else if (vx < -127) vx = -127;
        if (vy >  127) vy =  127; else if (vy < -127) vy = -127;

        const int qxQ = (x << 8) - (vx * amp * 2);
        const int qyQ = (y << 8) - (vy * amp * 2);
        int ix = qxQ >> 8, iy = qyQ >> 8;
        const uint8_t fa = ease8InOutCubic((uint8_t)(qxQ & 255));
        const uint8_t fb = ease8InOutCubic((uint8_t)(qyQ & 255));
        const int ix1 = (((ix + 1) % cols) + cols) % cols, iy1 = (((iy + 1) % rows) + rows) % rows;
        ix = ((ix % cols) + cols) % cols;  iy = ((iy % rows) + rows) % rows;
        const size_t t00 = (size_t)iy  * cols + ix,  t10 = (size_t)iy  * cols + ix1;
        const size_t t01 = (size_t)iy1 * cols + ix,  t11 = (size_t)iy1 * cols + ix1;
        for (int c = 0; c < 3; c++) {
          const uint8_t c0 = cfx_lerp8(pix[t00 * 3 + c], pix[t10 * 3 + c], fa);
          const uint8_t c1 = cfx_lerp8(pix[t01 * 3 + c], pix[t11 * 3 + c], fa);
          out[c] = cfx_lerp8(c0, c1, fb);
        }
      }

      // --- fall to black, then print ------------------------------------------
      // Drip fades far more slowly than Bands, and it has to. Bands injects
      // continuously, so the fade is what stops it saturating - the two are in
      // balance every frame. Drip injects in occasional events with nothing at
      // all in between, so the same fade simply erases each drop before it has
      // been carried anywhere. At the shared rate the whole mode averaged a
      // brightness of one.
      // A third, not a quarter. A quarter was set when the only test signal was
      // the gated synthetic generator, where drops are genuinely rare; real
      // audio delivers many more and the field never got back to black - it
      // measured a mean of 84 at the default fade, which is washed out. A third
      // puts the DEFAULT slider position in the middle of the usable range on
      // real music. Measured against live audio the 140 default holds a quarter
      // of the surface dark, 90 holds a half, and 190 barely returns to black at
      // all - so the control sweeps from a lingering wash down to a sparse
      // scatter with the shipped setting between them. The absolute brightness
      // at each setting moves with the material and is not worth quoting; the
      // fraction of the surface that gets back to black is the stable number.
      const int fd = SEGMENT.check1 ? (fade > 2 ? fade / 3 : 1) : fade;
      for (int c = 0; c < 3; c++) out[c] = (out[c] > fd) ? (uint8_t)(out[c] - fd) : 0;

      // Height is cz on the cube and the row on a flat panel, so "frequency is
      // altitude" means the same thing in both.
      const int hh = cube ? ((int)cz[i] + 128)
                          : (255 - (y * 255) / (rows - 1));
      // Drops paint a soft sphere around where they landed. Distance is in
      // SURFACE coordinates, so a drop near an edge spills onto the next face
      // instead of stopping dead at the fold.
      if (nDrop) {
        for (int k = 0; k < nDrop; k++) {
          const int ddx = (int)cx[i] - dropX[k];
          const int ddy = (int)cy[i] - dropY[k];
          const int ddz = (int)cz[i] - dropZ[k];
          const int r2 = ddx * ddx + ddy * ddy + ddz * ddz;
          if (r2 >= dropR2) continue;
          const int t = 255 - (r2 * 255) / dropR2;
          const int w = ((t * t) >> 8) * (int)dropAmp[k] >> 8;
          if (w <= 0) continue;
          const uint32_t c = sb_dropColor(
              SEGMENT.color_from_palette(dropIdx[k], false, true, 0), 110);
          // Drops land hard. A gentle blend lets each new drop average with
          // whatever the flow has already smeared there, and a few rounds of
          // that is mud rather than colour.
          const int mix = w > 250 ? 250 : w;
          out[0] = cfx_lerp8(out[0], (uint8_t)((c >> 16) & 0xFF), (uint8_t)mix);
          out[1] = cfx_lerp8(out[1], (uint8_t)((c >>  8) & 0xFF), (uint8_t)mix);
          out[2] = cfx_lerp8(out[2], (uint8_t)( c        & 0xFF), (uint8_t)mix);
        }
      }

      const uint8_t aInj = lutAmp[hh & 0xFF];
      if (aInj) {
        // Painted TOWARD the band colour, not added to it. Adding saturates:
        // a pixel inside a band gains the full injection every frame and only
        // loses the fade, so all three channels climb to 255 within a second
        // and the cube goes white - measured, mean 110 with saturation at 67
        // and a tenth of the surface black, which is the opposite of an effect
        // that falls to black. A crossfade has an equilibrium instead: it
        // approaches the band colour while the fade pulls it down, and the two
        // settle. When the band goes quiet nothing holds it up and it decays.
        const uint32_t c = SEGMENT.color_from_palette(lutIdx[hh & 0xFF], false, true, 0);
        int mix = aInj + flash;
        if (mix > 235) mix = 235;               // never a hard replace
        out[0] = cfx_lerp8(out[0], (uint8_t)((c >> 16) & 0xFF), (uint8_t)mix);
        out[1] = cfx_lerp8(out[1], (uint8_t)((c >>  8) & 0xFF), (uint8_t)mix);
        out[2] = cfx_lerp8(out[2], (uint8_t)( c        & 0xFF), (uint8_t)mix);
      }
      nxt[i * 3 + 0] = out[0];
      nxt[i * 3 + 1] = out[1];
      nxt[i * 3 + 2] = out[2];
    }
  }
  memcpy(pix, nxt, 3 * m);

  // --- render ---------------------------------------------------------------------
  const uint8_t drive = cfx_drive(vol, 0.35f, 110);
  CFX_NET_PREP();
  size_t i = 0;
  for (int y = 0; y < rows; y++) {
    CFX_NET_ROW(y);
    for (int x = 0; x < cols; x++, i++) {
      CFX_NET_SKIP(x);
      const size_t ci = (size_t)cfx_cidx(x, y, cols, B, cube);
      SEGMENT.setPixelColorXY(x, y,
        mq_scale(RGBW32(sb_contrast(pix[ci * 3]),
                        sb_contrast(pix[ci * 3 + 1]),
                        sb_contrast(pix[ci * 3 + 2]), 0), drive));
    }
  }
  FX_DONE;
}

static const char _data_FX_MODE_SPECTRAL_BLOOM[] PROGMEM =
  // Fall to black defaults LOW on purpose. It is the control that decides
  // whether the spectrum is legible as altitude at all: colour injected at a
  // band is carried away by the flow, so a slow fade lets it wander the whole
  // cube before it dies. Measured as the height difference between a
  // treble-only and a bass-only spectrum, separation peaks around 90-140 and
  // collapses to nothing - and past 200 actually INVERTS - as the fade slows.
  "Ace 3-D Spectral Bloom@Flow,Inject,Density,Fall to black,Size,Drip,Beat flash,Flat mode;;!;2f;sx=128,ix=255,c1=140,c2=140,c3=10,o2=1,pal=11";


// ---------------------------------------------------------------------------
// Registration - joins the effect bank, which decides whether this effect
// claims one of the device's limited effect slots. See cube_fx_bank.h.
// ---------------------------------------------------------------------------
static CfxBankReg cube_fx_30_spectral_bloom_reg(&mode_spectral_bloom,
                                                _data_FX_MODE_SPECTRAL_BLOOM);
