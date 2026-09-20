#pragma once

// ===========================================================================
// cube_fx_common.h - shared helpers for the "Cube" family of LED effects
// ===========================================================================
// Included by every cube_fx_*.cpp file in this folder. Anything used by two
// or more effects lives here so it is defined once; anything used by exactly
// one effect stays local to that effect's own .cpp file instead. If you are
// adding a brand-new effect, you almost never need to edit this file - just
// #include it and use what you need from it.
//
// See README.md in this folder for the full picture (net layout, how to add
// a new effect, why the split works this way).
// ===========================================================================

#include "wled.h"
#include <math.h>

// ---------------------------------------------------------------------------
// Effect signature compatibility
// ---------------------------------------------------------------------------
// WLED 16.0 and up, 17.0.0-dev included:  void     mode_x() { ... }
// WLED 0.15 and older:                    uint16_t mode_x() { ... return FRAMETIME; }
//
// Verified against v16.0.1: WS2812FX::mode_ptr is void (*)(). The uint16_t
// form only applies to 0.15 and older, whatever the older docs say. Set
//   -D FX_LEGACY_RETURN=1
// in your platformio_override.ini build_flags if you ever build that far back.
#ifndef FX_LEGACY_RETURN
  #define FX_LEGACY_RETURN 0
#endif

#if FX_LEGACY_RETURN
  #define FX_RET  uint16_t
  #define FX_DONE return FRAMETIME
#else
  #define FX_RET  void
  #define FX_DONE return
#endif

/*
 * ===========================================================================
 * Cube-native audio-reactive effects for WLED (0.15 / 16.x / 17-dev)
 * ===========================================================================
 *
 *   00 Cube Axes        calibration - XYZ as RGB, verify the net mapping
 *   01 Cube Ripples     beat-spawned spherical wavefronts crossing every edge
 *   02 Spectral Globe   latitude = frequency, azimuth folded into petals
 *   03 Cube Slice       tumbling plane of spectrum sweeping through the solid
 *   04 Cube Edges       edges lined, beat pulses edge<->centre, wave along edges
 *   05 Cube Frame       free-floating wireframe you can spin out of alignment
 *   06 Cube Chladni     nodal surface of a 3D box mode, cut by the cube's faces
 *   07 Cube Bloom       lobed shells, each shape fixed from the FFT at the beat
 *   08 Rubiks Cube      real 3x3 puzzle: scramble, then unwind on the beat
 *   09 Cube Cell        Waving Cell's nested sines, evaluated on the 3D surface
 *   10 Cube Wire        edges only, beat pulses running ALONG them with trails
 *                       (+ Gyro Wire)
 *   11 Question Block   ? block -> item roulette; shake hard and it shatters
 *   12 Tron             light cycles on the five faces
 *   13 Liquid           a level that stays level (+ Gyro Liquid)
 *   14 Split GEQ        equator-split bars, or a circular GEQ on every face
 *   15 Quadrant Labyrinth
 *   16 Cube Speaker     the cube as a driver cone
 *   17 DNA Helix
 *   18 Audio Atlas      gyro-locked band map (Gyro)
 *   19 Plasma           summed plane waves, one per band
 *   20 Matrix Rain      glyph columns pouring off the lid and down the walls
 *   21 Breakout         two-player, played from the encoders
 *   22 Gyro Sand        a glass box of sand, poured by real gravity
 *   23 Gyro Rain        rain that falls down whichever way the cube is held
 *   24 Whirlpool        an eye on the lid, arms spiralling out onto the walls
 *   25 Cube Fire        smoulders at the base, climbs the walls, pools on the lid
 *   26 Soap             curl-noise flow folding colour over the whole solid
 *   27 Black Hole       a round void on the lid, disc winding in, arc on the rim
 *   28 Spectral Wormhole  GEQ round the bottom edge, water up the walls into a
 *                       swirling film on the lid (Black Hole's flow, reversed)
 *
 * The seven flat 2-D analysers live together in cube_fx.cpp. Full catalogue,
 * accessory requirements and setup are in README.md.
 *
 * The idea: every pixel gets a 3D position on the cube's surface. Effects are
 * then functions of (X,Y,Z), so they are continuous across folds for free -
 * no seam handling anywhere in the effect code.
 *
 * Net assumed (3x3 blocks of B x B, corners are gaps):
 *
 *          +--------+
 *          | NORTH  |
 *     +----+--------+----+
 *     |WEST|  TOP   |EAST|
 *     +----+--------+----+
 *          | SOUTH  |
 *          +--------+
 *
 * Cube axes: +X east, +Y north, +Z up. Top face at Z = +1.
 * Each arm folds upward, so the edge touching TOP is that wall's top edge.
 *
 * On any other matrix the LUT falls back to a flat plane at Z = 0 and every
 * effect degrades sensibly (ripples become circles, the globe becomes a polar
 * mandala, the slice becomes sweeping bands).
 *
 * Cube detection is automatic (square side, a multiple of 3, at least 12); the
 * "Flat mode" checkbox forces the plane on a square panel that would otherwise
 * be misread as a cube. See README.md for the size table and the caveat.
 * ===========================================================================
 */

// ---------------------------------------------------------------------------
// shared helpers (static: private to this file, may duplicate cube_fx.cpp)
// ---------------------------------------------------------------------------
static um_data_t *cfx_getAudioData() {
  um_data_t *um_data;
  if (!UsermodManager::getUMData(&um_data, USERMOD_ID_AUDIOREACTIVE)) {
    um_data = simulateSound(SEGMENT.soundSim);
  }
  return um_data;
}

static inline void cfx_bands(const uint8_t *fft, int &bass, int &mid, int &treb) {
  bass = (fft[0] + fft[1] + fft[2]) / 3;
  mid  = (fft[5] + fft[6] + fft[7] + fft[8]) / 4;
  treb = (fft[12] + fft[13] + fft[14] + fft[15]) / 4;
}

static inline uint8_t cfx_drive(float vol, float gain, int floorV) {
  int32_t d = (int32_t)(vol * gain) + floorV;
  if (d < 0) d = 0;
  return (uint8_t)((d > 255) ? 255 : d);
}

static void cfx_smoothSpec(uint8_t *spec, const uint8_t *fft, uint8_t sm) {
  if (sm < 1) sm = 1;
  for (int i = 0; i < 16; i++) {
    int cur = (int)spec[i];
    cur += ((int)fft[i] - cur) / (int)sm;
    if ((int)fft[i] > cur) cur = fft[i];      // fast attack, slow release
    spec[i] = (uint8_t)cur;
  }
}

// Fast atan2, max error ~1e-5 rad, no library call. Effects that need an ANGLE
// per pixel - a phase, a sector index, a winding - were each carrying their own
// copy of this; it lives here now. Accurate enough that the result is
// indistinguishable at 8-bit palette resolution, and it never divides by zero.
static inline float cfx_atan2f(float y, float x) {
  const float ax = fabsf(x), ay = fabsf(y);
  const float mx = (ax > ay) ? ax : ay;
  if (mx < 1e-20f) return 0.0f;
  const float a = ((ax > ay) ? ay : ax) / mx;
  const float s = a * a;
  float r = ((-0.0464964749f * s + 0.15931422f) * s - 0.327622764f) * s * a + a;
  if (ay > ax) r = 1.57079637f - r;
  if (x < 0.0f) r = 3.14159274f - r;
  return (y < 0.0f) ? -r : r;
}

// 16-bit trig on a float angle in radians. 0.006 degrees of resolution against
// 1.4 for the 8-bit tables, which matters wherever the angle sets where
// something physically IS rather than what colour it is - a tube's silhouette,
// a pole's position - because that error lands on the geometry and reads as a
// wobble. Torus Knot and Voxel Vortex each carried a copy; it lives here now.
static inline float cfx_sinf16(float rad) {
  return (float)sin16_t((uint16_t)(int32_t)(rad * (65536.0f / 6.28318531f))) * (1.0f / 32767.0f);
}
static inline float cfx_cosf16(float rad) {
  return (float)sin16_t((uint16_t)(int32_t)(rad * (65536.0f / 6.28318531f)) + 16384u) * (1.0f / 32767.0f);
}

// ---------------------------------------------------------------------------
// Torus knots - the (p,q) table
// ---------------------------------------------------------------------------
// p windings round the main axis to q round the tube. gcd(p,q) = 1 or the
// curve closes early and stops being a knot. p is the per-pixel loop count in
// the meridian construction both knot effects use, so it is capped at 7. Index
// 0 is the trefoil. A 5-bit custom3 indexes it directly.
#define CFX_NKNOT 32
static const uint8_t CFX_KNOT_PQ[CFX_NKNOT][2] PROGMEM = {
  { 2,  3 }, { 3,  2 }, { 2,  5 }, { 5,  2 }, { 3,  4 }, { 4,  3 }, { 2,  7 },
  { 7,  2 }, { 3,  5 }, { 5,  3 }, { 2,  9 }, { 5,  4 }, { 3,  7 }, { 7,  3 },
  { 2, 11 }, { 3,  8 }, { 4,  7 }, { 3, 10 }, { 5,  6 }, { 6,  5 }, { 3, 11 },
  { 5,  7 }, { 7,  5 }, { 5,  8 }, { 6,  7 }, { 7,  6 }, { 4, 11 }, { 5,  9 },
  { 5, 11 }, { 7,  9 }, { 6, 11 }, { 7, 11 },
};
static inline void cfx_knotPQ(uint8_t pick, int &P, int &Q) {
  if (pick >= CFX_NKNOT) pick = CFX_NKNOT - 1;
  P = (int)pgm_read_byte(&CFX_KNOT_PQ[pick][0]);
  Q = (int)pgm_read_byte(&CFX_KNOT_PQ[pick][1]);
}

