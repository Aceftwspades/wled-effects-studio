#include "wled.h"
#include "cube_fx_common.h"
#include "cube_fx_bank.h"

// ===========================================================================
// Ace 3-D Warp - MilkDrop's feedback warp, on the cube
// ===========================================================================
// The mechanism that makes every MilkDrop preset look like MilkDrop, and the
// one thing this folder did not have: a FEEDBACK BUFFER. Each frame the
// previous frame is re-sampled through a displacement field - a zoom about a
// centre, a rotation, and four travelling sines that ripple the whole picture
// - decayed a little, and then something new is drawn on top. Whatever is
// drawn gets carried outward, turned, rippled and faded by every frame that
// follows, so a single ring becomes a tunnel of rings and a scribble becomes
// smoke. The displacement field is the preset; the thing drawn on top is the
// waveform.
//
// The displacement is lifted from BeatDrop's vis_milk2/milkdropfs.cpp (the
// per-vertex warp pass, WarpedBlit) - zoom, the zoom exponent, rot, and the
// four warp sines with their drifting frequencies f[0..3] exactly as written
// there. BeatDrop is 3-clause BSD, MilkDrop 2 by Ryan Geiss / Nullsoft.
//
// ---------------------------------------------------------------------------
// THE SCREEN IS A SPHERE, SO THE CENTRE IS A POLE
// ---------------------------------------------------------------------------
// MilkDrop's field is written in screen coordinates about a fixed centre.
// Here the screen is the sphere of directions and the centre is an AXIS - a
// pole on the solid that the CfxTumble wanders slowly. A pixel's direction is
// taken into the pole's frame and laid out as MilkDrop's (x, y) by an
// azimuthal equidistant chart: distance from the pole is polar angle, bearing
// is azimuth. The field moves (x, y) exactly as milkdropfs.cpp moves its
// vertices, the result is charted back onto the sphere, and THAT direction is
// where the previous frame is sampled. Zoom > 1 pulls the sample toward the
// pole, so content streams away from it - the tunnel, with the tumble
// carrying its mouth round the cube.
//
// The sampling is the folder's cross-fold bilinear (cfx_face / cfx_rev), the
// same transport Soap and Watershed use, so a sample that lands past a fold
// reads the neighbouring face and nothing tears at an edge.
//
// ---------------------------------------------------------------------------
// THE WAVEFORM IS RECONSTRUCTED, AND THAT IS SAID PLAINLY
// ---------------------------------------------------------------------------
// Every MilkDrop wave mode draws the time-domain PCM waveform. WLED's
// audioreactive publishes no such thing - volume, sixteen FFT bins, a peak
// flag, a dominant frequency. So the waveform here is REBUILT from the bins:
// sixteen sines at one to sixteen cycles across the window, each at its
// bin's level, each with a phase that drifts at its own rate. It is not the
// audio. It moves like it - bass makes slow wide swings, treble puts fine
// wiggle on them, silence is a flat line - and the circular wave modes, which
// only ever wanted a wiggly closed curve modulated by the music, do not know
// the difference. The scope-line modes that depend on the waveform's actual
// shape are not here, because they would be a lie.
//
// Seven modes, custom3, ported from the same file: Circle (mode 0), Spiral
// (1, the x-y oscilloscope that goes round in time), Star (13), Flower (14),
// Lasso (15), Triangle (16), and Spiro (2, the faint scaled-up nebula). Above
// 6 the modes cycle. Each draws its points as MilkDrop does, with the segments
// between them filled in, straight into the feedback buffer. The rebuild and
// the seven shapes are cfx_waveRebuild / cfx_waveShape in cube_fx_common.h,
// shared with Scope, which draws the same figures without the feedback.
//
// ---------------------------------------------------------------------------
// WHAT THE MUSIC DOES TO THE FIELD
// ---------------------------------------------------------------------------
// The usual preset idioms: bass pushes the zoom, treble wobbles the rotation,
// the warp amount breathes with the mids. The beat is an owed rotational
// lurch - the whole field turns a few degrees over 140 ms and settles - which
// is the same discipline every effect here uses for a hit.
// ===========================================================================

