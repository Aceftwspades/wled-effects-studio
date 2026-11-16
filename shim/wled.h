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
#include <cmath>                   // std::abs of a float (WLED's 1-D effects): a newer libc++ - Emscripten's on CI -
#include <cstdlib>                 // has it in std only through these two, not through math.h and stdlib.h
#include <utility>                 // std::swap, used by WLED's soapPixels
#include <algorithm>
using std::min;
using std::max;
#include "pgmspace.h"
#include "fastled_slim.h"                   // wled00/src/dependencies/fastled_slim, on the include path

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

// AI: below section was generated by an AI
// colors.cpp / colors.h, transcribed: the fade's "video" rounding (a channel
// that was lit stays lit unless it is under a quarter of the brightest, which
// is what fadePixelColor and its XY twin ask for), the add that keeps the
// colour's ratios on overflow instead of washing it to white (preserveCR), and
// the scale the blurs use. Each works on two channels at a time as WLED does,
// so the rounding is the device's to the bit.
static inline uint32_t color_fade(uint32_t c1, uint8_t amount, bool video = false) {
  if (c1 == 0 || amount == 0) return 0;     // black or a full fade
  if (amount == 255) return c1;             // no change
  const uint32_t TWO_CHANNEL_MASK = 0x00FF00FF;
  const uint32_t rb = c1 & TWO_CHANNEL_MASK, wg = (c1 >> 8) & TWO_CHANNEL_MASK;
  uint32_t rb_scaled, wg_scaled;
  if (video) {
    rb_scaled = ((rb * amount + 0x007F007F) >> 8) & TWO_CHANNEL_MASK;
    wg_scaled = (wg * amount + 0x007F007F) & ~TWO_CHANNEL_MASK;
    const uint8_t r = (uint8_t)(rb >> 16), g = (uint8_t)wg, b = (uint8_t)rb, w = (uint8_t)(wg >> 16);
    uint8_t maxc = (r > g) ? ((r > b) ? r : b) : ((g > b) ? g : b);
    maxc = (maxc >> 2) + 1;                 // a channel over ~25% of the brightest keeps its last step
    rb_scaled |= r > maxc ? 0x00010000 : 0;
    wg_scaled |= g > maxc ? 0x00000100 : 0;
    rb_scaled |= b > maxc ? 0x00000001 : 0;
    wg_scaled |= w ? 0x01000000 : 0;
  } else {
    rb_scaled = ((rb * (amount + 1)) >> 8) & TWO_CHANNEL_MASK;
    wg_scaled = ((wg * (amount + 1)) & ~TWO_CHANNEL_MASK);
  }
  return rb_scaled | wg_scaled;
}
static inline uint32_t color_add(uint32_t c1, uint32_t c2, bool preserveCR = false) {
  if (c1 == 0) return c2;
  if (c2 == 0) return c1;
  const uint32_t TWO_CHANNEL_MASK = 0x00FF00FF;
  uint32_t rb = (c1 & TWO_CHANNEL_MASK) + (c2 & TWO_CHANNEL_MASK);
  uint32_t wg = ((c1 >> 8) & TWO_CHANNEL_MASK) + ((c2 >> 8) & TWO_CHANNEL_MASK);
  if (preserveCR) {                         // scale all four down by the one that overflowed most
    if ((rb | wg) & 0x01000100) {
      const uint32_t r = rb >> 16, b = rb & 0xFFFF, w = wg >> 16, g = wg & 0xFFFF;
      uint32_t maxval = (r > g) ? ((r > b) ? r : b) : ((g > b) ? g : b);
      maxval = (w > maxval) ? w : maxval;
      const uint32_t scale = (uint32_t(255) << 8) / maxval;
      rb = ((rb * scale) >> 8) & TWO_CHANNEL_MASK;
      wg = (wg * scale) & ~TWO_CHANNEL_MASK;
    } else wg <<= 8;
  } else {                                  // each channel saturates at 255
    rb |= ((rb & 0x01000100) - ((rb >> 8) & 0x00010001)) & 0x00FF00FF;
    wg |= ((wg & 0x01000100) - ((wg >> 8) & 0x00010001)) & 0x00FF00FF;
    wg <<= 8;
  }
  return rb | wg;
}
static inline uint32_t fast_color_scale(const uint32_t c, const uint8_t scale) {
  const uint32_t rb = (((c & 0x00FF00FF) * scale) >> 8) & 0x00FF00FF;
  const uint32_t wg = (((c >> 8) & 0x00FF00FF) * scale) & ~0x00FF00FF;
  return rb | wg;
}
// AI: end

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
// AI: below section was generated by an AI
// colors.cpp: (C1*(256-blend) + C2 + C2*blend) / 256 a channel. The plain
// (C1*(255-b) + C2*b) >> 8 it replaces lost a step of brightness every blend,
// so a trail blended toward its own colour drained to black here and not there.
static inline uint32_t color_blend(uint32_t color1, uint32_t color2, uint8_t blend) {
  const uint32_t TWO_CHANNEL_MASK = 0x00FF00FF;
  const uint32_t rb1 = color1 & TWO_CHANNEL_MASK, wg1 = (color1 >> 8) & TWO_CHANNEL_MASK;
  const uint32_t rb2 = color2 & TWO_CHANNEL_MASK, wg2 = (color2 >> 8) & TWO_CHANNEL_MASK;
  const uint32_t rb3 = ((((rb1 << 8) | rb2) + (rb2 * blend) - (rb1 * blend)) >> 8) & TWO_CHANNEL_MASK;
  const uint32_t wg3 = ((((wg1 << 8) | wg2) + (wg2 * blend) - (wg1 * blend))) & ~TWO_CHANNEL_MASK;
  return rb3 | wg3;
}
// AI: end
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

