"""Swapping the engine for a new build, as every code edit and graph build
does (issue #3): Engine.reload() unloads the old library - dlclose on Linux
and macOS, FreeLibrary on Windows - and the new one runs, keeping the
effect, its sliders and the geometry. Two copies of the newest build stand
in for an old build and a new one. A dlclose handed a cut-down pointer
kills the process outright, so on Linux this test failing is a crash, not
an assert. Needs a built engine (python build.py --native-only).
Run with  python tests/test_engine.py  (or pytest)."""
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from native.engine import Engine, _unload
from native.geometry import Geometry
from native.toolchain import latest_library, lib_ext


def _copies(n):
    """n copies of the newest build in a folder of their own: separate
    files, so the loader gives each its own handle."""
    src = latest_library()
    assert src, "no engine built - python build.py --native-only"
    d = tempfile.mkdtemp(prefix="cubefx_reload_")
    paths = []
    for i in range(n):
        p = os.path.join(d, f"engine_{i}{lib_ext()}")
        shutil.copy2(src, p)
        paths.append(p)
    return d, paths


def test_reload_swaps_the_build_and_keeps_the_effect():
    d, (a, b, c) = _copies(3)
    try:
        e = Engine(a)
        e.set_geometry(Geometry("matrix", w=16, h=8))
        i = next(k for k, name in enumerate(e.names) if name != "Solid")
        e.select(i, params={"sx": 200, "ix": 40})
        e.frame()
        e.reload(b)                                   # unloads a
        assert e.library == b and e.names[e.idx] == e.names[i]
        assert (e.cols, e.rows) == (16, 8) and e.fx.get("sx") == 200
        for _ in range(3):
            e.frame()
        assert e.rgb().shape == (8, 16, 3)
        e.reload(c)                                   # and again: unloads b
        e.frame()
        assert e.library == c
        if os.name == "nt":
            # Windows holds a loaded DLL's file open: gone only when FreeLibrary worked
            os.remove(a)
            os.remove(b)
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_unload_takes_a_full_width_handle():
    """_unload on its own: the library's handle is a 64-bit pointer on a
    64-bit system, passed whole."""
    import ctypes as C
    d, (a,) = _copies(1)
    try:
        lib = C.CDLL(a)
        assert lib.simEffectCount() > 0
        _unload(lib)
        if os.name == "nt":
            os.remove(a)
    finally:
        shutil.rmtree(d, ignore_errors=True)


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
