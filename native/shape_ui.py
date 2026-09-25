"""The Shape frame: the editor for a geometry built from parts.

One more of the dockable frames (device_ui does the header and the
docking). The frame edits the project's geometry when it is a `shape`:
the parts and their order (the wiring), each part's settings, position,
rotation and scale, mirrors and arrays, LEDs read from a mesh or an
xLights model, and LEDs placed by hand - click the 3-D view with "place"
on and an LED lands on the working plane; drag one to move it. The
selected part's LEDs are ringed in the 3-D view.

    build(app)            # the window, once (device_ui.build calls it)
    refresh(app)          # everything in it from the geometry
    poll(app)             # per frame: the rings round the selected part's LEDs
    click / drag / release(app)   # the 3-D view, when placing
"""
import os
import json
import math
import dearpygui.dearpygui as dpg

from native.typeface import px
from native import typeface
from native import form

from native import weight
import numpy as np

from native import shapes, shape_io, render
from native.geometry import Geometry

TAG = "shape_win"
MESH_MODES = (("edges", "LEDs along the edges"), ("vertices", "an LED per vertex"), ("surface", "LEDs over the surface"))


def _c():
    from native import chrome
    return chrome


def _parts(app):
    g = app.project.geometry
    return g.params.get("parts") if g.kind == "shape" else None


def _apply(app, parts=None, undo_from=None, **more):
    """The parts (and any other shape option) into a new geometry, with an
    undo step kept (`undo_from`: the params to go back to, when the
    geometry already moved on - a drag)."""
    g = app.project.geometry
    p = dict(g.params) if g.kind == "shape" else {}
    if parts is not None:
        p["parts"] = parts
    p.update(more)
    stack = getattr(app, "_shape_undo", None)
    if stack is None:
        stack = app._shape_undo = []
    stack.append(undo_from or json.dumps(g.params if g.kind == "shape" else {"parts": []}))
    del stack[:-40]
    was = g.kind
    app.apply_geometry(Geometry("shape", **p))
    if was != "shape" and dpg.does_item_exist("geom_kind"):
        dpg.set_value("geom_kind", "shape"); app.rebuild_geom_fields()
    refresh(app)


def undo(app):
    stack = getattr(app, "_shape_undo", None)
    if not stack:
        app.gp.status("nothing to undo in the shape"); return
    p = json.loads(stack.pop())
    app.apply_geometry(Geometry("shape", **p))
    refresh(app)


def _sel(app):
    parts = _parts(app) or []
    i = getattr(app, "_shape_sel", 0)
    return min(max(0, i), len(parts) - 1) if parts else -1


# --- build ---------------------------------------------------------------------------------
def build(app):
    c = _c()
    from native import device_ui
    with dpg.window(tag=TAG, show=False, width=px(560), height=px(640), no_collapse=True, no_title_bar=True):
        device_ui.header(app, "shape")
        with dpg.group(horizontal=True):
            c.info("A shape is a list of parts in wiring order. Units are LED pitches: a strip of pitch 1 has its LEDs one unit apart. "
                   "The selected part's LEDs are ringed in the 3-D view, its wiring drawn through them, its axis an arrow.")
            dpg.add_text("", tag="shape_desc", color=c.DIM, wrap=px(520))
        with dpg.group(horizontal=True):
            dpg.add_button(label="Undo", small=True, callback=lambda: undo(app))
            dpg.add_button(label="Clear", small=True, callback=lambda: _apply(app, parts=[]))
            weight.danger(dpg.last_item())
            dpg.add_button(label="Open...", small=True, callback=lambda: dpg.show_item("shape_open_dialog"))
            c.tip("a shape file (.shape.json) saved from here")
            dpg.add_button(label="Save...", small=True, callback=lambda: dpg.show_item("shape_save_dialog"))
            weight.primary(dpg.last_item())
            dpg.add_button(label="Export .xmodel...", small=True, callback=lambda: dpg.show_item("shape_xmodel_dialog"))
            c.tip("the shape as an xLights custom model, the wiring as its node numbers")
            dpg.add_button(label="Export positions...", small=True, callback=lambda: dpg.show_item("shape_points_dialog"))
            c.tip("every LED as a CSV row - x, y, z, its wiring index, its part - in wiring order, for any other tool; "
                  "Import... reads the file back as a points part")
        with dpg.group(horizontal=True):
            typeface.label(dpg.add_text("PARTS", color=c.ACCENT))
            dpg.add_combo(["strip", "grid"], tag="shape_layout", width=px(70), default_value="strip",
                          callback=lambda s, v: _apply(app, layout=v))
            c.tip("the logical layout the effects see: one strip in wiring order, or a grid seen from the front")
            dpg.add_button(label="Segment per part", small=True, callback=lambda: segments_per_part(app))
            c.tip("each part its own WLED segment - effect, palette, sliders - up to eight")
        kinds = [k for k in shapes.KINDS if k != "reference"]
        for row in (kinds[:5], kinds[5:]):
            with dpg.group(horizontal=True):
                for k in row:
                    dpg.add_button(label="+ " + k, small=True, width=px(100), user_data=k, callback=lambda s, a, u: add_part(app, u))
                    c.tip(shapes.KINDS[k][1])
        with dpg.group(horizontal=True):
            dpg.add_button(label="Import...", small=True, callback=lambda: dpg.show_item("shape_import_dialog"))
            c.tip("a mesh or model as LEDs: .obj, .ply, .stl from Blender or CAD; an xLights .xmodel, or a whole xLights layout "
                  "(xlights_rgbeffects.xml: every model a part, where it stands); an x y z [index] point list (CSV, text, JSON)")
            dpg.add_combo([m[1] for m in MESH_MODES], tag="shape_mesh_mode", width=px(170), default_value=MESH_MODES[0][1])
            c.tip("how a mesh becomes LEDs: one every pitch along its edges, one at each vertex, or spread over its surface")
            form.inline("pitch")
            typeface.mono(dpg.add_input_float(tag="shape_mesh_pitch", width=px(70), default_value=1.0, step=0, format="%.2f"))
            c.tip("the LED spacing along the edges or over the surface, in the model's units")
            dpg.add_button(label="Reference...", small=True,
                           callback=lambda: (setattr(app, "_shape_ref", True), dpg.show_item("shape_import_dialog")))
            c.tip("a mesh drawn in the 3-D view to place LEDs against, not LEDs: the tree, the house, the enclosure")
        with dpg.child_window(tag="shape_parts", height=px(110), border=True):
            pass
        with dpg.group(horizontal=True):
            typeface.label(dpg.add_text("PART", tag="shape_part_title", color=c.ACCENT))
            dpg.add_text("", tag="shape_part_kind", color=c.DIM)
        with dpg.child_window(tag="shape_fields", height=-30, border=False):
            pass
        # PREVIEW: a turntable of the shape, rendered off screen, looping here and saved as a GIF - folded away until wanted
        with dpg.collapsing_header(label="PREVIEW", tag="shape_prev_hdr", default_open=False):
            with dpg.group(horizontal=True):
                dpg.add_combo(["effect", "parts", "wiring"], tag="shape_prev_mode", width=px(90), default_value="effect")
                c.tip("lit by the effect the sim runs, or each part in a colour of its own, or a chase along the wiring")
                dpg.add_input_float(tag="shape_prev_secs", width=px(60), default_value=4.0, step=0, format="%.0f s")
                dpg.add_button(label="Generate a preview", tag="shape_prev_go", small=True, callback=lambda: generate_preview(app))
                c.tip("a turn of the shape, rendered off screen: a GIF and a PNG in the project's export folder, looping here")
                dpg.add_button(label="Open the folder", small=True, callback=lambda: app.reveal(os.path.join(app.project.path, "export")))
            dpg.add_text("", tag="shape_prev_status", color=c.DIM, wrap=0)
            with dpg.group(tag="shape_prev_img"):
                pass
    # the file dialogs: a mesh or model in, a shape file in or out
    with dpg.file_dialog(directory_selector=False, show=False, tag="shape_import_dialog", width=px(640), height=px(420),
                         callback=lambda s, a: import_file(app, a.get("file_path_name", ""))):
        for ext, col in ((".obj", (120, 200, 120)), (".ply", (120, 200, 120)), (".stl", (120, 200, 120)),
                         (".xmodel", (200, 180, 90)), (".xml", (200, 180, 90)), (".csv", (150, 150, 220)), (".txt", (150, 150, 220)), (".json", (150, 150, 220))):
            dpg.add_file_extension(ext, color=col)
    with dpg.file_dialog(directory_selector=False, show=False, tag="shape_open_dialog", width=px(640), height=px(420),
                         callback=lambda s, a: open_shape(app, a.get("file_path_name", ""))):
        dpg.add_file_extension(".shape.json", color=(150, 150, 220))
        dpg.add_file_extension(".json", color=(150, 150, 220))
    with dpg.file_dialog(directory_selector=False, show=False, tag="shape_xmodel_dialog", width=px(640), height=px(420),
                         default_filename="shape.xmodel", callback=lambda s, a: export_xmodel(app, a.get("file_path_name", ""))):
        dpg.add_file_extension(".xmodel", color=(200, 180, 90))
    with dpg.file_dialog(directory_selector=False, show=False, tag="shape_points_dialog", width=px(640), height=px(420),
                         default_filename="positions.csv", callback=lambda s, a: export_points(app, a.get("file_path_name", ""))):
        dpg.add_file_extension(".csv", color=(120, 200, 120))
    with dpg.file_dialog(directory_selector=False, show=False, tag="shape_save_dialog", width=px(640), height=px(420),
                         default_filename="shape.shape.json", callback=lambda s, a: save_shape(app, a.get("file_path_name", ""))):
        dpg.add_file_extension(".json", color=(150, 150, 220))


