#include "wled.h"
#include "cube_fx_common.h"
#include "cube_fx_bank.h"

// ===========================================================================
// Ace 3-D Poincare - a hyperbolic tiling, flowing for ever, with no seam
// ===========================================================================
// The cube's lit surface is five faces of six. Remove one face from a sphere
// and what is left is topologically a DISK - which is exactly the domain of
// the Poincare disk model of the hyperbolic plane. So a {p,q} tiling can be
// laid over this solid with no seam handling anywhere, not because the folds
// are patched up but because there is nothing to patch: the picture is a
// function of the surface point, and the surface has no boundary except the
// bottom rim.
//
// Stereographic projection from the bottom pole does the mapping, the same
// projection Feigenbaum and Mandelbrot use and for the same reason - it is
// conformal, so tiles keep their shape across a fold, and it is bounded here
// because there is no bottom face for the pole to sit on. The disk centre
// lands on the middle of the lid; the bottom rim maps to a rounded square at
// radius 1.93 (corners) to 2.41 (edge midpoints), which is then scaled to sit
// inside the unit disk. The ideal boundary - hyperbolic infinity - therefore
// lies just OUTSIDE the cube. Tiles shrink towards the bottom rim but never
// quite reach the vanishing point, which is the whole reason this is drawable.
//
// ---------------------------------------------------------------------------
// THE FOLD
// ---------------------------------------------------------------------------
// Every pixel is reduced into one fundamental triangle of the (2,p,q) triangle
// group, and the picture is whatever texture that triangle carries. Three
// mirrors: two lines through the origin at 0 and pi/p, and one geodesic.
//
//   - the two lines are a dihedral fold, done by rotating into the nearest
//     sector and taking |v|
//   - the geodesic is the circle orthogonal to the unit circle whose nearest
//     approach to the origin is the polygon's inradius. Orthogonality means
//     d^2 = rho^2 + 1, and with the Euclidean inradius r it comes out as
//     d = (r + 1/r)/2, rho = (1/r - r)/2 - verified exact to 9 decimals.
//
// r itself is hyperbolic trigonometry on the (pi/p, pi/q, pi/2) triangle:
// cosh(inradius) = cos(pi/q)/sin(pi/p), and Euclidean radius = tanh(dist/2).
//
// Measured over the real net at the shipped depth, across the whole table, the
// fold needs at most 5 inversions and averages under one, so PC_MAXIT is
// generous and this is far cheaper than it looks - most pixels take the
// dihedral fold and no inversion at all.
//
// ---------------------------------------------------------------------------
// THE FLOW WRAPS EXACTLY - BUT NOT THE WAY I FIRST THOUGHT
// ---------------------------------------------------------------------------
// Hyperbolic geometry has no dilations, so the endless motion here is a
// TRANSLATION, not a zoom: the tiling holds still and the cube slides through
// it. Tiles swell up out of one side of the bottom rim, sweep over the whole
// solid, and compress into the other side. The translation's fixed points sit
// at radius 1, outside the mapped region, so there is no source or sink
// anywhere on the surface - the flow is non-zero over every pixel.
//
// For that to loop, the translation after one period has to be an element of
// the tiling's own symmetry group. The obvious argument - reflect in the
// polygon edge, reflect in the axis, both are mirrors, so the composition is a
// translation - is WRONG, and measuring caught it. Those two geodesics
// intersect, so their composition is a rotation, not a translation. A
// translation needs two DISJOINT perpendiculars to the axis, and the second
// one is a mirror of the group only when p is even.
//
// Scanning it numerically gives the real rule, which is that odd p needs a
// GLIDE - translate by 2*inradius and rotate by pi/p over the same period,
// because for odd p the neighbouring polygon across an edge sits rotated by
// half a sector. With that, every tiling in the table below returns to itself
// to within 2e-15. Without the twist, odd p misses by more than a whole tile.
//
// ---------------------------------------------------------------------------
// WHY GENERATION COUNT IS NOT ALLOWED NEAR THE COLOUR
// ---------------------------------------------------------------------------
// Colouring tiles by how many inversions they took is the obvious thing to do
// and it would wreck the loop. The geometry wraps exactly, but the LABELLING
// does not: a tile two rings out before the wrap is three rings out after it.
// Measured across the table, the generation shift at the wrap is +1 for only
// 71-96% of the surface, the rest going the other way - so a colour built on
// it would mottle a tenth to a quarter of the cube at every loop.
//
// Every texture below therefore reads the FOLDED POSITION only, which wraps
// with the geometry. The count survives as nothing but a loop bound.
//
// ---------------------------------------------------------------------------
// DEPTH, AND TWO WAYS OF COUNTING TILES THAT DIFFER BY A FACTOR OF 2p
// ---------------------------------------------------------------------------
// How far into the disk the bottom rim is pushed decides how much hyperbolic
// structure lands on the cube. Getting it wrong is what most of this effect's
// development was spent on, twice, in opposite directions.
//
// The first calibration used a net with 48-pixel faces - nine times what this
// cube has - and put 36% of the picture into single-pixel cells. Correcting
// that overshot, because the counting script hashed the whole fold path
// INCLUDING the dihedral sector, which identifies fundamental TRIANGLES rather
// than tiles. There are 2p triangles to a tile, so at p = 12 it was reading 24
// tiles as 576, and the depth it recommended left the cube showing about three
// polygons in total. Both errors measured cleanly and were wrong.
//
// Counted properly - hashing only the geodesic crossings, since the dihedral
// fold happens inside a tile - the invariant is pixels per tile: tile count
// grows like 1/(1-R^2) and pixels like B^2, so holding the ratio fixed means
// 1-R^2 ~ 1/B^2, which is pc_depth(). At the cube's 16-pixel face that gives
// R = 0.86, and the table below then spans 19 to 69 tiles at 19 to 67 pixels
// each.
//
// One consequence is worth stating because it is not a flaw to be fixed: a
// hyperbolic tiling puts exponentially more tiles near the ideal boundary than
// near the centre, so the LID is always the interior of a single tile and all
// the tiling proper lives on the walls. That is why there are two lattices in
// the paint loop rather than one.
//
// The control depth would otherwise have used went to contrast instead, which
// matters more, and it is nearly redundant with Symmetry anyway - that sweeps
// the same axis from 19 tiles to 69.
// ===========================================================================