// --- WLED's 32-bit colour types (wled00/colors.h, colors.cpp) -----------------
// Copied, not approximated: Twinklefox, Twinklecat, Pride 2015, Colorwaves,
// Aurora and Colortwinkle build their colours in these, and without them six
// of WLED's best-known 1-D effects were left out of the simulator. The layouts
// match the firmware's (CRGBW's bytes are B, G, R, W - a 0xWWRRGGBB word).
struct CRGBW;
struct CHSV32 {                                   // HSV with a 16-bit hue
  union {
    struct { uint16_t h; uint8_t s; uint8_t v; };
    uint32_t hsv32;
  };
  inline CHSV32() = default;
  inline CHSV32(uint16_t ih, uint8_t is, uint8_t iv) : h(ih), s(is), v(iv) {}
  inline CHSV32(uint8_t ih, uint8_t is, uint8_t iv) : h((uint16_t)ih << 8), s(is), v(iv) {}
  inline CHSV32(const CHSV &chsv) : h((uint16_t)chsv.h << 8), s(chsv.s), v(chsv.v) {}
  inline operator CHSV() const { return CHSV((uint8_t)(h >> 8), s, v); }
  inline CHSV32(const CRGBW &rgb);
  inline CHSV32 &operator=(const CRGBW &rgb);
};
static inline void hsv2rgb_spectrum(const CHSV32 &hsv, CRGBW &rgb);
struct CRGBW {                                    // a 32-bit colour, 0xWWRRGGBB
  union {
    uint32_t color32;
    struct { uint8_t b; uint8_t g; uint8_t r; uint8_t w; };
    uint8_t raw[4];
  };
  inline CRGBW() = default;
  constexpr CRGBW(uint32_t color) : color32(color) {}
  constexpr CRGBW(uint8_t red, uint8_t green, uint8_t blue, uint8_t white = 0) : b(blue), g(green), r(red), w(white) {}
  constexpr CRGBW(CRGB rgb) : b(rgb.b), g(rgb.g), r(rgb.r), w(0) {}
  inline CRGBW(CHSV32 hsv) { hsv2rgb_rainbow(hsv.h, hsv.s, hsv.v, raw, true); }
  inline CRGBW(CHSV hsv) { hsv2rgb_rainbow(hsv.h << 8, hsv.s, hsv.v, raw, true); }
  inline const uint8_t &operator[](uint8_t x) const { return raw[x]; }
  inline CRGBW &operator=(uint32_t color) { color32 = color; return *this; }
  inline CRGBW &operator=(CHSV32 hsv) { hsv2rgb_rainbow(hsv.h, hsv.s, hsv.v, raw, true); return *this; }
  inline CRGBW &operator=(CHSV hsv) { hsv2rgb_rainbow(hsv.h << 8, hsv.s, hsv.v, raw, true); return *this; }
  inline CRGBW &operator=(const CRGB &rgb) { b = rgb.b; g = rgb.g; r = rgb.r; w = 0; return *this; }
  inline operator uint32_t() const { return color32; }
  inline void adjust_hue(int hueshift) {
    CHSV32 hsv = *this;
    hsv.h += hueshift << 8;
    hsv2rgb_spectrum(hsv, *this);
  }
  uint8_t getAverageLight() const { return (r + g + b + w) >> 2; }
  uint8_t getRGBaverage() const { return ((r + g + b) * 21846) >> 16; }
};
// colors.cpp: HSV (16-bit hue) to RGB, white 0
static inline void hsv2rgb_spectrum(const CHSV32 &hsv, CRGBW &rgb) {
  unsigned p, q, t;
  unsigned region = ((unsigned)hsv.h * 6) >> 16;
  unsigned remainder = (hsv.h - (region * 10923)) * 6;
  if (hsv.s == 0) { rgb.r = rgb.g = rgb.b = hsv.v; return; }
  p = (hsv.v * (255 - hsv.s)) >> 8;
  q = (hsv.v * (255 - ((hsv.s * remainder) >> 16))) >> 8;
  t = (hsv.v * (255 - ((hsv.s * (65535 - remainder)) >> 16))) >> 8;
  switch (region) {
    case 0:  rgb.r = hsv.v; rgb.g = t;     rgb.b = p;     break;
    case 1:  rgb.r = q;     rgb.g = hsv.v; rgb.b = p;     break;
    case 2:  rgb.r = p;     rgb.g = hsv.v; rgb.b = t;     break;
    case 3:  rgb.r = p;     rgb.g = q;     rgb.b = hsv.v; break;
    case 4:  rgb.r = t;     rgb.g = p;     rgb.b = hsv.v; break;
    default: rgb.r = hsv.v; rgb.g = p;     rgb.b = q;     break;
  }
}
static inline void hsv2rgb_spectrum(const CHSV &hsv, CRGB &rgb) {
  CRGBW rgb32;
  hsv2rgb_spectrum(CHSV32(hsv), rgb32);
  rgb = CRGB(rgb32.r, rgb32.g, rgb32.b);
}
// colors.cpp: RGB to HSV (16-bit hue), white ignored
static inline void rgb2hsv(const CRGBW &rgb, CHSV32 &hsv) {
  int32_t r = rgb.r, g = rgb.g, b = rgb.b;
  uint32_t maxval = (r > g) ? ((r > b) ? r : b) : ((g > b) ? g : b);
  if (maxval == 0) { hsv.hsv32 = 0; return; }
  uint32_t minval = (r < g) ? ((r < b) ? r : b) : ((g < b) ? g : b);
  hsv.v = maxval;
  int32_t delta = maxval - minval;
  if (delta != 0) {
    hsv.s = (255 * delta) / maxval;
    if ((int32_t)maxval == r)      hsv.h = (uint16_t)((10923 * (g - b)) / delta);
    else if ((int32_t)maxval == g) hsv.h = (uint16_t)(21845 + (10923 * (b - r)) / delta);
    else                           hsv.h = (uint16_t)(43690 + (10923 * (r - g)) / delta);
  } else {
    hsv.s = 0; hsv.h = 0;
  }
}
inline CHSV32::CHSV32(const CRGBW &rgb) { rgb2hsv(rgb, *this); }
inline CHSV32 &CHSV32::operator=(const CRGBW &rgb) { rgb2hsv(rgb, *this); return *this; }
static inline CRGBW hsv2rgb(const CHSV32 &hsv) { return CRGBW(hsv); }
static inline void  hsv2rgb(const CHSV32 &hsv, CRGBW &rgb) { rgb = CRGBW(hsv); }
static inline void  hsv2rgb(const CHSV32 &hsv, uint32_t &rgb) { rgb = CRGBW(hsv).color32; }

