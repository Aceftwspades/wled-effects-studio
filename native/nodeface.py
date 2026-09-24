"""The face of a node - what a rack module shows without being read:
the function it computes as one line, its category's hue, the shape of
its transfer, the range of its outputs, a thumbnail of its pattern.
Pure Python (numpy for the thumbnails): graph_ui.py draws what this
computes, and the tests read it without a window.

    summary(n, d, wired)        "a + 0.5", "0..1 -> 3..5", "sine x 3 cycles"
    CATEGORY_HUES[d["cat"]]     the title bar's colour
    transfer(n, d, wired)       [(x, y)] of a one-in one-out maths node, or None
    out_range(n, d, name)       (lo, hi) of an output whose range is known, or None
    pattern(n, d, wired, N)     an N x N array of 0..1 for a pattern node, or None
    ramp_strip(n, d, k)         k colours across a Colour ramp / Blackbody / Colour pick
"""
import math
import os
import re

import numpy as np

# --- a face per category ---------------------------------------------------------
# nine muted hues, apart from each other, dark enough for white text
CATEGORY_HUES = {
    "signals":  (46, 84, 122),      # blue: what changes with time
    "coords":   (40, 96, 90),       # teal: where the pixel is
    "generate": (96, 70, 122),      # violet: patterns
    "maths":    (66, 70, 84),       # slate: the plain operators (the commonest, so the quietest)
    "colour":   (128, 70, 58),      # rust
    "controls": (112, 92, 40),      # amber: the sliders
    "graph":    (58, 62, 70),       # grey: structure
    "output":   (126, 52, 82),      # magenta: the LEDs
    "custom":   (52, 104, 66),      # green: your own code
    "subgraphs": (54, 88, 104),     # steel: a graph of your own, folded
}
CATEGORY_ORDER = ("controls", "signals", "coords", "generate", "maths", "colour", "custom", "graph", "output")


def hue(cat):
    return CATEGORY_HUES.get(cat, CATEGORY_HUES["graph"])


# --- the function as one line ------------------------------------------------------
_WIRED = object()


def _fmt(v):
    if v is _WIRED or v is None:
        return "?"
    if isinstance(v, bool):
        return "on" if v else "off"
    if isinstance(v, (int, float)):
        if isinstance(v, float) and not math.isfinite(v):
            return str(v)
        if abs(v) < 1e7 and float(v) == int(v):
            return str(int(v))
        s = f"{v:.3g}"
        return s.replace("e+0", "e").replace("e-0", "e-")
    if isinstance(v, (list, tuple)):
        if len(v) == 3 and all(isinstance(c, int) for c in v):
            return "#%02x%02x%02x" % tuple(max(0, min(255, c)) for c in v)
        return "(" + ", ".join(_fmt(c) for c in v) + ")"
    return str(v)


def values(n, d, wired):
    """{name: value} for the node's inputs and params: the typed value, or
    the pin's name when a wire feeds it (the wire says what it is)."""
    out = {}
    ins = n.get("inputs", {}) if isinstance(n.get("inputs"), dict) else {}
    for i in d["inputs"]:
        out[i["name"]] = i["name"] if i["name"] in wired else ins.get(i["name"], i.get("default"))
    for p in d["params"]:
        out[p["name"]] = n.get("params", {}).get(p["name"], p.get("default"))
    return out


def _g(V, name):
    """A value as text: the pin's name when wired, else the number."""
    v = V.get(name)
    return v if isinstance(v, str) and v == name else _fmt(v)


_FUNCS = (("cfx_sinf16", "sin"), ("cfx_atan2f", "atan2"), ("floorf", "floor"), ("fabsf", "abs"), ("powf", "pow"),
          ("sqrtf", "sqrt"), ("expf", "exp"), ("logf", "log"), ("cosf", "cos"), ("sinf", "sin"), ("fmaxf", "max"),
          ("fminf", "min"), ("gc_sat", "sat"), ("gc_vlen", "length"), ("gc_hash", "hash"), ("gc_hsv", "hsv"),
          ("gc_blackbody", "blackbody"), ("gc_adjust", "adjust"), ("mq_scale", "scale"), ("gc_v3", "vec"),
          ("gc_vdot", "dot"), ("gc_vnorm", "normalise"), ("gc_vsub", "sub"), ("gc_vadd", "add"), ("gc_vscale", "scale"),
          ("gc_col2v", "components"), ("gc_mandel", "mandel"), ("color_add", "add"))


