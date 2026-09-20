#include "wled.h"
#include "cube_fx_common.h"
#include "cube_fx_bank.h"

// ===========================================================================
// Ace 3-D Voronoi - nearest-seed cells on the sphere, breathing on the beat
// ===========================================================================
// Scatter seeds over the sphere, give every pixel the colour of whichever seed
// is nearest, and the surface partitions itself into cells. Seamless for the
// usual reason - the distance is the angle between two unit vectors, so the
// folds of the net never enter into it - and unlike the hyperbolic tiling in
// cube_fx_38 it has no density gradient at all. Cells are the same size
// everywhere, which at sixteen pixels a face is worth more than any amount of
// mathematical depth: every cell gets the same handful of pixels to say
// something with.
//
// ---------------------------------------------------------------------------
// EDGES FROM F2 MINUS F1, WHICH IS EXACT AND NOT AN ESTIMATE
// ---------------------------------------------------------------------------
// The usual way to outline a Voronoi diagram is to guess at the boundary by
// sampling neighbours or thresholding a gradient. There is no need. Track the
// nearest distance and the SECOND nearest, and the difference between them
// falls to zero exactly on the boundary and nowhere else.
//
// Better, it converts to pixels exactly. With d_i = 1 - dot(p, s_i), the
// difference d2 - d1 is dot(p, s1 - s2), which is |s1 - s2| times the sine of
// the angle from the bisecting plane. So dividing by the chord between the two
// seeds gives the distance to the boundary in RADIANS, and dividing that by
// the angle one pixel subtends gives it in pixels. The border is then a
// constant width everywhere, whatever the local cell size - which is the thing
// three effects in this folder in a row got wrong by expressing a line width
// as a fraction of a cell instead.
//
// ---------------------------------------------------------------------------
// THE SEEDS WANDER, THEY DO NOT ROAM
// ---------------------------------------------------------------------------
// Seeds start on a Fibonacci spiral, which is as evenly as points spread on a
// sphere without iterating. Each then oscillates about that home position on
// two tangent axes at two incommensurate rates, so the pattern is never still
// and never repeats.
//
// Deliberately an oscillation and not a free drift: seeds moving along their
// own great circles wander independently, and independent wanderers clump.
// Clumped seeds mean cells that shrink under a pixel and vanish, and a couple
// of cells swelling to swallow a whole face. Bounded to about a third of the
// seed spacing, the arrangement stays even for ever.
//
// ---------------------------------------------------------------------------
// THE BEAT MOVES A BOUNDARY, NOT A BRIGHTNESS
// ---------------------------------------------------------------------------
// A kick adds WEIGHT to one seed, and weight subtracts from that seed's
// distance - an additively weighted Voronoi diagram - so its cell physically
// swells and shoves its neighbours back, then relaxes. The territory moves.
// That is a much better use of a beat here than flashing a cell, because the
// structure is the thing this effect is about, and it is the one response that
// could not be done by any other effect in the set.
//
// The weight is capped against the cell size rather than being an absolute, so
// a swell reads the same at six cells as at forty-eight and can never let one
// seed eat the sphere.
// ===========================================================================

// ---------------------------------------------------------------------------
// TEN PARAMETERS OUT OF FIVE SLIDERS
// ---------------------------------------------------------------------------
// check1 is a SHIFT key. It does not change the picture at all - it changes
// which page of parameters the five sliders address, so the effect carries ten
// controls on hardware that only has five.
//
// The mechanism matters, because the obvious one does not work. Writing the
// incoming page back into SEGMENT.speed and friends - which the parameter
// memory usermod already does, so it is legal - loses the other page the
// moment anything pushes all five sliders at once, and both the simulator's
// control column and a preset load do exactly that.
//
// So nothing is ever written back. Both pages are held here, the sliders are
// treated as a CONTROLLER rather than as storage, and a page only takes a new
// value for a slider that actually moved since the last frame. Flipping shift
// therefore disturbs nothing: the sliders have not moved, so neither page
// changes, and the five controls simply start addressing the other page.
//
// The visible cost is that after a flip the slider POSITIONS no longer show
// the values they control, until you touch them - the first touch snaps that
// one parameter to wherever the slider physically sits. That is the honest
// trade for ten controls, and it is why the page-two names are in the metadata
// alongside the page-one ones.
//
// The pages live at file scope rather than in segment data, so they survive
// switching to another effect and back. They do not survive a reboot; the
// parameter memory usermod restores whichever page was active, and the other
// returns to its defaults.
// ===========================================================================

