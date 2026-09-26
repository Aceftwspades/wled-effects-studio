"""Each kind of part's natural sizes, as fields in real units - what the
Shape frame shows for a part and what the add gallery asks before a part
goes in (the ninth pass's S8 and S9).

A part's settings are in the shape's units (LED pitches, shapes.py); a
field shows them the way the thing is measured on the bench: counts, a
length in the shape's unit, a strip's density as LEDs a metre, degrees.
A few settings mean "work it out" at 0 (a ring's radius from its LEDs, an
arch's span): their field shows what it works out to, and typing a value
sets it.

    shape_fields.FIELDS[kind]             # [Field(key, label, type, tip, ask)]
    shape_fields.value(part, f, sp)       # the number (or text, or flag) the field shows
    shape_fields.put(part, f, v, sp)      # a copy of the part with the field set to v
    shape_fields.text(part, f, sp)        # the value in words, with its unit
"""
import copy
import math

import numpy as np

from native import shapes, units


class Field:
    """key: the part's setting (or a derived one, "_..."); type: count,
    length, density, angle, number, bool, choice, text, box (read only),
    turns (read only); ask: the gallery asks it before adding."""

    def __init__(self, key, label, type, tip="", ask=False, lo=None, hi=None):
        self.key, self.label, self.type, self.tip, self.ask, self.lo, self.hi = key, label, type, tip, ask, lo, hi

    def __repr__(self):
        return f"Field({self.key!r}, {self.type})"


F = Field
_PITCH = F("pitch", "LEDs a metre", "density", "the strip's density: 60 a metre is 1.67 cm apart (the shape's own density "
           "unless this part's strip differs)")
_START = F("start_deg", "first LED at", "angle", "degrees round from +X to the first LED")

