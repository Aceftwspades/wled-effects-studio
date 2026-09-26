"""Building a shape with the pointer, in the 3-D view (the Shape frame open):

- **Pick**: a click selects the part under the pointer (on nothing: none);
  Shift-click adds it or takes it away; Shift-drag draws a box, and every
  part with an LED in it joins the selection.
- **Handles** on the selection: arrows (X red, Y green, Z blue) move it
  along an axis, the squares between two arrows in their plane, the ring
  in the middle in the plane of the screen; in turn mode rings turn it
  about each axis. A move snaps its place to a ruler step that follows the
  zoom, a turn to 15 degrees; Ctrl held, neither.
- **Blender's keys** over the view: G moves, R turns, S scales - then X, Y
  or Z locks the axis (again: free), a typed number is exact (in the
  shape's unit, degrees, or a factor), Enter or a click keeps it, Esc or a
  right-click puts it back.
- **Snap to join**: one part moved so its first LED comes near another
  part's end lands one LED spacing beyond that end, and goes after it in
  the wiring (its last LED near a first: before it).
- **A part's menu**: a right-click on it - duplicate and move, a mirrored
  copy, reverse, move in the wiring, frame, rename, hide, lock, light it,
  delete.

    shape_tools.press(app)             # left press on the view: True when a handle, a box or a modal move took it
    shape_tools.drag(app)              # the pointer moving with the button down: True when taken
    shape_tools.release(app)           # the button up
    shape_tools.right(app)             # right press on the view: True when taken (a modal cancelled, a part's menu)
    shape_tools.key(app, code)         # a key while a modal move runs: True when taken
    shape_tools.start(app, mode)       # G, R, S: "move", "turn", "scale"
    shape_tools.poll(app)              # per frame: a modal move follows the pointer
    shape_tools.draw(app, v, parent)   # the handles, the box, the join, the readout (shape_view.poll calls it)
"""
import copy
import json
import math

import numpy as np
import dearpygui.dearpygui as dpg

from native import shapes, units, view3d, typeface
from native.typeface import px

AXIS_COL = {0: (232, 86, 86), 1: (118, 200, 92), 2: (86, 146, 240)}
AXIS_NAME = "XYZ"
ARROW = 76            # an arrow's length on the screen, px (less as it points at the eye)
PLANE_AT = 24         # a plane square's corner from the middle, px, along its two arrows
PLANE_SIZE = 12
CENTRE = 9
RING = 62             # the turn rings' radius on the screen, px
GRAB = 7              # how near the pointer must be to take a handle, px
JOIN_PX = 16          # how near an end must come to join, px
CLICK = 4             # a press that moves less than this is a click, px
TURN_STEP = 15.0      # degrees


def _ui():
    from native import shape_ui
    return shape_ui


def _sv():
    from native import shape_view
    return shape_view


def _run():
    from native import shape_run
    return shape_run


def _parts(app):
    return _ui()._parts(app) or []


TEST_MODS = set()      # the test hooks' stand-in for held modifier keys ("shift", "ctrl")


def _ctrl():
    return "ctrl" in TEST_MODS or dpg.is_key_down(dpg.mvKey_LControl) or dpg.is_key_down(dpg.mvKey_RControl)


def _shift():
    return "shift" in TEST_MODS or dpg.is_key_down(dpg.mvKey_LShift) or dpg.is_key_down(dpg.mvKey_RShift)


def pickable(part):
    return not part.get("hidden") and not part.get("locked")


def movable(app):
    """The selected parts a handle or a key moves: the locked ones stay."""
    parts = _parts(app)
    return sorted(i for i in _ui().selection(app) if 0 <= i < len(parts) and not parts[i].get("locked"))


def pivot(parts, idxs):
    """What the selection turns and scales about: the middle of its parts' places."""
    if not idxs:
        return np.zeros(3)
    return np.mean([np.asarray(parts[i].get("pos", [0, 0, 0]), np.float64) for i in idxs], axis=0)


# --- the view's numbers: a point on the screen, the screen way of an axis -------------------------
def _screen(v, p):
    sx, sy, ok, depth = _sv().project(v, np.asarray(p, np.float64).reshape(-1, 3))
    return np.array([sx[0], sy[0]]), bool(ok[0]), float(depth[0])


def _px_per_unit(v, depth):
    """Screen pixels a unit of the shape measures at this depth."""
    return float(v.cam.scale(np.asarray([depth]))[0]) / v.frame[1]


def _axis_screen(v, p0, a):
    """(unit screen direction, pixels a unit along world axis a) at p0."""
    s0, ok0, d0 = _screen(v, p0)
    e = np.zeros(3); e[a] = 1.0
    eps = 0.05 * v.frame[1]
    s1, ok1, _ = _screen(v, np.asarray(p0) + e * eps)
    d = s1 - s0
    L = float(np.linalg.norm(d))
    if not (ok0 and ok1) or L < 1e-6:
        return None, 0.0
    return d / L, L / eps


def _plane_hit(v, mx, my, point, normal):
    """Where the ray under a screen point meets the plane through `point` with `normal` (the shape's units)."""
    o, d = _sv().ray(v, mx, my)
    n = np.asarray(normal, np.float64)
    den = float(np.dot(d, n))
    if abs(den) < 1e-9:
        return None
    t = float(np.dot(np.asarray(point, np.float64) - o, n)) / den
    return None if t <= 0 else o + d * t


def snap_step(app, v, depth):
    """The move snap: the ruler division nearest ten pixels at this depth."""
    g = app.project.geometry
    return units.round_step(10.0 / max(1e-6, _px_per_unit(v, depth)), g.params)


