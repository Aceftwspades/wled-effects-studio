// ===========================================================================
// sim_main.cpp - the host side of the simulator
// ===========================================================================
// Owns the one segment, drives the clock, and exposes a tiny C surface to the
// page. The effect list is not maintained here: it is whatever the compiled
// effect sources registered into the bank roster at static-init time, so it
// cannot drift from what the firmware would register.
// ===========================================================================
#include <stdio.h>
#include "shim/wled.h"
#include "../usermods/cube_fx/cube_fx_bank.h"

// The same C surface serves two front ends. It was written for a browser and
// turned out to be exactly what a native host wants as well, because ctypes and
// Emscripten's ccall need the same thing: plain C linkage, no structs by value,
// and buffers handed back as pointers rather than copied.
//
//   WASM     browser page, via Emscripten
//   DLL      native app, via ctypes
//
// SIM_API is whichever "do not discard this symbol" the toolchain needs.
#ifdef __EMSCRIPTEN__
  #include <emscripten/emscripten.h>
  #define SIM_API EMSCRIPTEN_KEEPALIVE
#elif defined(_WIN32)
  #define SIM_API __declspec(dllexport)
#else
  #define SIM_API __attribute__((visibility("default")))
#endif

WS2812FX strip;
Segment *_segPtr = nullptr;
int Segment::_vw = 48;
int Segment::_vh = 48;
uint8_t Segment::map1D2D = 0;

// --- segments ----------------------------------------------------------------
// WLED layers several segments on one strip, each a rectangle of it with its
// own effect, sliders, colours, palette and opacity. The shim's Segment has
// static width and height (every effect reads them through SEGMENT), so a
// segment's effect runs with those set to ITS size and its own pixel buffer,
// and afterwards the buffers are composited into the strip in order - later
// over earlier, faded by opacity, as the device draws them. Segment 0 is the
// whole strip and the only one until the host adds more; every API that
// says "the segment" means the current one (simSegSelect).
#define SIM_MAX_SEGS 8
struct SimSeg {
  Segment seg;
  int x0 = 0, y0 = 0, x1 = 0, y1 = 0;     // bounds in the strip, exclusive end
  int fx = 0;
  uint8_t opacity = 255;
  uint8_t blend = 0;                       // WLED's segment blend mode ("bm"), 0..16
  uint8_t map1d2d = 0;
  uint32_t *buf = nullptr;
  size_t bufLen = 0;
  bool used = false;
};
static SimSeg gSegs[SIM_MAX_SEGS];
static int gSegCount = 1;
static int gCurSeg = 0;
static int gStripW = 48, gStripH = 48;
static Segment &gSegRef() { return gSegs[gCurSeg].seg; }
#define gSeg gSegRef()
// Room for the largest geometry the studio offers: a 256 x 256 matrix, or a
// cube with 85-pixel faces. simInit() refuses anything larger, and the Python
// side reads the size back rather than assuming it got what it asked for.
static uint32_t gPixels[256 * 256];

// --- audio the page can steer ------------------------------------------------
static float   gVolume = 0.0f;
static uint8_t gFft[16] = {0};
static uint8_t gPeak = 0;
static float   gMajorPeak = 0.0f, gMagnitude = 0.0f;
static void   *gU[9];
static um_data_t gUm = { gU, 9 };
// the PCM slot, as audioreactive's cube_fx block publishes it (u_data[8])
struct SimPcm { volatile uint8_t which; int8_t buf[2][256]; };
static SimPcm gPcm = { 0, {{0}, {0}} };

um_data_t *simAudio() {
  gU[0] = &gVolume;  gU[1] = &gVolume; gU[2] = gFft;
  gU[3] = &gPeak;    gU[4] = &gMajorPeak; gU[5] = &gMagnitude;
  gU[8] = &gPcm;
  return &gUm;
}

SIM_API void simPcmSet(const int8_t *samples, int n) {
  const uint8_t w = gPcm.which ^ 1;
  for (int i = 0; i < 256; i++) gPcm.buf[w][i] = (i < n) ? samples[i] : 0;
  gPcm.which = w;
}

