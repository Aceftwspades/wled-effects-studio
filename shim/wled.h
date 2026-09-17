#pragma once
// ===========================================================================
// wled.h - host stand-in, so the REAL effect sources compile unmodified
// ===========================================================================
// The point of the simulator is that it runs the same code the cube runs. Not
// a port, not a re-implementation - the actual .cpp files, built against this
// header instead of the firmware's.
//
// That constraint is what makes the thing worth having. Every Soap bug we
// chased lived in a detail a re-implementation would have quietly normalised:
// a palette lookup asking for NOWRAP, a refresh rate an order of magnitude too
// low, a missing smoothstep on a blend weight. A simulator that "mostly does
// the same thing" would have shown none of them, and would have lied
// confidently while we tuned against it.
//
// So where fidelity is cheap, it is bought outright:
//
//   * The MATH is WLED's own. fastled_slim.cpp compiles straight in, so
//     perlin8, sin8_t, scale8, qadd8 and ease8InOutCubic are bit-for-bit what
//     the device computes. This matters more than it looks - every magnitude
//     we tune (SP_CURL, Density, the whirlpool spin constants) is calibrated
//     against the noise field's actual shape, so a re-rolled Perlin would make
//     every number we pick here wrong on the hardware.
//
//   * allocateData() keeps WLED's REUSE SEMANTICS: an existing buffer is handed
//     back whenever it is already big enough, and `call` is not reset when the
//     request merely shrinks. Effects depend on that (it is what the geometry
//     watchdog exists to work around), so the shim reproduces it rather than
//     the obvious always-fresh-allocation version.
//
// What is NOT faithful, and is marked so at each site: the palette SET is a
// subset, and the segment model is one segment with no transitions, mirroring
// or grouping. Neither affects the questions the simulator is for.
// ===========================================================================

#include <stdint.h>
#include <vector>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include <utility>                 // std::swap, used by WLED's soapPixels
#include <algorithm>
using std::min;
using std::max;
#include "pgmspace.h"
#include "../../wled00/src/dependencies/fastled_slim/fastled_slim.h"

typedef uint8_t byte;

// Stock WLED effects bail out through this when the segment is not 2D.
// Falling back to black is close enough for a comparison view.
#define FX_FALLBACK_STATIC { SEGMENT.fill(0); return; }

// Extracted from wled00/colors.cpp by build.py - the real thing, so the
// wrap/no-wrap behaviour that caused Soap's colour seams is reproduced exactly.
uint32_t ColorFromPalette(const CRGBPalette16 &pal, unsigned index,
                          uint8_t brightness = 255, TBlendType blendType = LINEARBLEND);

// --- trig ------------------------------------------------------------------
// Declared here, DEFINED by compiling WLED's own wled_math.cpp into the build.
// These are lookup-and-interpolate, not std::sin wrappers, and their exact
// curve is what every phase and frequency constant in the effects was tuned
// against - so substituting real sine here would quietly shift every one of
// them.
int16_t sin16_t(uint16_t theta);
int16_t cos16_t(uint16_t theta);
uint8_t sin8_t(uint8_t theta);
uint8_t cos8_t(uint8_t theta);
float   sin_approx(float);
float   cos_approx(float);
float   tan_approx(float);
float   atan2_t(float, float);
float   atan_t(float);
float   acos_t(float);
float   asin_t(float);
float   floor_t(float);
float   fmod_t(float, float);

// --- noise -----------------------------------------------------------------
// Declared here, DEFINED by gen/wled_noise.cpp, which build.py lifts verbatim
// out of wled00/util.cpp. Same signatures and same default arguments as
// fcn_declare.h, so the effects are compiling against the firmware's contract.
int32_t  perlin1D_raw(uint32_t x, bool is16bit = false);
int32_t  perlin2D_raw(uint32_t x, uint32_t y, bool is16bit = false);
int32_t  perlin3D_raw(uint32_t x, uint32_t y, uint32_t z, bool is16bit = false);
uint16_t perlin16(uint32_t x);
uint16_t perlin16(uint32_t x, uint32_t y);
uint16_t perlin16(uint32_t x, uint32_t y, uint32_t z);
uint8_t  perlin8(uint16_t x);
uint8_t  perlin8(uint16_t x, uint16_t y);
uint8_t  perlin8(uint16_t x, uint16_t y, uint16_t z);

