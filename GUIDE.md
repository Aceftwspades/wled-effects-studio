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
every control - a pill at the bottom says how to come back, and **Esc**
does too; **space** pauses. A key on its own - a letter, a digit, a sign -
acts with the pointer over the views or the graph (or while presenting):
a stray one from the side panel, a frame or the code changes nothing, and
the footer says where it works. Every key is on the menus and under
Settings > Keyboard shortcuts (Shift+F1), where any can be changed. The
menus are File, Edit, View, Node, **Build** (compile, Live, Watch, run as
a script, flash the firmware), Playback, Device (what is done to a
device), **Window** (every frame and window - checked while it is open, a
click opens or closes it, and Close every frame), Settings and Help; each
command is in one place. The **command palette** (Ctrl+P) finds any of
them by name - every action and every menu command, the graphs to open
and the recent projects too; Enter runs the first. Every control
explains itself on hover; a dim **(?)** at the end of a row holds what
the row as a whole is for. Buttons say what they weigh: the one a dialog
or a frame is for is filled in the accent, one that changes a device or
deletes something is red, a way out (Cancel, Not now) has no slab. The
pane last clicked in and the selected nodes wear a still outline in the
accent; Settings > Selection frames can make it a gradient - a WLED
palette, the studio's own, or one made there - still or turning. What
has nothing to act on is greyed - on the menus, the toolbar and in the
frames: Delete with nothing selected, Undo with nothing done, a send
with no device - and its key says why instead. An empty list says what
it would hold and offers the next step (the Send frame with no device:
**Find a device**). The toolbar's
graph tools (zoom, Home, add, delete, arrange, fold) show while the graph
does, and its right half is the device and the frames - in words while
the window is wide enough for them, as icons when it is not: Devices
(Ctrl+Shift+N), Flash (Ctrl+Shift+U), Send (Ctrl+Shift+S), Stream (the
DDP stream on or off, Ctrl+Shift+T, lit amber while it runs); then Shape
(Ctrl+Shift+E), Sequence (Ctrl+Shift+Q), Library (Ctrl+Shift+L), Palettes
(Ctrl+Shift+G), Outputs (Ctrl+Shift+O) and Audio in (Ctrl+Shift+M). A
frame's word (or icon) is lit in the accent while the frame is open, and
a click opens it or closes it, as the Window menu does. Playback >
Randomise is Ctrl+Shift+X.

**Type and size.** The interface is set in the system's own face (Segoe
UI on Windows) at the system's own size: a frame's title larger and
heavier, the capitals over a group of controls (STEPS, ON THE DEVICE)
smaller and heavier, a caption beside what it belongs to - a count, a
size, a key - small. Code, the logs, the footer's figures, the
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
View > 3-D view over the graph) brings it back. The **minimap** sits
faint over its corner of the graph - the nodes under it read through -
and comes up full when the pointer reaches it; a click on it moves the
view there. View > Minimap shows or hides it and picks its corner (or
leaves it to one the 3-D view leaves free; a corner the view has, it
cedes to the other corner of that edge). A node's long settings (bitmap rows,
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

