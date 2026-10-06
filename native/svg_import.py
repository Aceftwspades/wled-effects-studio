"""Drawings from an SVG file, as the strokes LEDs are laid along.

A neon sign, a logo, lettering or a silhouette is drawn in Inkscape,
Illustrator, Figma or a cutting plotter's program and saved as SVG; this
reads the geometry out of it - every path and basic shape, flattened to
polylines in millimetres - so the Shape frame can lay a strip along each
stroke at the LED's real spacing (native/outline.py).

    paths = read(path)           # [Stroke(points Nx2 in mm, closed, name)]; y down, as the drawing has it
    paths = parse(svg_text)      # the same from text

What is read, and how (SVG 1.1 / SVG 2 where they agree):

- **path** with every command - M L H V C S Q T A Z in both cases, implicit
  repeats (a moveto's extra pairs are lines), the reflected control points of
  S and T, and arcs converted from endpoint to centre form as the spec's
  implementation notes give it (F.6.5, with the out-of-range radii scaled up,
  F.6.6). The number grammar is the spec's: "1.5.5" is two numbers, "-1-2"
  two, exponents allowed, an arc's flags packed as "011" read one digit each.
- **line, polyline, polygon, rect** (rounded corners too), **circle, ellipse**.
- **g, svg, a, switch, symbol** (through **use**, its href resolved anywhere
  in the document, x and y applied) - and every **transform**: matrix,
  translate, scale, rotate about a point, skewX, skewY, composed down the tree.
- **Units**: the root's width and height in mm, cm, in, pt, pc, px, Q with
  its viewBox (and preserveAspectRatio's default, uniform and centred) give
  millimetres, so a sign drawn 600 mm wide comes in 600 mm wide. Without a
  size, a user unit is a CSS pixel (1/96 in).
- Left out: whatever is not drawn - display:none or visibility:hidden (an
  attribute or the style), defs, clipPath, mask, marker, pattern, metadata,
  title - and text and images, which have no geometry until a program turns
  them into paths (Inkscape: Path > Object to Path). `skipped` says what was
  left out, so the frame can tell you.

Curves are flattened by subdivision to `tol` millimetres off the true curve
(0.05 mm by default: far finer than any LED spacing), after the transform,
so a curve scaled up by a transform is as smooth as one drawn large.
"""
import math
import re
import xml.etree.ElementTree as ET

import numpy as np

