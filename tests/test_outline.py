"""Signs: SVG drawings read (svg_import.py), LEDs laid along strokes and
lettering traced from a font (outline.py), and the "text" and "outline"
parts. Run with  python tests/test_outline.py  (or pytest).
"""
import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from native import svg_import, outline, shapes        # noqa: E402
from native.geometry import Geometry                  # noqa: E402

SVG = '<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" {size}>{body}</svg>'


def _strokes(body, size='width="100mm" height="100mm" viewBox="0 0 100 100"'):
    return svg_import.parse(SVG.format(size=size, body=body))


def test_shapes_and_lengths():
    s, _ = _strokes('<circle cx="50" cy="50" r="10"/>')
    assert len(s) == 1 and s[0].closed and abs(s[0].length() - 2 * math.pi * 10) < 0.2
    s, _ = _strokes('<rect x="10" y="10" width="30" height="20"/>')
    assert abs(s[0].length() - 100.0) < 1e-6
    s, _ = _strokes('<rect width="40" height="20" rx="5"/>')
    assert abs(s[0].length() - (2 * (30 + 10) + 2 * math.pi * 5)) < 0.2
    s, _ = _strokes('<ellipse cx="0" cy="0" rx="20" ry="10"/><line x1="0" y1="0" x2="3" y2="4"/>'
                    '<polygon points="0,0 10,0 10,10"/><polyline points="0 0 0 10 10 10"/>')
    assert [x.closed for x in s] == [True, False, True, False]
    assert abs(s[1].length() - 5.0) < 1e-9 and abs(s[2].length() - (20 + math.sqrt(200))) < 1e-9


def test_path_grammar():
    s, _ = _strokes('<path d="M10-5L.5.5 20 20"/>')                              # packed numbers, implicit lineto
    assert s[0].points.tolist() == [[10.0, -5.0], [0.5, 0.5], [20.0, 20.0]]
    s, _ = _strokes('<path d="M0 0a10 10 0 0110 10"/>')                           # packed arc flags
    assert abs(s[0].length() - math.pi * 5) < 0.05 and np.allclose(s[0].points[-1], [10, 10])
    s, _ = _strokes('<path d="m10 10 10 0 0 10z l 5 5"/>')                        # relative, z, then on from the start
    assert s[0].closed and s[0].points.tolist() == [[10, 10], [20, 10], [20, 20]]
    assert not s[1].closed and s[1].points.tolist() == [[10, 10], [15, 15]]
    s, _ = _strokes('<path d="M0 50 C 0 0 50 0 50 50 S 100 100 100 50"/>')        # S reflects the last control
    p = s[0].points
    assert np.allclose(p[-1], [100, 50]) and abs(p[:, 1].min() - 12.5) < 0.1 and abs(p[:, 1].max() - 87.5) < 0.1
    s, _ = _strokes('<path d="M0 0 Q 10 20 20 0 T 40 0"/>')                       # T reflects the quadratic's control
    assert np.allclose(s[0].points[-1], [40, 0]) and s[0].points[:, 1].min() < -9 and s[0].points[:, 1].max() > 9
    s, _ = _strokes('<path d="M0,0 A10,10 0 1,1 20,0"/>')                         # a half circle, large arc
    assert abs(s[0].length() - math.pi * 10) < 0.1
    s, _ = _strokes('<path d="M0,0 A1,1 0 0,1 20,0"/>')                           # radii too small: scaled up (F.6.6)
    assert abs(s[0].length() - math.pi * 10) < 0.1


def test_units_transforms_and_what_is_left_out():
    s, _ = _strokes('<line x1="0" y1="0" x2="96" y2="0"/>', size="")              # no size: CSS pixels
    assert abs(s[0].length() - 25.4) < 1e-9
    s, _ = _strokes('<line x1="0" y1="0" x2="10" y2="0"/>', size='width="1in" height="1in" viewBox="0 0 10 10"')
    assert abs(s[0].length() - 25.4) < 1e-9
    s, _ = _strokes('<line x1="0" y1="0" x2="10" y2="0"/>', size='width="20mm" height="10mm" viewBox="0 0 10 10"')
    assert abs(s[0].length() - 10.0) < 1e-9                                       # uniform: the smaller scale, centred
    s, sk = _strokes('<defs><path id="a" d="M0 0 H10"/></defs>'
                     '<g transform="translate(5,5) rotate(90)"><use xlink:href="#a"/></g>'
                     '<path d="M0 0 H50" style="display:none"/><g visibility="hidden"><circle r="3"/></g>'
                     '<text>Hi</text><image href="x.png"/>')
    assert len(s) == 1 and np.allclose(s[0].points, [[5, 5], [5, 15]], atol=1e-9)
    assert sk == {"text": 1, "image": 1}
    s, _ = _strokes('<g transform="matrix(2 0 0 2 0 0) scale(0.5) skewX(0)"><line x1="0" y1="0" x2="10" y2="0"/></g>')
    assert abs(s[0].length() - 10.0) < 1e-9
    try:
        svg_import.parse("<html/>")
        assert False, "read a non-SVG"
    except ValueError:
        pass