def _pretty(expr, V):
    """A code template's expression as a formula: values in for the typed
    pins, C's spelling out."""
    def sub_in(m):
        name = m.group(1)
        v = V.get(name, _WIRED)
        return name if (isinstance(v, str) and v == name) else (_fmt(v) if v is not _WIRED else name)
    expr = re.sub(r"\$in\.(\w+)", sub_in, expr)
    expr = re.sub(r"\$p\.(\w+)", lambda m: _fmt(V.get(m.group(1))), expr)
    expr = re.sub(r"\$st\.(\w+)", r"\1'", expr)
    expr = expr.replace("$first", "first")
    expr = expr.replace("6.28318531f", "2pi").replace("6.2831853f", "2pi").replace("3.14159265f", "pi")
    expr = re.sub(r"(\d)\.0f\b", r"\1", expr)
    expr = re.sub(r"(\d)f\b", r"\1", expr)
    expr = re.sub(r"\((?:const )?(?:u?int(?:8|16|32)_t|int|float|bool|uint8_t)\)", "", expr)
    for a, b in _FUNCS:
        expr = re.sub(r"\b" + re.escape(a) + r"\b", b, expr)
    expr = expr.replace("*", "×")
    expr = re.sub(r"\s+", " ", expr).strip()
    while expr.startswith("(") and expr.endswith(")") and _balanced(expr[1:-1]):
        expr = expr[1:-1].strip()
    return expr


def _balanced(s):
    depth = 0
    for c in s:
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth < 0:
                return False
    return depth == 0


def _generic(n, d, V):
    """One-statement code reads as its expression; anything else lists
    the typed values that shape it."""
    code = (d.get("code") or "").strip()
    m = re.fullmatch(r"\$out\.(\w+)\s*=\s*(.+?);", code, re.S)
    if m and "\n" not in code and "$out." not in m.group(2):
        return _pretty(m.group(2), V)
    parts = []
    for i in d["inputs"]:
        v = V.get(i["name"])
        if isinstance(v, str) and v == i["name"]:
            continue                                        # wired: the wire says
        if i["type"] in ("float", "bool", "vector") and v is not None:
            parts.append(f"{i['name']} {_fmt(v)}")
    for p in d["params"]:
        if p["type"] in ("float", "int", "bool", "choice", "color") and p["name"] in V:
            parts.append(f"{p['name']} {_fmt(V[p['name']])}")
    return ", ".join(parts[:4])


def _rows_size(rows):
    rs = [r for r in str(rows).split("/") if r != ""]
    return (max((len(r) for r in rs), default=0), len(rs))


_MATH_BINARY = {"add": "+", "subtract": "-", "multiply": "×", "divide": "÷", "power": "^", "modulo": "mod",
                "min": "min", "max": "max", "smooth min": "smin", "smooth max": "smax", "less": "<", "greater": ">",
                "equal": "=", "atan2": "atan2", "wrap": "wrap", "snap": "snap", "pingpong": "pingpong"}