MM = {"mm": 1.0, "cm": 10.0, "in": 25.4, "pt": 25.4 / 72.0, "pc": 25.4 / 6.0, "px": 25.4 / 96.0, "q": 0.25, "": 25.4 / 96.0}
_NUM = re.compile(r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?")
_SKIP = {"defs", "clipPath", "mask", "marker", "pattern", "metadata", "title", "desc", "style", "script", "symbol",
         "linearGradient", "radialGradient", "filter", "foreignObject"}


class Stroke:
    """One stroke of the drawing: its points (N x 2, mm, y down), whether it closes on itself, and
    the id or kind of the element it came from."""
    __slots__ = ("points", "closed", "name")

    def __init__(self, points, closed, name=""):
        self.points, self.closed, self.name = np.asarray(points, np.float64).reshape(-1, 2), bool(closed), name

    def length(self):
        p = self.points
        if len(p) < 2:
            return 0.0
        L = float(np.linalg.norm(np.diff(p, axis=0), axis=1).sum())
        return L + (float(np.linalg.norm(p[-1] - p[0])) if self.closed else 0.0)


# --- small parsers -------------------------------------------------------------------------
def length_mm(text, default=None):
    """'12.5mm' -> 12.5; '100' -> 100 px in mm; a percentage or an em: `default`."""
    if text is None:
        return default
    m = re.fullmatch(r"\s*([-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?)\s*([a-zA-Z%]*)\s*", str(text))
    if not m:
        return default
    unit = m.group(2).lower()
    if unit not in MM:
        return default                                    # %, em, ex: relative to what this reader has not got
    return float(m.group(1)) * MM[unit]


def _num(text, default=0.0):
    if text is None:
        return default
    m = _NUM.search(str(text))
    return float(m.group(0)) if m else default


def _style(el):
    """The element's presentation: its attributes, with its style="" over them."""
    out = {k: v for k, v in el.attrib.items()}
    for item in (el.get("style") or "").split(";"):
        if ":" in item:
            k, v = item.split(":", 1)
            out[k.strip()] = v.strip()
    return out


def _hidden(el):
    st = _style(el)
    return st.get("display", "").strip() == "none" or st.get("visibility", "").strip() in ("hidden", "collapse")


def _tag(el):
    t = el.tag
    return t.split("}", 1)[1] if isinstance(t, str) and "}" in t else t


def transform(text):
    """A transform attribute as a 3x3 matrix (applied to column vectors), its functions composed
    left to right as the spec says."""
    M = np.eye(3)
    if not text:
        return M
    for name, args in re.findall(r"(matrix|translate|scale|rotate|skewX|skewY)\s*\(([^)]*)\)", text):
        a = [float(x) for x in _NUM.findall(args)]
        T = np.eye(3)
        if name == "matrix" and len(a) == 6:
            T = np.array([[a[0], a[2], a[4]], [a[1], a[3], a[5]], [0, 0, 1]])
        elif name == "translate" and a:
            T[0, 2], T[1, 2] = a[0], (a[1] if len(a) > 1 else 0.0)
        elif name == "scale" and a:
            T[0, 0], T[1, 1] = a[0], (a[1] if len(a) > 1 else a[0])
        elif name == "rotate" and a:
            c, s = math.cos(math.radians(a[0])), math.sin(math.radians(a[0]))
            R = np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]])
            if len(a) >= 3:
                Tp, Tm = np.eye(3), np.eye(3)
                Tp[0, 2], Tp[1, 2], Tm[0, 2], Tm[1, 2] = a[1], a[2], -a[1], -a[2]
                R = Tp @ R @ Tm
            T = R
        elif name == "skewX" and a:
            T[0, 1] = math.tan(math.radians(a[0]))
        elif name == "skewY" and a:
            T[1, 0] = math.tan(math.radians(a[0]))
        M = M @ T
    return M


def _apply(M, pts):
    pts = np.asarray(pts, np.float64).reshape(-1, 2)
    return pts @ M[:2, :2].T + M[:2, 2]


def _scale_of(M):
    """How much the transform enlarges, on average - for the curve tolerance."""
    return math.sqrt(max(abs(np.linalg.det(M[:2, :2])), 1e-12))


# --- curves --------------------------------------------------------------------------------------
def _flat_cubic(p0, p1, p2, p3, tol, out, depth=0):
    """A cubic Bezier flattened to within tol: its control points' distance from the chord says
    how far the curve can stray from it."""
    d = p3 - p0
    n = math.hypot(d[0], d[1])
    if n < 1e-12:
        dev = max(np.linalg.norm(p1 - p0), np.linalg.norm(p2 - p0))
    else:
        dev = max(abs(d[0] * (p0[1] - p1[1]) - d[1] * (p0[0] - p1[0])),
                  abs(d[0] * (p0[1] - p2[1]) - d[1] * (p0[0] - p2[0]))) / n
    if dev <= tol or depth > 16:
        out.append(p3)
        return
    p01, p12, p23 = (p0 + p1) / 2, (p1 + p2) / 2, (p2 + p3) / 2
    p012, p123 = (p01 + p12) / 2, (p12 + p23) / 2
    m = (p012 + p123) / 2
    _flat_cubic(p0, p01, p012, m, tol, out, depth + 1)
    _flat_cubic(m, p123, p23, p3, tol, out, depth + 1)


