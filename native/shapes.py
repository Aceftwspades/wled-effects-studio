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

import json
import numpy as np

# each kind: the parameters it takes, with their defaults, and a line for the editor
KINDS = {
    "strip":    ({"n": 30, "pitch": 1.0}, "a straight run of n LEDs along X"),
    "ring":     ({"n": 24, "pitch": 1.0, "radius": 0.0, "start_deg": 0.0}, "n LEDs round a circle in the X-Y plane (radius 0: from the pitch)"),
    "panel":    ({"w": 8, "h": 8, "pitch": 1.0, "serpentine": True, "vertical": False}, "w x h LEDs, stood up in the X-Z plane facing the camera"),
    "cylinder": ({"w": 24, "h": 8, "pitch": 1.0}, "w round, h tall, seamless"),
    "sphere":   ({"w": 24, "h": 12, "pitch": 1.0}, "w round, h latitude rows"),
    "cube":     ({"B": 8, "pitch": 1.0, "six": False}, "B x B a face, five faces (six with the bottom)"),
    "polygon":  ({"sides": 5, "per_side": 6, "pitch": 1.0, "radius": 0.0, "start_deg": 0.0},
                 "sides straight sides of per_side LEDs each, in the X-Y plane (radius 0: from the pitch)"),
    "polyhedron": ({"solid": "soccer ball", "mode": "edges", "per_edge": 5, "radius": 12.0},
                   "the edges of a solid, per_edge LEDs each (mode faces: every face outlined on its own)"),
    "polyline": ({"points": [[0, 0, 0], [8, 0, 0], [8, 8, 0]], "pitch": 1.0}, "a strip run laid along a path, an LED every pitch"),
    "points":   ({"points": [[0, 0, 0]]}, "LEDs where they are put, in that order"),
    "reference": ({"vertices": [], "edges": [], "file": ""}, "a mesh drawn as a wireframe to place LEDs against - not LEDs"),
}


# the choices a text parameter takes (the editor shows a combo)
CHOICES = {"solid": ["tetrahedron", "cube", "octahedron", "dodecahedron", "icosahedron", "soccer ball"],
           "mode": ["edges", "faces"]}

# the axis "aim" points: a strip's length, a panel's face, a flat part's normal
AXIS = {"strip": (1.0, 0.0, 0.0), "panel": (0.0, -1.0, 0.0), "polyline": (1.0, 0.0, 0.0)}

# the kinds that are one run of strip (a length says their size; the rest a box)
LINEAR = ("strip", "ring", "polygon", "polyline")


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
    if k == "polygon":
        sides, m = max(3, int(p.get("sides", 5))), max(1, int(p.get("per_side", 6)))
        side = m * pitch                                                # LEDs a pitch apart along each side
        r = float(p.get("radius", 0.0)) or side / (2.0 * math.sin(math.pi / sides))
        a0 = math.radians(float(p.get("start_deg", 0.0)))
        corners = np.stack([np.cos(a0 + np.arange(sides + 1) * 2 * math.pi / sides) * r,
                            np.sin(a0 + np.arange(sides + 1) * 2 * math.pi / sides) * r, np.zeros(sides + 1)], 1)
        t = (np.arange(m) + 0.5) / m                                    # centred on each side: no LED on a corner
        pos = np.concatenate([corners[i] + (corners[i + 1] - corners[i]) * t[:, None] for i in range(sides)])
        return pos.astype(np.float32), None                             # no normals: the shape's centre gives them
    if k == "polyhedron":
        V, E, F = polyhedron(p.get("solid", "soccer ball"))
        V = V * float(p.get("radius", 12.0))
        m = max(1, int(p.get("per_edge", 5)))
        t = (np.arange(m) + 0.5) / m
        if p.get("mode", "edges") == "faces":
            out = []
            for face in face_order(V, F):
                ring = list(face) + [face[0]]
                out += [V[ring[i]] + (V[ring[i + 1]] - V[ring[i]]) * t[:, None] for i in range(len(face))]
        else:
            out = [V[a] + (V[b] - V[a]) * t[:, None] for a, b in edge_walk(V, E)]
        return np.concatenate(out).astype(np.float32), None
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
    # a kind this version does not know (a project from a newer studio, a
    # hand-edited file): no LEDs, rather than a project that will not open
    return np.zeros((0, 3), np.float32), None


