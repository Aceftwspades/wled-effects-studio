"""A starting point for a shape (the ninth pass's S17).

With no parts yet the Shape frame's list is a start: objects people light,
ready to size - a matrix, a cube, a sphere, a Christmas tree, a star, the
241-LED ring disc, a room's ceiling outline, a window, an infinity cube, a
soccer ball, a helix column, a spiral disc - each opening the add gallery
on its kind with its sizes filled in (in the shape's unit); and drawing a
run, importing a model or an xLights layout, mapping lights by camera.
Choosing "shape" in the panel's GEOMETRY changes nothing until a first part
goes in.

    shape_start.OBJECTS                  # (label, kind, params, rot, what)
    shape_start.fill(app, parent)        # the start, into the list's place
    shape_start.part(i)                  # object i as a part (its settings, turned as it stands)
"""
import dearpygui.dearpygui as dpg

from native import shapes
from native.typeface import px

# sizes at 60 LEDs a metre (a spacing 1.67 cm): a 180 cm tree is 108 spacings
OBJECTS = (
    ("Matrix", "panel", {"w": 16, "h": 16}, None, "a 16 x 16 panel, standing"),
    ("Cube", "cube", {"B": 8}, None, "panels on five faces (six with the bottom)"),
    ("Sphere", "sphere", {"w": 24, "h": 12}, None, "rows round a ball"),
    ("Christmas tree", "tree", {"strands": 12, "per_strand": 50, "height": 108.0, "base": 60.0, "top": 3.0, "zigzag": True}, None,
     "12 strands of 50 down a 180 cm cone"),
    ("Star", "star", {"points": 5, "per_edge": 10}, [90.0, 0.0, 0.0], "a five-pointed star, standing"),
    ("Ring disc", "rings", {"counts": "1,8,12,16,24,32,40,48,60"}, [90.0, 0.0, 0.0], "the 241-LED board of nine rings"),
    ("Room outline", "frame", {"w": 240, "h": 180}, [90.0, 0.0, 0.0], "strips round a 4 x 3 m ceiling, laid flat"),
    ("Window", "frame", {"w": 60, "h": 90}, None, "a 1 x 1.5 m window's frame"),
    ("Infinity cube", "polyhedron", {"solid": "cube", "mode": "edges", "per_edge": 18, "radius": 17.32}, None,
     "strips along a cube's twelve edges"),
    ("Soccer ball", "polyhedron", {"solid": "soccer ball", "mode": "edges", "per_edge": 5, "radius": 12.0}, None,
     "the edges of a truncated icosahedron"),
    ("Helix column", "helix", {"n": 120, "radius": 4.0, "height": 60.0}, None, "2 m of strip wound round a tube"),
    ("Spiral disc", "spiral", {"n": 200, "gap": 1.5, "inner": 1.0}, [90.0, 0.0, 0.0], "a strip laid in a flat spiral, standing"),
)


def part(i):
    label, kind, params, rot, _ = OBJECTS[i]
    q = shapes.new_part(kind, **params)
    q["name"] = label.lower()
    if rot is not None:
        q["rot"] = list(rot)
    return q


def fill(app, P):
    """The start, into the list's place: the objects, and the other ways in."""
    from native import chrome, shape_gallery, shape_ui, typeface
    typeface.label(dpg.add_text("START WITH AN OBJECT", parent=P, color=chrome.ACCENT))
    per_row = 6
    size = px(58)
    for r in range(0, len(OBJECTS), per_row):
        with dpg.group(horizontal=True, parent=P):
            for i in range(r, min(len(OBJECTS), r + per_row)):
                label, kind, params, rot, what = OBJECTS[i]
                with dpg.group():
                    dpg.add_image_button(_texture(i), width=size, height=size, frame_padding=1, user_data=i,
                                         tag=f"start_obj_{i}", callback=lambda s, a, u: choose(app, u))
                    chrome.tip(f"{label}: {what} - its sizes asked next")
                    typeface.small(dpg.add_text(label, wrap=size + px(4), color=chrome.TEXT))
    with dpg.group(horizontal=True, parent=P):
        dpg.add_text("or", color=chrome.DIM)
        dpg.add_button(label="Draw a run", small=True, callback=lambda: shape_ui._shape_run().toggle(app))
        dpg.add_button(label="Import a model or a layout...", small=True, callback=lambda: shape_ui._import(app, False))
        dpg.add_button(label="Any part...", small=True, callback=lambda: shape_gallery.show(app))
        chrome.tip("the gallery of every kind of part")


def choose(app, i):
    """An object picked: the gallery on its kind, its sizes filled in."""
    from native import shape_gallery
    shape_gallery.show(app, OBJECTS[i][1], preset=part(i))


def _texture(i):
    tag = f"start_tex_{i}"
    if dpg.does_item_exist(tag):
        return tag
    from native import render, chrome
    from native.textures import registry
    import numpy as np
    q = part(i)
    pos, _, _ = shapes.resolve([q])
    n = max(1, len(pos))
    t = np.linspace(0.35, 1.0, n)[:, None]
    acc = np.asarray(chrome.ACCENT[:3], np.float32)
    rgb = np.clip(acc * t + (255 - acc) * 0.25 * t, 0, 255).astype(np.uint8)
    size = px(58)
    img = render.render_points(pos, rgb, size, -0.6, 0.55, 4.2, led=0.3, bg=tuple(chrome.PANEL[:3]))
    dpg.add_static_texture(size, size, render.texture_rgba(img), tag=tag, parent=registry())
    return tag