// FX.h: three colours a segment; the data a segment may fairly take - the
// ESP32's 64 KB over its 32 segments (Popcorn, Starburst and Exploding
// Fireworks size their particles from it)
#define NUM_COLORS        3
#define MAX_NUM_SEGMENTS  32
// fcn_declare.h's allocators (PSRAM first on a board that has it): the heap here
inline void *p_malloc(size_t n) { return malloc(n); }
inline void p_free(void *p) { free(p); }
#define MAX_SEGMENT_DATA  (64 * 1024)
#define FAIR_DATA_PER_SEG (MAX_SEGMENT_DATA / MAX_NUM_SEGMENTS)

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
#ifndef bitWrite
  #define bitWrite(v, b, bv) ((bv) ? bitSet(v, b) : bitClear(v, b))     // Arduino's (Colortwinkle keeps its state in bits)
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

  // AI: below section was generated by an AI
  // FX_fcn.cpp's Segment::allocateData, transcribed: a buffer already big
  // enough is reused, and cleared on the effect's first call when it is under
  // the fair share (a larger one keeps what it held, as on the device); and
  // what every segment holds together may not pass MAX_SEGMENT_DATA - the
  // limit of a board without PSRAM, which is what a firmware build targets
  // unless told otherwise. Over it the effect gets false, as there.
  static size_t &usedSegmentData() { static size_t used = 0; return used; }
  bool allocateData(size_t len) {
    if (len == 0) return false;
    if (data && _dataLen >= len) {
      if (call == 0 && _dataLen < FAIR_DATA_PER_SEG) memset(data, 0, len);
      return true;
    }
    if (usedSegmentData() + len - _dataLen > MAX_SEGMENT_DATA) return false;
    deallocateData();
    data = (uint8_t *)calloc(len, 1);
    if (!data) return false;
    usedSegmentData() += len;
    _dataLen = len;
    return true;
  }
  void deallocateData() {
    if (data) { free(data); usedSegmentData() -= _dataLen; }
    data = nullptr; _dataLen = 0;
  }
  // AI: end

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
  // FX.h's overload for channels given apart (Exploding Fireworks' flare on a matrix)
  void setPixelColorXY(int x, int y, uint8_t r, uint8_t g, uint8_t b, uint8_t w = 0) {
    setPixelColorXY(x, y, RGBW32(r, g, b, w));
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
  // AI: below section was generated by an AI
  // FX_fcn.cpp's Segment::blur and FX_2Dfcn.cpp's blur2D, transcribed: each
  // pixel keeps 255-n (all of it when smearing) and gives n/2 to each
  // neighbour, so nothing creeps one way. On a matrix blur() is blur2D both
  // ways; on a strip it runs along the strip. blurRows / blurCols are blur2D
  // with one axis at 0 (FX.h).
  void blur(uint8_t n, bool smear = false) {
    if (!n) return;
    if (is2D()) { blur2D(n, n, smear); return; }
    blurLine(0, 1, _vw * _vh, n, smear);
  }
  void blur2D(uint8_t blur_x, uint8_t blur_y, bool smear = false) {
    if (blur_x) for (int y = 0; y < _vh; y++) blurLine(y * _vw, 1, _vw, blur_x, smear);
    if (blur_y) for (int x = 0; x < _vw; x++) blurLine(x, _vw, _vh, blur_y, smear);
  }
  void blurRows(uint8_t n, bool smear = false) { blur2D(n, 0, smear); }
  void blurCols(uint8_t n, bool smear = false) { blur2D(0, n, smear); }
  // one row, column or strip: `len` pixels from `start`, `stride` apart
  void blurLine(int start, int stride, int len, uint8_t amount, bool smear) {
    if (len <= 0) return;
    const uint8_t keep = smear ? 255 : 255 - amount, seep = amount >> 1;
    uint32_t cur = pixels[start];
    uint32_t carryover = fast_color_scale(cur, seep);
    pixels[start] = fast_color_scale(cur, keep);
    for (int k = 1; k < len; k++) {
      const int i = start + k * stride;
      cur = pixels[i];
      const uint32_t part = fast_color_scale(cur, seep);
      cur = color_add(fast_color_scale(cur, keep), carryover);
      pixels[i - stride] = color_add(pixels[i - stride], part);     // the pixel before
      pixels[i] = cur;
      carryover = part;
    }
  }
  // AI: end

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
  // FX.h's own overload for channels given apart (Fire Flicker, TV Simulator)
  void setPixelColor(int i, uint8_t r, uint8_t g, uint8_t b, uint8_t w = 0) {
    setPixelColor(i, RGBW32(r, g, b, w));
  }
  void addPixelColor(int i, uint32_t c, bool pc = true) {
    setPixelColor(i, color_add(getPixelColor(i), c, pc));
  }
  // FX.h: the amount is what is KEPT (255 leaves it), faded the "video" way
  void fadePixelColor(int i, uint8_t fade) {
    setPixelColor(i, color_fade(getPixelColor(i), fade, true));
  }
  void blendPixelColor(int i, uint32_t c, uint8_t blend) {
    setPixelColor(i, color_blend(getPixelColor(i), c, blend));
  }

  // AI: below section was generated by an AI
  // FX_2Dfcn.cpp's moveX / moveY / move, transcribed. dir: 0 = moveX(+d) (the
  // picture goes left), 1 = left-up, 2 = moveY(+d) (up), 3 = right-up, 4 =
  // right, 5 = right-down, 6 = down, 7 = left-down. Without wrap the pixels
  // shifted in keep what they held (the device does not clear them); a delta
  // as large as the side does nothing.
  void moveX(int delta, bool wrap = false) {
    const int vW = _vw, vH = _vh, absDelta = delta < 0 ? -delta : delta;
    if (!delta || absDelta >= vW) return;
    uint32_t *col = (uint32_t *)malloc(sizeof(uint32_t) * vW);
    if (!col) return;
    int newDelta, stop = vW, start = 0;
    if (wrap) newDelta = (delta + vW) % vW;
    else { if (delta < 0) start = absDelta; stop = vW - absDelta; newDelta = delta > 0 ? delta : 0; }
    for (int y = 0; y < vH; y++) {
      for (int x = 0; x < stop; x++) { int sx = x + newDelta; if (wrap) sx %= vW; col[x] = pixels[y * vW + sx]; }
      for (int x = 0; x < stop; x++) pixels[y * vW + x + start] = col[x];
    }
    free(col);
  }
  void moveY(int delta, bool wrap = false) {
    const int vW = _vw, vH = _vh, absDelta = delta < 0 ? -delta : delta;
    if (!delta || absDelta >= vH) return;
    uint32_t *col = (uint32_t *)malloc(sizeof(uint32_t) * vH);
    if (!col) return;
    int newDelta, stop = vH, start = 0;
    if (wrap) newDelta = (delta + vH) % vH;
    else { if (delta < 0) start = absDelta; stop = vH - absDelta; newDelta = delta > 0 ? delta : 0; }
    for (int x = 0; x < vW; x++) {
      for (int y = 0; y < stop; y++) { int sy = y + newDelta; if (wrap) sy %= vH; col[y] = pixels[sy * vW + x]; }
      for (int y = 0; y < stop; y++) pixels[(y + start) * vW + x] = col[y];
    }
    free(col);
  }
  void move(unsigned dir, unsigned delta, bool wrap = false) {
    if (delta == 0) return;
    const int d = (int)delta;
    switch (dir) {
      case 0: moveX( d, wrap);                  break;
      case 1: moveX( d, wrap); moveY( d, wrap); break;
      case 2:                  moveY( d, wrap); break;
      case 3: moveX(-d, wrap); moveY( d, wrap); break;
      case 4: moveX(-d, wrap);                  break;
      case 5: moveX(-d, wrap); moveY(-d, wrap); break;
      case 6:                  moveY(-d, wrap); break;
      case 7: moveX( d, wrap); moveY(-d, wrap); break;
    }
  }
  // AI: end

  void fadePixelColorXY(int x, int y, uint8_t fade) {
    setPixelColorXY(x, y, color_fade(getPixelColorXY(x, y), fade, true));
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

  // FX_2Dfcn.cpp's drawCircle: the outline - Xiaolin Wu's when soft, Bresenham's
  // otherwise (Ripple and Ripple Rainbow on a matrix)
  void drawCircle(int cx, int cy, int radius, uint32_t col, bool soft = false) {
    if (radius <= 0) return;
    if (soft) {
      const int rsq = radius * radius;
      int x = 0, y = radius;
      unsigned oldFade = 0;
      while (x < y) {
        const float yf = sqrtf((float)(rsq - x * x));
        const uint8_t fade = (uint8_t)(255.0f * (ceilf(yf) - yf));
        if (oldFade > fade) y--;
        oldFade = fade;
        for (uint8_t i = 0; i < 16; i++) {
          const int swaps = (i & 0x4) ? 1 : 0, adj = (i < 8) ? 0 : 1;
          const int dx = (i & 1) ? -1 : 1, dy = (i & 2) ? -1 : 1;
          const int px = swaps ? cx + (y - adj) * dx : cx + x * dx;
          const int py = swaps ? cy + x * dy : cy + (y - adj) * dy;
          const uint32_t pixCol = getPixelColorXY(px, py);
          setPixelColorXY(px, py, adj ? color_blend(pixCol, col, fade) : color_blend(col, pixCol, fade));
        }
        x++;
      }
    } else {
      int d = 3 - 2 * radius, y = radius, x = 0;
      while (y >= x) {
        for (int i = 0; i < 4; i++) {
          const int dx = (i & 1) ? -x : x, dy = (i & 2) ? -y : y;
          setPixelColorXY(cx + dx, cy + dy, col);
          setPixelColorXY(cx + dy, cy + dx, col);
        }
        x++;
        if (d > 0) { y--; d += 4 * (x - y) + 10; } else d += 4 * x + 6;
      }
    }
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
  unsigned _segIndex = 0;               // the segment being drawn (sim_main.cpp sets it): FX.h's _segment_index
  unsigned getCurrSegmentId() const { return _segIndex; }
  unsigned getActiveSegmentsNum() const { return 1; }
  // FX.h: the strip's brightness - the sim draws at full brightness, the
  // picture before the global brightness is put on it (Colortwinkle paces its
  // fades by it) - and the most segments a device takes (Starburst and
  // Exploding Fireworks size their share of the data by it)
  uint8_t  getBrightness() const  { return 255; }
  static constexpr unsigned getMaxSegments() { return MAX_NUM_SEGMENTS; }
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
  #include "fx_modes.h"                     // gen/, on the include path
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
