"""
What every node, pin and setting does, in plain words.

Written for someone who has never built an effect: what the node is for,
what to plug into it, what comes out, and one thing to try. Merged into
the node library by nodedefs.library(), shown in the editor when a node
or a pin is hovered, in the add menu's search, and in a node's menu.

Numbers here are mostly 0..1: a slider at the top is 1, a colour channel
full is 1, a coordinate across the cube runs 0 to 1. A "turn" is one full
circle (Sine, Rotate, Wave count in turns, not degrees).

    DOCS[node] = {
        "doc":    what it does,
        "in":     {pin: what to plug in},
        "out":    {pin: what comes out},
        "params": {setting: what it changes},
    }
"""

DOCS = {
    # ------------------------------------------------------------ controls
    "Speed": {
        "doc": "The Speed slider on the WLED page, as a number from 0 (left) to 1 (right). Multiply it into a rate "
               "(Integrate's rate, a Multiply before Time) so the slider sets how fast things move.",
        "out": {"value": "the slider's position, 0..1"},
        "params": {"label": "the name the slider shows on the WLED page (set in the properties; the node's title carries it)",
                   "default": "where the slider starts, 0..255 (set in the properties)"}},
    "Intensity": {
        "doc": "The Intensity slider on the WLED page, 0..1. Use it for how much - brightness, size, how many. "
               "The label you give it is what the page shows.",
        "out": {"value": "the slider's position, 0..1"},
        "params": {"label": "the name the slider shows on the WLED page", "default": "where the slider starts, 0..255"}},
    "Custom 1": {
        "doc": "The third slider on the WLED page, 0..1, with whatever name you give it.",
        "out": {"value": "the slider's position, 0..1"},
        "params": {"label": "the name the slider shows", "default": "where the slider starts, 0..255"}},
    "Custom 2": {
        "doc": "The fourth slider on the WLED page, 0..1, with whatever name you give it.",
        "out": {"value": "the slider's position, 0..1"},
        "params": {"label": "the name the slider shows", "default": "where the slider starts, 0..255"}},
    "Custom 3": {
        "doc": "The fifth slider, 0..1. On the device it has only 32 steps, so use it for choices (a shape, a count), "
               "not for anything that should glide.",
        "out": {"value": "the slider's position, 0..1, in 32 steps"},
        "params": {"label": "the name the slider shows", "default": "where the slider starts, 0..31"}},
    "Check 1": {
        "doc": "The first checkbox on the WLED page. Plug it into a Select to switch between two behaviours, or into a "
               "Mask to turn a layer on and off.",
        "out": {"on": "true when the box is ticked"},
        "params": {"label": "the name the checkbox shows", "default": "ticked to start with"}},
    "Check 2": {
        "doc": "The second checkbox on the WLED page.",
        "out": {"on": "true when the box is ticked"},
        "params": {"label": "the name the checkbox shows", "default": "ticked to start with"}},
    "Check 3": {
        "doc": "The third checkbox on the WLED page. On a cube it is taken by 'Flat mode', so prefer the first two.",
        "out": {"on": "true when the box is ticked"},
        "params": {"label": "the name the checkbox shows", "default": "ticked to start with"}},
    "Colour 1": {"doc": "The primary colour picked on the WLED page.", "out": {"color": "that colour"}},
    "Colour 2": {"doc": "The secondary colour picked on the WLED page.", "out": {"color": "that colour"}},
    "Colour 3": {"doc": "The tertiary colour picked on the WLED page.", "out": {"color": "that colour"}},

    # ------------------------------------------------------------ signals
    "Time": {
        "doc": "The clock. t counts seconds since the effect started; feed it into a Wave, a Noise's z, or an Add to make "
               "something drift. dt is how long this frame took, for things that move a fixed amount per second.",
        "out": {"t": "seconds since the effect started", "dt": "this frame's length in milliseconds"}},
    "Audio": {
        "doc": "What the microphone hears, as numbers 0..1. volume is the overall loudness; bass, mid and treble are the "
               "low, middle and high bands; beat is true on the frame a kick lands; hit is how hard it landed. "
               "Plug bass into a brightness, beat into a Random hold or Emitters.",
        "out": {"volume": "overall loudness, 0..1", "bass": "the low band, 0..1", "mid": "the middle band, 0..1",
                "treble": "the high band, 0..1", "beat": "true for the frame a kick is detected",
                "hit": "how hard the kick was, 0..1 (0 between kicks)"}},
    "FFT bin": {
        "doc": "One of the sixteen frequency bands the microphone is split into, from low (0) to high (15). "
               "For a whole spectrum along a coordinate use Spectrum instead.",
        "out": {"level": "how loud that band is, 0..1"},
        "params": {"bin": "which band, 0 (lowest) to 15 (highest)"}},
    "Beat kick": {
        "doc": "A position that jumps forward on each beat and settles over a few frames - the way a hit should move a "
               "pattern. Add its phase to whatever you scroll (a Wave's phase, a Palette index) and the picture lurches "
               "on the kick and eases.",
        "in": {"beat": "the beat, from Audio", "throw": "how far each beat throws it"},
        "out": {"phase": "the running offset: add it to a position"}},
    "Tempo": {
        "doc": "Musical time. Wire Audio's beat in and it measures the tempo from the gaps between hits (30..300 bpm, "
               "smoothed) and counts time in beats: a Wave with `beats` / 4 on its x is one cycle a bar at whatever "
               "speed the song runs. On each hit the count snaps to the nearest whole beat, so the phase stays with "
               "the music; without beats it runs at the fallback bpm (the synth's, in the sim).",
        "in": {"beat": "the beat, from Audio", "fallback": "the bpm to run at until beats arrive"},
        "out": {"bpm": "the tempo measured", "beats": "time in beats, running", "phase": "where in the beat, 0..1",
                "bar": "where in a four-beat bar, 0..1"}},
    "Integrate": {
        "doc": "A number that keeps growing at a rate you set - the way to make a phase, a scroll or an angle that never "
               "stops. Plug a Speed slider into rate and you have a clock the slider controls. wrap makes it start "
               "over at that value (1 for a phase, 0 to never wrap).",
        "in": {"rate": "how much to add per second (a slider, a Multiply of one)",
               "reset": "true starts it from 0 again (the beat, to restart on a kick)"},
        "out": {"value": "the running total"},
        "params": {"wrap": "start over when it reaches this; 0 = never"}},
    "Envelope": {
        "doc": "Smooths a jumpy signal. It follows rises quickly (attack) and falls slowly (release), so a bass that "
               "flickers becomes a swell that breathes. Put it between Audio and anything that would flicker.",
        "in": {"x": "the signal to smooth"},
        "out": {"value": "the smoothed signal"},
        "params": {"attack": "how fast it rises, in milliseconds", "release": "how fast it falls, in milliseconds"}},
    "Random hold": {
        "doc": "A random number that stays put until the trigger fires, then picks a new one. Feed it the beat and "
               "something changes direction, colour or place on every kick and holds in between.",
        "in": {"trigger": "true to pick a new random (the beat)"},
        "out": {"value": "the current random, 0..1", "changed": "true on the frame it picked a new one"}},
    "Rising edge": {
        "doc": "Turns a switch into a tap: true for exactly one frame when its input goes from off to on. Use it when "
               "something should happen once per press or per beat, not for as long as the input stays on.",
        "in": {"x": "the switch to watch"},
        "out": {"pulse": "true for one frame when x turns on"}},
    "Spectrum": {
        "doc": "The whole spectrum as a curve you can read anywhere: index 0 is the lowest band, 1 the highest. Feed a "
               "coordinate into index and the bands spread across the cube - a graphic equaliser along u, or round "
               "the ring. smooth stops it flickering.",
        "in": {"index": "where to read, 0 (bass) .. 1 (treble); a coordinate spreads the spectrum out"},
        "out": {"level": "how loud it is there, 0..1"},
        "params": {"smooth": "0 = raw, near 1 = very smooth and slow", "interpolate": "blend between bands rather than stepping"}},
    "Frame count": {
        "doc": "first is true only on the very first frame, for setting something up once (seeding a Field). count is "
               "how many frames have run.",
        "out": {"first": "true on the first frame only", "count": "frames since the effect started"}},
    "Loudest bin": {
        "doc": "Which of the sixteen frequency bands is loudest right now, as a number from 0 (bass) to 1 (treble), and "
               "how loud it is. A hue for whatever the beat drops: kicks come out red, hi-hats blue.",
        "out": {"bin": "the loudest band, 0..1", "level": "its loudness, 0..1"},
        "params": {"from": "only look at bands from this one", "to": "up to this one"}},
    "Gravity": {
        "doc": "Which way is down, as a direction in the cube's own frame. With a motion sensor fitted it is the real "
               "down; without one it is straight down, tilted by the two inputs. Feed the direction into Dot 3 with "
               "Position to get 'height', or step along it to make things fall.",
        "in": {"tilt_x": "lean, -1..1, used when there is no sensor", "tilt_y": "lean the other way, -1..1"},
        "out": {"g": "down, as one vector wire", "gx": "down's x part", "gy": "down's y part",
                "gz": "down's z part (-1 is straight down)", "sensor": "true when a real sensor is supplying it"}},
    "Emitters": {
        "doc": "Drops a thing on the surface each time the trigger fires - up to eight alive at once - and remembers "
               "where and how old each is. Plug the beat into trigger and the Shells node reads them: rings spreading "
               "from wherever each kick landed.",
        "in": {"trigger": "true drops a new one (the beat)", "pos": "where to drop it, if not random (a vector; z = 1 is the lid)",
               "tag": "a number kept with it - a hue, say (Loudest bin)",
               "life": "how many seconds each one lives"},
        "out": {"slots": "the list - wire this to Shells", "count": "how many are alive"},
        "params": {"random": "drop each one at a random point on the surface instead of x, y, z"}},
    "Delay": {
        "doc": "Remembers a number for one frame. It is the one node a wire may loop back through: feed it a value "
               "and plug its output back into what made that value, and each frame sees last frame's result. "
               "For 'only restart the cycle when the cycle is over' and the like. The editor puts one on a wire "
               "for you when the wire would close a loop (undo takes it out again).",
        "in": {"x": "the value to remember"},
        "out": {"value": "what x was last frame (0 on the first)"}},
    "Spring": {
        "doc": "A weight on a spring. It is pulled toward target, and a kick sends it swinging: overshoot, swing back, "
               "settle. Plug the beat's hit into kick and use the value to tilt or bounce something - it will slosh "
               "like liquid rather than snap.",
        "in": {"target": "where it settles", "kick": "a push - the beat's hit"},
        "out": {"value": "where it is now", "velocity": "how fast it is moving"},
        "params": {"hz": "how many swings a second", "damping": "how quickly the swinging dies away, 0 (forever) .. 1"}},
    "Ease": {
        "doc": "A value that glides instead of jumping. Give it a target - a slider, a switch, a random - and it "
               "moves there over about `seconds`, so a change on the WLED page fades in rather than snapping.",
        "in": {"target": "where to go", "seconds": "roughly how long the glide takes"},
        "out": {"value": "where it is now", "moving": "true while it is still on its way"}},
    "Steps": {
        "doc": "A step sequencer: eight values (sliders on the node), one at a time - each trigger moves to the next, "
               "the last wraps to the first, reset goes back to the start. Trigger it from Audio's beat, a Tempo's "
               "phase through a Threshold and Rising edge, or any pulse. The value drives whatever you like: a "
               "palette index that jumps on the beat, a brightness pattern, which of the States shows.",
        "in": {"trigger": "a rise here moves to the next step", "reset": "back to the first step while true"},
        "out": {"value": "the current step's value", "step": "which step, 0..7", "changed": "true on the frame a step changes"},
        "params": {"length": "how many of the eight play", "s1": "step 1", "s2": "step 2", "s3": "step 3", "s4": "step 4",
                   "s5": "step 5", "s6": "step 6", "s7": "step 7", "s8": "step 8"}},
    "Sequencer": {
        "doc": "A timed cycle of up to four phases - a bump, a spin, a hold, a rest - each lasting the seconds you "
               "give it, started by the trigger (or straight away). It tells you which phase is on, how far "
               "through it is (0..1) and how long since the cycle began; loop makes it repeat.",
        "in": {"trigger": "true starts the cycle from the top (the beat)", "t1": "phase 1's length in seconds",
               "t2": "phase 2's length", "t3": "phase 3's length", "t4": "phase 4's length"},
        "out": {"phase": "1, 2, 3 or 4 while running, 0 when finished", "progress": "how far through the current phase, 0..1",
                "since": "seconds since the cycle started", "running": "true until the last phase ends"},
        "params": {"loop": "start again at the end", "start_running": "run once from the first frame without a trigger"}},
    "Statistics": {
        "doc": "The least, the most and the average of a field over every pixel, from last frame. Divide a field by "
               "its max to keep it in range whatever it does, or use the mean to know how much of the cube is lit.",
        "out": {"min": "the smallest value anywhere", "max": "the largest", "mean": "the average"},
        "params": {"field": "which field to measure"}},
    "Particles": {
        "doc": "Sparks, rain, fireworks, embers. Points are born at `rate` a second (and `burst size` at once when "
               "burst is true), fly with a velocity plus some random spread, fall with gravity, slow with drag, and "
               "die after `life` seconds. They stay on the cube's surface unless you say otherwise. Wire slots to "
               "Sprites to see them.",
        "in": {"rate": "how many are born a second", "burst": "true births a burst (the beat)", "burst_count": "how many in a burst",
               "pos": "where they are born (unless random)", "velocity": "the speed and direction they start with",
               "spread": "how much random is added to that", "gravity": "the pull, e.g. (0, 0, -1) for down",
               "drag": "how quickly they slow, 0 never", "life": "seconds each lives", "tag": "a number kept with each - a hue"},
        "out": {"slots": "the particles - wire this to Sprites", "count": "how many are alive"},
        "params": {"max": "the most alive at once (up to 48)", "random_pos": "born anywhere on the surface instead of at pos",
                   "on_surface": "keep them on the cube's surface", "floor": "at the bottom edge: die, bounce, or wrap to the lid"}},
    "Number": {"doc": "A fixed number you type in. Most pins can be typed straight on the node instead; this is for a "
                      "value you want to send to several places.",
               "out": {"value": "the number"}, "params": {"value": "the number"}},
    "Toggle": {"doc": "A fixed on or off.", "out": {"on": "the setting"}, "params": {"on": "on or off"}},
    "Colour": {"doc": "A fixed colour you pick.", "out": {"color": "the colour"}, "params": {"rgb": "the colour"}},

    # ------------------------------------------------------------ coords
    "Coords": {
        "doc": "Where this pixel is. u and v run 0..1 across and down the whole logical picture (on a cube, the "
               "unfolded net). cx, cy are the same centred (-1..1); r and angle are polar about the centre. The "
               "simplest way to make something vary across the strip or panel.",
        "out": {"u": "across, 0 (left) .. 1 (right)", "v": "down, 0 (top) .. 1 (bottom)",
                "cx": "across, centred: -1 .. 1", "cy": "up, centred: -1 .. 1",
                "r": "distance from the centre, 0 .. ~1.4", "angle": "angle round the centre, in radians (-pi .. pi)"}},
    "Direction": {
        "doc": "On a cube, the direction from the middle of the cube out through this pixel (a unit vector, length 1). "
               "Because it never sees the folds, anything drawn from it - Noise, Dot 3, Mirror fold - flows over "
               "every edge seamlessly. On a flat panel it is a gentle dome.",
        "out": {"dir": "the direction as one vector wire - plug it into Noise, Dot 3, Mirror fold, Torus knot",
                "nx": "the direction's x part", "ny": "its y part", "nz": "its z part (1 straight up)"}},
    "Position": {
        "doc": "This pixel's place in the cube's box, each of x, y, z from -1 to 1, z up, so the lid is z = 1. Use it "
               "where a straight line matters (slabs, planes, gravity height); use Direction for angles.",
        "out": {"pos": "the position as one vector wire", "x": "-1 (west) .. 1 (east)", "y": "-1 (south) .. 1 (north)",
                "z": "-1 (bottom) .. 1 (the lid)"}},
    "Text": {
        "doc": "Words in a 5x7 pixel font, baked into the effect (only the letters used go in). Wire Coords u, v; "
               "colour the 'on' pixels with a Palette, a Colour, anything - 'i' runs 0..1 along the text so each "
               "letter can take its own colour. To scroll, wire Time x speed into offset: the text moves left, "
               "and with loop on it comes round again after a gap of the matrix's width. size 2 doubles the "
               "pixels; row places the top of the letters (-1 centres them).",
        "in": {"u": "across, 0..1 (Coords u)", "v": "down, 0..1 (Coords v)", "offset": "scroll, in pixels - Time x speed"},
        "out": {"on": "true on a letter's pixel", "i": "which letter, 0..1 along the text"},
        "params": {"text": "the words (ASCII; only their letters are baked in)", "size": "pixels per font pixel, 1..4",
                   "row": "the top row of the letters; -1 centres them", "loop": "scroll round again after a gap of the width"}},
    "Shape part": {
        "doc": "A shape (GEOMETRY > shape) is parts in wiring order - strips, rings, panels, a cube... This says which "
               "part the pixel belongs to and where along that part it sits, so one graph can treat the parts "
               "differently: a chase along each strip, ring 2 in another colour. On a cube net or a matrix, or on "
               "the device without the shape table sent, every pixel is part 0 of 1.",
        "in": {"pick": "the part number whose mask you want (0 is the first)"},
        "out": {"part": "the part's number, 0 for the first", "along": "0 at the part's first LED, 1 at its last",
                "count": "how many parts the shape has", "mask": "true for pixels on the picked part"}},
    "Cube face": {
        "doc": "Which face this pixel is on, and where on that face - a and b run 0..1 across each face, so the same "
               "picture repeats on every face (tiles, sprites). nx, ny, nz is the face's outward normal.",
        "out": {"face": "0 east, 1 west, 2 north, 3 south, 4 lid, 5 bottom", "a": "across the face, 0..1",
                "b": "down the face, 0..1", "normal": "the face's outward direction as one vector wire",
                "nx": "the face's outward direction, x", "ny": "y", "nz": "z"}},
    "Cube ring": {
        "doc": "The cube as a well: 'around' goes once round the walls (0..1), 'depth' goes from the middle of the "
               "lid (0), over the rim (0.5), down to the bottom edge (1). Rain falls along depth; a spiral is "
               "around plus depth.",
        "out": {"around": "round the cube, 0..1 (wraps)", "depth": "0 lid centre, 0.5 rim, 1 bottom edge"}},
    "Ring to uv": {
        "doc": "The reverse of Cube ring: give it a point as around and depth and it tells you which pixel shows it, "
               "as the u, v that Previous at and Field read. Add a little to depth and you are reading the pixel one "
               "step down the wall - how fire rises and rain leaves a trail.",
        "in": {"around": "round the cube, 0..1", "depth": "0 lid centre .. 1 bottom edge"},
        "out": {"u": "that pixel, across", "v": "that pixel, down"}},
    "Position to uv": {
        "doc": "Any point in the box - even one slightly off the surface - to the pixel that shows it. Take Position, "
               "add a small step in some direction, and this tells you which pixel is that way: the neighbour a "
               "grain of sand falls into.",
        "in": {"pos": "the point, as a vector (Position plus a step)"},
        "out": {"u": "that pixel, across", "v": "that pixel, down"}},
    "Transform": {
        "doc": "Moves, turns and zooms a pair of coordinates about a pivot - feed Coords' u, v through it and "
               "anything drawn from the result pans, spins or scales. A clock into turns spins the whole picture.",
        "in": {"u": "the coordinate across", "v": "the coordinate down", "move_u": "shift across", "move_v": "shift down",
               "turns": "spin, 1 = a full circle", "zoom": "1 leaves it, 2 zooms in, 0.5 out",
               "pivot_u": "the point it turns and zooms about, across", "pivot_v": "and down"},
        "out": {"u": "the new coordinate across", "v": "the new coordinate down"}},
    "Pixel": {
        "doc": "This pixel's whole-number column, row and index. For when you want to count pixels rather than "
               "measure in 0..1.",
        "out": {"x": "column, 0 .. width-1", "y": "row, 0 .. height-1", "i": "index, row * width + column"}},

    # ------------------------------------------------------------ generate
    "Noise": {
        "doc": "Smooth random blobs - clouds, plasma, flames. Give it a point (Direction's nx, ny, nz for a seamless "
               "cube, or Coords) and it returns 0..1 that varies smoothly from place to place. Plug Time into z to "
               "make the blobs drift; raise scale for smaller blobs.",
        "in": {"x": "where to sample", "y": "where to sample", "z": "where to sample - Time makes it move",
               "scale": "how many blobs across: bigger = finer"},
        "out": {"value": "the noise, 0..1"},
        "params": {"octaves": "1 is smooth blobs; 3-5 adds finer and finer detail on top - clouds, smoke",
                   "roughness": "how strong each finer layer is, 0..1"}},
    "Voronoi": {
        "doc": "Cells. Random points are scattered through space and every pixel belongs to the nearest one - the "
               "pattern of a giraffe, dried mud, stained glass. Feed Position (seamless on the cube) and use "
               "distance for soft cells, edge for the cracks between them, id to colour each cell.",
        "in": {"pos": "where to sample (Position)", "scale": "how many cells per unit: bigger = smaller cells",
               "seed": "a different seed, different cells"},
        "out": {"distance": "how far to the nearest point, 0 at it", "edge": "0 on a cell's edge, larger toward its middle",
                "id": "a random 0..1 that is the same over the whole cell", "centre": "where the cell's point is"}},
    "Checker": {"doc": "A chessboard of 1s and 0s.", "in": {"x": "across", "y": "down", "scale": "squares per unit"},
                "out": {"value": "1 or 0, alternating"}},
    "Gradient": {"doc": "A smooth ramp in the shape you pick: along x, curved, round the centre, from the centre, "
                        "or diagonal. Feed Coords' cx, cy for the round ones.",
                 "in": {"x": "across (cx for radial and spherical)", "y": "down (cy)"}, "out": {"value": "0..1"},
                 "params": {"shape": "linear, quadratic, radial (angle round the centre), spherical (bright at the centre), diagonal"}},
    "Brick": {"doc": "A brick wall, alternate rows offset by half a brick, with a mortar gap you can size.",
              "in": {"x": "across", "y": "down", "scale": "rows of bricks per unit", "mortar": "how wide the gaps are, 0..0.5"},
              "out": {"value": "1 on a brick, 0 in the mortar", "row": "which row this brick is in", "column": "which brick along the row"}},
    "Wave": {
        "doc": "A repeating wave along its input: sine, triangle, square or saw. Feed a coordinate into x for stripes "
               "and a phase (Integrate, or Time times a speed) to scroll them. cycles is how many waves fit in one "
               "unit of x.",
        "in": {"x": "what to wave along - a coordinate", "phase": "slides the wave along; a clock scrolls it",
               "cycles": "waves per unit of x", "distort": "bends the wave with noise, 0 = straight"},
        "out": {"value": "the wave, 0..1"},
        "params": {"shape": "sine (smooth), triangle (linear), square (on/off), saw (ramp)"}},
    "Ripple": {
        "doc": "Rings spreading from a point, like a drop in water. cx, cy is the centre in the -1..1 picture; phase "
               "moves the rings outward; rings is how many.",
        "in": {"cx": "the centre, across, -1..1", "cy": "the centre, up, -1..1", "phase": "a clock spreads the rings",
               "rings": "how many rings across the picture"},
        "out": {"value": "the rings, 0..1"}},
    "Mandelbrot": {
        "doc": "The Mandelbrot set. Give it a point x, y and it says how quickly that point escapes (0 = at once, "
               "1 = never, it is inside). Scale and offset a coordinate to zoom around the edge. Julia mode draws a "
               "Julia set instead, with jx, jy as its constant.",
        "in": {"x": "the point's x (real part)", "y": "the point's y (imaginary part)",
               "jx": "the Julia constant's x (Julia mode)", "jy": "the Julia constant's y (Julia mode)"},
        "out": {"value": "0 (escaped at once) .. 1 (inside the set)"},
        "params": {"iterations": "how carefully to look - more shows finer detail, costs more",
                   "julia": "draw a Julia set instead"}},
    "Sprites": {
        "doc": "Draws Particles as dots. At each pixel: how much particle is here (a soft dot `size` across), and "
               "the nearest one's tag (colour it), age (fade it as it dies) and speed (stretch or brighten it).",
        "in": {"slots": "from Particles", "pos": "this pixel's position (Position's pos)", "size": "how big each dot is"},
        "out": {"value": "how much particle is here, 0..1", "tag": "the nearest particle's tag", "age": "its age, 0 born .. 1 dying",
                "speed": "how fast it is going"},
        "params": {"falloff": "soft (a smooth dot), hard (a disc), spark (a bright pin with a faint halo)"}},
    "Shells": {
        "doc": "Spheres growing out of every Emitter: at each pixel, how much of a shell is passing through. Wire "
               "Emitters' slots here and Position into x, y, z, and each beat becomes a ring that crosses every "
               "edge of the cube as one ring.",
        "in": {"slots": "from Emitters", "pos": "this pixel's position (Position's pos)",
               "speed": "how fast the shells grow, in cube-widths per second", "width": "how thick a shell is"},
        "out": {"value": "how much shell is here, 0..1", "tag": "the tag of the strongest shell (its colour)",
                "age": "how old that shell is, in seconds"}},
    "Reaction diffusion": {
        "doc": "Real chemistry: two substances that spread and react on a small hidden grid, making tendrils, spots and "
               "stripes that grow, split and merge - with a memory, so the picture is never the same twice. Read it "
               "with any coordinate (Coords u, v; or Cube ring). feed and kill choose the pattern family.",
        "in": {"u": "where to read, across, 0..1 (wraps)", "v": "where to read, down, 0..1"},
        "out": {"v": "the second substance - the tendrils, 0..1", "u": "the first substance - the background, 0..1"},
        "params": {"feed": "0.03 .. 0.06: how much fuel comes in", "kill": "0.055 .. 0.065: how fast the pattern dies",
                   "steps": "simulation steps per frame - faster growth, more work", "seed": "how much to start with"}},
    "Bifurcation": {
        "doc": "The famous fig-tree diagram of chaos: for each value of c across the picture, where the sequence "
               "x -> x*x + c ends up. Read it with u (the c axis) and v (the x axis); narrow the windows to zoom in. "
               "Brightness is how often the sequence lands there.",
        "in": {"u": "across: which c, 0..1 of the window", "v": "down: which x, 0..1 of the window",
               "c_lo": "the c window's left edge", "c_hi": "its right edge", "x_lo": "the x window's bottom", "x_hi": "its top"},
        "out": {"density": "how often the sequence visits here, 0..1"},
        "params": {"trail": "how long visits glow, 0 .. 0.99", "orbits": "how many steps to run each frame"}},
    "Image": {
        "doc": "A picture file, baked into the effect. Pick the file, choose how many pixels across and down and how "
               "many colours, and read it with any coordinate - Cube face's a, b puts it on every face. The device "
               "needs no file. Right-click the node to turn it into editable pixel art.",
        "in": {"u": "where to read, across, 0..1", "v": "where to read, down, 0..1"},
        "out": {"color": "the picture's colour there", "slot": "which of its colours (a number)", "on": "false where the picture is transparent"},
        "params": {"file": "the image file (png, jpg, gif...)", "width": "pixels across", "height": "pixels down",
                   "colours": "how many colours to keep", "alpha_clear": "treat transparent pixels as off"}},
    "States": {
        "doc": "Several bitmaps, one shown at a time: the states are separated by '|', each is rows of digits "
               "separated by '/' ('.' transparent) like Bitmap. The state at index is read at u, v - wire a beat "
               "counter, a Random hold or a slider into index for a face that changes, a sprite that animates. "
               "The digit is a colour slot for Colour pick; count says how many states there are.",
        "in": {"u": "across, 0..1", "v": "down, 0..1", "index": "which state, 0, 1, 2... (rounded down, clamped)"},
        "out": {"slot": "the digit at the pixel (0 where transparent)", "on": "true where the state has a pixel",
                "count": "how many states"},
        "params": {"states": "the states, '|' between them; rows of digits, '/' between rows, '.' for none"}},
    "Levels": {
        "doc": "The last touch on a colour: brightness scales it, contrast stretches it about mid grey (above 1 "
               "punchier, below 1 flatter), gamma bends it (below 1 brightens the darks). 1, 1, 1 changes nothing.",
        "in": {"color": "the colour to adjust", "brightness": "0..2, 1 as is", "contrast": "0..3, 1 as is",
               "gamma": "0.2..3, 1 as is"},
        "out": {"color": "the adjusted colour"}},
    "Flip": {
        "doc": "u and v turned round: left for right, top for bottom, or swapped so the picture lies on its "
               "diagonal. Between Coords and the nodes that draw, to mirror a whole effect without touching it.",
        "in": {"u": "across, 0..1", "v": "down, 0..1"},
        "out": {"u": "across, flipped as asked", "v": "down, flipped as asked"},
        "params": {"flip_u": "mirror left-right", "flip_v": "mirror top-bottom", "swap": "u and v exchanged"}},
    "Bitmap": {
        "doc": "Pixel art you type: one line per row, a digit for a coloured pixel, a dot for an empty one. Read it "
               "with a coordinate and send slot to Colour pick to give each digit a colour.",
        "in": {"u": "where to read, across, 0..1", "v": "where to read, down, 0..1"},
        "out": {"slot": "the digit there (0..9)", "on": "false where there is a dot"},
        "params": {"rows": "the rows: digits and dots, one row per line"}},
    "Hash": {
        "doc": "A random number that is always the same for the same inputs. Feed it a cell number and every cell gets "
               "its own fixed random - a colour per tile, a speed per column. Change seed to reshuffle them all.",
        "in": {"x": "what to hash (a cell, a column)", "y": "and this", "seed": "reshuffle: a different seed, different randoms"},
        "out": {"value": "the random, 0..1"}},
    "Torus knot": {
        "doc": "A looping, twisted tube floating inside the cube, seen from the middle. Feed it Direction and it tells "
               "you whether this pixel looks at the tube, how far along the tube that spot is (for stripes), how "
               "close to its edge (for shading), and which way its surface faces (for lighting).",
        "in": {"dir": "the pixel's direction (Direction's dir)", "tube": "how fat the tube is"},
        "out": {"on": "1 where the tube is seen, else 0", "along": "how far along the tube, 0..1 - stripes",
                "edge": "0 at the tube's middle, 1 at its edge", "normal": "which way the tube's surface faces, as a vector",
                "Nx": "which way the tube's surface faces, x", "Ny": "y", "Nz": "z"},
        "params": {"p": "how many times the knot winds round", "q": "how many times it winds through",
                   "R": "the knot's overall size", "r": "the loop's size"}},
    "Path": {
        "doc": "A route through the cube, from points you type (x, y, z in the -1..1 box, one point per ';'). "
               "For each pixel: how far it is from the route, and how far along the route the nearest point is - "
               "a light running along a track (Band on `along` plus a clock), a glowing wire, a shape's outline.",
        "in": {"pos": "this pixel's position (Position)"},
        "out": {"distance": "how far from the route", "along": "how far along it the nearest point is, 0..1", "nearest": "that point"},
        "params": {"points": "the corners: x,y,z; x,y,z; ...", "closed": "join the last point back to the first"}},
    "Sparkle": {
        "doc": "Random pixels lit. density is what fraction; change seed (Time through a Floor for steps) to make them "
               "twinkle.",
        "in": {"density": "what fraction of pixels are lit, 0..1", "seed": "a different seed lights different pixels"},
        "out": {"value": "1 where lit, else 0"}},
    "Stripes": {
        "doc": "Hard-edged bands along a coordinate. count is how many, duty how wide the bright ones are, phase "
               "scrolls them.",
        "in": {"x": "the coordinate to stripe along", "count": "how many stripes", "phase": "slides the stripes",
               "duty": "how much of each stripe is bright, 0..1"},
        "out": {"value": "1 in a stripe, else 0"}},

    # ------------------------------------------------------------ maths
    "Add": {"doc": "a + b. Offsets a value, or sums two patterns.",
            "in": {"a": "the first number", "b": "the second number"}, "out": {"result": "a + b"}},
    "Subtract": {"doc": "a - b. A difference, or a distance from a level.",
                 "in": {"a": "the number to subtract from", "b": "the number taken away"}, "out": {"result": "a - b"}},
    "Multiply": {"doc": "a x b. Scales a value (a slider times a rate), or masks one pattern with another.",
                 "in": {"a": "the first number", "b": "the second number"}, "out": {"result": "a x b"}},
    "Divide": {"doc": "a / b (0 when b is 0).", "in": {"a": "the number to divide", "b": "what to divide it by"}, "out": {"result": "a / b"}},
    "Mix": {"doc": "Slides between two values: t = 0 gives a, t = 1 gives b, halfway gives the average. Crossfades.",
            "in": {"a": "the value at t = 0", "b": "the value at t = 1", "t": "the slider, 0..1"}, "out": {"result": "the blend"}},
    "Remap": {"doc": "Changes a value's range: what was in low..in high becomes out low..out high. The everyday node for "
                     "turning a 0..1 slider into 'between 2 and 8 stripes'.",
              "in": {"x": "the value to remap"}, "out": {"result": "the remapped value"},
              "params": {"in_lo": "the input's low end", "in_hi": "the input's high end",
                         "out_lo": "what in low becomes", "out_hi": "what in high becomes"}},
    "Map range": {
        "doc": "Remap with everything on pins: what was in low..in high becomes out low..out high, with an easing curve if "
               "you want it and, with steps above 0, in whole steps. Wire a slider into out high and the range itself "
               "becomes something the user controls.",
        "in": {"x": "the value to remap", "in_lo": "the input's low end", "in_hi": "the input's high end",
               "out_lo": "what in low becomes", "out_hi": "what in high becomes", "steps": "0 for smooth, or how many steps"},
        "out": {"result": "the remapped value"},
        "params": {"ease": "how it runs between the ends: linear, smooth, ease in, ease out, ease in-out",
                   "clamp": "hold the result inside the output range"}},
    "Float curve": {
        "doc": "A curve you draw on the node: points along 0..1, each with a value, smoothly joined. Feed a "
               "gradient, a heat or a phase through it to reshape it by hand - a fade that lingers, a response "
               "that kicks in late, a bump in the middle.",
        "in": {"x": "where to read, 0..1"},
        "out": {"result": "the curve's value there"},
        "params": {"points": "the points: position and value, any number from two"}},
    "Clamp": {"doc": "Keeps a value between lo and hi.", "in": {"x": "the value to limit"}, "out": {"result": "x, held between lo and hi"},
              "params": {"lo": "the lowest allowed", "hi": "the highest allowed"}},
    "Fract": {"doc": "The part after the decimal point: 2.7 becomes 0.7. Turns a growing number into a 0..1 that wraps "
                     "- the usual way to make anything repeat.", "in": {"x": "any number"}, "out": {"result": "x's fraction, 0..1"}},
    "Abs": {"doc": "Drops the sign: -0.3 becomes 0.3. Distance from zero.", "in": {"x": "any number"}, "out": {"result": "|x|"}},
    "Power": {"doc": "x to the power e. With x in 0..1, a high e squeezes a gradient toward 0 (sharp falloff, "
                     "gloss highlights); e below 1 spreads it.", "in": {"x": "the base, usually 0..1", "e": "the exponent"}, "out": {"result": "x^e"}},
    "Floor": {"doc": "Rounds down to a whole number. Turns a smooth coordinate into cell numbers.",
              "in": {"x": "any number"}, "out": {"result": "x rounded down"}},
    "Modulo": {"doc": "The remainder after dividing by m, always 0..m. Like Fract but for any period.",
               "in": {"x": "any number", "m": "the period"}, "out": {"result": "x wrapped into 0..m"}},
    "Cosine": {"doc": "A smooth 0..1 hump for every whole number of x: 1 at 0, 0 at 0.5, 1 at 1, and so on.",
               "in": {"x": "in turns: 1 = one full cycle"}, "out": {"result": "0..1"}},
    "Band": {"doc": "A soft bright band around every whole number of x - slabs, bars, rings. sharp makes the bands "
                    "narrower.", "in": {"x": "in turns", "sharp": "1 = wide and soft, 10 = thin lines"}, "out": {"result": "0..1"}},
    "Dot 3": {"doc": "How far a point lies along a direction (the dot product). Position against Gravity gives height; "
                     "Position against a slab's direction gives which slab; Direction against a light gives brightness.",
              "in": {"a": "the point (a vector)", "b": "the direction (a vector)"},
              "out": {"result": "the distance along the direction"}},
    "Vector": {"doc": "Three numbers joined into one vector wire, for the nodes that take a vector (Dot 3, Length, "
                      "Vector math). The opposite of Vector split.",
               "in": {"x": "the x part", "y": "the y part", "z": "the z part"}, "out": {"v": "the vector"}},
    "Vector split": {"doc": "A vector wire taken apart into its three numbers.",
                     "in": {"v": "the vector"}, "out": {"x": "its x part", "y": "its y part", "z": "its z part"}},
    "Vector math": {
        "doc": "Arithmetic on vectors, chosen by the dropdown. add / subtract / multiply / min / max work part by part; "
               "scale multiplies by the number; normalize makes the length 1; cross gives the direction at right "
               "angles to both; dot, distance and length give a number (on the value pin); reflect bounces a off b; "
               "project drops a onto b.",
        "in": {"a": "the first vector", "b": "the second vector (where the op needs one)", "scale": "the number, for scale"},
        "out": {"v": "the vector result", "value": "the number result (dot, distance, length; else the result's length)"},
        "params": {"op": "which operation"}},
    "Vector rotate": {
        "doc": "Turns a vector about any axis - a whole cube tumbling in one node when fed Direction and a clock.",
        "in": {"v": "the vector to turn", "axis": "the axis to turn about (a direction)", "turns": "how far: 1 = a full circle"},
        "out": {"v": "the turned vector"}},
    "Math": {
        "doc": "One node for every sum: pick the operation from the dropdown. Covers what Add, Multiply and the rest do, "
               "plus sqrt, sign, round, ceil, snap (round to a step of b), ping-pong (bounce between 0 and b), wrap, "
               "less / greater / equal (1 or 0), sin / cos / tan in turns, log and exp.",
        "in": {"a": "the first number", "b": "the second number, where the op needs one"},
        "out": {"result": "the answer"},
        "params": {"op": "which operation"}},
    "Rotate": {"doc": "Turns a pair of coordinates round the origin. Feed a clock into turns and a pattern spins; three "
                      "of these on x, y, z tumble the whole cube.",
               "in": {"x": "the point's x", "y": "the point's y", "turns": "how far to turn: 1 = a full circle"}, "out": {"x": "the turned x", "y": "the turned y"}},
    "Length": {"doc": "Distance from the origin: the size of a 2-D or 3-D vector. Length of (cx, cy) is the radius.",
               "in": {"v": "the vector (make one with Vector for 2-D: x, y, 0)"}, "out": {"result": "its length"}},
    "Direction to": {"doc": "A direction in 3-D from two angles: turn round (a), then tilt up (b). Feed clocks in and "
                            "the direction sweeps about - a slab's normal, a light.",
                     "in": {"turns_a": "round, in turns", "turns_b": "up, in turns (0.25 = straight up)"},
                     "out": {"dir": "the direction as one vector wire", "x": "the direction's x", "y": "y", "z": "z"}},
    "Log": {"doc": "The natural logarithm. log of a radius makes rings that are evenly spaced when zooming.",
            "in": {"x": "must be positive"}, "out": {"result": "ln(x)"}},
    "Exp": {"doc": "e to the power x. A zoom that shrinks by the same proportion every second is Exp of a clock.",
            "in": {"x": "any number"}, "out": {"result": "e^x"}},
    "Mirror fold": {
        "doc": "A kaleidoscope for the whole cube. Give it a direction and it reflects that direction into one wedge, "
               "so whatever you draw from the result is mirrored over the whole solid - 6 to 120 copies depending on "
               "the symmetry. Draw after the fold, not before.",
        "in": {"v": "a direction (Direction's dir, perhaps through Vector rotate)"},
        "out": {"v": "the folded direction"},
        "params": {"symmetry": "which mirror set: dihedral n (a pie of n slices), tetrahedral, octahedral (matches the cube), icosahedral (most copies)"}},
    "Sine": {"doc": "A sine wave: -1..1, one full wave per turn of x. (Wave gives 0..1 with more shapes.)",
             "in": {"x": "in turns"}, "out": {"result": "-1 .. 1"}},
    "Smoothstep": {"doc": "A soft switch: 0 below edge 0, 1 above edge 1, an S-curve between. Turns a gradient into a soft "
                          "edge - the usual way to get 'bright near here, dark elsewhere' without a hard line. "
                          "Swap the edges to flip it.",
                   "in": {"x": "the value to soften"}, "out": {"result": "0..1"},
                   "params": {"e0": "where it starts rising", "e1": "where it reaches 1"}},
    "Threshold": {"doc": "A hard switch: on when x reaches 'at'. Gives both a true/false and a 1/0 number.",
                  "in": {"x": "the value", "at": "the level"}, "out": {"on": "x >= at", "value": "1 when on, else 0"}},
    "Select": {"doc": "One of two values, chosen by a switch: b when on, a when off. A checkbox into on and the "
                      "effect changes behaviour.",
               "in": {"on": "the switch", "a": "the value when off", "b": "the value when on"}, "out": {"result": "a or b"}},
    "Min": {"doc": "The smaller of the two. Cuts one pattern by another.", "in": {"a": "one value", "b": "the other"}, "out": {"result": "the smaller"}},
    "Max": {"doc": "The larger of the two. Lays one pattern over another, brightest wins.", "in": {"a": "one value", "b": "the other"}, "out": {"result": "the larger"}},
    "Not": {"doc": "Flips a switch: on becomes off.", "in": {"on": "the switch"}, "out": {"result": "the opposite"}},

    # ------------------------------------------------------------ colour
    "Palette": {
        "doc": "A colour from the palette chosen on the WLED page. index 0..1 runs through the palette and wraps, so a "
               "coordinate plus a clock gives a scrolling rainbow; brightness dims it. This is how most effects "
               "get their colour.",
        "in": {"index": "where in the palette, 0..1 (wraps)", "brightness": "0 dark .. 1 full"},
        "out": {"color": "the colour"}},
    "Palette source": {
        "doc": "Like Palette, but reads the 'palette source' setting - the colours the audio-reactive palettes are "
               "built from - instead of the segment's palette. Falls back to the segment's palette on a build "
               "without that usermod.",
        "in": {"index": "where in it, 0..1 (wraps)", "brightness": "0 dark .. 1 full"},
        "out": {"color": "the colour"}},
    "Colour pick": {
        "doc": "One of eight colours you set, chosen by number: 0 gives the first, 1 the second... The palette for a "
               "Bitmap's digits, or for a cell number.",
        "in": {"index": "which colour, 0..7"}, "out": {"color": "the colour"},
        "params": {"c0": "colour 0", "c1": "colour 1", "c2": "colour 2", "c3": "colour 3", "c4": "colour 4",
                   "c5": "colour 5", "c6": "colour 6", "c7": "colour 7"}},
    "HSV": {
        "doc": "A colour from hue, saturation and brightness. h goes round the rainbow (0 red, 0.33 green, 0.67 blue, "
               "1 red again, so it wraps); s 0 is white/grey, 1 full colour; v is brightness.",
        "in": {"h": "hue, 0..1 round the wheel", "s": "saturation, 0 grey .. 1 vivid", "v": "brightness, 0..1"},
        "out": {"color": "the colour"}},
    "Scale": {"doc": "Dims a colour by a number (1 leaves it, 0.5 halves it, 0 is black).",
              "in": {"color": "the colour", "by": "how much to keep, 0..1"}, "out": {"color": "the dimmed colour"}},
    "Blend": {
        "doc": "Puts one colour on top of another - the layering node. 'over' covers 'under' by amount; 'add' adds "
               "light; 'max' keeps the brighter; 'multiply' darkens; 'screen' lightens. Chain Blends to stack layers.",
        "in": {"under": "the layer below", "over": "the layer on top", "amount": "how much of 'over' shows, 0..1"},
        "out": {"color": "the result"},
        "params": {"mode": "over (cover), add (light adds up), max (brighter wins), min, multiply (darken), screen (lighten), "
                           "overlay, difference, soft light, and hue / saturation / colour / luminosity (take that part of 'over')"}},
    "Layers": {
        "doc": "A stack of up to four layers on a base colour, each with its own blend mode and amount - the "
               "whole picture's layering in one node instead of a chain of Blends. A layer with nothing wired is "
               "skipped.",
        "in": {"base": "the bottom layer", "layer 1": "the first layer on top", "amount 1": "how much of layer 1 shows, 0..1",
               "layer 2": "the next layer", "amount 2": "how much of it, 0..1", "layer 3": "the next", "amount 3": "how much, 0..1",
               "layer 4": "the top layer", "amount 4": "how much, 0..1"},
        "out": {"color": "the stack"},
        "params": {"mode 1": "how layer 1 combines: over, add, max, screen, multiply", "mode 2": "for layer 2",
                   "mode 3": "for layer 3", "mode 4": "for layer 4"}},
    "Adjust": {
        "doc": "Tweaks a colour the way a photo app does: shift the hue round the wheel, boost or drain the "
               "saturation, brighten, add contrast, apply gamma, or invert.",
        "in": {"color": "the colour to adjust", "hue": "shift round the wheel, in turns (0.5 = opposite colour)",
               "saturation": "1 leaves it, 0 makes grey, 2 doubles it", "value": "brightness multiplier",
               "contrast": "1 leaves it, above 1 pushes toward black and white", "gamma": "1 leaves it, below 1 lifts the mids",
               "invert": "swap for the opposite colour"},
        "out": {"color": "the adjusted colour"}},
    "Blackbody": {
        "doc": "The colour of something hot: a candle, a bulb, daylight, a blue-white star. Feed a heat value "
               "remapped to 1000..10000 for a fire that goes red, orange, yellow, white.",
        "in": {"kelvin": "the temperature: 1500 candle, 3000 bulb, 6500 daylight, 10000 blue-white"},
        "out": {"color": "that glow"}},
    "Colour ramp": {
        "doc": "A gradient you draw on the node: colour stops along 0..1, read at t. The strip shows it. Add and "
               "remove stops, set each one's position and colour; linear blends between them, constant makes hard "
               "bands, ease blends softly. Your own palette without leaving the graph.",
        "in": {"t": "where to read, 0..1 - a coordinate, a heat, a phase"},
        "out": {"color": "the gradient's colour there"},
        "params": {"stops": "the stops: position and colour, any number from two", "mode": "linear, constant (bands) or ease"}},
    "Mask": {"doc": "Shows a colour only where the mask is bright: colour times a 0..1 pattern. Noise as the mask makes "
                    "clouds of that colour.",
             "in": {"color": "the colour", "mask": "0 hides it .. 1 shows it"}, "out": {"color": "the masked colour"}},
    "Previous at": {
        "doc": "What another pixel showed last frame. Give it a u, v and you read that pixel's colour from the frame "
               "before - read the pixel below to make things rise, beside to smear, and feed the result back into "
               "the output (through a Fade) for trails.",
        "in": {"u": "which pixel, across, 0..1", "v": "which pixel, down, 0..1"},
        "out": {"color": "that pixel's colour last frame"}},
    "Field": {
        "doc": "A hidden number stored per pixel between frames - a simulation's memory (heat, water, sand) kept "
               "separate from the colour. This reads last frame's value at any pixel; Field write stores this "
               "pixel's new value. Two fields per graph, 0 and 1.",
        "in": {"u": "which pixel, across, 0..1", "v": "which pixel, down, 0..1"},
        "out": {"value": "the stored number there, from last frame"},
        "params": {"field": "which field, 0 to 3"}},
    "Field write": {
        "doc": "Stores a number for this pixel, to be read by Field next frame. The other half of a simulation: "
               "compute the new heat, write it here, read it back next frame with Field.",
        "in": {"value": "this pixel's number for next frame"},
        "params": {"field": "which field, 0 to 3"}},
    "Drain": {
        "doc": "Water running downhill over the pixels. Given a height field and a water field, it tells each pixel "
               "how much water flows into it from the neighbours that are higher, whether it is a sink (a hollow), "
               "and its height. Write the height and the new water back with Field write and you have rivers.",
        "out": {"water": "the water arriving here this frame", "sink": "true if nothing around is lower",
                "height": "this pixel's height, from the field"},
        "params": {"height_field": "the field holding heights", "water_field": "the field holding water"}},
    "Blur": {
        "doc": "Last frame's picture, softened: the average of the pixels around this one. Blend it under the new "
               "picture for softness, or add a little of it for a glow.",
        "out": {"color": "the blurred colour here"},
        "params": {"radius": "how wide the blur is, in pixels (1 = the 3 x 3 around)"}},
    "Glow": {
        "doc": "Bloom: a colour plus a blurred copy of last frame's picture, so anything bright bleeds light into "
               "its neighbours. Put it just before Output.",
        "in": {"color": "the picture", "amount": "how much glow, 0..1"},
        "out": {"color": "the picture with its glow"},
        "params": {"radius": "how far the glow reaches, in pixels"}},
    "Previous": {
        "doc": "This pixel's own colour last frame. Fade it a little and Blend the new picture on top and everything "
               "leaves a trail.",
        "out": {"color": "last frame's colour here"}},
    "Fade": {"doc": "Dims a colour by keep - the same as Scale, named for what it does after Previous: keep 0.9 and "
                    "trails fade over about a second.",
             "in": {"color": "the colour", "keep": "how much survives each frame, 0..1"}, "out": {"color": "the faded colour"}},
    "Split": {"doc": "Takes a colour apart into red, green, blue and brightness, each 0..1.",
              "in": {"color": "the colour to take apart"}, "out": {"r": "red, 0..1", "g": "green", "b": "blue", "luma": "perceived brightness"}},
    "Combine": {"doc": "Makes a colour from red, green and blue amounts, each 0..1.",
                "in": {"r": "red, 0..1", "g": "green", "b": "blue"}, "out": {"color": "the colour"}},

    # ------------------------------------------------------------ custom
    "Expression": {
        "doc": "A node you write yourself: one line of C++ giving a number, using a, b, c and the pixel's coordinates "
               "(u, v, cx, cy, r, ang, nx, ny, nz, t). For the one calculation the other nodes do not have.",
        "in": {"a": "a number your expression can use", "b": "another", "c": "another"},
        "out": {"result": "what the expression gives"},
        "params": {"expr": "the C++ expression, e.g. sinf(a * 6.283f) * b"}},
    "Colour expression": {
        "doc": "A node you write yourself, giving a colour: one line of C++, with a, b and the colour 'under' to use. "
               "Helpers: gc_hsv(h, s, v), mq_scale(c, 0..255), color_blend(a, b, 0..255), SEGCOLOR(0).",
        "in": {"a": "a number", "b": "another", "under": "a colour"},
        "out": {"color": "what the expression gives"},
        "params": {"expr": "the C++ expression"}},

    # ------------------------------------------------------------ output
    "Output": {"doc": "The colour this pixel will show. Every graph needs exactly one.",
               "in": {"color": "the final colour"}},
    "Effect settings": {
        "doc": "Settings for the effect as a whole: which palette it starts with, whether it is for a strip, a "
               "matrix or both, whether it wants audio, and names for the colour pickers. One per graph.",
        "params": {"palette": "the palette id it starts with (11 is Rainbow)", "dimensions": "where it runs",
                   "audio": "what it listens to, if anything", "colours": "names for the three colour pickers, comma separated"}},

    # ------------------------------------------------------------ graph
    "Graph input": {
        "doc": "When this graph is used as a node inside another graph, this is one of that node's input pins. Name "
               "it, choose its type, and give it a default for when nothing is wired in.",
        "out": {"value": "whatever the parent wires in (or the default)"},
        "params": {"name": "the pin's name on the outer node", "type": "number, colour or switch", "default": "the value when unwired"}},
    "Graph output": {
        "doc": "When this graph is used as a node inside another graph, this is one of that node's output pins.",
        "in": {"value": "what the outer node's pin gives"},
        "params": {"name": "the pin's name on the outer node", "type": "number, colour or switch"}},
    "Knot": {"doc": "A bend in a wire, to route it neatly. Changes nothing.", "in": {"in": "any number"}, "out": {"out": "the same value"}},
    "Knot colour": {"doc": "A bend in a colour wire. Changes nothing.", "in": {"in": "any colour"}, "out": {"out": "the same colour"}},
    "Send": {
        "doc": "A wire with no line drawn. Whatever feeds a Send named `bass` reaches every Receive named `bass`, "
               "wherever they sit - the compiler joins each pair and both nodes vanish, so they cost nothing. "
               "For a value used all over a big graph (the beat, the time, a master speed) without wires crossing "
               "everything. Names are local to one graph file; a Send with nothing wired in sends the value typed "
               "on it. A loop through a pair is a loop like any other.",
        "in": {"in": "the number to send"}, "params": {"name": "the name its Receives answer to"}},
    "Receive": {
        "doc": "The other end of a Send: gives what feeds the Send of the same name. A Receive with no Send of its "
               "name is an error (the node says so).",
        "out": {"out": "what the Send is fed"}, "params": {"name": "the Send to listen to"}},
    "Send colour": {
        "doc": "A Send for a colour: what feeds it reaches every Receive colour of the same name.",
        "in": {"in": "the colour to send"}, "params": {"name": "the name its Receive colours answer to"}},
    "Receive colour": {
        "doc": "The other end of a Send colour: the colour fed to the Send colour of the same name.",
        "out": {"out": "the colour the Send colour is fed"}, "params": {"name": "the Send colour to listen to"}},
    "Scope": {
        "doc": "A plot of whatever is wired in, in the node: the last seconds of it, its min and max written. A "
               "frame-scope value as it is, a per-pixel one at the centre pixel. Leave one on a wire to watch it; "
               "the compiler skips it, so it costs the effect nothing.",
        "in": {"x": "the value to watch"}, "params": {"seconds": "how long a stretch the plot shows"}},
    "Note": {"doc": "A note to yourself on the graph. Not part of the effect.", "params": {"text": "the note"}},
    "Frame": {"doc": "A titled box to group nodes. Drag it and the nodes inside come along. Not part of the effect.",
              "params": {"title": "the box's title", "w": "width", "h": "height", "colour": "its colour"}},
}


