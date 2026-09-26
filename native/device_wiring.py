"""A device's wiring as WLED itself uses it - read (GET only: nothing on the
device changes) and laid over whatever geometry the studio has - and the
order a stream to it must be in.

What WLED does with its LEDs' order (wled00/FX.h getMappedPixelIndex, and
FX_2Dfcn.cpp setUpMatrix): every pixel an effect draws has a LOGICAL index
- a place on the segment, y * width + x on a matrix - and a table maps it
to the PHYSICAL LED, the wiring. The table is the device's ledmap.json
when it has one; else the matrix its 2-D setup describes (panels, their
start corners, rows or columns, serpentine, a gaps file); else the LEDs in
order, a strip.

Realtime data - the studio's stream over DDP - lands on the same logical
indices, and goes through the same table while the device's Sync settings
say "Respect LED maps" (cfg if.live.rlm, on by default): so a stream must
be in LOGICAL order, the frame as the effect draws it. Only with that
switched off does WLED take the pixels in wiring order. The studio sent
wiring order always, and a device with a map - the cube - showed it
scrambled: the map applied twice.

    info = device_wiring.read(host)          # {"panels", "gaps", "ledmap", "total", "rlm", "mso"}
    w, h, table, source = device_wiring.table(info)
    geom, words = device_wiring.apply(geometry, info, host)   # the geometry with the device's wiring (ValueError: cannot)
    device_wiring.stream_order(info)         # "logical" or "wiring"
    device_wiring.cube_params(table, B)      # a cube's face order, turns and switches, from a table (or None)
"""
import itertools
import json
import urllib.error
import urllib.request

import numpy as np

from native import matrix2d
from native.geometry import Geometry


