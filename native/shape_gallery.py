"""Add a part from pictures (the ninth pass's S9).

The Shape frame's "Add part..." opens this: a picture of every kind of part,
grouped - lines, flat, solid, free - and from a file. A picture chosen asks
that kind's natural sizes in the shape's unit (shape_fields' "ask" fields,
with what the part comes to - its LEDs, its size - as they change); Add puts
it in: a line joined to the end of the selected part (its first LED one
spacing on from that part's last, running on the same way), anything else
beside the selection; next after it in the wiring, selected.

    shape_gallery.build(app)            # the window, once (shape_ui.build calls it)
    shape_gallery.show(app, kind=None)  # open it, on a kind
    shape_gallery.add(app, part)        # a made part into the shape, placed and wired as above
"""
import json

import numpy as np
import dearpygui.dearpygui as dpg

from native import shapes, units, render, typeface, form, num, weight
from native.typeface import px

TAG = "shape_gallery"
GROUPS = (("LINES", ("strip", "polyline", "arch", "helix", "spiral")),
          ("FLAT", ("ring", "rings", "polygon", "star", "spokes", "frame", "panel")),
          ("SOLID", ("cube", "cylinder", "sphere", "tree", "polyhedron")),
          ("FREE", ("points", "formula")))
NAMES = {"polyline": "path", "points": "loose points", "rings": "rings in rings", "polyhedron": "a solid's edges",
         "spokes": "spokes", "frame": "frame (window, door)", "helix": "helix (round a tube)", "spiral": "flat spiral"}
JOINED = ("strip", "polyline", "arch", "helix", "spiral")      # the kinds that carry on from the end of the selected part
THUMB = 88


def name_of(kind):
    return NAMES.get(kind, kind)


def _sample(kind):
    """A part to draw a kind's picture from: its defaults (loose points and a path given a few)."""
    if kind == "points":
        rs = np.random.RandomState(7)
        return shapes.new_part("points", points=np.round(rs.uniform(-6, 6, (18, 3)), 2).tolist())
    if kind == "polyline":
        return shapes.new_part("polyline", points=[[0, 0, 0], [8, 0, 0], [8, 8, 0], [16, 8, 4]])
    return shapes.new_part(kind)


def _picture(kind, size):
    """The kind's picture: its LEDs from above and to the side, dim to bright along the wiring."""
    part = _sample(kind)
    pos, _, _ = shapes.resolve([part])
    n = len(pos)
    t = np.linspace(0.35, 1.0, max(1, n))[:, None]
    from native import chrome
    acc = np.asarray(chrome.ACCENT[:3], np.float32)
    rgb = np.clip(acc * t + (255 - acc) * 0.25 * t, 0, 255).astype(np.uint8)
    yaw, pitch = (-0.6, 0.75)
    if kind in ("panel", "arch", "frame"):
        yaw, pitch = (3.0, 0.35)                                # the upright ones from nearly the front
    img = render.render_points(pos, rgb, size, yaw, pitch, 4.2, led=0.34, bg=tuple(chrome.PANEL[:3]))
    return img


def _texture(kind):
    tag = f"gallery_tex_{kind}"
    if dpg.does_item_exist(tag):
        return tag
    from native.textures import registry
    size = px(THUMB)
    dpg.add_static_texture(size, size, render.texture_rgba(_picture(kind, size)), tag=tag, parent=registry())
    return tag


def build(app):
    from native import chrome
    with dpg.window(tag=TAG, label="Add a part", no_title_bar=True, show=False, width=px(760), height=px(600), no_collapse=True):
        chrome.dialog_header(TAG, "Add a part")
        with dpg.group(horizontal=True):
            with dpg.child_window(tag="gallery_tiles", width=px(452), height=-px(8), border=False):
                pass
            with dpg.child_window(tag="gallery_form", width=-1, height=-px(8), border=True):
                pass


def show(app, kind=None):
    """Open the gallery on a kind (the last one added, at first a strip)."""
    from native import chrome
    if not dpg.does_item_exist(TAG):
        return
    _fill_tiles(app)
    choose(app, kind or getattr(app, "_gallery_kind", None) or "strip")
    chrome._centre(TAG, 760, 600)
    dpg.show_item(TAG)
    dpg.focus_item(TAG)