SUMMARY = {
    "Remap":      lambda V, x: f"{_fmt(V['in_lo'])}..{_fmt(V['in_hi'])} -> {_fmt(V['out_lo'])}..{_fmt(V['out_hi'])}",
    "Map range":  lambda V, x: f"{_g(V, 'in_lo')}..{_g(V, 'in_hi')} -> {_g(V, 'out_lo')}..{_g(V, 'out_hi')}"
                               + ("" if V.get("ease") == "linear" else f", {V.get('ease')}") + (", clamped" if V.get("clamp") else ""),
    "Smoothstep": lambda V, x: f"edges {_fmt(V['e0'])}..{_fmt(V['e1'])}",
    "Clamp":      lambda V, x: f"{_fmt(V['lo'])}..{_fmt(V['hi'])}",
    "Threshold":  lambda V, x: f"{_g(V, 'x')} >= {_g(V, 'at')}",
    "Mix":        lambda V, x: f"{_g(V, 'a')} <-> {_g(V, 'b')} by {_g(V, 't')}",
    "Select":     lambda V, x: f"{_g(V, 'on')} ? {_g(V, 'b')} : {_g(V, 'a')}",
    "Math":       lambda V, x: (f"{_g(V, 'a')} {_MATH_BINARY[V['op']]} {_g(V, 'b')}" if V.get("op") in _MATH_BINARY
                                else f"{V.get('op')}({_g(V, 'a')})"),
    "Vector math": lambda V, x: f"{V.get('op')}, scale {_g(V, 'scale')}",
    "Wave":       lambda V, x: f"{V.get('shape')} × {_g(V, 'cycles')} cycles"
                               + (f", phase {_g(V, 'phase')}" if V.get("phase") not in (0.0, 0) else "")
                               + (f", distort {_g(V, 'distort')}" if V.get("distort") not in (0.0, 0) else ""),
    "Noise":      lambda V, x: f"scale {_g(V, 'scale')}, {_fmt(V.get('octaves'))} octave" + ("" if V.get("octaves") == 1 else "s"),
    "Ease":       lambda V, x: f"-> {_g(V, 'target')} in {_g(V, 'seconds')} s",
    "Envelope":   lambda V, x: f"attack {_fmt(V['attack'])} ms, release {_fmt(V['release'])} ms",
    "Integrate":  lambda V, x: f"+{_g(V, 'rate')} /s" + (f", wrap {_fmt(V['wrap'])}" if (V.get("wrap") or 0) > 0 else ""),
    "Spring":     lambda V, x: f"{_fmt(V['hz'])} Hz, damping {_fmt(V['damping'])}",
    "Steps":      lambda V, x: f"{int(V.get('length') or 8)} steps: " + " ".join(_fmt(V.get(f's{k}')) for k in range(1, int(V.get('length') or 8) + 1)),
    "Sequencer":  lambda V, x: f"{_g(V, 't1')} {_g(V, 't2')} {_g(V, 't3')} {_g(V, 't4')} s" + (", loop" if V.get("loop") else ""),
    "Tempo":      lambda V, x: f"fallback {_g(V, 'fallback')} bpm",
    "Delay":      lambda V, x: "last frame's x",
    "Random hold": lambda V, x: "a new random on each trigger",
    "Rising edge": lambda V, x: "a pulse as x goes on",
    "Beat kick":  lambda V, x: f"throw {_g(V, 'throw')}",
    "Palette":    lambda V, x: (x.get("palette") or "the segment's palette") + (f", × {_g(V, 'brightness')}" if V.get("brightness") not in (1.0, 1, "brightness") else ""),
    "Palette source": lambda V, x: x.get("palette") or "the palette source",
    "Colour ramp": lambda V, x: f"{len(V.get('stops') or [])} stops, {V.get('mode')}",
    "Colour pick": lambda V, x: f"slot {_g(V, 'index')} of 8",
    "Colour":     lambda V, x: _fmt(V.get("rgb")),
    "Number":     lambda V, x: _fmt(V.get("value")),
    "Toggle":     lambda V, x: _fmt(V.get("on")),
    "Expression": lambda V, x: str(V.get("expr", "")),
    "Colour expression": lambda V, x: str(V.get("expr", "")),
    "Send":       lambda V, x: f"'{V.get('name', '')}'",
    "Receive":    lambda V, x: f"'{V.get('name', '')}'",
    "Send colour": lambda V, x: f"'{V.get('name', '')}'",
    "Receive colour": lambda V, x: f"'{V.get('name', '')}'",
    "Graph input": lambda V, x: f"{V.get('name', '')}, a {V.get('type', 'float')}",
    "Graph output": lambda V, x: f"{V.get('name', '')}, a {V.get('type', 'float')}",
    "Bitmap":     lambda V, x: "%d × %d" % _rows_size(V.get("rows", "")),
    "States":     lambda V, x: f"{len(str(V.get('states', '')).split('|'))} states of %d × %d" % _rows_size(str(V.get("states", "")).split("|")[0]),
    "Text":       lambda V, x: f"'{V.get('text', '')}'" + (f" × {V.get('size')}" if (V.get("size") or 1) != 1 else ""),
    "Image":      lambda V, x: (os.path.basename(str(V.get("file"))) if V.get("file") else "no file") + f", {V.get('width')} × {V.get('height')}",
    "Path":       lambda V, x: f"{len([p for p in str(V.get('points', '')).split(';') if p.strip()])} points" + (", closed" if V.get("closed") else ""),
    "Gradient":   lambda V, x: str(V.get("shape")),
    "Checker":    lambda V, x: f"{_g(V, 'scale')} squares across",
    "Stripes":    lambda V, x: f"{_g(V, 'count')} stripes, duty {_g(V, 'duty')}",
    "Ripple":     lambda V, x: f"{_g(V, 'rings')} rings about {_g(V, 'cx')}, {_g(V, 'cy')}",
    "Voronoi":    lambda V, x: f"scale {_g(V, 'scale')}, seed {_g(V, 'seed')}",
    "Brick":      lambda V, x: f"scale {_g(V, 'scale')}, mortar {_g(V, 'mortar')}",
    "Mandelbrot": lambda V, x: ("julia" if V.get("julia") else "mandelbrot") + f", {V.get('iterations')} iterations",
    "Torus knot": lambda V, x: f"({V.get('p')}, {V.get('q')}) knot, tube {_g(V, 'tube')}",
    "Blend":      lambda V, x: f"{V.get('mode')}, amount {_g(V, 'amount')}",
    "Layers":     lambda V, x: " / ".join(str(V.get(f"mode {k}")) for k in range(1, 5)),
    "Scale":      lambda V, x: f"× {_g(V, 'by')}",
    "Fade":       lambda V, x: f"keep {_g(V, 'keep')}",
    "Mask":       lambda V, x: f"× {_g(V, 'mask')}",
    "Levels":     lambda V, x: f"brightness {_g(V, 'brightness')}, contrast {_g(V, 'contrast')}, gamma {_g(V, 'gamma')}",
    "Adjust":     lambda V, x: f"hue {_g(V, 'hue')}, sat {_g(V, 'saturation')}, value {_g(V, 'value')}",
    "HSV":        lambda V, x: f"h {_g(V, 'h')} s {_g(V, 's')} v {_g(V, 'v')}",
    "Blur":       lambda V, x: f"radius {V.get('radius')}",
    "Glow":       lambda V, x: f"radius {V.get('radius')}, amount {_g(V, 'amount')}",
    "Transform":  lambda V, x: f"move {_g(V, 'move_u')}, {_g(V, 'move_v')}; turn {_g(V, 'turns')}; zoom {_g(V, 'zoom')}",
    "Rotate":     lambda V, x: f"{_g(V, 'turns')} turns",
    "Time":       lambda V, x: "t in seconds, dt in ms",
    "Frame count": lambda V, x: "frames since the start",
    "Audio":      lambda V, x: "the microphone's volume, bands, beat",
    "FFT bin":    lambda V, x: f"bin {V.get('bin')}" if "bin" in V else "one band",
    "Spectrum":   lambda V, x: "the 16 bands",
    "Loudest bin": lambda V, x: f"bins {V.get('from')}..{V.get('to')}",
    "Gravity":    lambda V, x: f"tilt {_g(V, 'tilt_x')}, {_g(V, 'tilt_y')}",
    "Emitters":   lambda V, x: f"life {_g(V, 'life')} s" + (", random" if V.get("random") else ""),
    "Particles":  lambda V, x: f"{_g(V, 'rate')} /s, life {_g(V, 'life')} s, {V.get('max')} at most",
    "Sprites":    lambda V, x: f"size {_g(V, 'size')}, {V.get('falloff')}",
    "Shells":     lambda V, x: f"speed {_g(V, 'speed')}, width {_g(V, 'width')}",
    "Reaction diffusion": lambda V, x: f"feed {_fmt(V['feed'])}, kill {_fmt(V['kill'])}",
    "Bifurcation": lambda V, x: f"c {_g(V, 'c_lo')}..{_g(V, 'c_hi')}, {V.get('orbits')} orbits",
    "Statistics": lambda V, x: f"field {V.get('field')}",
    "Sparkle":    lambda V, x: f"density {_g(V, 'density')}",
    "Hash":       lambda V, x: f"seed {_g(V, 'seed')}",
    "Mirror fold": lambda V, x: str(V.get("symmetry")),
    "Speed":      lambda V, x: "the Speed slider, 0..1",
    "Intensity":  lambda V, x: "the Intensity slider, 0..1",
    "Custom 1":   lambda V, x: "the Custom 1 slider, 0..1",
    "Custom 2":   lambda V, x: "the Custom 2 slider, 0..1",
    "Custom 3":   lambda V, x: "the Custom 3 slider, 0..1",
    "Check 1":    lambda V, x: "the Check 1 box",
    "Check 2":    lambda V, x: "the Check 2 box",
    "Check 3":    lambda V, x: "the Check 3 box",
    "Colour 1":   lambda V, x: "the segment's first colour",
    "Colour 2":   lambda V, x: "the segment's second colour",
    "Colour 3":   lambda V, x: "the segment's third colour",
    "Divide":     lambda V, x: f"{_g(V, 'a')} ÷ {_g(V, 'b')}",
    "Fract":      lambda V, x: f"fract({_g(V, 'x')})",
    "Power":      lambda V, x: f"{_g(V, 'x')} ^ {_g(V, 'e')}",
    "Modulo":     lambda V, x: f"{_g(V, 'x')} mod {_g(V, 'm')}",
    "Log":        lambda V, x: f"log({_g(V, 'x')})",
    "Exp":        lambda V, x: f"exp({_g(V, 'x')})",
    "Min":        lambda V, x: f"min({_g(V, 'a')}, {_g(V, 'b')})",
    "Max":        lambda V, x: f"max({_g(V, 'a')}, {_g(V, 'b')})",
    "Not":        lambda V, x: f"not {_g(V, 'on')}",
    "Sine":       lambda V, x: f"sin(2pi × {_g(V, 'x')}), -1..1",
    "Cosine":     lambda V, x: f"cos(2pi × {_g(V, 'x')}), 0..1",
    "Band":       lambda V, x: f"a band about whole {_g(V, 'x')}, sharpness {_g(V, 'sharp')}",
    "Float curve": lambda V, x: f"a curve of {len(V.get('points') or [])} points",
    "Vector rotate": lambda V, x: f"{_g(V, 'turns')} turns about {_g(V, 'axis')}",
    "Vector split": lambda V, x: "x, y, z of v",
    "Vector":     lambda V, x: f"({_g(V, 'x')}, {_g(V, 'y')}, {_g(V, 'z')})",
    "Dot 3":      lambda V, x: f"{_g(V, 'a')} . {_g(V, 'b')}",
    "Direction to": lambda V, x: f"turns {_g(V, 'turns_a')}, {_g(V, 'turns_b')}",
    "Flip":       lambda V, x: ", ".join(k for k, on in (("flip u", V.get("flip_u")), ("flip v", V.get("flip_v")), ("swap", V.get("swap"))) if on) or "as it is",
    "Shape part": lambda V, x: f"part {_g(V, 'pick')}",
    "Blackbody":  lambda V, x: f"{_g(V, 'kelvin')} K",
    "Previous":   lambda V, x: "this pixel, last frame",
    "Previous at": lambda V, x: f"last frame at {_g(V, 'u')}, {_g(V, 'v')}",
    "Combine":    lambda V, x: f"rgb({_g(V, 'r')}, {_g(V, 'g')}, {_g(V, 'b')})",
    "Split":      lambda V, x: "r, g, b of the colour",
    "Field":      lambda V, x: f"field {V.get('field')} at u, v",
    "Field write": lambda V, x: f"into field {V.get('field')}",
    "Drain":      lambda V, x: f"heights {V.get('height_field')}, water {V.get('water_field')}",
    "Coords":     lambda V, x: "u, v of this pixel",
    "Direction":  lambda V, x: "the pixel's outward direction",
    "Position":   lambda V, x: "the pixel's x, y, z",
    "Cube face":  lambda V, x: "which face, and where on it",
    "Cube ring":  lambda V, x: "around the cube, and how deep",
    "Pixel":      lambda V, x: "the pixel's index and count",
    "Output":     lambda V, x: "the LEDs",
    "Effect settings": lambda V, x: x.get("palette") or "",
    "Note":       lambda V, x: str(V.get("text", ""))[:40],
    "Frame":      lambda V, x: str(V.get("title", "")),
    "Knot":       lambda V, x: "",
    "Knot colour": lambda V, x: "",
    "Scope":      lambda V, x: f"{_fmt(V.get('seconds'))} s",
}


