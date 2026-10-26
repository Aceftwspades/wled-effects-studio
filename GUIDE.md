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
starts it again. The Linux build (the release's tarball) downloads its own
tarball and opens the folder it landed in, to unpack over the app's. From
a checkout the answer is `git pull`.

**From the tree** (Windows):

```bash
cd wled-effects-studio                                 # the clone
pip install -r requirements.txt                        # dearpygui, numpy, pillow; the audio packages
python -m native.doctor                                # what is here and what is missing
python build.py --native-only                          # once; the app rebuilds the engine as it needs
python -m native.app                                   # or the desktop shortcut
```

On Linux and macOS the packages go in a virtual environment (a current
distribution refuses them in the system's Python), and `run_studio.sh`
uses it by itself; the README names the system packages Linux wants
(PortAudio; the ALSA headers python-rtmidi builds against):

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m native.doctor
.venv/bin/python build.py --native-only
./run_studio.sh                                        # ./install_linux.sh puts it in the app launcher
```

**Help**: the first time the studio starts, a Welcome panel offers the
[tutorial](TUTORIAL.md), a second one that builds a Christmas tree in the
shape editor (**Build a Christmas tree**), this guide, the example effects
and a search for devices (Help > Welcome... brings it back; its checkbox
shows it at every start). Help > User guide (**F1**), Tutorial, Tutorial:
a tree in 3-D and Node reference open in a window of the studio's own: the contents down the left mark
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

**Node tutorials.** A node with a tutorial has more under its reference
entry: **Why use it** (what it is for, and how it differs from the
nodes like it), a **Tutorial** - a small graph built round the node,
step by step, with a picture of it running (it plays in the reader
too), and for a value that changes over time a line of it under the
LEDs - then **Try this**, changes to make and what each does, and
**Used in**, the examples that use it. **Try it in the studio** opens
that graph live: your project is saved and left, the graph opens in
a project of its own (*Node tutorials*) with the node selected, the
page moves to a column at the right, the side panel folds away and the
3-D view goes to the bottom-left corner, so the graph, the LEDs and
the node's values are all in sight. Each **Try this** button makes its
change on the running graph; change anything else you like as well.
The bar at the top of the page has **Reset the tutorial** (the graph
as written), **Copy into my project** (the graph as you have it, saved
as a new graph in your own project, which then opens with it) and
**Back to my project** (your project, the graph you had open, and the
panel, the 3-D view's corner and the camera as they were). Nothing a
tutorial does reaches your project but Copy.

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
and the recent projects too; Up and Down choose one as you type, Enter runs
it (the first, until you choose). Every control
explains itself on hover; a dim **(?)** at the end of a row holds what
the row as a whole is for. Buttons say what they weigh: the one a dialog
or a frame is for is filled in the accent, one that changes a device or
deletes something is red, a way out (Cancel, Not now) has no slab. The
pane last clicked in and the selected nodes wear a frame of a gradient
going round them; Settings > Appearance, in its **Selection frames** tab,
picks the gradient - a WLED palette, the studio's own, or one made there -
and whether it turns, stands still, or is a plain outline in the accent. What
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
Settings > Appearance, in its **Interface size** tab, sets it from 80 to 200%;
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
grip (the striped corner, or Ctrl+wheel over it) sizes it, its maximize
button lays it over the whole graph (the same button, then a restore,
puts it back in its corner at its size), and its tuck button puts it
away to a tab in the corner, where it is not drawn until the tab (or
View > 3-D view over the graph) brings it back. The **minimap** sits
faint over its corner of the graph - the nodes under it read through -
and comes up full when the pointer reaches it; a click on it moves the
view there. View > Minimap shows or hides it and picks its corner (or
leaves it to one the 3-D view leaves free; a corner the view has, it
cedes to the other corner of that edge). Select a node with anything to
set and its **properties** come up over the graph: its settings and the
values of the inputs nothing is wired to, each field a twin of the
node's own (an edit in one shows in the other), and what a node has no
room for - bitmap rows, long expressions and paths, curves - there
alone. N keeps them open, their x closes them until another node is
selected. As panes, the properties sit under the 3-D view (N hides
them). The **add menu** describes the node under the
pointer in a column beside its list - what it does, every pin and
setting - before you add it: go straight across to it to read on (the
wheel scrolls a long one); a search describes its first hit, the one
Enter adds. What a node or pin does comes up **at the
pointer** when it rests on one (as panes, in the box above the graph).

The panes go where you want them: drag one by the `:::` at its top right
onto another - near an edge it snaps beside or above that pane, in the
middle the two swap - or pick a preset under View > Layout; the splitters
between panes resize them. A view can leave for a second monitor: View >
Pop out (or right-click the view) opens it in a window of its own, which
orbits and zooms on its own and remembers where it was. It shows the 3-D
view's look (Appearance > 3-D view). **F11**, **F** or a double-click puts
it full screen on the monitor it is on, and back; moving the mouse shows a
bar in its corner with **Full screen** and **Back into the studio**. **Esc**
leaves full screen, and pressed again (or Back into the studio, or closing
the window) brings the pane back. The side panel's sections fold on their arrow or title
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
and both fields follow. Effect settings' palette is picked by name. A
Math node shows its second pin only while its operation takes two - sqrt,
sin and the other one-input ones leave it off, unless a wire is on it -
and its dropdown lists the operations in groups (arithmetic, compare,
rounding, trigonometry); Vector math does the same with b and scale. Every
node and pin explains itself at the pointer when hovered (or in the box
above the graph, as panes), and while the effect is on the cube that
shows the pin's live value. The
bolt on the toolbar (**L**) - Live - rebuilds as you edit (on unless
turned off, and remembered; an edit that changes no code, a zoom or a
label, builds nothing); F5 rebuilds on demand.
A typed value on a pin needs no rebuild at all: the compiled effect
reads it from a small table, and dragging the field (or the XY pad)
pokes the running engine, so the picture follows the drag at once -
as a synth follows a knob; a colour typed on a pin too (its red, green
and blue each a slot of the table). Adding or wiring nodes, or a
setting on a node, still rebuilds - but the edit shows at once all the
same: while the C++ compiles, the sim's Studio Script effect runs the
graph from bytecode (compiled in a few milliseconds), under the graph's
own name and sliders, and the build takes its place at the same moment
when it lands, so the swap is not seen. A graph with a node the script
does not have (a Bitmap, a Field, a particle system) waits for its
build, as before. A pattern's coordinates read the
pixel while nothing is wired or typed on them - a Noise dropped in says
**position x** on its field and draws at once, as wiring Position into
it would; a Checker, Wave or Bitmap reads Coords' u and v. Type a number
to fix one; reset the pin (Backspace, or its menu) and it reads the
pixel again.
Sub-graphs (select nodes, Ctrl+G) fold a cluster into one node you can
reuse. File > History keeps a copy at every save; **changes** beside a
copy shows what is different now (the code as a diff; a graph as the
nodes added and gone, the settings and values changed, the wires) before
you restore it. The editor has the
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
**Scenes** node takes them to the device: the snapshots' values for the
pins (what a drag or a knob moves - a node's settings stay as built) go
into the effect as a table, and its **index** picks one, faded to over
its **fade** seconds - a Counter on the beat steps a verse look into a
chorus look a bar at a time. Build after saving a snapshot: the table is
made when the graph compiles. A
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
match), so a graph reads by colour first; Settings > Appearance's Colours
tab has the legend and the switch, and a colour you give a node still wins. Nodes
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

**From a shader.** File > New effect from a shader... takes a Shadertoy
image shader - paste the "Image" tab's code, or **Open a file...** (.glsl,
.frag, .txt) - and **Make the effect** turns it into a code effect of the
project, opened in the code pane and built. Every LED runs the shader's
`mainImage` at its own place (the matrix, or the cube's net, as one
picture; y up as on Shadertoy), with `iTime` (scaled by Speed),
`iResolution`, `iFrame` and `iTimeDelta`; Intensity is the brightness.
The file carries the small vector library it needs (vec2 to vec4, mat2,
mat3, the GLSL functions), so it builds into any firmware like any code
effect - read it as GLSL in C++: swizzles are methods (`p.xy()`), the
functions are `gl_` named. What an LED cannot have - textures and buffers
(`iChannel0`, `texture()`), derivatives, `ivec` and `mat4` - is refused
with its line. A device runs it in floats, pixel by pixel, where a GPU
runs thousands at once: keep a shader light (few loops, few octaves) for
the cube.

**Draft vs. list.** A new effect is a draft: built and shown only while
you edit it. File > "Add to the effects list" (Ctrl+I) makes it part of the
project: always built, exported, shipped.

## Seeing it properly

The geometry section sets the cube's face size and whether it has six
faces (a lit bottom; it takes the net's bottom-right corner block, and
the flash build and the settings push tell the device) - or a matrix,
cylinder, sphere, strip, or an XYZ file - and for the cube its wiring - which face
first, turns, serpentine - which is what the exported ledmap says. The
wiring can come from the device, whatever the geometry: **Read the
device's wiring** (under GEOMETRY, or Device > Read the device's wiring)
reads what WLED uses (read only: the device is not changed) - its ledmap,
else its 2-D setup (LED Preferences > 2D Configuration: the size, where the
first LED is, rows or columns, serpentine, panels, a gaps file), else its
LEDs in order - and lays it over the geometry the studio has. A cube's
faces are found back as its own settings - their order, each one's turns,
serpentine and the start corner - when the wiring is one those can say,
and kept as the device's own map when it is not (then its button
**Use the wiring fields instead** gives the settings back); a cube of
another face size takes the device's. A
matrix with a ledmap on the device takes the ledmap (WLED uses it over its
2-D setup); one panel of a 2-D setup becomes the matrix's switches,
several (or a gaps file) the map WLED makes of them. A strip, cylinder,
sphere or torus takes it at its size; a shape's wiring is its parts' own
order. Audio
comes from the synth (sliders, a beat clock), a live capture, or an audio
file (a WAV as it is; MP3, FLAC, OGG, M4A through ffmpeg). Playback has A/B compare - two effects side by side, or
**itself as built now**: B keeps that build while you edit, and each
rebuild shows the new version (A) beside the one from before (B), both
restarted together with the same sliders, palette and audio - a slider sweep,
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
again, or Esc, closes it. Which node that time goes to: Node > **What each
node costs** builds a timed copy of the graph beside the sim (the app's
engine is left alone), runs it for a moment, and puts each node's share of
the effect's own work and its time on the device (the speed factor's
estimate) over its corner - a quarter or more in amber - until the graph is
compiled again; the status line says the frame's and the top three, and how
much is the rest (each pixel's coordinates, the drawing). The device's own
proportions can differ (a division or a sine costs more there next to a
multiply): read the shares as where the time goes. A **MIDI
controller** (Window > MIDI, OSC and phone...) puts its knobs on the
sliders: pick the port ("Rescan" after plugging one in), pick what a knob
should drive - a parameter slider, a check, the palette or the effect by
index, the effect from the setlist, the next or the previous effect, a
typed value on a pin of the open graph - press "Learn" and move
the knob; a right-click on a parameter slider, or a pin's menu, offers
the same. A mapping moves the slider, the picture and, with the sim
streamed, the device; a pin's mapping has a range to edit and belongs to
that graph. The mappings are the project's. To switch effects live, build
a **setlist** in the window ("Add current" puts the effect on screen at its
end; Up, Down and Remove order it): a **Program Change** then picks from it
by number - program 1 the first - with nothing to learn ("Program Change
picks" turns that off), and "next effect" and "previous effect" learnt on
two pads or buttons step through it, wrapping (with no setlist, through
every effect). A knob's 128 steps cannot reach each of the studio's 200-odd
effects, which is what the setlist is for. A pad's release never switches
anything, and next and previous fire once on the press - or as a knob
crosses its middle. **CROSSFADE** blends the effect going out into the one
coming in over the seconds set, in any of the device's transition styles
(fade, swipe, push, circular, fairy dust); 0 cuts. The **DEVICE** row's
"switch it too" (on unless unticked) makes every MIDI switch set the active
device's own effect as well - with the device's own defaults for it, and the
crossfade as its transition - so the cube follows the controller with no
stream running (while the sim is streamed to it, the stream is what it
shows). The effect must have one of the device's effect slots (below).
"Send the setlist" writes the setlist onto the device as presets (70 up) and
a playlist (69) that steps through them every so many seconds, so it plays
with the studio closed. **Window > Effect slots...** is the device's effect
bank: which of the cube_fx effects the firmware compiles take one of its
slots, in what order - the device lists only those, after its built-ins, in
that order (and the on-cube menu with them). "Read the device" shows what it
has; Add, Add the rest, Up, Down and Remove change it;
"Write to the device and reboot" writes the slots (the rest of the
device's settings kept) and reboots it, since effects join the list as it
boots. A newly flashed effect
needs a slot before the device lists it. A drum machine's or a DAW's
**MIDI clock** on the port is followed while it plays (the window's CLOCK
row turns it off): each of its beats fires the synth's, and its tempo is
the synth's; stopped, the synth keeps its own beat again. It needs the optional
python-rtmidi (`pip install python-rtmidi`); without it the window says
so. **OSC** comes in beside it, with nothing to install: tick the OSC
row's "listen on UDP port" (9000 unless changed) and point a phone's or a
tablet's OSC app - TouchOSC, Open Stage Control, a DAW's OSC out - at this
machine and that port; Learn then takes a fader as it takes a knob, and a
mapping moves things the same way. A fader sends 0..1 (finer than MIDI's
128 steps), an int 0..127 is taken as MIDI's, an XY pad's two numbers are
two controls. OSC has no password - anyone on the network who reaches the
port can move what is mapped - so it stays off until turned on, and it
only ever moves the sim's sliders and pins. A **phone remote** needs no app
at all: tick the PHONE row's "serve a remote page on port" (8765 unless
changed) and open the link under it in the phone's browser, on the same
network - it is the address to type, or select it to copy and send it to
the phone. The page has the effect (a list, and Previous and Next, which
step through the setlist as MIDI's do), the effect's own sliders and checks
by their names, the palette, a **master brightness** and **Blackout**, and
the Sequence's show: Play, Stop, and each step - a step tapped plays the
show from it. The master brightness dims the picture every view and the
stream read; it is the phone's alone (the studio's panels do not change).
The link carries a key, so a phone or a computer without the link cannot
use the page; **New key** makes another, and the old link stops working. It
stays off until turned on, and it is on again at the next start when it was
left on. Its **HTTPS** check (on when the studio has the cryptography
package) serves the page over HTTPS with a certificate the studio makes
itself: the first time, the phone's browser warns that it does not know the
certificate - **Advanced**, then go on to the address. The page's **Camera**
link sends the phone's own camera to the studio (**Start**, then allow the
camera; **Front / back**, a size and a frame rate) - a source for the Video
node and a camera for mapping. A browser offers the camera only to a page
served over HTTPS, so the camera needs the check. Segments (+ in
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
is off is black, as on the real thing; View > Unlit LEDs as dim dots draws
it as a **dim dot** instead (smaller than a lit one, in the middle of its
cell on a cube's face), so the shape reads when most of it is dark. The
shape stands on a faint **floor** that fades out from the middle (left out
when the view looks up from below it) - View > A floor under the shape
turns it off; a popped-out view does the same, and a screenshot or a recording takes the view as
it is shown (the library's and the shape's previews leave both out).
How the view is **lit** is Settings > Appearance's **3-D view** tab: the
studio's plain look, or a film's - **Glow**, **Cinematic** or **Night** -
each LED a glowing dot with a halo or - **Diffused** - its light spread
as behind frosted acrylic (a cube's within each face, any other shape's
to the LEDs nearest it; a **diffuser** further away spreads it more: how
an effect will read on a diffused shape), the floor a mirror with the cube's **reflection** fading
into it, their colour **spilling** into the room behind them, a film's **curve** and an **exposure**, a
**vignette** and moving **grain**; a screenshot, a GIF or a video adds
**bloom**, the light past white spreading round it. Each part has its
strength, kept over the preset; "Back to the preset" drops them. Every
shape - a cube, a strip, a sphere, a shape of parts - takes all of it.
**Glow in pictures** says how a screenshot, a GIF or a video of any shape
but a cube makes its glow: **exact** - each LED its own round glowing dot,
as the live view draws it; **fast** - one blur of the whole picture,
softer, and two or three times quicker for a big sphere, torus or matrix;
**automatic** (the first time) - whichever is quicker for that picture. The
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
order, and under that two tabs: **Shape**, the whole shape's own settings
(its real sizes, what the effects see, power) whatever is selected, and
the selection's - one part, its sizes, place, copies and wiring; several,
lining them up. Picking a part brings its tab forward; with nothing
selected there is only the Shape tab.

**Real sizes.** A shape is measured in LED spacings; its **LEDs a metre**
(30, 60, 96 and 144 are the strips sold, or type any other) says what a
spacing is on the bench - 60 a metre is 1.67 cm - and **lengths in** picks
mm, cm or inches. Every length in the frame and the view is in that unit:
a strip's length, a ring's diameter, a lead's gap, the floor's squares.
Only what is shown changes - the device gets the shape fitted to its box as
ever. (Both are the shape's own settings: the **Shape** tab.)
A part can have a strip of another density: its own **LEDs a metre**.

**A starting point.** With no parts yet, the list is a start: objects
people light, ready to size - a matrix, a cube, a sphere, a Christmas tree,
a star, the 241-LED ring disc, a room's ceiling outline, a window, an
infinity cube, a soccer ball, a helix column, a spiral disc - each opening
the gallery below on its sizes; or **Draw a run**, **Import a model or a
layout...**, **Map lights by camera...** (below), or **Any part...** (the
whole gallery). Choosing "shape" under GEOMETRY opens this and changes
nothing until the first part goes in. **The tree tutorial** (New to
shapes?) opens the tutorial that builds a tree and its star here, step by
step.

**Checks as you build.** Under the tools, what is likely a mistake or will
matter on the bench: LEDs sitting on another (two parts laid over each
other, a copy left on its part), a lead of a metre or more (a data wire
that long may want a buffer, or a sacrificial LED near the controller), LED
outputs carrying another count than the shape, the current at full white
against the limiter's ceiling, a formula that does not work out, parts
hidden, LEDs of mapped lights no two sides of the films saw, a grid
layout that leaves LEDs dark (seen from the front, an LED behind another
shares its cell) - each with **show me**, which selects and frames it (or
opens the Outputs frame).

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
BY HAND's **place** ticked each drags to where it really is.

**How** picks the plan. **One LED at a time** is sure where LEDs sit close
together, but slow for a long string (500 LEDs at 0.2 s are close to two
minutes). **Every LED at once, by code** (the way of Lightwork) lights every
LED in each picture, each flashing its own address in Gray code: a bit
picture and its inverse for each bit of the count, so 500 LEDs take 20
pictures - seconds, not minutes. It reads the pictures pixel by pixel, so
two LEDs that blur together on the flash still part, and a reflection lit
in every picture (and its inverse) takes no address. It wants a darker room
than the slow way. **LED brightness** sets how bright the plan lights
them: lower it when the camera flares.

**Mapping live with a camera** needs no film: pick the camera (**Find**
lists the webcams ffmpeg can open, **the phone's camera** - the phone
remote's Camera page, Start on the phone - and the VIDEO section's
**network stream** when it has an address), and **Map live** lights each step of the plan
on the device, waits **settle** new pictures for the stream and the camera
to catch up, takes the picture itself, and reads the side - no flashes, no
clock. **Calibrate** first: it lights every LED and shows the camera's view
with each LED found marked and counted. Raise **threshold** if the room's
lights or reflections are counted, lower it if dim LEDs are missed; **apart**
drops doubles closer than that; **largest** drops a spot too big to be one
LED (a lamp, a window). The same settings read the filmed sides.

**Lightwork's layout CSV**: **Save CSV (Lightwork)** writes the shape's
LEDs, in wiring order, as `address,x,y,z` (each 0 to 1, y down the picture)
into the project's `export` folder - for Lightwork's scraper, MadMapper or
TouchDesigner. **Import CSV...** takes one back as a points part, sized to
**its height** (one made in two dimensions lies flat).

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
  per face in faces mode, the LEDs where they were). With LEDs on its
  **faces**, every face is outlined on its own, **faces inset** (half a
  spacing unless set) in from its edges - two faces share each edge, so
  their strips lie side by side - and each LED faces the way its face
  does. Loose points have
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

**The shape's own settings** (the Shape tab): real sizes (above), the
**layout** the effects see (below), **Segment per part**, the colours the
view builds in, and BY HAND.

**File...** opens a shape file (`.shape.json`, to reuse across projects),
saves one, **imports** a model - `.obj`, `.ply` and `.stl` from Blender or
any CAD program as LEDs **along the edges** at a spacing (a strip run round
the outline, chained into as few runs as it can), one **per vertex**, or
**over the surface** (asked in the import dialog: each flat region - an
STL's triangles of one plane joined back into a face - a regular grid a
spacing apart, half a spacing in from its border; a curved surface spread
evenly, no two LEDs nearer than a spacing); an xLights **`.xmodel`**
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

**Signs**: the add gallery's **lettering** part is words in any font on
the computer, standing facing you - drawn as **one stroke a letter** (the
line a neon tube follows: the letters thinned to their centre lines) or
as **the letters' outlines** (channel letters, edge-lit acrylic) - with
the letters' height, `\n` for a new line, and the wiring between strokes
the **shortest** (each next stroke the nearest end to where the last
finished) or in reading order. **An SVG drawing...** (the gallery's FROM A
FILE, or File > Import) reads a sign, a logo or lettering drawn in
Inkscape, Illustrator, Figma or a cutter's program: every path and shape -
curves, arcs, transforms, groups, `<use>` - at the drawing's real size
(its width and height in mm, cm or inches) or fitted to a width, as an
**outline** part. Either way the LEDs go a strip's spacing apart along
each stroke, the length left over split between a stroke's two ends (a
closed one, an O or a circle, leaves it where the strip's ends meet); a
mark shorter than half a spacing - an i's dot - is one LED. Text in an SVG
has no shape until it is turned into paths (Inkscape: Path > Object to
Path): the import says what it left out.

**Power**: on the Shape tab the frame's **POWER** works out where the
strips need power fed in. A strip's thin copper rails drop the voltage
along it - with the square of the length - and past about a tenth of the
supply's voltage colours shift and the far LEDs brown out. It solves the
voltage at every LED along the whole wiring (the leads between runs carry
the power on) and places feeds - the first LED, then every so many -
until none is more than the **drop allowed** down, for the **strip**'s
voltage (5, 12 or 24 V), its current an LED at full white and its rails'
resistance (typical figures; change them to your strip's sheet), at the
brightness **planned for**. It says the draw, the supply to buy (a fifth
to spare) and what the brightness limiter lets through when the Outputs
frame has a supply set; **feeds on the shape** draws them on the 3-D view
as amber rings.

**At the bench**: File > **Build sheet** writes `build_sheet.html` to the
export folder and opens it - a printable page with the shape's diagram
(parts in their colours and numbers, the data in, the feeds, the leads),
every part's LED numbers, strip to cut and where its data comes in, the
outputs, the power plan with the wire for each feed, and the checks still
open. **Print template (1:1 SVG)...** writes the shape seen flat at its
real size - every LED marked (a cross, or a hole of the diameter typed, for
a drilling template) and numbered, with a 100 mm bar to check the print -
to print at actual size, tile, or cut on a plotter or a laser.

**Parts in a graph**: the **Shape part** node says which part a pixel is
in, where along it (0..1), how many parts there are, and gives a mask for
a chosen part - one graph, the parts treated differently. **Segment per
part** gives every part its own WLED segment instead, each with its own
effect, palette and sliders (the strip layout; up to eight).

**Layout**: a shape is one logical strip in wiring order (what 1-D effects
and the 3-D nodes work on), or, as "grid", a w x h matrix the LEDs are
projected onto for WLED's 2-D effects - or the grid an xLights model came
with. **projected** says how: from the front, the side or above;
**around (unrolled)**, the angle round the shape across and its height
down, so a 2-D effect runs all the way round a tree, a column or a helix
with its two edges meeting at the back; **as a globe**, longitude across
and latitude down, for a ball or a dome; or **the best fit** (the
default), which tries them all and keeps the one that gives the most LEDs
a cell of their own, then the fullest grid. Each is fitted to the shape's
own rows and columns - a sphere's latitudes, a tree's strands - not laid
on round multiples of a spacing. Two LEDs in one cell are reported: the
cell keeps the first, and the other gets no pixel and stays dark; **grid
cell** under 1 makes the grid finer for LEDs closer than a spacing (to 256
a side). A line under it says the grid's size and whether every LED has a
cell. Effects made for any shape run on the strip by the LEDs'
real positions: the project's own graphs, and WLED's 1-D effects along
the wiring. An effect written for a matrix alone - WLED's 2-D effects and
the cube's "Ace 3-D" ones - runs as one solid colour on LEDs laid out in
one row, and a line under the effect (the side panel's EFFECT) says so
and what to pick instead, with a button, **Lay the shape out as a grid**,
that does it (the best fit). The side panel's GEOMETRY has the layout
too, as **effects see**, with the grid's size under it, and **Shape
settings...** opens the Shape frame on its Shape tab.

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

**The library** (Window > Library) shows every effect in the sim as a
looping thumbnail, in banks: **Graphs** (the project's graphs, with
their tags - what nodes they use, audio, 3-D, script), **Usermod effects**
(cube_fx, the project's code effects, the Studio Script) and **Stock**
(WLED's own). The bank in front is drawn first; a bar under the banks
shows how far the thumbnails have got. Type to search; click a tile to
run its effect in the sim (a graph is built first if it never was) - the
layout stays as it is, and a graph is waiting in the graph pane (G). Drag
a tile onto the Sequence's list of steps to add a step of that effect
there - on a row, in its place; below the rows, at the end - with the
Library and the Sequence both on screen (one among the panes or floating,
the other in the dock). A
graph not built yet shows as its script runs it, when the script can.
Every thumbnail and preview starts from a clean cube - the pixels and the
effect's memory cleared, the clock at 0 - hearing the synth, so nothing
of the effect before shows through.

The fourth bank, **Gallery**, is other people's graphs, online
([the gallery](https://github.com/Aceftwspades/wled-effects-gallery)): a
tile each, its preview turning on a cube, its author, what it is and its
tags on hover. A click fetches it into this project - checked against
the gallery's list, and asked first, since an effect is code that runs on
this computer when it is built - and it opens in the graph pane.
**Read it again** reads the list anew; **The gallery's page** opens it in the
browser. **Share this graph...** makes the graph open now into what you
send to add it: name it, say what it is in a sentence, tag it, sign it,
show its effect in the sim, and **Make the folder** puts its bundle, a
preview (the effect on screen, turning) and its entry in
`captures/gallery-share/<name>/`, then opens the folder and the gallery's
page, whose README says how to send it (a pull request, which a check
looks over).
**Generate previews** renders a turn of the 3-D view for every effect of
the bank in front (or only the tiles shown) on the project's shape, each
with the graph's own settings - a GIF and a PNG per effect in
`export/library/` with a README index, for a catalogue or a forum post -
and the tiles then show those turns. A bar shows which effect it is on
and how many are left; **Cancel** stops it after the one it is making.

The audio's major peak (the loudest band's frequency and level, which
the Freq effects, Rocktaves and Blurz place their pixels by) comes from
the sixteen bands - the synth's and live audio alike.

**Sending the sound to WLEDs**: LIVE AUDIO's **send to WLEDs** sends what
the effects here hear - the synth, live audio or an audio file - as
audioreactive's audio sync, so every WLED on the network set to receive
it moves to the same music, stock firmware too, no microphone needed.
**multicast** is how WLEDs send it themselves (239.0.0.1, port 11988);
**broadcast** is for a network that drops multicast; **unicast** sends to
the active device only. A device receives with its audio input set to
**network sound only** (Device > Audio input), or with Sync set to
Receive in its own audioreactive settings. The line under it counts the
packets sent, about fifty a second.

**Curves by hand**: select a Float curve node and the Properties pane
shows its curve large - click to add a point, drag one, right-click to
remove it; the node's small preview and its numbers follow, and the
curve runs as a script as well as compiled.

## Live video on any shape

A webcam, a video file, the screen, a phone's camera, a stream on the network
or the built-in test pattern can be the picture on any shape, with a style or a pattern layer over it. The video plays in the
studio and reaches the LEDs by streaming (**Device > Stream the sim to the
device**, Ctrl+Shift+T): the device gets the finished picture over DDP,
E1.31 or Art-Net. A device cannot play video by itself, so a graph with a
Video node shows black there when it is flashed instead of streamed.

1. **The source**: the side panel's **VIDEO** section. Choose the test
   pattern, **a video file** (**Choose...**: mp4, mov, mkv, webm, avi,
   gif; **loop the file** plays it round), **a webcam** (**Find** lists
   the cameras on this computer) or **the screen** (**Find** lists the
   whole desktop, each monitor when there are several, and on Windows each
   window on screen by its title - a music visualiser, a game, a browser
   tab's video: whatever is there reaches the LEDs), **the phone's camera**
   (the phone remote's page, Window > MIDI, OSC and phone: its **Camera**
   link on the phone, then **Start** - the panel shows the link, and needs
   the remote served over HTTPS) or **a network stream** (**address**: an
   `rtsp://`, `rtmp://`, `srt://` or `http://` stream - a phone camera
   app's such as IP Webcam, DroidCam or Larix, OBS's, an IP camera's; Enter
   plays it). **size** is how many
   pixels across the frame is decoded at - 96 is plenty for most shapes.
   **Play** starts it (again: pause, the picture holds), **Stop** closes
   it - a webcam is switched off. A small preview shows what is coming in.
   Files, webcams, the screen and streams are read by ffmpeg, which must be on the
   PATH (ffmpeg.org); the test pattern and the phone's camera need nothing. The screen is read on
   Windows, on macOS (it asks for the Screen Recording permission the first
   time) and on Linux under X11 - a Wayland session has none to offer.
   Nothing starts by itself when a project
   opens.
2. **The Video node** (Add > generate > Video) gives the video's colour at
   each pixel, and its brightness (`luma`). Its **projection** puts the
   frame on the shape: **picture** - the matrix or the cube's net as a
   flat picture, or the u and v you wire in; **front** and **top** -
   straight through a 3-D shape; **around** - wrapped round it, for a
   cylinder or a tree; **faces** - upright on every face of a cube;
   **sphere** - all round it.
3. **A style** is one step on the node: **palette** (the brightness
   through the WLED palette, so the video matches the effect),
   **posterize** (a few flat steps of each colour - **levels**), **mono**
   (shades of Colour 1), **edges** (only the outlines - **gain**) and
   **pixelate** (big blocks - **blocks**).
4. **A pattern layer**: the video's colour is a colour like any other -
   Blend it with a pattern, Layers, Mask it with stripes, Adjust or Levels
   it. The Video node's tutorial (F1 on it, then Try it) has a stripe
   layer screened over the video, ready to change.

**The Video Switchboard** (an example graph: open it from the graph pane's
list) is a VJ desk made of sub-graphs. Ten looks - Clean, Neon Edges,
Mosaic, Thermal, Halftone, Chroma Split, Melt, Motion Trails, Imprint and
Follow Spot - each a sub-graph (`fx_...`) with the same pins: u and v,
amount (the **Detail** slider) and t (turned by **Motion**), a colour out.
**Deck A** and **Deck B** pick one each, a tenth of the slider apart (the
Note on the graph lists them), and **A - B** crossfades between the decks.
**Auto mix on the bar** swings the mix to the other deck every four beats;
**Shuffle looks** deals a deck a random look as the mix leaves it, so it
comes back as something new - with both on, it runs a show by itself.
**Kaleidoscope** turns and mirror-folds where every look reads the frame.
Three looks follow what moves: **VS Motion** compares each frame's
brightness with the last (kept in the graph's fields 0 and 1), so
**Motion Trails** draws glowing tracers behind anything moving, **Imprint**
leaves fading afterimages of it, and **Follow Spot** lights a circle that
glides after the middle of the motion, with a lock-on ring. To change a
look, select its node and press Tab to enter it (Tab again, or Node >
Sub-graph > Back to the parent graph, to come back); to swap one for a
look of your own, make a sub-graph with the same pins and wire it in its
place on both decks' **VS Pick**. The **VJ frame** (below) is the same
desk made a frame of its own, with more looks and a source per deck.

## Playing it live: modulators and the mixer

**Modulators** (Playback > Modulators...) move a slider of the effect by
themselves, around where it is set - in the sim and so in the stream.
**+ Modulator** adds one; each row picks the slider, what moves it and how
far (the number after it): **a wave (LFO)** - sine, triangle, saw up or
down, square or random - over a length in beats; **on the beat**, a push
upward on each beat of the sound, eased in over 140 ms and let go over
its time; or **a step pattern** of up to 16 levels (the small sliders
under its row, **+** and **-** for more or fewer), a step every so many
beats. The beats are the show's tempo (the synth's without one). A
modulator never takes the slider over: drag the slider, play a step of
the show, move it from MIDI, and it moves around the new place; untick
it or take it away (**x**) and the slider is left where it was set.
The device does not run them: they are for the sim and the stream.

**The mixer** (Playback > Mixer...) runs a second effect beside the one
the studio has, hearing the same sound, and a fader takes the picture
from one to the other: **deck A** is the studio's effect, edited and
played as ever, **deck B** the one chosen here with **its speed** and
**its intensity**. Tick **mix in deck B**; at the fader's ends only one
deck shows, and between them the two meet through the **blend** -
crossfade, add, screen, multiply, lighten or difference - eased from
either end. **A** and **B** throw the fader to an end; **Swap** puts deck
B's effect on deck A (where its sliders can be edited) and A's on B, the
fader turned round so the picture stays. The fader is a MIDI target too
(the mixer's fader, in the MIDI frame's learn), and the phone remote shows
it while the mixer is on. What the mixer shows is what every view, the
stream, a recording, a video, an FSEQ export and a device GIF take; the
device itself has no second deck (it blends between a show's presets).

## The VJ frame

**Window > VJ** (Ctrl+Shift+J, or **VJ** on the toolbar) is a VJ's desk:
two decks, each a **video** source and a **look**, a crossfader between
them, and the mix on the shape. Tick **on air** and the mix shows in
place of the effect - in every view, and so in the stream, a recording,
a video, an FSEQ export and a device GIF; untick it and the effect is
back. It runs in the studio only: the LEDs get it by the stream. The
small picture at the top right is what is on air (dim while off air);
**BEAT** lights on each beat, **Tap** sets the show's tempo by tapping (the
Sequence's Tap; the first tap is a bar's first beat), and beside it what the
looks pulse on - **on the bar grid** (the tempo, kept on the beats the
effects hear: each pulse eased in across its beat, none on an off-beat the
detector took, none in silence) or **every beat heard** (each beat the
detector hears, off-beats and all) - and the tempo and the bar the
auto-mix counts. **cue** turns a pop-out of the 3-D view (View > Pop
out) into the cue monitor: it shows the deck off the mix - the one to set
up before fading to it - while every other view and the stream go on with
the mix. **undo** (or Ctrl+Z with the frame focused, Ctrl+Y to
redo) takes back the VJ's last change - a drag of a knob is one step.

Each deck's look is drawn on a small canvas, then laid on the shape by
**MAP**: as the logical view lays it out, through the shape from the front
or the top, round it, the same on every face, or all round it as a
sphere's map (the Video node's projections). The canvas's size is beside
it: 96 x 72 by default, coarser to cost less, finer to be sharper, or a
wide panel's (16:9), a long strip's or a tall shape's own proportions.

