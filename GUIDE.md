# WLED Effects Studio — a short guide

Effects for a WLED LED cube (or any matrix or strip), built as node graphs
or as C++, previewed on a simulated cube with synthetic or live audio, and
sent to the device three ways. STUDIO.md is the long history and roadmap;
NODES.md lists every node; TUTORIAL.md builds a first effect node by node.

## First run

**The packaged app** (a release zip, or `python package.py` from the
tree): unzip anywhere and run `WLED Effects Studio.exe`. It is portable -
projects, builds and captures land in its folder (or in `%LOCALAPPDATA%\WLED
Effects Studio` when the folder cannot be written to). The engine comes
prebuilt, and the release ships a compiler (a cut-down MinGW-w64 GCC in
`toolchain\`), so everything works at once, building your own effects
included - a new effect builds in seconds. Only flashing firmware needs
more: a WLED checkout (set `WLED_ROOT`) and PlatformIO. `WLED Effects Studio (console).exe` is
the same app with a console, for when something goes wrong.

**From the tree**:

```bash
cd studio
pip install -r requirements.txt                        # dearpygui, numpy, pillow; the audio packages
python -m native.doctor                                # what is here and what is missing
python build.py --native-only                          # once; the app rebuilds the engine as it needs
python -m native.app                                   # or the desktop shortcut
```

The window: a menu bar and a toolbar of icons; the two views (the
**logical net** the effect draws, and the **3-D cube**); a side panel with
the project, the effect, its sliders, the segments, the geometry, colours
and audio. **G** opens the graph pane, **C** the code pane; **Q / E / W**
show one view or both full-frame (press again to come back); **H** hides
every control; **space** pauses. Every key is on the menus and under
Settings > Keyboard shortcuts, where any can be changed. Every control
explains itself on hover; a dim **(?)** at the end of a row holds what
the row as a whole is for. The toolbar's
right half is the device and the frames: devices (Ctrl+Shift+N), flash
(Ctrl+Shift+U), send to device (Ctrl+Shift+S), the DDP stream on or off
(Ctrl+Shift+T, lit amber while it runs); then the shape editor
(Ctrl+Shift+E), the sequence (Ctrl+Shift+Q), the library (Ctrl+Shift+L),
the palettes (Ctrl+Shift+G) and the LED outputs (Ctrl+Shift+O). Playback
> Randomise is Ctrl+Shift+X.

A node's long settings (bitmap rows, expressions, files) are edited in
the Properties pane, which sits under the 3-D view in the graph layout (N
hides it); while the add menu is open, the node under the pointer is
described there - what it does, every pin and setting - before you add it. The panes go where you want them: drag one by the `:::` at its top right
onto another - near an edge it snaps beside or above that pane, in the
middle the two swap - or pick a preset under View > Layout; the splitters
between panes resize them. A view can leave for a second monitor: View >
Pop out (or right-click the view) opens it in a window of its own, which
orbits and zooms on its own and remembers where it was; close it and the
pane comes back. The side panel's sections fold on their arrow or title
and move by their own `:::` (drop one on another section to put it above
or below); right-click a section header to expand, collapse or restore
them all.

## Making an effect

**As a graph.** Ctrl+N, name it, and the graph pane opens with a starter.
Right-click the grid to add a node (type to search); drag from a pin to a
pin to wire, or to empty space for a list of what could go there. Every
node and pin explains itself in the box above the graph when hovered, and
while the effect is on the cube the box shows the pin's live value. The
bolt on the toolbar (**L**) rebuilds as you edit; F5 rebuilds on demand.
Sub-graphs (select nodes, Ctrl+G) fold a cluster into one node you can
reuse. File > History keeps a copy at every save. The editor has the
Blender habits: A selects all, Ctrl+[ / Ctrl+] grow the selection up or
down the wires, Shift+Home frames it, Ctrl+Delete deletes a node and
joins the wires across it, a node dropped on a wire is spliced in, a
Ctrl+right-drag cuts wires, Alt while editing a value edits every
selected node of that type, Backspace over a value resets it, Ctrl+P is
the command palette and Ctrl+Alt+Z the undo history. Zoomed out past
50% (Settings > Simplified nodes below) the nodes become small stand-ins
- a title and its wires - for getting about a big graph. Settings > Keyboard
shortcuts lists the rest.

**As code.** Ctrl+N in the code pane makes a `.cpp` from the effect
skeleton; the editor colours it, errors from a build go to their lines,
and the API reference under it lists what the firmware offers. A graph can
also be handed to the code pane (File > Open graph as code) when the nodes
cannot reach something.

**Draft vs. list.** A new effect is a draft: built and shown only while
you edit it. File > "Add to the effects list" (Ctrl+I) makes it part of the
project: always built, exported, shipped.

## Seeing it properly

The geometry section sets the cube's face size and whether it has six
faces (a lit bottom; it takes the net's bottom-right corner block, and
the flash build and the settings push tell the device) - or a matrix,
cylinder, sphere, strip, or an XYZ file - and for the cube its wiring - which face
first, turns, serpentine - which is what the exported ledmap says. Audio
comes from the synth (sliders, a beat clock), a live capture, or a WAV
file. Playback has A/B compare (two effects side by side), a slider sweep,
and scrubbing back through the last seconds while paused. Segments (+ in
the panel) layer several effects with WLED's blend modes and opacity, and
carry WLED's segment options - reverse, mirror (and Y, and swap XY on a
matrix), group, space, offset - which the sim lays out the way the device
does and every send and preset carries.

**The 3-D view** turns by dragging and zooms by the wheel; View > Camera
has presets (isometric, front, back, left, right, top, below), three
saved views, and a **background picture** - the room, the house - dimmed
behind the LEDs, for the point cloud and the GPU cube alike.

## Any shape: the shape editor

GEOMETRY > shape (or View > Shape editor...) opens the **Shape** frame - a
window like the Device ones, docks the same way. A shape is a list of
**parts** in wiring order: strips, rings, panels, cylinders, spheres, cubes,
polygons (sides of so many LEDs each), polyhedra (the edges of a solid -
tetrahedron to icosahedron, and the **soccer ball**, a truncated
icosahedron - or every face outlined on its own), a strip run along a
path (polyline), and loose points. Each part has its own settings - the
LED count is always among them: LEDs, LEDs a side, LEDs an edge, wide x
high; a path takes a count and sets its pitch - then:

- **PLACE**: position, rotation and scale as drag-numbers - drag one and
  the part moves in the 3-D view as you drag (the sim takes the new
  shape when you let go; ctrl-click to type a value). "reverse" turns its
  wiring round; mirror and array make copies; up/down reorder parts,
  which reorders the wiring.
- **AIM**: a direction (x y z, or azimuth and elevation, or one of the
  six axis buttons), a distance and a spin. **aim outward** turns the
  part so its axis - a strip's length, a panel's face, a flat part's
  normal - runs along the direction and puts it that far from the
  origin along it; **turn only** keeps its place; **aim at the origin**
  points it inward from where it is. The yellow arrow in the 3-D view is
  the selected part's axis. This is how a ball is built by hand: a
  pentagon aimed outward at radius 9, then a hexagon beside it at
  another direction, and so on - or start from a polyhedron in "faces"
  mode and **split into parts**, which gives every face its own polygon
  (every edge its own strip in "edges" mode) with the LEDs exactly where
  they were, each then moved, turned and re-counted alone.

Units are LED pitches - a strip with pitch 1 has its LEDs one unit apart
- so a mesh's own units are the pitch when it is imported.

- **Import...** reads a whole xLights layout (`xlights_rgbeffects.xml`:
  every model a part, placed by its world position and rotation, sized by
  its scale - custom models, matrices, lines and poly lines exactly,
  circles, spheres, cubes, window frames, arches, trees and stars near
  enough and named in the status; anything else as a strip of its LEDs),
  or `.obj`, `.ply` and `.stl` from
  Blender or any CAD program - LEDs **along the edges** at a pitch (a
  strip run round the outline, chained into as few runs as it can), or
  one **per vertex**, or **over the surface** - an xLights **`.xmodel`**
  custom model (the LEDs, their numbering, and its grid), or an `x y z
  [index]` point list (CSV, whitespace or JSON; the index column is the
  wiring order).
- **Reference...** puts a mesh in the 3-D view as a wireframe
  that is not LEDs - the tree, the house, the enclosure - moved, turned
  and scaled like any part, to place the LEDs against.
- **Place** LEDs by hand: tick "place", click the 3-D view and an LED lands
  on the working plane (z = 0 by default; choose x, y or z and a value);
  they go into the selected points part, or a new one. Drag an LED to move
  it; "renumber: nearest chain" rewires a points part the way a strip
  would most likely be run through them; "turn into a path" makes a
  polyline of the points and fills it with LEDs at the pitch.
- **Export .xmodel** writes the shape (any geometry, on its grid) as an
  xLights custom model, the wiring as the node numbers.
- **Generate a preview** (the frame's PREVIEW fold, or View > Generate a
  preview of the shape) renders a turn of the shape off screen - lit by
  the effect the sim runs, or each part in a colour of its own, or a chase
  along the wiring - loops it in the frame and writes `shape_preview.gif`
  and `.png` into the project's export folder, for a README or a forum
  post.
- The selected part's LEDs are ringed in the 3-D view with its wiring
  drawn through them; Undo steps back; Save/Open keep a shape as a file
  (`.shape.json`) to reuse across projects.

**Parts in a graph**: the **Shape part** node says which part a pixel is
in, where along it (0..1), how many parts there are, and gives a mask for
a chosen part - one graph, the parts treated differently. **One segment
per part** in the frame gives every part its own WLED segment instead,
each with its own effect, palette and sliders (the strip layout; up to
eight).

**Layout**: a shape is one logical strip in wiring order (what 1-D effects
and the 3-D nodes work on), or, as "grid", a w x h matrix the LEDs are
projected onto from the front - or the grid an xLights model came with.
On a grid, two LEDs in one cell are reported: the cell keeps the first.

**On the device**: the shape's positions go along with it. Device > Send
the shape uploads the ledmap (the wiring) and `/geometry.bin`, a table of
every LED's position and outward direction, which the cube effects read
instead of their cube-net rule - so Position, Direction, Cube face and
every effect that asks where a pixel is see the real shape, on the device
exactly as in the sim. Cylinders, spheres and tori send the table too; a
cube net and a flat matrix have a rule of their own and send none.

**Palettes of your own** (Edit > Palettes...): a gradient drawn by hand -
click the bar to add a stop, drag it, right-click to remove it, a colour
and a position each, up to 18 - kept with the project, in the sim as a
palette of its own (ids 200 down, in the palette combo like any other,
blended the way the device blends) and sent to the device as its custom
palettes (`/palette{n}.json`, the same ids there - by position, so the
first here replaces whatever the device had as palette 0). "From the
sim's palette" starts from whatever the sim shows.

**The library** (File > Library...) shows every graph of the project as a
looping thumbnail with its tags (what nodes it uses, audio, 3-D, script);
type to search; click a tile to run its effect in the sim (built first if
it never was) - the layout stays as it is, and its graph is waiting in
the graph pane (G).
**Generate previews** renders a turn of the 3-D view for every effect (or
only the tiles shown) on the project's shape, each with the graph's own
settings - a GIF and a PNG per effect in `export/library/` with a
README index, for a catalogue or a forum post - and the tiles then show
those turns.

**Curves by hand**: select a Float curve node and the Properties pane
shows its curve large - click to add a point, drag one, right-click to
remove it; the node's small preview and its numbers follow, and the
curve runs as a script as well as compiled.

## A show: the Sequence frame

Playback > Sequence... (or Device > Sequence). A **step** is what the sim
shows when you add it - every segment's effect, sliders, palette, bounds,
opacity and blend, the colours, the brightness - with a name, how many
seconds it holds and a transition time. "Update from the sim"
recaptures it, "Load into the sim" puts it back to tweak; up /
down reorder. The **timeline** under the list shows the steps as blocks
along the time: click one to select it, drag the line between two to
retime the one on the left; the faint lines are the bpm's bars, the
ticks the beats found in the WAV, the wave the WAV itself (Play restarts
the WAV with the sequence). **RAMP** moves one slider of the first
segment over the step, from the step's value to the end value - in the
sim as it plays; on the device as sub-steps in the playlist (a second
apiece, up to twelve), since a preset cannot move a slider. **Play in
the sim** runs the steps in turn, each change
blended over its transition time in the style chosen (fade, swipes,
pushes, outside-in, inside-out, circular, fairy dust - WLED's own; on the
device the style is its blend-style setting). **Send presets + playlist**
saves each step as a WLED preset (ids from "presets from", existing
ones overwritten) and the sequence as a playlist preset with the
durations and transitions - about a second a preset, since the device
writes each one from its main loop and the next is only sent once it
has; "Send and run it" starts it; "Save presets.json" writes the same
for a device that is not on the network.
Effects and palettes are matched by name against the device's own lists,
and a step whose effect the device does not have is left out and named.
**BEATS**: a bpm typed, tapped (Tap, on the beat), taken from the synth,
or found in the WAV playing as live audio (WAV's: the tempo and the
beats themselves, from the loudness rising - rough the way tapping is),
and "Snap durations to bars" rounds every step to whole bars of it, so
the sequence changes on the music. **Render GIF** and **Render video**
play the sequence once and record it into `captures/` - a GIF, or an
mp4 (which needs ffmpeg on the path). The toolbar's record button and
File > Record 15 s GIF / video do the same for whatever the sim shows.
**SCHEDULE** under it is the device's timers: "+ run the playlist at"
and "+ off at" add a row - a time of day, or sunrise / sunset with an
offset in minutes, a preset, the days - "Send the schedule" writes them
to the device (and saves an "Off" preset, id 250, for the
off rows); "Read the device's" shows what it has.

## Getting it onto the cube

Everything about the device is under the **Device** menu, in three frames.
Each opens as a window over the panes. At its top right: **dock** slots
it into the pane space under the main pane (drag the ::: grip onto any
pane to put it beside or above that one, like the panes themselves) and,
once docked, **float** takes it out again; **x** closes it (so does Esc
while a floating frame has the focus), and the menu opens it again. The
arrangement is remembered. While you type in any frame's box the hotkeys
stay quiet.

- **Devices** finds WLED on the network - "Scan the network" asks by mDNS,
  asks every known device for the nodes it has heard, and sweeps the
  subnet - or takes an address typed in. Each row says what the device is
  (chip, WLED version, how many effects, whether it has the Studio Script
  effect); the tick marks the **active device**, where every send and the
  flash go (also Device > Active device). The list is the app's; the
  active choice is the project's.
- **Send to device** shows the active device and what it runs now (the
  effect, its fps, the Script effect's frame budget), and has the sends:
  1. **Send the graph as a script** (Ctrl+Shift+D). No firmware build: the
     graph is compiled to bytecode and sent to the Studio Script effect on
     the device, which runs it within two seconds. Playback > "Run the
     graph as a script" previews exactly that in the sim first. Not every
     node is scriptable - the studio names the one that is not.
  2. **Send the effect's settings** pushes the effect, sliders,
     palette, colours and the segment's blend mode.
  3. **Send the shape** uploads the ledmap (the wiring) and, for a shape,
     its positions table; **Send the ledmap only** just the wiring. Both
     ask first: a wiring that is not the device's leaves it dark or
     scrambled. **Import the device's ledmap** reads it back as the geometry.
- **LIVE**, in the same frame: **stream the sim to the device** sends
  every frame the sim draws to the device over DDP (WLED's realtime
  input, on by default) - any effect, built or not, on the real LEDs at
  once, in the wiring order the ledmap would use; the device goes back to
  its own effect a couple of seconds after the stream stops. The
  **wiring test** under it runs a chase along the wiring order (LEDs/s),
  lights one LED by its index (< > step it), one part of a shape (or the
  parts in turn), one LED output (the outputs frame's ranges), all red /
  green / blue / white for the colour order, every other LED, or a
  twinkle - in the sim and on the device when streaming - the way to
  check a new ledmap, shape or wiring before trusting it; play resumes
  the effect.
- **LED outputs and power** (Device menu): the wiring split into the
  device's outputs - one, one per part of a shape, or every N LEDs - each
  a pin, a start, a count, an LED type, a colour order and reversed or
  not; "Read the device's" shows what it has now; **Send outputs + power
  limit** writes them as its LED config over /json/cfg. POWER shows what
  the frame on screen draws at the LED's full-white current (55 mA by
  default) against the supply you enter, and how far WLED's auto
  brightness limiter would dim it; "preview the limiter" dims the sim
  the same way, and the footer shows the amps all the time.
- **Flash firmware** (Ctrl+Shift+U). WHAT GOES ON THE DEVICE says, before
  anything is built, exactly what the firmware will carry - the tree's
  WLED version and build id, the environment chain with its board and
  partition table, the usermods, the features in and out with their flags,
  the studio effects shipped (and the listed ones that are not), the
  built-in cube effects - and, when a device is active, what it runs now,
  the last flash recorded to it from this project, and which effects this
  flash would add or drop. A board that is not the device's chip is
  called out in red. "Preview (no compile)" stages the usermod and writes
  the environment block and shows both in the log, so the build's inputs
  can be read before Start. Tick the effects to ship (each shows
  its flash cost after a first build), pick the environment - the active
  device's chip suggests one - and the studio builds WLED with your
  effects as a usermod and sends it over OTA to the active device. The
  frame says in plain words when a build will not fit the board's
  partition. Under FEATURES untick what your device has not - the motion
  sensor, the knob and screen, slider memory - and choose the audio (with
  the waveform, stock, or none): the firmware gets smaller, and the nodes
  that lean on a feature you left out say so. Device > Usermods and
  features manages WLED's own usermods for the project as well: tick,
  untick, add one from the tree, import a folder or zip.

**Export usermod** (Device menu, or File > Project) writes the usermod
folder and zip for a build elsewhere. If the effects (or a graph bundle)
need firmware not every WLED tree has - the IMU driver - the studio asks
whether to include it; importing such a bundle offers to turn the feature
on and install what it carries.

## When something is wrong

- The example graphs in `projects/default/graphs` are twenty-two effects
  rebuilt from the firmware's own; `python examples/build_examples.py
  --check` compiles, builds and runs them all (and every scriptable one in
  the Script effect). `python tests/smoke_app.py` drives the app through
  its main flows and fails on any traceback; `python tests/walk_menus.py`
  calls every menu item and context-menu row.
- A frame that throws is written once to `%TEMP%\cubefx\crash.txt` (this
  run's; the last run's is `crash.prev.txt`) and to the console, and the
  status line says so; the sim pauses.
- Settings > Appearance: dark, light, soft light or slate, and every one
  of the theme's seven colours editable.
- Settings > "Draw the cube on the GPU" / "Scale the net on the GPU" are
  the fast paths; turn them off if the views misbehave on a machine.