// --- colour ----------------------------------------------------------------
#define RGBW32(r,g,b,w) (uint32_t)((uint32_t)(w)<<24 | (uint32_t)(r)<<16 | (uint32_t)(g)<<8 | (uint32_t)(b))
#define R(c) (uint8_t)(((c)>>16)&0xFF)
#define G(c) (uint8_t)(((c)>> 8)&0xFF)
#define B(c) (uint8_t)(((c)    )&0xFF)
#define W(c) (uint8_t)(((c)>>24)&0xFF)
#define BLACK 0u
#define SEGLEN Segment::vLength()
// The named colours and the palette-wrap test the stock effects use. Both live
// in FX.h / FX.cpp above the effect bodies, so the extraction never sees them.
#define RED     (uint32_t)0xFF0000
#define GREEN   (uint32_t)0x00FF00
#define BLUE    (uint32_t)0x0000FF
#define WHITE   (uint32_t)0xFFFFFF
#define YELLOW  (uint32_t)0xFFFF00
#define CYAN    (uint32_t)0x00FFFF
#define MAGENTA (uint32_t)0xFF00FF
#define PURPLE  (uint32_t)0x400080
#define ORANGE  (uint32_t)0xFF3000
#define PINK    (uint32_t)0xFF1493
#define ULTRAWHITE (uint32_t)0xFFFFFFFF
#define DARKSLATEGRAY (uint32_t)0x2F4F4F
#define GRAY    (uint32_t)0x808080
// paletteBlend 1 = wrap. The simulator has no blend setting, and every effect
// that passes this wants the wrapping form.
#define PALETTE_SOLID_WRAP true
#define SPEED_FORMULA_L (5U + (50U * (255U - SEGMENT.speed)) / SEGLEN)
// Commented out in FX.cpp's preamble yet still referenced by an audio
// effect. 10 kHz sampling, matching the figure given there.
#ifndef MAX_FREQUENCY
  #define MAX_FREQUENCY  5120
#endif
#ifndef MAX_FREQ_LOG10
  #define MAX_FREQ_LOG10 3.71f
#endif

static inline uint32_t color_fade(uint32_t c, uint8_t s, bool = false) {
  return RGBW32(scale8(R(c),s), scale8(G(c),s), scale8(B(c),s), scale8(W(c),s));
}
static inline uint32_t color_add(uint32_t a, uint32_t b, bool = false) {
  return RGBW32(qadd8(R(a),R(b)), qadd8(G(a),G(b)), qadd8(B(a),B(b)), qadd8(W(a),W(b)));
}

// --- randomness ------------------------------------------------------------
// xorshift rather than rand(), so a run is reproducible frame for frame when
// the seed is held - which is what makes "did that change help?" answerable.
static inline uint32_t &_rngState() { static uint32_t s = 0x2545F491u; return s; }
static inline uint32_t hw_random() {
  uint32_t &x = _rngState();
  x ^= x << 13; x ^= x >> 17; x ^= x << 5; return x;
}
static inline uint32_t hw_random(uint32_t lim)              { return lim ? hw_random() % lim : 0; }
static inline uint32_t hw_random(uint32_t lo, uint32_t hi)  { return lo + (hi > lo ? hw_random() % (hi - lo) : 0); }
static inline uint16_t hw_random16()                        { return (uint16_t)(hw_random() >> 8); }
static inline uint16_t hw_random16(uint16_t lim)            { return lim ? (uint16_t)(hw_random16() % lim) : 0; }
static inline uint16_t hw_random16(uint16_t lo, uint16_t hi) { return hi > lo ? (uint16_t)(lo + hw_random16((uint16_t)(hi - lo))) : lo; }
static inline uint8_t  hw_random8()                         { return (uint8_t)(hw_random() >> 16); }
static inline uint8_t  hw_random8(uint8_t lim)              { return lim ? (uint8_t)(hw_random8() % lim) : 0; }
static inline uint8_t  hw_random8(uint8_t lo, uint8_t hi)   { return hi > lo ? (uint8_t)(lo + hw_random8((uint8_t)(hi - lo))) : lo; }

// --- audio -----------------------------------------------------------------
// Same shape the audioreactive usermod publishes, so the effects' unpacking
// code is unchanged. The values are driven from the UI.
typedef struct { void **u_data; uint8_t u_size; } um_data_t;
#define USERMOD_ID_AUDIOREACTIVE 1
extern um_data_t *simAudio();
// --- just enough of WLED's config plumbing to COMPILE a usermod ------------
// A usermod that carries settings implements addToConfig / readFromConfig /
// appendConfigData against ArduinoJson and Print. The simulator has no settings
// page and no cfg.json, so these do nothing - but they have to exist, or a
// usermod with settings cannot be built here at all, and the whole point of
// compiling the real file is that it is the real file.
//
// readFromConfig returning false is the honest answer: nothing was read, so the
// usermod keeps its compiled-in defaults.
#ifndef FPSTR
  #define FPSTR(s) (s)
#endif
struct JsonObject {
  struct Slot {
    template <class T> Slot &operator=(const T &) { return *this; }
    template <class T> operator T() const { return T(); }
  };
  bool isNull() const { return true; }
  JsonObject createNestedObject(const char *) { return JsonObject(); }
  Slot operator[](const char *) const { return Slot(); }
};
template <class S, class T> inline bool getJsonValue(const S &, T &) { return false; }
class Print {
 public:
  void print(const char *) {}
  void print(int) {}
};

#ifndef USERMOD_ID_UNSPECIFIED
  #define USERMOD_ID_UNSPECIFIED 0
#endif

struct UsermodManager {
  static bool getUMData(um_data_t **d, uint8_t) { *d = simAudio(); return true; }
};
static inline um_data_t *simulateSound(uint8_t) { return simAudio(); }
// The stock audio-reactive 2-D effects fetch their data through this rather
// than through UsermodManager, so they get the same buffer either way.
static inline um_data_t *getAudioData() { return simAudio(); }

