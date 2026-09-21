"""The face of a node without a window (native/nodeface.py): every node
summarises at its defaults in plain words, the hand-written lines read
as meant, the transfer curves and pattern thumbnails come out finite and
in range, the strips and ranges are what the nodes say.
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from native.nodedefs import library                # noqa: E402
from native import nodeface as F                    # noqa: E402

LIB = library()


def node(name, params=None, inputs=None):
    d = LIB[name]
    n = {"id": 1, "type": name, "pos": [0, 0], "params": {p["name"]: p["default"] for p in d["params"]}, "inputs": {}}
    n["params"].update(params or {}); n["inputs"].update(inputs or {})
    return n, d


def test_every_node_summarises_in_plain_words():
    bad = []
    for name in LIB:
        if name in ("Expression", "Colour expression"):
            continue                                        # their text IS the function, C and all
        n, d = node(name)
        s = F.summary(n, d, set())
        if "$" in s or re.search(r"\d f\b|\df\b", s) or "(float)" in s or "(int)" in s or "SEGMENT" in s or "gc_" in s or len(s) > 60:
            bad.append((name, s))
    assert not bad, bad


def test_hand_written_summaries():
    n, d = node("Add", inputs={"b": 0.5})
    assert F.summary(n, d, {"a"}) == "a + 0.5"
    n, d = node("Remap", params={"in_lo": 0, "in_hi": 1, "out_lo": 3, "out_hi": 5})
    assert F.summary(n, d) == "0..1 -> 3..5"
    n, d = node("Wave", params={"shape": "triangle"}, inputs={"cycles": 0.25})
    assert F.summary(n, d, {"x"}) == "triangle × 0.25 cycles"
    n, d = node("Ease", inputs={"seconds": 0.2})
    assert F.summary(n, d, {"target"}) == "-> target in 0.2 s"
    n, d = node("Steps", params={"length": 3, "s1": 1, "s2": 0, "s3": 0.5})
    assert F.summary(n, d) == "3 steps: 1 0 0.5"
    n, d = node("Math", params={"op": "sqrt"})
    assert F.summary(n, d, {"a"}) == "sqrt(a)"
    n, d = node("Math", params={"op": "multiply"}, inputs={"b": 3})
    assert F.summary(n, d, {"a"}) == "a × 3"
    n, d = node("Palette")
    assert F.summary(n, d, {"index"}, {"palette": "Fire"}) == "Fire"
    n, d = node("Send", params={"name": "beat"})
    assert F.summary(n, d) == "'beat'"
    n, d = node("Bitmap", params={"rows": "0110/1001/1001/0110/0000"})
    assert F.summary(n, d) == "4 × 5"
    n, d = node("Blackbody", inputs={"kelvin": 6500.0})
    assert F.summary(n, d) == "6500 K"
    n, d = node("Expression", params={"expr": "a * b + c"})
    assert F.summary(n, d) == "a * b + c"
    n, d = node("Multiply")
    assert F.summary(n, d, {"a", "b"}) == "a × b"                    # both wired: the names
    n, d = node("Sine")
    assert "2pi" in F.summary(n, d, {"x"})


def test_transfer_curves_are_finite_and_shaped():
    for name, (f, rng) in F.TRANSFER.items():
        if f is None:
            continue
        n, d = node(name)
        pts = F.transfer(n, d, {"x"})
        assert pts and len(pts) == 48 and all(abs(y) < 1e6 for _, y in pts), name
    n, d = node("Remap", params={"in_lo": 0, "in_hi": 1, "out_lo": 3, "out_hi": 5})
    pts = F.transfer(n, d)
    assert abs(pts[0][1] - 3.0) < 1e-9 and abs(pts[-1][1] - 5.0) < 1e-9
    n, d = node("Threshold", inputs={"at": 0.5})
    pts = F.transfer(n, d, {"x"})
    assert pts[0][1] == 0.0 and pts[-1][1] == 1.0
    n, d = node("Float curve", params={"points": [[0, 0], [0.5, 1], [1, 0]]})
    pts = F.transfer(n, d, {"x"})
    assert max(y for _, y in pts) > 0.9 and abs(pts[-1][1]) < 1e-9
    assert F.transfer(*node("Add")) is None


def test_pattern_thumbnails():
    for name in F.PATTERNS:
        n, d = node(name)
        a = F.pattern(n, d, {"x", "y", "pos"}, 16)
        assert a is not None and a.shape == (16, 16) and float(a.min()) >= 0.0 and float(a.max()) <= 1.0, name
    n, d = node("Checker", inputs={"scale": 2.0})
    a = F.pattern(n, d, set(), 8)
    assert a[0, 0] != a[0, 4] and a[0, 0] != a[4, 0] and a[0, 0] == a[4, 4]     # two squares across, a checker
    n, d = node("Stripes", inputs={"count": 2.0, "duty": 0.5})
    a = F.pattern(n, d, set(), 8)
    assert list(a[0]) == [1, 1, 0, 0, 1, 1, 0, 0]
    assert F.pattern(*node("Add")) is None


def test_strips_and_ranges():
    n, d = node("Blackbody")
    strip = F.ramp_strip(n, d, 5)
    assert len(strip) == 5 and strip[0][0] == 255 and strip[0][2] < 40 and strip[-1][2] == 255       # warm to cool
    assert abs(F.strip_marker(n, d, set()) - (3000 - 1000) / 11000) < 1e-9
    n, d = node("Colour ramp", params={"stops": [[0.0, 0, 0, 0], [1.0, 255, 255, 255]], "mode": "linear"})
    strip = F.ramp_strip(n, d, 3)
    assert strip == [(0, 0, 0), (128, 128, 128), (255, 255, 255)]
    n["params"]["mode"] = "constant"
    assert F.ramp_strip(n, d, 3)[1] == (0, 0, 0)
    n, d = node("Colour pick", params={"c1": [10, 20, 30]})
    assert F.ramp_strip(n, d)[1] == (10, 20, 30)
    n, d = node("Steps", params={"length": 4, "s1": 0, "s2": 2, "s3": 1, "s4": 0.5})
    assert F.out_range(n, d, "value") == (0.0, 2.0) and F.out_range(n, d, "step") == (0.0, 3.0)
    n, d = node("Integrate", params={"wrap": 4.0})
    assert F.out_range(n, d, "value") == (0.0, 4.0)
    n["params"]["wrap"] = 0.0
    assert F.out_range(n, d, "value") is None
    assert F.out_range(*node("Audio"), "bass") == (0.0, 1.0)
    assert F.out_range(*node("Add"), "result") is None
    assert set(F.CATEGORY_HUES) >= {d["cat"] for d in LIB.values() if d.get("cat")}


if __name__ == "__main__":
    import inspect
    bad = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and inspect.isfunction(fn):
            try:
                fn(); print("ok  ", name)
            except Exception as ex:
                bad += 1; print("FAIL", name, str(ex)[:3000])
    sys.exit(1 if bad else 0)
