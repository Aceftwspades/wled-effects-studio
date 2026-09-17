# Native simulator — phase 1

The engine, headless. No window yet; that is phase 2.

This exists because the browser build could not do two things: reach the system
audio properly, and keep time. `getDisplayMedia` is the only route a page has to
the speakers — a picker, a permission prompt, and no control over buffering —
and `requestAnimationFrame` is throttled whenever the tab is not frontmost,
which silently invalidated measurements more than once.

## Build

```
python build.py                 # both targets
python build.py --native-only   # just cubefx.dll
python build.py --wasm-only     # just the browser build
```

Requires the **MSVC Build Tools** (for headers and import libraries) and the
clang that already ships inside **emsdk**. Nothing else to install.

Compiled with clang rather than MSVC deliberately. `CFX_NET_PREP` declares
`uint8_t _outCol[cols]` — a variable-length array, a GCC/clang extension MSVC
has never supported and rejects in every effect that renders. The choice was to
change firmware to suit a host compiler, or use a host compiler that takes the
firmware as written. The second is the only one compatible with the point of
this tool.

## Use

```
python -m native.cli --list
python -m native.cli --measure "spectral fountain" --ms 25000
python -m native.cli --measure soap --sweep c3=50,120,210
python -m native.cli --measure "black hole" --set sx=200,o1=1 --faceB 8
python -m native.cli --snapshot "spectral wormhole" --at 6000,14000 --scale 6 --out shot
python -m native.cli --live 10
```

`--measure` reports the same five figures the browser harness reports — mean,
sigma, dark %, bright %, saturation — over all lit pixels and over the lid
alone, plus **swing**: the standard deviation of each measure *across* the run.
Swing is how consistent an effect is over time, as opposed to how much structure
it has in any one frame; the two are independent and both matter.

`--live` prints band levels from the system output, to check the loopback path.

## Parity with the browser build

Both targets compile the same `sim_main.cpp` and the same effect sources, and
`native/synth.py` is a line-for-line port of the page's audio generator, so a
measurement taken here is directly comparable with one taken there. Verified:

| effect | metric | native | browser |
|---|---|---|---|
| Spectral Fountain, 12 s | mean / σ / dark / sat | 52.7 / 49.0 / 35.2 / 168.1 | 52.7 / 49.0 / 35.2 / 168.1 |
| Ace 3-D Soap, 25 s | mean / σ / dark / sat | 66.2 / 48.9 / 24.5 / 163.1 | 66.2 / 48.9 / 24.5 / 163.1 |

Identical to the last decimal, which also confirms the two builds agree on the
float paths (`sinf`/`cosf`/`sqrtf` differ between C libraries in principle).

**Re-run this after any change to the shim or the build.** It is the check that
lets the browser build eventually be retired, and it is only meaningful while
both still exist.

> **These two numbers are stale as of the palette work.** They were taken when
> the simulator ignored an effect's `pal=` default and pinned the palette to its
> own id 1; both sides now honour the metadata default against WLED's real
> palette set, so the same runs produce different — and more representative —
> figures. The comparison itself is untouched and still worth running. Re-taking
> it needs the browser harness driven in an actual browser, which is the only
> part of this that cannot be done from a script.

## Palettes

The simulator carries WLED's **real** palette set, not a stand-in. `palettes.cpp`
is lifted verbatim at build time (only its `#include` lines are rewritten), and
`Segment::loadPalette()` is transcribed from `FX_fcn.cpp`, so a palette ID means
the same thing here as on the device:

| IDs | what |
|---|---|
| 0 | the effect's own default, else Party |
| 1–5 | dynamic: random, and the segment-colour ones |
| 6–12 | the seven FastLED palettes |
| 13–71 | the 59 cpt-city gradients |
| 201–255 | usermod-registered, counting **down** from 255 |

Because the IDs now agree, an effect's `pal=` metadata default is honoured like
every other default. **This used to be the biggest gotcha in the tool**: with only
six hand-copied gradients here, a metadata default of `pal=11` was Rainbow on the
device and landed on Mono in the simulator, so effects were previewed in
greyscale at a reported saturation of zero and the page had to override it.

Usermods run as well — `setup()` before the first frame, `loop()` before each
one — so `cube_fx_palettes.cpp`'s four audio-reactive palettes register and
repaint here as they do on hardware. They show up as `CubeFX: Kick` and friends.

One deliberate divergence, in `simLoadPalette()`: the firmware reads the gradient
table with `pgm_read_dword`, which is correct where a pointer is 32 bits and
truncates one on a 64-bit host. `PROGMEM` is a no-op here, so the entry is read
as an ordinary pointer.


## Recording a GIF

**Record 15 s GIF** (the toolbar's red dot, or File) captures the next fifteen seconds and
writes them beside the frame captures, named after the effect:

```
%TEMP%\cubefx\Ace_3_D_Maelstrom_1788732215.gif
```

Frames come from the LIVE run, not a re-simulation. What you get is what was on
the screen - live audio if it is on, and any slider you moved while it ran. A
re-simulation would quietly hand you the synthetic generator and the metadata
defaults instead, which is not what you were looking at when you decided the
clip was worth keeping.

It records whatever is being SHOWN, so `Q`, `E` and `W` frame the clip: net
only, cube only, or both side by side. Encoding runs on a worker thread, so the
window keeps drawing through it; the line beside the button counts down and
then names the file.

For a repeatable clip of a known effect at known settings, use the headless
`--gif` above instead - that one IS a re-simulation, which is the point.

## Frame capture

The running app will write a PNG of its own window on request. Create the
trigger file and it answers on its next tick:

```
%TEMP%\cubefx\capture.request   ->   %TEMP%\cubefx\capture.png
```

Any empty file will do; the app deletes the request and writes the PNG. This
exists so the window can be looked at without a screen grab.

It uses `dpg.output_frame_buffer`, which returns the frame Dear PyGui just
rendered — the viewport and nothing else. No other window, no desktop, no
wallpaper, and nothing at all when the app is not running. That scoping is the
point of doing it this way rather than through a Windows screen or window grab,
which photographs whatever happens to be in front of it: asked once to check
this app's theme, a window grab returned a locked machine's lock screen. A frame
buffer cannot make that mistake, because the app has nothing else to give.

## View modes

| key | does |
|---|---|
| `Q` | unfolded net fills the frame |
| `E` | cube fills the frame |
| `W` | both, side by side |
| `H` | show/hide the control column |
| `F11` | fullscreen the window itself |
| `space` | play/pause |

`Q`, `E` and `W` go straight to a full-frame picture: the view centred on
black, no control column, no captions, no borders, no padding. They are not
layout choices with a separate "now hide the chrome" step — the view is what you
wanted to look at, so it is all that is on screen. Pair with `F11` for a
visualiser that owns the display.

`H` brings the controls back without leaving the layout, for adjusting a slider
while watching, and takes them away again.

The cube render is **capped at 620 px** whatever the pane size, and the image is
scaled up to fill. The renderer is quadratic and is already the most expensive
thing the app does: 28 ms a frame at 620, 64 ms at 900. Rendering a fullscreen
cube at its true size would take the app from 35 fps to 15, so fullscreen makes
the picture bigger rather than sharper. The net has no such cap — it is scaled
by a whole number so the LED grid stays hard, and it costs 16 ms a frame at
1296 px, which is affordable.
