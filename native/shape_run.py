"""Draw a run (the ninth pass's S11) - and a path's corners afterwards.

**Draw a run**: click corners in the 3-D view and a strip (a path part) is
laid along them, an LED every spacing (the shape's density). The corners go
on the plane the view faces most: from above, a floor level with the last
corner (at first the shape's floor); from the front, a wall; from the side,
the other wall - so the top, front and side views (7, 1, 3) draw flat,
upright and side-on runs. The first corner snaps to a round distance (and
onto a part's end, one spacing on, to carry its run on); each run after it
to a direction 15 degrees at a time and a round length (Ctrl: free). As it
grows: each run's length, and the whole in the shape's unit and in LEDs. A
click back on the last corner, or Enter, ends it; Backspace takes the last
corner back; Esc leaves without it.

**A path's corners**, while it is the only part selected: squares on the
view to drag (on the plane the view faces most, snapped the same way), and
a table in the frame - x, y, z in the unit; a corner inserted after one
(halfway to the next) or deleted; the path reversed; drawn on from its end.

    shape_run.toggle(app) / shape_run.active(app) / shape_run.start(app, part=None)
    shape_run.click(app) -> bool             # a left press while drawing: a corner, or the end
    shape_run.key(app, code) -> bool         # Enter, Backspace, Esc while drawing
    shape_run.draw(app, v, parent)           # the run so far, the rubber band, its LEDs, its lengths
    shape_run.corners_table(app, P, i, part, sp)
    shape_run.corner_press(app) / corner_drag(app) / corner_release(app)   # a path's corners in the view
"""
import json
import math

import numpy as np
import dearpygui.dearpygui as dpg

from native import shapes, units, view3d, typeface
from native.typeface import px

ANGLE = 15.0          # degrees a run's direction snaps to
CLOSE = 7             # px: a click this near the last corner ends the run
CORNER = 5            # px: half a corner square's side


def _ui():
    from native import shape_ui
    return shape_ui


def _sv():
    from native import shape_view
    return shape_view


def _tools():
    from native import shape_tools
    return shape_tools


def active(app):
    return getattr(app, "_run", None) is not None


def _button(app):
    if dpg.does_item_exist("shape_draw_btn"):
        from native import weight
        (weight.primary if active(app) else weight.plain)("shape_draw_btn")
        dpg.configure_item("shape_draw_btn", label="Drawing... (Enter ends)" if active(app) else "Draw a run")


def toggle(app):
    if active(app):
        finish(app)
    else:
        start(app)


def start(app, part=None):
    """Drawing on: a new run, or (part: an index) the path part drawn on from its end."""
    if not view3d.editing(app):
        from native import device_ui
        device_ui.show(app, "shape")
    corners = []
    if part is not None:
        parts = _ui()._parts(app) or []
        if 0 <= part < len(parts) and parts[part]["kind"] == "polyline":
            corners = [list(map(float, c)) for c in world_corners(parts[part])]
    app._run = {"corners": corners, "part": part, "pre": json.dumps(app.project.geometry.params)}
    app._shape_place = False
    _button(app)
    app.gp.status("drawing a run: click corners in the 3-D view (from above: on the floor; from the front or the side: on a wall); "
                  "Enter or a click on the last corner ends it, Backspace takes one back, Esc leaves")


def cancel(app):
    app._run = None
    _button(app)
    app.gp.status("no run drawn")