# --- the parts list and the selected part's fields ------------------------------------------
def refresh(app):
    if not dpg.does_item_exist("shape_parts"):
        return
    c = _c()
    g = app.project.geometry
    parts = _parts(app)
    dpg.delete_item("shape_parts", children_only=True)
    dpg.delete_item("shape_fields", children_only=True)
    if parts is None:
        dpg.set_value("shape_desc", "the geometry is not a shape: choose 'shape' under GEOMETRY in the panel, or add a part below to start one")
        dpg.set_value("shape_part_title", "")
        return
    dpg.set_value("shape_desc", g.describe())
    dpg.set_value("shape_layout", g.params.get("layout", "strip"))
    sel = _sel(app)
    marks = _marks(app)
    for i, part in enumerate(parts):
        n = shapes.part_count(part)
        with dpg.group(horizontal=True, parent="shape_parts"):
            dpg.add_checkbox(default_value=(i in marks), user_data=i,
                             callback=lambda s, a, u: (marks.add(u) if a else marks.discard(u), _arrange_hint(app)))
            dpg.add_selectable(label=f"{i + 1:2d}  {part.get('name', part['kind'])}", width=px(190), default_value=(i == sel), user_data=i,
                               callback=lambda s, a, u: (setattr(app, "_shape_sel", u), refresh(app)))
            typeface.small(dpg.add_text(f"{part['kind']}, {n} LEDs", color=c.DIM))
            dpg.add_button(label="up", small=True, user_data=i, callback=lambda s, a, u: move_part(app, u, -1), show=i > 0)
            dpg.add_button(label="down", small=True, user_data=i, callback=lambda s, a, u: move_part(app, u, 1), show=i < len(parts) - 1)
            dpg.add_button(label="copy", small=True, user_data=i, callback=lambda s, a, u: dup_part(app, u))
            dpg.add_button(label="x", small=True, user_data=i, callback=lambda s, a, u: del_part(app, u))
            weight.danger(dpg.last_item())
    if not parts:
        dpg.add_text("no parts yet: + one above, import a file, or place LEDs by hand", parent="shape_parts", color=c.DIM)
    if sel < 0:
        dpg.set_value("shape_part_title", ""); dpg.set_value("shape_part_kind", "")
        return
    part = parts[sel]
    kind = shapes.KINDS.get(part["kind"], ({}, f"unknown kind {part['kind']!r} - no LEDs"))
    dpg.set_value("shape_part_title", f"PART {sel + 1}: {part.get('name', part['kind'])}")
    _arrange_hint(app)
    dpg.set_value("shape_part_kind", f"- {part['kind']}, {shapes.part_count(part)} LEDs")
    P = "shape_fields"
    with form.row("name", parent=P):
        dpg.add_input_text(width=px(200), default_value=str(part.get("name", "")), on_enter=True,
                           callback=lambda s, v: set_part(app, sel, name=v))
    if part["kind"] == "reference":
        dpg.add_text(f"{part['params'].get('file', '?')}: {len(part['params'].get('vertices') or [])} vertices, "
                     f"{len(part['params'].get('edges') or [])} edges - drawn in the 3-D view, not LEDs", parent=P, color=c.DIM, wrap=0)
    HINT = {"n": "LEDs", "per_side": "LEDs a side", "per_edge": "LEDs an edge", "sides": "sides", "pitch": "pitch",
            "radius": "radius", "start_deg": "start angle", "w": "wide", "h": "high", "B": "a face edge"}
    TIPS = {"pitch": "the LED spacing, in the shape's units", "radius": "0: sized so the LEDs sit a pitch apart",
            "start_deg": "degrees round from +X to the first LED (or corner)", "w": "LEDs", "h": "LEDs", "B": "LEDs along a face's edge",
            "serpentine": "every other row runs back the other way", "vertical": "the rows run up and down", "six": "the bottom face too"}
    for key, default in kind[0].items():
        if key in ("points", "normals", "vertices", "edges", "file"):
            continue
        val = part["params"].get(key, default)
        label = HINT.get(key, key)
        tip = TIPS.get(key) if not (key == "radius" and part["kind"] == "polyhedron") else None
        if isinstance(default, bool):
            form.check(key, parent=P, default_value=bool(val), user_data=key,
                       callback=lambda s, v, u: set_param(app, sel, u, bool(v)))
            if tip:
                c.tip(tip)
            continue
        with form.row(label, parent=P, tip=tip):
            if isinstance(default, str):
                dpg.add_combo(shapes.CHOICES.get(key, [str(val)]), width=px(140), default_value=str(val), user_data=key,
                              callback=lambda s, v, u: set_param(app, sel, u, str(v)))
            elif isinstance(default, int):
                dpg.add_input_int(width=px(110), default_value=int(val), min_value=1, max_value=4096, min_clamped=True,
                                  on_enter=True, user_data=key, callback=lambda s, v, u: set_param(app, sel, u, int(v)))
            else:
                dpg.add_input_float(width=px(110), default_value=float(val), step=0, format="%.2f",
                                    on_enter=True, user_data=key, callback=lambda s, v, u: set_param(app, sel, u, float(v)))
    if part["kind"] == "polyline":
        # the count as a field too: the pitch follows (LEDs at both ends)
        n = shapes.part_count(part)
        with form.row("LEDs", parent=P, tip="the count sets the pitch: LEDs at both ends"):
            dpg.add_input_int(width=px(110), default_value=n, min_value=2, max_value=4096, min_clamped=True,
                              on_enter=True, callback=lambda s, v: set_polyline_count(app, sel, int(v)))
    if part["kind"] == "polyhedron":
        with dpg.group(horizontal=True, parent=P):
            dpg.add_button(label="split into parts", small=True, callback=lambda: split_polyhedron(app, sel))
            c.tip("a strip per edge (or a polygon per face, in faces mode), the LEDs where they were - each then moved, turned and counted alone")
    if part["kind"] in ("points", "polyline"):
        pts = part["params"].get("points") or []
        dpg.add_text(f"{len(pts)} point(s)" + (" - place more: tick 'place', click the 3-D view" if part["kind"] == "points" else " on the path"),
                     parent=P, color=c.DIM)
        with dpg.group(horizontal=True, parent=P):
            dpg.add_button(label="delete the last", small=True, callback=lambda: pop_point(app, sel))
            weight.danger(dpg.last_item())
            dpg.add_button(label="renumber: nearest chain from the first", small=True, callback=lambda: chain_part(app, sel))
            if part["kind"] == "points":
                dpg.add_button(label="turn into a path", small=True, callback=lambda: set_part(app, sel, kind="polyline"))
    with dpg.group(horizontal=True, parent=P):
        typeface.label(dpg.add_text("PLACE", color=c.ACCENT))
        c.info("drag a number and the part moves in the 3-D view as you drag; the sim takes the shape when you let go; ctrl-click to type")
    with form.row("position", parent=P, tip="x, y and z"):
        dpg.add_drag_floatx(width=px(240), size=3, default_value=list(part.get("pos", [0, 0, 0])) + [0.0], format="%.2f",
                            speed=0.05, callback=lambda s, v: nudge(app, sel, pos=[float(x) for x in v[:3]]))
    with form.row("rotation", parent=P, tip="about x, y and z, in degrees"):
        dpg.add_drag_floatx(width=px(240), size=3, default_value=list(part.get("rot", [0, 0, 0])) + [0.0], format="%.1f°",
                            speed=0.5, callback=lambda s, v: nudge(app, sel, rot=[float(x) for x in v[:3]]))
    sc = part.get("scale", 1.0)
    with form.row("scale", parent=P):
        dpg.add_drag_float(width=px(110), default_value=float(sc if not isinstance(sc, list) else sc[0]), format="%.2f×",
                           speed=0.01, min_value=0.01, max_value=100.0, clamped=True, callback=lambda s, v: nudge(app, sel, scale=float(v)))
    form.check("reverse the wiring of this part", parent=P, default_value=bool(part.get("reverse")),
               callback=lambda s, v: set_part(app, sel, reverse=bool(v)))
    # AIM: the part's axis along a direction, at a distance from the origin -
    # the way to build round a ball: a polygon per face, each aimed outward
    ax = shapes.axis_of(part)
    axname = {(1.0, 0.0, 0.0): "its length", (0.0, -1.0, 0.0): "its face"}.get(tuple(ax), "its normal (+Z)")
    ppos = np.asarray(part.get("pos", [0, 0, 0]), np.float64); dist = float(np.linalg.norm(ppos))
    d0 = (ppos / dist) if dist > 1e-6 else np.array([0.0, 0.0, 1.0])
    with dpg.group(horizontal=True, parent=P):
        typeface.label(dpg.add_text("AIM", color=c.ACCENT))
        c.info(f"point {axname} along the direction (x y z, or azimuth and elevation, or an axis button). 'aim outward' also puts the part "
               "the distance from the origin along it; 'turn only' keeps its place; 'aim at the origin' points it inward from where it is. "
               "Spin turns it about the direction. The yellow arrow in the 3-D view is the axis.")
    with form.row("direction", parent=P, tip="x, y and z - or its azimuth and elevation, in degrees"):
        dpg.add_input_floatx(tag="shape_aim_dir", width=px(200), size=3, default_value=[float(v) for v in d0] + [0.0], format="%.3f",
                             callback=lambda s, v: _dir_to_angles(v))
        az, el = _angles_of(d0)
        form.inline("az")
        dpg.add_input_float(tag="shape_aim_az", width=px(70), default_value=az, step=0, format="%.1f°", callback=lambda: _angles_to_dir())
        form.inline("el")
        dpg.add_input_float(tag="shape_aim_el", width=px(70), default_value=el, step=0, format="%.1f°", callback=lambda: _angles_to_dir())
    with form.row("distance", parent=P, tip="from the origin, for 'aim outward'"):
        dpg.add_input_float(tag="shape_aim_dist", width=px(80), default_value=dist, step=0, format="%.2f")
        form.inline("spin")
        dpg.add_input_float(tag="shape_aim_spin", width=px(70), default_value=0.0, step=0, format="%.1f°")
        c.tip("a turn about the direction, in degrees")
        for lbl, v in (("+X", (1, 0, 0)), ("-X", (-1, 0, 0)), ("+Y", (0, 1, 0)), ("-Y", (0, -1, 0)), ("+Z", (0, 0, 1)), ("-Z", (0, 0, -1))):
            dpg.add_button(label=lbl, small=True, user_data=v, callback=lambda s, a, u: _set_dir(u))
    with dpg.group(horizontal=True, parent=P):
        dpg.add_button(label="aim outward", small=True, callback=lambda: aim_part(app, sel, "outward"))
        dpg.add_button(label="turn only", small=True, callback=lambda: aim_part(app, sel, "turn"))
        dpg.add_button(label="aim at the origin", small=True, callback=lambda: aim_part(app, sel, "origin"))
        dpg.add_button(label="from its place", small=True, callback=lambda: _set_dir(list(d0), dist))
        c.tip("the direction and distance the part is at now, into the fields")
    with dpg.group(horizontal=True, parent=P):
        typeface.label(dpg.add_text("ARRANGE", color=c.ACCENT))
        dpg.add_text("", tag="shape_arrange_hint", color=c.DIM)
        dpg.add_text("align", color=c.DIM)
        for ax, lbl in enumerate("XYZ"):
            dpg.add_button(label=lbl, small=True, user_data=ax, callback=lambda s, a, u: align_parts(app, u))
        c.tip("the ticked parts given this part's position on that axis")
        dpg.add_text("  spread", color=c.DIM)
        for ax, lbl in enumerate("XYZ"):
            dpg.add_button(label=lbl, small=True, user_data=ax, callback=lambda s, a, u: distribute_parts(app, u))
        c.tip("the ticked parts (three or more) spaced evenly along that axis between the two farthest apart")
        dpg.add_button(label="same scale", small=True, callback=lambda: match_parts(app, "scale"))
        dpg.add_button(label="same turn", small=True, callback=lambda: match_parts(app, "rot"))
        c.tip("the ticked parts given this part's scale, or its rotation")
        dpg.add_button(label="tick all", small=True, callback=lambda: (_marks(app).update(range(len(_parts(app) or []))), refresh(app)))
        dpg.add_button(label="none", small=True, callback=lambda: (_marks(app).clear(), refresh(app)))
    with dpg.group(horizontal=True, parent=P):
        dpg.add_text("mirror", color=c.DIM)
        for ax, lbl in enumerate("XYZ"):
            dpg.add_button(label=lbl, small=True, user_data=ax, callback=lambda s, a, u: mirror_part(app, sel, u))
        dpg.add_text("  array", color=c.DIM)
        typeface.mono(dpg.add_input_int(tag="shape_array_n", width=px(96), default_value=3, min_value=2, max_value=64, min_clamped=True))
        c.tip("copies, this one included")
        form.inline("apart")
        typeface.mono(dpg.add_input_floatx(tag="shape_array_off", width=px(180), size=3, default_value=[10.0, 0.0, 0.0, 0.0], format="%.1f"))
        c.tip("each copy moved by this x, y and z from the one before")
        dpg.add_button(label="make", small=True, callback=lambda: array_part(app, sel))
    dpg.add_separator(parent=P)
    with dpg.group(horizontal=True, parent=P):
        typeface.label(dpg.add_text("BY HAND", color=c.ACCENT))
        dpg.add_checkbox(label="place", tag="shape_place", default_value=bool(getattr(app, "_shape_place", False)),
                         callback=lambda s, v: setattr(app, "_shape_place", bool(v)))
        c.tip("click the 3-D view to put an LED on the plane; they go into the selected points part, or a new one; drag one to move it")
        dpg.add_text("plane", color=c.DIM)
        dpg.add_combo(["z", "y", "x"], tag="shape_plane_axis", width=px(50), default_value=getattr(app, "_shape_plane", ("z", 0.0))[0],
                      callback=lambda s, v: setattr(app, "_shape_plane", (v, getattr(app, "_shape_plane", ("z", 0.0))[1])))
        dpg.add_text("=", color=c.DIM)
        typeface.mono(dpg.add_input_float(tag="shape_plane_v", width=px(70), default_value=getattr(app, "_shape_plane", ("z", 0.0))[1], step=0, format="%.1f",
                                          callback=lambda s, v: setattr(app, "_shape_plane", (getattr(app, "_shape_plane", ("z", 0.0))[0], float(v)))))