# --- the solids ---------------------------------------------------------------------------
_PHI = (1.0 + 5 ** 0.5) / 2.0


def _even_perms(v):
    """The three cyclic permutations of a triple."""
    x, y, z = v
    return [(x, y, z), (y, z, x), (z, x, y)]


def _signs(v, which):
    """Every sign choice of the chosen components (a mask of 1s)."""
    out = [tuple(v)]
    for i in range(3):
        if which[i] and v[i] != 0:
            out = [tuple(-c if j == i else c for j, c in enumerate(o)) for o in out] + out
    return out


def polyhedron(solid):
    """A solid's (vertices (n, 3) on the unit sphere, edges (m, 2), faces:
    lists of vertex indices, each in order round the face)."""
    P = _PHI
    if solid == "tetrahedron":
        V = [(1, 1, 1), (1, -1, -1), (-1, 1, -1), (-1, -1, 1)]
    elif solid == "cube":
        V = _signs((1, 1, 1), (1, 1, 1))
    elif solid == "octahedron":
        V = [v for base in ((1, 0, 0), (0, 1, 0), (0, 0, 1)) for v in _signs(base, (1, 1, 1))]
    elif solid == "icosahedron":
        V = [v for base in _even_perms((0, 1, P)) for v in _signs(base, (1, 1, 1))]
    elif solid == "dodecahedron":
        V = _signs((1, 1, 1), (1, 1, 1)) + [v for base in _even_perms((0, 1 / P, P)) for v in _signs(base, (1, 1, 1))]
    else:                                                               # the soccer ball: a truncated icosahedron
        V = []
        for base in ((0, 1, 3 * P), (1, 2 + P, 2 * P), (P, 2, 2 * P + 1)):
            for perm in _even_perms(base):
                V += _signs(perm, (1, 1, 1))
    V = np.unique(np.round(np.asarray(V, np.float64), 9), axis=0)
    V = V / np.linalg.norm(V, axis=1, keepdims=True)
    # edges: every pair at the shortest distance
    D = np.linalg.norm(V[:, None] - V[None], axis=2)
    D[np.arange(len(V)), np.arange(len(V))] = np.inf
    lo = D.min()
    E = np.asarray([(i, j) for i in range(len(V)) for j in range(i + 1, len(V)) if D[i, j] <= lo * 1.001], int)
    return V.astype(np.float32), E, faces_of(V, E)


def faces_of(V, E):
    """The faces of a convex polyhedron from its edges: each directed edge
    followed by the sharpest left turn (seen from outside) until it
    closes, so a face runs counter-clockwise about its outward normal -
    the way a polygon part runs about its +Z; every directed edge is on
    one face."""
    nbrs = {i: [] for i in range(len(V))}
    for a, b in E:
        nbrs[int(a)].append(int(b)); nbrs[int(b)].append(int(a))
    todo = {(int(a), int(b)) for a, b in E} | {(int(b), int(a)) for a, b in E}
    faces = []
    while todo:
        u, v = min(todo)
        face = [u]
        while True:
            todo.discard((u, v))
            face.append(v)
            n = V[v] / (np.linalg.norm(V[v]) or 1.0)                     # outward at v
            d = V[v] - V[u]
            best, best_a = None, None
            for w in nbrs[v]:
                if w == u and len(nbrs[v]) > 1:
                    continue
                e = V[w] - V[v]
                # the turn from d to e about n: the sharpest left turn wins
                a = math.atan2(float(np.dot(np.cross(d, e), n)), float(np.dot(d, e)))
                if best is None or a > best_a:
                    best, best_a = w, a
            u, v = v, best
            if v == face[0]:
                todo.discard((u, v))
                break
            if len(face) > 64:
                break
        faces.append(face[:-1] if face[-1] == face[0] else face)
    # each face once, in a fixed order (by its centre), its vertices as traced
    seen, out = set(), []
    for f in faces:
        key = tuple(sorted(f))
        if key not in seen and len(f) >= 3:
            seen.add(key); out.append(f)
    return out