def finish(app):
    """The run made: a path part through its corners (two or more), after the selected part in the wiring, selected."""
    r = getattr(app, "_run", None)
    app._run = None
    _button(app)
    if r is None:
        return
    pts = r["corners"]
    if len(pts) < 2:
        app.gp.status("a run needs two corners or more: none made"); return
    ui = _ui()
    parts = list(ui._parts(app) or [])
    first = np.asarray(pts[0], np.float64)
    local = [[round(float(v), 4) for v in (np.asarray(p) - first)] for p in pts]
    if r.get("part") is not None and 0 <= r["part"] < len(parts) and parts[r["part"]]["kind"] == "polyline":
        i = r["part"]
        q = json.loads(json.dumps(parts[i]))
        q["pos"] = [round(float(v), 4) for v in first]; q["rot"] = [0.0, 0.0, 0.0]; q["scale"] = 1.0; q["reverse"] = False
        q["params"]["points"] = local
        parts[i] = q
        ui._set_sel(app, {i})
        ui._apply(app, parts, undo_from=r["pre"], refit="grow")
        app.gp.status(f"{q.get('name', 'the path')}: {len(pts)} corners, {shapes.part_count(q)} LEDs")
        return
    q = shapes.new_part("polyline", points=local, pitch=1.0)
    q["pos"] = [round(float(v), 4) for v in first]
    q["name"] = f"run {sum(1 for p in parts if p['kind'] == 'polyline') + 1}"
    sel = ui._sel(app) if parts else -1
    at = sel + 1 if 0 <= sel < len(parts) else len(parts)
    parts.insert(at, q)
    ui._set_sel(app, {at})
    ui._apply(app, parts, undo_from=r["pre"], refit="grow")
    L = float(np.linalg.norm(np.diff(np.asarray(pts), axis=0), axis=1).sum())
    app.gp.status(f"{q['name']}: {len(pts)} corners, {units.show(L, app.project.geometry.params)}, {shapes.part_count(q)} LEDs; "
                  f"part {at + 1} in the wiring")


# --- the plane the view faces most, and snapping on it -------------------------------------------
def plane(app, v, through=None):
    """(axis, value): the plane drawn on - from above z, from the front y,
    from the side x - through `through` (a point), else the last corner,
    else the shape's floor or its middle."""
    fwd = -np.asarray(v.cam.R[2], np.float64)
    ax = int(np.argmax(np.abs(fwd)))
    if through is not None:
        return ax, float(through[ax])
    r = getattr(app, "_run", None)
    if r and r["corners"]:
        return ax, float(r["corners"][-1][ax])
    g = app.project.geometry
    pos = np.asarray(g.pos, np.float32).reshape(-1, 3)
    pos = pos[np.isfinite(pos).all(1)]
    if ax == 2:
        return 2, float(pos[:, 2].min()) if len(pos) and (_ui()._parts(app) or []) else 0.0
    return ax, float((pos[:, ax].min() + pos[:, ax].max()) / 2) if len(pos) and (_ui()._parts(app) or []) else 0.0


def _in_plane(ax):
    """The plane's two axes (u, v), right-handed about the one across it."""
    return {2: (0, 1), 1: (0, 2), 0: (1, 2)}[ax]


def snapped(app, v, p, last=None):
    """A point on the plane snapped: the first to the ruler step (and onto a
    part's end, carried on), the rest a round length and 15 degrees on from
    the last corner (Ctrl held: as it is). (point, note)."""
    tools = _tools()
    if tools._ctrl():
        return p, ""
    s, ok, depth = tools._screen(v, p)
    step = tools.snap_step(app, v, depth)
    ax, _ = plane(app, v)
    a, b = _in_plane(ax)
    if last is None:
        # onto a part's end, one spacing on: a run carried on from it
        best = None
        for j, q in enumerate(_ui()._parts(app) or []):
            e = shapes.ends(q) if not q.get("hidden") and q.get("kind") != "reference" else None
            if e is None or e[3] is None:
                continue
            target = e[2] + e[3] * e[4]
            t, ok2, _ = tools._screen(v, target)
            d = float(np.linalg.norm(t - s)) if ok and ok2 else 1e9
            if d <= px(tools.JOIN_PX) and (best is None or d < best[0]):
                best = (d, target, q.get("name", q["kind"]))
        if best is not None:
            return np.asarray(best[1], np.float64), f"on from {best[2]}"
        out = np.array(p, np.float64)
        out[a] = round(out[a] / step) * step
        out[b] = round(out[b] / step) * step
        return out, ""
    d = np.asarray(p, np.float64) - np.asarray(last, np.float64)
    du, dv = float(d[a]), float(d[b])
    L = math.hypot(du, dv)
    if L < 1e-9:
        return np.asarray(last, np.float64), ""
    ang = round(math.degrees(math.atan2(dv, du)) / ANGLE) * ANGLE
    L = max(step, round(L / step) * step)
    out = np.array(last, np.float64)
    out[a] += L * math.cos(math.radians(ang))
    out[b] += L * math.sin(math.radians(ang))
    return out, ""


def _pointer_point(app, v):
    """The plane's point under the pointer, snapped; None when the plane is edge-on."""
    sv = _sv()
    mx, my, _ = sv.pointer(app)
    ax, val = plane(app, v)
    p = sv.unproject(v, mx, my, ax, val)
    if p is None:
        return None, ""
    r = getattr(app, "_run", None)
    last = r["corners"][-1] if r and r["corners"] else None
    return snapped(app, v, p, last)


