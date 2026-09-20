#include "wled.h"
#include <string.h>
#include "cube_fx_common.h"
#include "cube_fx_bank.h"

// ===========================================================================
// Ace 3-D Kaleidoscope - a spherical mirror group, cut by an arrangement
// ===========================================================================
// Companion to Ace 3-D Poincare, and the other half of the same idea. That one
// folds the cube into a HYPERBOLIC triangle group; this one folds it into a
// SPHERICAL one, which is the case where the group is finite and the picture
// closes up on itself instead of running away into a rim.
//
// Every pixel becomes a direction, that direction is reflected into one
// fundamental domain, and whatever is drawn in the domain is mirrored back out
// over the whole solid. Seamless for the same reason as everything else in
// this folder - the picture is a function of the surface point, so the folds
// of the net never enter into it - but with a stronger property on top: the
// symmetry is EXACT and finite, so the cube carries 4 to 120 identical mirror
// images of one small tile of pattern.
//
// Crucially the fold has nothing to do with the cube's own shape. Octahedral
// symmetry lines up with the faces; icosahedral cannot, and deliberately cuts
// across them.
//
// ---------------------------------------------------------------------------
// FOLD, THEN FIELD - AND THE ORDER IS THE WHOLE TRICK
// ---------------------------------------------------------------------------
// The field is an ARRANGEMENT of circles: a handful of planes, each splitting
// the sphere in two, so a point is described by which side of each one it
// falls on. That bitmask is the cell, and each cell is flat-shaded from its own
// id, so the picture is hard-edged rather than a gradient field. Eight planes
// through the origin would cut the sphere into n(n-1)+2 = 58 cells; these are
// offset (see below) so the count is lower and depends on where they sit, but
// the character is the same - crisp regions meeting along circular arcs.
//
// The arrangement is evaluated AFTER the fold, never before. Evaluated before,
// it is just a pattern of cells and the mirrors are invisible; evaluated
// after, every cell is reproduced exactly in all 48 or 120 copies of the
// domain and the mirror lines fall where cells meet their own reflections.
// That is the difference between two patterns sharing a surface and a
// kaleidoscope.
//
// ---------------------------------------------------------------------------
// WHY THE PLANES ARE OFFSET, WHICH IS NOT WHAT I FIRST BUILT
// ---------------------------------------------------------------------------
// Planes through the ORIGIN cut great circles, and a great circle almost never
// touches the fundamental domain: the octahedral domain is one forty-eighth of
// the sphere, a triangle about 40 degrees on its longest side, and a randomly
// oriented great circle misses it far more often than it hits. Folded first,
// most of the arrangement therefore evaluates to a constant and the cube comes
// out flat-shaded in one colour.
//
// So the planes carry an offset - dot(n, g) > c rather than > 0, which cuts a
// small circle instead of a great one - and the offsets are anchored to the
// domain: kd_load() measures where the domain actually sits by folding a grid
// of directions and averaging, plus how far it spreads, and every cut is
// placed at that centroid plus a drifting fraction of that spread. Then a cut
// always crosses the domain, wherever the symmetry has put it.
//
// ---------------------------------------------------------------------------
// TWO CLOCKS
// ---------------------------------------------------------------------------
// The whole direction is rotated before folding, about two axes at different
// rates, so the kaleidoscope tumbles - and separately the plane offsets drift,
// so cells grow and merge and split inside it. Structure slow, field faster.
// Both are continuous and neither needs to wrap: a rotation is a rotation, and
// the arrangement has no period to respect.
// ===========================================================================

#define KD_NSYM     32
#define KD_MAXMIR   16          // Dn at n = 16; icosahedral needs 15
#define KD_MAXCUT   12
#define KD_NROOT     4          // two zeros and two poles
#define KD_PASSES    4          // measured worst case is 2 sweeps
#define KD_PHI      1.61803399f

struct KdState {
  uint8_t  mode;
  uint8_t  clk[2];
  uint8_t  sym;                 // which row of the symmetry table is loaded
  uint8_t  surge;
  uint16_t spinA, spinB;        // the two rotation clocks
  uint16_t drift;               // palette rotation
  uint16_t cutPh[KD_MAXCUT];    // each cut's own offset phase
  uint16_t rootPh[KD_NROOT];    // where the zeros and poles have drifted to
  // --- derived from `sym` --------------------------------------------------
  uint8_t  nm;                  // how many mirrors
  float    mir[KD_MAXMIR][3];
  float    cx, cy, cz;          // centroid direction of the fundamental domain
  float    t1[3], t2[3];        // a tangent frame there - the phase field's chart
  float    spread, invSpread;   // how far the domain reaches from that centroid
  float    cut[KD_MAXCUT][3];   // cut plane normals, fixed per symmetry
};

