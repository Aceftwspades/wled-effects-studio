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
from native import num
from native import typeface
from native import form

from native import weight
import numpy as np

from native import shapes, shape_io, render, units
from native.geometry import Geometry

TAG = "shape_win"
MESH_MODES = (("edges", "LEDs along the edges"), ("vertices", "an LED per vertex"), ("surface", "LEDs over the surface"))


def _c():
    from native import chrome
    return chrome


def _shape_view():
    from native import shape_view
    return shape_view


def _parts(app):
    g = app.project.geometry
    return g.params.get("parts") if g.kind == "shape" else None


def _apply(app, parts=None, undo_from=None, refit=None, **more):
    """The parts (and any other shape option) into a new geometry, with an
    undo step kept (`undo_from`: the params to go back to, when the
    geometry already moved on - a drag). `refit`: "grow" when parts came
    in (the view's held frame grows to take them), "all" when the shape
    was replaced (fitted afresh); a move never refits."""
    g = app.project.geometry
    p = dict(g.params) if g.kind == "shape" else {}
    if parts is not None:
        p["parts"] = parts
    p.update(more)
    stack = getattr(app, "_shape_undo", None)
    if stack is None:
        stack = app._shape_undo = []
    before = undo_from or json.dumps(g.params if g.kind == "shape" else {"parts": []})
    stack.append(before)
    del stack[:-40]
    names = getattr(app, "_shape_undo_names", None)
    if names is None:
        names = app._shape_undo_names = []
    after = dict(g.params if g.kind == "shape" else {}, **({"parts": parts} if parts is not None else {}), **more)
    names.append(step_name(json.loads(before), after))
    del names[:-40]
    app._shape_redo = []                                    # a new step: the steps undone are gone
    app._shape_redo_names = []
    was = g.kind
    app.apply_geometry(Geometry("shape", **p))
    if was != "shape" and dpg.does_item_exist("geom_kind"):
        dpg.set_value("geom_kind", "shape"); app.rebuild_geom_fields()
    refresh(app)
    if refit:
        from native import view3d
        view3d.refit(app, grow=(refit == "grow"))


def _names(app, which):
    n = getattr(app, which, None)
    if n is None:
        n = []
        setattr(app, which, n)
    return n


def undo(app):
    stack = getattr(app, "_shape_undo", None)
    if not stack:
        app.gp.status("nothing to undo in the shape"); return
    g = app.project.geometry
    redo_stack = getattr(app, "_shape_redo", None)
    if redo_stack is None:
        redo_stack = app._shape_redo = []
    redo_stack.append(json.dumps(g.params if g.kind == "shape" else {"parts": []}))
    names, rnames = _names(app, "_shape_undo_names"), _names(app, "_shape_redo_names")
    what = names.pop() if len(names) == len(stack) and names else "a change"
    rnames.append(what)
    p = json.loads(stack.pop())
    app.apply_geometry(Geometry("shape", **p))
    refresh(app)
    app.gp.status(f"undone: {what}")


def redo(app):
    stack = getattr(app, "_shape_redo", None)
    if not stack:
        app.gp.status("nothing to redo in the shape"); return
    g = app.project.geometry
    undo_stack = getattr(app, "_shape_undo", None)
    if undo_stack is None:
        undo_stack = app._shape_undo = []
    undo_stack.append(json.dumps(g.params if g.kind == "shape" else {"parts": []}))
    names, rnames = _names(app, "_shape_undo_names"), _names(app, "_shape_redo_names")
    what = rnames.pop() if len(rnames) == len(stack) and rnames else "a change"
    names.append(what)
    p = json.loads(stack.pop())
    app.apply_geometry(Geometry("shape", **p))
    refresh(app)
    app.gp.status(f"redone: {what}")


def undo_steps(app):
    """The shape's steps, oldest first, named (for Edit > Undo history)."""
    stack = getattr(app, "_shape_undo", None) or []
    names = _names(app, "_shape_undo_names")
    return names[-len(stack):] if len(names) >= len(stack) else ["a change"] * (len(stack) - len(names)) + names


def undo_to(app, k):
    """k steps back."""
    for _ in range(max(0, int(k))):
        if not getattr(app, "_shape_undo", None):
            break
        undo(app)


_FIELD_WORDS = (("pos", "moved"), ("rot", "turned"), ("scale", "scaled"), ("params", "resized"), ("reverse", "reversed"),
                ("copies", "copies changed"), ("mirror", "mirror changed"), ("name", "renamed"), ("hidden", "hidden or shown"),
                ("locked", "locked or unlocked"), ("kind", "made another kind"))


def step_name(old, new):
    """A shape step in words, from the shape before and after: "moved strip 1", "added tree 1", "re-wired"."""
    po, pn = old.get("parts") or [], new.get("parts") or []
    nm = lambda q: q.get("name", q.get("kind", "a part"))
    if len(pn) > len(po):
        added = [q for q in pn if q not in po]
        return "added " + (", ".join(nm(q) for q in added[:2]) + (" ..." if len(added) > 2 else "") if added else f"{len(pn) - len(po)} parts")
    if len(pn) < len(po):
        gone = [q for q in po if q not in pn]
        return "deleted " + (", ".join(nm(q) for q in gone[:2]) + (" ..." if len(gone) > 2 else "") if gone else f"{len(po) - len(pn)} parts")
    changed = [i for i, (a, b) in enumerate(zip(po, pn)) if a != b]
    if not changed:
        keys = sorted(k for k in set(old) | set(new) if k != "parts" and old.get(k) != new.get(k))
        return ("changed the shape's " + ", ".join(keys)) if keys else "a change"
    if len(changed) > 1 and sorted(json.dumps(q, sort_keys=True) for q in po) == sorted(json.dumps(q, sort_keys=True) for q in pn):
        return "re-wired"
    if len(changed) == 1:
        a, b = po[changed[0]], pn[changed[0]]
        words = [w for k, w in _FIELD_WORDS if a.get(k) != b.get(k)]
        return f"{words[0] if words else 'changed'} {nm(b)}"
    return f"changed {len(changed)} parts"


def selection(app):
    """The selected parts: a set of indices. Before anything is picked, the
    part the frame shows (the first), as it always had."""
    parts = _parts(app) or []
    sels = getattr(app, "_shape_sels", None)
    if sels is None:
        sels = app._shape_sels = ({min(max(0, getattr(app, "_shape_sel", 0)), len(parts) - 1)} if parts else set())
    return {k for k in sels if 0 <= k < len(parts)}


def _sel(app):
    """The active part - the one the frame shows, the one the arrange tools
    line the others up to: the last picked of the selection; -1 with none."""
    s = selection(app)
    if not s:
        return -1
    i = getattr(app, "_shape_sel", -1)
    return i if i in s else max(s)


def _set_sel(app, idxs, active=None):
    """The selection set without a refresh (an edit's _apply follows)."""
    idxs = set(int(i) for i in idxs)
    app._shape_sels = idxs
    app._shape_sel = active if active is not None else (max(idxs) if idxs else -1)