// --- palettes ----------------------------------------------------------------
// wled00/palettes.cpp is compiled in, so the tables below are the firmware's
// own. What is transcribed here is Segment::loadPalette() from FX_fcn.cpp,
// which is the part that decides what a palette ID MEANS - including the
// dynamic ones built from segment colours and the usermod range that a
// registered palette lands in.
//
// It matters that this is a transcription and not an approximation: the whole
// point of the simulator is that a number set here means the same thing on the
// device, and palette IDs are numbers effects carry in their metadata.
std::vector<UsermodPalette> usermodPalettes;
std::vector<CRGBPalette16>  customPalettes;

size_t removeUsermodPalettes(const char *name) {
  const size_t before = usermodPalettes.size();
  for (int i = (int)usermodPalettes.size() - 1; i >= 0; i--)
    if (usermodPalettes[i].name == name) usermodPalettes.erase(usermodPalettes.begin() + i);
  return before - usermodPalettes.size();
}

int simPaletteCount() { return (int)(FIXED_PALETTE_COUNT + usermodPalettes.size()); }

// Transcribed from Segment::loadPalette(), wled00/FX_fcn.cpp.
static void simLoadPalette(CRGBPalette16 &target, uint8_t pal, const uint32_t *colors) {
  const int umCount   = (int)usermodPalettes.size();
  const int custCount = (int)customPalettes.size();
  if (pal >= FIXED_PALETTE_COUNT) {
    if (pal > WLED_CUSTOM_PALETTE_ID_BASE) {
      if ((WLED_USERMOD_PALETTE_ID_BASE - pal) >= umCount) pal = 0;
    } else {
      if ((WLED_CUSTOM_PALETTE_ID_BASE - pal) >= custCount) pal = 0;
    }
  }
  const CRGB prim = CRGB(R(colors[0]), G(colors[0]), B(colors[0]));
  const CRGB sec  = CRGB(R(colors[1]), G(colors[1]), B(colors[1]));
  const CRGB ter  = CRGB(R(colors[2]), G(colors[2]), B(colors[2]));
  switch (pal) {
    case 0:  target = PartyColors_gc22; break;
    // 1 is WLED's randomly generated palette, regenerated on a timer by
    // handleRandomPalette(). There is no such timer here, so it is pinned to
    // Party rather than left as an undefined third thing.
    case 1:  target = PartyColors_gc22; break;
    case 2:  target = CRGBPalette16(prim); break;
    case 3:  target = CRGBPalette16(prim, prim, sec, sec); break;
    case 4:  target = CRGBPalette16(ter, sec, prim); break;
    case 5:
      if (colors[2]) target = CRGBPalette16(prim,prim,prim,prim,prim,sec,sec,sec,sec,sec,ter,ter,ter,ter,ter,prim);
      else           target = CRGBPalette16(prim,prim,prim,prim,prim,prim,prim,prim,sec,sec,sec,sec,sec,sec,sec,sec);
      break;
    default:
      if (pal > WLED_CUSTOM_PALETTE_ID_BASE) {
        target = usermodPalettes[WLED_USERMOD_PALETTE_ID_BASE - pal].palette;
      } else if (pal >= FIXED_PALETTE_COUNT) {
        target = customPalettes[WLED_CUSTOM_PALETTE_ID_BASE - pal];
      } else if (pal < DYNAMIC_PALETTE_COUNT + FASTLED_PALETTE_COUNT) {
        target = *fastledPalettes[pal - DYNAMIC_PALETTE_COUNT];
      } else {
        // The ONE place this cannot be a literal transcription. The firmware
        // reads the table entry with pgm_read_dword, which is right on an
        // ESP32 where a pointer is 32 bits - on a 64-bit host it truncates the
        // pointer and the first gradient palette dereferences garbage. PROGMEM
        // is a no-op here, so the entry is just a pointer and is read as one.
        uint8_t tcp[72];
        memcpy(tcp, gGradientPalettes[pal - (DYNAMIC_PALETTE_COUNT + FASTLED_PALETTE_COUNT)], sizeof(tcp));
        target.loadDynamicGradientPalette(tcp);
      }
      break;
  }
}

