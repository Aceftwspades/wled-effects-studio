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
import dearpygui.dearpygui as dpg
import numpy as np

from native import shapes, shape_io, render
from native.geometry import Geometry

TAG = "shape_win"
MESH_MODES = (("edges", "along the edges, an LED every pitch"), ("vertices", "one LED per vertex"), ("surface", "over the surface, an LED every pitch"))


def _c():
    from native import chrome
    return chrome


def _parts(app):
    g = app.project.geometry
    return g.params.get("parts") if g.kind == "shape" else None


def _apply(app, parts=None, **more):
    """The parts (and any other shape option) into a new geometry, with an
    undo step kept."""
    g = app.project.geometry
    p = dict(g.params) if g.kind == "shape" else {}
    if parts is not None:
        p["parts"] = parts
    p.update(more)
    stack = getattr(app, "_shape_undo", None)
    if stack is None:
        stack = app._shape_undo = []
    stack.append(json.dumps(g.params if g.kind == "shape" else {"parts": []}))
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
    with dpg.window(tag=TAG, show=False, width=560, height=640, no_collapse=True, no_title_bar=True):
        device_ui.header(app, "shape")
        dpg.add_text("", tag="shape_desc", color=c.DIM, wrap=0)
        with dpg.group(horizontal=True):
            dpg.add_combo(["strip", "grid"], tag="shape_layout", width=90, default_value="strip",
                          callback=lambda s, v: _apply(app, layout=v))
            dpg.add_text("logical layout: one strip in wiring order, or a grid seen from the front", color=c.DIM)
        with dpg.group(horizontal=True):
            dpg.add_button(label="One segment per part", small=True, callback=lambda: segments_per_part(app))
            dpg.add_text("each part its own WLED segment (effect, palette, sliders) - up to eight", color=c.DIM)
        with dpg.group(horizontal=True):
            dpg.add_button(label="Undo", small=True, callback=lambda: undo(app))
            dpg.add_button(label="Clear", small=True, callback=lambda: _apply(app, parts=[]))
            dpg.add_button(label="Save as file...", small=True, callback=lambda: dpg.show_item("shape_save_dialog"))
            dpg.add_button(label="Open a shape file...", small=True, callback=lambda: dpg.show_item("shape_open_dialog"))
        dpg.add_text("PARTS - the order is the wiring", color=c.ACCENT)
        kinds = [k for k in shapes.KINDS if k != "reference"]
        for row in (kinds[:4], kinds[4:]):
            with dpg.group(horizontal=True):
                for k in row:
                    dpg.add_button(label="+ " + k, small=True, width=100, user_data=k, callback=lambda s, a, u: add_part(app, u))
        with dpg.group(horizontal=True):
            dpg.add_button(label="Import a mesh or model...", small=True, callback=lambda: dpg.show_item("shape_import_dialog"))
            dpg.add_combo([m[1] for m in MESH_MODES], tag="shape_mesh_mode", width=230, default_value=MESH_MODES[0][1])
            dpg.add_input_float(tag="shape_mesh_pitch", width=70, default_value=1.0, step=0, format="%.2f")
            dpg.add_text("pitch", color=c.DIM)
        with dpg.group(horizontal=True):
            dpg.add_button(label="Import as a reference (drawn, not LEDs)...", small=True,
                           callback=lambda: (setattr(app, "_shape_ref", True), dpg.show_item("shape_import_dialog")))
            dpg.add_text("a mesh to place LEDs against: the tree, the house, the enclosure", color=c.DIM)
        with dpg.child_window(tag="shape_parts", height=150, border=True):
            pass
        dpg.add_text("PART", tag="shape_part_title", color=c.ACCENT)
        with dpg.child_window(tag="shape_fields", height=-250, border=False):
            pass
        # PREVIEW: a turntable of the shape, rendered off screen, looping here and saved as a GIF
        with dpg.group(horizontal=True):
            dpg.add_text("PREVIEW", color=c.ACCENT)
            dpg.add_combo(["effect", "parts", "wiring"], tag="shape_prev_mode", width=90, default_value="effect")
            dpg.add_input_float(tag="shape_prev_secs", width=60, default_value=4.0, step=0, format="%.0f s")
            dpg.add_button(label="Generate a preview", tag="shape_prev_go", callback=lambda: generate_preview(app))
            dpg.add_button(label="Open the folder", small=True, callback=lambda: app.reveal(os.path.join(app.project.path, "export")))
        dpg.add_text("a turn of the shape as the sim lights it, its parts each a colour, or a chase along the wiring - a GIF and a PNG in the project's export folder",
                     color=c.DIM, wrap=0)
        dpg.add_text("", tag="shape_prev_status", color=c.DIM, wrap=0)
        with dpg.group(tag="shape_prev_img"):
            pass
    # the file dialogs: a mesh or model in, a shape file in or out
    with dpg.file_dialog(directory_selector=False, show=False, tag="shape_import_dialog", width=640, height=420,
                         callback=lambda s, a: import_file(app, a.get("file_path_name", ""))):
        for ext, col in ((".obj", (120, 200, 120)), (".ply", (120, 200, 120)), (".stl", (120, 200, 120)),
                         (".xmodel", (200, 180, 90)), (".csv", (150, 150, 220)), (".txt", (150, 150, 220)), (".json", (150, 150, 220))):
            dpg.add_file_extension(ext, color=col)
    with dpg.file_dialog(directory_selector=False, show=False, tag="shape_open_dialog", width=640, height=420,
                         callback=lambda s, a: open_shape(app, a.get("file_path_name", ""))):
        dpg.add_file_extension(".shape.json", color=(150, 150, 220))
        dpg.add_file_extension(".json", color=(150, 150, 220))
    with dpg.file_dialog(directory_selector=False, show=False, tag="shape_save_dialog", width=640, height=420,
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
    dpg.set_value("shape_desc", g.describe() + f"; {g.count} LEDs; from the parts' units, a pitch is 1")
    dpg.set_value("shape_layout", g.params.get("layout", "strip"))
    sel = _sel(app)
    for i, part in enumerate(parts):
        n = shapes.part_count(part)
        with dpg.group(horizontal=True, parent="shape_parts"):
            dpg.add_selectable(label=f"{i + 1:2d}  {part.get('name', part['kind'])}", width=200, default_value=(i == sel), user_data=i,
                               callback=lambda s, a, u: (setattr(app, "_shape_sel", u), refresh(app)))
            dpg.add_text(f"{part['kind']}, {n} LEDs", color=c.DIM)
            dpg.add_button(label="up", small=True, user_data=i, callback=lambda s, a, u: move_part(app, u, -1), show=i > 0)
            dpg.add_button(label="down", small=True, user_data=i, callback=lambda s, a, u: move_part(app, u, 1), show=i < len(parts) - 1)
            dpg.add_button(label="copy", small=True, user_data=i, callback=lambda s, a, u: dup_part(app, u))
            dpg.add_button(label="x", small=True, user_data=i, callback=lambda s, a, u: del_part(app, u))
    if not parts:
        dpg.add_text("no parts yet: add one above, import a file, or place LEDs by hand (a points part)", parent="shape_parts", color=c.DIM)
    if sel < 0:
        dpg.set_value("shape_part_title", "")
        return
    part = parts[sel]
    dpg.set_value("shape_part_title", f"PART {sel + 1}: {part.get('name', part['kind'])} - {shapes.KINDS[part['kind']][1]}")
    P = "shape_fields"
    dpg.add_input_text(label="name", parent=P, width=200, default_value=str(part.get("name", "")), on_enter=True,
                       callback=lambda s, v: set_part(app, sel, name=v))
    if part["kind"] == "reference":
        dpg.add_text(f"{part['params'].get('file', '?')}: {len(part['params'].get('vertices') or [])} vertices, "
                     f"{len(part['params'].get('edges') or [])} edges - drawn in the 3-D view, not LEDs", parent=P, color=c.DIM, wrap=0)
    for key, default in shapes.KINDS[part["kind"]][0].items():
        if key in ("points", "normals", "vertices", "edges", "file"):
            continue
        val = part["params"].get(key, default)
        if isinstance(default, bool):
            dpg.add_checkbox(label=key, parent=P, default_value=bool(val), user_data=key,
                             callback=lambda s, v, u: set_param(app, sel, u, bool(v)))
        elif isinstance(default, int):
            dpg.add_input_int(label=key, parent=P, width=90, default_value=int(val), min_value=1, max_value=4096, min_clamped=True,
                              on_enter=True, user_data=key, callback=lambda s, v, u: set_param(app, sel, u, int(v)))
        else:
            dpg.add_input_float(label=key, parent=P, width=90, default_value=float(val), step=0, format="%.2f",
                                on_enter=True, user_data=key, callback=lambda s, v, u: set_param(app, sel, u, float(v)))
    if part["kind"] in ("points", "polyline"):
        pts = part["params"].get("points") or []
        dpg.add_text(f"{len(pts)} point(s)" + (" - place more: tick 'place', click the 3-D view" if part["kind"] == "points" else " on the path"),
                     parent=P, color=c.DIM)
        with dpg.group(horizontal=True, parent=P):
            dpg.add_button(label="delete the last", small=True, callback=lambda: pop_point(app, sel))
            dpg.add_button(label="renumber: nearest chain from the first", small=True, callback=lambda: chain_part(app, sel))
            if part["kind"] == "points":
                dpg.add_button(label="turn into a path", small=True, callback=lambda: set_part(app, sel, kind="polyline"))
    dpg.add_input_floatx(label="position", parent=P, width=240, size=3, default_value=list(part.get("pos", [0, 0, 0])) + [0.0], format="%.2f",
                         on_enter=True, callback=lambda s, v: set_part(app, sel, pos=[float(x) for x in v[:3]]))
    dpg.add_input_floatx(label="rotation (deg)", parent=P, width=240, size=3, default_value=list(part.get("rot", [0, 0, 0])) + [0.0], format="%.1f",
                         on_enter=True, callback=lambda s, v: set_part(app, sel, rot=[float(x) for x in v[:3]]))
    sc = part.get("scale", 1.0)
    dpg.add_input_float(label="scale", parent=P, width=90, default_value=float(sc if not isinstance(sc, list) else sc[0]), step=0, format="%.2f",
                        on_enter=True, callback=lambda s, v: set_part(app, sel, scale=float(v)))
    dpg.add_checkbox(label="reverse the wiring of this part", parent=P, default_value=bool(part.get("reverse")),
                     callback=lambda s, v: set_part(app, sel, reverse=bool(v)))
    with dpg.group(horizontal=True, parent=P):
        dpg.add_text("mirror", color=c.DIM)
        for ax, lbl in enumerate("XYZ"):
            dpg.add_button(label=lbl, small=True, user_data=ax, callback=lambda s, a, u: mirror_part(app, sel, u))
        dpg.add_text("  array", color=c.DIM)
        dpg.add_input_int(tag="shape_array_n", width=60, default_value=3, min_value=2, max_value=64, min_clamped=True)
        dpg.add_input_floatx(tag="shape_array_off", width=180, size=3, default_value=[10.0, 0.0, 0.0, 0.0], format="%.1f")
        dpg.add_button(label="make", small=True, callback=lambda: array_part(app, sel))
    dpg.add_separator(parent=P)
    with dpg.group(horizontal=True, parent=P):
        dpg.add_checkbox(label="place", tag="shape_place", default_value=bool(getattr(app, "_shape_place", False)),
                         callback=lambda s, v: setattr(app, "_shape_place", bool(v)))
        dpg.add_text("click the 3-D view to put an LED on the plane", color=c.DIM)
        dpg.add_combo(["z", "y", "x"], tag="shape_plane_axis", width=50, default_value=getattr(app, "_shape_plane", ("z", 0.0))[0],
                      callback=lambda s, v: setattr(app, "_shape_plane", (v, getattr(app, "_shape_plane", ("z", 0.0))[1])))
        dpg.add_text("=", color=c.DIM)
        dpg.add_input_float(tag="shape_plane_v", width=70, default_value=getattr(app, "_shape_plane", ("z", 0.0))[1], step=0, format="%.1f",
                            callback=lambda s, v: setattr(app, "_shape_plane", (getattr(app, "_shape_plane", ("z", 0.0))[0], float(v))))
    dpg.add_text("placed LEDs go into the selected points part (a new one when none is selected); drag one to move it",
                 parent=P, color=c.DIM, wrap=0)


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


def set_param(app, i, key, value):
    parts = json.loads(json.dumps(_parts(app) or []))
    if 0 <= i < len(parts):
        parts[i]["params"][key] = value
        _apply(app, parts)


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
        app._prev_frames = frames
        if dpg.does_item_exist("shape_prev_tex"):
            dpg.delete_item("shape_prev_tex")
        with dpg.texture_registry():
            dpg.add_dynamic_texture(w, h, _rgba(frames[0]), tag="shape_prev_tex")
        dpg.delete_item("shape_prev_img", children_only=True)
        dpg.add_image("shape_prev_tex", width=200, height=200, parent="shape_prev_img")
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


def _rgba(frame):
    h, w = frame.shape[:2]
    out = np.ones((h, w, 4), np.float32)
    out[:, :, :3] = frame.astype(np.float32) / 255.0
    return out.ravel()


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
    g = app.project.geometry
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
    """The floating frames over the view: (x0, y0, x1, y1) each, so overlay
    marks are not drawn on top of a window that covers the LEDs."""
    from native import device_ui
    out = []
    for slot, (tag, _, _, _) in device_ui.FRAMES.items():
        if dpg.does_item_exist(tag) and dpg.is_item_shown(tag) and not app.docked(slot):
            x, y = dpg.get_item_pos(tag); w, h = dpg.get_item_rect_size(tag)
            out.append((x, y, x + w, y + h))
    return out


def _clear(covers, x, y):
    return not any(a <= x <= c and b <= y <= d for a, b, c, d in covers)


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
        if ok[i] and 0 <= sx[i] <= size and 0 <= sy[i] <= size and _clear(covers, x0 + sx[i], y0 + sy[i]):
            dpg.draw_circle((x0 + sx[i], y0 + sy[i]), min(r, 14), color=col, thickness=1.5, parent="shape_dl")
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