#define PC_NTILING  32
#define PC_MAXIT    10          // measured worst case is 5; this is headroom
#define PC_RIMRAW   2.41421356f // (sqrt2+1): bottom edge midpoint, projected
#define PC_QWAVES   5           // directions summed for the quasicrystal texture
#define PC_WEBPX    2.2f        // lattice half-width, in pixels, before taper

// See the header. At the cube's 16-pixel face this returns 0.86, which is
// where the table below lands on 19 to 69 tiles. Clamped so a tiny panel does
// not collapse to a single polygon and a large one does not run away into the
// rim, where the tiles go sub-pixel however many of them there are.
static inline float pc_depth(int B, bool cube) {
  if (!cube) return 0.78f;
  float v = 1.0f - 66.7f / ((float)B * (float)B);
  if (v < 0.36f) v = 0.36f; else if (v > 0.8836f) v = 0.8836f;
  return sqrtf(v);
}

// p-gons, q of them at each vertex. Every row is hyperbolic (1/p + 1/q < 1/2),
// and every row was picked by COUNTING it on the real net rather than by
// looking at its inradius: the tile counts in the comments are measured at the
// shipped depth, and the table is ordered by them so the slider sweeps density
// evenly. p runs from 3 to 12 across it, which is the other thing the eye
// reads - it is the rotational order of every rosette on the cube.
//
// The band is deliberately 19 to 69 tiles. Below that the cube shows one
// polygon and no tiling; above it the outer ring goes sub-pixel and the walls
// measure as noise. Both ends were tried.
static const uint8_t PC_TILING[PC_NTILING][2] PROGMEM = {
  {  9, 10 },   //  0   19 tiles,  67 px each   glide
  {  7, 12 },   //  1   21 tiles,  61 px each   glide
  { 10,  8 },   //  2   21 tiles,  61 px each
  { 10, 11 },   //  3   21 tiles,  61 px each
  { 11,  7 },   //  4   21 tiles,  61 px each   glide
  { 11, 10 },   //  5   21 tiles,  61 px each   glide
  { 11, 12 },   //  6   21 tiles,  61 px each   glide
  {  9,  8 },   //  7   23 tiles,  56 px each   glide
  {  6,  9 },   //  8   25 tiles,  51 px each
  {  6, 12 },   //  9   25 tiles,  51 px each
  {  8,  8 },   // 10   25 tiles,  51 px each
  { 12,  5 },   // 11   25 tiles,  51 px each
  { 12,  7 },   // 12   25 tiles,  51 px each
  {  5, 12 },   // 13   27 tiles,  47 px each   glide
  {  7,  9 },   // 14   27 tiles,  47 px each   glide
  { 11,  6 },   // 15   27 tiles,  47 px each   glide
  {  7,  7 },   // 16   29 tiles,  44 px each   glide
  { 10,  6 },   // 17   29 tiles,  44 px each
  {  7,  6 },   // 18   31 tiles,  41 px each   glide
  {  4, 11 },   // 19   33 tiles,  39 px each
  {  5,  8 },   // 20   33 tiles,  39 px each   glide
  {  6,  7 },   // 21   33 tiles,  39 px each
  {  8,  5 },   // 22   33 tiles,  39 px each
  { 11,  4 },   // 23   33 tiles,  39 px each   glide
  {  5,  6 },   // 24   35 tiles,  37 px each   glide
  {  5,  5 },   // 25   39 tiles,  33 px each   glide
  {  4,  9 },   // 26   41 tiles,  31 px each
  {  8,  4 },   // 27   41 tiles,  31 px each
  {  9,  3 },   // 28   43 tiles,  30 px each   glide
  {  3, 11 },   // 29   57 tiles,  22 px each   glide
  {  4,  6 },   // 30   57 tiles,  22 px each
  {  3, 10 },   // 31   69 tiles,  19 px each   glide
};