// ---------------------------------------------------------------------------
// Quaternion tumble - a slow, gimbal-free wander through orientations
// ---------------------------------------------------------------------------
// For effects whose whole identity is an AXIS - a ring, a vortex, a pair of
// poles - and that want that axis to roam the solid. Euler angles are the wrong
// tool for exactly those: they spend their life near the configuration where
// two of the three angles control the same rotation, and interpolating them
// independently sends the axis on a curved, speed-varying path that reads as a
// wobble. Slerp between unit quaternions is a great circle at constant angular
// velocity, which is what "it is turning" looks like.
//
// The table is sixteen orientations with axes on a Fibonacci sphere and the
// rotation amount stepped by the golden angle, walked with a stride of 3. That
// pair was measured, not chosen: every consecutive leg is at least 97 degrees
// and the mean is 128, so no leg arrives somewhere it had almost got to already.
// Random targets average the same and have short legs in them, and a short leg
// looks like the effect stalled.
//
// Usage: a CfxTumble in SEGENV data, cfx_tumbleInit() on the first call, then
// cfx_tumbleStep() with a 16-bit step per frame (65536 = one full leg) and
// cfx_tumbleMatrix() for the world -> object matrix. The leg counter WRAPPING
// is what retargets, not the counter being small - it is small for the first
// few frames of every leg too.
#define CFX_TUMBLE_N      16
#define CFX_TUMBLE_STRIDE 3
static const float CFX_TUMBLE_Q[CFX_TUMBLE_N][4] PROGMEM = {   // w, x, y, z
  {  0.649448f,  0.264610f,  0.000000f,  0.712881f },
  {  0.019634f, -0.429775f,  0.393709f,  0.812343f },
  { -0.619094f,  0.049858f, -0.568101f,  0.539905f },
  {  0.214309f,  0.491368f,  0.640902f,  0.549431f },
  { -0.453990f, -0.788962f, -0.139556f,  0.389815f },
  {  0.400749f,  0.734323f, -0.467116f,  0.286309f },
  { -0.271440f, -0.245426f,  0.912973f,  0.180460f },
  {  0.571788f, -0.377390f, -0.726641f,  0.051275f },
  { -0.078459f,  0.934595f,  0.341313f, -0.062307f },
  { -0.693087f, -0.654500f,  0.270168f, -0.135160f },
  {  0.117537f,  0.399828f, -0.854409f, -0.310334f },
  { -0.539138f,  0.226659f,  0.722624f, -0.368470f },
  {  0.309017f, -0.680342f, -0.394272f, -0.534969f },
  { -0.364470f,  0.660461f, -0.145201f, -0.640210f },
  {  0.488621f, -0.292529f,  0.416092f, -0.708903f },
  { -0.175796f, -0.044023f, -0.339725f, -0.922900f },
};

struct CfxTumble {
  float    qa[4], qb[4];       // the leg's endpoints
  uint16_t leg;                // 0..65535 along it
  uint8_t  qi;                 // table index of qb
};

static inline void cfx_tumbleLoad(int i, float *q) {
  const int k = ((i % CFX_TUMBLE_N) + CFX_TUMBLE_N) % CFX_TUMBLE_N;
  for (int j = 0; j < 4; j++) q[j] = pgm_read_float(&CFX_TUMBLE_Q[k][j]);
}

static inline void cfx_tumbleInit(CfxTumble &t) {
  t.qi = CFX_TUMBLE_STRIDE;
  cfx_tumbleLoad(0, t.qa);
  cfx_tumbleLoad(t.qi, t.qb);
  t.leg = 0;
}

// The same walk, but starting upright: the first leg runs from the identity
// - the pole on the lid's centre - out to the table. For an effect whose
// figure is drawn about the pole, this is the difference between a picture
// that starts centred and one that starts thirty degrees toward a corner.
static inline void cfx_tumbleInitTop(CfxTumble &t) {
  t.qi = CFX_TUMBLE_STRIDE;
  t.qa[0] = 1.0f; t.qa[1] = 0.0f; t.qa[2] = 0.0f; t.qa[3] = 0.0f;
  cfx_tumbleLoad(t.qi, t.qb);
  t.leg = 0;
}
// Keep the frame's pole above a height on the cube. The walk visits every
// orientation, and an effect drawn ABOUT the pole loses its figure when the
// pole sinks under the open bottom. This lifts the pole to z = zmin along
// the shortest arc and turns the whole frame with it, continuously, so the
// figure slides along the rim instead of falling through it. M maps cube
// directions into the pole's frame; its pole is M's third row.
static inline void cfx_tumbleKeepAbove(float M[3][3], float zmin) {
  const float px = M[2][0], py = M[2][1], pz = M[2][2];
  if (pz >= zmin) return;
  const float h = sqrtf(px * px + py * py);
  float tx, ty, tz = zmin;
  const float hh = sqrtf(1.0f - zmin * zmin);
  if (h > 1e-6f) { tx = px / h * hh; ty = py / h * hh; } else { tx = hh; ty = 0.0f; }
  // R takes p to t (Rodrigues); the new frame is M * R^T
  float ax = py * tz - pz * ty, ay = pz * tx - px * tz, az = px * ty - py * tx;
  const float sn = sqrtf(ax * ax + ay * ay + az * az);
  if (sn < 1e-6f) return;
  ax /= sn; ay /= sn; az /= sn;
  const float c = px * tx + py * ty + pz * tz, s_ = sn, k = 1.0f - c;
  float R[3][3] = {
    { c + ax * ax * k,        ax * ay * k - az * s_,  ax * az * k + ay * s_ },
    { ay * ax * k + az * s_,  c + ay * ay * k,        ay * az * k - ax * s_ },
    { az * ax * k - ay * s_,  az * ay * k + ax * s_,  c + az * az * k       } };
  float N[3][3];
  for (int i = 0; i < 3; i++) for (int j = 0; j < 3; j++)
    N[i][j] = M[i][0] * R[j][0] + M[i][1] * R[j][1] + M[i][2] * R[j][2];   // M * R^T
  for (int i = 0; i < 3; i++) for (int j = 0; j < 3; j++) M[i][j] = N[i][j];
}
static inline void cfx_tumbleStep(CfxTumble &t, uint16_t step) {
  if (!step) step = 1;
  const uint16_t nl = (uint16_t)(t.leg + step);
  if (nl < t.leg) {                                    // wrapped: leg complete
    for (int j = 0; j < 4; j++) t.qa[j] = t.qb[j];
    t.qi = (uint8_t)((t.qi + CFX_TUMBLE_STRIDE) % CFX_TUMBLE_N);
    cfx_tumbleLoad(t.qi, t.qb);
  }
  t.leg = nl;
}

// Slerp to the current orientation, then that as a matrix TRANSPOSED - what a
// pixel needs is world -> object, and the transpose of a rotation is its
// inverse for free.
static inline void cfx_tumbleMatrix(const CfxTumble &t, float M[3][3]) {
  float d = t.qa[0]*t.qb[0] + t.qa[1]*t.qb[1] + t.qa[2]*t.qb[2] + t.qa[3]*t.qb[3];
  float b[4] = { t.qb[0], t.qb[1], t.qb[2], t.qb[3] };
  // q and -q are the same orientation but opposite ways round the sphere.
  // Without this half the legs take the long way and the tumble reverses
  // direction at random.
  if (d < 0.0f) { d = -d; for (int j = 0; j < 4; j++) b[j] = -b[j]; }
  const float u = (float)t.leg * (1.0f / 65535.0f);
  float wa, wb;
  if (d > 0.9995f) { wa = 1.0f - u; wb = u; }          // sin(Om) -> 0: lerp
  else {
    const float om = acosf(d), so = sinf(om);
    wa = sinf((1.0f - u) * om) / so;
    wb = sinf(u * om) / so;
  }
  float q[4];
  for (int j = 0; j < 4; j++) q[j] = wa * t.qa[j] + wb * b[j];
  const float n  = sqrtf(q[0]*q[0] + q[1]*q[1] + q[2]*q[2] + q[3]*q[3]);
  const float in = (n > 1e-6f) ? (1.0f / n) : 1.0f;
  const float w = q[0]*in, x = q[1]*in, y = q[2]*in, z = q[3]*in;
  M[0][0] = 1.0f - 2.0f*(y*y + z*z); M[1][0] = 2.0f*(x*y - z*w);         M[2][0] = 2.0f*(x*z + y*w);
  M[0][1] = 2.0f*(x*y + z*w);        M[1][1] = 1.0f - 2.0f*(x*x + z*z);  M[2][1] = 2.0f*(y*z - x*w);
  M[0][2] = 2.0f*(x*z - y*w);        M[1][2] = 2.0f*(y*z + x*w);         M[2][2] = 1.0f - 2.0f*(x*x + y*y);
}

static inline int8_t cfx_clamp8(float v) {
  const int r = (int)(v * 127.0f);
  return (int8_t)((r < -127) ? -127 : (r > 127 ? 127 : r));
}

// True when this segment looks like the cube's unfolded net.
static inline bool cfx_isCube(int cols, int rows) {
  return !SEGMENT.check3 && cols == rows && cols >= 12 && (cols % 3) == 0;
}