**Looks**: **Browse...** on a deck shows every look as a moving thumbnail,
and a click puts it on that deck; **look** lists them too:

- **Video**: the Video Switchboard's ten - Clean, Neon Edges, Mosaic,
  Thermal, Halftone, Chroma Split, Melt, Motion Trails, Imprint and Follow
  Spot (the last three follow what moves in the picture) - and **Gradient
  Map**, the video's brightness through the deck's colours: any clip in
  the set's palette.
- **Shaders**, in the Shadertoy manner - a picture worked out for every
  pixel from where it is, the time and the sound: Plasma, Tunnel, Warp,
  Voronoi, Kaleido Tunnel, Starfield, Metaballs and Beat Rings.
- **MilkDrop**, its way of making pictures: the last frame fed back,
  zoomed, turned and warped a little and faded, the sound drawn over it -
  Nebula, Vortex, Fireflies, Bloom, Liquid Mirror and Pulse Grid, in the
  deck's colours (rainbow for MilkDrop's own hues). A deck's video, when
  it has one, seeds the feedback.
- **Flames**: fractal flames (Scott Draves' algorithm, Electric Sheep's) -
  points thrown at random through a few bent maps, where they land counted
  and shown on a log scale, turning slowly. **Mutate** breeds a new flame
  from the one on the deck, kept with the project.
