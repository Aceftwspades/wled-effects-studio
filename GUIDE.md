# WLED Effects Studio — a short guide

Effects for a WLED LED cube (or any matrix or strip), built as node graphs
or as C++, previewed on a simulated cube with synthetic or live audio, and
sent to the device three ways. STUDIO.md is the long history and roadmap;
NODES.md lists every node; TUTORIAL.md builds a first effect node by node.

## First run

```bash
cd studio
pip install dearpygui numpy pillow sounddevice        # pyaudiowpatch on Windows for loopback
python build.py --native-only                          # once; the app rebuilds the engine as it needs
python -m native.app                                   # or the desktop shortcut
```

The window: a menu bar and a toolbar of icons; the two views (the
**logical net** the effect draws, and the **3-D cube**); a side panel with
the project, the effect, its sliders, the segments, the geometry, colours
and audio. **G** opens the graph pane, **C** the code pane; **Q / E / W**
show one view or both full-frame (press again to come back); **H** hides
every control; **space** pauses. Every key is on the menus and under
Settings > Keyboard shortcuts, where any can be changed.

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
the panel) layer several effects with WLED's blend modes and opacity.

## Any shape: the shape editor

GEOMETRY > shape (or View > Shape editor...) opens the **Shape** frame - a
window like the Device ones, docks the same way. A shape is a list of
**parts** in wiring order: strips, rings, panels, cylinders, spheres, cubes,
a strip run along a path (polyline), and loose points. Each part has its
own settings (LED count, pitch, serpentine...), a position, a rotation and
a scale; the buttons make a mirror or an array of it; "reverse" turns its
wiring round; up/down reorder parts, which reorders the wiring. Units are
LED pitches - a strip with pitch 1 has its LEDs one unit apart - so a
mesh's own units are the pitch when it is imported.

- **Import a mesh or model...** reads `.obj`, `.ply` and `.stl` from
  Blender or any CAD program - LEDs **along the edges** at a pitch (a
  strip run round the outline, chained into as few runs as it can), or
  one **per vertex**, or **over the surface** - an xLights **`.xmodel`**
  custom model (the LEDs, their numbering, and its grid), or an `x y z
  [index]` point list (CSV, whitespace or JSON; the index column is the
  wiring order).
- **Place** LEDs by hand: tick "place", click the 3-D view and an LED lands
  on the working plane (z = 0 by default; choose x, y or z and a value);
  they go into the selected points part, or a new one. Drag an LED to move
  it; "renumber: nearest chain" rewires a points part the way a strip
  would most likely be run through them; "turn into a path" makes a
  polyline of the points and fills it with LEDs at the pitch.
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

## A show: the Sequence frame

Playback > Sequence... (or Device > Sequence). A **step** is what the sim
shows when you add it - every segment's effect, sliders, palette, bounds,
opacity and blend, the colours, the brightness - with a name, how many
seconds it holds and a transition time. "Update the step from the sim"
recaptures it, "Load the step into the sim" puts it back to tweak; up /
down reorder; **Play in the sim** runs the steps in turn (a cut at each
change - the transition is the device's). **Send presets + playlist**
saves each step as a WLED preset (ids from "first preset id", existing
ones overwritten) and the sequence as a playlist preset with the
durations and transitions; "Send and run it" starts it; "Save
presets.json" writes the same for a device that is not on the network.
Effects and palettes are matched by name against the device's own lists,
and a step whose effect the device does not have is left out and named.

## Getting it onto the cube

Everything about the device is under the **Device** menu, in three frames.
Each opens as a window over the panes; its **dock** button slots it into
the pane space under the main pane (drag its ::: grip onto any pane to put
it beside or above that one, like the panes themselves), **float** takes
it out again, and the arrangement is remembered.

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
  2. **Send the current effect's settings** pushes the effect, sliders,
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
  lights one LED by its index (< > step it), or one part of a shape (or
  the parts in turn), in the sim and on the device when streaming - the
  way to check a new ledmap or shape before trusting it; play resumes
  the effect.
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
- A crash's traceback lands in `%TEMP%\cubefx\crash.txt` as well as the
  console.
- Settings > Appearance: dark, light, soft light or slate, and every one
  of the theme's seven colours editable.
- Settings > "Draw the cube on the GPU" / "Scale the net on the GPU" are
  the fast paths; turn them off if the views misbehave on a machine.
