#include "wled.h"
#include "cube_fx_common.h"
#include "cube_fx_bank.h"

// ===========================================================================
// Ace 3-D Fracture - the shell shatters, then heals
// ===========================================================================
// The third of the cellular-walk effects, and deliberately the one whose
// FINISHED SHAPE is different. Lichtenberg draws a divergent tree and Watershed
// a convergent one; both end as branches on black. A fracture ends as CLOSED
// CELLS, because of one rule the other two do not have:
//
//     a crack that reaches another crack stops.
//
// That single arrest condition turns a set of growing lines into a partition of
// the surface. Nothing here computes a cell or knows what one is - the cells are
// what is left over, and they close because cracks cannot cross. Craquelure on
// a glaze, mud drying, a windscreen going: all the same rule.
//
// ---------------------------------------------------------------------------
// STAINED GLASS WITHOUT LABELLING ANY CELLS
// ---------------------------------------------------------------------------
// Lighting the cells properly would mean a connected-component pass and a label
// per pixel. It is not needed. A distance-to-nearest-crack field, relaxed a few
// passes a frame over the pixel graph, is zero on every crack and rises toward
// the middle of whatever encloses it - so each cell lights from its own interior
// and darkens at its edges without ever knowing it is a cell. Colour follows the
// same distance, which gives every cell a graded fill and reads as glass rather
// than as a flat polygon.
//
// The same relaxation was written for Lichtenberg's echo. It earns its keep
// twice.
//
// ---------------------------------------------------------------------------
// THE ARC
// ---------------------------------------------------------------------------
//   STRESS   nothing but the healed remains of the last shatter, dimming.
//   NUCLEATE a beat opens several flaws at once. Each throws cracks in OPPOSITE
//            directions, so a crack grows from its middle outward the way a
//            real one does, rather than from one end.
//   ARREST   tips stop on meeting anything already cracked. The pattern
//            finishes itself; there is no test for "done" beyond every tip
//            having run out of intact ground.
//   SHATTER  the instant the last tip arrests, the whole figure flashes at
//            once - the only moment the entire network is lit together.
//   HEAL     cracks fade and the cells swell back into each other as the
//            distance field forgets them.
// ===========================================================================

#define FR_TIPS    72           // crack tips propagating at once
#define FR_DMAX    40           // how far the cell-fill field is tracked
#define FR_DPASS   4            // relaxation passes per frame - EVEN, because
                                // each pass swaps the double buffer

enum { FR_STRESS = 0, FR_GROW, FR_FLASH, FR_HEAL };

struct FrTip {
  uint16_t at;
  int8_t   dx, dy, dz;          // heading, x100
  uint8_t  hue;
  uint8_t  life;
  uint8_t  active;
};

struct FrState {
  uint8_t  mode;
  uint8_t  clk[2];
  uint8_t  phase;
  uint8_t  flash;               // the shatter, decaying
  int16_t  holdMs;
  float    step;                // fractional crack steps carried over
  uint16_t hueCyc;
  FrTip    tip[FR_TIPS];
};