def edge_walk(V, E):
    """The edges in a wiring order: on from the end just reached when an
    unused edge starts there, else the nearest unused edge. (a, b) pairs."""
    left = [(int(a), int(b)) for a, b in E]
    out = []
    at = None
    while left:
        if at is not None:
            k = next((i for i, (a, b) in enumerate(left) if at in (a, b)), None)
        else:
            k = None
        if k is None:
            here = V[at] if at is not None else V[0]
            k = min(range(len(left)), key=lambda i: min(np.linalg.norm(V[left[i][0]] - here), np.linalg.norm(V[left[i][1]] - here)))
            a, b = left[k]
            if at is not None and np.linalg.norm(V[b] - here) < np.linalg.norm(V[a] - here):
                a, b = b, a
        else:
            a, b = left[k]
            if b == at:
                a, b = b, a
        left.pop(k); out.append((a, b)); at = b
    return out


def face_order(V, F):
    """The faces nearest-next from the first, each started at the vertex
    nearest where the last ended."""
    F = [list(f) for f in F]
    cent = [V[f].mean(0) for f in F]
    left = list(range(len(F)))
    out, at = [], None
    while left:
        k = left[0] if at is None else min(left, key=lambda i: np.linalg.norm(cent[i] - at))
        left.remove(k)
        f = F[k]
        if at is not None:
            j = min(range(len(f)), key=lambda i: np.linalg.norm(V[f[i]] - at))
            f = f[j:] + f[:j]
        out.append(f); at = V[f[0]]
    return out


# --- aiming: a part's axis along a direction ------------------------------------------------
def axis_of(part):
    return np.asarray(AXIS.get(part.get("kind"), (0.0, 0.0, 1.0)), np.float64)


def euler_of(R):
    """(rx, ry, rz) degrees with rotation(rx, ry, rz) == R (Rz Ry Rx)."""
    sy = -float(R[2, 0])
    sy = max(-1.0, min(1.0, sy))
    ry = math.asin(sy)
    if abs(math.cos(ry)) > 1e-6:
        rx = math.atan2(float(R[2, 1]), float(R[2, 2]))
        rz = math.atan2(float(R[1, 0]), float(R[0, 0]))
    else:                                                               # looking straight up or down: roll into rx
        rx = math.atan2(-float(R[1, 2]), float(R[1, 1]))
        rz = 0.0
    return [round(math.degrees(v), 3) for v in (rx, ry, rz)]


def aim_rotation(axis, direction, spin_deg=0.0):
    """The rotation taking `axis` onto `direction`, then `spin` degrees
    about the direction: (rx, ry, rz) for the part."""
    a = np.asarray(axis, np.float64); a /= (np.linalg.norm(a) or 1.0)
    d = np.asarray(direction, np.float64)
    L = np.linalg.norm(d)
    if L < 1e-9:
        return [0.0, 0.0, 0.0]
    d /= L
    c = float(np.dot(a, d))
    v = np.cross(a, d)
    s = np.linalg.norm(v)
    if s < 1e-9:
        if c > 0:
            R = np.eye(3)
        else:                                                           # opposite: half a turn about any perpendicular
            p = np.cross(a, [1.0, 0.0, 0.0])
            if np.linalg.norm(p) < 1e-6:
                p = np.cross(a, [0.0, 1.0, 0.0])
            p /= np.linalg.norm(p)
            R = 2.0 * np.outer(p, p) - np.eye(3)
    else:
        v /= s
        K = np.array([[0, -v[2], v[1]], [v[2], 0, -v[0]], [-v[1], v[0], 0]])
        ang = math.atan2(s, c)
        R = np.eye(3) + math.sin(ang) * K + (1 - math.cos(ang)) * (K @ K)
    if spin_deg:
        t = math.radians(spin_deg)
        K = np.array([[0, -d[2], d[1]], [d[2], 0, -d[0]], [-d[1], d[0], 0]])
        R = (np.eye(3) + math.sin(t) * K + (1 - math.cos(t)) * (K @ K)) @ R
    return euler_of(R)


def aimed(part, direction, distance=None, spin_deg=0.0):
    """A copy of the part turned so its axis runs along `direction`, and
    (with a distance) moved to that far from the origin along it."""
    q = {k: (list(v) if isinstance(v, list) else (dict(v) if isinstance(v, dict) else v)) for k, v in part.items()}
    d = np.asarray(direction, np.float64)
    L = np.linalg.norm(d)
    if L < 1e-9:
        return q
    d /= L
    q["rot"] = aim_rotation(axis_of(part), d, spin_deg)
    if distance is not None:
        q["pos"] = [round(float(c), 3) for c in d * float(distance)]
    return q