def select(app, idxs, add=False, toggle=False, active=None):
    """The selection: `idxs`; or added to it; or each one turned over. The
    active part is the last of idxs still selected."""
    parts = _parts(app) or []
    idxs = [int(i) for i in idxs if 0 <= int(i) < len(parts)]
    cur = selection(app)
    if toggle:
        for i in idxs:
            cur ^= {i}
    elif add:
        cur |= set(idxs)
    else:
        cur = set(idxs)
    a = active if active is not None else next((i for i in reversed(idxs) if i in cur), None)
    if a is None or a not in cur:
        a = getattr(app, "_shape_sel", -1) if getattr(app, "_shape_sel", -1) in cur else (max(cur) if cur else -1)
    _set_sel(app, cur, a)
    refresh(app)


def pick_row(app, i):
    """A row of the list clicked: that part alone; with Ctrl or Shift, added
    to the selection or taken out of it."""
    mod = any(dpg.is_key_down(k) for k in (dpg.mvKey_LControl, dpg.mvKey_RControl, dpg.mvKey_LShift, dpg.mvKey_RShift))
    select(app, [i], toggle=mod)


# --- build ---------------------------------------------------------------------------------
# The frame is an inspector (the ninth pass's S13): the building is done in the 3-D view; here are the
# exact values. At the top the tools and the file's; then the parts in wiring order (S14); then what the
# selection needs - nothing: the shape's own settings; one part: its sizes, its place, its wiring; several:
# lining them up.
LIE_FACE = {"ring": (0.0, 0.0, 1.0), "polygon": (0.0, 0.0, 1.0), "star": (0.0, 0.0, 1.0), "rings": (0.0, 0.0, 1.0),
            "spokes": (0.0, 0.0, 1.0), "spiral": (0.0, 0.0, 1.0), "panel": (0.0, -1.0, 0.0), "arch": (0.0, -1.0, 0.0),
            "frame": (0.0, -1.0, 0.0)}
LIE_LINE = ("strip", "polyline")


def build(app):
    c = _c()
    from native import device_ui, shape_tools, shape_gallery
    with dpg.window(tag=TAG, show=False, width=px(560), height=px(640), no_collapse=True, no_title_bar=True):
        device_ui.header(app, "shape")
        with dpg.group(horizontal=True):
            c.info("A shape is its parts in wiring order. Build it in the 3-D view: click a part to select it, drag its "
                   "handles or press G, R or S to move, turn or scale it; right-click it for its menu. Here are the exact "
                   "values - and, with nothing selected, the shape's own: its LED density and unit.")
            dpg.add_text("", tag="shape_desc", color=c.DIM, wrap=px(520))
        with dpg.group(horizontal=True, tag="shape_tools_row"):
            dpg.add_button(label="Add part...", tag="shape_add_btn", callback=lambda: shape_gallery.show(app))
            weight.primary(dpg.last_item())
            c.tip("a strip, a ring, a tree, a star... picked from pictures, its sizes asked first; it joins the end of the "
                  "selected part (or goes beside it)")
            dpg.add_button(label="Draw a run", tag="shape_draw_btn", callback=lambda: _shape_run().toggle(app))
            c.tip("click corners in the 3-D view and a strip is laid along them, an LED every spacing; double-click or "
                  "Enter ends it, Backspace takes the last corner back, Esc leaves it")
            dpg.add_button(label="File...", tag="shape_file_btn", callback=lambda: _file_menu(app))
            c.tip("open or save a shape; import a model, an xLights model or layout, a point list; a reference mesh; "
                  "export an xLights model or the positions; a preview")
            dpg.add_button(label="Undo", tag="shape_undo_btn", callback=lambda: undo(app))
            dpg.add_button(label="Redo", tag="shape_redo_btn", callback=lambda: redo(app))
        with dpg.group(horizontal=True):
            typeface.label(dpg.add_text("WIRING", color=c.ACCENT))
            dpg.add_text("the parts in the order the LEDs are wired: drag a row to move it", tag="shape_list_hint", color=c.DIM)
        with dpg.child_window(tag="shape_parts", height=px(150), border=True):
            pass
        with dpg.group(horizontal=True):
            typeface.label(dpg.add_text("SHAPE", tag="shape_part_title", color=c.ACCENT))
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
    # the list's right-click: one handler for every row (its row's index is its user data)
    with dpg.item_handler_registry(tag="shape_row_handlers"):
        dpg.add_item_clicked_handler(button=dpg.mvMouseButton_Right, callback=lambda s, a: _row_menu(app, a[1]))
    # the File menu: a popup at its button
    with dpg.window(tag="shape_file_menu", show=False, no_title_bar=True, no_resize=True, no_move=True, autosize=True, popup=True):
        for label, fn, tip in (
                ("Open a shape...", lambda: dpg.show_item("shape_open_dialog"), "a shape file (.shape.json) saved from here"),
                ("Save the shape...", lambda: dpg.show_item("shape_save_dialog"), "the parts, their settings and the density, to reuse"),
                (None, None, None),
                ("Import a model or a layout...", lambda: _import(app, False),
                 "a mesh as LEDs (.obj, .ply, .stl from Blender or CAD); an xLights .xmodel, or a whole xLights layout "
                 "(xlights_rgbeffects.xml: every model a part, where it stands); an x y z [index] point list (CSV, text, JSON)"),
                ("A reference mesh...", lambda: _import(app, True),
                 "a mesh drawn in the 3-D view to place LEDs against, not LEDs: the tree, the house, the enclosure"),
                (None, None, None),
                ("Export an xLights model...", lambda: dpg.show_item("shape_xmodel_dialog"),
                 "the shape as an xLights custom model, the wiring as its node numbers"),
                ("Export the positions...", lambda: dpg.show_item("shape_points_dialog"),
                 "every LED as a CSV row - x, y, z, its wiring index, its part - in wiring order, for any other tool"),
                ("Generate a preview", lambda: generate_preview(app), "a turn of the shape: a GIF and a PNG in the export folder"),
                (None, None, None),
                ("Clear the shape", lambda: _apply(app, parts=[], refit="all"), "every part gone (Undo brings them back)")):
            if label is None:
                dpg.add_separator(); continue
            dpg.add_selectable(label=label, width=px(260), user_data=fn, callback=lambda s, a, u: (dpg.hide_item("shape_file_menu"), u()))
            c.tip(tip)
    app.FLOATING = tuple(getattr(app, "FLOATING", ())) + ("shape_file_menu",)
    shape_tools.build_menu(app)                             # a part's right-click menu (the view's and the list's)
    shape_gallery.build(app)                                # the add gallery
    # the file dialogs: a mesh or model in (how a mesh becomes LEDs asked there), a shape file in or out
    with dpg.file_dialog(directory_selector=False, show=False, tag="shape_import_dialog", width=px(700), height=px(460),
                         callback=lambda s, a: import_file(app, a.get("file_path_name", ""))):
        for ext, col in ((".obj", (120, 200, 120)), (".ply", (120, 200, 120)), (".stl", (120, 200, 120)),
                         (".xmodel", (200, 180, 90)), (".xml", (200, 180, 90)), (".csv", (150, 150, 220)), (".txt", (150, 150, 220)), (".json", (150, 150, 220))):
            dpg.add_file_extension(ext, color=col)
        with dpg.group(tag="shape_import_opts"):
            dpg.add_text("a mesh (.obj, .ply, .stl) becomes LEDs:", color=c.DIM)
            dpg.add_combo([m[1] for m in MESH_MODES], tag="shape_mesh_mode", width=px(190), default_value=MESH_MODES[0][1])
            c.tip("one every spacing along its edges, one at each vertex, or spread over its surface")
            with dpg.group(horizontal=True):
                dpg.add_text("spacing", color=c.DIM)
                typeface.mono(dpg.add_input_float(tag="shape_mesh_pitch", width=px(80), default_value=1.0, step=0, format="%.2f"))
                c.tip("the LED spacing along the edges or over the surface, in the model's own units")
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