- **Text and image**: **Text** scrolls the deck's **words** across in its
  colours (speed 0 holds them still in the middle, fitted to the canvas -
  a logo); **Image** shows a picture file (**picture ...**), filling the
  canvas and drifting slowly - a logo, a poster.
- **Effect**: any effect of the studio's, run on the shape itself beside
  the main one (its **speed** and **amount** are the effect's Speed and
  Intensity; **its colours** and **palette** are the effect's own, or a
  gradient's three colours and a palette of your choosing - a gradient
  chosen while the palette is the effect's own makes it Color Gradient,
  the palette drawn from those colours, so the effect paints in them);
  under them, **the effect's own sliders and checks** as it names them -
  Flat mode, a size, a shape - kept with the deck and its presets).
- **Yours** (below): looks in Python, Shadertoy shaders, and MilkDrop
  presets imported.

A look changed on a deck that is showing - by hand, MIDI, the phone,
Shuffle or Mutate - blends in from its last picture over a beat rather
than jumping.

Under the preview: **level** (the deck's own, apart from the fader - turn
a deck down without moving it), **amount** (what the look makes more of:
the edges' gain, the mosaic's blocks, a shader's detail), **speed** and
**colours**. Right-click the look, a level, amount, speed or any knob under
AFTER (or the crossfader) for **Learn MIDI** - the next knob, fader or pad
moved on the controller is bound to it - or **Forget its MIDI**.
**Shuffle** deals the deck another look. The deck off the mix is shown
dimmer: it is the one to set up before fading to it - and it keeps
running (at half the frame rate), so a feedback look on it has built up
its picture by the time it is cut to. The rest is folded
away in four sections:

- **VIDEO**: the deck's source - no video, the test pattern, video files,
  a webcam, the screen (or a window), the phone's camera or a network
  stream; **...** adds files to the deck's list (several at once - each
  copied into the project's `assets/vj`, so the project keeps them when it
  is moved or shared), or picks the camera, the screen or the address; **||** pauses the video (the picture holds). Two
  decks on the same source share it (a webcam opens once). With files, the
  list picks the one playing, **>** goes to the next, **x** takes one off
  the list; **clip speed** plays it faster or slower, **from** and **to**
  play only that stretch (to 0: its end), looped; **next file** steps
  through the list by hand, every beat, or with the auto-mix's bars. A
  deck's video rolls on while the deck is off the mix, so a cut to it
  has a picture at once and the clip is where it would be.
