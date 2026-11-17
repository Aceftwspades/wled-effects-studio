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

- **65 effects** — cube-native 3-D pieces, flat 2-D analysers, a game, motion toys
  and a utility, plus **Studio Script**, which runs effects sent from the WLED Effects
  Studio without a firmware build. More than a device has room for: the **effect
  bank** chooses which of them get a slot (below). Full catalogue below.
- **A cube geometry layer** — every pixel gets a real position on the cube surface,
  so effects are continuous across the folds with no seam handling in the effect
  code. On a non-cube matrix the same effects fall back to a flat plane.
- **Optional accessories**, each compiled out by a build flag when you leave it off:
  - a **microphone** (the `audioreactive` usermod) for sound reactivity,
  - an **MPU6050 IMU** for tilt, shake, and orientation,
  - up to four **rotary encoders** + an **OLED** for on-device control.
- **Six audio-reactive palettes** (Kick, Tilt, Bloom, Ladder, Arc, Sweep) that work
  under any effect, this folder's or WLED's own.
- **Any shape**, not only the cube: the studio can send each pixel's real position
  (`/geometry.bin`), and every effect then draws on that shape.
- **Per-effect parameter memory** — the sliders and checkboxes you leave an effect
  on are remembered and restored next time you select it, keyed by effect name so
  it survives rebuilds.

---

## Hardware

### Controller

| Board | Environment | Notes |
|-------|-------------|-------|
| ESP32 (classic) | `esp32dev_customfx` | 1.5 MB app partition, which the full set no longer fits (about 1.64 MB): leave features out (`-D CFX_WITH_UI=0` and the like, below) or use a larger-app partition table. |
| ESP32-S3 (e.g. N16R8) | `esp32s3_customfx` | 3 MB app partition, PSRAM lifts the segment-data cap, hardware-accelerated FFT. Digital I2S mic required — the S3 has no analog-mic path. |

Both environments are defined in `platformio_override.ini`, which is not part of the
repository (it is in `.gitignore`): create it in the repository's root with the block
under *Building and flashing*. Audio needs an I2S microphone on the S3; the classic
ESP32 also accepts an analog mic.

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
`cfx_pos()` lights the bottom as the sixth face, and so do the few that ride the walls
as a band or walk cells across folds (Tron, Matrix Rain, Breakout, DNA Helix, Whirlpool,
Cube Fire, Split GEQ); the bottom's orientation is `X = a, Y = -b, Z = -1`: looked at
from below, north is up. In the studio's ledmap tool, which writes the ledmap for a
cube's wiring, the bottom face's letter is `B`: its `faces` order becomes
`N,W,T,E,S,B`.

