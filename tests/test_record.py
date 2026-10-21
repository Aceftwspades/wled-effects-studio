"""Automation recorded while the show plays (native/sequence.py record_into,
thin): a take becomes a curve ramp that runs as recorded over the stretch it
was moved and as the step had it elsewhere, simplified to a curve's points
by keeping the ones that matter. Run with  python tests/test_record.py  (or pytest).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from native import sequence                                  # noqa: E402


def _step(sx=100, ramps=None):
    return {"dur": 8.0, "segments": [{"effect": "Rainbow", "params": {"sx": sx, "ix": 128}}], "ramps": ramps or {}}


def _curve(st, key, start, pts):
    st["segments"][0]["params"][key] = start
    st["ramps"][key] = {"shape": "curve", "points": pts}
    return st


def test_thin_keeps_the_ends_and_the_corners():
    pts = [(i / 20, 0.0) for i in range(11)] + [(0.5 + i / 20, 200.0) for i in range(1, 11)]
    kept = sequence.thin(pts, 4)
    assert kept[0] == pts[0] and kept[-1] == pts[-1] and len(kept) <= 4
    assert any(v == 0.0 and t == 0.5 for t, v in kept) and any(v == 200.0 and abs(t - 0.55) < 1e-9 for t, v in kept)
    straight = [(i / 10, i * 10.0) for i in range(11)]
    assert sequence.thin(straight, 8) == [straight[0], straight[-1]]          # a straight line needs no more


def test_a_take_in_the_middle_leaves_the_rest_as_it_was():
    st = _step(100)                                                     # no ramp: 100 all through
    take = [(0.4 + k * 0.01, 100 + k * 5) for k in range(21)]           # 0.4 .. 0.6, rising to 200
    start, pts = sequence.record_into(st, "sx", take)
    assert start == 100 and len(pts) <= sequence.CURVE_MAX
    _curve(st, "sx", start, pts)
    for t, want in ((0.1, 100), (0.38, 100), (0.5, 150), (0.6, 200), (0.9, 100)):
        got = sequence.ramp_value(st, "sx", t)
        assert abs(got - want) <= 6, (t, got, want)


def test_a_take_from_the_start_sets_the_step_s_own_value():
    st = _step(100)
    start, pts = sequence.record_into(st, "sx", [(0.0, 30), (0.2, 30), (0.3, 90)])
    assert start == 30
    _curve(st, "sx", start, pts)
    assert sequence.ramp_value(st, "sx", 0.25) in range(55, 66) and sequence.ramp_value(st, "sx", 0.8) == 100


def test_a_take_over_an_existing_ramp_keeps_the_ramp_outside_it():
    st = _step(0, {"sx": {"end": 255, "shape": "linear"}})            # 0 -> 255 over the step
    start, pts = sequence.record_into(st, "sx", [(0.7, 20), (0.75, 20), (0.8, 20)])
    _curve(st, "sx", start, pts)
    assert abs(sequence.ramp_value(st, "sx", 0.3) - 76) <= 4                # the ramp, before the take
    assert sequence.ramp_value(st, "sx", 0.75) == 20                         # the take
    assert abs(sequence.ramp_value(st, "sx", 0.95) - 242) <= 6               # the ramp again after it


def test_a_long_wobbly_take_fits_a_curve():
    import math
    st = _step(128)
    take = [(k / 200, 128 + 100 * math.sin(k / 200 * 6 * math.pi)) for k in range(201)]
    start, pts = sequence.record_into(st, "sx", take)
    assert len(pts) <= sequence.CURVE_MAX and all(0 < p[0] <= 1 for p in pts)
    _curve(st, "sx", start, pts)
    # the three peaks and troughs are still there, roughly
    for t, want in ((1 / 12, 228), (3 / 12, 28), (5 / 12, 228)):
        assert abs(sequence.ramp_value(st, "sx", t) - want) <= 40, (t, sequence.ramp_value(st, "sx", t))


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
