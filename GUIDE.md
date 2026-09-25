# WLED Effects Studio — a short guide

Effects for a WLED LED cube (or any matrix or strip), built as node graphs
or as C++, previewed on a simulated cube with synthetic or live audio, and
sent to the device three ways. [The node reference](NODES.md) lists every
node; [the tutorial](TUTORIAL.md) builds a first effect node by node;
[STUDIO.md](STUDIO.md) is the long history and roadmap.

## First run

**The packaged app** (a release zip, or `python package.py` from the
tree): unzip anywhere and run `WLED Effects Studio.exe`. It is portable -
projects, builds and captures land in its folder (or in `%LOCALAPPDATA%\WLED
Effects Studio` when the folder cannot be written to). The engine comes
prebuilt, and the release ships a compiler (a cut-down MinGW-w64 GCC in
`toolchain\`), so everything works at once, building your own effects
included - a new effect builds in seconds. Only flashing firmware needs
more: a checkout of the WLED fork and PlatformIO. The Flash frame offers
to get the checkout itself (**Get the WLED fork...**: a clone beside the
app, or the branch as a zip when git is not installed; then a restart),
or takes one you have (**I have one: choose its folder...**, or `WLED_ROOT`). `WLED Effects Studio (console).exe` is
the same app with a console, for when something goes wrong.

**Updates**: the app asks the studio's releases on GitHub once a day
(Help > Check for updates... asks now; the dialog's checkbox turns the
daily check off). A newer release shows in Help as "Update available";
**Download and install** fetches the zip, closes the studio, copies the new
one over its folder - projects, captures and the toolchain untouched - and
starts it again. From a checkout the answer is `git pull`.

**From the tree**:

```bash
cd wled-effects-studio                                 # the clone
pip install -r requirements.txt                        # dearpygui, numpy, pillow; the audio packages
python -m native.doctor                                # what is here and what is missing
python build.py --native-only                          # once; the app rebuilds the engine as it needs
python -m native.app                                   # or the desktop shortcut
```

**Help**: the first time the studio starts, a Welcome panel offers the
[tutorial](TUTORIAL.md), this guide, the example effects and a search
for devices (Help > Welcome... brings it back; its checkbox shows it at
every start). Help > User guide (**F1**), Tutorial and Node reference
open in a window of the studio's own: the contents down the left mark
the section on screen, the box at the top searches the page - each
mention in turn, marked where it is (Enter or F3 for the next, Shift+F3
the one before, with which of how many) - a link to another document
opens it there, **< Back** (Alt+Left, or Backspace) returns to where you
were, and Esc closes it. A picture the page had to shrink opens at full
size on a click (**Fit the window** and **Full size** switch between
the two); a block of code has a **copy** button. In the graph, **F1**
over a node - or with one selected - opens that node's own entry in the
[node reference](NODES.md); the first row of a node's right-click menu
does the same, and every row of that menu shows its key. Keyboard
shortcuts moved to **Shift+F1**.

The window: a menu bar and a toolbar of icons; the two views (the
**logical net** the effect draws, and the **3-D cube**); a side panel with
the project, the effect, its sliders, the segments, the geometry, colours
and audio. **G** opens the graph pane, **C** the code pane; **Q / E / W**
show one view or both full-frame (press again to come back); **H** hides
every control; **space** pauses. Every key is on the menus and under
Settings > Keyboard shortcuts, where any can be changed. Every control
explains itself on hover; a dim **(?)** at the end of a row holds what
the row as a whole is for. Buttons say what they weigh: the one a dialog
or a frame is for is filled in the accent, one that changes a device or
deletes something is red, a way out (Cancel, Not now) has no slab. What
has nothing to act on is greyed - on the menus, the toolbar and in the
frames: Delete with nothing selected, Undo with nothing done, a send
with no device - and its key says why instead. An empty list says what
it would hold and offers the next step (the Send frame with no device:
**Find a device**). The toolbar's
right half is the device and the frames: devices (Ctrl+Shift+N), flash
(Ctrl+Shift+U), send to device (Ctrl+Shift+S), the DDP stream on or off
(Ctrl+Shift+T, lit amber while it runs); then the shape editor
(Ctrl+Shift+E), the sequence (Ctrl+Shift+Q), the library (Ctrl+Shift+L),
the palettes (Ctrl+Shift+G), the LED outputs (Ctrl+Shift+O) and the audio
input (Ctrl+Shift+M). Playback > Randomise is Ctrl+Shift+X.

**Type and size.** The interface is set in the system's own face (Segoe
UI on Windows) at the system's own size: a frame's title larger and
heavier, the capitals over a group of controls (STEPS, ON THE DEVICE)
smaller and heavier, a caption beside what it belongs to - a count, a
size, a key - small. Code, the logs, the status line's figures, the
values in a node's fields and the numbers drawn on the graph and the
timeline are in its monospace (Consolas), so their columns line up and a
changing figure does not shift the words after it; a node's title and
its pins' names are words, in the interface's face. Everything comes at
one **interface size** - the type, every control, the panes, the dialogs
and the icons - and it starts as the monitor's own scale (the system's
display setting), so the studio is as large as the rest of the desktop.
Settings > Appearance > **Interface size** sets it from 80 to 200%;
**The monitor's** goes back to the system's. The size takes effect at
the next start: **Restart now** closes the studio and starts it again
at once (the graph is saved; code with unsaved changes is asked about
first). The side panel's width and the 3-D view's size over the graph
keep their share of the window across a change; the graph keeps a zoom
of its own (the wheel, or View > Zoom), first the one nearest the
interface size.

**Forms read left to right.** In the side panel and the frames a row's
name comes first, right-aligned in a column of its own against its
control, so the names and the controls each line up (a name too long
for the column is cut, the whole of it on hover); a checkbox keeps its
words after it, under the controls; where a row holds several fields,
each is led by its own words ("presets from [10] playlist [9] named
[Show]"), and a unit sits inside its field where the field allows
("10.0 s", "120.0 bpm", "30 fps"). A **colour** is its swatch and its
hex: a click on the swatch opens the picker (with R, G and B), and the
hex takes #FFA000, FA0 or 255,160,0 typed and Enter. The LED outputs are
a table under their column names.

**The graph gets the room.** In the graph layout the canvas takes the
window (View > Graph: canvas first; off, the 3-D view, the properties
and the panel sit beside the graph as panes, as in the other layouts).
The side panel folds to a **rail** of its sections' icons at the
window's edge: a click opens the panel beside the rail at that
section (or, the panel open, goes to it, the section in view lit on the
rail), and the rail's top button folds it away again. The **3-D view** sits in
a corner of the graph: its `:::` drags it to another corner, its size
handle (or Ctrl+wheel over it) sizes it, and its tuck button puts it
away to a tab in the corner, where it is not drawn until the tab (or
View > 3-D view over the graph) brings it back; the minimap keeps to a
corner the view leaves free. A node's long settings (bitmap rows,
expressions, files, curves) come up in the **properties** over the graph
while such a node is selected, and while the add menu is open the node
under the pointer is described there - what it does, every pin and
setting - before you add it; N keeps them open, their x closes them
until another node is selected. As panes, the properties sit under the
3-D view (N hides them). What a node or pin does comes up **at the
pointer** when it rests on one (as panes, in the box above the graph).

The panes go where you want them: drag one by the `:::` at its top right
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
pin to wire, or to empty space for a list of what could go there. A
node's fields line up after their names. Every **number** - on a node,
in the side panel, in the frames - is the same control: its value on
the track, with its unit ("20 ms", "1.2 Hz", "120 bpm"); **drag** it
sideways to change it (Shift: ten times as far, Alt: a hundredth); **click**
it - press and let go without moving - to type a value (Enter takes it,
Escape leaves it; a double click or Ctrl+click does the same);
**Ctrl+wheel** over it steps it. One with a range has a thin **fill**
under it for where it sits; one without paces itself by its size (a big
number moves in big steps, a small one finely), and one that moves by
ratio - a time, a rate, a scale - moves by ratio, its fill along the log
of its range. Press `=` over a number on a node (or use "type an
expression..." in a pin's menu, "type an expression for" in the node's)
for a box that takes **arithmetic**: `2*pi`, `1/3`, `x*2` (x is the
value it has), `sqrt(2)`, `min(a, 4)` with the node's own numbers by
name, `rand()`; Enter sets it, Escape leaves it. Two
inputs that make one point - Transform's pivot and move, Gravity's
tilt, Mandelbrot's Julia constant - also get an **XY pad**: drag the dot
and both fields follow. Effect settings' palette is picked by name. Every
node and pin explains itself at the pointer when hovered (or in the box
above the graph, as panes), and while the effect is on the cube that
shows the pin's live value. The
bolt on the toolbar (**L**) rebuilds as you edit; F5 rebuilds on demand.
A typed value on a pin needs no rebuild at all: the compiled effect
reads it from a small table, and dragging the field (or the XY pad)
pokes the running engine, so the picture follows the drag at once -
as a synth follows a knob. Adding or wiring nodes, a setting on a node
or a colour still rebuilds.
Sub-graphs (select nodes, Ctrl+G) fold a cluster into one node you can
reuse. File > History keeps a copy at every save. The editor has the
Blender habits: A selects all, Ctrl+[ / Ctrl+] grow the selection up or
down the wires, Shift+Home frames it, Ctrl+Delete deletes a node and
joins the wires across it, a node dropped on a wire is spliced in, a
Ctrl+right-drag cuts wires, Alt while editing a value edits every
selected node of that type, Backspace over a value resets it, Ctrl+P is
the command palette and Ctrl+Alt+Z the undo history. **Snapshots**
(Ctrl+Shift+K) keep the whole graph's settings as named states - save
the look you have, bring one back, morph between two with a slider. A
node's menu can
**change its type** (the wires stay where they fit), **reset its
settings**, and **unfold** a sub-graph node back into its nodes; with
several nodes selected, **merge selection through** an Add, Multiply,
Mix, Blend... wires their outputs together. Inside a sub-graph the trail
above the graph (breadcrumbs) leads back up. A value used all over a big
graph - the beat, a master speed - can travel without a wire: a **Send**
named `beat` feeds every **Receive** named `beat` (Send colour / Receive
colour for a colour); the compiler joins each pair, so they cost nothing.
A wire that would close a **loop** gets a **Delay** put on it for you
(the loop then carries last frame's value, the only thing a loop can
carry); a loop through a per-pixel node or a colour is refused as
before, and the message names the fix (Previous, for a colour). A **Bitmap** node's pixels
are painted in the properties pane: the left button sets the pen's
digit (a colour slot for Colour pick), the right empties a pixel, and
the rows follow. Zoomed out past 50% (Settings > Simplified nodes
below) the nodes become small stand-ins - a title, one line on what the
node computes, and its wires - for getting about a big graph. Every
node has that **one line**: `a × 2`, `0..1 -> 3..5`, `sine × 3 cycles`,
`-> target in 0.2 s`, the palette's name - made from its settings and
typed values, following a drag. A collapsed node shows it as its body,
and the help on hover puts it before the node's description. Nodes wear their **category's colour** on the title bar (amber
sliders, blue signals, teal coordinates, violet patterns, slate maths,
rust colour, green custom code, magenta output; the add menu's headers
match), so a graph reads by colour first; Settings > Appearance has the
legend and the switch, and a colour you give a node still wins. Nodes
also **show what they do**, like a rack module's face: a strip of the
palette or a colour ramp with a marker at the live index, the audio's
sixteen bands live (an FFT bin's own bar lit), a period of the Wave with
a dot riding it, the Noise's texture scrolling with its z, thumbnails of
Checker, Stripes, Ripple, Voronoi, Brick, Mandelbrot and the Gradient at
their typed values, the transfer curve of Remap, Smoothstep, Clamp,
Threshold, Power and the other one-in one-out maths nodes, a Bitmap's
pixels, a Path from above, an Image's picture, a Text's text, and a
three-second sparkline on Integrate, Ease, Envelope, Spring, Delay,
Random hold, Beat kick and Tempo; a Steps node lights its current step.
On the pins, a switch is a **light** (bright when on, glowing out after
a one-frame hit) and a number whose range is known has a **meter** under
it; hovering a frame-scope output draws its last three seconds beside
the pin, and a **Scope** node left on any wire keeps that plot in the
graph (its seconds set the window; it costs the effect nothing). A pin
fed by "modulate with" shows its **range** under its name - a bar from
the low end to the high with the live value on it and the numbers at
its ends; Ctrl+wheel over an end nudges it.
Settings > Keyboard shortcuts lists the rest.

**As code.** Ctrl+N in the code pane makes a `.cpp` from the effect
skeleton; the editor colours it, errors from a build go to their lines,
and the API reference under it lists what the firmware offers - a click
puts the snippet at the cursor. Find (Enter next, Shift+Enter previous,
F3 / Shift+F3 the same, the status saying "3 of 12"; "case" and "word"
narrow it) and replace - one at the cursor, or all. A graph can
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
scrubbing back through the last seconds while paused (in every view,
the point cloud too), and a **speed** -
1/4x to 4x (Shift+, and Shift+. step it, Shift+/ is back to 1x) - for
watching an effect slowly or running it ahead; the footer says the speed
while it is not 1x. The footer also names the **LED under the pointer**
in either view: its wiring index, its part, its position. A **MIDI
controller** (Playback > MIDI controller...) puts its knobs on the
sliders: pick the port ("Rescan" after plugging one in), pick what a knob
should drive - a parameter slider, a check, the palette or the effect by
index, a typed value on a pin of the open graph - press "Learn" and move
the knob; a right-click on a parameter slider, or a pin's menu, offers
the same. A mapping moves the slider, the picture and, with the sim
streamed, the device; a pin's mapping has a range to edit and belongs to
that graph. The mappings are the project's. It needs the optional
python-rtmidi (`pip install python-rtmidi`); without it the window says
so. Segments (+ in
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
  which reorders the wiring. **ARRANGE** works on the parts ticked in
  the list: align them to this part on X, Y or Z, spread three or more
  evenly along an axis, or give them this part's scale or turn.
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

Units are LED pitches - a strip with pitch 1 has its LEDs one unit
apart - so a mesh's own units are the pitch when it is imported.

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
opacity and blend, the colours, the brightness - with a name, how long
it is **held** and how long it **blends** in from the one before. "Update from the sim"
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
- **Audio input** (Device menu, Ctrl+Shift+M): what the device listens
  through - a microphone (INMP441, SPH0645, a PDM mic, an ES7243 module)
  or a **line-in**: a PCM1808 / WM8782 ADC breakout (the four I2S wires,
  the master clock included - any free GPIO on an S3), or an ES8388
  codec board's line-in jack (the AudioKit's and the LyraT's pins are
  filled in; another board's typed in, with its I2C pins). Pick the
  MODULE and the type, the pins a board fixes, and the levels a line
  signal wants (gain 40, squelch 4, no AGC) are set; edit any of them.
  "Read the device's" shows what it runs now; **Send the audio input**
  writes it over /json/cfg - the levels take at once, a new type or new
  pins after a reboot, which is offered. Tick **meter** and the bar
  shows the level the device hears, twice a second: play something into
  the jack and watch it move. A fresh flash boots with these settings
  too (the studio's env carries them as flags). On a line-in the fork's
  firmware mixes both channels to mono and removes the DC offset, so a
  line signal drives the audio nodes the way a mic does.
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
- Settings > "Draw the 3-D view on the GPU" / "Scale the logical view on
  the GPU" are the fast paths: a cube is drawn as its faces, textured;
  every other geometry as a cloud of squares, one per LED, coloured from
  one texture written once a frame (a 2,000-LED sphere: 6 ms a frame
  against 34 on the CPU). Turn them off if the views misbehave on a
  machine; pictures and recordings always come from the software renderer.

## Reference: every menu, key and button

<!-- uiref start: written by `python tests/make_uiref.py` from the running app - change the app, not this -->

### Menus

- **File** › New graph effect... `Ctrl+N`
- **File** › New code effect...
- **File** › Open graph › … the project's graphs
- **File** › Open code effect › … the project's code effects
- **File** › Save `Ctrl+S`
- **File** › Rename... `F2`
- **File** › Remove from the effects list `Ctrl+I`
- **File** › History... `Ctrl+Shift+Y`
- **File** › Library... `Ctrl+Shift+L`
- **File** › Generate previews of every effect
- **File** › Open graph as code
- **File › Project** › New project...
- **File › Project** › Open › … the projects
- **File › Project** › Recent › … the projects opened lately
- **File › Project** › Open folder...
- **File › Project** › Export project as zip — the whole project - effects, graphs, sub-graphs, user nodes, assets, the settings - as one zip in captures/, to keep or to hand over; the history and the export folder stay behind
- **File › Project** › Import project from zip... — a zip made here (or a project folder zipped by hand) into projects/, and opened
- **File › Project** › Export usermod (folder + zip)
- **File** › Import graph bundle...
- **File** › Export graph bundle
- **File** › Screenshot of the 3-D view `F12`
- **File** › Record 15 s GIF `Ctrl+F12`
- **File** › Record 15 s video `Ctrl+Shift+F12`
- **File** › Quit
- **Edit** › Undo `Ctrl+Z`
- **Edit** › Redo `Ctrl+Y`
- **Edit** › Undo history... `Ctrl+Alt+Z`
- **Edit** › Repeat last action `Shift+R`
- **Edit** › Cut `Ctrl+X`
- **Edit** › Copy `Ctrl+C`
- **Edit** › Paste `Ctrl+V`
- **Edit** › Duplicate with inputs `Shift+D`
- **Edit › Delete** › Delete `Delete`
- **Edit › Delete** › Delete and reconnect `Ctrl+Delete`
- **Edit › Delete** › Disconnect (keep the nodes)
- **Edit › Select** › All `A`
- **Edit › Select** › None `Alt+A`
- **Edit › Select** › Invert `Ctrl+Shift+I`
- **Edit › Select** › What feeds the selection `Ctrl+[`
- **Edit › Select** › What the selection feeds `Ctrl+]`
- **Edit › Select** › Everything wired to it `Shift+L`
- **Edit** › Command palette... `Ctrl+P`
- **Edit** › Snapshots... `Ctrl+Shift+K`
- **Edit** › Palettes (gradients)... `Ctrl+Shift+G`
- **Edit** › Find / replace in code `Ctrl+F`
- **Edit** › Open code in external editor `Ctrl+E`
- **Device** › Devices... `Ctrl+Shift+N`
- **Device** › Flash firmware... `Ctrl+Shift+U`
- **Device** › Send to device... `Ctrl+Shift+S`
- **Device** › Sequence: presets and a playlist... `Ctrl+Shift+Q`
- **Device** › LED outputs and power... `Ctrl+Shift+O`
- **Device** › Audio input (mic / line-in)... `Ctrl+Shift+M`
- **Device** › Active device › … the devices known
- **Device** › Scan the network for devices
- **Device** › Stream the sim to the device (DDP) `Ctrl+Shift+T`
- **Device** › Send the graph as a script `Ctrl+Shift+D`
- **Device** › Send the current effect's settings `Ctrl+Shift+P`
- **Device** › Send the shape (ledmap + positions)
- **Device** › Send the ledmap only
- **Device** › Import the device's ledmap
- **Device** › Import a ledmap file...
- **Device** › Usermods and features...
- **Device** › Export usermod (folder + zip)
- **View** › Logical net `Q`
- **View** › 3-D view `E`
- **View** › Net and 3-D `W`
- **View** › Code `C`
- **View** › Graph `G`
- **View** › Presentation (hide controls) `H`
- **View** › Side panel
- **View** › Properties pane (graph) `N` — the selected node's longer settings; canvas first they come up over the graph when a node needs them, and this (N) keeps them open
- **View** › Graph: canvas first — the graph takes the window: the 3-D view in a corner of it, the properties over it when a node needs them, the panel a rail of its sections, the help at the pointer; off, they sit beside the graph as panes
- **View** › 3-D view over the graph — canvas first: the 3-D view in its corner of the graph, or tucked away to a tab
- **View** › Focus mode (dim all but the selection) `/`
- **View** › Fullscreen `F11`
- **View › Zoom** › Zoom in `Ctrl+=`
- **View › Zoom** › Zoom out `Ctrl+-`
- **View › Zoom** › Zoom 100% `Ctrl+0`
- **View › Zoom** › Frame all `Home`
- **View › Zoom** › Frame the selection `Shift+Home`
- **View** › Snap to grid `Shift+Tab`
- **View** › Minimap
- **View › Camera** › Isometric
- **View › Camera** › Front
- **View › Camera** › Back
- **View › Camera** › Left
- **View › Camera** › Right
- **View › Camera** › Top
- **View › Camera** › Below
- **View › Camera** › Saved view 1
- **View › Camera** › Save the view as 1
- **View › Camera** › Saved view 2
- **View › Camera** › Save the view as 2
- **View › Camera** › Saved view 3
- **View › Camera** › Save the view as 3
- **View › Camera** › Background picture...
- **View › Camera** › Clear the background
- **View** › Shape editor... `Ctrl+Shift+E`
- **View** › Generate a preview of the shape
- **View › Layout** › Classic: main pane, 3-D, panel
- **View › Layout** › Panel on the left
- **View › Layout** › 3-D on the left
- **View › Layout** › 3-D under the main pane
- **View › Layout** › 3-D above the panel
- **View › Layout** › Panel under the 3-D, main pane on the right
- **View › Layout** › Reset pane sizes
- **View › Pop out (a window of its own, for another monitor)** › The logical net
- **View › Pop out (a window of its own, for another monitor)** › The 3-D view
- **Node** › Add node...  (or right-click the graph) `Shift+A`
- **Node** › Add › … every node (see NODES.md)
- **Node** › Connect selected `F`
- **Node** › Swap the first two inputs `Alt+S`
- **Node** › Label the node... `Shift+F2`
- **Node › Show** › Collapse / expand `K`
- **Node › Show** › Hide / show unwired pins `Ctrl+H`
- **Node › Show** › Mute (pass through) `M`
- **Node › Arrange** › Arrange (the selection, or all) `Ctrl+L`
- **Node › Arrange** › Frame the selection `Ctrl+J`
- **Node › Arrange** › Align left edges `Alt+Left`
- **Node › Arrange** › Align right edges `Alt+Right`
- **Node › Arrange** › Align tops `Alt+Up`
- **Node › Arrange** › Align bottoms `Alt+Down`
- **Node › Arrange** › Align centres, across
- **Node › Arrange** › Align centres, down
- **Node › Arrange** › Distribute across `Alt+H`
- **Node › Arrange** › Distribute down `Alt+V`
- **Node › Sub-graph** › Fold the selection into one... `Ctrl+G`
- **Node › Sub-graph** › Enter the selected sub-graph `Tab`
- **Node › Sub-graph** › Back to the parent graph
- **Node** › Where is the selected node's type used
- **Node** › Stop pin preview `Escape`
- **Playback** › Play / pause `Space`
- **Playback** › Step one frame `.`
- **Playback › Speed** › 1/4x
- **Playback › Speed** › 1/2x
- **Playback › Speed** › 1x
- **Playback › Speed** › 2x
- **Playback › Speed** › 4x
- **Playback › Speed** › Slower `Shift+,`
- **Playback › Speed** › Faster `Shift+.`
- **Playback › Speed** › Back to 1x `Shift+/`
- **Playback** › Restart effect `Ctrl+R`
- **Playback** › Randomise the settings `Ctrl+Shift+X`
- **Playback** › Sequence...
- **Playback** › Compare with another effect... `Ctrl+Shift+B`
- **Playback** › Sweep a slider... `Ctrl+Shift+W`
- **Playback** › MIDI controller...
- **Playback** › Compile + reload `F5`
- **Playback** › Run the graph as a script (no build) `Ctrl+Shift+R`
- **Playback** › Live: rebuild the graph as it changes `L`
- **Playback** › Watch: rebuild when the code is saved outside
- **Settings** › Keyboard shortcuts...
- **Settings** › Selection frames...
- **Settings** › Appearance...
- **Settings** › External editor command...
- **Settings** › Draw the 3-D view on the GPU — the shape's faces as textured quads on the GPU, where it has them; loose LEDs are drawn as points either way. Off: the software renderer for everything - the fallback when a machine's GPU misbehaves
- **Settings** › Scale the logical view on the GPU — softer LED edges and faster; off: the CPU repeats each LED's pixels
- **Settings › Simplified nodes below** › 70%
- **Settings › Simplified nodes below** › 50%
- **Settings › Simplified nodes below** › 40%
- **Settings › Simplified nodes below** › 30%
- **Settings › Simplified nodes below** › never
- **Settings** › Device speed factor...
- **Settings** › Open the project folder
- **Settings** › Open the build folder
- **Help** › User guide `F1` — every part of the studio, in a window here: the contents down the side, a search, the keys and menus at the end
- **Help** › Tutorial — a first effect from nothing, step by step, with pictures
- **Help** › Node reference — every node, pin and setting; F1 over a node in the graph opens its own entry
- **Help** › Effect API reference — what a code effect can call, beside the code editor
- **Help** › Keyboard shortcuts `Shift+F1`
- **Help** › Welcome...
- **Help** › Check for updates...
- **Help** › Report a problem... — bundles what a bug report needs - the version, the doctor's findings, the machine, the project's settings, the last crash - into one zip in captures/, and offers the issues page; nothing of your effects or graphs goes in
- **Help** › About

### Keys

Every action, its key (Settings › Keyboard shortcuts rebinds them) and where it works.

| Key | Does | Where |
|---|---|---|
| `Q` | Logical net, full frame (again: back to the panels) | anywhere |
| `E` | 3-D view, full frame (again: back) | anywhere |
| `W` | Net and 3-D, full frame (again: back) | anywhere |
| `C` | Code pane (again: back) | anywhere |
| `G` | Graph pane (again: back) | anywhere |
| `H` | Presentation: hide / show the controls | anywhere |
| `F11` | Fullscreen window | anywhere |
| `Ctrl+Shift+H` | Hide / show the side panel | anywhere |
| `N` | Hide / show the graph's properties pane | in the graph |
| `—` | Graph layout: canvas first (3-D in a corner, the panel a rail) or panes | anywhere |
| `—` | The side panel beside the graph: open it / fold it to its rail | in the graph |
| `—` | The 3-D view over the graph: tuck it away / bring it back | in the graph |
| `Space` | Play / pause | anywhere |
| `.` | Step one frame | anywhere |
| `Shift+,` | Playback slower (1/4x .. 4x) | anywhere |
| `Shift+.` | Playback faster | anywhere |
| `Shift+/` | Playback at 1x | anywhere |
| `Ctrl+R` | Restart the effect | anywhere |
| `[` | Previous effect in the list | anywhere |
| `]` | Next effect in the list | anywhere |
| `Shift+[` | Previous palette | anywhere |
| `Shift+]` | Next palette | anywhere |
| `L` | Live: rebuild the graph as it changes | anywhere |
| `Ctrl+Shift+B` | Compare with another effect side by side / stop | anywhere |
| `Ctrl+Shift+W` | Sweep a slider through its range / stop | anywhere |
| `F5` | Compile + reload | anywhere |
| `Ctrl+N` | New effect | anywhere |
| `Ctrl+O` | Open a graph or code effect (the list) | anywhere |
| `Ctrl+S` | Save | anywhere |
| `F2` | Rename | anywhere |
| `Ctrl+I` | Add to / remove from the effects list | anywhere |
| `Ctrl+F` | Find / replace in the code | anywhere |
| `F3` | Find the next match | anywhere |
| `Shift+F3` | Find the previous match | anywhere |
| `Ctrl+E` | Open the code in the external editor | anywhere |
| `F12` | Screenshot of the 3-D view | anywhere |
| `Ctrl+F12` | Record 15 s as a GIF | anywhere |
| `Ctrl+Shift+F12` | Record 15 s as a video (mp4; needs ffmpeg) | anywhere |
| `F1` | User guide: the studio's help, in a window | anywhere |
| `F1` | The reference for the node under the pointer (else the selected one) | in the graph |
| `—` | Tutorial: a first effect, step by step | anywhere |
| `—` | Node reference: every node, pin and setting | anywhere |
| `—` | Welcome: where to start | anywhere |
| `Shift+F1` | Keyboard shortcuts | anywhere |
| `Ctrl+Shift+U` | Build the firmware and flash the device | anywhere |
| `Ctrl+Shift+P` | Send the current effect's settings to the device | anywhere |
| `Ctrl+Shift+R` | Run the graph as a script (what the device would run) | anywhere |
| `Ctrl+Shift+D` | Send the graph to the device as a script | anywhere |
| `Ctrl+Shift+T` | Stream the sim to the device (DDP), on / off | anywhere |
| `Ctrl+Shift+N` | Devices on the network | anywhere |
| `Ctrl+Shift+S` | Send to device: the effects, a script, the shape | anywhere |
| `Ctrl+Shift+E` | Shape editor | anywhere |
| `Ctrl+Shift+Q` | Sequence: presets, a playlist and the schedule | anywhere |
| `Ctrl+Shift+L` | Library: every effect as a looping thumbnail | anywhere |
| `Ctrl+Shift+G` | Palettes: gradients of the project's own | anywhere |
| `Ctrl+Shift+O` | LED outputs and power | anywhere |
| `Ctrl+Shift+M` | Audio input: the device's microphone or line-in | anywhere |
| `Ctrl+Shift+X` | Randomise the settings | anywhere |
| `Ctrl+Z` | Undo (the graph, or the code) | anywhere |
| `Ctrl+Y` | Redo (the graph, or the code) | anywhere |
| `Ctrl+X` | Cut | in the graph |
| `Ctrl+C` | Copy | in the graph |
| `Ctrl+V` | Paste | in the graph |
| `Shift+D` | Duplicate with its inputs | in the graph |
| `Delete` | Delete the selection | in the graph |
| `Shift+A` | Add a node (search) | in the graph |
| `F` | Connect two selected nodes | in the graph |
| `M` | Mute | in the graph |
| `K` | Collapse / expand | in the graph |
| `Ctrl+H` | Hide / show unwired pins | in the graph |
| `Ctrl+G` | Fold the selection into a sub-graph | in the graph |
| `Tab` | Enter the selected sub-graph / back out | in the graph |
| `Ctrl+L` | Arrange (the selection, or the whole graph) | in the graph |
| `Alt+Left` | Align the selected nodes' left edges | in the graph |
| `Alt+Right` | Align their right edges | in the graph |
| `Alt+Up` | Align their tops | in the graph |
| `Alt+Down` | Align their bottoms | in the graph |
| `Alt+H` | Distribute the selected nodes across | in the graph |
| `Alt+V` | Distribute them down | in the graph |
| `Ctrl+=` | Zoom in | in the graph |
| `Ctrl+-` | Zoom out | in the graph |
| `Ctrl+0` | Zoom 100% | in the graph |
| `Home` | Frame the whole graph | in the graph |
| `Escape` | Stop the pin preview | in the graph |
| `/` | Focus mode: dim all but the selection | in the graph |
| `A` | Select every node | in the graph |
| `Alt+A` | Select nothing | in the graph |
| `Ctrl+Shift+I` | Invert the selection | in the graph |
| `Ctrl+[` | Select what feeds the selection too | in the graph |
| `Ctrl+]` | Select what the selection feeds too | in the graph |
| `Shift+L` | Select everything wired to the selection | in the graph |
| `Shift+Home` | Frame the selection | in the graph |
| `Shift+Tab` | Snap to grid on / off (Ctrl while dragging: the other way) | in the graph |
| `Ctrl+Delete` | Delete and reconnect (what fed it feeds what it fed) | in the graph |
| `—` | Disconnect the selected nodes (every wire in and out) | in the graph |
| `=` | Type an expression into the value under the pointer | in the graph |
| `Alt+S` | Swap a node's first two inputs | in the graph |
| `Shift+F2` | Label the selected node | in the graph |
| `Ctrl+J` | Put a Frame round the selection | in the graph |
| `Shift+R` | Repeat the last action | anywhere |
| `Ctrl+P` | Command palette: every action by name | anywhere |
| `Ctrl+Shift+K` | Snapshots: the graph's settings as named states | anywhere |
| `—` | MIDI controller: knobs onto the sliders | anywhere |
| `Ctrl+Alt+Z` | Undo history | anywhere |
| `Ctrl+Shift+Y` | History of the current graph or code | anywhere |

### Buttons

Every button, with what its tooltip says.

**Devices frame**: `dock` — dock: into the pane space, under the main pane (or drag the grip onto a pane); `close` — close (Esc while the frame has the focus); the menu opens it again; `Scan the network` — asks by mDNS, asks every known device for the nodes it has heard of, and sweeps the subnet; `Stop`; `Add`; `Refresh all` — asks every listed device again what it is and runs; `use`; `remove`

**Flash Firmware frame**: `dock` — dock: into the pane space, under the main pane (or drag the grip onto a pane); `close` — close (Esc while the frame has the focus); the menu opens it again; `flash_env_fit`; `Preview (no compile)` — stages the build and lists what it would carry - the manifest, resolved the way the build resolves it - without compiling; `all`; `none`; `Usermods...`; `Start`; `Cancel`; `Open the build folder`

**Send To Device frame**: `dock` — dock: into the pane space, under the main pane (or drag the grip onto a pane); `close` — close (Esc while the frame has the focus); the menu opens it again; `Find a device`; `Read` — ask the device again what it is and runs; `Open in the browser`; `Calibrate the speed factor` — the current effect's settings sent, the device's fps read for three seconds, and the footer's device fps estimate set from the measurement (Settings > Device speed factor holds the number); `Send the graph as a script` — the graph as bytecode for the Studio Script effect - no firmware build; the device runs it at once; `Send the effect's settings` — the effect the sim shows, with its sliders, checks, palette and colours, onto the device's segment; `Send the shape` — the ledmap (the wiring) and the positions table, so Position and Direction see the real shape; `Send the ledmap only`; `Import the device's` — the device's ledmap becomes the geometry: a matrix with its gaps and wiring, or a strip; `Import a file...`; `<`; `>`

**Shape frame**: `dock` — dock: into the pane space, under the main pane (or drag the grip onto a pane); `close` — close (Esc while the frame has the focus); the menu opens it again; `Undo`; `Clear`; `Open...` — a shape file (.shape.json) saved from here; `Save...`; `Export .xmodel...` — the shape as an xLights custom model, the wiring as its node numbers; `Export positions...` — every LED as a CSV row - x, y, z, its wiring index, its part - in wiring order, for any other tool; Import... reads the file back as a points part; `Segment per part` — each part its own WLED segment - effect, palette, sliders - up to eight; `+ strip` — a straight run of n LEDs along X; `+ ring` — n LEDs round a circle in the X-Y plane (radius 0: from the pitch); `+ panel` — w x h LEDs, stood up in the X-Z plane facing the camera; `+ cylinder` — w round, h tall, seamless; `+ sphere` — w round, h latitude rows; `+ cube` — B x B a face, five faces (six with the bottom); `+ polygon` — sides straight sides of per_side LEDs each, in the X-Y plane (radius 0: from the pitch); `+ polyhedron` — the edges of a solid, per_edge LEDs each (mode faces: every face outlined on its own); `+ polyline` — a strip run laid along a path, an LED every pitch; `+ points` — LEDs where they are put, in that order; `Import...` — a mesh or model as LEDs: .obj, .ply, .stl from Blender or CAD; an xLights .xmodel, or a whole xLights layout (xlights_rgbeffects.xml: every model a part, where it stands); an x y z [index] point list (CSV, text, JSON); `Reference...` — a mesh drawn in the 3-D view to place LEDs against, not LEDs: the tree, the house, the enclosure; `up`; `down`; `copy`; `x`; `delete the last`; `renumber: nearest chain from the first`; `turn into a path`; `+X`; `-X`; `+Y`; `-Y`; `+Z`; `-Z`; `aim outward`; `turn only`; `aim at the origin`; `from its place` — the direction and distance the part is at now, into the fields; `X`; `Y`; `Z` — the ticked parts given this part's position on that axis; `same scale`; `same turn` — the ticked parts given this part's scale, or its rotation; `tick all`; `none`; `make`; `Generate a preview` — a turn of the shape, rendered off screen: a GIF and a PNG in the project's export folder, looping here; `Open the folder`

**Sequence frame**: `dock` — dock: into the pane space, under the main pane (or drag the grip onto a pane); `close` — close (Esc while the frame has the focus); the menu opens it again; `undo` — the steps (or the schedule) as they were before the last change; Ctrl+Z here does the same, Ctrl+Y redoes; `+ Add from the sim` — a new step: what the sim shows now - effect, sliders, palette, colours, segments; `Update from the sim` — the selected step becomes what the sim shows now; `Load into the sim` — the sim shows the selected step; `Add what the sim shows`; `x` — this slider's ramp off (the others stay); `Play in the sim`; `Stop`; `Render GIF` — plays the sequence once and records it as a GIF, into captures/; `Render video` — plays the sequence once and records it as an mp4, into captures/ - needs ffmpeg on the path; `Tap` — tap tempo: tap on the beat, the bpm from the gaps; `Synth's` — the bpm of the sim's synthetic beat; `WAV's` — the tempo and the beats found in the WAV playing as live audio (AUDIO > play a WAV file); `Snap durations to bars` — every step's seconds rounded to whole bars, so the sequence changes on the music; `Send presets + playlist` — about a second a preset: the device writes each one from its main loop, and the next is sent once it has; `Send and run it`; `Save presets.json...` — the same presets and playlist as a file, for a device that is not on the network; `+ run the playlist at`; `+ off at` — a time the lights go off: an Off preset (id 250) is saved on the device and timed; `Read the device's`; `Send the schedule`; `Run the playlist at...`

**Library frame**: `dock` — dock: into the pane space, under the main pane (or drag the grip onto a pane); `close` — close (Esc while the frame has the focus); the menu opens it again; `Remake the thumbnails`; `Generate previews` — a turn of the 3-D view for every effect on the project's shape - a GIF and a PNG each in export/library, with an index; the tiles then show those turns; `Open the folder`; `no preview`

**Palettes frame**: `dock` — dock: into the pane space, under the main pane (or drag the grip onto a pane); `close` — close (Esc while the frame has the focus); the menu opens it again; `undo` — the palettes as they were before the last change; Ctrl+Z here does the same, Ctrl+Y redoes; `+ New`; `From the sim's palette` — a new one that starts as the palette the sim shows; `Copy`; `Remove`; `Use in the sim`; `New palette`; `spread evenly`; `Send this one` — slot n is /palette{n}.json on the device, palette id 200 - n everywhere; the device reloads its custom palettes on upload; `Send all`; `Remove this one there`

**Led Outputs frame**: `dock` — dock: into the pane space, under the main pane (or drag the grip onto a pane); `close` — close (Esc while the frame has the focus); the menu opens it again; `one output`; `one per part`; `by count:`; `+ output`; `Read the device's`; `One output`; `Send outputs + power limit` — over /json/cfg; the device re-initialises its outputs (reboot it if it does not)

**Audio Input frame**: `dock` — dock: into the pane space, under the main pane (or drag the grip onto a pane); `close` — close (Esc while the frame has the focus); the menu opens it again; `Read the device's` — what the device's audioreactive is set to now (its type, pins and levels), into these fields; `Send the audio input` — over /json/cfg; the levels take at once, a new type or new pins after a reboot (offered when needed); `Reboot the device` — restarts the device so a new type or new pins take effect; the LEDs go dark for a few seconds

**Keyboard shortcuts**: `Reset all to defaults`

**Appearance**: `dark`; `light`; `soft light`; `slate`; `Back to the preset` — the preset's colours again, your changes dropped; `The monitor's` — the size the monitor is set to in the system's display settings; `Restart now` — the studio closes and starts again at the new size; the graph is saved, and unsaved code is asked about first

**Selection frames**: `Save`; `Save + use for nodes`; `Save + use for pane`; `Delete`

**About**: `The studio on GitHub`; `The WLED fork`; `WLED`

**Usermods and features**: `Add`; `Import a folder...`; `Import a zip...`

**Update**: `Download and install`; `Release page`; `Not now`

**A WLED checkout**: `Clone`; `Restart the studio`; `Close`

**Report a problem**: `Open the issues page` — a new issue on the studio's GitHub page, in the browser - attach the zip there; `Show the zip` — the captures folder, where the report landed; `Close`

**The panes and the toolbar**: `New effect` — New effect  Ctrl+N; `Open a graph or a code effect` — Open a graph or a code effect  Ctrl+O; `Save` — Save  Ctrl+S; `Compile + reload` — Compile + reload  F5; `Live` — Live: rebuild the graph as it changes  L; `Undo` — Undo  Ctrl+Z  (nothing to undo); `Redo` — Redo  Ctrl+Y  (nothing to redo); `Play` — Play  Space; `Pause` — Pause  Space; `Step one frame` — Step one frame  .; `Restart the effect` — Restart the effect  Ctrl+R; `Logical net` — Logical net  Q; `3-D view` — 3-D view  E; `Net and 3-D` — Net and 3-D  W; `Code` — Code  C; `Graph` — Graph  G; `Zoom out` — Zoom out  Ctrl+-; `100%` — Zoom 100%  Ctrl+0; `Zoom in` — Zoom in  Ctrl+=; `Frame the whole graph` — Frame the whole graph  Home; `Add a node` — Add a node (or right-click the graph)  Shift+A; `Delete the selection` — Delete the selection  Delete  (select a node first); `Arrange the graph` — Arrange the graph  Ctrl+L; `Fold the selection into a sub-graph` — Fold the selection into a sub-graph  Ctrl+G  (select two nodes or more); `Devices on the network` — Devices on the network  Ctrl+Shift+N; `Build the firmware and flash the device` — Build the firmware and flash the device  Ctrl+Shift+U; `Send to the device` — Send to the device: the effects, a script, the shape  Ctrl+Shift+S; `Stream the sim to the device` — Stream the sim to the device (DDP)  Ctrl+Shift+T; `Shape editor` — Shape editor  Ctrl+Shift+E; `Sequence` — Sequence: presets, a playlist and the schedule  Ctrl+Shift+Q; `Library` — Library: every effect as a looping thumbnail  Ctrl+Shift+L; `Palettes` — Palettes: gradients of the project's own  Ctrl+Shift+G; `LED outputs and power` — LED outputs and power  Ctrl+Shift+O; `Open the code in an external editor` — Open the code in an external editor  Ctrl+E; `Screenshot of the 3-D view` — Screenshot of the 3-D view  F12; `Record 15 s as a GIF` — Record 15 s as a GIF (a video: File > Record 15 s video)  Ctrl+F12; `find` — the next match (Shift+Enter in the box, or Shift+F3: the previous); the status says which of how many; `replace` — the match the cursor is on, then the next is found; `replace all`; `read from file`; `apply to file`; `< back`; `help_split`; `tuck the 3-D view away to a tab in its c` — tuck the 3-D view away to a tab in its corner (it is not drawn while it is away); `drag to size the 3-D view` — drag to size the 3-D view (or Ctrl+wheel over it); its ::: drags it to another corner; `close until another node is selected` — close until another node is selected (N keeps it open); `sec_effect_arrow`; `sec_segments_arrow`; `+`; `-`; `undo` — the segments as they were before the last change (add, remove, bounds, blend, options); `sec_geometry_arrow`; `Edit the shape...`; `sec_colours_arrow`; `sec_parameters_arrow`; `sec_audio_arrow`; `sec_live_arrow`; `use live audio`; `play a WAV file...`; `fold the panel away` — fold the panel away: the graph gets the room back; `EFFECT` — EFFECT: the project, the effect and its palette - goes to it; `SEGMENTS` — SEGMENTS: the strip's segments, their bounds and blends - goes to it; `GEOMETRY` — GEOMETRY: the shape the LEDs are on - goes to it; `COLOURS` — COLOURS: the segment's three colours - goes to it; `PARAMETERS` — PARAMETERS: the effect's sliders and checkboxes - goes to it; `AUDIO` — AUDIO: the synthetic audio's levels - goes to it; `LIVE` — LIVE: audio from a line in, a microphone or a WAV file - goes to it; `vsplit_0_0`; `vsplit_1_0`; `hsplit_0_0`; `hsplit_0_1`; `hsplit_1_0`; `hsplit_1_1`; `hsplit_2_0`; `hsplit_2_1`

<!-- uiref end -->
