#include "wled.h"
#include "cube_fx_common.h"
#include "cube_fx_bank.h"

// ===========================================================================
// Ace 3-D Maelstrom - a spiral falling into itself, forever
// ===========================================================================
// A LOGARITHMIC spiral, and the choice is the whole effect.
//
// For r = a * e^(b*theta), scaling the figure by e^(2*pi*b) lands it exactly on
// top of itself rotated by a turn. Scale and rotation are the same operation.
// So a spiral drawn as
//
//     phase = DENSITY * log(radius) + ARMS * azimuth + t
//
// zooms continuously as t advances, and because log(radius) enters linearly a
// CONSTANT rate of t is a constant rate of zoom - the same proportion per
// second, forever, with nothing to reset and no seam to hide. An Archimedean
// spiral cannot do that: its arms are evenly spaced, so zooming makes the
// middle sparse and the edge crowded and the illusion dies within a second.
//
// The centre is a genuine singularity - log(0) is unbounded - so the arms
// crowd infinitely into it and the eye has nowhere to settle. That is the
// hypnosis, and it is free: it comes from the coordinate, not from any special
// case in the drawing.
//
// ---------------------------------------------------------------------------
// WHERE THE CENTRE IS, AND WHY
// ---------------------------------------------------------------------------
// The lid, straight up. The spiral sinks into the top face and its arms wrap
// down all four walls to the bottom, so the whole solid is one continuous
// figure and every vertical seam is a place an arm crosses rather than a place
// it stops. cfx_buildCube already hands back the two coordinates this needs -
// azimuth about the vertical, and a latitude that treats the top face as a
// pole - so the cube and a flat panel take the SAME code path, one being polar
// about the lid and the other polar about the middle of the panel.
//
// ---------------------------------------------------------------------------
// WHAT THE MUSIC DOES
// ---------------------------------------------------------------------------
// Almost nothing, on purpose. A hypnotic figure that lurches on every kick is
// not hypnotic, it is a strobe. A beat adds a brief surge to the zoom rate and
// a little brightness, so the spiral BREATHES with the track and pulls harder
// on a downbeat.
//
// The one large gesture is what happens when the kicks STOP. After a couple of
// seconds without one the zoom turns around and the spiral unwinds outward,
// and it turns back the moment a kick lands. That gives the figure a second
// state and makes a breakdown legible from across a room without anything
// flashing - the direction of the whole image is the message.
//
// It eases through zero over about a second and a half rather than flipping.
// A sign change from one frame to the next is a visible tear, and worse, it
// throws away the one thing the effect is selling: the spiral slowing, coming
// to a stop, hanging there and then drawing back is the moment worth having,
// and it only exists if the turn is a movement rather than an edit.
// ===========================================================================

// The four top corners, as unit vectors.
static const int8_t MS_CORNER[4][3] PROGMEM = {
  {  73,  73,  73 }, { -73,  73,  73 }, { -73, -73,  73 }, {  73, -73,  73 },
};