// ---------------------------------------------------------------------------
// Six faces
// ---------------------------------------------------------------------------
// A cube with a lit BOTTOM keeps the same 3B x 3B net: the bottom face lives in
// the (2,2) corner block - the one under EAST, right of SOUTH. The net stays
// square, so cube detection and every buffer keep their shape; that one block
// simply stops being a gap. Its orientation is the one cfx_pos always gave
// the gap corners (X = a, Y = -b, Z = -1): looking up at it from below, north
// is up and east is to your left, as it would be. The flag comes from the
// build (-D CFX_SIX_FACES=1, what the studio sets when the project's cube has
// six faces), from the CubeFXBank usermod's settings, or from the simulator.
// Everything that asks "is this pixel a gap" asks these, never the block
// index directly.
extern bool cfx_sixFaces;
extern uint8_t cfx_scriptStride;   // the Studio Script effect's frame-budget stride: 1 full, 2 half, 4 quarter width
extern uint32_t cfx_scriptTook;    // its last frame's pixel loop, microseconds
static inline int  cfx_faces() { return cfx_sixFaces ? 6 : 5; }
static inline bool cfx_gapBlock(int bx, int by) {
  return bx != 1 && by != 1 && !(cfx_sixFaces && bx == 2 && by == 2);
}
static inline bool cfx_gap(int x, int y, int B) { return cfx_gapBlock(x / B, y / B); }

// The shape as a table (cube_fx_00_geometry.cpp): a position for every
// pixel, sent by the studio for any shape that is not a cube net or a flat
// matrix. Present and sized for this segment, it is what cfx_pos() answers.
extern const int8_t *cfx_geomTab;      // cols*rows x (x, y, z), int8, -1..1 as -127..127
extern const int8_t *cfx_geomNrm;      // the normals the same way, or null
extern const uint8_t *cfx_geomPart;    // cols*rows x (part id, place along the part 0..255), or null
extern uint16_t cfx_geomCols, cfx_geomRows, cfx_geomParts;
void cfx_geomPoll();
static inline bool cfx_geomFor(int cols, int rows) {
  return cfx_geomTab && cfx_geomCols == (uint16_t)cols && cfx_geomRows == (uint16_t)rows;
}
// The pixel's outward direction (unit): the table's normal when it has
// them, else the direction from the centre.
static inline void cfx_geomNormal(int x, int y, int cols, float X, float Y, float Z, float &nx, float &ny, float &nz) {
  if (cfx_geomNrm) {
    const int8_t *n = cfx_geomNrm + ((size_t)y * cols + x) * 3;
    nx = n[0] * (1.0f / 127.0f); ny = n[1] * (1.0f / 127.0f); nz = n[2] * (1.0f / 127.0f);
    return;
  }
  const float L = sqrtf(X * X + Y * Y + Z * Z); const float iL = L > 1e-6f ? 1.0f / L : 1.0f;
  nx = X * iL; ny = Y * iL; nz = Z * iL;
}

// The part of the shape a pixel belongs to (a shape is parts in wiring
// order: strips, rings, panels...), where along it the pixel sits (0..1)
// and how many parts there are: 0, 0, 1 without a table.
static inline void cfx_geomPartOf(int x, int y, int cols, int &part, float &along, int &nparts) {
  if (cfx_geomPart) {
    const uint8_t *p = cfx_geomPart + ((size_t)y * cols + x) * 2;
    part = p[0]; along = p[1] * (1.0f / 255.0f); nparts = cfx_geomParts > 0 ? cfx_geomParts : 1;
  } else { part = 0; along = 0.0f; nparts = 1; }
}

// Surface position of one pixel. If a face on your cube comes out rotated or
// mirrored, only the six face lines below need changing - every effect in
// this file reads through here. A shape table for this segment's size
// answers first: that is how any shape reaches every effect.
static inline void cfx_pos(int x, int y, int cols, int rows, int B, bool cubeNet,
                           float &X, float &Y, float &Z) {
  if (cfx_geomFor(cols, rows)) {
    const int8_t *p = cfx_geomTab + ((size_t)y * cols + x) * 3;
    X = p[0] * (1.0f / 127.0f); Y = p[1] * (1.0f / 127.0f); Z = p[2] * (1.0f / 127.0f);
    return;
  }
  if (cubeNet) {
    const int bx = x / B, by = y / B;
    const float a = 2.0f * ((x % B) + 0.5f) / (float)B - 1.0f;   // -1..1
    const float b = 2.0f * ((y % B) + 0.5f) / (float)B - 1.0f;

    if      (bx == 1 && by == 1) { X =  a; Y = -b; Z =  1.0f; }  // TOP
    else if (bx == 1 && by == 0) { X =  a; Y =  1.0f; Z =  b; }  // NORTH
    else if (bx == 1 && by == 2) { X =  a; Y = -1.0f; Z = -b; }  // SOUTH
    else if (bx == 0 && by == 1) { X = -1.0f; Y = -b; Z =  a; }  // WEST
    else if (bx == 2 && by == 1) { X =  1.0f; Y = -b; Z = -a; }  // EAST
    else                         { X =  a; Y = -b; Z = -1.0f; }  // BOTTOM at (2,2) when six; the gap corners
  } else {
    X = 2.0f * (x + 0.5f) / (float)cols - 1.0f;
    Y = 1.0f - 2.0f * (y + 0.5f) / (float)rows;
    Z = 0.0f;
  }
}

// --- frame-rate independence ------------------------------------------------
// Milliseconds since the previous frame. fx_dt keeps its timestamp in the TOP
// 16 bits of a 32-bit store so the low bits stay free for the effect's flags.
static inline uint16_t fx_dt(uint32_t &store) {
  const uint16_t now = (uint16_t)strip.now;
  uint16_t dt = (uint16_t)(now - (uint16_t)(store >> 16));
  if (dt > 250) dt = 250;
  store = (store & 0x0000FFFFu) | ((uint32_t)now << 16);
  return dt;
}
static inline uint16_t fx_dt8(uint8_t *store) {
  const uint16_t now = (uint16_t)strip.now;
  uint16_t dt = (uint16_t)(now - ((uint16_t)store[0] | ((uint16_t)store[1] << 8)));
  if (dt > 250) dt = 250;
  store[0] = (uint8_t)(now & 0xFF); store[1] = (uint8_t)(now >> 8);
  return dt;
}
// Calibrated at 23 ms, so motion is unchanged at ~43 fps and holds steady
// above it rather than running away with the frame rate.
static inline int32_t fx_step(int32_t perFrame, uint16_t dtMs) {
  return (perFrame * (int32_t)dtMs) / 23;
}
static inline uint8_t fx_fade(int perFrame, uint16_t dtMs) {
  int32_t v = ((int32_t)perFrame * (int32_t)dtMs) / 23;
  return (uint8_t)((v > 255) ? 255 : ((v < 1) ? 1 : v));
}

// --- beat gate ---------------------------------------------------------------
// samplePeak fires on any transient, stays set for several frames, and is
// binary. That combination is what makes beat responses feel violent. This:
//   - consumes the flag the way WLED's own AR effects do, so one hit fires once
//   - ignores transients the LOW bins aren't carrying, so hats and snares and
//     vocal consonants are filtered out and kicks come through
//   - returns the STRENGTH of the hit, so a soft kick gives a soft response
// Build with -D FX_BEAT_FLOOR=25 to let quieter hits through, or a higher
// value to be stricter.
//
// NOTE ON LINKAGE: this and the two analyzers below are `inline`, NOT
// `static inline`. A static function in a header gets its own private copy of
// its function-local statics in every .cpp that includes it - so with ~30
// effect files you'd get ~30 independent beat gates, and the "one answer per
// frame" contract would only hold within a single file. Plain `inline` gives
// one shared instance across the whole build, which is what these were always
// documented to be.
#ifndef FX_BEAT_FLOOR
  #define FX_BEAT_FLOOR 40
#endif
// How far the low band must RISE above the level it was already sitting at
// for a transient to count as a kick. A sustained bass note keeps re-arming
// samplePeak every few frames without ever rising, and every one of those
// used to come through as a full-strength beat - which is what made tempo
// lock run away and beat-driven effects machine-gun under a held note.
// Lower this if kicks feel like they're being missed on dense mixes.
#ifndef FX_BEAT_RISE
  #define FX_BEAT_RISE 38
#endif
inline uint8_t fx_lowBeat(um_data_t *um) {
  static uint32_t seenFrame = 0xFFFFFFFFu;
  static uint8_t  cached    = 0;
  static uint8_t  prevPeak  = 0;
  static uint8_t  loFloor   = 0;               // where the low band already sits
  static uint32_t dtStore   = 0;
  if (strip.now == seenFrame) return cached;   // one answer per frame
  seenFrame = strip.now;
  cached = 0;

  const uint16_t dt  = fx_dt(dtStore);
  const uint8_t *fft = (uint8_t *)um->u_data[2];
  const int lo = (fft[0] + fft[1] + fft[2]) / 3;

  // Two-sided ~260 ms slew, updated every frame - this is the "floor" a kick
  // has to clear, not a peak follower. Evaluated against the PREVIOUS frame's
  // value so the kick's own spike can't raise its own bar.
  const int floorNow = (int)loFloor;
  {
    int e = floorNow + (((lo - floorNow) * (int)dt) / 260);
    if (e < 0) e = 0; else if (e > 255) e = 255;
    loFloor = (uint8_t)e;
  }

  const uint8_t peak = *(uint8_t *)um->u_data[3];
  const bool rising = peak && !prevPeak;       // the flag stays set for frames
  prevPeak = peak ? 1 : 0;
  if (!rising) return 0;

  int hi = 0;
  for (int k = 7; k < 16; k++) hi += fft[k];
  hi /= 9;
  if (lo < FX_BEAT_FLOOR || lo <= hi) return 0;
  if (lo < floorNow + FX_BEAT_RISE) return 0;  // not a transient, just a held note
  cached = (uint8_t)lo;                        // strength, not a flag
  return cached;
}

