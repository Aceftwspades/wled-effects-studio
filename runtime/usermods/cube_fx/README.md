# Cube FX

A family of audio-reactive and motion-reactive LED effects for WLED, built for a
**five-faced LED cube** — a matrix folded into a cross-shaped net so that one flat
segment drives the top face and four walls at once. Everything degrades cleanly to
a flat panel, so the effects are usable on an ordinary 2-D matrix too.

The set ships as a WLED usermod. Alongside the effects it includes an optional
on-cube control surface — a rotary-encoder menu on a small OLED — and drivers for a
motion sensor and a microphone, so a finished cube can be operated without a phone.

---

## What you get

- **34 effects** — cube-native 3-D pieces, flat 2-D analysers, a couple of games,
  and motion toys. Full catalogue below.
- **A cube geometry layer** — every pixel gets a real position on the cube surface,
  so effects are continuous across the folds with no seam handling in the effect
  code. On a non-cube matrix the same effects fall back to a flat plane.
- **Optional accessories**, each a self-contained usermod you can leave out:
  - a **microphone** (WLED's stock `audioreactive`) for sound reactivity,
  - an **MPU6050 IMU** for tilt, shake, and orientation,
  - one or two **rotary encoders** + an **OLED** for on-device control.
- **Per-effect parameter memory** — the sliders you leave an effect on are
  remembered and restored next time you select it, keyed by effect name so it
  survives rebuilds.

---

## Hardware

### Controller

| Board | Environment | Notes |
|-------|-------------|-------|
| ESP32 (classic) | `esp32dev_customfx` | The default. ~92% of a 1.5 MB app partition. |
| ESP32-S3 (e.g. N16R8) | `esp32s3_customfx` | 3 MB app partition, PSRAM lifts the segment-data cap, hardware-accelerated FFT. Digital I2S mic required — the S3 has no analog-mic path. |

Both environments live in `platformio_override.ini`. Audio needs an I2S microphone
on the S3; the classic ESP32 also accepts an analog mic.

### The LED cube

The cube is a single matrix segment laid out as a **3×3 grid of B×B blocks**. The
four corner blocks are unlit gaps; the centre block is the **top face** and the four
edge blocks fold up into the **four walls**. The bottom is open — five faces, not
six — unless you have a six-faced cube, in which case the **bottom face takes the
bottom-right corner block** (under EAST, right of SOUTH) and the net stays the same
3×3 square.

```
        +--------+                    +--------+
        | NORTH  |                    | NORTH  |
   +----+--------+----+          +----+--------+----+
   |WEST|  TOP   |EAST|          |WEST|  TOP   |EAST|
   +----+--------+----+          +----+--------+----+
        | SOUTH  |                    | SOUTH  |BOTTOM|
        +--------+                    +--------+------+
          five faces                      six faces
```

**Optional parts.** The IMU driver, the encoder + OLED menu and the per-effect
slider memory each compile only while their flag is 1 - `CFX_WITH_IMU`,
`CFX_WITH_UI`, `CFX_WITH_PARAM_MEMORY`, all 1 by default - and audioreactive's
PCM slot only while `CFX_PCM` is 1. Pass `-D CFX_WITH_IMU=0` (etc.) in
`build_flags` for a device without that hardware; the studio's flash dialog
has a picker that does exactly this. Everything degrades: no IMU means gravity
settles to top-face-up, no PCM means Warp and Scope rebuild a waveform from the
FFT bins.

Six faces is a setting, not a different net: tick **six_faces** on the CubeFXBank
usermod's settings page (or build with `-D CFX_SIX_FACES=1`, which the studio does
for a project whose cube has six). Every effect that reads pixel positions through
`cfx_pos()` — nearly all of them — lights the bottom as the sixth face; the bottom's
orientation is `X = a, Y = -b, Z = -1`: looked at from below, north is up. A few
effects that ride the walls as a band or walk cells across folds (Tron, Matrix Rain,
Breakout, DNA Helix, Whirlpool, Cube Fire, Split GEQ) leave the bottom dark. The
bottom-face ledmap letter is `B`; `faces` becomes `N,W,T,E,S,B`.