def _arc_points(x1, y1, rx, ry, phi_deg, large, sweep, x2, y2, tol_user):
    """An elliptical arc from (x1,y1) to (x2,y2), as SVG's implementation notes convert it
    (F.6.5 endpoint -> centre, F.6.6 radii corrected), sampled finely enough for tol_user. The
    points after the start."""
    if (x1, y1) == (x2, y2):
        return []
    rx, ry = abs(rx), abs(ry)
    if rx < 1e-12 or ry < 1e-12:
        return [(x2, y2)]                                   # a zero radius: a straight line (F.6.2)
    phi = math.radians(phi_deg % 360.0)
    c, s = math.cos(phi), math.sin(phi)
    dx2, dy2 = (x1 - x2) / 2.0, (y1 - y2) / 2.0
    x1p, y1p = c * dx2 + s * dy2, -s * dx2 + c * dy2
    lam = (x1p * x1p) / (rx * rx) + (y1p * y1p) / (ry * ry)
    if lam > 1.0:                                           # radii too small to reach: scaled up just enough
        k = math.sqrt(lam)
        rx, ry = rx * k, ry * k
    num = rx * rx * ry * ry - rx * rx * y1p * y1p - ry * ry * x1p * x1p
    den = rx * rx * y1p * y1p + ry * ry * x1p * x1p
    co = math.sqrt(max(0.0, num / den)) if den > 0 else 0.0
    if large == sweep:
        co = -co
    cxp, cyp = co * rx * y1p / ry, -co * ry * x1p / rx
    cx, cy = c * cxp - s * cyp + (x1 + x2) / 2.0, s * cxp + c * cyp + (y1 + y2) / 2.0

    def ang(ux, uy, vx, vy):
        a = math.atan2(ux * vy - uy * vx, ux * vx + uy * vy)
        return a

    t1 = ang(1.0, 0.0, (x1p - cxp) / rx, (y1p - cyp) / ry)
    dt = ang((x1p - cxp) / rx, (y1p - cyp) / ry, (-x1p - cxp) / rx, (-y1p - cyp) / ry)
    if not sweep and dt > 0:
        dt -= 2 * math.pi
    elif sweep and dt < 0:
        dt += 2 * math.pi
    # enough segments that the chord's sag (r (1 - cos(h/2))) stays under the tolerance
    r = max(rx, ry)
    h = 2.0 * math.acos(max(-1.0, min(1.0, 1.0 - tol_user / r))) if r > tol_user else math.pi / 2
    n = max(2, int(math.ceil(abs(dt) / max(h, 1e-3))))
    out = []
    for i in range(1, n + 1):
        t = t1 + dt * i / n
        x, y = rx * math.cos(t), ry * math.sin(t)
        out.append((c * x - s * y + cx, s * x + c * y + cy))
    out[-1] = (x2, y2)                                      # exactly where the command said
    return out


# --- path data -----------------------------------------------------------------------------------
class _Reader:
    """The path data's tokens: a command letter, a number, or (for an arc's flags) one digit."""
    def __init__(self, d):
        self.d, self.i = d or "", 0

    def _ws(self):
        while self.i < len(self.d) and self.d[self.i] in " \t\r\n,":
            self.i += 1

    def command(self):
        self._ws()
        if self.i < len(self.d) and self.d[self.i].isalpha():
            self.i += 1
            return self.d[self.i - 1]
        return None

    def more(self):
        """A number comes next (an implicit repeat of the command)."""
        self._ws()
        return self.i < len(self.d) and (self.d[self.i].isdigit() or self.d[self.i] in "+-.")

    def number(self):
        self._ws()
        m = _NUM.match(self.d, self.i)
        if not m:
            raise ValueError(f"a number expected at {self.i}: {self.d[self.i:self.i + 12]!r}")
        self.i = m.end()
        return float(m.group(0))

    def flag(self):
        self._ws()
        if self.i < len(self.d) and self.d[self.i] in "01":
            self.i += 1
            return self.d[self.i - 1] == "1"
        raise ValueError(f"an arc flag (0 or 1) expected at {self.i}")


