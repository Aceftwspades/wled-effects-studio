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


def test_fit_words_cuts_at_a_word():
    assert F.fit_words("the Speed slider, 0..1", 40) == "the Speed slider, 0..1"
    assert F.fit_words("the Speed slider, 0..1", 20) == "the Speed slider..."       # not "the Speed slider, 0."
    assert F.fit_words("scale 6, 1 octave", 12) == "scale 6..."
    assert len(F.fit_words("a" * 50, 10)) == 10 and F.fit_words("a" * 50, 10).endswith("...")   # one long word: cut, marked
    assert F.fit_words("abc", 2) == "ab"
    for n in range(4, 40):
        assert len(F.fit_words("the microphone's volume, bands, beat", n)) <= n


def test_pins_and_settings_go_by_names_people_use():
    """C9: a pin or a setting shows in words - no underscores, no bare
    codes (in_lo is "in low", Smoothstep's e0 "edge 0", a Steps s3
    "step 3") - and no node shows two of its inputs and settings, or two
    of its outputs, by the same name."""
    lib = library()
    assert F.label("Remap", "in_lo") == "in low" and F.label("Remap", "out_hi") == "out high"
    assert F.label("Smoothstep", "e0") == "edge 0" and F.label("Steps", "s3") == "step 3"
    assert F.label("Colour pick", "c5") == "colour 5" and F.label("Noise", "scale") == "scale"
    bad = []
    for t, d in lib.items():
        for group in (d.get("inputs", []) + d.get("params", []), d.get("outputs", [])):
            shown = [F.label(t, p["name"]) for p in group]
            bad += [f"{t}: {s!r} twice" for s in set(shown) if shown.count(s) > 1]
            bad += [f"{t}: {s!r} has an underscore" for s in shown if "_" in s]
    assert not bad, bad


def test_fit_width_cuts_at_a_word_by_the_drawn_width():
    """A stand-in's line in the interface's face: fitted by the width the
    words are drawn, so narrow letters fit more of them than wide ones."""
    even = lambda t: len(t) * 7.0
    assert F.fit_width("the Speed slider, 0..1", 140, even) == F.fit_words("the Speed slider, 0..1", 20)
    assert F.fit_width("abc", 1000, even) == "abc"
    narrow = lambda t: sum(3.0 if ch in "il.,' " else 9.0 for ch in t)
    fits_i = F.fit_width("iiii iiii iiii iiii iiii", 60, narrow)
    fits_m = F.fit_width("MMMM MMMM MMMM MMMM MMMM", 60, narrow)
    assert len(fits_i) > len(fits_m) and narrow(fits_i) <= 60 and narrow(fits_m) <= 60
    for w in range(10, 300, 7):
        assert even(F.fit_width("the microphone's volume, bands, beat", w, even)) <= max(w, 7)


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
    for name in list(F.PATTERNS) + ["Noise"]:
        n, d = node(name)
        a = F.pattern(n, d, {"x", "y", "pos", "z"}, (48, 24))
        assert a is not None and a.shape == (24, 48) and float(a.max()) > float(a.min()), name   # a patch, with something in it
    n, d = node("Noise")
    a, b = F.pattern(n, d, set(), (48, 24), live={"z": 0.0}), F.pattern(n, d, set(), (48, 24), live={"z": 0.25})
    assert float(abs(a - b).mean()) > 0.02                                       # it scrolls with z
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


def test_nodes_spend_their_rows_on_the_work():
    """C12: a control node's label and default are the properties' - none
    of its rows - and its line says them; a range's two settings take one
    row, two again when one end is a pin; the transfer curve carries its own
    numbers only where the node's fields do not show the range."""
    from native import graph as G
    n, d = node("Speed", params={"label": "Rise", "default": 128})
    assert F.param_rows(n, d) == 0 and F.is_meta("Speed", "label") and F.is_meta("Check 2", "default")
    assert not F.is_meta("Remap", "in_lo") and not F.is_meta("Colour 1", "label")
    assert F.summary(n, d) == "“Rise”, 128 at the start"
    assert F.summary(*node("Custom 3")) == "the Custom 3 slider, 16 at the start"
    assert F.summary(*node("Check 1", params={"default": True})) == "the Check 1 box, on at the start"
    n, d = node("Remap")
    assert F.param_rows(n, d) == 2 and F.range_on_node(n, d)
    assert [w for _, _, w in F.pairs("Remap")] == ["in", "out"]
    n["expose"] = ["out_hi"]                                   # out high a pin: out low a row of its own
    assert F.param_rows(n, G.exposed_def(d, n)) == 2 and not F.range_on_node(n, G.exposed_def(d, n))
    assert F.param_rows(*node("Smoothstep")) == 1 and F.param_rows(*node("Loudest bin")) == 1
    assert F.range_on_node(*node("Clamp")) and not F.range_on_node(*node("Sine"))
    n, d = node("Remap")
    n["collapsed"] = True
    assert F.param_rows(n, d) == 0
    # every pair is two settings of the node, of one kind, the first before the second
    for t, prs in F.PAIRS.items():
        names = [p["name"] for p in LIB[t]["params"]]
        for a, b, words in prs:
            assert a in names and b in names and names.index(a) < names.index(b) and words, (t, a, b)
            ta, tb = (next(p["type"] for p in LIB[t]["params"] if p["name"] == k) for k in (a, b))
            assert ta == tb and ta in ("int", "float"), (t, a, ta, tb)


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