#define WP_NS      96                        // waveform samples per frame
#define WP_NMODE   CFX_WAVE_MODES
#define WP_TWOPI   6.28318531f
#define WP_CHART   1.6f                      // radians of polar angle per unit of (x,y)

struct WpState {
  uint8_t   mode;
  uint8_t   clk[2];
  uint8_t   surge;
  uint8_t   warpMix;             // smoothed mids, drives the warp amount
  uint8_t   bassS, trebS;
  CfxTumble tumble;
  uint16_t  warpT;               // MilkDrop's fWarpTime, 16.16-ish in 1/64 s
  uint16_t  kick;                // rotation owed
  uint16_t  drift;
  uint16_t  cycle;
  uint16_t  t;                   // GetTime() stand-in, in 1/64 s
  uint16_t  ph[16];              // reconstruction phases
};

static inline void wp_stamp(uint8_t *nxt, uint16_t i, uint32_t c) {
  if (i == 0xFFFF) return;
  uint8_t *p = nxt + (size_t)i * 3;
  const uint8_t r = (uint8_t)(c >> 16), g = (uint8_t)(c >> 8), b = (uint8_t)c;
  if (r > p[0]) p[0] = r;
  if (g > p[1]) p[1] = g;
  if (b > p[2]) p[2] = b;
}

