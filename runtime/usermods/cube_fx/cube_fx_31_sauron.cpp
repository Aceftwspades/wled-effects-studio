#include "wled.h"
#include "cube_fx_common.h"
#include "cube_fx_bank.h"
#include "cube_fx_imu.h"

// ===========================================================================
// Ace 3-D Sauron - the cube is the Eye
// ===========================================================================
// A gaze direction wanders the sphere of directions the cube points in. Every
// lit pixel already knows where it sits in space - cfx_buildCube hands back a
// unit-ish position per pixel - so "how far is this pixel from where the Eye is
// looking" is one dot product, and the whole structure falls out of that single
// number without a single per-face special case. The Eye crosses the seams
// because nothing in it knows the seams are there.
//
// ---------------------------------------------------------------------------
// WHAT IS ON THE GLASS, FROM THE CENTRE OUT
// ---------------------------------------------------------------------------
//   pupil    a VERTICAL SLIT, black. Not a disc - the slit is the whole
//            silhouette, and a round pupil reads as a bullseye or a bloodshot
//            marble rather than as something looking at you. It is an ellipse
//            in the two axes across the gaze, narrow one way and tall the
//            other, so it stays a slit however the Eye is turned.
//   iris     white-hot at the pupil's edge, falling through amber to deep red.
//            This is the only part with hard edges; everything outside it is
//            turbulent.
//   wreath   flame. Noise sampled in WORLD space and dragged outward, so the
//            licks travel away from the pupil rather than crawling across the
//            surface, and they cross a corner without shearing.
//   far side FALLS TO BLACK. The Eye looks one way. A cube lit all over is a
//            lamp, and the darkness is what makes the gaze a direction rather
//            than a texture - it is doing as much work here as the fire is.
//
// ---------------------------------------------------------------------------
// WHAT THE MUSIC DOES, AND WHAT IT DELIBERATELY DOES NOT
// ---------------------------------------------------------------------------
// Two things, and both are physical rather than a readout:
//
//   FLARE   a beat opens the wreath and CONSTRICTS the pupil, the way a real
//           pupil answers light. The slit narrowing on the beat is the whole
//           trick: it is a tiny movement on a black shape against a bright
//           one, and it reads from across a room where a brightness change
//           does not.
//   DART    a transient makes the gaze SNAP to a new direction. Held apart by
//           a refractory so each one lands as an event you can follow rather
//           than a shimmer, and eased over a few frames so it travels rather
//           than teleports - an eye that cuts between angles reads as a
//           glitch, one that sweeps reads as searching.
//
// There is no band-to-position mapping. Sixteen bins arranged around a sphere
// would be a spectrum analyser wearing a costume; the spectrum decides how
// hard the Eye burns and how often it looks somewhere else, and that is all.
//
// ---------------------------------------------------------------------------
// WHERE IT IS WILLING TO LOOK
// ---------------------------------------------------------------------------
// Everywhere in the upper half, but not evenly. A landmark is drawn from the
// weighted table below and the target is then blended most of the way toward a
// free direction, so the distribution CLUSTERS on the positions that read best
// - a face centre, the lid, a top corner, a top edge - and thins out between
// them without ever excluding them. Measured, the hot core visits 94% of the
// surface over forty seconds.
//
// Nothing below the equator. A gaze on the vertical middle of a wall puts half
// an Eye on glass and half falling off the bottom edge onto nothing, and the
// cube has no floor to catch it.
//
// CORNER MODE folds the target into one octant, chosen by the Corner control.
// A gaze inside an octant can only light faces whose normals it agrees with,
// which is exactly the three you see when the cube is looked at from that
// corner - so it is a strict cut rather than a bias, and the 4-6% that still
// lands on the other two is the wreath wrapping a seam, which is correct.
// ===========================================================================

struct SrState {
  uint8_t  mode;
  uint32_t nx, ny, nz;              // flame clocks, Q8
  int8_t   gx, gy, gz;              // where the Eye looks now, Q7
  int8_t   tx, ty, tz;              // where it is travelling to
  int8_t   ux, uy, uz;              // the slit's long axis, perpendicular to g
  uint8_t  flare;                   // beat envelope
  uint8_t  peak;                    // slow-release spectrum peak
  uint8_t  spec[16];
  uint16_t hold;                    // ms until the gaze may dart again
  uint16_t ease;                    // 0..65535 through the current sweep
  uint8_t  last0, last1;            // the two landmarks just used
  int8_t   pofAx, pofAy;            // pupil offset at the start of a glance
  int8_t   pofDx, pofDy;            // and how far it is moving, signed
  uint16_t pofE;                    // 0..65535 through that glance
  uint16_t pofHold;                 // ms until the pupil may glance again
  uint8_t  clk[2];
};

