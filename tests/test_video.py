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


def test_a_stream_address_is_a_network_one():
    for url in ("rtsp://192.168.1.20:8554/live", "http://10.0.0.2:8080/video", "srt://host:9000", "rtmp://h/app/key"):
        args = video.stream_args(url)
        assert args[-2:] == ["-i", url] and "nobuffer" in args, args
    assert "-rtsp_transport" in video.stream_args("rtsp://h/x")
    for url in ("", "clip.mp4", "file:///etc/passwd", "concat:a.mp4|b.mp4", "subfile,,start,0,end,0,,:x", "http://"):
        try:
            video.stream_args(url)
            raise AssertionError(f"{url!r} was taken as a stream")
        except ValueError as e:
            assert "not a stream address" in str(e)


def test_a_stream_through_ffmpeg():
    """A network stream: ffmpeg serving its test picture as MJPEG over HTTP on the loopback (as a phone camera
    app does), read as a "stream" source - and by the camera list's entry, as mapping opens it."""
    if not shutil.which("ffmpeg"):
        print("     (no ffmpeg: the stream test is left out)")
        return
    import socket
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    url = f"http://127.0.0.1:{port}/video"
    srv = subprocess.Popen([shutil.which("ffmpeg"), "-v", "error", "-re", "-f", "lavfi", "-i",
                            "testsrc=size=160x120:rate=15", "-f", "mpjpeg", "-listen", "1", url])
    src = None
    try:
        end = time.time() + 15
        while True:                       # opened again until the server is up (it takes one connection: no probe)
            src = video.open_camera(video.STREAM + url, width=64, height=48, fit=True)
            assert src.kind == "stream" and src.label == video.STREAM + url
            while src.latest()[1] < 3 and time.time() < end and not src.error:
                time.sleep(0.05)
            if src.latest()[1] >= 3 or time.time() >= end:
                break
            src.close()
            time.sleep(0.2)
        frame, n = src.latest()
        assert n >= 3 and frame.shape == (48, 64, 3) and frame.max() > 100, (n, src.error)
    finally:
        if src is not None:
            src.close()
        srv.kill()
        srv.wait(5)


def test_the_phones_camera():
    """The phone remote's camera as a source: nothing until a frame comes, then the newest, filled or fitted."""
    import io
    from PIL import Image
    from native import phone
    hub = phone.CameraHub()
    src = video.PhoneSource(hub, 96, 54)
    assert src.latest() == (None, 0) and "waiting for the phone" in src.describe()
    buf = io.BytesIO()
    Image.new("RGB", (480, 640), (20, 200, 40)).save(buf, "JPEG")         # a phone held upright
    hub.put(buf.getvalue())
    frame, n = src.latest()
    assert frame.shape == (54, 96, 3) and n == 1 and frame[0, 0, 1] > 150   # filled: green to the corners
    assert src.latest()[1] == 1                                             # the same frame: not made again
    fit = video.PhoneSource(hub, 96, 54, fit=True).latest()[0]
    assert fit[27, 0].max() < 10 and fit[27, 48, 1] > 150                   # fitted: barred at the sides
    src.pause(True)
    hub.put(buf.getvalue())
    assert src.latest()[1] == 1 and src.paused                              # paused: the picture holds
    assert video.open_camera(video.PHONE).kind == "phone"


def test_the_monitors_xrandr_lists():
    """X11's monitors, from `xrandr --listmonitors`: the name, the size and where each one sits."""
    text = ("Monitors: 2\n 0: +*HDMI-0 1920/598x1080/336+0+0  HDMI-0\n"
            " 1: +DP-1 2560/597x1440/336+1920+-360  DP-1\n")
    assert video._xrandr_monitors(text) == [("HDMI-0", 1920, 1080, 0, 0), ("DP-1", 2560, 1440, 1920, -360)]
    assert video._xrandr_monitors("") == []


def test_the_screen_through_ffmpeg():
    """The screen as a video source: the whole desktop (or X11's whole screen) first in the list, and frames
    from it at the source's size. Left out without ffmpeg, without a display, and on macOS (it asks for the
    Screen Recording permission, which a test cannot give)."""
    if not shutil.which("ffmpeg") or sys.platform == "darwin":
        print("     (no ffmpeg, or macOS: the screen test is left out)")
        return
    found = video.screens()
    if not found:
        print(f"     (no screen here: {video.screen_note()})")
        return
    assert found[0][0] in ("the whole desktop", "the whole screen"), found[0][0]
    src = video.open_source("screen", name=found[0][0], width=64, height=36)
    try:
        end = time.time() + 10
        while src.latest()[1] < 3 and time.time() < end and not src.error:
            time.sleep(0.05)
        frame, n = src.latest()
        assert n >= 3 and frame.shape == (36, 64, 3), (n, src.error)
    finally:
        src.close()
    try:
        video.open_source("screen", name="no such display")
        raise AssertionError("a screen that is not there was opened")
    except ValueError as e:
        assert "no screen called" in str(e)


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
