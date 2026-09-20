#include "wled.h"
#include "cube_fx_common.h"
#include "cube_fx_imu.h"
#include "cube_fx_bank.h"

// ===========================================================================
// 22. ACE GYRO SAND
// ===========================================================================
// A glass box of sand. Grains are individual particles living in the cube's
// VOLUME, falling along real gravity, piling up on whichever face is currently
// the floor, and drawn on whichever wall they are nearest - so you are looking
// through the glass at the pile inside.
//
// ---------------------------------------------------------------------------
// WHY PARTICLES AND NOT A HEIGHT FIELD
// ---------------------------------------------------------------------------
// This used to be a 16x16 field of column depths. A continuum like that can
// draw a dune beautifully and can never draw a GRAIN: there is nothing in the
// model that is a single piece of sand, so nothing can be thrown, and a beat
// could only ever make the surface relax faster. Worse, on a cube only the
// field's edge columns face outward, so four fifths of the simulation was
// invisible and the walls each showed one 16-wide slice.
//
// Particles cost about the same memory (the per-pixel coordinate LUTs are
// gone, which pays for most of the grains) and give all three behaviours the
// continuum could not: an hourglass drain, a burst, and a pile that is built
// out of things rather than described by a number.
//
// ---------------------------------------------------------------------------
// HOURGLASS
// ---------------------------------------------------------------------------
// The floor is whichever face gravity points at, chosen with hysteresis so it
// does not flicker when the cube is held near an edge. When that choice
// changes - you turned the cube over - EVERY settled grain is released at
// once. They then fall on their own, which is the hourglass: not an animation
// of a flip, just sand that no longer has a floor under it.
//
// ---------------------------------------------------------------------------
// PILING, AND WHY GRAINS ROLL
// ---------------------------------------------------------------------------
// A coarse 8x8 height grid in the plane perpendicular to gravity says how deep
// the pile is in each column. A falling grain settles when it reaches that
// depth - but first it looks at its neighbours, and if one is meaningfully
// lower it is pushed toward it instead and keeps falling.
//
// That one rule is what gives the pile a slope. Without it grains stack into
// vertical towers exactly where they happen to land, because nothing else in
// the model has any opinion about the shape of a heap. It is also far cheaper
// than the alternative - relaxing the surface afterwards - and it cannot
// desynchronise the grid from the grains, because the grain moves first and
// the grid only ever records where one actually stopped.
//
// ---------------------------------------------------------------------------
// MUSIC
// ---------------------------------------------------------------------------
//   beat        releases a scoop of grains from the pile surface and throws
//               them up: the firework. Burst size scales with how hard it hit
//   spectral    bass, mid and treble each push along a different axis, so a
//               busy mix shoves the sand in several directions at once and it
//               ends up looking like a snow globe - which is the point
//   shake       the whole pile lifts off
//
// WITH NO SENSOR gravity is straight down the cube's own -Z and everything
// else behaves normally.
// ===========================================================================

#define SD_HG      8                  // height grid is SD_HG x SD_HG columns
#define SD_Q       4                  // position fixed point: 1 cube unit = 16
#define SD_LIM     (127 << SD_Q)      // wall, in Q4 cube units

#ifndef SD_MAXGRAIN
  #define SD_MAXGRAIN 640
#endif
#ifndef SD_ROLL_TOL
  #define SD_ROLL_TOL 6               // neighbour must be this much lower to roll into
#endif
#ifndef SD_VCAP
  #define SD_VCAP 110                 // terminal velocity, Q4 per 23 ms
#endif
#ifndef SD_FILL_TARGET
  #define SD_FILL_TARGET 120          // pile levels off near this height, of 254
#endif

struct SdGrain {
  int16_t p[3];                       // position, Q4 cube units, +/-SD_LIM
  int8_t  v[3];                       // velocity, Q4 per 23 ms
  uint8_t set;                        // 1 = settled into the pile, not simulated
};

// st[] layout
#define SD_ST_MODE  0
#define SD_ST_AXIS  1                 // gravity axis code: idx*2 + (sign<0)
#define SD_ST_CLK   2                 // +3
#define SD_ST_SEED  4
#define SD_ST_LEN   8

static inline int sdClampV(int v) {
  return (v > SD_VCAP) ? SD_VCAP : ((v < -SD_VCAP) ? -SD_VCAP : v);
}

// Height above the floor, in cube units, for a position along the gravity
// axis. gSgn is the direction gravity points, so the floor sits at +127*gSgn.
static inline int sdHeight(int pAxisQ, int gSgn) {
  return 127 - gSgn * (pAxisQ >> SD_Q);
}

static inline int sdCol(int pQ) {
  int c = ((pQ >> SD_Q) + 128) >> 5;             // -128..127 -> 0..7
  return (c < 0) ? 0 : ((c > SD_HG - 1) ? SD_HG - 1 : c);
}