def _shape_run():
    from native import shape_run
    return shape_run


def _import(app, reference):
    """The import dialog: a model's LEDs, or (reference) a mesh drawn to place LEDs against."""
    app._shape_ref = bool(reference)
    if dpg.does_item_exist("shape_import_opts"):
        dpg.configure_item("shape_import_opts", show=not reference)
    dpg.show_item("shape_import_dialog")


def _file_menu(app):
    """The File menu, under its button."""
    if not dpg.does_item_exist("shape_file_menu"):
        return
    st = dpg.get_item_state("shape_file_btn")
    x, y = st.get("rect_min", dpg.get_mouse_pos(local=False))
    h = st.get("rect_size", (0, px(20)))[1]
    dpg.configure_item("shape_file_menu", show=True)
    dpg.set_item_pos("shape_file_menu", [int(x), int(y + h + 2)])


def _row_menu(app, item):
    """A right-click on a row of the list: that part's menu (the view's)."""
    from native import shape_tools
    i = dpg.get_item_user_data(item) if dpg.does_item_exist(item) else None
    if not isinstance(i, int) or not (0 <= i < len(_parts(app) or [])):
        return
    if i not in selection(app):
        select(app, [i])
    shape_tools.open_menu(app, i, dpg.get_mouse_pos(local=False))


def _drop_row(app, target, src):
    """A row dropped on another: the dragged part moves to that place in the wiring."""
    parts = _parts(app) or []
    j = dpg.get_item_user_data(target) if dpg.does_item_exist(target) else None
    if not isinstance(src, int) or not isinstance(j, int) or src == j or not (0 <= src < len(parts)):
        return
    _set_sel(app, {j})
    _apply(app, shapes.reordered(parts, src, j))
    app.gp.status(f"{parts[src].get('name', parts[src]['kind'])}: part {j + 1} in the wiring now")


def _icon_toggle(icon, tip, cb, user_data, active=False):
    """A small icon button in a row (a part's direction, hidden, locked)."""
    from native.icons import texture
    c = _c()
    b = dpg.add_image_button(texture(icon, px(14)), width=px(14), height=px(14), frame_padding=2, user_data=user_data,
                             tint_color=c.ACCENT if active else c.TEXT, callback=cb)
    c.tip(tip)
    return b


# --- the list and what the selection needs ----------------------------------------------------
def refresh(app):
    if not dpg.does_item_exist("shape_parts"):
        return
    c = _c()
    g = app.project.geometry
    parts = _parts(app)
    if dpg.does_item_exist("shape_exact_tn"):
        app._shape_exact = bool(dpg.get_value("shape_exact_tn"))            # the fold stays as it was left
    dpg.delete_item("shape_parts", children_only=True)
    dpg.delete_item("shape_fields", children_only=True)
    _undo_buttons(app)
    if parts is None:
        dpg.set_value("shape_desc", "the geometry is not a shape: add a part to start one (Add part...), or draw a run")
        dpg.set_value("shape_part_title", "SHAPE"); dpg.set_value("shape_part_kind", "")
        return
    sp = g.params
    dpg.set_value("shape_desc", f"{len(parts)} part(s), {g.count} LEDs  ·  {units.density(sp):g} LEDs a metre  ·  in {units.unit(sp)}"
                  + (f"  ·  {g.collisions} LEDs share a grid cell" if getattr(g, "collisions", 0) else ""))
    chosen = selection(app)
    sel = _sel(app)
    from native.shape_view import part_colour
    counts = [shapes.part_count(q) for q in parts]
    start = 0
    for i, part in enumerate(parts):
        n = counts[i]
        grp = part.get("group") or ""
        if grp and (i == 0 or (parts[i - 1].get("group") or "") != grp):
            members = [k for k, q in enumerate(parts) if (q.get("group") or "") == grp]
            with dpg.group(horizontal=True, parent="shape_parts"):
                dpg.add_selectable(label=f"  {grp}", width=px(190), default_value=set(members) <= chosen,
                                   user_data=members, callback=lambda s, a, u: select(app, u))
                c.tip("the group: a click selects every part in it")
                typeface.small(dpg.add_text(f"group of {len(members)}, {sum(counts[k] for k in members)} LEDs", color=c.DIM))
        with dpg.group(horizontal=True, parent="shape_parts", indent=px(14) if grp else 0):
            col = tuple(int(v) for v in part_colour(i)) + (255,)
            dpg.add_color_button(col, width=px(12), height=px(12), no_border=True, no_drag_drop=True, no_tooltip=True)
            row = dpg.add_selectable(label=f"{i + 1:2d}  {part.get('name', part['kind'])}", width=px(176), default_value=(i in chosen),
                                     user_data=i, callback=lambda s, a, u: pick_row(app, u),
                                     drop_callback=lambda s, a: _drop_row(app, s, a), payload_type="shape_part")
            with dpg.drag_payload(parent=row, drag_data=i, payload_type="shape_part"):
                dpg.add_text(f"{part.get('name', part['kind'])}: drop it on a row to wire it there")
            dpg.bind_item_handler_registry(row, "shape_row_handlers")
            flags = "".join(f", {w}" for w, on in (("hidden", part.get("hidden")), ("locked", part.get("locked"))) if on)
            typeface.small(dpg.add_text(f"{part['kind']} · {n} · LEDs {start}-{start + n - 1}{flags}" if n else f"{part['kind']} · no LEDs",
                                        color=c.DIM))
            _icon_toggle("run_back" if part.get("reverse") else "run_on",
                         "its LEDs run the other way: the arrow is the way they run along it (click to turn it round)" if part.get("reverse")
                         else "the way its LEDs run along it: click to turn its wiring round", lambda s, a, u: set_part(app, u, reverse=not _parts(app)[u].get("reverse")), i,
                         active=bool(part.get("reverse")))
            _icon_toggle("eye_off" if part.get("hidden") else "eye",
                         "hidden: dark in the view while you build, not picked - still LEDs on the device (click to show it)" if part.get("hidden")
                         else "shown: click to hide it while you build (it stays LEDs on the device)",
                         lambda s, a, u: set_part(app, u, hidden=not _parts(app)[u].get("hidden")), i, active=bool(part.get("hidden")))
            _icon_toggle("lock" if part.get("locked") else "unlock",
                         "locked: not picked or moved in the view (click to unlock)" if part.get("locked")
                         else "click to lock it: the view's clicks, handles and keys pass it by", lambda s, a, u: set_part(app, u, locked=not _parts(app)[u].get("locked")), i,
                         active=bool(part.get("locked")))
            dpg.add_button(label="x", small=True, user_data=i, callback=lambda s, a, u: del_part(app, u))
            weight.danger(dpg.last_item())
            c.tip("delete the part (Undo brings it back)")
        start += n
    if not parts:
        with dpg.group(parent="shape_parts"):
            dpg.add_text("No parts yet. Add one (Add part...) or draw a run in the 3-D view (Draw a run); File... imports a "
                         "model or an xLights layout.", color=c.DIM, wrap=px(480))
    P = "shape_fields"
    if not chosen:
        dpg.set_value("shape_part_title", "SHAPE"); dpg.set_value("shape_part_kind", "- nothing selected: the shape's own settings")
        _shape_settings(app, P, sp)
    elif len(chosen) == 1 and 0 <= sel < len(parts):
        part = parts[sel]
        dpg.set_value("shape_part_title", f"PART {sel + 1}: {part.get('name', part['kind'])}")
        dpg.set_value("shape_part_kind", f"- {part['kind']}, {counts[sel]} LEDs")
        _part_settings(app, P, sel, part, sp)
    else:
        dpg.set_value("shape_part_title", f"{len(chosen)} PARTS")
        dpg.set_value("shape_part_kind", f"- {sum(counts[i] for i in chosen)} LEDs; part {sel + 1} the active one (the last picked)")
        _several_settings(app, P, sorted(chosen), sp)


