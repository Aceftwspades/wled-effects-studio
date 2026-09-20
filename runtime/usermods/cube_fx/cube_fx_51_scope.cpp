#include "wled.h"
#include "cube_fx_common.h"
#include "cube_fx_bank.h"

// ===========================================================================
// Ace 3-D Scope - MilkDrop's wave modes, bare, on black
// ===========================================================================
// The same seven closed-curve waveforms Warp draws - Circle, Spiral, Spiro,
// Star, Flower, Lasso, Triangle - drawn as bright oscilloscope figures on a
// black solid, with no feedback field behind them. Where Warp is about what
// the field does to the figure over time, this is about the figure itself:
// thick, a rainbow along its length, a short comet behind its motion, and a
// pole that wanders the cube so the figure is never parked on one face.
//
// It exists to be looked at with real music. The figures are drawn from a
// waveform REBUILT from the sixteen FFT bins (cfx_waveRebuild - see the note
// there), and whether that reconstruction reads as musical is something the
// simulator's synthetic spectra cannot settle. This is the effect to put live
// audio through: if a snare reads as a snare and a bass drop reads as a bass
// drop on the Circle, the rebuild is doing its job, and Warp inherits it.
//
// ---------------------------------------------------------------------------
// HOW IT IS DRAWN
// ---------------------------------------------------------------------------
// A glow buffer, decayed hard every frame - 0.66, so a frame's trace is gone
// in six - and the figure stamped into it with a small brush. That is a
// feedback buffer with no field, and it is what gives a moving figure a
// comet without leaving the solid full of smoke. The brush is a cross: the
// point and its four neighbours on the face, the neighbours at half weight,
// which at sixteen pixels a face is the difference between a line and a
// row of dots. The segments between consecutive points are filled the way
// Warp fills them.
//
// The beat swells the figure - the chart's scale is owed a jump and pays it
// off a third a frame - so a hit reads as the whole figure breathing out and
// settling, which is what MilkDrop's bass-sized waves do.
// ===========================================================================

#define SC_NS      96
#define SC_TWOPI   6.28318531f
#define SC_CHART   1.6f

struct ScState {
  uint8_t   mode;
  uint8_t   clk[2];
  CfxTumble tumble;
  uint16_t  kick;                // scale owed
  uint16_t  drift;
  uint16_t  cycle;
  uint16_t  t;
  uint16_t  ph[16];
};

static inline void sc_stamp(uint8_t *g, uint16_t i, uint32_t c, uint8_t w) {
  if (i == 0xFFFF) return;
  uint8_t *p = g + (size_t)i * 3;
  const uint8_t r = scale8((uint8_t)(c >> 16), w), gg = scale8((uint8_t)(c >> 8), w), b = scale8((uint8_t)c, w);
  if (r  > p[0]) p[0] = r;
  if (gg > p[1]) p[1] = gg;
  if (b  > p[2]) p[2] = b;
}

// The brush: the point, and its four face-neighbours at half weight. The
// neighbours are found by nudging the plane point by one pixel's worth of
// chart in each direction, so the cross follows the fold like everything else.
static inline void sc_brush(uint8_t *g, float x, float y, float px, const float M[3][3],
                            const uint16_t *rev, int Bq, uint32_t c, uint8_t w) {
  sc_stamp(g, cfx_plotPole(x, y, SC_CHART, M, rev, Bq), c, w);
  const uint8_t h = (uint8_t)(w / 2);
  sc_stamp(g, cfx_plotPole(x + px, y, SC_CHART, M, rev, Bq), c, h);
  sc_stamp(g, cfx_plotPole(x - px, y, SC_CHART, M, rev, Bq), c, h);
  sc_stamp(g, cfx_plotPole(x, y + px, SC_CHART, M, rev, Bq), c, h);
  sc_stamp(g, cfx_plotPole(x, y - px, SC_CHART, M, rev, Bq), c, h);
}

