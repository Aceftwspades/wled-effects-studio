"""Shapes from other programs.

    mesh = read_mesh(path)                 # .obj / .ply / .stl: vertices, edges, faces, normals
    pts, nrm = mesh_leds(mesh, "edges", pitch=1.0)   # LEDs at the vertices, along the edges, or over the surface
    model = read_xmodel(path)              # an xLights prop: LEDs with their numbers, and the grid
    pts, order = read_points(path)         # x y z [index] rows: CSV, whitespace or JSON

A mesh from Blender or a CAD program says where a shape's corners and
surfaces are, not where the LEDs go. Three readings of it:

- **vertices**: one LED per vertex, in the file's order - a wireframe prop
  drawn with a vertex per LED.
- **edges**: an LED every `pitch` along the edges - a strip run round the
  shape's outline. The edges are chained into as few runs as possible
  (each starts where the last ended when it can), so the wiring order is
  a plausible strip path; the studio's chain tool can redo it.
- **surface**: an LED every `pitch` over the faces - a shape covered in
  LEDs, panel-like, ordered face by face.

xLights models (`.xmodel`) already are LEDs: a custom model is a grid of
node numbers (rows by `;`, columns by `,`, layers by `|` for the 3-D
kind), which gives positions, the wiring order (the numbers) and a logical
grid WLED can use directly. Other xLights model types are not read.
"""
import json
import math
import os
import re
import struct
import xml.etree.ElementTree as ET

import numpy as np


# --- meshes ----------------------------------------------------------------------------------
class Mesh:
    def __init__(self):
        self.v = np.zeros((0, 3), np.float32)      # vertices
        self.vn = None                             # per-vertex normals, or None
        self.edges = []                            # (i, j) pairs, unique
        self.faces = []                            # index lists
        self.source = ""

    def finish(self):
        seen = set()
        out = []
        for f in self.faces:
            for k in range(len(f)):
                a, b = f[k], f[(k + 1) % len(f)]
                key = (min(a, b), max(a, b))
                if a != b and key not in seen:
                    seen.add(key); out.append(key)
        for a, b in self.edges:
            key = (min(a, b), max(a, b))
            if a != b and key not in seen:
                seen.add(key); out.append(key)
        self.edges = out
        return self


def read_obj(path):
    m = Mesh(); m.source = os.path.basename(path)
    vs, vns, vn_of = [], [], {}
    for line in open(path, encoding="utf-8", errors="replace"):
        parts = line.split()
        if not parts or parts[0].startswith("#"):
            continue
        if parts[0] == "v" and len(parts) >= 4:
            vs.append([float(parts[1]), float(parts[2]), float(parts[3])])
        elif parts[0] == "vn" and len(parts) >= 4:
            vns.append([float(parts[1]), float(parts[2]), float(parts[3])])
        elif parts[0] in ("f", "l") and len(parts) >= 3:
            idx = []
            for tok in parts[1:]:
                bits = tok.split("/")
                i = int(bits[0])
                i = i - 1 if i > 0 else len(vs) + i
                idx.append(i)
                if len(bits) >= 3 and bits[2]:
                    n = int(bits[2]); vn_of[i] = n - 1 if n > 0 else len(vns) + n
            if parts[0] == "f":
                m.faces.append(idx)
            else:
                m.edges += [(idx[k], idx[k + 1]) for k in range(len(idx) - 1)]
    m.v = np.asarray(vs, np.float32).reshape(-1, 3)
    if vns and vn_of:
        vn = np.zeros((len(vs), 3), np.float32)
        for i, n in vn_of.items():
            if 0 <= i < len(vs) and 0 <= n < len(vns):
                vn[i] = vns[n]
        m.vn = vn
    return m.finish()