// Where the Eye is willing to look.
//
// A uniformly random direction spends most of its time pointing at nothing in
// particular - a low corner, an edge halfway up a wall - and those read worst,
// because the slit is split across two faces at an angle and the flame wreath
// is cut into three pieces by seams that do not line up with anything. The
// readable positions are the ones with symmetry behind them: the centre of a
// face, where the whole Eye sits on flat glass, and a TOP corner or top edge,
// where the seams radiate out of the pupil instead of slicing across it.
//
// So the gaze picks from a table of those, weighted so four fifths of the
// choices are in the upper half. ANG is the diagonal of a unit vector at Q7 -
// 127/sqrt(3) and 127/sqrt(2) - which keeps every entry the same length and
// saves renormalising nine times at init.
#define SR_D3 73
#define SR_D2 90

struct SrTarget { int8_t x, y, z; uint8_t w; };
static const SrTarget SR_LOOK[] PROGMEM = {
  // Wall centres, RAISED. Every landmark now sits above the equator: a gaze on
  // the vertical middle of a wall shows half an Eye on a face and half falling
  // off the bottom edge onto nothing, and the cube has no floor to catch it.
  // Lifting them puts the whole Eye on glass and keeps the light where it can
  // be seen.
  {  125,    0,   22, 2 }, { -125,    0,   22, 2 },
  {    0,  125,   22, 2 }, {    0, -125,   22, 2 },
  // the lid, straight up
  {    0,    0,  127, 3 },
  // the four TOP corners, where three faces meet at the pupil
  {  SR_D3,  SR_D3,  SR_D3, 3 }, { -SR_D3,  SR_D3,  SR_D3, 3 },
  {  SR_D3, -SR_D3,  SR_D3, 3 }, { -SR_D3, -SR_D3,  SR_D3, 3 },
  // the four top edges, seams running out of the Eye rather than across it
  {  SR_D2,     0,  SR_D2, 2 }, { -SR_D2,     0,  SR_D2, 2 },
  {     0,  SR_D2,  SR_D2, 2 }, {     0, -SR_D2,  SR_D2, 2 },
};

// The four top corners again, indexed, for the corner selector.
static const SrTarget SR_CORNER[4] PROGMEM = {
  {  SR_D3,  SR_D3,  SR_D3, 0 }, { -SR_D3,  SR_D3,  SR_D3, 0 },
  { -SR_D3, -SR_D3,  SR_D3, 0 }, {  SR_D3, -SR_D3,  SR_D3, 0 },
};
#define SR_NLOOK ((int)(sizeof(SR_LOOK) / sizeof(SR_LOOK[0])))

// A unit-ish vector from three signed bytes, renormalised to Q7.
static inline void sr_norm(int &x, int &y, int &z) {
  int m = (int)sqrtf((float)(x * x + y * y + z * z));
  if (m < 1) { x = 0; y = 0; z = 127; return; }
  x = (x * 127) / m; y = (y * 127) / m; z = (z * 127) / m;
}

// Any vector perpendicular to g, used as the slit's long axis.
//
// Crossing with world up gives that, EXCEPT when the Eye happens to look
// straight up or down, where the cross product collapses to nothing and the
// slit would spin wildly for the frames either side of it. Falling back to a
// different reference near the poles costs three compares and removes a
// twitch that is otherwise impossible to reproduce on purpose.
static void sr_upAxis(int gx, int gy, int gz, int &ux, int &uy, int &uz) {
  int rx = 0, ry = 0, rz = 127;
  if (gz > 110 || gz < -110) { rx = 0; ry = 127; rz = 0; }
  ux = gy * rz - gz * ry;
  uy = gz * rx - gx * rz;
  uz = gx * ry - gy * rx;
  ux >>= 7; uy >>= 7; uz >>= 7;
  sr_norm(ux, uy, uz);
}