// --- odds and ends the stock 2-D effects use --------------------------------
// Small enough that reimplementing beats extracting, and none of them carry
// behaviour an effect could be judged on.
static inline uint32_t color_blend(uint32_t c1, uint32_t c2, uint8_t b) {
  if (b == 0) return c1;
  if (b == 255) return c2;
  const uint8_t ib = 255 - b;
  return RGBW32((R(c1) * ib + R(c2) * b) >> 8, (G(c1) * ib + G(c2) * b) >> 8,
                (B(c1) * ib + B(c2) * b) >> 8, (W(c1) * ib + W(c2) * b) >> 8);
}
static inline uint32_t color_blend16(uint32_t a, uint32_t b, uint16_t x) {
  return color_blend(a, b, (uint8_t)(x >> 8));
}
static inline float mapf(float x, float a, float b, float c, float d) {
  return (b - a) == 0.0f ? c : c + (x - a) * (d - c) / (b - a);
}
static inline uint16_t sqrt32_bw(uint32_t v) { return (uint16_t)sqrtf((float)v); }
static inline uint8_t  gamma8inv(uint8_t v)  { return v; }   // sim renders linear
static inline uint8_t  gamma8(uint8_t v)     { return v; }   // likewise: no gamma, no inverse
static inline uint8_t  inoise8(uint16_t x)                       { return perlin8(x); }
static inline uint8_t  inoise8(uint16_t x, uint16_t y)           { return perlin8(x, y); }
static inline uint8_t  inoise8(uint16_t x, uint16_t y, uint16_t z) { return perlin8(x, y, z); }
// WLED aliases these to its own approximations rather than libm, and the
// effects were tuned against that curve, so the shim points at the same ones.
#define sin_t  sin_approx
#define cos_t  cos_approx
#define tan_t  tan_approx
static inline float radians(float d) { return d * 0.01745329252f; }
// Only the hue is used by the one effect that calls this, but saturation and
// value are computed properly anyway - a wrong V here would read as a dead
// pixel rather than as a wrong colour, which is harder to spot.
static inline CHSV rgb2hsv(const CRGB &c) {
  const uint8_t mx = c.r > c.g ? (c.r > c.b ? c.r : c.b) : (c.g > c.b ? c.g : c.b);
  const uint8_t mn = c.r < c.g ? (c.r < c.b ? c.r : c.b) : (c.g < c.b ? c.g : c.b);
  const int d = mx - mn;
  uint8_t h = 0;
  if (d) {
    int hh;
    if (mx == c.r)      hh = ((c.g - c.b) * 43) / d;
    else if (mx == c.g) hh = 85 + ((c.b - c.r) * 43) / d;
    else                hh = 171 + ((c.r - c.g) * 43) / d;
    h = (uint8_t)(hh & 0xFF);
  }
  return CHSV(h, (uint8_t)(mx ? (d * 255) / mx : 0), mx);
}
static inline long  map(long x, long a, long b, long c, long d) {
  return (b - a) == 0 ? c : (x - a) * (d - c) / (b - a) + c;
}
#ifndef constrain
  #define constrain(v, lo, hi) ((v) < (lo) ? (lo) : ((v) > (hi) ? (hi) : (v)))
#endif

// The file-scope generator several stock effects draw from. WLED seeds it from
// hardware entropy; here it is the same deterministic xorshift everything else
// uses, so a run stays reproducible.
class PRNG {
 public:
  explicit PRNG(uint32_t seed = 0x1234567u) : s(seed ? seed : 1u) {}
  uint32_t next() { s ^= s << 13; s ^= s >> 17; s ^= s << 5; return s; }
  uint8_t  random8()            { return (uint8_t)(next() >> 16); }
  uint8_t  random8(uint8_t lim) { return lim ? (uint8_t)(random8() % lim) : 0; }
  uint8_t  random8(uint8_t lo, uint8_t hi) {
    return hi > lo ? (uint8_t)(lo + random8((uint8_t)(hi - lo))) : lo;
  }
  uint16_t random16()           { return (uint16_t)(next() >> 8); }
  uint16_t random16(uint16_t l) { return l ? (uint16_t)(random16() % l) : 0; }
  uint32_t getSeed() const      { return s; }
  void     setSeed(uint32_t v)  { s = v ? v : 1u; }
 private:
  uint32_t s;
};
// FX.cpp declares this at file scope, above every effect, so no per-effect span
// can reach it. One instance for the whole simulator, as there.
inline PRNG prng(0x9E3779B9u);

// Declared beside the 1-D ripple effects in FX.cpp, thousands of lines from the
// 2-D effect that also uses it, so no per-effect span can pick it up. Copied
// verbatim rather than approximated - the effect casts its scratch buffer to
// this, so the layout has to match exactly.
typedef struct Ripple {
  uint8_t state;
  uint8_t color;
  uint16_t pos;
} ripple;

#ifndef bitRead
  #define bitRead(v, b)  (((v) >> (b)) & 1)
  #define bitSet(v, b)   ((v) |= (1UL << (b)))
  #define bitClear(v, b) ((v) &= ~(1UL << (b)))
#endif

