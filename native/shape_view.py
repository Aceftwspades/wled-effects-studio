"""The 3-D view while a shape is built - the Shape frame open on a shape.

- Each part in a colour of its own, the selected part bright and the rest
  dimmed, the part under the pointer a little lighter; the effect's colours
  a toggle away (the frame's "colours" switch; kept in the prefs).
- The wiring on the shape: IN at the first LED, END at the last, arrows
  along each part the way its LEDs run, and each lead between one part's
  last LED and the next part's first dashed and labelled with its length
  (a gap of a spacing or less is a join, and is not drawn).
- The part under the pointer named: its LEDs, its size, the LED's number.
- The floor's step in words, and the camera's keys.

Everything is drawn on a viewport drawlist over the view, kept off
whatever floats over it (the frames, dialogs, menus - the list the
gradient frames keep off).

    shape_view.colours(app, rgb)      # the view's colours this frame: the parts', or the effect's
    shape_view.view(app)              # the view's square, frame and camera, or None
    shape_view.project(v, pos)        # (sx, sy, ok, depth) on the screen
    shape_view.unproject(v, mx, my, axis, value)   # the point of a plane under the pointer
    shape_view.pick(app, v, mx, my)   # (wiring index, part) under the pointer
    shape_view.poll(app)              # per frame: the overlay
"""
import colorsys
import math

import numpy as np
import dearpygui.dearpygui as dpg

from native import shapes, units, view3d, typeface
from native.typeface import px

DIM_OTHERS = 0.38            # the parts not selected, while one is
HOVER = 0.72                 # the part under the pointer, not selected
JOIN = 0.6                   # a lead of less than this (the shape's units) past the LEDs' spacing is a join


def part_colour(k):
    """Part k's colour: hues a golden turn apart, so neighbours differ
    (the shape preview's "parts" mode uses the same)."""
    r, g, b = colorsys.hsv_to_rgb((k * 0.61803) % 1.0, 0.75, 1.0)
    return np.array([r * 255, g * 255, b * 255], np.uint8)


def mode(app):
    """What the view colours the LEDs by while building: "parts" or "effect"."""
    return "effect" if app.prefs.get("shape_colours") == "effect" else "parts"


def set_mode(app, m):
    from native.project import save_prefs
    app.prefs["shape_colours"] = "effect" if m == "effect" else "parts"
    save_prefs(app.prefs)
    if dpg.does_item_exist("shape_colours"):
        dpg.set_value("shape_colours", "the effect" if m == "effect" else "the parts")


def drawn(app):
    """The geometry the view is drawing: the project's while a part is being
    dragged (the engine gets it on release), else the engine's."""
    g, p = app.eng.geom, app.project.geometry
    if g is not None and p is not None and p.kind == g.kind and len(p.pos) == len(g.pos):
        return p
    return g


def _parts_of_logical(g):
    """Per logical position, its part (-1 where no LED): cached on the geometry."""
    got = getattr(g, "_view_parts", None)
    if got is not None:
        return got
    n = len(g.pos)
    out = np.full(n, -1, int)
    owner = getattr(g, "owner", None)
    phys = np.asarray(g.phys, int)
    if owner is not None:
        k = min(len(phys), len(owner))
        ok = (phys[:k] >= 0) & (phys[:k] < n)
        out[phys[:k][ok]] = np.asarray(owner[:k], int)[ok]
    g._view_parts = out
    return out