static FX_RET mode_gyro_sand() {
  if (!strip.isMatrix || !SEGMENT.is2D()) { SEGMENT.fill(SEGCOLOR(0)); FX_DONE; }
  const int cols = SEG_W, rows = SEG_H;
  if (cols < 6 || rows < 6) { SEGMENT.fill(SEGCOLOR(0)); FX_DONE; }

  const bool cube = cfx_isCube(cols, rows);
  const int  B    = cube ? (cols / 3) : 1;

  // Grain count follows the face area, so a big net gets a dense box and a
  // small one does not drown in particles it cannot resolve. Fixed by geometry
  // alone - a slider that resized the buffer would reallocate mid-pour.
  int NP = cube ? (B * B * 2) : ((cols * rows) / 3);
  if (NP > SD_MAXGRAIN) NP = SD_MAXGRAIN;
  if (NP < 64) NP = 64;

  const size_t need = (size_t)NP * sizeof(SdGrain) + SD_HG * SD_HG + SD_ST_LEN;
  if (!SEGENV.allocateData(need)) { SEGMENT.fill(SEGCOLOR(0)); FX_DONE; }

  SdGrain *g  = (SdGrain *)SEGENV.data;          // offset 0: malloc alignment holds
  uint8_t *H  = (uint8_t *)(g + NP);
  uint8_t *st = H + SD_HG * SD_HG;

  const CfxImuState &imu = cfx_imu();
  // Gravity - where things fall. No sensor means straight down the cube's -Z.
  const int G[3] = { imu.valid ? (int)imu.gx : 0,
                     imu.valid ? (int)imu.gy : 0,
                     imu.valid ? (int)imu.gz : -127 };

  const uint8_t want = (uint8_t)(cube ? 1 : 2);
  const bool fresh = (SEGENV.call == 0 || st[SD_ST_MODE] != want);
  if (fresh) {
    for (int k = 0; k < SD_ST_LEN; k++) st[k] = 0;
    st[SD_ST_MODE] = want;
    st[SD_ST_AXIS] = 5;                          // -Z: idx 2, negative
    for (int k = 0; k < SD_HG * SD_HG; k++) H[k] = 0;
    for (int i = 0; i < NP; i++) {
      g[i].p[0] = (int16_t)((int)hw_random16(2 * SD_LIM) - SD_LIM);
      g[i].p[1] = (int16_t)((int)hw_random16(2 * SD_LIM) - SD_LIM);
      g[i].p[2] = (int16_t)((int)hw_random16(2 * SD_LIM) - SD_LIM);
      g[i].v[0] = g[i].v[1] = g[i].v[2] = 0;
      g[i].set = 0;
    }
  }

  int dt = (int)fx_dt8(st + SD_ST_CLK);
  if (dt > 60) dt = 60;

  // --- which way is down, with hysteresis ----------------------------------
  int hIdx = st[SD_ST_AXIS] >> 1;
  int gSgn = (st[SD_ST_AXIS] & 1) ? -1 : 1;
  {
    const int cur = (G[hIdx] < 0) ? -G[hIdx] : G[hIdx];
    for (int j = 0; j < 3; j++) {
      const int m = (G[j] < 0) ? -G[j] : G[j];
      if (j != hIdx && m > cur + 26) hIdx = j;    // deadband, or it chatters on an edge
    }
    if (G[hIdx] > 20) gSgn = 1; else if (G[hIdx] < -20) gSgn = -1;
  }
  const uint8_t axisCode = (uint8_t)(hIdx * 2 + ((gSgn < 0) ? 1 : 0));
  const bool flipped = (axisCode != st[SD_ST_AXIS]);
  st[SD_ST_AXIS] = axisCode;

  const int uIdx = (hIdx == 0) ? 1 : 0;
  const int vIdx = (hIdx == 2) ? 1 : 2;

  // The hourglass. Nothing animates the turn - the floor simply stops being
  // where it was, every grain is let go at once, and gravity does the rest.
  if (flipped) {
    for (int i = 0; i < NP; i++) g[i].set = 0;
    for (int k = 0; k < SD_HG * SD_HG; k++) H[k] = 0;
  }

  // --- audio ---------------------------------------------------------------
  um_data_t     *um  = cfx_getAudioData();
  const uint8_t *fft = (uint8_t *)um->u_data[2];
  const float    vol = *(float *)um->u_data[0];
  int bass, mid, treb;
  cfx_bands(fft, bass, mid, treb);
  const CfxTempoState &tempo = cfx_tempo(um);

  uint8_t knock = tempo.hit;
  if (imu.shake > knock) knock = imu.shake;

  // --- the burst -----------------------------------------------------------
  // A beat scoops grains off the pile and throws them. They are taken from the
  // TOP of the pile (highest columns first is too expensive to sort, so a
  // random column and a settled grain near its surface is close enough) and
  // given real upward velocity, which is what makes it read as a firework
  // rather than as the pile brightening.
  const int burstMax = 4 + ((int)SEGMENT.custom2 * NP) / 900;
  if (knock > 24 && SEGMENT.check1) {
    int launch = (burstMax * (int)knock) / 255;
    if (imu.shake > 120) launch = burstMax;                 // shaken: everything goes
    const int up = 55 + ((int)knock >> 1);

    // Spectral push: each band drives a different axis, so a dense mix throws
    // sand several ways at once instead of everything going straight up.
    const int pu = SEGMENT.check2 ? ((bass - treb) >> 2) : 0;
    const int pv = SEGMENT.check2 ? ((mid  - treb) >> 2) : 0;

    for (int k = 0; k < launch; k++) {
      const int i = (int)hw_random16((uint16_t)NP);
      if (!g[i].set) continue;
      g[i].set = 0;
      g[i].v[hIdx] = (int8_t)sdClampV(-gSgn * (up + (int)hw_random8() / 6));
      g[i].v[uIdx] = (int8_t)sdClampV(pu + (int)hw_random8() / 8 - 16);
      g[i].v[vIdx] = (int8_t)sdClampV(pv + (int)hw_random8() / 8 - 16);
      const int c = sdCol(g[i].p[uIdx]) + sdCol(g[i].p[vIdx]) * SD_HG;
      if (H[c] > 3) H[c] -= 3;                              // it left a hole
    }
  }

  // --- fall, roll, settle --------------------------------------------------
  const int accel  = 1 + ((int)SEGMENT.speed * 6) / 255;    // hourglass pour rate
  const int bounce = (int)cfx_c3full(SEGMENT.custom3) >> 3;             // 0..31, wall restitution
  const int active = 32 + ((int)SEGMENT.custom1 * (NP - 32)) / 255;

  // How much one settled grain raises its column, chosen so the pile levels off
  // at ~SD_FILL_TARGET of the 254-unit depth once the grains are down, not so it
  // slams into the ceiling. Deriving it from `active` (roughly the settled
  // count at rest) rather than a constant is what makes that height hold: a
  // column receives active/SD_HG^2 grains on average, so deposit *
  // (active/SD_HG^2) ~= SD_FILL_TARGET by construction, independent of how many
  // grains the Fill slider is running. The old fixed ~80 filled a column in
  // three grains, saturated every column in a second, and left later grains
  // settling on the ceiling. Floored at 2 so a very dense field still builds
  // visible relief instead of a flat layer lost to integer truncation.
  int deposit = ((int)SD_HG * SD_HG * SD_FILL_TARGET) / (active < 1 ? 1 : active);
  if (deposit < 2) deposit = 2;

  for (int i = 0; i < active; i++) {
    SdGrain &q = g[i];
    if (q.set) continue;

    q.v[hIdx] = (int8_t)sdClampV((int)q.v[hIdx] + (gSgn * accel * dt) / 23);

    for (int a = 0; a < 3; a++) {
      int np = (int)q.p[a] + ((int)q.v[a] * dt) / 23;
      if (np >  SD_LIM) { np =  SD_LIM; q.v[a] = (int8_t)(-(int)q.v[a] * bounce / 32); }
      if (np < -SD_LIM) { np = -SD_LIM; q.v[a] = (int8_t)(-(int)q.v[a] * bounce / 32); }
      q.p[a] = (int16_t)np;
    }

    const int cu = sdCol(q.p[uIdx]), cv = sdCol(q.p[vIdx]);
    const int ci = cv * SD_HG + cu;
    const int ha = sdHeight(q.p[hIdx], gSgn);

    if (ha > (int)H[ci]) continue;                          // still in the air

    // Reached the pile. Look downhill first: if a neighbour is meaningfully
    // lower, roll toward it rather than settling here. This is the only thing
    // in the model that gives the heap a slope.
    int bestD = -1, bestDrop = SD_ROLL_TOL;
    for (int d = 0; d < 4; d++) {
      const int nu = cu + ((d == 0) ? 1 : (d == 1 ? -1 : 0));
      const int nv = cv + ((d == 2) ? 1 : (d == 3 ? -1 : 0));
      if (nu < 0 || nu >= SD_HG || nv < 0 || nv >= SD_HG) continue;
      const int drop = (int)H[ci] - (int)H[nv * SD_HG + nu];
      if (drop > bestDrop) { bestDrop = drop; bestD = d; }
    }

    if (bestD >= 0) {                                       // roll
      const int ax = (bestD < 2) ? uIdx : vIdx;
      const int dir = (bestD == 0 || bestD == 2) ? 1 : -1;
      q.v[ax] = (int8_t)sdClampV((int)q.v[ax] + dir * 14);
      q.v[hIdx] = (int8_t)((int)q.v[hIdx] / 2);             // shed the fall, keep sliding
      continue;
    }

    // Settle: park it exactly on the surface and stop simulating it.
    q.p[hIdx] = (int16_t)((gSgn * (127 - (int)H[ci])) << SD_Q);
    q.v[0] = q.v[1] = q.v[2] = 0;
    q.set = 1;
    const int nh = (int)H[ci] + deposit;
    H[ci] = (uint8_t)((nh > 254) ? 254 : nh);
  }

  // --- render ---------------------------------------------------------------
  // Each grain is drawn on the face it is NEAREST, dimmed by how far away that
  // face is - so the box has depth and the pile reads as being inside it. The
  // open bottom is never a candidate, so grains resting on a floor low in the
  // box appear low on the walls instead of vanishing.
  const uint8_t drive = cfx_drive(vol, 1.0f, 120 + (SEGMENT.intensity >> 1));
  SEGMENT.fill(SEGCOLOR(0));

  for (int i = 0; i < active; i++) {
    const SdGrain &q = g[i];
    const int px = q.p[0] >> SD_Q, py = q.p[1] >> SD_Q, pz = q.p[2] >> SD_Q;

    int x, y, dist;
    if (!cube) {
      x = ((px + 128) * cols) >> 8;
      y = ((py + 128) * rows) >> 8;
      dist = 0;
    } else {
      const int dLid = 127 - pz, dN = 127 - py, dS = 127 + py,
                dW = 127 + px, dE = 127 - px;
      int face = 0; dist = dLid;
      if (dN < dist) { dist = dN; face = 1; }
      if (dS < dist) { dist = dS; face = 2; }
      if (dW < dist) { dist = dW; face = 3; }
      if (dE < dist) { dist = dE; face = 4; }

      int a, b, bx, by;
      switch (face) {                                       // inverse of cfx_pos
        case 1:  a =  px; b =  pz; bx = 1; by = 0; break;   // NORTH
        case 2:  a =  px; b = -pz; bx = 1; by = 2; break;   // SOUTH
        case 3:  a =  pz; b = -py; bx = 0; by = 1; break;   // WEST
        case 4:  a = -pz; b = -py; bx = 2; by = 1; break;   // EAST
        default: a =  px; b = -py; bx = 1; by = 1; break;   // TOP
      }
      int lx = ((a + 128) * B) >> 8, ly = ((b + 128) * B) >> 8;
      if (lx < 0) lx = 0; else if (lx > B - 1) lx = B - 1;
      if (ly < 0) ly = 0; else if (ly > B - 1) ly = B - 1;
      x = bx * B + lx;
      y = by * B + ly;
    }
    if (x < 0 || x >= cols || y < 0 || y >= rows) continue;

    // Airborne grains are brighter and whiter than settled ones, so a burst
    // reads instantly against the pile it came out of.
    const int speed = ((int)q.v[0] < 0 ? -q.v[0] : q.v[0])
                    + ((int)q.v[1] < 0 ? -q.v[1] : q.v[1])
                    + ((int)q.v[2] < 0 ? -q.v[2] : q.v[2]);
    int lum = 255 - (dist * 170) / 254;
    if (!q.set) lum = (int)qadd8((uint8_t)lum, (uint8_t)(speed >> 1));
    if (lum > 255) lum = 255;

    const int ha = sdHeight(q.p[hIdx], gSgn);
    uint8_t pi = (uint8_t)(30 + (ha * 170) / 254 + (q.set ? 0 : 40));
    uint32_t c = SEGMENT.color_from_palette(pi, false, false, 0);
    if (!q.set && speed > 90)
      c = color_add(c, mq_scale(RGBW32(255, 255, 255, 0), (uint8_t)((speed - 90) >> 1)), true);

    SEGMENT.setPixelColorXY(x, y, mq_scale(c, scale8((uint8_t)lum, drive)));
  }
  FX_DONE;
}

static const char _data_FX_MODE_GYRO_SAND[] PROGMEM =
  "Ace Gyro Sand@Pour rate,Glow,Fill,Burst size,Bounce,Beat bursts,Spectral push,Flat mode;;!;2f;sx=120,ix=150,c1=200,c2=120,c3=13,o1=1,o2=1";



// ---------------------------------------------------------------------------
// Registration - joins the effect bank, which decides whether this effect
// claims one of the device's limited effect slots. See cube_fx_bank.h.
// ---------------------------------------------------------------------------
static CfxBankReg cube_fx_22_gyro_sand_reg(&mode_gyro_sand, _data_FX_MODE_GYRO_SAND);