// --- palettes --------------------------------------------------------------
// The REAL WLED set, not a handful of hand-copied gradients. wled00/palettes.cpp
// is compiled straight into the simulator, so the seven FastLED palettes and
// the 59 cpt-city gradients are the same bytes the firmware ships, and
// Segment::loadPalette() below is a transcription of the firmware's own.
//
// This replaced a six-palette table whose ids did not line up with WLED's at
// all: a metadata default of pal=11 meant Rainbow on the device and landed on
// Mono here, so every effect that trusted its own default was previewed in
// greyscale. Ids now mean the same thing on both sides.
//
// The ID space, from wled00/const.h:
//     0                      default (effect's own, else Party)
//     1 .. 5                 dynamic - random, and the segment-colour ones
//     6 .. 12                FastLED palettes
//    13 .. 71                cpt-city gradients
//    72 ..200                user custom palettes, growing DOWN from 200
//   201 ..255                usermod palettes, growing DOWN from 255
constexpr size_t FASTLED_PALETTE_COUNT  = 7;
constexpr size_t GRADIENT_PALETTE_COUNT = 59;
constexpr size_t DYNAMIC_PALETTE_COUNT  = 6;
constexpr size_t FIXED_PALETTE_COUNT    = DYNAMIC_PALETTE_COUNT + FASTLED_PALETTE_COUNT + GRADIENT_PALETTE_COUNT;
constexpr uint8_t WLED_USERMOD_PALETTE_ID_BASE = 255;
constexpr uint8_t WLED_CUSTOM_PALETTE_ID_BASE  = 200;
constexpr size_t  WLED_MAX_USERMOD_PALETTES    = WLED_USERMOD_PALETTE_ID_BASE - WLED_CUSTOM_PALETTE_ID_BASE;

// Defined by wled00/palettes.cpp, compiled in by build.py.
extern const TProgmemRGBPalette16  PartyColors_gc22;
extern const TProgmemRGBPalette16* const fastledPalettes[];
extern const uint8_t* const gGradientPalettes[];

// A usermod registers palettes by pushing into this vector; the firmware reads
// the entry LIVE on every frame, which is what lets a usermod repaint a palette
// continuously and have it show up under any effect. Same contract here.
struct UsermodPalette {
  CRGBPalette16 palette;
  const char   *name;
  uint8_t       palIndex;
  const char   *palName;
};
extern std::vector<UsermodPalette> usermodPalettes;
extern std::vector<CRGBPalette16>  customPalettes;
size_t removeUsermodPalettes(const char *name);
int    simPaletteCount();

class Segment;
extern Segment *_segPtr;

// How a 1-D effect is laid onto a 2-D segment. FX.h's mapping1D2D_t.
enum mapping1D2D_t : uint8_t {
  M12_Pixels = 0, M12_pBar = 1, M12_pArc = 2, M12_pCorner = 3, M12_sPinwheel = 4
};

class Segment {
 public:
  static int _vw, _vh;
  // The segment is 1-D when the host set it up with a height of 1 - the
  // same test FX.h makes: is2D() is width() > 1 && height() > 1. Everything
  // that used to assume 2-D now asks.
  static int  vWidth()  { return _vw; }
  static int  vHeight() { return _vh; }
  static bool is2Ds()   { return _vw > 1 && _vh > 1; }
  int virtualWidth()  const { return _vw; }
  int virtualHeight() const { return _vh; }
  int width()  const { return _vw; }          // stock WLED effects use these
  int height() const { return _vh; }
  bool is2D() const { return is2Ds(); }
  static uint8_t map1D2D;                     // mapping1D2D_t, host-set

  // Transcribed from Segment::virtualLength(), FX_fcn.cpp: the length a 1-D
  // effect sees on a 2-D segment depends on how it is being expanded.
  static int vLength() {
    if (is2Ds()) {
      switch (map1D2D) {
        case M12_pBar:    return _vh;
        case M12_pCorner: return _vw > _vh ? _vw : _vh;
        case M12_pArc:    return (int)sqrtf((float)(_vh * _vh + _vw * _vw));
        default:          return _vw * _vh;
      }
    }
    return _vw * _vh;
  }

  // Built from the same 16-stop tables color_from_palette() uses, so a stock
  // effect and one of ours put side by side are drawing from the same colours.
  const CRGBPalette16 &currentPalette() const;

  uint8_t  speed = 128, intensity = 128;
  uint8_t  custom1 = 128, custom2 = 128;
  // custom3 is FIVE BITS in the firmware - `uint8_t custom3 : 5` in FX.h, range
  // 0..31, and WLED's own effects treat it that way (`map(custom3, 0, 31, ...)`,
  // and a comment calling it the reduced resolution slider).
  //
  // This shim declared it as a full byte, and that single mismatch made the
  // simulator lie about every effect that scales custom3 as if it were 0..255.
  // Anything tuned here against a value above 31 was tuned against a setting
  // the hardware cannot reach - json.cpp constrains the incoming value to
  // 0..31 before it is stored, so a request for 210 arrives as 31.
  //
  // simParams() applies that same constraint, so the two agree. Matching the
  // firmware means the simulator now fails the same way the cube does, which is
  // the only way it is worth anything.
  uint8_t  custom3 : 5;
  Segment() : custom3(16) {}
  bool     check1 = false, check2 = false, check3 = false;
  uint8_t  palette = 11, soundSim = 0, mode = 0;
  // WLED's own DEFAULT_COLOR (FX.h) is 0xFFA000, so a fresh install shows amber
  // wherever an effect paints with SEGCOLOR(0). This was 0xFFAA00 - close
  // enough to look right and wrong enough to be a different colour.
  uint32_t colors[3] = { 0xFFA000u, 0u, 0u };