# --- edits -----------------------------------------------------------------------------------
def add_part(app, kind):
    parts = list(_parts(app) or [])
    part = shapes.new_part(kind)
    part["name"] = f"{kind} {sum(1 for p in parts if p['kind'] == kind) + 1}"
    if parts:
        # a new part beside the last, not on top of it: the last's right edge, a gap, the new one's left edge
        last = parts[-1]
        def half_x(q):
            pts = shapes.part_points(q)[0]
            sc = q.get("scale", 1.0); sc = sc[0] if isinstance(sc, list) else sc
            return float(np.abs(pts[:, 0]).max()) * float(sc) if len(pts) else 0.0
        part["pos"] = [float(last.get("pos", [0, 0, 0])[0]) + half_x(last) + half_x(part) + 2.0,
                       float(last.get("pos", [0, 0, 0])[1]), float(last.get("pos", [0, 0, 0])[2])]
    parts.append(part)
    app._shape_sel = len(parts) - 1
    _apply(app, parts)


def del_part(app, i):
    parts = list(_parts(app) or [])
    if 0 <= i < len(parts):
        parts.pop(i)
        app._shape_sel = min(i, len(parts) - 1)
        _apply(app, parts)


def dup_part(app, i):
    parts = list(_parts(app) or [])
    if 0 <= i < len(parts):
        q = json.loads(json.dumps(parts[i]))
        q["name"] = q.get("name", q["kind"]) + " copy"
        parts.insert(i + 1, q)
        app._shape_sel = i + 1
        _apply(app, parts)