def fit_words(text, n):
    """`text` in at most n characters, cut at a word with "..." when it
    does not fit - a stand-in's line is narrow, and a word cut in half
    reads as another word ("the Speed slider, 0.")."""
    text = str(text)
    if len(text) <= n:
        return text
    if n <= 3:
        return text[:n]
    cut = text[:n - 3]
    if not (text[n - 3] == " " or cut.endswith(" ")):       # the cut splits a word: back to the last whole one
        sp = cut.rfind(" ")
        if sp > n // 3:
            cut = cut[:sp]
    return cut.rstrip().rstrip(",;:").rstrip() + "..."


def summary(n, d, wired=(), extra=None):
    """One line on what the node computes now, from its typed values."""
    V = values(n, d, wired)
    f = SUMMARY.get(n["type"])
    try:
        text = f(V, extra or {}) if f else _generic(n, d, V)
    except Exception:
        text = _generic(n, d, V)
    text = re.sub(r"\s+", " ", str(text)).strip()
    return text if len(text) <= 60 else text[:57] + "..."


# --- the transfer of a one-in one-out maths node ------------------------------------
def _num(V, name, default=0.0):
    v = V.get(name)
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _smooth(t):
    t = min(1.0, max(0.0, t))
    return t * t * (3.0 - 2.0 * t)


