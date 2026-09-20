// This file is compiled for speed, not size. The firmware builds with -Os,
// and at -Os GCC turned the VM's 67-way switch into a tree of branches
// (seven or eight taken branches per op) and refused to inline the one-line
// helpers - gc_sat, fminf, the register reads - so a MOV cost 40 cycles.
// -O2 gives the helpers their place and, with jump tables turned back on (the
// ESP-IDF toolchain builds with -fno-jump-tables), the switch its table; the pragma
// must sit above the includes, because GCC will not inline a function
// compiled with different optimisation options into one compiled at -O2.
#if defined(__GNUC__) && !defined(__clang__)
#pragma GCC optimize("O2", "jump-tables", "tree-switch-conversion")
#endif
#include "wled.h"
#include "cube_fx_common.h"
#include "cube_fx_bank.h"
#include "cube_fx_studio_helpers.h"

// ===========================================================================
// Studio Script - the scripted runtime
// ===========================================================================
// Runs a program the WLED Effects Studio compiled from a node graph
// (native/script.py), so an effect reaches the cube over the network with no
// firmware build: the studio POSTs /studio.bin to /upload, this effect sees
// the file change and runs it. One effect slot, any graph the studio's
// subset can express (see script.py for what cannot).
//
// The program is straight-line bytecode over a float register file, colour
// registers and a state array kept between frames: a frame stream run once a
// frame after the VM fills the fixed registers (time, sliders, audio...), a
// pixel stream run per pixel with that pixel's coordinates in the fixed
// registers. No jumps: an `if` on a live value was compiled to selects.
// Every op is a switch case below, in the order of script.py's OPS table -
// the two are one table, kept in step by hand.
//
// In the simulator (CFX_SIM) the studio hands the program over in memory
// (simScriptLoad), so a script previews exactly as it will run.
// ===========================================================================

#define SS_FIXED 56          // fixed registers; the compiler allocates from here
#define SS_BAND0 40          // the sixteen bands; 36 was SEGENV.call's register and the bands overwrote it
#define SS_MAX_PROG (24 * 1024)

enum : uint8_t {
  SS_END, SS_CONST, SS_MOV, SS_ADD, SS_SUB, SS_MUL, SS_DIV, SS_MIN, SS_MAX, SS_POW, SS_MOD, SS_ATAN2,
  SS_ABS, SS_FLOOR, SS_FRACT, SS_SIN, SS_COS, SS_SQRT, SS_EXP, SS_LOG, SS_SAT, SS_SIGN, SS_ROUND, SS_NOT,
  SS_TAN, SS_TRUNC, SS_CEIL, SS_LT, SS_LE, SS_GT, SS_GE, SS_EQ, SS_NE, SS_AND, SS_OR, SS_SEL,
  SS_NOISE, SS_HASH, SS_FBM, SS_PAL, SS_HSV, SS_RGB, SS_CR, SS_CG, SS_CB, SS_CMIX, SS_CSCALE, SS_CADD, SS_CMUL,
  SS_CMAX, SS_CMIN, SS_CSEL, SS_SEGCOL, SS_CMOV, SS_CCONST, SS_OUT, SS_STLD, SS_STST, SS_RND, SS_BLEND,
  SS_RINGUV, SS_POSUV, SS_FOLD, SS_KNOT, SS_MANDEL, SS_EASE, SS_LOUDEST
};

enum { SSF_u, SSF_v, SSF_cx, SSF_cy, SSF_r, SSF_ang, SSF_px, SSF_py, SSF_W, SSF_H, SSF_N, SSF_t, SSF_dt,
       SSF_sx, SSF_ix, SSF_c1, SSF_c2, SSF_c3, SSF_o1, SSF_o2, SSF_o3, SSF_vol, SSF_beat, SSF_first,
       SSF_X3, SSF_Y3, SSF_Z3, SSF_nx, SSF_ny, SSF_nz, SSF_B, SSF_cube, SSF_hit, SSF_bass, SSF_mid, SSF_treb, SSF_call,
       SSF_part, SSF_along, SSF_parts };

// Each op's operands, in script.py's OPS letters: f a float register, c a
// colour register, i a 16-bit integer, k a 32-bit float. ssParse walks both
// streams against this table once, when a program arrives, and refuses one
// with a register out of range or an op it does not know - so the run loop
// below indexes the register files straight, with no check per operand.
static const char *const SS_SIG[] = {
  "", "fk", "ff", "fff", "fff", "fff", "fff", "fff", "fff", "fff", "fff", "fff",
  "ff", "ff", "ff", "ff", "ff", "ff", "ff", "ff", "ff", "ff", "ff", "ff",
  "ff", "ff", "ff", "fff", "fff", "fff", "fff", "fff", "fff", "fff", "fff", "ffff",
  "ffff", "ffff", "fffffff", "cff", "cfff", "cfff", "fc", "fc", "fc", "cccf", "ccf", "ccc", "ccc",
  "ccc", "ccc", "cfcc", "ci", "cc", "ci", "c", "fi", "if", "f", "cccfi",
  "ffff", "fffff", "ffffffi", "ffffffffffffff", "ffffff", "fff", "ffii"
};
#define SS_NOPS (sizeof(SS_SIG) / sizeof(SS_SIG[0]))

