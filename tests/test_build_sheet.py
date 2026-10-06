"""The bench (build_sheet.py): the build sheet's parts, outputs, power and
checks, and the 1:1 template's size and marks. Run with
python tests/test_build_sheet.py  (or pytest).
"""
import os
import re
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from native import build_sheet, shapes, units      # noqa: E402
from native.geometry import Geometry               # noqa: E402


def _shape():
    strip = shapes.new_part("strip", n=60)
    ring = shapes.new_part("ring", n=24)
    ring["pos"] = [0.0, 0.0, 30.0]
    return Geometry("shape", parts=[strip, ring], density=60)


def test_the_sheet_says_what_to_build():
    g = _shape()
    page = build_sheet.sheet(g, {"outs": [{"name": "output 1", "pin": 16, "start": 0, "len": 84, "rev": False}]},
                             "test: build sheet", [("warn", "a long lead from strip to ring"), ("info", "84 LEDs")], "test")
    assert page.startswith("<!doctype html>") and "</html>" in page
    assert "84 LEDs in 2 part(s)" in page and "60 LEDs a metre" in page
    # the strip's 60 LEDs at 60 a metre: a metre of strip to cut; the ring's 24: 0.4 m
    assert "1.000 m" in page and "0.400 m" in page
    assert "0 - 59" in page and "60 - 83" in page                       # each part's LED numbers
    assert "GPIO 16" in page and "Feed power in at LED" in page and "AWG" in page
    assert "a long lead from strip to ring" in page and "class='warn'" in page
    assert page.count("<svg") == 1                                      # the diagram, inline: nothing to load


def test_the_template_is_at_actual_size():
    g = _shape()
    svg, view, W, H = build_sheet.template(g)
    assert view == "front"                                              # thinnest along Y: seen from the front
    mm = units.mm(g.params)
    pos, _, _ = shapes.resolve(g.params["parts"])
    width = float(np.ptp(np.asarray(pos)[:, 0])) * mm
    assert abs(W - (width + 30.0)) < 1e-6                               # the LEDs' spread and the margins, in mm
    assert re.search(r'width="[\d.]+mm" height="[\d.]+mm"', svg) and f'viewBox="0 0 {W:.3f} {H:.3f}"' in svg
    assert svg.count("<circle") == 84 and "h100" in svg and "actual size" in svg      # every LED, the 100 mm bar
    holes, _, _, _ = build_sheet.template(g, hole_mm=12.0)
    assert 'r="6.00"' in holes and "h3.6" not in holes                  # holes, not crosses
    try:
        build_sheet.template(Geometry("shape", parts=[]))
        assert False, "a template of nothing"
    except ValueError:
        pass


if __name__ == "__main__":
    import inspect
    bad = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and inspect.isfunction(fn):
            try:
                fn(); print("ok  ", name)
            except Exception as ex:
                bad += 1; print("FAIL", name, repr(ex)[:3000])
    sys.exit(1 if bad else 0)
