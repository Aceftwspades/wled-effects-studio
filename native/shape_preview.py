"""A preview of the shape the project has: a turntable of the 3-D view,
rendered off screen by a second engine, looping in the Shape frame and
written as a GIF and a PNG into the project's export folder.

Three ways to light it:

- **effect**: the effect the sim is running, with its sliders and palette
- **parts**: each part of a shape in a colour of its own (a cube net or
  a matrix: one colour) - what the wiring is made of
- **wiring**: a chase along the wiring order with a trail - which LED
  comes after which

    frames = turntable(app, mode="effect", seconds=4, fps=15, size=320, turns=1)
    path = save(app, frames)                # export/shape_preview.gif (+ .png of the first frame)
"""
import os
import colorsys
import numpy as np

from native import render, gif, live_out


def _colour_of_part(k, n):
    r, g, b = colorsys.hsv_to_rgb((k * 0.61803) % 1.0, 0.75, 1.0)
    return np.array([r * 255, g * 255, b * 255], np.uint8)


def frame_colours(app, eng, mode, wt, dt):
    """(rows, cols, 3) for one frame in the chosen mode."""
    g = app.project.geometry
    if mode == "effect":
        eng.frame(int(dt * 1000))
        return eng.rgb()
    n = g.w * g.h
    rgb = np.zeros((n, 3), np.uint8)
    phys = np.asarray(g.phys, int)
    if mode == "parts":
        owner = getattr(g, "owner", None)
        for led, li in enumerate(phys):
            k = int(owner[led]) if (owner is not None and led < len(owner)) else 0
            rgb[li] = _colour_of_part(k, 1)
    else:
        cols = wt.frame(dt)
        k = min(len(phys), len(cols))
        rgb[phys[:k]] = np.maximum(cols[:k], 48)             # the unlit LEDs a dim grey, so the shape stays visible under the chase
    return rgb.reshape(g.h, g.w, 3)


def turntable(app, mode="effect", seconds=4.0, fps=15, size=320, turns=1.0, log=lambda m: None, eng=None, effect=None, params=None):
    """The turntable: a list of (size, size, 3) frames. `eng`, `effect`
    (an index) and `params` pick another effect on a second engine already
    made - the library's previews; without them, the sim's own."""
    from native.engine import Engine
    g = app.project.geometry
    if mode == "effect":
        try:
            if eng is None:
                eng = app.second_engine("shape")
                eng.set_geometry(g)
            if effect is None:
                eng.select(app.eng.idx, params=dict(app.eng.fx, pal=app.eng.pal))
                eng.colors(*app.seg_cols)
            else:
                eng.select(int(effect), params=params or None)
            for _ in range(10):
                eng.frame(23)                        # a moment in, so the picture is not the first frame's
        except Exception as e:
            log(f"no second engine for the preview ({e}); the parts are shown instead")
            mode = "parts"
    wt = None
    if mode == "wiring":
        owner = getattr(g, "owner", None) if g.kind == "shape" else None
        wt = live_out.WiringTest(g.count, owner)
        wt.mode = "chase"; wt.speed = max(8.0, g.count / max(1.0, seconds)); wt.trail = max(4, g.count // 40)
    n = max(2, int(seconds * fps))
    frames = []
    yaw0, pitch, dist = app.yaw, app.pitch, app.dist
    for i in range(n):
        yaw = yaw0 + turns * 2 * np.pi * i / n
        rgb = frame_colours(app, eng, mode, wt, 1.0 / fps)
        if g.kind == "cube" and not app.eng.fx.get("o3"):
            img = render.render(rgb, g.params.get("B", 16), size, yaw, pitch, dist, six=bool(g.params.get("six")))
        else:
            img = render.render_points(g.pos, rgb.reshape(-1, 3), size, yaw, pitch, dist)
        frames.append(img)
    return frames


def save(app, frames, fps=15, name="shape_preview"):
    """The frames as a GIF and the first as a PNG in the project's export folder: (gif path, png path)."""
    out = os.path.join(app.project.path, "export")
    gpath = os.path.join(out, name + ".gif")
    os.makedirs(os.path.dirname(gpath), exist_ok=True)
    gif.write(gpath, frames, fps=fps)
    ppath = os.path.join(out, name + ".png")
    try:
        from PIL import Image
        Image.fromarray(frames[0]).save(ppath)
    except Exception:
        ppath = None
    return gpath, ppath