// Build the two per-pixel coordinates the spiral is drawn from, about ANY axis.
//
// Recentring means recomputing these, because they are the whole geometry:
// azimuth about the chosen axis, and angular distance from it. It is a few
// transcendentals per lit pixel and happens only when the centre changes - a
// single dropped frame on a button press, against making every pixel of every
// frame pay for a centre that almost never moves.
static void ms_build(uint8_t *az, uint16_t *lr, int cols, int rows, int B,
                     bool cube, float nx, float ny, float nz, int flatCorner) {
  // Two axes across the centre axis, for the azimuth to be measured against.
  // The reference is swapped near the pole for the usual reason: a cross
  // product with something parallel collapses to nothing.
  float rx = 0.0f, ry = 0.0f, rz = 1.0f;
  if (nz > 0.9f || nz < -0.9f) { rx = 0.0f; ry = 1.0f; rz = 0.0f; }
  float ux = ny * rz - nz * ry, uy = nz * rx - nx * rz, uz = nx * ry - ny * rx;
  float ul = sqrtf(ux * ux + uy * uy + uz * uz);
  if (ul < 0.0001f) ul = 1.0f;
  ux /= ul; uy /= ul; uz /= ul;
  const float vx = ny * uz - nz * uy, vy = nz * ux - nx * uz, vz = nx * uy - ny * ux;

  // A flat panel has no corners to point at, so "corner" there means moving
  // the sink toward a corner OF THE PANEL - the same gesture, one dimension
  // down, and the only reading that keeps the control meaningful in 2-D.
  const float fcx = (flatCorner < 0) ? 0.0f : ((flatCorner == 0 || flatCorner == 3) ? 0.62f : -0.62f);
  const float fcy = (flatCorner < 0) ? 0.0f : ((flatCorner < 2) ? 0.62f : -0.62f);

  for (int y = 0; y < rows; y++) {
    for (int x = 0; x < cols; x++) {
      if (cube && cfx_gap(x, y, B)) continue;          // gap corner
      const size_t i = (size_t)cfx_cidx(x, y, cols, B, cube);
      float X, Y, Z;
      cfx_pos(x, y, cols, rows, B, cube, X, Y, Z);

      float a, rad;
      if (cube) {
        const float len = sqrtf(X * X + Y * Y + Z * Z);
        const float ix = (len > 0.0001f) ? X / len : 0.0f;
        const float iy = (len > 0.0001f) ? Y / len : 0.0f;
        const float iz = (len > 0.0001f) ? Z / len : 1.0f;
        float d = ix * nx + iy * ny + iz * nz;
        if (d < -1.0f) d = -1.0f; else if (d > 1.0f) d = 1.0f;
        rad = acosf(d) * (255.0f / 2.7f);                          // 0 at the sink
        a = atan2f(ix * vx + iy * vy + iz * vz,
                   ix * ux + iy * uy + iz * uz) * (128.0f / 3.14159265f) + 128.0f;
      } else {
        const float dx = X - fcx, dy = Y - fcy;
        rad = sqrtf(dx * dx + dy * dy) * 180.0f;
        a = atan2f(dy, dx) * (128.0f / 3.14159265f) + 128.0f;
      }
      if (rad < 0.0f) rad = 0.0f;
      az[i] = (uint8_t)((int)(a + 0.5f) & 255);
      lr[i] = (uint16_t)(log2f(rad + 1.0f) * 256.0f);
    }
  }
}

struct MsState {
  uint8_t  mode;
  uint32_t tPhase;                  // zoom position, Q8
  uint32_t tColour;                 // palette scroll, Q8
  uint8_t  surge;                   // beat envelope
  uint16_t sinceKick;               // ms since the last kick, saturating
  int16_t  dir;                     // zoom direction, -256..256, eased
  uint8_t  corner;                  // 0..3, which corner is next
  uint8_t  lastChk;                 // check2 as it was last frame, for edges
  uint8_t  builtFor;                // centre the tables currently describe
  uint8_t  clk[2];
};

