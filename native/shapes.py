"""Shapes: a geometry built from parts.

A shape is a list of parts - strip runs, rings, panels, cylinders,
spheres, cubes, a polyline a strip follows, loose points placed by hand
or read from a file - each with a position, a rotation and a scale. The
parts resolve to one list of LEDs in wiring order: part after part, each
part's own order inside (a strip along its length, a ring round from its
start angle, a panel in rows with serpentine as chosen), reversed when
the part says so. That order IS the ledmap; the positions are what the
3-D view draws and what the device's shape table carries, so Position,
Direction and the rest see the real shape.

    parts = [{"kind": "ring", "params": {"n": 24}, "pos": [0, 0, 0], "rot": [0, 0, 0], "scale": 1.0}, ...]
    pos, nrm, owner = resolve(parts)      # (n, 3) positions, (n, 3) unit normals, (n,) part index

Units are LED pitches: a strip of pitch 1 has its LEDs one unit apart,
the sim draws an LED as a square of a pitch's size, and the whole shape
is fitted to the device's -1..1 box when it is sent. Z is up, Y is away
from the camera, X is to the right - the cube's axes.
"""
import math

import numpy as np

# each kind: the parameters it takes, with their defaults, and a line for the editor
KINDS = {
    "strip":    ({"n": 30, "pitch": 1.0}, "a straight run of n LEDs along X"),
    "ring":     ({"n": 24, "pitch": 1.0, "radius": 0.0, "start_deg": 0.0}, "n LEDs round a circle in the X-Y plane (radius 0: from the pitch)"),
    "panel":    ({"w": 8, "h": 8, "pitch": 1.0, "serpentine": True, "vertical": False}, "w x h LEDs, stood up in the X-Z plane facing the camera"),
    "cylinder": ({"w": 24, "h": 8, "pitch": 1.0}, "w round, h tall, seamless"),
    "sphere":   ({"w": 24, "h": 12, "pitch": 1.0}, "w round, h latitude rows"),
    "cube":     ({"B": 8, "pitch": 1.0, "six": False}, "B x B a face, five faces (six with the bottom)"),
    "polyline": ({"points": [[0, 0, 0], [8, 0, 0], [8, 8, 0]], "pitch": 1.0}, "a strip run laid along a path, an LED every pitch"),
    "points":   ({"points": [[0, 0, 0]]}, "LEDs where they are put, in that order"),
    "reference": ({"vertices": [], "edges": [], "file": ""}, "a mesh drawn as a wireframe to place LEDs against - not LEDs"),
}


def new_part(kind, **params):
    p = dict(KINDS[kind][0])
    p.update(params)
    return {"kind": kind, "name": kind, "params": p, "pos": [0.0, 0.0, 0.0], "rot": [0.0, 0.0, 0.0], "scale": 1.0, "reverse": False}


# --- one part's LEDs, in its own frame ------------------------------------------------
def _matrix_order(w, h, serpentine, vertical):
    """Logical indices (row-major) in wiring order for a panel."""
    out = []
    if vertical:
        for x in range(w):
            ys = range(h) if (not serpentine or x % 2 == 0) else range(h - 1, -1, -1)
            out += [y * w + x for y in ys]
    else:
        for y in range(h):
            xs = range(w) if (not serpentine or y % 2 == 0) else range(w - 1, -1, -1)
            out += [y * w + x for x in xs]
    return np.asarray(out)