#define VN_MAX      48          // seeds; the loop is O(seeds) per pixel
#define VN_GOLDEN   2.39996323f // golden angle, for the seed spiral
#define VN_NPAR      5          // sliders per page

// Page 0 is filled from the metadata defaults on first run; page 1 is these.
static uint8_t vnPage[2][VN_NPAR] = {
  { 110, 128, 110, 160,   8 },
  { 150, 120,  70, 130,  25 },   // Swell, Relax, Warp, Wander, Hue
};
static uint8_t vnSeen[VN_NPAR];
static bool    vnInit = false;

struct VnState {
  uint8_t  mode;
  uint8_t  clk[2];
  uint8_t  n;                   // seeds currently placed
  uint8_t  nextSeed;            // which one the next kick lands on
  uint16_t drift;               // palette rotation
  float    home[VN_MAX][3];
  float    ta[VN_MAX][3], tb[VN_MAX][3];   // tangent axes at home
  uint16_t ph[VN_MAX][2];       // the two wander phases
  uint8_t  wt[VN_MAX];          // swell, decaying
};

// Fibonacci spiral: the standard way to spread n points near-evenly over a
// sphere without relaxing them. Also builds each seed a tangent frame, which
// is what it wanders on.
static void vn_seed(VnState *s, int n) {
  s->n = (uint8_t)n;
  for (int i = 0; i < n; i++) {
    const float z = 1.0f - 2.0f * ((float)i + 0.5f) / (float)n;
    float r = 1.0f - z * z; r = (r > 0.0f) ? sqrtf(r) : 0.0f;
    const float a = (float)i * VN_GOLDEN;
    float hx = r * cosf(a), hy = r * sinf(a), hz = z;
    s->home[i][0] = hx; s->home[i][1] = hy; s->home[i][2] = hz;

    float ux = 0.0f, uy = 0.0f, uz = 1.0f;
    if (hz > 0.9f || hz < -0.9f) { ux = 1.0f; uz = 0.0f; }
    float ax = uy * hz - uz * hy, ay = uz * hx - ux * hz, az = ux * hy - uy * hx;
    float L = sqrtf(ax * ax + ay * ay + az * az);
    if (L < 1e-6f) { ax = 1.0f; ay = 0.0f; az = 0.0f; L = 1.0f; }
    s->ta[i][0] = ax / L; s->ta[i][1] = ay / L; s->ta[i][2] = az / L;
    s->tb[i][0] = hy * s->ta[i][2] - hz * s->ta[i][1];
    s->tb[i][1] = hz * s->ta[i][0] - hx * s->ta[i][2];
    s->tb[i][2] = hx * s->ta[i][1] - hy * s->ta[i][0];

    s->ph[i][0] = (uint16_t)(i * 20341u);
    s->ph[i][1] = (uint16_t)(i * 44771u + 9007u);
    s->wt[i]    = 0;
  }
}

