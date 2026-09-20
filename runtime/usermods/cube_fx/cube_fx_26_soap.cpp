#include "wled.h"
#include "cube_fx_common.h"
#include "cube_fx_bank.h"

// ===========================================================================
// 26. ACE 3-D SOAP
// ===========================================================================
// Wide swaths of colour sliding over the whole cube, folding into each other
// like oil on water. A port of WLED's Soap, and deliberately a close one: the
// first attempt reinvented too much and lost the look entirely.
//
// ---------------------------------------------------------------------------
// WHAT ACTUALLY MAKES SOAP LOOK LIKE SOAP
// ---------------------------------------------------------------------------
// Reading the original rather than remembering it, four things carry the look,
// and all four matter:
//
//   1. COLOUR LIVES IN A BUFFER AND IS ONLY EVER MOVED - never recomputed from
//      position and time. Transported colour remembers where it has been, so it
//      stretches and folds; recomputed colour always reads as a pattern playing.
//
//   2. THE DISPLACEMENT IS LARGE AND COHERENT. The original drags a whole row
//      by up to twenty pixels at once, and the row beside it by nearly the same
//      amount, because the amount comes from a very low frequency noise field.
//      Big neighbouring regions therefore move together. THIS is what makes the
//      swaths wide - not the palette, and not the detail in the noise.
//
//   3. THE SAMPLING IS SUB-PIXEL. Colour is read between pixels and blended, so
//      motion is continuous instead of a grid of jumps. Nearest-pixel sampling
//      of a colour field re-quantises it every frame and grinds smooth
//      gradients into mush within seconds.
//
//   4. FRESH COLOUR KEEPS ARRIVING, AND FAR FASTER THAN IT LOOKS. In the flat
//      original it enters wherever a shift reads past the edge of the panel, and
//      those pixels are REPLACED outright, not blended - about a quarter of the
//      panel every frame at default Density. A cube surface is closed, with no
//      edge for colour to enter through, so here every pixel crossfades toward a
//      palette colour drawn from a slowly morphing noise field instead. The rate
//      has to be comparable, though: transport plus interpolation is a mixer,
//      and anything that stirs will go uniform unless fresh pigment arrives as
//      fast as the stirring blends it away.
//
// ---------------------------------------------------------------------------
// WHY THE FIRST ATTEMPT LOOKED WRONG
// ---------------------------------------------------------------------------
// Worth recording, because it violated three of those four. Displacement was
// about ONE pixel per frame rather than many, so nothing ever gathered into a
// swath. Sampling was nearest-pixel through a lookup table, so the field ground
// itself down. Several percent of cells were hard-overwritten with fresh noise
// every frame, shredding what structure survived. And the stored palette index
// was multiplied before lookup, wrapping the palette several times over and
// turning what should have been broad areas into fine rainbow banding.
//
// ---------------------------------------------------------------------------
// FLOW IN 3D, SO THE FOLDS DO NOT EXIST
// ---------------------------------------------------------------------------
// Shearing rows and columns is meaningless on a folded net - a row crosses
// three faces at two right angles. So the displacement here is a 3D vector
// field sampled at each pixel's position in space. Being a smooth function of
// 3D position it agrees across every fold for free: a swath slides off the lid
// and continues down a wall, because in the space the flow lives in there is no
// wall, only the surface of a cube.
//
// Reading colour back from an arbitrary surface point needs a reverse lookup,
// built once at start-up: every pixel is filed by which face it sits on (its
// dominant axis) and where on that face. A sample that runs off the edge of a
// face is turned back into a 3D point, which then classifies onto the
// neighbour - so a bilinear tap straddling a fold reads the right pixels on
// both sides of it.
//
// Speed, Smoothness and Density keep the meanings they have in the original.
// ===========================================================================

#ifndef SP_CURL
  #define SP_CURL 6                 // gain from that gradient to flow units
#endif

struct SoapState {
  uint8_t  mode;
  // Q8. The clocks are fractional because the slider now reaches speeds BELOW
  // one noise unit per frame, and at whole-unit resolution "slower than 1" is
  // simply not a representable number - it rounds to 1 or to stopped.
  uint32_t nx, ny, nz;              // potential-field time coords, Q8
  uint32_t ct;                      // colour-source noise time, Q8
  uint8_t  splash;                  // beat envelope for the colour refresh
  uint8_t  bassEnv;                 // bass envelope, also drives colour
  uint8_t  clk[2];
};