def colours(app, rgb):
    """The LEDs' colours for the 3-D view: the effect's as given, or - while
    a shape is built with the parts shown - each part's colour, the
    selection bright, the others dimmed, the one under the pointer lighter.
    (n, 3) uint8 in the view's (logical) order."""
    if not view3d.editing(app) or getattr(app, "wiring", None) is not None:
        return rgb                                          # the wiring test lighting a part shows as it is
    g = drawn(app)
    if g is None or g.kind != "shape":
        return rgb
    rgb = np.asarray(rgb).reshape(-1, 3)
    of = _parts_of_logical(g)
    if len(of) != len(rgb):
        return rgb
    parts = g.params.get("parts") or []
    hidden = [k for k, q in enumerate(parts) if q.get("hidden")]
    if mode(app) == "effect":
        if not hidden:
            return rgb
        out = rgb.copy()
        out[np.isin(of, hidden)] = 0                        # a hidden part is dark while building, whatever runs
        return out
    nparts = int(of.max()) + 1 if len(of) and of.max() >= 0 else 0
    if nparts == 0:
        return rgb
    from native import shape_ui
    sel = shape_ui.selection(app)
    hov = getattr(app, "_shape_hover", None)
    base = np.stack([part_colour(k) for k in range(nparts)]).astype(np.float32)
    gain = np.full(nparts, DIM_OTHERS if sel else 1.0, np.float32)
    for k in sel:
        if 0 <= k < nparts:
            gain[k] = 1.0
    if hov is not None and 0 <= hov[1] < nparts and hov[1] not in sel:
        gain[hov[1]] = max(gain[hov[1]], HOVER)
    for k in hidden:
        if 0 <= k < nparts:
            gain[k] = 0.0
    out = np.zeros_like(rgb)
    lit = of >= 0
    out[lit] = np.clip(base[of[lit]] * gain[of[lit], None], 0, 255).astype(np.uint8)
    return out


# --- the view: where it is on the screen, its camera ---------------------------------------------
class View:
    """The 3-D view this frame: the square the LEDs are projected into
    (x0, y0, size), the drawlist's rectangle (what may be drawn on), the
    frame and the camera."""

    def __init__(self, x0, y0, size, clip, frame, cam):
        self.x0, self.y0, self.size, self.clip, self.frame, self.cam = x0, y0, size, clip, frame, cam

    def inside(self, x, y):
        a, b, c, d = self.clip
        return a <= x <= c and b <= y <= d


def view(app):
    """The view for a shape, or None (another geometry, the view hidden)."""
    g = app.project.geometry
    if g is None or g.kind != "shape" or not dpg.does_item_exist("cube_img") or not dpg.is_item_shown("cube_win"):
        return None
    st = dpg.get_item_state("cube_img")
    if "rect_min" not in st:
        return None
    (x0, y0), (w, h) = st["rect_min"], st["rect_size"]
    if w <= 0:
        return None
    clip = (x0, y0, x0 + w, y0 + h)
    pq = getattr(app, "point_quads", None)
    if pq is not None and pq.size:                        # the GPU cloud: a square of the view's side, centred in its drawlist
        x0 += (w - pq.size) * 0.5; y0 += (h - pq.size) * 0.5; w = pq.size
    else:
        clip = (x0, y0, x0 + w, y0 + w)
    return View(x0, y0, float(w), clip, view3d.frame(app), view3d.cam(app, float(w)))


def project(v, pos):
    """(sx, sy, ok, depth) of positions (the shape's units) on the screen."""
    c, ext = v.frame
    P = (np.asarray(pos, np.float64).reshape(-1, 3) - np.asarray(c, np.float64)) / ext
    sx, sy, ok, depth = v.cam.screen(P)
    return sx + v.x0, sy + v.y0, ok, depth


def unproject(v, mx, my, axis=2, value=0.0):
    """The point of the plane `axis` = `value` (the shape's units) under a
    screen point, or None when the ray runs along it or away from it."""
    c, ext = v.frame
    o, d = v.cam.ray(mx - v.x0, my - v.y0)
    if abs(d[axis]) < 1e-9:
        return None
    t = ((value - float(c[axis])) / ext - o[axis]) / d[axis]
    if t <= 0:
        return None
    return (o + t * d) * ext + np.asarray(c, np.float64)


def ray(v, mx, my):
    """The ray under a screen point in the shape's units: (origin, direction)."""
    c, ext = v.frame
    o, d = v.cam.ray(mx - v.x0, my - v.y0)
    return o * ext + np.asarray(c, np.float64), d


