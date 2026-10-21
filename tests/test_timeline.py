"""The Sequence frame's timeline and recorder without the studio (native/sequence_ui.py): the view - zoomed
about a time, kept inside the show, fitted to a step or to all of it, the page turned as the playhead
leaves it - the WAV's columns at any zoom, and recording automation: a slider moved by hand while a step
plays is taken (one moved by playback is not), its ramp gives way to the hand, and the take becomes a
curve on the step. A stand-in app: no window.
Run with  python tests/test_timeline.py  (or pytest).
"""
import os
import sys
import time
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import dearpygui.dearpygui as dpg                              # noqa: E402
import numpy as np                                             # noqa: E402

from native import sequence, sequence_ui as S                  # noqa: E402

dpg.create_context()                                           # the frame's items are asked after: none exist


class _Eng:
    def __init__(self):
        self.fx = {k: 128 for k in sequence.RAMP_KEYS}
        self.idx, self.seg = 3, 0

    def seg_count(self):
        return 1

    def push(self):
        pass


def _app(durs=(10.0, 20.0, 30.0)):
    steps = [{"name": f"s{i}", "dur": d, "segments": [{"effect": "Rainbow", "params": {"sx": 100, "ix": 50}}]}
             for i, d in enumerate(durs)]
    return SimpleNamespace(project=SimpleNamespace(options={"sequence": {"steps": steps}}, save=lambda: None),
                           prefs={}, gp=SimpleNamespace(status=lambda *a, **k: None), eng=_Eng(), _transition=None)


def test_the_whole_show_until_zoomed():
    app = _app()
    assert S._span_now(app) == (0.0, 60.0, 60.0)
    assert S._view(app, 60.0, 600) == (0.0, 10.0)                 # 600 px for 60 s


def test_a_zoom_keeps_the_time_under_the_pointer():
    app = _app()
    S.zoom(app, 4.0, at=30.0)                                     # 15 s shown, 30 s where it was: in the middle
    t0, span, _ = S._span_now(app)
    assert abs(span - 15.0) < 1e-9 and abs(t0 - 22.5) < 1e-9
    S.zoom(app, 2.0, at=24.0)                                     # 24 s stays 1.5 s from the left edge's 22.5 / 2
    t0, span, _ = S._span_now(app)
    assert abs(span - 7.5) < 1e-9 and abs((24.0 - t0) / span - (24.0 - 22.5) / 15.0) < 1e-9


def test_the_view_stays_inside_the_show():
    app = _app()
    S.set_view(app, -5.0, 10.0)
    assert S._span_now(app)[:2] == (0.0, 10.0)
    S.set_view(app, 58.0, 10.0)
    assert S._span_now(app)[:2] == (50.0, 10.0)
    S.set_view(app, 0.0, 0.01)
    assert S._span_now(app)[1] == S.MIN_SPAN
    S.set_view(app, 3.0, 90.0)                                    # more than the show: the whole show again
    assert app._tl_view is None and S._span_now(app) == (0.0, 60.0, 60.0)
    S.zoom(app, 1 / 3)                                            # zoomed out past it: the same
    assert app._tl_view is None


def test_fitted_to_a_step_and_back():
    app = _app()
    S.fit_step(app, 1)                                            # 10..30 s, a twentieth either side
    t0, span, _ = S._span_now(app)
    assert abs(t0 - 9.0) < 1e-9 and abs(span - 22.0) < 1e-9
    S.fit_all(app)
    assert app._tl_view is None


def test_a_step_off_the_timeline_is_brought_onto_it():
    app = _app()
    S.set_view(app, 0.0, 5.0)
    S._into_view(app, 2)                                          # 30..60 s: its start a tenth in
    t0, span, _ = S._span_now(app)
    assert abs(t0 - (30.0 - 0.5)) < 1e-9 and span == 5.0
    S._into_view(app, 2)                                          # already on it: left alone
    assert abs(S._span_now(app)[0] - 29.5) < 1e-9


def test_the_page_turns_with_the_playhead():
    app = _app()
    S.set_view(app, 0.0, 10.0)
    now = time.perf_counter()
    app._seq_play = {"i": 1, "next": now + 15.0, "paused": None}  # 15 s into the show
    S._follow_head(app)
    t0, span, _ = S._span_now(app)
    assert t0 <= 15.0 <= t0 + span and abs(t0 - (15.0 - 0.2)) < 0.05
    app.prefs["seq_follow"] = False
    app._seq_play["next"] = now + 1.0                               # 29 s: off the page, but follow is off
    S._follow_head(app)
    assert abs(S._span_now(app)[0] - t0) < 1e-9