def test_leds_a_pitch_apart():
    # an open run: a pitch apart, the leftover split between the ends
    P = [[[0.0, 0.0], [10.5, 0.0]]]
    pos, owner = outline.leds(P, [False], 1.0)
    assert len(pos) == 11 and np.allclose(np.diff(pos[:, 0]), 1.0) and abs(pos[0, 0] - 0.25) < 1e-6
    # a closed loop: floor(length / pitch) LEDs, the gap where the strip's ends meet
    sq = [[[0.0, 0.0], [4.0, 0.0], [4.0, 4.0], [0.0, 4.0]]]
    pos, _ = outline.leds(sq, [True], 1.0)
    assert len(pos) == 16
    # a dot: one LED
    pos, _ = outline.leds([[[2.0, 3.0], [2.1, 3.0]]], [False], 1.0)
    assert len(pos) == 1 and np.allclose(pos[0], [2.05, 0, 3.0])
    assert outline.counts([[[2.0, 3.0], [2.1, 3.0]], [[0, 0], [5, 0]]], [False, False], 1.0) == (7, 1)
    # standing in the X-Z plane, y up turned to Z up
    pos, _ = outline.leds([[[0.0, 0.0], [0.0, 3.0]]], [False], 1.0)
    assert np.allclose(pos[:, 1], 0) and pos[-1, 2] > pos[0, 2]


def test_the_shortest_wiring():
    # three strokes far apart in a shuffled order: the shortest wiring leads less wire between them
    paths = [[[20.0, 0.0], [30.0, 0.0]], [[0.0, 0.0], [10.0, 0.0]], [[40.0, 0.0], [50.0, 0.0]]]
    closed = [False] * 3

    def leads(order):
        ends = []
        for k, rev, rot in order:
            P = np.asarray(paths[k])
            P = P[::-1] if rev else P
            ends.append((P[0], P[-1]))
        return sum(float(np.linalg.norm(ends[i + 1][0] - ends[i][1])) for i in range(len(ends) - 1))

    short, given = outline.wiring(paths, closed, "shortest"), outline.wiring(paths, closed, "drawing")
    assert [k for k, _, _ in short] == [1, 0, 2] and leads(short) < leads(given)
    # a closed stroke starts at its point nearest where the last one finished
    o = outline.wiring([[[0.0, 0.0], [1.0, 0.0]], [[5.0, 0.0], [5.0, 5.0], [9.0, 5.0], [9.0, 0.0]]], [False, True])
    assert o[1] == (1, False, 0)


def test_text_traced():
    font = outline.fonts().get(outline.default_font())
    if not font:                                    # a machine with no fonts (a bare CI image): nothing to trace with
        print("     (skipped: no font on this computer)")
        return
    o = outline.text_strokes("O", font, 100.0, "outline")
    assert len(o) == 2 and all(s.closed for s in o)                              # the O's outside and its hole
    c = outline.text_strokes("O", font, 100.0, "center")
    assert len(c) == 1 and c[0].closed                                            # one ring, the tube's line
    i = outline.text_strokes("i", font, 100.0, "center")
    assert len(i) == 2 and any(s.name == "dot" or s.length() < 5 for s in i)     # the stem and its dot
    H = outline.text_strokes("H", font, 100.0, "center")
    assert 3 <= len(H) <= 5                                                       # two stems and the bar (split at the joins)
    ys = np.concatenate([s.points[:, 1] for s in H])
    assert 80 <= np.ptp(ys) <= 110                                                # a capital about the height asked
    # the part: LEDs a pitch apart along the lettering, the same again from the cache
    g = Geometry("shape", parts=[shapes.new_part("text", text="IO", height=12.0)])
    assert 30 <= g.count <= 60
    g2 = Geometry("shape", parts=[shapes.new_part("text", text="IO", height=12.0)])
    assert g2.count == g.count and np.allclose(g2.pos, g.pos)
    two = Geometry("shape", parts=[shapes.new_part("text", text="I\\nI", height=12.0)])   # \n: a second line
    assert np.ptp(two.pos[:, 2]) > 12.0


def test_an_svg_as_a_part():
    paths, closed = outline.fit(_strokes('<circle cx="50" cy="50" r="40"/><line x1="0" y1="50" x2="100" y2="50"/>')[0],
                                unit_mm=10.0)
    allp = np.concatenate([np.asarray(p) for p in paths])
    assert abs(np.ptp(allp[:, 0]) - 10.0) < 1e-6 and abs(allp[:, 0].min() + 5.0) < 1e-6     # 100 mm / 10 mm, centred
    g = Geometry("shape", parts=[shapes.new_part("outline", paths=paths, closed=closed)])
    assert g.count == int(2 * math.pi * 4) + 11                                   # the circle's 25, the line's 11
    sized, _ = outline.fit(_strokes('<line x1="0" y1="0" x2="300" y2="0"/>')[0], unit_mm=10.0, size=12.0)
    assert abs(np.ptp(np.asarray(sized[0])[:, 0]) - 12.0) < 1e-6                 # fitted to a width instead


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
