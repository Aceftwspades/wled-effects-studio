"""The 3-D view's camera: a pan, an orthographic projection, views from the
front, the side and above, framing a selection or everything - and, while
the Shape frame is open, a frame held still, so a part moved at the edge of
the shape does not refit and rescale the whole view under the pointer.

The camera is the app's yaw, pitch and dist, as ever, plus `look` - the
point it circles, in the fitted -1..1 space the LEDs are drawn in - and
`ortho`. The axes are the shapes' (shapes.py): Z up; the front is seen
from -Y with X to the right; the right side from +X; above, X to the right
and Y up the screen.

    view3d.kw(app)                 # {"look", "ortho"}: what render.* and the GPU quads take
    view3d.frame(app)              # (centre, extent) the LEDs are fitted by
    view3d.cam(app, size)          # a render.Cam for the view at `size`
    view3d.pan(app, dx, dy)        # the pointer moved (dx, dy) px with the pan held
    view3d.preset(app, name)       # front, back, left, right, top, below, isometric - eased
    view3d.toggle_ortho(app)
    view3d.frame_points(app, pts)  # the view on these (the geometry's units)
    view3d.home(app)               # everything, as the view first had it
    view3d.floor_step(app)         # a shape's floor on round distances: (step, origin), or None
    view3d.poll(app)               # per frame: the easing, the buttons on the view
"""
import math
import time

import numpy as np
import dearpygui.dearpygui as dpg

from native import render, units
from native.typeface import px

HOME = (-0.6, 0.75, 4.6)                  # the view the studio opens with
DIST = (0.3, 14.0)                        # nearest and farthest the eye goes from what it circles
PITCH = math.pi / 2 - 1e-4                # straight down, less a hair (the camera's right stays X)
EASE = 0.22                               # seconds a preset or a framing takes to arrive

# name -> (yaw, pitch, orthographic): the shapes' axes (see the top)
PRESETS = {"front": (math.pi, 0.0, True), "back": (0.0, 0.0, True),
           "left": (-math.pi / 2, 0.0, True), "right": (math.pi / 2, 0.0, True),
           "top": (math.pi, PITCH, True), "below": (math.pi, -PITCH, True),
           "isometric": (HOME[0], HOME[1], False)}
BUTTONS = (("Front", "front", "view_front"), ("Side", "right", "view_side"), ("Top", "top", "view_top"))


def _state(app):
    if not hasattr(app, "look"):
        app.look = np.zeros(3)
        app.ortho = False
    return app


def kw(app):
    """The pan and the projection, as the render functions and the GPU quads take them."""
    _state(app)
    return {"look": app.look, "ortho": app.ortho}


def editing(app):
    """The Shape frame open on a shape: the view is for building then."""
    g = getattr(app.project, "geometry", None)
    return (g is not None and g.kind == "shape" and dpg.does_item_exist("shape_win") and dpg.is_item_shown("shape_win"))


# --- the frame the LEDs are fitted by ---------------------------------------------------------
def frame(app):
    """(centre, extent): the positions' own box, or - while building - the
    box held from when the Shape frame opened (eased to a new one when the
    shape outgrows it, or on Home)."""
    pos = app.view_positions()
    if not editing(app):
        app._frame_hold = None
        app._frame_ease = None
        return render.frame_of(pos)
    ease = getattr(app, "_frame_ease", None)
    if ease is not None:
        t = min(1.0, (time.perf_counter() - ease["t0"]) / ease["dur"])
        a, b = ease["a"], ease["b"]
        s = t * t * (3 - 2 * t)
        f = (a[0] + (b[0] - a[0]) * s, a[1] + (b[1] - a[1]) * s)
        if t >= 1.0:
            app._frame_ease = None
            app._frame_hold = b
        return (np.asarray(f[0], np.float32), float(f[1]))
    hold = getattr(app, "_frame_hold", None)
    if hold is None:
        hold = app._frame_hold = render.frame_of(pos)
    return hold


def refit(app, grow=False, animate=True):
    """The held frame fitted to the shape again - with `grow`, only when
    the shape has come out of it or shrunk to a fraction of it (a part
    added, a file imported; a part moved never refits)."""
    if not editing(app):
        return
    new = render.frame_of(app.view_positions())
    old = getattr(app, "_frame_hold", None)
    if old is None:
        app._frame_hold = new
        return
    if grow:
        pos = np.asarray(app.view_positions(), np.float32)
        pos = pos[np.isfinite(pos).all(1)]
        if len(pos):
            P = (pos - old[0]) / old[1]
            inside = float(np.abs(P).max()) <= 1.1
            if inside and new[1] > old[1] * 0.3:
                return
    if animate:
        app._frame_ease = {"t0": time.perf_counter(), "dur": EASE, "a": (np.asarray(old[0], np.float64), float(old[1])),
                           "b": (np.asarray(new[0], np.float64), float(new[1]))}
    else:
        app._frame_hold = new
    _ease_to(app, look=np.zeros(3))