def _heading(P, text, info=None):
    c = _c()
    with dpg.group(horizontal=True, parent=P):
        typeface.label(dpg.add_text(text, color=c.ACCENT))
        if info:
            c.info(info)


def _shape_settings(app, P, sp):
    """Nothing selected: the shape's own - its LED density and unit, its layout, the colours the view builds in."""
    c = _c()
    _heading(P, "REAL SIZES", "a shape is measured in LED spacings; its density says what a spacing is on the bench (60 LEDs a "
             "metre: 1.67 cm), and the unit what lengths are shown in. Only what is shown changes: the device gets the "
             "shape fitted to its box as ever.")
    with form.row("LEDs a metre", parent=P, tip="the strip most of the shape is: 30, 60, 96 or 144 a metre are the ones sold"):
        dens = units.density(sp)
        dpg.add_combo([f"{d:g}" for d in units.DENSITIES] + (["%g" % dens] if dens not in units.DENSITIES else []),
                      default_value=f"{dens:g}", width=px(80), callback=lambda s, v: set_shape_option(app, density=float(v)))
        typeface.mono(dpg.add_input_float(default_value=dens, width=px(80), step=0, format="%.4g", on_enter=True,
                                          callback=lambda s, v: set_shape_option(app, density=max(1.0, float(v)))))
        c.tip("any other density: type it and press Enter")
    with form.row("lengths in", parent=P, tip="millimetres, centimetres or inches"):
        dpg.add_combo(list(units.UNITS), default_value=units.unit(sp), width=px(80), callback=lambda s, v: set_shape_option(app, unit=v))
    _heading(P, "THE EFFECTS SEE", "one strip in wiring order (what 1-D effects and the 3-D nodes work on), or a grid the LEDs are "
             "projected onto from the front - or the grid an xLights model came with")
    with form.row("layout", parent=P):
        dpg.add_combo(["strip", "grid"], tag="shape_layout", width=px(80), default_value=sp.get("layout", "strip"),
                      callback=lambda s, v: _apply(app, layout=v))
        dpg.add_button(label="Segment per part", small=True, callback=lambda: segments_per_part(app))
        c.tip("each part its own WLED segment - effect, palette, sliders - up to eight")
    _heading(P, "WHILE YOU BUILD")
    with form.row("colours", parent=P, tip="what the 3-D view shows while you build: each part in a colour of its own (the selected "
                  "one bright, the rest dimmed, the wiring drawn on them), or the effect the sim runs"):
        dpg.add_combo(["the parts", "the effect"], tag="shape_colours", width=px(110),
                      default_value="the effect" if app.prefs.get("shape_colours") == "effect" else "the parts",
                      callback=lambda s, v: _shape_view().set_mode(app, "effect" if v == "the effect" else "parts"))
    _by_hand(app, P)
    with dpg.group(parent=P):
        dpg.add_spacer(height=px(4))
        dpg.add_text("Click a part in the 3-D view (or its row above) for its sizes and place.", color=c.DIM, wrap=px(480))


def _by_hand(app, P):
    """Placing loose LEDs by clicking the view: on a working plane."""
    c = _c()
    with dpg.group(horizontal=True, parent=P):
        typeface.label(dpg.add_text("BY HAND", color=c.ACCENT))
        dpg.add_checkbox(label="place", tag="shape_place", default_value=bool(getattr(app, "_shape_place", False)),
                         callback=lambda s, v: setattr(app, "_shape_place", bool(v)))
        c.tip("click the 3-D view to put an LED on the plane; they go into the selected points part, or a new one; drag one to move it")
        form.inline("plane")
        dpg.add_combo(["z", "y", "x"], tag="shape_plane_axis", width=px(50), default_value=getattr(app, "_shape_plane", ("z", 0.0))[0],
                      callback=lambda s, v: setattr(app, "_shape_plane", (v, getattr(app, "_shape_plane", ("z", 0.0))[1])))
        dpg.add_text("=", color=c.DIM)
        sp = app.project.geometry.params
        typeface.mono(dpg.add_input_float(tag="shape_plane_v", width=px(80),
                                          default_value=units.to_unit(getattr(app, "_shape_plane", ("z", 0.0))[1], sp), step=0,
                                          format=f"%.1f {units.unit(sp)}",
                                          callback=lambda s, v: setattr(app, "_shape_plane", (getattr(app, "_shape_plane", ("z", 0.0))[0],
                                                                                              units.from_unit(float(v), app.project.geometry.params)))))


def set_shape_option(app, **opts):
    """The shape's density or unit (what is shown - the LEDs stay where they are)."""
    _apply(app, **opts)


def _size_fields(app, P, i, part, sp):
    """A part's sizes, from shape_fields: counts, lengths in the unit, LEDs a metre, angles."""
    from native import shape_fields as sf
    c = _c()
    for f in sf.FIELDS.get(part["kind"], []):
        v = sf.value(part, f, sp)
        if f.type in ("box", "turns"):
            with form.row(f.label, parent=P, tip=f.tip or None):
                typeface.mono(dpg.add_text(sf.text(part, f, sp), color=c.DIM))
            continue
        if f.type == "bool":
            form.check(f.label, parent=P, default_value=bool(v), user_data=f,
                       callback=lambda s, a, u: _set_field(app, i, u, bool(a)))
            if f.tip:
                c.tip(f.tip)
            continue
        with form.row(f.label, parent=P, tip=f.tip or None):
            if f.type == "choice":
                dpg.add_combo(shapes.CHOICES.get(f.key, [str(v)]), width=px(150), default_value=str(v), user_data=f,
                              callback=lambda s, a, u: _set_field(app, i, u, a))
            elif f.type == "text":
                typeface.mono(dpg.add_input_text(default_value=str(v), width=px(300), on_enter=True, user_data=f,
                                                 callback=lambda s, a, u: _set_field(app, i, u, a)))
                if part["kind"] == "formula":
                    c.tip("Enter takes it")
            elif f.type == "count":
                num.add(None, int(v), f.lo or 1, f.hi or 4096, integer=True, width=px(120), wide=True, user_data=f,
                        callback=lambda s, a, u: _set_field(app, i, u, int(a)))
            else:
                num.add(None, float(v), None, None, digits=2 if f.type != "angle" else 1, unit=sf.unit_of(f, sp), width=px(120),
                        user_data=f, pace=1.0 if f.type != "angle" else 15.0,
                        callback=lambda s, a, u: _set_field(app, i, u, float(a)))
    if part["kind"] == "formula":
        err = shapes.formula_error(part)
        if err:
            dpg.add_text(f"the formula: {err}", parent=P, color=c.RED, wrap=px(480))