- **SOUND**: what the deck listens to - the bass, the mid, the treble, the
  level or the beat - and what that **moves**: the amount, the speed, the
  hue, a zoom or the brightness, **by** so much. A look then answers the
  music as you set it, not only as it was written.
- **AFTER**: what is done to the look's picture - a **kaleidoscope** of so
  many mirrors, a **hue** turn, **trails** (what was there fades slowly
  behind what is), a **blur**, **mirror** and **strobe on the beat**.
- **PRESETS**: a deck's look and knobs kept by **Save as...**, put on a
  deck from the list, **Rename...**d or **Delete**d; on a bred flame, its
  own **Rename...** and **Forget** (the deck goes back to the flame it came
  from).

**DECK C - over the mix** (folded away under AUTO) is a third deck with
everything A and B have, laid over their mix at its **level** (0, the
default: not there) through its own blend - screened, added, the lighter of
each, multiplied, their difference, or **over** (what it draws covers the
mix and its black lets the mix through): words or a logo over whatever the
fader does, a strobe or a flame on top of both.

**MIX**: the crossfader (deck A at 0, B at 1), **A** and **B** throw it to
an end, **Cut** goes straight to the other deck, **Fade** sweeps there
over two beats - **now**, or **on the next beat** or **on the next bar**
of the count the auto-mix keeps (from here, MIDI or the phone alike: a
press a little early lands on the music) - and the blend (crossfade, add, screen, multiply, lighten,
difference) is how the two meet between the ends - or, in place of
**blend**, a wipe: the other deck swept, pushed or opened in as the fader
moves (the Sequence's transitions). **AUTO** moves the fader by itself:
**every few bars** (1 to 16) - on the show's bars while it plays, else on
the tempo's, kept on the beats the effects hear (a beat heard near where
the tempo puts one pulls the count onto it; one between, an off-beat,
does not count) - **Tap** the tempo in and its first tap is a bar's first
beat - or **at the show's
sections** while the Sequence plays: a cut into a drop, a slow fade into
an intro, a breakdown or the outro, two beats into the rest; **shuffle
looks** deals the deck the mix just left a new look - one no deck has,
**from any look** or **from its own family** (a flame for a flame: a set
that keeps of a piece) - so with both it plays by itself.

**Playing it**: the MIDI frame's learn lists the VJ's crossfader, Cut,
Fade, Shuffle A and B and on air, and for each deck its look (along the
list), every knob (amount, speed, hue, kaleidoscope, trails, blur), the
next video file and pause. Modulators (Playback > Modulators...) move the
decks' knobs too - "VJ A amount" and so on. The phone remote shows a VJ
card while the frame is open: the fader, Cut, Fade, On air, Shuffle A and
B, and each deck's look (picked from the list) and level - deck C's "over"
the mix.

**In a show**: a step added (or updated) from the sim while the VJ is on
air is the VJ's - its decks, fader, blend, wipe, map and canvas kept with
it and named after its looks. Played, it puts them on air, blended in
over the step's blend; a step that is not the VJ's takes the VJ off air
again, blended out the same way. When the show stops, the desk is as you
left it before the show's VJ steps took it over. A VJ step's ramps have
one more, the **VJ crossfader**: draw it on the timeline like any other,
or record it - with **record automation** armed, move the fader while the
step plays. The device plays a VJ step as the effect it was captured over;
the VJ itself is the stream's.

**Looks of your own**: **New shader...** makes a `.glsl` file in the
project's `looks/` folder and opens it in your editor: paste a shader from
shadertoy.com over it (the code of its Image tab) and save, and it runs on
its deck as it is, on the graphics card (OpenGL 3.3, through moderngl).
It has what Shadertoy gives - iTime, iResolution, iFrame, iChannel0 (the
deck's video) and iChannel1 (the sound, as Shadertoy's audio input) - and
the studio's own iBeat, iBass, iMid, iTreble, iLevel and iAmount. What its
four channels hold is chosen per channel - the deck's **video**, the
**sound** (Shadertoy's audio input), a **noise** texture (as Shadertoy's
RGBA noise), the deck's **picture**, a buffer **A** to **D**, or **none**:
by default iChannel0 is the video, 1 the sound, 2 the noise; the shader's
file can say otherwise with a line like `//@ iChannel2 = picture`, and the
deck's **channels** row (shown while a shader is on it) chooses again,
"file: ..." being what the file says. A shader of several passes - Shadertoy's
Buffer A to D and Common tabs - goes in one file, each pass after a line
`//@ buffer A` (`//@ common`, `//@ image`), with `//@ iChannel0 = A` in a
pass to read buffer A (its own: its last frame); they run A to D, then the
image. One that reads the keyboard will not run, and one that does not
compile says why, at its own line numbers. **Import...** copies MilkDrop
presets (`.milk`) and shaders (`.glsl`) into `looks/`: a preset is listed
with the MilkDrop looks and runs approximately - its zoom, rotation, warp,
stretch and drift, decay, wave, its custom shapes (sides, colours, borders,
instances, textured) and custom waves, and its per-frame, per-pixel and
per-point equations; its MilkDrop 2 warp and composite shaders are
translated to GLSL and run on the graphics card, and one that does not
translate is left out, said under the decks while the rest runs.
**New look...** makes a small Python file in the project's `looks/` folder
from an example and opens it in your editor; saved, it reloads in the frame
at once, listed under Yours (**Edit** opens it again). A Python look is a
program and runs as one: a project opened from elsewhere with Python looks
in it asks first, once, whether to run them (**Run them** allows that
project on this computer - kept in the studio's own settings, so a project
cannot allow itself); until then they are listed under the decks as not
run. Shaders and MilkDrop presets cannot run anything but their own
pictures and equations, and need no asking. It is a function `draw(c, st)` that returns the picture for
every pixel at once - numpy arrays, in the Shadertoy manner - from where
each pixel is (`c.u`, `c.v`, `c.x`, `c.y`, `c.r`, `c.a`), the time, the
beat and the sound, the deck's video and knobs, and `st`, kept from frame
to frame; the example's comments list it all, and the helpers the built-in
looks use are there too (a MilkDrop preset or a flame of your own is a few
lines). A look that fails says so under the decks and draws dark.

## A show: the Sequence frame

Window > Sequence (Ctrl+Shift+Q). A **step** is what the sim
shows when you add it - every segment's effect, sliders, palette, bounds,
opacity and blend, the colours - with a name, how long it is **held**,
how long it **blends** in from the one before, and a **brightness**.
**+ Add from the sim** puts a new step after the selected one. Each
step keeps a **look**: the colours its effect showed over the second and
a half after it was added, a strip of them - its swatch in the list and
the fill of its block on the timeline, so a fire step reads as fire. (A
step made before looks gets one the first time it is shown.)

