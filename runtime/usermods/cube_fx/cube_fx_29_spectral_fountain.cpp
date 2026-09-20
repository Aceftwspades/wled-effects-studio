#include "wled.h"
#include "cube_fx_common.h"
#include "cube_fx_bank.h"

// ===========================================================================
// 29. ACE 3-D SPECTRAL FOUNTAIN
// ===========================================================================
// Soap, with the pigment under control. Sixteen nozzles set into the cube fire
// jets of colour through the film, one per FFT band, and the wakes they shed
// sweep across the walls and eat each other.
//
// This is deliberately a CLOSE relative of Soap and a distant one of Black Hole.
// It runs on Soap's chart (3-D surface positions and a fold-following reverse
// lookup), Soap's transport, Soap's eased bilinear taps and Soap's contrast.
// The only thing replaced is WHERE COLOUR COMES FROM. Soap bleeds fresh pigment
// in everywhere at once from a noise field, which is why it looks like an
// endless marble with no author. Here almost all of it arrives at sixteen
// points whose strength is the spectrum - so the same fluid, driven.
//
// ---------------------------------------------------------------------------
// A JET THAT ACTUALLY LEAVES A WAKE
// ---------------------------------------------------------------------------
// The obvious way to add a jet is to add a directed velocity near the nozzle.
// That is wrong here, and specifically it would throw away the property Soap is
// built on. Soap's flow is the curl of a scalar potential, and a curl cannot
// diverge: nothing pools, nothing drains, colour can only ever be folded and
// sheared. Adding a plain directed push breaks that immediately - it compresses
// the field ahead of the nozzle and rarefies it behind.
//
// So the jets are added as VORTICES instead, and the divergence-free property
// survives because a sum of curls is still a curl.
//
// One vortex is a circular flow. TWO of them, side by side and counter-
// rotating, drive fluid between them in a straight line and drag it back around
// the outside - which is not an approximation of a jet, it is what a jet in a
// fluid actually is. The wake is not something drawn on afterwards; it is the
// pair's own far field. Fire it harder and the pair throws a longer plume and
// two bigger rolls, which then run into whatever the neighbouring nozzles are
// shedding. That collision is the effect.
//
// Each vortex contributes
//
//     v = GAMMA * (n x d) * (1 - r^2/R^2)^2
//
// with d the vector from vortex to pixel and n the face normal. Two things make
// this cheap enough to run sixteen times per pixel: (n x d) already vanishes at
// the centre, so no singular core needs special-casing, and everything is in
// r SQUARED, so the inner loop needs no square root and no division.
//
// ---------------------------------------------------------------------------
// WHERE THE NOZZLES SIT
// ---------------------------------------------------------------------------
// ON THE CUBE:
//   default       a ring round the bottom edge of the walls, four to a wall,
//                 firing up - a fountain, and the wakes collide on the walls
//   Inward        moved to the lid rim, firing in across the top face
//   Distributed   spread over all five faces instead of a ring. Wins over
//                 Inward if both are set.
//
// ON A FLAT PANEL, where there are no faces to hang a ring off:
//   default       a line along the bottom edge, firing up the panel
//   Inward        a ring in the middle firing at its own centre - and at full
//                 angle a rotating collar instead
//   Distributed   a four-by-four grid, every jet parallel, so the angle slider
//                 sweeps the whole field over together
//
// Jet angle leans every jet off its "up" by the same amount, so at the extremes
// all sixteen shear the same way and the whole film acquires a rotation on top
// of the local chaos. Centre of the slider is straight up.
//
// ---------------------------------------------------------------------------
// KEEPING IT FROM GOING GREY
// ---------------------------------------------------------------------------
// Soap's own notes carry the warning: transport plus interpolation is a mixer,
// and the original beats it only by repainting about a QUARTER of the panel
// every frame. Sixteen small injection sites are a large cut to that rate, so a
// small ambient bleed from Soap's noise field is kept underneath as insurance.
// It is deliberately weak - the point of this effect is that the colour has an
// author - but without something there the film between the jets stirs itself
// to uniform grey exactly as Soap's notes describe.
// ===========================================================================

#ifndef SF_CURL
  #define SF_CURL 6                 // gain from the noise gradient to flow units
#endif
#define SF_NOZ    16                // one per FFT band
#ifndef SF_HUEMUL
  #define SF_HUEMUL 2               // palette wraps per sweep of the nozzle ring
#endif
// Background bleed toward the noise palette, in 1/255ths per frame. Zero means
// the sixteen nozzles are the ONLY source of colour in the effect - see the
// note at the bottom of the transport loop. Kept as a constant rather than
// deleted so the trade can be re-run: at zero the per-frame noise field and its
// palette lookup are compiled out entirely, so it costs nothing to leave here.
#define SF_AMBIENT 0