def _set_field(app, i, f, v):
    from native import shape_fields as sf
    parts = json.loads(json.dumps(_parts(app) or []))
    if not (0 <= i < len(parts)):
        return
    parts[i] = sf.put(parts[i], f, v, app.project.geometry.params)
    _apply(app, parts)


def _part_settings(app, P, sel, part, sp):
    c = _c()
    with form.row("name", parent=P):
        dpg.add_input_text(width=px(220), default_value=str(part.get("name", "")), on_enter=True,
                           callback=lambda s, v: set_part(app, sel, name=v))
    if part["kind"] == "reference":
        dpg.add_text(f"{part['params'].get('file', '?')}: {len(part['params'].get('vertices') or [])} vertices, "
                     f"{len(part['params'].get('edges') or [])} edges - drawn in the 3-D view, not LEDs", parent=P, color=c.DIM, wrap=0)
    else:
        _heading(P, "SIZE")
        _size_fields(app, P, sel, part, sp)
        _kind_tools(app, P, sel, part, sp)
    # PLACE: where it stands and which way it lies, in the shape's unit
    _heading(P, "PLACE", "drag a number and the part moves in the 3-D view as you drag (the sim takes it when you let go); "
             "ctrl-click to type. Or drag its handles in the view, or G, R, S there.")
    u = units.unit(sp)
    with form.row("position", parent=P, tip=f"x, y and z in {u}"):
        dpg.add_drag_floatx(width=px(270), size=3, default_value=[units.to_unit(v, sp) for v in part.get("pos", [0, 0, 0])] + [0.0],
                            format=f"%.2f {u}", speed=max(0.01, units.to_unit(0.05, sp)),
                            callback=lambda s, v: nudge(app, sel, pos=[units.from_unit(float(x), app.project.geometry.params) for x in v[:3]]))
    if part["kind"] in LIE_FACE or part["kind"] in LIE_LINE:
        with form.row("lie", parent=P, tip="flat on the floor, standing up facing the front, or facing out from the shape's middle"):
            for label, how in (("flat", "flat"), ("upright", "upright"), ("facing out", "out")):
                dpg.add_button(label=label, small=True, user_data=how, callback=lambda s, a, u: lie(app, sorted(selection(app)), u))
    with form.row("turn 90°", parent=P, tip="a quarter turn about each axis, about the part's own middle"):
        for ax in "XYZ":
            dpg.add_button(label=ax, small=True, user_data=ax, callback=lambda s, a, u: quarter_turn(app, sorted(selection(app)), "XYZ".index(u)))
    # the exact ones, folded: its rotation, scale, the aim
    with dpg.tree_node(label="exact rotation, scale and aim", tag="shape_exact_tn", parent=P,
                       default_open=bool(getattr(app, "_shape_exact", False))):
        _exact(app, "shape_exact_tn", sel, part, sp)
    _copies_settings(app, P, sel, part, sp)
    _heading(P, "WIRING")
    form.check("its LEDs run the other way", parent=P, default_value=bool(part.get("reverse")),
               callback=lambda s, v: set_part(app, sel, reverse=bool(v)))
    with dpg.group(horizontal=True, parent=P):
        dpg.add_text("in the wiring", color=c.DIM)
        from native import shape_tools
        for label, where in (("first", "first"), ("earlier", "earlier"), ("later", "later"), ("last", "last")):
            dpg.add_button(label=label, small=True, user_data=where, callback=lambda s, a, u: shape_tools.wiring_move(app, sel, u))
        dpg.add_button(label="light it", small=True, callback=lambda: shape_tools.light(app, sel))
        c.tip("the wiring test lighting this part: in the sim, and on the device while the sim is streamed to it")


def _copies_settings(app, P, sel, part, sp):
    """COPIES: the part repeated as it is - copies moved and turned from it, mirrors of them - live (S12)."""
    c = _c()
    u = units.unit(sp)
    _heading(P, "COPIES", "the part repeated: copies each moved and turned from the one before, and mirrors of them all. They "
             "are live - change the part and they follow - and one part in the list and the wiring; 'make separate' when "
             "one needs a change of its own.")
    cp = part.get("copies") or {}
    n = max(1, int(cp.get("n", 1) or 1))
    with form.row("copies", parent=P, tip="how many times the part appears, itself included (1: none)"):
        num.add(None, n, 1, 256, integer=True, wide=True, width=px(100), callback=lambda s, v: set_copies(app, sel, n=int(v)))
    if n > 1:
        with form.row("each moved", parent=P, tip=f"each copy moved this far from the one before (x, y, z in {u}, the shape's axes)"):
            dpg.add_drag_floatx(size=3, width=px(270), default_value=[units.to_unit(float(v), sp) for v in (cp.get("step") or [0, 0, 0])[:3]] + [0.0],
                                format=f"%.2f {u}", speed=max(0.01, units.to_unit(0.05, sp)),
                                callback=lambda s, v: set_copies(app, sel, step=[units.from_unit(float(x), app.project.geometry.params) for x in v[:3]]))
        with form.row("each turned", parent=P, tip="each copy turned this far from the one before, about the axis through the "
                      "part's middle or the shape's origin (a ring of copies round the middle: 360 / copies)"):
            num.add(None, float(cp.get("turn", 0.0) or 0.0), None, None, digits=1, unit="°", width=px(100), pace=15.0,
                    callback=lambda s, v: set_copies(app, sel, turn=float(v)))
            dpg.add_combo(["X", "Y", "Z"], default_value=str(cp.get("axis", "z")).upper()[:1] or "Z", width=px(50),
                          callback=lambda s, v: set_copies(app, sel, axis=v.lower()))
            dpg.add_combo(["its middle", "the origin"], default_value="the origin" if cp.get("about") == "origin" else "its middle",
                          width=px(110), callback=lambda s, v: set_copies(app, sel, about="origin" if v == "the origin" else "middle"))
        form.check("every other one runs back", parent=P, default_value=bool(cp.get("zigzag")),
                   callback=lambda s, v: set_copies(app, sel, zigzag=bool(v)))
        c.tip("the wiring comes back along every second copy - strips laid back and forth")
    m = part.get("mirror") or {}
    with form.row("mirrored across", parent=P, tip="the part (its copies too) mirrored exactly across the plane at right angles "
                  "to each axis ticked, through the shape's origin or the part's middle"):
        for a in "xyz":
            dpg.add_checkbox(label=a.upper(), default_value=bool(m.get(a)), user_data=a,
                             callback=lambda s, v, ax: set_mirror(app, sel, **{ax: bool(v)}))
        dpg.add_combo(["the origin", "its middle"], default_value="its middle" if m.get("about") == "middle" else "the origin",
                      width=px(110), callback=lambda s, v: set_mirror(app, sel, about="middle" if v == "its middle" else "origin"))
    if any(m.get(a) for a in "xyz"):
        form.check("the mirror runs back", parent=P, default_value=bool(m.get("back")),
                   callback=lambda s, v: set_mirror(app, sel, back=bool(v)))
        c.tip("the mirrored LEDs wired from their far end, so the chain comes back the way it went")
    if n > 1 or any(m.get(a) for a in "xyz"):
        with dpg.group(horizontal=True, parent=P):
            dpg.add_button(label="make separate", small=True, callback=lambda: make_separate(app, sel))
            c.tip(f"the {shapes.copies(part)} as parts of their own, the LEDs where they are: copies the same kind, "
                  "mirrors loose points (no turn makes a mirror)")