# --- drawing ----------------------------------------------------------------------------------------
def click(app):
    """A left press on the view while drawing: a corner - or, on the last corner, the end. True: taken."""
    if not active(app):
        return False
    sv = _sv()
    v = sv.view(app)
    if v is None:
        return True
    r = app._run
    mx, my, _ = sv.pointer(app)
    if r["corners"]:
        s, ok, _ = _tools()._screen(v, r["corners"][-1])
        if ok and np.hypot(s[0] - mx, s[1] - my) <= px(CLOSE) and len(r["corners"]) >= 2:
            finish(app); return True
    p, _ = _pointer_point(app, v)
    if p is None:
        app.gp.status("the plane is edge-on here: turn the view (7 from above, 1 from the front)"); return True
    if r["corners"] and np.linalg.norm(np.asarray(p) - np.asarray(r["corners"][-1])) < 1e-6:
        return True
    r["corners"].append([float(c) for c in p])
    return True


def key(app, code):
    """Enter ends the run, Backspace takes the last corner back, Esc leaves. True: taken."""
    if not active(app):
        return False
    if code in (dpg.mvKey_Return, getattr(dpg, "mvKey_NumPadEnter", -1)):
        finish(app); return True
    if code == dpg.mvKey_Escape:
        cancel(app); return True
    if code == dpg.mvKey_Back:
        if app._run["corners"]:
            app._run["corners"].pop()
        return True
    return False


def _leds(corners):
    """The LEDs a run through these corners gets: one every spacing (1 unit), both ends lit."""
    if len(corners) < 2:
        return np.zeros((0, 3))
    pos, _ = shapes.part_points(shapes.new_part("polyline", points=[list(map(float, c)) for c in corners], pitch=1.0))
    return pos


def draw(app, v, D):
    """The run so far, the rubber band to the pointer, the LEDs it would get, its lengths."""
    if not active(app):
        return
    from native import chrome
    sv = _sv()
    g = app.project.geometry
    sp = g.params
    r = app._run
    corners = [np.asarray(c, np.float64) for c in r["corners"]]
    nxt, note = _pointer_point(app, v)
    acc = tuple(chrome.ACCENT[:3])
    size = sv.small()
    pts = corners + ([nxt] if nxt is not None else [])
    if pts:
        sx, sy, ok, _ = sv.project(v, np.asarray(pts))
        # the LEDs the run would get, small
        L = _leds(pts)
        if len(L):
            lx, ly, lok, _ = sv.project(v, L)
            for x, y, o in zip(lx, ly, lok):
                if o and v.inside(x, y):
                    dpg.draw_circle((x, y), 2.2, color=(255, 255, 255, 170), fill=(255, 255, 255, 120), parent=D)
        for k in range(len(pts) - 1):
            if ok[k] and ok[k + 1]:
                last = (k == len(pts) - 2 and nxt is not None)
                dpg.draw_line((sx[k], sy[k]), (sx[k + 1], sy[k + 1]), color=acc + ((150,) if last else (240,)), thickness=1.4 if last else 2.2, parent=D)
                seg = float(np.linalg.norm(pts[k + 1] - pts[k]))
                if seg > 1e-6:
                    t = units.show(seg, sp)
                    typeface.draw_text(((sx[k] + sx[k + 1]) / 2 + px(6), (sy[k] + sy[k + 1]) / 2 - size - px(2)), t, size,
                                       color=(255, 255, 255, 230), parent=D)
        for k in range(len(corners)):
            if ok[k]:
                s = px(CORNER)
                dpg.draw_rectangle((sx[k] - s, sy[k] - s), (sx[k] + s, sy[k] + s), color=acc + (255,), fill=acc + (160,), parent=D)
        if nxt is not None and ok[-1]:
            dpg.draw_circle((sx[-1], sy[-1]), px(4), color=(255, 255, 255, 240), thickness=1.6, parent=D)
            if note:
                typeface.draw_text((sx[-1] + px(10), sy[-1] + px(6)), note, size, color=(255, 255, 255, 230), parent=D)
    # the readout
    total = float(np.linalg.norm(np.diff(np.asarray(pts), axis=0), axis=1).sum()) if len(pts) > 1 else 0.0
    n = len(_leds(pts)) if len(pts) > 1 else 0
    ax, val = plane(app, v)
    where = {2: "on the floor", 1: "on a wall facing the front", 0: "on a wall facing the side"}[ax]
    line = (f"Draw a run  {where} ({'xyz'[ax]} = {units.show(val, sp)})  ·  {len(corners)} corner(s), "
            f"{units.show(total, sp)}, {n} LEDs    click a corner   Enter or the last corner ends it   Backspace   Esc   Ctrl: no snapping")
    w = typeface.measure(line, "body", size)
    a, b, c, d = v.clip
    x = max(a + px(8), (a + c) / 2 - w / 2); y = d - size - px(30)
    dpg.draw_rectangle((x - px(8), y - px(5)), (x + w + px(8), y + size + px(5)), color=acc + (255,),
                       fill=tuple(chrome.PANEL[:3]) + (240,), rounding=px(4), parent=D)
    typeface.draw_text((x, y), line, size, color=tuple(chrome.TEXT[:3]) + (255,), parent=D)