# --- the handles ---------------------------------------------------------------------------------
def gizmo(app, v):
    """The handles for the selection now: {"p0" world, "c" screen, "axes":
    {a: (dir, length px, px a unit)}, "planes": {(a, b): square}, "rings":
    {a: points}} or None (nothing movable, or a modal move running)."""
    if getattr(app, "_tool", None) is not None and app._tool.get("kind") in ("modal", "corner"):
        return None
    if getattr(app, "_shape_place", False) or _run().active(app):
        return None
    idx = movable(app)
    if not idx:
        return None
    parts = _parts(app)
    p0 = pivot(parts, idx)
    c, ok, depth = _screen(v, p0)
    if not ok or not v.inside(*c):
        return None
    k = _px_per_unit(v, depth)
    out = {"p0": p0, "c": c, "depth": depth, "axes": {}, "planes": {}, "rings": {}, "mode": getattr(app, "_gizmo", "move")}
    for a in range(3):
        u, ka = _axis_screen(v, p0, a)
        if u is None:
            continue
        f = min(1.0, ka / max(1e-6, k))                 # 1 across the screen, 0 pointing at the eye
        if f >= 0.2:
            out["axes"][a] = (u, px(ARROW) * f, ka)
    if out["mode"] == "move":
        for a, b in ((0, 1), (0, 2), (1, 2)):
            if a in out["axes"] and b in out["axes"]:
                ua, ub = out["axes"][a][0], out["axes"][b][0]
                q = c + (ua + ub) * px(PLANE_AT)
                s = px(PLANE_SIZE) * 0.5
                out["planes"][(a, b)] = (q[0] - s, q[1] - s, q[0] + s, q[1] + s)
    else:
        r_world = px(RING) / max(1e-6, k)
        t = np.linspace(0, 2 * math.pi, 49)
        for a in range(3):
            e1 = np.zeros(3); e1[(a + 1) % 3] = 1.0
            e2 = np.zeros(3); e2[(a + 2) % 3] = 1.0
            P = p0 + r_world * (np.cos(t)[:, None] * e1 + np.sin(t)[:, None] * e2)
            sx, sy, ok, _ = _sv().project(v, P)
            if ok.all():
                out["rings"][a] = np.stack([sx, sy], 1)
    return out


def _seg_dist(p, a, b):
    ab = b - a
    t = max(0.0, min(1.0, float(np.dot(p - a, ab) / max(1e-9, np.dot(ab, ab)))))
    return float(np.linalg.norm(p - (a + ab * t)))


def handle_at(gz, mx, my):
    """The handle under a screen point: ("free",), ("axis", a), ("plane", (a, b)), ("ring", a), or None."""
    if gz is None:
        return None
    m = np.array([mx, my], np.float64)
    c = gz["c"]
    if np.linalg.norm(m - c) <= px(CENTRE) + 2:
        return ("free",)
    if gz["mode"] == "move":
        for ab, (x0, y0, x1, y1) in gz["planes"].items():
            if x0 - 2 <= mx <= x1 + 2 and y0 - 2 <= my <= y1 + 2:
                return ("plane", ab)
        best = None
        for a, (u, L, _) in gz["axes"].items():
            d = _seg_dist(m, c + u * px(CENTRE), c + u * (L + px(8)))
            if d <= px(GRAB) and (best is None or d < best[0]):
                best = (d, a)
        return ("axis", best[1]) if best else None
    best = None
    for a, pts in gz["rings"].items():
        d = min(_seg_dist(m, pts[i], pts[i + 1]) for i in range(len(pts) - 1))
        if d <= px(GRAB) and (best is None or d < best[0]):
            best = (d, a)
    return ("ring", best[1]) if best else None


def set_mode(app, mode):
    """The handles' mode: "move" (arrows and squares) or "turn" (rings)."""
    app._gizmo = "turn" if mode == "turn" else "move"
    for m in ("move", "turn"):
        if dpg.does_item_exist(f"gizmo_{m}"):
            from native import weight
            (weight.primary if m == app._gizmo else weight.plain)(f"gizmo_{m}")


# --- a transform of the selection from its start ----------------------------------------------
def _begin(app, kind, **kw):
    """A drag or a modal move starts: the parts as they are, for the preview
    and for putting back."""
    parts = _parts(app)
    idx = movable(app)
    if not idx:
        return None
    t = {"kind": kind, "start": json.loads(json.dumps(parts)), "idx": idx, "p0": pivot(parts, idx),
         "pre": json.dumps(app.project.geometry.params), "g0": app.project.geometry, "join": None}
    t.update(kw)
    app._tool = t
    return t


def _preview(app, parts, t):
    """The parts shown moved at once, and kept on the move for when it is
    kept (one undo step then). A move, a turn or a scale keeps every LED:
    only where they are changes - so the geometry the move began with is
    shown with its LEDs' places replaced, its layout as it was (on the grid
    layout a move changes which LEDs share a cell; the grid is worked out
    again when the move is kept) and the engine untouched."""
    t["parts"] = parts
    g0 = t["g0"]
    pos_w, _, _ = shapes.resolve(parts)
    phys = np.asarray(g0.phys, int)
    if len(pos_w) < len(phys):
        return
    g = copy.copy(g0)
    g.pos = np.array(g0.pos, np.float32, copy=True)
    g.pos[phys] = pos_w[:len(phys)]
    g.params = dict(g0.params, parts=parts)
    app.project.geometry = g


def _moved_parts(t, delta):
    parts = json.loads(json.dumps(t["start"]))
    for i in t["idx"]:
        parts[i] = shapes.moved(parts[i], delta)
    return parts


def _turned_parts(t, axis, deg):
    R = shapes.axis_rotation(axis, deg)
    parts = json.loads(json.dumps(t["start"]))
    for i in t["idx"]:
        parts[i] = shapes.turned(parts[i], R, t["p0"])
    return parts