struct SfState {
  uint8_t  mode;
  uint32_t nx, ny, nz;              // potential-field clocks, Q8
  uint32_t ct;                      // colour-source noise clock, Q8
  uint8_t  splash;                  // beat envelope
  uint8_t  bassEnv;
  uint8_t  peak;                    // slow-release spectrum peak, for auto-range
  uint8_t  spec[SF_NOZ];            // smoothed spectrum, fast attack
  uint8_t  clk[2];
};

// One nozzle: where it is, which way its face points, and the two counter-
// rotating centres whose pair makes the jet.
struct SfNozzle {
  int16_t px, py, pz;               // nozzle centre
  int8_t  nx, ny, nz;               // outward face normal
  int8_t  tx, ty, tz;               // jet axis, Q7 - the plume runs along this
  int16_t ax, ay, az;               // vortex A centre
  int16_t bx, by, bz;               // vortex B centre
};

// How far the pigment reaches ALONG the jet, in surface units, where a face is
// 254 across.
//
// The injection region used to be a circle centred on the orifice, which is not
// how a jet lays dye down: colour entered as a blob and only the flow carried
// it anywhere, so the sixteen sources read as sixteen smudges rather than
// sixteen jets. It is now a teardrop, stretched forward along the axis only.
//
// The length is deliberately NOT a multiple of the nozzle radius. Tying the two
// together means the size slider shortens the plume as it narrows it, so
// turning the nozzles down to where they stop merging also starves the field -
// sigma fell from 51 to 35 across that sweep and the effect went back to
// stirring itself pale. Held separate, the slider controls only how WIDE each
// jet is against the 63 units between neighbours: narrow enough and you see
// sixteen distinct plumes, wide enough and they merge into one film. That is
// the axis worth having a knob on.
#ifndef SF_PLUME
  #define SF_PLUME 300
#endif

// Face-local frame: outward normal, an "along" axis and an "up" axis. For the
// walls up is +Z, so a jet at centre angle climbs the wall; for the lid there is
// no up and the pair is simply laid in the plane.
static void sf_frame(int f, float *n, float *u, float *v) {
  static const signed char T[5][9] = {
    {  0,-1, 0,   1, 0, 0,   0, 0, 1 },   // -Y wall
    {  1, 0, 0,   0, 1, 0,   0, 0, 1 },   // +X wall
    {  0, 1, 0,  -1, 0, 0,   0, 0, 1 },   // +Y wall
    { -1, 0, 0,   0,-1, 0,   0, 0, 1 },   // -X wall
    {  0, 0, 1,   1, 0, 0,   0, 1, 0 },   // +Z lid
  };
  const signed char *t = T[(f < 0 || f > 4) ? 4 : f];
  for (int i = 0; i < 3; i++) { n[i] = t[i]; u[i] = t[3 + i]; v[i] = t[6 + i]; }
}