static FX_RET mode_maelstrom() {
  if (!strip.isMatrix || !SEGMENT.is2D()) { SEGMENT.fill(SEGCOLOR(0)); FX_DONE; }
  const int cols = SEG_W, rows = SEG_H;
  if (cols < 8 || rows < 8) { SEGMENT.fill(SEGCOLOR(0)); FX_DONE; }

  const bool cube = cfx_isCube(cols, rows);
  const int  B    = cube ? (cols / 3) : 1;
  const size_t m  = cfx_litCount(cols, rows, B, cube);

  // az is a byte, the log radius two. No scratch and no compaction pass,
  // because both are computed per LIT pixel straight from cfx_pos rather than
  // built across the full rectangle and squeezed down afterwards - which is
  // the step that has to be done one array at a time to be safe, and is not
  // worth doing at all when the arithmetic is this cheap.
  const size_t need = sizeof(MsState) + m + 2 * m;
  if (!SEGENV.allocateData(need)) { SEGMENT.fill(SEGCOLOR(0)); FX_DONE; }

  MsState  *s   = (MsState *)SEGENV.data;
  uint8_t  *az  = (uint8_t *)(s + 1);
  uint16_t *lr  = (uint16_t *)(az + m);

  const uint8_t want = (uint8_t)(cube ? 1 : 2);
  const bool fresh = (SEGENV.call == 0 || s->mode != want);
  if (fresh) {
    s->mode = want;
    s->tPhase = 0; s->tColour = 0; s->surge = 0;
    s->sinceKick = 0; s->dir = 256;
    s->corner = 0; s->lastChk = SEGMENT.check2 ? 1 : 0; s->builtFor = 255;
    s->clk[0] = s->clk[1] = 0;
  }

  // The checkbox is a toggle AND a "next". Every time it goes ON it advances
  // to the following corner, so tapping it walks round the cube; turning it
  // off puts the sink back on the lid. One control, four positions plus home,
  // which is the most a checkbox has any right to carry.
  {
    const uint8_t now2 = SEGMENT.check2 ? 1 : 0;
    if (now2 && !s->lastChk) s->corner = (uint8_t)((s->corner + 1) & 3);
    s->lastChk = now2;
  }
  const uint8_t centreId = SEGMENT.check2 ? (uint8_t)(1 + s->corner) : 0;
  if (s->builtFor != centreId || fresh) {
    s->builtFor = centreId;
    if (centreId == 0) {
      ms_build(az, lr, cols, rows, B, cube, 0.0f, 0.0f, 1.0f, -1);
    } else {
      const int k = centreId - 1;
      const float cx = (int8_t)pgm_read_byte(&MS_CORNER[k][0]) / 127.0f;
      const float cy = (int8_t)pgm_read_byte(&MS_CORNER[k][1]) / 127.0f;
      const float cz = (int8_t)pgm_read_byte(&MS_CORNER[k][2]) / 127.0f;
      const float l  = sqrtf(cx * cx + cy * cy + cz * cz);
      ms_build(az, lr, cols, rows, B, cube, cx / l, cy / l, cz / l, k);
    }
  }

  uint16_t dt = fx_dt8(s->clk);
  if (dt > 60) dt = 60;

  // --- audio ------------------------------------------------------------------
  um_data_t     *um  = cfx_getAudioData();
  const float    vol = *(float *)um->u_data[0];
  // Always on. Beat detection was a checkbox, but with it off the surge went
  // and the reverse-on-silence went with it, which left the box meaning "make
  // this effect ignore the music entirely" - a thing nobody needs a control
  // for when there is a whole non-reactive palette of effects next to it.
  const uint8_t  beat = fx_lowBeat(um);
  if (beat > s->surge) s->surge = beat;
  { const int f = (int)s->surge - (int)fx_step(5, dt);
    s->surge = (uint8_t)(f < 0 ? 0 : f); }

  // --- parameters ---------------------------------------------------------------
  // Bands per octave of radius. The one control that changes what the figure
  // IS rather than how it moves: at 1 a slow whirlpool, at 5 a tunnel.
  //
  // Five, not eight. A wall spans about one octave of radius, so on a 16-pixel
  // face the band count IS the pixel count somewhere past five - measured, the
  // rings counted down a wall run 3, 3, 6, 7, 10 and then fall back to 7 as
  // they alias. A control whose top third undoes itself is worse than a
  // shorter one. Near the sink the figure aliases whatever this is set to, and
  // that is fine: it is a singularity and reads as texture, which is the
  // hypnosis rather than a defect.
  const int dens = 1 + ((int)cfx_c3full(SEGMENT.custom3) * 4) / 255;

  // Arms. Zero is legal and gives concentric rings - a target rather than a
  // spiral - which is worth having and is why the range starts there.
  const int arms = ((int)SEGMENT.custom1 * 9) / 255;

  // --- which way it is going ----------------------------------------------------
  // Inward while the kicks keep coming, outward when they stop.
  if (beat > 40) s->sinceKick = 0;
  else if (s->sinceKick < 60000 - dt) s->sinceKick += dt;

  const bool quietNow = (s->sinceKick > 2200);
  const int  dirT = quietNow ? -256 : 256;
  {
    // A full turnaround takes about 1.4 s, which is slow enough to watch the
    // figure stall and slow enough that a gap between phrases does not set it
    // rocking back and forth.
    const int stp = (int)((512L * (int32_t)dt) / 1400) + 1;
    if (s->dir < dirT) { s->dir = (int16_t)(s->dir + stp); if (s->dir > dirT) s->dir = (int16_t)dirT; }
    else if (s->dir > dirT) { s->dir = (int16_t)(s->dir - stp); if (s->dir < dirT) s->dir = (int16_t)dirT; }
  }

  const int32_t adv0 = ((24 + (int32_t)SEGMENT.speed * 5) * (int32_t)dt) / 23;
  const int32_t adv  = (adv0 * (int32_t)s->dir) / 256;
  s->tPhase += (uint32_t)(adv + ((adv * (int32_t)s->surge) / 200));
  const int32_t cadv = ((int32_t)SEGMENT.custom2 * 4 * (int32_t)dt) / 23;
  s->tColour += (uint32_t)cadv;

  // Which way the colour runs.
  //
  // The palette gradient has to lie along SOME direction in the figure, and
  // the two that mean anything are the two the spiral itself defines. Across
  // the arms - the default - gives each arm one colour and marches the colours
  // through the bands, so the figure reads as coloured rings turning. Along
  // the arms puts the whole palette down the length of each arm instead, so a
  // single arm runs through the spectrum from the sink to the rim and the
  // colour crawls outward along it.
  //
  // The along-coordinate is not a guess: bands are lines of constant
  // dens*lr + arms*az, so the direction that travels ALONG a band is the one
  // that leaves that sum unchanged, and arms*lr - dens*az is the coordinate
  // which varies fastest that way. It falls out of the same two numbers that
  // draw the spiral, which is why it stays square to the arms at every setting
  // of Arms and Density rather than only at the one it was tuned for.
  const bool along = SEGMENT.check1;

  const int bias = ((int)SEGMENT.intensity * 120) / 255;
  const int gain = 256 + (int)SEGMENT.intensity * 4;
  const uint8_t drive = cfx_drive(vol, 0.5f, 175);
  const uint16_t ph = (uint16_t)(s->tPhase >> 8);
  const uint8_t  cs = (uint8_t)(s->tColour >> 8);

  // --- paint --------------------------------------------------------------------
  CFX_NET_PREP();
  for (int y = 0; y < rows; y++) {
    CFX_NET_ROW(y);
    for (int x = 0; x < cols; x++) {
      CFX_NET_SKIP(x);
      const size_t i = (size_t)cfx_cidx(x, y, cols, B, cube);

      // The spiral coordinate. Subtracting the clock rather than adding it is
      // what makes the arms travel OUTWARD from the sink - the figure falling
      // toward you - instead of draining away into it.
      // NOT shifted. lr is already log2(radius) * 256, so multiplying by the
      // density gives exactly `dens` wraps of the 256-unit band per octave -
      // which is the definition of the control. Shifting it back down by 8, as
      // this first did, left the radial term spanning 24 units out of 256 from
      // the pole to the base: a tenth of one band across the whole cube. The
      // azimuth then had the figure to itself and it drew a four-pointed star.
      const int vv = (int)lr[i] * dens + (int)az[i] * arms;
      const uint8_t v = (uint8_t)(vv - (int)ph);

      // Colour rides the bands when running across them, so an arm keeps one
      // hue as it travels; when running along them it is the arms that sweep
      // through a colour field instead, so the zoom is deliberately left out.
      // Divided down HARD. The along-coordinate runs about 6000 units from the
      // sink to the base, which is two dozen full trips round the palette
      // along a single arm - fine stripes crawling up it, not the broad bands
      // that were wanted. Shifted down by four it makes roughly one and a half
      // sweeps of the palette across the whole figure, so each arm carries two
      // or three big swaths whose edges lie square across it and which travel
      // outward along the arm as the colour scrolls.
      const int cw = along ? (((int)lr[i] * arms - (int)az[i] * dens) >> 4) : (int)v;

      // Bands. A sine gives a soft barber pole; biasing and gaining it hardens
      // the arms and opens real black between them, which is what stops a
      // figure this busy turning into a single bright smear.
      int h = (int)sin8_t(v);
      h = ((h - bias) * gain) >> 8;
      if (h < 0) h = 0; else if (h > 255) h = 255;
      h = (h * (200 + ((int)s->surge * 55) / 255)) >> 8;
      if (h > 255) h = 255;

      uint32_t c = 0;
      if (h) {
        // Palette position follows the band and scrolls with time, so an arm
        // holds one colour along its whole length and the whole figure cycles.
        c = SEGMENT.color_from_palette((uint8_t)(cw + cs), false, true, 0);
        c = mq_scale(c, (uint8_t)h);
      }
      SEGMENT.setPixelColorXY(x, y, mq_scale(c, drive));
    }
  }
  FX_DONE;
}

static const char _data_FX_MODE_MAELSTROM[] PROGMEM =
  "Ace 3-D Maelstrom@Zoom,Contrast,Arms,Colour cycle,Density,Colour along arms,Corner (tap for next),Flat mode;;!;2f;sx=90,ix=120,c1=85,c2=40,c3=10,pal=11";


// ---------------------------------------------------------------------------
// Registration - joins the effect bank, which decides whether this effect
// claims one of the device's limited effect slots. See cube_fx_bank.h.
// ---------------------------------------------------------------------------
static CfxBankReg cube_fx_32_maelstrom_reg(&mode_maelstrom, _data_FX_MODE_MAELSTROM);