def test_the_wave_s_columns():
    # a file of 100 s, quiet for its first half, loud for its second
    a = np.concatenate([np.full(1000, 0.1), np.full(1000, 1.0)])
    cs = np.concatenate([[0.0], np.cumsum(a)])
    xs, amp = S.wave_columns(cs, 100.0, 0.0, 10.0, 1000, 100.0)   # 10 px a second, every 2 px
    assert len(xs) == 500 and abs(amp[10] - 0.1) < 1e-9 and abs(amp[400] - 1.0) < 1e-9
    xs, amp = S.wave_columns(cs, 100.0, 0.0, 1.0, 100, 100.0, every=50)   # 50 s a column: the means
    assert np.allclose(amp, [0.1, 1.0])
    xs, amp = S.wave_columns(cs, 100.0, 40.0, 10.0, 1000, 60.0)   # from 40 s, as far as the show's 60
    assert xs[-1] <= 200 and abs(amp[0] - 0.1) < 1e-9 and abs(amp[-1] - 1.0) < 1e-9


def test_a_slider_moved_by_hand_is_recorded_and_playback_is_not():
    app = _app()
    st = S._steps(app)["steps"][0]
    st["ramps"] = {"ix": {"end": 250, "shape": "linear"}}          # playback moves Intensity
    S._REC.armed, S._REC.takes, S._REC.held, S._REC.steps, S._REC.applied = True, {}, {}, {}, None
    try:
        for f in range(1, 41):
            t = f / 40.0
            if 10 <= f <= 20:
                app.eng.fx["sx"] = 100 + 10 * (f - 10)            # the hand: Speed 100 -> 200 over a quarter of it
            S._rec_poll(app, 0, t)
            S._apply_ramps(app, 0, t)
            S._REC.applied = (0, app.eng.idx, app.eng.seg, dict(app.eng.fx))
            if f == 15:
                assert "sx" in S._REC.held and "ix" not in S._REC.held
        keys = {k for (_, k) in S._REC.takes}
        assert keys == {"sx"}, keys                                 # Intensity moved, but by its ramp
        take = S._REC.takes[(id(st), "sx")]
        assert take[0][0] == 0.25 and take[0][1] == 100            # from the first move
        S._rec_flush(app)
        assert st["ramps"]["sx"]["shape"] == "curve" and st["segments"][0]["params"]["sx"] == 100
        assert abs(sequence.ramp_value(st, "sx", 0.5) - 200) <= 2  # held at 200 to the end of the take
        assert sequence.ramp_value(st, "sx", 0.1) == 100            # before it, the step's own value
        assert st["ramps"]["ix"] == {"end": 250, "shape": "linear"}  # the ramp it did not touch, as it was
    finally:
        S._REC.armed, S._REC.takes, S._REC.held, S._REC.steps, S._REC.applied = False, {}, {}, {}, None


def test_a_ramp_gives_way_to_the_hand():
    app = _app()
    st = S._steps(app)["steps"][0]
    st["ramps"] = {"sx": {"end": 250, "shape": "linear"}}
    S._REC.held = {"sx": time.perf_counter()}                       # the hand has Speed
    try:
        app.eng.fx["sx"] = 30
        S._apply_ramps(app, 0, 0.5)
        assert app.eng.fx["sx"] == 30                               # left where the hand put it
        S._REC.held = {}
        S._apply_ramps(app, 0, 0.5)
        assert app.eng.fx["sx"] == sequence.ramp_value(st, "sx", 0.5)   # let go: the ramp's again
    finally:
        S._REC.held = {}


def test_a_change_of_effect_is_not_a_hand():
    app = _app()
    S._REC.armed, S._REC.takes, S._REC.held, S._REC.steps = True, {}, {}, {}
    try:
        S._REC.applied = (0, app.eng.idx, 0, dict(app.eng.fx))
        app.eng.idx = 7                                             # another effect: its sliders all new
        app.eng.fx = {k: 10 for k in sequence.RAMP_KEYS}
        S._rec_poll(app, 0, 0.5)
        assert not S._REC.held and not S._REC.takes
    finally:
        S._REC.armed, S._REC.takes, S._REC.held, S._REC.steps, S._REC.applied = False, {}, {}, {}, None


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