def move_part(app, i, d):
    parts = list(_parts(app) or [])
    j = i + d
    if 0 <= i < len(parts) and 0 <= j < len(parts):
        parts[i], parts[j] = parts[j], parts[i]
        app._shape_sel = j
        _apply(app, parts)


def set_part(app, i, **fields):
    parts = json.loads(json.dumps(_parts(app) or []))
    if 0 <= i < len(parts):
        if fields.get("kind") == "polyline":
            parts[i]["params"] = {"points": parts[i]["params"].get("points", []), "pitch": 1.0}
        parts[i].update(fields)
        _apply(app, parts)


def nudge(app, i, **fields):
    """A drag: the part moved in the view at once (the same LED count, so
    the engine needs nothing), the full apply when the mouse lets go."""
    parts = json.loads(json.dumps(_parts(app) or []))
    if not (0 <= i < len(parts)):
        return
    parts[i].update(fields)
    g = app.project.geometry
    if getattr(app, "_shape_pending", None) is None:
        app._shape_pre = json.dumps(g.params)               # the undo step: where the drag started
    app._shape_pending = parts
    try:
        g2 = Geometry("shape", **dict(g.params, parts=parts))
        if g2.count == g.count:
            app.project.geometry = g2                        # the views draw project.geometry
            return
    except Exception:
        pass
    _poll_pending(app, force=True)