// The surface-topology helpers this used to carry privately - face
// classification, the fold-following reverse lookup and the symmetric lerp -
// now live in cube_fx_common.h as cfx_face/cfx_unface/cfx_rev/cfx_lerp8, so
// Spectral Fountain can share them rather than own a second copy. A private
// index helper went with them: it was byte-for-byte the cube branch of
// cfx_cidx, which had been added to the common header later without this file
// ever being updated to use it.

// Push the tones back apart on the way out.
//
// Transport plus interpolation is a mixer, and the first thing a mixer takes is
// the EXTREMES. Measured against the original: WLED's Soap keeps about a
// quarter of its pixels near black and a twentieth genuinely hot, while this
// held 1% and 0% with more than half of everything piled into a single mid
// band. That missing range IS the readability - the dark gaps are what let the
// eye find where one swath stops and the next starts, and without them a
// correct simulation of flowing colour still reads as flat.
//
// ease8InOutCubic is a smoothstep: it moves values away from the middle and
// leaves the two ends where they are, which is the exact inverse of what the
// blending did. Applied per channel it deepens the darks and lets highlights
// climb without shifting hue appreciably.
// Applied twice, at full strength. Once was not close: it moved near-black from
// 1% of the cube to 6% where the original sits at 24%, because a single
// smoothstep only nudges values that the mixing had already dragged well into
// the middle. Two passes bite hard enough on the mid band to open real gaps
// without touching either end.
static inline uint8_t sp_contrast(uint8_t v) {
  return ease8InOutCubic(ease8InOutCubic(v));
}

