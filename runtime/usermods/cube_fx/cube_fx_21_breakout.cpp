#include "wled.h"
#include "cube_fx_common.h"
#include "ace_ui_bus.h"
#include "cube_fx_bank.h"

// ===========================================================================
// 21. ACE 3-D BREAKOUT  (two-player, playable from the knobs)
// ===========================================================================
// Breakout wrapped around the cube, with the bricks as a CAP over the top: the
// whole top face plus the first few rows of every wall. The ball climbs a
// wall, crosses the top face, and comes down the far side.
//
// ---------------------------------------------------------------------------
// ONE RULER OVER FIVE FACES
// ---------------------------------------------------------------------------
// A wall-only cylinder cannot host this. Bricks on the top face would sit
// somewhere the ball can never reach, so the board could never be cleared.
// Instead every pixel gets one (u, d) coordinate, the same trick
// cube_fx_20_matrix_rain uses:
//
//        u          0 .. ringW-1   column around the ring
//        d = 0      centre of the top face
//        d = topd-1 the rim
//        d = topd   first wall row
//        d = dmax   the paddle row, at the open bottom edge
//
// So "up" is one direction the whole way from the bottom edge to the middle of
// the lid, and the ball needs no special case at the fold. Bricks fill d = 0
// up to brickDepth, which is the entire lid plus however far down the walls
// the Brick depth slider asks for - capped at halfway so there is always clear
// wall left to rally in.
//
// Crossing the centre is not a bounce: d going negative means the ball passed
// over the middle of the lid and is now on the OPPOSITE side of the cube, so
// it reappears at u + ringW/2. That is what the geometry actually does, and it
// is the best thing in the effect to watch.
//
// Near the centre every column converges, so a constant du would whip the ball
// around the middle. `boUScale()` fades u-motion out as d approaches 0, which
// makes the ball travel straight through the centre instead - which is also
// what a real ball crossing the pole would do.
//
// ---------------------------------------------------------------------------
// CONTROL
// ---------------------------------------------------------------------------
// The effect asks for the knobs every frame with aceUiGameWant(). While it is
// running, a CLICK on the Now Playing screen hands them over; a 500 ms BACK
// hold (or Home) gives them back. The offer is a timestamp, not a flag, so
// switching to any other effect drops it on its own - see ace_ui_bus.h.
//
// Encoder 0 drives paddle 0, encoder 1 drives paddle 1. With one encoder, or
// with "Auto P2" checked, paddle 1 plays itself - so this is a game on a
// one-knob build and two-player the moment a second knob exists.
//
// Any paddle nobody is driving plays itself, which means that WITH THE KNOBS
// IN THE MENU BOTH PADDLES ARE AUTOMATIC and this is simply an ambient effect
// that happens to be a real game of Breakout. Nothing has to be configured for
// that; "Auto P1" and "Auto P2" only exist to force it while you are also
// playing, either to hand one paddle to the cube or to pin it to demo mode.
//
// On a cube with NO PANEL there is no Now Playing screen to click, so the
// effect takes the knobs by itself as soon as it starts - see the note at the
// grab below. On a cube with no encoders either, nothing is driveable and it
// runs as the demo.
//
// Ball position and velocity are Q8 (256 = one cell) so the ball can travel at
// any speed and still be tested against a grid, with no floats in the frame
// path.
// ---------------------------------------------------------------------------

#ifndef BO_BRICK_W
  #define BO_BRICK_W 2          // brick width in ring columns
#endif
#ifndef BO_MAXCOL
  #define BO_MAXCOL 254         // 255 is the "not on the board" marker in col[]
#endif
#ifndef BO_LIVES
  #define BO_LIVES 3
#endif
#ifndef BO_KNOB_STEP
  #define BO_KNOB_STEP 256      // exactly one column per detent - see boSnap()
#endif
#ifndef BO_SERVE_MIN_MS
  #define BO_SERVE_MIN_MS 120   // ignore the click that started the rally
#endif
#ifndef BO_SERVE_AUTO_MS
  #define BO_SERVE_AUTO_MS 6000 // nudge an idle human along
#endif
#ifndef BO_SERVE_AI_MS
  #define BO_SERVE_AI_MS 900    // an AI holding the ball is never going to click
#endif
#ifndef BO_STALL_MS
  #define BO_STALL_MS 7000      // no brick and no paddle for this long = stuck, re-serve