def _poll_pending(app, force=False):
    parts = getattr(app, "_shape_pending", None)
    if parts is None:
        return
    if not force and dpg.is_mouse_button_down(dpg.mvMouseButton_Left):
        return
    app._shape_pending = None
    pre = getattr(app, "_shape_pre", None); app._shape_pre = None
    _apply(app, parts, undo_from=pre)


def set_polyline_count(app, i, n):
    """A path's LED count: the pitch that gives it, LEDs at both ends."""
    parts = json.loads(json.dumps(_parts(app) or []))
    if 0 <= i < len(parts) and parts[i]["kind"] == "polyline":
        pts = np.asarray(parts[i]["params"].get("points") or [[0, 0, 0]], np.float32).reshape(-1, 3)
        total = float(np.linalg.norm(np.diff(pts, axis=0), axis=1).sum()) if len(pts) > 1 else 0.0
        if total > 0 and n >= 2:
            parts[i]["params"]["pitch"] = round(total / (n - 1) - 1e-6, 5)
            _apply(app, parts)


def split_polyhedron(app, i):
    parts = json.loads(json.dumps(_parts(app) or []))
    if 0 <= i < len(parts) and parts[i]["kind"] == "polyhedron":
        pieces = shapes.split_part(parts[i])
        parts[i:i + 1] = pieces
        app._shape_sel = i
        _apply(app, parts)
        app.gp.status(f"split into {len(pieces)} parts, the LEDs where they were")


def _angles_of(d):
    """(azimuth, elevation) degrees of a direction: az round Z from +X, el up from the X-Y plane."""
    d = np.asarray(d, np.float64); L = np.linalg.norm(d)
    if L < 1e-9:
        return 0.0, 90.0
    d = d / L
    return round(math.degrees(math.atan2(d[1], d[0])), 1), round(math.degrees(math.asin(max(-1.0, min(1.0, d[2])))), 1)


def _dir_to_angles(v):
    az, el = _angles_of(list(v)[:3])
    dpg.set_value("shape_aim_az", az); dpg.set_value("shape_aim_el", el)


def _angles_to_dir():
    az, el = math.radians(dpg.get_value("shape_aim_az")), math.radians(dpg.get_value("shape_aim_el"))
    dpg.set_value("shape_aim_dir", [math.cos(el) * math.cos(az), math.cos(el) * math.sin(az), math.sin(el), 0.0])


def _set_dir(v, dist=None):
    dpg.set_value("shape_aim_dir", [float(x) for x in v[:3]] + [0.0]); _dir_to_angles(v)
    if dist is not None:
        dpg.set_value("shape_aim_dist", float(dist))


def aim_part(app, i, how):
    """The part's axis along the AIM direction: "outward" also moves it to
    the distance along it, "turn" keeps its place, "origin" points the
    axis at the origin from where it is."""
    parts = json.loads(json.dumps(_parts(app) or []))
    if not (0 <= i < len(parts)):
        return
    d = [float(x) for x in list(dpg.get_value("shape_aim_dir"))[:3]]
    spin = float(dpg.get_value("shape_aim_spin") or 0.0)
    if how == "origin":
        d = [-float(x) for x in parts[i].get("pos", [0, 0, 0])]
        if np.linalg.norm(d) < 1e-9:
            app.gp.status("the part is at the origin: nothing to aim at"); return
    if np.linalg.norm(d) < 1e-9:
        app.gp.status("a direction of zero: type one, or pick an axis"); return
    parts[i] = shapes.aimed(parts[i], d, float(dpg.get_value("shape_aim_dist")) if how == "outward" else None, spin)
    _apply(app, parts)


def set_param(app, i, key, value):
    parts = json.loads(json.dumps(_parts(app) or []))
    if 0 <= i < len(parts):
        parts[i]["params"][key] = value
        _apply(app, parts)


def _marks(app):
    """The parts ticked for the arrange tools: a set of indices."""
    m = getattr(app, "_shape_marks", None)
    if m is None:
        m = app._shape_marks = set()
    return m


def _arrange_hint(app):
    if dpg.does_item_exist("shape_arrange_hint"):
        n = len(_marks(app))
        dpg.set_value("shape_arrange_hint", f"{n} ticked" if n else "tick parts in the list")


def _marked(app):
    parts = _parts(app) or []
    return sorted(i for i in _marks(app) if 0 <= i < len(parts))


def align_parts(app, axis):
    idxs = _marked(app)
    if not idxs:
        app.gp.status("tick the parts to align, in the list"); return
    _apply(app, shapes.aligned(_parts(app), idxs, _sel(app), axis))
    app.gp.status(f"{len(idxs)} part(s) aligned on {'xyz'[axis]} to part {_sel(app) + 1}")


def distribute_parts(app, axis):
    idxs = _marked(app)
    if len(idxs) < 3:
        app.gp.status("tick three parts or more to spread them"); return
    _apply(app, shapes.distributed(_parts(app), idxs, axis))
    app.gp.status(f"{len(idxs)} parts spread evenly along {'xyz'[axis]}")


def match_parts(app, what):
    idxs = _marked(app)
    if not idxs:
        app.gp.status("tick the parts to match, in the list"); return
    _apply(app, shapes.matched(_parts(app), idxs, _sel(app), what))
    app.gp.status(f"{len(idxs)} part(s) given part {_sel(app) + 1}'s {'turn' if what == 'rot' else 'scale'}")


def mirror_part(app, i, axis):
    parts = list(_parts(app) or [])
    if 0 <= i < len(parts):
        parts.insert(i + 1, shapes.mirrored(parts[i], axis))
        app._shape_sel = i + 1
        _apply(app, parts)


def array_part(app, i):
    parts = list(_parts(app) or [])
    if 0 <= i < len(parts):
        n = int(dpg.get_value("shape_array_n")); off = list(dpg.get_value("shape_array_off"))[:3]
        parts[i + 1:i + 1] = shapes.arrayed(parts[i], n, off)
        _apply(app, parts)


def pop_point(app, i):
    parts = json.loads(json.dumps(_parts(app) or []))
    if 0 <= i < len(parts) and parts[i]["params"].get("points"):
        parts[i]["params"]["points"].pop()
        nr = parts[i]["params"].get("normals")
        if nr:
            nr.pop()
        _apply(app, parts)


def chain_part(app, i):
    parts = json.loads(json.dumps(_parts(app) or []))
    if 0 <= i < len(parts) and parts[i]["params"].get("points"):
        pts = np.asarray(parts[i]["params"]["points"], np.float32)
        order = shapes.chain_order(pts, 0)
        parts[i]["params"]["points"] = pts[order].tolist()
        nr = parts[i]["params"].get("normals")
        if nr and len(nr) == len(pts):
            parts[i]["params"]["normals"] = np.asarray(nr, np.float32)[order].tolist()
        _apply(app, parts)