// Lay out the sixteen nozzles for the chosen placement and jet angle.
//
// Rebuilt every frame rather than cached, and in floats: it is sixteen
// iterations of a little trigonometry against a per-pixel loop four orders of
// magnitude larger, so it costs nothing, and caching it would mean tracking
// when the angle slider moved.
//
// The integer version this replaces was wrong in two ways a float version
// cannot be. It divided position offsets that were ALREADY in surface units by
// 127, which floored them to zero and stacked all four nozzles on a wall at
// that wall's centre; and it applied the same divide to the jet axis, which
// quantised the angle slider to whole axes so it could only ever point at
// ninety-degree steps. Both were invisible in the rendered output - the effect
// looked plausible throughout - and only turned up when a single nozzle was
// fired on its own and asked where its pigment had landed.
static void sf_build(SfNozzle *nz, int layout, uint8_t angle, int sep) {
  // Jet direction is cos*up + sin*along, so the centre of the slider is
  // straight up the face and the ends are fully tangential either way.
  const float th = ((float)angle - 128.0f) * (1.5707963f / 128.0f);   // +/-90 deg
  const float cs = cosf(th), sn = sinf(th);

  for (int k = 0; k < SF_NOZ; k++) {
    int f, j; float pu, pv;

    if (layout == 2) {                              // DISTRIBUTED: over all five
      // Twelve on the walls, three to a wall, and four on the lid.
      if (k < 12) { f = k / 3;  j = k % 3;
                    pu = -85 + j * 85;  pv = ((k & 1) ? 40 : -40); }
      else        { f = 4;      j = k - 12;
                    pu = (j & 1) ? 70 : -70;  pv = (j & 2) ? 70 : -70; }
    } else if (layout == 1) {                       // INWARD: on the lid rim
      f = 4; j = k % 4;
      const int sd = k / 4;
      const int t = -95 + j * 63;                   // along the rim
      switch (sd) {
        case 0:  pu = t;    pv = -100; break;
        case 1:  pu = 100;  pv = t;    break;
        case 2:  pu = -t;   pv = 100;  break;
        default: pu = -100; pv = -t;   break;
      }
    } else {                                        // DEFAULT: bottom ring
      f = k / 4; j = k % 4;
      pu = -95 + j * 63;                            // along the wall
      pv = -95;                                     // near the bottom edge
    }

    float nv[3], u[3], v[3];
    sf_frame(f, nv, u, v);

    // Nozzle centre FIRST, from the unrotated frame. The inward layout rotates
    // the frame below to aim its jets, and doing that before this line rotates
    // the position too: a corner offset like (-95,-100) has magnitude 138, so
    // once turned it lands outside the lid's own +/-127 and classifies onto a
    // wall. Every "inward" nozzle was being built on the side of the cube.
    SfNozzle &N = nz[k];
    N.px = (int16_t)(nv[0] * 127.0f + u[0] * pu + v[0] * pv);
    N.py = (int16_t)(nv[1] * 127.0f + u[1] * pu + v[1] * pv);
    N.pz = (int16_t)(nv[2] * 127.0f + u[2] * pu + v[2] * pv);
    N.nx = (int8_t)nv[0]; N.ny = (int8_t)nv[1]; N.nz = (int8_t)nv[2];

    // For the inward layout the jet must point at the middle of the lid, so
    // "up" becomes the in-plane direction back toward the face centre and
    // "along" the perpendicular of that. Both go through temporaries:
    // overwriting v and then reading it back while building u is the kind of
    // aliasing bug that silently half-works.
    if (layout == 1) {
      float len = sqrtf(pu * pu + pv * pv);
      if (len < 1.0f) len = 1.0f;
      const float du = -pu / len, dv = -pv / len;
      float nu[3], nvv[3];
      for (int i = 0; i < 3; i++) {
        nvv[i] = u[i] * du  + v[i] * dv;
        nu[i]  = u[i] * -dv + v[i] * du;
      }
      for (int i = 0; i < 3; i++) { u[i] = nu[i]; v[i] = nvv[i]; }
    }

    // Jet axis, then the pair laid across it. s = n x t is the in-plane
    // perpendicular, so the two centres straddle the jet and their opposed
    // circulations drive fluid along it.
    const float tx = v[0] * cs + u[0] * sn;
    const float ty = v[1] * cs + u[1] * sn;
    const float tz = v[2] * cs + u[2] * sn;
    const float sx = nv[1] * tz - nv[2] * ty;
    const float sy = nv[2] * tx - nv[0] * tz;
    const float sz = nv[0] * ty - nv[1] * tx;

    N.tx = (int8_t)(tx * 127.0f); N.ty = (int8_t)(ty * 127.0f);
    N.tz = (int8_t)(tz * 127.0f);

    N.ax = (int16_t)(N.px + sx * (float)sep);
    N.ay = (int16_t)(N.py + sy * (float)sep);
    N.az = (int16_t)(N.pz + sz * (float)sep);
    N.bx = (int16_t)(N.px - sx * (float)sep);
    N.by = (int16_t)(N.py - sy * (float)sep);
    N.bz = (int16_t)(N.pz - sz * (float)sep);
  }
}

// The flat-panel nozzle, and its own layouts.
//
// A plane has no faces to hang a ring off, so the three placements mean
// something different here - but they mean something, which is the point. The
// flat path used to hardcode a line of nozzles along the bottom with the pair
// always laid across the X axis, so neither the angle slider nor either
// checkbox reached it at all.
//
//   default       a line along the bottom edge, firing up the panel
//   Inward        a ring in the middle of the panel firing at its own centre,
//                 which at full angle becomes a rotating collar instead
//   Distributed   a four-by-four grid, every jet pointing the same way, so the
//                 angle slider sweeps the whole field over together
struct SfNoz2 {
  int16_t px, py;                   // nozzle centre
  int16_t ax, ay, bx, by;           // the counter-rotating pair
};

