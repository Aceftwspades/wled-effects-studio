# WLED Effects Studio — the playground branch

The simulator grows into an effect editor for any WLED user: write an effect
as C++ in the app and see it on your own geometry within a second, or build one
from a stack of layers with sliders bound to the segment's controls, on a strip,
a matrix, a cube, a sphere, a cylinder, a torus, or a coordinate list you
imported from your own build. What you make exports as a usermod file that
compiles into stock WLED unchanged, plus the ledmap for your wiring.

This branch is allowed to change firmware and other usermods. Every such change
is made as if it will be brought forward: small, isolated, named, and with a
fallback so a dropped patch degrades rather than breaks.

## Decisions taken at the start

| question | decision |
|---|---|
| how effects are authored | **C++ first**, compiled with the clang already in use, hot-reloaded. A scripted runtime that runs the same effect on a device without reflashing is a later phase. |
| what the composer produces | **one generated C++ effect** — a node graph compiles to a single `mode_*()` function, exportable as a usermod file. (Decided as a layer stack at first; changed to a ComfyUI-style graph, since a stack is a graph with one edge per node.) |
| geometries | 1-D strip, 2-D matrix with WLED's own orientation options, 3-D parametric shapes (cube net, sphere, cylinder, torus), and custom 3-D from an XYZ file |
| platform | desktop, cross-platform from the start — the Python / DearPyGui app, with audio capture and toolchain detection per OS |

## How it fits together

```
 geometry.json ─┐                          ┌─ ledmap.json  (for the device)
                ├─► logical segment ───────┤
 (kind+params   │   1-D: n                  └─ XYZ per pixel (for the renderer)
  or XYZ list)  │   2-D: w x h (+ lit mask)
                │
 effects/*.cpp ─┼─► clang: one object per TU, cached ─► link ─► engine_N.dll ─► app loads it
 graphs/*.json  ┘   (a graph is generated to .cpp first)           (old one unloaded)
```

WLED itself has no idea of 3-D. An effect sees a 1-D segment or a 2-D matrix,
and a ledmap turns logical pixels into physical ones. So every 3-D shape here
is a **logical 2-D grid plus a position for each logical pixel** — exactly what
the cube net already is, made general. The renderer draws whatever positions
the geometry hands it; the effect code never knows the difference.

## Phases

### Phase 1 — foundation (done, first pass)

1. **Incremental build.** One object per translation unit, cached on source
   and header mtimes, compiled in parallel; a link step produces a **versioned**
   `engine_<n>.dll` so the running app can load the new one and drop the old
   without the file lock that made "close the sim before building" a rule.
   Editing one effect costs one compile and one link — the second, not the
   ten-second full build.
