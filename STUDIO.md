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
- [x] **Zoom** — 10% to 200% in fourteen steps (50% to 200% at first): the wheel over the editor
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
- [x] **Live values** on frame-scope pins (sliders, audio, Integrate) when
      hovered - done in the fifth pass, and more: a readout on every
      frame-scope output all the time, a plot beside a hovered one.
- [x] Wire-drag from an *input* to an empty spot (the menu lists what could
      feed it); Alt-click to detach a node from its wires; F to connect two
      selected nodes.
- [x] A **properties side panel** for the long params (Bitmap rows,
      Expression, Image file).
- [x] Preview thumbnails on nodes - the pin preview's picture on the node
      previewed, and (sixth pass) a glyph on every node that has a shape
      to show: the function drawn, not its output, which the compile-to-C++
      model cannot tap per node cheaply.

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
- [x] Numeric expressions in fields ("2*pi") - done in the seventh pass:
      a box beside the field (=), since the number boxes are Dear PyGui's.
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
      views (the point cloud too, since the seventh pass).
- [x] **Per-effect cost on the device**: the engine's ms/frame on this PC,
      smoothed, and a device fps from it by a factor (60 by default,
      Settings > Device speed factor) - an estimate, labelled as one, until
      a device measurement calibrates the factor (the seventh pass's
      Calibrate button does).

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
      C++). Sliders are keyframed per sequence step, and ramp along one
      with a shape (the third and seventh passes).
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
      thirteen): Meteors, Spirals, Pinwheel, Curtain, Marquee, Shockwave,
      Butterfly, Snowstorm, Fan, Garlands, Lightning, Morph, Tendril.
      Writing them found two script compiler bugs: a declaration with
      two type words after `static` looped forever (`static or take()`
      skipped the take), and a hex literal's suffix strip ate its F
      digits (`0xFFFFu` -> `0x`) - and one in the bank: the roster's
      count was a byte, so the sim's 256-effect roster wrapped at the
      257th effect and the examples check found four effects.
- [x] **Icons and a bug sweep** after the second pass: the toolbar's
      right half opens the frames (devices, flash, send, the stream as
      a toggle; shape, sequence, library, palettes, outputs), each with
      a key (Ctrl+Shift+N/U/S/T, E/Q/L/G/O; randomise X); the frames'
      dock button is an icon that flips to "float" when docked. Fixed on
      the way: hotkeys fired while typing in any of the new frames'
      boxes (the guard now asks what has the focus, not a fixed list);
      every shape preview, thumbnail and transition made another engine
      on another copy of the DLL, none ever let go (a pool, one engine a
      purpose, reloaded when the library is rebuilt); the schedule's Off
      preset was the playlist's id + 1 = the first step's preset, so the
      off timer played the first step (a fixed id, 250); a part of a kind
      this version does not know made the project unopenable (now no
      LEDs); a sequence step saved on a bigger shape put a segment off
      the matrix (bounds clamped); popouts outlived a crashed or killed
      app (they watch the parent's pid).
**Third pass** (September 2026; after the panels were made succinct), in
the order to do them:

- [x] **WLED's segment options** - reverse, mirror, reverse Y, mirror Y,
      transpose, grouping, spacing, offset - in the sim (`simSegOptions`;
      `simSegLand` places each virtual pixel the way `setPixelColor` and
      `setPixelColorXY` do, so spacing shows what is under), in the
      panel's SEGMENTS section, saved with segments, and sent with the
      effect's settings and with every preset (WLED's own names: rev, mi,
      rY, mY, tp, grp, spc, of).
- [x] **A timeline** under the sequence's steps: the steps as blocks
      along the time, the transition into each shaded, the selected one
      outlined, a playhead while it plays, the bpm's bars, the WAV's wave
      behind (Play restarts the WAV with the sequence); click a step to
      select it, drag the line between two to retime the one on the left.
- [x] **Beats from the WAV** (`audio.beats_of`): an onset envelope, its
      autocorrelation over 60..200 bpm for the period (the peak refined
      between lags), the comb phase the onsets like best - the bpm into
      the BEATS row, the beats as ticks on the timeline; then "Snap
      durations to bars" follows the actual music.