The **transport** at the top: from the top, play from the selected step
(Space with the frame's keyboard) - playing, the same button pauses and
goes on - stop, and **loop** (round again after the last step; the
device's playlist repeats too). The clock says where the show is.

The **timeline**: the steps as blocks along the time, names and lengths
on them, the blend into each a wedge of the colour before it, each
ramp's curve across its lower half (the brightness's in gold); the
ruler along the top with the time, or the bars numbered when a tempo is
set; the beats found in an audio file as ticks along the bottom, the
file's wave faint behind. Click the ruler to go to that time (hold and
drag to scrub): the sim shows that moment, paused there until you play.
Click a step to select it, double-click to show it in the sim, drag it
to move it, drag the line after it to make it longer or shorter - on
the beats when a tempo is set (Alt: anywhere) - and drag the small
handle at the bottom of its blend to set the blend. Right-click a step
for Play from here, Show it in the sim, Update from the sim, Add from
the sim after it, Duplicate, Delete. The step playing is underlined.

**Zooming and moving along the timeline**, as in an arrangement view: the
**wheel** over it moves it along the time, **Ctrl+wheel** zooms in or
out at the pointer, and a **middle-button drag** moves it as if by hand.
The **-** and **+** over it zoom about its middle, **All** puts the
whole show across it again, and **Step** the selected step with a
little either side (**Z** and **Shift+Z** with the frame's keyboard); the
time it shows is written beside them. The strip over the timeline is the
**overview**: the whole show in its colours, with a box round the part the
timeline shows - drag the box to move along, drag its sides to zoom, or
click beside it to go there. With **follow** ticked, a playing show turns
the page when the playhead reaches the timeline's edge. A step selected in
the list while it is off the timeline is brought onto it. Drag the **grip**
under the timeline down to make it taller - the ramps and the curves'
points get the room - and up to make it smaller; the height is kept.

**The show's audio**: under the timeline, **AUDIO** holds tracks of
sound laid on the show's time - a show of light and sound made together.
**+ Audio...** puts an audio file (WAV, MP3, FLAC, OGG, M4A...; anything
but a WAV needs ffmpeg) at the playhead, or at the selected step's start,
on a track with room there (a new one when none has); the file is copied
into the project's `assets/audio`. **+ Track** adds a lane. Each clip shows
its wave and its name, and is used as the steps are: drag it to move it -
onto the beats when a tempo is set, onto a step's start or another clip's
end when it comes near (Alt: anywhere), up or down onto another track -
drag either end to trim it, and drag the small handles at its top corners
to fade it in and out. Where two clips on a track overlap they **crossfade
by themselves** over the overlap (a hollow handle is an automatic fade); a
fade dragged by hand is kept as it is (a filled handle) until **Automatic
fades** in the clip's right-click menu, which also has Play from its start,
Duplicate after it, To a new track and Delete (Delete with the frame's
keyboard too). A track's **M** mutes it; right-click a lane for Mute, Add
audio here... and Remove the track. The wheel, Ctrl+wheel, the middle
button, the overview and follow move the tracks with the steps. While the
show plays, its audio is heard - in time with it, through the computer's
sound (sounddevice) - and the effects hear it too, in place of the synth
or the live audio, so the light moves to the show's own sound. The
timeline reaches as far as the last clip; the show itself plays its steps.
A device plays the steps as presets: the audio is the studio's.

**Song sections**: a strip over the steps holds the show's sections -
Intro, Verse, Build, Drop, Breakdown, Outro - each its own colour.
**Find sections** (in the **SHOW** row) listens to the show's audio tracks
for where the sound changes and how loud each part is (Foote's audio
novelty), puts the edges on the bars (finding the tempo too when none is
set), and names each part by its loudness: rough, the way any machine's
ear is, and yours to correct. Drag an edge to move it; click a section to
select it, double-click to play from it; right-click it to call it another
kind, **Fit its steps to it** (the steps under it stretched to fill it),
Play from it, Split it at the playhead or Delete it - or right-click the
empty strip to **Add a section here**. Steps and clips snap to the
sections' edges as they do to the beats.

**Make a show...** (in the **SHOW** row) makes the steps from the audio,
as SoundSwitch's autoscript does: each section cut into steps of 2, 4 or 8
bars (**a step**), each step an effect whose energy suits its section -
calm ones for an intro, a verse or a breakdown, the brightest for a drop,
the intensity and speed ramped up over a build, a cut on the drop, slow
blends into the quiet parts, the outro faded out. **effects from** picks
the pool: the studio's and the project's effects, the MIDI setlist, or
every effect (the plain colour ones, and those that follow a hand tilting
the cube rather than the music, are left out). Each effect's energy is
measured first - its brightness and how much it moves, a second and a half
of it on a spare engine - and kept for the next time. **Make the show**
puts the steps in place of the show's (Ctrl+Z brings the old ones back;
the sections are found first when there are none), **Another take** makes
other choices among the same effects. Then edit it like any other show.

**Timecode**: the **TIMECODE** row lets a clock from outside run the
show - a DAW's timeline, a DJ's, a lighting desk's. Pick **MIDI (MTC)**
for MIDI Time Code on the MIDI frame's input port (a DAW sends it on a
virtual port - loopMIDI on Windows, the IAC bus on macOS), or **audio
(LTC)** for SMPTE timecode on an audio input (picked beside it), and type
the timecode the show starts at - 01:00:00:00 is a common one. While the
timecode runs, the show plays at its time and is put back on it whenever
they drift more than a few frames apart; where it stops, or is located
somewhere else, the show is held there; before the start it is stopped.
While the timecode stands still, the show can still be played by hand.
The words beside show the timecode coming in, its rate (24, 25, 29.97
drop-frame or 30) and whether it runs.

The **list** has a row a step: its swatch, name, effect, length (and
bars, with a tempo), and buttons to duplicate or delete it. Drag a row
by its name onto another to move it. With the frame's keyboard, Delete
removes the selected step and Ctrl+D duplicates it; Ctrl+Z undoes.
Beside the step count, the **show's length**: change it and every step
stretches or shrinks with it, in proportion.

**Every number is live.** A step's length in its row, its held seconds
and bars, its blend and brightness, the show's length, the tempo and the
beats a bar, the preset ids, a ramp's end: drag one sideways, or click
it and type, and everything that follows from it moves as you go - the
row, the card, the bars, the timeline, the show's length, the clock of
the step playing. A drag is one undo step, not one a frame. A blend
longer than its step is cut to the step.

The selected step's card: Update from the sim (what the sim shows now,
its own settings kept), Load into the sim, Duplicate, Delete; its name,
held (in seconds, and in bars with a tempo), blend, **brightness** (its
preset sets the device's; the sim shows it while the sequence plays).

**Edit live** (the checkbox beside Delete) makes the sim the selected
step: it is loaded, and the card opens an **EFFECT** section with the
side panel's controls for it - the **layer** (its segments, + and - to
add or take one away), the effect, the palette, the sliders and
checkboxes, the layer's **mirror**, reverse and swap XY (mirror Y and
reverse Y on a 2-D layer), and with more than one layer its opacity and
blend mode. A change here or in the side panel goes into the step as you
make it - a drag one undo step - and the two show the same values, each
following the other. Select another step and the sim shows it, edits
going to it; a name that was the effect's follows a new effect, a name
of its own is kept. **While the show plays** (or is held at a time),
the step on the playhead is the one edited: the selection follows the
playhead, and a change - another effect, a palette, a slider - goes into
the step playing. A slider a ramp moves is the ramp's while it plays (its
in-between values are not kept as the step's); during a blend from one
step into the next nothing is written, and the next is taken up once
the blend is done. Off, the sim is free again, to set up something new
for Add from the sim.