  uint32_t *pixels = nullptr;          // the frame the renderers read
  uint8_t  *data   = nullptr;          // effect scratch
  // size_t, and NOT uint16_t. WLED declares this `unsigned` and compares
  // `_dataLen >= len` with no cast; narrowing it here silently wrapped every
  // allocation over 64 KB.
  //
  // It took a segfault to find, because it only bites when a SMALLER
  // allocation precedes a larger one that truncates below it. Spectral Bloom on
  // a 96x96 net wants 58 KB as a cube and 83 KB flat, because flat mode lights
  // all nine face-blocks where the cube lights five. 83074 truncates to 17538,
  // which is less than the 58 KB already held, so the reuse test passed and the
  // effect wrote 24 KB past its buffer. Allocating the flat size FIRST hides it
  // completely - calloc gets the real size - which is why a fuzz that set flat
  // mode before selecting the effect found nothing.
  size_t    _dataLen = 0;
  uint32_t  call = 0, step = 0;
  uint16_t  aux0 = 0, aux1 = 0;
  // Segment options the 1-D effects read. One segment covering everything,
  // never reversed or mirrored - the front end has no such controls yet.
  bool     reverse = false, mirror = false, reverse_y = false, mirror_y = false;
  uint16_t start = 0, stop = 0, offset = 0;
  // FX.h: number of virtual vertical strips a 1-D effect is expanded onto -
  // the width in bar mode, one otherwise.
  unsigned nrOfVStrips() const { return (is2D() && map1D2D == M12_pBar) ? (unsigned)_vw : 1u; }

  void markForReset() { call = 0; }

  // WLED's semantics, deliberately: reuse a buffer that is already big enough,
  // and do NOT reset `call` when the requirement shrinks. Effects are written
  // around this, so getting it "cleaner" here would hide real bugs.
  bool allocateData(size_t len) {
    if (data && _dataLen >= len) return true;
    if (data) free(data);
    data = (uint8_t *)calloc(len, 1);
    if (!data) { _dataLen = 0; return false; }
    _dataLen = len;
    return true;
  }

  void fill(uint32_t c) { for (int i = 0; i < _vw * _vh; i++) pixels[i] = c; }
  void setPixelColorXY(int x, int y, uint32_t c) {
    if (x < 0 || y < 0 || x >= _vw || y >= _vh) return;
    pixels[y * _vw + x] = c;
  }
  // Stock effects hand this a CRGB. WLED's real Segment overloads for it, and
  // CRGB's uint32_t conversion is explicit, so the overload is required rather
  // than optional.
  void setPixelColorXY(int x, int y, const CRGB &c) {
    setPixelColorXY(x, y, RGBW32(c.r, c.g, c.b, 0));
  }
  uint32_t getPixelColorXY(int x, int y) const {
    if (x < 0 || y < 0 || x >= _vw || y >= _vh) return 0;
    return pixels[y * _vw + x];
  }
  void addPixelColorXY(int x, int y, uint32_t c, bool pc = true) {
    setPixelColorXY(x, y, color_add(getPixelColorXY(x, y), c, pc));
  }
  void fadeToBlackBy(uint8_t n) {
    for (int i = 0; i < _vw * _vh; i++) pixels[i] = color_fade(pixels[i], 255 - n);
  }
  // Separable blur, run FORWARDS AND BACKWARDS on each axis.
  //
  // A single pass per axis is a causal IIR filter: every pixel takes from the
  // one before it and the result feeds the next, so the whole field creeps
  // toward +x and +y a little on every frame. One frame it is invisible; over a
  // few hundred it walks the picture into the corner and off the grid. Frizzles
  // renders correctly for ten seconds and then decays to nothing, and any
  // effect that leans on blur was drifting the same way, just less visibly.
  // WLED calls blur2D(amount, amount, smear), which is symmetric; running the
  // second pass in reverse cancels the bias.
  void blur(uint8_t n, bool = false) {
    if (!n) return;
    const uint8_t keep = 255 - n;
    for (int y = 0; y < _vh; y++) {
      for (int x = 1; x < _vw; x++)
        pixels[y*_vw+x] = color_add(color_fade(pixels[y*_vw+x], keep),
                                    color_fade(pixels[y*_vw+x-1], n), true);
      for (int x = _vw - 2; x >= 0; x--)
        pixels[y*_vw+x] = color_add(color_fade(pixels[y*_vw+x], keep),
                                    color_fade(pixels[y*_vw+x+1], n), true);
    }
    for (int x = 0; x < _vw; x++) {
      for (int y = 1; y < _vh; y++)
        pixels[y*_vw+x] = color_add(color_fade(pixels[y*_vw+x], keep),
                                    color_fade(pixels[(y-1)*_vw+x], n), true);
      for (int y = _vh - 2; y >= 0; y--)
        pixels[y*_vw+x] = color_add(color_fade(pixels[y*_vw+x], keep),
                                    color_fade(pixels[(y+1)*_vw+x], n), true);
    }
  }
  void blur2D(uint8_t n, bool b = false) { blur(n, b); }

