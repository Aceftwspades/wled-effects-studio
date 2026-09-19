"""
Geometry: what the LEDs are, where they are, and how an effect sees them.

WLED has no idea of 3-D. An effect sees a 1-D segment or a 2-D matrix, and a
ledmap turns logical pixels into physical ones. So every shape here is a
LOGICAL segment - n, or w x h - plus a position in space for every logical
pixel and a lit mask for the ones that exist. The renderer draws whatever
positions it is handed; the effect code never knows the difference between a
matrix, a cylinder and a sphere, which is exactly how it is on the device.

Kinds:

  strip      n LEDs in a line (or a ring, when `ring` is set)
  matrix     w x h, with WLED's own 2-D options - serpentine, vertical,
             start corner - which affect only the PHYSICAL order (the ledmap),
             never what the effect sees
  cube       the five-face net this project was built for: 3B x 3B logical
             with the four corner blocks unlit, positions on a cube's faces;
             `six` lights the bottom face too, in the (2,2) corner block
  cylinder   w round, h tall - a matrix rolled into a tube, seamless in x
  sphere     w round, h latitude rows - a matrix wrapped onto a globe
  torus      w round the ring, h round the tube
  xyz        a coordinate list from a file: one logical row of n, positions
             as given, physical order as given
  shape      built from parts (native/shapes.py): strips, rings, panels,
             cylinders, spheres, cubes, a strip along a path, loose points -
             placed, turned and scaled - or read from a mesh or an xLights
             model; the parts' order is the wiring. Logically a strip of n
             (`layout` "strip") or a w x h grid the LEDs are projected onto
             ("grid", or the grid an xLights model came with)

A Geometry is plain data; to_json()/from_json() round-trip it for the project
file. The engine only ever hears (w, h) via simInit; positions are for the
renderer and the ledmap export.
"""
import json
import math
import os

import numpy as np

KINDS = ("strip", "matrix", "cube", "cylinder", "sphere", "torus", "xyz", "shape")


