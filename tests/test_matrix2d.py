"""A device's 2-D setup read as the studio's matrix (native/matrix2d.py):
WLED's walk (WS2812FX::setUpMatrix) against the matrix geometry's own
wiring for one panel, every start corner, rows or columns, serpentine or
not; several panels with their offsets; the gaps file; a /json/cfg's
matrix block; the geometry that comes of it.
Run with  python tests/test_matrix2d.py  (or pytest)."""
import itertools
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from native import matrix2d as m2
from native.geometry import Geometry


def _panel(w, h, x=0, y=0, b=False, r=False, v=False, s=False):
    return {"w": w, "h": h, "x": x, "y": y, "b": b, "r": r, "v": v, "s": s}


def test_one_panel_is_the_matrix_s_own_wiring():
    for (w, h), (b, r, v, s) in itertools.product(((5, 3), (4, 4), (2, 7)), itertools.product((False, True), repeat=4)):
        W, H, table = m2.layout([_panel(w, h, b=b, r=r, v=v, s=s)])
        assert (W, H) == (w, h) and sorted(table) == list(range(w * h))
        phys = Geometry._matrix_order(w, h, {"serpentine": s, "vertical": v, "start_right": r, "start_bottom": b})
        assert all(phys[table[i]] == i for i in range(w * h)), (w, h, b, r, v, s)


def test_panels_side_by_side_and_stacked():
    # two 4 x 2 panels, the second to the right of the first
    W, H, t = m2.layout([_panel(4, 2), _panel(4, 2, x=4)])
    assert (W, H) == (8, 2)
    assert t[:8] == [0, 1, 2, 3, 8, 9, 10, 11] and t[8:] == [4, 5, 6, 7, 12, 13, 14, 15]
    # two 2 x 2 panels, one under the other, the second serpentine from the bottom right
    W, H, t = m2.layout([_panel(2, 2), _panel(2, 2, y=2, b=True, r=True, s=True)])
    assert (W, H) == (2, 4) and t[:4] == [0, 1, 2, 3]
    assert t[6:8] == [5, 4] and t[4:6] == [6, 7]          # its first row walked from the right, the next back
    # a hole where no panel is: -1
    W, H, t = m2.layout([_panel(2, 2), _panel(2, 2, x=3)])
    assert (W, H) == (5, 2) and t[2] == -1 and t[7] == -1 and sorted(v for v in t if v >= 0) == list(range(8))


def test_the_gaps_file():
    # 3 x 2: the second pixel missing (-1, not counted), the fifth unused (0, counted, not shown)
    gaps = [1, -1, 1, 1, 0, 1]
    W, H, t = m2.layout([_panel(3, 2)], gaps)
    assert t == [0, -1, 1, 2, -1, 4]
    # a gaps file shorter than the matrix is left out, as WLED does
    assert m2.layout([_panel(3, 2)], [1, -1])[2] == list(range(6))


def test_a_cfg_and_the_geometry_it_makes():
    cfg = {"hw": {"led": {"total": 256, "matrix": {"mpc": 1, "panels": [{"b": True, "r": False, "v": True, "s": True,
                                                                             "x": 0, "y": 0, "h": 16, "w": 16}]}}}}
    panels = m2.panels_of(cfg)
    params, words = m2.geometry_params(panels, None, "cube.local")
    assert params == {"w": 16, "h": 16, "serpentine": True, "vertical": True, "start_right": False, "start_bottom": True}
    assert "columns from the bottom left, serpentine" in words
    g = Geometry("matrix", **params)
    assert g.count == 256 and "map" not in g.params
    # several panels, or gaps: the table, as a ledmap is
    cfg["hw"]["led"]["matrix"] = {"mpc": 2, "panels": [{"w": 8, "h": 8, "x": 0, "y": 0}, {"w": 8, "h": 8, "x": 8, "y": 0, "s": True}]}
    params, words = m2.geometry_params(m2.panels_of(cfg), None, "cube.local")
    g = Geometry("matrix", **params)
    assert (g.w, g.h, g.count) == (16, 8, 128) and words.startswith("2 panels making 16 x 8")
    assert m2.panels_of({"hw": {"led": {}}}) is None and m2.panels_of({}) is None


def test_a_setup_wled_would_refuse():
    try:
        m2.layout([_panel(1, 9)])
    except ValueError as e:
        assert "will not set up" in str(e)
    else:
        raise AssertionError("a 1-wide matrix was taken")


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