// Fixed cut directions - deliberately NOT symmetric with anything, so the
// arrangement does not accidentally line up with the mirrors and collapse.
static const float KD_CUTDIR[KD_MAXCUT][3] = {
  {  0.5774f,  0.5774f,  0.5774f }, { -0.7071f,  0.7071f,  0.0000f },
  {  0.2673f, -0.5345f,  0.8018f }, {  0.8944f,  0.0000f, -0.4472f },
  { -0.3015f, -0.9045f,  0.3015f }, {  0.4082f,  0.4082f, -0.8165f },
  { -0.8571f,  0.2857f,  0.4286f }, {  0.0000f, -0.6402f, -0.7682f },
  {  0.6667f, -0.3333f,  0.6667f }, { -0.4264f,  0.6396f, -0.6396f },
  {  0.1961f,  0.9806f,  0.0000f }, { -0.5883f, -0.1961f, -0.7845f },
};

// Reflect v in the plane with unit normal m, but only if it is on the far side.
static inline bool kd_bounce(float &x, float &y, float &z, const float *m) {
  const float d = x * m[0] + y * m[1] + z * m[2];
  if (d >= 0.0f) return false;
  const float t = 2.0f * d;
  x -= t * m[0]; y -= t * m[1]; z -= t * m[2];
  return true;
}

// Reduce a direction into the fundamental domain: reflect in any mirror it is
// behind, repeat until nothing moves. Terminates for any finite reflection
// group; measured, it settles in two or three sweeps.
static inline void kd_fold(const KdState *s, float &x, float &y, float &z) {
  for (int pass = 0; pass < KD_PASSES; pass++) {
    bool moved = false;
    for (int j = 0; j < s->nm; j++) moved |= kd_bounce(x, y, z, s->mir[j]);
    if (!moved) break;
  }
}

static void kd_addMir(KdState *s, float x, float y, float z) {
  if (s->nm >= KD_MAXMIR) return;
  const float L = sqrtf(x * x + y * y + z * z);
  if (L < 1e-6f) return;
  s->mir[s->nm][0] = x / L; s->mir[s->nm][1] = y / L; s->mir[s->nm][2] = z / L;
  s->nm++;
}