The **WLED Effects Studio** ([Aceftwspades/wled-effects-studio](https://github.com/Aceftwspades/wled-effects-studio))
is the desktop companion to this folder: it previews these effects on a simulated cube,
writes the cube's ledmap, builds effects from node graphs and sends them to Studio
Script, and flashes this firmware. Nothing here needs it.

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

**Cube Axes — the calibration tool.** *Ace 3-D Cube Axes* is not a show effect; it paints each pixel's position directly: **+X → red (east), +Y → green
(north), +Z → blue (up)**. That turns three otherwise-invisible things into something
you can just look at, and it is worth running first on any new build.

- **Is the segment a cube at all?** On a real cube net the four corner blocks go
  **dark** (the gaps) and the colour flows smoothly over every edge. On a flat panel
  (e.g. a segment set to the face size 8×8 instead of the net 24×24) there are no dark
  corners, just a gradient — the effect is silently running its flat fallback and not
  driving the five faces.
- **Is a face rotated or mirrored?** A **hard colour break at a seam** means that face
  is flipped relative to what the geometry assumes. Note which seam; the six face
  lines in `cfx_pos()` (in `cube_fx_common.h`) are the only place that needs changing.
  (A shape the studio sent as `/geometry.bin` overrides them for a segment of its
  size: remove that file to go back to the net.)
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

The fix is per-effect: tick **Flat mode**, the **last checkbox** in a cube effect's
settings. It forces flat rendering regardless of the segment's shape. Three
exceptions: the seven 2-D analysers have no Flat mode (they are flat already);
Quadrant Labyrinth's third checkbox is **Unify net**, and it has no Flat mode; and on
Studio Script the third checkbox, **Check 3**, is a program's own control and also
forces flat.

Panels whose side is *not* a multiple of 3 — 16×16, 32×32, 8×32, and most strips —
are never misdetected, so Flat mode is only relevant on those specific square sizes.

### Optional accessories

| Accessory | In Settings → Usermods | Left out by | Adds | Effects that use it |
|-----------|------------------------|-------------|------|---------------------|
| Microphone | `audioreactive`'s own page | not listing `audioreactive` in `custom_usermods` | real sound reactivity | most effects (they animate without it, but only *react* with it) |
| MPU6050 IMU | **AceIMU** (`ace_imu_mpu6050.cpp`) | `-D CFX_WITH_IMU=0` | tilt, shake, orientation | the Gyro effects (below), Sauron's Gyro |
| Rotary encoders, up to 4 | **AceUI-Enc** (`ace_ui_encoder.cpp`) | `-D CFX_WITH_UI=0` | on-cube menu control; play Breakout | Breakout needs one to play |
| OLED 128×64 / 128×32 | **AceUI-Screen** (`ace_ui_screen.cpp`) | `-D CFX_WITH_UI=0` | the on-cube menu display | — |

The three Ace parts are files of this one usermod (`cube_fx`), not usermods of their
own in `custom_usermods`. None are required. Effects run on a bare cube; the
accessories add reactivity and local control.

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
| Liquid | mic | A sloshing liquid level that settles back to the cube's own horizontal and splashes on the beat. |
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
| Spectral Fountain | mic | Soap's film with sixteen nozzles, one per FFT band, firing jets of colour whose wakes sweep the walls. |
| Spectral Bloom | mic | Soap's curls carrying the spectrum's colour over black, dropped where the hit lands. |
| Sauron | mic (IMU optional) | The cube as the Eye: a gaze that wanders the directions the cube points in. Its **Gyro** checkbox steers it by the IMU. |
| Maelstrom | mic | A logarithmic spiral falling into itself for ever. |
| Mandelbrot | mic | An endless zoom into the Mandelbrot set, laid on the solid by stereographic projection. |
| Lichtenberg | mic | A branching discharge from a beat's seed, walking to the far side of the cube. |
| Feigenbaum | mic | An endless zoom into the period-doubling fig tree. |
| Watershed | mic | Drainage: threads gathering into trunks and running to a sink, the mirror of Lichtenberg. |
| Fracture | mic | The shell cracks into closed cells, then heals. |
| Poincare | mic | A hyperbolic tiling flowing for ever over the five faces, with no seam. |
| Kaleidoscope (3-D) | mic | A spherical mirror group folding a pattern over the solid. Not the 2-D Kaleidoscope below. |
| Voronoi | mic | Nearest-seed cells on the sphere, breathing on the beat. |
| Truchet | mic | A curve network of random tiles that rewires itself on the beat. |
| Moire (3-D) | mic | Two dot lattices warped through each other. Not the 2-D Moire Rosette below. |
| Torus Knot | mic | A (p,q) knot seen from inside it, the cube as a panoramic viewport. |
| Liquid Tunnel | mic | Reaction-diffusion tendrils growing down a log-polar shaft. |
| Voxel Vortex | mic | A ring of cuboids tumbled through the space round the cube. |
| Helix Tunnel | mic | A helical vortex that turns into a tunnel of arcs. |
| Candy Knot | mic | Torus Knot's fat, banded sibling. |
| Pleats | mic | A pleated surface bent by the music, lit from one side. |
| Warp | mic | MilkDrop's feedback warp: each frame the last one re-sampled through a moving field, with a waveform drawn in. Best with this fork's audioreactive PCM (below). |
| Scope | mic | MilkDrop's seven waveform shapes as bright oscilloscope figures on black. Best with the PCM too. |
| Paintball | mic | Paint balls splatting onto the solid from every side. |
| Murmuration | mic | A flock of starlings round the cube, scattered by a hawk on the kick. |
| Jelly Bounce | mic | Glowing jellies in a glass box, split by the kick. |

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

### Utilities

| Effect | Needs | What it is |
|--------|-------|-----------|
| Life Counter | — | A Magic: The Gathering life tracker, not a light show: the four walls carry the four players' life totals, which are the first four sliders (Player 1 to 4), and the lid a mana symbol (Mana). |
| Studio Script | — | Runs an effect the studio sends, with no firmware build: see *Studio Script*, below. |

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

WLED's audioreactive usermod. Add it to `custom_usermods` (the environments below
do). This fork's copy (`usermods/audioreactive`) adds a slot with the raw sound
(`CFX_PCM`) and the pitch classes, which Warp and Scope draw their waveform from;
the stock usermod works too, and they then rebuild a waveform from the FFT bins.
Every audio effect reads through it; when it's absent the
effects fall back to WLED's simulated-sound generator, so they animate but do not
respond to real sound. On the ESP32-S3 the mic must be **digital I2S** — there is no
analog-mic path on that chip, and an analog mic fails silently (the effects look
alive on simulated audio while hearing nothing).

### Motion — `ace_imu_mpu6050`

An MPU6050 on I2C gives the Gyro effects tilt, shake, and orientation. Defaults are
SDA **21** / SCL **13** (or −1 to follow LED Preferences). While LED Preferences has
global I2C pins set, the driver keeps to those and refuses its own unless **force** is
ticked; "set I2C pins first" on the Info page means neither is set. Settings cover the sensor
ranges (±4 g / ±500 °/s suit a handled cube), the axis mapping (which sensor axis
points cube east/north/up), and a gravity-fusion time constant.

**Set the axis mapping against Cube Axes, not against the datasheet.** The three
`axisX/Y/Z` settings tell the driver which sensor axis points cube east, north, and
up — and the *cube* directions they refer to are the ones you confirmed visually with
the Cube Axes effect (holding the cube SOUTH-toward-you; see above). Get those two to
agree and the Gyro effects behave: tilt the cube and Gyro Sand pours the right way,
Gyro Rain still falls down. If a Gyro effect reacts to the wrong axis — sand runs
uphill, "up" is sideways — an `axisX/Y/Z` entry is swapped or inverted, not the sensor.

One-tap calibration actions live in the on-cube **System** menu and in the
**action** dropdown on the AceIMU settings page: **Calibrate gyro** (sit the cube
still, top up) writes the gyro bias, **Level now** writes a level reference for a
board that's glued in slightly askew, and **Clear level trim** takes it away again
(the settings page also has **Re-initialise sensor**). Without the sensor the Gyro effects still run — gravity just reads as
straight down the cube's own Z.

### On-cube control — `ace_ui_encoder` + `ace_ui_screen`

Up to four rotary encoders (`-D ACE_UI_MAX_ENC=n` for another limit) and a small OLED
give a full menu on the cube: browse and
apply effects, edit parameters, palettes and presets, brightness, per-segment
mirror/reverse, and power — no phone needed.

- **Encoders** attach on direct GPIO or an MCP23017 expander. Each knob has a *turn*
  role (navigate, brightness, edit, or pinned to one parameter) and a *button* role
  (full click/back/home, or a dedicated back button). A press-and-hold grammar gives
  back / home / lock without a second click, and holding two buttons for 3 s reboots
  (`rebootMs`; 0 turns it off; with one knob, use System → Reboot). Encoder A/B need
  pull-ups — on the module or the internal ones. The pins start unset (−1). If the
  Info page says **pin already in use**, another part of WLED has claimed one of the
  knob's pins; **switch pin already in use** means the knob turns but its button was
  left alone.
- **Screen** drives SSD1306, SH1106, or SSD1309 panels at 128×64 (and the SSD1306 at
  128×32) over its **own I2C bus (Wire1)** by default, **shared I2C** with the IMU,
  **hardware SPI**, or **its own SPI pins** (software SPI). On SPI, the panel owns CS/DC/RST here but SCLK/MOSI come from WLED's global
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

Create `platformio_override.ini` in the repository's root (it is not tracked; WLED's
`platformio_override.sample.ini` shows the format) with the environments:

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