  // --- what the stock 2-D effects reach for --------------------------------
  // Reimplementations, not extractions: these are Segment methods spread across
  // FX_fcn.cpp and FX_2Dfcn.cpp and entangled with segment state this shim does
  // not model (grouping, spacing, transitions, raw buffers). The ALGORITHMS are
  // copied from those sources - fade_out's mapped rate, wu_pixel's weights and
  // its don't-repaint check, fillCircle's span fill - so the effects behave as
  // they do on the device. What is dropped is the segment machinery around
  // them, which the simulator has never modelled and which none of these
  // effects depend on.
  int length() const { return vLength(); }
  int virtualLength() const { return vLength(); }
  int rawLength() const { return _vw * _vh; }

  // The 1-D accessors. Transcribed from Segment::setPixelColor(int) and
  // getPixelColor(int) in FX_fcn.cpp: on a 1-D segment they are the raw
  // buffer; on a 2-D one they EXPAND the 1-D effect according to map1D2D,
  // which is what lets every stock 1-D effect run on a matrix or a cube the
  // way it does on the device. Virtual strips (index >> 16) are honoured for
  // the bar mode, as on the device. Pinwheel falls back to Pixels.
  void setPixelColor(int i, uint32_t c) {
    if (i < 0) return;
    int vStrip = 0;
    const int vL = vLength();
    if (i >= vL) { vStrip = i >> 16; i &= 0xFFFF; if (i >= vL) return; }
    if (is2Ds()) {
      const int vW = _vw, vH = _vh;
      switch (map1D2D) {
        case M12_pBar:
          if (vStrip > 0) setPixelColorXY(vStrip - 1, vH - i - 1, c);
          else for (int x = 0; x < vW; x++) setPixelColorXY(x, vH - i - 1, c);
          break;
        case M12_pArc:
          if (i == 0) setPixelColorXY(0, 0, c);
          else {
            const float r = (float)i;
            const float step = 1.57079637f / (2.8284f * r + 4.0f);
            for (float rad = 0.0f; rad <= 0.78539819f + step * 0.5f; rad += step) {
              const int x = (int)roundf(sinf(rad) * r), y = (int)roundf(cosf(rad) * r);
              setPixelColorXY(x, y, c); setPixelColorXY(y, x, c);
            }
          }
          break;
        case M12_pCorner:
          for (int x = 0; x <= i; x++) setPixelColorXY(x, i, c);
          for (int y = 0; y <  i; y++) setPixelColorXY(i, y, c);
          break;
        default:
          setPixelColorXY(i % vW, i / vW, c);
          break;
      }
      return;
    }
    pixels[i] = c;
  }
  uint32_t getPixelColor(int i) const {
    if (i < 0) return 0;
    const int vStrip = i >> 16;
    i &= 0xFFFF;
    if (i >= vLength()) return 0;
    if (is2Ds()) {
      const int vW = _vw, vH = _vh;
      int x = 0, y = 0;
      switch (map1D2D) {
        case M12_pBar:
          if (vStrip > 0) { x = vStrip - 1; y = vH - i - 1; } else y = vH - i - 1;
          break;
        case M12_pArc:
          if (i > vW && i > vH) { x = y = (int)sqrtf((float)(i * i / 2)); break; }
          /* fall through */
        case M12_pCorner:
          if (vW > vH) x = i; else y = i;
          break;
        default:
          x = i % vW; y = i / vW;
          break;
      }
      return getPixelColorXY(x, y);
    }
    return pixels[i];
  }
  // CRGB's operator uint32_t is EXPLICIT, so passing one where a colour is
  // wanted needs a real overload rather than a conversion.
  void setPixelColor(int i, const CRGB &c) {
    setPixelColor(i, RGBW32(c.r, c.g, c.b, 0));
  }
  void addPixelColor(int i, uint32_t c, bool pc = true) {
    setPixelColor(i, color_add(getPixelColor(i), c, pc));
  }
  void fadePixelColor(int i, uint8_t fade) {
    setPixelColor(i, color_fade(getPixelColor(i), 255 - fade));
  }
  void blendPixelColor(int i, uint32_t c, uint8_t blend) {
    setPixelColor(i, color_blend(getPixelColor(i), c, blend));
  }

  // Shift the whole field one step. dir is 0..7 clockwise from up.
  void move(uint8_t dir, uint8_t delta, bool = true) {
    if (!delta) return;
    static const int DX[8] = { 0, 1, 1, 1, 0, -1, -1, -1 };
    static const int DY[8] = { -1, -1, 0, 1, 1, 1, 0, -1 };
    const int dx = DX[dir & 7] * delta, dy = DY[dir & 7] * delta;
    const int n = _vw * _vh;
    uint32_t *tmp = (uint32_t *)malloc(sizeof(uint32_t) * n);
    if (!tmp) return;
    memcpy(tmp, pixels, sizeof(uint32_t) * n);
    for (int y = 0; y < _vh; y++)
      for (int x = 0; x < _vw; x++) {
        const int sx = x - dx, sy = y - dy;
        pixels[y * _vw + x] = (sx >= 0 && sy >= 0 && sx < _vw && sy < _vh)
                              ? tmp[sy * _vw + sx] : 0u;
      }
    free(tmp);
  }