// The symmetry table, as a function rather than a data table because the
// dihedral families are generated:
//   0..13   Dnh, n = 2..15   - n meridian mirrors plus the equator
//   14..28  Dn,  n = 2..16   - meridians only, so top and bottom differ
//   29      tetrahedral (2,3,3), 6 mirrors, 24 copies
//   30      octahedral  (2,3,4), 9 mirrors, 48 copies - lines up with the cube
//   31      icosahedral (2,3,5), 15 mirrors, 120 copies - deliberately cannot
static void kd_load(KdState *s, uint8_t idx) {
  s->sym = idx;
  s->nm  = 0;

  if (idx <= 28) {
    const bool equator = (idx <= 13);
    const int  n = equator ? (idx + 2) : (idx - 14 + 2);
    for (int k = 0; k < n && s->nm < KD_MAXMIR; k++) {
      const float a = (float)k * 3.14159265f / (float)n;
      kd_addMir(s, -sinf(a), cosf(a), 0.0f);
    }
    if (equator) kd_addMir(s, 0.0f, 0.0f, 1.0f);
  } else if (idx == 29 || idx == 30) {
    if (idx == 30) {                       // octahedral adds the three axes
      kd_addMir(s, 1.0f, 0.0f, 0.0f);
      kd_addMir(s, 0.0f, 1.0f, 0.0f);
      kd_addMir(s, 0.0f, 0.0f, 1.0f);
    }
    kd_addMir(s, 1.0f, -1.0f, 0.0f);  kd_addMir(s, 1.0f, 1.0f, 0.0f);
    kd_addMir(s, 0.0f, 1.0f, -1.0f);  kd_addMir(s, 0.0f, 1.0f, 1.0f);
    kd_addMir(s, 1.0f, 0.0f, -1.0f);  kd_addMir(s, 1.0f, 0.0f, 1.0f);
  } else {
    // The 15 two-fold axes of the icosahedron. |(1, phi, 1/phi)| is exactly 2,
    // which is a good check that the golden ratio went in the right places.
    const float P = KD_PHI, Q = KD_PHI - 1.0f;   // 1/phi == phi - 1
    kd_addMir(s, 1.0f, 0.0f, 0.0f);
    kd_addMir(s, 0.0f, 1.0f, 0.0f);
    kd_addMir(s, 0.0f, 0.0f, 1.0f);
    for (int a = 0; a < 2; a++)
      for (int b = 0; b < 2; b++) {
        const float sa = a ? -1.0f : 1.0f, sb = b ? -1.0f : 1.0f;
        kd_addMir(s, 1.0f, sa * P, sb * Q);
        kd_addMir(s, sa * P, sb * Q, 1.0f);
        kd_addMir(s, sb * Q, 1.0f, sa * P);
      }
  }

  // ORIENTATION IS NOT COSMETIC. A fundamental-domain reduction terminates
  // only if every normal is a positive root of ONE chamber - that is, if there
  // exists a region where all the dot products are positive at once. Signs
  // chosen plane by plane happen to satisfy that for the dihedral and
  // octahedral sets and do NOT satisfy it for the icosahedral one: measured,
  // zero percent of directions ever landed in a domain and every pixel burned
  // the entire pass budget while the reflections cycled.
  //
  // Pointing every normal at one generic direction fixes it for any group. The
  // chamber containing that direction becomes the domain, and all five
  // families then reduce in at most two sweeps, with the domains coming out at
  // 1/24, 1/48 and 1/120 of the sphere as the group orders require.
  { const float gx = 0.2374f, gy = 0.4451f, gz = 0.8632f;
    for (int j = 0; j < s->nm; j++)
      if (s->mir[j][0] * gx + s->mir[j][1] * gy + s->mir[j][2] * gz < 0.0f) {
        s->mir[j][0] = -s->mir[j][0];
        s->mir[j][1] = -s->mir[j][1];
        s->mir[j][2] = -s->mir[j][2];
      }
  }

  // Where the fundamental domain actually sits, and how far it reaches. Both
  // are measured by folding a grid of directions, because deriving them per
  // group is a page of case analysis for a number that only has to be roughly
  // right - it is anchoring the cuts, not defining the picture.
  float ax = 0.0f, ay = 0.0f, az = 0.0f;
  int   cnt = 0;
  for (int i = 0; i < 12; i++)
    for (int j = 0; j < 24; j++) {
      const float th = (float)(i + 0.5f) * 3.14159265f / 12.0f;
      const float ph = (float)j * 6.28318531f / 24.0f;
      float x = sinf(th) * cosf(ph), y = sinf(th) * sinf(ph), z = cosf(th);
      kd_fold(s, x, y, z);
      ax += x; ay += y; az += z; cnt++;
    }
  const float L = sqrtf(ax * ax + ay * ay + az * az);
  if (L > 1e-5f) { s->cx = ax / L; s->cy = ay / L; s->cz = az / L; }
  else           { s->cx = 0.0f;   s->cy = 0.0f;   s->cz = 1.0f;  }

  float far = 0.0f;
  for (int i = 0; i < 12; i++)
    for (int j = 0; j < 24; j++) {
      const float th = (float)(i + 0.5f) * 3.14159265f / 12.0f;
      const float ph = (float)j * 6.28318531f / 24.0f;
      float x = sinf(th) * cosf(ph), y = sinf(th) * sinf(ph), z = cosf(th);
      kd_fold(s, x, y, z);
      const float d = 1.0f - (x * s->cx + y * s->cy + z * s->cz);
      if (d > far) far = d;
    }
  s->spread = sqrtf(far > 0.0f ? far : 0.02f);   // chord-ish, good enough
  if (s->spread < 0.05f) s->spread = 0.05f;
  s->invSpread = 1.0f / s->spread;

  // A tangent frame at the centroid. This is the chart the phase field is
  // evaluated in - the domain is a small patch, so a tangent plane is the
  // right local coordinate and costs two dot products instead of a
  // projection. Built from whichever axis is least aligned with the centroid,
  // so the cross product never collapses.
  { float ux = 0.0f, uy = 0.0f, uz = 1.0f;
    if (fabsf(s->cz) > 0.9f) { ux = 1.0f; uz = 0.0f; }
    float tx = uy * s->cz - uz * s->cy;                 // u x c: the first tangent
    float ty = uz * s->cx - ux * s->cz;
    float tz = ux * s->cy - uy * s->cx;
    float L2 = sqrtf(tx * tx + ty * ty + tz * tz);
    if (L2 < 1e-6f) { tx = 1.0f; ty = 0.0f; tz = 0.0f; L2 = 1.0f; }
    s->t1[0] = tx / L2; s->t1[1] = ty / L2; s->t1[2] = tz / L2;
    s->t2[0] = s->cy * s->t1[2] - s->cz * s->t1[1];
    s->t2[1] = s->cz * s->t1[0] - s->cx * s->t1[2];
    s->t2[2] = s->cx * s->t1[1] - s->cy * s->t1[0]; }

  for (int k = 0; k < KD_MAXCUT; k++) {
    s->cut[k][0] = KD_CUTDIR[k][0];
    s->cut[k][1] = KD_CUTDIR[k][1];
    s->cut[k][2] = KD_CUTDIR[k][2];
  }
  (void)cnt;
}