def segments_per_part(app):
    """The sim's segments set to the parts: on the strip layout each part is
    a run of LEDs, so segment k is part k's range (the first eight)."""
    g = app.project.geometry
    parts = _parts(app)
    if not parts:
        return
    if g.params.get("layout") == "grid":
        app.gp.status("segments per part need the strip layout (a part is a run of LEDs there; on the grid the parts interleave)"); return
    counts = [shapes.part_count(p) for p in parts]
    if len(counts) > 8:
        app.gp.status(f"{len(counts)} parts: the first eight get segments")
    app.eng.seg_truncate(1)
    start = 0
    for k, n in enumerate(counts[:8]):
        app.eng.seg_config(k, start, 0, start + n, 1, 255)
        start += n
    app.eng.seg_select(0)
    app.save_segments()
    dpg.set_value("fx_combo", app.eng.names[app.eng.idx])
    app.rebuild_params(); app.sync_palette_combo(); app.rebuild_seg_fields()
    app.gp.status(f"{min(8, len(counts))} segments, one per part: pick each in SEGMENTS and give it an effect")


# --- the preview -----------------------------------------------------------------------------
def generate_preview(app, mode=None, seconds=None):
    """The turntable rendered on a worker; shown and saved when it is done."""
    import threading
    from native import shape_preview
    if getattr(app, "_prev_job", None) is not None and app._prev_job.is_alive():
        return
    if dpg.does_item_exist("shape_prev_hdr"):
        dpg.set_value("shape_prev_hdr", True)                # the View menu's "Generate a preview" lands here folded
    mode = mode or dpg.get_value("shape_prev_mode")
    seconds = float(seconds or dpg.get_value("shape_prev_secs") or 4.0)
    seconds = max(1.0, min(20.0, seconds))
    dpg.set_value("shape_prev_status", f"rendering a {seconds:.0f} s turn ({mode})...")
    dpg.configure_item("shape_prev_go", enabled=False)
    app._prev_result = None

    def work():
        try:
            frames = shape_preview.turntable(app, mode, seconds, 15, 320, 1.0, log=lambda m: None)
            paths = shape_preview.save(app, frames, 15)
            app._prev_result = (frames, paths, None)
        except Exception as e:
            app._prev_result = (None, None, str(e))
    app._prev_job = threading.Thread(target=work, daemon=True); app._prev_job.start()


def _poll_preview(app):
    """The finished preview into the frame: a looping texture, the paths."""
    res = getattr(app, "_prev_result", None)
    if res is not None:
        app._prev_result = None
        frames, paths, err = res
        if dpg.does_item_exist("shape_prev_go"):
            dpg.configure_item("shape_prev_go", enabled=True)
        if err:
            dpg.set_value("shape_prev_status", f"preview failed: {err}"); return
        h, w = frames[0].shape[:2]
        app._prev_frames = frames; app._prev_k = -1
        if dpg.does_item_exist("shape_prev_tex") and getattr(app, "_prev_tex_size", None) == (w, h):
            dpg.set_value("shape_prev_tex", _rgba(frames[0]))
        else:
            # the image goes before its texture: a texture cannot be deleted
            # while something draws it (the alias then stays taken)
            dpg.delete_item("shape_prev_img", children_only=True)
            if dpg.does_item_exist("shape_prev_tex"):
                dpg.delete_item("shape_prev_tex")
            from native.textures import registry
            dpg.add_dynamic_texture(w, h, _rgba(frames[0]), tag="shape_prev_tex", parent=registry())
            dpg.add_image("shape_prev_tex", width=px(200), height=px(200), parent="shape_prev_img")
            app._prev_tex_size = (w, h)
        g = app.project.geometry
        dpg.set_value("shape_prev_status", f"{g.describe()}: {len(frames)} frames -> {os.path.basename(paths[0])}" + (f", {os.path.basename(paths[1])}" if paths[1] else "") + " in export/")
        app.gp.status(f"preview saved: {paths[0]}")
    frames = getattr(app, "_prev_frames", None)
    if frames and dpg.does_item_exist("shape_prev_tex") and dpg.is_item_shown(TAG):
        import time as _t
        k = int(_t.time() * 15) % len(frames)
        if k != getattr(app, "_prev_k", -1):
            app._prev_k = k
            dpg.set_value("shape_prev_tex", _rgba(frames[k]))


_rgba = render.texture_rgba


# --- files -----------------------------------------------------------------------------------
def import_file(app, path):
    """A mesh (.obj/.ply/.stl), an xLights model (.xmodel) or a point list
    into a points part; a model's own grid becomes the layout when it is
    the shape's only part."""
    if not path:
        return
    ext = os.path.splitext(path)[1].lower()
    parts = list(_parts(app) or [])
    more = {}
    as_ref = bool(getattr(app, "_shape_ref", False)); app._shape_ref = False
    try:
        if as_ref:
            if ext not in (".obj", ".ply", ".stl"):
                raise ValueError("a reference is a mesh (.obj, .ply or .stl)")
            mesh = shape_io.read_mesh(path)
            part = shapes.new_part("reference", vertices=mesh.v.tolist(), edges=[list(e) for e in mesh.edges], file=mesh.source)
            part["name"] = f"{mesh.source} (reference)"
            note = f"reference {mesh.source}: {len(mesh.v)} vertices, {len(mesh.edges)} edges drawn, no LEDs"
        elif ext in (".obj", ".ply", ".stl"):
            mesh = shape_io.read_mesh(path)
            mode = next(m[0] for m in MESH_MODES if m[1] == dpg.get_value("shape_mesh_mode"))
            pts, nrm = shape_io.mesh_leds(mesh, mode, float(dpg.get_value("shape_mesh_pitch")) or 1.0)
            if len(pts) == 0:
                raise ValueError("no LEDs came of it")
            part = shapes.new_part("points", points=pts.tolist())
            if nrm is not None:
                part["params"]["normals"] = nrm.tolist()
            part["name"] = f"{mesh.source} ({mode})"
            note = f"{len(pts)} LEDs {mode} of {mesh.source} ({len(mesh.v)} vertices, {len(mesh.edges)} edges, {len(mesh.faces)} faces)"
        elif ext == ".xml":
            new, notes = shape_io.read_layout(path)
            parts += new
            app._shape_sel = len(parts) - 1
            _apply(app, parts)
            app.gp.status(f"{len(new)} model(s) from the layout" + (f"; approximated: {'; '.join(notes[:4])}" + (" ..." if len(notes) > 4 else "") if notes else ""))
            return
        elif ext == ".xmodel":
            m = shape_io.read_xmodel(path)
            part = shapes.new_part("points", points=m["points"].tolist())
            part["name"] = m["name"]
            if not parts and m["grid"]:
                more = {"layout": "grid", "grid": [m["grid"][0], m["grid"][1], list(m["grid"][2])]}
            note = f"{len(m['points'])} LEDs of xLights model {m['name']} ({m['w']} x {m['h']}" + (f" x {m['d']}" if m['d'] > 1 else "") + ")"
        else:
            pts, order = shape_io.read_points(path)
            part = shapes.new_part("points", points=pts.tolist())
            part["name"] = os.path.basename(path)
            note = f"{len(pts)} LEDs from {os.path.basename(path)}" + (" in the file's numbering" if order is not None else "")
    except Exception as e:
        app.gp.status(f"could not read {os.path.basename(path)}: {e}")
        dpg.set_value("shape_desc", f"could not read {os.path.basename(path)}: {e}")
        return
    parts.append(part)
    app._shape_sel = len(parts) - 1
    _apply(app, parts, **more)
    app.gp.status(note)


