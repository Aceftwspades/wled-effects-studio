"""Live video (native/video.py, the Video node): a frame in the engine's
video slot read back by a built Video node - the picture projection, the
cube's faces, each style - the test pattern moving without ffmpeg, a file
decoded by ffmpeg when there is one, and a device build of the node
reading black. Run with  python tests/test_video.py
"""
import os
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import numpy as np                                        # noqa: E402

from native import graph as G, video                      # noqa: E402
from native.nodedefs import library                       # noqa: E402

_ENG = {}


def _graph(title, params, extra_inputs=None):
    lib = library()
    return G.Graph({"name": title, "implicit": 1,
                    "nodes": [{"id": 1, "type": "Video", "pos": [0, 0], "params": params, "inputs": dict(extra_inputs or {})},
                              {"id": 2, "type": "Output", "pos": [0, 0], "params": {}, "inputs": {}}],
                    "links": [[1, "color", 2, "color"]]}, lib=lib)


CASES = {"Video picture": ({"projection": "picture", "style": "none"}, None),
         "Video faces": ({"projection": "faces", "style": "none"}, None),
         "Video mono": ({"projection": "picture", "style": "mono"}, None),
         "Video posterize": ({"projection": "picture", "style": "posterize"}, {"levels": 2.0}),
         "Video edges": ({"projection": "picture", "style": "edges"}, None),
         "Video pixelate": ({"projection": "picture", "style": "pixelate"}, {"blocks": 2.0})}


def _engine():
    """One side build with a Video graph per case (the app's build untouched)."""
    if "e" in _ENG:
        return _ENG["e"]
    import build as B
    from native import scratch
    from native.toolchain import build_engine
    from native.engine import Engine
    srcs = []
    for title, (params, extra) in CASES.items():
        p = scratch.path("test_" + G._ident(title) + ".cpp")
        with open(p, "w", encoding="utf-8", newline="\n") as f:
            f.write(_graph(title, params, extra).compile(title=title))
        srcs.append(p)
    rep = build_engine(B.engine_sources(srcs, log=lambda *a: None), B.include_dirs(), log=lambda *a: None, point_latest=False)
    assert rep.ok, rep.error_lines()[:5]
    _ENG["e"] = Engine(rep.library)
    return _ENG["e"]


def _run(e, title, frame, geom=None):
    from native.geometry import Geometry
    e.set_geometry(geom or Geometry("matrix", w=16, h=8))
    e.select(e.names.index(title))
    e.clear()
    e.video(frame)
    e.frame(30)
    e.frame(30)
    return e.rgb().astype(int)


def _halves():
    """A frame: red on the left half, blue on the right."""
    f = np.zeros((54, 96, 3), np.uint8)
    f[:, :48] = (255, 0, 0)
    f[:, 48:] = (0, 0, 255)
    return f


def test_the_picture_projection_reads_the_frame():
    e = _engine()
    out = _run(e, "Video picture", _halves())
    assert out[4, 1].tolist() == [255, 0, 0], out[4, 1]
    assert out[4, 14].tolist() == [0, 0, 255], out[4, 14]
    black = _run(e, "Video picture", None)
    assert black.max() == 0                                    # no frame: black


def test_faces_put_the_picture_on_every_face():
    from native.geometry import Geometry
    e = _engine()
    out = _run(e, "Video faces", _halves(), Geometry("cube", B=8))
    lit = e.lit_mask()
    reds = ((out[..., 0] > 200) & lit).sum()
    blues = ((out[..., 2] > 200) & lit).sum()
    assert reds > 0 and blues > 0 and abs(reds - blues) <= lit.sum() // 8, (reds, blues)


def test_the_styles():
    e = _engine()
    grey = np.full((54, 96, 3), 100, np.uint8)
    e.colors(0x00FF00)                                          # Colour 1: green
    mono = _run(e, "Video mono", grey)
    assert mono[4, 4, 1] > 0 and mono[4, 4, 0] == 0 and mono[4, 4, 2] == 0, mono[4, 4]
    post = _run(e, "Video posterize", grey)
    assert set(np.unique(post)) <= {0, 255}, np.unique(post)    # two levels: off or full
    edges = _run(e, "Video edges", _halves())
    assert edges[4, 1].max() < 30 and edges[4, 7:9].max() > 60    # dark on flat colour, lit where it changes
    pix = _run(e, "Video pixelate", _halves())
    assert (pix[:, :8] == pix[0, 0]).all() and (pix[:, 8:] == pix[0, 15]).all()   # two blocks across


def test_the_test_pattern_moves_without_ffmpeg():
    src = video.open_source("test")
    a, n0 = src.latest()
    time.sleep(0.2)
    b, n1 = src.latest()
    assert a.shape == (video.HEIGHT, video.WIDTH, 3) and n1 > n0 and not np.array_equal(a, b)
    src.pause(True)
    c, _ = src.latest(); time.sleep(0.1); d, _ = src.latest()
    assert np.array_equal(c, d)                                 # paused: the picture holds


def test_a_file_through_ffmpeg():
    if not shutil.which("ffmpeg"):
        print("     (no ffmpeg: the file test is left out)")
        return
    from native import scratch
    path = scratch.path("test_clip.mp4")
    subprocess.run([shutil.which("ffmpeg"), "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=160x120:rate=25:duration=2",
                    "-pix_fmt", "yuv420p", path], check=True)
    src = video.open_source("file", path=path, loop=True)
    try:
        end = time.time() + 10
        while src.latest()[1] < 3 and time.time() < end:
            time.sleep(0.05)
        frame, n = src.latest()
        assert n >= 3 and frame.shape == (video.HEIGHT, video.WIDTH, 3) and frame.max() > 100, (n, src.error)
    finally:
        src.close()


def test_a_device_build_reads_black():
    src = _graph("Video device", {"projection": "front", "style": "palette"}).compile(title="Video device")
    assert "GC_VIDEO(" in src
    from native.graph import GENERATED
    head = GENERATED.split("#else", 1)[1]
    assert "#define GC_VIDEO(u, v) (0u)" in head                # outside the sim: black, nothing to link


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