def cam(app, size):
    _state(app)
    return render.Cam(app.yaw, app.pitch, app.dist, size, app.look, app.ortho)


def floor_step(app):
    """A shape's floor on round distances in its unit: (step, origin) in the
    fitted space - the lines every `step`, one through the world's origin -
    or None for any other geometry (the floor as it always was)."""
    g = app.project.geometry
    if g is None or g.kind != "shape":
        return None
    c, ext = frame(app)
    step = units.grid(g.params, ext)
    return step / ext, ((0.0 - float(c[0])) / ext, (0.0 - float(c[1])) / ext)


def floor_label(app):
    """The floor's step in words ("10 cm"), for a shape."""
    g = app.project.geometry
    if g is None or g.kind != "shape":
        return ""
    _, ext = frame(app)
    return units.show(units.grid(g.params, ext), g.params)


# --- moving the camera -----------------------------------------------------------------------
def pan(app, dx, dy):
    """The pointer moved (dx, dy) px with the pan held: what is under it
    follows it (at the depth of the point the camera circles)."""
    _state(app)
    _, R = render._camera(app.yaw, app.pitch, app.dist)
    size = max(60.0, float(getattr(app, "view_side", 400) or 400))
    f = (size * 0.5) / math.tan(math.radians(38.0) * 0.5)
    k = app.dist / f
    app.look = np.asarray(app.look, np.float64) + (-dx * R[0] + dy * R[1]) * k
    app._cam_ease = None


def zoom(app, notches):
    _state(app)
    app.dist = max(DIST[0], min(DIST[1], app.dist * math.exp(-notches * 0.06)))
    app._cam_ease = None


def orbit(app, yaw, pitch):
    """A turn by hand: the angles as given (pitch kept short of straight up
    or down); an orthographic view a preset made goes back to perspective,
    as it does in Blender - one made with its key stays."""
    _state(app)
    app.yaw, app.pitch = yaw, max(-PITCH, min(PITCH, pitch))
    app._cam_ease = None
    if app.ortho and getattr(app, "_ortho_auto", False):
        app.ortho = False
        app._ortho_auto = False
        refresh_buttons(app)


def _ease_to(app, yaw=None, pitch=None, dist=None, look=None, animate=True):
    """The camera eased to what is given; what is not keeps the target of an
    ease already under way (a view key then Home: both arrive)."""
    _state(app)
    a = (app.yaw, app.pitch, app.dist, np.asarray(app.look, np.float64))
    e = getattr(app, "_cam_ease", None)
    base = e["b"] if e is not None else a
    b = [base[0] if yaw is None else yaw, base[1] if pitch is None else pitch, base[2] if dist is None else dist,
         np.asarray(base[3], np.float64) if look is None else np.asarray(look, np.float64)]
    # the short way round
    b[0] = a[0] + ((b[0] - a[0] + math.pi) % (2 * math.pi) - math.pi)
    if not animate:
        app.yaw, app.pitch, app.dist, app.look = b[0], b[1], b[2], b[3]
        app._cam_ease = None
        return
    app._cam_ease = {"t0": time.perf_counter(), "dur": EASE, "a": a, "b": tuple(b)}


def preset(app, name, animate=True):
    """A named view: its angles eased to, orthographic for the six along
    the axes (perspective for the isometric), the pan kept."""
    _state(app)
    if name not in PRESETS:
        return
    yaw, pitch, ortho = PRESETS[name]
    app.ortho = ortho
    app._ortho_auto = ortho
    _ease_to(app, yaw, pitch, animate=animate)
    refresh_buttons(app)
    app.gp.status(f"view: {name}" + (" (orthographic)" if ortho else ""))


def toggle_ortho(app, on=None):
    _state(app)
    app.ortho = (not app.ortho) if on is None else bool(on)
    app._ortho_auto = False
    refresh_buttons(app)
    app.gp.status("orthographic: no perspective, sizes true across the view" if app.ortho else "perspective")


def home(app, animate=True):
    """Everything in view, as the studio opens it: the pan gone, the
    distance back, the held frame fitted to the shape again."""
    _state(app)
    if editing(app):
        refit(app, animate=animate)
    _ease_to(app, dist=HOME[2], look=np.zeros(3), animate=animate)