def _scaled_parts(t, k):
    parts = json.loads(json.dumps(t["start"]))
    for i in t["idx"]:
        parts[i] = shapes.scaled(parts[i], k, t["p0"])
    return parts


def _snap_pos(app, v, t, delta, axes, depth):
    """The move's place snapped to the ruler step on the axes it moves
    along (Ctrl held: as it is)."""
    if _ctrl():
        return delta
    step = snap_step(app, v, depth)
    p = t["p0"] + delta
    out = np.array(delta, np.float64)
    for a in axes:
        out[a] = round(p[a] / step) * step - t["p0"][a]
    t["step"] = step
    return out


def _join(app, v, t, delta, axis=None):
    """Snap to join: with one part moving, its first LED near another part's
    end (one spacing on from the end's last LED) or its last LED near a
    part's first - the move that puts it there, and which. On an axis, only
    a join that lies on the axis line. (delta, (how, part)) or (delta, None)."""
    if len(t["idx"]) != 1:
        return delta, None
    i = t["idx"][0]
    start = t["start"]
    me = shapes.ends(start[i])
    if me is None:
        return delta, None
    f0, din, l0, dout, sp = me
    best = None
    for j, q in enumerate(start):
        if j == i or q.get("hidden") or q.get("kind") == "reference":
            continue
        e = shapes.ends(q)
        if e is None:
            continue
        qf, qin, ql, qout, qsp = e
        cands = []
        if qout is not None:
            cands.append(("after", j, ql + qout * qsp, f0))          # its first LED one spacing on from q's last
        if qin is not None:
            cands.append(("before", j, qf - qin * qsp, l0))          # its last LED one spacing before q's first
        for how, jj, target, mine in cands:
            want = target - mine
            if axis is not None:                                     # on the axis line only
                e_a = np.zeros(3); e_a[axis] = 1.0
                want = e_a * float(np.dot(want, e_a))
            at, ok, _ = _screen(v, mine + want)
            goal, ok2, _ = _screen(v, target)
            now, ok3, _ = _screen(v, mine + delta)
            if not (ok and ok2 and ok3) or np.linalg.norm(at - goal) > 2.0:
                continue
            d = float(np.linalg.norm(now - goal))
            if d <= px(JOIN_PX) and (best is None or d < best[0]):
                best = (d, want, (how, jj, target))
    if best is None:
        return delta, None
    return best[1], best[2]


def _move_to(app, v, t, mx, my):
    """The selection moved for the pointer at (mx, my): by the handle (or the
    modal move's axis) taken at the start."""
    h = t.get("handle") or ("free",)
    m0 = t["m0"]
    depth = t.get("depth", 1.0)
    if h[0] == "axis":
        a = h[1]
        u, ka = _axis_screen(v, t["p0"], a)
        if u is None:
            return
        s = float(np.dot(np.array([mx, my]) - m0, u)) / max(1e-6, ka)
        delta = np.zeros(3); delta[a] = s
        delta = _snap_pos(app, v, t, delta, (a,), depth)
        delta, t["join"] = _join(app, v, t, delta, a)
    else:
        if h[0] == "plane":
            a, b = h[1]
            normal = np.zeros(3); normal[3 - a - b] = 1.0
            axes = (a, b)
        else:
            normal = v.cam.R[2]                                                             # the screen's plane
            axes = (0, 1, 2)
        h0 = _plane_hit(v, m0[0], m0[1], t["p0"], normal)
        h1 = _plane_hit(v, mx, my, t["p0"], normal)
        if h0 is None or h1 is None:
            return
        delta = h1 - h0
        delta = _snap_pos(app, v, t, delta, axes, depth)
        delta, t["join"] = _join(app, v, t, delta)
    t["delta"] = delta
    _preview(app, _moved_parts(t, delta), t)


def _turn_to(app, v, t, mx, my):
    a = t["handle"][1] if t.get("handle") and t["handle"][0] == "ring" else t.get("axis")
    c, ok, _ = _screen(v, t["p0"])
    if not ok:
        return
    ang = lambda p: math.atan2(-(p[1] - c[1]), p[0] - c[0])
    d = math.degrees(ang((mx, my)) - ang(t["m0"]))
    d = (d + 180.0) % 360.0 - 180.0
    toward = v.cam.R[2]                                   # from the shape to the eye
    if a is None:
        axis = toward                                     # about the line of sight
        sign = 1.0
    else:
        axis = np.zeros(3); axis[a] = 1.0
        sign = 1.0 if float(np.dot(axis, toward)) >= 0 else -1.0
    deg = d * sign
    if not _ctrl():
        deg = round(deg / TURN_STEP) * TURN_STEP
    t["deg"], t["axis_vec"] = deg, axis
    _preview(app, _turned_parts(t, axis, deg), t)


def _scale_to(app, v, t, mx, my):
    c, ok, _ = _screen(v, t["p0"])
    if not ok:
        return
    r0 = max(4.0, float(np.linalg.norm(np.asarray(t["m0"]) - c)))
    k = max(0.02, float(np.linalg.norm(np.array([mx, my]) - c)) / r0)
    if not _ctrl():
        k = max(0.1, round(k * 10.0) / 10.0)
    t["k"] = k
    _preview(app, _scaled_parts(t, k), t)


def _commit(app, t, what):
    """The move kept: applied, one undo step (from before it began), the
    join's reorder with it, and a word on the footer."""
    ui = _ui()
    parts = t.get("parts") or _parts(app)
    msg = what
    if t.get("join") and len(t["idx"]) == 1:
        how, j, _ = t["join"]
        i = t["idx"][0]
        name = lambda k: parts[k].get("name", parts[k]["kind"])
        want = j + 1 if how == "after" else j
        if i < want:
            want -= 1
        if want != i:
            parts = shapes.reordered(parts, i, want)
            ui._set_sel(app, {want})
            msg = f"{name(i)} joined {how} {name(j)}: {'next after' if how == 'after' else 'just before'} it in the wiring now"
        else:
            msg = f"{name(i)} joined {how} {name(j)}"
    app._tool = None
    ui._apply(app, parts, undo_from=t["pre"])
    app.gp.status(msg)


