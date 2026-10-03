"""The Library's ground without the window: a clean cube (Engine.clear) as
a fresh engine has it - the effect before it gone from the pixels - the
audio's major peak from the bands (the Freq effects were dark without it),
every effect of the sim sorted into its bank (graphs, usermod, stock), and
a thumbnail's frames from a clean cube hearing the synth, a flash too short
for every third frame caught. Run with  python tests/test_library.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import numpy as np                                      # noqa: E402
from native.engine import Engine                         # noqa: E402
from native.synth import Synth                           # noqa: E402
from native import library_ui                            # noqa: E402


def _run(e, name, n=3):
    e.select(e.names.index(name))
    for _ in range(n):
        e.frame(40)
    return e.rgb().astype(int)


def test_a_clean_cube_forgets_the_effect_before():
    fresh = _run(Engine(), "Sinelon")
    e = Engine()
    _run(e, "Fire 2012", 60)
    dirty = _run(e, "Sinelon")
    e = Engine()
    _run(e, "Fire 2012", 60)
    e.select(e.names.index("Sinelon")); e.clear()
    for _ in range(3):
        e.frame(40)
    clean = e.rgb().astype(int)
    lit = lambda a: int((a.max(axis=2) > 10).sum())
    assert lit(dirty) > 2 * lit(fresh), (lit(dirty), lit(fresh))          # the fire showed through
    assert lit(clean) == lit(fresh), (lit(clean), lit(fresh))
    assert e.now_ms == 120 and e.sim_ms == 120                            # the clock from 0


def test_the_major_peak_from_the_bands():
    e = Engine()
    e.fft[:] = 0
    e.fft[9] = 200
    e.audio_peak()
    e.select(e.names.index("Freqmap")); e.clear()
    for _ in range(4):
        e.fft[:] = 0; e.fft[9] = 200; e.audio_peak()
        e.frame(40)
    assert e.rgb().max() > 30                                             # lit by the peak's band
    e.fft[:] = 0
    e.audio_peak()                                                        # silence: no peak
    s = Synth()
    e2 = Engine(); e2.select(e2.names.index("Freqmatrix")); e2.clear()
    for _ in range(40):
        s.push(e2); e2.frame(40)
    assert e2.rgb().max() > 30                                            # the synth's sound has a peak now


class _GP:
    def __init__(self):
        self.dir = os.path.join(os.path.dirname(HERE), "examples", "graphs")
        from native.nodedefs import library
        self.lib = library()

    def files(self):
        return sorted(f for f in os.listdir(self.dir) if f.endswith(".json"))[:3]

    def resolve_sub(self, name):
        return None


class _Project:
    path = os.path.join(os.path.dirname(HERE), "examples")

    def effect_files(self):
        return []

    def effect_title(self, f):
        return f


class _App:
    def __init__(self):
        self.eng = Engine()
        self.gp = _GP()
        self.project = _Project()


def test_every_effect_in_its_bank():
    app = _App()
    b = library_ui.banks(app)
    assert set(b) == {"graphs", "usermod", "stock"}
    assert len(b["graphs"]) == 3 and all(fn for _, _, fn in b["graphs"])
    keys = [k for bank in b.values() for k, _, _ in bank if k]
    assert len(keys) == len(set(keys)) and set(keys) <= set(app.eng.names)
    built = sum(1 for k, _, _ in b["graphs"] if k)
    assert len(b["usermod"]) + len(b["stock"]) + built == len(app.eng.names)
    um = {n for _, n, _ in b["usermod"]}
    assert "Studio Script" in um and any(n.startswith("Ace 3-D") for n in um)
    stock = {n for _, n, _ in b["stock"]}
    assert {"Fire 2012", "Sinelon", "Rainbow"} <= stock and not any(n.startswith("Ace 3-D") for n in stock)


def test_a_thumbnail_from_a_clean_cube():
    e = Engine()
    _run(e, "Fire 2012", 60)
    s = Synth()
    frames = library_ui.clean_frames(e, e.names.index("Ace 3-D Cube Ripples"), 24, syn=s)
    assert len(frames) == 24 and frames[0].shape == e.rgb().shape
    assert max(int(f.max()) for f in frames) > 30                        # an audio effect, heard
    strobe = library_ui.clean_frames(e, e.names.index("Strobe"), 72, every=1, syn=s)
    assert max(int(f.max()) for f in strobe) > 30                         # its flashes, every frame sampled


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