#endif
#ifndef BO_IDLE_RELEASE_MS
  #define BO_IDLE_RELEASE_MS 45000  // knobs untouched this long: give them back, go to demo
#endif

// Ball speed is per 23 ms, matching fx_step's calibration, so the game plays
// the same on a cube running 20 fps and one running 60.
#define BO_TICK_MS 23

struct BoState {
  int32_t  bu, bd;              // ball position, Q8. bu wraps at ringW<<8
  int32_t  vu, vd;              // ball velocity, Q8 per BO_TICK_MS
  int32_t  pad[2];              // paddle centres, Q8, wrap with the ring
  uint16_t bricksLeft;
  uint16_t bcols;
  uint8_t  bdepth;              // brick rows in use, measured in d
  uint8_t  lives;
  uint8_t  level;
  uint8_t  served;
  uint8_t  mode;
  uint8_t  flash;
  uint8_t  hitPad;              // who touched it last - where a rescue re-serves
  uint8_t  parkOn;              // which paddle the un-served ball rides
  uint8_t  grabbed;             // panel-less builds take the knobs once, not every frame
  uint8_t  chaser;              // which auto paddle owns the ball - sticky, see the AI block
  uint16_t serveAt;
  uint16_t actAt;               // last brick break or paddle touch, for the stall watchdog
  uint8_t  clk[2];              // fx_dt8 store
};

// Where a paddle may sit, as a half-open range of Q8 ring columns. Co-op is
// the whole loop; a Versus mode clamps player p to its own half here and
// nothing else in the file has to change.
static inline void boPaddleRange(int p, int32_t ringQ, int32_t &lo, int32_t &hi) {
  (void)p; lo = 0; hi = ringQ;
}

static inline int32_t boWrap(int32_t v, int32_t m) {
  if (m <= 0) return 0;
  v %= m;                       // modulo, not a while loop: a fast ball can be
  if (v < 0) v += m;            // many ring-widths out in one step
  return v;
}

// Shortest signed distance from a to b on a loop: what makes a paddle chase
// the ball the SHORT way round the cube rather than unwrapping the long way
// when the ball crosses the seam.
static inline int32_t boLoopDelta(int32_t a, int32_t b, int32_t m) {
  int32_t d = boWrap(b - a, m);
  if (d > m / 2) d -= m;
  return d;
}

static inline bool boOnPaddle(int32_t padQ, int halfW, int u, int ringW) {
  const int32_t d = boLoopDelta(padQ, ((int32_t)u << 8) + 128, (int32_t)ringW << 8);
  const int32_t w = (int32_t)(halfW + 1) << 8;
  return d > -w && d < w;
}

// Move a paddle by `delta` without letting it pass through the other one.
//
// Works on the GAP, measured one way round the ring as a plain 0..ringQ
// number, and clamps it to [minSep, ringQ - minSep]. Both ends of that range
// are the same physical situation - the two paddles touching - approached from
// opposite sides, so the pair are confined to complementary arcs whose shared
// boundaries move as they do.
//
// It takes a DELTA rather than a target on purpose. Deciding which side the
// mover is on from a signed shortest-path distance looks equivalent and is
// not: that distance flips sign as a paddle passes the antipode, so a paddle
// walking away from its partner would be judged to have crossed the moment it
// got more than half a ring away, and get snapped straight back to its
// partner's side. Accumulating the gap instead has no such discontinuity.
static int32_t boBlock(int32_t from, int32_t delta, int32_t other,
                       int32_t ringQ, int32_t minSep) {
  if (minSep * 2 >= ringQ) return boWrap(from + delta, ringQ);  // ring too small to separate
  const int32_t g0 = boWrap(from - other, ringQ);               // gap, 0 .. ringQ
  int32_t g1 = g0 + delta;
  if (g1 < minSep)         g1 = minSep;
  if (g1 > ringQ - minSep) g1 = ringQ - minSep;
  return boWrap(other + g1, ringQ);
}

// Paddles sit on whole columns, so the lit span is always an ODD number of
// pixels (2*halfW+1) with a real centre pixel. Without this the centre falls
// between two columns half the time and there is no place on the paddle that
// returns the ball straight.
static inline int32_t boSnap(int32_t q) {
  return ((q >> 8) << 8) + 128;
}