def _cancel(app):
    t = getattr(app, "_tool", None)
    app._tool = None
    if t and t.get("g0") is not None:
        app.project.geometry = t["g0"]                      # the engine never had the move
        app.gp.status("put back")


# --- the pointer on the view -------------------------------------------------------------------
def press(app):
    """A left press on the 3-D view while building: a modal move kept; a
    handle taken; Shift: a click or a box to come. True when taken (else the
    view turns, as ever - and a press that does not move is a click, which
    release() makes a pick)."""
    if not view3d.editing(app):
        return False
    t = getattr(app, "_tool", None)
    if t is not None and t.get("kind") == "modal":
        _keep(app, t)
        return True
    if _run().active(app):
        return _run().click(app)                            # a corner of the run being drawn
    if _run().corner_press(app):
        return True                                         # a path's corner taken
    sv = _sv()
    v = sv.view(app)
    if v is None:
        return False
    mx, my, _ = sv.pointer(app)
    app._press = (mx, my)
    gz = gizmo(app, v)
    h = handle_at(gz, mx, my)
    if h is not None:
        t = _begin(app, "handle", handle=h, m0=np.array([mx, my], np.float64), depth=gz["depth"])
        return t is not None
    if _shift():
        app._tool = {"kind": "box", "m0": (mx, my), "m1": (mx, my)}
        return True
    return False


def drag(app):
    if _run().corner_drag(app):
        return True
    t = getattr(app, "_tool", None)
    if t is None or t.get("kind") not in ("handle", "box"):
        return False
    sv = _sv()
    v = sv.view(app)
    mx, my, _ = sv.pointer(app)
    if t["kind"] == "box":
        t["m1"] = (mx, my)
        return True
    if v is None:
        return True
    if t["handle"][0] == "ring" or (t["handle"][0] == "free" and getattr(app, "_gizmo", "move") == "turn"):
        _turn_to(app, v, t, mx, my)
    else:
        _move_to(app, v, t, mx, my)
    return True


def release(app):
    """The button up: a handle's drag kept; a box's parts selected; a click
    (a press that did not move) picks the part under it - Shift: added or
    taken away; on nothing, none."""
    if _run().corner_release(app):
        return True
    t = getattr(app, "_tool", None)
    sv = _sv()
    if t is not None and t.get("kind") == "handle":
        moved = t.get("delta") is not None or t.get("deg") is not None
        if not moved:
            app._tool = None
            return True
        _commit(app, t, _handle_words(app, t))
        return True
    if t is not None and t.get("kind") == "box":
        app._tool = None
        (x0, y0), (x1, y1) = t["m0"], t["m1"]
        if abs(x1 - x0) < CLICK and abs(y1 - y0) < CLICK:
            _click(app, x0, y0, toggle=True)
            return True
        _box(app, min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))
        return True
    p = getattr(app, "_press", None)
    app._press = None
    if p is None or not view3d.editing(app):
        return False
    mx, my, _ = sv.pointer(app)
    if abs(mx - p[0]) < CLICK and abs(my - p[1]) < CLICK:
        _click(app, mx, my, toggle=False)
    return False                                           # the turn it started ends as ever


def _click(app, mx, my, toggle):
    sv = _sv()
    v = sv.view(app)
    if v is None:
        return
    hit = pick(app, v, mx, my)
    ui = _ui()
    if hit is None:
        if not toggle:
            ui.select(app, [])
        return
    ui.select(app, [hit[1]], toggle=toggle)


def pick(app, v, mx, my):
    """The pickable part's LED under a screen point (hidden and locked parts are passed over)."""
    sv = _sv()
    g = sv.drawn(app)
    got = sv.pick(app, v, mx, my, g)
    if got is None:
        return None
    parts = _parts(app)
    k, pi = got
    if 0 <= pi < len(parts) and pickable(parts[pi]):
        return got
    # the part on top is hidden or locked: the next one under the point, if any
    W, owner = sv.wiring(g)
    sx, sy, ok, depth = sv.project(v, W)
    half = np.maximum(1.0, v.cam.scale(depth) * (sv.LED / v.frame[1])) + 1.0
    under = ok & (np.abs(sx - mx) <= half) & (np.abs(sy - my) <= half)
    bad = np.array([not (0 <= o < len(parts)) or not pickable(parts[o]) for o in owner], bool)
    idx = np.nonzero(under & ~bad)[0]
    if len(idx) == 0:
        return None
    k = int(idx[np.argmin(depth[idx])])
    return k, int(owner[k])


def _box(app, x0, y0, x1, y1):
    """Every pickable part with an LED in the box joins the selection."""
    sv = _sv()
    v = sv.view(app)
    g = sv.drawn(app)
    if v is None or g is None:
        return
    W, owner = sv.wiring(g)
    sx, sy, ok, _ = sv.project(v, W)
    inside = ok & (sx >= x0) & (sx <= x1) & (sy >= y0) & (sy <= y1)
    parts = _parts(app)
    got = sorted({int(o) for o in owner[inside] if 0 <= o < len(parts) and pickable(parts[o])})
    _ui().select(app, got, add=True)
    app.gp.status(f"{len(got)} part(s) in the box, added to the selection" if got else "no parts in the box")


