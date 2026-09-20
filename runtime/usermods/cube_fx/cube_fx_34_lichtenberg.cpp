#include "wled.h"
#include "cube_fx_common.h"
#include "cube_fx_bank.h"

// ===========================================================================
// Ace 3-D Lichtenberg - a discharge that crosses the whole cube
// ===========================================================================
// A beat seeds a point. From there a leader walks the surface toward the point
// FURTHEST AWAY from where it started, branching as it goes, never allowed to
// touch a path already drawn. When it arrives - or runs out of legal ground -
// the figure holds, throws one wave outward into the empty pixels around it,
// and then erases itself from the beginning, so the tail chases the head off
// the cube.
//
// The pacing is deliberately split. SEEDING is on the beat and so are the
// flashbacks, but the journey itself runs in real seconds and ignores tempo
// entirely. That is what lets one strike take four or five seconds to cross the
// solid while still starting when the music says so - the effect rolls over you
// instead of twitching once per beat.
//
// ---------------------------------------------------------------------------
// A CELLULAR WALK, NOT A CONTINUOUS ONE
// ---------------------------------------------------------------------------
// Every rule here is about PIXELS and their neighbours - which one is free,
// which has a lit neighbour, which is nearest the goal - so the walk happens on
// the pixel graph itself rather than by drifting a float position around and
// sampling whatever it lands on. The neighbour table built at init is what
// makes that cheap, and because cfx_rev follows the fold when it is built, a
// neighbour across a seam is an ordinary entry: the walk, the spacing rule and
// the wave all cross the cube's folds without a single special case.
//
// ---------------------------------------------------------------------------
// THE RULES, IN ORDER
// ---------------------------------------------------------------------------
//   SEED     a beat picks a free surface point. The goal is its antipode - the
//            furthest pixel away - so every strike crosses the whole solid.
//   STEP     of the four neighbours take the free one that most advances toward
//            the goal, scored by dot product with the goal direction. No
//            per-strike distance field is needed for that.
//   SPACE    a pixel may not be taken if any neighbour belongs to a different
//            branch. That leaves one dark pixel between any two paths, which is
//            what keeps the figure readable however dense the branching gets.
//   BRANCH   a fork aims somewhere new, so it leaves the parent instead of
//            running beside it and dying against the spacing rule.
//   ARRIVE   when every head has stopped, the figure holds briefly.
//   WAVE     then one wave is pushed into the free pixels around the whole
//            figure. It carries the shape of the bolt and collapses wherever it
//            meets anything already lit.
//   ERASE    after the hold the path decays from the SEED forward, so the lit
//            length slides away across the cube rather than fading in place.
//   FLASH    while lit path remains, a beat can send a flashback running back
//            down it toward the start.
// ===========================================================================

#define LB_STRIKES  8           // journeys in flight at once, at most
#define LB_HEADS    48          // branch heads across all of them
#define LB_SEEDHEADS 3          // heads a seed starts with, fanned apart
// A head that has stopped getting closer to the goal for this many steps has
// gone as far as this surface allows. The cube has no bottom face, so the
// true antipode of a lid seed is often not a pixel at all - waiting for the
// head to ARRIVE there means waiting for it to trap itself against its own
// trail instead, which is what made path lengths swing between 17 and 133.
#define LB_STALL    14
#define LB_BRANCHES 31          // branches per strike - 5 bits, see LB_OWN
#define LB_ORDMAX   250         // longest path tracked, in pixels
#define LB_WAVEMAX  31          // how far a wave reaches, in pixels - 5 bits
#define LB_WAVETAIL 9           // pixels of trail behind the wave front
#define LB_FBTAIL   7           // pixels of trail behind a flashback

// Occupancy packs the owning strike and branch into one byte, which is what
// lets the spacing rule ask "is this someone else's?" with a single compare.
// Zero means empty, so branch numbering starts at one.
#define LB_OWN(strike, branch)  ((uint8_t)(((strike) << 5) | (branch)))
#define LB_OWNSTRIKE(v)         ((uint8_t)((v) >> 5))
#define LB_OWNBRANCH(v)         ((uint8_t)((v) & 31))

// A pixel the leader has drawn sits at this level; a flashback is what makes it
// bright. Dim enough that the two read as separate events.
#define LB_PATHLVL  120

enum { LB_GROW = 0, LB_HOLD, LB_ERASE };