def read_ply(path):
    m = Mesh(); m.source = os.path.basename(path)
    with open(path, "rb") as f:
        head = []
        while True:
            line = f.readline().decode("ascii", "replace").strip()
            head.append(line)
            if line == "end_header" or not line:
                break
        fmt = next((l.split()[1] for l in head if l.startswith("format")), "ascii")
        elements = []
        for l in head:
            if l.startswith("element"):
                _, name, n = l.split()[:3]
                elements.append([name, int(n), []])
            elif l.startswith("property") and elements:
                bits = l.split()
                if bits[1] == "list":
                    elements[-1][2].append(("list", bits[2], bits[3], bits[4]))
                else:
                    elements[-1][2].append((bits[1], bits[2]))
        TYPES = {"char": "b", "uchar": "B", "short": "h", "ushort": "H", "int": "i", "uint": "I", "float": "f", "double": "d",
                 "int8": "b", "uint8": "B", "int16": "h", "uint16": "H", "int32": "i", "uint32": "I", "float32": "f", "float64": "d"}
        endian = "<" if "little" in fmt else ">"
        vs, vns, faces, edges = [], [], [], []
        for name, n, props in elements:
            for _ in range(n):
                row = {}
                if fmt == "ascii":
                    toks = f.readline().decode("ascii", "replace").split()
                    k = 0
                    for p in props:
                        if p[0] == "list":
                            cnt = int(toks[k]); k += 1
                            row[p[3]] = [float(t) for t in toks[k:k + cnt]]; k += cnt
                        else:
                            row[p[1]] = float(toks[k]); k += 1
                else:
                    for p in props:
                        if p[0] == "list":
                            cnt = struct.unpack(endian + TYPES[p[1]], f.read(struct.calcsize(TYPES[p[1]])))[0]
                            sz = struct.calcsize(TYPES[p[2]])
                            row[p[3]] = list(struct.unpack(endian + TYPES[p[2]] * cnt, f.read(sz * cnt)))
                        else:
                            row[p[1]] = struct.unpack(endian + TYPES[p[0]], f.read(struct.calcsize(TYPES[p[0]])))[0]
                if name == "vertex":
                    vs.append([row.get("x", 0), row.get("y", 0), row.get("z", 0)])
                    if "nx" in row:
                        vns.append([row["nx"], row.get("ny", 0), row.get("nz", 0)])
                elif name == "face":
                    idx = row.get("vertex_indices") or row.get("vertex_index") or []
                    faces.append([int(i) for i in idx])
                elif name == "edge":
                    edges.append((int(row.get("vertex1", 0)), int(row.get("vertex2", 0))))
    m.v = np.asarray(vs, np.float32).reshape(-1, 3)
    m.vn = np.asarray(vns, np.float32) if len(vns) == len(vs) and vs else None
    m.faces, m.edges = faces, edges
    return m.finish()


def read_stl(path):
    m = Mesh(); m.source = os.path.basename(path)
    data = open(path, "rb").read()
    tris = []
    ascii_ = data[:5] == b"solid" and b"facet" in data[:400]
    if ascii_:
        cur = []
        for line in data.decode("ascii", "replace").splitlines():
            t = line.split()
            if len(t) >= 4 and t[0] == "vertex":
                cur.append([float(t[1]), float(t[2]), float(t[3])])
                if len(cur) == 3:
                    tris.append(cur); cur = []
    else:
        n = struct.unpack("<I", data[80:84])[0]
        off = 84
        for _ in range(n):
            if off + 50 > len(data):
                break
            vals = struct.unpack("<12f", data[off:off + 48])
            tris.append([list(vals[3:6]), list(vals[6:9]), list(vals[9:12])])
            off += 50
    # triangles share corners: one vertex per distinct position
    index = {}
    vs = []
    for tri in tris:
        f = []
        for p in tri:
            key = tuple(round(c, 5) for c in p)
            if key not in index:
                index[key] = len(vs); vs.append(list(key))
            f.append(index[key])
        m.faces.append(f)
    m.v = np.asarray(vs, np.float32).reshape(-1, 3)
    return m.finish()


def read_mesh(path):
    ext = os.path.splitext(path)[1].lower()
    if ext == ".obj":
        return read_obj(path)
    if ext == ".ply":
        return read_ply(path)
    if ext == ".stl":
        return read_stl(path)
    raise ValueError(f"not a mesh file: {os.path.basename(path)} (.obj, .ply or .stl)")


def _chain_edges(edges, v):
    """The edges as runs: each run continues from the last run's end when
    an unused edge starts there, else starts a new one at the nearest
    unused edge. [(i, j), ...] in walking order, direction fixed."""
    left = list(edges)
    out = []
    cur = None
    while left:
        pick = None
        if cur is not None:
            for k, (a, b) in enumerate(left):
                if a == cur:
                    pick = (k, a, b); break
                if b == cur:
                    pick = (k, b, a); break
        if pick is None:
            if cur is None:
                pick = (0, left[0][0], left[0][1])
            else:
                d = [min(np.linalg.norm(v[a] - v[cur]), np.linalg.norm(v[b] - v[cur])) for a, b in left]
                k = int(np.argmin(d)); a, b = left[k]
                pick = (k, a, b) if np.linalg.norm(v[a] - v[cur]) <= np.linalg.norm(v[b] - v[cur]) else (k, b, a)
        k, a, b = pick
        left.pop(k)
        out.append((a, b)); cur = b
    return out


MESH_MAX = 20000        # LEDs one reading of a mesh may place: the studio holds 65,536, a WLED drives a few thousand
MESH_AIM = 3000         # what the pitch suggested past MESH_MAX aims for


class TooManyLeds(ValueError):
    """A mesh reading that would place more than MESH_MAX LEDs; `pitch` is
    one that gives about MESH_AIM (None when the pitch is not the reason)."""
    def __init__(self, text, pitch=None):
        super().__init__(text)
        self.pitch = pitch