# --- G, R and S ------------------------------------------------------------------------------
def start(app, mode):
    """A modal move (G), turn (R) or scale (S) of the selection, following
    the pointer until a click or Enter keeps it, Esc or a right-click puts
    it back."""
    if not view3d.editing(app):
        return
    sv = _sv()
    v = sv.view(app)
    if v is None:
        return
    if not movable(app):
        app.gp.status("select a part first: click it in the view (a locked part does not move)")
        return
    mx, my, _ = sv.pointer(app)
    parts = _parts(app)
    c, ok, depth = _screen(v, pivot(parts, movable(app)))
    t = _begin(app, "modal", mode=mode, m0=np.array([mx, my], np.float64), axis=None, typed="", depth=depth,
               handle=("free",))
    if mode == "turn":
        t["handle"] = None
    app.gp.status({"move": "moving", "turn": "turning", "scale": "scaling"}[mode]
                  + ": X, Y or Z locks the axis, a number is exact, Enter or a click keeps it, Esc puts it back")


def _keep(app, t):
    """A modal move kept: brought up to date first (a number typed and Enter
    pressed in the same frame has had no frame to show it), then applied."""
    poll(app)
    _commit(app, t, _modal_words(app, t))


def _typed(t):
    try:
        return float(t["typed"]) if t["typed"] not in ("", "-", ".", "-.") else None
    except ValueError:
        return None


def _keep_menu_in(app):
    """The part's menu inside the window: its size is only known once it is
    drawn, so it is moved in each frame while it shows."""
    if not (dpg.does_item_exist(MENU) and dpg.is_item_shown(MENU)):
        return
    w, h = dpg.get_item_rect_size(MENU)
    if not w:
        return
    x, y = dpg.get_item_pos(MENU)
    vw, vh = dpg.get_viewport_client_width(), dpg.get_viewport_client_height()
    nx, ny = max(4, min(x, vw - w - 8)), max(4, min(y, vh - h - 8))
    if (nx, ny) != (x, y):
        dpg.set_item_pos(MENU, [int(nx), int(ny)])


def poll(app):
    """Per frame: a modal move follows the pointer (or the typed number);
    the part's menu kept inside the window."""
    _keep_menu_in(app)
    t = getattr(app, "_tool", None)
    if t is None or t.get("kind") != "modal":
        return
    if not view3d.editing(app):
        _cancel(app); return
    sv = _sv()
    v = sv.view(app)
    if v is None:
        return
    mx, my, _ = sv.pointer(app)
    n = _typed(t)
    g = app.project.geometry
    if t["mode"] == "move":
        if n is not None:
            a = t["axis"] if t["axis"] is not None else 0
            delta = np.zeros(3); delta[a] = units.from_unit(n, g.params)
            t["delta"] = delta; t["join"] = None
            _preview(app, _moved_parts(t, delta), t)
        else:
            t["handle"] = ("axis", t["axis"]) if t["axis"] is not None else ("free",)
            _move_to(app, v, t, mx, my)
    elif t["mode"] == "turn":
        if n is not None:
            axis = np.zeros(3); axis[t["axis"] if t["axis"] is not None else 2] = 1.0
            t["deg"], t["axis_vec"] = n, axis
            _preview(app, _turned_parts(t, axis, n), t)
        else:
            t["handle"] = ("ring", t["axis"]) if t["axis"] is not None else None
            _turn_to(app, v, t, mx, my)
    else:
        if n is not None:
            t["k"] = max(0.001, n)
            _preview(app, _scaled_parts(t, t["k"]), t)
        else:
            _scale_to(app, v, t, mx, my)


_DIGITS = {getattr(dpg, f"mvKey_{d}"): d for d in "0123456789"}
_DIGITS.update({getattr(dpg, f"mvKey_NumPad{d}"): d for d in "0123456789" if hasattr(dpg, f"mvKey_NumPad{d}")})


def key(app, code):
    """A key while a modal move runs: X, Y, Z lock the axis (again: free); a
    number (digits, a point, a minus; Backspace) is exact; Enter keeps it;
    Esc puts it back. True when taken."""
    if _run().key(app, code):
        return True                                         # drawing a run: Enter, Backspace, Esc
    t = getattr(app, "_tool", None)
    if t is None or t.get("kind") != "modal":
        return False
    if code == dpg.mvKey_Escape:
        _cancel(app); return True
    if code in (dpg.mvKey_Return, getattr(dpg, "mvKey_NumPadEnter", -1)):
        _keep(app, t); return True
    for a, name in enumerate(AXIS_NAME):
        if code == getattr(dpg, f"mvKey_{name}"):
            t["axis"] = None if t["axis"] == a else a
            return True
    if code in _DIGITS:
        t["typed"] += _DIGITS[code]; return True
    if code in (getattr(dpg, "mvKey_Period", -1), getattr(dpg, "mvKey_Decimal", -1)):
        if "." not in t["typed"]:
            t["typed"] += "."
        return True
    if code in (getattr(dpg, "mvKey_Minus", -1), getattr(dpg, "mvKey_Subtract", -1)):
        t["typed"] = t["typed"][1:] if t["typed"].startswith("-") else "-" + t["typed"]
        return True
    if code == dpg.mvKey_Back:
        t["typed"] = t["typed"][:-1]; return True
    return True                                             # every other key waits while the move runs


def _handle_words(app, t):
    g = app.project.geometry
    n = len(t["idx"])
    who = "1 part" if n == 1 else f"{n} parts"
    if t.get("deg") is not None:
        return f"{who} turned {t['deg']:.0f} degrees"
    d = t.get("delta")
    return f"{who} moved {units.show(float(np.linalg.norm(d)), g.params)}" if d is not None else who


def _modal_words(app, t):
    g = app.project.geometry
    n = len(t["idx"])
    who = "1 part" if n == 1 else f"{n} parts"
    if t["mode"] == "turn":
        return f"{who} turned {t.get('deg', 0.0):.1f} degrees"
    if t["mode"] == "scale":
        return f"{who} scaled {t.get('k', 1.0):.3g}x"
    d = t.get("delta")
    return f"{who} moved {units.show(float(np.linalg.norm(d)), g.params)}" if d is not None else who