  void fadePixelColorXY(int x, int y, uint8_t fade) {
    setPixelColorXY(x, y, color_fade(getPixelColorXY(x, y), 255 - fade));
  }

  void fade_out(uint8_t rate) {
    rate = (uint8_t)((256 - rate) >> 1);
    const int mapped = 256 / (rate + 1);
    for (int i = 0; i < _vw * _vh; i++) {
      const uint32_t c = pixels[i];
      if (c == colors[1]) continue;                 // already at target
      uint32_t out = 0;
      for (int sh = 0; sh < 32; sh += 8) {
        const int c2 = (int)((colors[1] >> sh) & 0xFF);
        const int c1 = (int)((c >> sh) & 0xFF);
        int d = (c2 - c1) * mapped / 256;
        if (d == 0) d = (c2 == c1) ? 0 : (c2 > c1 ? 1 : -1);
        out |= (uint32_t)((c1 + d) & 0xFF) << sh;
      }
      pixels[i] = out;
    }
  }

  uint32_t color_wheel(uint8_t pos) const {
    if (palette) return color_from_palette(pos, false, true, 0);
    uint8_t rgb[4];
    hsv2rgb_rainbow((uint16_t)(pos << 8), 255, 255, rgb, false);
    return RGBW32(rgb[0], rgb[1], rgb[2], 0);
  }

  void fillCircle(int cx, int cy, int radius, uint32_t col, bool = false) {
    if (radius <= 0) return;
    for (int y = -radius; y <= radius; y++)
      for (int x = -radius; x <= radius; x++) {
        if (x * x + y * y > radius * radius + radius) continue;
        const int px = cx + x, py = cy + y;
        if (px < 0 || py < 0 || px >= _vw || py >= _vh) continue;
        setPixelColorXY(px, py, col);
      }
  }

  // Wu antialiased point, from the version in FX_2Dfcn.cpp. The weights and the
  // "do not repaint an unchanged pixel" test are the same; several effects lean
  // on the softness this gives, and a nearest-pixel stand-in makes them look
  // like a different effect entirely.
  void wu_pixel(uint32_t x, uint32_t y, const CRGB &c) {
    #define _WUW(a, b) ((uint8_t)(((a) * (b) + (a) + (b)) >> 8))
    const unsigned xx = x & 0xff, yy = y & 0xff, ix = 255 - xx, iy = 255 - yy;
    const uint8_t wu[4] = { _WUW(ix, iy), _WUW(xx, iy), _WUW(ix, yy), _WUW(xx, yy) };
    for (int i = 0; i < 4; i++) {
      const int wx = (int)(x >> 8) + (i & 1), wy = (int)(y >> 8) + ((i >> 1) & 1);
      if (wx < 0 || wy < 0 || wx >= _vw || wy >= _vh) continue;
      const uint32_t old = getPixelColorXY(wx, wy);
      const uint32_t nw = RGBW32(qadd8(R(old), (uint8_t)((c.r * wu[i]) >> 8)),
                                 qadd8(G(old), (uint8_t)((c.g * wu[i]) >> 8)),
                                 qadd8(B(old), (uint8_t)((c.b * wu[i]) >> 8)), 0);
      if (nw != old) setPixelColorXY(wx, wy, nw);
    }
    #undef _WUW
  }

  uint32_t color_from_palette(uint16_t i, bool mapping, bool moving,
                              uint8_t mcol, uint8_t pbri = 255) const {
    if (palette == 0 && mcol < 3) return color_fade(colors[mcol], pbri);
    unsigned idx = i;
    if (mapping) idx = (i * 255) / (_vw * _vh ? _vw * _vh : 1);
    // The wrap distinction is not cosmetic: asking for the no-wrap form is what
    // put three hard seams through Soap's colour when the index swept the
    // palette more than once.
    return ColorFromPalette(currentPalette(), (uint8_t)idx, pbri,
                            moving ? LINEARBLEND : LINEARBLEND_NOWRAP);
  }
};

class WS2812FX {
 public:
  Segment *_currentSegment = nullptr;
  uint32_t now = 0;
  bool isMatrix = true;
  Segment &getSegment(int)        { return *_currentSegment; }
  unsigned getSegmentsNum() const { return 1; }
  unsigned getMainSegmentId() const { return 0; }
  unsigned getCurrSegmentId() const { return 0; }
  unsigned getActiveSegmentsNum() const { return 1; }
  uint8_t  getModeCount() const   { return 1; }
  const char *getModeData(unsigned = 0) const { return ""; }
  uint8_t  addEffect(uint8_t, void (*)(), const char *) { return 0; }
};
extern WS2812FX strip;

