"""Audits: every effect in the roster run on every geometry kind without
the engine faulting; which of WLED's stock effects the sim leaves out and
why, each with a reason; and the GPU view's placement of every LED and
every cube face corner against the software renderer's projection, for
every geometry kind and several cameras. Run with
python tests/test_audit.py  (or pytest).
"""
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from native.geometry import Geometry               # noqa: E402

GEOMETRIES = [("strip", {"n": 150}), ("matrix", {"w": 32, "h": 16}), ("cube", {"B": 16}), ("cylinder", {"w": 24, "h": 10}),
              ("sphere", {"w": 24, "h": 12}), ("torus", {"w": 24, "h": 8}),
              ("xyz", {"points": [[float(i % 7), float(i // 7), float(i % 3)] for i in range(40)]})]


def test_every_effect_runs_on_every_geometry():
    """Five frames of each - a null read in an effect (three audio effects
    wrote to slots the sim did not provide) is an OSError here, a crash
    on the device's sim page."""
    from native.engine import Engine
    from native.synth import Synth
    e = Engine()
    bad, n = [], 0
    for kind, params in GEOMETRIES:
        e.set_geometry(Geometry(kind, **params))
        for i, name in enumerate(e.names):
            try:
                e.select(i)
                syn = Synth()
                for _ in range(5):
                    syn.push(e); e.frame()
                n += 1
            except OSError as ex:
                bad.append(f"{name} on {kind}: {ex}")
    print(f"  {n} effect x geometry runs")
    assert not bad, "\n".join(bad[:20])


def test_stock_skips_are_explained():
    """Every stock effect the sim leaves out is named with the reason, in
    build.py (the 2-D ones) or gen/stock1d_skip.json (the 1-D ones, from
    the compiler's own words); and the list stays short."""
    import build as B
    two_d = dict(B.STOCK_SKIP)
    p = os.path.join(ROOT, "gen", "stock1d_skip.json")
    one_d = json.load(open(p, encoding="utf-8")).get("skip", {}) if os.path.exists(p) else {}
    print(f"  2-D stock effects left out ({len(two_d)}):")
    for k, why in sorted(two_d.items()):
        print(f"    {k}: {why}")
    print(f"  1-D stock effects left out ({len(one_d)}):")
    for k, why in sorted(one_d.items()):
        print(f"    {k}: {why[:90]}")
    assert all(isinstance(v, str) and v.strip() for v in two_d.values()), "a 2-D skip without a reason"
    assert all(isinstance(v, str) and v.strip() for v in one_d.values()), "a 1-D skip without a reason"
    assert len(two_d) <= 6 and len(one_d) <= 24, "more stock effects left out than before - the extractor regressed?"


def _cameras():
    for yaw in (0.3, 1.2, 2.5, 4.0):
        for pitch in (-0.4, 0.2, 0.7):
            yield yaw, pitch, 3.2


def test_gpu_points_match_the_software_projection():
    """Every LED square the GPU path places sits where render.project puts
    the LED, for every geometry kind and camera - the two are the same
    maths, and must stay so."""
    import dearpygui.dearpygui as dpg
    from native.gpucube import PointQuads
    from native.render import project, frame_of, _camera
    dpg.create_context()
    bad = []
    try:
        with dpg.window(tag="w"):
            pass
        for kind, params in GEOMETRIES:
            g = Geometry(kind, **params)
            pos = np.asarray(g.pos, np.float32)[np.asarray(g.lit, bool)]
            pq = PointQuads("w", f"pq_{kind}", pos)
            size = 400
            pq.resize(size)
            for yaw, pitch, dist in _cameras():
                pq.camera(yaw, pitch, dist)
                sx, sy, ok = project(pos, size, yaw, pitch, dist, frame=frame_of(pos))
                # the k-th square shows the k-th farthest LED: read each square's centre and match it to its LED
                eye, R = _camera(yaw, pitch, dist)
                P = (pos - frame_of(pos)[0]) / frame_of(pos)[1]
                depth = -((P - eye) @ R.T)[:, 2]
                order = np.argsort(np.where(ok, -depth, np.inf))
                worst, checked = 0.0, 0
                for k, i in enumerate(order):
                    if not ok[i]:
                        continue
                    cfg = dpg.get_item_configuration(pq.items[k])
                    if not cfg.get("show"):
                        continue                              # off the frame: not placed
                    cx = (cfg["p1"][0] + cfg["p3"][0]) * 0.5; cy = (cfg["p1"][1] + cfg["p3"][1]) * 0.5
                    worst = max(worst, abs(cx - sx[i]), abs(cy - sy[i])); checked += 1
                if worst > 0.01:
                    bad.append(f"{kind} yaw {yaw} pitch {pitch}: a square {worst:.3f} px from its LED")
                if checked < len(pos) // 2:
                    bad.append(f"{kind} yaw {yaw} pitch {pitch}: only {checked} of {len(pos)} squares placed")
            dpg.delete_item(f"pq_{kind}")
    finally:
        dpg.destroy_context()
    assert not bad, "\n".join(bad)


def test_gpu_cube_faces_match_the_software_projection():
    """The cube's faces on the GPU: each visible face's corner cells land
    on render()'s projection of the face corners, camera after camera."""
    import dearpygui.dearpygui as dpg
    from native.gpucube import CubeQuads, FACES, N
    from native.render import _camera
    dpg.create_context()
    bad = []
    try:
        with dpg.window(tag="w"):
            pass
        with dpg.texture_registry():
            dpg.add_dynamic_texture(48, 48, [0.0] * (48 * 48 * 4), tag="tex")
        cq = CubeQuads("w", "cq", "tex")
        size = 400
        cq.resize(size)
        f = (size * 0.5) / np.tan(np.radians(38.0) * 0.5)
        for yaw, pitch, dist in _cameras():
            cq.camera(yaw, pitch, dist)
            eye, R = _camera(yaw, pitch, dist)
            for fi, fc in enumerate(FACES):
                c = fc["corners"]
                if np.dot(c.mean(axis=0), c.mean(axis=0) - eye) >= 0 or fi == 5:
                    continue                                  # culled on both sides
                cam = (c - eye) @ R.T
                scr = np.stack([size * 0.5 + f * cam[:, 0] / -cam[:, 2], size * 0.5 - f * cam[:, 1] / -cam[:, 2]], 1)
                # the software renderer's face corners, against the outer corners of the GPU's corner cells
                quads = cq.items[fi]
                first, last = dpg.get_item_configuration(quads[0]), dpg.get_item_configuration(quads[N * N - 1])
                if not first.get("show"):
                    bad.append(f"face {fi} yaw {yaw} pitch {pitch}: hidden on the GPU, drawn in software"); continue
                gpu = np.array([first["p1"], last["p3"]])          # corner 0 and corner 2, each grown 0.35 px outward
                want = np.array([scr[0], scr[2]])
                err = float(np.abs(gpu - want).max())
                if err > 0.6:
                    bad.append(f"face {fi} yaw {yaw} pitch {pitch}: corners {err:.2f} px apart")
    finally:
        dpg.destroy_context()
    assert not bad, "\n".join(bad)


if __name__ == "__main__":
    import inspect
    failed = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and inspect.isfunction(fn):
            try:
                fn(); print("ok  ", name)
            except Exception as e:
                failed += 1; print("FAIL", name, str(e)[:2000])
    sys.exit(1 if failed else 0)
