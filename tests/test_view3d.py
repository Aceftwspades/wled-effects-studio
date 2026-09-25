"""The 3-D view for building (the ninth pass): real units, the camera's
projection (perspective and orthographic, panned), its rays, the floor
on round distances, and the colours and picking of a shape's parts.
Run with  python -m pytest tests  from studio (or the functions by hand)."""
import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from native import render, units, shapes


def test_units_show_and_convert():
    p = {"density": 60, "unit": "cm"}
    assert abs(units.mm(p) - 1000 / 60) < 1e-9
    assert units.show(3.0, p) == "5 cm"                       # three LEDs at 60 a metre
    assert units.show(60.0, p) == "1 m"                       # a metre or more from cm
    assert units.show(60.0, p, exact=True) == "100 cm"
    assert units.number(1.5, p) == "2.5"
    assert abs(units.from_unit(5.0, p) - 3.0) < 1e-9
    assert units.show(3.0, {"density": 60, "unit": "mm"}) == "50 mm"
    assert units.show(1.0, {"density": 25.4, "unit": "in"}) == "1.55 in"      # 39.37 mm
    assert units.density({}) == 60.0 and units.unit({"unit": "furlong"}) == "cm"


def test_round_steps_fall_on_ruler_divisions():
    p = {"density": 60, "unit": "cm"}
    # 0.45 of an extent of 30 LEDs (50 cm) is 22.5 cm: the nearest division is 20 cm
    assert abs(units.to_unit(units.grid(p, 30.0), p) - 20.0) < 1e-9
    on_ruler = lambda x, u: min(abs(x - s) for s in units._STEPS[u]) < 1e-9
    for ext in (1, 3, 10, 40, 200, 900):
        step = units.to_unit(units.grid(p, float(ext)), p)
        assert on_ruler(step, "cm"), step
    pin = {"density": 60, "unit": "in"}
    assert on_ruler(units.to_unit(units.grid(pin, 30.0), pin), "in")


def test_orthographic_keeps_the_look_points_size():
    """Switching projection keeps the picture's size at the point the camera circles."""
    size = 400.0
    per = render.Cam(0.3, 0.4, 3.0, size)
    ort = render.Cam(0.3, 0.4, 3.0, size, ortho=True)
    right = per.R[0]
    for c in (per, ort):
        sx, sy, ok, _ = c.screen(np.stack([np.zeros(3), right * 0.1]))
        assert ok.all()
        assert abs(sx[0] - size / 2) < 1e-6 and abs(sy[0] - size / 2) < 1e-6
    w_per = per.screen(right[None] * 0.1)[0][0] - size / 2
    w_ort = ort.screen(right[None] * 0.1)[0][0] - size / 2
    assert abs(w_per - w_ort) < 0.2
    # orthographic: the same offset, nearer or farther, lands in the same place
    fwd = -per.R[2]
    a = ort.screen((right * 0.1 + fwd * 0.8)[None])[0][0]
    b = ort.screen((right * 0.1 - fwd * 0.8)[None])[0][0]
    assert abs(a - b) < 1e-6


def test_rays_pass_through_what_they_are_cast_at():
    for ortho in (False, True):
        for look in (None, (0.2, -0.1, 0.3)):
            cam = render.Cam(-0.6, 0.75, 4.6, 500.0, look, ortho)
            P = np.array([[0.3, -0.2, 0.5], [-0.7, 0.1, -0.2]])
            sx, sy, ok, depth = cam.screen(P)
            for i in range(2):
                o, d = cam.ray(sx[i], sy[i])
                # the point is on the ray: its distance from the line is ~0
                v = P[i] - o
                assert np.linalg.norm(v - np.dot(v, d) * d) < 1e-6, (ortho, look)


def test_a_pan_moves_everything_the_same():
    cam0 = render.Cam(0.5, 0.3, 4.0, 400.0)
    shift = cam0.R[0] * 0.2
    cam1 = render.Cam(0.5, 0.3, 4.0, 400.0, look=shift)
    P = np.array([[0.0, 0.0, 0.0], [0.4, -0.3, 0.2]])
    s0, s1 = cam0.screen(P), cam1.screen(P)
    # the look point moves the view: a point at the new look point is in the middle
    c = cam1.screen(shift[None])
    assert abs(c[0][0] - 200.0) < 1e-6 and abs(c[1][0] - 200.0) < 1e-6
    assert s1[0][0] < s0[0][0]                                 # panned right, the picture goes left


def test_unproject_lands_on_the_plane_under_the_point():
    frame = (np.array([2.0, 1.0, 0.5], np.float32), 10.0)
    for ortho in (False, True):
        cam = dict(yaw=-0.6, pitch=0.75, dist=4.6, look=(0.1, 0.0, -0.1), ortho=ortho)
        p = render.unproject(210.0, 180.0, 400.0, cam["yaw"], cam["pitch"], cam["dist"], frame, 2, 0.0,
                             look=cam["look"], ortho=ortho)
        assert p is not None and abs(p[2]) < 1e-6
        sx, sy, ok = render.project(np.asarray([p], np.float32), 400.0, cam["yaw"], cam["pitch"], cam["dist"],
                                    frame=frame, look=cam["look"], ortho=ortho)
        assert ok[0] and abs(sx[0] - 210.0) < 1e-3 and abs(sy[0] - 180.0) < 1e-3


def test_floor_lines_go_through_the_origin():
    xs, ys = render.floor_lines(1.8, 0.4, (0.13, -0.27))
    assert np.min(np.abs(xs - 0.13)) < 1e-9 and np.min(np.abs(ys + 0.27)) < 1e-9
    assert np.allclose(np.diff(xs), 0.4) and xs.min() >= -1.8 - 1e-9 and xs.max() <= 1.8 + 1e-9
    assert len(render.floor_segments(0.0, step=0.28)) <= render.FLOOR_POOL


def test_the_parts_colours_are_the_previews():
    from native import shape_view, shape_preview
    for k in range(6):
        assert tuple(shape_view.part_colour(k)) == tuple(shape_preview._colour_of_part(k, 1))
    assert len({tuple(shape_view.part_colour(k)) for k in range(8)}) == 8


def test_runs_and_wiring_of_a_shape():
    from native import shape_view
    from native.geometry import Geometry
    ring = shapes.new_part("ring", n=12)
    strip = shapes.new_part("strip", n=5); strip["pos"] = [20.0, 0.0, 0.0]
    g = Geometry("shape", parts=[ring, strip])
    W, owner = shape_view.wiring(g)
    assert len(W) == 17 and shape_view.runs(owner) == {0: (0, 12), 1: (12, 17)}
    # the lead: from the ring's last LED to the strip's first, less a spacing
    assert shape_view._spacing(W, 0, 12, 12, 17) > 0.5
    parts_of = shape_view._parts_of_logical(g)
    assert parts_of.tolist() == [0] * 12 + [1] * 5


if __name__ == "__main__":
    bad = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print("ok  ", name)
            except Exception as e:
                bad += 1
                import traceback
                traceback.print_exc()
                print("FAIL", name, e)
    sys.exit(1 if bad else 0)