def wiring(g):
    """(positions in wiring order (n, 3), owner (n,)) of a shape's LEDs."""
    phys = np.asarray(g.phys, int)
    pos = np.asarray(g.pos, np.float32).reshape(-1, 3)
    owner = np.asarray(getattr(g, "owner", np.zeros(len(phys), int)), int)
    k = min(len(phys), len(owner))
    return pos[phys[:k]], owner[:k]


def runs(owner):
    """Each part's [start, end) in wiring order: {part: (a, b)} (a part's LEDs are one run)."""
    out = {}
    if len(owner) == 0:
        return out
    cuts = np.nonzero(np.diff(owner))[0] + 1
    starts = np.concatenate([[0], cuts]); ends = np.concatenate([cuts, [len(owner)]])
    for a, b in zip(starts, ends):
        out.setdefault(int(owner[a]), (int(a), int(b)))
    return out


LED = 0.42                   # the share of the LED spacing an LED's square covers (render_points, PointQuads)


def pick(app, v, mx, my, g=None):
    """The LED under a screen point: (wiring index, part) or None. Of the
    LEDs whose square is under the point, the one drawn on top (the
    nearest the eye); with none, the nearest within a few pixels."""
    g = g or drawn(app)
    if g is None or g.kind != "shape" or not v.inside(mx, my):
        return None
    W, owner = wiring(g)
    if len(W) == 0:
        return None
    sx, sy, ok, depth = project(v, W)
    parts = g.params.get("parts") or []
    hidden = [k for k, q in enumerate(parts) if q.get("hidden")]
    if hidden:
        ok = ok & ~np.isin(owner, hidden)                   # a hidden part is not there to point at
    c, ext = v.frame
    half = np.maximum(1.0, v.cam.scale(depth) * (LED / ext)) + 1.0          # the drawn square's half side, and a pixel
    under = ok & (np.abs(sx - mx) <= half) & (np.abs(sy - my) <= half)
    if under.any():
        idx = np.nonzero(under)[0]
        k = int(idx[np.argmin(depth[idx])])
        return k, int(owner[k])
    d = np.hypot(sx - mx, sy - my)
    d[~ok] = np.inf
    k = int(np.argmin(d))
    if not np.isfinite(d[k]) or d[k] > max(6.0, float(half[k]) * 2.0):
        return None
    return k, int(owner[k])


def pointer(app):
    """(x, y, on the view): the pointer - or the test hooks' stand-in for it
    (a test's process cannot bring the window to the front, so the real
    pointer may be over another window)."""
    t = getattr(app, "_test_pointer", None)
    if t is not None:
        return float(t[0]), float(t[1]), True
    mx, my = dpg.get_mouse_pos(local=False)
    return mx, my, dpg.does_item_exist("cube_img") and dpg.is_item_hovered("cube_img")


# --- what the overlay keeps off -------------------------------------------------------------------
def covers(app):
    """What is drawn over the view - floating frames, dialogs, open menus:
    (x0, y0, x1, y1) each - so no mark lands on top of it."""
    return app.overlay_holes("cube")


def clear(cov, x, y, pad=0.0):
    """Nothing covers (x, y) - with `pad`, nothing within pad of it either."""
    return not any(a - pad <= x <= c + pad and b - pad <= y <= d + pad for a, b, c, d in cov)


def visible(v, cov, sx, sy):
    """Per screen point: inside the view and under nothing that floats over it."""
    a, b, c, d = v.clip
    ok = (sx >= a) & (sx <= c) & (sy >= b) & (sy <= d)
    for x0, y0, x1, y1 in cov:
        ok &= ~((sx >= x0) & (sx <= x1) & (sy >= y0) & (sy <= y1))
    return ok