// --- beat generators --------------------------------------------------------
// Copied from wled00/util.cpp rather than approximated: they are the clock the
// stock effects move to, and the exact sawtooth matters. millis() is the
// simulated clock, so a beat here lands where it lands on the device.
static inline uint32_t millis();
static inline uint16_t beat88(uint16_t bpm88, uint32_t tb = 0) {
  return (uint16_t)(((millis() - tb) * bpm88 * 280) >> 16);
}
static inline uint16_t beat16(uint16_t bpm, uint32_t tb = 0) {
  if (bpm < 256) bpm <<= 8;
  return beat88(bpm, tb);
}
static inline uint8_t beat8(uint16_t bpm, uint32_t tb = 0) { return beat16(bpm, tb) >> 8; }
static inline uint16_t beatsin16_t(uint16_t bpm, uint16_t lo = 0, uint16_t hi = 65535,
                                   uint32_t tb = 0, uint16_t phase = 0) {
  const uint16_t b = (uint16_t)(sin16_t((uint16_t)(beat16(bpm, tb) + phase)) + 32768);
  return (uint16_t)(lo + scale16(b, (uint16_t)(hi - lo)));
}
static inline uint8_t beatsin8_t(uint16_t bpm, uint8_t lo = 0, uint8_t hi = 255,
                                 uint32_t tb = 0, uint8_t phase = 0) {
  const uint8_t b = (uint8_t)(sin8_t((uint8_t)(beat8(bpm, tb) + phase)));
  return (uint8_t)(lo + scale8(b, (uint8_t)(hi - lo)));
}

// Deliberately the SIMULATED clock, not the wall clock. The page advances time
// by an explicit dt each frame, so effects that lean on millis() (the IMU's
// staleness checks, the param-memory timers) stay in step with the ones that
// use strip.now - and a paused frame is genuinely frozen rather than drifting
// while you look at it.
static inline uint32_t millis() { return strip.now; }
static inline uint32_t micros() { return strip.now * 1000u; }

// The FX_MODE_* ids, lifted from FX.h by build.py so an effect that compares
// SEGMENT.mode against one - mode_android does - sees the device's numbers.
#if __has_include("../gen/fx_modes.h")
  #include "../gen/fx_modes.h"
#endif

#define SEGMENT      (*strip._currentSegment)
#define SEGENV       (*strip._currentSegment)
#define SEG_W        Segment::vWidth()
#define SEG_H        Segment::vHeight()
#define SEGCOLOR(x)  (SEGMENT.colors[x])
#define SEGPALETTE   (SEGMENT.currentPalette())
#define FRAMETIME    23
#define WLED_FPS     42
#define FRAMETIME_FIXED (1000/WLED_FPS)
#define MIN(a,b)     ((a)<(b)?(a):(b))
#define MAX(a,b)     ((a)>(b)?(a):(b))
#ifndef M_TWOPI
  #define M_TWOPI 6.283185307179586
#endif

// --- what the stock 1-D effects reach for --------------------------------------
// paletteBlend is the global palette-blend setting (0 wrap when moving, 1 wrap,
// 2 never, 3 always). WLED's default is 0.
static uint8_t paletteBlend = 0;

// beatsin88_t, wled_math.cpp: bpm in 8.8 fixed point.
static inline uint16_t beatsin88_t(uint16_t bpm88, uint16_t lo = 0, uint16_t hi = 65535,
                                   uint32_t tb = 0, uint16_t phase = 0) {
  const uint16_t b = (uint16_t)(sin16_t((uint16_t)(beat88(bpm88, tb) + phase)) + 32768);
  return (uint16_t)(lo + scale16(b, (uint16_t)(hi - lo)));
}

// util.cpp, verbatim: a colour-wheel index at least 42 away from the last.
static inline uint8_t get_random_wheel_index(uint8_t pos) {
  uint8_t r = 0, x = 0, y = 0, d = 0;
  while (d < 42) {
    r = hw_random8();
    x = (uint8_t)abs((int)pos - (int)r);
    y = (uint8_t)(255 - x);
    d = MIN(x, y);
  }
  return r;
}

// The traffic light asks for its pre-16.0 colours through the inverse gamma.
// The simulator applies no gamma at all, so the inverse is the identity here -
// which is the honest reading: with no gamma applied, nothing is there to
// invert.
static inline uint32_t gamma32inv(uint32_t c) { return c; }

// Usermod base + registration, stubbed: the effect files each declare a
// CfxBankReg, and that static registration is exactly the effect list the
// simulator enumerates - so the roster comes for free and cannot disagree with
// what the firmware would register.
// Usermods are REAL here now, not stubs. They were stubbed while the only
// usermod-shaped code in this folder was effect registration, which happens
// through CfxBankReg instead - but a usermod that registers and repaints
// palettes has to actually run, and its loop() is where the audio-reactive
// gradients are rewritten. sim_main drives setup() once and loop() per frame.
class Usermod;
void simRegisterUsermod(Usermod *u);

class Usermod {
 public:
  virtual ~Usermod() {}
  virtual void setup() {}
  virtual void loop() {}
  virtual uint16_t getId() { return 0; }
  // The settings hooks exist so a usermod that HAS settings still compiles
  // here. They are never called - there is no settings page and no cfg.json -
  // so a usermod keeps its compiled-in defaults, which is what readFromConfig
  // returning false says.
  virtual void addToConfig(JsonObject &) {}
  virtual bool readFromConfig(JsonObject &) { return false; }
  virtual void appendConfigData(Print &) {}
};
#define REGISTER_USERMOD(x) namespace { struct _umReg_##x { _umReg_##x() { simRegisterUsermod(&x); } } _umRegInst_##x; }