struct SsProgram {
  uint8_t *bytes = nullptr;
  size_t len = 0;
  uint16_t nf = 0, nc = 0, ns = 0;
  uint32_t frameLen = 0, pixelLen = 0;
  // The streams as the run loop reads them: 16-bit words (an op, then its
  // operands; a float immediate as two), decoded from the file's bytes when
  // it arrives, so every operand is one aligned load.
  uint16_t *words = nullptr;
  const uint16_t *frame = nullptr, *pixel = nullptr;
  uint32_t frameWords = 0, pixelWords = 0;
  uint32_t stamp = 0;                // changes when a new program is loaded
  bool valid = false;
  bool usesPolar = false;            // the pixel stream reads r or ang
  bool usesSpace = false;            // ... or the 3-D position / normal
  bool usesPart = false;             // ... or the shape part
};
static SsProgram gSs;
uint8_t cfx_scriptStride = 1;      // the frame budget's current stride (1 = full resolution); the bank reports it
uint32_t cfx_scriptTook = 0;       // the last frame's pixel loop, microseconds

// One stream checked against SS_SIG and decoded into words at `out`;
// false on a bad op or register. The fixed registers the stream reads are
// noted in `reads` (bits 0..55); the number of words written in `n`.
static bool ssCheck(const uint8_t *p, const uint8_t *end, const SsProgram &P, uint64_t &reads, uint16_t *out, uint32_t &n) {
  n = 0;
  while (p < end) {
    const uint8_t op = *p++;
    out[n++] = op;
    if (op == SS_END) return true;
    if (op >= SS_NOPS) return false;
    for (const char *k = SS_SIG[op]; *k; k++) {
      if (*k == 'k') {
        if (end - p < 4) return false;
        out[n++] = p[0] | (p[1] << 8); out[n++] = p[2] | (p[3] << 8); p += 4; continue;
      }
      if (end - p < 2) return false;
      const uint16_t v = p[0] | (p[1] << 8); p += 2;
      out[n++] = v;
      if (*k == 'f') { if (v >= P.nf) return false; if (v < SS_FIXED) reads |= (uint64_t)1 << v; }
      else if (*k == 'c') { if (v >= P.nc) return false; }
    }
  }
  return false;                          // ran off the end without an END: the run loop relies on one
}

static bool ssParse(SsProgram &P) {
  P.valid = false;
  if (!P.bytes || P.len < 19 || memcmp(P.bytes, "STUV", 4) != 0 || P.bytes[4] != 1) return false;
  const uint8_t *h = P.bytes + 5;
  P.nf = h[0] | (h[1] << 8); P.nc = h[2] | (h[3] << 8); P.ns = h[4] | (h[5] << 8);
  P.frameLen = (uint32_t)h[6] | ((uint32_t)h[7] << 8) | ((uint32_t)h[8] << 16) | ((uint32_t)h[9] << 24);
  P.pixelLen = (uint32_t)h[10] | ((uint32_t)h[11] << 8) | ((uint32_t)h[12] << 16) | ((uint32_t)h[13] << 24);
  if (19 + P.frameLen + P.pixelLen > P.len) return false;
  if (P.nf < SS_FIXED || P.nf > 4096 || P.nc < 1 || P.nc > 2048 || P.ns > 4096) return false;
  const uint8_t *fb = P.bytes + 19, *pb = fb + P.frameLen;
  free(P.words);
  P.words = (uint16_t *)malloc((P.frameLen + P.pixelLen + 2) * sizeof(uint16_t));   // a byte never makes more than a word
  if (!P.words) return false;
  uint64_t reads = 0;
  if (!ssCheck(fb, fb + P.frameLen, P, reads, P.words, P.frameWords)) return false;
  P.frame = P.words;
  reads = 0;
  if (!ssCheck(pb, pb + P.pixelLen, P, reads, P.words + P.frameWords, P.pixelWords)) return false;
  P.pixel = P.words + P.frameWords;
  P.usesPolar = (reads & (((uint64_t)1 << SSF_r) | ((uint64_t)1 << SSF_ang))) != 0;
  P.usesSpace = (reads & (((uint64_t)1 << SSF_X3) | ((uint64_t)1 << SSF_Y3) | ((uint64_t)1 << SSF_Z3)
                        | ((uint64_t)1 << SSF_nx) | ((uint64_t)1 << SSF_ny) | ((uint64_t)1 << SSF_nz))) != 0;
  P.usesPart = (reads & (((uint64_t)1 << SSF_part) | ((uint64_t)1 << SSF_along))) != 0;
  P.valid = true;
  P.stamp++;
  return true;
}

