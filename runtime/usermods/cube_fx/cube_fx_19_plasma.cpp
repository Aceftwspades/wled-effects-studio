#include "wled.h"
#include "cube_fx_audio.h"
#include "cube_fx_bank.h"

// ===========================================================================
// 19. ACE 3-D PLASMA
// ===========================================================================
// The demoscene plasma, rebuilt as a spectrum analyser you can't read.
//
// A plasma is nothing but a sum of sine waves sampled over a surface. That is
// also, exactly, what a spectrum is - so instead of drawing the FFT as bars
// and calling it audio-reactive, this hands each band ONE WAVE and lets the
// interference do the work:
//
//   layer A   low  spatial frequency   amplitude <- BASS envelope
//   layer B   x1.6 that                amplitude <- MID  envelope
//   layer C   x2.9 that                amplitude <- TREBLE envelope
//
// The ratios are deliberately irrational-ish (13/8, 23/8). Whole-number
// ratios lock into a repeating tile within a second or two and the whole
// thing reads as wallpaper; these never quite line up, so the pattern keeps
// finding new shapes for as long as you leave it running.
//
// Because the amplitudes are the band envelopes, a bass-only passage is three
// slow rolling bands, a busy mix is a boiling interference field, and silence
// collapses it to a nearly still gradient. The music is not decorating the
// pattern - it IS the pattern's spectrum.
//
// ---------------------------------------------------------------------------
// WHY THE COORDINATES ARE NORMALISED ON THE CUBE
// ---------------------------------------------------------------------------
// Every other cube effect samples cfx_buildCube()'s raw surface position, where
// a face sits at +/-127 and a corner is sqrt(3) further from the centre than a
// face centre is. Feed that to a plane wave and the wavelength stretches by up
// to 73% as you cross a fold - fine for noise, obvious for a clean sine.
//
// So this file builds its own LUT: the same surface points PROJECTED ONTO THE
// UNIT SPHERE. Every wave then has a constant wavelength measured in ANGLE, so
// the bands are the same width on a face centre, over an edge, and at a corner.
// Beat ripples become true geodesic rings for the same reason, and they cost
// one dot product each instead of a distance.
//
// On a flat panel the projection would be catastrophic - normalising a plane
// collapses every pixel onto the unit circle and you get radial spokes - so
// flat mode keeps the raw X,Y and Z stays 0. Same generator, textbook 2D
// plasma.
//
// ---------------------------------------------------------------------------
// DOMAIN WARP
// ---------------------------------------------------------------------------
// A plain sum of plane waves is a plaid, not a plasma. The liquid look comes
// from a fourth, very slow wave that is not drawn: its value is added to the
// ARGUMENTS of layers B and C, so the two fast layers are dragged back and
// forth through the slow one's field. That is domain warping, it costs one
// extra dot product, and it is the difference between "interference pattern"
// and "something alive".
//
// The same warp wave drives a gentle luminance roll, so the field has bright
// and dark regions instead of being uniformly lit everywhere.
//
// ---------------------------------------------------------------------------
// CONTROLS
// ---------------------------------------------------------------------------
//   Flow          how fast the layers march. Each layer moves at its own rate
//                 and layer B moves BACKWARDS, so they beat against each other.
//   Glow          overall brightness floor. Volume rides on top of it.
//   Scale         spatial zoom: ~0.4 to ~3 wavelengths across the cube.
//   Warp          domain-warp depth. 0 = plaid, 255 = molten.
//   Audio depth   how much of each layer's amplitude the band owns. At 0 the
//                 three layers are equal and fixed (a pretty, deaf plasma); at
//                 255 a band that is silent removes its layer completely.
//   Beat ripples  each kick launches a geodesic ring from a random point on the
//                 surface. It does not draw a circle - it bends the plasma's
//                 phase as it passes, so the field bulges and snaps back.
//   Tone colour   palette offset follows cfx_brightness() (spectral centroid)
//                 instead of drifting on a clock, so colour tracks TIMBRE: a
//                 filter sweep walks the palette even at constant volume.
//   Flat mode     force the plane on a square flat panel.
//
// Time (not amplitude) is scaled by cfx_drop().speedScale, so the whole field
// slows through a riser and surges under a held bass note.
// ---------------------------------------------------------------------------

// --- tunables (all -D overridable) -----------------------------------------
#ifndef PL_RINGS
  #define PL_RINGS 3           // concurrent beat ripples