def path_strokes(d, M, tol, name=""):
    """A path's d as strokes (its subpaths), in the coordinates M takes them to, flattened to tol
    there."""
    r = _Reader(d)
    tol_user = tol / _scale_of(M)
    strokes = []
    cur = []                                                # the subpath so far, user units
    x = y = sx = sy = 0.0
    prev_ctrl, prev_cmd = None, None

    def finish(closed):
        nonlocal cur
        if len(cur) >= 2 or (closed and len(cur) >= 3):
            pts = _apply(M, cur)
            keep = np.concatenate([[True], np.linalg.norm(np.diff(pts, axis=0), axis=1) > 1e-9])
            pts = pts[keep]
            if closed and len(pts) > 2 and np.linalg.norm(pts[-1] - pts[0]) < 1e-9:
                pts = pts[:-1]                                # the closing point is the start again
            if len(pts) >= 2:
                strokes.append(Stroke(pts, closed and len(pts) >= 3, name))
        cur = []

    def cubic(p1, p2, p3):
        # flattened in user units to the tolerance the transform scales to tol (an affine map takes
        # a Bezier to the Bezier of the mapped controls, so the curve itself is not distorted)
        out = []
        P = np.asarray([(x, y), p1, p2, p3], np.float64)
        _flat_cubic(P[0], P[1], P[2], P[3], tol_user, out)
        cur.extend([tuple(q) for q in out])

    cmd = None
    while True:
        c = r.command()
        if c is None:
            if cmd is None or not r.more():
                break
            c = cmd                                         # a repeat: the command again with new numbers
            if c in "Mm":
                c = "L" if c == "M" else "l"                # a moveto's extra pairs are lines
        cmd = c
        rel = c.islower()
        C = c.upper()
        ox, oy = (x, y) if rel else (0.0, 0.0)
        if C == "M":
            finish(False)
            x, y = ox + r.number(), oy + r.number()
            sx, sy = x, y
            cur = [(x, y)]
            cmd = c
            prev_ctrl = None
        elif C == "L":
            x, y = ox + r.number(), oy + r.number()
            cur.append((x, y)); prev_ctrl = None
        elif C == "H":
            x = ox + r.number() if rel else r.number()
            cur.append((x, y)); prev_ctrl = None
        elif C == "V":
            y = oy + r.number() if rel else r.number()
            cur.append((x, y)); prev_ctrl = None
        elif C in "CS":
            if C == "C":
                x1, y1 = ox + r.number(), oy + r.number()
            else:                                           # S: the first control is the last one reflected
                x1, y1 = (2 * x - prev_ctrl[0], 2 * y - prev_ctrl[1]) if prev_cmd in "CS" and prev_ctrl else (x, y)
            x2, y2 = ox + r.number(), oy + r.number()
            ex, ey = ox + r.number(), oy + r.number()
            if not cur:
                cur = [(x, y)]
            cubic((x1, y1), (x2, y2), (ex, ey))
            prev_ctrl = (x2, y2)
            x, y = ex, ey
        elif C in "QT":
            if C == "Q":
                qx, qy = ox + r.number(), oy + r.number()
            else:
                qx, qy = (2 * x - prev_ctrl[0], 2 * y - prev_ctrl[1]) if prev_cmd in "QT" and prev_ctrl else (x, y)
            ex, ey = ox + r.number(), oy + r.number()
            if not cur:
                cur = [(x, y)]
            # a quadratic is the cubic with its controls two thirds of the way to the quadratic's
            cubic((x + 2.0 / 3.0 * (qx - x), y + 2.0 / 3.0 * (qy - y)),
                  (ex + 2.0 / 3.0 * (qx - ex), ey + 2.0 / 3.0 * (qy - ey)), (ex, ey))
            prev_ctrl = (qx, qy)
            x, y = ex, ey
        elif C == "A":
            rx, ry, rot = r.number(), r.number(), r.number()
            large, sweep = r.flag(), r.flag()
            ex, ey = ox + r.number(), oy + r.number()
            if not cur:
                cur = [(x, y)]
            cur.extend(_arc_points(x, y, rx, ry, rot, large, sweep, ex, ey, tol_user))
            x, y = ex, ey
            prev_ctrl = None
        elif C == "Z":
            finish(True)
            x, y = sx, sy
            cur = [(x, y)]                                  # drawing on without a moveto starts from here
            prev_ctrl = None
        else:
            raise ValueError(f"unknown path command {c!r}")
        prev_cmd = C
    finish(False)
    return strokes