def mesh_estimate(mesh, mode="edges", pitch=1.0):
    """About how many LEDs mesh_leds places, from the edges' lengths and
    the triangles' sides alone - worked out before any is placed, as a CAD
    file in millimetres at a pitch of 1 is hundreds of thousands (a 1 m
    triangle: 501,501), minutes of work and a frozen window (issue #7)."""
    v = np.asarray(mesh.v, np.float64)
    if len(v) == 0:
        return 0
    if mode == "vertices":
        return len(v)
    pitch = abs(float(pitch)) or 1.0
    if mode == "edges":
        if not mesh.edges:
            return 0
        e = np.asarray(mesh.edges, np.int64).reshape(-1, 2)
        L = np.linalg.norm(v[e[:, 1]] - v[e[:, 0]], axis=1)
        return int(np.sum(np.maximum(1, np.round(L / pitch)) + 1))
    if mode == "surface":
        tri = [(f[0], f[k], f[k + 1]) for f in mesh.faces for k in range(1, len(f) - 1)]
        if not tri:
            return 0
        t = np.asarray(tri, np.int64)
        a, b, c = v[t[:, 0]], v[t[:, 1]], v[t[:, 2]]
        area = float(0.5 * np.linalg.norm(np.cross(b - a, c - a), axis=1).sum())
        return int(round(area / (pitch * pitch))) + len(tri) // 8 + 1      # a pitch square each, and the odd one more
    raise ValueError(f"unknown mesh reading {mode!r}")


def _round_up(x):
    """The next of 1, 2, 2.5, 5 times a power of ten, at or above x."""
    k = 10.0 ** math.floor(math.log10(x))
    for m in (1.0, 2.0, 2.5, 5.0, 10.0):
        if m * k >= x * (1 - 1e-9):
            return m * k
    return 10.0 * k


def mesh_pitch_for(mesh, mode, pitch=1.0, aim=MESH_AIM):
    """A round pitch that places about `aim` LEDs or fewer - the count goes
    with 1/pitch along edges, 1/pitch squared over a surface."""
    pitch = abs(float(pitch)) or 1.0
    n = mesh_estimate(mesh, mode, pitch)
    if n <= aim:
        return pitch
    p = _round_up(pitch * (n / aim) ** (0.5 if mode == "surface" else 1.0))
    for _ in range(12):
        if mesh_estimate(mesh, mode, p) <= aim * 1.2:
            break
        p = _round_up(p * 1.01)
    return p


# --- LEDs over a mesh's surface ------------------------------------------------------------------
# The first reading laid an affine lattice over each triangle of a fan - its spacing from two sides
# taken apart, so a square at a pitch of 1 got 153 LEDs 0.77 apart instead of 100 a pitch apart,
# a thin or obtuse triangle put LEDs a tenth of a pitch apart, and the duplicates on shared edges
# were found by rounding to cells (two that straddle a cell's border both stayed: 0.4 apart on a
# cube's folds). Now:
#   - flat regions - the triangles of one plane joined across their shared edges, so an STL's
#     triangulated cube face is one square again - get a regular grid at the pitch, centred, its
#     LEDs at least half a pitch in from the region's border: a panel of the surface, as built;
#   - the rest (curved surfaces, regions too small for a grid) is sampled finely and thinned so no
#     two LEDs are nearer than 0.98 of a pitch (a spatial hash that looks in the neighbouring cells,
#     so nothing straddles a border unseen);
#   - the grids' LEDs on two sides of a fold are both kept: along the surface they are a pitch
#     apart, though the chord between them is shorter.
SURFACE_THIN = 0.98