FIELDS = {
    "strip": [F("n", "LEDs", "count", "how many LEDs", ask=True, lo=1, hi=4096),
              F("_length", "length", "length", "the strip's length: its LEDs times their spacing (typing it sets the count)", ask=True),
              _PITCH],
    "ring": [F("n", "LEDs", "count", "how many LEDs round it", ask=True, lo=1, hi=4096),
             F("radius", "diameter", "diameter", "across the ring through its LEDs (from the LEDs and their spacing until typed)", ask=True),
             _PITCH, _START],
    "panel": [F("w", "across", "count", "LEDs across", ask=True, lo=1, hi=256), F("h", "down", "count", "LEDs down", ask=True, lo=1, hi=256),
              _PITCH, F("serpentine", "every other row back", "bool", "the rows snake: each runs back the way the last came"),
              F("vertical", "in columns", "bool", "the wiring runs up and down the columns instead of along the rows"),
              F("_box", "size", "box")],
    "cylinder": [F("w", "round", "count", "LEDs round", ask=True, lo=3, hi=256), F("h", "rows", "count", "rows up it", ask=True, lo=1, hi=256),
                 _PITCH, F("_box", "size", "box")],
    "sphere": [F("w", "round", "count", "LEDs round the widest row", ask=True, lo=3, hi=256),
               F("h", "rows", "count", "rows from pole to pole", ask=True, lo=2, hi=128), _PITCH, F("_box", "size", "box")],
    "cube": [F("B", "LEDs a face's edge", "count", "a face is B x B LEDs", ask=True, lo=2, hi=85), _PITCH,
             F("six", "the bottom face too", "bool", "six faces, not five"), F("_box", "size", "box")],
    "polygon": [F("sides", "sides", "count", "how many straight sides", ask=True, lo=3, hi=64),
                F("per_side", "LEDs a side", "count", ask=True, lo=1, hi=1024),
                F("radius", "across the corners", "diameter", "from corner to corner through the middle (from the LEDs until typed)"),
                _PITCH, _START],
    "polyhedron": [F("solid", "solid", "choice", "tetrahedron to icosahedron, and the soccer ball (a truncated icosahedron)", ask=True),
                   F("mode", "LEDs on", "choice", "edges: a strip along every edge; faces: every face outlined on its own", ask=True),
                   F("per_edge", "LEDs an edge", "count", ask=True, lo=1, hi=256),
                   F("radius", "radius", "length", "from the middle to a corner", ask=True), F("_box", "size", "box")],
    "polyline": [F("_count", "LEDs", "count", "how many along the path (it sets their spacing: LEDs at both ends)", lo=2, hi=4096),
                 _PITCH],
    "points": [],
    "tree": [F("strands", "strands", "count", "strands of LEDs round the tree", ask=True, lo=1, hi=128),
             F("per_strand", "LEDs a strand", "count", ask=True, lo=2, hi=1024),
             F("height", "height", "length", ask=True), F("base", "across the base", "length", ask=True),
             F("top", "across the top", "length", "0: the strands meet at a point"),
             F("turns", "turns round", "number", "0: straight down the cone; 1: each strand goes once round on the way"),
             F("degrees", "round the tree", "angle", "360 all round; 180 a half tree against a wall"),
             F("zigzag", "every other strand down", "bool", "a strand goes up, the next comes down - the wiring's way, not the look's")],
    "star": [F("points", "points", "count", ask=True, lo=3, hi=24), F("per_edge", "LEDs an edge", "count", ask=True, lo=1, hi=512),
             F("radius", "across the points", "diameter", "from point to point through the middle (from the LEDs until typed)", ask=True),
             F("inner", "inner corners at", "number", "how far in the inner corners are, as a share of the points' radius (0.38: a classic star)", lo=0.05, hi=0.95),
             _PITCH, F("start_deg", "a point at", "angle", "degrees round from +X to the first point (90: pointing up the Y axis)")],
    "helix": [F("n", "LEDs", "count", "the strip's LEDs", ask=True, lo=2, hi=4096),
              F("radius", "tube radius", "length", "the tube it is wound round", ask=True),
              F("height", "wound over", "length", "the height the strip is wound over: the turns follow from the strip's length", ask=True),
              _PITCH, F("_turns", "turns", "turns")],
    "spiral": [F("n", "LEDs", "count", ask=True, lo=2, hi=4096), F("gap", "between turns", "length", ask=True),
               F("inner", "starts at radius", "length"), _PITCH, F("_box", "size", "box")],
    "arch": [F("n", "LEDs", "count", ask=True, lo=2, hi=4096),
             F("span", "span", "length", "foot to foot (a half circle as long as the strip until typed)", ask=True),
             F("rise", "rise", "length", "from the feet to the top (half the span until typed)", ask=True), _PITCH],
    "rings": [F("counts", "LEDs a ring", "text", "each ring's LEDs from the middle out, with commas: 1,8,12,16,24,32 (a 241-LED "
                "board is 1,8,12,16,24,32,40,48,60)", ask=True),
              F("gap", "between rings", "length", "0: each ring sized by its LEDs and their spacing"), _PITCH,
              F("outward", "wired from the middle out", "bool", "the middle ring first (off: the outside first)"), _START],
    "frame": [F("w", "LEDs across", "count", "along the top (and the bottom)", ask=True, lo=1, hi=4096),
              F("h", "LEDs up a side", "count", ask=True, lo=1, hi=4096), _PITCH,
              F("bottom", "the bottom too", "bool", "off: three sides - a door, a screen's back"),
              F("start", "starts at", "choice", "the corner the wiring comes in at"),
              F("clockwise", "clockwise", "bool", "the way round from there, seen from the front"), F("_box", "size", "box")],
    "spokes": [F("spokes", "spokes", "count", ask=True, lo=1, hi=128), F("per_spoke", "LEDs a spoke", "count", ask=True, lo=1, hi=1024),
               F("inner", "from the middle", "length", "where the spokes start"), _PITCH,
               F("zigzag", "back along every other", "bool", "out along one spoke, back in along the next"), _START],
    "formula": [F("n", "LEDs", "count", ask=True, lo=1, hi=4096),
                F("x", "x =", "text", "t runs 0 to 1 along the LEDs, i is the LED (from 0), n the count; sin, cos, pi, tau, sqrt... (in LED spacings)", ask=True),
                F("y", "y =", "text", ask=True), F("z", "z =", "text", ask=True)],
    "reference": [],
}


def _eff(part):
    """The part's LEDs in its own frame (the settings' "work it out" values come from them)."""
    return shapes.part_points(part)[0]