def _get(host, path, timeout):
    """A path's JSON from the device, or None when it has no such file (404)."""
    try:
        with urllib.request.urlopen(f"http://{host}{path}", timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise


def read(host, timeout=6.0):
    """Everything that says the device's wiring, and how it takes a stream."""
    cfg = _get(host, "/json/cfg", timeout) or {}
    panels = matrix2d.panels_of(cfg)
    gaps = None
    if panels:
        g = _get(host, "/2d-gaps.json", timeout)
        gaps = [int(v) for v in g] if isinstance(g, list) else None
    lm = _get(host, "/ledmap.json", timeout)
    ledmap = lm if isinstance(lm, dict) and isinstance(lm.get("map"), list) and lm["map"] else None
    live = (cfg.get("if") or {}).get("live") or {}
    total = int((((cfg.get("hw") or {}).get("led") or {}).get("total")) or 0)
    return {"panels": panels, "gaps": gaps, "ledmap": ledmap, "total": total,
            "rlm": bool(live.get("rlm", True)), "mso": bool(live.get("mso", False))}


def table(info):
    """(width, height, table, source): table[logical] = the physical LED, -1
    for none - the device's ledmap, else its 2-D setup, else a strip."""
    lm = info.get("ledmap")
    if lm:
        m = [int(v) for v in lm["map"]]
        w, h = int(lm.get("width") or 0), int(lm.get("height") or 0)
        if not (w > 0 and h > 0) and info.get("panels"):
            w = max(p["x"] + p["w"] for p in info["panels"])
            h = max(p["y"] + p["h"] for p in info["panels"])
        if not (w > 0 and h > 0 and w * h <= len(m) + w):
            w, h = len(m), 1
        m = (m + [-1] * (w * h))[:w * h]
        return w, h, m, "its ledmap"
    if info.get("panels"):
        w, h, m = matrix2d.layout(info["panels"], info.get("gaps"))
        return w, h, m, "its 2-D setup" + (" and gaps file" if info.get("gaps") is not None else "")
    n = max(1, int(info.get("total") or 0))
    return n, 1, list(range(n)), "its LEDs in order"


def stream_order(info):
    """What a stream to the device must be in: "logical" (it maps the pixels
    with its own table - Respect LED maps, WLED's default) or "wiring"."""
    return "logical" if (info is None or info.get("rlm", True) or info.get("mso")) else "wiring"


# --- a cube's wiring, from a table --------------------------------------------------------------
def cube_params(tab, B):
    """The cube's own wiring settings - face order, each face's quarter
    turns, serpentine, vertical, the start corner - that make exactly this
    table (logical -> physical over the 3B x 3B net), or None when no
    setting does (the faces not one after another, a face walked its own
    way): then the table itself is kept."""
    n = 3 * B
    t = np.asarray(tab, int)
    if len(t) != n * n:
        return None
    six = bool((t.reshape(n, n)[2 * B:, 2 * B:] >= 0).any())
    have = "NWTESB" if six else "NWTES"
    per = B * B
    cells, first = {}, {}
    for f in have:
        bx, by = Geometry.FACES[f]
        ys, xs = np.mgrid[by * B:(by + 1) * B, bx * B:(bx + 1) * B]
        idx = (ys * n + xs).ravel()
        ids = t[idx]
        if (ids < 0).any():
            return None
        k = int(ids.min())
        if k % per or sorted(ids.tolist()) != list(range(k, k + per)):
            return None                                   # the face's LEDs not one run of its own
        cells[f], first[f] = idx, k
    order = sorted(have, key=lambda f: first[f])
    if [first[f] for f in order] != [i * per for i in range(len(order))]:
        return None
    grid = np.stack(np.mgrid[0:B, 0:B], axis=-1)
    # the plainest reading first: rows before columns, serpentine, from the top left
    for vert, serp, bottom, right in itertools.product((False, True), (True, False), (False, True), (False, True)):
        flags = {"serpentine": serp, "vertical": vert, "start_right": right, "start_bottom": bottom}
        walk = Geometry._matrix_order(B, B, flags)
        rots = {}
        for f in order:
            bx, by = Geometry.FACES[f]
            want = t[cells[f]]
            for r in range(4):
                rv = np.rot90(grid, -r)
                got = np.full(n * n, -1)
                for i, k in enumerate(walk):
                    oy, ox = rv[k // B, k % B]
                    got[(by * B + int(oy)) * n + bx * B + int(ox)] = first[f] + i
                if (got[cells[f]] == want).all():
                    rots[f] = r
                    break
            else:
                break
        if len(rots) == len(order):
            p = dict(flags, B=B, six=six, faces=",".join(order), rots=",".join(str(rots[f]) for f in order))
            check = Geometry("cube", **p).ledmap()["map"]
            if [int(v) for v in check] == [int(v) for v in t]:
                return p
    return None


# --- over the studio's geometry ------------------------------------------------------------------
def apply(geom, info, host="the device"):
    """The geometry the studio has, wired as the device is: (a new Geometry,
    words). The kind stays; a cube takes the device's face size if it
    differs. ValueError when the device's layout cannot be this kind's."""
    w, h, tab, source = table(info)
    src = f"{host}, {source}"
    k = geom.kind
    if k == "matrix":
        if info.get("ledmap") is None and info.get("panels"):
            params, words = matrix2d.geometry_params(info["panels"], info.get("gaps"), src)
            return Geometry("matrix", **params), words
        if h < 2:
            raise ValueError("its LEDs are a strip (no 2-D setup and no 2-D ledmap): choose strip, or set up its 2-D matrix")
        return Geometry("matrix", w=w, h=h, map=tab, source=src), f"{w} x {h} from {source}"
    if k == "cube":
        if h < 2 or w != h or w % 3:
            raise ValueError(f"it lays its LEDs out {w} x {h}; a cube's net is square, three faces across (3B x 3B)")
        B = w // 3
        p = cube_params(tab, B)
        note = "" if B == int(geom.params.get("B", 16)) else f" (faces {B} x {B}, as the device has them)"
        if p is not None:
            return (Geometry("cube", **p),
                    f"faces {p['faces'].replace(',', ' ')}, turned {p['rots'].replace(',', ' ')}, "
                    + ("serpentine" if p["serpentine"] else "not serpentine") + (", columns" if p["vertical"] else ", rows")
                    + " from the " + ("bottom" if p["start_bottom"] else "top") + " " + ("right" if p["start_right"] else "left")
                    + note)
        six = bool((np.asarray(tab).reshape(w, w)[2 * B:, 2 * B:] >= 0).any())
        return (Geometry("cube", B=B, six=six, map=tab, source=src),
                f"the device's own map (its faces not wired as the cube's settings can say){note}")
    if k == "strip":
        if h > 1:
            raise ValueError(f"it lays its LEDs out {w} x {h}: choose matrix or cube first")
        if tab == list(range(len(tab))):
            return Geometry("strip", n=len(tab), ring=bool(geom.params.get("ring"))), f"{len(tab)} LEDs in order"
        return Geometry("strip", n=len(tab), map=tab, source=src, ring=bool(geom.params.get("ring"))), f"{len(tab)} LEDs from {source}"
    if k in ("cylinder", "sphere", "torus"):
        if (w, h) != (geom.w, geom.h):
            raise ValueError(f"it lays its LEDs out {w} x {h}; this {k} is {geom.w} x {geom.h} - set it to the same size first")
        return Geometry(k, **dict(geom.params, map=tab, source=src)), f"{w} x {h} from {source}"
    if k == "shape":
        raise ValueError("a shape's wiring is its parts' order - Send the shape gives the device this one")
    raise ValueError("points from a file keep the file's own order")
