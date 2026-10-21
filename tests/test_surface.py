"""Shapes drawn as their surface on the GPU (Geometry.surface, gpucube.SurfaceQuads) and the glow of pictures
(render._points: sprites, or a blur where that costs less). The surface passes through every LED; its patches
are placed far first and only some hundreds of them; an LED's cell keeps the point cloud's share of the spacing;
the colours sent only when they change; a picture's glow by either way near the other's.
Run with  python tests/test_surface.py  (or pytest).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import dearpygui.dearpygui as dpg                              # noqa: E402
import numpy as np                                             # noqa: E402

from native import look, render                                # noqa: E402
from native.geometry import Geometry                           # noqa: E402

dpg.create_context()
with dpg.window(tag="test_win"):
    pass
from native.gpucube import PointQuads, SurfaceQuads            # noqa: E402

KINDS = (("matrix", dict(w=12, h=7)), ("cylinder", dict(w=20, h=6)), ("sphere", dict(w=24, h=12)), ("torus", dict(w=30, h=10)))


def test_the_surface_passes_through_every_led():
    for kind, kw in KINDS:
        g = Geometry(kind, **kw)
        assert g.is_surface(), kind
        ys, xs = np.mgrid[0:g.h, 0:g.w]
        assert np.allclose(g.surface(xs.ravel(), ys.ravel()), g.pos, atol=1e-5), kind
    for kind, kw in (("strip", dict(n=30)), ("cube", dict(B=6)), ("xyz", dict(points=[[0, 0, 0], [1, 1, 1]]))):
        g = Geometry(kind, **kw)
        assert not g.is_surface() and g.surface(0.0, 0.0) is None, kind


def test_a_sphere_closes_at_its_poles_and_a_torus_round_both_ways():
    g = Geometry("sphere", w=24, h=12)
    top, bottom = g.surface(np.arange(5.0), np.full(5, -0.5)), g.surface(np.arange(5.0), np.full(5, g.h - 0.5))
    assert np.allclose(top, top[0]) and np.allclose(bottom, bottom[0])          # one point each: no hole
    t = Geometry("torus", w=30, h=10)
    assert np.allclose(t.surface(-0.5, 2.0), t.surface(t.w - 0.5, 2.0), atol=1e-6)
    assert np.allclose(t.surface(3.0, -0.5), t.surface(3.0, t.h - 0.5), atol=1e-6)


def _quads(tag, g):
    sq = SurfaceQuads("test_win", tag, g)
    sq.resize(300, 300, 300)
    return sq


def test_the_patches_are_few_and_placed_far_first():
    g = Geometry("sphere", w=64, h=32)
    sq = _quads("sq_sphere", g)
    assert sq.nu * sq.nv <= 512 < g.w * g.h
    sq.camera(0.3, 0.4, 4.6)
    shown = [q for q in sq.items if dpg.get_item_configuration(q)["show"]]
    assert 0 < len(shown) <= len(sq.items)
    # the order of drawing is far to near: each shown quad's patch (its corners' mean depth) no nearer than the next's
    from native.render import Cam
    cam = Cam(0.3, 0.4, 4.6, 300, None, False, 38.0)
    _, _, _, depth = cam.screen(sq.C.reshape(-1, 3))
    depth = depth.reshape(sq.nv + 1, sq.nu + 1)
    d = ((depth[:-1, :-1] + depth[:-1, 1:] + depth[1:, 1:] + depth[1:, :-1]) * 0.25).ravel()
    order = [sq._ranks[k] for k, q in enumerate(sq.items) if dpg.get_item_configuration(q)["show"]]
    assert np.all(np.diff(d[order]) <= 1e-6)
    sq.camera(0.3, 0.4, 4.6)                                       # the same camera: nothing placed again
    assert sq._last is not None


def test_an_led_cell_keeps_the_point_cloud_s_share():
    for K in (1, 2, 3, 4):
        sq = _quads(f"sq_cell_{K}", Geometry("matrix", w=8, h=4))
        sq.K = K
        a = sq._cell_alpha()
        assert a.shape == (K, K) and abs(a.mean() - (2 * PointQuads.LED) ** 2) < 1e-6, (K, a.mean())
        assert np.allclose(a, a[::-1, ::-1])                         # centred


def test_colours_go_up_only_when_they_change():
    g = Geometry("matrix", w=8, h=4)
    sq = _quads("sq_cols", g)
    rgb = np.full((g.w * g.h, 3), 200, np.uint8)
    sq.colours(rgb)
    was = sq._rgb_was
    sq.colours(rgb.copy())
    assert sq._rgb_was is was                                       # the same: not sent again
    rgb[3] = 0
    sq.colours(rgb)
    assert sq._rgb_was is not was
    tex = np.asarray(dpg.get_value(sq.tex)).reshape(g.h * sq.K, g.w * sq.K, 4)
    assert tex[..., 3].max() <= 1.0 and tex[..., 3].min() < 0.9      # the gaps between the LEDs clear
    rgb[:] = 0
    rgb[9] = 220                                                     # one LED lit, the board round it dark
    sq.colours(rgb, lk=look.PRESETS["cinematic"])                    # the glow's texture: the board clear
    tex = np.asarray(dpg.get_value(sq.tex)).reshape(g.h * sq.K, g.w * sq.K, 4)
    assert tex[..., 3].min() == 0.0 and tex[..., 3].max() > 0.9


def _picture(g, lk, size):
    pos = g.pos
    yy = np.arange(len(pos))
    rgb = np.stack([(np.sin(yy * 0.21) * 0.5 + 0.5) * 255, (np.sin(yy * 0.07 + 2) * 0.5 + 0.5) * 255,
                    (yy % 7 == 0) * 255], 1).astype(np.uint8)
    return render.render_points(pos, rgb, size, 0.4, 0.45, 4.6, lk=dict(lk, reflect=0))


def test_a_picture_s_glow_by_a_blur_is_near_the_sprites():
    g = Geometry("sphere", w=48, h=24)
    lk = look.PRESETS["cinematic"]
    keep = render._glow_points
    try:
        a = _picture(g, lk, 300)                                     # this one is drawn by the blur...
        render._glow_points = lambda out, sx, sy, ok, depth, half, rgb, unlit, lk_: render._sprite_points(
            out, sx, sy, ok, depth, half, rgb, unlit, lk_, None, np.argsort(-depth))
        b = _picture(g, lk, 300)                                     # ...and this by the sprites
    finally:
        render._glow_points = keep
    assert np.abs(a.astype(float) - b).mean() < 10 and abs(float(a.mean()) - float(b.mean())) < 6


def test_the_cheaper_way_is_taken():
    called = []
    keep = (render._glow_points, render._sprite_points)
    render._glow_points = lambda *a, **k: called.append("blur")
    render._sprite_points = lambda *a, **k: called.append("sprites")
    try:
        _picture(Geometry("strip", n=60), look.PRESETS["glow"], 400)          # a few small LEDs: sprites
        _picture(Geometry("sphere", w=64, h=32), look.PRESETS["glow"], 400)   # 2,048 big ones: the blur
    finally:
        render._glow_points, render._sprite_points = keep
    assert called == ["sprites", "blur"], called


if __name__ == "__main__":
    import inspect
    bad = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and inspect.isfunction(fn):
            try:
                fn(); print("ok  ", name)
            except Exception as e:
                bad += 1; print("FAIL", name, repr(e))
    sys.exit(1 if bad else 0)