// --- band envelopes ----------------------------------------------------
// Frame-rate-independent fast-attack / slow-release follower. Release is
// expressed as a time constant in ms so the envelope behaves the same at
// 20 fps as at 100 fps - the old `env -= (env-x)>>3` form released ~3x
// faster on the panel than on the cube purely because of frame rate.
inline uint8_t fx_env(uint8_t prev, uint8_t now, uint16_t dtMs, uint16_t releaseMs) {
  if (now >= prev) return now;                       // instant attack
  if (releaseMs < 1) releaseMs = 1;
  int32_t drop = ((int32_t)(prev - now) * (int32_t)dtMs) / (int32_t)releaseMs;
  if (drop < 1) drop = 1;
  const int32_t v = (int32_t)prev - drop;
  return (uint8_t)((v < 0) ? 0 : v);
}

// --- tempo analyzer ----------------------------------------------------
// Turns fx_lowBeat()'s one-shot hits into a continuous, predictive tempo:
// a free-running phase that ticks at the current estimated beat period (so
// animation stays smooth between hits and survives a missed one), pulled
// gently toward each confirmed hit, plus a BPM estimate and a confidence
// value effects use to fade beat-locked motion back to idle when the bass
// drops out rather than firing on a stale prediction.
//
// One shared lock across the whole build - there is only one song playing,
// and the per-frame guard means several segments can all read it cheaply.
//
// `beat` is the one thing most effects actually want: a single-frame flag
// that fires when the PREDICTED beat lands. Before, every effect had to
// stash last frame's phase and test for a wrap itself, which mis-fires every
// time the PLL nudges the phase backwards. Read st.beat instead.
struct CfxTempoState {
  uint16_t periodMs;    // estimated beat period, ms (0 = not locked yet)
  uint8_t  phase;       // 0..255 sawtooth, wraps once per predicted beat
  uint8_t  confidence;  // 0..255 - trust in phase/bpm right now
  uint16_t bpm;         // derived display value, 0 while unlocked
  uint8_t  beat;        // 255 on the single frame the predicted beat lands
  uint8_t  hit;         // fx_lowBeat() strength this frame, 0 if none
};

#ifndef FX_TEMPO_MIN_MS
  #define FX_TEMPO_MIN_MS 300   // 200 BPM ceiling
#endif
#ifndef FX_TEMPO_MAX_MS
  #define FX_TEMPO_MAX_MS 1500  // 40 BPM floor
#endif
// A locked tempo ignores hits landing sooner than this fraction of a period
// after the last accepted beat. Without it a SUSTAINED bass note - which
// re-triggers samplePeak over and over - feeds a stream of tiny intervals
// into the estimator and octave-correction happily doubles them into
// "plausible" ones, so the whole lock accelerates for as long as the note
// holds. That runaway is what used to make beat-locked effects visibly speed
// up under a held bass note. It is now an explicit, tunable behaviour in
// cfx_drop().surge instead of an accident in here.
#ifndef FX_TEMPO_REFRACT_PCT
  #define FX_TEMPO_REFRACT_PCT 60
#endif

inline CfxTempoState &cfx_tempo(um_data_t *um) {
  static CfxTempoState st         = {0, 0, 0, 0, 0, 0};
  static uint32_t       lastBeatMs = 0;
  static bool            haveLast  = false;
  static uint32_t         dtStore  = 0;
  static uint16_t          phaseQ8 = 0;              // phase in 8.8 fixed point
  static uint32_t           seenFrame = 0xFFFFFFFFu;

  if (strip.now == seenFrame) return st;             // one update per frame
  seenFrame = strip.now;

  const uint16_t dtMs = fx_dt(dtStore);
  const uint8_t  hit  = fx_lowBeat(um);
  const uint32_t now  = strip.now;
  st.hit  = hit;
  st.beat = 0;

  // Predict: advance phase every frame regardless of whether a hit arrived.
  // Kept in 8.8 fixed point - the old integer step truncated ~0.8 of a phase
  // unit per frame at 43 fps, which is a ~7% slow drift the PLL then had to
  // fight on every single beat.
  if (st.periodMs > 0) {
    uint32_t adv = ((uint32_t)dtMs * 65536u) / (uint32_t)st.periodMs;
    if (adv > 0xFFFFu) adv = 0xFFFFu;
    const uint32_t np = (uint32_t)phaseQ8 + adv;
    if (np > 0xFFFFu) st.beat = 255;                 // predicted beat lands now
    phaseQ8  = (uint16_t)np;
    st.phase = (uint8_t)(phaseQ8 >> 8);
  }

  // Refractory: once locked, a transient arriving far too soon after the last
  // accepted beat is not a beat. Drop it entirely - don't even restart the
  // interval clock with it.
  const bool refractory = haveLast && st.periodMs > 0 && st.confidence >= 64 &&
    (now - lastBeatMs) < ((uint32_t)st.periodMs * FX_TEMPO_REFRACT_PCT) / 100;

  if (hit && !refractory) {
    if (haveLast) {
      uint32_t interval = now - lastBeatMs;

      // Octave-correct against the current estimate by the NEAREST whole
      // multiple, so one missed beat (2x), two missed beats (3x) and a
      // double-time leak (1/2x) all fold back correctly. The old code only
      // ever halved or doubled once, so a 3x gap folded to 1.5x and dragged
      // the lock somewhere between the two.
      if (st.periodMs > 0 && interval > 0) {
        const uint32_t p = st.periodMs;
        if (interval >= p) {
          const uint32_t m = (interval + p / 2) / p;
          if (m >= 2 && interval / m >= FX_TEMPO_MIN_MS) interval /= m;
        } else {
          const uint32_t k = (p + interval / 2) / interval;
          if (k >= 2 && interval * k <= FX_TEMPO_MAX_MS) interval *= k;
        }
      }

      if (interval >= FX_TEMPO_MIN_MS && interval <= FX_TEMPO_MAX_MS) {
        // Accept freely while acquiring lock; once locked, reject hits that
        // don't land near the current estimate (an off-beat snare/hat leak)
        // instead of letting them drag tempo around.
        const bool plausible = (st.confidence < 64) || (st.periodMs == 0) ||
          (interval > (uint32_t)st.periodMs * 3 / 4 && interval < (uint32_t)st.periodMs * 4 / 3);

        if (plausible) {
          const int sm = (st.confidence < 64) ? 2 : 6;   // fast acquire, slow settle
          st.periodMs = (st.periodMs == 0) ? (uint16_t)interval
            : (uint16_t)(st.periodMs + ((int32_t)interval - (int32_t)st.periodMs) / sm);

          if (st.confidence > 96) {
            // PLL nudge on the SIGNED phase error. Phase near 255 means the
            // real beat beat our prediction to it, so the fix is to wrap
            // forward, not to drag the phase back down toward zero - which
            // is exactly what the old unsigned `phase -= phase/4` did, and
            // why lock never felt tight on the back half of a cycle.
            int32_t err = (int32_t)phaseQ8;
            if (err > 32768) err -= 65536;
            const int32_t np = (int32_t)phaseQ8 - err / 4;
            if (np > 0xFFFF) st.beat = 255;
            phaseQ8 = (uint16_t)((uint32_t)np & 0xFFFFu);
          } else {
            phaseQ8 = 0;                               // snap while acquiring
            st.beat = 255;
          }
          st.phase = (uint8_t)(phaseQ8 >> 8);

          st.confidence = (uint8_t)(st.confidence + (255 - st.confidence) / 3);
        } else if (st.confidence > 20) {
          st.confidence -= 20;   // don't trust it, but let a real tempo change land
        }
      }
    }
    lastBeatMs = now;
    haveLast   = true;
  }

  // Bass likely dropped: keep ticking so a returning kick lands in phase,
  // but stop trusting the prediction. Decay is per-second, not per-frame, so
  // "how long until the scope goes dim" doesn't depend on frame rate.
  if (haveLast && st.periodMs > 0) {
    const uint32_t silence = now - lastBeatMs;
    if (silence > (uint32_t)st.periodMs * 2) {
      const int32_t d = ((int32_t)dtMs * 170) / 1000;     // ~1.5 s to fully doubt
      st.confidence = (st.confidence > d) ? (uint8_t)(st.confidence - d) : 0;
    }
    if (silence > (uint32_t)st.periodMs * 8) {   // stopped, not dropped - forget it
      st.periodMs = 0;
      haveLast    = false;
      phaseQ8     = 0;
      st.phase    = 0;
    }
  }

  st.bpm = (st.periodMs > 0) ? (uint16_t)(60000u / st.periodMs) : 0;
  return st;
}

// --- drop / build / surge helper ---------------------------------------
// A "drop" is NOT just loud bass. It is the bass hit that arrives after the
// track has taken the bass AWAY for a while and let the mids swell - the
// breakdown-then-slam shape. The old version here fired on any sustained
// bass-heavy passage, which on bass-forward music meant it was latched on
// almost permanently and never read as an event at all.
//
// Three separate outputs, because they are three separate musical things:
//
//   build   0..255, live. Rises while the bass is gone and the mids are
//           carrying the track - i.e. you are inside a riser. This is the
//           thing to hold your breath on.
//   hit     one-shot 0..255, the single frame the drop lands. Strength is
//           the product of how long the bass was gone, how much the mids
//           swelled, and how hard the returning kick is.
//   intensity 0..255, `hit` decaying over FX_DROP_DECAY_MS. Use for glow,
//           thickness, extra spawns - anything that should ring out.
//   surge   0..255. A SUSTAINED bass-heavy hold (the long note, not a kick).
//           Separate from the drop entirely, and it is what drives the
//           speed-up in speedScale.
//
// speedScale is a 8.8-style multiplier where 256 == normal speed, so it can
// express both directions: surge pushes it above 256 (faster), a build pulls
// it under (the track holding back). Feed it to cfx_dropDt().
struct CfxDropState {
  uint8_t  hit;         // one-shot: 255-scale strength on the drop frame only
  uint8_t  intensity;   // decaying tail of the last drop
  uint8_t  build;       // 0..255 - how deep into a build-up we are right now
  uint8_t  surge;       // 0..255 - sustained bass-heavy hold
  uint16_t speedScale;  // 256 = normal, >256 faster, <256 slower
  bool     active;      // intensity > 0
};

