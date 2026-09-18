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
hides it). The panes go where you want them: drag one by the `:::` at its top right
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

## Getting it onto the cube

Three routes, all under File > Project, all needing the device's address:

1. **Send the graph as a script** (Ctrl+Shift+D). No firmware build: the
   graph is compiled to bytecode and sent to the Studio Script effect on
   the device, which runs it within two seconds. Playback > "Run the graph
   as a script" previews exactly that in the sim first. Not every node is
   scriptable - the studio names the one that is not.
2. **Build firmware + flash** (Ctrl+Shift+U). Tick the effects to ship
   (each shows its flash cost after a first build), pick the environment,
   and the studio builds WLED with your effects as a usermod and sends it
   over OTA. The dialog says in plain words when a build will not fit the
   board's partition. Under FEATURES untick what your device has not - the
   motion sensor, the knob and screen, slider memory - and choose the
   audio (with the waveform, stock, or none): the firmware gets smaller,
   and the nodes that lean on a feature you left out say so. Settings >
   Usermods and features manages WLED's own usermods for the project as
   well: tick, untick, add one from the tree, import a folder or zip.
3. **Export** the usermod folder and zip for a build elsewhere. If the
   effects (or a graph bundle) need firmware not every WLED tree has -
   the IMU driver - the studio asks whether to include it; importing such
   a bundle offers to turn the feature on and install what it carries.

"Send the current effect's settings" pushes the sliders, palette, colours
and the segment's blend mode; "Send ledmap" uploads the wiring.

## When something is wrong

- The example graphs in `projects/default/graphs` are twenty-two effects
  rebuilt from the firmware's own; `python examples/build_examples.py
  --check` compiles, builds and runs them all (and every scriptable one in
  the Script effect). `python tests/smoke_app.py` drives the app through
  its main flows and fails on any traceback.
- A crash's traceback lands in `%TEMP%\cubefx\crash.txt` as well as the
  console.
- Settings > Appearance: dark, light, soft light or slate, and every one
  of the theme's seven colours editable.
- Settings > "Draw the cube on the GPU" / "Scale the net on the GPU" are
  the fast paths; turn them off if the views misbehave on a machine.