def part_points(part):
    """(pos, nrm) of one part before its transform: (n, 3) each; nrm may be None."""
    k, p = part["kind"], part.get("params", {})
    pitch = float(p.get("pitch", 1.0)) or 1.0
    if k == "strip":
        n = max(1, int(p.get("n", 30)))
        t = np.arange(n, dtype=np.float32) - (n - 1) / 2.0
        return np.stack([t * pitch, np.zeros(n), np.zeros(n)], 1), np.tile([0.0, -1.0, 0.0], (n, 1))
    if k == "ring":
        n = max(1, int(p.get("n", 24)))
        r = float(p.get("radius", 0.0)) or n * pitch / (2 * math.pi)
        a = np.radians(float(p.get("start_deg", 0.0))) + np.arange(n) * (2 * math.pi / n)
        pos = np.stack([np.cos(a) * r, np.sin(a) * r, np.zeros(n)], 1)
        return pos, np.stack([np.cos(a), np.sin(a), np.zeros(n)], 1)
    if k == "panel":
        w, h = max(1, int(p.get("w", 8))), max(1, int(p.get("h", 8)))
        ys, xs = np.mgrid[0:h, 0:w]
        pos = np.stack([(xs.ravel() - (w - 1) / 2.0) * pitch, np.zeros(w * h), ((h - 1) / 2.0 - ys.ravel()) * pitch], 1)
        order = _matrix_order(w, h, bool(p.get("serpentine", True)), bool(p.get("vertical", False)))
        return pos[order], np.tile([0.0, -1.0, 0.0], (w * h, 1))
    if k == "cylinder":
        w, h = max(3, int(p.get("w", 24))), max(1, int(p.get("h", 8)))
        ys, xs = np.mgrid[0:h, 0:w]
        a = xs.ravel() * (2 * math.pi / w)
        r = w * pitch / (2 * math.pi)
        pos = np.stack([np.cos(a) * r, np.sin(a) * r, ((h - 1) / 2.0 - ys.ravel()) * pitch], 1)
        order = _matrix_order(w, h, bool(p.get("serpentine", False)), False)
        return pos[order], np.stack([np.cos(a), np.sin(a), np.zeros(w * h)], 1)[order]
    if k == "sphere":
        w, h = max(3, int(p.get("w", 24))), max(2, int(p.get("h", 12)))
        ys, xs = np.mgrid[0:h, 0:w]
        a = xs.ravel() * (2 * math.pi / w)
        lat = (ys.ravel() + 0.5) / h * math.pi - math.pi / 2
        R = w * pitch / (2 * math.pi)
        nrm = np.stack([np.cos(lat) * np.cos(a), np.cos(lat) * np.sin(a), -np.sin(lat)], 1)
        order = _matrix_order(w, h, bool(p.get("serpentine", False)), False)
        return (nrm * R)[order], nrm[order]
    if k == "cube":
        B = max(2, int(p.get("B", 8)))
        six = bool(p.get("six", False))
        pos, nrm = [], []
        # faces in the cube_fx wiring order: N, W, T, E, S (, B); each a B x B raster
        half = (B - 1) / 2.0
        grid = [((a - half) * pitch, (b - half) * pitch) for b in range(B) for a in range(B)]
        R = B * pitch / 2.0
        # each face as cfx_pos() places it (a: the column, b: the row of the net's block)
        faces = [("N", lambda a, b: (a, R, b), (0, 1, 0)), ("W", lambda a, b: (-R, -b, a), (-1, 0, 0)),
                 ("T", lambda a, b: (a, -b, R), (0, 0, 1)), ("E", lambda a, b: (R, -b, -a), (1, 0, 0)),
                 ("S", lambda a, b: (a, -R, -b), (0, -1, 0))]
        if six:
            faces.append(("B", lambda a, b: (a, -b, -R), (0, 0, -1)))
        for _, f, n in faces:
            for a, b in grid:
                pos.append(f(a, b)); nrm.append(n)
        return np.asarray(pos, np.float32), np.asarray(nrm, np.float32)
    if k == "polyline":
        pts = np.asarray(p.get("points") or [[0, 0, 0]], np.float32).reshape(-1, 3)
        if len(pts) < 2:
            return pts, None
        seg = np.diff(pts, axis=0)
        L = np.linalg.norm(seg, axis=1)
        total = float(L.sum())
        n = max(1, int(total / pitch) + 1)
        d = np.arange(n) * pitch
        d = d[d <= total + 1e-6]
        cum = np.concatenate([[0.0], np.cumsum(L)])
        out = []
        for s in d:
            i = int(np.searchsorted(cum, s, side="right") - 1)
            i = min(max(i, 0), len(seg) - 1)
            t = (s - cum[i]) / L[i] if L[i] > 0 else 0.0
            out.append(pts[i] + seg[i] * t)
        return np.asarray(out, np.float32), None
    if k == "reference":
        return np.zeros((0, 3), np.float32), None          # drawn, never lit
    if k == "points":
        pts = np.asarray(p.get("points") or [[0, 0, 0]], np.float32).reshape(-1, 3)
        nrm = p.get("normals")
        nrm = np.asarray(nrm, np.float32).reshape(-1, 3) if nrm is not None and len(nrm) == len(pts) else None
        return pts, nrm
    raise ValueError(f"unknown part kind {k!r}")


def rotation(rx, ry, rz):
    """A rotation matrix from degrees about X, then Y, then Z."""
    ax, ay, az = np.radians([rx, ry, rz])
    cx, sx = math.cos(ax), math.sin(ax)
    cy, sy = math.cos(ay), math.sin(ay)
    cz, sz = math.cos(az), math.sin(az)
    Rx = np.array([[1, 0, 0], [0, cx, -sx], [0, sx, cx]])
    Ry = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]])
    Rz = np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]])
    return Rz @ Ry @ Rx


def transform(part, pos, nrm):
    """A part's LEDs into the shape's frame: scale, rotate, move."""
    s = part.get("scale", 1.0)
    s = np.asarray(s if isinstance(s, (list, tuple)) else [s, s, s], np.float32)
    R = rotation(*part.get("rot", [0, 0, 0]))
    out = (pos * s) @ R.T + np.asarray(part.get("pos", [0, 0, 0]), np.float32)
    if nrm is not None:
        n = nrm @ R.T
        L = np.linalg.norm(n, axis=1, keepdims=True)
        nrm = n / np.where(L > 1e-9, L, 1.0)
    if part.get("reverse"):
        out = out[::-1]
        if nrm is not None:
            nrm = nrm[::-1]
    return out.astype(np.float32), None if nrm is None else nrm.astype(np.float32)


