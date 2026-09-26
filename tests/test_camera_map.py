"""Mapping lights by camera (the ninth pass's S18): the plan's timing, an
LED found on a picture, and whole films - synthetic, from two and three
sides, a camera running fast, LEDs hidden from a side, one through ffmpeg
as an mp4 - mapped back to where the LEDs were.
Run with  python -m pytest tests  from studio (or the functions by hand)."""
import math
import os
import shutil
import subprocess
import sys
import tempfile

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from native import camera_map as cm


def _tree(n=60, seed=4):
    """LEDs wound up a cone, jittered: a string on a small tree."""
    rs = np.random.RandomState(seed)
    t = np.linspace(0, 1, n)
    r = 40 * (1 - t) + 4
    a = t * 2 * math.pi * 4
    P = np.stack([r * np.cos(a), r * np.sin(a), t * 120], 1)
    return P + rs.normal(0, 1.5, P.shape)


def _shape_error(A, B):
    """How far two point sets are apart once each is centred and scaled to the same size (a share of that size)."""
    A = np.asarray(A, float) - np.mean(A, 0); B = np.asarray(B, float) - np.mean(B, 0)
    A /= np.sqrt((A ** 2).sum(1).mean()); B /= np.sqrt((B ** 2).sum(1).mean())
    return float(np.sqrt(((A - B) ** 2).sum(1).mean()))


def test_the_plan():
    p = cm.Plan(10, on=0.2, off=0.05)
    assert p.at(0.5) == "all" and p.at(p.sync + 0.1) == "none"
    assert p.at(p.first + 0.1) == 0 and p.at(p.first + 0.22) == "none" and p.at(p.first + 3 * p.step + 0.05) == 3
    assert p.at(p.end + 0.1) == "all" and p.at(p.total + 0.1) == "none"
    assert all(p.at(p.lit_time(k)) == k for k in range(10))


def test_an_led_on_a_picture():
    h, w = 120, 160
    ys, xs = np.mgrid[0:h, 0:w]
    rs = np.random.RandomState(0)
    dark = 10 + rs.normal(0, 2, (h, w))
    lit = dark + 180 * np.exp(-((xs - 71.3) ** 2 + (ys - 40.6) ** 2) / (2 * 1.6 ** 2))
    u, v, c = cm.detect(lit, dark)
    assert abs(u - 71.3) < 0.35 and abs(v - 40.6) < 0.35 and c > cm.CONF
    u, v, c = cm.detect(dark + rs.normal(0, 2, (h, w)), dark)
    assert c < cm.CONF                                           # nothing lit: nothing found


def test_two_sides_map_a_tree():
    P = _tree()
    plan = cm.Plan(len(P), on=0.2, off=0.05)
    sides = []
    for ang, hide in ((0, (5, 17)), (90, (30,))):
        frames = cm.synthetic_video(P, plan, ang, fps=30.0, size=(200, 200), hide=hide, seed=ang)
        found, dark = cm.scan(frames, 30.0, plan)
        assert len(found) >= len(P) - len(hide) - 1
        sides.append((ang, found))
    pos, full = cm.combine(sides, len(P))
    assert full.sum() >= len(P) - 3
    assert _shape_error(pos, P) < 0.04, _shape_error(pos, P)
    # an LED hidden from one side still lands near where it was
    for k in (5, 17, 30):
        assert np.linalg.norm((pos[k] - pos.mean(0)) / np.ptp(pos[:, 2]) - (P[k] - P.mean(0)) / np.ptp(P[:, 2])) < 0.08