struct PcState {
  uint8_t  mode;
  uint8_t  clk[2];
  uint8_t  tile;          // which row of PC_TILING is loaded
  uint8_t  surge;
  uint16_t phase;         // 0..65535 is one exact wrap
  uint16_t spin;          // continuous rotation of the disk, 65536 = one turn
  uint16_t drift;         // slow palette rotation
  // --- derived from `tile`, rebuilt only when it changes -------------------
  uint8_t  p;
  float    d, rho, rho2;  // the inversion circle
  float    rIn, invRIn;   // Euclidean inradius of the central polygon
  float    invEn;         // 1 / deepest point of the fundamental triangle
  float    aFull;         // atanh amount of one full wrap, in Mobius terms
  float    twist;         // pi/p for odd p, 0 for even - see the header
  float    mirC, mirS;    // normal of the pi/p mirror
  float    rotC[12], rotS[12];
};

// Five directions over pi. cos is even, so half a turn covers the star.
static const float PC_QC[PC_QWAVES] = { 1.000000f, 0.809017f, 0.309017f, -0.309017f, -0.809017f };
static const float PC_QS[PC_QWAVES] = { 0.000000f, 0.587785f, 0.951057f,  0.951057f,  0.587785f };

// Palette indices are cyclic, so a blend has to take the short way round -
// straight interpolation between 250 and 5 sweeps the whole wheel backwards.
static inline uint8_t pc_mixIdx(uint8_t a, uint8_t b, uint8_t f) {
  int dl = (int)b - (int)a;
  if (dl > 128) dl -= 256; else if (dl < -128) dl += 256;
  return (uint8_t)((int)a + (dl * (int)f) / 255);
}