class Geometry:
    def __init__(self, kind="cube", **params):
        if kind not in KINDS:
            raise ValueError(f"unknown geometry kind {kind!r}")
        self.kind = kind
        self.params = dict(params)
        self.w = 1           # logical width
        self.h = 1           # logical height (1 = a 1-D segment)
        self.lit = None      # (h*w,) bool, which logical pixels exist
        self.pos = None      # (h*w, 3) float, positions; NaN where unlit
        self.nrm = None      # (h*w, 3) float, outward unit normals, or None (the direction from the centre then)
        self.phys = None     # (n_lit,) logical indices in PHYSICAL (wiring) order
        self._build()
        if self.params.get("map") is not None and self.kind in ("strip", "matrix"):
            self._apply_map()

    def _apply_map(self):
        """A device's ledmap, WLED's way round: map[logical] = physical, -1
        for a logical position with no LED. Unlit positions leave the
        picture; the wiring order is the map's."""
        m = [int(v) for v in self.params["map"]][:self.w * self.h]
        m += [-1] * (self.w * self.h - len(m))
        arr = np.asarray(m)
        self.lit = arr >= 0
        logical = np.nonzero(self.lit)[0]
        order = np.argsort(arr[logical], kind="stable")
        self.phys = logical[order]
        self.phys_ids = arr[logical][order]          # the device's own numbering, gaps and all

    @classmethod
    def from_ledmap(cls, d, source="ledmap"):
        """A WLED ledmap.json (with width and height for a matrix)."""
        m = d.get("map") or []
        w, h = int(d.get("width") or 0), int(d.get("height") or 0)
        if w > 0 and h > 0:
            return cls("matrix", w=w, h=h, map=list(m), source=source)
        return cls("strip", n=len(m), map=list(m), source=source)

    # --- construction -------------------------------------------------------
    # what the engine can hold and the views can show; a project.json edited
    # by hand, or an old one, is clamped here rather than trusted
    MAX_PIXELS = 256 * 256
    LIMITS = {"n": (1, 2000), "w": (1, 256), "h": (1, 256), "B": (1, 85)}

    def _clamp(self, key, default, lo=None):
        a, b = self.LIMITS[key]
        if lo is not None:
            a = max(a, lo)
        try:
            v = int(self.params.get(key, default))
        except (TypeError, ValueError):
            v = default
        v = min(b, max(a, v))
        self.params[key] = v
        return v

    def _build(self):
        p = self.params
        k = self.kind
        if k == "strip":
            n = self._clamp("n", 60)
            self.w, self.h = n, 1
            t = np.arange(n, dtype=np.float32)
            if p.get("ring"):
                a = t * (2 * math.pi / n)
                r = n / (2 * math.pi) * 0.5
                self.pos = np.stack([np.cos(a) * r, np.sin(a) * r, np.zeros(n)], 1).astype(np.float32)
            else:
                self.pos = (np.stack([t - (n - 1) / 2.0, np.zeros(n), np.zeros(n)], 1) * 0.5).astype(np.float32)
            self.lit = np.ones(n, bool)
            self.phys = np.arange(n)
        elif k == "matrix":
            w, h = self._clamp("w", 16), self._clamp("h", 16)
            self.w, self.h = w, h
            ys, xs = np.mgrid[0:h, 0:w]
            # a panel stood upright in the X-Z plane, facing -Y (the camera side)
            self.pos = np.stack([xs.ravel() - (w - 1) / 2.0, np.zeros(w * h),
                                 (h - 1) / 2.0 - ys.ravel()], 1).astype(np.float32) * 0.5
            self.lit = np.ones(w * h, bool)
            self.phys = self._matrix_order(w, h, p)
        elif k == "cube":
            B = self._clamp("B", 16)
            self.w = self.h = 3 * B
            pos, lit = _cube_net(B, bool(p.get("six")))
            self.pos, self.lit = pos, lit
            if p.get("faces"):
                self.phys = self._cube_order(B, p)
            else:
                self.phys = np.nonzero(lit)[0]  # the net's raster order, as before any wiring was set
        elif k == "cylinder":
            w, h = self._clamp("w", 32, lo=3), self._clamp("h", 16)
            self.w, self.h = w, h
            ys, xs = np.mgrid[0:h, 0:w]
            a = xs.ravel() * (2 * math.pi / w)
            r = w / (2 * math.pi) * 0.5
            self.pos = np.stack([np.cos(a) * r, np.sin(a) * r, ((h - 1) / 2.0 - ys.ravel()) * 0.5], 1).astype(np.float32)
            self.nrm = np.stack([np.cos(a), np.sin(a), np.zeros(w * h)], 1).astype(np.float32)
            self.lit = np.ones(w * h, bool)
            self.phys = self._matrix_order(w, h, p)
        elif k == "sphere":
            w, h = self._clamp("w", 32, lo=3), self._clamp("h", 16, lo=2)
            self.w, self.h = w, h
            ys, xs = np.mgrid[0:h, 0:w]
            a = xs.ravel() * (2 * math.pi / w)
            # latitude rows from near the north pole to near the south, so the
            # top row is a small ring, not a point every effect would waste
            lat = (ys.ravel() + 0.5) / h * math.pi - math.pi / 2
            R = w / (2 * math.pi) * 0.5
            self.pos = np.stack([np.cos(lat) * np.cos(a) * R, np.cos(lat) * np.sin(a) * R,
                                 -np.sin(lat) * R], 1).astype(np.float32)
            self.nrm = self.pos / R
            self.lit = np.ones(w * h, bool)
            self.phys = self._matrix_order(w, h, p)
        elif k == "torus":
            w, h = self._clamp("w", 40, lo=3), self._clamp("h", 12, lo=3)
            self.w, self.h = w, h
            ys, xs = np.mgrid[0:h, 0:w]
            u = xs.ravel() * (2 * math.pi / w)
            v = ys.ravel() * (2 * math.pi / h)
            R = w / (2 * math.pi) * 0.5
            r = h / (2 * math.pi) * 0.5
            self.pos = np.stack([(R + r * np.cos(v)) * np.cos(u), (R + r * np.cos(v)) * np.sin(u),
                                 r * np.sin(v)], 1).astype(np.float32)
            self.nrm = np.stack([np.cos(v) * np.cos(u), np.cos(v) * np.sin(u), np.sin(v)], 1).astype(np.float32)
            self.lit = np.ones(w * h, bool)
            self.phys = self._matrix_order(w, h, p)
        elif k == "shape":
            from native import shapes
            pos, nrm, owner = shapes.resolve(p.get("parts") or [])
            pos, nrm = pos[:self.MAX_PIXELS], nrm[:self.MAX_PIXELS] if nrm is not None else None
            n = len(pos)
            if n == 0:
                pos = np.zeros((1, 3), np.float32); nrm = None; n = 1
            self.owner = owner[:n]
            self.collisions = 0
            grid = p.get("grid") if p.get("layout") == "grid" else None
            if p.get("layout") == "grid" and not grid:
                w, h, m, self.collisions = shapes.grid_layout(pos, float(p.get("cell", 1.0)) or 1.0)
                grid = (w, h, m)
            if grid:
                w, h, m = int(grid[0]), int(grid[1]), [int(v) for v in grid[2]]
                m = (m + [-1] * (w * h))[:w * h]
                self.w, self.h = w, h
                self.pos = np.full((w * h, 3), np.nan, np.float32)
                self.nrm = np.zeros((w * h, 3), np.float32) if nrm is not None else None
                self.lit = np.zeros(w * h, bool)
                order = []
                for li, led in enumerate(m):
                    if 0 <= led < n:
                        self.pos[li] = pos[led]; self.lit[li] = True; order.append((led, li))
                        if nrm is not None:
                            self.nrm[li] = nrm[led]
                self.phys = np.asarray([li for _, li in sorted(order)], int)
            else:
                self.w, self.h = n, 1
                self.pos, self.nrm = pos, nrm
                self.lit = np.ones(n, bool)
                self.phys = np.arange(n)
        elif k == "xyz":
            pts = np.asarray(p.get("points", []), dtype=np.float32).reshape(-1, 3)
            pts = pts[~np.isnan(pts).any(1)][:self.MAX_PIXELS]      # a bad row is dropped, not drawn at NaN
            n = len(pts)
            if n == 0:
                pts = np.zeros((1, 3), np.float32); n = 1
            self.w, self.h = n, 1
            c = pts.mean(0)
            span = float(np.abs(pts - c).max()) or 1.0
            self.pos = (pts - c) / span * (n ** 0.5) * 0.5
            self.lit = np.ones(n, bool)
            self.phys = np.arange(n)

    @staticmethod
    def _matrix_order(w, h, p):
        """Physical (wiring) order of logical pixels, from WLED's 2-D panel
        options: serpentine, vertical, and the start corner."""
        serp = bool(p.get("serpentine", True))
        vert = bool(p.get("vertical", False))
        right = bool(p.get("start_right", False))
        bottom = bool(p.get("start_bottom", False))
        out = []
        if not vert:
            for y in range(h):
                yy = h - 1 - y if bottom else y
                xs = list(range(w))
                if right: xs.reverse()
                if serp and (y % 2 == 1): xs.reverse()
                out += [yy * w + x for x in xs]
        else:
            for x in range(w):
                xx = w - 1 - x if right else x
                ys = list(range(h))
                if bottom: ys.reverse()
                if serp and (x % 2 == 1): ys.reverse()
                out += [y * w + xx for y in ys]
        return np.asarray(out)

    FACES = {"N": (1, 0), "W": (0, 1), "T": (1, 1), "E": (2, 1), "S": (1, 2), "B": (2, 2)}

    @classmethod
    def _cube_order(cls, B, p):
        """The cube's wiring: the faces in the order given (N W T E S as the
        net shows them, and B for the bottom of a six-faced cube), each
        turned by quarter turns and walked as WLED's panel options say
        (serpentine, vertical, start corner)."""
        names = cls.FACES
        have = "NWTESB" if p.get("six") else "NWTES"
        order, seen = [], set()
        for f in str(p.get("faces", "")).upper().replace(" ", "").split(","):
            if f in have and f not in seen:
                order.append(f); seen.add(f)
        order += [f for f in have if f not in seen]
        rots = []
        for r in str(p.get("rots", "")).split(","):
            r = r.strip()
            rots.append(int(r) % 4 if r.lstrip("-").isdigit() else 0)
        rots += [0] * (len(have) - len(rots))
        n = 3 * B
        walk = cls._matrix_order(B, B, p)
        grid = np.stack(np.mgrid[0:B, 0:B], axis=-1)           # (y, x) of each local pixel
        out = []
        for f, r in zip(order, rots):
            bx, by = names[f]
            rv = np.rot90(grid, -r)                              # the face turned r quarter turns
            for k in walk:
                oy, ox = rv[k // B, k % B]
                out.append((by * B + int(oy)) * n + bx * B + int(ox))
        return np.asarray(out)

    # --- queries --------------------------------------------------------------
    # The shape as the firmware's table (cube_fx_00_geometry.cpp): a position
    # for every logical pixel in the -1..1 box, int8, and the normals when
    # the shape knows them. A cube net and a flat matrix have a rule of their
    # own in cfx_pos(), so they send none (and would move their axes if they
    # did: a matrix's effects live in the X-Y plane there).
    HAS_RULE = ("cube", "matrix", "strip")

    def table(self):
        """The `/geometry.bin` bytes, or None for a kind cfx_pos() already knows."""
        if self.kind in self.HAS_RULE:
            return None
        pos = np.asarray(self.pos, np.float32).reshape(-1, 3).copy()
        lit = np.asarray(self.lit, bool)
        if not lit.any():
            return None
        c = (np.nanmin(pos[lit], 0) + np.nanmax(pos[lit], 0)) * 0.5
        span = float(np.nanmax(np.abs(pos[lit] - c))) or 1.0
        q = np.clip(np.round((pos - c) / span * 127.0), -127, 127)
        q[~np.isfinite(q)] = 0
        q[~lit] = 0
        nrm = None
        if self.nrm is not None:
            nrm = np.clip(np.round(np.asarray(self.nrm, np.float32).reshape(-1, 3) * 127.0), -127, 127)
            nrm[~np.isfinite(nrm)] = 0
        parts = None
        if self.kind == "shape" and getattr(self, "owner", None) is not None and len(self.owner):
            # part id and the place along the part, per logical pixel (0 where unlit)
            owner = np.asarray(self.owner, int)
            along = np.zeros(len(owner), np.float32)
            for k in np.unique(owner):
                idx = np.nonzero(owner == k)[0]
                along[idx] = np.linspace(0.0, 1.0, len(idx)) if len(idx) > 1 else 0.0
            parts = np.zeros((self.w * self.h, 2), np.uint8)
            phys = np.asarray(self.phys, int)
            for led, li in enumerate(phys):
                if led < len(owner) and 0 <= li < len(parts):
                    parts[li] = (min(255, int(owner[led])), int(round(along[led] * 255)))
        import struct
        flags = (1 if nrm is not None else 0) | (2 if parts is not None else 0)
        head = b"STGM" + struct.pack("<BHHH", 1, self.w, self.h, flags)
        out = head + q.astype(np.int8).tobytes()
        if nrm is not None:
            out += nrm.astype(np.int8).tobytes()
        if parts is not None:
            out += parts.tobytes()
        return out

    @property
    def is2d(self):
        return self.h > 1

    @property
    def count(self):
        return int(self.lit.sum())

    def ledmap(self):
        """WLED's ledmap.json, the way the firmware reads it (FX_fcn.cpp,
        deserializeMap): one entry per LOGICAL position of the segment, in
        segment order, giving the PHYSICAL LED there, -1 where there is none
        - the cube's corner gaps. So a 48x48 cube is 2304 entries, 1280 of
        them LEDs. `phys` here is the inverse (logical indices in wiring
        order), which was what used to be written, and which the device
        would have read backwards."""
        n = self.w * self.h
        m = [-1] * n
        ids = getattr(self, "phys_ids", None)
        for k, logical in enumerate(self.phys):
            if 0 <= int(logical) < n:
                m[int(logical)] = int(ids[k]) if ids is not None else k
        out = {"map": m}
        if self.h > 1:
            out["width"], out["height"] = int(self.w), int(self.h)
        return out

    def describe(self):
        k, p = self.kind, self.params
        if k == "strip":    return f"strip, {self.w} LEDs" + (" (ring)" if p.get("ring") else "")
        if k == "matrix":   return f"matrix {self.w}x{self.h}"
        if k == "cube":     return f"cube, {p.get('B', 16)} px faces, {'six' if p.get('six') else 'five'} ({self.count} LEDs)"
        if k == "cylinder": return f"cylinder {self.w} round x {self.h}"
        if k == "sphere":   return f"sphere {self.w} round x {self.h} rows"
        if k == "torus":    return f"torus {self.w} x {self.h}"
        if k == "shape":
            parts = p.get("parts") or []
            lay = f", on a {self.w}x{self.h} grid" if p.get("layout") == "grid" else ""
            hit = f" ({self.collisions} LEDs share a cell: not addressed)" if getattr(self, "collisions", 0) else ""
            return f"shape of {len(parts)} part(s), {self.count} LEDs{lay}{hit}"
        return f"{self.w} points from file"

    # --- persistence --------------------------------------------------------------
    def to_json(self):
        p = dict(self.params)
        if "points" in p:
            p["points"] = [[float(v) for v in row] for row in p["points"]]
        return {"kind": self.kind, "params": p}

    @classmethod
    def from_json(cls, d):
        return cls(d.get("kind", "cube"), **d.get("params", {}))

    @classmethod
    def from_xyz_file(cls, path):
        """CSV / whitespace / JSON list of x y z rows."""
        pts = []
        txt = open(path, encoding="utf-8").read()
        if txt.lstrip().startswith("["):
            for row in json.loads(txt):
                if isinstance(row, dict):
                    pts.append([row.get("x", 0), row.get("y", 0), row.get("z", 0)])
                else:
                    pts.append(list(row)[:3])
        else:
            for line in txt.splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = [v for v in line.replace(",", " ").split() if v]
                try:
                    pts.append([float(v) for v in parts[:3]])
                except ValueError:
                    continue
        return cls("xyz", points=pts, source=os.path.basename(path))


def _cube_net(B, six=False):
    """Positions on the cube's faces for the 3B x 3B net, from the same face
    lines cfx_pos uses (cube_fx_common.h). Unlit where the net has no face;
    with `six` the (2,2) corner block is the bottom face."""
    n = 3 * B
    pos = np.full((n * n, 3), np.nan, np.float32)
    lit = np.zeros(n * n, bool)
    half = B / 2.0
    for y in range(n):
        for x in range(n):
            bx, by = x // B, y // B
            a = 2.0 * ((x % B) + 0.5) / B - 1.0
            b = 2.0 * ((y % B) + 0.5) / B - 1.0
            if   bx == 1 and by == 1: X, Y, Z = a, -b, 1.0        # TOP
            elif bx == 1 and by == 0: X, Y, Z = a, 1.0, b         # NORTH
            elif bx == 1 and by == 2: X, Y, Z = a, -1.0, -b       # SOUTH
            elif bx == 0 and by == 1: X, Y, Z = -1.0, -b, a       # WEST
            elif bx == 2 and by == 1: X, Y, Z = 1.0, -b, -a       # EAST
            elif six and bx == 2 and by == 2: X, Y, Z = a, -b, -1.0   # BOTTOM
            else:
                continue
            i = y * n + x
            pos[i] = (X * half, Y * half, Z * half)   # Z up, as render.py's camera
            lit[i] = True
    return pos, lit
