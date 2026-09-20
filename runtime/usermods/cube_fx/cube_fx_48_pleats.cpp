#include "wled.h"
#include "cube_fx_common.h"
#include "cube_fx_bank.h"

// ===========================================================================
// Ace 3-D Pleats - a pleated surface bent by the music, lit from the side
// ===========================================================================
// A field of vertical pleats - ridges and grooves round the whole solid - with
// a wave pushed sideways through them, so the pleats bend. Light comes from
// one side, each ridge has a lit flank and a shadowed one, and where the wave
// bends a pleat the lit flank widens or narrows. The bending is what the
// music does. At rest one slow, wide wave drifts through; the more there is in
// the music, and the higher up the spectrum it sits, the more waves there are
// and the tighter they get.
//
// ---------------------------------------------------------------------------
// THE SURFACE IS A HEIGHT FIELD, AND THE NORMAL IS ITS GRADIENT
// ---------------------------------------------------------------------------
// The pleat coordinate is
//
//     u = N theta / 2pi + D(theta, phi, t)
//
// with theta the azimuth round the vertical axis, phi the elevation, N the
// number of pleats and D the displacement - a sum of sines whose amplitudes
// are the music. The pleat's height is a profile h(frac(u)), and the surface
// is z = A h(u). Its normal is the gradient of that, which the chain rule
// hands over without any finite differencing:
//
//     n = normalise( -A h'(u) du/ds_theta,  -A h'(u) du/ds_phi,  1 )
//
// where du/ds_theta = (N/2pi + dD/dtheta) / cos(phi) and du/ds_phi = dD/dphi.
// So the displacement's gradient TILTS the normal, and that tilt is the whole
// of the 3-D: a pleat bent by the wave is lit as a bent pleat, its flank
// turning toward or away from the light along the bend, with no geometry
// anywhere but the derivative. Blinn-Phong on the normal - a diffuse flank, a
// tight specular along the ridge line, a floor so the shadowed flank is dark
// rather than black.
//
// ---------------------------------------------------------------------------
// THE MUSIC IS THE WAVE'S SPECTRUM, LITERALLY
// ---------------------------------------------------------------------------
// D is five sines. Each takes its amplitude from a slice of the FFT - bass at
// the bottom, the top four bins at the top - and each has its OWN spatial
// frequency, rising with the slice:
//
//     bass    one wave up the height of the solid, big and slow
//     mids    two or three, medium
//     treble  five, seven, tight ripples
//
// So the spectrum of the music is the spectrum of the surface. Gentle music,
// which lives in the low slices, bends the pleats in one or two wide slow
// curves. Metal lights every slice, and the surface goes to a jagged tangle
// of tight ripples on top of the big ones - not louder, DIFFERENT. That was
// the brief, and it is the reason for five components rather than one
// amplitude: one amplitude cannot tell a wall of guitars from a cello.
//
// Loudness scales the lot and the treble sharpens the pleats from rounded to
// creased. Each slice's level has a fast attack and a slow release, because a
// surface that snapped back between drum hits would flicker rather than move.
//
// At rest the bass slice keeps a floor amplitude, so there is always one slow
// wave drifting through and the pleats are never simply straight. Calm, but
// visible: the surface at rest is a picture, not a screensaver waiting.
//
// ---------------------------------------------------------------------------
// THE LID
// ---------------------------------------------------------------------------
// Pleats that are vertical on every wall are meridians, and meridians meet at
// the pole - the middle of the lid. Nothing avoids that; a vector field with
// no zero cannot be combed onto a sphere. The pleats converge, their spacing
// in pixels goes as the distance from the pole, and inside a few pixels of it
// they would alias to noise. So the pleat relief fades toward the pole, sized
// in pixels the way the other guards in this folder are: full at three pixels
// of spacing, gone at one and a half. What is left in the middle of the lid is
// the wave itself, lit as a smooth bulge - which is what the top of a pleated
// dome would look like anyway.
// ===========================================================================

#define PL_TWOPI  6.28318531f
#define PL_NB     5                          // spectral slices -> wave components

struct PlState {
  uint8_t  mode;
  uint8_t  clk[2];
  uint8_t  lvl[PL_NB];           // smoothed slice levels
  uint8_t  loud;
  uint8_t  sharp;                // smoothed treble -> ridge crease
  uint16_t ph[PL_NB];            // each component's phase
  uint16_t kick;                 // phase owed to the bass wave
  uint16_t drift;                // palette rotation
};