def _map_range(x, V):
    lo, hi, olo, ohi = _num(V, "in_lo"), _num(V, "in_hi", 1.0), _num(V, "out_lo"), _num(V, "out_hi", 1.0)
    t = (x - lo) / (hi - lo) if hi != lo else 0.0
    if V.get("clamp"):
        t = min(1.0, max(0.0, t))
    e = V.get("ease")
    if e == "smooth":
        t = _smooth(t)
    elif e == "ease in":
        t = t * t
    elif e == "ease out":
        t = 1.0 - (1.0 - t) ** 2
    elif e == "ease in-out":
        t = 2 * t * t if t < 0.5 else 1.0 - (-2 * t + 2) ** 2 / 2
    steps = _num(V, "steps")
    if steps > 1:
        t = math.floor(t * steps) / (steps - 1) if steps > 1 else t
    return olo + t * (ohi - olo)


def _curve(x, V):
    pts = sorted((float(p[0]), float(p[1])) for p in (V.get("points") or [[0, 0], [1, 1]]))
    if not pts:
        return x
    if x <= pts[0][0]:
        return pts[0][1]
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        if x <= x1:
            return y0 if x1 == x0 else y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    return pts[-1][1]


# type: (f(x, V), x range as (lo, hi) or a function of V giving it)
TRANSFER = {
    "Remap":      (lambda x, V: _num(V, "out_lo") + (x - _num(V, "in_lo")) * ((_num(V, "out_hi", 1) - _num(V, "out_lo")) / ((_num(V, "in_hi", 1) - _num(V, "in_lo")) or 1.0)),
                   lambda V: (_num(V, "in_lo"), _num(V, "in_hi", 1.0))),
    "Map range":  (_map_range, lambda V: (_num(V, "in_lo"), _num(V, "in_hi", 1.0))),
    "Smoothstep": (lambda x, V: _smooth((x - _num(V, "e0")) / ((_num(V, "e1", 1) - _num(V, "e0")) or 1.0)),
                   lambda V: (min(_num(V, "e0"), _num(V, "e1", 1)) - 0.25, max(_num(V, "e0"), _num(V, "e1", 1)) + 0.25)),
    "Clamp":      (lambda x, V: min(_num(V, "hi", 1), max(_num(V, "lo"), x)),
                   lambda V: (_num(V, "lo") - 0.25, _num(V, "hi", 1) + 0.25)),
    "Threshold":  (lambda x, V: 1.0 if x >= _num(V, "at", 0.5) else 0.0, (0.0, 1.0)),
    "Fract":      (lambda x, V: x - math.floor(x), (0.0, 2.0)),
    "Abs":        (lambda x, V: abs(x), (-1.0, 1.0)),
    "Floor":      (lambda x, V: math.floor(x), (0.0, 3.0)),
    "Power":      (lambda x, V: max(0.0, x) ** _num(V, "e", 2.0) if _num(V, "e", 2.0) >= 0 else 0.0, (0.0, 1.0)),
    "Modulo":     (lambda x, V: (x - math.floor(x / _num(V, "m", 1)) * _num(V, "m", 1)) if _num(V, "m", 1) != 0 else 0.0,
                   lambda V: (0.0, 2.0 * abs(_num(V, "m", 1.0)) or 2.0)),
    "Sine":       (lambda x, V: math.sin(x * 2 * math.pi), (0.0, 1.0)),
    "Cosine":     (lambda x, V: 0.5 + 0.5 * math.cos(x * 2 * math.pi), (0.0, 1.0)),
    "Log":        (lambda x, V: math.log(max(1e-6, x)), (0.01, 4.0)),
    "Exp":        (lambda x, V: math.exp(min(60.0, x)), (-2.0, 2.0)),
    "Band":       (lambda x, V: (0.5 + 0.5 * math.cos(x * 2 * math.pi)) ** max(0.01, _num(V, "sharp", 1.0)), (0.0, 1.0)),
    "Float curve": (_curve, (0.0, 1.0)),
    "Ease":       (None, None),      # a signal, not a transfer: the sparkline shows it
}