static FX_RET mode_sauron() {
  if (!strip.isMatrix || !SEGMENT.is2D()) { SEGMENT.fill(SEGCOLOR(0)); FX_DONE; }
  const int cols = SEG_W, rows = SEG_H;
  if (cols < 8 || rows < 8) { SEGMENT.fill(SEGCOLOR(0)); FX_DONE; }
  const size_t n = (size_t)cols * rows;

  const bool cube = cfx_isCube(cols, rows);
  const int  B    = cube ? (cols / 3) : 1;
  const size_t m  = cfx_litCount(cols, rows, B, cube);

  // Room for the BUILD, not just the result.
  //
  // cfx_buildCube fills three full-rectangle arrays of n, and the three that
  // survive are only m long - 27B^2 written into 15B^2 if the result's own
  // space is used as the scratch, which is a heap overflow and a hard crash
  // with no traceback. Spectral Bloom can do that trick because it has six
  // arrays to lend; this effect keeps three, so it asks for the larger of the
  // two and gives the tail back after the build.
  const size_t scratch = cube ? (size_t)3 * n : 0;
  const size_t body    = (3 * m > scratch) ? 3 * m : scratch;
  const size_t need    = sizeof(SrState) + body;
  if (!SEGENV.allocateData(need)) { SEGMENT.fill(SEGCOLOR(0)); FX_DONE; }

  SrState *s  = (SrState *)SEGENV.data;
  int8_t  *cx = (int8_t *)(s + 1);
  int8_t  *cy = cx + m;
  int8_t  *cz = cy + m;

  const uint8_t want = (uint8_t)(cube ? 1 : 2);
  const bool init = (SEGENV.call == 0 || s->mode != want);
  if (init) {
    s->mode = want;
    s->flare = 0; s->peak = 0; s->hold = 0; s->ease = 65535;
    s->last0 = s->last1 = 255;
    s->pofAx = s->pofAy = 0; s->pofDx = s->pofDy = 0;
    s->pofE = 65535; s->pofHold = 0;
    s->clk[0] = s->clk[1] = 0;
    memset(s->spec, 0, sizeof(s->spec));
    s->nx = (uint32_t)hw_random16() << 8;
    s->ny = (uint32_t)hw_random16() << 8;
    s->nz = (uint32_t)hw_random16() << 8;
    s->gx = 90; s->gy = 60; s->gz = 40;
    { int a = s->gx, b = s->gy, c = s->gz; sr_norm(a, b, c);
      s->gx = (int8_t)a; s->gy = (int8_t)b; s->gz = (int8_t)c; }
    s->tx = s->gx; s->ty = s->gy; s->tz = s->gz;
    { int a, b, c; sr_upAxis(s->gx, s->gy, s->gz, a, b, c);
      s->ux = (int8_t)a; s->uy = (int8_t)b; s->uz = (int8_t)c; }

    if (cube) {
      int8_t *sc = cx;
      cfx_buildCube(sc, sc + n, sc + 2 * n, nullptr, nullptr, cols, rows, cube);
      // Compact the three rectangles onto the five lit faces - ONE ARRAY PER
      // PASS, in order, and not all three interleaved.
      //
      // Interleaved was wrong and the cube showed it. cy's destination starts
      // at m, which is still inside the FIRST scratch rectangle: at B=16,
      // writing cy[0] lands on offset 1280, which is holding the X coordinate
      // of the pixel at (32,26) in the middle band, and destroys it about a
      // thousand reads before it is wanted. 560 of 3840 writes did that.
      //
      // The corruption follows the scan order, which is why it looked like a
      // face problem rather than a memory one: the north band is read first and
      // came out almost clean, the middle band lost a slice, and the south band
      // - read last, after the most damage - banded worst. Positions that are
      // wrong by a little put neighbouring pixels on the wrong side of the
      // iris and reach thresholds, and a threshold crossed at the wrong place
      // IS a band.
      //
      // Doing one array at a time is safe because each pass only writes below
      // the rectangle it is reading, and the rectangles it has already finished
      // with are the only ones it is allowed to land in. Verified exhaustively
      // for B in 4, 8, 16, 32: no pass reads a byte a previous pass destroyed.
      for (int arr = 0; arr < 3; arr++) {
        const int8_t *from = sc + (size_t)arr * n;
        int8_t       *to   = cx + (size_t)arr * m;
        size_t j = 0;
        for (int y = 0; y < rows; y++)
          for (int x = 0; x < cols; x++) {
            if (cfx_gap(x, y, B)) continue;    // gap corner
            to[j++] = from[(size_t)y * cols + x];
          }
      }
    } else {
      cfx_buildCube(cx, cy, cz, nullptr, nullptr, cols, rows, cube);
    }

    // Normalise ONCE, and only on the cube. These are fixed for the life of
    // the effect, and a sqrtf per pixel per frame to recompute a constant is
    // the sort of thing that costs a cube its frame rate for nothing.
    //
    // A FLAT panel is left as coordinates, because normalising it destroys the
    // picture: cfx_pos gives a flat panel Z = 0 for every pixel, so every point
    // along a ray out of the centre normalises to the SAME direction. The
    // angular distance that draws the whole Eye then depends only on the angle
    // around the centre and not at all on the distance from it - which is why
    // flat mode came out as a fan of wedges rather than as an eye.
    if (cube) {
      for (size_t k = 0; k < m; k++) {
        int a = cx[k], b = cy[k], c = cz[k];
        sr_norm(a, b, c);
        cx[k] = (int8_t)a; cy[k] = (int8_t)b; cz[k] = (int8_t)c;
      }
    }
  }

  uint16_t dt = fx_dt8(s->clk);
  if (dt > 60) dt = 60;

  // --- audio ------------------------------------------------------------------
  um_data_t     *um  = cfx_getAudioData();
  const float    vol = *(float *)um->u_data[0];
  const uint8_t *fft = (uint8_t *)um->u_data[2];
  const CfxTempoState &tempo = cfx_tempo(um);
  // Always on. It was a checkbox and never wanted to be one - the pupil
  // constricting on the beat is most of what makes this read as an eye rather
  // than as a fire, and turning it off gives you a lava lamp. Freeing the box
  // is what makes room for Corner mode.
  const uint8_t beat = fx_lowBeat(um);
  if (beat > s->flare) s->flare = beat;
  { const int f = (int)s->flare - (int)fx_step(6, dt);
    s->flare = (uint8_t)(f < 0 ? 0 : f); }

  cfx_smoothSpec(s->spec, fft, 3);
  {
    int mx = 0;
    for (int i = 0; i < 16; i++) if (s->spec[i] > mx) mx = s->spec[i];
    if (mx > s->peak) s->peak = (uint8_t)mx;
    else { const int d = (int)s->peak - (int)fx_step(1, dt);
           s->peak = (uint8_t)((d < 0) ? 0 : d); }
  }
  const int pk = (s->peak < 40) ? 40 : (int)s->peak;
  int bass, mid, treb; cfx_bands(s->spec, bass, mid, treb);
  const int lvl = ((bass + mid + treb) * 255) / (3 * pk);

  // --- parameters ---------------------------------------------------------------
  const int sp = SEGMENT.speed;
  const int32_t adv = ((32 + (sp * 3)) * (int32_t)dt) / 23;
  s->nx += (uint32_t)adv;
  s->ny += (uint32_t)((adv * 3) / 4);
  s->nz += (uint32_t)((adv * 5) / 4);
  const uint16_t ox = (uint16_t)(s->nx >> 8), oy = (uint16_t)(s->ny >> 8),
                 oz = (uint16_t)(s->nz >> 8);

  // Wreath reach, in the same Q7 units the dot products land in. Intensity sets
  // the still size; the music pushes it out from there, so a quiet passage
  // still has an Eye and a loud one has it blazing.
  // Angle units: SR_ANG is a half turn, so 504 is 90 degrees and the far pole
  // is 1008. Working in ANGLE rather than in the sine of it is what lets the
  // wreath pass the terminator at all - a radius taken across the gaze folds
  // back on itself at 90 degrees and can never describe the far side.
  //
  // Wreath reaches the whole cube at maximum. At 255 the still reach alone is
  // a full half turn, so every pixel is inside it before the music adds
  // anything, and the Eye becomes a cube that is entirely on fire with a slit
  // cut in it. At 0 it is a hard bright pinpoint. That is the whole span.
  const int reach = 60 + ((int)SEGMENT.intensity * 948) / 255
                       + ((lvl > 255 ? 255 : lvl) * 110) / 255
                       + ((int)s->flare * 130) / 255;

  // Iris: the hard bright ring. Kept a fixed fraction of the wreath so the two
  // stay in proportion as the music breathes rather than the ring swimming
  // about inside its own flames.
  const int iris = 40 + ((int)SEGMENT.custom1 * 180) / 255;

  // The slit's shape is fixed now that custom2 picks a corner. 200 of 255 is
  // where it sat by default and where it reads best: narrow enough to be a
  // slit rather than a pupil, wide enough to survive being drawn on a
  // sixteen-pixel face. The pupil still CONSTRICTS on a flare, which is the
  // movement that sells it as an eye.
  const int slit = 200;
  // Half the iris, not three fifths. The slit used to fill so much of the
  // iris that there was nowhere for it to go - about ten units of travel at
  // the default, which is invisible. This leaves it room to glance while still
  // reading as a slit rather than a dot.
  const int pupB = 20 + iris / 2;                           // along the slit
  int pupA = pupB - (pupB * 3 * slit) / (4 * 255);           // across it
  pupA = pupA - (pupA * (int)s->flare) / 420;                // constrict
  if (pupA < 2) pupA = 2;

  // --- where the Eye looks ------------------------------------------------------
  // custom3 is FIVE BITS. See cfx_c3full.
  const int rest = cfx_c3full(SEGMENT.custom3);              // restlessness

  if (s->hold > dt) s->hold -= dt; else s->hold = 0;

  // Corner mode: keep the gaze inside the three faces you can actually see
  // when the cube is stood on a shelf and looked at from one side. custom2
  // chooses WHICH top corner is the centre of that view - it does not lock the
  // Eye to the corner, it decides which three faces are in play.
  const bool corner = SEGMENT.check2;
  const int  cSel   = ((int)SEGMENT.custom2 * 4) / 256;      // 0..3
  const int  cvx = (int8_t)pgm_read_byte(&SR_CORNER[cSel].x);
  const int  cvy = (int8_t)pgm_read_byte(&SR_CORNER[cSel].y);

  // check1 was Searching, which had stopped meaning anything: the Eye wanders
  // in silence now too, so there was no second behaviour for it to select.
  const bool gyro = SEGMENT.check1;
  const int  onBeat = (tempo.beat && tempo.confidence > 90) || tempo.hit || beat > 120;

  // Quiet is not the same as stopped.
  //
  // The gaze used to need lvl > 40 to move at all, so silence left the Eye
  // staring at one spot until the music came back - which reads as broken
  // rather than as calm. Below the threshold it now walks continuously
  // instead: it retargets the moment it arrives, over a long sweep, so the
  // Eye glides from face to face and never sits.
  const bool quiet   = (lvl < 45);
  const bool arrived = (s->ease >= 65535);
  const bool go = arrived ? (quiet || (!s->hold && (onBeat || rest > 200)))
                          : (!s->hold && onBeat && lvl > 45);
  if (go) {
    // A landmark, weighted, and biased AWAY from the current one so the sweep
    // is worth watching: a dart of a few degrees is indistinguishable from
    // drift.
    int total = 0;
    for (int k = 0; k < SR_NLOOK; k++) total += pgm_read_byte(&SR_LOOK[k].w);
    int nxv = s->gx, nyv = s->gy, nzv = s->gz, tries = 0, pick = 255;
    do {
      int r = (int)hw_random16() % (total > 0 ? total : 1), k = 0;
      while (k < SR_NLOOK - 1) {
        const int w = pgm_read_byte(&SR_LOOK[k].w);
        if (r < w) break;
        r -= w; k++;
      }
      // Not one of the last two. Thirteen landmarks picked with replacement
      // revisit often enough that the Eye looked like it was working through a
      // rota rather than searching, and a repeat inside three moves is what
      // makes it read that way.
      if (k == s->last0 || k == s->last1) continue;
      nxv = (int8_t)pgm_read_byte(&SR_LOOK[k].x);
      nyv = (int8_t)pgm_read_byte(&SR_LOOK[k].y);
      nzv = (int8_t)pgm_read_byte(&SR_LOOK[k].z);
      pick = k;
      const int d = (nxv * s->gx + nyv * s->gy + nzv * s->gz) >> 7;
      if (d < 90) break;                                     // far enough away
    } while (++tries < 10);
    if (pick != 255) { s->last1 = s->last0; s->last0 = (uint8_t)pick; }

    // EVERYWHERE BETWEEN, not just the thirteen.
    //
    // A landmark plus a few degrees of slop still only ever framed thirteen
    // shots. The landmarks are the positions that read best and they should
    // keep pulling, but the whole upper half wants to be reachable - the
    // interesting places are as often between two of them as on one.
    //
    // So: a free direction anywhere in the upper hemisphere, blended most of
    // the way toward the landmark that was drawn. The result clusters on the
    // readable geometry and thins out between, which is the distribution
    // wanted rather than either extreme - a rota of thirteen at one end, an
    // aimless twitch at the other.
    {
      int frx = (int)hw_random8() - 128;
      int fry = (int)hw_random8() - 128;
      // -105..127. Weighted upward, but it must be able to go WELL below the
      // equator: a wall is two thirds of the cube's visible height and cutting
      // the gaze off at the middle of it left the bottom third permanently
      // unvisited. The floor stops short of straight down, where the Eye would
      // centre on a face the cube does not have.
      int frz = ((int)hw_random8() * 232) / 255 - 105;
      sr_norm(frx, fry, frz);
      const int bl = 112;                            // ~44% of the way out
      nxv += ((frx - nxv) * bl) >> 8;
      nyv += ((fry - nyv) * bl) >> 8;
      nzv += ((frz - nzv) * bl) >> 8;
      if (nzv < -105) nzv = -105;
    }

    // Corner mode is a STRICT three-face cut: fold the direction into the
    // selected corner's octant. A gaze inside that octant can only light faces
    // whose normals it agrees with, which is exactly the three you can see
    // when the cube is looked at from there - so nothing lands round the back
    // where it cannot be seen, and the whole octant is still reachable rather
    // than a handful of points in it.
    if (corner) {
      nxv = (cvx > 0) ? (nxv < 0 ? -nxv : nxv) : (nxv > 0 ? -nxv : nxv);
      nyv = (cvy > 0) ? (nyv < 0 ? -nyv : nyv) : (nyv > 0 ? -nyv : nyv);
      // Z is left alone. Only the two WALLS and the lid are visible from a top
      // corner, and a wall runs all the way down - folding Z up as well would
      // have confined the Eye to the top of a view that is mostly wall.
    }
    sr_norm(nxv, nyv, nzv);
    s->tx = (int8_t)nxv; s->ty = (int8_t)nyv; s->tz = (int8_t)nzv;
    s->ease = 0;
    // 1.6 s down to 0.35 s across the restlessness control. Ignored while
    // quiet, where arrival alone is the trigger.
    s->hold = (uint16_t)(1600 - (rest * 1250) / 255);
  }

  // How long a sweep takes, in milliseconds, decided by the MUSIC.
  //
  // A fixed rate made the Eye move at the same pace over a ballad and a
  // drum-and-bass track, which is the one thing a thing that is supposed to be
  // hunting must not do. Locked to a tempo it crosses in one beat, so the
  // arrival lands with the music rather than near it; unlocked it free-runs;
  // quiet it takes its time. A hard beat then snaps the sweep shorter still,
  // so the velocity of the hit is in the movement and not only in the flare.
  int sweepMs;
  if (quiet)                                         sweepMs = 2600;
  else if (tempo.confidence > 90 && tempo.periodMs > 220)
                                                     sweepMs = (int)tempo.periodMs;
  else                                               sweepMs = 900;
  sweepMs -= (sweepMs * (int)s->flare) / 380;        // harder beat, faster sweep
  sweepMs  = (sweepMs * (330 - sp)) / 220;           // and the Sweep slider trims
  if (sweepMs < 120)  sweepMs = 120;
  if (sweepMs > 5000) sweepMs = 5000;

  // Eased, not stepped: an eye that cuts between angles reads as a dropped
  // frame, one that sweeps reads as searching. Sixteen bits through the sweep,
  // because at eight the slowest walk advanced by less than one count a frame
  // and stuck.
  if (s->ease < 65535) {
    const uint32_t inc = ((uint32_t)65535 * dt) / (uint32_t)sweepMs;
    const uint32_t e = (uint32_t)s->ease + (inc ? inc : 1);
    s->ease = (uint16_t)(e > 65535 ? 65535 : e);
    // LINEAR while quiet, eased with music.
    //
    // ease8InOutCubic has almost no velocity at either end, which is exactly
    // right for a dart - it leaves hard and settles - and exactly wrong for a
    // walk, because the Eye then pauses at every landmark and the smooth glide
    // becomes step, stop, step, stop. Measured, half the frames of a silent
    // run had the gaze effectively stationary. A straight ramp holds its speed
    // all the way across and only changes direction on arrival.
    const uint8_t g8 = (uint8_t)(s->ease >> 8);
    const uint8_t f  = quiet ? g8 : ease8InOutCubic(g8);
    int gxv = cfx_lerp8((uint8_t)(s->gx + 128), (uint8_t)(s->tx + 128), f) - 128;
    int gyv = cfx_lerp8((uint8_t)(s->gy + 128), (uint8_t)(s->ty + 128), f) - 128;
    int gzv = cfx_lerp8((uint8_t)(s->gz + 128), (uint8_t)(s->tz + 128), f) - 128;
    sr_norm(gxv, gyv, gzv);
    if (s->ease >= 65535) { gxv = s->tx; gyv = s->ty; gzv = s->tz; }
    s->gx = (int8_t)gxv; s->gy = (int8_t)gyv; s->gz = (int8_t)gzv;
    int a, b, c; sr_upAxis(s->gx, s->gy, s->gz, a, b, c);
    s->ux = (int8_t)a; s->uy = (int8_t)b; s->uz = (int8_t)c;
  }

  // GYRO: hold the gaze still in the ROOM while the cube turns under it.
  //
  // The gaze is kept in cube coordinates, so ordinarily it turns with the cube
  // and the Eye is painted on the shell like a decal. Rotating the stored gaze
  // into cube frame every drawn frame instead pins it to the world: pick the
  // cube up and turn it, and the Eye stays looking at the same corner of the
  // room while the faces slide past underneath. That is the whole illusion of
  // something inside rather than something printed on.
  //
  // basis is cube -> world and is a rotation, so world -> cube is its
  // TRANSPOSE - the columns read as rows. Nine multiplies, once a frame, not
  // once a pixel.
  int egx = s->gx, egy = s->gy, egz = s->gz;
  int eux = s->ux, euy = s->uy, euz = s->uz;
  if (gyro) {
    const CfxImuState &imu = cfx_imu();
    if (imu.valid) {
      const int16_t *b = imu.basis;
      const int tx = egx, ty = egy, tz = egz;
      egx = ((int)b[0] * tx + (int)b[3] * ty + (int)b[6] * tz) >> 7;
      egy = ((int)b[1] * tx + (int)b[4] * ty + (int)b[7] * tz) >> 7;
      egz = ((int)b[2] * tx + (int)b[5] * ty + (int)b[8] * tz) >> 7;
      sr_norm(egx, egy, egz);
      // The slit stays upright in the ROOM as well, which is the half of it
      // that sells the effect: an eye whose pupil rolls with the case looks
      // painted on however still the gaze is.
      int a, bb, c;
      sr_upAxis(egx, egy, egz, a, bb, c);
      eux = a; euy = bb; euz = c;
    }
  }

  // --- the pupil glances inside the iris ---------------------------------------
  // A second search, at a different scale.
  //
  // The Eye hunts across the cube; the pupil hunts inside the iris. It is the
  // pupil's POSITION against the iris that moves, not its angle - an eye
  // glances by sliding its pupil across the socket, and a slit that rotates
  // instead reads as the whole head tilting.
  //
  // Only the pupil moves. The iris and the wreath stay centred on the gaze,
  // which is what makes the offset legible: a bright ring holding still while
  // the black shape inside it slides is unmistakable, where a ring and a pupil
  // moving together is just the Eye looking somewhere else.
  //
  // Bounded by the room actually available, so the slit reaches the rim of the
  // iris and stops rather than wandering out into the flames.
  const int roomA = (iris - pupA) / 2;
  const int roomB = (iris - pupB) / 2;
  if (s->pofHold > dt) s->pofHold -= dt; else s->pofHold = 0;
  if (s->pofE >= 65535 && !s->pofHold) {
    s->pofAx = (int8_t)(s->pofAx + s->pofDx);
    s->pofAy = (int8_t)(s->pofAy + s->pofDy);
    const int tx = (roomA > 0) ? ((int)(hw_random8() % (2 * roomA + 1)) - roomA) : 0;
    const int ty = (roomB > 0) ? ((int)(hw_random8() % (2 * roomB + 1)) - roomB) : 0;
    s->pofDx = (int8_t)(tx - s->pofAx);
    s->pofDy = (int8_t)(ty - s->pofAy);
    s->pofE = 0;
    // Its own schedule, shorter than the gaze's. Restless drives both, so they
    // quicken together without ever landing together.
    s->pofHold = (uint16_t)(900 - (rest * 620) / 255);
  }
  if (s->pofE < 65535) {
    // A glance is FAST - a third of a sweep. It is a flick, not a drift, and
    // the two motions stay separable because one snaps while the other glides.
    const uint32_t rms = (uint32_t)sweepMs / 3;
    const uint32_t inc = ((uint32_t)65535 * dt) / (rms ? rms : 1);
    const uint32_t e = (uint32_t)s->pofE + (inc ? inc : 1);
    s->pofE = (uint16_t)(e > 65535 ? 65535 : e);
  }
  const uint8_t pofF = ease8InOutCubic((uint8_t)(s->pofE >> 8));
  const int pofX = (int)s->pofAx + (((int)s->pofDx * pofF) / 255);
  const int pofY = (int)s->pofAy + (((int)s->pofDy * pofF) / 255);

  // The right-hand axis, across the slit.
  int rx = (int)euy * egz - (int)euz * egy;
  int ry = (int)euz * egx - (int)eux * egz;
  int rz = (int)eux * egy - (int)euy * egx;
  rx >>= 7; ry >>= 7; rz >>= 7;
  sr_norm(rx, ry, rz);


  // A HIGH floor. The usual (vol, 1.0, 40) makes overall brightness follow the
  // volume, which on real music held the whole Eye at about half and took sigma
  // from 33 to 15 - the picture was not darker in an interesting way, it was
  // uniformly turned down. Volume already has a job here: it pushes the wreath
  // out. Letting it dim the fire as well means a quiet passage has a small DIM
  // eye instead of a small bright one, and small and bright is the whole point.
  const uint8_t drive = cfx_drive(vol, 0.6f, 170);

  // --- paint --------------------------------------------------------------------
  CFX_NET_PREP();
  for (int y = 0; y < rows; y++) {
    CFX_NET_ROW(y);
    for (int x = 0; x < cols; x++) {
      CFX_NET_SKIP(x);
      const size_t i = (size_t)cfx_cidx(x, y, cols, B, cube);
      const int px = cx[i], py = cy[i], pz = cz[i];

      int ang, da, db;
      if (cube) {
        // Q14 dot products, kept to five bits of extra precision rather than
        // shifted straight back to Q7. At Q7 a sixteen-pixel face spans only a
        // handful of distinct radii, so every threshold in here landed on the
        // same few values across whole runs of pixels and the Eye came out in
        // concentric BANDS. Five more bits costs nothing and the rings go.
        const int dd = (px * egx + py * egy + pz * egz) >> 5;
        da = (px * rx + py * ry + pz * rz) >> 5;
        db = (px * eux + py * euy + pz * euz) >> 5;
        // Angle from the gaze: 0 at the pupil, 504 at the terminator, 1008 at
        // the far pole. Monotonic the whole way round, which is what lets the
        // wreath cover the back of the cube rather than stopping at 90 degrees.
        ang = 504 - dd;
      } else {
        // FLAT: the panel is the eye seen face on. Distance from the gaze
        // point in the plane, in the same units the cube branch produces, so
        // every threshold below reads identically. The slit is vertical by
        // construction here rather than by a rotated axis - on a flat panel
        // there is no reason for it to be anything else, and a slit that
        // wandered its own angle just looked unsteady.
        //
        // The gaze point is the 3-D gaze's own X and Y, so the walk, the darts
        // and the tempo lock all still drive it: looking up puts the Eye in the
        // middle of the panel and looking out moves it to an edge.
        // FOUR, chosen so the panel spans about the same angular range the
        // cube does. At two, a panel corner was only 718 units from the centre
        // against the sphere's 1008, so every reach setting covered far more of
        // a flat panel than of a cube: the shared default measured mean 107 and
        // 11% dark flat against 41 and 57% on the cube - the same slider giving
        // a washed-out panel and a dark cube. At four they read alike, and
        // maximum still swallows the whole panel.
        da = (px - egx) * 4;
        db = (py - egy) * 4;
        ang = (int)sqrtf((float)(da * da + db * db));
      }

      uint8_t heat = 0;
      {
        if (ang < 400) {
          // Elliptical pupil, in the plane across the gaze. Only tested near
          // the front, where da and db still mean what they look like.
          // Offset applies to the PUPIL only - ang, which draws the iris and
          // the wreath, is untouched above.
          const int ea = ((da - pofX) * 128) / (pupA > 0 ? pupA : 1);
          const int eb = ((db - pofY) * 128) / (pupB > 0 ? pupB : 1);
          if (ea * ea + eb * eb < 128 * 128) goto sr_done;   // the slit
        }

        if (ang < iris) {
          // White-hot at the pupil's edge, falling to deep red at the rim.
          const int t = (ang * 255) / (iris > 0 ? iris : 1);
          heat = (uint8_t)(255 - (t * 120) / 255);
        } else {
          const int outr = ang - iris;
          if (outr < reach) {
            // Flame. Sampled in world space and dragged outward, so licks
            // travel away from the Eye and cross a seam without shearing.
            const int pull = (outr * 3) / 4;
            const uint8_t nz1 = inoise8((uint16_t)(px * 5 + ox + pull),
                                        (uint16_t)(py * 5 + oy + pull),
                                        (uint16_t)(pz * 5 + oz));
            const uint8_t nz2 = inoise8((uint16_t)(px * 11 - oy),
                                        (uint16_t)(py * 11 + oz),
                                        (uint16_t)(pz * 11 - ox));
            int turb = (nz1 * 3 + nz2) >> 2;
            // Falls to nothing at the rim, so the wreath has an edge rather
            // than a haze.
            const int env = 255 - (outr * 255) / (reach > 0 ? reach : 1);
            // Bias hard, then fall off ONCE. Squaring the envelope on top of
            // the bias put the whole wreath at palette index 10 - which on a
            // fire palette is black - and left a bright ring on an unlit cube.
            int h = (turb - 66) * 3;                        // bias: dark gaps
            if (h > 255) h = 255;
            if (h < 0) h = 0;
            h = (h * env) / 255;
            heat = (uint8_t)((h * 235) / 255);
          }
        }

        // A gentle fall toward the far pole, so the Eye still sits ON the cube
        // rather than being printed through it - but nothing like the old hard
        // cut at the terminator, which is the other half of what stopped a
        // maximum wreath from ever reaching the back.
        heat = (uint8_t)(((int)heat * (150 + ((1008 - ang) * 105) / 1008)) / 255);
      }
      sr_done:;

      uint32_t c;
      if (heat == 0) {
        c = 0;
      } else {
        // Heat straight onto the palette. On a fire palette that is the
        // literal reading; on any other it is still dark-to-bright, which is
        // the only property this effect needs from it.
        c = SEGMENT.color_from_palette(heat, false, true, 0);
        // Whiten the very core, which no palette can be relied on to do. It is
        // what separates "a hot ring" from "a hole in something burning".
        if (heat > 210) {
          const int w = ((heat - 210) * 255) / 45;
          uint8_t r = (c >> 16) & 0xFF, g = (c >> 8) & 0xFF, b = c & 0xFF;
          r = (uint8_t)(r + ((255 - r) * w) / 255);
          g = (uint8_t)(g + ((255 - g) * w) / 255);
          b = (uint8_t)(b + ((255 - b) * w) / 255);
          c = RGBW32(r, g, b, 0);
        }
      }
      SEGMENT.setPixelColorXY(x, y, mq_scale(c, drive));
    }
  }
  FX_DONE;
}