// Sine by table: 256 entries over a turn and a straight line between them
// (a hundredth of a per cent out at worst), because on an ESP32 sinf is a
// few hundred cycles and even WLED's sin_t, a float wrapper on sin16_t, was
// 300 ns an op. Made when the effect first runs.
static float ssSinTab[258];
static bool ssSinReady = false;
static void ssSinInit() {
  if (ssSinReady) return;
  for (int i = 0; i < 258; i++) ssSinTab[i] = sinf((float)i * (6.28318530718f / 256.0f));
  ssSinReady = true;
}
static inline float ssFloor(float x) { const float f = (float)(int32_t)x; return f > x ? f - 1.0f : f; }
static inline float ssCeil(float x) { const float f = (float)(int32_t)x; return f < x ? f + 1.0f : f; }
static inline float ssSinTurns(float t) {         // t in 256ths of a turn
  const float f = ssFloor(t);
  const int i = (int32_t)f & 255;
  return ssSinTab[i] + (ssSinTab[i + 1] - ssSinTab[i]) * (t - f);
}
static inline float ssSin(float rad) { return ssSinTurns(rad * (256.0f / 6.28318530718f)); }
static inline float ssCos(float rad) { return ssSinTurns(rad * (256.0f / 6.28318530718f) + 64.0f); }

// The palette, 256 entries, made on the first PAL of a frame and kept for
// the rest of it: one palette lookup per index per frame, not per pixel.
static uint32_t ssPalTab[256];
static bool ssPalReady = false;
static inline uint32_t ssPal(uint8_t i) {
  if (!ssPalReady) {
    for (int k = 0; k < 256; k++) ssPalTab[k] = SEGMENT.color_from_palette((uint8_t)k, false, true, 0);
    ssPalReady = true;
  }
  return ssPalTab[i];
}

#ifdef CFX_SIM
// The simulator loads programs from memory.
extern "C" void simScriptLoad(const uint8_t *bytes, int n) {
  free(gSs.bytes); gSs.bytes = nullptr; gSs.len = 0;
  if (bytes && n > 0 && n <= SS_MAX_PROG) {
    gSs.bytes = (uint8_t *)malloc(n); memcpy(gSs.bytes, bytes, n); gSs.len = n;
  }
  ssParse(gSs);
}
extern "C" int simScriptOk() { return gSs.valid ? 1 : 0; }
static void ssPoll() {}
#else
// The device reads /studio.bin, and again whenever it changes (a few KB,
// checked every two seconds - a read, not a rebuild).
static void ssPoll() {
  static uint32_t last = 0;
  if (millis() - last < 2000) return;
  last = millis();
  File f = WLED_FS.open("/studio.bin", "r");
  if (!f) return;
  size_t n = f.size();
  if (n < 19 || n > SS_MAX_PROG) { f.close(); return; }
  uint8_t *buf = (uint8_t *)malloc(n);
  if (!buf) { f.close(); return; }
  size_t got = f.read(buf, n);
  f.close();
  if (got == n && !(gSs.bytes && gSs.len == n && memcmp(gSs.bytes, buf, n) == 0)) {
    free(gSs.bytes); gSs.bytes = buf; gSs.len = n;
    ssParse(gSs);
  } else free(buf);
}
#endif

static inline uint16_t ssU16(const uint16_t *&p) { return *p++; }
static inline float ssF32(const uint16_t *&p) { uint32_t u = (uint32_t)p[0] | ((uint32_t)p[1] << 16); p += 2; float v; memcpy(&v, &u, 4); return v; }

#ifndef IRAM_ATTR
#define IRAM_ATTR
#endif