#endif
#ifndef PL_RING_MS
  #define PL_RING_MS 950       // ms for a ripple to cross the whole surface
#endif
#ifndef PL_RING_WIDTH
  #define PL_RING_WIDTH 44     // ripple thickness, in dot-product units
#endif
#ifndef PL_RING_WARP
  #define PL_RING_WARP 80      // how hard a ripple bends the phase at full strength
#endif
#ifndef PL_RING_LUM
  #define PL_RING_LUM 85       // how much a ripple brightens as it passes
#endif
#ifndef PL_BASS_MS
  #define PL_BASS_MS 280       // band envelope release times
#endif
#ifndef PL_MID_MS
  #define PL_MID_MS 210
#endif
#ifndef PL_TREB_MS
  #define PL_TREB_MS 150
#endif
#ifndef PL_LUM_SWING
  #define PL_LUM_SWING 70      // luminance roll from the warp layer
#endif
#ifndef PL_HUE_RATE
  #define PL_HUE_RATE 6        // palette drift when Tone colour is off
#endif
// How much level the gaps between bands lose, 0..255. 0 = flat wash (no
// negative space), 255 = gaps go fully black. Applied as a MULTIPLIER on the
// level rather than a subtraction, so raising it deepens the gaps without ever
// pushing the band cores past 255 - see the note at the pixel loop.
#ifndef PL_BAND_DEPTH
  #define PL_BAND_DEPTH 200
#endif

// state block, after the three coordinate LUTs
#define PL_ST_MODE 0
#define PL_ST_CLK  1           // + 2, fx_dt8
#define PL_ST_RR   3           // round robin for ripple slots
#define PL_ST_BASS 4
#define PL_ST_MID  5
#define PL_ST_TREB 6
#define PL_ST_BEAT 7
#define PL_ST_RING 8           // PL_RINGS x (ox, oy, oz, age, strength)
#define PL_ST_LEN  (PL_ST_RING + PL_RINGS * 5)

// ---------------------------------------------------------------------------
// The one piece of geometry this effect owns: surface direction per pixel.
// Cube -> unit sphere (constant wavelength in angle). Flat -> raw plane.
// Runs once per segment, so floats are fine.
// ---------------------------------------------------------------------------
static void pl_buildDir(int8_t *nx, int8_t *ny, int8_t *nz,
                        int cols, int rows, bool cube) {
  const int B = cube ? (cols / 3) : 1;
  for (int y = 0; y < rows; y++) {
    for (int x = 0; x < cols; x++) {
      const size_t i = (size_t)y * cols + x;
      float X, Y, Z;
      cfx_pos(x, y, cols, rows, B, cube, X, Y, Z);
      if (cube) {
        const float len = sqrtf(X * X + Y * Y + Z * Z);
        const float s   = (len > 0.001f) ? (1.0f / len) : 0.0f;
        nx[i] = cfx_clamp8(X * s);
        ny[i] = cfx_clamp8(Y * s);
        nz[i] = cfx_clamp8(Z * s);
      } else {
        nx[i] = cfx_clamp8(X);
        ny[i] = cfx_clamp8(Y);
        nz[i] = 0;
      }
    }
  }
}

// A wave vector from two angles: azimuth a, elevation b. Components come out
// on a -128..127 scale, which is what the >>7 in the pixel loop expects.
static inline void pl_aim(uint8_t a, uint8_t b, int &kx, int &ky, int &kz) {
  const int ca = (int)cos8_t(a) - 128, sa = (int)sin8_t(a) - 128;
  const int cb = (int)cos8_t(b) - 128, sb = (int)sin8_t(b) - 128;
  kx = (cb * ca) >> 7;
  ky = (cb * sa) >> 7;
  kz = sb;
}