def transfer(n, d, wired=(), points=48):
    """[(x, y)] over the node's input range, or None when the node has no
    transfer (its x is a wire, the shape holds all the same)."""
    t = TRANSFER.get(n["type"])
    if not t or t[0] is None:
        return None
    f, rng = t
    V = values(n, d, wired)
    lo, hi = rng(V) if callable(rng) else rng
    if not (hi > lo):
        lo, hi = lo - 0.5, lo + 0.5
    out = []
    for k in range(points):
        x = lo + (hi - lo) * k / (points - 1)
        try:
            y = float(f(x, V))
        except (ValueError, ZeroDivisionError, OverflowError):
            y = 0.0
        if not math.isfinite(y):
            y = 0.0
        out.append((x, y))
    return out


# --- the range of an output, for a meter under its number ----------------------------
_UNIT = (0.0, 1.0)
OUT_RANGES = {
    ("Audio", "volume"): _UNIT, ("Audio", "bass"): _UNIT, ("Audio", "mid"): _UNIT, ("Audio", "treble"): _UNIT,
    ("Audio", "hit"): _UNIT, ("Audio", "peak"): _UNIT,
    ("FFT bin", "level"): _UNIT, ("Loudest bin", "level"): _UNIT, ("Spectrum", "value"): _UNIT,
    ("Wave", "value"): _UNIT, ("Ease", "value"): _UNIT, ("Envelope", "value"): _UNIT, ("Random hold", "value"): _UNIT,
    ("Tempo", "phase"): _UNIT, ("Tempo", "bar"): _UNIT, ("Sequencer", "phase"): _UNIT, ("Sequencer", "progress"): _UNIT,
    ("Beat kick", "phase"): _UNIT, ("Smoothstep", "result"): _UNIT, ("Cosine", "result"): _UNIT, ("Band", "result"): _UNIT,
    ("Fract", "result"): _UNIT, ("Threshold", "value"): _UNIT, ("Sine", "result"): (-1.0, 1.0),
    ("Speed", "value"): _UNIT, ("Intensity", "value"): _UNIT, ("Custom 1", "value"): _UNIT, ("Custom 2", "value"): _UNIT,
    ("Custom 3", "value"): _UNIT, ("Noise", "value"): _UNIT, ("Gradient", "value"): _UNIT, ("Checker", "value"): _UNIT,
    ("Stripes", "value"): _UNIT, ("Ripple", "value"): _UNIT, ("Hash", "value"): _UNIT, ("Sparkle", "value"): _UNIT,
    ("Voronoi", "distance"): _UNIT, ("Voronoi", "edge"): _UNIT, ("Mandelbrot", "value"): _UNIT,
}


def out_range(n, d, name):
    """(lo, hi) when the output's range is known: the table, a Steps
    node's sliders' span, an Integrate's wrap, a Remap's out range."""
    t = n["type"]
    if (t, name) in OUT_RANGES:
        return OUT_RANGES[(t, name)]
    P = n.get("params", {})
    if t == "Steps" and name == "value":
        vs = [float(P.get(f"s{k}", 0.0)) for k in range(1, int(P.get("length", 8) or 8) + 1)]
        return (min(vs), max(vs)) if vs and max(vs) > min(vs) else (0.0, 1.0)
    if t == "Steps" and name == "step":
        return (0.0, float(int(P.get("length", 8) or 8) - 1))
    if t == "Integrate" and float(P.get("wrap", 1.0) or 0) > 0:
        return (0.0, float(P["wrap"]))
    if t == "Remap" and name == "result":
        lo, hi = float(P.get("out_lo", 0.0)), float(P.get("out_hi", 1.0))
        return (min(lo, hi), max(lo, hi)) if hi != lo else None
    if t == "Clamp" and name == "result":
        return (float(P.get("lo", 0.0)), float(P.get("hi", 1.0)))
    return None