// Spatial frequency (waves up the height), azimuthal lean, drift rate and gain
// per slice. Frequencies rise with the slice; gains fall, because a treble
// ripple that moved the pleats as far as a bass wave would shred them.
//
// The lean is applied as PL_KTH * sin(theta + offset), never as PL_KTH * theta.
// theta comes from atan2 and wraps from +pi to -pi along one line - straight
// up the middle of the west face - and a term linear in theta with a
// non-integer coefficient is discontinuous there by 2 pi PL_KTH. The first
// version had exactly that, and the wave field tore along that line: the
// pleats on either side were bent by different amounts, and the seam ran the
// full height of the face. sin(theta) is periodic whatever its coefficient.
static const float PL_KPHI[PL_NB]  = { 1.1f, 2.2f, 3.4f, 5.0f, 7.2f };
static const float PL_KTH[PL_NB]   = { 0.6f, 0.9f, 1.4f, 1.9f, 2.6f };
static const float PL_TOFF[PL_NB]  = { 0.0f, 1.1f, 2.3f, 3.6f, 4.8f };
static const uint16_t PL_RATE[PL_NB] = { 5, 8, 12, 17, 23 };
static const float PL_GAIN[PL_NB]  = { 0.95f, 0.70f, 0.48f, 0.34f, 0.24f };
static const uint8_t PL_LO[PL_NB]  = { 0, 2, 5, 8, 12 };     // FFT bin ranges
static const uint8_t PL_HI[PL_NB]  = { 1, 4, 7, 11, 15 };

