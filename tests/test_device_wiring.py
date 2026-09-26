"""A device's wiring over the studio's geometry (native/device_wiring.py):
the table WLED uses (ledmap first, else the 2-D setup, else a strip); a
cube's face order, turns and switches found back from any table the cube's
settings can make, and the device's own map kept when they cannot; the
other kinds; the order a stream must be in; and the stream's bytes in it.
Run with  python tests/test_device_wiring.py  (or pytest)."""
import itertools
import os
import random
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from native import device_wiring as dw, live_out
from native.geometry import Geometry


def _cube(B, six, faces, rots, serp, vert, right, bottom):
    return Geometry("cube", B=B, six=six, faces=",".join(faces), rots=",".join(str(r) for r in rots),
                    serpentine=serp, vertical=vert, start_right=right, start_bottom=bottom)


def test_a_cube_s_wiring_found_back_from_its_map():
    rs = random.Random(7)
    cases = [(4, six, flags) for six in (False, True) for flags in itertools.product((False, True), repeat=4)]
    for B, six, (serp, vert, right, bottom) in cases:
        have = list("NWTESB" if six else "NWTES")
        faces = have[:]; rs.shuffle(faces)
        rots = [rs.randrange(4) for _ in faces]
        g = _cube(B, six, faces, rots, serp, vert, right, bottom)
        tab = g.ledmap()["map"]
        p = dw.cube_params(tab, B)
        assert p is not None, (six, faces, rots, serp, vert, right, bottom)
        assert Geometry("cube", **p).ledmap()["map"] == tab            # the same wiring (settings may say it another way)
        assert p["six"] == six and p["B"] == B
    # a 16 x 16 cube too
    g = _cube(16, False, list("TNESW"), [1, 0, 3, 2, 0], True, False, True, False)
    assert Geometry("cube", **dw.cube_params(g.ledmap()["map"], 16)).ledmap()["map"] == g.ledmap()["map"]


def test_a_cube_wired_its_own_way_keeps_the_device_map():
    g = _cube(4, False, list("NWTES"), [0] * 5, True, False, False, False)
    tab = list(g.ledmap()["map"])
    # two LEDs of one face swapped: no setting of the cube's makes that
    a, b = [i for i, v in enumerate(tab) if v in (3, 5)]
    tab[a], tab[b] = tab[b], tab[a]
    assert dw.cube_params(tab, 4) is None
    geom, words = dw.apply(Geometry("cube", B=4), {"ledmap": {"map": tab, "width": 12, "height": 12}, "total": 80})
    assert "map" in geom.params and "own map" in words
    assert geom.ledmap()["map"] == tab and geom.count == 80
    # the device's face size, taken
    geom, words = dw.apply(Geometry("cube", B=8), {"ledmap": {"map": g.ledmap()["map"], "width": 12, "height": 12}, "total": 80})
    assert geom.params["B"] == 4 and "faces 4 x 4" in words and "map" not in geom.params


def test_the_table_the_device_uses():
    lm = {"map": [2, 1, 0, -1], "width": 2, "height": 2}
    panels = [{"w": 2, "h": 2, "x": 0, "y": 0, "b": False, "r": False, "v": False, "s": False}]
    assert dw.table({"ledmap": lm, "panels": panels}) == (2, 2, [2, 1, 0, -1], "its ledmap")          # the ledmap wins
    assert dw.table({"ledmap": {"map": [3, 2, 1, 0]}, "panels": panels})[:2] == (2, 2)                 # its size from the 2-D setup
    assert dw.table({"ledmap": None, "panels": panels, "gaps": None}) == (2, 2, [0, 1, 2, 3], "its 2-D setup")
    assert dw.table({"ledmap": None, "panels": None, "total": 5}) == (5, 1, [0, 1, 2, 3, 4], "its LEDs in order")


def test_the_other_kinds():
    info = {"ledmap": {"map": [4, 3, 2, 1, 0]}, "panels": None, "total": 5}
    g, _ = dw.apply(Geometry("strip", n=60), info)
    assert (g.kind, g.count) == ("strip", 5) and g.ledmap()["map"] == [4, 3, 2, 1, 0]
    g, _ = dw.apply(Geometry("strip", n=60), {"ledmap": None, "panels": None, "total": 30})
    assert g.count == 30 and "map" not in g.params
    cyl = Geometry("cylinder", w=4, h=2)
    tab = [7, 6, 5, 4, 0, 1, 2, 3]
    g, _ = dw.apply(cyl, {"ledmap": {"map": tab, "width": 4, "height": 2}, "panels": None, "total": 8})
    assert g.kind == "cylinder" and g.ledmap()["map"] == tab
    for geom, info in ((Geometry("cylinder", w=8, h=2), {"ledmap": {"map": tab, "width": 4, "height": 2}}),
                       (Geometry("shape", parts=[]), {"ledmap": None, "panels": None, "total": 8}),
                       (Geometry("strip", n=8), {"ledmap": {"map": tab, "width": 4, "height": 2}})):
        try:
            dw.apply(geom, info)
        except ValueError:
            pass
        else:
            raise AssertionError(f"{geom.kind} took a layout it cannot hold")


def test_the_order_a_stream_is_in():
    assert dw.stream_order(None) == "logical"                          # WLED's default until the device says
    assert dw.stream_order({"rlm": True}) == "logical"
    assert dw.stream_order({"rlm": False, "mso": False}) == "wiring"
    assert dw.stream_order({"rlm": False, "mso": True}) == "logical"   # the main segment's own pixels


def test_the_stream_s_bytes():
    g = _cube(4, False, list("NWTES"), [1, 0, 2, 0, 3], True, True, False, True)
    n = g.w * g.h
    rgb = np.zeros((g.h, g.w, 3), np.uint8)
    rgb.reshape(-1, 3)[:, 0] = np.arange(n) % 256                     # each logical pixel's index in its red
    rgb.reshape(-1, 3)[:, 1] = np.arange(n) // 256
    logical = live_out.stream_bytes(rgb, g, "logical")
    assert len(logical) == n * 3                                       # the whole net, as the effect draws it
    wiring = np.frombuffer(live_out.stream_bytes(rgb, g, "wiring"), np.uint8).reshape(-1, 3)
    m = g.ledmap()["map"]
    for L in range(n):                                                 # LED m[L] carries logical pixel L
        if m[L] >= 0:
            assert int(wiring[m[L], 0]) + 256 * int(wiring[m[L], 1]) == L


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