# --- pattern thumbnails ----------------------------------------------------------------
def _grid(N):
    """Pixel centres over a square of N, or a (W, H) patch: x, y in 0..1
    (the patch keeps square pixels: y spans H / W of the way)."""
    W, H = (N, N) if isinstance(N, int) else (int(N[0]), int(N[1]))
    y, x = np.mgrid[0:H, 0:W]
    return (x + 0.5) / W, (y + 0.5) / W                    # as the effect samples them


def _hash3(ix, iy, iz):
    """A value in 0..1 for an integer lattice point, the same every time."""
    h = np.sin(ix * 12.9898 + iy * 78.233 + iz * 37.719) * 43758.5453
    return h - np.floor(h)


def noise_patch(N, scale=4.0, octaves=1, roughness=0.5, z=0.0):
    """Smooth value noise over the patch at the typed scale, `z` sliding
    through the third dimension: the Noise node's thumbnail, and how it
    scrolls with its live z."""
    x, y = _grid(N)
    out = np.zeros_like(x)
    amp, total, sc = 1.0, 0.0, float(scale)
    for _ in range(max(1, min(4, int(octaves)))):
        px, py, pz = x * sc, y * sc, np.full_like(x, float(z) * sc)
        x0, y0, z0 = np.floor(px), np.floor(py), np.floor(pz)
        fx, fy, fz = px - x0, py - y0, pz - z0
        fx, fy, fz = fx * fx * (3 - 2 * fx), fy * fy * (3 - 2 * fy), fz * fz * (3 - 2 * fz)
        v = 0.0
        for dz in (0, 1):
            vz = 0.0
            for dy in (0, 1):
                a = _hash3(x0, y0 + dy, z0 + dz) * (1 - fx) + _hash3(x0 + 1, y0 + dy, z0 + dz) * fx
                vz = vz + a * (fy if dy else (1 - fy))
            v = v + vz * (fz if dz else (1 - fz))
        out += v * amp
        total += amp
        amp *= float(roughness); sc *= 2.0
    return np.clip(out / max(1e-6, total), 0.0, 1.0)


def _voronoi(N, scale, seed):
    x, y = _grid(N)
    rng = np.random.RandomState(int(seed * 1000) & 0xFFFF)
    k = max(1, int(round(scale)))
    pts = (np.mgrid[0:k, 0:k].reshape(2, -1).T + rng.rand(k * k, 2)) / k
    d = np.full(x.shape, 9.0)
    for px, py in pts:
        for ox in (-1, 0, 1):
            for oy in (-1, 0, 1):
                d = np.minimum(d, np.hypot(x - (px + ox), y - (py + oy)))
    return np.clip(d * k, 0.0, 1.0)


def _mandel(N, V):
    x, y = _grid(N)
    it = int(V.get("iterations") or 40)
    if V.get("julia"):
        z = (x * 3.0 - 1.5) + 1j * (y * 3.0 - 1.5)
        c = complex(_num(V, "jx"), _num(V, "jy"))
    else:
        c = (x * 3.0 - 2.2) + 1j * (y * 2.6 - 1.3)
        z = np.zeros_like(c)
    out = np.zeros(x.shape)
    alive = np.ones(x.shape, bool)
    for k in range(min(it, 60)):
        z = np.where(alive, z * z + c, z)
        esc = alive & (np.abs(z) > 2.0)
        out[esc] = k / float(min(it, 60))
        alive &= ~esc
    return out


PATTERNS = {
    "Checker": lambda N, V: (((np.floor(_grid(N)[0] * _num(V, "scale", 4)) + np.floor(_grid(N)[1] * _num(V, "scale", 4))) % 2)),
    "Stripes": lambda N, V: ((_grid(N)[0] * _num(V, "count", 6) + _num(V, "phase")) % 1.0 < _num(V, "duty", 0.5)).astype(float),
    "Ripple":  lambda N, V: 0.5 + 0.5 * np.cos(2 * np.pi * (np.hypot(_grid(N)[0] - 0.5 - _num(V, "cx"), _grid(N)[1] - 0.5 - _num(V, "cy")) * _num(V, "rings", 4) - _num(V, "phase"))),
    "Voronoi": lambda N, V: _voronoi(N, _num(V, "scale", 3), _num(V, "seed")),
    "Brick":   lambda N, V: _brick(N, V),
    "Mandelbrot": _mandel,
    "Gradient": lambda N, V: _gradient(N, V),
}


def _brick(N, V):
    x, y = _grid(N)
    s, m = _num(V, "scale", 4), _num(V, "mortar", 0.1)
    yy = y * s
    row = np.floor(yy)
    off = np.where(np.mod(row, 2) == 1, 0.5, 0.0)
    xx = x * s * 2 + off
    fx, fy = xx - np.floor(xx), yy - np.floor(yy)
    return ((fx > m) & (fy > m)).astype(float)