// Reloaded every call rather than cached on the palette id, because a usermod
// palette's SIXTEEN STOPS change under a fixed id - that is the entire point of
// them. Caching on the id would freeze the audio-reactive ones on their first
// frame, which is exactly the bug this would have shipped with.
const CRGBPalette16 &Segment::currentPalette() const {
  static CRGBPalette16 cache;
  simLoadPalette(cache, palette, colors);
  return cache;
}

// --- usermods -----------------------------------------------------------------
static std::vector<Usermod *> simUsermods;
static bool simUsermodsStarted = false;
void simRegisterUsermod(Usermod *u) { simUsermods.push_back(u); }

// setup() has to be able to run BEFORE the first frame, because that is where a
// usermod registers its palettes and the host asks for the palette list while
// building its UI. Deferring it to the first frame left the audio-reactive
// palettes missing from the list until something had already been rendered.
void simEnsureUsermods() {
  if (simUsermodsStarted) return;
  simUsermodsStarted = true;
  for (auto *u : simUsermods) u->setup();
}
static void simUsermodFrame() {
  simEnsureUsermods();
  for (auto *u : simUsermods) u->loop();
}

// --- stock WLED effects, for side-by-side comparison -------------------------
// Extracted verbatim by build.py and pushed onto the same roster the cube
// effects register into, so they appear in the same list and are driven by the
// same clock, parameters and audio. Comparing "ours" against "theirs" is then
// just changing the dropdown, rather than an argument about whether the two
// were even fed the same thing.
// Defined in gen/wled_fx.cpp, which build.py writes: it adds every 2-D effect
// it extracted, with that effect's OWN metadata string. The list lives beside
// the extraction so the two cannot fall out of step, and so nothing has to be
// maintained here when WLED gains or loses an effect.
void simRegisterStock();
void simRegisterStock1D();     // gen/wled_fx1d.cpp, written by native/stock1d.py

static void registerStock() {
  static bool done = false;
  if (done) return;
  done = true;
  simRegisterStock();
  simRegisterStock1D();
}

// --- the C surface the page calls -------------------------------------------
// The palette usermod's one setting. On the device this comes from the Usermods
// settings page; here it comes from the control column. Declared OUTSIDE the
// extern "C" block below - inside it they would take C linkage and not match
// the C++ definitions in cube_fx_palettes.cpp.
void    cfxSetPaletteSource(uint8_t s);
uint8_t cfxGetPaletteSource();

// The six-face flag's one definition (cube_fx_common.h declares it; the sim
// does not compile the bank, where the firmware's lives). C++ linkage, so it
// sits outside the block.
bool cfx_sixFaces = false;