struct LbHead {
  uint16_t at;                  // compact pixel index
  int8_t   tx, ty, tz;          // this head's own aim, x100
  uint8_t  strike;
  uint8_t  branch;              // 1..LB_BRANCHES
  uint8_t  ord;                 // pixels walked from the seed
  uint8_t  grace;               // steps still exempt from the spacing rule
  int16_t  bestReach;           // furthest toward the goal this head has been
  uint8_t  stall;               // steps since it last got any closer
  uint8_t  active;
};

struct LbStrike {
  uint8_t active;
  uint8_t phase;                // LB_GROW / LB_HOLD / LB_ERASE
  uint8_t hue;
  int8_t  gx, gy, gz;           // goal direction, x100 - the seed's antipode
  uint8_t nextBranch;
  uint8_t maxOrd;               // furthest any head of this strike reached
  uint8_t eraseAt;              // path at or below this ord is decaying
  int16_t holdMs;
  uint8_t fbAt;                 // flashback position; 255 = none running
  uint8_t waveAt;               // wave front, 1..LB_WAVEMAX; 0 = no wave
  uint8_t waveAmp;
};

struct LbState {
  uint8_t  mode;
  uint8_t  clk[2];
  uint8_t  spec[16];
  uint8_t  bpk[16];
  uint16_t glowHue;             // Q8 palette cursor for the waves
  uint8_t  hiAvg;                // slow mean of the upper bins, for snare onsets
  uint16_t snareGap;             // ms since the last snare, for its refractory
  float    gacc;                // fractional pixels of growth carried over
  float    wacc;                // ditto for the waves
  LbHead   head[LB_HEADS];
  LbStrike st[LB_STRIKES];
};