def _gradient(N, V):
    x, y = _grid(N)
    g = V.get("shape", "linear")
    if g == "quadratic":
        return x * x
    if g == "radial":
        return np.clip(np.hypot(x - 0.5, y - 0.5) * 2.0, 0, 1)
    if g == "spherical":
        return np.clip(1.0 - np.hypot(x - 0.5, y - 0.5) * 2.0, 0, 1)
    if g == "diagonal":
        return (x + y) * 0.5
    return x


def pattern(n, d, wired=(), N=32, live=None):
    """An N x N (or (W, H)) array of 0..1 for a pattern node at its typed
    values - a wired pin takes its live value when given, else the
    default - or None. Noise is a pattern too, sliding with its z."""
    f = PATTERNS.get(n["type"])
    if n["type"] == "Noise":
        f = lambda N, V: noise_patch(N, _num(V, "scale", 4.0), V.get("octaves") or 1, _num(V, "roughness", 0.5), _num(V, "z"))
    if not f:
        return None
    V = values(n, d, wired)
    for k, v in (live or {}).items():
        V[k] = v
    for i in d["inputs"]:                                   # a wired pin: the default stands in
        if isinstance(V.get(i["name"]), str) and V[i["name"]] == i["name"]:
            V[i["name"]] = i.get("default", 0.0)
    try:
        a = np.asarray(f(N, V), dtype=float)
    except Exception:
        return None
    return np.clip(np.nan_to_num(a), 0.0, 1.0)


# --- colour strips ---------------------------------------------------------------------
def blackbody(kelvin):
    """An (r, g, b) for a colour temperature, Tanner Helland's fit, 1000..40000 K."""
    t = max(1000.0, min(40000.0, float(kelvin))) / 100.0
    if t <= 66:
        r = 255.0
        g = 99.4708025861 * math.log(t) - 161.1195681661 if t > 0 else 0.0
        b = 0.0 if t <= 19 else 138.5177312231 * math.log(t - 10) - 305.0447927307
    else:
        r = 329.698727446 * ((t - 60) ** -0.1332047592)
        g = 288.1221695283 * ((t - 60) ** -0.0755148492)
        b = 255.0
    return tuple(int(max(0.0, min(255.0, c))) for c in (r, g, b))


def ramp_colour(stops, t, mode="linear"):
    """The colour at t of a ramp's stops [[t, r, g, b], ...]."""
    st = sorted((float(s[0]), (int(s[1]), int(s[2]), int(s[3]))) for s in (stops or []))
    if not st:
        return (0, 0, 0)
    if t <= st[0][0]:
        return st[0][1]
    for (t0, c0), (t1, c1) in zip(st, st[1:]):
        if t <= t1:
            if mode == "constant" or t1 == t0:
                return c0
            f = (t - t0) / (t1 - t0)
            if mode == "ease":
                f = _smooth(f)
            return tuple(int(round(a + (b - a) * f)) for a, b in zip(c0, c1))
    return st[-1][1]


def ramp_strip(n, d, k=24):
    """k colours across the node's strip, or None: a Colour ramp's stops,
    a Blackbody from 1000 to 12000 K, a Colour pick's eight."""
    t = n["type"]
    P = n.get("params", {})
    if t == "Colour ramp":
        return [ramp_colour(P.get("stops"), i / (k - 1), P.get("mode", "linear")) for i in range(k)]
    if t == "Blackbody":
        return [blackbody(1000.0 + 11000.0 * i / (k - 1)) for i in range(k)]
    if t == "Colour pick":
        return [tuple(int(c) for c in (P.get(f"c{i}") or [0, 0, 0])[:3]) for i in range(8)]
    return None


def strip_marker(n, d, wired, live=None):
    """Where on the strip the typed (or live) input lands, 0..1, or None."""
    t = n["type"]
    if t == "Blackbody":
        v = live if live is not None else (None if "kelvin" in wired else n.get("inputs", {}).get("kelvin", 3000.0))
        return None if v is None else max(0.0, min(1.0, (float(v) - 1000.0) / 11000.0))
    if t == "Colour ramp":
        v = live if live is not None else (None if "t" in wired else n.get("inputs", {}).get("t", 0.0))
        return None if v is None else max(0.0, min(1.0, float(v)))
    if t == "Colour pick":
        v = live if live is not None else (None if "index" in wired else n.get("inputs", {}).get("index", 0.0))
        return None if v is None else max(0.0, min(1.0, (float(v) + 0.5) / 8.0))
    if t == "Palette":
        v = live if live is not None else (None if "index" in wired else n.get("inputs", {}).get("index", 0.0))
        return None if v is None else max(0.0, min(1.0, float(v) % 1.0 if float(v) >= 1.0 else float(v)))
    return None


# --- what draws a sparkline, what moves ---------------------------------------------------
SPARK = {"Integrate": "value", "Ease": "value", "Envelope": "value", "Spring": "value", "Delay": "value",
         "Random hold": "value", "Beat kick": "phase", "Tempo": "phase"}
SPARK_SECONDS = 3.0