// One AI step for paddle p, closing on `aim`. Skill is a SPEED CAP, not aim:
// a capped chaser misses fast balls and wide angles, so it loses believably
// instead of being either perfect or useless. It is blocked by the other
// paddle like anything else, so it has to go the long way round rather than
// sliding through - which is also what stops it parking on top of a player.
static void boChase(BoState *s, int p, int32_t aim, int32_t ringQ,
                    int32_t minSep, uint16_t dt, int skill) {
  const int32_t d    = boLoopDelta(s->pad[p], aim, ringQ);
  const int32_t cap  = (int32_t)(24 + ((skill * 40) >> 5)) * (int32_t)dt / BO_TICK_MS;
  const int32_t step = (d > cap) ? cap : ((d < -cap) ? -cap : d);
  s->pad[p] = boSnap(boBlock(s->pad[p], step, s->pad[p ^ 1], ringQ, minSep));
}

// How much of the ball's sideways velocity applies at depth d. Full on the
// walls; fading to nothing at the centre of the lid, where every column meets
// and a constant du would spin the ball on the spot.
static inline int32_t boUScale(int32_t dQ, int topd) {
  if (topd <= 0) return 256;
  const int32_t half = (int32_t)topd << 7;          // half the lid radius, Q8
  if (dQ >= half) return 256;
  if (dQ <= 0) return 0;
  return (dQ * 256) / half;
}

// ---------------------------------------------------------------------------
// (u, d) for every pixel. Lid is radial from the centre; walls continue the
// same ruler downward. Mirrors cube_fx_20_matrix_rain's mapping so the two
// effects agree about which way the cube is wound.
// ---------------------------------------------------------------------------
static int boEdge(int t, int den, int B) {
  int idx = ((t + den) * B) / (2 * den);
  if (idx < 0)     idx = 0;
  if (idx > B - 1) idx = B - 1;
  return idx;
}

static void boBuildMap(uint8_t *col, uint8_t *dep, int cols, int rows,
                       bool cube, int B, int topd) {
  for (int y = 0; y < rows; y++) {
    for (int x = 0; x < cols; x++) {
      const size_t i = (size_t)y * cols + x;

      if (!cube) { col[i] = (uint8_t)x; dep[i] = (uint8_t)y; continue; }

      const int bx = x / B, by = y / B, lx = x % B, ly = y % B;
      if (bx != 1 && by != 1) { col[i] = 255; dep[i] = 0; continue; }   // gap corner

      if (bx == 1 && by == 1) {                          // TOP: radial, centre out
        const int ax = 2 * lx - (B - 1), ay = 2 * ly - (B - 1);
        const int aax = (ax < 0) ? -ax : ax, aay = (ay < 0) ? -ay : ay;
        const int r2  = (aax > aay) ? aax : aay;
        dep[i] = (uint8_t)(r2 >> 1);
        if (r2 == 0) { col[i] = 0; continue; }            // dead centre, odd B only

        // An exact diagonal leaves through a CORNER and has to be broken by
        // quadrant. Folding it into one of the two edges instead leaves east
        // and west unnamed on the innermost ring.
        int c;
        if (aay > aax) {
          const int idx = boEdge(ax, aay, B);
          c = (ay < 0) ? idx : (2 * B + (B - 1 - idx));                 // N : S
        } else if (aax > aay) {
          const int idx = boEdge(ay, aax, B);
          c = (ax > 0) ? (B + idx) : (3 * B + (B - 1 - idx));           // E : W
        } else {
          c = (ay < 0) ? ((ax < 0) ? 0 : B) : ((ax > 0) ? (2 * B) : (3 * B));
        }
        col[i] = (uint8_t)c;
        continue;
      }

      int bu, bv;                                        // walls, cfx_buildBand order
      if      (by == 0) { bu = lx;                 bv = B - 1 - ly; }   // NORTH
      else if (bx == 2) { bu = B + ly;             bv = lx;         }   // EAST
      else if (by == 2) { bu = 2 * B + B - 1 - lx; bv = ly;         }   // SOUTH
      else              { bu = 3 * B + B - 1 - ly; bv = B - 1 - lx; }   // WEST
      col[i] = (uint8_t)bu;
      dep[i] = (uint8_t)(topd + bv);
    }
  }
}