def readout(app, t):
    """The line a modal move shows at the view's foot."""
    g = app.project.geometry
    ax = f" {AXIS_NAME[t['axis']]}" if t.get("axis") is not None else ""
    typed = t["typed"]
    if t["mode"] == "move":
        d = t.get("delta")
        what = (f"{typed} {units.unit(g.params)}" if typed else
                ("  ".join(f"{AXIS_NAME[a]} {units.number(d[a], g.params)}" for a in range(3) if abs(d[a]) > 1e-9) + f" {units.unit(g.params)}"
                 if d is not None and np.abs(d).max() > 1e-9 else "0"))
        head = "Move"
    elif t["mode"] == "turn":
        what = f"{typed} degrees" if typed else f"{t.get('deg', 0.0):.0f} degrees"
        head = "Turn" + ("" if t.get("axis") is not None else " (about the line of sight)")
    else:
        what = f"{typed}x" if typed else f"{t.get('k', 1.0):.2f}x"
        head = "Scale"
    j = t.get("join")
    parts = t["start"]
    jn = f"   join {j[0]} {parts[j[1]].get('name', parts[j[1]]['kind'])}" if j else ""
    return f"{head}{ax}  {what}{jn}    X Y Z lock   a number is exact   Enter or click keeps it   Esc puts it back"


# --- drawing ------------------------------------------------------------------------------------
def draw(app, v, D):
    """The handles on the selection, a box being drawn, a join about to be
    made, and a modal move's readout - on the view's overlay."""
    from native import chrome
    sv = _sv()
    cov = sv.covers(app)
    _run().draw(app, v, D)                                  # a run being drawn
    _run().draw_corners(app, v, D)                          # a lone selected path's corners
    t = getattr(app, "_tool", None)
    if t is not None and t.get("kind") == "box":
        (x0, y0), (x1, y1) = t["m0"], t["m1"]
        acc = tuple(chrome.ACCENT[:3])
        dpg.draw_rectangle((min(x0, x1), min(y0, y1)), (max(x0, x1), max(y0, y1)), color=acc + (220,), fill=acc + (36,),
                           thickness=1.2, parent=D)
    j = t.get("join") if t is not None else None
    if j is not None:
        s, ok, _ = _screen(v, j[2])
        if ok and sv.clear(cov, *s):
            dpg.draw_circle(tuple(s), px(9), color=(255, 255, 255, 230), thickness=2.0, parent=D)
            parts = t["start"]
            word = f"join {j[0]} {parts[j[1]].get('name', parts[j[1]]['kind'])}"
            typeface.draw_text((s[0] + px(12), s[1] - px(20)), word, sv.small(), color=(255, 255, 255, 240), parent=D)
    if t is not None and t.get("kind") == "modal":
        line = readout(app, t)
        size = sv.small()
        w = typeface.measure(line, "body", size)
        a, b, c, d = v.clip
        x = max(a + px(8), (a + c) / 2 - w / 2); y = d - size - px(30)
        dpg.draw_rectangle((x - px(8), y - px(5)), (x + w + px(8), y + size + px(5)), color=tuple(chrome.ACCENT[:3]) + (255,),
                           fill=tuple(chrome.PANEL[:3]) + (240,), rounding=px(4), parent=D)
        typeface.draw_text((x, y), line, size, color=tuple(chrome.TEXT[:3]) + (255,), parent=D)
        if t.get("axis") is not None:                       # the locked axis as a long line through the pivot
            a_ = t["axis"]
            e = np.zeros(3); e[a_] = 1.0
            span = 4.0 * v.frame[1]
            P = np.stack([t["p0"] - e * span, t["p0"] + e * span])
            sx, sy, ok, _ = sv.project(v, P)
            if ok.all():
                dpg.draw_line((sx[0], sy[0]), (sx[1], sy[1]), color=AXIS_COL[a_] + (170,), thickness=1.2, parent=D)
        return
    gz = gizmo(app, v)
    if gz is None:
        return
    c = gz["c"]
    if not sv.clear(cov, *c, px(RING if gz["mode"] == "turn" else ARROW)):
        return
    hot = None
    if t is not None and t.get("kind") == "handle":
        hot = t["handle"]
    else:
        mx, my, on = sv.pointer(app)
        hot = handle_at(gz, mx, my) if on else None
    if gz["mode"] == "move":
        for (a, b), (x0, y0, x1, y1) in gz["planes"].items():
            col = AXIS_COL[3 - a - b]
            lit = hot == ("plane", (a, b))
            dpg.draw_rectangle((x0, y0), (x1, y1), color=col + (255,), fill=col + ((200,) if lit else (90,)), thickness=1.0, parent=D)
        for a, (u, L, _) in gz["axes"].items():
            col = AXIS_COL[a]
            lit = hot == ("axis", a)
            tip = c + u * L
            dpg.draw_line(tuple(c + u * px(CENTRE)), tuple(tip), color=col + (255,), thickness=3.0 if lit else 2.0, parent=D)
            n = np.array([-u[1], u[0]])
            h = px(9) if lit else px(7)
            dpg.draw_triangle(tuple(tip + u * h * 1.6), tuple(tip + n * h * 0.6), tuple(tip - n * h * 0.6), color=col + (255,),
                              fill=col + (255,), parent=D)
            typeface.draw_text(tuple(tip + u * h * 1.6 + np.array([px(3), -px(8)])), AXIS_NAME[a], sv.small(), color=col + (255,), parent=D)
    else:
        for a, pts in gz["rings"].items():
            lit = hot == ("ring", a)
            dpg.draw_polyline([tuple(p) for p in pts], color=AXIS_COL[a] + ((255,) if lit else (200,)), thickness=3.0 if lit else 1.8, parent=D)
    lit = hot == ("free",)
    dpg.draw_circle(tuple(c), px(CENTRE), color=(255, 255, 255, 255 if lit else 200), fill=(255, 255, 255, 70 if lit else 25),
                    thickness=1.6, parent=D)