def export_xmodel(app, path):
    """The geometry as an xLights custom model - any kind, on its grid."""
    if not path:
        return
    try:
        w, h, n = shape_io.write_xmodel(app.project.geometry, path)
    except Exception as e:
        app.gp.status(f"could not write the model: {e}"); return
    app.gp.status(f"xLights model written: {os.path.basename(path)}, {w} x {h} grid, {n} LEDs")


def export_points(app, path):
    """Every LED's position, its wiring index and its part, as CSV."""
    if not path:
        return
    try:
        n = shape_io.write_points(app.project.geometry, path)
    except Exception as e:
        app.gp.status(f"could not write the positions: {e}"); return
    app.gp.status(f"positions written: {os.path.basename(path)}, {n} LEDs in wiring order")


def save_shape(app, path):
    if not path or _parts(app) is None:
        return
    g = app.project.geometry
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"studio_shape": 1, "geometry": g.to_json()}, f, indent=1)
    app.gp.status(f"shape saved to {os.path.basename(path)}")


def open_shape(app, path):
    if not path:
        return
    try:
        d = json.load(open(path, encoding="utf-8"))
        g = Geometry.from_json(d["geometry"] if "geometry" in d else d)
        if g.kind != "shape":
            raise ValueError("not a shape file")
    except Exception as e:
        app.gp.status(f"could not open {os.path.basename(path)}: {e}"); return
    app._shape_sel = 0
    _apply(app, **g.params)


# --- the 3-D view: placing and dragging LEDs, the rings round the selected part ------------
def _view(app):
    """(rect_min, size, ext) of the 3-D image, or None when it is not the point cloud."""
    g = app.project.geometry
    if g.kind != "shape" or not dpg.does_item_exist("cube_img") or not dpg.is_item_shown("cube_win"):
        return None
    st = dpg.get_item_state("cube_img")
    if "rect_min" not in st:
        return None
    (x0, y0), (w, h) = st["rect_min"], st["rect_size"]
    if w <= 0:
        return None
    pq = getattr(app, "point_quads", None)
    if pq is not None and pq.size:                        # the GPU cloud: a square of the view's side, centred in its drawlist
        x0 += (w - pq.size) * 0.5; y0 += (h - pq.size) * 0.5; w = pq.size
    return (x0, y0), float(w), render.frame_of(g.pos)


def _plane(app):
    ax, v = getattr(app, "_shape_plane", ("z", 0.0))
    return {"x": 0, "y": 1, "z": 2}[ax], float(v)


def _hit(app, mx, my):
    """The LED under the pointer: (part index, point index within a points part) or None."""
    v = _view(app)
    if v is None:
        return None
    (x0, y0), size, ext = v
    parts = _parts(app) or []
    pos, _, owner = shapes.resolve(parts)
    if len(pos) == 0:
        return None
    sx, sy, ok = render.project(pos, size, app.yaw, app.pitch, app.dist, frame=ext)
    d = np.hypot(sx + x0 - mx, sy + y0 - my)
    d[~ok] = np.inf
    k = int(np.argmin(d))
    if d[k] > 9:
        return None
    pi = int(owner[k])
    if parts[pi]["kind"] != "points":
        return (pi, None)
    # which of the part's points: its index in the part's order (reverse and the transform kept)
    n_before = int((owner[:k] == pi).sum())
    n = shapes.part_count(parts[pi])
    return (pi, (n - 1 - n_before) if parts[pi].get("reverse") else n_before)


def click(app, at=None):
    """A click on the 3-D view while placing: an LED under the pointer is
    picked up, else a new one is put on the plane. True when handled."""
    if not getattr(app, "_shape_place", False) or _parts(app) is None:
        return False
    v = _view(app)
    if v is None:
        return False
    mx, my = at or dpg.get_mouse_pos(local=False)
    hit = _hit(app, mx, my)
    if hit and hit[1] is not None:
        app._shape_drag = hit
        app._shape_sel = hit[0]
        return True
    (x0, y0), size, ext = v
    axis, value = _plane(app)
    p = render.unproject(mx - x0, my - y0, size, app.yaw, app.pitch, app.dist, ext, axis, value)
    if p is None:
        app.gp.status("the plane is edge-on here: turn the view, or choose another plane"); return True
    parts = json.loads(json.dumps(_parts(app) or []))
    sel = _sel(app)
    if sel < 0 or parts[sel]["kind"] != "points":
        parts.append(shapes.new_part("points", points=[])); parts[-1]["name"] = f"placed {sum(1 for q in parts if q['kind'] == 'points')}"
        sel = len(parts) - 1
    part = parts[sel]
    # into the part's own frame: undo its move, rotation and scale
    R = shapes.rotation(*part.get("rot", [0, 0, 0]))
    s = part.get("scale", 1.0); s = np.asarray(s if isinstance(s, list) else [s, s, s], np.float32)
    local = ((np.asarray(p, np.float32) - np.asarray(part.get("pos", [0, 0, 0]), np.float32)) @ R) / np.where(s != 0, s, 1)
    if part.get("reverse"):
        part["params"].setdefault("points", []).insert(0, [round(float(c), 3) for c in local])
    else:
        part["params"].setdefault("points", []).append([round(float(c), 3) for c in local])
    app._shape_sel = sel
    _apply(app, parts)
    return True


def drag(app):
    """The pointer moving with an LED picked up: it follows on the plane (applied on release)."""
    hit = getattr(app, "_shape_drag", None)
    if not hit:
        return False
    v = _view(app)
    if v is None:
        return True
    (x0, y0), size, ext = v
    mx, my = dpg.get_mouse_pos(local=False)
    axis, value = _plane(app)
    p = render.unproject(mx - x0, my - y0, size, app.yaw, app.pitch, app.dist, ext, axis, value)
    if p is not None:
        app._shape_drag_to = [float(c) for c in p]
    return True