static FX_RET mode_pleats() {
  if (!strip.isMatrix || !SEGMENT.is2D()) { SEGMENT.fill(SEGCOLOR(0)); FX_DONE; }
  const int cols = SEG_W, rows = SEG_H;
  if (cols < 8 || rows < 8) { SEGMENT.fill(SEGCOLOR(0)); FX_DONE; }

  const bool cube = cfx_isCube(cols, rows);
  const int  B    = cube ? (cols / 3) : 1;

  if (!SEGENV.allocateData(sizeof(PlState))) { SEGMENT.fill(SEGCOLOR(0)); FX_DONE; }
  PlState *s = (PlState *)SEGENV.data;

  const uint8_t want = (uint8_t)(cube ? 1 : 2);
  if (SEGENV.call == 0 || s->mode != want) {
    s->mode = want; s->clk[0] = s->clk[1] = 0;
    for (int b = 0; b < PL_NB; b++) { s->lvl[b] = 0; s->ph[b] = (uint16_t)(b * 9000); }
    s->loud = 0; s->sharp = 0; s->kick = 0; s->drift = 0;
  }

  uint16_t dt = fx_dt8(s->clk);
  if (dt > 60) dt = 60;

  // --- parameters -----------------------------------------------------------
  const int  fill    = (int)SEGMENT.intensity * 2;
  const int  finsI   = (int)SEGMENT.custom1;
  const int  swayI   = (int)SEGMENT.custom2;
  const int  depthI  = (int)cfx_c3full(SEGMENT.custom3);   // custom3 is 5-bit
  const bool ripples = SEGMENT.check2;

  // Pleats round the solid. 64 pixels of wall at 16 a face: 8 is eight pixels
  // a pleat, 24 is under three, which is the floor at which a flank still
  // reads as a flank.
  const int   N     = 8 + (finsI * 16) / 255;
  const float depth = 0.35f + (float)depthI * (1.65f / 255.0f);   // relief, in fin widths
  const float sway  = 0.30f + (float)swayI * (1.70f / 255.0f);    // audio gain

  // --- audio ----------------------------------------------------------------
  um_data_t     *um  = cfx_getAudioData();
  const float    vol = *(float *)um->u_data[0];
  const uint8_t *fft = (const uint8_t *)um->u_data[2];
  const uint8_t  beat = SEGMENT.check1 ? fx_lowBeat(um) : 0;

  // Slice levels: peak of the bins in the slice, fast attack, slow release.
  for (int b = 0; b < PL_NB; b++) {
    int pk = 0;
    for (int i = PL_LO[b]; i <= PL_HI[b]; i++) if ((int)fft[i] > pk) pk = fft[i];
    const int cur = s->lvl[b];
    int nv;
    // The attack is ~160 ms, not the ~45 a meter would use: this is a
    // SURFACE, and at 45 it snapped to each drum hit in a single frame - a
    // cut, measured as a one-frame surge - where at 160 it is seen to move
    // there over three or four frames, which is what a hit should look like.
    if (pk > cur) nv = cur + ((pk - cur) * (int)dt) / 160;
    else          nv = cur - ((cur - pk) * (int)dt) / 380;         // ~380 ms down
    if (nv < 0) nv = 0; else if (nv > 255) nv = 255;
    s->lvl[b] = (uint8_t)nv;
  }
  { int lw = (int)(vol * 2.2f); if (lw > 255) lw = 255;
    const int cur = s->loud;
    int nv = (lw > cur) ? cur + ((lw - cur) * (int)dt) / 160
                        : cur - ((cur - lw) * (int)dt) / 600;
    s->loud = (uint8_t)(nv < 0 ? 0 : (nv > 255 ? 255 : nv)); }
  { const int aim = ((int)s->lvl[3] + (int)s->lvl[4]) / 2;
    const int cur = s->sharp;
    int nv = cur + ((aim - cur) * (int)dt) / 250;
    s->sharp = (uint8_t)(nv < 0 ? 0 : (nv > 255 ? 255 : nv)); }

  // The beat shoves the bass wave along - owed and paid a third a frame, so
  // the whole surface is seen to lurch rather than cut.
  if (beat) {
    uint32_t k = (uint32_t)s->kick + (uint32_t)beat;
    if (k > 620u) k = 620u;
    s->kick = (uint16_t)k;
  }
  if (s->kick) {
    uint32_t give = ((uint32_t)s->kick * (uint32_t)dt) / 70u;
    if (!give) give = 1;
    if (give > s->kick) give = s->kick;
    s->ph[0] = (uint16_t)(s->ph[0] + give * 30u);
    s->kick  = (uint16_t)(s->kick - give);
  }

  // --- clocks ---------------------------------------------------------------
  { const uint32_t r = (uint32_t)(2 + (int)SEGMENT.speed / 3) * (uint32_t)dt / 23u;
    for (int b = 0; b < PL_NB; b++)
      s->ph[b] = (uint16_t)(s->ph[b] + (r * PL_RATE[b]) / 5u); }
  s->drift = (uint16_t)(s->drift + ((uint32_t)dt * (uint32_t)SEGMENT.speed) / 120u);

  // --- the wave components, once per frame ---------------------------------
  // Amplitude in pleat widths. Slice 0 keeps a floor so the surface is never
  // simply straight; the rest are silent until the music gives them something.
  float amp[PL_NB], phs[PL_NB];
  { const float loudK = 0.55f + 0.45f * ((float)s->loud / 255.0f);
    for (int b = 0; b < PL_NB; b++) {
      float a = ((float)s->lvl[b] / 255.0f) * PL_GAIN[b] * sway * loudK;
      if (b == 0) a += 0.32f;                             // the resting wave
      if (b >= 3 && !ripples) a = 0.0f;
      amp[b] = a;
      phs[b] = (float)s->ph[b] * (PL_TWOPI / 65536.0f);
    } }

  float lco[PL_NB], lsi[PL_NB];
  for (int b = 0; b < PL_NB; b++) { lco[b] = cfx_cosf16(PL_TOFF[b]); lsi[b] = cfx_sinf16(PL_TOFF[b]); }

  // Ridge profile: rounded at rest, creased under treble. Both are periodic in
  // u with unit period; h and h' come from the same f.
  const float crease = (float)s->sharp / 255.0f;

  // Light in the tangent frame: from the left and above, toward the viewer.
  const float Lx = -0.58f, Ly = 0.40f, Lz = 0.71f;
  // Half vector with the view (0,0,1), for the specular
  float Hx = Lx, Hy = Ly, Hz = Lz + 1.0f;
  { const float hl = sqrtf(Hx*Hx + Hy*Hy + Hz*Hz); Hx /= hl; Hy /= hl; Hz /= hl; }

  const float radPx = 1.5707963f / (float)(cube ? B : (cols < rows ? cols : rows) / 2);
  const float finN  = (float)N * (1.0f / PL_TWOPI);
  const uint8_t hueOff = (uint8_t)(s->drift >> 8);
  const uint8_t drive  = cfx_drive(vol, 0.5f, 200);

  // --- paint ----------------------------------------------------------------
  CFX_NET_PREP();
  for (int y = 0; y < rows; y++) {
    CFX_NET_ROW(y);
    for (int x = 0; x < cols; x++) {
      CFX_NET_SKIP(x);

      float theta, phi, cphi;
      float guard = 1.0f;
      if (cube) {
        float X, Y, Z; cfx_pos(x, y, cols, rows, B, cube, X, Y, Z);
        const float PL = sqrtf(X * X + Y * Y + Z * Z);
        const float iL = (PL > 1e-6f) ? (1.0f / PL) : 1.0f;
        const float nx = X * iL, ny = Y * iL, nz = Z * iL;
        cphi  = sqrtf(nx * nx + ny * ny);
        theta = cfx_atan2f(ny, nx);
        phi   = cfx_atan2f(nz, cphi);
        // Pleat spacing in pixels at this latitude; fade the relief where it
        // drops through three pixels toward one and a half. See the header.
        const float spacePx = (cphi * PL_TWOPI / (float)N) / radPx;
        guard = (spacePx - 1.5f) * (1.0f / 1.5f);
        if (guard < 0.0f) guard = 0.0f; else if (guard > 1.0f) guard = 1.0f;
        if (cphi < 0.02f) cphi = 0.02f;
      } else {
        // A panel: pleats straight up, the wave up the panel.
        float X, Y, Z; cfx_pos(x, y, cols, rows, B, cube, X, Y, Z);
        theta = X * 3.14159f; phi = Y * 1.3f; cphi = 1.0f;
      }

      // --- the displacement and its gradient -----------------------------
      // sin(theta + o) = sin(theta) cos(o) + cos(theta) sin(o), with the
      // per-slice cos(o)/sin(o) folded in once a frame, so the periodic lean
      // costs no trig beyond the one pair per pixel.
      const float sth = cfx_sinf16(theta), cth = cfx_cosf16(theta);
      float D = 0.0f, dDt = 0.0f, dDp = 0.0f;
      for (int b = 0; b < PL_NB; b++) {
        if (amp[b] <= 0.0f) continue;
        const float lean  = sth * lco[b] + cth * lsi[b];       // sin(theta + o)
        const float dlean = cth * lco[b] - sth * lsi[b];       // cos(theta + o)
        const float arg = PL_KPHI[b] * phi + PL_KTH[b] * lean + phs[b];
        const float sn = cfx_sinf16(arg), cs = cfx_cosf16(arg);
        D   += amp[b] * sn;
        dDp += amp[b] * PL_KPHI[b] * cs;
        dDt += amp[b] * PL_KTH[b]  * dlean * cs;
      }

      // --- the pleat and its normal ---------------------------------------
      const float u  = theta * finN + D;
      const float f  = u - floorf(u);
      // rounded: h = 0.5 - 0.5 cos(2 pi f), h' = pi sin(2 pi f)
      // creased: h = 1 - |2f - 1|,          h' = -2 sign(2f - 1)
      const float hr = 0.5f - 0.5f * cfx_cosf16(f * PL_TWOPI);
      const float dr = 3.14159f * cfx_sinf16(f * PL_TWOPI);
      const float hc = 1.0f - ((f < 0.5f) ? (1.0f - 2.0f * f) : (2.0f * f - 1.0f));
      const float dc = (f < 0.5f) ? 2.0f : -2.0f;
      const float h  = hr + (hc - hr) * crease;
      const float hp = dr + (dc - dr) * crease;

      const float A   = depth * guard;
      const float ut  = (finN + dDt) / cphi;              // du/ds_theta
      const float up  = dDp;                              // du/ds_phi
      float Nx = -A * hp * ut, Ny = -A * hp * up, Nz = 1.0f;
      const float nl = sqrtf(Nx*Nx + Ny*Ny + Nz*Nz);
      Nx /= nl; Ny /= nl; Nz /= nl;

      // --- lighting ---------------------------------------------------------
      float diff = Nx*Lx + Ny*Ly + Nz*Lz;
      if (diff < 0.0f) diff = 0.0f;
      float spec = Nx*Hx + Ny*Hy + Nz*Hz;
      if (spec < 0.0f) spec = 0.0f;
      spec *= spec; spec *= spec; spec *= spec; spec *= spec;   // ^16
      // The groove floor sits in shadow regardless of the light: an ambient
      // that follows the height, so ridges lift out of their grooves.
      const float amb = 0.11f + 0.15f * h;
      float shade = amb + 0.82f * diff + 0.85f * spec;
      // Where the guard has flattened the pleats the wave alone lights the
      // surface, dimmer, so the lid's middle is a soft bulge, not a hole.
      shade *= 0.55f + 0.45f * guard;
      if (shade > 1.0f) shade = 1.0f;

      // Hue is the WAVE - the displacement itself walks the palette - so the
      // bent region is one colour and the straight one another, the way the
      // reference's orange river runs through its violet. A little of the
      // height on top so a ridge and its groove differ.
      const uint8_t idx = (uint8_t)(hueOff + (int)(D * 46.0f) + (int)(h * 14.0f) + 96);

      int lum = (int)((float)fill * shade);
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

static const char _data_FX_MODE_PLEATS[] PROGMEM =
  "Ace 3-D Pleats@Drift,Fill,Pleats,Sway,Depth,Beat surge,Ripples,Flat mode;;!;2f;sx=90,ix=128,c1=110,c2=128,c3=16,o1=1,o2=1,pal=13";


// ---------------------------------------------------------------------------
// Registration - joins the effect bank, which decides whether this effect
// claims one of the device's limited effect slots. See cube_fx_bank.h.
// ---------------------------------------------------------------------------
static CfxBankReg cube_fx_48_pleats_reg(&mode_pleats, _data_FX_MODE_PLEATS);