static const char _data_FX_MODE_SAURON[] PROGMEM =
  // Wreath sweeps the whole span, so the default sits low in its travel on
  // purpose. Measured against real music: at 0 the Eye is a hard pinpoint with
  // three quarters of the cube dark; at 255 the still reach alone is a full
  // half turn and every pixel is inside the fire before the music adds a thing,
  // leaving 12% dark - a burning cube with a slit cut in it. The shipped 80
  // lands at mean 41, sigma 58, 56% dark over a 45 second run.
  //
  // The lid takes 31% of the light against a 20% share of the surface. That is
  // the gaze table doing its job, not a bug: a low corner splits the slit
  // across two faces at an angle and cuts the wreath into three pieces, so the
  // Eye only ever looks at a face centre, the lid, a TOP corner or a top edge.
  "Ace 3-D Sauron@Sweep,Wreath,Iris,Corner,Restless,Gyro,Corner mode,Flat mode;;!;2f;sx=110,ix=80,c1=70,c2=0,c3=14,pal=35";


// ---------------------------------------------------------------------------
// Registration - joins the effect bank, which decides whether this effect
// claims one of the device's limited effect slots. See cube_fx_bank.h.
// ---------------------------------------------------------------------------
static CfxBankReg cube_fx_31_sauron_reg(&mode_sauron, _data_FX_MODE_SAURON);