static FX_RET mode_lichtenberg() {
  if (!strip.isMatrix || !SEGMENT.is2D()) { SEGMENT.fill(SEGCOLOR(0)); FX_DONE; }
  const int cols = SEG_W, rows = SEG_H;
  if (cols < 8 || rows < 8) { SEGMENT.fill(SEGCOLOR(0)); FX_DONE; }

  const bool cube = cfx_isCube(cols, rows);
  const int  B    = cube ? (cols / 3) : 1;
  const int  Bq   = cube ? B : 1;
  const size_t lut = cube ? (size_t)6 * Bq * Bq : 0;
  const size_t m  = cfx_litCount(cols, rows, B, cube);

  const size_t need = sizeof(LbState) + lut * sizeof(uint16_t)
                    + 8 * m + 4 * m * sizeof(uint16_t);
  if (!SEGENV.allocateData(need)) { SEGMENT.fill(SEGCOLOR(0)); FX_DONE; }

  LbState  *s   = (LbState *)SEGENV.data;
  uint16_t *rev = (uint16_t *)(s + 1);
  uint8_t  *own = (uint8_t *)(rev + lut);   // strike|branch, 0 = free
  uint8_t  *ord = own + m;                  // pixels from the seed
  uint8_t  *hue = ord + m;                  // palette entry
  uint8_t  *lvl = hue + m;                  // brightness
  uint8_t  *wv  = lvl + m;                  // strike|wave step, 0 = no wave
  int8_t   *px3 = (int8_t *)(wv + m);       // surface direction, x100
  int8_t   *py3 = px3 + m;
  int8_t   *pz3 = py3 + m;
  uint16_t *nbr = (uint16_t *)(pz3 + m);    // four neighbours per pixel

  const uint8_t want = (uint8_t)(cube ? 1 : 2);
  if (SEGENV.call == 0 || s->mode != want) {
    s->mode = want; s->clk[0] = s->clk[1] = 0;
    s->glowHue = 0; s->hiAvg = 0; s->snareGap = 0; s->gacc = s->wacc = 0.0f;
    for (int i = 0; i < 16; i++) { s->spec[i] = 0; s->bpk[i] = 0; }
    for (int i = 0; i < LB_HEADS; i++)   s->head[i].active = 0;
    for (int i = 0; i < LB_STRIKES; i++) s->st[i].active = 0;
    for (size_t i = 0; i < m; i++) {
      own[i] = 0; ord[i] = 0; hue[i] = 0; lvl[i] = 0; wv[i] = 0;
    }

    if (cube) {
      for (size_t k = 0; k < lut; k++) rev[k] = 0xFFFF;
      for (int y = 0; y < rows; y++)
        for (int x = 0; x < cols; x++) {
          if (cfx_gap(x, y, B)) continue;
          const size_t ci = (size_t)cfx_cidx(x, y, cols, B, cube);
          float X, Y, Z; cfx_pos(x, y, cols, rows, B, cube, X, Y, Z);
          int f, a, b; cfx_face((int)(X * 127.0f), (int)(Y * 127.0f),
                                (int)(Z * 127.0f), f, a, b);
          int ai = ((a + 128) * Bq) >> 8, bi = ((b + 128) * Bq) >> 8;
          if (ai < 0) ai = 0; else if (ai >= Bq) ai = Bq - 1;
          if (bi < 0) bi = 0; else if (bi >= Bq) bi = Bq - 1;
          rev[((size_t)f * Bq + bi) * Bq + ai] = (uint16_t)ci;
        }
    }

    // Directions and neighbours, built together because both come from the same
    // walk over the lit pixels.
    for (int y = 0; y < rows; y++)
      for (int x = 0; x < cols; x++) {
        if (cube && cfx_gap(x, y, B)) continue;
        const size_t ci = (size_t)cfx_cidx(x, y, cols, B, cube);
        float X, Y, Z; cfx_pos(x, y, cols, rows, B, cube, X, Y, Z);
        if (cube) {
          float L = sqrtf(X * X + Y * Y + Z * Z);
          if (L < 0.0001f) L = 1.0f;
          X /= L; Y /= L; Z /= L;
        }
        px3[ci] = (int8_t)(X * 100.0f);
        py3[ci] = (int8_t)(Y * 100.0f);
        pz3[ci] = (int8_t)(Z * 100.0f);

        uint16_t *nb4 = nbr + ci * 4;
        if (cube) {
          int f, a, b; cfx_face((int)(X * 127.0f), (int)(Y * 127.0f),
                                (int)(Z * 127.0f), f, a, b);
          int ai = ((a + 128) * Bq) >> 8, bi = ((b + 128) * Bq) >> 8;
          if (ai < 0) ai = 0; else if (ai >= Bq) ai = Bq - 1;
          if (bi < 0) bi = 0; else if (bi >= Bq) bi = Bq - 1;
          nb4[0] = cfx_rev(rev, Bq, f, ai - 1, bi);
          nb4[1] = cfx_rev(rev, Bq, f, ai + 1, bi);
          nb4[2] = cfx_rev(rev, Bq, f, ai,     bi - 1);
          nb4[3] = cfx_rev(rev, Bq, f, ai,     bi + 1);
        } else {
          nb4[0] = (x > 0)        ? (uint16_t)(ci - 1)    : 0xFFFF;
          nb4[1] = (x < cols - 1) ? (uint16_t)(ci + 1)    : 0xFFFF;
          nb4[2] = (y > 0)        ? (uint16_t)(ci - cols) : 0xFFFF;
          nb4[3] = (y < rows - 1) ? (uint16_t)(ci + cols) : 0xFFFF;
        }
      }
  }

  uint16_t dt = fx_dt8(s->clk);
  if (dt > 60) dt = 60;

  // --- audio ------------------------------------------------------------------
  um_data_t     *um  = cfx_getAudioData();
  const float    vol = *(float *)um->u_data[0];
  const uint8_t *fft = (uint8_t *)um->u_data[2];
  CfxTempoState &tp  = cfx_tempo(um);
  cfx_smoothSpec(s->spec, fft, 150);

  // --- parameters ---------------------------------------------------------------
  const int  gainI   = 40 + ((int)SEGMENT.intensity * 215) / 255;
  const int  fork    = (int)SEGMENT.custom1;
  const int  glow    = (int)SEGMENT.custom2;
  const int  overlap = (int)cfx_c3full(SEGMENT.custom3);
  const bool doFlash = SEGMENT.check1;
  const bool ground  = SEGMENT.check2;

  const bool locked = (tp.confidence >= 64 && tp.periodMs > 0);

  // Journeys allowed in flight at once. At zero a strike must finish and clear
  // the surface before the next may seed; at full, every beat starts one.
  int allowed = 1 + (overlap * (LB_STRIKES - 1)) / 255;
  if (allowed < 1) allowed = 1; else if (allowed > LB_STRIKES) allowed = LB_STRIKES;

  // Real seconds, not beats. This is the control that stops it twitching.
  //
  // The floor is 10 px/s, not 4. The bottom of the range used to crawl slowly
  // enough that a crossing stopped reading as one movement, so the whole lower
  // third of the slider was unusable. Raising the floor would have sped up the
  // default too, so the default slider position moved down to compensate and
  // lands on the same speed it did before.
  const float pxPerSec = 10.0f + (float)SEGMENT.speed * (50.0f / 255.0f);

  // --- what counts as "on the beat" -----------------------------------------
  // Three sources, because a track will give you any of them and the effect
  // should land on whichever is there: the predicted beat when the tempo lock is
  // good, the kick, and the snare.
  //
  // fx_lowBeat only watches bass, so it is deaf to a snare or a clap - which on
  // a lot of material is the transient you actually hear. The upper bins get
  // their own onset test: energy well above its own slow mean, with a refractory
  // gap so one hit does not register as three.
  const bool kick = (tp.hit != 0);
  bool snare = false;
  {
    int hi = 0;
    for (int k = 7; k < 15; k++) hi += (int)s->spec[k];
    hi >>= 3;
    s->snareGap = (uint16_t)((s->snareGap + dt > 4000) ? 4000 : s->snareGap + dt);
    if (hi > (int)s->hiAvg + 28 && hi > 42 && s->snareGap > 110) {
      snare = true; s->snareGap = 0;
    }
    s->hiAvg = (uint8_t)(((int)s->hiAvg * 15 + hi) >> 4);
  }

  // Seeding stays at one per beat while the tempo is locked, so the Overlap
  // slider keeps its meaning; without a lock it follows the transients rather
  // than a free-running timer that ignores the music.
  const bool onBeat = locked ? (tp.beat != 0) : (kick || snare);
  // Everything else fires on whichever of the three arrives first.
  const bool accent = onBeat || kick || snare;

  // --- seed a journey -------------------------------------------------------
  if (onBeat) {
    int live = 0, slot = -1;
    for (int k = 0; k < LB_STRIKES; k++) {
      if (s->st[k].active) live++; else if (slot < 0) slot = k;
    }
    if (slot >= 0 && live < allowed) {
      int best = 0, bestRise = -1;
      for (int k = 0; k < 16; k++) {
        const int rise = (int)s->spec[k] - (int)s->bpk[k];
        if (rise > bestRise) { bestRise = rise; best = k; }
      }
      // A free pixel to start from. A handful of tries is enough; if they all
      // land on something lit the beat simply passes without a strike.
      size_t seed = (size_t)-1;
      for (int t = 0; t < 24; t++) {
        size_t c;
        if (cube && ground) {
          // Ground strike: start on the lid, so the journey runs over an edge
          // and down a wall on its way to the far side.
          const int lx = B + (int)(hw_random8() % (uint8_t)B);
          const int ly = B + (int)(hw_random8() % (uint8_t)B);
          c = (size_t)cfx_cidx(lx, ly, cols, B, cube);
        } else {
          c = (size_t)(hw_random16() % (uint16_t)m);
        }
        if (c < m && !own[c] && !lvl[c] && !wv[c]) { seed = c; break; }
      }
      if (seed != (size_t)-1) {
        LbStrike &S = s->st[slot];
        S.active = 1; S.phase = LB_GROW; S.hue = (uint8_t)((best * 255) / 15);
        S.nextBranch = 1; S.maxOrd = 0; S.eraseAt = 0;
        S.holdMs = 0; S.fbAt = 255; S.waveAt = 0; S.waveAmp = 0;
        // The goal is the antipode of the seed, so the walk crosses the solid.
        S.gx = (int8_t)(-px3[seed]); S.gy = (int8_t)(-py3[seed]);
        S.gz = (int8_t)(-pz3[seed]);

        own[seed] = LB_OWN(slot, 1); ord[seed] = 0;
        hue[seed] = S.hue; lvl[seed] = LB_PATHLVL;

        int made = 0;
        for (int q = 0; q < LB_HEADS && made < LB_SEEDHEADS; q++) {
          if (s->head[q].active) continue;
          LbHead &H = s->head[q];
          H.active = 1; H.at = (uint16_t)seed; H.strike = (uint8_t)slot;
          H.branch = S.nextBranch++; H.ord = 0; H.grace = 2;
          H.bestReach = -32000; H.stall = 0;
          // All aiming at the goal, each leaning somewhere different, so one of
          // them boxing itself in does not end the whole journey.
          H.tx = (int8_t)((int)hw_random8() - 128);
          H.ty = (int8_t)((int)hw_random8() - 128);
          H.tz = (int8_t)((int)hw_random8() - 128);
          made++;
        }
      }
    }
  }
  for (int k = 0; k < 16; k++) s->bpk[k] = s->spec[k];

  // --- walk the heads -------------------------------------------------------
  s->gacc += pxPerSec * (float)dt * 0.001f;
  int steps = (int)s->gacc;
  if (steps > 4) { steps = 4; s->gacc = 0.0f; } else s->gacc -= (float)steps;

  for (int st = 0; st < steps; st++) {
    for (int q = 0; q < LB_HEADS; q++) {
      LbHead &H = s->head[q];
      if (!H.active) continue;
      LbStrike &S = s->st[H.strike];
      if (!S.active || S.phase != LB_GROW) { H.active = 0; continue; }

      const uint8_t mine = LB_OWN(H.strike, H.branch);
      const uint16_t *nb4 = nbr + (size_t)H.at * 4;

      int bestJ = -1, bestScore = -1000000;
      for (int d = 0; d < 4; d++) {
        const uint16_t j = nb4[d];
        if (j == 0xFFFF || j >= m) continue;
        if (own[j] || lvl[j]) continue;                 // taken, or still fading

        // SPACING. A pixel beside somebody else's path may not be used, which
        // leaves one dark pixel between any two branches. A head is exempt on
        // its first step, because a fork necessarily starts beside its parent.
        if (!H.grace) {
          bool touch = false;
          const uint16_t *nb2 = nbr + (size_t)j * 4;
          for (int e = 0; e < 4 && !touch; e++) {
            const uint16_t k2 = nb2[e];
            if (k2 == 0xFFFF || k2 >= m) continue;
            if (own[k2] && own[k2] != mine) touch = true;
          }
          if (touch) continue;
        }

        // Toward the goal, plus this head's own aim at half weight - that is
        // what makes a fork take a different route rather than the same one.
        const int score = (int)px3[j] * S.gx + (int)py3[j] * S.gy + (int)pz3[j] * S.gz
                        + ((((int)px3[j] * H.tx + (int)py3[j] * H.ty
                           + (int)pz3[j] * H.tz)) >> 1);
        if (score > bestScore) { bestScore = score; bestJ = (int)j; }
      }

      if (H.grace) H.grace--;
      if (bestJ < 0 || H.ord >= LB_ORDMAX) { H.active = 0; continue; }

      const size_t j = (size_t)bestJ;
      H.at = (uint16_t)j;
      if (H.ord < 255) H.ord++;
      own[j] = mine; ord[j] = H.ord; hue[j] = S.hue; lvl[j] = LB_PATHLVL;
      if (H.ord > S.maxOrd) S.maxOrd = H.ord;

      // Far enough. Either it has genuinely reached the far side, or it has
      // stopped making progress toward it - both mean this head is done.
      const int reach = (int)px3[j] * S.gx + (int)py3[j] * S.gy + (int)pz3[j] * S.gz;
      if (reach > 8200) { H.active = 0; continue; }
      if (reach > (int)H.bestReach + 20) { H.bestReach = (int16_t)reach; H.stall = 0; }
      else if (++H.stall > LB_STALL) { H.active = 0; continue; }

      // BRANCH.
      if (S.nextBranch <= LB_BRANCHES && (int)hw_random8() < (fork >> 3)) {
        for (int r = 0; r < LB_HEADS; r++) {
          if (s->head[r].active) continue;
          LbHead &N = s->head[r];
          N.active = 1; N.at = (uint16_t)j; N.strike = H.strike;
          N.branch = S.nextBranch++; N.ord = H.ord; N.grace = 1;
          N.bestReach = H.bestReach; N.stall = 0;
          N.tx = (int8_t)((int)hw_random8() - 128);
          N.ty = (int8_t)((int)hw_random8() - 128);
          N.tz = (int8_t)((int)hw_random8() - 128);
          break;
        }
      }
    }
  }

  // --- strike lifecycle -----------------------------------------------------
  s->glowHue = (uint16_t)(s->glowHue + (uint32_t)dt * 40u);
  const int holdMs = 90 + (glow * 360) / 255;

  for (int k = 0; k < LB_STRIKES; k++) {
    LbStrike &S = s->st[k];
    if (!S.active) continue;

    if (S.phase == LB_GROW) {
      bool any = false;
      for (int q = 0; q < LB_HEADS && !any; q++)
        if (s->head[q].active && s->head[q].strike == k) any = true;
      if (!any) { S.phase = LB_HOLD; S.holdMs = (int16_t)holdMs; }
    } else if (S.phase == LB_HOLD) {
      // The hold is a MINIMUM, then it waits for the next accent. The wave is
      // the loudest thing this effect does and it used to fire whenever the walk
      // happened to finish, which is nowhere in particular. Now it lands with
      // the music. The negative bound is a timeout, so a lost tempo cannot leave
      // a finished figure sitting there for ever.
      S.holdMs = (int16_t)(S.holdMs - (int)dt);
      if (S.holdMs <= 0 && (accent || S.holdMs <= -900)) {
        S.phase = LB_ERASE;
        S.waveAt = 1; S.waveAmp = 255;
        // Push the wave into every free pixel touching the finished figure.
        for (size_t i = 0; i < m; i++) {
          if (!own[i] || LB_OWNSTRIKE(own[i]) != k) continue;
          const uint16_t *nb4 = nbr + i * 4;
          for (int d = 0; d < 4; d++) {
            const uint16_t j = nb4[d];
            if (j == 0xFFFF || j >= m) continue;
            if (own[j] || lvl[j] || wv[j]) continue;
            wv[j] = LB_OWN(k, 1);
          }
        }
      }
    }
  }

  // --- the wave -------------------------------------------------------------
  // One step outward per tick, into free ground only. It cannot enter a lit
  // pixel or another wave, so it collapses wherever it meets one - which is
  // what makes it hug the shape of the bolt instead of becoming a disc.
  // The wave is not on a slider of its own - there are only five and all of
  // them are spoken for - so it rides Travel speed. But it cannot ride it at a
  // FIXED multiple: at the top of the range that put the wave at 156 px/s, which
  // crosses the whole solid in under a second and reads as a flash rather than a
  // wave. The multiple compresses instead, 2.6x at the bottom down to 1.4x at
  // the top, so the wave stays a wave where the leader is fastest and is left
  // alone everywhere else.
  const float waveMul = 2.6f - 1.2f * ((float)SEGMENT.speed / 255.0f);
  s->wacc += pxPerSec * waveMul * (float)dt * 0.001f;
  int wsteps = (int)s->wacc;
  if (wsteps > 3) { wsteps = 3; s->wacc = 0.0f; } else s->wacc -= (float)wsteps;

  for (int ws = 0; ws < wsteps; ws++) {
    for (int k = 0; k < LB_STRIKES; k++) {
      LbStrike &S = s->st[k];
      if (!S.active || !S.waveAt) continue;
      const uint8_t front = S.waveAt;
      if (front >= LB_WAVEMAX) { S.waveAt = 0; continue; }
      for (size_t i = 0; i < m; i++) {
        if (!wv[i] || LB_OWNSTRIKE(wv[i]) != k) continue;
        if (LB_OWNBRANCH(wv[i]) != front) continue;
        const uint16_t *nb4 = nbr + i * 4;
        for (int d = 0; d < 4; d++) {
          const uint16_t j = nb4[d];
          if (j == 0xFFFF || j >= m) continue;
          if (own[j] || lvl[j] || wv[j]) continue;      // collapses on anything lit
          wv[j] = LB_OWN(k, front + 1);
        }
      }
      S.waveAt = (uint8_t)(front + 1);
    }
  }

  // --- erase from the seed, and the flashbacks -------------------------------
  {
    const float er = pxPerSec * (float)dt * 0.001f;
    for (int k = 0; k < LB_STRIKES; k++) {
      LbStrike &S = s->st[k];
      if (!S.active) continue;
      if (S.phase == LB_ERASE && S.eraseAt < 255) {
        const int adv = (int)(er + 0.5f);
        const int na = (int)S.eraseAt + (adv < 1 ? 1 : adv);
        S.eraseAt = (na > 255) ? 255 : (uint8_t)na;
      }
      if (S.waveAmp) {
        const int f = (int)S.waveAmp - (int)fx_step(7, dt);
        S.waveAmp = (uint8_t)(f < 0 ? 0 : f);
      }
      // A flashback runs back down the path toward the start. It may only start
      // once the head has stopped, and only while lit path remains.
      if (S.fbAt != 255) {
        const int adv = (int)(er * 3.0f + 0.5f);
        const int na = (int)S.fbAt - (adv < 1 ? 1 : adv);
        S.fbAt = (na <= (int)S.eraseAt) ? 255 : (uint8_t)na;
      } else if (doFlash && accent && S.phase != LB_GROW && S.eraseAt < S.maxOrd) {
        S.fbAt = S.maxOrd;
      }
    }
  }

  // --- fade, and free what has gone out --------------------------------------
  {
    const uint8_t f = fx_fade(9 + ((255 - glow) * 26) / 255, dt);
    for (size_t i = 0; i < m; i++) {
      if (!lvl[i]) { own[i] = 0; ord[i] = 0; continue; }
      bool dying = true;
      if (own[i]) {
        const LbStrike &S = s->st[LB_OWNSTRIKE(own[i])];
        dying = !S.active || (S.phase == LB_ERASE && ord[i] <= S.eraseAt);
      }
      if (dying) {
        lvl[i] = (lvl[i] > f) ? (uint8_t)(lvl[i] - f) : 0;
        if (!lvl[i]) { own[i] = 0; ord[i] = 0; }
      }
    }
    // Retire a strike once nothing of it is left on the surface.
    for (int k = 0; k < LB_STRIKES; k++) {
      LbStrike &S = s->st[k];
      if (!S.active || S.phase != LB_ERASE) continue;
      if (S.eraseAt < S.maxOrd || S.waveAt || S.waveAmp) continue;
      bool any = false;
      for (size_t i = 0; i < m && !any; i++)
        if (own[i] && LB_OWNSTRIKE(own[i]) == k) any = true;
      if (!any) {
        for (size_t i = 0; i < m; i++) if (wv[i] && LB_OWNSTRIKE(wv[i]) == k) wv[i] = 0;
        S.active = 0;
      }
    }
  }

  const uint8_t drive = cfx_drive(vol, 0.5f, 190);

  // --- paint ----------------------------------------------------------------
  CFX_NET_PREP();
  for (int y = 0; y < rows; y++) {
    CFX_NET_ROW(y);
    for (int x = 0; x < cols; x++) {
      CFX_NET_SKIP(x);
      const size_t i = (size_t)cfx_cidx(x, y, cols, B, cube);

      uint32_t c = 0;
      int bright = 0;
      uint8_t idx = 0;

      if (lvl[i]) {
        idx = hue[i];
        bright = lvl[i];
        if (own[i]) {
          const LbStrike &S = s->st[LB_OWNSTRIKE(own[i])];
          if (S.active && S.fbAt != 255) {
            const int back = (int)S.fbAt - (int)ord[i];
            if (back >= 0 && back < LB_FBTAIL)
              bright = 255 - (back * 90) / LB_FBTAIL;
          }
        }
      } else if (wv[i]) {
        const LbStrike &S = s->st[LB_OWNSTRIKE(wv[i])];
        if (S.active && S.waveAmp) {
          const int step = LB_OWNBRANCH(wv[i]);
          const int back = (int)S.waveAt - step;
          if (back >= 0 && back < LB_WAVETAIL) {
            bright = ((int)S.waveAmp * (LB_WAVETAIL - back)) / LB_WAVETAIL;
            // The trail shifts through the palette as it travels outward.
            idx = (uint8_t)(S.hue + (uint8_t)(s->glowHue >> 8) + step * 7);
          }
        }
      }

      if (bright > 0) {
        int b = (bright * gainI) >> 8;
        if (b > 255) b = 255;
        c = SEGMENT.color_from_palette(idx, false, true, 0);
        c = mq_scale(c, (uint8_t)b);
      }
      SEGMENT.setPixelColorXY(x, y, mq_scale(c, drive));
    }
  }
  FX_DONE;
}

static const char _data_FX_MODE_LICHTENBERG[] PROGMEM =
  "Ace 3-D Lichtenberg@Travel speed,Brightness,Branching,Afterglow,Overlap,Flashbacks,Ground strike,Flat mode;;!;2f;sx=42,ix=225,c1=150,c2=170,c3=10,o1=1,pal=11";


// ---------------------------------------------------------------------------
// Registration - joins the effect bank, which decides whether this effect
// claims one of the device's limited effect slots. See cube_fx_bank.h.
// ---------------------------------------------------------------------------
static CfxBankReg cube_fx_34_lichtenberg_reg(&mode_lichtenberg, _data_FX_MODE_LICHTENBERG);