static void pc_load(PcState *s, uint8_t idx) {
  s->tile = idx;
  const int p = pgm_read_byte(&PC_TILING[idx][0]);
  const int q = pgm_read_byte(&PC_TILING[idx][1]);
  s->p = (uint8_t)p;

  const float K = cosf(3.14159265f / (float)q) / sinf(3.14159265f / (float)p);
  const float r = sqrtf((K - 1.0f) / (K + 1.0f));       // tanh(inradius/2)
  s->rIn    = r;
  s->invRIn = 1.0f / r;
  s->d      = 0.5f * (r + 1.0f / r);
  s->rho    = 0.5f * (1.0f / r - r);
  s->rho2   = s->rho * s->rho;
  s->aFull  = acoshf(K);                                // the hyperbolic inradius
  s->twist  = (p & 1) ? (3.14159265f / (float)p) : 0.0f;

  const float mp = 3.14159265f / (float)p;
  s->mirC = cosf(mp); s->mirS = sinf(mp);
  for (int k = 0; k < p; k++) {                         // rotate by -k*2pi/p
    const float a = -(float)k * 2.0f * mp;
    s->rotC[k] = cosf(a); s->rotS[k] = sinf(a);
  }

  // How deep the fundamental triangle actually gets. This is NOT the polygon
  // inradius and it is not close to it - measured across the table, the
  // deepest point of the triangle sits at 0.12 to 0.30 of that. Normalising
  // by the wrong one is what made the first build light the entire surface as
  // though every pixel were on a mirror, and read as a flat mean of 76.
  // Sampled rather than derived: it runs only when Symmetry moves.
  float best = 0.0f;
  for (int i = 1; i < 24; i++) {
    const float rr = (float)i * (s->rIn * 1.7f / 24.0f);
    for (int j = 0; j <= 12; j++) {
      const float th = (float)j * mp / 12.0f;           // across the wedge
      const float uu = rr * cosf(th), vv = rr * sinf(th);
      float e = vv;
      const float e2 = uu * s->mirS - vv * s->mirC;  if (e2 < e) e = e2;
      const float dx = uu - s->d;
      const float e3 = sqrtf(dx * dx + vv * vv) - s->rho;  if (e3 < e) e = e3;
      if (e > best) best = e;
    }
  }
  s->invEn = (best > 1e-4f) ? (1.0f / best) : 1.0f;
}