**RAMPS**: any slider of any segment - or the brightness - moving over
the step from its value to an end value, in a shape (straight, eased,
up and back, a jump half way); add one from "+ a ramp...", a row each.
The shape **curve** is an automation lane you draw: the ramp becomes
points on the selected step's block on the timeline (its lower half,
where the ramps' lines run), starting as the shape it had. Drag a point
to move it (the last stays at the step's end), Shift+click the lower half
for one more (on the curve whose line passes nearest), right-click a
point to take it away; the row's end value is the last point's. In the
sim they move as it plays; on the device they become sub-steps in the
playlist (about a second apiece, up to twelve - a curve's land on its
points), since a preset cannot move a slider.

**Recording automation**: the red-dot button beside Stop arms recording
(the show plays from the selected step if it was stopped). While the show
plays, move a slider - in the card, the side panel, from MIDI or the
phone - and the slider's moves are recorded into the step playing: when
the step ends (or the show is paused or stopped, or the button pressed
again) they become a **curve** ramp on it, running as you moved it over
the stretch you moved it, and as it was before and after. A slider held
still for a moment is let go; a ramp on a slider being moved gives way to
the hand while it is recorded. A take is simplified to a curve's sixteen
points, the ones that keep its shape. Stop ends the recording; undo takes
a recorded step back as it was.

**BEATS**: the tempo the show is laid on - typed, tapped (Tap, on the
beat), the synth's, or found in the audio file playing as live audio
(the file's: the tempo and the beats themselves, from the loudness
rising - rough the way tapping is), kept with the sequence. "Snap
lengths to bars" rounds every step to whole bars; "drags on the beats"
lands a dragged length on a beat. Transitions blend in the style chosen
(fade, swipes, pushes, outside-in, inside-out, circular, fairy dust -
WLED's own; on the device the style is its blend-style setting). **Render
GIF** plays the sequence once from the top and records it into `captures/`.
**Render video...** makes it an mp4 (ffmpeg on the path) frame by frame:
the show is stepped a frame's time at a time, each frame drawn at the
video's size however long it takes, so every frame is the show's and none
is skipped or repeated, and the show's **audio** tracks are mixed in for the
same stretch. Its dialog chooses the **view** (the 3-D view, the logical
net, or both side by side), the **size** (720p, 1080p, 4K, square or
portrait), the **frames a second** (24, 30, 60), the **quality** (high,
standard, a small file), the **length** (the whole show or the selected
step) and the **camera** (as it is, or turning round the shape as the show
plays), and says how many frames it will be; the choices are kept with the
show. While it renders the dialog says how far it is and how long is left,
and **Cancel the render** stops it. The 3-D view is drawn square at the
video's height, with the live view's margin round it, on the whole frame's
background; the look's spill glows in the room behind the shape and its
curve, vignette and grain cover the whole frame - a wide video has no bars.

**Export FSEQ...** makes the show an FSEQ file for **Falcon Player** (FPP),
the player of the xLights world, which plays it to any pixel controllers -
WLED among them, over DDP or E1.31. The show is stepped frame by frame as
for a video, each frame's LEDs written in wiring order, three channels a
LED (LED 0's red is channel 1); its dialog picks the **frames a second**
(40, 25 or 20 - FPP's 25, 40 and 50 ms frames), the **length** and the
**audio**: the show's tracks mixed into an MP3 beside it (a WAV without
ffmpeg), named in the file as its media, so FPP plays the sound with it.
The file is FSEQ v2, uncompressed; both go into `captures/`. In FPP,
upload the two (Content Setup > File Manager), put the sequence in a
playlist, and give each WLED a channel output at its LEDs' start channel.

**ON THE DEVICE**: "Send and run it" saves each step as a WLED preset
(ids from "presets from", existing ones overwritten) and the sequence as
a playlist preset with the lengths and blends, then starts it - about a
second a preset, since the device writes each one from its main loop
and the next is only sent once it has; "Send presets + playlist" only
saves them; "Save presets.json" writes the same for a device that is not
on the network. Effects and palettes are matched by name against the
device's own lists, and a step whose effect the device does not have is
left out and named. The line under the buttons says whether the device
has the show as it is here, or it has changed since it was sent there.

**Several devices as one stage**: with **every device of the stream**
ticked, the show goes to each device the LIVE row streams to (its
**several devices** ticked, Send to device frame) - each sent at the same
time on its own, so four devices take no longer than one - and "Send and
run it" starts them together once every one has the show: the playlists
are started by requests made at the same moment. Each device then plays
the effects on its own LEDs from its own clock; for one picture spread
over several controllers, stream it instead (the LIVE row's ranges give
each device its part), or export it for Falcon Player (Export FSEQ...).

**SCHEDULE** (folded away; its header says how many timers) is the
device's timers: "+ run the playlist at" and "+ off at" add a row - a
time of day, or sunrise / sunset with an offset in minutes, a preset,
the days - "Send the schedule" writes them to the device (and saves an
"Off" preset, id 250, for the off rows); "Read the device's" shows what
it has.

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
grip on the side panel; its **x** (or Esc while it has the focus) closes it.
Dropped on another pane's edge instead - above the 3-D view, beside the
logical view - the frame becomes a pane there, as the outline shows while
you drag: laid out with the others, its own header at its top right (float,
its grip to move it again, close). Floated, closed or docked, it leaves the
panes; a preset arrangement puts it back in the dock.
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
     node is scriptable - the studio names the one that is not (a block of
     state, per-pixel fields or a baked table: Particles, Field, Image...).
     Voronoi, Vector rotate, Adjust, Blackbody, Palette source, Previous,
     Blur, Glow and Sparkle need the Script effect of firmware from 1.4.0:
     sent to an older one, the studio says to flash it once first.
  2. **Send the effect's settings** makes the device show what the sim
     does: every segment - its effect, sliders, palette, colours, bounds,
     blend and options - and the device's segments past the sim's off.
  3. **Send the shape** uploads the ledmap (the wiring) and, for a shape,
     its positions table; **Send the ledmap only** just the wiring. Both
     ask first: a wiring that is not the device's leaves it dark or
     scrambled. **Import the device's ledmap** reads it back as the geometry.
  4. **Play a GIF on the device...** has the device play a loop by itself,
     the studio closed and no stream: **Catch the sim and send** takes
     what the sim shows from that moment - any effect, a graph, a video
     look, a show playing - for the **length** at the **frames a second**
     chosen, at the device's own matrix size, makes it a GIF, uploads it to
     the device's files under **its name** and sets the main segment to
     WLED's **Image** effect named after it (the Image effect plays the file
     its segment is named for). **Send a GIF file...** does the same with a
     GIF (or a picture) of your own, cropped to fill the matrix. It needs
     an ESP32 build (WLED_ENABLE_GIF; an ESP8266 has no GIF player) and
     room on the device's files - the studio says when there is not.
- **LIVE**, in the same frame: **stream the sim to the device** sends
  every frame the sim draws to the device over DDP (WLED's realtime
  input, on by default) - any effect, built or not, on the real LEDs at
  once; the device goes back to its own effect a couple of seconds after
  the stream stops. **over** picks the protocol, kept for each device:
  DDP, or **E1.31 (sACN)** or **Art-Net**, 170 LEDs a universe from the
  **universe** beside it - for a WLED with that receiver on in its Sync
  settings (DMX mode Multiple RGB), or a Falcon, ESPixelStick or FPP
  controller. The line under it says how the stream is going, once a
  second: the frames sent against the rate asked, the kbit/s, the
  device's own fps and how long it takes to answer (asked every two
  seconds), any send errors - and a trace of the rate beside it. The frame goes in the order the device takes it,
  which the studio asks it as the stream starts: WLED puts streamed pixels
  on its segment's places and sends them to its LEDs through its own map
  (its ledmap or 2-D setup) while its Sync settings say **Respect LED
  maps** - on by default - so the frame goes as the effect draws it, the
  whole net of a cube, and the device's map does the wiring; with that
  off it goes in the wiring order the geometry has (read the device's
  wiring first). The footer says which, and when the device lays its
  pixels out at another size than the geometry. The
  **wiring test** under it runs a chase along the wiring order (LEDs/s),
  lights one LED by its index (< > step it), one part of a shape (or the
  parts in turn), one LED output (the outputs frame's ranges), all red /
  green / blue / white for the colour order, every other LED, or a
  twinkle - in the sim and on the device when streaming - the way to
  check a new ledmap, shape or wiring before trusting it; play resumes
  the effect.
  Tick **several devices** and the stream goes to every device ticked in
  the list under it at once, each over its own protocol (set by making it
  the active device). Each gets **the whole frame** - every device the
  same picture - or **a range**: that many LEDs from that place in the
  wiring order, the first of them its own LED 0 - one shape spread over
  several controllers, a cube with a controller per face. **Fill from the
  LED outputs** hands the outputs frame's ranges to the ticked devices in
  turn; the line beside it says how the ranges cover the LEDs (any left
  out, or sent to two devices). The health line then has a line a device.
  The choice is the project's, as the ranges are its shape's.
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
  that lean on a feature you left out say so. "With the waveform" is the
  studio's audioreactive patch: besides the bands it keeps the sound's
  waveform (the Waveform node) and, on an ESP32 or an S3, which of the
  twelve notes are sounding (the Notes node); the studio computes both
  the same way from the audio it plays or hears, so the sim - and a
  stream to the device - shows what the device will. Device > Usermods and
  features manages WLED's own usermods for the project as well: tick,
  untick, add one from the tree, import a folder or zip.
  The **built-in cube effects** are in the list too, one by one, each with
  what it leans on (audio, the IMU, the shape table) and its size once
  built: an unticked one is not compiled at all (the build makes a copy of
  cube_fx without it, every helper kept), and one that needs a feature you
  left out says so. "what the project uses" ships the project's effects
  and, of the built-ins, only Studio Script (the graphs sent as scripts).
  FIRMWARE at the top picks what is flashed: **the studio's build** (all of
  the above), **a WLED release** (WLED's own binary - the version, and the
  file for the device's chip, the plainest first; downloaded once and
  kept), **WLED from the checkout** (the environment built without the
  studio's usermods) or **a .bin file** you have. Whatever it is, its image
  header says which chip it is for, and a binary for another chip than
  the device's is never sent; a firmware that is not the studio's asks
  first, as it takes the cube effects, Studio Script and the shape table
  off the device until a studio build goes on again (WLED keeps its
  settings across it). An ESP32-S3 comes in several flash sizes: pick the
  release file for your board's.
  **SEND** picks how it goes: **over the network** (the device's own
  /update - it must run WLED on this network) or **over USB**, for a new
  board, a wiped one or one that will not boot: plug it in, Refresh, pick
  the port (ESP boards' USB chips are named and listed first), and tick
  "erase everything first" for a clean start. A USB flash writes the whole
  image, bootloader and partitions too, so it takes the studio's build or
  the checkout's - not a release's or a file's .bin, which hold the
  application alone. Afterwards the board comes up as the Wi-Fi network
  **WLED-AP** (password wled1234) at 4.3.2.1 to be set up; when esptool
  cannot reach it, the log says what to try (hold BOOT, another cable, the
  environment for the chip it found). A bar under the buttons follows the
  build - from the second full build of an environment it knows how many
  files are left and says how long - and then the upload.
  **SETTINGS**: a flash over the network first copies the device's
  settings, presets, ledmap and shape table into the project's `backups/`
  (the last ten per device; its Wi-Fi passwords are never copied); "Back
  up now" does it any time and "Restore..." puts a copy back, the device
  rebooting to read it. **PREVIOUS FIRMWARE** keeps the last three images
  flashed to each device from the project, and "Send it again" puts one
  back - the undo for a flash that turned out badly. Without PlatformIO
  the frame offers **Install PlatformIO**: its own installer, run with
  this computer's Python.

**Export usermod** (File > Export usermod) writes the usermod
folder and zip for a build elsewhere. If the effects (or a graph bundle)
need firmware not every WLED tree has - the IMU driver - the studio asks
whether to include it; importing such a bundle offers to turn the feature
on and install what it carries.

## When something is wrong

- The example graphs in `examples/graphs` (a new project starts with a copy
  in its `graphs/`) are effects rebuilt from the firmware's own; `python examples/build_examples.py
  --check` compiles, builds and runs them all (and every scriptable one in
  the Script effect). `python tests/smoke_app.py` drives the app through
  its main flows and fails on any traceback; `python tests/walk_menus.py`
  calls every menu item and context-menu row. The smoke test works in a
  project of its own (made from the examples, deleted after); both turn on
  the app's remote control (`STUDIO_REMOTE_CONTROL=1`), which is off in
  everyday use.
- A frame that throws is written once to `crash.txt` in the studio's
  private scratch folder - `%TEMP%\cubefx` on Windows, `$XDG_RUNTIME_DIR/cubefx`
  or `$TMPDIR/cubefx-<uid>` on Linux and macOS (this run's; the last run's
  is `crash.prev.txt`) - and to the console, and the footer's line says so
  (the message log keeps it); the sim pauses.
- A `project.json` that does not read (a hand edit's stray comma, a write
  cut short) is kept as `project.json.bad-<time>` before anything is saved
  over it, and the studio says so; the settings are saved whole (to a
  temporary file, then moved over), and File > History keeps copies of them
  too (**The project's settings**, at most one every five minutes; their
  **changes** name the settings that differ).
- Settings > Appearance, in four tabs: **Colours** (dark, light, soft
  light or slate, and every one of the theme's seven colours editable;
  the nodes' category colours), **Selection frames** (the frames' look
  and gradients), **3-D view** (how the view is lit: a look and each
  part's strength) and **Interface size**. The window is one size for all
  of them - the largest tab's - and scrolls on a screen too short for it.
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
- **File** › New effect from a shader...
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
- **Edit** › Command palette... `Ctrl+P` — every action and menu command by name: type a few letters, Up / Down choose, Enter runs it
- **Edit** › Find / replace in code `Ctrl+F`
- **Edit** › Open code in external editor `Ctrl+E`
- **Device** › Active device › … the devices known
- **Device** › Scan the network for devices
- **Device** › Stream the sim to the device `Ctrl+Shift+T`
- **Device** › Send the graph as a script `Ctrl+Shift+D`
- **Device** › Send the current effect's settings `Ctrl+Shift+P`
- **Device** › Send the shape (ledmap + positions)
- **Device** › Send the ledmap only
- **Device** › Import the device's ledmap
- **Device** › Read the device's wiring — the order the device's LEDs are wired in, as WLED uses it (its ledmap, else its 2-D setup, else a strip), over the geometry the studio has - a cube's faces too; read only, the device is not changed
- **Device** › Import a ledmap file...
- **Device** › Usermods and features...
- **View** › Logical net `Q`
- **View** › 3-D view `E`
- **View** › Net and 3-D `W`
- **View** › Code `C`
- **View** › Graph `G`
- **View** › Presentation (hide controls) `H`
- **View** › Side panel
- **View** › Properties pane (graph) `N` — the selected node's settings and the values of its free inputs; canvas first they come up over the graph when the node has something to set, and this (N) keeps them open
- **View** › Graph: canvas first — the graph takes the window: the 3-D view in a corner of it, the properties over it when the selected node has something to set, the panel a rail of its sections, the help at the pointer; off, they sit beside the graph as panes
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
- **Node** › What each node costs (on the device)
- **Node › Show** › Collapse / expand `K`
- **Node › Show** › Hide / show unwired pins `Ctrl+H`
- **Node › Show** › Mute (pass through) `M`
- **Node › Arrange** › Arrange (the selection, or all) `Ctrl+L`
- **Node › Arrange** › Space out overlapping nodes
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
- **Playback** › Modulators...
- **Playback** › Mixer...
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
- **Window** › VJ: two decks of video and looks `Ctrl+Shift+J`
- **Window** › Snapshots... `Ctrl+Shift+K`
- **Window** › MIDI, OSC and phone...
- **Window** › Effect slots...
- **Window** › Message log...
- **Window** › Close every frame
- **Settings** › Keyboard shortcuts... `Shift+F1`
- **Settings** › Appearance... — the colours, the selection frames, how the 3-D view is lit and the interface size, a tab each
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
- **Help** › Tutorial: a tree in 3-D — a shape for real lights: a Christmas tree and its star built in the shape editor, the wiring checked, sent
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
| `Ctrl+Shift+B` | Compare side by side: before and after an edit, or another effect / stop | anywhere |
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
| `—` | Tutorial: a Christmas tree in 3-D, the shape editor step by step | anywhere |
| `—` | Node reference: every node, pin and setting | anywhere |
| `—` | Welcome: where to start | anywhere |
| `Shift+F1` | Keyboard shortcuts | anywhere |
| `Ctrl+Shift+U` | Build the firmware and flash the device | anywhere |
| `Ctrl+Shift+P` | Send the current effect's settings to the device | anywhere |
| `Ctrl+Shift+R` | Run the graph as a script (what the device would run) | anywhere |
| `Ctrl+Shift+D` | Send the graph to the device as a script | anywhere |
| `Ctrl+Shift+T` | Stream the sim to the device, on / off | anywhere |
| `Ctrl+Shift+N` | Devices on the network | anywhere |
| `Ctrl+Shift+S` | Send to device: the effects, a script, the shape | anywhere |
| `Ctrl+Shift+E` | Shape editor | anywhere |
| `Ctrl+Shift+Q` | Sequence: presets, a playlist and the schedule | anywhere |
| `Ctrl+Shift+L` | Library: every effect as a looping thumbnail | anywhere |
| `Ctrl+Shift+G` | Palettes: gradients of the project's own | anywhere |
| `Ctrl+Shift+O` | LED outputs and power | anywhere |
| `Ctrl+Shift+M` | Audio input: the device's microphone or line-in | anywhere |
| `Ctrl+Shift+J` | VJ: two decks of video and looks | anywhere |
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
| `—` | Space out nodes that overlap, the layout kept | in the graph |
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
| `—` | Measure what each node costs, here and on the device | in the graph |
| `Shift+R` | Repeat the last action | anywhere |
| `Ctrl+P` | Command palette: every action and menu command by name | anywhere |
| `Ctrl+Shift+K` | Snapshots: the graph's settings as named states | anywhere |
| `—` | MIDI, OSC and phone: knobs, faders and a phone onto the sliders | anywhere |
| `—` | Effect slots: which cube_fx effects the device lists | anywhere |
| `Ctrl+Alt+Z` | Undo history | anywhere |
| `Ctrl+Shift+Y` | History of the current graph or code | anywhere |

### Buttons

Every button, with what its tooltip says.

**Devices frame**: `dock` — dock: a tab beside the side panel's (or drag the grip onto the panes); `close` — close (Esc while the frame has the focus); the menu opens it again; `Scan the network` — asks by mDNS, asks every known device for the nodes it has heard of, and sweeps the subnet; `Stop`; `Add`; `Refresh all` — asks every listed device again what it is and runs; `use`; `remove`

**Flash firmware frame**: `dock` — dock: a tab beside the side panel's (or drag the grip onto the panes); `close` — close (Esc while the frame has the focus); the menu opens it again; `Refresh` — WLED's releases again, from GitHub; `Choose...`; `flash_env_fit`; `Preview (no compile)` — stages the build and lists what it would carry - the manifest, resolved the way the build resolves it - without compiling; `all`; `none` — the project's effects and the built-in cube effects, all or none; `what the project uses` — the project's effects, and of the built-in cube effects only Studio Script (for the graphs sent as scripts); `Usermods...`; `Install PlatformIO` — PlatformIO's own installer, downloaded and run with this computer's Python (a few minutes; it sets PlatformIO up in its own folder, ~/.platformio); `Back up now` — the device's settings, presets, ledmap and shape table into the project now (a flash over the network keeps them first anyway); its Wi-Fi passwords are never copied; `Restore...` — a backup's files back onto the device, which reboots to read them; `Send it again` — that image to the device again - undoing a flash that turned out badly; `Start`; `Cancel`; `Open the build folder`

**Send to device frame**: `dock` — dock: a tab beside the side panel's (or drag the grip onto the panes); `close` — close (Esc while the frame has the focus); the menu opens it again; `Find a device`; `Read` — ask the device again what it is and runs; `Open in the browser`; `Calibrate the speed factor` — the current effect's settings sent, the device's fps read for three seconds, and the footer's device fps estimate set from the measurement (Settings > Device speed factor holds the number); `Send the graph as a script` — the graph as bytecode for the Studio Script effect - no firmware build; the device runs it at once; `Send the effect's settings` — the effect the sim shows, with its sliders, checks, palette and colours, onto the device's segment; `Send the shape` — the ledmap (the wiring) and the positions table, so Position and Direction see the real shape; `Send the ledmap only`; `Play a GIF on the device...` — what the sim shows for a few seconds - or a GIF file - played by the device itself (WLED's Image effect): no stream needed; `Import the device's` — the device's ledmap becomes the geometry: a matrix with its gaps and wiring, or a strip; `Import a file...`; `Fill from the LED outputs`; `<`; `>`

**Shape frame**: `dock` — dock: a tab beside the side panel's (or drag the grip onto the panes); `close` — close (Esc while the frame has the focus); the menu opens it again; `Add part...` — a strip, a ring, a tree, a star... picked from pictures, its sizes asked first; it joins the end of the selected part (or goes beside it); `Draw a run` — click corners in the 3-D view and a strip is laid along them, an LED every spacing; double-click or Enter ends it, Backspace takes the last corner back, Esc leaves it; `File...` — open or save a shape; import a model, an xLights model or layout, a point list; a reference mesh; export an xLights model or the positions; a preview; `Undo`; `Redo`; `show me`; `the way its LEDs run along it` — the way its LEDs run along it: click to turn its wiring round; `shown` — shown: click to hide it while you build (it stays LEDs on the device); `click to lock it` — click to lock it: the view's clicks, handles and keys pass it by; `x` — delete the part (Undo brings it back); `delete the last`; `renumber: nearest chain from the first`; `turn into a path`; `X`; `Y`; `Z`; `+X`; `-X`; `+Y`; `-Y`; `+Z`; `-Z`; `aim outward`; `turn only`; `aim at the origin`; `from its place` — the direction and distance the part is at now, into the fields; `first`; `earlier`; `later`; `last`; `light it` — the wiring test lighting this part: in the sim, and on the device while the sim is streamed to it; `Generate a preview` — a turn of the shape, rendered off screen: a GIF and a PNG in the project's export folder, looping here; `Open the folder`

**Sequence frame**: `dock` — dock: a tab beside the side panel's (or drag the grip onto the panes); `close` — close (Esc while the frame has the focus); the menu opens it again; `play from the top`; `play from the selected step` — play from the selected step (Space while the frame has the keyboard); playing, it pauses and goes on; `stop` — stop: the sim goes back to running on its own; `record automation` — record automation: while the show plays, a slider moved (here or in the side panel) is written into the step playing as a curve ramp - over the stretch it was moved, the rest of the step as it was. Again: stop recording; `+ Add from the sim` — a new step after the selected one: what the sim shows now - effect, sliders, palette, colours, segments; `undo` — the steps (or the schedule) as they were before the last change; Ctrl+Z here does the same, Ctrl+Y redoes; `-` — zoom out (Ctrl+wheel over the timeline zooms at the pointer); `+` — zoom in (Ctrl+wheel over the timeline zooms at the pointer); `All` — the whole show across the timeline (Shift+Z); `Step` — the selected step across the timeline, a little either side (Z); `Find sections` — the show's audio listened to: its intro, verses, builds, drops, breakdowns and outro, as named sections over the steps - and its tempo, when none is set; `Make a show...` — steps laid on the sections and the bars: calm effects for the quiet parts, the brightest for the drops, the intensity rising over a build - from the effects you choose, then yours to edit; `+ Audio...` — an audio file onto the show, at the playhead (or the selected step's start), on a track with room there: heard while the show plays, and by its effects; copied into the project; `+ Track` — one more track: a lane of its own under the others, for a layer of sound over another; `a copy of this step, after it`; `this step away` — this step away (undo brings it back); `Update from the sim` — the selected step becomes what the sim shows now (its name, length, blend and ramps kept); `Load into the sim` — the sim shows the selected step (double-click it on the timeline does the same); `Duplicate` — a copy of the selected step, after it (Ctrl+D); `Delete` — the selected step away (Delete); undo brings it back; `x` — this ramp off (the others stay); `Tap` — tap tempo: tap on the beat, the bpm from the gaps; `Synth's` — the bpm of the sim's synthetic beat; `the file's` — the tempo and the beats found in the audio file playing as live audio (AUDIO > play an audio file); `Snap lengths to bars` — every step's length rounded to whole bars, so the sequence changes on the music; `Render GIF` — plays the sequence once from the top and records it as a GIF, into captures/; `Render video...` — the show made into an mp4, frame by frame at the size, rate and quality chosen, with its audio - into captures/; needs ffmpeg on the path; `Export FSEQ...` — the show frame by frame into an FSEQ file for Falcon Player, with its audio beside it - FPP plays it to the controllers, WLED among them; `Send and run it`; `Send presets + playlist` — about a second a preset: the device writes each one from its main loop, and the next is sent once it has; `Save presets.json...` — the same presets and playlist as a file, for a device that is not on the network; `+ run the playlist at`; `+ off at` — a time the lights go off: an Off preset (id 250) is saved on the device and timed; `Read the device's`; `Send the schedule`; `Run the playlist at...`

**Library frame**: `dock` — dock: a tab beside the side panel's (or drag the grip onto the panes); `close` — close (Esc while the frame has the focus); the menu opens it again; `Remake the thumbnails`; `Generate previews` — a turn of the 3-D view for every effect of the bank in front, on the project's shape - a GIF and a PNG each in export/library, with an index; the tiles then show those turns; `Cancel`; `Open the folder`; `not built yet`; `making...`

**Palettes frame**: `dock` — dock: a tab beside the side panel's (or drag the grip onto the panes); `close` — close (Esc while the frame has the focus); the menu opens it again; `undo` — the palettes as they were before the last change; Ctrl+Z here does the same, Ctrl+Y redoes; `+ New`; `From the sim's palette` — a new one that starts as the palette the sim shows; `Copy`; `Remove`; `Use in the sim`; `spread evenly`; `Send this one` — slot n is /palette{n}.json on the device, palette id 200 - n everywhere; the device reloads its custom palettes on upload; `Send all`; `Remove this one there`

**LED outputs frame**: `dock` — dock: a tab beside the side panel's (or drag the grip onto the panes); `close` — close (Esc while the frame has the focus); the menu opens it again; `one output`; `one per part`; `by count:`; `+ output`; `Read the device's`; `x`; `Send outputs + power limit` — over /json/cfg; the device re-initialises its outputs (reboot it if it does not)

**Audio input frame**: `dock` — dock: a tab beside the side panel's (or drag the grip onto the panes); `close` — close (Esc while the frame has the focus); the menu opens it again; `Read the device's` — what the device's audioreactive is set to now (its type, pins and levels), into these fields; `Send the audio input` — over /json/cfg; the levels take at once, a new type or new pins after a reboot (offered when needed); `Reboot the device` — restarts the device so a new type or new pins take effect; the LEDs go dark for a few seconds

**VJ frame**: `dock` — dock: a tab beside the side panel's (or drag the grip onto the panes); `close` — close (Esc while the frame has the focus); the menu opens it again; `undo` — the VJ's last change undone (Ctrl+Z with the frame focused, Ctrl+Y redoes); `New look...` — a look of your own: a small Python file in the project's looks/ folder, made from an example and opened in your editor - it reloads here each time it is saved; it goes on the deck off the mix; `New shader...` — a Shadertoy shader of your own: a .glsl file to paste one from shadertoy.com into (its Image tab's code) - it runs as it is, on the graphics card; `Import...` — a MilkDrop preset (.milk) or a Shadertoy shader (.glsl) copied into the project's looks/ and listed - a preset runs its motion, decay, wave, shapes, custom waves and equations, and its MilkDrop 2 shaders translated (one that does not translate is left out, and said); `Tap` — tap on the beat: the show's tempo from the gaps (the Sequence's Tap) - the first tap is the first beat of a bar; `Browse...` — every look as a moving thumbnail: click one to put it on this deck; `Shuffle` — a look this deck does not have, at random; `Mutate` — a new flame bred from this one (its maps nudged, a variation swapped) - kept with the project; `Edit` — this look's file in your editor: saved, it reloads here; `...` — the picture file the Image look shows; `||` — the video paused (the picture holds) or played on; `>` — the next file; `x` — this file off the list; `Save as...`; `Rename...`; `Delete`; `Forget` — this bred flame no longer kept; the deck goes back to the flame it came from; `A` — all deck A; `B` — all deck B; `Cut` — straight to the other deck (now, or on the next beat or bar - the choice beside Fade); `Fade` — to the other deck over two beats (now, or from the next beat or bar)

**Keyboard shortcuts**: `close` — close (Esc while it has the focus); `Reset all to defaults`

**Appearance**: `close` — close (Esc while it has the focus); `dark`; `light`; `soft light`; `slate`; `Back to the preset` — the preset's colours again, your changes dropped; `Save`; `Save + use for nodes`; `Save + use for pane`; `Delete`; `Studio`; `Glow`; `Cinematic`; `Diffused`; `Night`; `The monitor's` — the size the monitor is set to in the system's display settings; `Restart now` — the studio closes and starts again at the new size; the graph is saved, and unsaved code is asked about first

**History**: `close` — close (Esc while it has the focus); `The project's settings` — The copies kept of the project's settings (project.json: the geometry, palettes, segments, sequence, outputs), or back to those of the graph or code open

**Changes since a version**: `close` — close (Esc while it has the focus); `Restore this version` — this version back in place of what is there now (which is kept first, as any restore keeps it)

**Undo history**: `close` — close (Esc while it has the focus)

**About**: `close` — close (Esc while it has the focus); `The studio on GitHub`; `The WLED fork`; `WLED`

**Usermods and features**: `close` — close (Esc while it has the focus); `Add`; `Import a folder...`; `Import a zip...`

**Update**: `close` — close (Esc while it has the focus); `Download and install`; `Release page`; `Not now`

**A WLED checkout**: `close` — close (Esc while it has the focus); `Clone`; `Restart the studio`; `Close`

**Report a problem**: `close` — close (Esc while it has the focus); `Open the issues page` — a new issue on the studio's GitHub page, in the browser - attach the zip there; `Show the zip` — the captures folder, where the report landed; `Close`

**Map lights by camera**: `close` — close (Esc while it has the focus); `Play the plan` — in the sim - and on the device while the sim is streamed to it (Stream the sim to the device, Ctrl+Shift+T); `Stop` — the plan stopped part way; `+ a side` — another side: how far it was turned from the first, then its film; `Find` — the webcams ffmpeg can open on this computer, the phone's camera, and the VIDEO section's network stream when it has an address; `Calibrate` — every LED lit, the camera's view with the LEDs found marked: set the threshold, the LED brightness, the blob distance and size until the count is right; again: stop; `Map live` — the plan stepped through with the camera: each step lit, let settle, pictured - the next side without an empty slot gets it; `Make the part` — the lights as a points part in the shape, in wiring order: an LED no two sides saw is estimated (the shape's checks list them, to drag where they are); `Save CSV (Lightwork)` — the shape's LEDs as Lightwork's layout CSV - address,x,y,z, each 0..1 - for Lightwork's scraper, MadMapper or TouchDesigner; into the project's export folder; `Import CSV...` — a Lightwork layout CSV (address,x,y,z) as a points part, sized to its height above

**Message log**: `close` — close (Esc while it has the focus); `copy all` — the log as text, to paste into an issue or a note; `clear` — empties the recent messages; the problems stay until they are fixed

**The panes and the toolbar**: `New effect` — New effect  Ctrl+N; `Open a graph or a code effect` — Open a graph or a code effect  Ctrl+O; `Save` — Save  Ctrl+S; `Compile + reload` — Compile + reload  F5; `Live` — Live: rebuild the graph as it changes  L; `Undo` — Undo  Ctrl+Z  (nothing to undo); `Redo` — Redo  Ctrl+Y  (nothing to redo); `Play` — Play  Space; `Pause` — Pause  Space; `Step one frame` — Step one frame  .; `Restart the effect` — Restart the effect  Ctrl+R; `Logical net` — Logical net  Q; `3-D view` — 3-D view  E; `Net and 3-D` — Net and 3-D  W; `Code` — Code  C; `Graph` — Graph  G; `Zoom out` — Zoom out  Ctrl+-; `100%` — Zoom 100%  Ctrl+0; `Zoom in` — Zoom in  Ctrl+=; `Frame the whole graph` — Frame the whole graph  Home; `Add a node` — Add a node (or right-click the graph)  Shift+A; `Delete the selection` — Delete the selection  Delete  (select a node first); `Arrange the graph` — Arrange the graph  Ctrl+L; `Fold the selection into a sub-graph` — Fold the selection into a sub-graph  Ctrl+G  (select two nodes or more); `Devices on the network` — Devices on the network  Ctrl+Shift+N; `Build the firmware and flash the device` — Build the firmware and flash the device  Ctrl+Shift+U; `Send to the device` — Send to the device: the effects, a script, the shape  Ctrl+Shift+S; `Stream the sim to the device` — Stream the sim to the device (DDP, E1.31 or Art-Net)  Ctrl+Shift+T; `Shape editor` — Shape editor  Ctrl+Shift+E; `Sequence` — Sequence: presets, a playlist and the schedule  Ctrl+Shift+Q; `Library` — Library: every effect as a looping thumbnail  Ctrl+Shift+L; `Palettes` — Palettes: gradients of the project's own  Ctrl+Shift+G; `LED outputs and power` — LED outputs and power  Ctrl+Shift+O; `Audio input` — Audio input: the device's microphone or line-in  Ctrl+Shift+M; `VJ` — VJ: two decks of video and looks, crossfaded onto the shape  Ctrl+Shift+J; `Devices` — Devices on the network  Ctrl+Shift+N; `Flash` — Build the firmware and flash the device  Ctrl+Shift+U; `Send` — Send to the device: the effects, a script, the shape  Ctrl+Shift+S; `Stream` — Stream the sim to the device (DDP, E1.31 or Art-Net)  Ctrl+Shift+T; `Shape` — Shape editor  Ctrl+Shift+E; `Outputs` — LED outputs and power  Ctrl+Shift+O; `Audio in` — Audio input: the device's microphone or line-in  Ctrl+Shift+M; `Open the code in an external editor` — Open the code in an external editor  Ctrl+E; `Screenshot of the 3-D view` — Screenshot of the 3-D view  F12; `Record 15 s as a GIF` — Record 15 s as a GIF (a video: File > Record 15 s video)  Ctrl+F12; `find` — the next match (Shift+Enter in the box, or Shift+F3: the previous); the status says which of how many; `replace` — the match the cursor is on, then the next is found; `replace all`; `read from file`; `apply to file`; `< back`; `help_split`; `Move` — the handles move the selected parts: an arrow along its axis, a square in its plane, the ring in the middle in the screen's plane (G does the same from the keyboard); `Turn` — the handles turn the selected parts: a ring about its axis, 15 degrees at a time (Ctrl: free; R does the same from the keyboard); `Front` — from the front: X to the right, Z up - orthographic  (1 over the view); `Side` — from the right side: Y to the right, Z up - orthographic  (3 over the view); `Top` — from above: X to the right, Y up the screen - orthographic  (7 over the view); `Persp` — perspective - click for orthographic, sizes true across the view  (5 over the view); `tuck the 3-D view away to a tab in its c` — tuck the 3-D view away to a tab in its corner (it is not drawn while it is away); `pip_max`; `drag to size the 3-D view` — drag to size the 3-D view (or Ctrl+wheel over it); its ::: drags it to another corner; `close until another node is selected` — close until another node is selected (N keeps it open); `sec_effect_arrow`; `Lay the shape out as a grid` — the shape's LEDs projected onto a grid (the best fit), so a matrix effect draws on it - the Shape frame's Shape tab says how, and can change it; `sec_segments_arrow`; `+`; `-`; `undo` — the segments as they were before the last change (add, remove, bounds, blend, options); `sec_geometry_arrow`; `Edit the shape...`; `Shape settings...` — the Shape frame on the whole shape's settings: its sizes, what the effects see and how a grid is projected, power; `sec_colours_arrow`; `sec_parameters_arrow`; `sec_audio_arrow`; `sec_live_arrow`; `use live audio`; `play an audio file...`; `sec_video_arrow`; `Choose...` — a video file: mp4, mov, mkv, webm, avi, gif - read by ffmpeg; `Find` — the webcams ffmpeg can open on this computer, into the list; `Stop` — the source closed (a webcam switched off); the Video node goes black; `fold the panel away` — fold the panel away: the graph gets the room back; `EFFECT` — EFFECT: the project, the effect and its palette - goes to it; `SEGMENTS` — SEGMENTS: the strip's segments, their bounds and blends - goes to it; `GEOMETRY` — GEOMETRY: the shape the LEDs are on - goes to it; `COLOURS` — COLOURS: the segment's three colours - goes to it; `PARAMETERS` — PARAMETERS: the effect's sliders and checkboxes - goes to it; `AUDIO` — AUDIO: the synthetic audio's levels - goes to it; `LIVE` — LIVE: audio from a line in, a microphone or an audio file - goes to it; `VIDEO` — VIDEO: a webcam, a file, the screen, a phone or a stream, for the Video node - goes to it; `VJ - in the dock` — VJ - in the dock: opens it beside the rail; `Panel` — Panel - brings it to the front; `VJ - brings it to the front`; `x` — close VJ (the menus open it again); `Devices - brings it to the front`; `Flash - brings it to the front`; `Send - brings it to the front`; `Shape - brings it to the front`; `Sequence - brings it to the front`; `Library - brings it to the front`; `Palettes - brings it to the front`; `LED outputs - in front`; `float` — float the frame in front: a window of its own over the panes (it opens so until docked again); `stats` — every figure: the picture's brightness, contrast, unlit share and saturation; the effect's, the device's and the studio's time; the current and the limiter - live while open; `N problems` — the problems that stay until they are fixed - a click opens the log at them; `log` — the last fifty messages, the problems first; each that is about a node or a line goes to it; `the latest message` — short, the whole of it on hover; a click opens the log; `vsplit_0_0`; `vsplit_1_0`; `hsplit_0_0`; `hsplit_0_1`; `hsplit_1_0`; `hsplit_1_1`; `hsplit_2_0`; `hsplit_2_1`

<!-- uiref end -->