def _fill_tiles(app):
    from native import chrome
    dpg.delete_item("gallery_tiles", children_only=True)
    P = "gallery_tiles"
    per_row = 4
    for title, kinds in GROUPS:
        typeface.label(dpg.add_text(title, parent=P, color=chrome.ACCENT))
        for r in range(0, len(kinds), per_row):
            with dpg.group(horizontal=True, parent=P):
                for k in kinds[r:r + per_row]:
                    with dpg.group():
                        dpg.add_image_button(_texture(k), width=px(THUMB), height=px(THUMB), frame_padding=2, user_data=k,
                                             tag=f"gallery_tile_{k}", callback=lambda s, a, u: choose(app, u))
                        chrome.tip(shapes.KINDS[k][1])
                        dpg.add_text(name_of(k), wrap=px(THUMB), color=chrome.TEXT)
        dpg.add_spacer(height=px(4), parent=P)
    typeface.label(dpg.add_text("FROM A FILE", parent=P, color=chrome.ACCENT))
    from native import shape_ui
    with dpg.group(horizontal=True, parent=P):
        dpg.add_button(label="A model or an xLights layout...", callback=lambda: (dpg.hide_item(TAG), shape_ui._import(app, False)))
        chrome.tip("a mesh (.obj, .ply, .stl) as LEDs along its edges, at its corners or over it; an xLights .xmodel or a whole "
                   "layout (xlights_rgbeffects.xml): its trees, stars, arches, spinners and frames as the parts here; an x y z point list")
        dpg.add_button(label="A reference mesh...", callback=lambda: (dpg.hide_item(TAG), shape_ui._import(app, True)))
        chrome.tip("a mesh drawn in the 3-D view to place LEDs against, not LEDs: the tree, the house, the enclosure")


def choose(app, kind):
    """A picture picked: its sizes asked, with what the part comes to."""
    from native import chrome, shape_fields as sf
    if kind not in shapes.KINDS:
        kind = "strip"
    app._gallery_kind = kind
    app._gallery_part = _sample(kind) if kind in ("polyline", "points") else shapes.new_part(kind)
    for _, kinds in GROUPS:
        for k in kinds:
            if dpg.does_item_exist(f"gallery_tile_{k}"):
                (weight.primary if k == kind else weight.plain)(f"gallery_tile_{k}")
    dpg.delete_item("gallery_form", children_only=True)
    P = "gallery_form"
    sp = app.project.geometry.params if app.project.geometry.kind == "shape" else {}
    typeface.heading(dpg.add_text(name_of(kind).capitalize(), parent=P, color=chrome.ACCENT))
    dpg.add_text(shapes.KINDS[kind][1], parent=P, color=chrome.DIM, wrap=px(270))
    dpg.add_spacer(height=px(4), parent=P)
    for f in sf.FIELDS.get(kind, []):
        if not f.ask:
            continue
        v = sf.value(app._gallery_part, f, sp)
        if f.type == "bool":
            form.check(f.label, width=110, parent=P, default_value=bool(v), user_data=f, callback=lambda s, a, u: _set(app, u, bool(a)))
            continue
        with form.row(f.label, width=110, parent=P, tip=f.tip or None):
            if f.type == "choice":
                dpg.add_combo(shapes.CHOICES.get(f.key, [str(v)]), default_value=str(v), width=px(150), user_data=f,
                              callback=lambda s, a, u: _set(app, u, a))
            elif f.type == "text":
                typeface.mono(dpg.add_input_text(default_value=str(v), width=px(150), user_data=f, callback=lambda s, a, u: _set(app, u, a)))
            elif f.type == "count":
                num.add(None, int(v), f.lo or 1, f.hi or 4096, integer=True, wide=True, width=px(120), user_data=f,
                        callback=lambda s, a, u: _set(app, u, int(a)))
            else:
                num.add(None, float(v), None, None, digits=2 if f.type != "angle" else 1, unit=sf.unit_of(f, sp), width=px(120),
                        user_data=f, pace=1.0, callback=lambda s, a, u: _set(app, u, float(a)))
    dpg.add_spacer(height=px(4), parent=P)
    dpg.add_text("", tag="gallery_amounts", parent=P, color=chrome.TEXT, wrap=px(270))
    dpg.add_text("", tag="gallery_where", parent=P, color=chrome.DIM, wrap=px(270))
    dpg.add_spacer(height=px(6), parent=P)
    with dpg.group(horizontal=True, parent=P):
        dpg.add_button(label="Add", tag="gallery_add", width=px(90), callback=lambda: add(app, app._gallery_part, close=True))
        weight.primary("gallery_add")
        chrome.tip("into the shape, placed as said above; the gallery closes (Add another keeps it open)")
        dpg.add_button(label="Add another", callback=lambda: add(app, app._gallery_part, close=False))
        chrome.tip("into the shape, and the gallery stays open for the next")
    _amounts(app)