# --- a part's menu ------------------------------------------------------------------------------
MENU = "shape_ctx"


def build_menu(app):
    """The part's right-click menu: a popup window shown at the pointer
    (filled when it opens), kept off by the overlays like any floating window."""
    with dpg.window(tag=MENU, show=False, no_title_bar=True, no_resize=True, no_move=True, autosize=True, popup=True):
        dpg.add_group(tag="shape_ctx_rows")
    app.FLOATING = tuple(getattr(app, "FLOATING", ())) + (MENU,)


def right(app):
    """A right press on the view while building: a modal move put back; on
    a part, its menu (the part selected first, unless it already is). True
    when taken."""
    if not view3d.editing(app):
        return False
    t = getattr(app, "_tool", None)
    if t is not None and t.get("kind") == "modal":
        _cancel(app); return True
    sv = _sv()
    v = sv.view(app)
    if v is None:
        return False
    mx, my, on = sv.pointer(app)
    if not on:
        return False                                        # not on the view (or under a window over it)
    g = sv.drawn(app)
    got = sv.pick(app, v, mx, my, g)                        # a locked part has its menu too
    if got is None:
        return False
    k, pi = got
    ui = _ui()
    if pi not in ui.selection(app):
        ui.select(app, [pi])
    open_menu(app, pi, (mx, my))
    return True


def menu_rows(app, pi):
    """The menu's rows for part pi: (label, key or "", what it does)."""
    ui = _ui()
    parts = _parts(app)
    part = parts[pi]
    keys = app.keys
    lab = lambda a: keys.label(a)
    n = len(ui.selection(app))
    them = "them" if n > 1 else "it"
    m = part.get("mirror") or {}
    reps = int((part.get("copies") or {}).get("n", 1) or 1)
    rows = [("Duplicate and move", lab("shape_dup"), lambda: duplicate(app)),
            ("Repeat it: copies" if reps <= 1 else f"Repeated {reps} times: one copy more", "", lambda: ui.set_copies(app, pi, n=reps + 1)),
            (("Unmirror" if m.get("x") else "Mirror") + " across X", "", lambda: ui.set_mirror(app, pi, x=not m.get("x"))),
            (("Unmirror" if m.get("y") else "Mirror") + " across Y", "", lambda: ui.set_mirror(app, pi, y=not m.get("y"))),
            (("Unmirror" if m.get("z") else "Mirror") + " across Z", "", lambda: ui.set_mirror(app, pi, z=not m.get("z"))),
            None,
            ("Reverse its wiring", "", lambda: ui.set_part(app, pi, reverse=not part.get("reverse"))),
            ("First in the wiring", "", lambda: wiring_move(app, pi, "first")),
            ("Earlier in the wiring", "", lambda: wiring_move(app, pi, "earlier")),
            ("Later in the wiring", "", lambda: wiring_move(app, pi, "later")),
            ("Last in the wiring", "", lambda: wiring_move(app, pi, "last")),
            None,
            (f"Frame {them}", lab("view_frame"), lambda: ui.frame_selection(app))]
    grp = part.get("group")
    if grp:
        members = [k for k, q in enumerate(parts) if q.get("group") == grp]
        rows.append((f"Select its group ({grp})", "", lambda: ui.select(app, members)))
    rows += [
            ("Rename...", "", lambda: rename(app, pi)),
            ("Show" if part.get("hidden") else "Hide", "", lambda: ui.set_part(app, pi, hidden=not part.get("hidden"))),
            ("Unlock" if part.get("locked") else "Lock", "", lambda: ui.set_part(app, pi, locked=not part.get("locked"))),
            ("Light it (the sim; the device while streaming)", "", lambda: light(app, pi)),
            None,
            (f"Delete {them}", lab("shape_delete"), lambda: delete(app))]
    return rows


def open_menu(app, pi, at):
    dpg.delete_item("shape_ctx_rows", children_only=True)
    parts = _parts(app)
    typeface.label(dpg.add_text(parts[pi].get("name", parts[pi]["kind"]).upper(), parent="shape_ctx_rows"))
    for row in menu_rows(app, pi):
        if row is None:
            dpg.add_separator(parent="shape_ctx_rows"); continue
        label, k, fn = row
        with dpg.group(horizontal=True, parent="shape_ctx_rows"):
            dpg.add_selectable(label=label, width=px(250), user_data=fn, callback=lambda s, a, u: (dpg.hide_item(MENU), u()))
            if k:
                typeface.small(dpg.add_text(k))
    dpg.configure_item(MENU, show=True)
    dpg.set_item_pos(MENU, [int(at[0]), int(at[1])])


def wiring_move(app, pi, where):
    parts = _parts(app)
    j = {"first": 0, "earlier": pi - 1, "later": pi + 1, "last": len(parts) - 1}[where]
    j = max(0, min(len(parts) - 1, j))
    if j == pi:
        return
    ui = _ui()
    ui._set_sel(app, {j})
    ui._apply(app, shapes.reordered(parts, pi, j))
    app.gp.status(f"{parts[pi].get('name', parts[pi]['kind'])}: LEDs from part {j + 1}'s place in the wiring now")


def rename(app, pi):
    from native import chrome
    parts = _parts(app)
    chrome.ask(app, "Rename the part", "its name, in the list and the menus", parts[pi].get("name", parts[pi]["kind"]),
               lambda v: _ui().set_part(app, pi, name=v) if v else None)