def apply(lib):
    """Merge these docs into a library: the node's doc, and a `doc` on each
    input, output and param. A definition's own doc is used where none is
    written here; a pin with nothing to say keeps its name."""
    for name, d in lib.items():
        nd = DOCS.get(name)
        if not nd:
            continue
        if nd.get("doc"):
            d["doc"] = nd["doc"]
        for key, pins in (("in", d["inputs"]), ("out", d["outputs"]), ("params", d["params"])):
            docs = nd.get(key, {})
            for p in pins:
                if docs.get(p["name"]):
                    p["doc"] = docs[p["name"]]
    return lib


def gaps():
    """Every node, pin and setting with nothing written about it. Empty
    is the rule: a new node is not finished until this is empty and
    NODES.md has been regenerated."""
    from native.nodedefs import library
    out = []
    for name, d in library().items():
        if name not in DOCS or not d.get("doc"):
            out.append(name)
        for key, pins in (("in", d["inputs"]), ("out", d["outputs"]), ("params", d["params"])):
            for p in pins:
                if not p.get("doc"):
                    out.append(f"{name} . {p['name']}")
    return out


def markdown():
    """The whole reference as Markdown, one section per category."""
    from native.nodedefs import library
    lib = library()
    order = ["controls", "signals", "coords", "generate", "maths", "colour", "custom", "output", "graph"]
    cats = {}
    for name, d in lib.items():
        cats.setdefault(d["cat"], []).append((name, d))
    out = ["# The nodes", "",
           "What every node, pin and setting does. Numbers are mostly 0..1; a 'turn' is one full circle.",
           "Hover a node or a pin in the editor and the same text appears under the toolbar.", ""]
    for c in order + sorted(k for k in cats if k not in order):
        if c not in cats:
            continue
        out += [f"## {c}", ""]
        for name, d in sorted(cats[c]):
            out += [f"### {name}", "", d.get("doc", ""), ""]
            for title, key in (("Inputs", "inputs"), ("Outputs", "outputs"), ("Settings", "params")):
                pins = d.get(key, [])
                if not pins:
                    continue
                out.append(f"**{title}**")
                from native.nodeface import label
                for p in pins:
                    # the name the node shows, and its key where that differs: what an expression may call it by
                    shown = label(name, p["name"])
                    key_ = f" `{p['name']}`" if shown != p["name"] else ""
                    out.append(f"- **{shown}**{key_} *({p['type']})*: {p.get('doc', '')}")
                out.append("")
    return "\n".join(out)


if __name__ == "__main__":
    import os, sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    missing = gaps()
    if missing:
        print("undocumented:", ", ".join(missing))
        sys.exit(1)
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "NODES.md")
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(markdown())
    print("wrote", path)