def _set(app, f, v):
    from native import shape_fields as sf
    sp = app.project.geometry.params if app.project.geometry.kind == "shape" else {}
    app._gallery_part = sf.put(app._gallery_part, f, v, sp)
    _amounts(app)


def _amounts(app):
    """What the part comes to, and where it will go."""
    from native import shape_fields as sf, shape_ui
    part = app._gallery_part
    sp = app.project.geometry.params if app.project.geometry.kind == "shape" else {}
    n = shapes.part_count(part)
    extra = ""
    if part["kind"] in shapes.LINEAR:
        pos, _ = shapes.part_points(part)
        seg = np.linalg.norm(np.diff(pos, axis=0), axis=1) if len(pos) > 1 else np.zeros(0)
        extra = f", {units.show(float(seg.sum()) + (float(np.median(seg)) if len(seg) else 0.0), sp)} of strip"
    if dpg.does_item_exist("gallery_amounts"):
        dpg.set_value("gallery_amounts", f"{n} LEDs{extra}  ·  {sf.box(part, sp)}")
    parts = shape_ui._parts(app) or []
    sel = shape_ui._sel(app) if parts else -1
    if not parts:
        where = "the first part of the shape, at its middle"
    elif sel >= 0 and part["kind"] in JOINED and shapes.ends(parts[sel]) is not None:
        where = f"joined to the end of {parts[sel].get('name', parts[sel]['kind'])}, running on its way; next after it in the wiring"
    elif sel >= 0:
        where = f"beside {parts[sel].get('name', parts[sel]['kind'])}; next after it in the wiring"
    else:
        where = "beside the shape; last in the wiring"
    if dpg.does_item_exist("gallery_where"):
        dpg.set_value("gallery_where", where)


def placed(parts, sel, part):
    """The new part placed: joined on from the selected part's end (a line),
    or beside the selection (or the shape) - its bottom level with it."""
    q = json.loads(json.dumps(part))
    if not parts:
        return q
    if 0 <= sel < len(parts) and q["kind"] in JOINED:
        e = shapes.ends(parts[sel])
        if e is not None and e[3] is not None:
            _, _, last, dout, sp = e
            local = dict(q, pos=[0.0, 0.0, 0.0], rot=[0.0, 0.0, 0.0], reverse=False)
            P, _ = shapes.transform(local, *shapes.part_points(local))
            if len(P) >= 2:
                d_in = P[1] - P[0]
                spacing = float(np.linalg.norm(d_in)) or sp
                q["rot"] = shapes.aim_rotation(d_in, dout)
                R = shapes.rotation(*q["rot"])
                target = last + dout * max(sp, spacing)
                q["pos"] = [round(float(v), 4) for v in target - R @ P[0]]
                return q
    # beside: to the right (+X) of the selected part (or the whole shape), a gap between, its foot level
    ref = [parts[sel]] if 0 <= sel < len(parts) else parts
    pos, _, _ = shapes.resolve(ref)
    mine, _, _ = shapes.resolve([dict(q, pos=[0.0, 0.0, 0.0])])
    if len(pos) == 0 or len(mine) == 0:
        return q
    gap = 3.0
    x = float(pos[:, 0].max()) + gap - float(mine[:, 0].min())
    y = float((pos[:, 1].min() + pos[:, 1].max()) / 2) - float((mine[:, 1].min() + mine[:, 1].max()) / 2)
    z = float(pos[:, 2].min()) - float(mine[:, 2].min())
    q["pos"] = [round(x, 4), round(y, 4), round(z, 4)]
    return q


def add(app, part, close=True):
    """The part into the shape: placed, named, next after the selected part in the wiring (last with none), selected."""
    from native import shape_ui
    parts = list(shape_ui._parts(app) or [])
    sel = shape_ui._sel(app) if parts else -1
    q = placed(parts, sel, part)
    q["name"] = f"{name_of(q['kind'])} {sum(1 for p in parts if p['kind'] == q['kind']) + 1}"
    at = sel + 1 if 0 <= sel < len(parts) else len(parts)
    parts.insert(at, q)
    shape_ui._set_sel(app, {at})
    shape_ui._apply(app, parts, refit="grow")
    app.gp.status(f"{q['name']} added: {shapes.part_count(q)} LEDs, part {at + 1} in the wiring")
    if close and dpg.does_item_exist(TAG):
        dpg.hide_item(TAG)
    elif dpg.does_item_exist(TAG) and dpg.is_item_shown(TAG) and getattr(app, "_gallery_part", None) is not None:
        _amounts(app)                                       # the gallery open: where the next one would go