def _pieces(xs, ys, good):
    """The runs of consecutive good points: lists of (x, y), two or more each."""
    out, cur = [], []
    for x, y, g in zip(xs, ys, good):
        if g:
            cur.append((float(x), float(y)))
        else:
            if len(cur) > 1:
                out.append(cur)
            cur = []
    if len(cur) > 1:
        out.append(cur)
    return out


def _chevron(x, y, dx, dy, s, col, parent):
    """A small arrow head at (x, y) pointing along (dx, dy)."""
    L = math.hypot(dx, dy)
    if L < 1e-6:
        return
    dx, dy = dx / L, dy / L
    bx, by = x - dx * s, y - dy * s
    nx, ny = -dy * s * 0.6, dx * s * 0.6
    dpg.draw_polyline([(bx + nx, by + ny), (x, y), (bx - nx, by - ny)], color=col, thickness=1.6, parent=parent)


def _dashed(a, b, col, parent, dash=5.0, gap=4.0):
    ax, ay = a; bx, by = b
    L = math.hypot(bx - ax, by - ay)
    if L < 1e-6:
        return
    ux, uy = (bx - ax) / L, (by - ay) / L
    t = 0.0
    while t < L:
        e = min(L, t + dash)
        dpg.draw_line((ax + ux * t, ay + uy * t), (ax + ux * e, ay + uy * e), color=col, thickness=1.2, parent=parent)
        t = e + gap


def small():
    """The overlay's text size: a little under the interface's."""
    return max(px(11), int(typeface.size_of("body") * 0.88))


def _label(x, y, lines, parent, clip, col=None):
    """A small box of text lines at (x, y) (its top left), moved inside the
    clip; the first line in `col` (else the text colour), the rest dim."""
    from native import chrome
    size = small()
    w = max(typeface.measure(t, "body", size) for t in lines) + px(12)
    h = len(lines) * (size + px(3)) + px(6)
    a, b, c, d = clip
    x = min(max(a + 2, x), c - w - 2)
    y = min(max(b + 2, y), d - h - 2)
    dpg.draw_rectangle((x, y), (x + w, y + h), color=tuple(chrome.LINE[:3]) + (255,), fill=tuple(chrome.PANEL[:3]) + (238,),
                       rounding=px(4), parent=parent)
    for i, t in enumerate(lines):
        typeface.draw_text((x + px(6), y + px(3) + i * (size + px(3))), t, size,
                           color=(col or tuple(chrome.TEXT[:3]) + (255,)) if i == 0 else tuple(chrome.DIM[:3]) + (255,), parent=parent)
    return w, h


def size_text(g, part_index, a, b, W):
    """A part's size in words: a run's length (strips, rings, paths - LEDs
    one spacing apart each end), else its box ("30 x 20 cm")."""
    parts = g.params.get("parts") or []
    part = parts[part_index] if 0 <= part_index < len(parts) else {}
    P = W[a:b]
    if len(P) == 0:
        return ""
    k = shapes.copies(part)
    if k > 1:
        return f"{k} x {size_text_of(part, g.params)}"
    if part.get("kind") in shapes.LINEAR:
        seg = np.linalg.norm(np.diff(P, axis=0), axis=1) if len(P) > 1 else np.zeros(0)
        spacing = float(np.median(seg)) if len(seg) else 1.0
        return units.show(float(seg.sum()) + spacing, g.params)
    lo, hi = np.nanmin(P, 0), np.nanmax(P, 0)
    dims = [float(v) for v in (hi - lo)]
    shown = [d for d in dims if d > 1e-3]
    if not shown:
        return units.show(0.0, g.params)
    u = units.unit(g.params)
    nums = " x ".join(units.number(d, g.params) for d in shown)
    return f"{nums} {u}"


def size_text_of(part, sp):
    """One copy of a part in words: a run's length, else its box."""
    P, _ = shapes.transform(dict(part, reverse=False), *shapes.part_points(part))
    if part.get("kind") in shapes.LINEAR and len(P) > 1:
        seg = np.linalg.norm(np.diff(P, axis=0), axis=1)
        return units.show(float(seg.sum()) + float(np.median(seg)), sp)
    from native import shape_fields
    return shape_fields.box(part, sp)