#ifndef FX_DROP_BASS_GONE
  #define FX_DROP_BASS_GONE   58    // bass envelope at/below this counts as "no bass"
#endif
#ifndef FX_DROP_BASS_BACK
  #define FX_DROP_BASS_BACK   140   // bass envelope crossing this counts as "it's back"
#endif
#ifndef FX_DROP_MID_MIN
  #define FX_DROP_MID_MIN     45    // mids must be carrying the track for it to be a build
#endif
#ifndef FX_DROP_VOID_MS
  #define FX_DROP_VOID_MS     1100  // minimum bass-free stretch before a return counts
#endif
#ifndef FX_DROP_VOID_FULL_MS
  #define FX_DROP_VOID_FULL_MS 3200 // bass-free stretch that scores a full-strength build
#endif
#ifndef FX_DROP_ARM_MS
  #define FX_DROP_ARM_MS      2200  // how long an armed build waits for its slam before fizzling
#endif
#ifndef FX_DROP_MIN_BUILD
  #define FX_DROP_MIN_BUILD   70    // build score required to call a return a drop
#endif
#ifndef FX_DROP_DECAY_MS
  #define FX_DROP_DECAY_MS    1500  // ms for intensity to ring out from 255 to 0
#endif
#ifndef FX_DROP_SURGE_ON
  #define FX_DROP_SURGE_ON    185   // bass envelope that starts the sustained-hold count
#endif
#ifndef FX_DROP_SURGE_OFF
  #define FX_DROP_SURGE_OFF   140   // lower bar that KEEPS an already-running hold alive
#endif
#ifndef FX_DROP_SURGE_MS
  #define FX_DROP_SURGE_MS    260   // continuous ms above threshold to call it a hold
#endif
#ifndef FX_DROP_SURGE_MAX_MS
  #define FX_DROP_SURGE_MAX_MS 7000 // safety: a hold can't ride forever
#endif
#ifndef FX_DROP_RAMP_MS
  #define FX_DROP_RAMP_MS     600   // ms to ease surge from 0<->255 in either direction
#endif
// Speed shaping, in percent of normal at full strength.
#ifndef FX_DROP_SURGE_PCT
  #define FX_DROP_SURGE_PCT   155   // held bass note -> up to 1.55x speed
#endif
#ifndef FX_DROP_BUILD_PCT
  #define FX_DROP_BUILD_PCT   78    // inside a riser -> down to 0.78x speed
#endif

inline CfxDropState &cfx_drop(um_data_t *um, const CfxTempoState &tempo) {
  static CfxDropState st = {0, 0, 0, 0, 256, false};
  static uint32_t   dtStore   = 0;
  static uint8_t     bassEnv  = 0;
  static uint8_t      midEnv  = 0;
  static uint8_t       midAtVoid = 0;
  static uint16_t       voidMs  = 0;
  static uint16_t        surgeMs = 0;
  static uint16_t         heldMs = 0;
  static bool              surging = false;
  static bool               armed  = false;    // a real build has been seen
  static uint8_t             armedBuild = 0;   // peak build score while armed
  static uint16_t             armedMs   = 0;   // how long we've been waiting for the slam
  static uint32_t              seenFrame = 0xFFFFFFFFu;

  if (strip.now == seenFrame) return st;        // one update per frame
  seenFrame = strip.now;

  const uint16_t dtMs = fx_dt(dtStore);
  const uint8_t *fft  = (uint8_t *)um->u_data[2];
  const uint8_t  bass = (uint8_t)((fft[0] + fft[1] + fft[2]) / 3);
  const uint8_t  mid  = (uint8_t)((fft[5] + fft[6] + fft[7] + fft[8]) / 4);

  const uint8_t prevBass = bassEnv;
  bassEnv = fx_env(bassEnv, bass, dtMs, 220);
  midEnv  = fx_env(midEnv,  mid,  dtMs, 320);

  st.hit = 0;

  // --- the void: bass gone, mids carrying ---------------------------------
  if (bassEnv <= FX_DROP_BASS_GONE) {
    if (voidMs == 0) midAtVoid = midEnv;        // remember where the mids started
    voidMs = (uint16_t)((voidMs + dtMs > 60000) ? 60000 : voidMs + dtMs);
  } else if (bassEnv < FX_DROP_BASS_BACK) {
    // grey zone - neither properly gone nor properly back. Hold the count so
    // one stray thump mid-breakdown doesn't wipe a 3-second build.
  } else {
    voidMs = 0;
  }

  // Live build score: how long the bass has been away x how present the mids
  // are x how much they've swelled since the void started.
  {
    uint32_t vs = ((uint32_t)voidMs * 255u) / FX_DROP_VOID_FULL_MS;
    if (vs > 255) vs = 255;
    int ms = ((int)midEnv - FX_DROP_MID_MIN) * 4;
    if (ms < 0) ms = 0;
    if (ms > 255) ms = 255;
    int swell = ((int)midEnv - (int)midAtVoid) * 3;
    if (swell < 0) swell = 0;
    if (swell > 255) swell = 255;
    const uint8_t midScore = (uint8_t)qadd8((uint8_t)((ms * 3) / 4), (uint8_t)(swell / 4));
    st.build = (voidMs >= FX_DROP_VOID_MS / 3)
      ? (uint8_t)scale8((uint8_t)vs, midScore) : 0;
  }

  // Arming has to LATCH. The frame the bass comes back is the frame voidMs is
  // reset, so a live `armed = build >= threshold` test is always false exactly
  // when the drop lands. Latch the peak build instead and hold it briefly.
  if (voidMs >= FX_DROP_VOID_MS && st.build >= FX_DROP_MIN_BUILD) {
    armed = true;
    armedMs = 0;
    if (st.build > armedBuild) armedBuild = st.build;
  } else if (armed) {
    armedMs = (uint16_t)((armedMs + dtMs > 60000) ? 60000 : armedMs + dtMs);
    if (armedMs > FX_DROP_ARM_MS) { armed = false; armedBuild = 0; }   // build fizzled
  }

  // --- the return: bass slams back while a build was in progress -----------
  if (armed) {
    const bool slam = (bassEnv >= FX_DROP_BASS_BACK) && (prevBass < FX_DROP_BASS_BACK);
    const bool kick = tempo.hit >= FX_BEAT_FLOOR * 2 && bassEnv >= FX_DROP_BASS_BACK;
    if (slam || kick) {
      const uint8_t force = tempo.hit ? (uint8_t)qadd8(150, (uint8_t)(tempo.hit >> 1)) : 190;
      st.hit       = scale8(armedBuild, force);
      st.intensity = st.hit;
      voidMs       = 0;
      armed        = false;
      armedBuild   = 0;
      midAtVoid    = midEnv;
    }
  }

  // Ring-out
  if (st.intensity) {
    const int32_t d = ((int32_t)255 * dtMs) / FX_DROP_DECAY_MS + 1;
    st.intensity = (st.intensity > d) ? (uint8_t)(st.intensity - d) : 0;
  }
  st.active = st.intensity > 0;

  // --- surge: a SUSTAINED bass-heavy hold, tracked independently -----------
  const bool hot = surgeMs > 0 ? (bassEnv >= FX_DROP_SURGE_OFF) : (bassEnv >= FX_DROP_SURGE_ON);
  if (hot) surgeMs = (uint16_t)((surgeMs + dtMs > 60000) ? 60000 : surgeMs + dtMs);
  else     surgeMs = 0;

  if (!surging && surgeMs >= FX_DROP_SURGE_MS) { surging = true; heldMs = 0; }
  if (surging) {
    heldMs = (uint16_t)((heldMs + dtMs > 60000) ? 60000 : heldMs + dtMs);
    if (!hot || heldMs >= FX_DROP_SURGE_MAX_MS) surging = false;
  }

  {
    const uint8_t target = surging ? 255 : 0;
    const int delta = (int)(((uint32_t)255 * dtMs) / FX_DROP_RAMP_MS) + 1;
    if (st.surge < target)
      st.surge = (uint8_t)((st.surge + delta > target) ? target : st.surge + delta);
    else if (st.surge > target)
      st.surge = (uint8_t)((st.surge - delta < target) ? target : st.surge - delta);
  }

  // --- speed multiplier ----------------------------------------------------
  // surge pushes past 256, a live build pulls under it. They can't both be
  // strong at once (one needs loud bass, the other needs none), so a simple
  // sum of the two offsets is well-behaved.
  {
    const int32_t up   = ((int32_t)st.surge * (FX_DROP_SURGE_PCT - 100) * 256) / (100 * 255);
    const int32_t down = ((int32_t)st.build * (100 - FX_DROP_BUILD_PCT) * 256) / (100 * 255);
    int32_t s = 256 + up - down;
    if (s < 64)   s = 64;
    if (s > 1024) s = 1024;
    st.speedScale = (uint16_t)s;
  }
  return st;
}

// Wrap an effect's own fx_dt() result with this before handing it to
// fx_step()/fx_fade(). 256 is normal speed, so this is a no-op at rest.
inline uint16_t cfx_dropDt(uint16_t dtMs, uint16_t speedScale) {
  uint32_t v = ((uint32_t)dtMs * speedScale) >> 8;
  if (v > 1000) v = 1000;
  return (uint16_t)v;
}

// --- cube-net gap skipping --------------------------------------------------
// The corner blocks of the net are unlit (four of them, or three with a lit
// bottom): 44% of the pixel work. These need `cube` and `B` in scope, so they
// follow the Flat mode checkbox. A column is 0 in the middle band, 1 left, 2
// right; a row likewise; a corner is skipped unless it is the six-face bottom.
#define CFX_NET_PREP()  uint8_t _outCol[cols]; \
                        if (cube) for (int _c = 0; _c < cols; _c++) _outCol[_c] = (uint8_t)(((_c / B) != 1) ? (1 + ((_c / B) == 2)) : 0)