def set_copies(app, i, **kw):
    parts = json.loads(json.dumps(_parts(app) or []))
    if 0 <= i < len(parts):
        c = parts[i].setdefault("copies", {})
        c.update(kw)
        if c.get("n", 1) > 1 and not any(c.get("step") or []) and not c.get("turn"):
            # copies at first: a row along X, a gap past the part's own length
            pos, _ = shapes.transform(dict(parts[i], reverse=False), *shapes.part_points(parts[i]))
            span = float(np.ptp(pos[:, 0])) if len(pos) else 0.0
            c["step"] = [round(span + 2.0, 4), 0.0, 0.0]
        _apply(app, parts, refit="grow")


def set_mirror(app, i, **kw):
    parts = json.loads(json.dumps(_parts(app) or []))
    if 0 <= i < len(parts):
        parts[i].setdefault("mirror", {}).update(kw)
        _apply(app, parts, refit="grow")


def make_separate(app, i):
    """A part's copies and mirrors as parts of their own, the LEDs where they were."""
    parts = json.loads(json.dumps(_parts(app) or []))
    if not (0 <= i < len(parts)):
        return
    pieces = shapes.separate(parts[i])
    parts[i:i + 1] = pieces
    _set_sel(app, set(range(i, i + len(pieces))), i)
    _apply(app, parts)
    app.gp.status(f"{len(pieces)} parts, the LEDs where they were")


def _kind_tools(app, P, sel, part, sp):
    """What only some kinds have: a path's corners, loose points' tools, a solid split into parts."""
    c = _c()
    if part["kind"] == "polyhedron":
        with dpg.group(horizontal=True, parent=P):
            dpg.add_button(label="split into parts", small=True, callback=lambda: split_polyhedron(app, sel))
            c.tip("a strip per edge (or a polygon per face, in faces mode), the LEDs where they were - each then moved, turned and counted alone")
    if part["kind"] == "polyline":
        _shape_run().corners_table(app, P, sel, part, sp)
    if part["kind"] == "points":
        pts = part["params"].get("points") or []
        dpg.add_text(f"{len(pts)} point(s) - place more: BY HAND below the list with nothing selected, or tick 'place' there",
                     parent=P, color=c.DIM, wrap=px(480))
        with dpg.group(horizontal=True, parent=P):
            dpg.add_button(label="delete the last", small=True, callback=lambda: pop_point(app, sel))
            weight.danger(dpg.last_item())
            dpg.add_button(label="renumber: nearest chain from the first", small=True, callback=lambda: chain_part(app, sel))
            dpg.add_button(label="turn into a path", small=True, callback=lambda: set_part(app, sel, kind="polyline"))
        _by_hand(app, P)


def _exact(app, parent, sel, part, sp):
    """The part's rotation (three angles), scale, and AIM - folded under PLACE."""
    c = _c()
    with form.row("rotation", parent=parent, tip="about x, y and z, in degrees"):
        dpg.add_drag_floatx(width=px(270), size=3, default_value=list(part.get("rot", [0, 0, 0])) + [0.0], format="%.1f°",
                            speed=0.5, callback=lambda s, v: nudge(app, sel, rot=[float(x) for x in v[:3]]))
    sc = part.get("scale", 1.0)
    with form.row("scale", parent=parent):
        num.add(None, float(sc if not isinstance(sc, list) else sc[0]), 0.01, 100.0, log=True, digits=2, unit="×", width=px(110),
                callback=lambda s, v: nudge(app, sel, scale=float(v)))
    # AIM: the part's axis along a direction, at a distance from the origin - the way to build round a ball by hand
    ax = shapes.axis_of(part)
    axname = {(1.0, 0.0, 0.0): "its length", (0.0, -1.0, 0.0): "its face"}.get(tuple(ax), "its normal (+Z)")
    ppos = np.asarray(part.get("pos", [0, 0, 0]), np.float64); dist = float(np.linalg.norm(ppos))
    d0 = (ppos / dist) if dist > 1e-6 else np.array([0.0, 0.0, 1.0])
    with dpg.group(horizontal=True, parent=parent):
        typeface.label(dpg.add_text("AIM", color=c.ACCENT))
        c.info(f"point {axname} along the direction (x y z, or azimuth and elevation, or an axis button). 'aim outward' also puts the part "
               "the distance from the origin along it; 'turn only' keeps its place; 'aim at the origin' points it inward from where it is. "
               "Spin turns it about the direction.")
    with form.row("direction", parent=parent, tip="x, y and z - or its azimuth and elevation, in degrees"):
        dpg.add_input_floatx(tag="shape_aim_dir", width=px(200), size=3, default_value=[float(v) for v in d0] + [0.0], format="%.3f",
                             callback=lambda s, v: _dir_to_angles(v))
        az, el = _angles_of(d0)
        form.inline("az")
        dpg.add_input_float(tag="shape_aim_az", width=px(70), default_value=az, step=0, format="%.1f°", callback=lambda: _angles_to_dir())
        form.inline("el")
        dpg.add_input_float(tag="shape_aim_el", width=px(70), default_value=el, step=0, format="%.1f°", callback=lambda: _angles_to_dir())
    u = units.unit(sp)
    with form.row("distance", parent=parent, tip=f"from the origin, for 'aim outward' ({u})"):
        dpg.add_input_float(tag="shape_aim_dist", width=px(90), default_value=units.to_unit(dist, sp), step=0, format=f"%.2f {u}")
        form.inline("spin")
        dpg.add_input_float(tag="shape_aim_spin", width=px(70), default_value=0.0, step=0, format="%.1f°")
        c.tip("a turn about the direction, in degrees")
        for lbl, v in (("+X", (1, 0, 0)), ("-X", (-1, 0, 0)), ("+Y", (0, 1, 0)), ("-Y", (0, -1, 0)), ("+Z", (0, 0, 1)), ("-Z", (0, 0, -1))):
            dpg.add_button(label=lbl, small=True, user_data=v, callback=lambda s, a, u: _set_dir(u))
    with dpg.group(horizontal=True, parent=parent):
        dpg.add_button(label="aim outward", small=True, callback=lambda: aim_part(app, sel, "outward"))
        dpg.add_button(label="turn only", small=True, callback=lambda: aim_part(app, sel, "turn"))
        dpg.add_button(label="aim at the origin", small=True, callback=lambda: aim_part(app, sel, "origin"))
        dpg.add_button(label="from its place", small=True, callback=lambda: _set_dir(list(d0), units.to_unit(dist, sp)))
        c.tip("the direction and distance the part is at now, into the fields")