**These names are a fixed convention, and getting the physical cube to match them
is the whole of orientation setup.** Hold the cube the way you normally look at it:
**SOUTH is the face toward you**, NORTH is the far side, TOP is up, and WEST/EAST are
left/right. The **Cube Axes** effect is the tool that makes this real rather than
theoretical — see the calibration note below.

**Two numbers, and only one of them is the segment.** This is the single most common
point of confusion, so it's worth stating plainly:

- **Face resolution `B`** — the pixels along one edge of a single face. An "8×8 cube"
  usually means **B = 8**: five 8×8 panels.
- **Segment size** — what you enter in WLED. Because the net is a 3×3 grid of B×B
  blocks, **the segment is always `3B × 3B`**, three times the face on each side. It
  is *not* the face size.

So an 8×8-faced cube is a **24×24 segment**, not an 8×8 one. Set the segment to the
unfolded net size, never the face size.

**Supported cube sizes.** A segment is treated as a cube when it is **square, its
side is a multiple of 3, and the side is at least 12** — i.e. `B ≥ 4`. The side
divided by three is the face resolution `B`:

| Face `B` | Panels per face | Segment (`3B × 3B`) | |
|----------|-----------------|---------------------|---|
| 4  | 4×4   | 12×12 | smallest usable cube |
| 8  | 8×8   | 24×24 | |
| 16 | 16×16 | 48×48 | the reference build |
| N  | N×N   | 3N×3N | any N ≥ 4 |

Bigger `B` is better for the game and text effects, which need a few pixels per face
to read. Below B=4 there simply isn't room for the geometry, and a segment under
12×12 isn't recognised as a cube at all — it runs as a flat panel (below).

**Cube Axes — the calibration tool.** The first effect, *Ace 3-D Cube Axes*, is not a
show effect; it paints each pixel's position directly: **+X → red (east), +Y → green
(north), +Z → blue (up)**. That turns three otherwise-invisible things into something
you can just look at, and it is worth running first on any new build.

- **Is the segment a cube at all?** On a real cube net the four corner blocks go
  **dark** (the gaps) and the colour flows smoothly over every edge. On a flat panel
  (e.g. a segment set to the face size 8×8 instead of the net 24×24) there are no dark
  corners, just a gradient — the effect is silently running its flat fallback and not
  driving the five faces.
- **Is a face rotated or mirrored?** A **hard colour break at a seam** means that face
  is flipped relative to what the geometry assumes. Note which seam; the five face
  lines in `cfx_pos()` (in `cube_fx_common.h`) are the only place that needs changing.
- **Does the map match the physical cube?** This is the step that matters for the IMU.
  Compare the preview — the effect thumbnail in the WLED UI, or the on-cube view — to
  the cube in your hand, held with **SOUTH facing you**. Red should brighten toward
  your right (east), green toward the far side (north), blue toward the top. When the
  preview and the physical cube agree in that orientation, the axis convention the
  effects use is the same one you're holding — which is exactly what the MPU6050 axis
  mapping has to line up with (see *Motion*, below). Sorting this out here, visually,
  is far easier than chasing it later through an IMU that thinks up is sideways.

### Flat panels, and the misdetection caveat

On any matrix that is **not** a cube net, every effect falls back to a flat plane and
still works — ripples become circles, the globe becomes a polar mandala, and so on.

There is one trap. Cube detection is automatic and geometric, so a **flat square
panel whose side happens to be a multiple of 3 and ≥ 12** — a 12×12, 18×18, or 24×24
flat matrix — is **misdetected as a cube**. You'll see the four corners go dark and
the image warp across invisible folds.

The fix is per-effect: tick **Flat mode**, which is always the **last checkbox** in
an effect's settings. It forces flat rendering regardless of the segment's shape.

Panels whose side is *not* a multiple of 3 — 16×16, 32×32, 8×32, and most strips —
are never misdetected, so Flat mode is only relevant on those specific square sizes.

