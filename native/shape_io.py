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


def mesh_leds(mesh, mode="edges", pitch=1.0):
    """The LEDs a mesh implies: (pos (n, 3), nrm (n, 3) or None)."""
    v = mesh.v
    if len(v) == 0:
        return np.zeros((0, 3), np.float32), None
    pitch = float(pitch) or 1.0
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
        out, nrm = [], []
        for f in mesh.faces:
            for k in range(1, len(f) - 1):            # a polygon as a fan of triangles
                a, b, c = v[f[0]], v[f[k]], v[f[k + 1]]
                n = np.cross(b - a, c - a); L = np.linalg.norm(n)
                if L < 1e-9:
                    continue
                n = n / L
                lab, lac = np.linalg.norm(b - a), np.linalg.norm(c - a)
                na, nc = max(1, int(lab / pitch)), max(1, int(lac / pitch))
                for i in range(na + 1):
                    for j in range(nc + 1):
                        s, t = i / na, j / nc
                        if s + t <= 1.0 + 1e-6:
                            out.append(a + (b - a) * s + (c - a) * t); nrm.append(n)
        pos = np.asarray(out, np.float32).reshape(-1, 3)
        # sampling a fan doubles points on shared edges: the closer of any pair goes
        keep = np.ones(len(pos), bool)
        if len(pos) > 1:
            q = np.round(pos / (pitch * 0.5)).astype(np.int64)
            seen = set()
            for i, key in enumerate(map(tuple, q)):
                if key in seen:
                    keep[i] = False
                else:
                    seen.add(key)
        return pos[keep], np.asarray(nrm, np.float32)[keep] if nrm else None
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
        lit = np.asarray(g.lit, bool)
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
def read_points(path):
    """x y z [index] rows - CSV, whitespace or a JSON list (of rows or of
    {x, y, z[, i]} objects): (pos (n, 3), order or None). With an index
    column the rows are sorted by it: the wiring order as the other program
    numbered the LEDs."""
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
    pts = np.asarray([r[:3] for r in rows], np.float32)
    idx = [r[3] for r in rows if len(r) >= 4]
    order = None
    if len(idx) == len(rows):
        order = np.argsort(np.asarray(idx))
        pts = pts[order]
    return pts, order