def _several_settings(app, P, idxs, sp):
    """Several selected: lining them up to the active part, spreading them, one turn or scale for all."""
    c = _c()
    _heading(P, "ARRANGE", "the selected parts lined up to the active one (the last picked, whose row is lit brightest) on an axis, "
             "spread evenly along one between the two farthest apart, or given its scale or turn")
    dpg.add_text("", tag="shape_arrange_hint", parent=P, color=c.DIM)
    with dpg.group(horizontal=True, parent=P):
        dpg.add_text("align", color=c.DIM)
        for ax, lbl in enumerate("XYZ"):
            dpg.add_button(label=lbl, small=True, user_data=ax, callback=lambda s, a, u: align_parts(app, u))
        c.tip("the selected parts given the active part's position on that axis")
        dpg.add_text("  spread", color=c.DIM)
        for ax, lbl in enumerate("XYZ"):
            dpg.add_button(label=lbl, small=True, user_data=ax, callback=lambda s, a, u: distribute_parts(app, u))
        c.tip("the selected parts (three or more) spaced evenly along that axis between the two farthest apart")
    with dpg.group(horizontal=True, parent=P):
        dpg.add_button(label="same scale", small=True, callback=lambda: match_parts(app, "scale"))
        dpg.add_button(label="same turn", small=True, callback=lambda: match_parts(app, "rot"))
        c.tip("the selected parts given the active part's scale, or its rotation")
    with form.row("lie", parent=P, tip="each part flat on the floor, standing up facing the front, or facing out from the shape's middle"):
        for label, how in (("flat", "flat"), ("upright", "upright"), ("facing out", "out")):
            dpg.add_button(label=label, small=True, user_data=how, callback=lambda s, a, u: lie(app, sorted(selection(app)), u))
    with form.row("turn 90°", parent=P, tip="each part a quarter turn about each axis, about its own middle"):
        for ax in "XYZ":
            dpg.add_button(label=ax, small=True, user_data=ax, callback=lambda s, a, u: quarter_turn(app, sorted(selection(app)), "XYZ".index(u)))
    with dpg.group(horizontal=True, parent=P):
        dpg.add_button(label="all", small=True, callback=lambda: select(app, range(len(_parts(app) or []))))
        c.tip("every part selected (A with the pointer on the 3-D view)")
        dpg.add_button(label="none", small=True, callback=lambda: select(app, []))
        dpg.add_button(label="group them...", small=True, callback=lambda: _ask_group(app, idxs))
        c.tip("a name for these parts together: a heading in the list that selects them all (a tree's strands, a room's walls)")
        if any((_parts(app) or [])[i].get("group") for i in idxs):
            dpg.add_button(label="ungroup", small=True, callback=lambda: set_group(app, idxs, ""))
            c.tip("the parts on their own again")
    _arrange_hint(app)


def _ask_group(app, idxs):
    from native import chrome
    parts = _parts(app) or []
    have = next((parts[i].get("group") for i in idxs if 0 <= i < len(parts) and parts[i].get("group")), "")
    chrome.ask(app, "Group the parts", "a name for them together", have or f"group {len({q.get('group') for q in parts if q.get('group')}) + 1}",
               lambda v: set_group(app, idxs, v) if v else None)


def set_group(app, idxs, name):
    """The parts given a group's name ("": none)."""
    parts = json.loads(json.dumps(_parts(app) or []))
    for i in idxs:
        if 0 <= i < len(parts):
            if name:
                parts[i]["group"] = str(name)
            else:
                parts[i].pop("group", None)
    _apply(app, parts)
    app.gp.status(f"{len(idxs)} part(s) grouped as {name}" if name else f"{len(idxs)} part(s) ungrouped")


def lie(app, idxs, how):
    """Each part laid flat, stood upright facing the front, or turned to face
    out from the shape's middle - its place kept."""
    parts = json.loads(json.dumps(_parts(app) or []))
    if not parts:
        return
    pos, _, _ = shapes.resolve(parts)
    mid = (pos.min(0) + pos.max(0)) * 0.5 if len(pos) else np.zeros(3)
    done = 0
    for i in idxs:
        if not (0 <= i < len(parts)):
            continue
        q = parts[i]; k = q["kind"]
        if k in LIE_FACE:
            face = LIE_FACE[k]
            if how == "flat":
                d = (0.0, 0.0, 1.0)
            elif how == "upright":
                d = (0.0, -1.0, 0.0)
            else:
                d = np.asarray(q.get("pos", [0, 0, 0]), np.float64) - mid; d[2] = 0.0
                d = d if np.linalg.norm(d) > 1e-6 else np.array([0.0, -1.0, 0.0])
            q["rot"] = shapes.aim_rotation(face, d)
        elif k in LIE_LINE:
            R = shapes.rotation(*q.get("rot", [0, 0, 0]))
            along = R @ np.array([1.0, 0.0, 0.0])
            if how == "flat":
                d = np.array([along[0], along[1], 0.0]); d = d if np.linalg.norm(d) > 1e-6 else np.array([1.0, 0.0, 0.0])
            elif how == "upright":
                d = np.array([0.0, 0.0, 1.0])
            else:
                d = np.asarray(q.get("pos", [0, 0, 0]), np.float64) - mid; d[2] = 0.0
                d = d if np.linalg.norm(d) > 1e-6 else np.array([1.0, 0.0, 0.0])
            q["rot"] = shapes.aim_rotation((1.0, 0.0, 0.0), d)
        else:
            continue
        done += 1
    if done:
        _apply(app, parts)
        app.gp.status(f"{done} part(s) {'laid flat' if how == 'flat' else 'stood up' if how == 'upright' else 'facing out'}")
    else:
        app.gp.status("a solid has no face to lie on: turn it with the handles, R, or 'turn 90°'")


def quarter_turn(app, idxs, axis):
    """Each part a quarter turn about a world axis through its own place."""
    parts = json.loads(json.dumps(_parts(app) or []))
    e = np.zeros(3); e[axis] = 1.0
    R = shapes.axis_rotation(e, 90.0)
    for i in idxs:
        if 0 <= i < len(parts):
            parts[i] = shapes.turned(parts[i], R, parts[i].get("pos", [0, 0, 0]))
    _apply(app, parts)


def _undo_buttons(app):
    """Undo and Redo greyed when there is nothing to step to."""
    for tag, stack in (("shape_undo_btn", "_shape_undo"), ("shape_redo_btn", "_shape_redo")):
        if dpg.does_item_exist(tag):
            dpg.configure_item(tag, enabled=bool(getattr(app, stack, None)))


# --- edits -----------------------------------------------------------------------------------
def add_part(app, kind):
    """A part of a kind, with its defaults, placed and wired as the gallery's Add does (shape_gallery.add)."""
    from native import shape_gallery
    shape_gallery.add(app, shapes.new_part(kind), close=False)


def del_part(app, i):
    parts = list(_parts(app) or [])
    if 0 <= i < len(parts):
        parts.pop(i)
        _set_sel(app, {min(i, len(parts) - 1)} if parts else set())
        _apply(app, parts)