static FX_RET mode_scope() {
  if (!strip.isMatrix || !SEGMENT.is2D()) { SEGMENT.fill(SEGCOLOR(0)); FX_DONE; }
  const int cols = SEG_W, rows = SEG_H;
  if (cols < 8 || rows < 8) { SEGMENT.fill(SEGCOLOR(0)); FX_DONE; }
  const size_t n = (size_t)cols * rows;

  const bool cube = cfx_isCube(cols, rows);
  const int  B    = cube ? (cols / 3) : 1;
  const int  Bq   = cube ? B : 1;
  const size_t lut = cube ? (size_t)6 * Bq * Bq : 0;
  const size_t m   = cube ? (size_t)cfx_faces() * B * B : n;

  const size_t need = sizeof(ScState) + 3 * m + lut * sizeof(uint16_t);
  if (!SEGENV.allocateData(need)) { SEGMENT.fill(SEGCOLOR(0)); FX_DONE; }
  ScState  *s   = (ScState *)SEGENV.data;
  uint8_t  *g   = (uint8_t *)(s + 1);
  uint16_t *rev = (uint16_t *)(g + 3 * m);

  const uint8_t want = (uint8_t)(cube ? 1 : 2);
  if (SEGENV.call == 0 || s->mode != want) {
    s->mode = want; s->clk[0] = s->clk[1] = 0;
    cfx_tumbleInitTop(s->tumble);                   // the pole starts on the lid
    s->kick = 0; s->drift = 0; s->cycle = 0; s->t = 0;
    for (int b = 0; b < 16; b++) s->ph[b] = (uint16_t)(b * 4111);
    memset(g, 0, 3 * m);
    if (cube) cfx_buildRev(rev, cols, rows, B);
  }

  uint16_t dt = fx_dt8(s->clk);
  if (dt > 60) dt = 60;

  // --- parameters -----------------------------------------------------------
  const int  tumbleI = (int)SEGMENT.intensity;       // how fast the pole wanders; 0 = locked on the lid
  const int  sizeI = (int)SEGMENT.custom1;
  const int  spanI = (int)SEGMENT.custom2;           // hue span along the figure
  const bool dual  = SEGMENT.check2;
  // Shape: 0..31 in four steps a mode, the last four steps cycle. A slider
  // that changed the figure over its first quarter and did the same thing
  // for the rest was the erratic feel; every quarter-turn now means one shape.
  int wmode = (int)SEGMENT.custom3 / 4;

  // --- audio ----------------------------------------------------------------
  um_data_t     *um  = cfx_getAudioData();
  const float    vol = *(float *)um->u_data[0];
  const uint8_t *fft = (const uint8_t *)um->u_data[2];
  const uint8_t  beat = SEGMENT.check1 ? fx_lowBeat(um) : 0;
  if (beat) {
    uint32_t k = (uint32_t)s->kick + (uint32_t)beat;
    if (k > 620u) k = 620u;
    s->kick = (uint16_t)k;
  }
  // The swell: the figure's scale, owed and paid a third a frame. Held as the
  // remaining debt, so the figure is large while it is owed and eases back.
  float swell = 0.0f;
  if (s->kick) {
    uint32_t give = ((uint32_t)s->kick * (uint32_t)dt) / 70u;
    if (!give) give = 1;
    if (give > s->kick) give = s->kick;
    s->kick = (uint16_t)(s->kick - give);
    swell = (float)s->kick * (0.45f / 620.0f);
  }

  // --- clocks ---------------------------------------------------------------
  { const uint32_t r = (uint32_t)(2 + (int)SEGMENT.speed / 3) * (uint32_t)dt / 23u;
    s->t     = (uint16_t)(s->t + r);
    s->cycle = (uint16_t)(s->cycle + (r * 3u) / 8u);
    // The pole's wander is its own slider, not Speed: 0 holds it on the lid,
    // full is a leg of the walk in about ten seconds.
    if (tumbleI) cfx_tumbleStep(s->tumble, (uint16_t)(((uint32_t)tumbleI * (uint32_t)dt) / 38u)); }
  s->drift = (uint16_t)(s->drift + ((uint32_t)dt * (uint32_t)(60 + SEGMENT.speed)) / 12u);
  cfx_wavePhases(s->ph, dt);
  if (wmode >= CFX_WAVE_MODES) wmode = (int)(((uint32_t)s->cycle * CFX_WAVE_MODES) >> 16);

  float M[3][3];
  cfx_tumbleMatrix(s->tumble, M);
  cfx_tumbleKeepAbove(M, 0.2f);                   // the figure stays on the solid

  float W[SC_NS];
  {
    // the real waveform when audioreactive publishes one (the PCM slot),
    // the rebuilt one otherwise
    const int8_t *pcm = cfx_pcm(um);
    if (pcm) cfx_waveFromPcm(pcm, W, SC_NS, 0.9f);
    else     cfx_waveRebuild(fft, s->ph, W, SC_NS);
  }

  const float   T      = (float)s->t * (1.0f / 64.0f);
  const float   scale  = (0.6f + (float)sizeI * (0.9f / 255.0f)) * (1.0f + swell);
  const uint8_t hueOff = (uint8_t)(s->drift >> 8);
  const uint8_t wb     = 230;                        // the figure's brightness, once the Bright slider
  const uint8_t drive  = cfx_drive(vol, 0.5f, 200);
  const float   px     = (1.5707963f / (float)(cube ? B : (cols < rows ? cols : rows) / 2)) / SC_CHART;

  // --- decay the glow ---------------------------------------------------------
  for (size_t i = 0; i < 3 * m; i++) g[i] = scale8(g[i], 168);

  // --- draw ---------------------------------------------------------------------
  for (int pass = 0; pass < (dual ? 2 : 1); pass++) {
    float lx = 0.0f, ly = 0.0f; bool have = false;
    for (int i = 0; i < SC_NS; i++) {
      float x, y;
      cfx_waveShape(wmode, i, SC_NS, W, T, x, y);
      x *= scale; y *= scale;
      if (pass) { x = -x; y = -y; }                        // the mirror
      const uint8_t hue = (uint8_t)(hueOff + (i * spanI) / SC_NS + (pass ? 128 : 0));
      const uint32_t c  = SEGMENT.color_from_palette(hue, false, true, 0);
      const uint8_t  w  = (wmode == 2) ? (uint8_t)(wb / 2) : wb;

      if (cube) {
        if (have) {
          const float dd = sqrtf((x - lx) * (x - lx) + (y - ly) * (y - ly));
          int sub = (int)(dd / px) + 1;
          if (sub > 6) sub = 6;
          for (int k = 1; k <= sub; k++) {
            const float t = (float)k / (float)sub;
            sc_brush(g, lx + (x - lx) * t, ly + (y - ly) * t, px, M, rev, Bq, c, w);
          }
        } else sc_brush(g, x, y, px, M, rev, Bq, c, w);
      } else {
        auto plotFlat = [&](float xx, float yy, uint8_t ww) {
          const int qx = (int)((xx + 1.0f) * 0.5f * (float)cols), qy = (int)((1.0f - yy) * 0.5f * (float)rows);
          if (qx < 0 || qy < 0 || qx >= cols || qy >= rows) return;
          sc_stamp(g, (uint16_t)((size_t)qy * cols + qx), c, ww); };
        auto brushFlat = [&](float xx, float yy) {
          const float p2 = 2.0f / (float)cols;
          plotFlat(xx, yy, w);
          plotFlat(xx + p2, yy, (uint8_t)(w / 2)); plotFlat(xx - p2, yy, (uint8_t)(w / 2));
          plotFlat(xx, yy + p2, (uint8_t)(w / 2)); plotFlat(xx, yy - p2, (uint8_t)(w / 2)); };
        if (have) {
          const float dd = sqrtf((x - lx) * (x - lx) + (y - ly) * (y - ly));
          int sub = (int)(dd * (float)cols * 0.5f) + 1;
          if (sub > 8) sub = 8;
          for (int k = 1; k <= sub; k++) {
            const float t = (float)k / (float)sub;
            brushFlat(lx + (x - lx) * t, ly + (y - ly) * t);
          }
        } else brushFlat(x, y);
      }
      lx = x; ly = y; have = true;
    }
  }

  // --- present -----------------------------------------------------------------
  CFX_NET_PREP();
  for (int y = 0; y < rows; y++) {
    CFX_NET_ROW(y);
    for (int x = 0; x < cols; x++) {
      CFX_NET_SKIP(x);
      const size_t i = (size_t)cfx_cidx(x, y, cols, B, cube);
      const uint32_t c = RGBW32(g[i * 3], g[i * 3 + 1], g[i * 3 + 2], 0);
      SEGMENT.setPixelColorXY(x, y, mq_scale(c, drive));
    }
  }
  FX_DONE;
}

static const char _data_FX_MODE_SCOPE[] PROGMEM =
  "Ace 3-D Scope@Speed,Tumble,Size,Rainbow,Shape,Beat surge,Mirror,Flat mode;;!;2f;sx=100,ix=0,c1=150,c2=160,c3=0,o1=1,o2=1,pal=11";


// ---------------------------------------------------------------------------
// Registration - joins the effect bank, which decides whether this effect
// claims one of the device's limited effect slots. See cube_fx_bank.h.
// ---------------------------------------------------------------------------
static CfxBankReg cube_fx_51_scope_reg(&mode_scope, _data_FX_MODE_SCOPE);