# --- a path's corners -------------------------------------------------------------------------------
def world_corners(part):
    """A path part's corners where they stand in the shape (its move, turn and scale in)."""
    pts = np.asarray(part["params"].get("points") or [[0, 0, 0]], np.float64).reshape(-1, 3)
    P, _ = shapes.transform(dict(part, reverse=False), pts.astype(np.float32), None)
    return np.asarray(P, np.float64)


def _single_path(app):
    ui = _ui()
    parts = ui._parts(app) or []
    sel = sorted(ui.selection(app))
    if len(sel) == 1 and parts[sel[0]]["kind"] == "polyline" and not parts[sel[0]].get("locked") and not active(app):
        return sel[0], parts[sel[0]]
    return None, None


def draw_corners(app, v, D):
    i, part = _single_path(app)
    if part is None:
        return
    sv = _sv()
    W = world_corners(part)
    sx, sy, ok, _ = sv.project(v, W)
    cov = sv.covers(app)
    t = getattr(app, "_tool", None)
    drag = t.get("corner") if t and t.get("kind") == "corner" else None
    mx, my, on = sv.pointer(app)
    for k in range(len(W)):
        if not ok[k] or not v.inside(sx[k], sy[k]) or not sv.clear(cov, sx[k], sy[k]):
            continue
        hot = drag == k or (on and abs(mx - sx[k]) <= px(CORNER) + 2 and abs(my - sy[k]) <= px(CORNER) + 2)
        s = px(CORNER) + (1 if hot else 0)
        dpg.draw_rectangle((sx[k] - s, sy[k] - s), (sx[k] + s, sy[k] + s), color=(255, 255, 255, 255),
                           fill=(255, 255, 255, 200 if hot else 70), parent=D)


def corner_press(app):
    i, part = _single_path(app)
    if part is None:
        return False
    sv = _sv()
    v = sv.view(app)
    if v is None:
        return False
    mx, my, _ = sv.pointer(app)
    W = world_corners(part)
    sx, sy, ok, _ = sv.project(v, W)
    hit = [k for k in range(len(W)) if ok[k] and abs(mx - sx[k]) <= px(CORNER) + 2 and abs(my - sy[k]) <= px(CORNER) + 2]
    if not hit:
        return False
    k = hit[0]
    app._tool = {"kind": "corner", "part": i, "corner": k, "start": W.copy(), "pre": json.dumps(app.project.geometry.params),
                 "g0": app.project.geometry, "moved": False}
    return True


def corner_drag(app):
    t = getattr(app, "_tool", None)
    if t is None or t.get("kind") != "corner":
        return False
    sv = _sv()
    v = sv.view(app)
    if v is None:
        return True
    mx, my, _ = sv.pointer(app)
    k = t["corner"]
    ax, val = plane(app, v, through=t["start"][k])
    p = sv.unproject(v, mx, my, ax, val)
    if p is None:
        return True
    if not _tools()._ctrl():
        s, ok, depth = _tools()._screen(v, p)
        step = _tools().snap_step(app, v, depth)
        a, b = _in_plane(ax)
        p = np.array(p, np.float64)
        p[a] = round(p[a] / step) * step
        p[b] = round(p[b] / step) * step
    W = t["start"].copy()
    W[k] = p
    t["world"] = W
    t["moved"] = True
    parts = json.loads(json.dumps(_ui()._parts(app) or []))
    parts[t["part"]] = _with_corners(parts[t["part"]], W)
    t["parts"] = parts
    g0 = t["g0"]
    if shapes.part_count(parts[t["part"]]) == shapes.part_count(g0.params["parts"][t["part"]]):
        _tools()._preview(app, parts, t)                    # the same LEDs moved: the view alone
    else:
        from native.geometry import Geometry                # a longer or shorter path: the engine takes it (one undo step on release)
        app.apply_geometry(Geometry("shape", **dict(app.project.geometry.params, parts=parts)))
        t["g0"] = app.project.geometry
    return True


