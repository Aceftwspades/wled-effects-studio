#include "wled.h"
#include "cube_fx_common.h"
#include "cube_fx_bank.h"

// ===========================================================================
// Ace 3-D Voxel Vortex - a ring of cuboids, tumbled by a quaternion
// ===========================================================================
// The cube is used as a CUBEMAP again: every pixel's outward direction is a ray
// leaving the middle of the solid, so the five faces are one panoramic viewport
// onto a scene that surrounds the viewer. Hung in that space is a torus built
// not as a surface but as an INSTANCED GRID - a few hundred rectangular blocks
// laid out on a (u,v) parametrisation, with real gaps between them that you can
// see through. Two apertures, at the poles, open and close on their own clock.
//
// ---------------------------------------------------------------------------
// THE RAY SOLVE IS EXACT, AND IT IS FOUR LINES
// ---------------------------------------------------------------------------
// A ray from the origin is p = t.d. On a torus of major radius R about z,
//
//     (sqrt(px^2 + py^2) - R)^2 + pz^2 = r^2
//
// and with s = sqrt(dx^2 + dy^2) that is t^2 - 2 R s t + R^2 - r^2 = 0, because
// s^2 + dz^2 = 1 collapses the quadratic's leading term to one. So
//
//     t = R s +/- sqrt(r^2 - R^2 dz^2)
//
// and the whole geometry falls out of a single discriminant:
//
//     D <= 0   the ray misses entirely - it is going out through an APERTURE,
//              which makes |dz| < r/R the exact, closed-form statement of how
//              wide the hole is. Nothing is tuned to make the aperture look
//              right; it is what the discriminant says.
//     D > 0    two hits. The near one is the inner wall of the ring, the far
//              one is the far side seen THROUGH the gaps between blocks.
//
// Both roots are positive whenever D > 0 (it needs R > r, which a torus that
// still has a hole always satisfies), so there is no behind-the-viewer case to
// reject. No marching, no epsilon, no step count: about twenty flops per pixel.
//
// The angle round the main axis, atan2(dy,dx), is CONSTANT along a ray through
// the origin, so u comes for free - and the tube angle v is one atan2 at the
// hit. That is the (u,v) grid the brief asks for, arrived at rather than
// imposed, and it is what makes an instanced block lookup a lookup instead of a
// search through a few hundred boxes.
//
// ---------------------------------------------------------------------------
// WHY BOTH HITS ARE DRAWN
// ---------------------------------------------------------------------------
// Drawing only the near wall makes this a texture on a band. Drawing the far
// wall too, dimmer, is what makes it a ring of objects with space inside it:
// look at a gap and you see through to the blocks on the other side, and when
// two gaps line up you see through to nothing at all. That black is not a
// background being revealed, it is the actual absence of geometry along that
// ray, and it costs one extra grid lookup.
//
// It also splits the work usefully. The near hit lands on the inner half of the
// tube and the far hit on the outer half, so between them they cover v in full
// and every block in the ring is reachable from some direction.
//
// ---------------------------------------------------------------------------
// ORIENTATION: A QUATERNION, AND WHY NOT THREE ANGLES
// ---------------------------------------------------------------------------
// The tumble slerps between unit quaternions drawn from a fixed table, one leg
// at a time. Euler angles would have been fewer lines and are the wrong tool
// twice over: a shape whose whole identity is an AXIS spends its life near the
// configuration where two of the three angles control the same rotation, and
// interpolating angles independently sends the axis on a curved, speed-varying
// path that reads as a wobble rather than a turn. Slerp is a great circle at
// constant angular velocity, which is what "it is turning" looks like.
//
// The table, the slerp and the retargeting are CfxTumble in cube_fx_common.h -
// they started here and were promoted when Helix Tunnel became the second
// effect with an axis to wander. The measurement behind the table is recorded
// there.
//
// ---------------------------------------------------------------------------
// THE VORTEX, AND WHERE THE POWER LAW WENT
// ---------------------------------------------------------------------------
// The twist is the brief's u' = u + k.rho.t applied literally, with rho the
// distance from the axis at the hit point. Since rho - R = r cos v, the shear
// across the tube is a cosine, so blocks lean one way on the inner wall and the
// other way on the outer one - the crescent look, and it is the geometry doing
// it rather than a texture.
//
// The power scaling asked for on the radial coordinate is applied to the
// APERTURE, once per frame, where it belongs and where it costs one powf:
// r = r0 * pow(breath, p) turns a sine breath into something that dwells at one
// end and snaps through the other. Per pixel the profile warp is a quadratic
// instead, because a powf on every hit is 2,560 of them a frame and at sixteen
// pixels to a face the two are indistinguishable. The place where the exponent
// is actually visible is the one that got it.
//
// ---------------------------------------------------------------------------
// THE HEXAGONS ARE ONLY EVER SEEN THROUGH A HOLE
// ---------------------------------------------------------------------------
// The backdrop is a hex tessellation - two interleaved triangular lattices,
// which is what a hex lattice is - and it is drawn ONLY where D <= 0, that is,
// only out through an aperture. That is not a rule, it is what makes the chart
// safe: the projection is the honest homogeneous divide, x/w with w = |dz|, and
// D <= 0 guarantees |dz| >= r/R, so w has a floor of about 0.45 and the
// perspective divide can never blow up. Reached through a block gap instead,
// where dz can be anything, the same divide would go to infinity at the
// horizon and paint a band of aliased noise round the equator.
//
// So the two ways of seeing past the ring stay distinct: out through the hole
// is a lattice, out through the gaps is black.
// ===========================================================================