static FX_RET mode_kaleidoscope() {
  if (!strip.isMatrix || !SEGMENT.is2D()) { SEGMENT.fill(SEGCOLOR(0)); FX_DONE; }
  const int cols = SEG_W, rows = SEG_H;
  if (cols < 8 || rows < 8) { SEGMENT.fill(SEGCOLOR(0)); FX_DONE; }

  const bool cube = cfx_isCube(cols, rows);
  const int  B    = cube ? (cols / 3) : 1;

  if (!SEGENV.allocateData(sizeof(KdState))) { SEGMENT.fill(SEGCOLOR(0)); FX_DONE; }
  KdState *s = (KdState *)SEGENV.data;

  const uint8_t want = (uint8_t)(cube ? 1 : 2);
  if (SEGENV.call == 0 || s->mode != want) {
    s->mode = want; s->clk[0] = s->clk[1] = 0;
    s->spinA = 0; s->spinB = 0; s->drift = 0; s->surge = 0;
    s->sym = 0xFF;
    for (int k = 0; k < KD_MAXCUT; k++) s->cutPh[k]  = (uint16_t)(k * 7411);
    for (int k = 0; k < KD_NROOT;  k++) s->rootPh[k] = (uint16_t)(k * 16384 + 2000);
  }

  uint16_t dt = fx_dt8(s->clk);
  if (dt > 60) dt = 60;

  // --- parameters -----------------------------------------------------------
  const int  fill   = (int)SEGMENT.intensity;
  const int  nCut   = 2 + ((int)SEGMENT.custom1 * 10) / 255;      // 2..12
                                     // never 1: two cells, one of which
                                     // hashes dark, is 95% black surface
  const int  mix    = (int)SEGMENT.custom2;   // cell id <-> phase field
  const bool seams  = SEGMENT.check2;
  {
    uint8_t pick = SEGMENT.custom3;                               // 5-bit index
    if (pick >= KD_NSYM) pick = KD_NSYM - 1;
    if (pick != s->sym) kd_load(s, pick);
  }

  // --- audio ----------------------------------------------------------------
  um_data_t     *um   = cfx_getAudioData();
  const float    vol  = *(float *)um->u_data[0];
  const uint8_t  beat = SEGMENT.check1 ? fx_lowBeat(um) : 0;
  if (beat > s->surge) s->surge = beat;
  { const int f = (int)s->surge - (int)fx_step(6, dt);
    s->surge = (uint8_t)(f < 0 ? 0 : f); }

  // --- the two clocks -------------------------------------------------------
  { const uint32_t sp = (uint32_t)(8 + (int)SEGMENT.speed / 2)
                        * (uint32_t)dt * (uint32_t)(100 + s->surge / 2) / (23u * 100u);
    s->spinA = (uint16_t)(s->spinA + sp);
    s->spinB = (uint16_t)(s->spinB + sp * 5u / 13u);   // incommensurate on purpose
  }
  for (int k = 0; k < nCut; k++)
    s->cutPh[k] = (uint16_t)(s->cutPh[k] +
                  ((uint32_t)dt * (uint32_t)(11 + (int)SEGMENT.speed / 3) * (3u + k)) / (23u * 4u));
  for (int k = 0; k < KD_NROOT; k++)
    s->rootPh[k] = (uint16_t)(s->rootPh[k] +
                   ((uint32_t)dt * (uint32_t)(7 + (int)SEGMENT.speed / 5) * (2u + k)) / (23u * 3u));
  s->drift = (uint16_t)(s->drift + (uint32_t)dt * 2u);

  // Two rotations about different axes. Composed once per frame, not per pixel.
  float R[3][3];
  { const float a = (float)s->spinA * (6.28318531f / 65536.0f);
    const float b = (float)s->spinB * (6.28318531f / 65536.0f);
    const float ca = cosf(a), sa = sinf(a), cb = cosf(b), sb = sinf(b);
    // Rz(a) then Rx(b)
    R[0][0] =  ca;      R[0][1] = -sa;      R[0][2] = 0.0f;
    R[1][0] =  cb * sa; R[1][1] =  cb * ca; R[1][2] = -sb;
    R[2][0] =  sb * sa; R[2][1] =  sb * ca; R[2][2] =  cb;
  }

  // Each cut's offset, anchored to where the domain actually is.
  float cOff[KD_MAXCUT];
  for (int k = 0; k < nCut; k++) {
    const float base = s->cut[k][0] * s->cx + s->cut[k][1] * s->cy + s->cut[k][2] * s->cz;
    const float w    = (float)(int16_t)(sin16_t(s->cutPh[k])) * (1.0f / 32768.0f);
    cOff[k] = base + w * s->spread * 0.85f;
  }

  // Zeros and poles of the rational map, drifting on their own circles inside
  // the domain. Two of each: arg((z-a0)(z-a1) * conj((z-b0)(z-b1))) is the
  // phase, which takes five complex multiplies and ONE atan2 rather than four.
  float rr[KD_NROOT], ri[KD_NROOT];
  for (int k = 0; k < KD_NROOT; k++) {
    const float a = (float)s->rootPh[k] * (6.28318531f / 65536.0f);
    const float R = 0.30f + 0.16f * (float)k;
    rr[k] = R * cosf(a); ri[k] = R * sinf(a);
  }

  const uint8_t hueOff = (uint8_t)(s->drift >> 8);
  const uint8_t drive  = cfx_drive(vol, 0.5f, 200);
  // One pixel, as an angle. The cube's faces span 90 degrees over B pixels, and
  // a direction near a corner turns more slowly per pixel than one at a face
  // centre - hence the 1/L, which keeps an outline the same width everywhere.
  const float pxA = cube ? (2.0f / (float)B) : (2.0f / (float)cols);

  // --- paint ----------------------------------------------------------------
  CFX_NET_PREP();
  for (int y = 0; y < rows; y++) {
    CFX_NET_ROW(y);
    for (int x = 0; x < cols; x++) {
      CFX_NET_SKIP(x);

      float X, Y, Z; cfx_pos(x, y, cols, rows, B, cube, X, Y, Z);
      if (!cube) Z = 1.0f - (X * X + Y * Y) * 0.5f;     // a panel becomes a dome
      const float L = sqrtf(X * X + Y * Y + Z * Z);
      const float iL = (L > 1e-6f) ? (1.0f / L) : 1.0f;
      float nx = X * iL, ny = Y * iL, nz = Z * iL;

      { const float rx = R[0][0] * nx + R[0][1] * ny + R[0][2] * nz;
        const float ry = R[1][0] * nx + R[1][1] * ny + R[1][2] * nz;
        const float rz = R[2][0] * nx + R[2][1] * ny + R[2][2] * nz;
        nx = rx; ny = ry; nz = rz; }

      kd_fold(s, nx, ny, nz);

      // --- the arrangement --------------------------------------------------
      uint32_t cell = 0;
      float    dCut = 9.0f;
      for (int k = 0; k < nCut; k++) {
        const float d = nx * s->cut[k][0] + ny * s->cut[k][1] + nz * s->cut[k][2] - cOff[k];
        if (d > 0.0f) cell |= (1u << k);
        const float ad = (d < 0.0f) ? -d : d;
        if (ad < dCut) dCut = ad;
      }

      // Distance to the nearest mirror. After folding every dot is >= 0, so
      // the smallest one is how close this pixel sits to a seam.
      float dMir = 9.0f;
      if (seams) {
        for (int j = 0; j < s->nm; j++) {
          const float d = nx * s->mir[j][0] + ny * s->mir[j][1] + nz * s->mir[j][2];
          if (d < dMir) dMir = d;
        }
      }

      // --- colour -----------------------------------------------------------
      // Two hue sources on two different channels, which is the whole reason
      // they compose. The cell id is DISCRETE - it says which island you are
      // on, and it is constant across that island. The phase field is
      // CONTINUOUS - the argument of a rational map with two zeros and two
      // poles, read in the tangent chart at the domain centroid - and it
      // sweeps the whole colour wheel around every zero and pole, winding one
      // way at a zero and the other at a pole.
      //
      // Because it is evaluated at the FOLDED point it inherits the mirror
      // symmetry exactly, so every vortex appears in all 8 to 120 copies at
      // once. And because the cell borders are black, colour flowing across
      // them does not blur the islands together.
      uint32_t h = cell * 2654435761u;
      h ^= h >> 13;
      const uint8_t cid = (uint8_t)(h >> 7);

      uint8_t phs = 0;
      if (mix) {
        const float zx = (nx * s->t1[0] + ny * s->t1[1] + nz * s->t1[2]) * s->invSpread;
        const float zy = (nx * s->t2[0] + ny * s->t2[1] + nz * s->t2[2]) * s->invSpread;
        float ar = 1.0f, ai = 0.0f, br = 1.0f, bi = 0.0f;
        for (int k = 0; k < KD_NROOT; k++) {
          const float dr = zx - rr[k], di = zy - ri[k];
          if (k < 2) { const float t = ar * dr - ai * di; ai = ar * di + ai * dr; ar = t; }
          else       { const float t = br * dr - bi * di; bi = br * di + bi * dr; br = t; }
        }
        const float wr = ar * br + ai * bi;        // num * conj(den)
        const float wi = ai * br - ar * bi;

        // Domain colouring proper: hue from the argument, contour rings from
        // the modulus. The argument alone was too quiet - one turn of the
        // palette spread over a whole island is barely a gradient - so it
        // winds twice per turn, and the |f| contours add the rings that
        // converge on every zero and pole. Together they make the spiral
        // that says which singularity you are looking at and which way it
        // turns.
        int fld = (int)(cfx_atan2f(wi, wr) * (128.0f / 3.14159274f));

        // log2|f|^2 without a log call: a float already stores its exponent,
        // and the top mantissa bits are a good enough fractional part at
        // 8-bit palette resolution.
        { const float den2 = br * br + bi * bi;
          const float num2 = ar * ar + ai * ai;
          float mod2 = num2 / ((den2 > 1e-20f) ? den2 : 1e-20f);
          if (!(mod2 > 1e-20f)) mod2 = 1e-20f;
          uint32_t bits; memcpy(&bits, &mod2, sizeof(bits));
          const int e   = (int)((bits >> 23) & 0xFF) - 127;
          int l2 = (e << 8) | (int)((bits >> 15) & 0xFF);           // 8.8
          // CLAMPED, and that is the whole difference between contours and
          // noise: log|f| runs to minus infinity at a zero and plus infinity
          // at a pole, so unbounded rings pile up without limit exactly where
          // the eye is drawn. Four octaves either side is all that resolves at
          // sixteen pixels a face.
          if (l2 >  1024) l2 =  1024; else if (l2 < -1024) l2 = -1024;
          fld += l2 >> 4; }

        phs = (uint8_t)fld;
      }
      const uint8_t idx = (uint8_t)(((int)cid * (255 - mix)) / 255
                                  + ((int)phs * mix) / 255 + hueOff);

      // Cells take a wide brightness range from their own id, not a narrow
      // one. Held near a mid grey they came out muddy - every cell the same
      // weight, sigma 23 - and the picture read as flat colour rather than as
      // glass. Some cells clipping at full is the point.
      int lum = (fill * (25 + ((int)((h >> 24) & 255) * 3) / 5)) >> 7;

      // Negative space: the cell boundaries are black, so neighbouring cells
      // stay separate instead of merging into one blob.
      { const float w = 0.85f * pxA * iL;
        if (dCut < w) lum = (int)((float)lum * (dCut / w)); }
      if (seams) {
        const float w = 0.85f * pxA * iL;
        if (dMir < w) lum = (int)((float)lum * (dMir / w));
      }
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

static const char _data_FX_MODE_KALEIDOSCOPE[] PROGMEM =
  "Ace 3-D Kaleidoscope@Spin,Fill,Circles,Colour mix,Symmetry,Beat surge,Seams,Flat mode;;!;2f;sx=110,ix=128,c1=90,c2=170,c3=4,o1=1,pal=11";


// ---------------------------------------------------------------------------
// Registration - joins the effect bank, which decides whether this effect
// claims one of the device's limited effect slots. See cube_fx_bank.h.
// ---------------------------------------------------------------------------
static CfxBankReg cube_fx_39_kaleidoscope_reg(&mode_kaleidoscope, _data_FX_MODE_KALEIDOSCOPE);