// Seed the brick field FROM THE PIXELS, so only cells that actually have a
// pixel somewhere get a brick. Filling the grid blindly would leave cells that
// no pixel maps to - unreachable, unclearable, and the board could never be
// finished. Near the centre of the lid the columns converge hard, so this is
// not a rare edge case; it is most of the lid.
static void boResetBricks(uint8_t *brick, BoState *s, const uint8_t *col,
                          const uint8_t *dep, size_t n, int bcols, int bdepth) {
  memset(brick, 0, (size_t)bdepth * bcols);
  s->bricksLeft = 0;
  for (size_t i = 0; i < n; i++) {
    if (col[i] == 255) continue;
    const int d = dep[i];
    if (d >= bdepth) continue;
    uint8_t *cell = &brick[d * bcols + (col[i] / BO_BRICK_W)];
    if (!*cell) { *cell = 1; s->bricksLeft++; }
  }
}

static void boPark(BoState *s, int dmax, uint8_t who) {
  s->served  = 0;
  s->parkOn  = (who < 2) ? who : 0;
  s->bu      = s->pad[s->parkOn];
  s->bd      = (int32_t)(dmax - 1) << 8;
  s->vu      = 0;
  s->vd      = 0;
  s->serveAt = (uint16_t)strip.now;
  s->actAt   = (uint16_t)strip.now;
}

static void boServe(BoState *s, int speed) {
  s->served = 1;
  s->vd     = -speed;                                    // up, toward the bricks
  s->vu     = (hw_random8() & 1) ? speed / 3 : -speed / 3;
}