def _planes(v, tris):
    """The triangles grouped into flat regions: those sharing an edge and lying in one plane (their
    normals within a hundredth of a degree, their planes within a millionth of the mesh's size)."""
    a, b, c = v[tris[:, 0]], v[tris[:, 1]], v[tris[:, 2]]
    n = np.cross(b - a, c - a)
    L = np.linalg.norm(n, axis=1)
    good = L > 1e-12
    n = n / np.where(good, L, 1.0)[:, None]
    d = np.einsum("ij,ij->i", n, a)
    scale = float(np.ptp(v, axis=0).max()) or 1.0
    parent = list(range(len(tris)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    owner = {}
    for t, (i, j, k) in enumerate(tris.tolist()):
        if not good[t]:
            continue
        for e in ((i, j), (j, k), (k, i)):
            key = (min(e), max(e))
            o = owner.get(key)
            if o is None:
                owner[key] = t
            elif np.dot(n[o], n[t]) > 1 - 1.5e-8 and abs(d[o] - d[t]) < 1e-6 * scale:
                parent[find(o)] = find(t)
    groups = {}
    for t in range(len(tris)):
        if good[t]:
            groups.setdefault(find(t), []).append(t)
    return list(groups.values()), n, L / 2.0


def _seg_dist(P, A, B):
    """Each point of P (k, 2) to the nearest of the segments A[i]-B[i] (m, 2)."""
    AB = B - A
    t = np.clip(np.einsum("kmj,mj->km", P[:, None] - A[None], AB) / np.maximum(np.einsum("mj,mj->m", AB, AB), 1e-18), 0, 1)
    Q = A[None] + t[..., None] * AB[None]
    return np.linalg.norm(P[:, None] - Q, axis=2).min(1)


def _region_grid(v, tris, group, n, pitch):
    """A flat region's grid: LEDs a pitch apart, centred on it, half a pitch in from its border."""
    T = tris[group]
    # the region's border: the edges only one of its triangles has
    cnt = {}
    for i, j, k in T.tolist():
        for e in ((i, j), (j, k), (k, i)):
            key = (min(e), max(e))
            cnt[key] = cnt.get(key, 0) + 1
    border = [e for e, c in cnt.items() if c == 1]
    if not border:
        return np.zeros((0, 3))
    # the plane's axes: along its longest border edge, and across it
    lens = [np.linalg.norm(v[b] - v[a]) for a, b in border]
    a, b = border[int(np.argmax(lens))]
    u = v[b] - v[a]
    u = u / (np.linalg.norm(u) or 1.0)
    w = np.cross(n, u)
    o = v[a]
    to2 = lambda P: np.stack([(P - o) @ u, (P - o) @ w], -1)            # noqa: E731
    corners = to2(v[np.unique(T)])
    lo, hi = corners.min(0), corners.max(0)
    # laid in the half-pitch margin from the start: a 10-pitch square is 10 x 10 at 0.5 .. 9.5, not
    # 11 x 11 from its border with the border rows dropped (9 x 9 and a ragged fill round it)
    usable = np.maximum(hi - lo - pitch, 0.0)
    cols = np.floor(usable / pitch + 1e-9).astype(int) + 1
    start = lo + pitch / 2.0 + (usable - (cols - 1) * pitch) / 2.0
    gx = start[0] + np.arange(cols[0]) * pitch
    gy = start[1] + np.arange(cols[1]) * pitch
    G = np.stack(np.meshgrid(gx, gy), -1).reshape(-1, 2)
    if len(G) == 0:
        return np.zeros((0, 3))
    # inside one of the region's triangles
    inside = np.zeros(len(G), bool)
    for i, j, k in T.tolist():
        A, B, C = to2(v[[i, j, k]])
        d = (B[1] - C[1]) * (A[0] - C[0]) + (C[0] - B[0]) * (A[1] - C[1])
        if abs(d) < 1e-18:
            continue
        l1 = ((B[1] - C[1]) * (G[:, 0] - C[0]) + (C[0] - B[0]) * (G[:, 1] - C[1])) / d
        l2 = ((C[1] - A[1]) * (G[:, 0] - C[0]) + (A[0] - C[0]) * (G[:, 1] - C[1])) / d
        inside |= (l1 >= -1e-9) & (l2 >= -1e-9) & (1 - l1 - l2 >= -1e-9)
    G = G[inside]
    if len(G):
        BA = to2(v[[e[0] for e in border]])
        BB = to2(v[[e[1] for e in border]])
        G = G[_seg_dist(G, BA, BB) >= pitch * 0.5 - 1e-9]
    return o + G[:, :1] * u + G[:, 1:] * w


def _fine(v, tris, n, pitch):
    """Every triangle sampled finely (a barycentric lattice about a third of a pitch apart): the
    candidates the thinning picks from. (points, normals)."""
    out, nrm = [], []
    for t, (i, j, k) in enumerate(tris.tolist()):
        a, b, c = v[i], v[j], v[k]
        m = max(1, int(np.ceil(max(np.linalg.norm(b - a), np.linalg.norm(c - a), np.linalg.norm(c - b)) / (pitch / 3.0))))
        s, r = np.meshgrid(np.arange(m + 1), np.arange(m + 1))
        ok = (s + r) <= m
        s, r = s[ok] / m, r[ok] / m
        out.append(a + (b - a) * s[:, None] + (c - a) * r[:, None])
        nrm.append(np.repeat(n[t][None], len(s), 0))
    if not out:
        return np.zeros((0, 3)), np.zeros((0, 3))
    return np.concatenate(out), np.concatenate(nrm)


def surface_leds(mesh, pitch=1.0):
    """LEDs over a mesh's surface about a pitch apart (see the notes above): (pos, normals)."""
    v = np.asarray(mesh.v, np.float64)
    tris = np.asarray([(f[0], f[k], f[k + 1]) for f in mesh.faces for k in range(1, len(f) - 1)], np.int64).reshape(-1, 3)
    if len(tris) == 0:
        return np.zeros((0, 3), np.float32), None
    groups, n, area = _planes(v, tris)
    kept, knrm = [], []
    for g in groups:
        if area[g].sum() >= 2.0 * pitch * pitch:
            P = _region_grid(v, tris, g, n[g[0]], pitch)
            kept += list(P)
            knrm += [n[g[0]]] * len(P)
    # the rest: fine samples thinned against everything kept so far
    r = SURFACE_THIN * pitch
    cell = {}

    def key(p):
        return (int(np.floor(p[0] / r)), int(np.floor(p[1] / r)), int(np.floor(p[2] / r)))

    for p in kept:
        cell.setdefault(key(p), []).append(p)
    C, CN = _fine(v, tris, n, pitch)
    r2 = r * r
    for p, q in zip(C, CN):
        kx, ky, kz = key(p)
        near = False
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for dz in (-1, 0, 1):
                    for o in cell.get((kx + dx, ky + dy, kz + dz), ()):
                        if (o[0] - p[0]) ** 2 + (o[1] - p[1]) ** 2 + (o[2] - p[2]) ** 2 < r2:
                            near = True
                            break
                    if near:
                        break
                if near:
                    break
            if near:
                break
        if not near:
            cell.setdefault((kx, ky, kz), []).append(p)
            kept.append(p); knrm.append(q)
    if not kept:
        return np.zeros((0, 3), np.float32), None
    return np.asarray(kept, np.float32), np.asarray(knrm, np.float32)


def mesh_leds(mesh, mode="edges", pitch=1.0, limit=MESH_MAX):
    """The LEDs a mesh implies: (pos (n, 3), nrm (n, 3) or None). More than
    `limit` of them is TooManyLeds, said before any is placed, with a pitch
    that would do."""
    v = mesh.v
    if len(v) == 0:
        return np.zeros((0, 3), np.float32), None
    pitch = abs(float(pitch)) or 1.0
    if limit:
        n = mesh_estimate(mesh, mode, pitch)
        if n > limit and mode == "vertices":
            raise TooManyLeds(f"{n:,} vertices: one LED each is more than {limit:,} - read it by its edges or its "
                              "surface, with a pitch")
        if n > limit:
            p = mesh_pitch_for(mesh, mode, pitch)
            raise TooManyLeds(f"this would be about {n:,} LEDs; at a pitch of {p:g} it is about "
                              f"{mesh_estimate(mesh, mode, p):,}. Is the file in millimetres?", pitch=p)
    if mode == "vertices":
        return v.copy(), (mesh.vn.copy() if mesh.vn is not None else None)
    if mode == "edges":
        out, seen = [], set()
        for a, b in _chain_edges(mesh.edges, v):
            pa, pb = v[a], v[b]
            L = float(np.linalg.norm(pb - pa))
            n = max(1, int(round(L / pitch)))
            for k in range(n + 1):
                p = pa + (pb - pa) * (k / n)
                key = tuple(np.round(p / (pitch * 0.5)).astype(np.int64))
                if key in seen:
                    continue                          # a corner two edges share, or a loop closing on its start
                seen.add(key); out.append(p)
        return np.asarray(out, np.float32), None
    if mode == "surface":
        return surface_leds(mesh, pitch)
    raise ValueError(f"unknown mesh reading {mode!r}")


# --- xLights models ---------------------------------------------------------------------------
def read_xmodel(path):
    """An xLights custom model: {"name", "w", "h", "d", "points" (n, 3), "order"
    (node numbers 1..), "grid": (w, h, map) for a 2-D model}. Positions: x
    across, z down the rows (as drawn), y the layer."""
    root = ET.parse(path).getroot()
    node = root if root.tag.lower() == "custommodel" else root.find(".//custommodel")
    if node is None:
        kinds = sorted({e.tag for e in root.iter()} - {root.tag})
        raise ValueError(f"not a custom model ({root.tag}: {', '.join(kinds[:6])}) - only xLights custom models are read")
    a = node.attrib
    w, h = int(float(a.get("parm1", 1))), int(float(a.get("parm2", 1)))
    d = int(float(a.get("Depth", a.get("parm3", 1)) or 1))
    data = a.get("CustomModel", "")
    if not data and node.find("CustomModelData") is not None:
        data = node.find("CustomModelData").text or ""
    layers = data.split("|")
    cells = {}                                       # node number -> (x, y, layer)
    for li, layer in enumerate(layers):
        rows = layer.split(";")
        for y, row in enumerate(rows):
            for x, tok in enumerate(row.split(",")):
                tok = tok.strip()
                if tok.isdigit() and int(tok) > 0:
                    cells.setdefault(int(tok), (x, y, li))
    if not cells:
        raise ValueError("the model has no LEDs in its grid")
    order = sorted(cells)
    pts = np.asarray([[cells[k][0], cells[k][2], -cells[k][1]] for k in order], np.float32)
    grid = None
    if len(layers) == 1:
        m = [-1] * (w * h)
        for i, k in enumerate(order):
            x, y, _ = cells[k]
            if 0 <= x < w and 0 <= y < h:
                m[y * w + x] = i
        grid = (w, h, m)
    return {"name": a.get("name", os.path.splitext(os.path.basename(path))[0]), "w": w, "h": h, "d": max(d, len(layers)),
            "points": pts, "order": order, "grid": grid, "source": os.path.basename(path)}


# --- an xLights layout: every model of xlights_rgbeffects.xml as a part -----------------------
def _f(a, key, default=0.0):
    try:
        return float(a.get(key, default) or default)
    except ValueError:
        return default


def _xl_to_studio(x, y, z):
    """xLights' world axes (Y up, Z toward the viewer) to the studio's (Z up, Y away)."""
    return [round(float(x), 3), round(-float(z), 3), round(float(y), 3)]


def _grid_points(cols, rows, sx, sy, serpentine=True, vertical=False):
    """A cols x rows grid, LEDs sx and sy apart, centred; in wiring order."""
    from native import shapes
    ys, xs = np.mgrid[0:rows, 0:cols]
    pos = np.stack([(xs.ravel() - (cols - 1) / 2.0) * sx, np.zeros(cols * rows), ((rows - 1) / 2.0 - ys.ravel()) * sy], 1)
    return pos[shapes._matrix_order(cols, rows, serpentine, vertical)]


def read_layout(path):
    """An xLights layout (xlights_rgbeffects.xml): each model as a part -
    placed by its world position, turned by its rotation, its LEDs sized
    by its scale - and a note per model the reader could only approximate.
    (parts, notes)."""
    from native import shapes
    root = ET.parse(path).getroot()
    models = root.find("models")
    if models is None:
        raise ValueError("no <models> in the file - an xlights_rgbeffects.xml is expected")
    parts, notes = [], []
    for m in models.findall("model"):
        a = m.attrib
        kind = a.get("DisplayAs", "")
        name = a.get("name", kind)
        p1, p2, p3 = int(_f(a, "parm1", 1)), int(_f(a, "parm2", 1)), int(_f(a, "parm3", 1))
        sx, sy, sz = _f(a, "ScaleX", 1.0) or 1.0, _f(a, "ScaleY", 1.0) or 1.0, _f(a, "ScaleZ", 1.0) or 1.0
        pos = _xl_to_studio(_f(a, "WorldPosX"), _f(a, "WorldPosY"), _f(a, "WorldPosZ"))
        rot = [round(_f(a, "RotateX"), 2), round(-_f(a, "RotateZ"), 2), round(_f(a, "RotateY"), 2)]
        serp = a.get("StartSide", "B") in ("B", "T")                       # the strings snake unless told otherwise
        part = None
        if kind == "Custom":
            data = a.get("CustomModel", "")
            if not data and m.find("CustomModelData") is not None:
                data = m.find("CustomModelData").text or ""
            w, h = max(1, p1), max(1, p2)
            cells = {}
            for li, layer in enumerate(data.split("|")):
                for y, row in enumerate(layer.split(";")):
                    for x, tok in enumerate(row.split(",")):
                        tok = tok.strip()
                        if tok.isdigit() and int(tok) > 0:
                            cells.setdefault(int(tok), (x, y, li))
            if cells:
                pts = [[(cells[k][0] - (w - 1) / 2.0) * sx, cells[k][2] * sz, ((h - 1) / 2.0 - cells[k][1]) * sy] for k in sorted(cells)]
                part = shapes.new_part("points", points=[[round(v, 3) for v in q] for q in pts])
        elif kind in ("Horiz Matrix", "Vert Matrix"):
            cols, rows = (p2, p1) if kind == "Horiz Matrix" else (p1, p2)
            pts = _grid_points(cols, rows, sx, sy, serp, kind == "Vert Matrix")
            part = shapes.new_part("points", points=np.round(pts, 3).tolist())
        elif kind == "Single Line":
            n = max(2, p1 * p2)
            end = _xl_to_studio(_f(a, "WorldPosX") + _f(a, "X2"), _f(a, "WorldPosY") + _f(a, "Y2"), _f(a, "WorldPosZ") + _f(a, "Z2"))
            d = np.asarray(end) - np.asarray(pos)
            L = float(np.linalg.norm(d))
            part = shapes.new_part("strip", n=n, pitch=round(L / (n - 1), 4) if L > 0 else 1.0)
            part["rot"] = shapes.aim_rotation((1.0, 0.0, 0.0), d) if L > 0 else [0, 0, 0]
            pos = [round(float(v), 3) for v in (np.asarray(pos) + np.asarray(end)) / 2]; rot = part["rot"]
        elif kind == "Poly Line":
            raw = [float(v) for v in (a.get("PointData", "") or "").replace(";", ",").split(",") if v.strip()]
            pts = [_xl_to_studio(*raw[i:i + 3]) for i in range(0, len(raw) - 2, 3)]
            if len(pts) >= 2:
                n = max(2, p1 * p2)
                total = float(sum(np.linalg.norm(np.asarray(pts[i + 1]) - np.asarray(pts[i])) for i in range(len(pts) - 1)))
                part = shapes.new_part("polyline", points=pts, pitch=round(total / (n - 1) - 1e-6, 5) if total > 0 else 1.0)
                pos, rot = [0.0, 0.0, 0.0], [0.0, 0.0, 0.0]                  # the points are already in the world
        elif kind in ("Circle", "Wreath"):
            n = max(3, p1 * p2)
            part = shapes.new_part("ring", n=n, radius=round(sx * 0.5, 3), pitch=1.0)
            rot = [90.0 + rot[0], rot[1], rot[2]]                            # stood up, facing the viewer
            notes.append(f"{name}: {kind} as one ring")
        elif kind == "Sphere":
            part = shapes.new_part("sphere", w=max(3, p1), h=max(2, p2), pitch=round(sx / max(1, p1) * 3.1416, 3))
            notes.append(f"{name}: sphere sized by its width")
        elif kind == "Cube":
            part = shapes.new_part("cube", B=max(2, p2), pitch=round(sx / max(1, p2), 3), six=True)
            notes.append(f"{name}: cube from its nodes per side")
        elif kind == "Window Frame":
            # the studio's frame part: top and bottom share a count (the top's), the sides theirs, sized to the model
            top, side, bottom = max(1, p1), max(1, p2), max(0, p3)
            pitch = round(sx / top, 5) if sx > 0 else 1.0
            part = shapes.new_part("frame", w=top, h=side, pitch=pitch, bottom=bottom > 0)
            if side * pitch > 0 and sy > 0:
                part["scale"] = [1.0, 1.0, round(sy / (side * pitch), 5)]           # the sides stretched to the model's height
            if bottom and bottom != top:
                notes.append(f"{name}: a window frame's bottom of {bottom} LEDs as the top's {top}")
        elif kind == "Arches":
            # an arch part per arch, side by side as xLights lays them, wired one after another
            arches, per = max(1, p1), max(2, p2)
            each = sx / arches
            for k in range(arches):
                q = shapes.new_part("arch", n=per, span=round(each * 0.9, 4), rise=round(sy if sy > 0 else each * 0.45, 4))
                q["name"] = f"{name} {k + 1}" if arches > 1 else name
                q["pos"] = [round(float(v), 3) for v in np.asarray(pos) + np.asarray([(k - (arches - 1) / 2.0) * each, 0, -sy / 2])]
                q["rot"] = rot
                parts.append(q)
            continue
        elif kind.startswith("Tree"):
            # strings x strands a string, the nodes shared out; turns and the bottom/top ratio if the model has them
            strands = max(1, p1 * max(1, p3))
            per = max(2, p2 // max(1, p3))
            digits = "".join(ch for ch in kind if ch.isdigit())
            deg = float(digits) if digits else 360.0
            ratio = _f(a, "TreeBottomTopRatio", 6.0) or 6.0
            part = shapes.new_part("tree", strands=strands, per_strand=per, height=round(sy, 4) or 30.0,
                                   base=round(sx, 4) or 18.0, top=round((sx or 18.0) / max(1.0, ratio), 4),
                                   turns=round(_f(a, "TreeSpiralRotations", 0.0), 3), degrees=deg, zigzag=True)
            if kind in ("Tree Flat", "Tree Ribbon"):
                notes.append(f"{name}: {kind} as a cone of strands")
        elif kind == "Star":
            points = max(3, p3 if p3 > 1 else 5)
            total = max(points * 2, p1 * p2)
            ratio = _f(a, "starRatio", 2.618) or 2.618
            part = shapes.new_part("star", points=points, per_edge=max(1, total // (2 * points)), radius=round(sx * 0.5, 4),
                                   inner=round(1.0 / ratio, 4))
            rot = [90.0 + rot[0], rot[1], rot[2]]                            # stood up, facing the viewer
        elif kind == "Spinner":
            arms = max(1, p1 * max(1, p3))
            per = max(1, p2)
            part = shapes.new_part("spokes", spokes=arms, per_spoke=per, pitch=round((sx * 0.5) / per, 5) if sx > 0 else 1.0,
                                   inner=0.0, zigzag=True)
            rot = [90.0 + rot[0], rot[1], rot[2]]
            notes.append(f"{name}: spinner as {arms} spokes of {per}")
        if part is None:
            n = max(1, p1 * p2)
            part = shapes.new_part("strip", n=n, pitch=round(sx / max(1, n), 3) if sx > 0 else 1.0)
            notes.append(f"{name}: {kind or 'unknown'} as a strip of {n}")
        part["name"] = name
        part["pos"] = pos; part["rot"] = rot
        parts.append(part)
    if not parts:
        raise ValueError("no models in the layout")
    return parts, notes


def write_xmodel(geom, path, name=None):
    """A geometry as an xLights custom model: its LEDs on a grid (the shape's
    grid layout, or one projected from the front), each cell the LED's
    number in the wiring order, 1-based; empty cells blank."""
    from native import shapes
    g = geom
    if g.kind == "shape" and g.params.get("layout") == "grid":
        w, h = g.w, g.h
        cells = {}
        for led, li in enumerate(np.asarray(g.phys, int)):
            cells[(int(li % w), int(li // w))] = led + 1
    else:
        pos = np.asarray(g.pos, np.float32)
        phys = np.asarray(g.phys, int)
        pts = pos[phys]
        ok = np.isfinite(pts).all(1)
        pts = np.where(ok[:, None], pts, 0)
        # a cell the size of the LED pitch: the typical distance to the nearest neighbour, from a sample
        samp = pts[np.linspace(0, len(pts) - 1, min(len(pts), 300)).astype(int)]
        d = np.linalg.norm(samp[:, None, :] - pts[None, :, :], axis=2)
        d[d <= 1e-6] = np.inf
        cell = float(np.median(d.min(axis=1))) if len(pts) > 1 else 1.0
        w, h, m, _ = shapes.grid_layout(pts, cell if np.isfinite(cell) and cell > 0 else 1.0)
        cells = {(k % w, k // w): led + 1 for k, led in enumerate(m) if led >= 0}
    rows = []
    for y in range(h):
        rows.append(",".join(str(cells.get((x, y), "")) for x in range(w)))
    data = ";".join(rows)
    name = name or os.path.splitext(os.path.basename(path))[0]
    xml = (f'<?xml version="1.0" encoding="UTF-8"?>\n<custommodel name="{name}" parm1="{w}" parm2="{h}" Depth="1" '
           f'StringType="RGB Nodes" Transparency="0" PixelSize="2" ModelBrightness="" Antialias="1" StrandNames="" NodeNames="" '
           f'CustomModel="{data}" SourceVersion="WLED Effects Studio" />\n')
    open(path, "w", encoding="utf-8", newline="\n").write(xml)
    return w, h, len(cells)


# --- point lists ------------------------------------------------------------------------------
def write_points(geom, path):
    """The geometry's LEDs as CSV rows in wiring order - x, y, z, the
    wiring index, the part's index and name - for any other tool; the
    file reads back here as a points part (read_points takes the first
    four columns, the index as the order). Returns the count."""
    import numpy as np
    pos = np.asarray(geom.pos, np.float32).reshape(-1, 3)
    phys = list(np.asarray(geom.phys, int)) if getattr(geom, "phys", None) is not None else list(range(len(pos)))
    parts = (geom.params.get("parts") or []) if geom.kind == "shape" else []
    owner = list(np.asarray(getattr(geom, "owner", []), int)) if geom.kind == "shape" else []
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(f"# {geom.describe()}\n# x, y, z, index (wiring order), part, part name\n")
        n = 0
        for k, li in enumerate(phys):
            x, y, z = pos[li]
            if not np.isfinite([x, y, z]).all():
                continue
            part = int(owner[k]) if k < len(owner) else 0
            name = parts[part].get("name", "") if part < len(parts) else ""
            f.write(f"{x:.4f},{y:.4f},{z:.4f},{k},{part},{name}\n")
            n += 1
    return n


def read_points(path, info=None):
    """x y z [index] rows - CSV, whitespace or a JSON list (of rows or of
    {x, y, z[, i]} objects): (pos (n, 3), order or None). With an index
    column the rows are sorted by it: the wiring order as the other program
    numbered the LEDs. A row without finite numbers (nan, inf) is left out;
    `info`, a dict, gets how many as "skipped"."""
    txt = open(path, encoding="utf-8").read()
    rows = []
    if txt.lstrip().startswith("["):
        for row in json.loads(txt):
            if isinstance(row, dict):
                rows.append([row.get("x", 0), row.get("y", 0), row.get("z", 0)] + ([row["i"]] if "i" in row else []))
            else:
                rows.append(list(row)[:4])
    else:
        for line in txt.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = [v for v in re.split(r"[,;\s]+", line) if v]
            try:
                rows.append([float(v) for v in parts[:4]])
            except ValueError:
                continue
    rows = [r for r in rows if len(r) >= 3]
    if not rows:
        raise ValueError("no x y z rows found")
    good, skipped = [], 0
    for r in rows:
        try:
            v = [float(x) for x in r[:4]]
        except (TypeError, ValueError, OverflowError):
            v = [math.nan]
        if len(v) >= 3 and all(math.isfinite(x) for x in v):
            good.append(v)
        else:
            skipped += 1
    if info is not None:
        info["skipped"] = skipped
    if not good:
        raise ValueError(f"no x y z rows with numbers found ({skipped} without)")
    rows = good
    pts = np.asarray([r[:3] for r in rows], np.float32)
    idx = [r[3] for r in rows if len(r) >= 4]
    order = None
    if len(idx) == len(rows):
        order = np.argsort(np.asarray(idx))
        pts = pts[order]
    return pts, order