// One stream. F, C, S are the register files; returns the OUT colour (or 0).
// Register operands were range-checked by ssParse; state slots are checked
// here, as the state block is sized separately. In IRAM: it runs a couple
// of thousand times a frame beside WiFi and the web server, which would
// otherwise keep pushing it out of the flash cache.
static uint32_t IRAM_ATTR ssRun(const uint16_t *p, const uint16_t *end, float *F, uint32_t *C, float *S,
                                uint16_t ns, const uint8_t *fft) {
  uint32_t out = 0;
  uint16_t a, b, c, d;
  #define RF(i) F[(i)]
  #define RC(i) C[(i)]
  // Threaded dispatch where the compiler allows it (GCC and clang): each op
  // ends by jumping straight to the next one's code through a table of
  // label addresses - no loop test, no bounds check, no jump back to a
  // switch - which is a fifth of the cost of a simple op. The op codes were
  // checked by ssParse and every stream ends in END, so nothing is tested
  // here. The switch is the same body for any other compiler.
#if defined(__GNUC__) || defined(__clang__)
  (void)end;
  static const void *const ssJump[] = { &&L_END, &&L_CONST, &&L_MOV, &&L_ADD, &&L_SUB, &&L_MUL, &&L_DIV, &&L_MIN, &&L_MAX, &&L_POW, &&L_MOD, &&L_ATAN2, &&L_ABS, &&L_FLOOR, &&L_FRACT, &&L_SIN, &&L_COS, &&L_SQRT, &&L_EXP, &&L_LOG, &&L_SAT, &&L_SIGN, &&L_ROUND, &&L_NOT, &&L_TAN, &&L_TRUNC, &&L_CEIL, &&L_LT, &&L_LE, &&L_GT, &&L_GE, &&L_EQ, &&L_NE, &&L_AND, &&L_OR, &&L_SEL, &&L_NOISE, &&L_HASH, &&L_FBM, &&L_PAL, &&L_HSV, &&L_RGB, &&L_CR, &&L_CG, &&L_CB, &&L_CMIX, &&L_CSCALE, &&L_CADD, &&L_CMUL, &&L_CMAX, &&L_CMIN, &&L_CSEL, &&L_SEGCOL, &&L_CMOV, &&L_CCONST, &&L_OUT, &&L_STLD, &&L_STST, &&L_RND, &&L_BLEND, &&L_RINGUV, &&L_POSUV, &&L_FOLD, &&L_KNOT, &&L_MANDEL, &&L_EASE, &&L_LOUDEST };
  #define OP(N) L_##N:
  #define END_OP goto *ssJump[*p++]
  END_OP;
#else
  #define OP(N) case SS_##N:
  #define END_OP break
  while (p < end) {
    switch (*p++) {
#endif
      OP(END) return out;                 // the stream's last op (ssParse insists on it)
      OP(CONST) a = ssU16(p); RF(a) = ssF32(p); END_OP;
      OP(MOV) a = ssU16(p); b = ssU16(p); RF(a) = RF(b); END_OP;
      OP(ADD) a = ssU16(p); b = ssU16(p); c = ssU16(p); RF(a) = RF(b) + RF(c); END_OP;
      OP(SUB) a = ssU16(p); b = ssU16(p); c = ssU16(p); RF(a) = RF(b) - RF(c); END_OP;
      OP(MUL) a = ssU16(p); b = ssU16(p); c = ssU16(p); RF(a) = RF(b) * RF(c); END_OP;
      OP(DIV) a = ssU16(p); b = ssU16(p); c = ssU16(p); RF(a) = RF(c) != 0.0f ? RF(b) / RF(c) : 0.0f; END_OP;
      OP(MIN) a = ssU16(p); b = ssU16(p); c = ssU16(p); RF(a) = RF(b) < RF(c) ? RF(b) : RF(c); END_OP;
      OP(MAX) a = ssU16(p); b = ssU16(p); c = ssU16(p); RF(a) = RF(b) > RF(c) ? RF(b) : RF(c); END_OP;
      OP(POW) a = ssU16(p); b = ssU16(p); c = ssU16(p); RF(a) = powf(RF(b) < 0.0f ? 0.0f : RF(b), RF(c)); END_OP;
      OP(MOD) { a = ssU16(p); b = ssU16(p); c = ssU16(p);                          // fmodf's sign, without the call
        RF(a) = RF(c) != 0.0f ? RF(b) - RF(c) * (float)(int32_t)(RF(b) / RF(c)) : 0.0f; END_OP; }
      OP(ATAN2) a = ssU16(p); b = ssU16(p); c = ssU16(p); RF(a) = cfx_atan2f(RF(b), RF(c)); END_OP;
      OP(ABS) a = ssU16(p); b = ssU16(p); RF(a) = fabsf(RF(b)); END_OP;
      OP(FLOOR) a = ssU16(p); b = ssU16(p); RF(a) = ssFloor(RF(b)); END_OP;
      OP(FRACT) a = ssU16(p); b = ssU16(p); RF(a) = RF(b) - ssFloor(RF(b)); END_OP;
      OP(SIN) a = ssU16(p); b = ssU16(p); RF(a) = ssSin(RF(b)); END_OP;
      OP(COS) a = ssU16(p); b = ssU16(p); RF(a) = ssCos(RF(b)); END_OP;
      OP(SQRT) a = ssU16(p); b = ssU16(p); RF(a) = sqrtf(RF(b) < 0.0f ? 0.0f : RF(b)); END_OP;
      OP(EXP) a = ssU16(p); b = ssU16(p); RF(a) = expf(RF(b)); END_OP;
      OP(LOG) a = ssU16(p); b = ssU16(p); RF(a) = RF(b) > 0.0f ? logf(RF(b)) : 0.0f; END_OP;
      OP(SAT) a = ssU16(p); b = ssU16(p); RF(a) = gc_sat(RF(b)); END_OP;
      OP(SIGN) a = ssU16(p); b = ssU16(p); RF(a) = RF(b) > 0.0f ? 1.0f : (RF(b) < 0.0f ? -1.0f : 0.0f); END_OP;
      OP(ROUND) a = ssU16(p); b = ssU16(p); RF(a) = ssFloor(RF(b) + 0.5f); END_OP;
      OP(NOT) a = ssU16(p); b = ssU16(p); RF(a) = RF(b) != 0.0f ? 0.0f : 1.0f; END_OP;
      OP(TAN) a = ssU16(p); b = ssU16(p); RF(a) = tanf(RF(b)); END_OP;
      OP(TRUNC) a = ssU16(p); b = ssU16(p); RF(a) = (float)(int32_t)RF(b); END_OP;
      OP(CEIL) a = ssU16(p); b = ssU16(p); RF(a) = ssCeil(RF(b)); END_OP;
      OP(LT) a = ssU16(p); b = ssU16(p); c = ssU16(p); RF(a) = RF(b) < RF(c) ? 1.0f : 0.0f; END_OP;
      OP(LE) a = ssU16(p); b = ssU16(p); c = ssU16(p); RF(a) = RF(b) <= RF(c) ? 1.0f : 0.0f; END_OP;
      OP(GT) a = ssU16(p); b = ssU16(p); c = ssU16(p); RF(a) = RF(b) > RF(c) ? 1.0f : 0.0f; END_OP;
      OP(GE) a = ssU16(p); b = ssU16(p); c = ssU16(p); RF(a) = RF(b) >= RF(c) ? 1.0f : 0.0f; END_OP;
      OP(EQ) a = ssU16(p); b = ssU16(p); c = ssU16(p); RF(a) = RF(b) == RF(c) ? 1.0f : 0.0f; END_OP;
      OP(NE) a = ssU16(p); b = ssU16(p); c = ssU16(p); RF(a) = RF(b) != RF(c) ? 1.0f : 0.0f; END_OP;
      OP(AND) a = ssU16(p); b = ssU16(p); c = ssU16(p); RF(a) = (RF(b) != 0.0f && RF(c) != 0.0f) ? 1.0f : 0.0f; END_OP;
      OP(OR) a = ssU16(p); b = ssU16(p); c = ssU16(p); RF(a) = (RF(b) != 0.0f || RF(c) != 0.0f) ? 1.0f : 0.0f; END_OP;
      OP(SEL) a = ssU16(p); b = ssU16(p); c = ssU16(p); d = ssU16(p); RF(a) = RF(b) != 0.0f ? RF(c) : RF(d); END_OP;
      OP(NOISE) { a = ssU16(p); b = ssU16(p); c = ssU16(p); d = ssU16(p);
        RF(a) = perlin8((uint16_t)(RF(b) * 256.0f), (uint16_t)(RF(c) * 256.0f), (uint16_t)(RF(d) * 256.0f)) * (1.0f / 255.0f); END_OP; }
      OP(HASH) a = ssU16(p); b = ssU16(p); c = ssU16(p); d = ssU16(p); RF(a) = gc_hash(RF(b), RF(c), RF(d)); END_OP;
      OP(FBM) { a = ssU16(p); uint16_t x = ssU16(p), y = ssU16(p), z = ssU16(p), s = ssU16(p), o = ssU16(p), rg = ssU16(p);
        RF(a) = gc_fbm(RF(x), RF(y), RF(z), RF(s), (int)RF(o), RF(rg)); END_OP; }
      OP(PAL) { a = ssU16(p); b = ssU16(p); c = ssU16(p);
        RC(a) = mq_scale(ssPal((uint8_t)(int)(gc_sat(RF(b)) * 255.0f)), (uint8_t)(gc_sat(RF(c)) * 255.0f)); END_OP; }
      OP(HSV) a = ssU16(p); b = ssU16(p); c = ssU16(p); d = ssU16(p); RC(a) = gc_hsv(RF(b), RF(c), RF(d)); END_OP;
      OP(RGB) { a = ssU16(p); b = ssU16(p); c = ssU16(p); d = ssU16(p);
        RC(a) = RGBW32((uint8_t)(gc_sat(RF(b)) * 255.0f), (uint8_t)(gc_sat(RF(c)) * 255.0f), (uint8_t)(gc_sat(RF(d)) * 255.0f), 0); END_OP; }
      OP(CR) a = ssU16(p); b = ssU16(p); RF(a) = (float)((RC(b) >> 16) & 255) * (1.0f / 255.0f); END_OP;
      OP(CG) a = ssU16(p); b = ssU16(p); RF(a) = (float)((RC(b) >> 8) & 255) * (1.0f / 255.0f); END_OP;
      OP(CB) a = ssU16(p); b = ssU16(p); RF(a) = (float)(RC(b) & 255) * (1.0f / 255.0f); END_OP;
      OP(CMIX) { a = ssU16(p); b = ssU16(p); c = ssU16(p); d = ssU16(p);
        RC(a) = color_blend(RC(b), RC(c), (uint8_t)(gc_sat(RF(d)) * 255.0f)); END_OP; }
      OP(CSCALE) a = ssU16(p); b = ssU16(p); c = ssU16(p); RC(a) = mq_scale(RC(b), (uint8_t)(gc_sat(RF(c)) * 255.0f)); END_OP;
      OP(CADD) a = ssU16(p); b = ssU16(p); c = ssU16(p); RC(a) = color_add(RC(b), RC(c), true); END_OP;
      OP(CMUL) a = ssU16(p); b = ssU16(p); c = ssU16(p); RC(a) = gc_blend_multiply(RC(b), RC(c), 1.0f); END_OP;
      OP(CMAX) a = ssU16(p); b = ssU16(p); c = ssU16(p); RC(a) = gc_blend_max(RC(b), RC(c), 1.0f); END_OP;
      OP(CMIN) a = ssU16(p); b = ssU16(p); c = ssU16(p); RC(a) = gc_blend_min(RC(b), RC(c), 1.0f); END_OP;
      OP(CSEL) a = ssU16(p); b = ssU16(p); c = ssU16(p); d = ssU16(p); RC(a) = RF(b) != 0.0f ? RC(c) : RC(d); END_OP;
      OP(SEGCOL) a = ssU16(p); b = ssU16(p); RC(a) = SEGCOLOR(b < 3 ? b : 0); END_OP;
      OP(CMOV) a = ssU16(p); b = ssU16(p); RC(a) = RC(b); END_OP;
      OP(CCONST) a = ssU16(p); b = ssU16(p); RC(a) = b; END_OP;
      OP(OUT) a = ssU16(p); out = RC(a); END_OP;
      OP(STLD) a = ssU16(p); b = ssU16(p); RF(a) = b < ns ? S[b] : 0.0f; END_OP;
      OP(STST) a = ssU16(p); b = ssU16(p); if (a < ns) S[a] = RF(b); END_OP;
      OP(RND) a = ssU16(p); RF(a) = gc_rnd(); END_OP;
      OP(BLEND) { a = ssU16(p); b = ssU16(p); c = ssU16(p); d = ssU16(p); uint16_t m = ssU16(p);
        const float amt = gc_sat(RF(d));
        switch (m) {
          case 0: RC(a) = gc_blend_over(RC(b), RC(c), amt); break;
          case 1: RC(a) = gc_blend_add(RC(b), RC(c), amt); break;
          case 2: RC(a) = gc_blend_multiply(RC(b), RC(c), amt); break;
          case 3: RC(a) = gc_blend_screen(RC(b), RC(c), amt); break;
          case 4: RC(a) = gc_blend_max(RC(b), RC(c), amt); break;
          case 5: RC(a) = gc_blend_min(RC(b), RC(c), amt); break;
          default: RC(a) = gc_blend_mode(m, RC(b), RC(c), amt); break;
        }
        END_OP; }
      OP(RINGUV) { a = ssU16(p); b = ssU16(p); c = ssU16(p); d = ssU16(p);
        float u_ = 0, v_ = 0; const int W = (int)F[SSF_W], H = (int)F[SSF_H], B = (int)F[SSF_B];
        gc_ring_uv(RF(c), RF(d), W, H, B, F[SSF_cube] != 0.0f, u_, v_); RF(a) = u_; RF(b) = v_; END_OP; }
      OP(POSUV) { a = ssU16(p); b = ssU16(p); c = ssU16(p); d = ssU16(p); uint16_t e = ssU16(p);
        float u_ = 0, v_ = 0; const int W = (int)F[SSF_W], H = (int)F[SSF_H], B = (int)F[SSF_B];
        gc_pos_uv(RF(c), RF(d), RF(e), W, H, B, F[SSF_cube] != 0.0f, u_, v_); RF(a) = u_; RF(b) = v_; END_OP; }
      OP(FOLD) { a = ssU16(p); b = ssU16(p); c = ssU16(p); uint16_t x = ssU16(p), y = ssU16(p), z = ssU16(p), sym = ssU16(p);
        float fx = RF(x), fy = RF(y), fz = RF(z); gc_fold((int)sym, fx, fy, fz); RF(a) = fx; RF(b) = fy; RF(c) = fz; END_OP; }
      OP(KNOT) { uint16_t o[6]; for (int i = 0; i < 6; i++) o[i] = ssU16(p);
        uint16_t in[8]; for (int i = 0; i < 8; i++) in[i] = ssU16(p);
        float al = 0, ed = 0, Nx = 0, Ny = 0, Nz = 0;
        const bool hit = gc_knot(RF(in[0]), RF(in[1]), RF(in[2]), (int)RF(in[3]), (int)RF(in[4]), RF(in[5]), RF(in[6]), RF(in[7]), al, ed, Nx, Ny, Nz);
        RF(o[0]) = hit ? 1.0f : 0.0f; RF(o[1]) = al; RF(o[2]) = ed; RF(o[3]) = Nx; RF(o[4]) = Ny; RF(o[5]) = Nz; END_OP; }
      OP(MANDEL) { a = ssU16(p); uint16_t x = ssU16(p), y = ssU16(p), zx = ssU16(p), zy = ssU16(p), it = ssU16(p);
        RF(a) = gc_mandel(RF(x), RF(y), RF(zx), RF(zy), (int)RF(it)); END_OP; }
      OP(EASE) a = ssU16(p); b = ssU16(p); c = ssU16(p); RF(a) = gc_ease(RF(b), (int)RF(c)); END_OP;
      OP(LOUDEST) { a = ssU16(p); b = ssU16(p); uint16_t from = ssU16(p), to = ssU16(p);
        int best = from < 16 ? from : 15; for (int i = from; i <= to && i < 16; i++) if (fft[i] > fft[best]) best = i;
        RF(a) = (float)best * (1.0f / 15.0f); RF(b) = (float)fft[best] * (1.0f / 255.0f); END_OP; }
#if !(defined(__GNUC__) || defined(__clang__))
      default: return out;                // an op this build does not know: stop the stream
    }
  }
#endif
  #undef OP
  #undef END_OP
  #undef RF
  #undef RC
  return out;
}