2. **Geometry model.** `native/geometry.py`: strip, matrix (with serpentine /
   vertical / start-corner as WLED's 2-D page defines them), cube net, sphere,
   cylinder, torus, XYZ file. Each yields the logical segment size, a lit mask,
   and an XYZ per logical pixel. The engine's `simInit` grows a 1-D mode; the
   shim gains the 1-D `Segment` surface (`setPixelColor(i)`, `length()`,
   `is2D()` that can say no) and the 1-D stock effects come in beside the 2-D
   ones.
3. **Point-cloud renderer.** `render.py` becomes a generic projector — every
   LED a disc at its XYZ, orbit camera — so a sphere and a strip render the
   same way the cube does.
4. **Code editor panel.** New / open / save an effect `.cpp`; edit; compile;
   errors listed with line numbers and click-to-line; the effect appears in the
   list on success and is selected. The template a new file starts from is the
   folder's own effect skeleton.
5. **Project files.** A folder with `geometry.json`, `effects/`, `recipes/`, and
   an `export/` that receives the usermod folder and the ledmap.
6. **Drafts and the effects list.** A file in `effects/` is a draft: it is
   built, and shows in the roster, only while it is the one being edited, so
   trying things does not pile effects into the list. File > "Add to the
   effects list" makes it a project effect — always built, in the roster,
   exported; the same item removes it again. File > Rename (F2) gives the
   current effect (or graph) a new title, file name and identifiers; a
   renamed sub-graph is rewritten in every graph that uses it.

### Phase 2 — the node graph (done, first pass)

Not a layer stack: a node graph, ComfyUI-style, because layering is just one
node feeding another. `native/nodedefs.py` is the library — controls (the
five sliders, three checkboxes, three colours, each slider node carrying the
label the exported effect will show), signals (time, audio bands, the beat,
a beat-kick that lurches and settles, constants), coordinates (u/v, centred,
polar, the cube's seamless direction), generators (noise, wave, ripple,
sparkle, stripes), maths, colour (palette, HSV, blend with six modes, mask,
Previous for feedback, split/combine), two Expression nodes that take a line
of C++ so a node you have not got can be written on the spot, and Output.

Every node is data: inputs, outputs, params, and a C++ template. A user node
is the same JSON in `<project>/nodes/`. `native/graph.py` compiles a graph to
one ordinary effect file — a topological sort, frame-scope nodes hoisted out
of the pixel loop (a Multiply of two sliders is not 1,280 multiplies), types
checked, defaults for unconnected pins — and it goes through the same build
and reload as a hand-written one. File > "Open graph as code" hands the
generated file to the code pane for anything the nodes cannot reach.

What the library reached by rebuilding twenty of the cube_fx effects as
graphs (`examples/build_examples.py` writes them; `--check` compiles, builds
and runs them; a new project starts with them in `graphs/`):

- **State between frames.** A node definition may name floats it keeps
  (`state`), held in `SEGENV.data`; `$st.name`, `$first`. Integrate (a
  running phase), Envelope (attack/release smoothing), Random hold (a random
  that re-rolls on a trigger - re-aim on the beat), Rising edge, Spectrum
  (the 16 bins, smoothed, read at an index - a spectrum along a coordinate).
  A frame-scope node fed a per-pixel value follows it down to per pixel; a
  stateful one refuses, with a message.
- **Fields.** A number per pixel kept between frames, double-buffered, up to
  two per graph: Field (read last frame's value at any u, v) and Field
  write. Cellular effects - fire, ripples, ageing - keep their simulation
  here instead of bending it through the palette.
- **Cube coordinates.** Position (the -1..1 box), Cube face (which face, and
  a, b on it - tiles per face), Cube ring (the lid-and-walls ruler: around,
  depth) and Ring to uv (its inverse, so a feedback read can step along the
  ring). Previous at reads last frame's colour at any position.
- **Maths.** Floor, Modulo, Cosine, Log, Exp, Band (a soft band around
  every whole number), Dot 3, Rotate, Length, Direction to (a unit vector
  from two angles), Hash (a stable random per cell, column or tile).
- **Events and things.** Emitters (up to eight things dropped on a
  trigger - at a point or at random on the surface - each with a tag and an
  age) and Shells (spherical shells expanding from each through 3-D space:
  the ripple that crosses every fold). Torus knot (a (p, q) knot seen from
  the centre: hit, where along it, how near the rim, the tube's normal).
  Gravity (the IMU's when fitted, else down, tilted by two inputs), Position
  to uv (any point of the box back to the pixel that shows it), Cube face's
  outward normal, Loudest bin, Frame count (first frame, count).
- **Loops.** Delay is the one node a wire may loop back through: its
  output is last frame's input, written after every other frame-scope node
  has run, so a value can depend on its own past (a cycle that restarts
  only when it is over). Any other loop is refused with a message.
- **Simulations in a chart.** Reaction diffusion (Gray-Scott chemistry on
  a 48 x 24 grid, stepped each frame, read at u, v - tendrils with
  history), Bifurcation (the fig tree of x -> x^2 + c as an orbit density
  over a c window and an x window), Spring (a damped oscillator kicked by
  the beat - slosh, bounce), Bitmap (pixel art as rows of digits, read at
  u, v) and Colour pick (its palette).
- **Images.** Image bakes a picture file into the effect at compile time
  - resized to the node's size, quantised to its number of colours, stored
  as an index table and a palette in the generated C++, so the device needs
  no files; a "..." button picks the file, relative to the project. Its
  menu offers "convert to Bitmap + Colour pick": the picture as rows of
  digits (edited as lines on the node) and its palette as eight colours,
  wired the same, so it can be drawn on. Node definitions may name a
  `codegen` function for C++ that a template cannot hold.
- **The heavy ones.** Mirror fold (a direction reflected into one
  fundamental domain of a finite mirror group - dihedral, tetrahedral,
  octahedral, icosahedral - so a picture is mirrored 6 to 120 times),
  Mandelbrot (escape time, or a Julia set), Drain (watershed drainage on
  the pixel grid over two fields: the water flowing into a pixel from the
  neighbours that drain to it).

The five: **Slab Cut** (Cube Slice - spectrum slabs through the solid at a
tumbling normal), **Cell Weave** (Cube Cell - nested sines over the position,
one axis per band, the fold drawing the walls), **Truchet Cube** (tiles per
face, arcs turned by a hash the beat re-rolls), **Ring Rain** (Matrix Rain
on the ring with no drop state - a hash per column), **Box Fire** (Cube Fire
- a heat field rising up the walls into the lid); then **Maelstrom** (the
log spiral, with the unwind when the kicks stop), **Kaleidoscope** (spin,
fold, cut by drifting planes), **Mandelbrot** (stereographic from the
bottom pole, a breathing zoom at a boundary point), **Watershed** (height
and water fields, Drain, erosion, storms on the beat) and **Moire** (funnel,
warp, two lattices); then **Cube Ripples** (Emitters on the beat, Shells
through the solid, a fading wake), **Cube Chladni** (the nodal surface of a
3-D standing wave, its three mode numbers following three bands),
**Candy Knot** (Torus knot, tumbling, striped, glossy, seamed), **Gyro
Sand** (a falling-sand automaton on a Field, gravity taken along the
surface, grains conserved by having both cells agree) and **Breakout**
(the ball two triangle waves, a paddle that follows it, bricks a Field it
clears - the ball does not bounce off them); then **Cube Axes** (position
as colour - the calibration effect), **Liquid Tunnel** (ln r down the
stereographic radius, a Gray-Scott medium in that chart, a dihedral fold,
a fake-normal light and a Fresnel rim), **Question Block** (the sprites on
every face; beat, bump, a decelerating reel into three items, a hold - the
cycle gated on idle through a Delay), **Feigenbaum** (the bifurcation
density on the stereographic plane, both windows shrinking toward the
Myrberg-Feigenbaum point at delta and alpha) and **Liquid** (a plane through
the solid on two Springs the beat kicks; wet below, a meniscus, ripples,
the lid a pool). Readings of the originals in nodes, not ports; the ones
that were particle systems are shader-style.

Every node, pin and setting carries a plain-words description
(`native/nodedocs.py`, merged into the library): hover a node's title or a
pin and it appears under the toolbar; a node's or pin's right-click menu
shows it too, and the add menu's search matches it. `python
native/nodedocs.py` writes the whole reference as `NODES.md` - and refuses,
naming them, while any node or pin is undocumented; the examples' `--check`
refuses the same way. A new node is not finished until both pass.

Sub-graphs: select some nodes and fold them (the toolbar, Edit > "Fold into
sub-graph", or the node's right-click menu) and they become one node. Each wire that crossed the
boundary becomes a pin — a "Graph input" node inside for every incoming one,
a "Graph output" for every outgoing — named after the pin it fed, and the
parent is rewired through the new node. The sub-graph is a file in
`<project>/subgraphs/`, appears under "subgraphs" in the add menus, and can
be dropped into any graph as many times as wanted. "Edit sub-graph" opens it
in place with a back button; a Graph input's name, type and default are edited
on the node, and a stale wire in a parent is dropped when it next opens. A
sub-graph previews on its own: its first colour output stands in for Output.
Compiling inlines the sub-graph wherever it is used — no call, no cost.

Live preview: the bolt on the toolbar (Playback > Live) rebuilds after
every edit — a wire, a value on a pin, a param, a new node — once the edits
pause for half a second. The build runs on the worker while the 3-D view
keeps showing the previous one, and the hot swap keeps the sliders, palette
and colours, so the effect changes under the cursor a second or two later.

### Phase 3 — wiring and export

The ledmap. For a matrix WLED's own settings suffice; for the shapes it is a
wiring model — per-face order for a cube, rings for a cylinder, a spiral for a
sphere — with the imported XYZ case taking its order from the file. Export
writes `ledmap.json` and a usermod folder ready to drop into `usermods/`.

### Phase 4 — the scripted runtime (done)

A small interpreter in the cube_fx usermod (the Studio Script effect) runs a
program the studio compiled from a graph, sent to the device as a file over
the network - no firmware build. See the roadmap entry for what it is and
what it cannot express.

## Features remaining

Measured against ComfyUI and Blender's node editor, and an ordinary code
editor. Ticked when done; the order within a group is the order to do them.

### Node editor

- [x] **Undo / redo.** Every mutation pushes a JSON snapshot; Ctrl+Z /
      Ctrl+Y, also in the right-click menu. Drags of one slider or keystrokes
      in one box within a second share a step. History is per open graph.
- [x] **Copy / cut / paste** (Ctrl+C/X/V; "paste here" in the right-click
      menu, copy/cut in a node's). The clipboard is graph JSON held on the
      app, so it works across graphs and into sub-graphs.
- [x] **Search in the add menu** — a box at the top of the right-click menu,
      focused as it opens; matches on name or description, Enter adds the
      first hit, Escape closes.
- [x] **Drop a wire on empty space → add a node** wired to it: the menu
      offers what that output can feed, most useful first, and the chosen
      node lands where the wire was dropped.
- [x] **Insert on wire**: right-click a connected input → "insert on the
      wire" lists what fits between the two ends and splices it in. (Dropping
      a dragged node onto a wire is not possible: the node editor cannot say
      which wire is under the pointer.)
- [x] **Reroute knots**: Knot and Knot colour, narrow pass-through nodes the
      compiler folds away; also offered first by "insert on the wire".
- [x] **Frames** and **notes**: a Frame is a titled, tinted box with a size
      on the node; nodes whose corner is inside move with it. A Note is a
      multi-line text. Neither is compiled.
- [x] **Collapse a node** to its pins (node menu); **node colour** swatches
      in the node menu, ten colours, same set as the wires.
- [x] **Pin preview**: an output pin's menu → "preview this output" builds
      the graph with that pin shown instead of the Output (a colour straight,
      a float or bool as a grey level, 0..1) as a draft named Preview; every
      compile shows the pin until "stop previewing".
- [x] **Validation on the node**: a red outline for what stops the compile
      (a cycle, more than one Output, a missing sub-graph), amber for an
      output that feeds nothing; the message is in the node's menu and the
      status line. Every input has a default, so none is "required".
- [x] **Keyboard**: arrows nudge the selection 10 px (Shift: 1 px); Home
      brings the graph's top-left to the origin. Ctrl+A and true panning are
      not possible: the node editor exposes neither.
- [x] **Zoom** — 50% to 200% in nine steps: the wheel over the editor
      (about the cursor), Ctrl+= / Ctrl+- / Ctrl+0. DearPyGui's node editor
      cannot zoom, so the panel does: every size it lays nodes out with is
      scaled, the editor gets a font and style theme to match (a monospace
      TTF from the system: Consolas, Menlo, DejaVu Sans Mono), and positions
      are scaled on the way in and out so the saved graph never changes.
      The editor's own panning cannot be set from code, only watched, so
      the picture is shifted instead to keep the point under the cursor
      still. Remembered across runs. A custom canvas is no longer needed
      for this; it remains the route to wire styling and thumbnails.
- [x] **Resizable panes**: a splitter between every pair of neighbouring
      panes; drag them, remembered across runs in `projects/studio.json`
      (per layout mode for the columns, since the graph wants more room
      than the net).
- [x] **Movable panes**: the three slots - the main pane (net, code or
      graph, whichever the layout mode shows), the 3-D view and the panel
      - sit in columns of rows (`App.arrangement`). Drag a pane by the
      `:::` at its top right onto another: near an edge it snaps beside or
      above that pane, in the middle the two swap; the target lights up
      as you go. View > Layout has six presets; the arrangement is
      remembered.
- [x] **Every menu item checked** (`tests/walk_menus.py`): the walker
      hooks call each item of the menu bar, each row of a node's, an
      input's and an output's context menu (the graph put back after each)
      and each pane menu row, and read the log for failures - 335 rows,
      none failing. It found two: Node > Stop pin preview called a method
      that did not exist, and Select > Invert / linked assumed a graph was
      open. Skipped on purpose: Quit, the 15 s recording, fullscreen, and
      the items that hand a path to the desktop.
- [x] **Menus regrouped**: Edit is undo, the clipboard, Delete (delete /
      delete and reconnect / disconnect) and Select as submenus, the
      palette, the code editor's two; Node is add, the node-shape actions,
      Show, Arrange (with align and distribute) and Sub-graph as submenus;
      View gathers Zoom. A node's context menu keeps the most-used rows on
      top and folds the rest in place (delete, colour, settings as pins,
      promote, more); a pin's menu folds the wire, insert-on-the-wire and
      drive-with lists. Hovering a node in the add menu describes it in
      the properties pane (`describe_type`), so it can be judged before
      it is added.
- [x] **A theme editor** (Settings > Appearance): four presets - dark,
      light, soft light (the light one dimmed for eyes that found it too
      bright), slate - and the seven colours a theme is made of
      (background, panels, controls, lines, text, dim text, accent), each
      a swatch that applies as it changes; "Back to the preset" drops the
      changes. `THEME_PRESETS` / `THEME_ROLES` / `theme_colors()` in app.py;
      light or dark is decided by the background's brightness, which is
      what sets which way controls lift.
- [x] **A properties pane** (the fourth slot, "props"; N hides it, View
      > Properties pane): a node's settings too long for the node - bitmap
      rows, expressions, files - are edited in a pane of their own, shown
      in the graph layout, movable and resizable like the others. It
      replaces the panel that grew above the editor on selection and
      shrank on deselection, which moved the graph under the pointer
      every time. Arrangements saved before it get it under the 3-D view.
- [x] **Panel sections fold and move** (`Section`, `App.sec_*`): every
      section of the side panel has an arrow, a title that folds it and a
      grip that drags it above or below another; order and folded state
      are remembered. A section header's right-click menu expands,
      collapses or restores them all.
- [x] **Pop-out views** (`native/popout.py`): the net or the 3-D view in
      a window of its own, for a second monitor (View > Pop out, or the
      pane's right-click menu). Dear PyGui has one viewport a process, so
      the pop-out is a second process reading a shared-memory block the
      app writes every frame - the net at LED resolution, the geometry -
      and drawing the cube itself (GPU quads, or the point cloud), as
      sharp as its window is big, with its own orbit and zoom. Closing the
      window gives the pane back; the window remembers where it was.

### Code editor

- [x] **Open in external editor** — VS Code if `code` is on the path (at
      the line, `-g`), else the system's .cpp association; `"editor"` in
      project.json overrides (a command with `{file}` and `{line}`). The pane
      reloads when the file is saved outside, and "watch" rebuilds too.
- [x] **Click an error to jump to its line** — the external editor opens at
      it, and the line's text shows in the status. The in-app box cannot move
      its own cursor, which is the limit of DearPyGui's text input.
- [x] **Find / replace** — find lists matching lines (click → line);
      replace all.
- [x] **API reference** under the code: `SEGMENT.*`, time, pixels, colour,
      noise, state, audio, cube helpers, metadata; a click copies the snippet
      (the box cannot take an insertion), Ctrl+V pastes it at the cursor.
- [x] A real editor widget in-app (drawlist-based): see the roadmap's
      "in-app code editor".

### Project and workflow

- [x] **Multiple projects**: a project picker at the top of the side panel
      lists `projects/`; File > Project makes a new one by name, opens one
      by name or picks any folder. The
      last project opened is remembered (`projects/studio.json`) and opens
      next time. Switching applies the project's geometry, effects list and
      graphs and rebuilds the engine for its list.
- [x] **Palette source node**: the colours the palette-source setting names
      (what the audio-reactive palettes draw from), at an index. One small
      firmware addition, `cfxPaletteSourceColor()` in cube_fx_palettes.cpp,
      declared weak by the generated code with the segment's palette as the
      fallback, so the effect builds without that usermod. The audio-reactive
      palettes themselves are ordinary palettes: pick one on the Palette node.
- [x] **Effect metadata in the UI**. Graphs: each control node carries its
      default beside its label, and an "Effect settings" node (one per graph)
      sets the default palette, 1-D / 2-D / both, the audio flag and the
      colour-slot labels; the compiler writes the whole string. Code: a
      Metadata form under the code pane reads the string out of the file by
      field and writes it back.
- [x] **Graph import / export**: File > "Export graph bundle" writes
      `export/<graph>.graph.json` with every sub-graph it reaches and any
      user nodes it uses; "Import graph bundle" (file dialog) unpacks one
      into the project, keeping existing sub-graphs of the same name.
- [x] **Export as a deliverable**: `export/` holds `ledmap.json`, a
      `usermod_studio/` folder that builds on its own (effects, the two
      headers, the bank's .cpp, a library.json, a README with the build
      steps), and `studio_export.zip` of the lot (File > Project > Export
      usermod). **Send ledmap** uploads ledmap.json to a device over
      `/upload`, to the address set under File > Project > Device
      (remembered per project).
- [x] **Record GIF** works in every layout (the toolbar, or File);
      **screenshot** saves the 3-D view to `export/shots/`. MP4 is not
      offered: it would need ffmpeg on the path for no gain over the GIF.
- [x] **Menus and a toolbar** (`native/chrome.py`). File / Edit / View /
      Node / Playback / Settings / Help, every action with its shortcut
      beside it, as any editor has them; a toolbar of icons for the ones
      used all day (new, open, save; build, live; undo, redo; play, step,
      restart; the five views; zoom; add, delete, arrange, fold; external
      editor, screenshot, GIF). The icons are drawn in code
      (`native/icons.py`: strokes on a unit square, rasterised at 4x) so
      they match the theme on every platform without an icon font. The
      panes keep only what names the thing in them - which file, the
      status line, find / replace under the code - and names are asked for
      in a small dialog instead of a box on the pane. Presentation mode
      (H) hides the menus and toolbar with the rest.
- [x] **A flat dark look with a few pops of colour.** Slabs on a panel, no
      bevels or bright borders, the accent blue wherever something is on
      (the active view, a checked box, a slider's grab), amber for live and
      for a build in progress, green play, a red record dot, section titles
      in the side panel in the accent. Selection is a turning angular
      gradient frame (`native/glow.py`: one conic texture, four strips
      whose texture coordinates rotate, plus a fainter glow outside) around
      the pane last clicked in and around every selected node, clipped to
      the editor. The views sit centred in their panes. Settings > Selection
      frames picks each frame's gradient - the studio's own, any WLED
      palette (mirrored, so it is seamless round the frame), or one made in
      the gradient creator there: stops with a position and a colour,
      started from any of those, mirrored or cyclic, saved by name in
      `studio.json`.
- [x] **A keymap** (`native/keys.py`): every keyboard action with a default
      key and a context (anywhere / the graph), rebound under Settings >
      Keyboard shortcuts - click the key, press the new one; a key taken
      from another action leaves that one unbound; the changes alone are
      kept in `studio.json`. Menu items and toolbar tooltips show the
      current key. Added on the way: `.` step, `Ctrl+R` restart, `[` `]`
      previous / next effect, `Shift+[` `]` palette, `L` live, `Ctrl+O`
      the open list, `Ctrl+I` add to / remove from the list, `Ctrl+E`
      external editor, `F12` screenshot, `Ctrl+F12` GIF, `F1` shortcuts,
      `Ctrl+Shift+H` the side panel; in the graph `Shift+A` add node, `K`
      collapse, `Ctrl+G` fold, `Tab` enter / leave a sub-graph, `Escape`
      stop the pin preview.

### Against Blender's node editors

Measured against Blender's shader, geometry and compositor nodes. The order
within each group is the order to do them.

**Types and maths**

- [x] **Vector socket type** — three floats on one wire (purple). Position,
      Direction, Cube face, Gravity and Direction to give one beside their
      parts; Dot 3, Length, Mirror fold, Torus knot, Shells, Emitters and
      Position to uv take one. Float into vector fills all three, vector
      into float is x, colour and vector convert as r, g, b. Vector / Vector
      split join and take apart. Graphs saved before are migrated on load.
- [x] **Vector math** (add, subtract, multiply, scale, normalize, cross, dot,
      distance, length, reflect, project, min, max, abs, fract, floor) and
      **Vector rotate** about any axis.
- [x] **Math** — one node, every arithmetic op in a dropdown: the eight we
      had plus sqrt, sign, round, ceil, snap, ping-pong, wrap, compare,
      smooth min/max, the trig set in turns, log, exp.
- [x] **Map range** with the ranges on pins, five easings and steps (Remap
      stays as the small linear one).
- [x] **Float Curve** - points drawn on the node (a plot, a row per point,
      add / remove), smoothstep between them, baked into the C++ as a table.

**Generators**

- [x] **Voronoi** (distance, edge, cell id, the cell's point) on a vector
      position - seamless from Position.
- [x] **Noise** gains octaves and roughness (fBm); one octave is the old node.
- [x] **Checker, Gradient (linear / quadratic / radial / spherical /
      diagonal), Brick**; distortion on Wave. Magic is Noise into Wave's
      distort.

**Colour**

- [x] **Colour ramp** — stops drawn on the node (a strip, a row per stop,
      add / remove), linear / constant / ease; baked into the C++ as a table.
- [x] **Adjust** (hue shift, saturation, value, contrast, gamma, invert).
- [x] **Blend modes**: overlay, difference, soft light, hue, saturation,
      colour, luminosity. **Blackbody**.
- [x] **Layers** — a base and four layers, a mode and an amount each.

**Simulation and time**

- [x] Four **Fields** per graph.
- [x] **Blur / Glow** (radius 1-3 over last frame's picture; Glow adds the
      blur), **Transform** (move / turn / zoom u, v about a pivot).
- [x] **Ease** (glides to its target over N seconds) and **Sequencer** (up
      to four timed phases, triggered or looping: phase, progress, since).
- [x] **Statistics** (min / max / mean of a field over every pixel).
- [x] **Particles** (up to 48: rate and bursts, velocity and spread,
      gravity, drag, life, tag, kept on the surface, die / bounce / wrap at
      the bottom) and **Sprites** (soft / hard / spark dots per pixel, with
      the nearest one's tag, age and speed). Example: Fireworks.
- [x] **Path** (points typed on the node, open or closed: distance to it,
      position along it, the nearest point).

**Editor**

- [x] **Mute** a node (its first input passes to its first output).
- [x] **Duplicate with links** (Shift+D).
- [x] **Arrange** (a layered layout by depth) — worth more here than in
      Blender, our nodes are wide.
- [x] **Hide unwired pins** on a node.
- [ ] **Live values** on frame-scope pins (sliders, audio, Integrate) when
      hovered - deferred: pin preview covers it for one pin at a time.
- [x] Wire-drag from an *input* to an empty spot (the menu lists what could
      feed it); Alt-click to detach a node from its wires; F to connect two
      selected nodes.
- [x] A **properties side panel** for the long params (Bitmap rows,
      Expression, Image file).
- [ ] Preview thumbnails on nodes - deferred: — the compile-to-C++ model does not give
      continuous per-node taps cheaply; the realistic version is a small
      image on the node being pin-previewed.

### Against Blender, second pass (September 2026)

The first list done, measured again - against the shader, geometry and
compositor editors plus Node Wrangler. Ranked by value over effort; the
order is the order they were done.

- [x] **Select all / none / invert** (A, Alt+A, Ctrl+Shift+I). imnodes owns
      the click selection and cannot be told to select, so nodes selected
      by key are a second list (`ext_sel`): they wear an accent outline,
      every selection-taking action reads the union, and dragging a
      clicked node carries them along (`_poll_ext_sel`).
- [x] **Frame selected** (Shift+Home): the graph shifted so the selection's
      box starts at the top left, the zoom the largest step it fits at.
- [x] **Select upstream / downstream / linked** (Ctrl+[, Ctrl+], Shift+L):
      the whole chain, not just the neighbours.
- [x] **Grid snapping** (Shift+Tab toggles; Ctrl while dragging does the
      other thing): nodes land on the 20-unit grid when let go.
- [x] **Delete with reconnect** (Ctrl+Delete): what fed the node's first
      wired input feeds whatever its outputs fed, where the types allow.
- [x] **Drop a node onto a wire** to splice it in: while one node is
      dragged and the POINTER (not the node's body - a node carried across
      a wire must not catch on it) is on a wire it could sit on, that wire
      fades and the wiring it would become is drawn - source to the node's
      input, its output on to the old end (`_poll_splice`, two curves on
      the overlay); let go there and it is done, the node downstream
      pushed right if the two now overlap.
- [x] **Swap inputs** (Alt+S): a node's first two, wires and typed values.
- [x] **Node labels** (Shift+F2, or the node's menu): a name of your own
      over the type; `label` on the node.
- [x] **Frame the selection** (Ctrl+J): a Frame sized round it. (Alt+P
      detach has no meaning here - a Frame holds what lies inside it.)
- [x] **Multi-edit**: Alt while changing a value puts it on every selected
      node of that type.
- [x] **Backspace over a value** resets it to its default; **Ctrl+wheel**
      over a dropdown steps it.
- [x] **Knife** (Ctrl+right-drag): the line drawn cuts every wire it crosses.
- [x] **A wire dropped on a node's body** lands on its first free pin that fits.
- [x] **Favourites and recents** at the top of the add menu (a node's
      menu stars it; the last six added are listed).
- [x] **Command palette** (Ctrl+P): every action by name with its key,
      Enter runs the first hit; graph actions listed while the graph is up.
- [x] **Undo history** (Ctrl+Alt+Z, Edit menu): the edits newest first,
      click one to go back to before it. Each snapshot is named after the
      method that took it.
- [x] **Ctrl+Shift+click** previews a node's output; again, the next one.
- [x] **Repeat last** (Shift+R).
- [x] **Zoom out to 10%**, and past a setting (Settings > Simplified
      nodes below: 70 / 50 / 40 / 30% / never; 50% by default) every node
      is a stand-in - its title over one row per wired pin, nothing to
      edit - with the footprint its full self would have at that zoom
      (arrange's height estimate), so the graph's spacing survives
      zooming out; for finding your way round a big graph
      (`GraphPanel.overview`, `_make_standin`, `_standin_rows`).
- [ ] Numeric expressions in fields ("2*pi") - deferred: the number boxes
      are Dear PyGui's and parse their own text.
- Not applicable: per-node timings (one compiled function, no per-node
  clock - the effect-ms readout is the honest equivalent), the
  spreadsheet (the pin preview and live value), simulation zones and
  baking (Fields, Sequencer, Particles), multiple editor areas (the
  movable panes and pop-outs).

### Alongside

- Cross-platform audio (done): WASAPI loopback on Windows, and any input
  device anywhere through sounddevice — a PulseAudio / PipeWire "Monitor of"
  on Linux, BlackHole on macOS, a microphone anywhere. The source picker is
  in the Audio section.
- True PCM into audioreactive: a ninth `u_data` slot fed from the FFT batch,
  double-buffered, with the effects falling back to the rebuilt waveform when
  the slot is absent. The one firmware-side change on the near horizon; small
  and self-contained by design.

## Roadmap

What is still missing, measured against a finished tool. In the order to do
them within each group; ticked when done.

### Getting effects onto the cube

- [x] **Flash from the studio** (`native/flash.py`; File > Project, the
      toolbar's plane, Ctrl+Shift+U). The export is staged into the WLED
      tree as `usermods/usermod_studio` (gitignored; beside cube_fx the
      bank's own usermod is left out, the effects register through
      cube_fx's and take bank slots), a generated `[env:studio_<base>]` is
      written into `platformio_override.ini` extending the chosen env with
      its usermods plus ours (its libraries seeded from the base env's, so
      the first build needs no registry), PlatformIO runs on a worker with
      its output in the dialog, and the binary goes to the device's
      `/update` as the web UI's update page sends it. Build and send are
      each a checkbox; Cancel stops the compiler; the env and address are
      remembered per project. **Effects to ship** is a checklist of the
      list, each with its flash cost measured from the last build's object
      files, and a budget line for the chosen env - about N KB of the
      partition, or how many to untick - so a plain ESP32 (1.5 MB app
      partition) can be fitted by choice rather than by trial. A build
      that does not fit says in plain words whether unticking would help
      or whether the environment's own firmware is already past the
      partition (esp32dev_customfx with cube_fx and audioreactive is: no
      selection fits, the S3 does).
- [x] **Push the current effect's settings** (File > Project, Ctrl+Shift+P):
      the effect and palette found by name in the device's own lists, the
      five sliders, the three checkboxes and the three colours to the first
      segment over `/json/state`.

### Working with graphs

- [x] **Undo for code edits**: edits within a second share a step, as the
      graph's do; Ctrl+Z / Ctrl+Y, the menu and the toolbar act on whichever
      pane is up (the box keeps its own undo while it has the keyboard).
- [x] **Expose a setting as a pin**: a node's right-click menu lists its
      numbers, switches and colours; one becomes an input pin with the value
      it had as the default, wired or not, and goes back the same way. The
      compiler rewrites the node's template for it (`exposed_def`).
- [x] **Where used**: a node's right-click menu and the Node menu list every
      graph and sub-graph with that type, with counts; a click opens it.
- [x] **Node presets**: a node's right-click menu saves it as it is set
      up, by name (`studio.json`, so they follow you across projects); the
      add menu lists them under "presets" and the search finds them.
- [x] **Version history** (`native/history.py`): every save of a graph, a
      sub-graph or a code effect first keeps what the file held, the newest
      40 per file under `<project>/history/`; File > History lists them
      with a restore, which keeps the current one first.
- [x] **Focus mode** (View, `/`): everything but the selection and what it
      is wired to goes dim - themes rebound on a selection change, nothing
      rebuilt.
- [x] **Wire labels**: an input pin's right-click menu labels its wire; the
      text is drawn at the wire's middle, kept in the link's meta beside
      its colour.

### Preview and testing

- [x] **A/B compare** (Playback, Ctrl+Shift+B): a second engine from a copy
      of the library (one process gets one instance per file), fed A's
      geometry, colours and audio each frame, the two renders side by side
      in the 3-D pane under a shared camera; it follows a rebuild.
- [x] **Slider sweep** (Playback, Ctrl+Shift+W): a slider goes 0 to full and
      back over N seconds, looping or once, optionally recorded as the GIF;
      the slider's own widgets follow.
- [x] **Audio file input**: "play a WAV file" in the Audio section runs a
      WAV through the same analyser as the live sources, at real time and
      looping (`audio.FileAudio`).
- [x] **Timeline scrub**: the last 300 net frames are kept while playing;
      paused, a slider above the parameters shows any of them in both
      views (the cube's face renderer; the point cloud still shows the
      live pixels).
- [x] **Per-effect cost on the device**: the engine's ms/frame on this PC,
      smoothed, and a device fps from it by a factor (60 by default,
      Settings > Device speed factor) - an estimate, labelled as one, until
      a device measurement calibrates the factor.

### Geometry

- [x] **Six-faced cubes**: the geometry section's "six faces: the bottom
      lit too" puts the BOTTOM face in the net's (2,2) corner block - the
      net stays 3B x 3B, so cube detection and every buffer keep their
      shape; that block just stops being a gap. In the firmware the flag is
      `cfx_sixFaces` (cube_fx_common.h: `cfx_gap()`, `cfx_gapBlock()`,
      `cfx_faces()`; the net-skip macros and `cfx_cidx` follow it, so the
      graph's generated code and the Script effect light the bottom for
      free), set by `-D CFX_SIX_FACES=1` - the studio adds it to the flash
      env for a six-faced project - or by the CubeFXBank usermod's
      `six_faces` setting, which "Send the current effect's settings" also
      pushes. The sim has `simSixFaces`; the renderers draw the sixth face
      (seen from below); the wiring takes `B` as a face letter. Effects
      that hand-build the four walls as a band or walk cells across folds
      (Tron, Matrix Rain, Breakout, DNA Helix, Whirlpool, Cube Fire, Split
      GEQ) leave the bottom dark; everything reading `cfx_pos` lights it.
- [x] **Ledmap import** (File > Project): from the device (`/ledmap.json`,
      which the firmware serves from its filesystem) or a file - a matrix
      with its gaps and wiring, or a strip. **The exported ledmap was the
      wrong way round**: it listed logical indices in wiring order, where
      the firmware (`deserializeMap`) reads one entry per logical position
      giving the physical LED, -1 for a gap - 2304 entries for a 48x48
      cube, 1280 of them LEDs. Export and Send now write that, with width
      and height; an imported map keeps the device's own LED numbering.
- [x] **A wiring editor** for the cube, in Geometry: the faces in wiring
      order, quarter turns per face, and WLED's panel options (serpentine,
      vertical, start corner) - what the exported ledmap says. "Show the
      wiring on the net" draws the path through the pixels, first LED
      amber, last red. Dragging single pixels is not offered: a cube is
      wired by the panel, and the per-face settings cover that.
- [x] **Multiple segments** (up to eight). The shim hosts a `Segment` per
      segment with its own pixel buffer, effect, sliders, palette, colours,
      state and 1-D mapping; each runs as THE segment (the shim's width and
      height are its size for the duration), then the buffers are
      composited into the strip in order, later over earlier, faded by
      opacity - and by its **blend mode**: the sim's compositor is a
      transcription of the firmware's `blendSegment()` (all seventeen: top,
      bottom, add, subtract, difference, average, multiply, divide,
      lighten, darken, screen, overlay, hard light, soft light, dodge,
      burn, stencil), combined with opacity exactly as it does, and the
      mode is pushed to the device as `bm` with the settings. The
      single-segment API means the current one; `simSeg*`
      add, bound, select and drop them. The side panel's SEGMENTS section
      lists them (+ / -, bounds, opacity); the effect, sliders, palette and
      colours above it are the current segment's; the net draws every
      segment's bounds with the current one in the accent. Saved with the
      project, restored on open, kept across a rebuild of the engine.

### Polish and workflow

- [x] **Recent projects** (File > Project > Recent, the last ten); the
      Open submenus list every graph and code effect.
- [x] **Autosave**: every 20 s, unsaved code or graph edits are kept as a
      version in the history (the file itself untouched), so a crash loses
      at most that; File > History restores it.
- [x] **Drag and drop** onto the window (`native/dropfiles.py`): on
      Windows the viewport's HWND gets DragAcceptFiles and a window
      procedure in front of Dear PyGui's that answers WM_DROPFILES; the
      loop takes the paths and sorts them - a graph or bundle opens, a
      .cpp becomes a code effect, an image an Image node (copied to
      assets/), an XYZ file or a ledmap the geometry, a WAV the audio.
      Elsewhere the hook does nothing and the imports on File remain.
- [x] **Context menus** on the two views and the code pane (screenshot,
      record, reset the camera, compare, full frame; the wiring; save,
      build, find, the external editor, history).
- [x] **Theme choice** (Settings > Appearance): dark or light, and the
      accent colour; the theme is rebuilt in place, the toolbar's icons
      follow.
- [x] **Tests** (`tests/test_graph.py`, plain functions - pytest or the
      loop at the bottom of this section): compile, frame-scope hoisting,
      the type rule, problems, exposed params, the state fallback, arrange,
      JSON round-trip with wire meta, the ledmap format.

### Lighter firmware: the feature picker

- [x] **Features** in the flash dialog (`flash.FEATURES`, `flash.AUDIO`):
      the IMU driver, the rotary encoder + OLED menu, per-effect slider
      memory, and the audio choice - audioreactive with the studio's PCM
      waveform, audioreactive as WLED ships it, or none. Each is a build
      flag the firmware defaults ON (`CFX_WITH_IMU`, `CFX_WITH_UI`,
      `CFX_WITH_PARAM_MEMORY`, `CFX_PCM`; the optional files are wrapped
      in `#if`), so a build outside the studio is unchanged; the studio's
      env passes =0 for what is unticked, and "no audio" drops
      audioreactive from the env. Under each the picker says what it
      brings and which nodes lean on it (`nodedefs.NEEDS`: Gravity on the
      IMU; Audio, FFT bin, Beat kick, Spectrum, Loudest bin on audio).
      With a feature off those nodes leave the add menu, a graph already
      using one wears the warning outline and its description says why -
      they still compile, each has a fallback (top-face-up gravity, WLED's
      simulated sound). A new project starts with no hardware ticked but
      audio; a project from before keeps everything, as it built.

- [x] **Usermod manager** (Settings > Usermods and features; the flash
      dialog's Usermods... button): the features above, then WLED's own
      usermods - the environment's and any the project adds - each on or
      off with a line about it; add one from this tree's usermods/ folder,
      import a folder or a zip into it, remove one from the list (the
      folder stays). Kept in the project's features as `usermods: {name:
      on}`; the staged env's custom_usermods is the base env's list with
      those changes on it (`flash.staged_usermods`).
- [x] **Dependencies travel with the work** (`flash.DEPENDENCIES`,
      `requirements_of_graph`, `requirements_of_code`). Exporting a graph
      bundle whose nodes need firmware that is not every WLED tree's (the
      IMU driver) asks whether to carry those usermod files in the bundle
      (`usermods` in the JSON; `requires` is always written); the usermod
      export asks the same for effects that call on it (the files land in
      the folder, the README gets a Needs section). Importing a bundle, or
      dropping a .cpp effect, checks its needs against the project's
      features and offers to turn them on - installing the bundled files
      where this tree lacks them (only under usermods/, never over a file
      that exists). Audio counts as standard: noted, never bundled.

### What xLights has that the studio should (September 2026)

xLights is a show sequencer and the studio is an effect tool for the
firmware, so half of it does not apply (a whole-house timeline, FPP
scheduling, video). These do, in the order to do them; ticked when done:

- [x] **Live output to the device over DDP** (`native/live_out.py`; the
      Send frame's LIVE row, Device > Stream the sim) - the sim's frames streamed
      to the device in real time (WLED's realtime protocol, UDP 4048, in
      physical order), so any effect - compiled, a graph, a script or not
      - shows on the real hardware before anything is built. With it a
      **wiring test** (xLights' Test tab): a chase along the wiring order,
      one LED by index, one part of a shape, with the same pattern shown
      in the sim - what a new ledmap or shape needs before it is trusted.
- [x] **Parts as the effects see them** (sub-models, strands; the table's
      flag bit 1, the Shape part node, the Shape frame's "One segment per
      part"): a part id
      per pixel in the position table, a **Shape part** node (the part's
      index, a mask for a chosen part, the position along it) and an
      option to give every part its own WLED segment, so each runs its
      own effect - xLights' per-strand render styles, the WLED way.
- [x] **Sequencing as WLED presets and playlists** (`native/sequence.py`,
      the Sequence frame under Playback and Device): a timeline of effects
      with durations and transitions, authored in the sim, exported as
      `presets.json` and a playlist and pushed to the device.
- [x] **Value curves**: the Float curve node's points drawn by hand in the
      properties pane (click to add, drag, right-click to remove; the
      node's own preview and the numbers follow), and the curve now runs
      as a script too (one select per segment, the same smoothstep as the
      C++). Sliders are keyframed per sequence step; a continuous
      slider curve along a step is not done.
- [x] **An effect library** (`native/library_ui.py`, File > Library): every
      graph of the project as a looping thumbnail (24 frames from a second
      engine, the same library copied as A/B does, so the one on screen is
      not disturbed), tags read off the graph (node categories, audio,
      motion, 3-D, dimensions, script), a search box, one click to open
      the graph and run its effect. **Generate previews** renders a turn
      of the 3-D view for every effect on the project's shape (its own
      settings, a second engine on a worker), a GIF and a PNG each in
      `export/library/` with a README index, and the tiles show the turns.
- [x] **A Text node** (a 5x7 font, scrolling, any 2-D layout) beside the
      picture nodes: only the letters used are baked in; `on` and `i`
      (which letter) out, `offset` in for scrolling, loop, size, row.
- [x] **Reference geometry** in the 3-D view: a `reference` part - a mesh
      imported as a wireframe (Import as a reference...), placed, turned
      and scaled like any part, never lit - the tree, the house, the
      enclosure - to place the LEDs against.
- [x] **Transition preview** (`native/transition.py`): a sequence step
      change with a transition time keeps the old step running in a second
      engine and blends the two pictures the device's way - fade, the
      swipes, the pushes, outside-in, inside-out, circular, fairy dust
      (the style chosen in the Sequence frame) - in every view and in the
      stream, until the time is up.

Not worth chasing: GLSL shaders (the graph is that), audio analysis
plugins, FPP scheduling, video playback.

**Second pass** (after the eight above), in the order to do them:

- [x] **A palette editor** (`native/palette_ui.py`, Edit > Palettes;
      `simCustomPalette` in the engine): a
      gradient drawn by hand - stops with a colour and a position - kept
      with the project, shown in the sim as a palette of its own, and sent
      to the device as a WLED custom palette (`/palette{n}.json`, ids 200
      down), so every effect there can use it.
- [x] **LED outputs** (`native/outputs.py`, `outputs_ui.py`; Device > LED
      outputs and power): a shape's wiring split into
      WLED busses - pin, count, LED type, colour order - per part or by
      count, pushed with the ledmap as the device's LED config; the whole
      new-build flow from model to device.
- [x] **Power** (per-model brightness limits; the same frame, and the
      footer): the current a frame would
      draw from the LEDs' mA rating, against the supply, in the footer;
      and WLED's auto-brightness limiter previewed in the sim.
- [x] **A schedule** (xSchedule; the Sequence frame's SCHEDULE rows):
      timed presets - this playlist at 18:00
      or sunset, off at 23:00 - authored in the Sequence frame and pushed
      as WLED's timers.
- [x] **Polish nodes** (per-layer settings): Levels (brightness, contrast,
      gamma) and Flip (mirror u, v, swap them); Sparkle and Blur were there.
- [x] **A States node** (faces): a set of bitmaps chosen by an index -
      mouths, eyes, expressions - switched from a beat or a slider.
- [x] **Randomise** (Playback > Randomise the settings): the sliders,
      the checks and the palette thrown, for exploring.
- [x] **xLights' effects as example graphs** (`examples/build_examples.py`,
      first eight): Meteors, Spirals, Pinwheel, Curtain, Marquee,
      Shockwave, Butterfly, Snowstorm. Writing them found two script
      compiler bugs: a declaration with two type words after `static`
      looped forever (`static or take()` skipped the take), and a hex
      literal's suffix strip ate its F digits (`0xFFFFu` -> `0x`).
      Still to do: Fan, Garlands, Lightning, Morph, Tendril.
- [x] **The 3-D view's surroundings** (View > Camera): a background
      picture (dimmed, behind the point cloud and the GPU cube alike),
      camera presets (isometric, front, back, left, right, top, below)
      and three saved views.
- [x] **Export a shape as `.xmodel`** (the Shape frame): any geometry on
      its grid - the shape's own, or one projected from the front at the
      LED pitch - as an xLights custom model, the wiring as the numbers.
- [x] **Beat alignment** (the Sequence frame's BEATS row): a bpm typed,
      tapped or taken from the synth, and every step's seconds snapped to
      whole bars of it.

### A self-contained app (on hold)

The goal: one download that runs, for any WLED user, not a checkout of
this repo with a compiler beside it. Today the studio is a source tree
inside the WLED checkout, run in place with hand-installed packages, and
the engine is compiled from the firmware's own sources by clang - which
is also what every graph build needs. In the order to do them, when the
housekeeping above is done:

- [ ] `pyproject.toml` + `requirements.txt` with pins, and `python -m
      native.doctor`: Python version, packages, the compiler, PlatformIO,
      and exactly what is missing.
- [ ] A prebuilt engine in releases (`cubefx.dll` for the commit), so a
      first run needs no compiler: viewing, the examples, the script
      preview and device pushes work at once; the compiler is needed only
      to build.
- [ ] A PyInstaller one-folder build (Windows first) - the app, its
      packages, the prebuilt engine - and the handful of firmware files
      the engine compiles copied in as a runtime folder, which is the step
      that cuts the dependency on the full WLED tree.
- [ ] A Linux / macOS pass: run it there, fix what falls over (font
      paths, viewport flags, audio device listing).
- [ ] Housekeeping first: the studio no longer assumes a cube anywhere a
      user reads - `studio/` (was `cube_sim/`), "WLED Effects Studio"; the
      firmware usermod stays `cube_fx` and its effect names keep the "Ace
      3-D" family prefix the on-cube menu filters on.

### Deferred from earlier lists

- [x] **Live values on pins**: the compiler puts a `GC_PROBE` after every
      number-like output - frame-scope ones as they are, per-pixel ones at
      the centre pixel - which the sim's `simProbeSet` records and the
      firmware compiles to nothing; hovering a pin shows `= value` in the
      help line while the effect on the cube is this graph's build (an
      unwired input shows its setting).
- [x] **Preview thumbnails on nodes**: the node whose pin is being
      previewed wears a small picture of the net - what the cube shows -
      refreshed every frame (nearest resampled, so the LEDs stay square).
      One node at a time, as the preview is; every node at once would need
      a field tap per node, which the compile-to-C++ model cannot give
      cheaply.
- [x] **An in-app code editor** (`native/codeedit.py`): lines drawn on a
      drawlist in Consolas with a gutter, C++ colouring (comments across
      lines, strings, numbers, keywords, preprocessor, MACROS), a cursor,
      selection by drag or Shift+arrows, click to place the cursor, wheel
      to scroll, Home/End/PageUp/PageDown, Enter keeping the indent,
      Ctrl+A/C/X, Ctrl+D duplicates the line, Ctrl+/ toggles a comment;
      paste and typed characters arrive through a one-line box kept
      focused behind the view (the one way Dear PyGui hands over
      characters). Error rows and find rows go to the line in it, marked;
      build errors tint their lines. The text still lives in the hidden
      "code" value, so undo, find, replace, metadata and history are as
      they were. The external editor remains for anyone who prefers it.
- [x] **The scripted runtime** (phase 4). `native/script.py` compiles a
      graph to bytecode: a compiler for the C subset the node templates
      use (expressions over floats, colours and 3-vectors, calls into a
      table of known helpers, if/else and ternaries lowered to selects,
      locals, statics as state, by-reference helpers), folding constant
      parameters so a node's choice chain becomes one branch. The **Studio
      Script** effect (`usermods/cube_fx/cube_fx_98_script.cpp`, in the
      bank) runs it: a float register file, colour registers, a state
      array kept between frames; a frame stream and a per-pixel stream; the
      VM fills the fixed registers (coordinates, time, sliders, checks,
      audio, the bands) and one switch runs the ops. On the device it
      reads `/studio.bin` and again whenever the file changes; in the sim
      the studio hands the program over in memory, so **Playback > Run the
      graph as a script** shows exactly what the device will run, and
      **File > Project > Send the graph to the device as a script** POSTs
      it to `/upload` and selects the effect there with the graph's own
      sliders and palette - no firmware build. `cube_fx_studio_helpers.h`
      is generated from the library's HELPERS so the VM has the same gc_*
      functions. 11 of the 22 examples are scriptable and match their C++
      builds pixel for pixel where deterministic (Random hold differs, as
      it must); the rest need per-pixel fields, state blocks, bitmaps or
      hand-written C++, and the studio names the node. The check runs
      every scriptable example in the VM. Compiled for the S3: +14 KB.
- [x] **True PCM into audioreactive**: a ninth `u_data` slot. In
      `audio_reactive.cpp` (one marked block) every FFT batch is folded 2:1
      to 256 int8 samples, scaled by the batch peak with a floor, into the
      half of a double buffer the readers are not on; `u_size` becomes 9.
      `cfx_pcm()` in cube_fx_common.h hands the current half over, or
      nullptr on a build without the block; Warp and Scope draw the real
      waveform from it and fall back to the rebuilt one. The sim carries
      the same slot: the synth makes a waveform from its bands the way the
      firmware's rebuild does (so the two move alike), a WAV or a capture
      gives its own samples. Compiled for the S3 (1.54 MB, no warnings).

## On the cube (18 September 2026)

Against the S3 cube at 192.168.1.17 (WLED 16.0.1, 48 x 48 net as five
WLED panels, a build from before the Studio Script rename and frame
budget): **Send the graph as a script** put the sine-wave tutorial graph
and then Maelstrom on the cube within a couple of seconds each, and WLED's
own live view (`tests/peek.py`, the web UI's Peek over the websocket)
showed the same pictures the sim's script preview drew. **Send the
current effect's settings** set sx / ix on the device's segment, read
back. The six-face setting is ignored by that build, as designed. The
device has no ledmap file (its wiring is WLED's panel layout), so the
ledmap import reports 404 and the export is not needed there.

The finding: the Script effect ran the sine graph at **7 fps** and
Maelstrom at 5 on the S3, against 43 fps for the compiled effects - the
bytecode VM was six to eight times slower than compiled code per pixel
(the sim showed the same ratio: 1.2 ms against 0.15).

### The script VM, made five times cheaper

Disassembling the sine graph's program said where the time went: 175 ops
a pixel, 78 of them CONST and 61 MUL, for a graph that does one sine.
The compiler was remaking the slider environment - `SEGMENT.speed` as
`sx * 255`, intensity, three customs, `strip.now` - for every node, into
that node's stream, twelve ops each, and giving every constant a fresh
register and a fresh CONST at every use. Now (`native/script.py`):

- **Constants once.** `Asm.const` keeps a table; a value is one register,
  set once a frame by a CONST in the frame stream, read from either
  stream (every op's destination is a fresh register, so nothing ever
  overwrites one).
- **The slider environment once**, in the frame stream, shared by every
  node.
- **Loop-invariant code motion** (`Asm.hoist`): a pixel-stream op whose
  inputs all hold for the frame - constants, sliders, time, frame-stream
  results - moves to the frame stream. A node's `speed / 255 * 4` runs
  once, not 2304 times.

- **Two peepholes**: a divide by a constant is a multiply by its
  reciprocal (a float divide is software on an ESP32, 250 ns), and
  `(int)(int)x` - the cast chains the templates write - is one TRUNC.

Programs are four to five times smaller (Moire 8982 -> 1592 bytes; its
pixel stream 930 -> 119 ops, Maelstrom's 293 -> 49).

Then the runtime (`cube_fx_98_script.cpp`), each step measured on the S3
with a program of forty copies of one op (`bench_ops.py` in the session's
scratch; the bank's info line reports the pixel loop's time):

- **The operand signature table** (`SS_SIG`, script.py's OPS letters):
  `ssParse` range-checks every register when a program arrives and decodes
  the streams into 16-bit words, so the run loop indexes the register files
  straight and reads each operand with one aligned load.
- **-O2 for the file**, with jump tables turned back on. The firmware
  builds with -Os and the ESP-IDF toolchain's `-fno-jump-tables`: GCC had
  made the VM's 67-way switch a tree of seven or eight taken branches per
  op and refused to inline gc_sat, fminf and the rest, so a MOV cost 40
  cycles (177 ns). A `#pragma GCC optimize("O2", "jump-tables")` above the
  includes (GCC will not inline across differing optimisation options)
  took that to 101 ns.
- **Threaded dispatch**: each op ends with a jump through a table of label
  addresses to the next op's code (GCC's and clang's labels-as-values; a
  switch remains for any other compiler, from the same body through the
  `OP` / `END_OP` macros) - no loop test, no bounds check, no jump back.
  MOV 68 ns, MUL 88, from 177 and 205.
- **A sine table**: 256 entries over a turn with a straight line between
  them, within a hundredth of a per cent of sinf; WLED's `sin_t` was 300
  ns an op, this is 160. Floor, ceil, fract, round and fmod are inline
  truncations instead of libm calls (FLOOR 283 -> 82 ns).
- **PAL reads a 256-entry table** made on the first PAL of each frame
  instead of calling `color_from_palette` per pixel; the polar and 3-D
  fixed registers (a root and an arc tangent a pixel) are only filled for
  a program that reads them; the loop is in IRAM.

What is left costs what the chip costs: a float divide 250 ns, a square
root 285, fmod 270, the hash 330 (three floorf), perlin 270.

On the cube, full resolution, from the earlier 7 and 5 fps: the sine
tutorial **39 fps**, Maelstrom **32** (its compiled build 43, WLED's
cap), Moire **25** (compiled 36), Truchet Cube **22**. In the sim the
Script effect runs at 1.1-1.8x the compiled effect's time, from 3.7-10x,
and the pictures are the same (mean difference 0 to 0.3/255 on the
examples that were exact before; the larger differences some show -
Truchet Cube 22/255, Candy Knot 14/255 - are `gc_rnd()` picking different
tiles, there before and expected).

Two things found on the way. **The frame budget** (a program over 40 ms
runs at half, then a quarter, of the width) coarsened on a single slow
frame - WiFi, or a program just loaded - and could not climb back, since
it climbed only below 12 ms: every script sat at half or quarter width and
looked streaky in the live view while reporting fine fps. It now takes
three slow frames in a row to coarsen, comes back when the next stride's
frame (about twice this one) would be under 30 ms, starts over at full
width with each new program, and says what it is doing on the info page
("Studio Script: full resolution, 18.2 ms a frame"). And **the bank**:
WLED saves a usermod's whole config block whenever any setting in it is
saved, so the studio's six-face push wrote CubeFXBank with every slot 0,
and the next boot placed no effect at all (255 modes became 220 - the
device had been running on its "not configured yet" default). An
all-empty bank is now treated as unconfigured: every effect registers,
as before the bank existed, and the info line says "none chosen - all 63
registered".

The flash path learned two things too: the first `/update` POST after a
while is closed by the device part-way through (the same POST ten seconds
later goes through), so it retries; and two builds of one tree share a
build id, so a reboot is recognised by the uptime starting over, not by
the id changing.

### Shapes: a position for every pixel, and an editor

Effects on the device knew where a pixel is only by rule: `cfx_pos()`
works a cube's face out from the net, and anything else is a flat
matrix. So the studio's cylinders and spheres, and the `xyz` point lists
it could already draw, gave every 3-D node the wrong answer on the device
(and in the engine). Now the shape travels with the effect:

- **The position table** (`cube_fx_00_geometry.cpp`, `/geometry.bin`):
  "STGM", version, cols, rows, flags, then int8 x y z per logical pixel in
  the -1..1 box, and with flag bit 0 the outward normals too. `cfx_pos()`
  answers from it when one is loaded for the segment's size; the graph
  prelude, the script VM's fixed registers and the compiled cube effects
  all go through `cfx_pos()`, so every one of them sees the shape.
  `cfx_geomNormal()` gives the direction (the table's, or from the
  centre). The device reads the file when it changes (from the bank
  usermod's loop, every two seconds); the sim is handed the same bytes by
  `Engine.set_geometry` (`simGeometry`). `Geometry.table()` makes it for
  every kind but a cube net, a matrix and a strip, which keep their rule
  (a matrix's effects live in the X-Y plane there, and a table would
  turn them on their side).
- **The `shape` geometry** (`native/shapes.py`): parts - strip, ring,
  panel, cylinder, sphere, cube, polyline, points - each with position,
  rotation, scale and a reverse flag, resolved to LEDs in wiring order;
  mirrors, arrays, a nearest-neighbour chain for loose points; a grid
  layout (from the front, a cell per pitch, collisions counted) or the
  grid an xLights model brings.
- **Readers** (`native/shape_io.py`): OBJ (v, vn, f, l), PLY (ascii and
  binary, vertex normals, faces, edges), STL (ascii and binary, corners
  merged) into a mesh; LEDs from it at the vertices, along the edges at
  a pitch (edges chained into runs so the wiring is a plausible strip
  path) or over the surface; xLights `.xmodel` custom models (rows `;`,
  columns `,`, layers `|`; the node numbers are the wiring, the grid is
  the layout); `x y z [i]` point lists.
- **The Shape frame** (`native/shape_ui.py`): one more dockable frame.
  Parts list and fields, imports, placing LEDs by clicking the 3-D view
  (`render.unproject` onto a chosen plane, through the same camera
  `render_points` draws with - which now centres the shape on its
  bounding box rather than the origin), dragging them, rings and a
  wiring line round the selected part on a viewport drawlist, undo, and
  shape files.

The table also carries the **parts** (flag bit 1: a part id and the
place along the part, 0..255, per pixel), read by `cfx_geomPartOf()` in
the graph prelude and as the script VM's `part`, `along` and `parts`
fixed registers - which uncovered that the VM's sixteen band registers
started at 36, on top of `SEGENV.call`'s; they start at 40 now. The
**Shape part** node gives a graph the part's number, the place along it,
the count and a mask for a chosen part; the Shape frame's **One segment
per part** makes each part (on the strip layout, where a part is a run of
LEDs) its own WLED segment with its own effect - xLights' per-strand
render, the WLED way.

**Overlays keep off what floats over them.** The wiring drawn on the
net, the shape editor's rings and wiring line and the reference
wireframes are viewport drawlists, which draw over every window - so
the wiring ran across the Library when it floated over the net. Every
one of them now keeps off `compute_holes()`, the same list the gradient
frames keep off (every window but the root, the file dialogs, the open
menus): the wiring line is broken under a window, a ring is left out
when its circle would touch one, a wireframe edge when either end is
covered; and the overlays are polled after the frames so the holes are
this frame's. The `wiring` test hook had been taken twice (the net's
overlay and the wiring test); the test is `wiring_test` now.

**A preview of the shape** (`native/shape_preview.py`): a turn of the
3-D view rendered off screen by a second engine - the effect the sim
runs, the parts each a colour, or a chase along the wiring on a dim
shape - looping in the Shape frame and written as `export/shape_preview.gif`
and `.png`; on a worker, so the window keeps drawing.

Two guards went in the same day: sending a ledmap or a shape asks first
(the device's wiring changes), and the menu walker skips every item that
reaches a real device - the walk had been sending the ledmap, the script
and the settings to the cube on every run.

### The Device menu and its frames

The device had been one free-text address per project, shared by four
menu items in two menus, and the flash environment was a combo that knew
nothing about the device - which is how this session began with the S3
being built for esp32dev. Now there is a **Device** menu and three
frames (`native/device_ui.py`, the network side in `native/devices.py`):

- **Devices**: the list, a scan, an address typed in. "Scan the network"
  does three things and takes the union: an mDNS query for
  `_wled._tcp.local` (a hand-written DNS reader; on Windows the system's
  resolver holds port 5353 and keeps the multicast answers, so it finds
  nothing there), every known device's `/json/nodes`, and a sweep of the
  /24 (`/json/info` to 254 addresses, sixty at a time, four seconds).
  Each find is probed for its chip, version, effect count and whether the
  Studio Script effect is there. The list is in the app's prefs; the
  active device is still the project's `device` option, so old projects
  keep theirs.
- **Send to device**: the active device, what it runs now (effect, fps,
  the Script effect's budget line - read on open and after each send),
  and the four sends.
- **Flash firmware**: the old dialog, sending to the active device, with
  the environment its chip suggests (`devices.env_for`: an S3 gets
  `esp32s3_customfx`) offered as a one-click fix when the combo says
  otherwise.

Each frame is a Dear PyGui window with the panes' header - title, dock
button, ::: grip - and three new OPTIONAL slots let the arrangement hold
them: "dock" puts a frame under the main pane, the grip dragged onto a
pane puts it beside or above that one (`move_slot` takes a floating slot
now: a drop in a pane's centre means below it, since a frame cannot take
a pane's place), "float" takes it out, and the arrangement is saved with
the rest. Docked, the window is placed and pinned by `relayout`; floating,
`device_ui.poll` keeps its grip at its top right as it is resized.

## Where the frame time goes

Measured (16 px cube, Maelstrom, 620 px view) before the GPU view: the
effect engine 0.13 ms a frame; the numpy cube render 28 ms; converting its
image to a float texture 6 ms; the net's whole-number upscale and texture 6
ms; a point cloud 14 ms. The engine is nothing - it has to run on an ESP32 -
so a GPU would buy the effects nothing; the display path was the cost, and
it was the display path that moved to the GPU:

- **The cube is textured quads** (`native/gpucube.py`): five faces, each
  8 x 8 `draw_image_quad`s sampling one net texture (the net at 4x, since
  the sampling is bilinear and the LEDs should stay square). The CPU
  projects 405 corners when the camera moves and uploads the net each
  frame; the warp is gone. Sub-quads are grown a third of a pixel so no
  crack opens between them. Settings > "Draw the cube on the GPU" turns it
  off; flat mode, point clouds and A/B keep the software renderer.
- **Texture conversion by lookup** (a 256-entry table) instead of a
  multiply over every channel.
- **vsync off**: Dear PyGui's vsync present blocked for a whole extra
  refresh (a windowed DX11 swap under the compositor), so every frame was
  two of them - 33 ms. Without it the compositor still paces at the refresh
  and nothing spins.

After: the cube layout 16 ms a frame (the 60 Hz ceiling), the graph layout
16, both views 24 (the net's 12x upscale and its 5 MB texture are what is
left; it stays crisp on purpose). The footer shows `effect` (the engine)
and `app` (the whole loop) in ms; the `measure` test hook prints the split.

## Polish pass (September 2026)

- Editor: find matches highlighted (the current one brighter), **F3** /
  **Shift+F3** next and previous, bracket matching, indent after `{` and
  a `}` stepping back out, Tab / Shift+Tab on a block, undo steps ending
  at a 0.6 s pause.
- Graph: **Arrange** works on a selection of two or more (anchored where
  they sit); Edit > Align (left, right, top, bottom, centres) and
  Distribute (across, down) on **Alt+arrows / Alt+H / Alt+V**.
- The net view scaled on the GPU (Settings, on by default): the "both"
  layout at the refresh rate too; the crisp CPU path remains a toggle.
- The Studio Script effect has a frame budget: over 40 ms a frame it runs
  at half, then a quarter, of the horizontal resolution and climbs back
  when frames fit - a heavy program cannot take the device down.
- `native/features.py`: segments, A/B, sweep, scripts, the device, the
  geometry extras and desktop drops moved out of app.py into a mixin.
- `tests/smoke_app.py` drives the app through fifteen steps and fails on
  a traceback. GUIDE.md is the short user guide.
- Sub-graphs take settings: inside one, a node's right-click menu
  promotes any of its settings to the sub-graph node outside (`promote`
  on the inner node; `sub_def` lists it, `flatten` applies it), so a
  reused sub-graph can differ per use without pins for everything.
- Movable panes and pop-out views (above, under Resizable panes): the
  panes sit where you put them, and a view can leave for another monitor.
- After an OTA the flash dialog reads `/json/info` before and after,
  waits for the device to come back, and reports its version and build
  id - and says so if the build did not change.

## Running it

```bash
cd studio
pip install dearpygui numpy pillow sounddevice        # pyaudiowpatch on Windows for loopback
python build.py --native-only                          # once; the app rebuilds incrementally
python -m native.app
```

Every action is on the menus with its shortcut; Settings > Keyboard
shortcuts (F1) lists them and lets you change any of them. Keys: **G** node graph, **C** code pane, **Q** logical view, **E** 3-D, **W** both,
(again returns to the panels), **H** hide the controls, **space** pause, **Ctrl+N / Ctrl+S / F2 / F5** new, save, rename, build. In the graph: **Delete** removes selected nodes,
**Ctrl+Z / Ctrl+Y** undo / redo, **Ctrl+C / X / V** copy, cut, paste, **wheel / Ctrl+= / Ctrl+- / Ctrl+0** zoom,
**M** mute, **Shift+D** duplicate with inputs, **Ctrl+L** arrange, **Ctrl+H** hide unwired pins, **F** connect two
selected nodes, **Alt+click** detach a node. Projects live in `studio/projects/<name>/`;
the default one is created on first run.

## Compatibility rules for this branch

- Firmware changes live in one clearly-marked block per file with a comment
  naming what depends on it, and everything that depends on it must work
  without it.
- The engine shim stays a transcription of WLED, not a reinterpretation. When
  it disagrees with the firmware, the firmware is right.
- Generated code uses only what a stock build has, plus `cube_fx_common.h` when
  a shape needs it, and says so at the top of the file.