def poll(app):
    """The overlay, redrawn each frame while the view shows a shape: the
    wiring (with the Shape frame open), the part under the pointer, the
    reference wireframes (always), the dragged LED's new place."""
    _poll_reference(app)
    if not dpg.does_item_exist("shape_dl"):
        return
    dpg.delete_item("shape_dl", children_only=True)
    app._shape_hover = None
    if not view3d.editing(app):
        return
    v = view(app)
    g = drawn(app)
    if v is None or g is None or g.kind != "shape":
        return
    from native import chrome, shape_ui
    D = "shape_dl"
    cov = covers(app)
    W, owner = wiring(g)
    n = len(W)
    if n == 0 or not (g.params.get("parts") or []):
        return
    sx, sy, ok, depth = project(v, W)
    good = visible(v, cov, sx, sy) & ok
    hidden = [k for k, q in enumerate(g.params.get("parts") or []) if q.get("hidden")]
    if hidden:
        good &= ~np.isin(owner, hidden)
    R = runs(owner)
    sel = shape_ui.selection(app)
    # the part under the pointer (for the colours next frame and the label now)
    mx, my, on = pointer(app)
    hit = pick(app, v, mx, my, g) if (on and clear(cov, mx, my)) else None
    app._shape_hover = hit
    # 1. the wiring along each part, arrows the way it runs - the selected part's in the text
    #    colour (its own colour is its LEDs', which would hide them), the rest in theirs, faint
    text = tuple(chrome.TEXT[:3])
    for k, (a, b) in R.items():
        mine = k in sel
        pc = tuple(int(c) for c in part_colour(k))
        col = text + (170,) if mine else pc + (80,)
        idx = np.arange(a, b)
        step = max(1, (b - a) // 1500)
        idx = idx[::step] if step > 1 else idx
        for piece in _pieces(sx[idx], sy[idx], good[idx]):
            dpg.draw_polyline(piece, color=col, thickness=1.4 if mine else 1.0, parent=D)
        # arrows every so far along the part's path on the screen
        seg = np.hypot(np.diff(sx[a:b]), np.diff(sy[a:b])) if b - a > 1 else np.zeros(0)
        total = float(seg[np.isfinite(seg)].sum()) if len(seg) else 0.0
        if total > px(28):
            every = max(px(46), total / 6.0)
            acc, nxt = 0.0, min(px(20), total * 0.25)
            for i in range(len(seg)):
                if not np.isfinite(seg[i]):
                    continue
                if not (good[a + i] and good[a + i + 1]):
                    acc += seg[i]
                    nxt = max(nxt, acc + px(10))            # a covered stretch: the next arrow waits for the part to show again
                    continue
                while seg[i] > 0 and acc + seg[i] >= nxt:
                    t = (nxt - acc) / seg[i]                 # 0..1 along this step: never back under what covers it
                    x = sx[a + i] + (sx[a + i + 1] - sx[a + i]) * t
                    y = sy[a + i] + (sy[a + i + 1] - sy[a + i]) * t
                    _chevron(x, y, sx[a + i + 1] - sx[a + i], sy[a + i + 1] - sy[a + i], px(6) if mine else px(5),
                             text + (255,) if mine else pc + (175,), D)
                    nxt += every
                acc += seg[i]
    # 2. IN at the first LED, END at the last; the boxes their words take, for the labels to keep off
    taken = []
    size = small()
    for i, word in ((0, "IN"), (n - 1, "END")):
        if not good[i]:
            continue
        col = tuple(int(c) for c in part_colour(int(owner[i]))) + (255,)
        r = px(8)
        dpg.draw_circle((sx[i], sy[i]), r, color=col, thickness=1.6, parent=D)
        tw = typeface.measure(word, "body", size)
        # the word on the side away from the part's next LED, so it does not sit on the wiring
        j = 1 if i == 0 else n - 2
        dx = sx[i] - sx[j] if 0 <= j < n and good[j] else -1.0
        tx = sx[i] + (r + px(3) if dx >= 0 else -(r + px(3) + tw))
        typeface.draw_text((tx, sy[i] - size / 2), word, size, color=col, parent=D)
        taken.append((min(tx, sx[i] - r), sy[i] - r, max(tx + tw, sx[i] + r), sy[i] + r))
    # 3. the leads between one part's last LED and the next's first: dashed, their length beside them
    order = sorted(R.items(), key=lambda kv: kv[1][0])
    lead_col = tuple(chrome.DIM[:3]) + (220,)
    for (k0, (a0, b0)), (k1, (a1, b1)) in zip(order, order[1:]):
        p, q = W[b0 - 1], W[a1]
        spacing = _spacing(W, a0, b0, a1, b1)
        gap = float(np.linalg.norm(q - p)) - spacing
        if gap <= JOIN:
            continue
        i, j = b0 - 1, a1
        if not (good[i] and good[j]):
            continue
        _dashed((sx[i], sy[i]), (sx[j], sy[j]), lead_col, D)
        txt = f"lead {units.show(gap, g.params)}"
        tw = typeface.measure(txt, "body", size)
        L = math.hypot(sx[j] - sx[i], sy[j] - sy[i]) or 1.0
        nx, ny = -(sy[j] - sy[i]) / L, (sx[j] - sx[i]) / L            # across the lead: the label beside it, not on it
        for t in (0.5, 0.35, 0.65, 0.2, 0.8):
            cx = sx[i] + (sx[j] - sx[i]) * t + nx * (size * 0.5 + px(6)) * (1 if ny <= 0 else -1)
            cy = sy[i] + (sy[j] - sy[i]) * t + ny * (size * 0.5 + px(6)) * (1 if ny <= 0 else -1)
            box = (cx - tw / 2 - 3, cy - size / 2 - 2, cx + tw / 2 + 3, cy + size / 2 + 2)
            if any(not (box[2] < q0 or box[0] > q2 or box[3] < q1 or box[1] > q3) for q0, q1, q2, q3 in taken):
                continue
            if not (v.inside(box[0], box[1]) and v.inside(box[2], box[3]) and clear(cov, box[0], box[1]) and clear(cov, box[2], box[3])):
                continue
            dpg.draw_rectangle(box[:2], box[2:], color=(0, 0, 0, 0), fill=tuple(chrome.BG[:3]) + (205,), rounding=3, parent=D)
            typeface.draw_text((cx - tw / 2, cy - size / 2), txt, size, color=tuple(chrome.TEXT[:3]) + (230,), parent=D)
            taken.append(box)
            break
    # 4. the part under the pointer, named
    if hit is not None:
        k, part = hit
        a, b = R.get(part, (k, k + 1))
        parts = g.params.get("parts") or []
        name = parts[part].get("name", parts[part].get("kind", "part")) if 0 <= part < len(parts) else "part"
        line1 = f"{name}  ·  LEDs {a}-{b - 1}  ·  {size_text(g, part, a, b, W)}"
        line2 = f"LED {k}  ·  {k - a + 1} of {b - a} in the part" + ("  ·  click to select" if part not in sel else "")
        _label(mx + px(16), my + px(12), [line1, line2], D, v.clip, col=tuple(int(c) for c in part_colour(part)) + (255,))
    # 5. the floor's step and the camera's keys, at the view's foot
    foot = []
    if app.prefs.get("view_floor", True):
        foot.append(f"grid {view3d.floor_label(app)}")
    foot.append(f"{units.density(g.params):g} LEDs a metre")
    keys = app.keys
    ks = [(keys.label("view_front"), "front"), (keys.label("view_side"), "side"), (keys.label("view_top"), "top"),
          (keys.label("view_ortho"), "ortho"), (keys.label("view_frame"), "frame")]
    hint = "   ".join(f"{k} {w}" for k, w in ks if k)
    size = small()
    a_, b_, c_, d_ = v.clip
    y = d_ - size - px(6)
    for text, x in ((" · ".join(foot), a_ + px(8)), (hint, None)):
        if not text:
            continue
        tw = typeface.measure(text, "body", size)
        x = x if x is not None else c_ - tw - px(8)
        if clear(cov, x, y) and clear(cov, x + tw, y + size):
            typeface.draw_text((x, y), text, size, color=tuple(chrome.DIM[:3]) + (230,), parent=D)
    # 5b. a mapped part's estimated LEDs (no two sides of the films saw them), ringed while it is selected
    amber = tuple(chrome.AMBER[:3]) + (230,)
    all_parts = g.params.get("parts") or []
    for k in sel:
        q = all_parts[k] if 0 <= k < len(all_parts) else None
        guess = (q or {}).get("guessed") or []
        if not guess or k not in R:
            continue
        a, b = R[k]
        m = min(b - a, shapes.local_count(q))
        for i in guess:
            if 0 <= i < m:
                w = (b - 1 - i) if q.get("reverse") else (a + i)
                if good[w]:
                    dpg.draw_circle((sx[w], sy[w]), px(7), color=amber, thickness=1.5, parent=D)
    # 6. the handles on the selection, a box, a join, a modal move's readout
    from native import shape_tools
    shape_tools.draw(app, v, D)
    # 7. a dragged LED's new place (by hand placing)
    to = getattr(app, "_shape_drag_to", None)
    if to is not None:
        tx, ty, tok, _ = project(v, np.asarray([to], np.float32))
        if tok[0]:
            X, Y = tx[0], ty[0]
            dpg.draw_line((X - 8, Y), (X + 8, Y), color=(255, 255, 255, 220), thickness=2, parent=D)
            dpg.draw_line((X, Y - 8), (X, Y + 8), color=(255, 255, 255, 220), thickness=2, parent=D)


def _spacing(W, a0, b0, a1, b1):
    """The LEDs' spacing at a lead's two ends: the distance past which a gap is a lead."""
    s = []
    if b0 - a0 > 1:
        s.append(float(np.linalg.norm(W[b0 - 1] - W[b0 - 2])))
    if b1 - a1 > 1:
        s.append(float(np.linalg.norm(W[a1 + 1] - W[a1])))
    return min(s) if s else 1.0


def _poll_reference(app):
    """The reference meshes as wireframes over the 3-D view, redrawn when
    the camera or the shape moves."""
    if not dpg.does_item_exist("ref_dl"):
        return
    v = view(app)
    from native import shape_ui
    parts = shape_ui._parts(app)
    segs = shapes.reference_segments(parts) if (v is not None and parts) else None
    cov = covers(app)
    key = None if segs is None or len(segs) == 0 else (round(app.yaw, 4), round(app.pitch, 4), round(app.dist, 3),
                                                       tuple(np.round(app.look, 4)), app.ortho, v.x0, v.y0, v.size,
                                                       float(v.frame[1]), tuple(np.round(v.frame[0], 4)), len(segs), id(parts), tuple(cov))
    if key == getattr(app, "_ref_key", "unset"):
        return
    app._ref_key = key
    dpg.delete_item("ref_dl", children_only=True)
    if key is None:
        return
    ax, ay, aok, _ = project(v, segs[:, 0])
    bx, by, bok, _ = project(v, segs[:, 1])
    col = (150, 160, 180, 110)
    for i in range(len(segs)):
        if aok[i] and bok[i] and v.inside(ax[i], ay[i]) and v.inside(bx[i], by[i]) \
                and clear(cov, ax[i], ay[i]) and clear(cov, bx[i], by[i]):
            dpg.draw_line((ax[i], ay[i]), (bx[i], by[i]), color=col, thickness=1, parent="ref_dl")