static void sf_build2(SfNoz2 *nz, int layout, uint8_t angle, int sep) {
  const float th = ((float)angle - 128.0f) * (1.5707963f / 128.0f);
  const float cs = cosf(th), sn = sinf(th);

  for (int k = 0; k < SF_NOZ; k++) {
    float px, py, tx, ty;

    if (layout == 1) {                              // ring, firing inward
      const float a = (float)k * (6.2831853f / (float)SF_NOZ);
      const float ca = cosf(a), sa = sinf(a);
      px = ca * 78.0f; py = sa * 78.0f;
      // Centre angle points at the middle; the ends run tangential, which turns
      // the ring from a fountain pointing in into a collar spinning round.
      tx = -(ca * cs) - (sa * sn);
      ty = -(sa * cs) + (ca * sn);
    } else if (layout == 2) {                       // grid, all pulling together
      const int i = k & 3, j = k >> 2;
      px = -95.0f + (float)i * 63.0f;
      py = -95.0f + (float)j * 63.0f;
      tx = sn; ty = -cs;                            // y runs DOWN the panel
    } else {                                        // a line along the bottom
      px = -119.0f + (float)k * (238.0f / (float)(SF_NOZ - 1));
      py = 100.0f;
      tx = sn; ty = -cs;
    }

    const float sx = -ty, sy = tx;                  // in-plane perpendicular
    nz[k].px = (int16_t)px;                   nz[k].py = (int16_t)py;
    nz[k].ax = (int16_t)(px + sx * (float)sep); nz[k].ay = (int16_t)(py + sy * (float)sep);
    nz[k].bx = (int16_t)(px - sx * (float)sep); nz[k].by = (int16_t)(py - sy * (float)sep);
  }
}

// Push the tones back apart on the way out - the same double smoothstep Soap
// needs, and for the same reason: transport plus interpolation eats the
// extremes first, and the extremes are what readability is made of.
static inline uint8_t sf_contrast(uint8_t v) {
  return ease8InOutCubic(ease8InOutCubic(v));
}