# --- arranging several parts (the layout tools) ---------------------------------------------
def aligned(parts, idxs, ref, axis):
    """The parts at `idxs` given the reference part's position on one axis (0 x, 1 y, 2 z)."""
    out = json.loads(json.dumps(parts))
    if not (0 <= ref < len(out)):
        return out
    v = float((out[ref].get("pos") or [0, 0, 0])[axis])
    for i in idxs:
        if 0 <= i < len(out) and i != ref:
            p = list(out[i].get("pos") or [0.0, 0.0, 0.0]); p[axis] = v; out[i]["pos"] = p
    return out


def distributed(parts, idxs, axis):
    """The parts at `idxs` spread evenly along one axis between the two
    farthest apart, in the order they sit."""
    out = json.loads(json.dumps(parts))
    ids = sorted({i for i in idxs if 0 <= i < len(out)}, key=lambda i: float((out[i].get("pos") or [0, 0, 0])[axis]))
    if len(ids) < 3:
        return out
    lo = float((out[ids[0]].get("pos") or [0, 0, 0])[axis]); hi = float((out[ids[-1]].get("pos") or [0, 0, 0])[axis])
    for k, i in enumerate(ids):
        p = list(out[i].get("pos") or [0.0, 0.0, 0.0]); p[axis] = lo + (hi - lo) * k / (len(ids) - 1); out[i]["pos"] = p
    return out


def matched(parts, idxs, ref, what="scale"):
    """The parts at `idxs` given the reference part's scale ("scale") or turn ("rot")."""
    out = json.loads(json.dumps(parts))
    if not (0 <= ref < len(out)):
        return out
    for i in idxs:
        if 0 <= i < len(out) and i != ref:
            if what == "rot":
                out[i]["rot"] = list(out[ref].get("rot") or [0.0, 0.0, 0.0])
            else:
                out[i]["scale"] = float(out[ref].get("scale", 1.0))
    return out


def split_part(part):
    """A polyhedron part as parts of its own: a strip per edge, or a
    polygon per face - each placed where the solid had it, so the LEDs
    stay put and every piece can then be moved, turned and resized alone."""
    if part.get("kind") != "polyhedron":
        return [part]
    p = part.get("params", {})
    V, E, F = polyhedron(p.get("solid", "soccer ball"))
    V = V * float(p.get("radius", 12.0))
    m = max(1, int(p.get("per_edge", 5)))
    Rp = rotation(*part.get("rot", [0, 0, 0]))
    sc = part.get("scale", 1.0); sc = float(sc[0] if isinstance(sc, list) else sc)
    at = np.asarray(part.get("pos", [0, 0, 0]), np.float64)
    world = lambda v: (np.asarray(v, np.float64) * sc) @ Rp.T + at
    out = []
    if p.get("mode", "edges") == "faces":
        for k, face in enumerate(face_order(V, F)):
            c = world(V[face].mean(0))
            v0 = world(V[face[0]])
            x = v0 - c; r = float(np.linalg.norm(x)); x /= (r or 1.0)
            z = np.cross(world(V[face[1]]) - v0, x)                     # the face's normal, outward for a traced face
            if np.dot(z, c) < 0:
                z = -z
            z /= (np.linalg.norm(z) or 1.0)
            y = np.cross(z, x)
            R = np.stack([x, y, z], 1)
            q = new_part("polygon", sides=len(face), per_side=m, radius=round(r, 4),
                         pitch=round(float(np.linalg.norm(world(V[face[1]]) - v0)) / m, 4), start_deg=0.0)
            q["name"] = f"{p.get('solid', 'solid')} face {k + 1}"
            q["pos"] = [round(float(v), 3) for v in c]; q["rot"] = euler_of(R)
            out.append(q)
    else:
        for k, (a, b) in enumerate(edge_walk(V, E)):
            A, B = world(V[a]), world(V[b])
            d = B - A; L = float(np.linalg.norm(d))
            q = new_part("strip", n=m, pitch=round(L / m, 4))
            q["name"] = f"{p.get('solid', 'solid')} edge {k + 1}"
            q["pos"] = [round(float(v), 3) for v in (A + B) / 2]
            q["rot"] = aim_rotation((1.0, 0.0, 0.0), d)
            out.append(q)
    if part.get("reverse"):
        out = [dict(q, reverse=True) for q in out][::-1]
    return out


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