#define VX_R      1.00f          // major radius. the object is scale-free, so
                                 // this is a unit, not a tuning
#define VX_TWOPI  6.28318531f
struct VxState {
  uint8_t  mode;
  uint8_t  clk[2];
  uint8_t  surge;
  CfxTumble tumble;              // the orientation - see cube_fx_common.h
  uint16_t spin;                 // the vortex's own rotation
  uint16_t kick;                 // rotation owed to spin but not yet delivered
  uint16_t breath;               // aperture clock
  uint16_t drift;                // palette rotation
};

// Wrap into [0,m). fmodf is signed, and a negative local coordinate in the hex
// lattice would put the cell centre in the wrong place - visible as a seam.
static inline float vx_wrap(float v, float m) {
  v -= m * floorf(v / m);
  return (v < 0.0f) ? 0.0f : v;
}

static FX_RET mode_voxelvortex() {
  if (!strip.isMatrix || !SEGMENT.is2D()) { SEGMENT.fill(SEGCOLOR(0)); FX_DONE; }
  const int cols = SEG_W, rows = SEG_H;
  if (cols < 8 || rows < 8) { SEGMENT.fill(SEGCOLOR(0)); FX_DONE; }

  const bool cube = cfx_isCube(cols, rows);
  const int  B    = cube ? (cols / 3) : 1;

  if (!SEGENV.allocateData(sizeof(VxState))) { SEGMENT.fill(SEGCOLOR(0)); FX_DONE; }
  VxState *s = (VxState *)SEGENV.data;

  const uint8_t want = (uint8_t)(cube ? 1 : 2);
  if (SEGENV.call == 0 || s->mode != want) {
    s->mode = want; s->clk[0] = s->clk[1] = 0;
    cfx_tumbleInit(s->tumble);
    s->spin = 0; s->kick = 0; s->breath = 0; s->drift = 0; s->surge = 0;
  }

  uint16_t dt = fx_dt8(s->clk);
  if (dt > 60) dt = 60;

  // --- parameters -----------------------------------------------------------
  const int  fill    = (int)SEGMENT.intensity * 2;
  const int  blockI  = (int)SEGMENT.custom1;
  const int  twistI  = (int)SEGMENT.custom2;
  const int  flareI  = (int)cfx_c3full(SEGMENT.custom3);   // custom3 is 5-bit
  const bool lattice = SEGMENT.check2;

  // Blocks round the ring, and across the tube. The tube count spans BOTH
  // walls, so half of it is what you see on the near one - hence the wider
  // range on v than the arithmetic suggests.
  const int NU = 7  + (blockI * 22) / 255;
  const int NV = 5  + (blockI * 9)  / 255;

  // --- audio ----------------------------------------------------------------
  um_data_t     *um   = cfx_getAudioData();
  const float    vol  = *(float *)um->u_data[0];
  const uint8_t  beat = SEGMENT.check1 ? fx_lowBeat(um) : 0;
  if (beat > s->surge) s->surge = beat;
  { const int f = (int)s->surge - (int)fx_step(32, dt);
    s->surge = (uint8_t)(f < 0 ? 0 : f); }

  // A lurch round the ring, owed rather than applied. Delivered whole, the
  // blocks would cut to a new position and the travel between the two states
  // is never drawn - which reads as a glitch, not as a hit. A third of the
  // debt a frame puts most of it inside 140 ms and leaves the rush visible.
  if (beat) {
    uint32_t k = (uint32_t)s->kick + (uint32_t)beat;
    if (k > 620u) k = 620u;
    s->kick = (uint16_t)k;
  }
  if (s->kick) {
    uint32_t give = ((uint32_t)s->kick * (uint32_t)dt) / 70u;
    if (!give) give = 1;
    if (give > s->kick) give = s->kick;
    s->spin = (uint16_t)(s->spin + give * 44u);
    s->kick = (uint16_t)(s->kick - give);
  }

  // --- clocks ---------------------------------------------------------------
  { const uint32_t r = (uint32_t)(3 + (int)SEGMENT.speed / 2) * (uint32_t)dt / 23u;
    s->spin   = (uint16_t)(s->spin + r);
    // The tumble is deliberately the slowest thing here. A leg is a 97-162
    // degree turn; run it at the ring's own rate and the shape never holds
    // still long enough to be read as a shape.
    cfx_tumbleStep(s->tumble, (uint16_t)(r / 5u));
    s->breath = (uint16_t)(s->breath + (r * 2u) / 7u); }
  s->drift = (uint16_t)(s->drift + ((uint32_t)dt * (uint32_t)SEGMENT.speed) / 90u);

  // Orientation, once per frame: slerp along the leg, then the world -> object
  // matrix. Every pixel's ray goes through this.
  float M[3][3];
  cfx_tumbleMatrix(s->tumble, M);

  // --- the aperture ---------------------------------------------------------
  // Power scaling on the breath: the exponent runs 0.45 to 2.4, so low Flare
  // dwells wide open and snaps shut, high Flare dwells shut and flicks open.
  // The linear middle is the boring case and it is where the slider is not.
  float rr;
  { const float ph = (float)s->breath * (VX_TWOPI / 65536.0f);
    float g = 0.5f + 0.5f * cfx_sinf16(ph);                     // 0..1
    const float p = 0.45f + (float)flareI * (1.95f / 255.0f);
    g = powf(g, p);
    rr = 0.44f + 0.46f * g;                                 // 0.44 .. 0.90 R
    // The beat dilates the hole. Geometry, not gain: |dz| < r/R is the exact
    // rim, so widening r MOVES it - every pixel along the aperture edge changes
    // what it is looking at. Brightening on the beat would have raised the
    // whole baseline instead of producing an event.
    rr += (float)s->surge * (0.09f / 255.0f);
    if (rr > 0.93f) rr = 0.93f;                             // r < R or the hole shuts
  }
  const float rr2 = rr * rr;

  // Profile warp. The near wall is v in the back half, the far wall the front
  // half, and this leans block boundaries toward one end of each - a flare
  // rather than an even ladder. Quadratic, monotone for |k| <= 1: see header.
  const float warp = ((float)flareI - 128.0f) * (0.85f / 128.0f);

  // Twist: u' = u + k (rho - R). rho - R is r cos v, so this is a cosine shear
  // across the tube, up to two and a half turns of it end to end.
  const float twist = (float)twistI * (1.35f / 255.0f) / (rr > 1e-3f ? rr : 1e-3f);
  const float phase = (float)s->spin * (1.0f / 65536.0f);

  // Grout. Held as a fraction of a cell, so the blocks stay blocks as the grid
  // gets denser instead of the gaps closing up.
  const float gap  = 0.11f;
  const float gapU = gap, gapV = gap;

  // Light lives in the cube's frame, so a highlight stays put on the solid
  // while the ring tumbles past it.
  float Lx, Ly, Lz;
  { const float lx = 0.36f, ly = -0.42f, lz = 0.83f;
    Lx = M[0][0]*lx + M[0][1]*ly + M[0][2]*lz;
    Ly = M[1][0]*lx + M[1][1]*ly + M[1][2]*lz;
    Lz = M[2][0]*lx + M[2][1]*ly + M[2][2]*lz; }

  const uint8_t hueOff = (uint8_t)(s->drift >> 8);
  const uint8_t drive  = cfx_drive(vol, 0.5f, 200);
  // Cell size. Bigger than it wants to be from the arithmetic: the aperture
  // is a small part of the view and hexagons only read as hexagons if a few
  // large ones fill it. At 4 they were a field of dots.
  const float   hexK   = 2.4f;

  // --- paint ----------------------------------------------------------------
  CFX_NET_PREP();
  for (int y = 0; y < rows; y++) {
    CFX_NET_ROW(y);
    for (int x = 0; x < cols; x++) {
      CFX_NET_SKIP(x);

      float X, Y, Z; cfx_pos(x, y, cols, rows, B, cube, X, Y, Z);
      if (!cube) Z = 1.0f - (X * X + Y * Y) * 0.5f;      // a panel becomes a dome
      const float PL = sqrtf(X * X + Y * Y + Z * Z);
      const float iL = (PL > 1e-6f) ? (1.0f / PL) : 1.0f;

      // the ray, in the ring's own frame
      float dx = X * iL, dy = Y * iL, dz = Z * iL;
      { const float ax = M[0][0]*dx + M[0][1]*dy + M[0][2]*dz;
        const float ay = M[1][0]*dx + M[1][1]*dy + M[1][2]*dz;
        const float az = M[2][0]*dx + M[2][1]*dy + M[2][2]*dz;
        dx = ax; dy = ay; dz = az; }

      int     lum = 0;
      uint8_t idx = hueOff;

      const float D = rr2 - VX_R * VX_R * dz * dz;
      if (D <= 0.0f) {
        // --- out through an aperture: the hex backdrop ---------------------
        if (lattice) {
          // The homogeneous divide, with w = |dz|. D <= 0 floors w at rr, so
          // this is the one place the projection is safe. See the header.
          const float w  = (dz < 0.0f) ? -dz : dz;
          const float hx = dx / w * hexK, hy = dy / w * hexK;

          // Two interleaved triangular lattices, which is what a hex lattice
          // is. Whichever centre is nearer owns the pixel.
          const float H = 1.7320508f;
          const float ax = vx_wrap(hx, 1.0f) - 0.5f;
          const float ay = vx_wrap(hy, H)    - H * 0.5f;
          const float bx = vx_wrap(hx + 0.5f,     1.0f) - 0.5f;
          const float by = vx_wrap(hy + H * 0.5f, H)    - H * 0.5f;
          const bool  useA = (ax*ax + ay*ay) < (bx*bx + by*by);
          const float lx = useA ? ax : bx, ly = useA ? ay : by;

          const float px = (lx < 0.0f) ? -lx : lx;
          const float py = (ly < 0.0f) ? -ly : ly;
          const float hd = (0.5f * px + 0.8660254f * py > px)
                         ? (0.5f * px + 0.8660254f * py) : px;
          const float edge = 0.5f - hd;                   // 0 at the wall
          if (edge < 0.19f) {
            float g = 1.0f - edge * (1.0f / 0.19f);
            if (g < 0.0f) g = 0.0f;
            g = g * g;
            lum = (int)((float)fill * g * 0.58f);
            idx = (uint8_t)(hueOff + 150);
          }
        }
      } else {
        const float sxy = sqrtf(dx * dx + dy * dy);
        const float sd  = sqrtf(D);
        const float base = VX_R * sxy;
        const float ang  = cfx_atan2f(dy, dx);            // constant along the ray

        // Near wall first, then the far wall seen through its gaps.
        for (int pass = 0; pass < 2; pass++) {
          const float t = pass ? (base + sd) : (base - sd);
          if (t <= 1e-4f) continue;
          const float rho = t * sxy, zet = t * dz;
          const float v   = cfx_atan2f(zet, rho - VX_R);  // tube angle, -pi..pi

          float vv = v * (1.0f / VX_TWOPI) + 0.5f;        // 0..1
          vv += warp * vv * (1.0f - vv);                  // the flare, quadratic
          float uu = ang * (1.0f / VX_TWOPI) + 0.5f
                   + twist * (rho - VX_R) + phase;

          const float gu = uu * (float)NU, gv = vv * (float)NV;
          const float fu = gu - floorf(gu), fv = gv - floorf(gv);
          if (fu < gapU || fu > 1.0f - gapU) continue;    // grout
          if (fv < gapV || fv > 1.0f - gapV) continue;

          // --- shading ------------------------------------------------------
          // The block's normal is the torus normal at the hit: straight out
          // from the tube's centre circle.
          const float ir = 1.0f / rr;
          const float cu = (sxy > 1e-6f) ? (dx / sxy) : 1.0f;
          const float su = (sxy > 1e-6f) ? (dy / sxy) : 0.0f;
          const float Nx = (rho - VX_R) * ir * cu;
          const float Ny = (rho - VX_R) * ir * su;
          const float Nz = zet * ir;

          // Half-Lambert. A block lit by one source has half its visible face
          // turned away, and clamped at zero that half is bare ambient - which
          // reads as murk rather than as shading. Squaring keeps the
          // terminator from going flat.
          float diff = 0.5f + 0.5f * (Nx*Lx + Ny*Ly + Nz*Lz);
          diff *= diff;

          // A bevel: brighter toward the middle of a face, so a block reads as
          // a solid with edges rather than as a lit rectangle. This is the
          // cheapest thing that makes instancing visible at sixteen pixels to
          // a face.
          const float eu = (fu < 0.5f ? fu : 1.0f - fu) - gapU;
          const float ev = (fv < 0.5f ? fv : 1.0f - fv) - gapV;
          const float e  = (eu < ev ? eu : ev) * (1.0f / (0.5f - gap));
          const float bev = 0.68f + 0.32f * (e > 1.0f ? 1.0f : e);

          // Perspective: the homogeneous divide again, this time as depth.
          // t IS the w that the projection would have divided by, so nearer
          // blocks are brighter and the ring reads as having an inside.
          float dep = 1.30f / (0.55f + t * 0.55f);
          if (dep > 1.35f) dep = 1.35f;

          float shade = (0.26f + 0.90f * diff) * bev * dep;
          if (pass) shade *= 0.62f;                        // the far wall

          lum = (int)((float)fill * shade);
          // Hue from the block's own index, so neighbours differ and the grid
          // is legible as a grid. Coprime strides, or whole rows share a hue.
          idx = (uint8_t)(hueOff + (int)floorf(gu) * 17 + (int)floorf(gv) * 29);
          break;
        }
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

static const char _data_FX_MODE_VOXELVORTEX[] PROGMEM =
  "Ace 3-D Voxel Vortex@Tumble,Fill,Blocks,Twist,Flare,Beat surge,Lattice,Flat mode;;!;2f;sx=100,ix=128,c1=110,c2=120,c3=16,o1=1,o2=1,pal=11";


// ---------------------------------------------------------------------------
// Registration - joins the effect bank, which decides whether this effect
// claims one of the device's limited effect slots. See cube_fx_bank.h.
// ---------------------------------------------------------------------------
static CfxBankReg cube_fx_45_voxelvortex_reg(&mode_voxelvortex, _data_FX_MODE_VOXELVORTEX);