static FX_RET mode_warp() {
  if (!strip.isMatrix || !SEGMENT.is2D()) { SEGMENT.fill(SEGCOLOR(0)); FX_DONE; }
  const int cols = SEG_W, rows = SEG_H;
  if (cols < 8 || rows < 8) { SEGMENT.fill(SEGCOLOR(0)); FX_DONE; }
  const size_t n = (size_t)cols * rows;

  const bool cube = cfx_isCube(cols, rows);
  const int  B    = cube ? (cols / 3) : 1;
  const int  Bq   = cube ? B : 1;
  const size_t lut = cube ? (size_t)6 * Bq * Bq : 0;
  const size_t m   = cube ? (size_t)cfx_faces() * B * B : n;

  const size_t need = sizeof(WpState) + 3 * m + 3 * m + 3 * m + lut * sizeof(uint16_t);
  if (!SEGENV.allocateData(need)) { SEGMENT.fill(SEGCOLOR(0)); FX_DONE; }

  WpState  *s   = (WpState *)SEGENV.data;
  int8_t   *cx  = (int8_t *)(s + 1);
  int8_t   *cy  = cx + m;
  int8_t   *cz  = cy + m;
  uint8_t  *pix = (uint8_t *)(cz + m);
  uint8_t  *nxt = pix + 3 * m;
  uint16_t *rev = (uint16_t *)(nxt + 3 * m);

  const uint8_t want = (uint8_t)(cube ? 1 : 2);
  if (SEGENV.call == 0 || s->mode != want) {
    s->mode = want; s->clk[0] = s->clk[1] = 0;
    s->surge = 0; s->warpMix = 0; s->bassS = s->trebS = 0;
    cfx_tumbleInitTop(s->tumble);                   // the pole starts on the lid
    s->warpT = 0; s->kick = 0; s->drift = 0; s->cycle = 0; s->t = 0;
    for (int b = 0; b < 16; b++) s->ph[b] = (uint16_t)(b * 4111);
    memset(pix, 0, 3 * m);

    if (cube) {
      // Same loan Soap makes: pix+nxt are scratch for the full-rectangle
      // build, and both are rewritten before they hold colour.
      int8_t *sc = (int8_t *)pix;
      cfx_buildCube(sc, sc + n, sc + 2 * n, nullptr, nullptr, cols, rows, cube);
      for (int y = 0; y < rows; y++)
        for (int x = 0; x < cols; x++) {
          if (cfx_gap(x, y, B)) continue;
          const size_t src = (size_t)y * cols + x;
          const size_t ci  = (size_t)cfx_cidx(x, y, cols, B, cube);
          cx[ci] = sc[src]; cy[ci] = sc[n + src]; cz[ci] = sc[2 * n + src];
        }
      cfx_buildRev(rev, cols, rows, B);
      memset(pix, 0, 3 * m);
    } else {
      cfx_buildCube(cx, cy, cz, nullptr, nullptr, cols, rows, cube);
      memset(pix, 0, 3 * m);
    }
  }

  uint16_t dt = fx_dt8(s->clk);
  if (dt > 60) dt = 60;

  // --- parameters -----------------------------------------------------------
  const int  tumbleI = (int)SEGMENT.intensity;       // how fast the pole wanders; 0 = locked on the lid
  const int  zoomI  = (int)SEGMENT.custom1;
  const int  warpI  = (int)SEGMENT.custom2;
  const bool trails = SEGMENT.check2;
  // Shape: 0..31 in four steps a mode, the last four steps cycle. A slider
  // that changed the figure over its first quarter and did the same thing
  // for the rest was the erratic feel; every quarter-turn now means one shape.
  int wmode = (int)SEGMENT.custom3 / 4;

  // --- audio ----------------------------------------------------------------
  um_data_t     *um  = cfx_getAudioData();
  const float    vol = *(float *)um->u_data[0];
  const uint8_t *fft = (const uint8_t *)um->u_data[2];
  int bass, mid, treb; cfx_bands(fft, bass, mid, treb);
  const uint8_t beat = SEGMENT.check1 ? fx_lowBeat(um) : 0;
  if (beat > s->surge) s->surge = beat;
  { const int f = (int)s->surge - (int)fx_step(32, dt);
    s->surge = (uint8_t)(f < 0 ? 0 : f); }
  { const int c = s->warpMix; s->warpMix = (uint8_t)(c + ((mid - c) * (int)dt) / 220);
    const int b2 = s->bassS;  s->bassS   = (uint8_t)(b2 + ((bass - b2) * (int)dt) / 90);
    const int t2 = s->trebS;  s->trebS   = (uint8_t)(t2 + ((treb - t2) * (int)dt) / 120); }

  // The beat is a lurch of the whole field - mostly a ZOOM, a little turn -
  // owed and paid a third a frame. Zoom rather than rotation because the
  // default wave is a ring about the pole, and a ring turned about its own
  // centre is the same ring: a rotation-only kick measured as no event at
  // all on the circle mode. A radial jump reads on every mode.
  if (beat) {
    uint32_t k = (uint32_t)s->kick + (uint32_t)beat;
    if (k > 620u) k = 620u;
    s->kick = (uint16_t)k;
  }
  float rotKick = 0.0f, zoomKick = 0.0f;
  if (s->kick) {
    uint32_t give = ((uint32_t)s->kick * (uint32_t)dt) / 70u;
    if (!give) give = 1;
    if (give > s->kick) give = s->kick;
    rotKick  = (float)give * 0.0004f;               // radians this frame
    zoomKick = (float)give * 0.0006f;               // zoom this frame
    s->kick = (uint16_t)(s->kick - give);
  }

  // --- clocks ---------------------------------------------------------------
  { const uint32_t r = (uint32_t)(2 + (int)SEGMENT.speed / 3) * (uint32_t)dt / 23u;
    s->t     = (uint16_t)(s->t + r);
    s->warpT = (uint16_t)(s->warpT + r);
    s->cycle = (uint16_t)(s->cycle + (r * 3u) / 8u);
    // The pole's wander is its own slider, not Speed: 0 holds it on the lid,
    // full is a leg of the walk in about ten seconds.
    if (tumbleI) cfx_tumbleStep(s->tumble, (uint16_t)(((uint32_t)tumbleI * (uint32_t)dt) / 38u)); }
  // Hue turns the wheel in about 2.5 s at the default: the trails only live
  // for half a second, so anything slower and every trail is one colour.
  s->drift = (uint16_t)(s->drift + ((uint32_t)dt * (uint32_t)(60 + SEGMENT.speed)) / 6u);
  cfx_wavePhases(s->ph, dt);

  if (wmode >= WP_NMODE) wmode = (int)(((uint32_t)s->cycle * WP_NMODE) >> 16);

  float M[3][3];
  cfx_tumbleMatrix(s->tumble, M);
  cfx_tumbleKeepAbove(M, 0.2f);                   // the figure stays on the solid

  // --- the field, once per frame -------------------------------------------
  // MilkDrop's numbers, with the usual preset idioms driving them: bass pushes
  // the zoom, treble wobbles the rotation, the warp breathes with the mids.
  const float T     = (float)s->t * (1.0f / 64.0f);           // seconds-ish
  const float zoom  = 1.0f + ((float)zoomI - 128.0f) * (0.05f / 128.0f)
                           + (float)s->bassS * (0.035f / 255.0f) + zoomKick;
  const float invZ  = 1.0f / zoom;
  const float rot   = 0.012f * cfx_sinf16(T * 0.31f)
                    + (float)s->trebS * (0.010f / 255.0f) * cfx_sinf16(T * 1.7f)
                    + rotKick;
  const float cr = cfx_cosf16(rot), sr = cfx_sinf16(rot);
  const float warp  = ((float)warpI * (3.0f / 255.0f)) * (0.35f + 0.65f * (float)s->warpMix / 255.0f);
  const float wT    = (float)s->warpT * (1.0f / 64.0f);
  // f[0..3], verbatim
  const float fw0 = 11.68f + 4.0f * cosf(wT * 1.413f + 10.0f);
  const float fw1 =  8.77f + 3.0f * cosf(wT * 1.113f + 7.0f);
  const float fw2 = 10.54f + 3.0f * cosf(wT * 1.233f + 3.0f);
  const float fw3 = 11.49f + 4.0f * cosf(wT * 0.933f + 5.0f);
  const float wsi = 1.0f;                                       // fWarpScaleInv
  // MilkDrop's 0.0035 is in a 0..1 texture; ours is a +/-1 chart on a solid
  // a fraction the size, so the same visual displacement wants about four
  // times the number.
  const float wK  = warp * 0.014f;
  const uint8_t decay = trails ? 250 : 241;

  float W[WP_NS];
  {
    // the real waveform when audioreactive publishes one (the PCM slot),
    // the rebuilt one otherwise
    const int8_t *pcm = cfx_pcm(um);
    if (pcm) cfx_waveFromPcm(pcm, W, WP_NS, 0.9f);
    else     cfx_waveRebuild(fft, s->ph, W, WP_NS);
  }
  const uint8_t hueOff = (uint8_t)(s->drift >> 8);
  const uint8_t drive  = cfx_drive(vol, 0.5f, 200);

  // --- transport: sample the previous frame through the field ---------------
  CFX_NET_PREP();
  for (int y = 0; y < rows; y++) {
    CFX_NET_ROW(y);
    for (int x = 0; x < cols; x++) {
      CFX_NET_SKIP(x);
      const size_t i = (size_t)cfx_cidx(x, y, cols, B, cube);
      uint8_t out[3];

      if (cube) {
        // this pixel's direction, in the pole's frame
        const float px = (float)cx[i], py = (float)cy[i], pz = (float)cz[i];
        const float il = 1.0f / sqrtf(px*px + py*py + pz*pz + 1e-3f);
        float nx = px * il, ny = py * il, nz = pz * il;
        { const float ax = M[0][0]*nx + M[0][1]*ny + M[0][2]*nz;
          const float ay = M[1][0]*nx + M[1][1]*ny + M[1][2]*nz;
          const float az = M[2][0]*nx + M[2][1]*ny + M[2][2]*nz;
          nx = ax; ny = ay; nz = az; }
        const float sxy = sqrtf(nx*nx + ny*ny);
        const float al  = cfx_atan2f(sxy, nz);                 // 0 at the pole
        const float rad = al * (1.0f / WP_CHART);
        const float isx = (sxy > 1e-6f) ? (1.0f / sxy) : 0.0f;
        // MilkDrop's (x, y)
        float u = rad * nx * isx, v = rad * ny * isx;

        // zoom (about the pole)
        u *= invZ; v *= invZ;
        // the four warp sines, verbatim in form
        u += wK * cfx_sinf16(wT * 0.333f + wsi * (u * fw0 - v * fw3));
        v += wK * cfx_cosf16(wT * 0.375f - wsi * (u * fw2 + v * fw1));
        u += wK * cfx_cosf16(wT * 0.753f - wsi * (u * fw1 - v * fw2));
        v += wK * cfx_sinf16(wT * 0.825f + wsi * (u * fw0 + v * fw3));
        // rotation
        { const float u2 = u * cr - v * sr, v2 = u * sr + v * cr; u = u2; v = v2; }

        // back to a direction, then to cube coordinates
        const float r2 = sqrtf(u*u + v*v);
        float al2 = r2 * WP_CHART;
        if (al2 > 3.10f) al2 = 3.10f;
        const float ir2 = (r2 > 1e-6f) ? (1.0f / r2) : 0.0f;
        const float s2 = sinf(al2), c2 = cosf(al2);
        const float dx = s2 * u * ir2, dy = s2 * v * ir2, dz = c2;
        const float qx = M[0][0]*dx + M[1][0]*dy + M[2][0]*dz;
        const float qy = M[0][1]*dx + M[1][1]*dy + M[2][1]*dz;
        const float qz = M[0][2]*dx + M[1][2]*dy + M[2][2]*dz;

        int f, a, b; cfx_face((int)(qx * 400.0f), (int)(qy * 400.0f), (int)(qz * 400.0f), f, a, b);
        const int aq = (a + 128) * Bq, bq = (b + 128) * Bq;
        const int ai = aq >> 8, bi = bq >> 8;
        const uint8_t fa = (uint8_t)(aq & 255), fb = (uint8_t)(bq & 255);
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
          out[c] = scale8(cfx_lerp8(c0, c1, fb), decay);
        }
      } else {
        // A panel: MilkDrop's own case, the chart is the screen.
        float u = 2.0f * (x + 0.5f) / (float)cols - 1.0f;
        float v = 1.0f - 2.0f * (y + 0.5f) / (float)rows;
        u *= invZ; v *= invZ;
        u += wK * cfx_sinf16(wT * 0.333f + wsi * (u * fw0 - v * fw3));
        v += wK * cfx_cosf16(wT * 0.375f - wsi * (u * fw2 + v * fw1));
        u += wK * cfx_cosf16(wT * 0.753f - wsi * (u * fw1 - v * fw2));
        v += wK * cfx_sinf16(wT * 0.825f + wsi * (u * fw0 + v * fw3));
        { const float u2 = u * cr - v * sr, v2 = u * sr + v * cr; u = u2; v = v2; }
        const float fx = (u + 1.0f) * 0.5f * (float)cols - 0.5f;
        const float fy = (1.0f - v) * 0.5f * (float)rows - 0.5f;
        int ix = (int)floorf(fx), iy = (int)floorf(fy);
        const uint8_t fa = (uint8_t)((fx - (float)ix) * 255.0f), fb = (uint8_t)((fy - (float)iy) * 255.0f);
        auto cl = [&](int xx, int yy) -> size_t {
          if (xx < 0) xx = 0; else if (xx >= cols) xx = cols - 1;
          if (yy < 0) yy = 0; else if (yy >= rows) yy = rows - 1;
          return (size_t)yy * cols + xx; };
        const size_t t00 = cl(ix, iy), t10 = cl(ix + 1, iy), t01 = cl(ix, iy + 1), t11 = cl(ix + 1, iy + 1);
        for (int c = 0; c < 3; c++) {
          const uint8_t c0 = cfx_lerp8(pix[t00 * 3 + c], pix[t10 * 3 + c], fa);
          const uint8_t c1 = cfx_lerp8(pix[t01 * 3 + c], pix[t11 * 3 + c], fa);
          out[c] = scale8(cfx_lerp8(c0, c1, fb), decay);
        }
      }
      nxt[i * 3 + 0] = out[0]; nxt[i * 3 + 1] = out[1]; nxt[i * 3 + 2] = out[2];
    }
  }

  // --- draw the wave on top ----------------------------------------------------
  {
    const uint8_t wb = 210;                       // the wave's brightness, once the Wave slider
    float lx = 0.0f, ly = 0.0f; bool have = false;
    const float ang0 = T * 0.2f;
    const float pxStep = (1.5707963f / (float)(cube ? B : (cols < rows ? cols : rows) / 2)) / WP_CHART;

    for (int i = 0; i < WP_NS; i++) {
      float x, y;
      cfx_waveShape(wmode, i, WP_NS, W, T, x, y);

      const uint8_t hue = (uint8_t)(hueOff + (i * 40) / WP_NS);
      uint32_t c = mq_scale(SEGMENT.color_from_palette(hue, false, true, 0), wmode == 2 ? (uint8_t)(wb / 2) : wb);

      if (cube) {
        if (have) {
          // fill the segment so the line does not break into dots
          const float dd = sqrtf((x - lx) * (x - lx) + (y - ly) * (y - ly));
          int sub = (int)(dd / pxStep) + 1;
          if (sub > 6) sub = 6;
          for (int k = 1; k <= sub; k++) {
            const float t = (float)k / (float)sub;
            wp_stamp(nxt, cfx_plotPole(lx + (x - lx) * t, ly + (y - ly) * t, WP_CHART, M, rev, Bq), c);
          }
        } else wp_stamp(nxt, cfx_plotPole(x, y, WP_CHART, M, rev, Bq), c);
      } else {
        auto plotFlat = [&](float xx, float yy) {
          const int px = (int)((xx + 1.0f) * 0.5f * (float)cols), py = (int)((1.0f - yy) * 0.5f * (float)rows);
          if (px < 0 || py < 0 || px >= cols || py >= rows) return;
          wp_stamp(nxt, (uint16_t)((size_t)py * cols + px), c); };
        if (have) {
          const float dd = sqrtf((x - lx) * (x - lx) + (y - ly) * (y - ly));
          int sub = (int)(dd * (float)cols * 0.5f) + 1;
          if (sub > 8) sub = 8;
          for (int k = 1; k <= sub; k++) {
            const float t = (float)k / (float)sub;
            plotFlat(lx + (x - lx) * t, ly + (y - ly) * t);
          }
        } else plotFlat(x, y);
      }
      lx = x; ly = y; have = true;
    }
  }
  memcpy(pix, nxt, 3 * m);

  // --- present -----------------------------------------------------------------
  for (int y = 0; y < rows; y++) {
    CFX_NET_ROW(y);
    for (int x = 0; x < cols; x++) {
      CFX_NET_SKIP(x);
      const size_t i = (size_t)cfx_cidx(x, y, cols, B, cube);
      const uint32_t c = RGBW32(pix[i * 3], pix[i * 3 + 1], pix[i * 3 + 2], 0);
      SEGMENT.setPixelColorXY(x, y, mq_scale(c, drive));
    }
  }
  FX_DONE;
}

static const char _data_FX_MODE_WARP[] PROGMEM =
  "Ace 3-D Warp@Speed,Tumble,Zoom,Warp,Shape,Beat surge,Trails,Flat mode;;!;2f;sx=100,ix=0,c1=150,c2=110,c3=0,o1=1,o2=0,pal=11";


// ---------------------------------------------------------------------------
// Registration - joins the effect bank, which decides whether this effect
// claims one of the device's limited effect slots. See cube_fx_bank.h.
// ---------------------------------------------------------------------------
static CfxBankReg cube_fx_50_warp_reg(&mode_warp, _data_FX_MODE_WARP);