Build the classic ESP32 (with the full set it no longer fits the 1.5 MB app
partition: add `build_flags = ${env:esp32dev.build_flags} -D CFX_WITH_UI=0` or the
like to it, or give it a larger app partition):

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

After flashing, in WLED set up your matrix as one square segment with the cube's
ledmap (the studio's ledmap tool writes it for your wiring), choose the effects in
**CubeFXBank** (below), enable the accessories you want in Settings → Usermods, and
set their pins there.

---

## Choosing the effects — the bank

A device holds at most 254 effects, and WLED's own take 216 of them, so a usermod has
about 39 slots - fewer than the 65 compiled here. Past the limit WLED drops an effect
without a word, and which ones it drops depends on the link order, so it can change
from build to build.

The **CubeFXBank** settings page (Settings → Usermods) fixes that. It has 36 slots
(`CFX_BANK_SLOTS`), each a dropdown of every compiled effect: the ones you put in the
slots are the ones the device registers, in slot order - the order of the WLED list
and the on-cube menu. **Assign all** fills the empty slots, **Clear all** empties
them; an effect already in a slot is greyed out in the others. Changes take effect
**on reboot**.

With **enabled** unticked, or every slot empty (a fresh flash), the bank chooses
nothing and every effect registers in link order until WLED's list is full, as
before the bank existed - so on a fresh flash some 26 effects are missing until you
choose. The Info page's **Cube FX slots** line says how many were placed and asks for
a reboot when the slots have changed since; **Cube FX roster** appears when an
effect was left off the roster (more than `CFX_BANK_MAX_FX`, 72, compiled) or two
names hash alike; **Cube FX slots free** counts what is left. The same page carries
**six_faces** (above).

---

## Studio Script

One slot for any number of effects made in the studio: it sends a program
(`/studio.bin`, a few KB of bytecode for the script VM - version `CFX_SCRIPT_VM`,
2) and this effect runs it, picking up a new one within a couple of seconds, with no
firmware build. Its sliders and checkboxes are generic - Speed, Intensity, Custom 1
to 3, Check 1 to 3 - and mean whatever the program says. Check 3 also forces flat
rendering (see Flat mode above).

A program too heavy for the chip draws at half, then a quarter, of the width after
three frames in a row over 40 ms, and goes back to full when a frame would come in
under 15 ms; the Info page's **Studio Script** line shows the resolution and the
frame time. One frame never runs past `SS_FRAME_BUDGET_US` (100 ms): it stops where
it is and the next frame carries on from that pixel, so a heavy program cannot
outlast the task watchdog.

## Audio palettes

Six palettes in WLED's palette list - **Kick**, **Tilt**, **Bloom**, **Ladder**,
**Arc**, **Sweep** - move with the sound, sampling the
**source** palette chosen on the **CubeFX** settings page. They work under any
effect.

## Any shape — `/geometry.bin`

The studio can send a shape's real pixel positions - a sphere, strands round a tree,
a model - as `/geometry.bin`. When it matches a segment's size, `cfx_pos()` reads the
positions from it instead of working them out from the cube net, so every effect here
draws on the real shape. The file is checked for changes every two seconds.

---

## Notes for developers

### One file per effect

Each effect is a self-contained `cube_fx_NN_name.cpp`: its `mode_*()` function, its
`_data_FX_MODE_*` metadata string, any tables it alone uses, and one line that files
it with the bank:

```cpp
static CfxBankReg cube_fx_plasma_reg(&mode_plasma, _data_FX_MODE_PLASMA);
```

WLED compiles every `.cpp` in the folder, so **adding an effect touches no other
file** — drop in a new `cube_fx_NN_name.cpp`, rebuild, and give it a bank slot (or
leave the bank unconfigured). The roster holds `CFX_BANK_MAX_FX` (72) effects.

The `NN` prefix is just a sort order: there are two `00` files (Cube Axes and the
geometry table) and Studio Script is `98`. It carries no meaning beyond filing order;
effects are identified everywhere that matters by **name**, not number, so
renumbering never invalidates saved settings.

The `cube_fx.cpp` file is the exception: it holds the seven flat 2-D analysers
together, for historical reasons, and registers them the same way.

### Shared code — `cube_fx_common.h`

Anything used by two or more effects lives here: the cube geometry (`cfx_pos`,
`cfx_buildCube`, `cfx_isCube`, `cfx_buildBand`, the `CFX_NET_*` gap-skip macros),
audio helpers (`cfx_getAudioData`, `cfx_bands`, `cfx_drive`, `cfx_smoothSpec`,
`fx_lowBeat`), frame-timing helpers (`fx_dt`, `fx_step`, `fx_fade` - rates written per
23 ms frame, about 43 fps, scaled to the frame's real length), and `mq_scale`.
Motion helpers live in `cube_fx_imu.h`; the audio-analysis toolkit in
`cube_fx_audio.h`; the helpers the studio's generated effects share in
`cube_fx_studio_helpers.h`; the hand-off that lets a settings save reach a usermod's `loop()` on its own task in
`cube_fx_handoff.h`. If you find yourself copying a helper into a second effect, that's
the signal to promote it into `cube_fx_common.h` and delete the copies.

### The effect-slot ceiling

WLED effect IDs are a single byte, and 255 is reserved, so the **total** number of
effects on a device — built-ins plus every usermod combined — cannot exceed 254. With
216 built-ins in 220 pre-allocated entries (`MODE_COUNT`) a usermod gets the four
gaps plus 35 above: 39 slots. `addEffect()` returns 255 and **fails silently** when
the list is full; the bank (above) is what decides which effects claim the slots.
(Effects that share a file, like Cube Wire / Gyro Wire, each still take one.)

### Per-effect parameter memory — `cube_fx_param_memory.cpp`

A small usermod that watches the main segment and remembers the sliders and the
three checkboxes you leave each effect on (in `/cfx_pmem.bin`), restoring them next
time that effect is selected. It keys on a hash of
the effect **name**, so the memory follows an effect across rebuilds and renumbering
rather than attaching to a numeric ID that may have shifted.

---

Much of this folder's newer code was written with AI assistance (Claude); those
sections are marked `// AI: below section was generated by an AI` in the source.