def frame_points(app, pts, animate=True):
    """The camera on these positions (the geometry's units): circling their
    middle, near enough that they fill most of the view."""
    _state(app)
    pts = np.asarray(pts, np.float64).reshape(-1, 3)
    pts = pts[np.isfinite(pts).all(1)]
    if len(pts) == 0:
        return
    c, ext = frame(app)
    P = (pts - np.asarray(c, np.float64)) / ext
    mid = (P.min(0) + P.max(0)) * 0.5
    r = max(0.06, float(np.linalg.norm(P - mid, axis=1).max()))
    d = r / math.sin(math.radians(38.0) * 0.5) * 1.12
    _ease_to(app, dist=max(DIST[0], min(DIST[1], d)), look=mid, animate=animate)


def saved(app):
    """The camera as a saved view keeps it: [yaw, pitch, dist, lx, ly, lz, ortho]."""
    _state(app)
    return [float(app.yaw), float(app.pitch), float(app.dist)] + [float(v) for v in app.look] + [1.0 if app.ortho else 0.0]


def restore(app, v):
    """A saved view back (three numbers from before the pan: no pan)."""
    _state(app)
    v = list(v)
    look = np.asarray(v[3:6], np.float64) if len(v) >= 6 else np.zeros(3)
    app.ortho = bool(v[6]) if len(v) >= 7 else False
    app._ortho_auto = False
    _ease_to(app, float(v[0]), float(v[1]), float(v[2]), look)
    refresh_buttons(app)


def poll(app):
    """Per frame, before anything draws: the camera's easing, and the
    buttons on the view kept at its top right."""
    _state(app)
    e = getattr(app, "_cam_ease", None)
    if e is not None:
        t = min(1.0, (time.perf_counter() - e["t0"]) / e["dur"])
        s = t * t * (3 - 2 * t)
        a, b = e["a"], e["b"]
        app.yaw = a[0] + (b[0] - a[0]) * s
        app.pitch = a[1] + (b[1] - a[1]) * s
        app.dist = a[2] + (b[2] - a[2]) * s
        app.look = a[3] + (b[3] - a[3]) * s
        if t >= 1.0:
            app._cam_ease = None
    place_buttons(app)


# --- the buttons on the view -------------------------------------------------------------------
def build_buttons(app, parent):
    """Front, Side, Top and the projection, at the 3-D view's top right
    (left of its grip; placed by poll)."""
    with dpg.group(horizontal=True, tag="view3d_btns", parent=parent, pos=(0, px(8))):
        for label, name, action in BUTTONS:
            dpg.add_button(label=label, small=True, tag=f"view3d_{name}", user_data=name,
                           callback=lambda s, a, u: preset(app, u))
            with dpg.tooltip(dpg.last_item()):
                dpg.add_text("", tag=f"view3d_{name}_tip")
        dpg.add_button(label="Persp", small=True, tag="view3d_ortho", callback=lambda: toggle_ortho(app))
        with dpg.tooltip("view3d_ortho"):
            dpg.add_text("", tag="view3d_ortho_tip")
    refresh_buttons(app)


def refresh_buttons(app):
    _state(app)
    if dpg.does_item_exist("menu_view_ortho"):
        dpg.set_value("menu_view_ortho", bool(app.ortho))
    if not dpg.does_item_exist("view3d_ortho"):
        return
    keys = getattr(app, "keys", None)
    lab = (lambda a: keys.label(a)) if keys is not None else (lambda a: "")
    tips = {"front": "from the front: X to the right, Z up", "right": "from the right side: Y to the right, Z up",
            "top": "from above: X to the right, Y up the screen"}
    for label, name, action in BUTTONS:
        k = lab(action)
        dpg.set_value(f"view3d_{name}_tip", f"{tips[name]} - orthographic" + (f"  ({k} over the view)" if k else ""))
    dpg.configure_item("view3d_ortho", label="Ortho" if app.ortho else "Persp")
    k = lab("view_ortho")
    dpg.set_value("view3d_ortho_tip", ("orthographic: no perspective, a size the same across the view - click for perspective"
                                       if app.ortho else "perspective - click for orthographic, sizes true across the view")
                  + (f"  ({k} over the view)" if k else ""))


def place_buttons(app):
    """At the view's top right, left of its grip, while the captions show
    and there is room; hidden otherwise."""
    if not dpg.does_item_exist("view3d_btns") or not dpg.does_item_exist("cube_win"):
        return
    w = dpg.get_item_rect_size("cube_win")[0] if dpg.is_item_shown("cube_win") else 0
    bw = dpg.get_item_rect_size("view3d_btns")[0] or px(190)
    show = bool(w) and getattr(app, "ui", True) and w >= bw + px(200)
    key = (int(w), int(bw), show)
    if key == getattr(app, "_view3d_btn_key", None):
        return
    app._view3d_btn_key = key
    dpg.configure_item("view3d_btns", show=show)
    if show:
        dpg.set_item_pos("view3d_btns", [int(w - bw - px(48)), px(8)])