static FX_RET mode_ace_plasma() {
  if (!strip.isMatrix || !SEGMENT.is2D()) { SEGMENT.fill(SEGCOLOR(0)); FX_DONE; }
  const int cols = SEG_W, rows = SEG_H;
  if (cols < 4 || rows < 4) { SEGMENT.fill(SEGCOLOR(0)); FX_DONE; }
  const size_t n = (size_t)cols * rows;
  if (!SEGENV.allocateData(16 + 3 * n + PL_ST_LEN)) { SEGMENT.fill(SEGCOLOR(0)); FX_DONE; }

  int16_t *ph = (int16_t *)SEGENV.data;    // [0..3] layer phase  [4..5] aim  [6] hue
  int8_t  *nx = (int8_t *)(ph + 8);
  int8_t  *ny = nx + n;
  int8_t  *nz = ny + n;
  uint8_t *st = (uint8_t *)(nz + n);

  const bool cube = cfx_isCube(cols, rows);
  const int  B    = cube ? (cols / 3) : 1;

  const uint8_t want = (uint8_t)(cube ? 1 : 2);
  if (SEGENV.call == 0 || st[PL_ST_MODE] != want) {
    pl_buildDir(nx, ny, nz, cols, rows, cube);
    for (int k = 0; k < 8; k++)         ph[k] = 0;
    for (int k = 0; k < PL_ST_LEN; k++) st[k] = 0;
    st[PL_ST_MODE] = want;
  }

  // --- audio -----------------------------------------------------------------
  // Envelopes and detectors run on REAL time (dtRaw); only the layer phases run
  // on musical time (dt), so a surge speeds the field up without also making
  // every envelope decay faster.
  um_data_t     *um  = cfx_getAudioData();
  const uint8_t *fft = (uint8_t *)um->u_data[2];
  const float    vol = *(float *)um->u_data[0];
  int bass, mid, treb;
  cfx_bands(fft, bass, mid, treb);

  const CfxTempoState &tempo = cfx_tempo(um);
  const CfxDropState  &drop  = cfx_drop(um, tempo);

  const uint16_t dtRaw = fx_dt8(st + PL_ST_CLK);
  const uint16_t dt    = cfx_dropDt(dtRaw, drop.speedScale);

  st[PL_ST_BASS] = fx_env(st[PL_ST_BASS], (uint8_t)bass, dtRaw, PL_BASS_MS);
  st[PL_ST_MID]  = fx_env(st[PL_ST_MID],  (uint8_t)mid,  dtRaw, PL_MID_MS);
  st[PL_ST_TREB] = fx_env(st[PL_ST_TREB], (uint8_t)treb, dtRaw, PL_TREB_MS);
  st[PL_ST_BEAT] = fx_env(st[PL_ST_BEAT], tempo.hit,     dtRaw, 240);

  // --- clocks ----------------------------------------------------------------
  // Layer B runs backwards on purpose: two waves travelling the same way just
  // slide, two travelling against each other interfere, and interference is
  // the entire visual.
  const int32_t sp = 3 + (SEGMENT.speed >> 3);
  ph[0] = (int16_t)(ph[0] + (int16_t)fx_step(sp * 12, dt));
  ph[1] = (int16_t)(ph[1] - (int16_t)fx_step(sp * 17, dt));
  ph[2] = (int16_t)(ph[2] + (int16_t)fx_step(sp * 23, dt));
  ph[3] = (int16_t)(ph[3] + (int16_t)fx_step(sp *  7, dt));
  ph[4] = (int16_t)(ph[4] + (int16_t)fx_step(sp *  3, dt));   // aim drift
  ph[5] = (int16_t)(ph[5] + (int16_t)fx_step(sp *  2, dt));
  ph[6] = (int16_t)(ph[6] + (int16_t)fx_step(PL_HUE_RATE * 8, dt));

  // --- wave vectors ----------------------------------------------------------
  // Two slowly drifting aim angles, sampled at four fixed offsets. The offsets
  // keep the four layers pointing in genuinely different directions forever,
  // without needing four independent rotations.
  const uint8_t a0 = (uint8_t)((uint16_t)ph[4] >> 8);
  const uint8_t b0 = (uint8_t)((uint16_t)ph[5] >> 8);
  int kAx, kAy, kAz, kBx, kBy, kBz, kCx, kCy, kCz, kWx, kWy, kWz;
  pl_aim(a0,               b0,               kAx, kAy, kAz);
  pl_aim((uint8_t)(a0+85), (uint8_t)(b0+40), kBx, kBy, kBz);
  pl_aim((uint8_t)(a0+170),(uint8_t)(b0+210),kCx, kCy, kCz);
  pl_aim((uint8_t)(b0+64), (uint8_t)(a0+128),kWx, kWy, kWz);

  // --- spatial frequencies ---------------------------------------------------
  // The pixel loop forms its angle as (dot * f) >> 5 over a dot range of +/-127,
  // so one full wavelength costs f = 32. In other words f/32 is the number of
  // wavelengths across the cube's diameter, and the ceiling below is set by the
  // FACE, not the slider: at 16 px across a face, layer C's 2.9x ratio is
  // already near Nyquist by f = 60, and past that a plasma turns to speckle.
  const int f  = 8 + (((int)SEGMENT.custom1 * 13) >> 6);       // ~0.25 .. 1.8 cycles
  const int fA = f;
  const int fB = (f * 13) >> 3;
  const int fC = (f * 23) >> 3;
  const int fW = (f *  5) >> 3;

  const uint8_t pA = (uint8_t)((uint16_t)ph[0] >> 8);
  const uint8_t pB = (uint8_t)((uint16_t)ph[1] >> 8);
  const uint8_t pC = (uint8_t)((uint16_t)ph[2] >> 8);
  const uint8_t pW = (uint8_t)((uint16_t)ph[3] >> 8);

  // --- layer amplitudes ------------------------------------------------------
  // dep = 0: three equal fixed layers. dep = 255: a band that isn't playing
  // takes its layer away entirely.
  const int dep  = cfx_c3full(SEGMENT.custom3);
  const int keep = 255 - dep;
  const int ampA = keep + (((int)st[PL_ST_BASS] * dep) >> 8);
  const int ampB = keep + (((int)st[PL_ST_MID]  * dep) >> 8);
  int       ampC = keep + (((int)st[PL_ST_TREB] * dep) >> 8);
  ampC = (ampC * 3) >> 2;                       // finest layer, kept in its place
  const int tot  = ampA + ampB + ampC + 1;
  const int inv  = 65536 / tot;                 // reciprocal: no per-pixel divide

  const int warpD = SEGMENT.custom2;            // domain-warp depth

  // --- beat ripples ----------------------------------------------------------
  if (SEGMENT.check1 && tempo.hit) {
    int slot = -1;
    for (int k = 0; k < PL_RINGS; k++)
      if (!st[PL_ST_RING + k * 5 + 4]) { slot = k; break; }
    if (slot < 0) { slot = st[PL_ST_RR] % PL_RINGS; st[PL_ST_RR]++; }
    uint8_t *e = st + PL_ST_RING + slot * 5;
    int ox, oy, oz;
    pl_aim(hw_random8(), hw_random8(), ox, oy, oz);
    e[0] = (uint8_t)(int8_t)((ox > 127) ? 127 : ox);
    e[1] = (uint8_t)(int8_t)((oy > 127) ? 127 : oy);
    e[2] = (uint8_t)(int8_t)((oz > 127) ? 127 : oz);
    e[3] = 0;                                            // age
    e[4] = (uint8_t)(90 + (tempo.hit >> 1));             // proportional to the kick
  }

  // Age them, and collect only the live ones so the pixel loop never walks a
  // dead slot. Ripples travel on musical time too.
  int rOx[PL_RINGS], rOy[PL_RINGS], rOz[PL_RINGS], rFront[PL_RINGS], rStr[PL_RINGS];
  int rN = 0;
  const int rAdv = ((int)dt * 255) / PL_RING_MS + 1;
  for (int k = 0; k < PL_RINGS; k++) {
    uint8_t *e = st + PL_ST_RING + k * 5;
    if (!e[4]) continue;
    const int adv = rAdv;
    if ((int)e[3] + adv >= 255) { e[3] = 255; e[4] = 0; continue; }
    e[3] = (uint8_t)(e[3] + adv);
    rOx[rN]    = (int8_t)e[0];
    rOy[rN]    = (int8_t)e[1];
    rOz[rN]    = (int8_t)e[2];
    rFront[rN] = 127 - (int)e[3];                        // +127 origin -> -127 antipode
    rStr[rN]   = ((int)e[4] * (255 - (int)e[3])) >> 8;   // fades as it spreads
    rN++;
  }

  // --- colour and level ------------------------------------------------------
  const uint8_t hue = SEGMENT.check2 ? cfx_brightness(um)
                                     : (uint8_t)((uint16_t)ph[6] >> 8);
  const int lumBase = 40 + (((int)SEGMENT.intensity * 150) >> 8)
                         + (((int)cfx_drive(vol, 1.4f, 0) * 65) >> 8);

  CFX_NET_PREP();
  size_t i = 0;
  for (int y = 0; y < rows; y++) {
    CFX_NET_ROW(y);
    for (int x = 0; x < cols; x++, i++) {
      CFX_NET_SKIP(x);
      const int px = nx[i], py = ny[i], pz = nz[i];

      // Domain warp: sampled first, then folded into the two fast layers.
      const int dW = (px * kWx + py * kWy + pz * kWz) >> 7;
      const int w  = (int)sin8_t((uint8_t)(((dW * fW) >> 5) + pW)) - 128;
      const int wq = (w * warpD) >> 8;

      // Ripples bend the phase of everything, and lift the level as they pass.
      int rip = 0, ripLum = 0;
      for (int k = 0; k < rN; k++) {
        int c;
        if (cube) {
          c = (px * rOx[k] + py * rOy[k] + pz * rOz[k]) >> 7;
        } else {
          int ddx = px - rOx[k], ddy = py - rOy[k];
          if (ddx < 0) ddx = -ddx;
          if (ddy < 0) ddy = -ddy;
          const int mx = (ddx > ddy) ? ddx : ddy, mn = (ddx > ddy) ? ddy : ddx;
          c = 127 - ((mx + ((mn * 3) >> 3)) >> 1);       // hypot approximation
        }
        int d = c - rFront[k];
        if (d < 0) d = -d;
        if (d >= PL_RING_WIDTH) continue;
        const int g = ((PL_RING_WIDTH - d) * rStr[k]) / PL_RING_WIDTH;
        rip    += (g * PL_RING_WARP) >> 8;
        ripLum += (g * PL_RING_LUM)  >> 8;
      }

      const int dA = (px * kAx + py * kAy + pz * kAz) >> 7;
      const int dB = (px * kBx + py * kBy + pz * kBz) >> 7;
      const int dC = (px * kCx + py * kCy + pz * kCz) >> 7;

      const int sA = (int)sin8_t((uint8_t)(((dA * fA) >> 5) + pA + rip)) - 128;
      const int sB = (int)sin8_t((uint8_t)(((dB * fB) >> 5) + pB + wq + rip)) - 128;
      const int sC = (int)sin8_t((uint8_t)(((dC * fC) >> 5) + pC + ((wq * 3) >> 1) + rip)) - 128;

      const int sum = sA * ampA + sB * ampB + sC * ampC;
      const uint8_t v = (uint8_t)(128 + ((sum * inv) >> 16));

      // Negative space: level follows how far v sits from the wave's neutral
      // point (128). Without this the whole field sat at one near-constant
      // brightness and bands showed up only as a colour change, with no dark
      // gap ever separating them.
      //
      // It scales the level instead of being added to it. Adding meant the
      // band contrast and the Glow floor fought for the same headroom: at high
      // Glow, or just a loud passage, the sum ran past 255 and every band core
      // clipped to flat white, losing exactly the detail the bands are for.
      // As a multiplier the crest can only ever reach the level Glow already
      // asked for, so nothing clips and PL_BAND_DEPTH purely controls how deep
      // the troughs go.
      const int away = (int)v - 128;                           // -128..127
      const int mag  = (away < 0) ? -away : away;              // 0..128
      const int fac  = (255 - PL_BAND_DEPTH) + ((mag * PL_BAND_DEPTH) >> 7);

      int lum = lumBase + ((w * PL_LUM_SWING) >> 8) + ripLum;
      if (lum < 0)   lum = 0;
      if (lum > 255) lum = 255;
      lum = (lum * fac) >> 8;

      SEGMENT.setPixelColorXY(x, y,
        SEGMENT.color_from_palette((uint8_t)(v + hue), false, false, 0, (uint8_t)lum));
    }
  }
  FX_DONE;
}

static const char _data_FX_MODE_ACE_PLASMA[] PROGMEM =
  "Ace 3-D Plasma@Flow,Glow,Scale,Warp,Audio depth,Beat ripples,Tone colour,Flat mode;;!;2f;sx=110,ix=150,c1=90,c2=130,c3=21,o1=1,o2=1";



// ---------------------------------------------------------------------------
// Registration - joins the effect bank, which decides whether this effect
// claims one of the device's limited effect slots. See cube_fx_bank.h.
// ---------------------------------------------------------------------------
static CfxBankReg cube_fx_19_plasma_reg(&mode_ace_plasma, _data_FX_MODE_ACE_PLASMA);