#define CFX_NET_ROW(Y)  const uint8_t _outRow = (uint8_t)((cube && (((Y) / B) != 1)) ? (1 + (((Y) / B) == 2)) : 0)
#define CFX_NET_SKIP(X) if (_outRow && _outCol[X] && !(cfx_sixFaces && _outRow == 2 && _outCol[X] == 2)) continue

// ---------------------------------------------------------------------------
// Storage that skips the gaps too
// ---------------------------------------------------------------------------
// The macros above stop us COMPUTING the four unlit corner blocks, but every
// effect still sized its per-pixel buffers to the whole 3B x 3B rectangle and
// carried storage for pixels that are never drawn - 44% of it wasted. That is
// invisible at one byte per pixel and expensive as soon as an effect keeps
// several bytes per pixel, which is what made Soap the largest allocation in
// the set and left it struggling to find contiguous space after a segment
// reset.
//
// cfx_cidx() renumbers the LIT pixels into a dense range, so a buffer only has
// to be cfx_litCount() entries long. It is pure arithmetic - no lookup table of
// its own - because the net is a plus shape and each row band has a known width:
//
//   y <  B    NORTH band, x in [B,2B)   -> [0,    B^2)
//   y < 2B    middle band, x in [0,3B)  -> [B^2,  4B^2)
//   else      SOUTH band, x in [B,2B)   -> [4B^2, 5B^2)
//
// Five blocks of B^2 - one per lit face - against nine for the rectangle; six
// with a lit bottom, whose block sits beside SOUTH so the south band is simply
// twice as wide. On a flat panel every pixel is lit, so this is the identity
// mapping and costs nothing. Only ever pass coordinates that survived
// CFX_NET_SKIP: a gap corner has no slot and would alias onto a real pixel's.
static inline int cfx_cidx(int x, int y, int cols, int B, bool cube) {
  if (!cube) return y * cols + x;
  const int BB = B * B;
  if (y <     B) return              y * B + (x - B);
  if (y < 2 * B) return BB + (y -     B) * 3 * B + x;
  return          4 * BB + (y - 2 * B) * (cfx_sixFaces ? 2 * B : B) + (x - B);
}

static inline size_t cfx_litCount(int cols, int rows, int B, bool cube) {
  return cube ? (size_t)cfx_faces() * B * B : (size_t)cols * rows;
}

// custom3 is a FIVE-BIT slider. Widen it before using it as a full byte.
//
// FX.h declares `uint8_t custom3 : 5`, and json.cpp constrains anything coming
// in over the API to 0..31 before storing it. WLED's own effects respect that -
// map(SEGMENT.custom3, 0, 31, ...) and a comment calling it the reduced
// resolution slider - but fourteen effects here scaled it as though it ran to
// 255, with metadata defaults up to 210. On hardware every one of those
// requests clamps to 31, so the control sat in the bottom eighth of its range
// and the rest of the slider did nothing at all.
//
// It went unnoticed for a long time because the simulator's shim declared the
// field as a full byte, so the simulator was the only place those effects ever
// worked as designed. The shim now matches the firmware, and this is how an
// effect asks for a 0..255 control from a 0..31 slider:
//
//     const int turb = cfx_c3full(SEGMENT.custom3);
//
// Effects that genuinely want the 0..31 value - a shape index, a small count, a
// value centred on 16 - should keep reading SEGMENT.custom3 directly.
static inline uint8_t cfx_c3full(uint8_t c3) {
  return (uint8_t)(((int)c3 * 255) / 31);
}

// ---------------------------------------------------------------------------
// Surface topology - reading colour back from an ARBITRARY point on the cube
// ---------------------------------------------------------------------------
// Effects that transport colour rather than recompute it need to sample the
// surface at a point that is not a pixel centre and may not even be on the same
// face - a flow that carries colour off the lid has to find it continuing down
// a wall. These four do that, and they are shared because getting the fold
// crossings right once is worth a great deal more than getting them right
// several times.
//
// The scheme: classify a point by its dominant axis (which face) and its two
// off-axis coordinates (where on that face). A bilinear tap that runs off the
// edge of a face is turned back into a 3-D point, which then classifies onto
// the NEIGHBOUR - so a tap straddling a fold reads the correct pixels on both
// sides of it, with no special case per edge.
//
// Faces are numbered 0..5 = +X,-X,+Y,-Y,+Z,-Z throughout.

#ifndef CFX_GRAD
  #define CFX_GRAD 10               // finite-difference step for grad(psi)
#endif

// Which face a surface point sits on - just the dominant axis. The cheap half
// of cfx_face(), for callers that only need the outward normal.
static inline int cfx_faceOnly(int x, int y, int z) {
  const int ax = x < 0 ? -x : x, ay = y < 0 ? -y : y, az = z < 0 ? -z : z;
  if (az >= ax && az >= ay) return (z >= 0) ? 4 : 5;
  if (ay >= ax)             return (y >= 0) ? 2 : 3;
  return (x >= 0) ? 0 : 1;
}

// Face plus position on it, the off-axis pair normalised to -127..127.
static inline void cfx_face(int x, int y, int z, int &face, int &a, int &b) {
  const int ax = x < 0 ? -x : x, ay = y < 0 ? -y : y, az = z < 0 ? -z : z;
  int m;
  if (az >= ax && az >= ay) { face = (z >= 0) ? 4 : 5; m = az; a = x; b = y; }
  else if (ay >= ax)        { face = (y >= 0) ? 2 : 3; m = ay; a = x; b = z; }
  else                      { face = (x >= 0) ? 0 : 1; m = ax; a = y; b = z; }
  if (m < 1) m = 1;
  a = (a * 127) / m;
  b = (b * 127) / m;
}

// The exact inverse. Feeding it an a or b beyond +/-127 gives a point past the
// edge of that face, which cfx_face() then drops onto the neighbour - that is
// how a bilinear tap crosses a fold.
static inline void cfx_unface(int face, int a, int b, int &x, int &y, int &z) {
  switch (face) {
    case 0:  x =  127; y = a;    z = b;    break;
    case 1:  x = -127; y = a;    z = b;    break;
    case 2:  x = a;    y =  127; z = b;    break;
    case 3:  x = a;    y = -127; z = b;    break;
    case 4:  x = a;    y = b;    z =  127; break;
    default: x = a;    y = b;    z = -127; break;
  }
}

// Reverse-table read that follows the fold when the cell runs off the face.
// `rev` is a [6][Bq][Bq] table of compacted pixel indices, built once by the
// caller; 0xFFFF means "no pixel here".
static inline uint16_t cfx_rev(const uint16_t *rev, int Bq, int face, int ai, int bi) {
  if (ai >= 0 && ai < Bq && bi >= 0 && bi < Bq)
    return rev[((size_t)face * Bq + bi) * Bq + ai];

  const int half = 128 / (Bq > 0 ? Bq : 1);
  const int a = ((ai * 256) / Bq) - 128 + half;
  const int b = ((bi * 256) / Bq) - 128 + half;
  int x, y, z;    cfx_unface(face, a, b, x, y, z);
  int f2, a2, b2; cfx_face(x, y, z, f2, a2, b2);
  if (f2 == face) return 0xFFFF;                     // never left: no neighbour
  int ai2 = ((a2 + 128) * Bq) >> 8, bi2 = ((b2 + 128) * Bq) >> 8;
  if (ai2 < 0) ai2 = 0; else if (ai2 >= Bq) ai2 = Bq - 1;
  if (bi2 < 0) bi2 = 0; else if (bi2 >= Bq) bi2 = Bq - 1;
  return rev[((size_t)f2 * Bq + bi2) * Bq + ai2];
}

// Symmetric so it cannot drift. The obvious A + (B-A)*f/255 truncates toward
// zero, which biases every interpolation back toward A - harmless once, but
// transport runs this on its own output tens of times a second and small biases
// compound into a visible drift of the whole field.
static inline uint8_t cfx_lerp8(uint8_t A, uint8_t Bv, uint8_t f) {
  return (uint8_t)(((int)A * (255 - (int)f) + (int)Bv * (int)f + 127) / 255);
}

// ---------------------------------------------------------------------------
// MilkDrop waveforms - a rebuilt waveform, and the closed-curve wave modes
// ---------------------------------------------------------------------------
// Every MilkDrop wave mode draws the time-domain PCM waveform, and WLED's
// audioreactive publishes no such thing - sixteen FFT bins, volume, a peak
// flag. cfx_waveRebuild() makes one from the bins: sixteen sines at one to
// sixteen cycles across the window, each at its bin's level, each with a phase
// the caller drifts at its own rate. It is not the audio. It moves like it -
// bass makes slow wide swings, treble puts fine wiggle on them, silence is a
// flat line - and the closed-curve modes, which only ever wanted a wiggly loop
// modulated by the music, do not know the difference. The scope-line modes,
// which depend on the waveform's actual shape, are deliberately not here.
//
// cfx_waveShape() is the point generator for seven modes, ported from
// BeatDrop's vis_milk2/milkdropfs.cpp (3-clause BSD; MilkDrop 2 by Ryan Geiss
// / Nullsoft): Circle (mode 0), Spiral (1), Spiro (2), Star (13), Flower (14),
// Lasso (15) and Triangle (16). Coordinates come out in MilkDrop's +/-1 plane;
// the caller charts them onto whatever it is drawing on. Warp and Scope share
// all of this.
#define CFX_WAVE_MODES 7