extern "C" {

SIM_API int simEffectCount() { registerStock(); return (int)cfxBankCount(); }

SIM_API const char *simEffectName(int i) {
  static char nm[48];
  if (i < 0 || i >= (int)cfxBankCount()) return "";
  cfxBankName(cfxBankRoster()[i].data, nm, sizeof(nm));
  return nm;
}

// The full metadata string, so the page can label sliders exactly as the web UI
// does rather than guessing what "custom2" means for this effect.
SIM_API const char *simEffectMeta(int i) {
  if (i < 0 || i >= (int)cfxBankCount()) return "";
  return cfxBankRoster()[i].data;
}

// A segment of w x h logical pixels. h == 1 is a 1-D strip: is2D() says no,
// SEGLEN is w, and effects that need a matrix fall back exactly as they do on
// a device with no 2-D configured. The buffer is bounded by the static
// gPixels; a request past it is clamped rather than overrun.
static void simSegBuffer(SimSeg &S) {
  const size_t need = (size_t)(S.x1 - S.x0) * (size_t)(S.y1 - S.y0);
  if (S.bufLen < need) { free(S.buf); S.buf = (uint32_t *)calloc(need ? need : 1, sizeof(uint32_t)); S.bufLen = need; }
  S.seg.pixels = S.buf;
}

static void simSegReset(SimSeg &S) {
  if (S.seg.data) { free(S.seg.data); S.seg.data = nullptr; }
  S.seg._dataLen = 0; S.seg.call = 0; S.seg.step = 0; S.seg.aux0 = 0; S.seg.aux1 = 0;
}

SIM_API void simInit(int w, int h) {
  if (w < 1) w = 1;
  if (h < 1) h = 1;
  if ((size_t)w * h > sizeof(gPixels) / sizeof(gPixels[0])) { w = 256; h = 256; }
  gStripW = w; gStripH = h;
  Segment::_vw = w; Segment::_vh = h;
  // one segment, the whole strip; the others are dropped
  for (int k = 0; k < SIM_MAX_SEGS; k++) { simSegReset(gSegs[k]); gSegs[k].used = false; }
  gSegCount = 1; gCurSeg = 0;
  SimSeg &S = gSegs[0];
  S.x0 = 0; S.y0 = 0; S.x1 = w; S.y1 = h; S.used = true; S.opacity = 255;
  simSegBuffer(S);
  _segPtr = &S.seg;
  strip._currentSegment = &S.seg;
  strip.isMatrix = (h > 1);
  strip.now = 0;
  memset(gPixels, 0, sizeof(uint32_t) * (size_t)w * h);
}

// --- the segment API ----------------------------------------------------------
SIM_API int simSegCount() { return gSegCount; }

// Segment k takes these bounds (exclusive ends, clamped to the strip) and
// opacity; a k past the count adds segments up to it. Its effect restarts,
// as it does on the device when a segment is resized.
SIM_API void simSegConfig(int k, int x0, int y0, int x1, int y1, int opacity) {
  if (k < 0 || k >= SIM_MAX_SEGS) return;
  if (x0 < 0) x0 = 0; if (y0 < 0) y0 = 0;
  if (x1 > gStripW) x1 = gStripW; if (y1 > gStripH) y1 = gStripH;
  if (x1 <= x0) x1 = x0 + 1; if (y1 <= y0) y1 = y0 + 1;
  if (x1 > gStripW) { x0 = gStripW - 1; x1 = gStripW; }
  if (y1 > gStripH) { y0 = gStripH - 1; y1 = gStripH; }
  SimSeg &S = gSegs[k];
  const bool resized = !S.used || S.x0 != x0 || S.y0 != y0 || S.x1 != x1 || S.y1 != y1;
  S.x0 = x0; S.y0 = y0; S.x1 = x1; S.y1 = y1;
  S.opacity = (uint8_t)(opacity < 0 ? 0 : (opacity > 255 ? 255 : opacity));
  S.used = true;
  if (k >= gSegCount) gSegCount = k + 1;
  simSegBuffer(S);
  if (resized) { simSegReset(S); memset(S.buf, 0, S.bufLen * sizeof(uint32_t)); }
}

// Segments past k go; k itself stays (at least one always does).
SIM_API void simSegTruncate(int k) {
  if (k < 1) k = 1;
  if (k > SIM_MAX_SEGS) k = SIM_MAX_SEGS;
  for (int i = k; i < SIM_MAX_SEGS; i++) { simSegReset(gSegs[i]); gSegs[i].used = false; }
  gSegCount = k;
  if (gCurSeg >= k) gCurSeg = k - 1;
}

// The segment the single-segment calls (simSelect, simParams, simColors,
// simSetMap1D2D, simFrame's idx) mean from now on.
SIM_API void simSegSelect(int k) {
  if (k < 0 || k >= gSegCount) return;
  gCurSeg = k;
  _segPtr = &gSegs[k].seg;
  strip._currentSegment = &gSegs[k].seg;
}

SIM_API void simSegEffect(int k, int idx) {
  if (k < 0 || k >= gSegCount) return;
  if (gSegs[k].fx != idx) simSegReset(gSegs[k]);
  gSegs[k].fx = idx;
}

SIM_API int simSegGet(int k, int what) {           // 0 x0, 1 y0, 2 x1, 3 y1, 4 opacity, 5 fx, 6 blend
  if (k < 0 || k >= gSegCount) return 0;
  const SimSeg &S = gSegs[k];
  switch (what) { case 0: return S.x0; case 1: return S.y0; case 2: return S.x1; case 3: return S.y1;
                  case 4: return S.opacity; case 5: return S.fx; case 6: return S.blend; }
  return 0;
}

// --- segment blend modes: a transcription of WS2812FX::blendSegment() ---------
// (wled00/FX_fcn.cpp). Per channel, t = the segment's pixel, b = what is under
// it; the result then mixes with what was under by the segment's opacity, as
// the firmware does: color_blend(under, blend(top, under), opacity). The
// order and numbering are index.js's "bm" list: top, bottom, add, subtract,
// difference, average, multiply, divide, lighten, darken, screen, overlay,
// hard light, soft light, dodge, burn, stencil.
static inline uint8_t bm_subtract  (uint8_t a, uint8_t b) { return b > a ? (b - a) : 0; }
static inline uint8_t bm_difference(uint8_t a, uint8_t b) { return b > a ? (b - a) : (a - b); }
static inline uint8_t bm_average   (uint8_t a, uint8_t b) { return (a + b) >> 1; }
static inline uint8_t bm_multiply  (uint8_t a, uint8_t b) { return (a * b) / 255; }
static inline uint8_t bm_divide    (uint8_t a, uint8_t b) { return a > b ? (b * 255) / a : 255; }
static inline uint8_t bm_lighten   (uint8_t a, uint8_t b) { return a > b ? a : b; }
static inline uint8_t bm_darken    (uint8_t a, uint8_t b) { return a < b ? a : b; }
static inline uint8_t bm_screen    (uint8_t a, uint8_t b) { return 255 - bm_multiply((uint8_t)~a, (uint8_t)~b); }
static inline uint8_t bm_overlay   (uint8_t a, uint8_t b) { return b < 128 ? 2 * bm_multiply(a, b) : (255 - 2 * bm_multiply((uint8_t)~a, (uint8_t)~b)); }
static inline uint8_t bm_hardlight (uint8_t a, uint8_t b) { return a < 128 ? 2 * bm_multiply(a, b) : (255 - 2 * bm_multiply((uint8_t)~a, (uint8_t)~b)); }
static inline uint8_t bm_softlight (uint8_t a, uint8_t b) { return (b * b * (255 - 2 * a) + 255 * 2 * a * b) / (255 * 255); }
static inline uint8_t bm_dodge     (uint8_t a, uint8_t b) { return bm_divide((uint8_t)~a, b); }
static inline uint8_t bm_burn      (uint8_t a, uint8_t b) { return (uint8_t)~bm_divide(a, (uint8_t)~b); }
static inline uint8_t bm_top       (uint8_t a, uint8_t b) { return a; }

static uint32_t simSegBlend(uint8_t mode, uint32_t t, uint32_t b) {
  typedef uint8_t (*Fn)(uint8_t, uint8_t);
  static const Fn fns[17] = { bm_top, bm_top, bm_top, bm_subtract, bm_difference, bm_average, bm_top, bm_divide,
                              bm_lighten, bm_darken, bm_screen, bm_overlay, bm_hardlight, bm_softlight, bm_dodge, bm_burn, bm_top };
  switch (mode) {
    case 0:  return t;
    case 1:  return b;
    case 2:  return color_add(t, b, true);
    case 6:  return RGBW32(bm_multiply(R(t), R(b)), bm_multiply(G(t), G(b)), bm_multiply(B(t), B(b)), bm_multiply(W(t), W(b)));
    case 16: return t ? t : b;
  }
  const Fn f = fns[mode < 17 ? mode : 0];
  return RGBW32(f(R(t), R(b)), f(G(t), G(b)), f(B(t), B(b)), f(W(t), W(b)));
}

// Each segment's frame into the strip, in order, later over earlier, by its
// blend mode and opacity, as the firmware composites them.
static void simComposite() {
  memset(gPixels, 0, sizeof(uint32_t) * (size_t)gStripW * gStripH);
  for (int k = 0; k < gSegCount; k++) {
    const SimSeg &S = gSegs[k];
    if (!S.used || !S.buf) continue;
    const int sw = S.x1 - S.x0;
    for (int y = S.y0; y < S.y1; y++) {
      for (int x = S.x0; x < S.x1; x++) {
        const uint32_t c = S.buf[(y - S.y0) * sw + (x - S.x0)];
        uint32_t &dst = gPixels[y * gStripW + x];
        dst = color_blend(dst, simSegBlend(S.blend, c, dst), S.opacity);
      }
    }
  }
}

SIM_API void simSegBlendMode(int k, int mode) {
  if (k < 0 || k >= SIM_MAX_SEGS) return;
  gSegs[k].blend = (uint8_t)(mode < 0 ? 0 : (mode > 16 ? 16 : mode));
}

// How a 1-D effect is expanded onto a 2-D segment: 0 strip, 1 bars, 2 arcs,
// 3 corner - WLED's map1D2D, set per segment in its UI.
SIM_API void simSetMap1D2D(int m) {
  gSegs[gCurSeg].map1d2d = (uint8_t)(m < 0 ? 0 : (m > 4 ? 4 : m));
  Segment::map1D2D = gSegs[gCurSeg].map1d2d;
}

// Six faces: the bottom lit, in the net's (2,2) block (cube_fx_common.h).
SIM_API void simSixFaces(int on) { cfx_sixFaces = (on != 0); }

SIM_API int simWidth()  { return gStripW; }
SIM_API int simHeight() { return gStripH; }

// Selecting an effect must look like WLED selecting one: the scratch buffer is
// released, so the incoming effect initialises from nothing rather than reading
// the previous effect's leftovers as its own state.
SIM_API void simSelect() {
  simSegReset(gSegs[gCurSeg]);
}

SIM_API void simParams(int sx, int ix, int c1, int c2, int c3,
                                    int o1, int o2, int o3, int pal) {
  gSeg.speed = (uint8_t)sx; gSeg.intensity = (uint8_t)ix;
  gSeg.custom1 = (uint8_t)c1; gSeg.custom2 = (uint8_t)c2;
  // Constrained, not truncated - json.cpp:306 does constrain(c3, 0, 31) before
  // storing, so a request for 210 reaches an effect as 31 rather than as 210&31.
  gSeg.custom3 = (uint8_t)(c3 < 0 ? 0 : (c3 > 31 ? 31 : c3));
  gSeg.check1 = o1 != 0; gSeg.check2 = o2 != 0; gSeg.check3 = o3 != 0;
  gSeg.palette = (uint8_t)pal;
}

// The FFT bins live here and the page writes into them directly. Handing back a
// pointer to a static beats malloc'ing one in JS: nothing to free, and no extra
// export just to allocate 16 bytes.
// The segment's three colours. Several effects paint with SEGCOLOR(0) - WLED's
// DEFAULT_COLOR is amber, so without a way to set this the front end could only
// ever show those effects in one colour.
SIM_API void simColors(uint32_t c0, uint32_t c1, uint32_t c2) {
  gSeg.colors[0] = c0; gSeg.colors[1] = c1; gSeg.colors[2] = c2;
}

SIM_API uint8_t *simFftPtr() { return gFft; }

// Probes: the studio's generated effects report the value on each pin here
// (frame-scope pins every frame, per-pixel ones at the centre pixel), so the
// editor can show live values on hover. Compiled out of the firmware:
// the calls sit behind CFX_SIM in the generated code.
static float gProbe[256];
SIM_API void simProbeSet(int i, float v) { if ((unsigned)i < 256u) gProbe[i] = v; }
SIM_API float simProbeGet(int i) { return ((unsigned)i < 256u) ? gProbe[i] : 0.0f; }

SIM_API void simAudioSet(float vol, int peak) {
  gVolume = vol; gPeak = (uint8_t)peak;
}

// One frame. dtMs is passed in rather than read from a wall clock so the page
// can step deterministically - which is the whole point of having this: you can
// hold a frame still and look at it.
SIM_API void simFrame(int idx, int dtMs) {
  if (idx < 0 || idx >= (int)cfxBankCount()) return;
  strip.now += (uint32_t)dtMs;
  // Usermods run BEFORE the effect, as they do on the device - the palette
  // usermod rewrites its gradients in loop(), and the effect must draw from the
  // version belonging to this frame rather than the previous one.
  simUsermodFrame();
  // idx is the current segment's effect (the single-segment call); the others
  // run their own. Each runs as THE segment: its size, its buffer, its mapping.
  gSegs[gCurSeg].fx = idx;
  const int keep = gCurSeg;
  for (int k = 0; k < gSegCount; k++) {
    SimSeg &S = gSegs[k];
    if (!S.used || S.fx < 0 || S.fx >= (int)cfxBankCount()) continue;
    Segment::_vw = S.x1 - S.x0; Segment::_vh = S.y1 - S.y0;
    Segment::map1D2D = S.map1d2d;
    strip.isMatrix = (Segment::_vh > 1);
    _segPtr = &S.seg; strip._currentSegment = &S.seg;
    cfxBankRoster()[S.fx].fn();
    S.seg.call++;
  }
  gCurSeg = keep;
  _segPtr = &gSegs[keep].seg; strip._currentSegment = &gSegs[keep].seg;
  Segment::_vw = gSegs[keep].x1 - gSegs[keep].x0; Segment::_vh = gSegs[keep].y1 - gSegs[keep].y0;
  Segment::map1D2D = gSegs[keep].map1d2d;
  simComposite();
}

// How many palettes exist right now, fixed plus whatever usermods registered.
// Queried after the first frame, because registration happens in setup().
SIM_API int simPalCount() { simEnsureUsermods(); return simPaletteCount(); }

// One palette entry as 0x00RRGGBB, so the Python side can draw swatches and a
// test can check a palette IS what its name says rather than inferring it from
// an effect's output.
// Display name of a usermod palette, in WLED's "name: palName" form, so the
// control column can list them without hard-coding what a usermod registered.
SIM_API const char *simUmPalName(int i) {
  simEnsureUsermods();
  static char buf[48];
  if (i < 0 || i >= (int)usermodPalettes.size()) return "";
  const UsermodPalette &u = usermodPalettes[i];
  snprintf(buf, sizeof(buf), "%s: %s", u.name ? u.name : "?",
           u.palName ? u.palName : "?");
  return buf;
}

SIM_API void simSetPalSource(int s) { simEnsureUsermods(); cfxSetPaletteSource((uint8_t)s); }
SIM_API int  simGetPalSource()      { simEnsureUsermods(); return (int)cfxGetPaletteSource(); }

SIM_API int simUmPalCount() { simEnsureUsermods(); return (int)usermodPalettes.size(); }

SIM_API uint32_t simPalColor(int pal, int idx) {
  static CRGBPalette16 tmp;
  simLoadPalette(tmp, (uint8_t)pal, gSeg.colors);
  return ColorFromPalette(tmp, (unsigned)(idx & 255), 255, LINEARBLEND);
}

SIM_API uint32_t *simPixels() { return gPixels; }

// The Studio Script effect (cube_fx_98_script.cpp) takes its program from
// memory here; the studio compiles a graph to bytecode and hands it over.
void simScriptLoad(const uint8_t *bytes, int n);
int simScriptOk();
SIM_API void simScript(const uint8_t *bytes, int n) { simScriptLoad(bytes, n); }
SIM_API int simScriptValid() { return simScriptOk(); }

} // extern "C"