# --- the basic shapes, as path data ---------------------------------------------------------------
def _shape_d(tag, a):
    g = lambda k, d=0.0: _num(a.get(k), d)                  # noqa: E731
    if tag == "line":
        return f"M{g('x1')},{g('y1')} L{g('x2')},{g('y2')}"
    if tag in ("polyline", "polygon"):
        nums = [float(v) for v in _NUM.findall(a.get("points", ""))]
        if len(nums) < 4:
            return ""
        pts = " ".join(f"{nums[i]},{nums[i + 1]}" for i in range(0, len(nums) - 1, 2))
        return "M" + pts + (" Z" if tag == "polygon" else "")
    if tag == "rect":
        x, y, w, h = g("x"), g("y"), g("width"), g("height")
        if w <= 0 or h <= 0:
            return ""
        rx, ry = a.get("rx"), a.get("ry")
        rx = _num(rx) if rx is not None else (_num(ry) if ry is not None else 0.0)
        ry = _num(ry) if ry is not None else rx
        rx, ry = min(rx, w / 2), min(ry, h / 2)
        if rx <= 0 or ry <= 0:
            return f"M{x},{y} H{x + w} V{y + h} H{x} Z"
        return (f"M{x + rx},{y} H{x + w - rx} A{rx},{ry} 0 0 1 {x + w},{y + ry} V{y + h - ry} "
                f"A{rx},{ry} 0 0 1 {x + w - rx},{y + h} H{x + rx} A{rx},{ry} 0 0 1 {x},{y + h - ry} "
                f"V{y + ry} A{rx},{ry} 0 0 1 {x + rx},{y} Z")
    if tag in ("circle", "ellipse"):
        cx, cy = g("cx"), g("cy")
        rx = g("r") if tag == "circle" else g("rx")
        ry = g("r") if tag == "circle" else g("ry")
        if rx <= 0 or ry <= 0:
            return ""
        # from the rightmost point, clockwise on screen (y down), as a browser draws it
        return (f"M{cx + rx},{cy} A{rx},{ry} 0 0 1 {cx},{cy + ry} A{rx},{ry} 0 0 1 {cx - rx},{cy} "
                f"A{rx},{ry} 0 0 1 {cx},{cy - ry} A{rx},{ry} 0 0 1 {cx + rx},{cy} Z")
    return ""