def reference_segments(parts, limit=3000):
    """The wireframe of every reference part, transformed: (m, 2, 3) segments."""
    out = []
    for part in parts:
        if part.get("kind") != "reference":
            continue
        v = np.asarray(part["params"].get("vertices") or [], np.float32).reshape(-1, 3)
        e = np.asarray(part["params"].get("edges") or [], int).reshape(-1, 2)
        if len(v) == 0 or len(e) == 0:
            continue
        e = e[(e[:, 0] >= 0) & (e[:, 1] >= 0) & (e[:, 0] < len(v)) & (e[:, 1] < len(v))][:limit]
        tv, _ = transform(dict(part, reverse=False), v, None)
        out.append(np.stack([tv[e[:, 0]], tv[e[:, 1]]], 1))
    return np.concatenate(out) if out else np.zeros((0, 2, 3), np.float32)


def resolve(parts):
    """Every part's LEDs, in wiring order: (pos (n, 3), nrm (n, 3) or None, owner (n,))."""
    P, N, O = [], [], []
    have_nrm = True
    for i, part in enumerate(parts):
        pos, nrm = part_points(part)
        pos, nrm = transform(part, pos, nrm)
        P.append(pos); O.append(np.full(len(pos), i))
        if nrm is None:
            have_nrm = False
            N.append(np.zeros_like(pos))
        else:
            N.append(nrm)
    if not P or sum(len(p) for p in P) == 0:
        return np.zeros((0, 3), np.float32), None, np.zeros(0, int)
    pos = np.concatenate(P)
    nrm = np.concatenate(N) if have_nrm else None
    if nrm is None:
        # no normals from the parts: the direction from the shape's centre
        c = (pos.min(0) + pos.max(0)) * 0.5
        d = pos - c
        L = np.linalg.norm(d, axis=1, keepdims=True)
        nrm = (d / np.where(L > 1e-9, L, 1.0)).astype(np.float32)
    return pos, nrm, np.concatenate(O)


def part_count(part):
    return len(part_points(part)[0])


# --- wiring helpers ----------------------------------------------------------------------
def chain_order(pos, start=0):
    """A nearest-neighbour walk from `start`: the order a strip would most
    likely be run through loose points. Indices."""
    n = len(pos)
    if n == 0:
        return np.zeros(0, int)
    left = np.ones(n, bool)
    order = [int(start) % n]
    left[order[0]] = False
    cur = pos[order[0]]
    for _ in range(n - 1):
        d = np.linalg.norm(pos - cur, axis=1)
        d[~left] = np.inf
        k = int(np.argmin(d))
        order.append(k); left[k] = False; cur = pos[k]
    return np.asarray(order)


def mirrored(part, axis):
    """A copy of a part mirrored through the shape's origin along an axis (0 x, 1 y, 2 z)."""
    q = {k: (list(v) if isinstance(v, list) else (dict(v) if isinstance(v, dict) else v)) for k, v in part.items()}
    q["pos"] = list(part.get("pos", [0, 0, 0])); q["pos"][axis] = -q["pos"][axis]
    rot = list(part.get("rot", [0, 0, 0]))
    # a mirror is not a rotation: the part is turned so its face points back; near enough for LED props
    if axis == 0: rot[1] = -rot[1]; rot[2] = 180 - rot[2]
    elif axis == 1: rot[0] = -rot[0]; rot[2] = -rot[2]
    else: rot[0] = 180 - rot[0]; rot[1] = -rot[1]
    q["rot"] = rot
    q["name"] = part.get("name", part["kind"]) + " mirror"
    return q


def arrayed(part, count, offset):
    """Copies of a part stepped by an offset: [part + offset, part + 2 offset, ...]."""
    out = []
    for k in range(1, max(1, int(count))):
        q = {kk: (list(v) if isinstance(v, list) else (dict(v) if isinstance(v, dict) else v)) for kk, v in part.items()}
        q["pos"] = [float(a) + float(b) * k for a, b in zip(part.get("pos", [0, 0, 0]), offset)]
        q["name"] = part.get("name", part["kind"]) + f" {k + 1}"
        out.append(q)
    return out


# --- a logical grid for a shape ----------------------------------------------------------
def grid_layout(pos, cell=1.0):
    """The LEDs onto a w x h logical grid, seen from the front (X across, Z
    up), a cell per pitch: (w, h, map) where map[logical] = LED index or -1.
    Two LEDs in one cell: the first keeps it, the rest are reported as
    collisions (they light with the ledmap as the last of the cell)."""
    if len(pos) == 0:
        return 1, 1, [-1], 0
    x, z = pos[:, 0], pos[:, 2]
    x0, z1 = x.min(), z.max()
    cx = np.round((x - x0) / cell).astype(int)
    cz = np.round((z1 - z) / cell).astype(int)
    w, h = int(cx.max()) + 1, int(cz.max()) + 1
    m = [-1] * (w * h)
    collisions = 0
    for i, (a, b) in enumerate(zip(cx, cz)):
        k = b * w + a
        if m[k] == -1:
            m[k] = i
        else:
            collisions += 1
    return w, h, m, collisions