### Optional accessories

| Accessory | Usermod | Adds | Effects that use it |
|-----------|---------|------|---------------------|
| Microphone | `audioreactive` (stock WLED) | real sound reactivity | most effects (they animate without it, but only *react* with it) |
| MPU6050 IMU | `ace_imu_mpu6050` | tilt, shake, orientation | the Gyro effects (below) |
| Rotary encoder ×1–2 | `ace_ui_encoder` | on-cube menu control; play Breakout | Breakout needs one to play |
| OLED 128×64 / 128×32 | `ace_ui_screen` | the on-cube menu display | — |

None are required. Effects run on a bare cube; the accessories add reactivity and
local control.

---

## Effect catalogue

Every effect works on the cube and degrades to a flat panel. The **Needs** column
lists what an effect *reacts to* — all audio effects still animate without a mic (on
WLED's simulated-sound generator), and all Gyro effects still run without the IMU
(gravity reads as straight down the cube's own Z). "Needs" means "for the intended
experience."

### Cube 3-D

| Effect | Needs | What it is |
|--------|-------|-----------|
| Cube Axes | — | Calibration aid: X/Y/Z as R/G/B. Verify the net mapping. |
| Cube Ripples | mic | Beat-spawned spherical wavefronts crossing every edge. |
| Spectral Globe | mic | Latitude = frequency, azimuth folded into petals. |
| Cube Slice | mic | A tumbling plane of spectrum sweeping through the solid. |
| Cube Edges | mic | Edges lined; beat pulses run edge↔centre and along the edges. |
| Cube Frame | mic | A free-floating wireframe you can spin out of alignment. |
| Cube Chladni | mic | The nodal surface of a 3-D box mode, cut by the cube's faces. |
| Cube Bloom | mic | Lobed shells, each shape fixed from the FFT at the beat. |
| Rubiks Cube | mic | A real 3×3 puzzle: scramble, then unwind on the beat. |
| Cube Cell | mic | Nested sines evaluated on the 3-D surface. |
| Cube Wire | mic | Edges only; beat pulses run along them with trails. |
| Tron | mic | Light-cycle trails wrapping the faces. |
| Liquid | mic | A level surface that stays level as the cube tilts. |
| Split GEQ | mic | Equator-split bars, or a circular GEQ on every face. Second slider spins each face. |
| Quadrant Labyrinth | mic | Maze walls that reconfigure on the beat. |
| Cube Speaker | mic | The cube rendered as a driver cone pumping to the audio. |
| DNA Helix | mic | A double helix winding around the cube. |
| Plasma | mic | Summed plane waves, one per band, with real dark negative space. |
| Matrix Rain | mic | Glyph columns pouring off the lid and down the walls. |
| Whirlpool | mic | An eye on the lid with arms spiralling out onto the walls (fluid advection). |
| Cube Fire | mic | A smouldering base flaring on bass hits; the lid carries the heat leading off the wall tops. |
| Soap | mic | Curl-noise flow folding palette colour over the whole solid — the cube-native answer to WLED's Soap. |
| Black Hole | mic | A round void on the lid, an accretion disc winding into it, and one bright arc riding the horizon. |
| Spectral Wormhole (3-D) | mic | A spectrum analyser around the bottom edge pouring water up the walls into a swirling film on the lid. Bands wrap once around, or mirror per wall so bass meets bass at two corners and treble at the other two. |

### Gyro (motion) — best with the MPU6050

| Effect | Needs | What it is |
|--------|-------|-----------|
| Gyro Wire | IMU | Cube Wire that hangs its wireframe on real gravity. |
| Question Block | IMU | The ? block: shake it and knock items loose; shake *hard* to shatter it. |
| Gyro Liquid | IMU | Liquid whose surface follows the room, not the cube. |
| Audio Atlas | IMU + mic | A band map locked to world-up as you turn the cube. |
| Gyro Sand | IMU + mic | A glass box of sand poured by real gravity; beats burst it like fireworks. |
| Gyro Rain | IMU + mic | Rain that always falls down, whichever way the cube is held. |

### Games

| Effect | Needs | What it is |
|--------|-------|-----------|
| Breakout | 1–2 encoders | Two-player Breakout wrapped around the cube. Bricks cap the lid and upper walls; the ball circles the loop. With the knobs idle, both paddles play themselves as an ambient demo. |

### Flat 2-D analysers (also fine on the cube)

These predate the cube geometry and are strongest on a flat matrix, but run on the
cube too.

| Effect | Needs | What it is |
|--------|-------|-----------|
| Chladni Plate | mic | Standing-wave nodal lines from the two loudest bins. |
| Spectral RD | mic | Gray-Scott reaction-diffusion; bass feeds, treble kills. |
| Harmonic Lissajous | mic | Locks on consonant intervals, wanders on dissonance. |
| Kaleidoscope | mic | A true mirror-fold of a live noise chamber. |
| Moire Rosette | mic | Interference between two counter-rotating gratings. |
| Spectral Wormhole (2-D) | mic | A log-polar spiral, spectrum falling inward forever. Unrelated to the 3-D effect of the same name above, which shares only the title. |
| Glass Kaleidoscope | mic | Discrete glass chips — circles, squares, triangles, stars. |

---

## Accessories in depth

### Microphone — `audioreactive`

The stock WLED audioreactive usermod. Add it to `custom_usermods` (it's already in
the sample override). Every audio effect reads through it; when it's absent the
effects fall back to WLED's simulated-sound generator, so they animate but do not
respond to real sound. On the ESP32-S3 the mic must be **digital I2S** — there is no
analog-mic path on that chip, and an analog mic fails silently (the effects look
alive on simulated audio while hearing nothing).

### Motion — `ace_imu_mpu6050`

An MPU6050 on I2C gives the Gyro effects tilt, shake, and orientation. Defaults are
SDA **21** / SCL **13** (or −1 to follow LED Preferences). Settings cover the sensor
ranges (±4 g / ±500 °/s suit a handled cube), the axis mapping (which sensor axis
points cube east/north/up), and a gravity-fusion time constant.

**Set the axis mapping against Cube Axes, not against the datasheet.** The three
`axisX/Y/Z` settings tell the driver which sensor axis points cube east, north, and
up — and the *cube* directions they refer to are the ones you confirmed visually with
the Cube Axes effect (holding the cube SOUTH-toward-you; see above). Get those two to
agree and the Gyro effects behave: tilt the cube and Gyro Sand pours the right way,
Gyro Rain still falls down. If a Gyro effect reacts to the wrong axis — sand runs
uphill, "up" is sideways — an `axisX/Y/Z` entry is swapped or inverted, not the sensor.

Two one-tap calibration actions live in the on-cube **System** menu (or run them from
the usermod's Info controls): **Calibrate gyro** (sit the cube still, top up) writes
the gyro bias, and **Level now** writes a level reference for a board that's glued in
slightly askew. Without the sensor the Gyro effects still run — gravity just reads as
straight down the cube's own Z.

### On-cube control — `ace_ui_encoder` + `ace_ui_screen`

One or two rotary encoders and a small OLED give a full menu on the cube: browse and
apply effects, edit parameters, palettes and presets, brightness, per-segment
mirror/reverse, and power — no phone needed.

- **Encoders** attach on direct GPIO or an MCP23017 expander. Each knob has a *turn*
  role (navigate, brightness, edit, or pinned to one parameter) and a *button* role
  (full click/back/home, or a dedicated back button). A press-and-hold grammar gives
  back / home / lock without a second click, and holding two buttons reboots. Encoder
  A/B need pull-ups — on the module or the internal ones.
- **Screen** drives SSD1306, SH1106, or SSD1309 panels (128×64 or 128×32) over its
  **own I2C bus (Wire1)** by default, **shared I2C** with the IMU, or **hardware
  SPI**. On SPI, the panel owns CS/DC/RST here but SCLK/MOSI come from WLED's global
  SPI pins in LED Preferences — set those or the panel stays dark. The two-colour
  yellow/blue OLEDs are supported as a fixed header band. A partial-update governor
  keeps the panel from ever stealing a cube frame.

Breakout is the one effect that reads the encoders directly: with the game running, a
click on the *Now Playing* screen hands the knobs to the paddles, and a short hold
gives them back. On a cube with no OLED it takes the knobs automatically; with no
encoders at all, it plays itself.

---

## Building and flashing

The effects and accessory usermods live in this folder and compile together. The
`olikraus/U8g2` display library is declared in `library.json`, so it's pulled in
automatically — nothing to add to `platformio.ini`.

`platformio_override.ini` defines the environments:

```ini
[env:esp32dev_customfx]
extends = env:esp32dev
custom_usermods =
  audioreactive
  cube_fx

[env:esp32s3_customfx]
extends = env:esp32s3dev_16MB_opi
custom_usermods =
  audioreactive
  cube_fx
build_flags = ${env:esp32s3dev_16MB_opi.build_flags}
  -D UM_AUDIOREACTIVE_USE_ESPDSP_FFT
```

Build the classic ESP32:

```bash
pio run -e esp32dev_customfx
```

or the S3:

```bash
pio run -e esp32s3_customfx
```

The binary lands in `build_output/release/`. Flash it over USB, or upload directly:

```bash
pio run -e esp32dev_customfx -t upload
```

After flashing, in WLED set up your matrix as one square segment with the cube's gap
map, enable the usermods you want in Settings → Usermods, and set the accessory pins
there.

---

## Notes for developers

### One file per effect

Each effect is a self-contained `cube_fx_NN_name.cpp`: its `mode_*()` function, its
`_data_FX_MODE_*` metadata string, any tables it alone uses, and its own tiny
`Usermod` subclass that calls `strip.addEffect(...)` and `REGISTER_USERMOD(...)`.
WLED compiles every `.cpp` in the folder and lets any number of usermods register
themselves, so **adding an effect touches no other file** — drop in a new
`cube_fx_NN_name.cpp` and rebuild.

The `NN` prefix is just a stable sort order, contiguous from `00`. It carries no
meaning beyond filing order and is renumbered when effects are culled; effects are
identified everywhere that matters by **name**, not number, so renumbering never
invalidates saved settings.

The `cube_fx.cpp` file is the exception: it holds the seven flat 2-D analysers
together, for historical reasons, and registers them the same way.

### Shared code — `cube_fx_common.h`

Anything used by two or more effects lives here: the cube geometry (`cfx_pos`,
`cfx_buildCube`, `cfx_isCube`, `cfx_buildBand`, the `CFX_NET_*` gap-skip macros),
audio helpers (`cfx_getAudioData`, `cfx_bands`, `cfx_drive`, `cfx_smoothSpec`,
`fx_lowBeat`), frame-timing helpers (`fx_dt`, `fx_step`, `fx_fade`), and `mq_scale`.
Motion helpers live in `cube_fx_imu.h`; the audio-analysis toolkit in
`cube_fx_audio.h`. If you find yourself copying a helper into a second effect, that's
the signal to promote it into `cube_fx_common.h` and delete the copies.

### The effect-slot ceiling

WLED effect IDs are a single byte, and 255 is reserved, so the **total** number of
effects on a device — built-ins plus every usermod combined — cannot exceed 255. With
~220 built-ins that leaves roughly 35 slots for everything else, and this set uses 34
of them. `addEffect()` returns 255 and **fails silently** when the list is full, so if
you add effects past the ceiling they simply won't appear. Trim or merge before adding
if you're near the limit. (Effects that share a file, like Cube Wire / Gyro Wire, each
still consume a slot.)

### Per-effect parameter memory — `cube_fx_param_memory.cpp`

A small usermod that watches the active segment and remembers the sliders you leave
each effect on, restoring them next time that effect is selected. It keys on a hash of
the effect **name**, so the memory follows an effect across rebuilds and renumbering
rather than attaching to a numeric ID that may have shifted.