static FX_RET mode_fracture() {
  if (!strip.isMatrix || !SEGMENT.is2D()) { SEGMENT.fill(SEGCOLOR(0)); FX_DONE; }
  const int cols = SEG_W, rows = SEG_H;
  if (cols < 8 || rows < 8) { SEGMENT.fill(SEGCOLOR(0)); FX_DONE; }

  const bool cube = cfx_isCube(cols, rows);
  const int  B    = cube ? (cols / 3) : 1;
  const int  Bq   = cube ? B : 1;
  const size_t lut = cube ? (size_t)6 * Bq * Bq : 0;
  const size_t m  = cfx_litCount(cols, rows, B, cube);

  const size_t need = sizeof(FrState) + lut * sizeof(uint16_t)
                    + 6 * m + 4 * m * sizeof(uint16_t);
  if (!SEGENV.allocateData(need)) { SEGMENT.fill(SEGCOLOR(0)); FX_DONE; }

  FrState  *s   = (FrState *)SEGENV.data;
  uint16_t *rev = (uint16_t *)(s + 1);
  int8_t   *px  = (int8_t *)(rev + lut);
  int8_t   *py  = px + m;
  int8_t   *pz  = py + m;
  uint8_t  *ck  = (uint8_t *)(pz + m);        // crack brightness, 0 = intact
  uint8_t  *ds  = ck + m;                     // distance to nearest crack
  uint8_t  *d2  = ds + m;                     // its double buffer
  uint16_t *nbr = (uint16_t *)(d2 + m);       // four neighbours per pixel

  const uint8_t want = (uint8_t)(cube ? 1 : 2);
  if (SEGENV.call == 0 || s->mode != want) {
    s->mode = want; s->clk[0] = s->clk[1] = 0;
    s->phase = FR_STRESS; s->flash = 0; s->holdMs = 0;
    s->step = 0.0f; s->hueCyc = 0;
    for (int i = 0; i < FR_TIPS; i++) s->tip[i].active = 0;
    for (size_t i = 0; i < m; i++) { ck[i] = 0; ds[i] = FR_DMAX; d2[i] = FR_DMAX; }

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
        px[ci] = (int8_t)(X * 100.0f);
        py[ci] = (int8_t)(Y * 100.0f);
        pz[ci] = (int8_t)(Z * 100.0f);

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
  const bool locked = (tp.confidence >= 64 && tp.periodMs > 0);
  const bool onBeat = locked ? (tp.beat != 0) : (tp.hit != 0);

  // --- parameters ---------------------------------------------------------------
  const int  gainI = 40 + ((int)SEGMENT.intensity * 215) / 255;
  const int  cell  = (int)SEGMENT.custom1;              // flaws per shatter
  const int  heal  = (int)SEGMENT.custom2;
  const int  jag   = (int)cfx_c3full(SEGMENT.custom3);
  const bool onMus = SEGMENT.check1;
  const bool glass = SEGMENT.check2;

  // --- nucleate ---------------------------------------------------------------
  // Several flaws at once, each throwing two cracks in OPPOSITE directions, so
  // a crack grows outward from its middle the way a real one does.
  const bool ready = (s->phase == FR_STRESS);
  bool go = false;
  if (ready) {
    if (onMus) go = onBeat;
    else { s->holdMs = (int16_t)(s->holdMs - (int)dt); go = (s->holdMs <= 0); }
  }
  if (go) {
    const int flaws = 3 + (cell * 13) / 255;
    int made = 0;
    for (int f = 0; f < flaws; f++) {
      size_t seed = (size_t)-1;
      for (int t = 0; t < 12; t++) {
        const size_t c = (size_t)(hw_random16() % (uint16_t)m);
        if (!ck[c]) { seed = c; break; }
      }
      if (seed == (size_t)-1) continue;
      int best = 0, bv = -1;
      for (int k = 0; k < 16; k++) if ((int)fft[k] > bv) { bv = fft[k]; best = k; }
      const uint8_t hu = (uint8_t)((best * 255) / 15 + (uint8_t)(s->hueCyc >> 8));
      // A tangent direction, and its opposite.
      const float nx = (float)px[seed] * 0.01f, ny = (float)py[seed] * 0.01f,
                  nz = (float)pz[seed] * 0.01f;
      float ux = (float)((int)hw_random8() - 128);
      float uy = (float)((int)hw_random8() - 128);
      float uz = (float)((int)hw_random8() - 128);
      const float dn = ux * nx + uy * ny + uz * nz;
      ux -= nx * dn; uy -= ny * dn; uz -= nz * dn;
      float L = sqrtf(ux * ux + uy * uy + uz * uz);
      if (L < 0.0001f) L = 1.0f;
      ux /= L; uy /= L; uz /= L;
      for (int side = 0; side < 2; side++) {
        for (int q = 0; q < FR_TIPS; q++) {
          if (s->tip[q].active) continue;
          FrTip &T = s->tip[q];
          T.active = 1; T.at = (uint16_t)seed; T.hue = hu; T.life = 200;
          const float sg = side ? -1.0f : 1.0f;
          T.dx = (int8_t)(ux * sg * 100.0f);
          T.dy = (int8_t)(uy * sg * 100.0f);
          T.dz = (int8_t)(uz * sg * 100.0f);
          made++;
          break;
        }
      }
      ck[seed] = 200;
    }
    if (made) { s->phase = FR_GROW; }
    else      { s->holdMs = 600; }
  }

  // --- propagate --------------------------------------------------------------
  s->step += (14.0f + (float)SEGMENT.speed * (60.0f / 255.0f)) * (float)dt * 0.001f;
  int steps = (int)s->step;
  if (steps > 5) { steps = 5; s->step = 0.0f; } else s->step -= (float)steps;

  if (s->phase == FR_GROW) {
    for (int st = 0; st < steps; st++) {
      for (int q = 0; q < FR_TIPS; q++) {
        FrTip &T = s->tip[q];
        if (!T.active) continue;
        const uint16_t *nb4 = nbr + (size_t)T.at * 4;
        // Wander a little, so the cracks are not straight lines.
        {
          const float j = (float)jag * (0.5f / 255.0f);
          const float nx = (float)px[T.at] * 0.01f, ny = (float)py[T.at] * 0.01f,
                      nz = (float)pz[T.at] * 0.01f;
          float dx = (float)T.dx, dy = (float)T.dy, dz = (float)T.dz;
          const float tx = ny * dz - nz * dy, ty = nz * dx - nx * dz, tz = nx * dy - ny * dx;
          const float wgl = ((float)((int)hw_random8() - 128) / 128.0f) * j;
          dx += tx * wgl; dy += ty * wgl; dz += tz * wgl;
          float L = sqrtf(dx * dx + dy * dy + dz * dz);
          if (L < 0.0001f) L = 1.0f;
          T.dx = (int8_t)(dx / L * 100.0f);
          T.dy = (int8_t)(dy / L * 100.0f);
          T.dz = (int8_t)(dz / L * 100.0f);
        }
        int bestJ = -1, bestS = -1000000;
        for (int d = 0; d < 4; d++) {
          const uint16_t j = nb4[d];
          if (j == 0xFFFF || j >= m) continue;
          const int sc = (int)px[j] * T.dx + (int)py[j] * T.dy + (int)pz[j] * T.dz;
          if (sc > bestS) { bestS = sc; bestJ = (int)j; }
        }
        // ARREST. This one line is what makes cells instead of branches.
        if (bestJ < 0 || ck[(size_t)bestJ] || !T.life) { T.active = 0; continue; }
        T.at = (uint16_t)bestJ;
        ck[(size_t)bestJ] = 200;
        T.life--;
      }
    }
    bool any = false;
    for (int q = 0; q < FR_TIPS && !any; q++) if (s->tip[q].active) any = true;
    if (!any) { s->phase = FR_FLASH; s->flash = 255; }
  }

  if (s->phase == FR_FLASH) {
    const int f = (int)s->flash - (int)fx_step(9, dt);
    s->flash = (uint8_t)(f < 0 ? 0 : f);
    if (!s->flash) { s->phase = FR_HEAL; }
  }

  // --- heal -------------------------------------------------------------------
  if (s->phase == FR_HEAL || s->phase == FR_STRESS) {
    const uint8_t f = fx_fade(1 + ((255 - heal) * 10) / 255, dt);
    if (f) {
      int left = 0;
      for (size_t i = 0; i < m; i++) {
        if (!ck[i]) continue;
        ck[i] = (ck[i] > f) ? (uint8_t)(ck[i] - f) : 0;
        if (ck[i]) left++;
      }
      if (s->phase == FR_HEAL && left < (int)(m / 40)) {
        for (size_t i = 0; i < m; i++) ck[i] = 0;
        s->phase = FR_STRESS; s->holdMs = 400;
      }
    }
  }

  // --- the cell fill ----------------------------------------------------------
  // Distance to the nearest crack, relaxed over the pixel graph. Zero on a
  // crack, rising toward the middle of whatever encloses it - so a cell lights
  // from its own interior without anything ever labelling it as a cell.
  {
    for (size_t i = 0; i < m; i++) {
      if (ck[i]) ds[i] = 0;
      else if (ds[i] < FR_DMAX) ds[i]++;
    }
    for (int pass = 0; pass < FR_DPASS; pass++) {
      for (size_t i = 0; i < m; i++) {
        int best = ds[i];
        const uint16_t *nb4 = nbr + i * 4;
        for (int q = 0; q < 4; q++) {
          const uint16_t j = nb4[q];
          if (j == 0xFFFF || j >= m) continue;
          const int t = (int)ds[j] + 1;
          if (t < best) best = t;
        }
        d2[i] = (uint8_t)best;
      }
      uint8_t *tmp = ds; ds = d2; d2 = tmp;
    }
  }

  s->hueCyc = (uint16_t)(s->hueCyc + (uint32_t)dt * 8u);
  const uint8_t drive = cfx_drive(vol, 0.5f, 195);

  // --- paint ----------------------------------------------------------------
  CFX_NET_PREP();
  for (int y = 0; y < rows; y++) {
    CFX_NET_ROW(y);
    for (int x = 0; x < cols; x++) {
      CFX_NET_SKIP(x);
      const size_t i = (size_t)cfx_cidx(x, y, cols, B, cube);

      uint32_t c = 0;
      int b = 0; uint8_t idx = 0;
      if (ck[i]) {
        // The crack itself: the brightest thing here, and the whole network
        // lights together for the instant of the shatter.
        b = 90 + ((int)ck[i] * 165) / 200;
        b += ((int)s->flash * 65) >> 8;
        idx = (uint8_t)((uint8_t)(s->hueCyc >> 8) + 200);
      } else if (glass && ds[i] < FR_DMAX) {
        // The cell, lit from its middle. Graded, so it reads as glass rather
        // than as a flat polygon.
        // QUADRATIC in the distance, not linear. Linear lit almost the whole
        // surface to mid grey and measured sigma 14 - the flattest thing in the
        // family - because a cell's edge was nearly as bright as its middle.
        // Squaring it holds the ground near every crack dark, which is what
        // makes the partition legible at all.
        // Normalised to a CELL, not to FR_DMAX. Cells here are eight or ten
        // pixels across, so dividing by the field's 40-pixel ceiling collapsed
        // the fill to nothing - glass on and glass off measured identically.
        const int d = (int)ds[i];
        b = d * d * 3;
        if (b > 118) b = 118;
        b += ((int)s->flash * 26) >> 8;
        idx = (uint8_t)((uint8_t)(s->hueCyc >> 8) + (uint8_t)(d * 5));
      }
      if (b > 0) {
        if (b > 255) b = 255;
        int q = (b * gainI) >> 8;
        if (q > 255) q = 255;
        c = SEGMENT.color_from_palette(idx, false, true, 0);
        c = mq_scale(c, (uint8_t)q);
      }
      SEGMENT.setPixelColorXY(x, y, mq_scale(c, drive));
    }
  }
  FX_DONE;
}

static const char _data_FX_MODE_FRACTURE[] PROGMEM =
  "Ace 3-D Fracture@Crack speed,Brightness,Flaws,Heal time,Jaggedness,Shatter on beat,Glass fill,Flat mode;;!;2f;sx=120,ix=210,c1=110,c2=150,c3=18,o1=1,o2=1,pal=11";


// ---------------------------------------------------------------------------
// Registration - joins the effect bank, which decides whether this effect
// claims one of the device's limited effect slots. See cube_fx_bank.h.
// ---------------------------------------------------------------------------
static CfxBankReg cube_fx_37_fracture_reg(&mode_fracture, _data_FX_MODE_FRACTURE);