def corner_release(app):
    t = getattr(app, "_tool", None)
    if t is None or t.get("kind") != "corner":
        return False
    app._tool = None
    if t.get("moved"):
        _ui()._apply(app, t["parts"], undo_from=t["pre"])
        app.gp.status("corner moved")
    return True


def _with_corners(part, W):
    """The path part with its corners at these places in the shape (its own frame kept)."""
    q = json.loads(json.dumps(part))
    R = shapes.rotation(*q.get("rot", [0, 0, 0]))
    s = q.get("scale", 1.0); s = np.asarray(s if isinstance(s, list) else [s, s, s], np.float64)
    local = ((np.asarray(W, np.float64) - np.asarray(q.get("pos", [0, 0, 0]), np.float64)) @ R) / np.where(s != 0, s, 1)
    q["params"]["points"] = np.round(local, 4).tolist()
    return q


def corners_table(app, P, i, part, sp):
    """The path's corners in the frame: where each is (the unit), one put in after it, deleted; the path reversed or drawn on."""
    from native import chrome, weight
    W = world_corners(part)
    u = units.unit(sp)
    typeface.label(dpg.add_text(f"CORNERS ({len(W)})", parent=P, color=chrome.ACCENT))
    for k in range(len(W)):
        with dpg.group(horizontal=True, parent=P):
            typeface.mono(dpg.add_text(f"{k + 1:2d}", color=chrome.DIM))
            dpg.add_input_floatx(size=3, width=px(250), default_value=[units.to_unit(float(c), sp) for c in W[k]] + [0.0],
                                 format=f"%.2f {u}", on_enter=True, user_data=k,
                                 callback=lambda s, a, kk: _set_corner(app, i, kk, [units.from_unit(float(c), app.project.geometry.params) for c in a[:3]]))
            if k < len(W) - 1:
                dpg.add_button(label="+", small=True, user_data=k, callback=lambda s, a, kk: _insert_corner(app, i, kk))
                chrome.tip("a corner halfway to the next")
            if len(W) > 2:
                dpg.add_button(label="x", small=True, user_data=k, callback=lambda s, a, kk: _delete_corner(app, i, kk))
                weight.danger(dpg.last_item())
    with dpg.group(horizontal=True, parent=P):
        dpg.add_button(label="reverse the path", small=True, callback=lambda: _reverse(app, i))
        chrome.tip("the corners the other way round: its LEDs run from the other end")
        dpg.add_button(label="draw on from its end", small=True, callback=lambda: start(app, i))
        chrome.tip("drawing on: click more corners in the 3-D view; Enter ends it")


def _edit_corners(app, i, fn):
    parts = json.loads(json.dumps(_ui()._parts(app) or []))
    if not (0 <= i < len(parts)) or parts[i]["kind"] != "polyline":
        return
    W = [list(c) for c in world_corners(parts[i])]
    W = fn(W)
    if W is None or len(W) < 2:
        return
    parts[i] = _with_corners(parts[i], np.asarray(W, np.float64))
    _ui()._apply(app, parts)


def _set_corner(app, i, k, p):
    def fn(W):
        if 0 <= k < len(W):
            W[k] = list(p)
        return W
    _edit_corners(app, i, fn)


def _insert_corner(app, i, k):
    def fn(W):
        if 0 <= k < len(W) - 1:
            W.insert(k + 1, [(a + b) / 2 for a, b in zip(W[k], W[k + 1])])
        return W
    _edit_corners(app, i, fn)


def _delete_corner(app, i, k):
    def fn(W):
        if len(W) > 2 and 0 <= k < len(W):
            W.pop(k)
        return W
    _edit_corners(app, i, fn)


def _reverse(app, i):
    _edit_corners(app, i, lambda W: W[::-1])