// --- the PCM slot ------------------------------------------------------------
// audioreactive (with the cube_fx block in it) publishes u_data[8]: the last
// FFT batch's samples, 256 of them, int8. cfx_pcm() hands them over, or
// nullptr on a build without the slot, and cfx_waveFromPcm() makes the
// waveform Warp and Scope draw from them - the real one, where
// cfx_waveRebuild() below makes a stand-in from the bins.
#define CFX_PCM_N 256
struct CfxPcmView { volatile uint8_t which; int8_t buf[2][CFX_PCM_N]; };
static inline const int8_t *cfx_pcm(um_data_t *um) {
  if (!um || um->u_size < 9 || !um->u_data[8]) return nullptr;
  const CfxPcmView *p = (const CfxPcmView *)um->u_data[8];
  return p->buf[p->which & 1];
}
static inline void cfx_waveFromPcm(const int8_t *pcm, float *W, int NS, float gain) {
  for (int i = 0; i < NS; i++) {
    const int j = (int)((uint32_t)i * CFX_PCM_N / (uint32_t)NS);
    W[i] = (float)pcm[j] * (gain / 127.0f);
  }
}

static inline void cfx_waveRebuild(const uint8_t *fft, const uint16_t *ph16, float *W, int NS) {
  float amp[16], ph[16], tot = 0.0f;
  for (int b = 0; b < 16; b++) {
    amp[b] = ((float)fft[b] / 255.0f) / (1.0f + 0.25f * (float)b);
    tot += amp[b];
    ph[b] = (float)ph16[b] * (6.28318531f / 65536.0f);
  }
  const float norm = 1.0f / (0.35f + tot);
  for (int i = 0; i < NS; i++) {
    float v = 0.0f;
    const float u = (float)i * (6.28318531f / (float)NS);
    for (int b = 0; b < 16; b++) {
      if (amp[b] < 0.004f) continue;
      v += amp[b] * cfx_sinf16(u * (float)(b + 1) + ph[b]);
    }
    W[i] = v * norm;
  }
}

// Advance the sixteen phases: bin b turns at (b+1) times the base rate.
static inline void cfx_wavePhases(uint16_t *ph16, uint16_t dt) {
  for (int b = 0; b < 16; b++)
    ph16[b] = (uint16_t)(ph16[b] + (uint32_t)dt * (uint32_t)(9 + 6 * b));
}

static inline void cfx_waveShape(int mode, int i, int NS, const float *W, float T,
                                 float &x, float &y) {
  const float TWOPI = 6.28318531f;
  const float wl = W[i], wr = W[(i + NS / 4) % NS];
  const float ang0 = T * 0.2f;
  switch (mode) {
    default:
    case 0: {   // Circle
      float rad = 0.5f + 0.4f * (wl + wr) * 0.5f;
      const float ang = (float)i * (TWOPI / (float)(NS - 1)) + ang0;
      if (i < NS / 10) {
        float mix = (float)i / (NS * 0.1f);
        mix = 0.5f - 0.5f * cosf(mix * 3.1416f);
        const float rad2 = 0.5f + 0.4f * W[(i + NS - 1) % NS];
        rad = rad2 * (1.0f - mix) + rad * mix;
      }
      x = rad * cosf(ang); y = rad * sinf(ang);
      break; }
    case 1: {   // Spiral: the x-y oscilloscope that goes round in time
      const float rad = 0.53f + 0.43f * wr;
      const float ang = W[(i + 32) % NS] * 1.57f + T * 2.3f;
      x = rad * cosf(ang); y = rad * sinf(ang);
      break; }
    case 2: {   // Spiro: the same, scaled up (the caller draws it faint)
      const float rad = 1.1f * (0.53f + 0.43f * wr);
      const float ang = W[(i + 32) % NS] * 1.57f + T * 2.3f;
      x = rad * cosf(ang); y = rad * sinf(ang);
      break; }
    case 3: {   // Star (MilkDrop2077)
      float rad = 0.7f + 0.4f * (wl + wr) * 0.5f;
      const float ang = (float)i * (TWOPI / (float)(NS - 1)) + ang0;
      if ((float)i < (float)NS / rad) {
        float mix = (float)i / (NS * 0.1f);
        mix = 0.5f - 0.5f * cosf(mix * 3.1416f);
        const float rad2 = 0.5f + 0.4f * W[(i + NS - 1) % NS];
        rad = rad2 * (1.0f - mix) + rad * mix;
      }
      x = rad * cosf(ang); y = rad * sinf(ang);
      break; }
    case 4: {   // Flower (MilkDrop2077)
      float rad = 0.7f + 0.7f * (wl + wr) * 0.5f;
      const float ang = (float)i * (TWOPI / (float)(NS - 1)) + ang0;
      if ((float)i < (float)NS / rad) {
        float mix = (float)i / (NS * 0.1f);
        mix = 0.7f - 0.7f * cosf(mix * 3.1416f);
        const float rad2 = 0.7f + 0.7f * W[(i + NS - 1) % NS];
        rad = rad2 * (1.0f - mix) + rad * (mix * 2.0f) / 8.0f;
      }
      x = rad * cosf(ang * 3.1416f) / 1.5f;
      y = rad * sinf(ang - T / 3.0f) / 1.5f;
      break; }
    case 5: {   // Lasso (MilkDrop2077)
      float ang = 0.5f * (W[(i + 32) % NS] + W[(i + 56) % NS]) * 1.57f + T * 2.0f;
      if (fabsf(ang) < 0.001f) ang = (ang < 0.0f) ? -0.001f : 0.001f;
      float tt = T / ang;
      tt -= floorf(tt / 3.14159f) * 3.14159f;                  // keep tan sane
      x = (cosf(T) * 0.5f + cosf(ang * 2.0f + tanf(tt))) * 0.6f;
      y = (sinf(T) * 2.0f * sinf(ang * 3.14f) / 2.8f) * 0.6f;
      break; }
    case 6: {   // Triangle (CodAv)
      const float progress = (float)i / (float)NS;
      const float phi0 = (floorf(progress * 3.0f) + 0.5f) / 3.0f * 6.28f + ang0;
      const float angle = progress * 6.28f + ang0;
      float ed = cosf(angle - phi0);
      if (fabsf(ed) < 0.02f) ed = (ed < 0.0f) ? -0.02f : 0.02f;
      float radius = (0.7f + ed * (wl + wr) * 0.5f) / (2.0f * ed);
      if (radius > 2.0f) radius = 2.0f; else if (radius < -2.0f) radius = -2.0f;
      x = radius * cosf(angle); y = radius * sinf(angle);
      break; }
  }
  if (x >  1.9f) x =  1.9f; else if (x < -1.9f) x = -1.9f;
  if (y >  1.9f) y =  1.9f; else if (y < -1.9f) y = -1.9f;
}

// A point of MilkDrop's plane, charted onto the solid about a tumbled pole -
// azimuthal equidistant, `chart` radians of polar angle per unit - and looked
// up in a rev table. 0xFFFF where nothing is lit. M is world->object.
static inline uint16_t cfx_plotPole(float x, float y, float chart, const float M[3][3],
                                    const uint16_t *rev, int Bq) {
  const float r = sqrtf(x * x + y * y);
  float al = r * chart;
  if (al > 3.05f) al = 3.05f;
  const float ir = (r > 1e-6f) ? (1.0f / r) : 0.0f;
  const float sa = sinf(al), ca = cosf(al);
  const float dx = sa * x * ir, dy = sa * y * ir, dz = ca;
  const float cx = M[0][0]*dx + M[1][0]*dy + M[2][0]*dz;
  const float cy = M[0][1]*dx + M[1][1]*dy + M[2][1]*dz;
  const float cz = M[0][2]*dx + M[1][2]*dy + M[2][2]*dz;
  int f, a, b;
  cfx_face((int)(cx * 300.0f), (int)(cy * 300.0f), (int)(cz * 300.0f), f, a, b);
  int ai = ((a + 128) * Bq) >> 8, bi = ((b + 128) * Bq) >> 8;
  if (ai < 0) ai = 0; else if (ai >= Bq) ai = Bq - 1;
  if (bi < 0) bi = 0; else if (bi >= Bq) bi = Bq - 1;
  return rev[((size_t)f * Bq + bi) * Bq + ai];
}

// Build the [6][Bq][Bq] reverse table of compact indices for a cube net.
static inline void cfx_buildRev(uint16_t *rev, int cols, int rows, int B) {
  const int Bq = B;
  for (size_t k = 0; k < (size_t)6 * Bq * Bq; k++) rev[k] = 0xFFFF;
  for (int y = 0; y < rows; y++)
    for (int x = 0; x < cols; x++) {
      if (cfx_gap(x, y, B)) continue;
      float X, Y, Z; cfx_pos(x, y, cols, rows, B, true, X, Y, Z);
      int f, a, b; cfx_face(cfx_clamp8(X), cfx_clamp8(Y), cfx_clamp8(Z), f, a, b);
      int ai = ((a + 128) * Bq) >> 8, bi = ((b + 128) * Bq) >> 8;
      if (ai < 0) ai = 0; else if (ai >= Bq) ai = Bq - 1;
      if (bi < 0) bi = 0; else if (bi >= Bq) bi = Bq - 1;
      rev[((size_t)f * Bq + bi) * Bq + ai] = (uint16_t)cfx_cidx(x, y, cols, B, true);
    }
}

// Waveform selector for the edge ripple. 0 = off.
static inline uint8_t cfx_wave(uint8_t shape, uint8_t t) {
  switch (shape) {
    case 1: return sin8_t(t);                                                   // sine
    case 2: return (t < 128) ? (uint8_t)(t << 1) : (uint8_t)((uint8_t)(255 - t) << 1);
    case 3: return (t < 128) ? 0 : 255;                                         // square
    case 4: return t;                                                           // saw up
    case 5: return (uint8_t)(255 - t);                                          // saw down
    default: return 255;
  }
}