def dup_part(app, i):
    parts = list(_parts(app) or [])
    if 0 <= i < len(parts):
        q = json.loads(json.dumps(parts[i]))
        q["name"] = q.get("name", q["kind"]) + " copy"
        parts.insert(i + 1, q)
        _set_sel(app, {i + 1})
        _apply(app, parts, refit="grow")


def move_part(app, i, d):
    parts = list(_parts(app) or [])
    j = i + d
    if 0 <= i < len(parts) and 0 <= j < len(parts):
        parts[i], parts[j] = parts[j], parts[i]
        _set_sel(app, {j})
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
        _set_sel(app, set(range(i, i + len(pieces))), i)
        _apply(app, parts, refit="grow")
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


def _arrange_hint(app):
    if dpg.does_item_exist("shape_arrange_hint"):
        n = len(selection(app))
        dpg.set_value("shape_arrange_hint", f"{n} selected" if n > 1 else "select two or more: Shift-click in the view or the list")


def _marked(app):
    return sorted(selection(app))


def align_parts(app, axis):
    idxs = _marked(app)
    if not idxs:
        app.gp.status("select the parts to align (Shift-click them in the view or the list)"); return
    _apply(app, shapes.aligned(_parts(app), idxs, _sel(app), axis))
    app.gp.status(f"{len(idxs)} part(s) aligned on {'xyz'[axis]} to part {_sel(app) + 1}")


def distribute_parts(app, axis):
    idxs = _marked(app)
    if len(idxs) < 3:
        app.gp.status("select three parts or more to spread them"); return
    _apply(app, shapes.distributed(_parts(app), idxs, axis))
    app.gp.status(f"{len(idxs)} parts spread evenly along {'xyz'[axis]}")


def match_parts(app, what):
    idxs = _marked(app)
    if not idxs:
        app.gp.status("select the parts to match (Shift-click them in the view or the list)"); return
    _apply(app, shapes.matched(_parts(app), idxs, _sel(app), what))
    app.gp.status(f"{len(idxs)} part(s) given part {_sel(app) + 1}'s {'turn' if what == 'rot' else 'scale'}")


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
            _set_sel(app, set(range(len(parts) - len(new), len(parts))), len(parts) - 1)
            _apply(app, parts, refit="grow")
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
    _set_sel(app, {len(parts) - 1})
    _apply(app, parts, refit="grow", **more)
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
    _set_sel(app, {0})
    _apply(app, refit="all", **g.params)


# --- the 3-D view: the selection, placing and dragging LEDs by hand -------------------------
# (what the view draws while a shape is built - the parts' colours, the wiring, the part under
# the pointer - is shape_view's; the camera is view3d's)
def view_colours(app, rgb):
    """The 3-D view's colours this frame (shape_view.colours)."""
    from native import shape_view
    return shape_view.colours(app, rgb)


def view_key_ok(app, action):
    """Whether one of the 3-D view's keys applies now: the camera's always;
    the shape's while a shape is built (else the key's other binding - G the
    graph pane - has it)."""
    if not action.startswith("shape_"):
        return True
    from native import view3d
    return view3d.editing(app)


def frame_selection(app):
    """F over the view: the camera on the selected parts while a shape is
    built, else everything."""
    from native import view3d, shape_view
    parts = _parts(app)
    sel = selection(app)
    if view3d.editing(app) and parts and sel:
        g = shape_view.drawn(app)
        if g is not None and g.kind == "shape":
            W, owner = shape_view.wiring(g)
            pts = W[np.isin(owner, sorted(sel))]
            if len(pts):
                view3d.frame_points(app, pts)
                return
    view3d.home(app)


def _plane(app):
    ax, v = getattr(app, "_shape_plane", ("z", 0.0))
    return {"x": 0, "y": 1, "z": 2}[ax], float(v)


def _hit(app, mx, my):
    """The LED under the pointer: (part index, point index within a points part) or None."""
    from native import shape_view
    v = shape_view.view(app)
    if v is None:
        return None
    g = shape_view.drawn(app)
    got = shape_view.pick(app, v, mx, my, g)
    if got is None:
        return None
    k, pi = got
    parts = _parts(app) or []
    if not (0 <= pi < len(parts)):
        return None
    if parts[pi]["kind"] != "points":
        return (pi, None)
    # which of the part's points: its index in the part's order (reverse and the transform kept)
    _, owner = shape_view.wiring(g)
    n_before = int((owner[:k] == pi).sum())
    n = shapes.part_count(parts[pi])
    return (pi, (n - 1 - n_before) if parts[pi].get("reverse") else n_before)


def _local(part, p):
    """A point of the shape into a part's own frame: its move, rotation and scale undone."""
    R = shapes.rotation(*part.get("rot", [0, 0, 0]))
    s = part.get("scale", 1.0); s = np.asarray(s if isinstance(s, list) else [s, s, s], np.float32)
    return ((np.asarray(p, np.float32) - np.asarray(part.get("pos", [0, 0, 0]), np.float32)) @ R) / np.where(s != 0, s, 1)


def click(app, at=None):
    """A click on the 3-D view while placing: an LED under the pointer is
    picked up, else a new one is put on the plane. True when handled."""
    if not getattr(app, "_shape_place", False) or _parts(app) is None:
        return False
    from native import shape_view
    v = shape_view.view(app)
    if v is None:
        return False
    mx, my = at or dpg.get_mouse_pos(local=False)
    hit = _hit(app, mx, my)
    if hit and hit[1] is not None:
        app._shape_drag = hit
        _set_sel(app, {hit[0]})
        return True
    axis, value = _plane(app)
    p = shape_view.unproject(v, mx, my, axis, value)
    if p is None:
        app.gp.status("the plane is edge-on here: turn the view, or choose another plane"); return True
    parts = json.loads(json.dumps(_parts(app) or []))
    sel = _sel(app)
    if sel < 0 or parts[sel]["kind"] != "points":
        parts.append(shapes.new_part("points", points=[])); parts[-1]["name"] = f"placed {sum(1 for q in parts if q['kind'] == 'points')}"
        sel = len(parts) - 1
    part = parts[sel]
    local = _local(part, p)
    if part.get("reverse"):
        part["params"].setdefault("points", []).insert(0, [round(float(c), 3) for c in local])
    else:
        part["params"].setdefault("points", []).append([round(float(c), 3) for c in local])
    _set_sel(app, {sel})
    _apply(app, parts)
    return True


def drag(app):
    """The pointer moving with an LED picked up: it follows on the plane (applied on release)."""
    hit = getattr(app, "_shape_drag", None)
    if not hit:
        return False
    from native import shape_view
    v = shape_view.view(app)
    if v is None:
        return True
    mx, my = dpg.get_mouse_pos(local=False)
    axis, value = _plane(app)
    p = shape_view.unproject(v, mx, my, axis, value)
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
    local = _local(part, to)
    pts = part["params"].get("points") or []
    if 0 <= k < len(pts):
        pts[k] = [round(float(c), 3) for c in local]
        _apply(app, parts)
    return True


def poll(app):
    """Per frame: the preview's frames, a drag's commit, and the view's
    overlay (shape_view: the wiring, the part under the pointer, the
    reference wireframes)."""
    _poll_preview(app)
    _poll_pending(app)
    from native import shape_view, shape_tools
    shape_tools.poll(app)                                   # a modal move following the pointer, before the overlay draws it
    shape_view.poll(app)