# --- the document ------------------------------------------------------------------------------------
def _root_matrix(root):
    """User units of the root svg to millimetres: its width and height over its viewBox, uniform and
    centred (preserveAspectRatio's default, xMidYMid meet); no size: a user unit is a CSS pixel."""
    vb = [float(v) for v in _NUM.findall(root.get("viewBox", ""))]
    w_mm, h_mm = length_mm(root.get("width")), length_mm(root.get("height"))
    M = np.eye(3)
    if len(vb) == 4 and vb[2] > 0 and vb[3] > 0:
        if w_mm is None and h_mm is None:
            w_mm, h_mm = vb[2] * MM["px"], vb[3] * MM["px"]
        elif w_mm is None:
            w_mm = h_mm * vb[2] / vb[3]
        elif h_mm is None:
            h_mm = w_mm * vb[3] / vb[2]
        sx, sy = w_mm / vb[2], h_mm / vb[3]
        par = (root.get("preserveAspectRatio") or "").strip()
        if par.startswith("none"):
            k = None
        else:
            k = min(sx, sy) if "slice" not in par else max(sx, sy)
        if k is None:
            M = np.array([[sx, 0, -vb[0] * sx], [0, sy, -vb[1] * sy], [0, 0, 1]])
        else:
            tx = -vb[0] * k + (w_mm - vb[2] * k) / 2.0
            ty = -vb[1] * k + (h_mm - vb[3] * k) / 2.0
            M = np.array([[k, 0, tx], [0, k, ty], [0, 0, 1]])
    else:                                                   # no viewBox: user units are CSS pixels, whatever the size says
        M = np.array([[MM["px"], 0, 0], [0, MM["px"], 0], [0, 0, 1]])
    return M


def parse(text, tol=0.05):
    """The drawing's strokes (see the module's notes) and what was left out: (strokes, skipped) where
    skipped counts the elements by kind ("text": 2)."""
    try:
        root = ET.fromstring(text)
    except ET.ParseError as e:
        raise ValueError(f"not readable as SVG: {e}")
    if _tag(root) != "svg":
        raise ValueError("not an SVG drawing (its root is not <svg>)")
    ids = {}
    for el in root.iter():
        if el.get("id"):
            ids[el.get("id")] = el
    strokes, skipped = [], {}

    def walk(el, M, depth=0):
        if depth > 40:
            return
        tag = _tag(el)
        if not isinstance(tag, str) or _hidden(el):
            return
        if tag in _SKIP and depth > 0:
            return
        M = M @ transform(el.get("transform"))
        if tag == "svg" and depth > 0:                      # a nested viewport: its place and viewBox
            T = np.eye(3)
            T[0, 2], T[1, 2] = _num(el.get("x")), _num(el.get("y"))
            vb = [float(v) for v in _NUM.findall(el.get("viewBox", ""))]
            w, h = _num(el.get("width"), 0.0), _num(el.get("height"), 0.0)
            if len(vb) == 4 and vb[2] > 0 and vb[3] > 0 and w > 0 and h > 0:
                k = min(w / vb[2], h / vb[3])
                T = T @ np.array([[k, 0, -vb[0] * k], [0, k, -vb[1] * k], [0, 0, 1]])
            M = M @ T
        if tag in ("svg", "g", "a", "switch"):
            for ch in el:
                walk(ch, M, depth + 1)
            return
        if tag == "use":
            ref = el.get("href") or el.get("{http://www.w3.org/1999/xlink}href") or ""
            target = ids.get(ref.lstrip("#"))
            if target is None or target is el:
                return
            T = np.eye(3)
            T[0, 2], T[1, 2] = _num(el.get("x")), _num(el.get("y"))
            M2 = M @ T
            if _tag(target) == "symbol":
                for ch in target:
                    walk(ch, M2, depth + 1)
            else:
                walk(target, M2, depth + 1)
            return
        name = el.get("id") or tag
        if tag == "path":
            try:
                strokes.extend(path_strokes(el.get("d", ""), M, tol, name))
            except ValueError:
                skipped["a path that does not parse"] = skipped.get("a path that does not parse", 0) + 1
            return
        d = _shape_d(tag, el.attrib)
        if d:
            strokes.extend(path_strokes(d, M, tol, name))
            return
        if tag in ("text", "image", "tspan", "textPath"):
            skipped[tag] = skipped.get(tag, 0) + 1

    walk(root, _root_matrix(root))
    return strokes, skipped


def read(path, tol=0.05):
    with open(path, "rb") as f:
        data = f.read()
    return parse(data.decode("utf-8", "replace"), tol)