// ---------------------------------------------------------------------------
// The 3D surface lookup. Any pointer may be null. Runs once per segment, so
// floats are fine.
// ---------------------------------------------------------------------------
static void cfx_buildCube(int8_t *cx, int8_t *cy, int8_t *cz,
                          uint8_t *az, uint8_t *el,
                          int cols, int rows, bool cubeNet) {
  const int B = cubeNet ? (cols / 3) : 1;

  for (int y = 0; y < rows; y++) {
    for (int x = 0; x < cols; x++) {
      const size_t i = (size_t)y * cols + x;
      float X, Y, Z;
      cfx_pos(x, y, cols, rows, B, cubeNet, X, Y, Z);

      if (cx) cx[i] = cfx_clamp8(X);
      if (cy) cy[i] = cfx_clamp8(Y);
      if (cz) cz[i] = cfx_clamp8(Z);

      if (az) az[i] = (uint8_t)(int)(atan2f(Y, X) * (128.0f / 3.14159265f) + 256.5f);

      if (el) {
        if (cubeNet) {
          // project the surface point onto a sphere and take its latitude, so
          // the top face is a pole instead of one flat constant value
          const float len = sqrtf(X * X + Y * Y + Z * Z);
          float nz = (len > 0.001f) ? (Z / len) : 0.0f;
          if (nz < -1.0f) nz = -1.0f; else if (nz > 1.0f) nz = 1.0f;
          float t = (asinf(nz) + 0.6155f) / 2.1863f;      // 0..1 over the solid
          if (t < 0.0f) t = 0.0f; else if (t > 1.0f) t = 1.0f;
          el[i] = (uint8_t)(t * 255.0f);
        } else {
          float v = 255.0f - sqrtf(X * X + Y * Y) * 180.0f;
          if (v < 0.0f) v = 0.0f; else if (v > 255.0f) v = 255.0f;
          el[i] = (uint8_t)v;
        }
      }
    }
  }
}


// ---------------------------------------------------------------------------
// Shared pixel/colour helper (originally introduced alongside Question Block,
// reused widely since - promoted here so every
// effect file can reach it without depending on another effect's file).
// ---------------------------------------------------------------------------
static inline uint32_t mq_scale(uint32_t c, uint8_t s) {
  return RGBW32(scale8((uint8_t)(c >> 16), s), scale8((uint8_t)(c >> 8), s),
                scale8((uint8_t)c, s), 0);
}

// ---------------------------------------------------------------------------
// Shared surface toolkit: wall "band" unwrap, face forward/inverse projection,
// direction lookup table, and pixel->cell mapping. Used by Question Block,
// Tron, Split GEQ, Matrix Rain and Breakout.
// ---------------------------------------------------------------------------
// ---------------------------------------------------------------------------
// Wall band: the four side faces are a seamless 4B x B cylinder. bu[] is the
// column around the ring, bv[] the row down from the top rim, and 255 in bu[]
// marks a pixel that is on the top face or in a gap. Derived from the same
// fold logic as cfx_pos, so the ring closes with no discontinuity at any of
// the four vertical corners.
// ---------------------------------------------------------------------------
static void cfx_buildBand(uint8_t *bu, uint8_t *bv, int cols, int rows, bool cubeNet, int B) {
  for (int y = 0; y < rows; y++) {
    for (int x = 0; x < cols; x++) {
      const size_t i = (size_t)y * cols + x;
      if (!cubeNet) { bu[i] = (uint8_t)x; bv[i] = (uint8_t)y; continue; }
      const int bx = x / B, by = y / B, lx = x % B, ly = y % B;
      if (bx == 1 && by == 1) { bu[i] = 255; bv[i] = 0; continue; }   // top face
      if (bx != 1 && by != 1) { bu[i] = 255; bv[i] = 0; continue; }   // gap corner, or the bottom: not a wall
      if      (by == 0) { bu[i] = (uint8_t)(lx);                 bv[i] = (uint8_t)(B - 1 - ly); }
      else if (bx == 2) { bu[i] = (uint8_t)(B + ly);             bv[i] = (uint8_t)(lx);         }
      else if (by == 2) { bu[i] = (uint8_t)(2 * B + B - 1 - lx); bv[i] = (uint8_t)(ly);         }
      else              { bu[i] = (uint8_t)(3 * B + B - 1 - ly); bv[i] = (uint8_t)(B - 1 - lx); }
    }
  }
}

static void lf_fwd(int f, float a, float b, float &X, float &Y, float &Z) {
  switch (f) {
    case 0:  X =  a; Y = -b; Z =  1.0f; break;   // TOP
    case 1:  X =  a; Y =  1.0f; Z =  b; break;   // NORTH
    case 2:  X =  a; Y = -1.0f; Z = -b; break;   // SOUTH
    case 3:  X = -1.0f; Y = -b; Z =  a; break;   // WEST
    default: X =  1.0f; Y = -b; Z = -a; break;   // EAST
  }
}
static int lf_inv(float X, float Y, float Z, float &a, float &b) {
  const float ax = fabsf(X), ay = fabsf(Y), az = fabsf(Z);
  if (az >= ax && az >= ay) {
    if (Z <= 0.0f) return -1;                    // the open bottom: no cell there
    a = X / az; b = -Y / az; return 0;
  }
  if (ay >= ax) {
    if (Y > 0.0f) { a = X / ay; b =  Z / ay; return 1; }
    a = X / ay; b = -Z / ay; return 2;
  }
  if (X < 0.0f) { a =  Z / ax; b = -Y / ax; return 3; }
  a = -Z / ax; b = -Y / ax; return 4;
}


// Face normals and tangent bases, matching lf_fwd exactly.
static const int8_t LF_N[5][3] = {{0,0,1},{0,1,0},{0,-1,0},{-1,0,0},{1,0,0}};
static const int8_t LF_U[5][3] = {{1,0,0},{1,0,0},{1,0,0},{0,0,1},{0,0,-1}};
static const int8_t LF_V[5][3] = {{0,-1,0},{0,0,1},{0,0,-1},{0,-1,0},{0,-1,0}};

// ---------------------------------------------------------------------------
// Directional transition table over all five faces: 320 cells x 4 headings,
// each entry packing the next cell and the heading you arrive with.
//
// The heading matters. Walk off the top face heading east and you are then
// heading DOWN the east wall - your direction rotated 90 degrees about the
// edge. That works out to the old face's outward normal, negated, expressed in
// the new face's basis. Without it a cycle would cross a fold and carry on in
// a direction that no longer means anything.
//
// 0xFFFF marks a step onto the unwired bottom, which behaves as a wall.
// ---------------------------------------------------------------------------
static void cfx_buildDirLut(uint16_t *lut) {
  for (int f = 0; f < 5; f++)
    for (int j = 0; j < 8; j++)
      for (int i2 = 0; i2 < 8; i2++) {
        const int c = f * 64 + j * 8 + i2;
        const float a = (i2 + 0.5f) / 4.0f - 1.0f, b = (j + 0.5f) / 4.0f - 1.0f;
        for (int d = 0; d < 4; d++) {
          const float da = (d == 0) ? 0.25f : ((d == 2) ? -0.25f : 0.0f);
          const float db = (d == 1) ? 0.25f : ((d == 3) ? -0.25f : 0.0f);
          float X, Y, Z, na, nb;
          lf_fwd(f, a + da, b + db, X, Y, Z);
          const float m = fmaxf(fabsf(X), fmaxf(fabsf(Y), fabsf(Z)));
          const int nf = lf_inv(X / m, Y / m, Z / m, na, nb);
          if (nf < 0) { lut[c * 4 + d] = 0xFFFF; continue; }
          int ni = (int)((na + 1.0f) * 4.0f); if (ni < 0) ni = 0; if (ni > 7) ni = 7;
          int nj = (int)((nb + 1.0f) * 4.0f); if (nj < 0) nj = 0; if (nj > 7) nj = 7;
          const int nc = nf * 64 + nj * 8 + ni;
          if (nc == c) { lut[c * 4 + d] = 0xFFFF; continue; }
          int nd = d;
          if (nf != f) {                       // rotate the heading over the fold
            const float tx = -(float)LF_N[f][0], ty = -(float)LF_N[f][1], tz = -(float)LF_N[f][2];
            const float du = tx*LF_U[nf][0] + ty*LF_U[nf][1] + tz*LF_U[nf][2];
            const float dv = tx*LF_V[nf][0] + ty*LF_V[nf][1] + tz*LF_V[nf][2];
            if (fabsf(du) >= fabsf(dv)) nd = (du > 0.0f) ? 0 : 2;
            else                        nd = (dv > 0.0f) ? 1 : 3;
          }
          lut[c * 4 + d] = (uint16_t)(nc | (nd << 12));
        }
      }
}

// Pixel -> surface cell, the five faces the cycles ride. 0xFFFF for gaps and
// for the six-face bottom, which the transition table treats as a wall.
static void cfx_buildCells(uint16_t *cellOf, int cols, int rows, bool cube, int B) {
  for (int y = 0; y < rows; y++)
    for (int x = 0; x < cols; x++) {
      const size_t i = (size_t)y * cols + x;
      if (!cube) { cellOf[i] = (uint16_t)(((y * 8) / rows) * 8 + (x * 8) / cols); continue; }
      const int bx = x / B, by = y / B;
      if ((bx != 1 && by != 1) || B < 8) { cellOf[i] = 0xFFFF; continue; }
      const int f = (bx == 1 && by == 1) ? 0 : (by == 0 ? 1 : (by == 2 ? 2 : (bx == 0 ? 3 : 4)));
      cellOf[i] = (uint16_t)(f * 64 + (((y % B) * 8) / B) * 8 + (((x % B) * 8) / B));
    }
}