def test_three_sides_a_fast_camera_and_one_moved():
    P = _tree(48, seed=9)
    plan = cm.Plan(len(P), on=0.2, off=0.05)
    sides = []
    for ang, scale, off in ((0, None, (0, 0)), (90, None, (12, -8)), (180, 1.1 * 0.8 * 200 / np.ptp(P[:, 2]), (-6, 5))):
        frames = cm.synthetic_video(P, plan, ang, fps=30.0, size=(200, 200), scale=scale, offset=off, seed=ang + 1)
        found, _ = cm.scan(frames, 30.6, plan)                  # the camera's clock 2% off: the flashes put it right
        sides.append((ang, found))
    pos, full = cm.combine(sides, len(P))
    assert full.all() and _shape_error(pos, P) < 0.04, _shape_error(pos, P)


def test_one_side_is_flat():
    P = _tree(40, seed=3)
    P[:, 1] = 0.0                                                # a flat string: lights round a window
    plan = cm.Plan(len(P), on=0.2, off=0.05)
    frames = cm.synthetic_video(P, plan, 0, fps=30.0, size=(200, 200), hide=(7,), seed=1)
    found, _ = cm.scan(frames, 30.0, plan)
    pos, full = cm.combine([(0, found)], len(P))
    assert not full[7] and full.sum() == len(P) - 1
    assert np.allclose(pos[:, 1], 0.0) and _shape_error(pos, P) < 0.04, _shape_error(pos, P)
    # turned a quarter, the same side lies across the other axis
    pos, _ = cm.combine([(90, found)], len(P))
    assert np.allclose(pos[:, 0], 0.0, atol=1e-9)


def test_a_webcam_at_uneven_times():
    P = _tree(30, seed=5)
    plan = cm.Plan(len(P), on=0.25, off=0.05)
    film = cm.synthetic_video(P, plan, 0, fps=120.0, size=(160, 160), seed=2)   # a fine clock to take pictures from
    rs = np.random.RandomState(1)
    t, stamps, frames = 0.0, [], []
    while t < plan.total:
        frames.append(film[int(t * 120.0)]); stamps.append(100.0 + t)
        t += rs.uniform(1 / 40.0, 1 / 20.0)                     # a webcam: 20 to 40 pictures a second, never even
    even, fps = cm.resample(frames, stamps, 30.0)
    assert abs(len(even) - (stamps[-1] - stamps[0]) * 30.0) <= 1
    found, _ = cm.scan(even, fps, plan)
    assert len(found) >= len(P) - 1, len(found)


def test_a_part_the_height_asked():
    P = _tree(30)
    seen = np.ones(len(P), bool); seen[[4, 11]] = False
    q = cm.to_part(P, seen, height=60.0)
    pts = np.asarray(q["params"]["points"])
    assert q["kind"] == "points" and len(pts) == 30 and abs(np.ptp(pts[:, 2]) - 60.0) < 1e-3 and abs(pts[:, 2].min()) < 1e-6
    assert q["guessed"] == [4, 11]


def test_a_film_through_ffmpeg():
    ff = shutil.which("ffmpeg")
    if not ff:
        print("  (no ffmpeg: the film round trip is not tried)")
        return
    P = _tree(36, seed=2)
    plan = cm.Plan(len(P), on=0.2, off=0.05)
    d = tempfile.mkdtemp()
    sides = []
    for ang in (0, 90):
        frames = cm.synthetic_video(P, plan, ang, fps=30.0, size=(180, 240), seed=ang + 5)
        path = os.path.join(d, f"side{ang}.mp4")
        h, w = frames[0].shape
        p = subprocess.Popen([ff, "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "gray", "-s", f"{w}x{h}", "-r", "30", "-i", "-",
                              "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18", path], stdin=subprocess.PIPE)
        for f in frames:
            p.stdin.write(f.tobytes())
        p.stdin.close(); p.wait()
        keep, fps, times = cm.read_video(path, plan, across=240)
        found, _ = cm.scan(keep, fps, plan, times=times)
        assert len(found) >= len(P) - 2, len(found)
        sides.append((ang, found))
    pos, full = cm.combine(sides, len(P))
    assert _shape_error(pos, P) < 0.05, _shape_error(pos, P)


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