static FX_RET mode_voronoi() {
  if (!strip.isMatrix || !SEGMENT.is2D()) { SEGMENT.fill(SEGCOLOR(0)); FX_DONE; }
  const int cols = SEG_W, rows = SEG_H;
  if (cols < 8 || rows < 8) { SEGMENT.fill(SEGCOLOR(0)); FX_DONE; }

  const bool cube = cfx_isCube(cols, rows);
  const int  B    = cube ? (cols / 3) : 1;

  if (!SEGENV.allocateData(sizeof(VnState))) { SEGMENT.fill(SEGCOLOR(0)); FX_DONE; }
  VnState *s = (VnState *)SEGENV.data;

  const uint8_t want = (uint8_t)(cube ? 1 : 2);
  if (SEGENV.call == 0 || s->mode != want) {
    s->mode = want; s->clk[0] = s->clk[1] = 0;
    s->drift = 0; s->nextSeed = 0; s->n = 0;
  }

  uint16_t dt = fx_dt8(s->clk);
  if (dt > 60) dt = 60;

  // --- parameters, across two pages -----------------------------------------
  { const uint8_t phys[VN_NPAR] = { SEGMENT.speed, SEGMENT.intensity,
                                    SEGMENT.custom1, SEGMENT.custom2, SEGMENT.custom3 };
    if (!vnInit) {
      for (int i = 0; i < VN_NPAR; i++) { vnPage[0][i] = phys[i]; vnSeen[i] = phys[i]; }
      vnInit = true;
    }
    const int pg = SEGMENT.check1 ? 1 : 0;
    for (int i = 0; i < VN_NPAR; i++) {
      if (phys[i] != vnSeen[i]) { vnPage[pg][i] = phys[i]; vnSeen[i] = phys[i]; }
    }
  }
  const int  drift  = (int)vnPage[0][0];
  const int  fill   = (int)vnPage[0][1];
  const int  cells  = (int)vnPage[0][2];
  const int  cush   = (int)vnPage[0][3];
  const int  edgeW  = (int)vnPage[0][4] & 0x1F;     // custom3 is five bits
  const int  swell  = (int)vnPage[1][0];
  const int  relax  = (int)vnPage[1][1];
  const int  warp   = (int)vnPage[1][2];
  const int  wander = (int)vnPage[1][3];
  // Slot four is custom3, which is a FIVE-bit slider - so whatever page uses
  // it only ever receives 0..31. Edges wants exactly that; Hue wants a full
  // byte and has to be widened, or it sits in the bottom eighth of its range
  // and the cube comes out nearly monochrome.
  const int  hueSpr = (int)cfx_c3full((uint8_t)(vnPage[1][4] & 0x1F));
  const bool wire   = SEGMENT.check2;
  int nWant = 6 + (cells * (VN_MAX - 6)) / 255;
  if (nWant < 6) nWant = 6; else if (nWant > VN_MAX) nWant = VN_MAX;
  if (nWant != (int)s->n) vn_seed(s, nWant);
  const int n = (int)s->n;

  // --- audio ----------------------------------------------------------------
  um_data_t     *um   = cfx_getAudioData();
  const float    vol  = *(float *)um->u_data[0];
  const uint8_t  beat = swell ? fx_lowBeat(um) : 0;
  if (beat) {
    // One kick, one seed. Round-robin rather than random so a run of beats
    // spreads over the sphere instead of hammering the same cell.
    s->wt[s->nextSeed] = 255;
    s->nextSeed = (uint8_t)((s->nextSeed + 7) % n);
  }
  // Relax sets how long a swell takes to let go - about a sixth of a second at
  // zero, about three at full. Swell being a depth slider rather than a
  // checkbox means zero turns it off, so nothing is lost by taking check1 for
  // the shift key.
  { const int d = (int)fx_step(2 + ((255 - relax) * 20) / 255, dt);
    for (int i = 0; i < n; i++) s->wt[i] = (uint8_t)((s->wt[i] > d) ? (s->wt[i] - d) : 0); }

  // --- wander ---------------------------------------------------------------
  // Quadratic, not linear. The old 11 + speed/4 only spanned 11 to 74, so the
  // bottom of the slider was never still and the top was never fast. This runs
  // 2 to 195 and passes through the old default at the same slider position,
  // so the shipped look is unchanged and both ends are new ground.
  for (int i = 0; i < n; i++) {
    const uint32_t r = (uint32_t)(2 + (drift * drift) / 336);
    s->ph[i][0] = (uint16_t)(s->ph[i][0] + ((uint32_t)dt * r * (3u + (i & 3u))) / (23u * 5u));
    s->ph[i][1] = (uint16_t)(s->ph[i][1] + ((uint32_t)dt * r * (2u + (i & 5u))) / (23u * 7u));
  }
  // Palette rotation rides the SAME control, at its own much slower rate.
  // Left on a fixed clock it was the only thing still moving at Drift 0, so
  // the bottom of the slider never actually reached still - and a frozen
  // diagram with only the beat swell moving turns out to be one of the better
  // things this effect does.
  s->drift = (uint16_t)(s->drift + ((uint32_t)dt * (uint32_t)drift) / 55u);

  // Live seed positions. Amplitude is a third of the seed spacing - see the
  // header for why this is an oscillation about a home and not a free drift.
  float sx[VN_MAX], sy[VN_MAX], sz[VN_MAX];
  { const float spacing = 2.0f / sqrtf((float)n);
    // Amplitude is a separate axis from rate: small and quick reads as
    // jitter, wide and slow as a slow morph. Past about half the spacing the
    // seeds start to crowd each other and cells vary a lot in size, which is
    // a legitimate look rather than a failure - hence the range reaching it.
    const float amp = spacing * (0.05f + (float)wander * (0.55f / 255.0f));
    for (int i = 0; i < n; i++) {
      const float u = amp * (float)sin16_t(s->ph[i][0]) * (1.0f / 32768.0f);
      const float v = amp * (float)sin16_t(s->ph[i][1]) * (1.0f / 32768.0f);
      float x = s->home[i][0] + u * s->ta[i][0] + v * s->tb[i][0];
      float y = s->home[i][1] + u * s->ta[i][1] + v * s->tb[i][1];
      float z = s->home[i][2] + u * s->ta[i][2] + v * s->tb[i][2];
      const float L = sqrtf(x * x + y * y + z * z);
      const float iL = (L > 1e-6f) ? (1.0f / L) : 1.0f;
      sx[i] = x * iL; sy[i] = y * iL; sz[i] = z * iL;
    }
  }

  // Swell, scaled against the cell size so it reads the same at any seed count
  // and can never let one seed swallow the sphere.
  // How far a full swell actually MOVES a boundary, which is the only thing
  // worth calibrating here. For two seeds an angle S apart, a weight w shifts
  // the bisector by w / (2 sin(S/2)); with S about 3.5/sqrt(n) that comes out
  // as w/3.5 radians regardless of how many seeds there are, so a cap
  // proportional to 1/sqrt(n) gives the same swell in pixels at every setting.
  //
  // The first version scaled the cap by 1/n instead, which moved the boundary
  // about a fifth of a pixel - measured, beat on versus off changed the swing
  // from 1.1 to 1.4 and nothing was visible. This moves it about two pixels.
  // Clamped, because at six seeds a cell is wide but the swell must still not
  // reach past a neighbour's own seed.
  float wt[VN_MAX];
  { float cap = 0.80f / sqrtf((float)n);
    if (cap > 0.22f) cap = 0.22f;
    cap *= (float)swell * (1.0f / 255.0f);
    for (int i = 0; i < n; i++) wt[i] = cap * (float)s->wt[i] * (1.0f / 255.0f); }

  // Warp gives every seed its own MULTIPLICATIVE weight. Additive weights
  // (the swell) slide a boundary while keeping it a straight bisector;
  // multiplicative ones bend it into a circular arc and make cells genuinely
  // different sizes - an Apollonius diagram rather than a Voronoi one.
  float mw[VN_MAX];
  { const float k = (float)warp * (0.95f / 255.0f);
    for (int i = 0; i < n; i++) {
      uint32_t h = (uint32_t)(i * 2246822519u + 374761393u); h ^= h >> 15;
      mw[i] = 1.0f + k * ((float)(h & 255) * (1.0f / 255.0f) - 0.5f);
    } }

  const uint8_t hueOff = (uint8_t)(s->drift >> 8);
  const uint8_t drive  = cfx_drive(vol, 0.5f, 200);
  const float   pxA    = cube ? (2.0f / (float)B) : (2.0f / (float)cols);
  const float   edgeR  = 0.15f + (float)edgeW * (0.11f);   // border half-width, px

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
      const float px = X * iL, py = Y * iL, pz = Z * iL;

      // nearest and second nearest, in one pass
      float b1 = 1e9f, b2 = 1e9f;
      int   i1 = 0, i2 = 0;
      for (int i = 0; i < n; i++) {
        const float d = (1.0f - (px * sx[i] + py * sy[i] + pz * sz[i])) * mw[i] - wt[i];
        if (d < b1)      { b2 = b1; i2 = i1; b1 = d; i1 = i; }
        else if (d < b2) { b2 = d;  i2 = i; }
      }

      // Distance to the boundary, in pixels. Exact - see the header.
      float edgePx;
      { const float dx = sx[i1] - sx[i2], dy = sy[i1] - sy[i2], dz = sz[i1] - sz[i2];
        // The chord alone is the gradient only for a plain bisector. With
        // multiplicative weights in play the field is scaled by them too, so
        // the mean of the two goes in or the outline thickens wherever warp
        // has shrunk a cell.
        float chord = sqrtf(dx * dx + dy * dy + dz * dz) * 0.5f * (mw[i1] + mw[i2]);
        if (chord < 1e-5f) chord = 1e-5f;
        edgePx = ((b2 - b1) / chord) / (pxA * iL); }

      // Normalised position inside the cell: 0 at the seed, 1 at the boundary,
      // and scale-free, so a big cell and a small one shade identically.
      // Clamped at zero FIRST. A swollen seed subtracts its weight from its own
      // distance, so b1 goes negative inside the swell - and then this ratio
      // blows up, taking the hue with it. That put rainbow speckle inside every
      // cell the beat hit, which looked like a colour effect and was a divide
      // by something close to zero.
      float c1 = (b1 > 0.0f) ? b1 : 0.0f;
      const float c2 = (b2 > 0.0f) ? b2 : 0.0f;
      float cu = (c1 + c2 > 1e-6f) ? (2.0f * c1 / (c1 + c2)) : 0.0f;
      if (cu > 1.0f) cu = 1.0f; else if (cu < 0.0f) cu = 0.0f;

      // colour: identity from the seed, gradient from the cushion
      uint32_t hsh = (uint32_t)(i1 + 1) * 2654435761u;
      hsh ^= hsh >> 13;
      const uint8_t idx = (uint8_t)(((int)(uint8_t)(hsh >> 9) * hueSpr) / 255
                                  + (int)(cu * (float)cush * 0.45f) + hueOff);

      int lum;
      if (wire) {
        // The diagram as a glowing web on black: only the boundaries light.
        const float t = edgePx / (edgeR + 0.9f);
        lum = (t >= 1.0f) ? 0 : (int)(2.2f * (float)fill * (1.0f - t) * (1.0f - t));
      } else {
        // Cushion drives the DOME as well as the hue gradient. Wired to hue
        // alone it was very nearly a dead control - sweeping it end to end
        // moved the mean by 0.4 - because the brightness falloff was a fixed
        // constant underneath it.
        lum = (fill * (256 + (int)((hsh >> 25) & 63) * 2)) >> 8;
        lum = (int)((float)lum * (1.0f - (0.20f + (float)cush * (0.60f / 255.0f)) * cu));
        if (edgePx < edgeR) lum = (int)((float)lum * (edgePx / edgeR));
      }
      // A swollen cell also brightens, so a kick reads even where the boundary
      // it moved is off the far side of the solid.
      lum += ((int)s->wt[i1] * fill) >> 10;
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

static const char _data_FX_MODE_VORONOI[] PROGMEM =
  "Ace 3-D Voronoi@Drift/Swell,Fill/Relax,Cells/Warp,Cushion/Wander,Edges/Hue,Shift,Wire,Flat mode;;!;2f;sx=110,ix=128,c1=110,c2=160,c3=8,pal=11";


// ---------------------------------------------------------------------------
// Registration - joins the effect bank, which decides whether this effect
// claims one of the device's limited effect slots. See cube_fx_bank.h.
// ---------------------------------------------------------------------------
static CfxBankReg cube_fx_40_voronoi_reg(&mode_voronoi, _data_FX_MODE_VORONOI);