static void mode_studio_script() {
  ssPoll();
  const bool is2d = SEGMENT.is2D();
  const int W = is2d ? SEG_W : SEGLEN, H = is2d ? SEG_H : 1;
  const int N = W * H;
  const bool cube = is2d && cfx_isCube(W, H);
  const int  B    = cube ? (W / 3) : 1;
  static uint8_t clk_[2] = {0, 0};
  const uint16_t dt = fx_dt8(clk_);
  const float t = (float)strip.now * 0.001f;
  (void)N;
  if (!gSs.valid) {
    // no program: a slow breathing dot, so a segment on this effect is not just dark
    const uint8_t k = (uint8_t)(96 + 64 * sinf(t * 2.0f));
    SEGMENT.fill(0);
    if (is2d) SEGMENT.setPixelColorXY(W / 2, H / 2, RGBW32(0, k, k, 0)); else SEGMENT.setPixelColor(0, RGBW32(0, k, k, 0));
    FX_DONE;
  }
  const SsProgram &P = gSs;
  ssSinInit();
  const size_t need = ((size_t)P.nf + P.ns) * sizeof(float) + (size_t)P.nc * sizeof(uint32_t) + 8;
  if (!SEGENV.allocateData(need)) { SEGMENT.fill(0); FX_DONE; }
  uint32_t *stamp = (uint32_t *)SEGENV.data;
  float *F = (float *)(SEGENV.data + 8);
  float *S = F + P.nf;
  uint32_t *C = (uint32_t *)(S + P.ns);
  const bool first = (SEGENV.call == 0) || (*stamp != P.stamp);
  if (first) { memset(SEGENV.data, 0, need); *stamp = P.stamp; }

  um_data_t *um = cfx_getAudioData();
  const uint8_t *fft = (const uint8_t *)um->u_data[2];
  int bass_, mid_, treb_; cfx_bands(fft, bass_, mid_, treb_);
  const uint8_t kick = fx_lowBeat(um);

  F[SSF_W] = (float)W; F[SSF_H] = (float)H; F[SSF_N] = (float)N; F[SSF_t] = t; F[SSF_dt] = (float)dt;
  F[SSF_sx] = SEGMENT.speed * (1.0f / 255.0f); F[SSF_ix] = SEGMENT.intensity * (1.0f / 255.0f);
  F[SSF_c1] = SEGMENT.custom1 * (1.0f / 255.0f); F[SSF_c2] = SEGMENT.custom2 * (1.0f / 255.0f); F[SSF_c3] = SEGMENT.custom3 * (1.0f / 31.0f);
  F[SSF_o1] = SEGMENT.check1 ? 1.0f : 0.0f; F[SSF_o2] = SEGMENT.check2 ? 1.0f : 0.0f; F[SSF_o3] = SEGMENT.check3 ? 1.0f : 0.0f;
  F[SSF_vol] = *(float *)um->u_data[0] * (1.0f / 255.0f); F[SSF_beat] = kick != 0 ? 1.0f : 0.0f; F[SSF_hit] = kick * (1.0f / 255.0f);
  F[SSF_bass] = bass_ * (1.0f / 255.0f); F[SSF_mid] = mid_ * (1.0f / 255.0f); F[SSF_treb] = treb_ * (1.0f / 255.0f);
  F[SSF_first] = first ? 1.0f : 0.0f; F[SSF_B] = (float)B; F[SSF_cube] = cube ? 1.0f : 0.0f; F[SSF_call] = (float)SEGENV.call;
  for (int i = 0; i < 16; i++) F[SS_BAND0 + i] = fft[i] * (1.0f / 255.0f);
  F[SSF_parts] = (float)(cfx_geomFor(W, H) && cfx_geomPart ? cfx_geomParts : 1);

  ssPalReady = false;
  ssRun(P.frame, P.frame + P.frameWords, F, C, S, P.ns, fft);

  // The budget: a program too heavy for the chip runs at half, then a
  // quarter, of the horizontal resolution (each pixel's colour repeated
  // across its neighbours) rather than dragging the whole device down.
  // Coarser after three frames in a row over 40 ms - one slow frame is
  // WiFi or a program just loaded, not the program - and finer again when
  // the next stride's frame, about twice this one, would come in under 30
  // ms; so a program that fits full resolution never sits at half.
  static uint8_t slow = 0;
  uint8_t &stride = cfx_scriptStride;
  if (first) { stride = 1; slow = 0; }
  const uint32_t t0 = micros();
  const int cols = W, rows = H; (void)rows;
  CFX_NET_PREP();
  for (int py = 0; py < H; py++) {
    CFX_NET_ROW(py);
    uint32_t last = 0;
    for (int px = 0; px < W; px++) {
      CFX_NET_SKIP(px);
      if (stride > 1 && (px % stride) != 0) {
        if (is2d) SEGMENT.setPixelColorXY(px, py, last); else SEGMENT.setPixelColor(px, last);
        continue;
      }
      const float u = (W > 1) ? (float)px / (float)(W - 1) : 0.5f;
      const float v = (H > 1) ? (float)py / (float)(H - 1) : 0.5f;
      const float cx = u * 2.0f - 1.0f, cy = 1.0f - v * 2.0f;
      F[SSF_u] = u; F[SSF_v] = v; F[SSF_cx] = cx; F[SSF_cy] = cy;
      F[SSF_px] = (float)px; F[SSF_py] = (float)py;
      // the polar and 3-D registers cost a root and an arc tangent a pixel: only for a program that reads them
      if (P.usesPolar) { F[SSF_r] = sqrtf(cx * cx + cy * cy); F[SSF_ang] = cfx_atan2f(cy, cx); }
      if (P.usesPart) { int pt, np_; float al; cfx_geomPartOf(px, py, W, pt, al, np_); F[SSF_part] = (float)pt; F[SSF_along] = al; }
      if (P.usesSpace) {
        float nx, ny, nz, X3, Y3, Z3;
        if (cfx_geomFor(W, H)) {                      // a shape table: the real positions and normals
          cfx_pos(px, py, W, H, B, false, X3, Y3, Z3);
          cfx_geomNormal(px, py, W, X3, Y3, Z3, nx, ny, nz);
        } else if (cube) {
          cfx_pos(px, py, W, H, B, true, X3, Y3, Z3);
          const float L = sqrtf(X3 * X3 + Y3 * Y3 + Z3 * Z3); const float iL = L > 1e-6f ? 1.0f / L : 1.0f;
          nx = X3 * iL; ny = Y3 * iL; nz = Z3 * iL;
        } else {
          X3 = cx; Y3 = cy; Z3 = 0.0f;
          const float Z = 1.0f - (cx * cx + cy * cy) * 0.5f;
          const float L = sqrtf(cx * cx + cy * cy + Z * Z); const float iL = L > 1e-6f ? 1.0f / L : 1.0f;
          nx = cx * iL; ny = cy * iL; nz = Z * iL;
        }
        F[SSF_X3] = X3; F[SSF_Y3] = Y3; F[SSF_Z3] = Z3; F[SSF_nx] = nx; F[SSF_ny] = ny; F[SSF_nz] = nz;
      }
      const uint32_t c = ssRun(P.pixel, P.pixel + P.pixelWords, F, C, S, P.ns, fft);
      last = c;
      if (is2d) SEGMENT.setPixelColorXY(px, py, c); else SEGMENT.setPixelColor(px, c);
    }
  }
  const uint32_t took = micros() - t0;
  cfx_scriptTook = took;
  if (took > 40000u) { if (++slow >= 3 && stride < 4) { stride *= 2; slow = 0; } }
  else { slow = 0; if (stride > 1 && took * 2u < 30000u) stride /= 2; }
  FX_DONE;
}

static const char _data_FX_MODE_STUDIO_SCRIPT[] PROGMEM = "Studio Script@Speed,Intensity,Custom 1,Custom 2,Custom 3,Check 1,Check 2,Check 3;;!;12;sx=128,ix=128";
static CfxBankReg studio_script_reg(&mode_studio_script, _data_FX_MODE_STUDIO_SCRIPT);