static FX_RET mode_poincare() {
  if (!strip.isMatrix || !SEGMENT.is2D()) { SEGMENT.fill(SEGCOLOR(0)); FX_DONE; }
  const int cols = SEG_W, rows = SEG_H;
  if (cols < 8 || rows < 8) { SEGMENT.fill(SEGCOLOR(0)); FX_DONE; }

  const bool cube = cfx_isCube(cols, rows);
  const int  B    = cube ? (cols / 3) : 1;

  // No per-pixel buffers. The stereographic map is a sqrt and two divides,
  // which is cheaper than the 46 KB it would take to cache it, and it keeps
  // this effect's allocation to a couple of hundred bytes.
  if (!SEGENV.allocateData(sizeof(PcState))) { SEGMENT.fill(SEGCOLOR(0)); FX_DONE; }
  PcState *s = (PcState *)SEGENV.data;

  const uint8_t want = (uint8_t)(cube ? 1 : 2);
  if (SEGENV.call == 0 || s->mode != want) {
    s->mode = want; s->clk[0] = s->clk[1] = 0;
    s->phase = 0; s->spin = 0; s->drift = 0; s->surge = 0;
    s->tile = 0xFF;
  }

  uint16_t dt = fx_dt8(s->clk);
  if (dt > 60) dt = 60;

  // --- parameters -----------------------------------------------------------
  const int  fill = (int)SEGMENT.intensity;
  const int  tex  = (int)SEGMENT.custom1;
  const int  tscl = (int)SEGMENT.custom2;
  const bool lead = SEGMENT.check2;
  {
    uint8_t pick = SEGMENT.custom3;                      // 5-bit: a table index
    if (pick >= PC_NTILING) pick = PC_NTILING - 1;
    if (pick != s->tile) pc_load(s, pick);
  }

  // --- audio ----------------------------------------------------------------
  um_data_t     *um   = cfx_getAudioData();
  const float    vol  = *(float *)um->u_data[0];
  const uint8_t  beat = SEGMENT.check1 ? fx_lowBeat(um) : 0;
  if (beat > s->surge) s->surge = beat;
  { const int f = (int)s->surge - (int)fx_step(6, dt);
    s->surge = (uint8_t)(f < 0 ? 0 : f); }

  // --- the flow -------------------------------------------------------------
  // Two motions on deliberately different clocks. `phase` runs 0..65535 over
  // exactly one group element, so the translation can free-run for ever
  // without the transform ever growing. `spin` is a plain rotation of the
  // disk, about three times slower.
  //
  // The spin is free to be ANY angle without breaking the loop, which is worth
  // spelling out: rotations commute, so the map at the end of a period is
  // g . R(spin) for the group element g, and a tiling is invariant under g -
  // the picture is identical to R(spin) alone. Structure slow, texture fast,
  // colour slowest, which is what stops two layers reading as noise.
  { const int32_t step = ((6 + (int32_t)SEGMENT.speed / 3) * (int32_t)dt
                          * (100 + (int32_t)s->surge / 2)) / (23 * 100);
    s->phase = (uint16_t)(s->phase + (uint32_t)(step < 1 ? 1 : step)); }
  s->spin  = (uint16_t)(s->spin +
             ((uint32_t)dt * (uint32_t)(4 + (int)SEGMENT.speed / 4)) / 48u);
  s->drift = (uint16_t)(s->drift + (uint32_t)dt * 3u);

  const float t   = (float)s->phase * (1.0f / 65536.0f);
  const float aM  = tanhf(t * s->aFull);                 // Mobius amount so far
  const float tw  = t * s->twist + (float)s->spin * (6.28318531f / 65536.0f);
  const float twC = cosf(tw), twS = sinf(tw);

  const float dep = pc_depth(B, cube);
  const float scl = cube ? (dep / PC_RIMRAW) : (dep / 1.41421356f);

  // The lattice has to be a constant width in PIXELS - not a constant fraction
  // of a tile, which is what the first build drew. Screen width is
  //   (distance in the folded domain) * (1 - r^2) * (pixels per disk unit),
  // so the threshold is 255 divided by that, and it carries the resolution and
  // the depth rather than being a tuned constant. Left as a fraction of a tile
  // it drew a five-pixel line on a six-pixel tile at one end of the Symmetry
  // control and a sub-pixel one at the other.
  const float pxPerUnit = (float)(cube ? 3 * B : cols) / (2.0f * dep);
  const float webG      = 255.0f * pxPerUnit / PC_WEBPX;
  // Texture frequency, in palette cycles across one fundamental triangle. The
  // ceiling matters: the first build ran this to 17, which swept the palette
  // twice inside a tile four pixels wide and measured as pure noise. At 16
  // pixels a face there is room for one cycle, not two.
  const float qk  = 0.25f + (float)tscl * (2.25f / 255.0f);
  const uint8_t hueOff = (uint8_t)(s->drift >> 8);
  const uint8_t drive  = cfx_drive(vol, 0.5f, 200);
  const int     tsel   = ((int)tex * 3) >> 8;                // 0..2
  const uint8_t tfrac  = (uint8_t)(((int)tex * 3) & 255);

  // --- paint ----------------------------------------------------------------
  CFX_NET_PREP();
  for (int y = 0; y < rows; y++) {
    CFX_NET_ROW(y);
    for (int x = 0; x < cols; x++) {
      CFX_NET_SKIP(x);

      float X, Y, Z; cfx_pos(x, y, cols, rows, B, cube, X, Y, Z);
      float u, v;
      if (cube) {
        const float L = sqrtf(X * X + Y * Y + Z * Z);
        const float den = 1.0f + Z / L;
        const float g = (den > 0.02f) ? (scl / (den * L)) : (scl * 50.0f / L);
        u = X * g; v = Y * g;
      } else {
        u = X * scl; v = Y * scl;                       // a panel IS the disk
      }

      // The Poincare conformal factor at the SCREEN point - before the glide,
      // because the glide is an isometry that moves the tiling, not the pixel.
      // Taking it afterwards measures the tiling frame instead and makes the
      // lattice width drift with the flow, which is what broke the first two
      // attempts at this.
      float scS = 1.0f - (u * u + v * v);
      if (scS < 0.12f) scS = 0.12f;

      // glide: spin, then translate along +u
      { const float ru = u * twC - v * twS, rv = u * twS + v * twC;
        const float nr = ru + aM,        ni = rv;
        const float dr = 1.0f + aM * ru, di = aM * rv;
        const float dn = dr * dr + di * di;
        const float iv = (dn > 1e-12f) ? 1.0f / dn : 0.0f;
        u = (nr * dr + ni * di) * iv;
        v = (ni * dr - nr * di) * iv; }

      // --- reduce into the fundamental triangle -----------------------------
      for (int it = 0; it < PC_MAXIT; it++) {
        const float th = cfx_atan2f(v, u);
        int k = (int)floorf(th * (float)s->p * 0.159154943f + 0.5f);   // /(2pi)
        k %= (int)s->p; if (k < 0) k += (int)s->p;
        if (k) { const float c = s->rotC[k], sn = s->rotS[k];
                 const float nu = u * c - v * sn; v = u * sn + v * c; u = nu; }
        if (v < 0.0f) v = -v;

        const float dx = u - s->d, q2 = dx * dx + v * v;
        if (q2 >= s->rho2) break;                        // inside the polygon
        const float f = s->rho2 / ((q2 > 1e-20f) ? q2 : 1e-20f);
        u = s->d + dx * f; v = v * f;
      }

      // --- distance to the three mirrors ------------------------------------
      // Taken in the FOLDED domain, where Euclidean and hyperbolic agree, so
      // the web is a constant hyperbolic width - which is what makes it thin
      // towards the rim in screen space, exactly as it should.
      // Only ONE of the three is a tile boundary. The two straight mirrors run
      // through the middle of a polygon, so lighting all three subdivides
      // every tile into its 2p wedges and the lid reads as a spoked star
      // rather than a tiling - which is exactly what the first build did.
      // The geodesic alone is the polygon edge, and it is the web; the other
      // two stay as a texture field, where the extra symmetry belongs.
      const float dx = u - s->d;
      float eg = sqrtf(dx * dx + v * v) - s->rho;        // 0 at a tile edge
      if (eg < 0.0f) eg = 0.0f;

      // Same distance, expressed at the screen instead of in the fundamental
      // domain: hyperbolic width is 2*eg/(1-|z_fold|^2), and that maps back to
      // the screen through (1-|z_screen|^2)/2. Both factors are needed - the
      // folded point is not near enough to the origin for its own to be 1.
      float fden = 1.0f - (u * u + v * v);
      if (fden < 0.20f) fden = 0.20f;
      const float egS = eg * scS / fden;

      float e = eg;                                      // nearest of all three
      { const float e2 = u * s->mirS - v * s->mirC;      // the pi/p mirror
        if (e2 < e) e = e2;
        if (v  < e) e = v; }                             // the theta=0 mirror
      if (e < 0.0f) e = 0.0f;
      const float emS = e * scS / fden;                  // the same, on screen
      float en = e * s->invEn;                           // 0 at a mirror, 1 mid
      if (en > 1.0f) en = 1.0f;

      // --- texture ----------------------------------------------------------
      const float nu = u * s->invRIn, nv = v * s->invRIn;
      uint8_t tv[4];
      for (int n = tsel; n <= tsel + 1; n++) {
        switch (n) {
          case 0:                                        // radial: rose window
            tv[n] = (uint8_t)(int)(sqrtf(nu * nu + nv * nv) * qk * 90.0f);
            break;
          case 1:                                        // distance to the web
            tv[n] = (uint8_t)(int)(en * qk * 130.0f);
            break;
          case 2: {                                      // quasicrystal
            int acc = 0;
            for (int w = 0; w < PC_QWAVES; w++)
              acc += (int)cos8_t((uint8_t)(int)((nu * PC_QC[w] + nv * PC_QS[w]) * qk * 70.0f));
            tv[n] = (uint8_t)(acc / PC_QWAVES);
            break; }
          default: {                                     // phase within the tile
            const float ph = cfx_atan2f(nv, nu) * (float)s->p * 0.318309886f;
            tv[n] = (uint8_t)(int)(ph * qk * 130.0f);
            break; }
        }
      }
      // --- brightness: a bright lattice over a dim textured ground ----------
      // The texture drives COLOUR, not brightness. It used to drive both, and
      // that made the lattice appear or vanish depending on which texture was
      // selected - the radial one happens to peak where the web is, so the two
      // cancelled and the cube read as a smooth wash. Structure is the web;
      // the texture says what colour things are.
      //
      // At sixteen pixels a face a tile is about six across, which is room for
      // a lattice and a couple of colour bands inside it and nothing finer. So
      // the detail here is the tiling itself, and black between the tiles is
      // what makes it read.
      // TWO lattices, because one is not enough on a surface this size. A
      // hyperbolic tiling puts exponentially more tiles near the ideal
      // boundary than near the centre, so with the disk centred on the lid the
      // lid is ALWAYS the interior of one single tile - measured, 33 tiles on
      // the cube and not one edge crossing the top face. That is the geometry,
      // not a bug, and drawing only tile edges leaves the lid blank.
      //
      // So the tile boundary is the bright lattice, and the polygon's own
      // mirrors are a dimmer one inside it. The walls then read as a tiling
      // and the lid as the rosette of the tile you are standing in, which is
      // what makes the whole solid carry something.
      int web = 255 - (int)(egS * webG);
      if (web < 0) web = 0;
      web = (web * web) >> 8;                            // taper, not a step
      { int mir = 255 - (int)(emS * webG);
        if (mir > 0) { mir = ((mir * mir) >> 8) * 5 / 9; if (mir > web) web = mir; } }

      // Hue shifts towards the edge, so the leading is its own colour rather
      // than the same colour turned up.
      const uint8_t idx = (uint8_t)(pc_mixIdx(tv[tsel], tv[tsel + 1], tfrac)
                                    + hueOff + (uint8_t)((web * 56) >> 8));

      int lum;
      if (lead) {
        // Leaded glass inverts the roles: the tiles carry the light and the
        // lattice is the dark came between them. It has to raise the ground as
        // it does so - subtracting the web from the ordinary fill just drove
        // the whole cube to black, 91% dark at a mean of 3.6.
        const int base = (fill * (70 + (int)tv[tsel] / 2)) >> 7;
        lum = (base * (255 - web)) >> 8;
      } else {
        const int fl = (fill * (80 + (int)tv[tsel] / 2)) >> 9;
        lum = (web > fl) ? web : fl;
      }
      if (lum > 255) lum = 255;

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

static const char _data_FX_MODE_POINCARE[] PROGMEM =
  "Ace 3-D Poincare@Flow speed,Fill,Texture,Texture scale,Symmetry,Beat surge,Leaded glass,Flat mode;;!;2f;sx=120,ix=120,c1=90,c2=150,c3=21,o1=1,pal=11";


// ---------------------------------------------------------------------------
// Registration - joins the effect bank, which decides whether this effect
// claims one of the device's limited effect slots. See cube_fx_bank.h.
// ---------------------------------------------------------------------------
static CfxBankReg cube_fx_38_poincare_reg(&mode_poincare, _data_FX_MODE_POINCARE);