def release(app):
    hit = getattr(app, "_shape_drag", None)
    if not hit:
        return False
    app._shape_drag = None
    to = getattr(app, "_shape_drag_to", None)
    app._shape_drag_to = None
    if to is None:
        return True
    parts = json.loads(json.dumps(_parts(app) or []))
    pi, k = hit
    part = parts[pi]
    R = shapes.rotation(*part.get("rot", [0, 0, 0]))
    s = part.get("scale", 1.0); s = np.asarray(s if isinstance(s, list) else [s, s, s], np.float32)
    local = ((np.asarray(to, np.float32) - np.asarray(part.get("pos", [0, 0, 0]), np.float32)) @ R) / np.where(s != 0, s, 1)
    pts = part["params"].get("points") or []
    if 0 <= k < len(pts):
        pts[k] = [round(float(c), 3) for c in local]
        _apply(app, parts)
    return True


def _covers(app):
    """What is drawn over the view - floating frames, dialogs, open menus:
    (x0, y0, x1, y1) each - so no mark lands on top of it (the list the
    gradient frames keep off too)."""
    return app.overlay_holes("cube")


def _clear(covers, x, y, pad=0.0):
    """Nothing covers (x, y) - with `pad`, nothing within pad of it either (a ring's radius)."""
    return not any(a - pad <= x <= c + pad and b - pad <= y <= d + pad for a, b, c, d in covers)


def _poll_reference(app):
    """The reference meshes as wireframes over the 3-D view, redrawn when
    the camera or the shape moves."""
    if not dpg.does_item_exist("ref_dl"):
        return
    v = _view(app)
    parts = _parts(app)
    segs = shapes.reference_segments(parts) if (v is not None and parts) else None
    covers = _covers(app)
    key = None if segs is None or len(segs) == 0 else (round(app.yaw, 4), round(app.pitch, 4), round(app.dist, 3), v[0], v[1], len(segs), id(parts), tuple(covers))
    if key == getattr(app, "_ref_key", "unset"):
        return
    app._ref_key = key
    dpg.delete_item("ref_dl", children_only=True)
    if key is None:
        return
    (x0, y0), size, ext = v
    ax, ay, aok = render.project(segs[:, 0], size, app.yaw, app.pitch, app.dist, frame=ext)
    bx, by, bok = render.project(segs[:, 1], size, app.yaw, app.pitch, app.dist, frame=ext)
    col = (150, 160, 180, 110)
    inside = lambda x, y: 0 <= x <= size and 0 <= y <= size          # the view's square only: no lines into the panels
    for i in range(len(segs)):
        if aok[i] and bok[i] and inside(ax[i], ay[i]) and inside(bx[i], by[i]) and _clear(covers, x0 + ax[i], y0 + ay[i]) and _clear(covers, x0 + bx[i], y0 + by[i]):
            dpg.draw_line((x0 + ax[i], y0 + ay[i]), (x0 + bx[i], y0 + by[i]), color=col, thickness=1, parent="ref_dl")


def poll(app):
    """Rings round the selected part's LEDs while the frame shows; the
    dragged LED's new place as a cross; the reference wireframes always."""
    _poll_reference(app)
    _poll_preview(app)
    _poll_pending(app)
    if not dpg.does_item_exist("shape_dl"):
        return
    dpg.delete_item("shape_dl", children_only=True)
    if not dpg.is_item_shown(TAG):
        return
    v = _view(app)
    parts = _parts(app)
    if v is None or not parts:
        return
    (x0, y0), size, ext = v
    sel = _sel(app)
    pos, _, owner = shapes.resolve(parts)
    mine = np.nonzero(owner == sel)[0][:600]
    if len(mine) == 0:
        return
    c = _c()
    covers = _covers(app)
    sx, sy, ok = render.project(pos[mine], size, app.yaw, app.pitch, app.dist, frame=ext)
    r = max(3.0, 0.42 * (size * 0.5) / np.tan(np.radians(19.0)) / (app.dist * ext[1]) * 0.9)
    col = tuple(c.ACCENT[:3]) + (200,)
    for i in range(len(mine)):
        if ok[i] and 0 <= sx[i] <= size and 0 <= sy[i] <= size and _clear(covers, x0 + sx[i], y0 + sy[i], min(r, 14)):
            dpg.draw_circle((x0 + sx[i], y0 + sy[i]), min(r, 14), color=col, thickness=1.5, parent="shape_dl")
    # the part's axis: a line from its centre the way "aim" points it, a dot at the tip
    part = parts[sel]
    ppos = np.asarray(part.get("pos", [0, 0, 0]), np.float32)
    span = float(np.linalg.norm(pos[mine] - ppos, axis=1).max()) if len(mine) else 1.0
    tip = ppos + (shapes.rotation(*part.get("rot", [0, 0, 0])) @ shapes.axis_of(part)).astype(np.float32) * max(1.5, span * 0.8)
    ex, ey, eok = render.project(np.stack([ppos, tip]), size, app.yaw, app.pitch, app.dist, frame=ext)
    if eok[0] and eok[1] and _clear(covers, x0 + ex[0], y0 + ey[0]) and _clear(covers, x0 + ex[1], y0 + ey[1]):
        dpg.draw_line((x0 + ex[0], y0 + ey[0]), (x0 + ex[1], y0 + ey[1]), color=(255, 200, 80, 220), thickness=2, parent="shape_dl")
        dpg.draw_circle((x0 + ex[1], y0 + ey[1]), 4, color=(255, 200, 80, 240), fill=(255, 200, 80, 200), parent="shape_dl")
    # the wiring: a faint line from LED to LED of the selected part
    if len(mine) > 1 and len(mine) <= 400:
        pts = [(x0 + sx[i], y0 + sy[i]) for i in range(len(mine)) if ok[i] and _clear(covers, x0 + sx[i], y0 + sy[i])]
        if len(pts) > 1:
            dpg.draw_polyline(pts, color=tuple(c.ACCENT[:3]) + (90,), thickness=1, parent="shape_dl")
    to = getattr(app, "_shape_drag_to", None)
    if to is not None:
        tx, ty, tok = render.project(np.asarray([to], np.float32), size, app.yaw, app.pitch, app.dist, frame=ext)
        if tok[0]:
            X, Y = x0 + tx[0], y0 + ty[0]
            dpg.draw_line((X - 8, Y), (X + 8, Y), color=(255, 255, 255, 220), thickness=2, parent="shape_dl")
            dpg.draw_line((X, Y - 8), (X, Y + 8), color=(255, 255, 255, 220), thickness=2, parent="shape_dl")