static FX_RET mode_breakout() {
  if (!strip.isMatrix || !SEGMENT.is2D()) { SEGMENT.fill(SEGCOLOR(0)); FX_DONE; }
  const int cols = SEG_W, rows = SEG_H;
  if (cols < 6 || rows < 6) { SEGMENT.fill(SEGCOLOR(0)); FX_DONE; }
  const size_t n = (size_t)cols * rows;

  const bool cubeRaw = cfx_isCube(cols, rows);
  const int  B       = cubeRaw ? (cols / 3) : 1;
  // A ring wider than the sentinel would alias a real column onto "not on the
  // board", so fall back to the flat mapping rather than mis-draw it.
  const bool cube    = cubeRaw && (4 * B) <= BO_MAXCOL;

  const int ringW = cube ? (4 * B) : cols;
  const int topd  = cube ? ((B + 1) / 2) : 0;            // lid depth, 0 when flat
  const int wallH = cube ? B : rows;
  const int dmax  = topd + wallH - 1;                    // the paddle row
  if (wallH < 5 || ringW < 8) { SEGMENT.fill(SEGCOLOR(0)); FX_DONE; }

  const int bcols = ringW / BO_BRICK_W;
  // Bricks never come more than halfway down the walls: past that there is no
  // room left to rally, and the paddles would be catching the ball straight
  // off the brick face.
  const int wallMax  = wallH / 2;
  const int maxDepth = topd + wallMax;

  // Sized for the DEEPEST brick field, not the slider's current value: the
  // buffer must not resize when a slider moves, or allocateData() would hand
  // back a different block mid-rally and the game would restart every time
  // somebody nudged Brick depth.
  const size_t need = sizeof(BoState) + 2 * n + (size_t)maxDepth * bcols;
  if (!SEGENV.allocateData(need)) { SEGMENT.fill(SEGCOLOR(0)); FX_DONE; }

  BoState *s     = (BoState *)SEGENV.data;               // offset 0: malloc alignment holds
  uint8_t *col   = SEGENV.data + sizeof(BoState);
  uint8_t *dep   = col + n;
  uint8_t *brick = dep + n;

  aceUiGameWant();                                       // every frame - see ace_ui_bus.h

  // A cube with no OLED has no Now Playing screen to click on, so the knobs
  // can never be handed over the normal way - the game would be permanently
  // unplayable on exactly the builds where it is the only thing the knob could
  // usefully do. Take them on arrival instead.
  //
  // Once only, tracked in segment state rather than re-asserted every frame:
  // otherwise a deliberate BACK release would be undone on the next frame and
  // there would be no way to give the knobs back at all. Selecting the effect
  // again resets the segment and re-grabs, which is the behaviour you want.
  //
  // With no encoders at all there is nothing to grab and nothing to drive the
  // paddles with, so this stays out of the way and both sides play themselves.
  {
    AceUiBus &ui = aceUi();
    if (!ui.screenReady && ui.encCount > 0 && !s->grabbed) {
      s->grabbed   = 1;
      ui.game.active = true;
    }

    // Hand the knobs back after a spell with nothing touching them.
    //
    // Without this, taking control once kept it FOREVER: game.active is only
    // cleared by an explicit BACK or Home, and while it is set the knobs are
    // routed to the paddles, so you cannot even navigate away. Walk off
    // mid-rally and whichever paddle was yours simply stops - which is exactly
    // the "auto mode never engages" this is meant to fix, because the effect
    // was still, correctly, treating you as present.
    //
    // Skipped on a panel-less build: there the menu is not reachable, so a
    // release would strand the knobs with no way to ask for them back.
    if (ui.screenReady && ui.game.active &&
        (millis() - ui.lastInputMs) > BO_IDLE_RELEASE_MS) {
      aceUiGameRelease();
    }
  }
  const bool playing = aceUiGameActive();

  const int halfW = 1 + (((int)SEGMENT.custom1 * (ringW / 8)) >> 9);
  int wallBrick   = 1 + (((int)SEGMENT.custom2 * (wallMax - 1)) >> 8);
  if (wallBrick > wallMax) wallBrick = wallMax;
  const int bdepth = topd + wallBrick;

  const uint8_t want = (uint8_t)(cube ? 1 : 2);
  if (SEGENV.call == 0 || s->mode != want || s->bcols != (uint16_t)bcols) {
    boBuildMap(col, dep, cols, rows, cube, B, topd);
    s->mode   = want;
    s->bcols  = (uint16_t)bcols;
    s->bdepth = (uint8_t)bdepth;
    s->lives  = BO_LIVES;
    s->level  = 0;
    s->flash  = 0;
    s->hitPad  = 0;
    s->grabbed = 0;
    s->chaser  = 0;
    s->pad[0] = boSnap((int32_t)(ringW / 4) << 8);
    s->pad[1] = boSnap((int32_t)(3 * ringW / 4) << 8);
    s->clk[0] = s->clk[1] = 0;
    boResetBricks(brick, s, col, dep, n, bcols, bdepth);
    boPark(s, dmax, 0);
  }

  // Depth slider moved: rebuild the field. Cheap, and re-seeding from the
  // pixels is the only way to keep bricksLeft honest.
  if (s->bdepth != (uint8_t)bdepth) {
    s->bdepth = (uint8_t)bdepth;
    boResetBricks(brick, s, col, dep, n, bcols, bdepth);
  }

  // Safety net: an empty board with the ball in play cannot be finished, so
  // treat it as a cleared level rather than leaving a dead cube on screen.
  if (!s->bricksLeft) {
    s->level++;
    boResetBricks(brick, s, col, dep, n, bcols, bdepth);
    boPark(s, dmax, s->hitPad);
  }

  const int32_t ringQ = (int32_t)ringW << 8;

  const uint16_t dt = fx_dt8(s->clk);

  // --- input --------------------------------------------------------------------
  // Detents are consumed even when not playing, so turns made while the menu
  // had the knobs cannot pile up and teleport a paddle on the next serve.
  const int16_t k0 = aceUiGameTakeAxis(0);
  const int16_t k1 = aceUiGameTakeAxis(1);
  const bool    f0 = aceUiGameTakeFire(0);
  const bool    f1 = aceUiGameTakeFire(1);

  // A paddle is human only while the knobs are actually handed over AND its
  // Auto box is clear. Everything else plays itself - so with nobody holding
  // the knobs BOTH paddles are automatic and the effect is an ambient demo
  // playing a real game, with no setting to remember. The Auto boxes force
  // that on even while you are playing, which is also how you take just one of
  // the two paddles.
  // Each paddle needs an encoder to actually be driven by. Without one the
  // "human" side would simply freeze, which looks like a hung effect rather
  // than a missing knob - so an undriveable paddle falls through to the AI.
  const bool human0 = playing && !SEGMENT.check1 && (aceUi().encCount >= 1);
  const bool human1 = playing && !SEGMENT.check2 && (aceUi().encCount >= 2);

  // Closest the centres may get. Each paddle lights 2*halfW+1 columns, so a
  // separation of exactly that puts them edge to edge - touching, with no gap
  // and no overlap. It was 2*(halfW+1), one column more, which left a permanent
  // dead column between them that the ball could drop through.
  const int32_t minSep = (int32_t)(2 * halfW + 1) << 8;

  if (human0) {
    int32_t lo, hi;
    boPaddleRange(0, ringQ, lo, hi);
    s->pad[0] = boSnap(boBlock(s->pad[0], (int32_t)k0 * BO_KNOB_STEP, s->pad[1], ringQ, minSep));
  }
  if (human1)
    s->pad[1] = boSnap(boBlock(s->pad[1], (int32_t)k1 * BO_KNOB_STEP, s->pad[0], ringQ, minSep));

  if (!human0 || !human1) {
    const int32_t ball  = s->served ? s->bu : s->pad[s->parkOn < 2 ? s->parkOn : 0];
    const int     skill = SEGMENT.custom3;

    // With BOTH on auto they split the ring rather than both lunging at the
    // ball: the nearer one takes it, the other holds the far side. Two
    // chasers on one ball bunch up against each other and leave half the cube
    // undefended, which reads as broken rather than automated.
    int chaser = -1;
    if (!human0 && !human1) {
      int32_t d0 = boLoopDelta(s->pad[0], ball, ringQ); if (d0 < 0) d0 = -d0;
      int32_t d1 = boLoopDelta(s->pad[1], ball, ringQ); if (d1 < 0) d1 = -d1;

      // Sticky, with a margin before the roles swap. Taking whichever is
      // nearer outright makes the pair trade jobs on almost every frame while
      // they are near-equidistant - and because the two targets are half a
      // ring apart, each paddle's aim then jumps back and forth by that much
      // every frame. Capped step speed turns that into a twitch on the spot:
      // both paddles look busy and neither ever arrives at the ball.
      uint8_t c = (s->chaser < 2) ? s->chaser : 0;
      const int32_t margin = ringQ / 8;
      if (c == 0 ? (d1 + margin < d0) : (d0 + margin < d1)) c ^= 1;
      s->chaser = c;
      chaser = (int)c;
    }

    for (int p = 0; p < 2; p++) {
      if (p == 0 ? human0 : human1) continue;
      const int32_t aim = (chaser >= 0 && p != chaser) ? boWrap(ball + ringQ / 2, ringQ) : ball;
      boChase(s, p, aim, ringQ, minSep, dt, skill);
    }
  }

  // --- ball ---------------------------------------------------------------------
  const int speed = 40 + (((int)SEGMENT.speed * 150) >> 8) + s->level * 5;

  if (!s->served) {
    s->bu = s->pad[s->parkOn < 2 ? s->parkOn : 0];       // rides its paddle until served
    s->bd = (int32_t)(dmax - 1) << 8;
    // An AI holding the ball serves itself promptly - it is never going to
    // click - which is what keeps the unattended demo moving. A human gets the
    // long timeout, as a nudge rather than a shove.
    const bool     parkHuman = (s->parkOn == 0) ? human0 : human1;
    const uint16_t held      = (uint16_t)strip.now - s->serveAt;
    if ((f0 || f1) && held > BO_SERVE_MIN_MS) boServe(s, speed);
    else if (held > (parkHuman ? BO_SERVE_AUTO_MS : BO_SERVE_AI_MS)) boServe(s, speed);
  } else {
    // Sub-step so a fast ball cannot pass through a brick row or the paddle
    // between frames: one step per half cell of travel.
    const int32_t mu = s->vu < 0 ? -s->vu : s->vu;
    const int32_t md = s->vd < 0 ? -s->vd : s->vd;
    const int32_t big = (mu > md) ? mu : md;
    int steps = (int)(((big * dt) / BO_TICK_MS) / 128) + 1;
    if (steps > 8) steps = 8;

    for (int it = 0; it < steps && s->served; it++) {
      const int32_t us = boUScale(s->bd, topd);
      s->bu = boWrap(s->bu + (((s->vu * us) >> 8) * dt) / (BO_TICK_MS * steps), ringQ);
      s->bd += (s->vd * dt) / (BO_TICK_MS * steps);

      // Over the middle of the lid and down the far side. Not a bounce - this
      // is the ball continuing in a straight line across the top of the cube.
      //
      // vd MUST flip with the position. d is a radius, so a ball that was
      // heading inward is heading OUTWARD once it is past the pole; mirroring
      // bd while leaving vd negative traps the ball at d≈0, re-crossing every
      // step and hopping half the ring each time - it looks like the ball
      // vanished into the middle of the lid, and nothing can ever reach it
      // again.
      if (s->bd < 0) {
        s->bd = -s->bd;
        s->bu = boWrap(s->bu + ringQ / 2, ringQ);
        s->vd = -s->vd;

        // The innermost ring is a POINT, not an arc: every column converges at
        // the centre of the lid, so a ball crossing there passes through all
        // of the cells at d = 0 at once.
        //
        // Without this those cells belong to whichever few columns the centre
        // pixels happen to map to - the four diagonals - so the last bricks on
        // the board could only be struck by arriving along one of exactly four
        // headings, and were effectively impossible to finish on.
        if (s->bdepth > 0) {
          for (int cc = 0; cc < bcols; cc++) {
            if (!brick[cc]) continue;                    // row d = 0
            brick[cc] = 0;
            if (s->bricksLeft) s->bricksLeft--;
            s->flash = qadd8(s->flash, 40);
            s->actAt = (uint16_t)strip.now;
          }
        }
      }

      const int cd = (int)(s->bd >> 8);
      const int cu = (int)(s->bu >> 8);

      if (cd < s->bdepth) {
        uint8_t *cell = &brick[cd * bcols + (cu / BO_BRICK_W)];
        if (*cell) {
          *cell = 0;
          if (s->bricksLeft) s->bricksLeft--;
          s->vd    = -s->vd;                             // no nudge: the cell is empty now
          s->flash = qadd8(s->flash, 90);
          s->actAt = (uint16_t)strip.now;                // progress: the watchdog stands down
          if (!s->bricksLeft) {
            s->level++;
            boResetBricks(brick, s, col, dep, n, bcols, bdepth);
            boPark(s, dmax, s->hitPad);
          }
        }
      }

      if (s->served && s->vd > 0 && cd >= dmax) {
        int caught = -1;
        for (int p = 0; p < 2; p++) if (boOnPaddle(s->pad[p], halfW, cu, ringW)) { caught = p; break; }
        if (caught >= 0) {
          s->bd = (int32_t)dmax << 8;

          // Where on the paddle it landed SETS the angle. It used to be added
          // to the existing vu, which wound the ball up to its sideways cap
          // over a few hits and left it orbiting the ring almost horizontally,
          // never coming back down.
          // Quantised to whole columns, so the paddle offers a small fixed set
          // of angles instead of a continuum. The paddle is 2*halfW+1 columns
          // wide with a true centre (boSnap), and that centre column returns
          // the ball dead straight - a shot the player can actually aim,
          // rather than one they happen to land on.
          const int32_t off  = boLoopDelta(s->pad[caught], s->bu, ringQ);
          int32_t offCells = (off + (off >= 0 ? 128 : -128)) / 256;
          if (offCells >  halfW) offCells =  halfW;
          if (offCells < -halfW) offCells = -halfW;
          const int32_t vmax = speed / 2;                // gentler than it was: 3/4 speed
          int32_t nvu = (halfW > 0) ? (offCells * vmax) / halfW : 0;
          s->vu = nvu;

          // The steeper the sideways angle the slower the climb, but never so
          // slow that the rally stalls - a third of full speed is the floor.
          const int32_t mag = nvu < 0 ? -nvu : nvu;
          int32_t nvd = speed - mag / 2;
          if (nvd < speed / 3) nvd = speed / 3;
          s->vd = -nvd;

          s->hitPad = (uint8_t)caught;
          s->flash  = qadd8(s->flash, 40);
          s->actAt  = (uint16_t)strip.now;
        } else if (s->bd > ((int32_t)(dmax + 1) << 8)) {
          if (s->lives) s->lives--;
          s->flash = 255;
          if (!s->lives) {
            s->lives = BO_LIVES;
            s->level = 0;
            boResetBricks(brick, s, col, dep, n, bcols, bdepth);
          }
          boPark(s, dmax, s->hitPad);
        }
      }
    }
  }

  // --- stall watchdog -----------------------------------------------------------
  // A ball in play that has broken no brick and touched no paddle for this long
  // is not in a rally any more, it is stuck. The known way in was the centre of
  // the lid (fixed above), but the general shape of the failure - a ball that
  // reaches nothing, on a board nobody can finish - deserves a net regardless
  // of which corner of the geometry finds it next.
  //
  // It re-serves from the paddle that touched it last, so the rescue puts the
  // ball back with whoever was playing rather than silently favouring player 1.
  if (s->served && (uint16_t)((uint16_t)strip.now - s->actAt) > BO_STALL_MS) {
    boPark(s, dmax, s->hitPad);
    boServe(s, speed);
    s->flash = qadd8(s->flash, 140);
  }

  if (s->flash) {
    const uint8_t f = fx_fade(18, dt);
    s->flash = (uint8_t)(s->flash > f ? s->flash - f : 0);
  }

  // --- render -------------------------------------------------------------------
  const uint8_t glow = 90 + (((int)SEGMENT.intensity * 165) >> 8);
  const uint8_t lift = (uint8_t)(s->flash >> 2);
  const int ballU = (int)(s->bu >> 8), ballD = (int)(s->bd >> 8);

  // The ball is drawn by NEAREST pixel, after the field, rather than by an
  // exact (u, d) match. Columns converge hard toward the middle of the lid, so
  // most (u, d) pairs there have no pixel at all - an exact match made the
  // ball vanish for as long as it was near the centre, which is also where it
  // is least obvious that it has not simply been lost.
  int     bestX = -1, bestY = 0;
  int32_t bestCost = INT32_MAX;

  size_t i = 0;
  for (int y = 0; y < rows; y++) {
    for (int x = 0; x < cols; x++, i++) {
      const int u = col[i];
      if (u == 255) { SEGMENT.setPixelColorXY(x, y, 0); continue; }    // gap corner
      const int d = dep[i];

      // Depth dominates: a pixel one row off is worse than one several columns
      // off, because the rows are what the player reads the ball's height from.
      const int32_t dd   = (d > ballD) ? (d - ballD) : (ballD - d);
      int32_t       du   = boLoopDelta((int32_t)u, (int32_t)ballU, (int32_t)ringW);
      if (du < 0) du = -du;
      const int32_t cost = dd * 1024 + du;
      if (cost < bestCost) { bestCost = cost; bestX = x; bestY = y; }
      uint32_t c = 0;
      bool isPad = false;

      if (d < s->bdepth && brick[d * bcols + (u / BO_BRICK_W)]) {
        // Palette walks with depth, so the cap reads as courses of brick from
        // the lid down rather than one slab of colour.
        const uint8_t idx = (uint8_t)((d * 210) / (s->bdepth ? s->bdepth : 1));
        c = mq_scale(SEGMENT.color_from_palette(idx, false, false, 0), glow);
      } else if (d == dmax) {
        const bool p0 = boOnPaddle(s->pad[0], halfW, u, ringW);
        const bool p1 = boOnPaddle(s->pad[1], halfW, u, ringW);
        if (p0 || p1) {
          // Dimmed until the knobs are actually yours, so "am I driving this?"
          // is answered by looking at the cube.
          //
          // WHITE IS THE BALL AND NOTHING ELSE. Overlapping paddles get their
          // own third colour rather than the obvious blend - cyan and orange
          // average out to a pale grey that reads as the ball sitting on the
          // paddle row, which is exactly the frame where you most need to know
          // where the ball actually is.
          const uint8_t k = playing ? 255 : 90;
          if (p0 && p1) c = mq_scale(RGBW32(190, 70, 255, 0), k);   // both, stacked
          else if (p0)  c = mq_scale(RGBW32(60, 200, 255, 0), k);   // player 1
          else          c = mq_scale(RGBW32(255, 120, 40, 0), k);   // player 2
          isPad = true;
        }
      } else if (d > dmax - (int)s->lives && d <= dmax - 1 && !s->served
                 && boOnPaddle(s->pad[0], 0, u, ringW)) {
        c = RGBW32(120, 90, 20, 0);                      // lives, stacked over the server
      }

      // The event flash deliberately skips the paddles. A full-strength miss
      // flash would wash them to white, which is the ball's colour and nobody
      // else's - and it would do it at the exact moment the ball was lost and
      // the player is scanning the bottom row for it.
      if (lift && c && !isPad) c = color_add(c, mq_scale(RGBW32(255, 255, 255, 0), lift), true);
      SEGMENT.setPixelColorXY(x, y, c);
    }
  }

  // Ball last, over whatever it is passing across.
  if (bestX >= 0) SEGMENT.setPixelColorXY(bestX, bestY, RGBW32(255, 255, 255, 0));
  FX_DONE;
}

static const char _data_FX_MODE_BREAKOUT[] PROGMEM =
  "Ace 3-D Breakout@Ball speed,Glow,Paddle width,Brick depth,AI skill,Auto P1,Auto P2,Flat mode;;!;2f;sx=120,ix=200,c1=110,c2=140,c3=16,o1=0,o2=0";



// ---------------------------------------------------------------------------
// Registration - joins the effect bank, which decides whether this effect
// claims one of the device's limited effect slots. See cube_fx_bank.h.
// ---------------------------------------------------------------------------
static CfxBankReg cube_fx_21_breakout_reg(&mode_breakout, _data_FX_MODE_BREAKOUT);