static FX_RET mode_spectral_fountain() {
  if (!strip.isMatrix || !SEGMENT.is2D()) { SEGMENT.fill(SEGCOLOR(0)); FX_DONE; }
  const int cols = SEG_W, rows = SEG_H;
  if (cols < 8 || rows < 8) { SEGMENT.fill(SEGCOLOR(0)); FX_DONE; }
  const size_t n = (size_t)cols * rows;

  const bool cube = cfx_isCube(cols, rows);
  const int  B    = cube ? (cols / 3) : 1;
  const int  Bq   = cube ? B : 1;
  const size_t lut = cube ? (size_t)6 * Bq * Bq : 0;
  const size_t m   = cfx_litCount(cols, rows, B, cube);

  const size_t need = sizeof(SfState) + 3 * m + 3 * m + 3 * m + m
                    + lut * sizeof(uint16_t);
  if (!SEGENV.allocateData(need)) { SEGMENT.fill(SEGCOLOR(0)); FX_DONE; }

  SfState *s   = (SfState *)SEGENV.data;
  int8_t  *cx  = (int8_t *)(s + 1);
  int8_t  *cy  = cx + m;
  int8_t  *cz  = cy + m;
  uint8_t *pix = (uint8_t *)(cz + m);
  uint8_t *nxt = pix + 3 * m;
  uint8_t *nz3 = nxt + 3 * m;                  // ambient colour source
  uint16_t *rev = (uint16_t *)(nz3 + m);

  const uint8_t want = (uint8_t)(cube ? 1 : 2);
  const bool init = (SEGENV.call == 0 || s->mode != want);
  if (init) {
    s->mode = want; s->splash = 0; s->bassEnv = 0; s->peak = 0;
    s->clk[0] = s->clk[1] = 0;
    memset(s->spec, 0, SF_NOZ);
    s->nx = (uint32_t)hw_random16() << 8; s->ny = (uint32_t)hw_random16() << 8;
    s->nz = (uint32_t)hw_random16() << 8; s->ct = (uint32_t)hw_random16() << 8;

    if (cube) {
      // pix and nxt are adjacent and together give 6m, and 2m >= n always holds
      // for a net, so they stand in as scratch for the full-rectangle build
      // before either holds any colour. Both are rewritten below.
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
  }

  uint16_t dt = fx_dt8(s->clk);
  if (dt > 60) dt = 60;

  // --- audio ------------------------------------------------------------------
  um_data_t     *um  = cfx_getAudioData();
  const float    vol = *(float *)um->u_data[0];
  const uint8_t *fft = (uint8_t *)um->u_data[2];
  int bass, mid, treb; cfx_bands(fft, bass, mid, treb);
  const uint8_t beat = fx_lowBeat(um);
  if (beat > s->splash) s->splash = beat;
  { const int f = (int)s->splash - (int)fx_step(7, dt);
    s->splash = (uint8_t)(f < 0 ? 0 : f); }
  s->bassEnv = fx_env(s->bassEnv, (uint8_t)bass, dt, 260);

  cfx_smoothSpec(s->spec, fft, 3);

  // Auto-range, so the fountain plays at the same vigour whatever the source
  // level is. Fast attack keeps a transient honest; slow release stops the
  // scale pumping on every beat; the floor stops silence amplifying its own
  // noise into a light show.
  {
    int mx = 0;
    for (int i = 0; i < SF_NOZ; i++) if (s->spec[i] > mx) mx = s->spec[i];
    if (mx > s->peak) s->peak = (uint8_t)mx;
    else { const int d = (int)s->peak - (int)fx_step(1, dt);
           s->peak = (uint8_t)((d < 0) ? 0 : d); }
  }
  const int pk = (s->peak < 40) ? 40 : (int)s->peak;

  // --- parameters ---------------------------------------------------------------
  // Scale is fixed at Soap's own default. The slider budget went to the fountain
  // controls; this is the value Soap ships with and it lays one broad gradient
  // across several faces, which is what makes the swaths wide.
  const int sc = 6;

  const int pixAmp = 2 + (((int)SEGMENT.custom1 * 12) >> 8);   // 2..14 pixels
  const int amp = cube ? ((254 / (B > 0 ? B : 1)) * pixAmp) : pixAmp;

  // Speed, recentred exactly as Soap's is: linear below the middle so the slow
  // half stays controllable, quadratic above so the top half accelerates.
  const int sp = SEGMENT.speed;
  int32_t flowQ;
  if (sp <= 128) flowQ = 32 + ((int32_t)(256 - 32) * sp) / 128;
  else { const int32_t t = sp - 128; flowQ = 256 + ((int32_t)3840 * t * t) / (127 * 127); }
  flowQ += ((int32_t)s->bassEnv * 384) / 255;
  flowQ += ((int32_t)s->splash * 512) / 255;

  const int32_t adv = (flowQ * (int32_t)dt) / 23;
  s->nx += (uint32_t)adv;
  s->ny += (uint32_t)((adv * 3) / 4);
  s->nz += (uint32_t)((adv * 5) / 4);
  s->ct += (uint32_t)((adv + 1) / 2);
  const uint16_t ox = (uint16_t)(s->nx >> 8), oy = (uint16_t)(s->ny >> 8),
                 oz = (uint16_t)(s->nz >> 8), oc = (uint16_t)(s->ct >> 8);

  // Nozzle radius, in surface units - the cube spans 254 per axis, so a face is
  // 254 across and this runs from a fifth of a face to most of one.
  //
  // Deliberately large. Small nozzles are the intuitive reading of "sixteen
  // jets" and they starve the effect: Soap survives its own mixing only because
  // it crossfades EVERY pixel toward fresh palette colour EVERY frame at about
  // sixteen percent, and sixteen small dots plus a two percent ambient bleed is
  // nowhere near that rate - the film averaged itself to a pale neutral within
  // seconds, exactly as Soap's notes say it will. Wide overlapping territories
  // put the influx back without giving up authorship: the picture is still
  // written by sixteen sources whose strength is the spectrum, it is just that
  // each of them owns a real piece of the cube.
  //
  // And it has to mean different things on the two geometries, because the unit
  // does. Surface coordinates run -127..127 on both, but on the cube that spans
  // ONE FACE of five and the ring of nozzles has about a thousand units of
  // perimeter to spread over, while on a flat panel it is the whole picture and
  // sixteen nozzles share barely two hundred. At the same radius every flat
  // nozzle overlapped every other one, so the blended palette index swung
  // through most of the palette over a few pixels and came out as concentric
  // rings that the flow then sheared into hard arcs - the one artefact in this
  // effect that never looked like fluid.
  const int Rbase = 40 + (((int)cfx_c3full(SEGMENT.custom3) * 170) >> 8);
  const int R  = cube ? Rbase : (Rbase / 3 + 8);
  const int R2 = R * R;
  const int sep = R / 2;                       // how far the pair straddles the jet
  const int reach = R + sep;                   // bounding radius for the vortices
  const int reach2 = reach * reach;
  // The pigment reaches further than the vortices do, forward along the axis,
  // so it needs its own looser bound or the plume gets clipped at the old one.
  // On a flat panel the whole picture is 254 units wide, so the plume is scaled
  // down with the radius for the same reason the radius itself is.
  const int Lp = cube ? SF_PLUME : (SF_PLUME / 3);
  const int plume = Lp + sep;
  const int plume2 = plume * plume;
  // Q8 ratio of plume length to lateral radius: a point Lp along the axis maps
  // back onto the rim of the lateral circle, which is what makes the falloff
  // reach exactly Lp forward whatever the radius is set to.
  const int elongQ = (Lp * 256) / (R > 0 ? R : 1);

  const int32_t jet = ((int32_t)SEGMENT.intensity * 200) / 255 + 30;

  // Only the table this geometry will actually use gets built. Guarding them
  // costs nothing and keeps the two paths provably independent - neither build
  // touches the RNG, so the cube's noise clocks see the same sequence either
  // way.
  const int layout = SEGMENT.check1 ? 2 : (SEGMENT.check2 ? 1 : 0);
  SfNozzle noz[SF_NOZ];
  SfNoz2   noz2[SF_NOZ];
  if (cube) sf_build(noz, layout, SEGMENT.custom2, sep);
  else      sf_build2(noz2, layout, SEGMENT.custom2, sep);

  // Per-nozzle circulation and palette position, resolved once rather than per
  // pixel.
  int32_t gam[SF_NOZ];
  uint8_t pidx[SF_NOZ];
  for (int k = 0; k < SF_NOZ; k++) {
    int lv = ((int)s->spec[k] * 255) / pk;
    if (lv > 255) lv = 255;
    gam[k] = (jet * lv) / 255 + (int32_t)(s->splash >> 3);
    // The nozzles walk right round the palette, one sixteenth apart, and the
    // whole ring drifts. Endpoints are deliberately included - the opposite of
    // what the spectrum effects want, where a band handed a black entry renders
    // as a silent band and the display lies. Here the nozzles pour pigment
    // rather than report anything, and the dark entries are the most valuable
    // in the set: dark gaps are what let the eye find where one swath stops and
    // the next begins.
    //
    // Spanning the full palette is only safe because of how these get combined
    // - see the blend below. Handing each pixel the nearest nozzle's RGB
    // outright put wildly different hues in adjacent territories and every
    // boundary between them averaged to grey, dropping saturation to 127
    // against Soap's 166. Narrowing the span fixed the saturation and cost the
    // structure instead, because all sixteen colours then had much the same
    // luminance: sigma fell from 49 to 33. There is no setting of the span
    // where both are right, which is the tell that the span was never the
    // problem.
    pidx[k] = (uint8_t)((uint8_t)(s->ct >> 11) + (uint8_t)((k * 256) / SF_NOZ));
  }

  // --- ambient colour source ------------------------------------------------------
  // Only worth maintaining if something reads it. With the bleed off it is
  // still needed once, to open on a marbled field rather than on black.
  if (SF_AMBIENT || init)
  for (int y = 0; y < rows; y++) {
    for (int x = 0; x < cols; x++) {
      if (cube && cfx_gap(x, y, B)) continue;
      const size_t ci = (size_t)cfx_cidx(x, y, cols, B, cube);
      const int u = cube ? (cx[ci] + 128) : ((x * 255) / (cols - 1));
      const int v = cube ? (cy[ci] + 128) : ((y * 255) / (rows - 1));
      const int w = cube ? (cz[ci] + 128) : 0;
      const uint8_t d = perlin8((uint16_t)(((u * sc) >> 2) + oc),
                                (uint16_t)((v * sc) >> 2),
                                (uint16_t)(((w * sc) >> 2) + 700));
      nz3[ci] = init ? d : (uint8_t)(scale8(nz3[ci], 200) + scale8(d, 55));
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
      if (cube && cfx_gap(x, y, B)) continue;
      const size_t i = (size_t)cfx_cidx(x, y, cols, B, cube);

      uint8_t out[3];
      // Pigment accumulator. What is summed is the nozzles' PALETTE POSITIONS,
      // weighted, rather than their colours - see the blend at the bottom of
      // this loop. refI is whichever nozzle got here first and everything else
      // is measured as a signed offset from it, so the sum stays correct across
      // the seam where the ring of nozzles closes and index 255 meets 0.
      int refI = -1, accW = 0, accD = 0;

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
        int vx = (nry * gz - nrz * gy) * SF_CURL;
        int vy = (nrz * gx - nrx * gz) * SF_CURL;
        int vz = (nrx * gy - nry * gx) * SF_CURL;

        // --- the jets -------------------------------------------------------------
        // Two counter-rotating centres per nozzle. Their sum is a jet along the
        // axis with the two wake rolls flanking it, and because each term is a
        // curl the whole field stays divergence-free.
        const int P[3] = { cx[i], cy[i], cz[i] };
        for (int k = 0; k < SF_NOZ; k++) {
          if (gam[k] < 6) continue;                        // silent band
          const int ddx = P[0] - noz[k].px, ddy = P[1] - noz[k].py, ddz = P[2] - noz[k].pz;
          const int dc2 = ddx * ddx + ddy * ddy + ddz * ddz;
          if (dc2 > plume2) continue;                      // nowhere near it
          if (noz[k].nx * nrx + noz[k].ny * nry + noz[k].nz * nrz < 0) continue; // far side

          // The vortices stay compact even when the plume does not, so they
          // keep their own tight bound. Widening this to cover the pigment
          // would have every pixel evaluating every nozzle's pair.
          if (dc2 <= reach2)
          for (int e = 0; e < 2; e++) {
            const int qx = e ? noz[k].bx : noz[k].ax;
            const int qy = e ? noz[k].by : noz[k].ay;
            const int qz = e ? noz[k].bz : noz[k].az;
            const int ex = P[0] - qx, ey = P[1] - qy, ez = P[2] - qz;
            const int r2 = ex * ex + ey * ey + ez * ez;
            if (r2 >= R2) continue;
            // (1 - r^2/R^2)^2, Q8. No sqrt anywhere in here.
            const int t1 = 256 - (r2 * 256) / R2;
            const int wgt = (t1 * t1) >> 8;
            // n x d is tangential and already vanishes at the centre, so the
            // vortex has a soft core for free.
            const int ccx = nry * ez - nrz * ey;
            const int ccy = nrz * ex - nrx * ez;
            const int ccz = nrx * ey - nry * ex;
            const int g = (int)((gam[k] * wgt) >> 8) * (e ? -1 : 1);
            vx += (ccx * g) / R;
            vy += (ccy * g) / R;
            vz += (ccz * g) / R;
          }

          // Pigment leaves the orifice and runs DOWN THE PLUME. The distance
          // used here is measured in a frame stretched along the jet axis, so
          // the region reaches SF_ELONG times further forward than it does
          // sideways or backwards - a teardrop pointing where the jet throws.
          int along = (ddx * (int)noz[k].tx + ddy * (int)noz[k].ty
                     + ddz * (int)noz[k].tz) / 127;
          const int perp2 = dc2 - along * along;
          if (along > 0) along = (along * 256) / elongQ;   // forward only
          const int shaped = along * along + (perp2 > 0 ? perp2 : 0);
          if (shaped < R2) {
            const int u1 = 256 - (shaped * 256) / R2;
            const int cw = ((u1 * u1) >> 8) * (int)gam[k] >> 8;
            if (cw > 0) {
              if (refI < 0) refI = pidx[k];
              accD += (int)(int8_t)((int)pidx[k] - refI) * cw;
              accW += cw;
            }
          }
        }

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
        // Flat: the same fluid in the plane. Nozzles sit along the bottom edge.
        const int u = (x * 255) / (cols - 1), v = (y * 255) / (rows - 1);
        const uint16_t ka = (uint16_t)((u * sc) >> 2), kb = (uint16_t)((v * sc) >> 2);
        const int p0  = (int)perlin8((uint16_t)(ka + ox), (uint16_t)(kb + oy));
        const int pdx = (int)perlin8((uint16_t)(ka + ox + CFX_GRAD), (uint16_t)(kb + oy));
        const int pdy = (int)perlin8((uint16_t)(ka + ox), (uint16_t)(kb + oy + CFX_GRAD));
        int vx =  (pdy - p0) * SF_CURL;
        int vy = -(pdx - p0) * SF_CURL;

        // The same vortex pairs, laid out by sf_build2 so the angle slider and
        // both layout checkboxes reach the plane too.
        const int gxp = (x * 254) / (cols - 1) - 127;
        const int gyp = (y * 254) / (rows - 1) - 127;
        for (int k = 0; k < SF_NOZ; k++) {
          if (gam[k] < 6) continue;
          const int ddx = gxp - noz2[k].px, ddy = gyp - noz2[k].py;
          const int dc2 = ddx * ddx + ddy * ddy;
          if (dc2 > reach2) continue;
          for (int e = 0; e < 2; e++) {
            const int ex = gxp - (e ? noz2[k].bx : noz2[k].ax);
            const int ey = gyp - (e ? noz2[k].by : noz2[k].ay);
            const int r2 = ex * ex + ey * ey;
            if (r2 >= R2) continue;
            const int t1 = 256 - (r2 * 256) / R2;
            const int wgt = (t1 * t1) >> 8;
            const int g = (int)((gam[k] * wgt) >> 8) * (e ? -1 : 1);
            vx += (-ey * g) / R;                      // 90-degree rotation = curl
            vy += ( ex * g) / R;
          }
          if (dc2 < R2) {
            const int u1 = 256 - (dc2 * 256) / R2;
            const int cw = ((u1 * u1) >> 8) * (int)gam[k] >> 8;
            if (cw > 0) {
              if (refI < 0) refI = pidx[k];
              accD += (int)(int8_t)((int)pidx[k] - refI) * cw;
              accW += cw;
            }
          }
        }

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

      // --- pigment ------------------------------------------------------------
      // Almost all of it arrives at a nozzle, weighted by how close this pixel
      // is to one and how hard that band is playing. The ambient bleed
      // underneath is small on purpose: it exists only so the film between the
      // jets cannot stir itself grey, which is the failure Soap's notes record.
      // The nozzles' palette POSITIONS are averaged and looked up once, rather
      // than their colours being averaged. This is the whole reason the effect
      // can use the full palette and still hold its saturation.
      //
      // Averaging RGB is what makes territory boundaries grey: halfway between
      // a red nozzle and a green one is genuinely grey, and there is nothing to
      // be done about that except keep the two colours similar, which costs all
      // the luminance range. Averaging the INDEX instead means halfway between
      // them is whatever the palette itself puts halfway between - a real
      // colour, chosen by whoever drew the palette. The transition sweeps
      // through the palette rather than dissolving toward its average, which is
      // exactly what Soap gets from looking its own scalar noise field up the
      // same way.
      // ...and the sum is then multiplied before lookup, which is where the
      // fine detail comes from. Sixteen wide nozzles give a colour field that
      // varies only over large distances, so the cube came out as a few soft
      // blobs where Soap has filaments. Soap solves the same problem with the
      // same move - it multiplies its scalar noise by three, so the palette
      // wraps three times across the surface. Each wrap is a hard edge, and a
      // hard edge dragged by the flow is precisely a filament. The multiply is
      // safe here only because the sum above is continuous across the nozzle
      // seam; on a discontinuous field it would tear.
      if (accW > 0) {
        const uint8_t I = (uint8_t)((refI + accD / accW) * SF_HUEMUL);
        const uint32_t c = SEGMENT.color_from_palette(I, false, true, 0);
        int mixIn = (accW * 255) / 340;
        if (mixIn > 255) mixIn = 255;
        out[0] = cfx_lerp8(out[0], (uint8_t)((c >> 16) & 0xFF), (uint8_t)mixIn);
        out[1] = cfx_lerp8(out[1], (uint8_t)((c >>  8) & 0xFF), (uint8_t)mixIn);
        out[2] = cfx_lerp8(out[2], (uint8_t)( c        & 0xFF), (uint8_t)mixIn);
      }
      // With the bleed at zero the nozzles are the only pigment in the effect,
      // and the palette lookup that fed it compiles out with everything else.
      if (SF_AMBIENT) {
        const uint32_t fr = SEGMENT.color_from_palette((uint8_t)((uint8_t)(~nz3[i]) * 3), false, true, 0);
        out[0] = cfx_lerp8(out[0], (uint8_t)((fr >> 16) & 0xFF), SF_AMBIENT);
        out[1] = cfx_lerp8(out[1], (uint8_t)((fr >>  8) & 0xFF), SF_AMBIENT);
        out[2] = cfx_lerp8(out[2], (uint8_t)( fr        & 0xFF), SF_AMBIENT);
      }
      nxt[i * 3 + 0] = out[0];
      nxt[i * 3 + 1] = out[1];
      nxt[i * 3 + 2] = out[2];
    }
  }
  memcpy(pix, nxt, 3 * m);

  // --- render ---------------------------------------------------------------------
  const uint8_t drive = cfx_drive(vol, 0.35f, 102);
  CFX_NET_PREP();
  size_t i = 0;
  for (int y = 0; y < rows; y++) {
    CFX_NET_ROW(y);
    for (int x = 0; x < cols; x++, i++) {
      CFX_NET_SKIP(x);
      const size_t ci = (size_t)cfx_cidx(x, y, cols, B, cube);
      SEGMENT.setPixelColorXY(x, y,
        mq_scale(RGBW32(sf_contrast(pix[ci * 3]),
                        sf_contrast(pix[ci * 3 + 1]),
                        sf_contrast(pix[ci * 3 + 2]), 0), drive));
    }
  }
  FX_DONE;
}

static const char _data_FX_MODE_SPECTRAL_FOUNTAIN[] PROGMEM =
  "Ace 3-D Spectral Fountain@Speed,Jet power,Density,Jet angle,Nozzle size,Distributed,Inward,Flat mode;;!;2f;sx=128,ix=150,c1=140,c2=128,c3=26,pal=11";


// ---------------------------------------------------------------------------
// Registration - joins the effect bank, which decides whether this effect
// claims one of the device's limited effect slots. See cube_fx_bank.h.
// ---------------------------------------------------------------------------
static CfxBankReg cube_fx_29_spectral_fountain_reg(&mode_spectral_fountain,
                                                   _data_FX_MODE_SPECTRAL_FOUNTAIN);