**Messages.** What the studio has to say - a build's result, a graph
that will not compile, a value set live, MIDI learn, an expression's
answer, a send to a device - comes up in the **footer**, under the
figures, in every layout: the latest message, short (its whole on hover,
and a click opens the log), red for a problem, amber for a warning. A
note leaves the line after a while and a warning later; an error stays
until the next message. A **problem stays until it is fixed**: a node
the graph cannot use (a wire between types that do not convert, a
Receive with no Send), a graph that does not compile, a build that
failed - the footer counts them (**2 problems**, in red) and a click
opens the log at them; they go by themselves once fixed. The **message
log** (the footer's **log**, or Window > Message log) holds the last fifty,
newest first under the problems; one about a node or a line of code has
a **go to** that opens its graph with the node selected and framed, or
its effect at the line. A value dragged on the running effect is one
line that changes, not fifty; the same message again is counted (x3).
**copy all** puts the log on the clipboard, **clear** empties it (the
problems stay), and a problem report (Help > Report a problem) carries
it.

## Making an effect

**As a graph.** Ctrl+N, name it, and the graph pane opens with a starter.
Right-click the grid to add a node (type to search); drag from a pin to a
pin to wire, or to empty space for a list of what could go there. A
node's fields line up after their names, and a node spends its height
on what it computes: the two ends of a range share a row - Remap's
"in  0 → 1" and "out  0 → 1", Clamp's range, Smoothstep's edges, a
Loudest bin's bins. A control node - Speed, Intensity, the customs, the
checks - is a title and its pin: what the WLED page calls the slider (or
the box) is in its title ("Speed: Rise"), and that name and where it
starts are set in the properties (select the node; ON THE WLED PAGE).
Every **number** - on a node,
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
name, `rand()`; Enter sets it, Escape leaves it. Pins and settings go by
names in words - Remap's "in low" and "out high", Smoothstep's "edge 0",
a Steps node's "step 3" - where their keys are code (`in_lo`, `e0`,
`s3`); an expression takes either (`in_low` or `in_lo`), and the node
reference gives both. Likewise a slider is its effect's own name
everywhere (MIDI learn, Sweep, a sequence's ramp), not its key. Two
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
the command palette and Ctrl+Alt+Z the undo history. **A node's wires
light up**: with the pointer on a node its wires are drawn brighter and
thicker and every other wire fades to a trace of its colour - on a pin,
that pin's wires alone - and the selection's wires stay lit, so one
node's connections can be followed across a busy graph (View > Light a
node's wires turns it off; focus mode, `/`, dims the other nodes too).
**Snapshots**
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
a dot riding it, the Noise's texture scrolling with its z, previews the
node's width of Checker, Stripes, Ripple, Voronoi, Brick, Mandelbrot and
the Gradient at their typed values, the transfer curve of Remap,
Smoothstep, Clamp, Threshold, Power and the other one-in one-out maths
nodes (its output's range written beside it, clear of the line, where
the node's fields do not show it already), a Bitmap's
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
in either view: its wiring index, its part, its position. It keeps the
two figures most wanted - the current the frame draws (and the limiter,
when it is working) and the frames a second on the device - and its
**stats** button opens the rest, live while it is open: the picture's
brightness, contrast, unlit share and saturation; the effect's time, the
device's (and how its speed factor was found) and the studio's own,
split into its parts; the current asked for and allowed. The button
again, or Esc, closes it. A **MIDI
controller** (Window > MIDI controller...) puts its knobs on the
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

**The 3-D view** turns by dragging, **pans** by a middle-drag (or
Ctrl+drag, on a touchpad) and zooms by the wheel; it turns round the
point it was panned to. The **Front**, **Side** and **Top** buttons at its
top right, and the number keys with the pointer on it - 1 the front, 3
the right side, 7 above, with Ctrl the opposite side, 0 the isometric view
(Blender's keypad, on the number row too) - ease the camera round to look
straight along an axis, and make the view **orthographic**: no
perspective, so a size is the same across the view and parts line up
true. 5 (or the button beside them) switches orthographic and perspective;
turning the view by hand goes back to perspective. **F** frames the
selection (in the shape editor, the selected parts; else everything) and
**Home** brings everything back into view. The axes are the shapes': the
front is seen from -Y, X to the right and Z up. View > Camera has the same
presets, three saved views (the pan and the projection kept with them),
and a **background picture** - the room, the house - dimmed
behind the LEDs, for the point cloud and the GPU cube alike. An LED that
is off is a **dim dot** there (smaller than a lit one, in the middle of
its cell on a cube's face), so the shape reads when most of it is dark,
and the shape stands on a faint **floor** that fades out from the middle
(left out when the view looks up from below it) - View > Unlit LEDs as
dim dots and View > A floor under the shape turn them off; a popped-out
view does the same, and a screenshot or a recording takes the view as
it is shown (the library's and the shape's previews leave both out). The
**logical view** fits its pane: as many whole pixels an LED as the
pane's width and height both allow (a wide net in a tall pane was drawn
as if the pane were square).

## Any shape: the shape editor

Window > Shape editor (Ctrl+Shift+E), or GEOMETRY > shape, opens the
**Shape** frame - in the dock like the Device ones, and floats the same
way. A shape is a list of **parts** in wiring order - strips, rings,
panels, trees, stars, arches, paths, loose points and more - and the LEDs
run through them part after part. You build it in the **3-D view**; the
frame is where the exact values are. At its top: **Add part...**, **Draw a
run**, **File...**, **Undo** and **Redo**. Under them the parts in wiring
order, and under that what the selection needs: with nothing selected,
the shape's own settings; one part, its sizes, place, copies and wiring;
several, lining them up.

**Real sizes.** A shape is measured in LED spacings; its **LEDs a metre**
(30, 60, 96 and 144 are the strips sold, or type any other) says what a
spacing is on the bench - 60 a metre is 1.67 cm - and **lengths in** picks
mm, cm or inches. Every length in the frame and the view is in that unit:
a strip's length, a ring's diameter, a lead's gap, the floor's squares.
Only what is shown changes - the device gets the shape fitted to its box as
ever. (Both are the shape's own settings: click on nothing to see them.)
A part can have a strip of another density: its own **LEDs a metre**.

**A starting point.** With no parts yet, the list is a start: objects
people light, ready to size - a matrix, a cube, a sphere, a Christmas tree,
a star, the 241-LED ring disc, a room's ceiling outline, a window, an
infinity cube, a soccer ball, a helix column, a spiral disc - each opening
the gallery below on its sizes; or **Draw a run**, **Import a model or a
layout...**, **Map lights by camera...** (below), or **Any part...** (the
whole gallery). Choosing "shape" under GEOMETRY opens this and changes
nothing until the first part goes in.

**Checks as you build.** Under the tools, what is likely a mistake or will
matter on the bench: LEDs sitting on another (two parts laid over each
other, a copy left on its part), a lead of a metre or more (a data wire
that long may want a buffer, or a sacrificial LED near the controller), LED
outputs carrying another count than the shape, the current at full white
against the limiter's ceiling, a formula that does not work out, parts
hidden, LEDs of mapped lights no two sides of the films saw - each with
**show me**, which selects and frames it (or opens the Outputs frame).

**Adding parts.** **Add part...** opens a gallery of pictures - LINES
(strip, path, arch, helix round a tube, flat spiral), FLAT (ring, rings in
rings, polygon, star, spokes, frame for a window or a door, panel), SOLID
(cube, cylinder, sphere, tree, a solid's edges) and FREE (loose points, and
a **formula**: x, y and z as expressions of t, i and n) - and FROM A FILE.
A picture asks its natural sizes in the unit (a tree: strands, LEDs a
strand, height, across the base) and says what it comes to (240 LEDs, 30
x 30 x 50 cm) and where it will go: a line **joined to the end of the
selected part** - its first LED one spacing on from that part's last,
running on the same way - anything else **beside** it, its foot level
with it; either way next after it in the wiring, and selected. **Add
another** keeps the gallery open.

**Draw a run** lays a strip where you click: corners on the plane the view
faces most - from above (7) the floor, from the front (1) or the side (3) a
wall - the first snapping to a round distance (or onto a part's end, to
carry its run on), each run after it to a round length at 15 degrees (Ctrl:
no snapping). As it grows the view shows its LEDs, each run's length, and
the whole in the unit and in LEDs. Enter, or a click back on the last
corner, ends it; Backspace takes a corner back; Esc leaves.

**Mapping lights by camera** (**Map lights by camera...**, in File... and
the start) is for lights in no pattern - a string wound round a real tree,
lights along a hedge. The studio plays a **plan**: a white flash, each LED
alone in wiring order for **each lit for** (0.2 s: a camera at 30 pictures
a second catches each one five or six times), then a white flash again.
The sim shows it, and the device does while the sim is streamed to it
(**Stream the sim to the device**, Ctrl+Shift+T - the device gets the
plan's own frame of **LEDs**, whatever geometry the sim has). Set **LEDs**
to the device's count, darken the room, stand the camera on something
still with the whole object in view - well back and zoomed in, since the
places come out truest from far off - press **Play the plan**, and film all
of it: the two flashes line the film up with the plan, whatever the
camera's clock or the stream's delay. Turn the object a quarter (or move
the camera round it, as far off and as high) and play and film again. Each
side gets its angle, anticlockwise seen from above, and **Add its film...**
(an mp4, mov, avi, mkv or webm, read with ffmpeg, which has to be on the
PATH); its card then shows the picture with the LEDs it found marked.
**+ a side** adds another angle; **Stop** ends the plan part way. With
**its height** measured, **Make the part** puts the lights in the shape as
a points part in wiring order, sized to it: from two sides or more in 3-D,
from one side flat as it faces the camera (a window, a wall). An LED no two
sides saw is estimated from its neighbours in the wiring: the checks list
them, the view rings them in amber while the part is selected, and with
BY HAND's **place** ticked each drags to where it really is. **Film with
the webcam** does a side with no video file when OpenCV is installed (`pip
install opencv-python`): the plan plays while the webcam takes its pictures.

**Building in the 3-D view.** While the frame is open the view shows each
part in a colour of its own - the selected ones bright, the rest dimmed
("colours" switches to the effect the sim runs) - and the **wiring drawn
on the shape**: IN at the first LED, END at the last, arrows along each
part the way its LEDs run, and every **lead** from one part's last LED to
the next part's first dashed and labelled with its length (a gap of one
spacing is a join and is not drawn). The part under the pointer is named
with its LEDs and size and the LED's number. The view keeps its scale
while you build; a part added outside it grows it, and Home fits it again.

- Click a part to select it (on nothing: none), Shift-click to add one or
  take it away, Shift-drag a box to add every part with an LED in it; the
  list selects the same way (Ctrl or Shift for more than one). The frame
  shows the last one picked - the **active** part.
- The selection wears **handles**: drag an arrow (X red, Y green, Z blue)
  to move it along that axis, a square between two arrows to move it in
  their plane, the ring in the middle to move it in the screen's plane -
  its place snapping to a round distance that follows the zoom (Ctrl held:
  free). **Turn** (at the view's top right, beside **Move**) makes the
  handles rings: drag one to turn the selection about that axis, 15
  degrees at a time.
- From the keyboard, with the pointer on the view, it is Blender's: **G**
  moves, **R** turns, **S** scales - then X, Y or Z locks the axis (again:
  free), a typed number is exact (in the unit, in degrees, as a factor: G
  X 10 Enter is ten centimetres along X), Enter or a click keeps it, Esc or
  a right-click puts it back. **Shift+D** copies the selection and starts
  moving the copies, **Delete** deletes it, **A** selects every part
  (again: none).
- Moving one part so its first LED comes near another part's end **joins**
  them: it lands one spacing on from that end ("join after ring 1" shows
  where) and goes after it in the wiring; its last LED near a part's first
  puts it before that part. Each move is one step to undo.
- **A part's menu** (right-click it, in the view or in the list):
  duplicate and move, repeat it (copies), mirror it across X, Y or Z,
  reverse its wiring, move it in the wiring (first, earlier, later, last),
  frame it, rename it, **hide** it (dark while you build, not picked, still
  LEDs on the device), **lock** it (not picked or moved in the view - the
  list still selects it), **light it** (the wiring test lighting that part:
  in the sim, and on the device while the sim is streamed to it), delete it.
- A path's corners, while it is the only part selected, are squares to
  drag (on the plane the view faces most, snapped the same way).

**The wiring list.** Each row: the part's colour, its name, its kind and
its LEDs (54-117), an arrow the way its LEDs run (click: the other way),
an eye (click: hidden while you build), a lock, and x to delete it. Drag a
row onto another to wire it there; right-click it for its menu.

**One part's settings.**

- **SIZE**: the kind's own - LEDs, a length (typing it sets the count), a
  diameter, LEDs a metre, a height, turns, a formula - in the unit. A
  setting that works itself out (a ring's diameter from its LEDs, an arch's
  span) shows what it comes to until you type one. A path shows its
  **CORNERS**: x, y and z in the unit, **+** to put a corner halfway to the
  next, **x** to delete one, **reverse the path**, **draw on from its end**.
  A solid's edges can **split into parts** (a strip per edge, or a polygon
  per face in faces mode, the LEDs where they were). Loose points have
  their tools and **BY HAND**: tick "place", click the view and an LED
  lands on the working plane (choose x, y or z and a value in the unit);
  drag one to move it; "renumber: nearest chain" rewires them the way a
  strip would most likely run, "turn into a path" fills them in at the
  spacing.
- **PLACE**: its position in the unit (drag a number and the part moves as
  you drag; ctrl-click to type); **lie** - flat on the floor, upright
  facing the front, or facing out from the shape's middle; **turn 90°**
  about X, Y or Z. Folded under "exact rotation, scale and aim": its three
  angles, its scale, and **AIM** - a direction (x y z, or azimuth and
  elevation, or an axis button), a distance and a spin: **aim outward**
  turns its axis (a strip's length, a panel's face, a flat part's normal)
  along the direction and puts it that far from the origin; **turn only**
  keeps its place; **aim at the origin** points it inward.
- **COPIES**: the part repeated, live - **copies** (itself included), each
  moved a step from the one before and turned about X, Y or Z through its
  middle or the shape's origin (360 / copies round the origin makes a
  ring of them), every other one running back if the strip goes back and
  forth; and **mirrored across** X, Y or Z, exactly, through the origin or
  its middle, the mirror running back if asked. Change the part and they
  follow; they are one part in the list and the wiring. **make separate**
  turns them into parts of their own, the LEDs where they were (mirrors as
  loose points - no turn makes a mirror).
- **WIRING**: its LEDs the other way, its place in the wiring (first,
  earlier, later, last), and **light it**.

**Several parts: ARRANGE.** The selected parts aligned to the active one
on X, Y or Z, spread evenly along an axis (three or more, between the two
farthest apart), given its scale (**same scale**) or its turn
(**same turn**), each laid flat, upright or facing out, or each turned 90°
about X, Y or Z. **group them...** names them together - a heading in the
list that selects them all (a tree's strands, a room's walls; a part's
menu selects its group too) - and **ungroup** parts them again.

**The shape's own settings** (nothing selected): real sizes (above), the
**layout** the effects see (below), **Segment per part**, the colours the
view builds in, and BY HAND.

**File...** opens a shape file (`.shape.json`, to reuse across projects),
saves one, **imports** a model - `.obj`, `.ply` and `.stl` from Blender or
any CAD program as LEDs **along the edges** at a spacing (a strip run round
the outline, chained into as few runs as it can), one **per vertex**, or
**over the surface** (asked in the import dialog); an xLights **`.xmodel`**
custom model (the LEDs, their numbering and its grid); a whole xLights
layout (`xlights_rgbeffects.xml`: every model a part where it stands -
custom models, matrices, lines and poly lines exactly; trees, stars,
arches, spinners and window frames as the tree, star, arch, spokes and
frame parts; circles, spheres and cubes near enough, named in the footer;
anything else as a strip of its LEDs); or an `x y z [index]` point list
(CSV, whitespace or JSON; the index column is the wiring order) - puts in
a **reference mesh** (a wireframe to place LEDs against, not LEDs: the
tree, the house, the enclosure - moved, turned and scaled like any part),
**maps lights by camera** (above), **exports** an xLights model (any
geometry on its grid, the wiring as its node numbers) or the positions (a
CSV row per LED), makes a **preview** (a
turn of the shape off screen - lit by the effect, the parts' colours or a
chase along the wiring - looping in the frame's PREVIEW fold and written as
`shape_preview.gif` and `.png` in the export folder), or clears the shape.
**Undo** and **Redo** step through every change, the handles' and keys'
too (Ctrl+Z and Ctrl+Y while the frame has the keyboard).

**Parts in a graph**: the **Shape part** node says which part a pixel is
in, where along it (0..1), how many parts there are, and gives a mask for
a chosen part - one graph, the parts treated differently. **Segment per
part** gives every part its own WLED segment instead, each with its own
effect, palette and sliders (the strip layout; up to eight).

**Layout**: a shape is one logical strip in wiring order (what 1-D effects
and the 3-D nodes work on), or, as "grid", a w x h matrix the LEDs are
projected onto from the front - or the grid an xLights model came with.
On a grid, two LEDs in one cell are reported: the cell keeps the first.

**On the device**: the shape's positions go along with it. Device > Send
the shape (or the Send frame's button) uploads the ledmap (the wiring) and `/geometry.bin`, a table of
every LED's position and outward direction, which the cube effects read
instead of their cube-net rule - so Position, Direction, Cube face and
every effect that asks where a pixel is see the real shape, on the device
exactly as in the sim. Cylinders, spheres and tori send the table too; a
cube net and a flat matrix have a rule of their own and send none.

**Palettes of your own** (Window > Palettes): a gradient drawn by hand -
click the bar to add a stop, drag it, right-click to remove it, a colour
and a position each, up to 18 - kept with the project, in the sim as a
palette of its own (ids 200 down, in the palette combo like any other,
blended the way the device blends) and sent to the device as its custom
palettes (`/palette{n}.json`, the same ids there - by position, so the
first here replaces whatever the device had as palette 0). "From the
sim's palette" starts from whatever the sim shows.

**The library** (Window > Library) shows every graph of the project as a
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

Window > Sequence (Ctrl+Shift+Q). A **step** is what the sim
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
Like every frame - the shape editor, the sequence, the library, the
palettes, the LED outputs, the audio input - each opens in the **dock**:
a tab beside the side panel's own, in the panel's column, so it never
covers the views it changes. The tab strip over the column shows one at a
time (the one in front in the accent; names become icons when they no
longer fit), its **x** closes a frame and the menu opens it again; the
column is as wide as the frame in front wants, and dragging its edge sets
that frame's width, kept. **float** at the strip's right takes the frame
in front out into a window of its own over the panes - it opens so until
it is docked again, by **dock** at its top right or by dropping its :::
grip on the panes; its **x** (or Esc while it has the focus) closes it.
While the graph has the room, the dock is the drawer beside the rail,
and the rail carries the docked frames' icons. Every window - a frame
floating, a dialog - wears the same header: its title, and its close at
the top right. While you type in any frame's box the hotkeys stay quiet.

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
- **LED outputs and power** (Window menu): the wiring split into the
  device's outputs - one, one per part of a shape, or every N LEDs - each
  a pin, a start, a count, an LED type, a colour order and reversed or
  not; "Read the device's" shows what it has now; **Send outputs + power
  limit** writes them as its LED config over /json/cfg. POWER shows what
  the frame on screen draws at the LED's full-white current (55 mA by
  default) against the supply you enter, and how far WLED's auto
  brightness limiter would dim it; "preview the limiter" dims the sim
  the same way, and the footer shows the amps all the time.
- **Audio input** (Window menu, Ctrl+Shift+M): what the device listens
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

**Export usermod** (File > Export usermod) writes the usermod
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
  footer's line says so (the message log keeps it); the sim pauses.
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
- **File** › Open graph as code
- **File › Project** › New project...
- **File › Project** › Open › … the projects
- **File › Project** › Recent › … the projects opened lately
- **File › Project** › Open folder...
- **File › Project** › Export project as zip — the whole project - effects, graphs, sub-graphs, user nodes, assets, the settings - as one zip in captures/, to keep or to hand over; the history and the export folder stay behind
- **File › Project** › Import project from zip... — a zip made here (or a project folder zipped by hand) into projects/, and opened
- **File › Project** › Open the project folder
- **File** › Import graph bundle...
- **File** › Export graph bundle
- **File** › Export usermod (folder + zip) — the project's effects as a WLED usermod - a folder and a zip - to build into firmware outside the studio
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
- **Edit** › Delete `Delete`
- **Edit** › Delete and reconnect `Ctrl+Delete`
- **Edit** › Disconnect (keep the nodes)
- **Edit › Select** › All `A`
- **Edit › Select** › None `Alt+A`
- **Edit › Select** › Invert `Ctrl+Shift+I`
- **Edit › Select** › What feeds the selection `Ctrl+[`
- **Edit › Select** › What the selection feeds `Ctrl+]`
- **Edit › Select** › Everything wired to it `Shift+L`
- **Edit** › Command palette... `Ctrl+P` — every action and menu command by name: type a few letters, Enter runs the first
- **Edit** › Find / replace in code `Ctrl+F`
- **Edit** › Open code in external editor `Ctrl+E`
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
- **View** › Light a node's wires — the wires of the node under the pointer (or of the pin) and of the selection drawn bright, every other wire faded to a trace of its colour
- **View** › Fullscreen `F11`
- **View › Zoom** › Zoom in `Ctrl+=`
- **View › Zoom** › Zoom out `Ctrl+-`
- **View › Zoom** › Zoom 100% `Ctrl+0`
- **View › Zoom** › Frame all `Home`
- **View › Zoom** › Frame the selection `Shift+Home`
- **View** › Snap to grid `Shift+Tab`
- **View › Minimap** › Show the minimap — the whole graph in small, the view in the accent - a click on it moves the view there; faint until the pointer comes to it
- **View › Minimap** › In a corner the 3-D view leaves free
- **View › Minimap** › Top left
- **View › Minimap** › Top right
- **View › Minimap** › Bottom left
- **View › Minimap** › Bottom right
- **View › Camera** › Isometric `0`
- **View › Camera** › Front `1`
- **View › Camera** › Back `Ctrl+1`
- **View › Camera** › Left `Ctrl+3`
- **View › Camera** › Right `3`
- **View › Camera** › Top `7`
- **View › Camera** › Below `Ctrl+7`
- **View › Camera** › Orthographic `5` — no perspective: a size is the same across the view - for lining parts up (the views from the front, the side and above turn it on; turning the view by hand turns it off again)
- **View › Camera** › Frame the selection `F`
- **View › Camera** › Everything in view `Home`
- **View › Camera** › Saved view 1
- **View › Camera** › Save the view as 1
- **View › Camera** › Saved view 2
- **View › Camera** › Save the view as 2
- **View › Camera** › Saved view 3
- **View › Camera** › Save the view as 3
- **View › Camera** › Background picture...
- **View › Camera** › Clear the background
- **View** › Unlit LEDs as dim dots — the 3-D view draws an LED that is off as a dim dot, so the shape reads on black; off: black, as the LEDs are
- **View** › A floor under the shape — a faint grid under the shape in the 3-D view, fading out from the middle - something for it to stand on
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
- **Playback** › Compare with another effect... `Ctrl+Shift+B`
- **Playback** › Sweep a slider... `Ctrl+Shift+W`
- **Build** › Compile + reload `F5`
- **Build** › Live: rebuild the graph as it changes `L`
- **Build** › Watch: rebuild when the code is saved outside — a code effect edited in another editor (Edit > Open code in external editor) rebuilt when it saves
- **Build** › Run the graph as a script (no build) `Ctrl+Shift+R` — the graph compiled to bytecode and run by the Studio Script effect in the sim - no C++ build
- **Build** › Flash firmware... `Ctrl+Shift+U` — the firmware built with the project's effects and written to a device (the Flash frame)
- **Build** › Open the build folder
- **Window** › Devices `Ctrl+Shift+N`
- **Window** › Send to device `Ctrl+Shift+S`
- **Window** › Shape editor `Ctrl+Shift+E`
- **Window** › Sequence: presets and a playlist `Ctrl+Shift+Q`
- **Window** › Library `Ctrl+Shift+L`
- **Window** › Palettes (gradients) `Ctrl+Shift+G`
- **Window** › LED outputs and power `Ctrl+Shift+O`
- **Window** › Audio input (mic / line-in) `Ctrl+Shift+M`
- **Window** › Snapshots... `Ctrl+Shift+K`
- **Window** › MIDI controller...
- **Window** › Message log...
- **Window** › Close every frame
- **Settings** › Keyboard shortcuts... `Shift+F1`
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
- **Help** › User guide `F1` — every part of the studio, in a window here: the contents down the side, a search, the keys and menus at the end
- **Help** › Tutorial — a first effect from nothing, step by step, with pictures
- **Help** › Node reference — every node, pin and setting; F1 over a node in the graph opens its own entry
- **Help** › Effect API reference — what a code effect can call, beside the code editor
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
| `—` | Light a node's wires while it is under the pointer or selected, fade the rest | in the graph |
| `—` | The graph's minimap: show / hide | in the graph |
| `—` | The 3-D view: unlit LEDs as dim dots, or black | anywhere |
| `—` | The 3-D view: a faint floor under the shape | anywhere |
| `1` | From the front (orthographic) | over the 3-D view |
| `Ctrl+1` | From the back | over the 3-D view |
| `3` | From the right side | over the 3-D view |
| `Ctrl+3` | From the left side | over the 3-D view |
| `7` | From above | over the 3-D view |
| `Ctrl+7` | From below | over the 3-D view |
| `0` | The isometric view (perspective) | over the 3-D view |
| `5` | Orthographic / perspective | over the 3-D view |
| `F` | Frame the selected parts (the shape editor), else everything | over the 3-D view |
| `Home` | Everything in view: the pan and the zoom back | over the 3-D view |
| `G` | Move the selected parts (then X, Y or Z, a number, Enter) | over the 3-D view |
| `R` | Turn the selected parts | over the 3-D view |
| `S` | Scale the selected parts | over the 3-D view |
| `Shift+D` | Duplicate the selected parts and move the copies | over the 3-D view |
| `Delete` | Delete the selected parts | over the 3-D view |
| `A` | Select every part, or none | over the 3-D view |
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
| `Ctrl+P` | Command palette: every action and menu command by name | anywhere |
| `Ctrl+Shift+K` | Snapshots: the graph's settings as named states | anywhere |
| `—` | MIDI controller: knobs onto the sliders | anywhere |
| `Ctrl+Alt+Z` | Undo history | anywhere |
| `Ctrl+Shift+Y` | History of the current graph or code | anywhere |

### Buttons

Every button, with what its tooltip says.

**Devices frame**: `dock` — dock: a tab beside the side panel's (or drag the grip onto the panes); `close` — close (Esc while the frame has the focus); the menu opens it again; `Scan the network` — asks by mDNS, asks every known device for the nodes it has heard of, and sweeps the subnet; `Stop`; `Add`; `Refresh all` — asks every listed device again what it is and runs; `use`; `remove`

**Flash firmware frame**: `dock` — dock: a tab beside the side panel's (or drag the grip onto the panes); `close` — close (Esc while the frame has the focus); the menu opens it again; `flash_env_fit`; `Preview (no compile)` — stages the build and lists what it would carry - the manifest, resolved the way the build resolves it - without compiling; `all`; `none`; `Usermods...`; `Start`; `Cancel`; `Open the build folder`

**Send to device frame**: `dock` — dock: a tab beside the side panel's (or drag the grip onto the panes); `close` — close (Esc while the frame has the focus); the menu opens it again; `Find a device`; `Read` — ask the device again what it is and runs; `Open in the browser`; `Calibrate the speed factor` — the current effect's settings sent, the device's fps read for three seconds, and the footer's device fps estimate set from the measurement (Settings > Device speed factor holds the number); `Send the graph as a script` — the graph as bytecode for the Studio Script effect - no firmware build; the device runs it at once; `Send the effect's settings` — the effect the sim shows, with its sliders, checks, palette and colours, onto the device's segment; `Send the shape` — the ledmap (the wiring) and the positions table, so Position and Direction see the real shape; `Send the ledmap only`; `Import the device's` — the device's ledmap becomes the geometry: a matrix with its gaps and wiring, or a strip; `Import a file...`; `<`; `>`

**Shape frame**: `dock` — dock: a tab beside the side panel's (or drag the grip onto the panes); `close` — close (Esc while the frame has the focus); the menu opens it again; `Add part...` — a strip, a ring, a tree, a star... picked from pictures, its sizes asked first; it joins the end of the selected part (or goes beside it); `Draw a run` — click corners in the 3-D view and a strip is laid along them, an LED every spacing; double-click or Enter ends it, Backspace takes the last corner back, Esc leaves it; `File...` — open or save a shape; import a model, an xLights model or layout, a point list; a reference mesh; export an xLights model or the positions; a preview; `Undo`; `Redo`; `the way its LEDs run along it` — the way its LEDs run along it: click to turn its wiring round; `shown` — shown: click to hide it while you build (it stays LEDs on the device); `click to lock it` — click to lock it: the view's clicks, handles and keys pass it by; `x` — delete the part (Undo brings it back); `delete the last`; `renumber: nearest chain from the first`; `turn into a path`; `X`; `Y`; `Z`; `+X`; `-X`; `+Y`; `-Y`; `+Z`; `-Z`; `aim outward`; `turn only`; `aim at the origin`; `from its place` — the direction and distance the part is at now, into the fields; `first`; `earlier`; `later`; `last`; `light it` — the wiring test lighting this part: in the sim, and on the device while the sim is streamed to it; `Generate a preview` — a turn of the shape, rendered off screen: a GIF and a PNG in the project's export folder, looping here; `Open the folder`

**Sequence frame**: `dock` — dock: a tab beside the side panel's (or drag the grip onto the panes); `close` — close (Esc while the frame has the focus); the menu opens it again; `undo` — the steps (or the schedule) as they were before the last change; Ctrl+Z here does the same, Ctrl+Y redoes; `+ Add from the sim` — a new step: what the sim shows now - effect, sliders, palette, colours, segments; `Update from the sim` — the selected step becomes what the sim shows now; `Load into the sim` — the sim shows the selected step; `Add what the sim shows`; `x` — this slider's ramp off (the others stay); `Play in the sim`; `Stop`; `Render GIF` — plays the sequence once and records it as a GIF, into captures/; `Render video` — plays the sequence once and records it as an mp4, into captures/ - needs ffmpeg on the path; `Tap` — tap tempo: tap on the beat, the bpm from the gaps; `Synth's` — the bpm of the sim's synthetic beat; `WAV's` — the tempo and the beats found in the WAV playing as live audio (AUDIO > play a WAV file); `Snap durations to bars` — every step's seconds rounded to whole bars, so the sequence changes on the music; `Send presets + playlist` — about a second a preset: the device writes each one from its main loop, and the next is sent once it has; `Send and run it`; `Save presets.json...` — the same presets and playlist as a file, for a device that is not on the network; `+ run the playlist at`; `+ off at` — a time the lights go off: an Off preset (id 250) is saved on the device and timed; `Read the device's`; `Send the schedule`; `Run the playlist at...`

**Library frame**: `dock` — dock: a tab beside the side panel's (or drag the grip onto the panes); `close` — close (Esc while the frame has the focus); the menu opens it again; `Remake the thumbnails`; `Generate previews` — a turn of the 3-D view for every effect on the project's shape - a GIF and a PNG each in export/library, with an index; the tiles then show those turns; `Open the folder`; `no preview`

**Palettes frame**: `dock` — dock: a tab beside the side panel's (or drag the grip onto the panes); `close` — close (Esc while the frame has the focus); the menu opens it again; `undo` — the palettes as they were before the last change; Ctrl+Z here does the same, Ctrl+Y redoes; `+ New`; `From the sim's palette` — a new one that starts as the palette the sim shows; `Copy`; `Remove`; `Use in the sim`; `New palette`; `spread evenly`; `Send this one` — slot n is /palette{n}.json on the device, palette id 200 - n everywhere; the device reloads its custom palettes on upload; `Send all`; `Remove this one there`

**LED outputs frame**: `dock` — dock: a tab beside the side panel's (or drag the grip onto the panes); `close` — close (Esc while the frame has the focus); the menu opens it again; `one output`; `one per part`; `by count:`; `+ output`; `Read the device's`; `One output`; `Send outputs + power limit` — over /json/cfg; the device re-initialises its outputs (reboot it if it does not)

**Audio input frame**: `dock` — dock: a tab beside the side panel's (or drag the grip onto the panes); `close` — close (Esc while the frame has the focus); the menu opens it again; `Read the device's` — what the device's audioreactive is set to now (its type, pins and levels), into these fields; `Send the audio input` — over /json/cfg; the levels take at once, a new type or new pins after a reboot (offered when needed); `Reboot the device` — restarts the device so a new type or new pins take effect; the LEDs go dark for a few seconds

**Keyboard shortcuts**: `close` — close (Esc while it has the focus); `Reset all to defaults`

**Appearance**: `close` — close (Esc while it has the focus); `dark`; `light`; `soft light`; `slate`; `Back to the preset` — the preset's colours again, your changes dropped; `The monitor's` — the size the monitor is set to in the system's display settings; `Restart now` — the studio closes and starts again at the new size; the graph is saved, and unsaved code is asked about first

**Selection frames**: `close` — close (Esc while it has the focus); `Save`; `Save + use for nodes`; `Save + use for pane`; `Delete`

**History**: `close` — close (Esc while it has the focus)

**Undo history**: `close` — close (Esc while it has the focus)

**About**: `close` — close (Esc while it has the focus); `The studio on GitHub`; `The WLED fork`; `WLED`

**Usermods and features**: `close` — close (Esc while it has the focus); `Add`; `Import a folder...`; `Import a zip...`

**Update**: `close` — close (Esc while it has the focus); `Download and install`; `Release page`; `Not now`

**A WLED checkout**: `close` — close (Esc while it has the focus); `Clone`; `Restart the studio`; `Close`

**Report a problem**: `close` — close (Esc while it has the focus); `Open the issues page` — a new issue on the studio's GitHub page, in the browser - attach the zip there; `Show the zip` — the captures folder, where the report landed; `Close`

**Map lights by camera**: `close` — close (Esc while it has the focus); `Play the plan` — in the sim - and on the device while the sim is streamed to it (Stream the sim to the device, Ctrl+Shift+T); `Stop` — the plan stopped part way; `+ a side` — another side: how far it was turned from the first, then its film; `Film with the webcam` — the plan played while the webcam takes its pictures: a side without a video file (needs OpenCV: pip install opencv-python); `Make the part` — the lights as a points part in the shape, in wiring order: an LED no two sides saw is estimated (the shape's checks list them, to drag where they are)

**Message log**: `close` — close (Esc while it has the focus); `copy all` — the log as text, to paste into an issue or a note; `clear` — empties the recent messages; the problems stay until they are fixed

**The panes and the toolbar**: `New effect` — New effect  Ctrl+N; `Open a graph or a code effect` — Open a graph or a code effect  Ctrl+O; `Save` — Save  Ctrl+S; `Compile + reload` — Compile + reload  F5; `Live` — Live: rebuild the graph as it changes  L; `Undo` — Undo  Ctrl+Z  (nothing to undo); `Redo` — Redo  Ctrl+Y  (nothing to redo); `Play` — Play  Space; `Pause` — Pause  Space; `Step one frame` — Step one frame  .; `Restart the effect` — Restart the effect  Ctrl+R; `Logical net` — Logical net  Q; `3-D view` — 3-D view  E; `Net and 3-D` — Net and 3-D  W; `Code` — Code  C; `Graph` — Graph  G; `Zoom out` — Zoom out  Ctrl+-; `100%` — Zoom 100%  Ctrl+0; `Zoom in` — Zoom in  Ctrl+=; `Frame the whole graph` — Frame the whole graph  Home; `Add a node` — Add a node (or right-click the graph)  Shift+A; `Delete the selection` — Delete the selection  Delete  (select a node first); `Arrange the graph` — Arrange the graph  Ctrl+L; `Fold the selection into a sub-graph` — Fold the selection into a sub-graph  Ctrl+G  (select two nodes or more); `Devices on the network` — Devices on the network  Ctrl+Shift+N; `Build the firmware and flash the device` — Build the firmware and flash the device  Ctrl+Shift+U; `Send to the device` — Send to the device: the effects, a script, the shape  Ctrl+Shift+S; `Stream the sim to the device` — Stream the sim to the device (DDP)  Ctrl+Shift+T; `Shape editor` — Shape editor  Ctrl+Shift+E; `Sequence` — Sequence: presets, a playlist and the schedule  Ctrl+Shift+Q; `Library` — Library: every effect as a looping thumbnail  Ctrl+Shift+L; `Palettes` — Palettes: gradients of the project's own  Ctrl+Shift+G; `LED outputs and power` — LED outputs and power  Ctrl+Shift+O; `Audio input` — Audio input: the device's microphone or line-in  Ctrl+Shift+M; `Devices` — Devices on the network  Ctrl+Shift+N; `Flash` — Build the firmware and flash the device  Ctrl+Shift+U; `Send` — Send to the device: the effects, a script, the shape  Ctrl+Shift+S; `Stream` — Stream the sim to the device (DDP)  Ctrl+Shift+T; `Shape` — Shape editor  Ctrl+Shift+E; `Outputs` — LED outputs and power  Ctrl+Shift+O; `Audio in` — Audio input: the device's microphone or line-in  Ctrl+Shift+M; `Open the code in an external editor` — Open the code in an external editor  Ctrl+E; `Screenshot of the 3-D view` — Screenshot of the 3-D view  F12; `Record 15 s as a GIF` — Record 15 s as a GIF (a video: File > Record 15 s video)  Ctrl+F12; `find` — the next match (Shift+Enter in the box, or Shift+F3: the previous); the status says which of how many; `replace` — the match the cursor is on, then the next is found; `replace all`; `read from file`; `apply to file`; `< back`; `help_split`; `Move` — the handles move the selected parts: an arrow along its axis, a square in its plane, the ring in the middle in the screen's plane (G does the same from the keyboard); `Turn` — the handles turn the selected parts: a ring about its axis, 15 degrees at a time (Ctrl: free; R does the same from the keyboard); `Front` — from the front: X to the right, Z up - orthographic  (1 over the view); `Side` — from the right side: Y to the right, Z up - orthographic  (3 over the view); `Top` — from above: X to the right, Y up the screen - orthographic  (7 over the view); `Persp` — perspective - click for orthographic, sizes true across the view  (5 over the view); `tuck the 3-D view away to a tab in its c` — tuck the 3-D view away to a tab in its corner (it is not drawn while it is away); `drag to size the 3-D view` — drag to size the 3-D view (or Ctrl+wheel over it); its ::: drags it to another corner; `close until another node is selected` — close until another node is selected (N keeps it open); `sec_effect_arrow`; `sec_segments_arrow`; `+`; `-`; `undo` — the segments as they were before the last change (add, remove, bounds, blend, options); `sec_geometry_arrow`; `Edit the shape...`; `sec_colours_arrow`; `sec_parameters_arrow`; `sec_audio_arrow`; `sec_live_arrow`; `use live audio`; `play a WAV file...`; `fold the panel away` — fold the panel away: the graph gets the room back; `EFFECT` — EFFECT: the project, the effect and its palette - goes to it; `SEGMENTS` — SEGMENTS: the strip's segments, their bounds and blends - goes to it; `GEOMETRY` — GEOMETRY: the shape the LEDs are on - goes to it; `COLOURS` — COLOURS: the segment's three colours - goes to it; `PARAMETERS` — PARAMETERS: the effect's sliders and checkboxes - goes to it; `AUDIO` — AUDIO: the synthetic audio's levels - goes to it; `LIVE` — LIVE: audio from a line in, a microphone or a WAV file - goes to it; `Panel` — Panel - brings it to the front; `Devices - brings it to the front`; `x` — close Devices (the menus open it again); `Flash - brings it to the front`; `Send - brings it to the front`; `Shape - brings it to the front`; `Sequence - brings it to the front`; `Library - brings it to the front`; `Palettes - brings it to the front`; `LED outputs - in front`; `float` — float the frame in front: a window of its own over the panes (it opens so until docked again); `stats` — every figure: the picture's brightness, contrast, unlit share and saturation; the effect's, the device's and the studio's time; the current and the limiter - live while open; `N problems` — the problems that stay until they are fixed - a click opens the log at them; `log` — the last fifty messages, the problems first; each that is about a node or a line goes to it; `the latest message` — short, the whole of it on hover; a click opens the log; `vsplit_0_0`; `vsplit_1_0`; `hsplit_0_0`; `hsplit_0_1`; `hsplit_1_0`; `hsplit_1_1`; `hsplit_2_0`; `hsplit_2_1`

<!-- uiref end -->