- [x] **Test patterns** in the wiring test: all red / green / blue /
      white (the colour order), alternate, twinkle, and one LED output
      at a time (the outputs frame's ranges).
- [x] **Import an xLights layout** (`shape_io.read_layout`): every
      model of `xlights_rgbeffects.xml` as a part, placed by its world
      position and rotation (xLights' Y-up to the studio's Z-up), sized
      by its scale: custom models, matrices, single lines and poly lines
      exactly; circles, spheres, cubes, window frames, arches, trees and
      stars approximated and named in the status; the rest a strip.
- [x] **Value curves** as a RAMP per step: one slider of the first
      segment from the step's value to an end value, straight; the sim's
      sliders follow as it plays; on the device `sequence.sub_steps`
      makes it a sub-step a second (2..12), a preset each, so a playlist
      of ramps stays under WLED's hundred entries.
- [x] **Render to video** (`App.write_video`): a recording is a GIF or
      an mp4 - the frames piped to ffmpeg as raw RGB, H.264 out - chosen
      where it starts (the record button and Ctrl+F12 a GIF; File >
      Record 15 s video and Ctrl+Shift+F12 an mp4; the sequence frame's
      Render GIF / Render video for the sequence's whole length).

- [x] **Every geometry on the GPU** (`gpucube.PointQuads`): a cube is
      still its textured faces; everything else - a matrix, a strip, a
      sphere, a shape of parts - is a cloud of squares, one draw_image_quad
      per LED, each sampling one texel of an N-wide colour texture that is
      written once a frame in one call. The squares are placed only when
      the camera moves, far first so nearer ones cover (the software
      renderer's painter's order), and the k-th square shows the k-th
      farthest LED, so the draw order is the depth order without moving
      items. A 2,048-LED sphere: 5.7 ms a frame (draw 0.7) against 33.6
      (draw 28) on the CPU. The 3-D view draws the project's geometry when
      it is the engine's shape moved, so a dragged part moves on the GPU
      path too; the shape editor's rings know the drawlist's centring.
      Pictures, recordings, popouts and previews keep the software path.
- [x] **The node menu grew** a few pixels a frame once "delete" or "more"
      was unfolded, until it met the screen's edge: a selectable with no
      width takes the width there is, and in a window that sizes itself
      to its content the two chase each other. The rows have a width now.
- [x] **The panels succinct**: every explanatory paragraph in the
      frames became a tooltip on the control it explained (`chrome.tip`)
      or a dim (?) at the end of its row (`chrome.info`); labels
      shortened, rows merged, the sequence's PLAY and BEATS rows put
      together after the steps, the shape frame's layout and segment
      controls moved onto the PARTS row and its preview to the end, the
      flash frame's feature descriptions on hover. The GEOMETRY section
      of the panel now follows any geometry change (a shape opened, a
      ledmap imported), where it used to go stale.
- [x] **Shapes with control**: polygon parts (sides x LEDs a side) and
      polyhedron parts (the edges of a tetrahedron, cube, octahedron,
      dodecahedron, icosahedron or soccer ball, or every face outlined;
      the faces traced from the edges by the sharpest left turn, the
      edges wired on from the end just reached), split into a polygon
      per face or a strip per edge with the LEDs where they were; the
      LED count a field on every kind (a path takes a count and sets
      its pitch); PLACE as drag-numbers that move the part live in the
      view (the sim takes it on release; the undo step is where the drag
      began); AIM - a direction, a distance, a spin - to point a part's
      axis and put it there, with the axis drawn as an arrow; the
      preview folded away so the fields have the room.
- [x] **Frames close; a library tile selects.** The frames had no way
      out but dock/float: an x beside the grip now (Esc too, for a
      floating frame with the focus), the menu opens them again. A
      library tile used to throw the window into the full-frame graph
      (`set_layout` is the presentation mode); it now runs the effect
      where you are, building it first if it never was, and leaves the
      graph in the graph pane. The segment row names the effect even
      with one segment.
- [x] **A cleanup and bug pass over the suite**, with the cube back on
      the network. Found on the device: a `psave` answers success at once
      but WLED writes the preset from its main loop, and a second psave
      before the write replaces the one pending - the sequence's presets
      fired back to back and only the first landed (each is now waited
      for by the presets file's modified time in `info.fs.pmt`; not by
      reading presets.json, which loses the write); a playlist psave
      without WLED's `"o": true` stores the device's current state under
      the id, so the playlist never was one; the Off preset lacked `ib`,
      so it did not carry "on": false; the device went dark for the Off
      preset's save (switched back on after); rows read back from the
      device's timers lost their kind. In the studio: pyflakes over
      everything (a real one: the script compiler's curve lowering read a
      name only a code node before it would have bound - a NameError
      for a curve-first graph); `tests/test_graph.py` had no runner, so
      `python tests/test_graph.py` had been running nothing; the shape
      preview deleted its texture while the image still drew it (the
      alias then stays taken); crash.txt grew for ever (9 MB) with the
      same frame's failure written every frame; the menu walker imported
      the device's ledmap when a device was there; a frame scrolled while
      docked came back floating with its title hidden; the roster's
      `_ident` and the texture `rgba` helpers were each in two places.
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

### A self-contained app (September 2026)

The goal: one download that runs, for any WLED user, not a checkout of
this repo with a compiler beside it. Done so far:

- [x] **`native/paths.py`**: the one place that knows where things are -
      RES (what ships and is read: shim/, gen/, runtime/, examples, docs;
      the studio folder, or the bundle's `_internal`), HOME (what the
      user makes: projects/, build/, captures/; the studio folder, or the
      exe's folder when writable, else %LOCALAPPDATA%), TREE (the WLED
      checkout, or WLED_ROOT, or none). Every module asks it; nothing
      works a path out from its own file any more. `build/latest` holds
      a name, not a path, so the folder can move.
- [x] **`runtime/`** (`python build.py --runtime`): the firmware files the
      engine compiles from - usermods/cube_fx, wled_math.cpp, FastLED's
      slim copy - copied out of the checkout; with gen/ as generated, the
      engine and every effect build with no WLED tree beside them. The
      sources include by name (`"wled.h"`, `"cube_fx_bank.h"`,
      `"fastled_slim.h"`, `"fx_modes.h"`) from an include path
      (`build.include_dirs()`), never by a path relative to the file.
- [x] **`python -m native.doctor`** (also `studio.py --doctor`): Python,
      the packages, the compiler, the engine, the checkout or runtime/,
      PlatformIO, ffmpeg - each with the line that fixes it; exit 1 when
      the app cannot run. `requirements.txt`, `pyproject.toml`.
- [x] **`python package.py`** (`studio.spec`): the engine built and
      copied in as a prebuilt library, runtime/ written, an icon drawn
      from the toolbar's cube, PyInstaller's one folder - `dist/WLED
      Effects Studio/`, about 80 MB, with a console variant beside the
      windowed exe for when something goes wrong; `--toolchain <folder>`
      copies a MinGW-w64 (or a clang) in as toolchain/, which the
      toolchain finds before any installed compiler and links with
      `-static` so the DLL needs nothing beside it; `--zip` for a
      release. Verified: the packaged app runs from `_internal`, makes
      its project beside the exe, loads the prebuilt engine, builds an
      effect against runtime/, opens a popout (`--popout`, the same exe).
- [x] **A compiler in the folder**: winlibs' MinGW-w64 GCC (16.2, UCRT)
      builds the engine and every example with the same numbers as clang
      (`STUDIO_TOOLCHAIN=<folder>` tries one out from the tree; the app
      finds `toolchain/` beside itself first); `package.py --toolchain`
      cuts a full winlibs (940 MB) down to what a build uses, by asking
      g++ - `-print-prog-name` for its programs, `-MM` for the headers the
      engine pulls in, `-Wl,--trace` for the archives a DLL link takes,
      `objdump -p` for the DLLs those programs import - the whole C++
      library kept, the Windows SDK's thousands of API headers, cc1, gdb,
      cmake and fortran dropped: 121 MB, with a NOTICE for the licence.
      The link is `-static`, so a built DLL needs only KERNEL32 and the
      UCRT. The engine's objects ship too, named by paths relative to the
      folder and stamped by contents (not mtimes), so a first build in a
      fresh copy compiles only the new effect: five seconds. The release
      zip is 86 MB; unpacked and run from another folder with no env, it
      built Fan and Garlands with its own g++.
- [x] **The standalone app tested as itself**: `STUDIO_EXE=<the console
      exe>` points `tests/smoke_app.py` and `tests/walk_menus.py` at a
      packaged app instead of the tree - its folder is the home they save
      and restore, they wait for it to unpack, and the app's output is
      line-buffered (studio.py) so a killed process leaves its log. On a
      fresh unzip in another folder: smoke 31 steps ok (the DDP stream
      received), walk 338 rows ok, no frame exception, the doctor from
      `--doctor` all green with the bundled g++; by hand: a script sent
      to the cube and running, a settings push refused with the right
      words, a DDP stream, three effects built with the bundled g++ in
      five seconds each. Found and fixed on the way: the flash frame and
      the usermods dialog were blank in a bundle (no WLED checkout) - they
      say so now, with WLED_ROOT as the way in, and Start / Preview refuse
      rather than staging into the app's own folder.
- [x] **Updates** (`native/update.py`, `native/version.py`): the app
      reads the newest release of `version.REPO` from GitHub's API once a
      day (no token), compares the tag with `__version__`, and offers the
      zip: downloaded to `updates/`, then a script that outlives the app
      waits for it to close, unpacks, robocopies over the folder with
      projects, captures, toolchain and updates left alone, and starts it
      again. Tried end to end against a local fake release: found at
      start, the dialog, the download, the swap, the restart. From a
      checkout: git pull. `STUDIO_UPDATE_URL` points a test at another
      releases JSON; `STUDIO_NO_UPDATE_CHECK` keeps the tests offline.
      `package.py` writes `version.json` (version, commit, day).
- [x] **Its own repository**: the studio moves to `Aceftwspades/
      wled-effects-studio` with its history (git subtree split); the WLED
      fork keeps the firmware side (usermods/cube_fx, the playground
      branch) and a pointer. The studio vendors `gen/` and `runtime/` from
      a pinned fork commit (`WLED_SOURCE.json`; `build.py --runtime` with
      WLED_ROOT refreshes them), finds a WLED checkout beside it or by
      WLED_ROOT for the flash, and carries WLED's licence (EUPL v1.2)
      since it compiles WLED's own effects, palettes and colour maths.
      A GitHub Actions workflow builds the Windows release zip on a
      version tag - winlibs downloaded and trimmed on the runner - and
      attaches it to a draft release for the update check to find once
      published.
- [x] **The checkout fetched from the Flash frame** (`native/wledtree.py`):
      with no WLED tree, the frame offers "Get the WLED fork..." - a
      shallow `git clone` of the fork's branch into a folder the dialog
      names (WLED beside the app), its progress in the dialog; without
      git, the branch as GitHub's zip, unpacked - remembered in the prefs
      (`ui.wled_root`, which `paths.py` reads at start; WLED_ROOT still
      wins) and a restart offered; or "I have one" for a checkout that
      exists. Tried from a copy with no tree: the clone, the restart, the
      flash frame listing the checkout's environments.
### Fourth pass: Blender and xLights (September 2026)

Measured once more against Blender's node editors (with Node Wrangler)
and xLights, with the three passes above done. What is left that fits
an effect tool for the firmware, ranked by value over effort; the order
is the order to do them.

- [x] **Playback speed** (xLights' half speed; a step rate in Blender):
      1/4, 1/2, 1, 2 and 4 times, from Playback > Speed and two keys
      (Shift+, slower, Shift+. faster; Shift+/ back to 1x); the engine
      steps that many simulated frames per real second, the synth's
      beat clock with it, so an effect can be studied slowly or run
      ahead. The footer says the speed when it is not 1x.
- [x] **Reset a node to its defaults** (Blender's Backspace on a node):
      every setting and every typed input value back to the library's,
      from the node's menu; Backspace on a value already did one.
- [x] **Export the shape's positions** (xLights' export model): the LEDs
      as CSV rows - index, part, x, y, z - from the Shape frame, for any
      other tool; the same file reads back as a points part.
- [x] **Breadcrumbs in sub-graphs** (Blender's context path): the trail
      from the top graph down to the one open, each name a button back
      to it, in place of the one "< back".
- [x] **Change a node's type keeping its wires** (Node Wrangler's switch
      type; xLights' change effect): the node's menu offers the library;
      the new node takes the old one's place, its wires reattached by
      pin name, then by the first free pin of the type; settings kept
      where the names match.
- [x] **Merge selected nodes with an operator** (Node Wrangler's
      Ctrl+numpad): two or more selected nodes' first outputs into a
      chain of Add, Multiply, Subtract, Min, Max or Mix for numbers, a
      Blend for colours, placed after them.
- [x] **Unfold a sub-graph** (Blender's ungroup, Ctrl+Alt+G): the node
      replaced by the sub-graph's own nodes, wired in place of its
      boundary nodes, positioned where it stood.
- [x] **Hover an LED for its index and part** (xLights' node numbers):
      the pointer over the logical net or the 3-D view names the LED
      under it - its wiring index, its part, its position - in the
      footer.
- [x] **Align and distribute parts** (xLights' layout tools): the
      selected parts of a shape aligned on an axis to the first, spread
      evenly between the first and last, or given the first's scale.
- [x] **Paint a bitmap** (xLights' effect assist): the Bitmap node's rows
      as a grid of cells in the properties pane, clicked and dragged to
      set and clear; the rows follow.

- [x] **The fields on a node** (Blender's fields): a number is a drag
      field (drag sideways, the pace a hundredth of the value's size;
      ctrl+click types), a setting with a range is a slider with the value
      written across it (`_field_theme`: the box a shade lighter than the
      node, the grab a narrow translucent bar so the value reads),
      Ctrl+wheel steps either; two inputs that are one point (nodedefs
      `PADS`: Transform's pivot and move, Gravity's tilt, Mandelbrot's
      Julia constant) get an XY pad - an image button whose texture is
      redrawn as the dot is dragged, both fields following, one undo
      step a stroke - shown while neither input is wired; the Effect
      settings' palette is a dropdown of the sim's palette names.

Looked at and left: Blender's simulation zones and baking (Fields,
Sequencer and Particles are the studio's), multiple editor areas (the
panes and pop-outs), numeric expressions in fields (Dear PyGui parses
its own), node timings (one compiled function); xLights' FPP export,
video, DMX, shaders, and per-effect fade in / out (WLED's transitions
cross-fade the presets already).

### Fifth pass: what music software knows (September 2026)

Modular synths, Max / Pd, Reaktor, VCV Rack, Bitwig's Grid and Ableton's
racks have edited real-time graphs for forty years, and an effect graph is
a patch: frame scope is control rate, pixel scope is audio rate, WLED's
sliders are the macro knobs. What they know that the studio did not, in
the order to do them:

- [x] **No compile between the knob and the sound.** A synth answers a
      turned knob at once; the studio rebuilt the effect for every typed
      value. Every unwired number, check and vector input compiles as a
      read from a parameter table (`gc_param[k]`, `static const` on the
      device - the typed values baked in, no DRAM; a live `static` in the
      sim, bound to the effect by `GC_PARAMS` each frame) and a drag on
      the field pokes the running engine (`simParamSet`); only a change
      of topology, a setting or a colour rebuilds. Settings stay literal:
      several size arrays and loops.
- [x] **Signal visible everywhere, always.** Frame-scope values - the
      sliders, Audio, the beat, Integrate, Ease, the Sequencer - are one
      number a frame, so probing them all costs nothing: a live readout
      on every frame-scope output pin, all the time, not on hover; a
      history plot on a hovered one.
- [x] **Control rate and audio rate told apart on the wire**
      (SuperCollider's kr / ar): frame-scope wires drawn thinner, so the
      graph shows which half runs once a frame and which 1,280 times.
      Found on the way, and the worst bug of the season: the panel's
      save() wrote node positions straight off the editor's grid - the
      graph scaled by the zoom and shifted by the pan - so a graph saved
      at 50% (and every Live compile saves) halved on every save, until
      several of the project's graphs were heaps at the origin; the
      history showed wobble.json's span going 820 → 410 → 205 → ... → 1
      over two days of test runs. save() converts now, _sync_pos leaves
      an unmoved node alone (the editor holds whole pixels: reading an
      unmoved node back at a small zoom crept it), the squashed graphs
      were restored from the examples and the history, and a test pins
      the conversions.
- [x] **Units and scales on the fields**: a node definition may say a
      value's unit (ms, Hz, s, beats, x, %, LEDs) and its scale
      (logarithmic for times and rates, bipolar about zero); the slider
      obeys and the field shows the unit.
- [x] **Modulation as a gesture** (Bitwig): a field's menu offers
      "modulate with..." - Time, the volume, a band, the beat, an LFO - an
      amount and a range; the Remap it makes stays folded out of sight,
      the range drawn on the field. Done as: the Remap folded to one small
      node labelled "scale ±1.5" (its out_lo / out_hi are the range); the
      range is on that label, not drawn on the field itself.
- [x] **Musical time**: a **Tempo** node measures the tempo from the
      beats as they come (the gaps between Audio's hits, smoothed, 30..300
      bpm; the fallback until beats arrive) and counts time in beats,
      snapping to the nearest whole beat on each hit so the phase stays
      with the music: `beats`, `phase` (in the beat), `bar` (over four).
      A Wave with beats / 4 on its x is one cycle a bar at any speed;
      "modulate with" offers the beat's and the bar's phase. Runs as a
      script too. A test drives it with the synth at 132 bpm and reads
      132 back.
- [x] **A Steps node** (the step sequencer: eight values as sliders on
      the node, one at a time, the next on each trigger, reset to the
      first; value, step and changed out; scripts too) and **snapshots**
      (Edit > Snapshots..., Ctrl+Shift+K): the whole graph's settings and
      typed values as named states kept in the graph file - save,
      recall, update, remove - and a MORPH slider between two: numbers
      blend, the rest switches half way, typed values follow live and a
      changed setting rebuilds.
- [x] **Modules that show what they do**: a gradient strip on Palette, the
      bands on Audio, a period of the Wave, a thumbnail of the Noise - the
      graph readable like a rack.
- [x] **Wireless sends** (a named Send / Receive pair, the Knot's cousin)
      and **loops closed with a delay**: a cycle offered a one-frame Delay
      at its back edge instead of a refusal. Send / Receive (and the
      colour pair) are joined by a pass before plan and compile, so both
      back ends see one wire and the nodes cost nothing; a Send fed by a
      Receive chains; a Receive with no Send is an error on the node, a
      Send nothing receives a warning; a loop through a pair is a cycle
      like any other. A wire that closes a loop gets a Delay when its
      source runs once a frame and carries a number (undo takes both
      out); a colour or per-pixel loop is linked and refused as before.
- [x] **MIDI learn**: a controller's knobs onto the panel's sliders (and
      through them the device), an optional python-rtmidi. native/midi.py
      (the port on rtmidi's thread, messages queued for the main one, the
      maps in the project's options) and native/midi_ui.py (Playback >
      MIDI controller: port, target, Learn, the mappings with a range
      each; a parameter slider's right-click and a pin's menu offer Learn
      too). Targets: the sliders, the checks, the palette and the effect
      by index, a typed value on a pin (a bool pin on/off). Not tried
      against a real controller yet: no MIDI input on this PC; the tests
      inject messages through the port's own callback.

### Sixth pass: the face of a module (September 2026)

Item 8 of the fifth pass shipped as its minimum: four glyph kinds on six
node types. Against a VCV Rack module - recognisable by its faceplate
before a word is read, lights for events, a scope on anything, the
function in the name - the graph is still a field of grey boxes with
numbers on them. This pass is the item in full, and the standard for the
work is "would a VCV user find it thin": each entry below is done when
every node it names has the thing, not the first three.

- [x] **Functions that say what they compute.** Every node has a
      one-line summary derived from its definition and its typed values:
      a one-statement code template prettied (`$in.a + $in.b` reads
      `a + 0.5` when b is typed 0.5, `floorf` reads `floor`, `6.2831853f`
      reads `2π`, casts and `f` suffixes go) and hand-written forms for
      the nodes whose code is not one line - Remap `0..1 → 3..5`,
      Map range, Smoothstep `edges 0..1`, Clamp, Threshold `≥ 0.5`, Mix,
      Select, Math its op, Wave `sine × 3 cycles`, Noise `scale 4, 1
      octave`, Ease `→ target in 1 s`, Envelope `20 / 250 ms`, Integrate
      `+1 /s, wrap 1`, Spring `1.2 Hz`, Steps `8 steps`, Sequencer `1 1 1
      1 s`, Tempo `fallback 120 bpm`, Palette the palette's name, Colour
      ramp its stop count, Expression its text, Send / Receive their
      name, Bitmap its size, Text its text, Image its file... Shown on the
      collapsed node as its body, on the stand-in zoomed out as a second
      line when the font allows, first in the hover box, and as the
      tooltip of a full node's title; it follows a typed value as it is
      dragged. Tests: every library node summarises at its defaults with
      no `$`, no `f` suffix and no C cast in the text; the hand-written
      ones are spot-checked. (native/nodeface.py; the line sits in the
      hover box rather than a title tooltip - a tooltip on a node fires
      over its fields too.) Found on the way: Dear PyGui 2.3 no longer
      hands the node editor's font or theme down to its nodes, so the
      zoom had stopped scaling text and node heights (a 50% graph drew
      full-size nodes at half spacing, overlapping); every node now
      binds the zoom's font and carries the zoom's styles in whichever
      theme it wears, and the smoke test measures a node at 100% and 50%.
- [x] **A face per category.** The title bar coloured by category by
      default - signals, coords, generate, maths, colour, controls,
      graph, output, custom: nine muted hues chosen apart - the node's
      own colour and muted still winning; the same hue on the Add menu's
      category headers and in the node library's rows, so the legend is
      learnt by using it; a legend with the switch to turn it off in
      Settings > Appearance; stand-ins keep the hue.
- [x] **Lights and meters.** A bool output pin gets a light in place of
      "on / off" - bright when true, dim when not, with a 150 ms
      afterglow so a one-frame hit is seen (a VCV LED decays) - and a
      float output whose range is known (Audio's outputs, Wave, Ease,
      Envelope, Random hold, the phases of Tempo, Sequencer and Beat
      kick, Steps within its sliders' span, Integrate within its wrap)
      gets a small bar under its number; the number stays for the rest.
- [x] **Glyphs that move.** The Wave carries a dot at its live phase
      when its x runs once a frame; the Palette strip a marker at the
      live index; the Noise thumbnail scrolls with its live z; Steps
      lights its current step; the FFT bin's own bar stands out in its
      bands; Integrate, Ease, Envelope, Spring, Delay, Random hold, Beat
      kick and Tempo draw a sparkline of their last three seconds.
- [x] **Glyphs for the rest.** The transfer curve of every one-in,
      one-out maths node computed over its input range - Remap, Map
      range, Smoothstep, Clamp, Threshold, Fract, Abs, Floor, Power,
      Modulo, Sine, Cosine, Log, Exp, Band, Float curve; strips for
      Colour ramp (its stops) and Blackbody (with the typed kelvin
      marked) and Colour pick (its eight); the Gradient's shape; pattern
      thumbnails for Checker, Stripes, Ripple, Voronoi, Brick and
      Mandelbrot from the typed values; a Bitmap's and States' pixels, an
      Image's picture, a Text's text, a Path's polyline seen from above.
      Each redrawn when a typed value or setting changes.
- [x] **A Scope node**: the rolling plot of anything wired in (three
      seconds, min and max marked, frame-scope as it is, per-pixel at the
      centre pixel), compiled to nothing - VCV's Scope, left on a wire.
- [x] **The hover plot the fifth pass promised** (item 2: "a history
      plot on a hovered one"; only the readouts shipped): hovering a
      frame-scope output pin draws its last three seconds beside the pin.
      All of the above in native/glyphs.py (a mixin of the panel) over
      one ring buffer of every probe's last ten seconds, recorded once a
      frame; the static faces redraw as a value is dragged; the node
      fields show five significant digits now (5000 K was 5e+03).
      tests/face_demo.py writes a graph with every face on it, which the
      smoke test builds and interrogates: the dot moves, the plots have
      points, the Noise has scrolled, the step is lit, the hovered pin
      has its plot.

After this pass: the earlier passes' ticked items read again for the
same kind of thinness, and each such item fleshed out to the feature it
names.

### Seventh pass: the thin ones fleshed out (September 2026)

The ticked items of every pass read again for the same thinness the
sixth pass found in item 8: a feature named in full and shipped in its
smallest form, or deferred twice with a reason that no longer holds.
What that reading found, in the order to do them; each is done when it
is the feature its line names.

- [x] **Numeric expressions in fields** (deferred in two passes: "the
      number boxes are Dear PyGui's and parse their own text"). They
      still do - so the expression goes beside the box: `=` while a
      field is hovered, or the field's menu row "type an expression...",
      opens a small box at the pointer; `2*pi`, `1/3`, `x*2` (x the value
      it has), `sqrt(2)`, `sin(0.25)`, `min(a, 4)`... with the usual
      operators, `pi`, `e`, `tau`, the maths functions and `rand`;
      Enter sets the value (typed inputs and settings alike, the running
      effect poked as a drag would), Escape leaves it. A safe evaluator
      (`native/expr.py`, the AST walked, nothing else called) with tests.
- [x] **The modulation range on the field** (the fifth pass's item 5
      promised "the range drawn on the field"; the folded Remap's label
      carried it instead). An input fed by a modulator's Remap shows its
      range under the pin's name - a bar from out_lo to out_hi with the
      live value's position on it, the two numbers at its ends - so the
      modulated node says what it is being swept over without opening
      the Remap; Ctrl+wheel over an end nudges it (a drag on the bar would
      fight the node editor for the click).
- [x] **The device speed factor measured, not guessed** ("an estimate,
      labelled as one, until a device measurement calibrates the
      factor"). The Devices frame gets "Calibrate the speed factor":
      the current effect's settings pushed to the device, its fps read
      from /json/info for a few seconds, and the factor set from the
      device's ms a frame against this PC's - the footer's estimate
      becomes a measurement, dated, and the label says so.
- [x] **The API reference inserts** ("a click copies the snippet (the
      box cannot take an insertion)": the in-app editor can): a click
      puts the snippet at the cursor, with the indent of the line it
      lands on; copying stays on the right button.
- [x] **Find and replace, whole** ("find lists matching lines (click ->
      line); replace all"): next and previous (Enter / Shift+Enter in the
      box, F3 / Shift+F3), the count and place ("3 of 12"), replace one
      (the match under the cursor, then the next found), match case and
      whole word.
- [x] **The scrub in every view** ("the point cloud still shows the live
      pixels"): the last seconds of every LED's colour kept beside the
      net frames, so a scrubbed frame shows on a strip, a sphere, a
      shape of parts as it does on the cube.
- [x] **Value curves with a shape** ("one slider ... straight"): a ramp
      per slider of a step (any of the five, several at once) with a
      shape - linear, ease in, ease out, ease in-out, up and back (a
      sine) and a step half way - drawn on the timeline under the step;
      the sim's sliders follow the shape, the device's sub-steps sample it
      (seven for up and back, so the top is played). A ramp saved before
      shapes reads as linear.
- [x] **The record set straight**: "Live values on frame-scope pins when
      hovered - deferred" and "Preview thumbnails on nodes - deferred" in
      the first Blender list are done (the fifth pass's always-on
      readouts and hover plot; the sixth pass's glyphs, and the pin
      preview's picture for a node's output), and the zoom is 10..200%,
      not 50..200%; the notes say so.

- [x] **A console window over the graph** (found by the user, not the
      tests). The studio runs without a console of its own - the packaged
      windowed exe, or pythonw - and on Windows such a process gives every
      console child a NEW console window, which on Windows 11 is a
      Terminal window. The compiler is a console program, so every Live
      rebuild threw one up over the node graph: opening and compiling one
      graph popped four (vswhere, and clang++ three times). Every child
      the app starts now goes through `native/procs.py`
      (CREATE_NO_WINDOW; `procs.run` / `procs.popen`) - the compiler and
      the linker, the compiler probes, PlatformIO, the objdump that
      measures flash cost, git, the popouts, the external editor and the
      openers. Two keep their own console on purpose, both marked in the
      source: the restart after fetching a checkout (it must outlive the
      studio) and the updater's copy (whose progress is the point).
      `tests/test_audit.py` walks the source and fails on a new
      `subprocess.run` or `Popen` that is neither; the fix was measured by
      counting the windows that appear while the studio compiles a graph
      under pythonw - four before, none after. STUDIO_CONSOLE_CHILDREN=1
      hands the children their console back, to watch a build go by.

### Eighth pass: the interface critique (September 2026)

A critique of the whole interface from captures of every layout, frame
and dialog at 1280 x 800 and 1920 x 1080 (published as the "Effects
Studio Critique" page): feature-complete, but nearly everything on
screen at once, at one weight, in a 13-px debugging font, with the
graph and the LEDs given less room than the controls around them. Its
findings, in the order to do them - the plain bugs first, then what
reaches furthest; (Cn) is the critique's number.

**Plain bugs**
- [x] The graph's zoom and tools on the toolbar stayed pale on a light
      theme: grouped (to hide them outside the graph), they were missed by
      the re-tint, which walks the group now.
- [x] **The light themes in the graph** (C3): switching theme left the
      value fields near-black under dark text until the graph was
      reopened; title bars kept dark hues under dark title text. A theme
      change now rebuilds the graph, light themes tint the title bars and
      darken pin names and wires, and everything the graph draws takes
      its colours from the theme (GraphPanel.pal). Shipped in 1.1.0. (The
      critique first said the fields stayed dark in a light theme; they
      only did until the graph was rebuilt.)
- [x] Help > Studio guide opened STUDIO.md, the development log: Help is
      the user guide, the tutorial and the node reference now (C4 below).
- [x] The Flash frame shows `partitions ${esp32.extreme_partitions}`
      unexpanded: PlatformIO's ${section.option} references are resolved
      now (the override first, nested, ${sysenv.X}).
- [x] The Sequence frame's timeline text is clipped by the steps list: it
      was drawn before its first layout, when it measured 0 high (the
      text at y = -7) and the frame 0 wide (the timeline 200 px); it takes
      its configured size and follows the frame's width.
- [x] The Shape frame's first line runs off the frame (wrapped, its (?)
      first).
- [x] The Library frame's count line is cut off (a line of its own).
- [x] Home ("Frame the whole graph") moves every node and adds an undo
      step; so did Frame the selection. Both fit the view now - the zoom
      the largest step the nodes fit at, the panel's view offset worked
      back from the editor's measured pan - and no node moves.
- [x] The shortcuts dialog lists its "anywhere" group twice.
- [x] Slider grabs cover their own digits: a thin translucent mark on
      every slider that writes its value (the node fields, and the
      frames' VALUE_SLIDERS).
- [x] The zoom box reads 120% in layouts with no graph: the graph's tools
      are shown only in the graph layout.
- [x] Stand-in summaries are cut mid-word (nodeface.fit_words: at a word,
      with "...").

**What reaches furthest**
- [x] **Help that reaches the user** (C4): the guide, the tutorial and
      the node reference read inside the studio (reader.py parses them,
      reader_ui.py draws them): set in a reading face (Segoe UI, Helvetica
      or DejaVu by platform, bold for headings and labels, Consolas for
      code) where the rest is the 13-px bitmap font; the contents down the
      left with the section on screen marked and kept in view; a search
      that stops at each mention, marks the words where they are drawn -
      the lines Dear ImGui wraps a paragraph into worked out again, so the
      mark sits on the word in a thirty-line paragraph - and says which of
      how many (Enter / F3, Shift+F3 back); links between the documents
      with Back (Alt+Left, Backspace); tables, lists, quotes, bold labels;
      code scrolled sideways with a copy button; the tutorial's pictures
      scaled to the page, a click showing them at full size. Help: User
      guide (F1), Tutorial, Node reference, Effect API reference, Keyboard
      shortcuts (Shift+F1), Welcome...; STUDIO.md out of it. F1 in the
      graph opens the node reference at the node under the pointer or the
      selected one; a node's menu leads with its first sentence and "<type>
      in the node reference..." (F1), shows every row's key in a column
      (menu items on top, the key after the words in a fold), and has
      delete, delete and reconnect and disconnect out of their fold. A
      first-run panel: the tutorial, the guide, the examples, a device;
      Help > Welcome... again, a checkbox to show it at every start. Three
      lines of the guide and the tutorial that began with "- " or "> "
      after a re-wrap (a list item or a quote on GitHub as well) mended,
      and a test that none does again; tests/test_reader.py (parsing, the
      wrap against Dear ImGui's own example, links, every node's entry,
      the keys), smoke steps for all of it.
- [x] **The graph gets the room** (C1): canvas first (native/room.py,
      View > Graph: canvas first, on by default) - the graph 96% of the
      width at 1920 and 95% at 1280, where it had 53%. The side panel
      folds to a rail of its sections' icons (drawn for it) at the
      window's edge; a click opens the panel beside the rail at that
      section, or goes to it when open, the section in view lit on the
      rail; the rail's top button folds it (a panel opened on the graph's
      left moves the view back as far, so no node moves on the screen).
      The 3-D view floats in a corner of the canvas: its ::: drags it to
      the nearest corner, its handle or Ctrl+wheel sizes it, its tuck
      button puts it away to a tab (not drawn meanwhile); the minimap
      keeps to a corner it leaves free. The properties come up over the
      canvas only for a node that needs them (text over several lines, a
      file, a curve, a bitmap) or while the add menu describes a node; N
      pins them, their x closes them until the selection changes, and
      they size to what they hold, above the 3-D view on its side. The
      help band became the help at the pointer, after a rest. What floats
      over the canvas is a top-level window: overlapping child windows of
      the root take the pointer in the order they were first drawn (the
      node editor's canvas, made later, would have won); the 3-D view and
      the properties move into their windows while the graph is up and
      back among the panes after, and the 3-D view's own overlays still
      draw on it. A press on anything floating over the graph is no
      longer the graph's (it finds nodes by their rectangles: a click on
      the 3-D view over a node pressed the node). The panes mode is the
      arrangement as it was.
- [x] **Button weights and empty states** (C5): native/weight.py.
      Primary (filled in the accent: the one thing a dialog or frame is
      for), danger (red: what changes a device or deletes - the ledmap
      and shape sends' confirms, a reboot, an import over the shape, the
      x on every row), quiet (no slab: Cancel, Not now, Close), the rest
      secondary; themed from the colours in force and rebound on a theme
      change, made before anything is built (made later, a theme became
      the "last item" the next tooltip hung on). The confirm weighs its
      answers (a way out quiet, the first primary, a device change red).
      Needs: what each action wants (a node selected, two, three, a graph,
      a copy, something to undo where Undo acts, a device, a sub-graph, a
      preview) greys it on the menus and the toolbar - the toolbar's icon
      fades too, Dear PyGui drawing a disabled image button as an enabled
      one - and its key says why instead of doing nothing; the frames'
      buttons have theirs (the Send frame's sends and reads a device, the
      Sequence's a step or steps, the Palettes' a palette, the Outputs'
      and Audio input's a device), and a disabled control of any kind is
      drawn greyed at all (a theme component: it was drawn live). Empty
      states say what the list would hold and offer the next step: the
      Library (New effect), the Flash effects list (add this effect), the
      Palettes (new, or the sim's), the Outputs (one output, or the
      device's), the Sequence's steps (what the sim shows; its timers
      plainly, one primary to a frame), the open menu; the Send frame with
      no device offers Find a device; where the frame's own primary is the
      step (Devices, MIDI), the words point to it. Found on the way: the
      lines built in the theme's colours kept the dark defaults - on a
      light theme the confirm's question was near-white, and a light
      project started so - they are recoloured when the theme changes and
      once at start; Delete took imnodes' selection alone (A, Ctrl+[ ...
      selected nothing it would delete).
- [x] **A type foundation and an interface size** (C2):
      native/typeface.py. The platform's interface face (Segoe UI,
      Helvetica, DejaVu Sans) where Dear PyGui's 13-px bitmap face was, in
      roles: body 16, small 14 (captions: a count, a size, a key beside
      what it belongs to), label 14 semibold (the capitals over a group:
      STEPS, ON THE DEVICE, and the side panel's sections), heading 20
      semibold (a frame's title, the properties' node, About), and the
      monospace, Consolas 13, for code, logs, the status figures, the
      expression box and every field's value on a node. Dear ImGui's sizes
      are line heights, not ems - Segoe UI's line is 1.33 em, Consolas' 1.0
      - so a first cut at "14" drew a 10.5-px em, smaller than the bitmap
      face it replaced and than the code beside it; 16 is the platform's
      9 pt, x-height for x-height with Consolas 13 (a test holds it). The
      graph sets a node's title, pin names and summary in the interface's
      face at its zoom and its fields' values in the monospace; text is
      placed by measured width - typeface.measure, Pillow at the em Dear
      ImGui asks FreeType for, the same hinted advances to the pixel in 510
      of 510 cases, before a frame has built the atlas - where it counted
      characters (right-aligned output names, readouts beside them, wire
      labels, the modulation ranges' ends, stand-in summaries cut at a word
      by width, the timeline's names, a usermod's line, the confirm's
      height by the reader's word wrap). The interface size: Settings >
      Appearance > Interface size, 80-200% in 5% steps, first the
      monitor's own scale; the process is per-monitor DPI aware, so
      Windows no longer stretches a 100% picture; The monitor's goes back
      to the system's; Restart now saves the graph, asks about unsaved
      code and starts the studio again (the old process ends, the new one
      runs at the size - tried end to end; the menu walk skips it). Every
      size in the interface is laid out at 100% and passes through px():
      panes, splitters, the rail, the 3-D view's corner, dialogs, file
      dialogs, swatches, the palette bar (drawn and hit-tested at it),
      tooltips' wrap, icons (rendered at the size, not stretched); the
      prefs keep the panel's width and the 3-D view's size at 100%, so
      they keep their share across a change; the graph's first zoom is the
      step nearest the size. test_audit fails on a literal size on any
      Dear PyGui call or helper default. Found on the way: drawn text takes
      only the font bound to the text item, not its drawlist's - the code
      editor's columns fell apart once the global face was proportional,
      and the timeline scaled the monospace to other sizes (soft); each
      drawn text binds a face made at its size now (typeface.draw_text).
      The properties pane sized its text box by the graph's zoom (48 px
      tall at 40%). About broke its sentences by hand for the old face's
      width and opened in the window's corner; Home framed a big graph at
      20% when the layout changed to the graph in the same frame (it
      guessed an 800 x 600 canvas; it reads the pane's laid-out size now).
      The reader shares the interface's fonts. Left for C6 and C7, where
      each control gets a label of its own: the panel's and the frames'
      field values in the monospace (their inline labels would go with
      them), and a node field's name in the interface's face.
- [x] **Forms read left to right** (C6): native/form.py. A form row is
      its name right-aligned in a column of its own, then its control
      (form.row; the column is measured to the pixel, so every control
      starts at the same x, a name too long for it cut at a word with the
      whole on hover); a checkbox keeps its words after it, under the
      controls (form.check, form.under); a row of several fields leads
      each with its words (form.inline: "presets from [10] playlist [9]
      named [Show]", "SD [-1] WS [-1] SCK [-1] MCLK [-1]"); a note sits
      under the controls (form.note). A row's value fields take the
      monospace as it closes (C2's leftover). The side panel throughout -
      the effect, segments (from x y, to x y, opacity, blend mode, the
      options, group / space / offset), geometry and the cube's wiring,
      parameters, audio, live - and the frames: Sequence (a step's name,
      held, blend; RAMP [sx] to [128] [linear]; blend as; beats a bar; the
      timers, their days as toggles that fit the frame), LED outputs (a
      table under its column names, the name and the type stretching to
      the frame), Audio input, Palettes, the Shape frame's part fields
      (position, rotation in degrees, scale as 1.00x, aim), the Send
      frame's stream and wiring test, the Flash environment, the code
      pane's metadata (each field's format on hover), Sweep. Units inside
      the field where its format allows ("10.0 s", "120.0 bpm", "30 fps",
      "20 LEDs/s", "0.0°"); an integer field has no format - C7's control
      takes those in. A colour is its swatch and its hex (form.swatch:
      the picker behind the swatch has R, G and B; the hex takes #FFA000,
      FA0 or 255,160,0): the segment's three colours, the theme's seven,
      a palette stop; a node's colour setting shows its swatch alone, as
      a colour input does. test_audit fails on a field labelled after
      itself - Dear PyGui's label, or a text straight after it - outside
      the graph's node fields (C7). Found on the way: loading a sequence
      step changed the colours but not the swatches showing them.
- [x] **One number control** (C7): native/num.py. Five kinds became one
      - the panel's slider showing no value beside a box that did, the
      nodes' drag fields, sliders whose grab sat on their digits, log
      sliders with the value outside the track, integer sliders whose
      grab at the minimum read as a checkbox. The value and its unit on
      the track in the monospace ("120 bpm", "1.00×", "150%"); drag it
      (Dear ImGui's Shift and Alt pace it); a click - pressed and let go
      without moving - types into it, the number selected (Dear PyGui's
      drag fields do nothing on a click; its focus_item puts one into its
      text mode, found by a probe and held by a test); Ctrl+wheel steps it,
      anywhere; a thin fill under it for where it sits in its range, along
      the log of it for a log field, which moves by ratio (its pace follows
      its size as it moves: Dear PyGui has no log flag); an open field
      paces by its size, or its default's while near 0; a range too wide to
      slide across clamps and paces as an open one; a field clamped at one
      end only is. num.set moves a value and its fill from outside (MIDI,
      a sweep, a sequence's ramps, the XY pads, a snapshot's morph, a typed
      expression), num.configure a range (the scrub's grows with the
      history). Everywhere: the side panel's parameters, audio and live
      gain (one field a row, filling the row), the segment's opacity, the
      scrub, the Sequence's ramp end, the Audio input's gain and squelch,
      the snapshots' morph, Settings > Appearance > Interface size, the
      Shape frame's scale; on the nodes every number input and setting,
      a ramp's stops and a curve's points. On a node the fields line up
      after their names - a column per node from its widest field name at
      the zoom, no more than half the node, a longer name cut - the name
      in the interface's face (C2's leftover), and a name stays while its
      field hides under a wire; a colour, a choice, a text and a vector
      follow their names too. Typed fields stay for numbers that are typed
      (pins, ids, counts, durations). test_audit fails on a slider or a
      single drag made anywhere but num.py, and on a field labelled after
      itself anywhere, the nodes now included; tests/test_num.py (formats,
      the fill, the pace, set / configure / step, a click against a drag
      with the mouse stubbed, and focus_item's typing on a real frame).
      The sliders' own theme (a thin grab over the digits) went with them.
- [x] **One window style, frames docked** (C8): native/dock.py. The
      frames opened floating, over the logical and 3-D views they change;
      they open in the dock now - the side panel's column, tabbed: a Panel
      tab and one per docked frame, one in front at a time, the column as
      wide as the tab in front wants (the panel its width, a frame the width
      it was drawn for, or the one its edge was dragged to, kept at 100%),
      so the views move over and are never covered. The strip is buttons
      (Dear PyGui's tab bar gave its first item all the width the others
      left, whatever it was): the one in front on the panel's ground in the
      accent, each frame's close beside it, names as icons when they do not
      fit, and at its right float, which takes the frame in front out into
      a window over the panes; a floated frame opens floating until docked
      again - by dock at its top right, or its grip dropped on the panes (a
      frame is no pane any more: an older arrangement holding one is
      migrated into the dock). While the graph has the room the dock is the
      drawer beside the rail, and the rail carries the docked frames' icons
      (a click brings one to the front, the drawer opened). A docked frame
      drops its own header - its tab names it. One window style: the
      nineteen dialogs (Appearance, Keyboard shortcuts, Usermods, History,
      Undo history, Snapshots, MIDI, Sweep, About, Update, Report, Selection
      frames, a WLED checkout, the Help reader and its picture, Welcome, and
      the three modal questions) lost Dear PyGui's title bar for the frames'
      header - the title in the heading face, a close at the top right that
      follows the window's width - and titles are in sentence case, frames'
      too ("LED outputs", not "LED OUTPUTS"; the capitals are for labels);
      Esc closes the dialog with the focus, as it does a floating frame. The
      walk found the float button pressed in the frame between the panel
      coming to the front and the strip being rebuilt (it floated the panel
      and failed): the dock's verbs ignore anything that is not a frame.
- [x] **Names people use** (C9): nodeface.label. A pin's or a setting's
      key stays its key (the graph's files, expressions, MIDI's mappings),
      and what the node shows is its name in words: 78 of 249 keys were
      code (in_lo, e0, turns_a, gx, s3, c5, alpha_clear...) - Remap's "in
      low" and "out high", Smoothstep's "edge 0", Direction to's "round" and
      "up", a Steps "step 3", a Colour pick's "colour 5", the rest by rule
      (_lo "low", _hi "high", _ words); on the node, its column measured by
      them, its checkboxes, the properties, the add menu's description (the
      key after the name where it differs), the hover help, the pin menus,
      the expression box and the status lines; an expression takes the name
      too (in_low) and the key wins a clash; the node reference leads each
      pin with its name, its key after it in code, and its prose uses the
      names. A test holds no underscore on screen and no node showing two
      pins alike (Particles had a "burst" and a "burst_count": "burst
      size"). No slider keys: MIDI learn's targets and status, Sweep's
      picker and the Sequence's ramp (its picker, its line, its timeline
      label, the step's summary) name a slider by the effect's own words,
      two alike told apart by place. The Usermods dialog describes a
      feature by what it brings ("the cube's tilt, for Gravity and the
      motion effects"), its source files on hover; its audio row is led by
      its word. The footer's measures in words: brightness, contrast, unlit,
      saturation (was mean, sigma, dark, sat; engine.stats keeps the
      harness's maths). The panel's "pal source" is "colours from".
- [x] **Messages that stay** (C10): native/messages.py. A message went
      to one line beside the graph's file name - the whole sentence, cut
      by the pane, replaced by the next, with no history - and in the
      other layouts nothing showed it. Every message (some 270 calls post
      one) goes to the footer now, under its figures, in every layout;
      the graph pane's own line went. The latest shows short (its first
      clause, cut at a word), its whole on hover, red for a problem and
      amber for a warning (a note that reads like a failure - could not,
      failed, dropped - is one), and a click opens the log; a note leaves
      the line after 12 s, a warning after 30, an error stays until the
      next. A problem stays until it is fixed: a node the graph cannot use
      (judged again on every change - a rebuild, a hover's dimming - and
      logged once while it lasts, gone when fixed), a graph that does not
      compile (held unless its nodes' problems already say why), a build
      that failed (linked to its first error's line); the footer counts
      them in red and a click opens the log at them; a project switched
      drops the last one's, a graph renamed takes its own along. The log
      (Help > Message log, or the footer's log) holds the last fifty under
      the problems, newest first, with the time; one about a node or a
      line has go to - its graph opened (a sub-graph as if entered from
      the graph open, so back returns), the node selected and framed, or
      its effect at the line; a graph that does not compile goes to the
      node at fault, or frames the graph; one from another project says
      so. Opening a graph says so ("opened box_fire.json"). copy all,
      clear (the problems stay); a problem report carries the log. A
      value dragged on the running effect is one line that changes
      ("Noise #12 scale: 0.61 - live"), the same message again is counted
      (x3), and a frame that throws is posted as an error. The messages
      name a pin by its node and its words ("Remap #7 out low"): C9's
      leftovers in the expression box's answers and errors, back to the
      default, a splice, a setting promoted or exposed, and modulate with
      (its Remap's label too). The footer's line of layout keys went (Help
      and Settings > Keyboard shortcuts carry them). Found on the way: go
      to called the Q/E/W switch, which is the presentation mode - the
      graph pane came up with no interface; app.show_pane brings a pane up
      with it. Dear PyGui keeps a tooltip as the next item of a row, and a
      row whose first item drawn is a tooltip goes on the line above: the
      log button sat at the end of the stats line and the footer measured
      a row short, so the panes hid the row - the problems button hides
      with its tooltip now; a text after a small button sits its padding
      lower, so the line is a button with no slab. Picking a graph from
      the pane's list inside a sub-graph kept the trail down to the old
      one; it is left behind now. tests/test_messages.py (a problem logged
      once while it lasts, a readout merged and a repeat counted, the
      kinds, the short line and the text of the log, clear, the row on a
      real frame, a note leaving the line); the smoke's expectations read
      the messages posted since the last batch, and it goes to a node from
      another layout.
- [x] **Finding the way round the graph** (C11): Home fits the graph by
      the view alone - the node editor reports no position of its own, so
      the pan measured against its 0, 0 took in the editor's place and
      Home put the graph's corner at the screen's (20, 20), under the rows
      above the canvas; the editor's origin is worked out from its pane,
      and a smoke step checks every node lands inside. **A node's wires
      lit**: with the pointer on a node its wires are drawn brighter and
      thicker (x1.6) and every other wire fades to a trace of its colour
      (22%); on a pin, that pin's wires alone; the selection's wires stay
      lit while it lasts. The nodes stay as they are (focus mode, which
      dims them too, rules the wires while it is on); a frame lights
      nothing and a node over one wins; a wire's label fades with its
      wire; the wire a dragged node would splice into keeps its own dim.
      Nothing is rebuilt - the wires' themes change when what is lit does,
      looked at twenty times a second. View > Light a node's wires (an
      action a key can be bound to; kept in the prefs). **The minimap**
      (imnodes' own: a click on it moves the view) sits faint over its
      corner - the nodes under it read through - and comes up full while
      the pointer is at it; View > Minimap shows or hides it and picks its
      corner, or leaves it to one the 3-D view leaves free (a picked
      corner the view has goes to the other corner of that edge), both
      kept; in the theme's colours (it kept imnodes' dark ones on a light
      theme). Found on the way: a theme bound to the node editor never
      reaches imnodes' minimap (a probe: it kept the app theme's colour
      under an editor theme of another), so the app theme's own minimap
      colours are set in place, which a frame later shows; and the app
      runs as __main__, so native.app imported by another module is a
      second copy - the minimap's colour items live in graph_ui. The smoke
      lights a node's wires by selection and checks one faded, all back
      after, and the minimap's corner against the 3-D view's.
- [x] **Nodes spend their height on the work** (C12): the control nodes
      - Speed, Intensity, the customs, the checks, the first thing on
      every graph - spent both their rows on the effect's metadata; their
      label and default are the properties' now (ON THE WLED PAGE: named,
      starts at, or ticked at the start; nodeface.META), the node is its
      title and its pin, the title carries the label ("Speed: Rise",
      following an edit there, and undo), and its line says both
      ("“Rise”, 128 at the start") for the folded node, the stand-in and
      the help; selecting one brings the properties over the graph. The
      two ends of a range share a row (nodeface.PAIRS): Remap's "in  0 →
      1" and "out", Clamp's range, Smoothstep's edges, a Loudest bin's bins
      - two again when one end is exposed as a pin. The critique measured
      a Remap at 214 px; at 100% it is 185 now, a control node 75. The
      transfer curve's numbers were 8-px grey on the line: where the
      node's fields show
      the output's range (Remap, Clamp) it has none, elsewhere they sit in
      a column of their own at its right, in the monospace at the
      captions' size. The pattern previews (Checker, Stripes, Voronoi...,
      the Noise, an Image) were 48 x 24: the node's width now, 40 tall,
      from a 120 x 32 texture (the live Noise's costs 0.6 ms every other
      frame). arrange and the stand-ins count the rows a node spends
      (nodeface.param_rows). Stand-ins' summaries were fixed with the
      plain bugs. Found on the way: the properties over the graph were
      sized 18 px short of their content (an allowance of 52 for a caption
      row and three paddings of 10), so a note's last line scrolled out of
      sight. test_face holds the rows, the pairs and the lines; the smoke
      the title, one row for Remap's in, and an edit of the label in the
      properties.
- [x] **Keys kept to the canvas, a way out shown** (C13): Q, E, W, C, G,
      H acted anywhere outside a text box, so a stray H from the panel hid
      every control. A key on its own - a letter, a digit, a sign - acts
      with the pointer over the views (the 3-D view in its corner of the
      graph too) or the graph, or anywhere while presenting; from the
      panel, a frame, a dialog or the code it changes nothing and the
      footer says where it works (one line that changes, however many are
      pressed). Keys with Ctrl or Alt, Space, the F keys and Esc are as
      they were. Entering presentation puts a pill at the bottom of the
      picture for a few seconds, fading, with the keys as bound: "H or Esc:
      the controls back", or after Q / E / W "E again or Esc: back to the
      panels · H: the controls over the picture"; Esc leaves it (after a
      dialog or a frame with the focus has had it). The Keyboard shortcuts
      dialog and the guide say so. The smoke presses Q with the pointer on
      the panel, and enters and leaves presentation.
- [x] **Menus: a Window menu, a Build menu, no duplicates** (C14): the
      frames were spread over five menus, the builds in Playback, the
      project folder in Settings, Export usermod and Sequence twice each.
      Now File, Edit, View, Node, **Build** (Compile + reload, Live, Watch,
      Run as a script, Flash firmware, the build folder), Playback, Device
      (what is done to a device), **Window** (every frame - Devices, Send,
      Shape editor, Sequence, Library, Palettes, LED outputs, Audio input -
      checked while open, a click opening or closing it, with its key; then
      Snapshots, MIDI controller, the Message log, and Close every frame),
      Settings (Keyboard shortcuts with its Shift+F1) and Help; each command
      in one place (the shape's and the library's preview generators are
      their frames' buttons; the project folder is File > Project's).
      Edit's Delete, Delete and reconnect and Disconnect at the top. The
      **command palette** finds every menu command by its path as well as
      the actions - the graphs to open, the recent projects, the devices -
      and runs one as a click would (a check item turned over). A node's
      menu opens on what can be done - its title, a problem if it has one,
      then its actions with their keys and Delete at the top level - its
      documentation on the title's hover and its reference last; the add
      menu is its search and its nodes (undo, redo, paste and arrange have
      their keys and menus). Found on the way: the tutorial sent a script
      from "File > Project" (it was Device's). The smoke opens and closes a
      frame from Window, runs a menu command from the palette and reads the
      node menu's order and the add menu's first row.
- [x] **The toolbar** (C15): its graph tools show while the graph does
      (a zoom box read 120% over a net and a 3-D view - fixed with the plain
      bugs). The device and frame buttons were nine look-alike glyphs: they
      are words now while the toolbar has room for them - Devices, Flash,
      Send, Stream, then Shape, Sequence, Library, Palettes, Outputs and
      Audio in (new to the row) - and their icons when it has not (a narrow
      window, or the graph's tools shown: the row measured each third of a
      second against the window, the words' width as drawn once seen); a
      frame's word or icon is lit in the accent while the frame is open and
      a click opens or closes it, as the Window menu does; Stream is lit
      amber while it runs; the tooltips carry the keys either way. The
      smoke widens the window for the words, narrows it for the icons and
      opens a frame to see it lit.
- [x] **The two views** (C16): unlit LEDs were drawn black on a
      near-black ground, so a torus running Box Fire was a black blob with
      a lit rim. An LED that is off is a dim dot now (render.UNLIT, under
      most lit colours and over the black): in the middle of its cell on a
      cube's face (the software renderer by the fraction within the cell,
      the GPU cube in its texture - render.dotted), a smaller square in a
      point cloud (the GPU cloud has a dot behind every LED, made in pairs
      so the far-first order holds, and an unlit LED's own square goes
      transparent). The shape stands on a faint floor, a grid fading out
      from the middle, under the cube or the cloud's lowest LED, left out
      when the view looks up from below (drawn by the software renderer,
      and as segments in the GPU drawlists before what stands on them).
      Both are View toggles and actions, kept in the prefs; the popout
      does the same (a flag in its block); screenshots and recordings take
      the view as shown, the library's and the shape's previews ask for
      neither. The logical view fits its pane: whole pixels an LED as the
      pane's width and height both allow (it was fitted to a square of the
      smaller side). Found on the way: render._fill, added in eff4578, only
      called itself - dead, and it would have recursed without end - so it
      went. test_audit draws the dots (dots, not tiles, on a cube; smaller
      than a lit LED in a cloud; in the GPU texture and behind a GPU point)
      and the floor (and none from below); the smoke turns both off and
      on.
- [x] **Decoration that does not move** (C17): the pane in focus and the
      selected nodes wore a turning rainbow gradient - the only chrome that
      moved, in an app whose content is moving light. By default they wear
      a still outline in the accent now: the border alone, two pixels, no
      glow, following the accent when the theme changes. Settings >
      Selection frames picks the look - the outline, the gradient still, or
      the gradient turning (as it was), kept - and its gradients and the
      gradient creator are for the gradient looks. The smoke picks the
      turning look and goes back to the outline; a capture checked the
      outline and the still gradient identical a second apart.
- [x] **The footer** (C18): nine statistics and, under them, a
      permanent line of layout keys (that went with C10). The footer keeps
      the two figures most people want - the current the frame draws, with
      the limiter while it is working, and the frames a second on the
      device - and the speed and the LED under the pointer when they apply;
      its **stats** button opens the rest above it, live while open: the
      picture's brightness, contrast, unlit share and saturation; the
      effect's time, the device's (the factor, measured or estimated) and
      the studio's, split into polls, sim, draw and render; the current
      asked for and allowed and the limiter. The button again, or Esc,
      closes it; presenting hides it. The Welcome panel names the keys as
      bound (with the pointer over the views or the graph: Q, E, W, C, G,
      H, Space; every key under Settings > Keyboard shortcuts). Found on
      the way: the popover opened over its own button (its height is only
      known once drawn) - it is placed above the button each frame while
      open. The smoke reads the footer, opens the stats, checks they sit
      above the button and closes them with Esc.

The eighth pass is done: C1-C18 and the plain bugs, released as 1.2.0.

### Ninth pass: building a shape in 3-D (September 2026)

Building a shape was a form: parts typed into place in LED pitches and
turned by three Euler angles, the 3-D view only to look at (orbit and
zoom; no pan, no pick, no handles), every part in the effect's colour,
the wiring order only the list's order, a path's corners not editable
once made, no redo; a frame of ten "+ kind" buttons, import settings
always showing, fifteen AIM controls, arrange tools behind unlabelled
tick boxes and one-shot mirrors and arrays; and choosing "shape" added a
ring nobody asked for. The pass moves the building into the 3-D view
and makes the frame the inspector for exact values. (Sn) is the
proposal's number; in the order to do them.

**See what you're building**
- [x] **Parts in their own colours** (S1) while the Shape frame is open,
      the selected part bright and the rest dimmed, the effect's colours a
      toggle away; the part under the pointer named with its LED range
      and length. `native/shape_view.py` is the 3-D view's half of the
      editor: `colours()` recolours the view's LEDs (the GPU cloud's
      texture and the software renderer's alike) from the part each
      logical LED belongs to - golden-ratio hues, the preview's "parts"
      mode now reading the same `part_colour` - with the selection at full
      brightness, the rest at 0.38 and the part under the pointer at 0.72;
      the frame's "colours" switch (the parts / the effect) is kept in the
      prefs. The per-LED rings round the selected part went: the colour
      says it, at any count. The pointer's part is `pick()`: of the LEDs
      whose square is under the point, the one drawn on top - the nearest
      the eye (the nearest in screen distance let a neighbour nearer the
      camera win in a small view) - named in a label with its LED range,
      its size (a run's length for strips, rings, polygons and paths, else
      its box) and the LED's number and place in the part.
- [x] **The wiring on the shape** (S2): IN at LED 0, arrows along each
      part the way it runs, END at the last LED, each lead between two
      parts dashed and labelled with its length; any LED's number under
      the pointer. Each part's line runs through its LEDs in wiring order
      in its colour, faint - the selected part's in the text colour, as
      its own would vanish into its LEDs - with chevrons spaced along its
      path on the screen; a lead is the gap from one part's last LED to
      the next's first less the LEDs' spacing (so a part butted on at one
      spacing is a join and draws nothing), its label beside the dashes
      and kept off IN and END. The whole overlay keeps off what floats
      over the view (`visible()`, vectorised) and is redrawn each frame.
- [x] **A camera for building** (S3): pan (middle-drag, Ctrl+drag),
      Front / Side / Top / Perspective on the view and on keys, frame the
      selection (F) and everything (Home), an orthographic view, the grid
      marked in real units; the view's frame held while editing so a moved
      part does not rescale everything. `render.Cam` is the one camera the
      software renderer, the GPU cube and cloud, the overlays, picking and
      the hover readout share: yaw, pitch and dist as before, plus `look`
      (the point it circles, in the fitted space) and `ortho` (every depth
      at the scale the look point has in perspective, so switching keeps
      the size; the eye stood well back so the depth order holds), with
      `screen()`, `scale()` and `ray()`. `native/view3d.py` drives it:
      presets eased over 0.22 s (and an ease given more while one is under
      way keeps the first's targets - a view key then Home both arrive),
      orthographic for the six along the axes and back to perspective when
      the view is turned by hand (Blender's auto-perspective), the pan at
      the look point's depth, F framing the selected parts' LEDs, Home the
      lot; the buttons at the view's top right; keys in a new "view"
      context - 1, 3, 7 (Ctrl: the other side), 0, 5, F, Home - that apply
      with the pointer on the view and shadow a global binding there
      (`Keymap.set` no longer unbinds one for the other). While the frame
      is open the view's frame is held from when it opened; a part added
      or imported outside it grows it (eased), a move never refits.
      **View > Camera's "front" had been the back**: the presets follow
      the shapes' axes now (the front from -Y, X to the right, Z up - what
      a panel faces and the grid layout projects onto), so a cube's front
      is its S face. `native/units.py` gives a shape a density (60 LEDs a
      metre unless set) and a unit (cm) - display only - and ruler steps
      (1-2-5, and inches' eighths to feet) for the floor, whose lines now
      fall on round distances through the world's origin (a pool of line
      items on the GPU, as a step sets how many) and are named at the
      view's foot with the camera's keys. Tests: `tests/test_view3d.py`
      (units, the projections and rays, a pan, the floor's lines, the
      parts' colours and runs) and the smoke's S1-S3 steps; a test hook
      `led_at` finds an LED on the screen and stands in for the pointer
      over it (a test's process cannot bring the window to the front).

**Move things directly**
- [x] **Pick in the view** (S4): click a part to select it, Shift-click
      to add or take away, Shift-drag a box; the list's tick boxes go.
      The shape has a selection now - a set and the active part (the last
      picked, the one the frame shows and the arrange tools line up to) -
      in `shape_ui.select()`; the list's rows select alike (Ctrl or Shift:
      more than one) and the tick boxes and "tick all" are gone. A press
      on the view that does not move is a click (a moving one turns the
      view, as ever); Shift makes a press a toggle or, dragged, a box;
      hidden and locked parts are passed over (`shape_tools.pick`).
- [x] **Handles** (S5): arrows to move along an axis, squares to move in
      a plane, rings to turn, snapping to the grid step and 15 degrees
      (Ctrl frees it); Blender's keys over the view - G, R, S, then X / Y /
      Z to lock, a typed number, Enter, Esc to cancel. `native/
      shape_tools.py`: the handles sit on the middle of the selected
      parts' places, drawn on the overlay, an arrow shortened as its axis
      points at the eye and left out under a fifth; the snap is not the
      floor's step (20 cm is coarse for a strip) but the ruler division
      nearest ten pixels at the handles' depth, applied to the place, not
      the step - a part lands on round numbers. Move and Turn buttons join
      the view's own while building. G, R and S (a view key context shared
      with the camera's; G the graph pane otherwise) follow the pointer each
      frame until Enter, a click, Esc or a right-click; X, Y, Z toggle the
      axis (drawn through the pivot), digits, a point and a minus type an
      exact amount in the shape's unit, degrees or a factor. A move is
      previewed as the same LEDs in new places - the geometry the move
      began with, its positions replaced - so the engine is not touched
      and the layout stays as it was until it is kept, one undo step. Two
      bugs on the way: Enter in the frame a number was typed applied the
      pointer's move (a move is brought up to date before it is kept), and
      on the grid layout a turn changed which LEDs shared a cell, so the
      preview (then a rebuilt geometry) was refused for its count and the
      turn lost - which also showed the GPU cloud could not take a new
      count at all: its colour texture was deleted while the background
      picture still drew it, and the name stayed taken
      (`PointQuads.set_points` remakes the picture first; an audit test).
- [x] **Snap to join** (S6): a part dragged near another's end lands one
      LED spacing beyond its last LED, and goes after it in the wiring.
      `shapes.ends()` gives a part's first and last LED in the shape and
      the way the strip runs at each; a lone moving part's first LED
      within 16 px of another's end continued by its spacing snaps there
      (on an axis only if the target is on the axis line), the target
      ringed and named ("join after ring 1"); kept, the part moves in the
      wiring to just after that part (its last LED near a first: just
      before), with a message saying so.
- [x] **A part's menu in the view** (S7): duplicate and move, mirror,
      repeat, reverse, move in the wiring, frame, rename, hide, lock,
      light it on the device (the wiring test), delete. A right-click on a
      part (it is selected first); its rows are the selection's where that
      reads right ("Frame them", "Delete them"). Hidden parts are dark in
      the view while building (either colouring), draw no wiring and are
      not picked; locked parts are not picked or moved (the list still
      selects them); both flags are the part's, saved with it, and named
      in the list. "Light it" runs the wiring test's part mode on that
      part (the sim shows it while it runs - the parts' colours step aside
      - and the device while the sim is streamed). "Repeat" waits for the
      live copies (S12); mirrored copies are the old one-shot kind until
      then. A test hook (`tool`) drives the pointer's part of all this -
      press, drag, release, right-click at an LED, a part, a handle or a
      spot on the view, Shift or Ctrl held - and the smoke runs S4-S7
      with it.

**Real sizes, real objects**
- [x] **Real units** (S8): the shape's LED density (30, 60, 96, 144 a
      metre or a spacing) and a unit (mm, cm, in); strips by length or
      count, rings by diameter, leads in centimetres. The display only:
      the device's table is fitted to its box as before; old shapes open
      at 60 a metre. The shape's settings (nothing selected) set both;
      `native/shape_fields.py` gives every kind its natural sizes as
      fields - counts, lengths in the unit, a density as LEDs a metre,
      angles, text - with a "work it out" setting (a ring's radius at 0)
      shown as what it comes to until typed (a polygon's and a star's
      across their corners, which have no LED); a strip's length typed
      sets its count. Positions, a path's corners, copies' steps, the
      working plane and AIM's distance are in the unit too.
- [x] **Add from a gallery** (S9): a thumbnail per kind, grouped (lines,
      flat, solid, free, from a file), each asking its natural sizes; the
      new part joined to the end of the selected one. `native/
      shape_gallery.py`: the pictures are the kinds' LEDs drawn dim to
      bright along the wiring (once, as textures); a picture asks its
      fields marked "ask" and says what the part comes to and where it
      goes. A line (strip, path, arch, helix, spiral) is joined on - its
      first LED one spacing past the selected part's last, turned to run on
      the same way (`shapes.ends`); anything else beside it, its foot level;
      either way next after it in the wiring. The frame's "+ kind" buttons,
      and the old placing "to the right of the last", went with it (the
      test hook's add uses the gallery's placing).
- [x] **The shapes people light** (S10), xLights' model types the
      checklist: tree (strands down a cone, or a spiral), star, helix or
      spiral, arch, concentric rings, frame (window, door, screen, room
      edge), spokes; and a formula part - x, y and z as expressions of the
      place along it, Pixelblaze's mapper's way. The xLights layout import
      maps its trees, stars, arches, spinners and window frames onto them.
      Each in `shapes.py`: a tree's strands evenly along a cone or a spiral
      (up one, down the next), a star's edges centred between its points, a
      helix's LEDs a spacing apart along it with the turns its length makes
      over the height given, a flat Archimedean spiral sampled until it is
      the strip's length, an arch's LEDs evenly along an elliptic arc on its
      feet, rings in rings (counts from the middle out; each sized by its
      LEDs or a gap), a frame's sides (three with no bottom, from any
      corner, either way round), spokes back and forth; a formula's x, y
      and z parsed once (`expr.compile`) and worked out per LED, a bad one
      named in the frame. A part's LEDs are cached by kind and settings (a
      drag re-resolves every frame). The xLights reader: Tree (strings x
      strands, turns, the bottom/top ratio, the degrees in its name), Star
      (its points and ratio), Arches (an arch part each, side by side),
      Spinner (spokes), Window Frame (its counts, the sides stretched to its
      height) - tests for each kind's spacing and for the import.
- [x] **Draw a run** (S11): click corners on the working plane (the grid
      and 15-degree snapping, the length in centimetres and LEDs as it
      grows); the corners handles afterwards, and a table in the frame.
      `native/shape_run.py`: the plane is the one the view faces most (from
      above a floor level with the last corner, from the front or side a
      wall), so 7, 1 and 3 draw flat, upright and side-on runs; the first
      corner also snaps onto a part's end (a run carried on); the run
      becomes a path part after the selected one. A lone selected path's
      corners are squares to drag - a longer or shorter path goes through
      the engine as it is dragged, its count changing - and a table: x, y,
      z in the unit, one put in halfway to the next, deleted, the path
      reversed, drawn on from its end.
- [x] **Live copies** (S12): repeat (a count, a step, a turn a copy, round
      a centre, every other one reversed) and mirror as settings of a part,
      exact mirrors; "make separate" when one copy needs its own change.
      `shapes.with_copies` repeats a part's LEDs in the shape - each copy
      moved by the step and turned about the axis through its middle or the
      origin, every other one run back - then mirrors them all across the
      planes ticked (exact: the positions negated, no turn), run back if
      asked; one part in the list and the wiring, `part_count` counting
      them. `shapes.separate` gives them as parts again with the LEDs where
      they were (copies the same kind, moved and turned; mirrors loose
      points). The one-shot mirror (a rotation "near enough") and array
      went; the part's menu mirrors and repeats live.

**The frame as an inspector**
- [x] **What the selection needs** (S13): nothing selected, the shape
      (density, units, layout, segments, a File menu); one part, its size,
      its place (flat / upright / outward and 90-degree turns, the exact
      angles folded), its copies and its wiring; several, align, spread
      and match. The import settings move into the import dialog. The
      frame's top: Add part, Draw a run, File (open, save, import, a
      reference, the exports, a preview, clear - a popup), Undo, Redo. A
      part: SIZE (its fields; a path's corners; a solid's split; loose
      points' tools and BY HAND), PLACE (the position in the unit; lie
      flat, upright or facing out from the shape's middle; turn 90 degrees;
      folded, the exact angles, the scale and AIM - the fold stays as it
      was left), COPIES, WIRING (the other way, its place in the wiring,
      light it). Several: align, spread, same scale, same turn, lie and
      turn each, group. The audit's rule that a word after a field is its
      label caught the working plane's "at".
- [x] **The list is the wiring** (S14): rows dragged to reorder, a swatch
      in the part's colour, the LED range, reverse as an arrow, hide and
      lock, groups. Drawn icons for the way a part's LEDs run, shown or
      hidden and locked (icons.py); a row dropped on another wires the part
      there; right-click a row for the part's menu (one handler for every
      row). A group is a name on its parts: a heading in the list before
      each run of them selects them all, "group them..." and "ungroup" in
      ARRANGE, and the part's menu selects its group.
- [x] **Undo and redo** (S15) as the rest of the studio has them: Ctrl+Z
      and Ctrl+Y over the view or the frame, a drag one step, the steps
      named in the undo history. A redo stack beside the undo one; Ctrl+Z
      and Ctrl+Y act on the shape with the pointer on the 3-D view while it
      is built (and with the frame's keyboard, as before); each step named
      from what changed ("moved strip 1", "added tree 1", "re-wired",
      "deleted ring 1", "changed the shape's density") and Edit > Undo
      history lists the shape's steps when the shape is what Undo acts on.
- [ ] **Checks as you build** (S16): two LEDs on one spot, a long lead, a
      total that is not the outputs' count, the power - each with a "show
      me" that frames it.
- [ ] **A starting point** (S17): an empty editor offers objects (matrix,
      cube, sphere, tree, star, ring disc, room outline), drawing a run,
      importing a model or an xLights layout; choosing "shape" changes
      nothing until one is picked.

**From the real object**
- [ ] **Map by camera** (S18): for lights that follow no pattern, the
      device lights one LED at a time, a webcam finds each, photos from
      two or more sides give 3-D, a missed LED is filled from its
      neighbours in the wiring. The method of Matt Parker's 2020 tree ("I
      wired my tree with 500 LED lights and calculated their 3D
      coordinates"; standupmaths/xmastree2020). Tested against a
      synthetic camera; never the cube.
- [ ] **The guide and the tutorial** (S19) rewritten round the new flow:
      GUIDE's shape section, a tutorial chapter building a tree.

### Line-in (September 2026)

- [x] **A line-in module on the device.** The fork's audioreactive reads
      both channels of a line-in source - type 4, "generic I2S with a
      master clock" (a PCM1808 or WM8782 ADC breakout), and type 6, an
      ES8388 codec board's line input - averages them to mono and takes
      the DC offset out with a first-order high-pass (`I2SSource`'s
      `stereoMix`; a microphone keeps the one-channel path), and reports
      the level it hears in /json/info (`u.AudioReactive["Input level"]`).
      The studio's **Audio input** frame (`native/audioin.py`,
      `audioin_ui.py`; Device menu, Ctrl+Shift+M): a preset per module
      that sets the usermod's type, the pins a board fixes (AudioKit,
      LyraT), the levels a line signal wants; read from the device, sent
      over /json/cfg with the reboot a type or pin change needs offered;
      a meter that polls the level; and the same settings as the studio
      env's build flags (`SR_DMTYPE`, `I2S_*PIN`, `MCLK_PIN`, `SR_GAIN`,
      `SR_SQUELCH`, `SR_AGC`, `I2CSDAPIN`/`I2CSCLPIN`), so a fresh flash
      boots with them. The fake WLED models the usermod's config, the
      reboot and the level; `tests/test_device.py` and the smoke test
      cover the round trip. Untested on real hardware yet: a PCM1808 or
      an ES8388 board on the cube - the wiring and the levels need a
      listen.

### Completeness (September 2026)

What would say the studio is complete, in the order to do them:

- [x] **A fake WLED device** (`tests/fake_wled.py`): an HTTP server with
      `/json/info`, `/json/effects`, `/json/state` (psave written a beat
      later from a "loop", a second psave before it replacing the one
      pending, a playlist stored only with "o", pdel, ps, pl, rmcpal),
      `/presets.json`, `/upload`, `/json/cfg` (timers cleared then set,
      the LED outputs) and a DDP counter - so every device path is
      exercised by the tests and CI, offline. `tests/test_device.py`
      drives the modules against it (11 tests); the smoke test sends
      everything to it and checks each frame's log with the `expect`
      hook. It found one real bug on its first run: a sequence whose
      effects the device does not have crashed the send's summary
      (`min()` over the skipped key), leaving the log at "sending..."
      and the buttons off for good.
- [x] **A node census** (`tests/test_nodes.py`): every node type alone
      in a minimal graph (every output folded into the Output), compiled
      to C++, all 126 built into one engine by the toolchain and each run
      for 40 frames; then through the script compiler - 91 scripted and
      run in the Script effect, 35 refused, each as a ScriptError that
      names the node. Found: Sprites and Shells without their slots wired
      were a C++ error (`gc_st` undeclared) instead of a graph problem -
      now a "must be wired from" error on the node, and Split was not
      scriptable for its shifts (it reads the channels through
      `gc_col2v` now). Found beside it: the object cache did not know
      which compiler made an object, so objects the bundled g++ made for
      a package were handed to clang and MSVC's linker ("invalid or
      corrupt file") - the compiler is in the stamp now.
- [x] **Sad paths**: a wire between types that do not convert (an error
      on the node it lands on, and the compile names both ends), a wire to
      a node or pin that is not there (dropped on load, counted in the
      status), a graph without its Output, a C++ effect that does not
      compile, a device that is off, a missing engine (built at start
      from the project's effects, or the app exits saying why) - each a
      status line, never a traceback; the smoke test walks them with the
      `expect` hook, `tests/test_graph.py` the graph ones.
- [x] **A frame-button walk and an action walk**: `tests/walk_menus.py`
      now also clicks every button of every frame, of the settings-type
      windows (keys, appearance, selection frames, history, undo, about,
      usermods) and of the panes (`frame_walk`: 190 buttons; the sends go
      to the fake WLED it starts; flashing, rendering, cloning, recording
      and the desktop are skipped), and runs every keymap action
      (`action_walk`: 82, toggles twice, the graph undone after each).
      894 rows, none failing.
- [x] **Script / C++ parity** (`tests/test_parity.py`): every census
      graph and every scriptable example as its compiled effect and as
      bytecode in the Studio Script effect, in the same engine from the
      same millisecond (`simNowSet`, a warm-up frame so both dt stores
      read 23 ms) with the same fake audio, the last ten of forty frames
      compared: 114 graphs, 111 within a mean of 4/255 (most exactly 0),
      the three with a Random hold apart by design. Found: an unwired
      colour input (a packed 0) was white in the script and black in
      C++; a `(uint8_t)` cast of a negative (a palette index below 0)
      clamped in the script where C wraps - both in the compiler.
- [x] **Round-trip serialisation** (`tests/test_roundtrip.py`): every
      example and project graph loaded, saved, loaded - the same JSON,
      the same C++, migrate() idempotent; every geometry kind (a mapped
      strip, a shape of parts, the soccer ball, a grid layout) through
      to_json / from_json with the same LEDs, places and wiring; a
      ledmap read back; a project's geometry, options and imports; the
      sequence's presets.json; the engine's segments (bounds, effect,
      options, blend); an xLights model written and read; and the 194
      older graphs the history holds all open and compile.
- [x] **A scrubbed-PATH run of the packaged app**: the package (built
      with the toolchain it ships, so its objects are the bundled g++'s),
      its doctor and the smoke test run with PATH cut to System32 - the
      bundled g++ builds (the smoke test now expects "loaded cubefx_"
      after a compile), every send reaches the fake device; and with no
      git on the path `wledtree.fetch` brings the fork as GitHub's zip
      (9 s). The release workflow's smoke test runs scrubbed too.
- [x] **A soak** (`tests/soak.py`, `--minutes` for a short one): the app
      driven for ten minutes - an effect every step, geometries, layouts,
      frames opened and closed, a graph compiled now and then - with the
      `stats` hook sampling RSS, Dear PyGui's item count and the frame
      times; the second half judged against the first. Found: three
      stock audio effects (Ripple Peak, Puddlepeak, Waterfall) wrote to
      audio slots the sim never provided - an access violation in the
      engine; and every `with dpg.texture_registry():` left an empty
      registry item behind (one per geometry change, build, thumbnail)
      - one registry now (`native/textures.py`). 197 steps: RSS 119 →
      133 MB (a plateau from minute six), items steady.
- [x] **A docs cross-check**: GUIDE.md ends with a reference section -
      every menu item with its key, every key action, every button of
      every frame, window and pane with its tooltip - written from the
      running app by `python tests/make_uiref.py` (the `uiref` hook);
      `tests/test_docs.py` fails when a menu item, action or button in
      the source is not named there. Run make_uiref after adding one,
      as nodedocs is run after adding a node.
- [x] **Audits** (`tests/test_audit.py`): every effect in the roster on
      every geometry kind for five frames (1,575 runs, none faulting);
      the stock effects the sim leaves out listed with their reasons (2
      of the 2-D ones, 16 of the 1-D) and the count held; the GPU view's
      square for every LED against `render.project`, and the cube's face
      corners against `render()`, for every geometry kind and twelve
      cameras - within a hundredth of a pixel.
- [x] **Product**: undo for the segments, the sequence's steps and
      schedule, and the palettes - the project journals every save that
      changes one of those options (`Project.undo/redo(key)`, forty
      deep, per option), Ctrl+Z / Ctrl+Y go to the frame with the focus
      (floating, or docked and last clicked in) and each frame has an
      `undo` button, the segments row too. File › Project › Export
      project as zip (`project.zip_project`: everything but the history
      and the export folder, into captures/) and Import project from
      zip... (`unzip_project` into projects/, a taken name numbered, a
      stray zip refused, nothing written outside the folder). Help ›
      Report a problem... (`native/report.py`): version, the doctor's
      findings, the machine, the project's settings with device
      addresses blanked, the prefs, the last crash tracebacks and the
      last 300 lines printed, as one zip in captures/, with the issues
      page a button away - nothing of the user's effects or graphs.

- [ ] A Linux / macOS pass. What is there: `paths.py` puts the home in
      `~/.local/share` or `~/Library/Application Support`, the toolchain
      takes clang or gcc from the path (`-fPIC`, `.so` / `.dylib`,
      `-undefined dynamic_lookup`), every Windows-only call (drag and
      drop, the loopback capture, the popout's parent check, the test
      hooks' real clicks) is behind a platform check, `run_studio.sh` is
      the launcher, and `studio.spec` skips the .ico off Windows. What is
      not: none of it has been run there yet - this machine has no Linux
      or macOS to hand (WSL holds only Docker's distro, and Docker Desktop
      would not come up). The pass, when a machine is there: `python3 -m
      native.doctor`, `python3 build.py --native-only`, the four test
      scripts, `python3 package.py` (PyInstaller builds for the platform
      it runs on; no toolchain bundling - the system compiler), and the
      things that only show on a screen: fonts, the viewport's flags, the
      audio device list.
- [x] Housekeeping first: the studio no longer assumes a cube anywhere a
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
  crack opens between them. Settings > "Draw the 3-D view on the GPU" turns it
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