static FX_RET mode_soap() {
  if (!strip.isMatrix || !SEGMENT.is2D()) { SEGMENT.fill(SEGCOLOR(0)); FX_DONE; }
  const int cols = SEG_W, rows = SEG_H;
  if (cols < 8 || rows < 8) { SEGMENT.fill(SEGCOLOR(0)); FX_DONE; }
  const size_t n = (size_t)cols * rows;

  const bool cube = cfx_isCube(cols, rows);
  const int  B   = cube ? (cols / 3) : 1;
  const int  Bq   = cube ? B : 1;
  const size_t lut = cube ? (size_t)6 * Bq * Bq : 0;

  // Everything below is sized to the LIT pixels only - see cfx_cidx().
  const size_t m = cube ? (size_t)cfx_faces() * B * B : n;

  const size_t need = sizeof(SoapState) + 3 * m      // surface coords
                    + 3 * m + 3 * m                  // colour buffer + next
                    + m                              // colour-source noise
                    + lut * sizeof(uint16_t);
  if (!SEGENV.allocateData(need)) { SEGMENT.fill(SEGCOLOR(0)); FX_DONE; }

  SoapState *s  = (SoapState *)SEGENV.data;
  int8_t   *cx  = (int8_t *)(s + 1);
  int8_t   *cy  = cx + m;
  int8_t   *cz  = cy + m;
  uint8_t  *pix = (uint8_t *)(cz + m);       // rgb triplets - the transported field
  uint8_t  *nxt = pix + 3 * m;
  uint8_t  *nz3 = nxt + 3 * m;               // smoothed noise: the colour source
  uint16_t *rev = (uint16_t *)(nz3 + m);

  const uint8_t want = (uint8_t)(cube ? 1 : 2);
  const bool init = (SEGENV.call == 0 || s->mode != want);
  if (init) {
    s->mode = want; s->splash = 0; s->bassEnv = 0; s->clk[0] = s->clk[1] = 0;
    s->nx = (uint32_t)hw_random16() << 8; s->ny = (uint32_t)hw_random16() << 8;
    s->nz = (uint32_t)hw_random16() << 8; s->ct = (uint32_t)hw_random16() << 8;

    if (cube) {
      // cfx_buildCube writes one entry per RECTANGLE pixel, so it wants 3n
      // bytes - more than the compacted coord arrays hold. pix and nxt are
      // adjacent and together give 6m, and 2m >= n always holds for a net
      // (10*B^2 >= 9*B^2), so they stand in as scratch before either holds any
      // colour. Both are fully rewritten below, so nothing survives the loan.
      int8_t *sc = (int8_t *)pix;
      cfx_buildCube(sc, sc + n, sc + 2 * n, nullptr, nullptr, cols, rows, cube);
      for (int y = 0; y < rows; y++)
        for (int x = 0; x < cols; x++) {
          if (cfx_gap(x, y, B)) continue;     // gap corner: no storage
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
          rev[((size_t)f * Bq + bi) * Bq + ai] = (uint16_t)ci;   // compact index
        }
    } else {
      cfx_buildCube(cx, cy, cz, nullptr, nullptr, cols, rows, cube);
    }
  }

  uint16_t dt = fx_dt8(s->clk);
  if (dt > 60) dt = 60;

  // --- audio ------------------------------------------------------------------
  um_data_t     *um  = cfx_getAudioData();
  const float    vol = *(float *)um->u_data[0];
  const uint8_t *fft = (uint8_t *)um->u_data[2];
  int bass, mid, treb; cfx_bands(fft, bass, mid, treb);
  const uint8_t beat = SEGMENT.check2 ? fx_lowBeat(um) : 0;
  if (beat > s->splash) s->splash = beat;
  { const int f = (int)s->splash - (int)fx_step(7, dt);
    s->splash = (uint8_t)(f < 0 ? 0 : f); }
  s->bassEnv = fx_env(s->bassEnv, (uint8_t)bass, dt, 260);

  // --- parameters ---------------------------------------------------------------
  // Scale is the size of a swath. Deliberately coarse - perlin8 repeats every
  // 256 units, so spanning the whole cube in well under one period is what lays
  // a single broad gradient across several faces instead of a fine mottle.
  const int sc = 2 + (((int)SEGMENT.custom2 * 12) >> 8);       // 2..14 (~0.5..3.5 periods)

  // Density is the displacement, in PIXELS, that a full-swing flow value drags
  // colour each frame. Large on purpose: this is point 2 above, and the single
  // biggest reason the first attempt had no swaths in it.
  const int pixAmp = 2 + (((int)SEGMENT.custom1 * 12) >> 8);   // 2..14 pixels
  const int amp = cube ? ((254 / (B > 0 ? B : 1)) * pixAmp) : pixAmp;

  // Speed, recentred so the setting worth living on sits in the MIDDLE of the
  // slider instead of pinned against its floor.
  //
  //     slider   0  ->  0.125 units/frame   (eight times slower than the middle)
  //     slider 128  ->  1.0                  the old bottom end, and the default
  //     slider 255  -> 16.0                  faster than the old top end of 14
  //
  // Linear below the middle so the slow half stays controllable, and quadratic
  // above it so the top half genuinely accelerates rather than creeping.
  const int sp = SEGMENT.speed;
  int32_t flowQ;                                               // Q8 units/frame
  if (sp <= 128) {
    flowQ = 32 + ((int32_t)(256 - 32) * sp) / 128;
  } else {
    const int32_t t = sp - 128;                                // 0..127
    flowQ = 256 + ((int32_t)3840 * t * t) / (127 * 127);
  }
  if (SEGMENT.check1) flowQ += ((int32_t)s->bassEnv * 384) / 255;   // Bass drive
  flowQ += ((int32_t)s->splash * 512) / 255;                   // beats nudge it on

  const int32_t adv = (flowQ * (int32_t)dt) / 23;
  s->nx += (uint32_t)adv;
  s->ny += (uint32_t)((adv * 3) / 4);
  s->nz += (uint32_t)((adv * 5) / 4);
  s->ct += (uint32_t)((adv + 1) / 2);

  // Whole-unit offsets for sampling, taken once.
  const uint16_t ox = (uint16_t)(s->nx >> 8), oy = (uint16_t)(s->ny >> 8),
                 oz = (uint16_t)(s->nz >> 8), oc = (uint16_t)(s->ct >> 8);

  const uint8_t smooth = (uint8_t)MIN(250, (int)SEGMENT.intensity);   // Smoothness

  // How hard each pixel crossfades toward fresh palette colour.
  //
  // This is the counterweight to the mixing, and it has to be much heavier than
  // it looks. The original fully REPLACES every pixel whose source read past the
  // edge of the panel - at default Density that is roughly an eighth of each row
  // per pass and two passes a frame, so about a quarter of the cube is repainted
  // with saturated palette colour every single frame. A 1% bleed, which is what
  // this was, loses that race badly: the field looked right for a few seconds
  // and then stirred itself into uniform grey with nothing arriving to stop it.
  // The audio now spends itself HERE rather than on brightness. Driving the
  // level was a poor use of it - the swing was invisible next to the colour, and
  // it fought the effect for headroom. Pushing pigment in instead is something
  // you can actually see: bass keeps fresh colour arriving, beats throw a
  // slug of it across the whole net at once.
  int refresh = 8 + (((int)cfx_c3full(SEGMENT.custom3) * 72) >> 8);        // 3%..31% per frame
  if (SEGMENT.check1) refresh += (int)s->bassEnv >> 3;         // Bass drive
  refresh += (int)s->splash >> 2;                              // Beat splash
  if (refresh > 120) refresh = 120;

  // --- the colour source: a slowly morphing noise field -------------------------
  for (int y = 0; y < rows; y++) {
    for (int x = 0; x < cols; x++) {
      if (cube && cfx_gap(x, y, B)) continue;      // gap: no storage
      const size_t ci = cube ? (size_t)cfx_cidx(x, y, cols, B, cube) : (size_t)y * cols + x;
      const int u = cube ? (cx[ci] + 128) : ((x * 255) / (cols - 1));
      const int v = cube ? (cy[ci] + 128) : ((y * 255) / (rows - 1));
      const int w = cube ? (cz[ci] + 128) : 0;
      const uint8_t d = perlin8((uint16_t)(((u * sc) >> 2) + oc),
                                (uint16_t)((v * sc) >> 2),
                                (uint16_t)(((w * sc) >> 2) + 700));
      nz3[ci] = init ? d
                     : (uint8_t)(scale8(nz3[ci], smooth) + scale8(d, (uint8_t)(255 - smooth)));
    }
  }

  if (init) {                                     // open already marbled
    for (size_t k = 0; k < m; k++) {
      const uint32_t c = SEGMENT.color_from_palette((uint8_t)((uint8_t)(~nz3[k]) * 3), false, true, 0);
      pix[k * 3 + 0] = (uint8_t)((c >> 16) & 0xFF);
      pix[k * 3 + 1] = (uint8_t)((c >>  8) & 0xFF);
      pix[k * 3 + 2] = (uint8_t)( c        & 0xFF);
    }
  }

  // --- transport ------------------------------------------------------------------
  for (int y = 0; y < rows; y++) {
    for (int x = 0; x < cols; x++) {
      if (cube && cfx_gap(x, y, B)) continue;     // gap: no storage
      const size_t i = cube ? (size_t)cfx_cidx(x, y, cols, B, cube) : (size_t)y * cols + x;

      uint8_t out[3];

      if (cube) {
        const int u = cx[i] + 128, v = cy[i] + 128, w = cz[i] + 128;
        const uint16_t ka = (uint16_t)((u * sc) >> 2), kb = (uint16_t)((v * sc) >> 2),
                       kc = (uint16_t)((w * sc) >> 2);
        // Curl of a scalar potential, which is what actually swirls.
        //
        // Three independent noise channels give a GENERAL vector field: it has
        // sources and sinks, so colour pools in some places and drains out of
        // others, and the motion reads as blobby drift. The original has no such
        // thing. Shifting every row by an amount that varies with y and then
        // every column by an amount that varies with x composes into ROTATION -
        // that is where its swirl comes from, and it is not something three
        // unrelated channels reproduce.
        //
        // n x grad(psi) is divergence-free by construction, so nothing pools,
        // and the flow circulates around the peaks and troughs of psi. Four
        // samples instead of three buys the whole character.
        const int p0  = (int)perlin8((uint16_t)(ka + ox), (uint16_t)(kb + oy), (uint16_t)(kc + oz));
        const int pdx = (int)perlin8((uint16_t)(ka + ox + CFX_GRAD), (uint16_t)(kb + oy), (uint16_t)(kc + oz));
        const int pdy = (int)perlin8((uint16_t)(ka + ox), (uint16_t)(kb + oy + CFX_GRAD), (uint16_t)(kc + oz));
        const int pdz = (int)perlin8((uint16_t)(ka + ox), (uint16_t)(kb + oy), (uint16_t)(kc + oz + CFX_GRAD));
        const int gx = pdx - p0, gy = pdy - p0, gz = pdz - p0;

        int nrx = 0, nry = 0, nrz = 0;              // outward face normal
        switch (cfx_faceOnly(cx[i], cy[i], cz[i])) {
          case 0:  nrx =  1; break;   case 1:  nrx = -1; break;
          case 2:  nry =  1; break;   case 3:  nry = -1; break;
          case 4:  nrz =  1; break;   default: nrz = -1; break;
        }
        int vx = (nry * gz - nrz * gy) * SP_CURL;
        int vy = (nrz * gx - nrx * gz) * SP_CURL;
        int vz = (nrx * gy - nry * gx) * SP_CURL;
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
        // Smoothstep the blend weights, exactly as the original does. Straight
        // bilinear averages four neighbours every frame, and since the flow also
        // STRETCHES colour into thin filaments, that average is a mixer: stir
        // long enough and every hue meets every other one, which is why it went
        // uniform - and brighter, because averaging red with green gives yellow.
        // Easing pushes the weights toward 0 and 1 so the resample stays close
        // to a straight copy, keeping the motion smooth without the blur.
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
        // Flat: the same transport in the plane, which is what Soap always was.
        const int u = (x * 255) / (cols - 1), v = (y * 255) / (rows - 1);
        const uint16_t ka = (uint16_t)((u * sc) >> 2), kb = (uint16_t)((v * sc) >> 2);
        // Same trick in the plane: rotating the gradient of a potential by 90
        // degrees gives a divergence-free field, so it circulates instead of
        // pooling.
        const int p0  = (int)perlin8((uint16_t)(ka + ox), (uint16_t)(kb + oy));
        const int pdx = (int)perlin8((uint16_t)(ka + ox + CFX_GRAD), (uint16_t)(kb + oy));
        const int pdy = (int)perlin8((uint16_t)(ka + ox), (uint16_t)(kb + oy + CFX_GRAD));
        int vx =  (pdy - p0) * SP_CURL;
        int vy = -(pdx - p0) * SP_CURL;
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

      // Fresh colour bleeds in everywhere, because a closed surface offers no
      // edge for it to enter through.
      const uint32_t fr = SEGMENT.color_from_palette((uint8_t)((uint8_t)(~nz3[i]) * 3), false, true, 0);
      nxt[i * 3 + 0] = cfx_lerp8(out[0], (uint8_t)((fr >> 16) & 0xFF), (uint8_t)refresh);
      nxt[i * 3 + 1] = cfx_lerp8(out[1], (uint8_t)((fr >>  8) & 0xFF), (uint8_t)refresh);
      nxt[i * 3 + 2] = cfx_lerp8(out[2], (uint8_t)( fr        & 0xFF), (uint8_t)refresh);
    }
  }
  memcpy(pix, nxt, 3 * m);

  // --- render ---------------------------------------------------------------------
  // Volume drives real dynamics rather than a token wobble. A floor of 190 with
  // 0.8 gain reached the 255 ceiling the moment volume passed 81 - which on
  // music is essentially always - so it never reacted at all, it just held the
  // whole effect at full brightness with a 75% floor under it in silence. These
  // numbers never saturate, so loud really is brighter than quiet, and quiet has
  // somewhere dark to go. It matters more here than in most effects: Soap paints
  // every pixel a saturated palette colour, so with nothing pulling the level
  // down the cube is a wall of full-brightness hues.
  const uint8_t drive = cfx_drive(vol, 0.35f, 102);
  CFX_NET_PREP();
  size_t i = 0;
  for (int y = 0; y < rows; y++) {
    CFX_NET_ROW(y);
    for (int x = 0; x < cols; x++, i++) {
      CFX_NET_SKIP(x);
      const size_t ci = cube ? (size_t)cfx_cidx(x, y, cols, B, cube) : i;
      SEGMENT.setPixelColorXY(x, y,
        mq_scale(RGBW32(sp_contrast(pix[ci * 3]),
                        sp_contrast(pix[ci * 3 + 1]),
                        sp_contrast(pix[ci * 3 + 2]), 0), drive));
    }
  }
  FX_DONE;
}

static const char _data_FX_MODE_SOAP[] PROGMEM =
  "Ace 3-D Soap@!,Smoothness,Density,Scale,Splash,Bass drive,Beat splash,Flat mode;;!;2f;sx=128,ix=200,c1=140,c2=90,c3=15,o1=1,o2=1,pal=11";


// ---------------------------------------------------------------------------
// Registration - joins the effect bank, which decides whether this effect
// claims one of the device's limited effect slots. See cube_fx_bank.h.
// ---------------------------------------------------------------------------
static CfxBankReg cube_fx_26_soap_reg(&mode_soap, _data_FX_MODE_SOAP);