def value(part, f, sp):
    """What field f shows for the part: a number in the chosen unit for
    lengths, LEDs a metre for a density, the setting itself otherwise. `sp`:
    the shape's params (its density and unit)."""
    p = part.get("params", {})
    k = f.key
    if f.type == "density":
        return units.density(sp) / (float(p.get("pitch", 1.0)) or 1.0)
    if k == "_length":
        return units.to_unit(int(p.get("n", 30)) * (float(p.get("pitch", 1.0)) or 1.0), sp)
    if k == "_count":
        return shapes.local_count(part)
    if f.type == "diameter":
        r = float(p.get("radius", 0.0))
        if r <= 0:
            pitch = float(p.get("pitch", 1.0)) or 1.0
            kind = part.get("kind")
            if kind == "polygon":                                 # to the corners, which have no LED
                sides = max(3, int(p.get("sides", 5)))
                r = max(1, int(p.get("per_side", 6))) * pitch / (2 * math.sin(math.pi / sides))
            elif kind == "star":                                  # to the points, which have no LED
                n, inner = max(3, int(p.get("points", 5))), min(0.95, max(0.05, float(p.get("inner", 0.4))))
                r = max(1, int(p.get("per_edge", 6))) * pitch / math.sqrt(1 + inner * inner - 2 * inner * math.cos(math.pi / n))
            else:
                P = _eff(part)
                r = float(np.linalg.norm(P[:, :2], axis=1).max()) if len(P) else 0.0
        return units.to_unit(2 * r, sp)
    if f.type == "length":
        v = float(p.get(k, 0.0))
        if v <= 0 and part.get("kind") == "arch" and k in ("span", "rise"):
            P = _eff(part)
            v = float(np.ptp(P[:, 0])) if k == "span" else float(P[:, 2].max())
        return units.to_unit(v, sp)
    if f.type == "turns":
        n = int(p.get("n", 60)); L = (n - 1) * (float(p.get("pitch", 1.0)) or 1.0)
        H = min(abs(float(p.get("height", 12.0))), L); r = float(p.get("radius", 3.0)) or 3.0
        return math.sqrt(max(0.0, L * L - H * H)) / (2 * math.pi * r)
    if f.type == "box":
        return None
    default = shapes.KINDS.get(part.get("kind"), ({}, ""))[0].get(k)
    v = p.get(k, default)
    if f.type == "count":
        return int(v if v is not None else 1)
    if f.type in ("angle", "number"):
        return float(v if v is not None else 0.0)
    if f.type == "bool":
        return bool(v)
    return "" if v is None else str(v)


def put(part, f, v, sp):
    """A copy of the part with field f set to v (in the field's terms)."""
    q = copy.deepcopy(part)
    p = q.setdefault("params", {})
    k = f.key
    if f.type == "density":
        d = max(0.1, float(v))
        p["pitch"] = round(units.density(sp) / d, 6)
    elif k == "_length":
        pitch = float(p.get("pitch", 1.0)) or 1.0
        p["n"] = max(1, int(round(units.from_unit(float(v), sp) / pitch)))
    elif k == "_count":
        pts = np.asarray(p.get("points") or [[0, 0, 0]], np.float32).reshape(-1, 3)
        total = float(np.linalg.norm(np.diff(pts, axis=0), axis=1).sum()) if len(pts) > 1 else 0.0
        n = max(2, int(v))
        if total > 0:
            p["pitch"] = round(total / (n - 1) - 1e-6, 6)
    elif f.type == "diameter":
        p["radius"] = round(max(0.0, units.from_unit(float(v), sp)) / 2.0, 5)
    elif f.type == "length":
        p[k] = round(max(0.0, units.from_unit(float(v), sp)), 5)
    elif f.type == "count":
        p[k] = int(max(f.lo or 1, min(f.hi or 1 << 16, int(v))))
    elif f.type in ("angle", "number"):
        x = float(v)
        if f.lo is not None:
            x = max(f.lo, x)
        if f.hi is not None:
            x = min(f.hi, x)
        p[k] = round(x, 5)
    elif f.type == "bool":
        p[k] = bool(v)
    elif f.type in ("choice", "text"):
        p[k] = str(v)
    return q


def box(part, sp):
    """The part's size as it stands (its scale in), in words: "30 x 20 cm"."""
    P, _ = shapes.transform(dict(part, pos=[0, 0, 0], reverse=False), *shapes.part_points(part))
    if len(P) == 0:
        return "-"
    dims = [float(d) for d in np.ptp(P, axis=0)]
    shown = [d for d in dims if d > 1e-3] or [0.0]
    return " x ".join(units.number(d, sp) for d in shown) + f" {units.unit(sp)}"


def text(part, f, sp):
    """The field's value in words, with its unit - for a read-only row and the gallery's tiles."""
    v = value(part, f, sp)
    if f.type == "box":
        return box(part, sp)
    if f.type in ("length", "diameter") or f.key == "_length":
        return f"{units.number(units.from_unit(v, sp), sp)} {units.unit(sp)}"
    if f.type == "density":
        return f"{v:.4g} a metre"
    if f.type == "turns":
        return f"{v:.2f}"
    if f.type == "angle":
        return f"{v:g} degrees"
    return str(v)


def unit_of(f, sp):
    """The unit a field's number is in, for the number control's suffix."""
    if f.type in ("length", "diameter") or f.key == "_length":
        return units.unit(sp)
    if f.type == "density":
        return "/m"
    if f.type == "angle":
        return "°"
    return ""
