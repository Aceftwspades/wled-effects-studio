"""The show rendered to a video (native/render_video.py) and the look of its frames (look.finish): the stretch of
the show and the frames it takes; the spill round the view's square in a wide frame, faded to nothing before its
edges; the spill behind the shape - in the room only - when where the room shows is known; the studio's clock held
and stepped (native/clock.py). A stand-in app: no window.
Run with  python tests/test_render_video.py  (or pytest).
"""
import os
import sys
import time
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np                                             # noqa: E402

from native import clock, look, render_video as R              # noqa: E402


def _app(durs=(2.0, 3.0, 5.0)):
    steps = [{"name": f"s{i}", "dur": d} for i, d in enumerate(durs)]
    return SimpleNamespace(project=SimpleNamespace(options={"sequence": {"steps": steps}}, save=lambda: None), _seq_sel=1)


def test_the_stretch_and_its_frames():
    app = _app()
    o = R.options(app)
    assert o["size"] == "1920x1080" and o["fps"] == 30 and o["view"] == "cube"
    assert R.span(app) == (0.0, 10.0)
    o["length"] = "step"
    assert R.span(app) == (2.0, 5.0)                               # the selected step
    assert R.size(app) == (1920, 1080)
    o["size"] = "1080x1920"
    assert R.size(app) == (1080, 1920)


def test_the_spill_round_the_view_in_a_wide_frame():
    lk = look.PRESETS["cinematic"]
    fall = look._spill_box(lk, 1600, 600, (520, 40, 520))
    assert fall.shape == (600, 1600)
    assert fall[300, 780] > 0.5                                    # strong behind the middle of the view
    assert fall[:, 0].max() < 0.02 and fall[:, -1].max() < 0.02    # nothing at the frame's sides: no edge, no bar


def test_the_spill_goes_into_the_room_only():
    lk = dict(look.PRESETS["cinematic"], vignette=0.0, grain=0.0, bloom=0.0, filmic=0.0, exposure=1.0)
    img = np.zeros((100, 100, 3), np.uint8)
    room = np.ones((100, 100), bool)
    room[30:70, 30:70] = False                                     # the shape: dark LEDs in the middle
    light = (np.array([1.0, 0.2, 0.1], np.float32), 0.8)
    out = look.finish(img, lk, 0, light, room=room)
    assert out[50, 50].max() == 0                                  # the shape's dark LEDs stay dark
    assert out[20, 50, 0] > 20                                     # the room behind it glows
    plain = look.finish(img, lk, 0, light)                         # without knowing the room: every dark pixel
    assert plain[50, 50, 0] > 20


def test_the_clock_held_and_stepped():
    clock.release()
    a = clock.now()
    assert abs(a - time.perf_counter()) < 0.05 and not clock.held()
    clock.hold()
    try:
        t = clock.now()
        time.sleep(0.02)
        assert clock.now() == t                                    # held: the real time passing does not move it
        clock.step(1 / 30)
        assert abs(clock.now() - (t + 1 / 30)) < 1e-9
    finally:
        clock.release()
    assert not clock.held()


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