def light(app, pi):
    """The wiring test lighting this part: in the sim (the view shows it
    while it runs) and on the device while the sim is streamed to it."""
    app.wiring_start("part")
    if getattr(app, "wiring", None) is not None:
        app.wiring.index = int(pi)
    app.gp.status(f"part {pi + 1} lit (the wiring test: Device > Send's wiring test turns it off; play turns it off too)")


def duplicate(app):
    """Copies of the selected parts, after the last of them in the wiring,
    selected and moving (Blender's Shift+D)."""
    ui = _ui()
    parts = list(_parts(app))
    idx = sorted(ui.selection(app))
    if not idx:
        app.gp.status("select a part first: click it in the view"); return
    copies = []
    for i in idx:
        q = json.loads(json.dumps(parts[i]))
        q["name"] = q.get("name", q["kind"]) + " copy"
        q.pop("locked", None)
        copies.append(q)
    at = idx[-1] + 1
    parts[at:at] = copies
    ui._set_sel(app, set(range(at, at + len(copies))), at + len(copies) - 1)
    ui._apply(app, parts, refit="grow")
    start(app, "move")


def delete(app):
    ui = _ui()
    parts = list(_parts(app))
    idx = set(ui.selection(app))
    if not idx:
        app.gp.status("select a part first: click it in the view"); return
    keep = [p for i, p in enumerate(parts) if i not in idx]
    ui._set_sel(app, {min(min(idx), len(keep) - 1)} if keep else set())
    ui._apply(app, keep)
    app.gp.status(f"{len(idx)} part(s) deleted (Ctrl+Z brings them back)")


def select_all(app):
    ui = _ui()
    parts = _parts(app)
    everything = set(range(len(parts)))
    ui.select(app, [] if ui.selection(app) == everything else sorted(everything))


# --- the test hooks' pointer ----------------------------------------------------------------------
def test_point(app, where):
    """A point on the view for a test hook: [x, y]; {"led": k} (LED k in the
    wiring); {"handle": [kind, arg]} (a handle of the selection's, e.g.
    ["axis", 0], ["plane", [0, 1]], ["free"], ["ring", 2]); {"from_press":
    [dx, dy]} (that far from the last press)."""
    sv = _sv()
    v = sv.view(app)
    if isinstance(where, (list, tuple)):
        return float(where[0]), float(where[1])
    if "from_press" in where:
        p = getattr(app, "_test_press_at", None) or (0.0, 0.0)
        return p[0] + float(where["from_press"][0]), p[1] + float(where["from_press"][1])
    if v is None:
        return None
    if "join" in where:                                     # during G: where the pointer brings part i's first LED onto part j's end
        i, j = (int(x) for x in where["join"])
        t = getattr(app, "_tool", None)
        parts = t["start"] if t else _parts(app)
        ej, ei = shapes.ends(parts[j]), shapes.ends(parts[i])
        tgt, ok1, _ = _screen(v, ej[2] + ej[3] * ej[4])
        fst, ok2, _ = _screen(v, ei[0])
        m0 = t["m0"] if t else np.array(sv.pointer(app)[:2])
        q = np.asarray(m0) + (tgt - fst) + np.array([3.0, 2.0])
        return float(q[0]), float(q[1])
    if "view" in where:                                     # a fraction across and down the view
        a, b, c, d = v.clip
        return a + (c - a) * float(where["view"][0]), b + (d - b) * float(where["view"][1])
    if "part" in where:                                     # part k's LED drawn on top of the rest of it
        g = sv.drawn(app)
        W, owner = sv.wiring(g)
        sx, sy, ok, depth = sv.project(v, W)
        mine = np.nonzero((owner == int(where["part"])) & ok & sv.visible(v, [], sx, sy))[0]
        if len(mine) == 0:
            return None
        k = int(mine[np.argmin(depth[mine])])
        return float(sx[k]), float(sy[k])
    if "led" in where:
        g = sv.drawn(app)
        W, _ = sv.wiring(g)
        sx, sy, ok, _ = sv.project(v, W[[int(where["led"])]])
        return float(sx[0]), float(sy[0])
    if "handle" in where:
        gz = gizmo(app, v)
        if gz is None:
            return None
        kind = where["handle"][0]
        c = gz["c"]
        if kind == "axis":
            u, L, _ = gz["axes"][int(where["handle"][1])]
            q = c + u * (L * 0.7)
        elif kind == "plane":
            a, b = where["handle"][1]
            x0, y0, x1, y1 = gz["planes"][(int(a), int(b))]
            q = np.array([(x0 + x1) / 2, (y0 + y1) / 2])
        elif kind == "ring":
            pts = gz["rings"][int(where["handle"][1])]
            q = pts[len(pts) // 8]
        else:
            q = c
        return float(q[0]), float(q[1])
    return None


def test_hook(app, op):
    """[action, where, mods]: "press", "drag", "release", "right" or "hover"
    at a test point, the modifiers held for it."""
    what = op[0]
    where = op[1] if len(op) > 1 else None
    TEST_MODS.clear(); TEST_MODS.update(op[2] if len(op) > 2 else [])
    xy = test_point(app, where) if where is not None else None
    if xy is not None:
        app._test_pointer = xy
    got = None
    if what == "press":
        app._test_press_at = xy
        got = press(app)
        if not got:
            app._dragging = False                         # (no turn in a test: the press is a click to come)
    elif what == "drag":
        got = drag(app)
    elif what == "release":
        got = release(app)
        TEST_MODS.clear()
    elif what == "right":
        got = right(app)
        TEST_MODS.clear()
    print("tool", what, None if xy is None else [round(xy[0]), round(xy[1])], "->", got,
          "sel", sorted(_ui().selection(app)), "tool", (app._tool or {}).get("kind") if getattr(app, "_tool", None) else None)
