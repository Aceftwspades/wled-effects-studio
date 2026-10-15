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
        # what lives in the library's statics comes along: a custom palette (its id showed a stock palette after
        # every build), the audio palettes' source, and a lone segment's options and blend (kept only with two)
        e.custom_palettes([{"name": "red", "stops": [[0, 255, 0, 0], [255, 255, 0, 0]]}])
        e.pal_source = 2
        e.seg_set_options(0, mi=True, grp=2); e.seg_blend(0, 2)
        e.reload(c)                                   # and again: unloads b
        e.frame()
        assert e.library == c
        assert e.palette_swatch(200)[0] == (255, 0, 0) and e.pal_source == 2
        assert e.seg_options(0)["mi"] and e.seg_options(0)["grp"] == 2 and e.seg_get(0)[6] == 2
        # an index the new library does not reach (a project with fewer effects): it raised IndexError from
        # set_geometry's select before reload could pick the effect by name, leaving the old library loaded
        e.idx = e.count + 3
        e.load(c)                                     # as reload does, the index from a longer library
        assert 0 <= e.idx < e.count
        e.idx = e.count + 3
        e.reload(c)
        assert 0 <= e.idx < e.count
        e.frame()
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


def test_segments_past_the_last_are_not_selected():
    """seg_select(k) past the last segment: the engine ignored it, and this side then edited segment 0 believing
    it k. seg_truncate kept the removed segment's state (selecting first saved it again), so a segment added
    there later started as the removed one."""
    e = Engine(); e.set_geometry(Geometry("matrix", w=16, h=8))
    try:
        e.seg_select(5)
        raise AssertionError("segment 5 of 1 selected")
    except IndexError:
        pass
    e.seg_config(1, 8, 0, 16, 8); e.seg_config(2, 0, 4, 8, 8); e.seg_select(2)
    e.seg_truncate(1)
    assert e.seg == 0 and sorted(e._segstate) == [0]


def test_only_a_unit_opening_with_wled_h_takes_the_precompiled_header():
    """Something defined before wled.h could change what it means, so such a unit compiles from source."""
    from native import toolchain as T
    cases = {"// a comment\n/* and a block\n */\n#include \"wled.h\"\nint a;\n": True,
             "#include \"wled.h\"\n#define X 1\n": True,
             "#define CFX_SRC 6\n#include \"wled.h\"\n": False,
             "#include <math.h>\n#include \"wled.h\"\n": False,
             "#include \"fastled_slim.h\"\n": False}
    d = tempfile.mkdtemp()
    try:
        for i, (text, want) in enumerate(cases.items()):
            f = os.path.join(d, f"case_{i}.cpp")
            with open(f, "w", encoding="utf-8") as fh:
                fh.write(text)
            assert T._uses_pch(f) is want, (text, want)
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_a_compile_failing_over_the_precompiled_header_is_tried_again():
    from native import toolchain as T
    assert T._pch_failed("fatal error: file 'x/wled.h' has been modified since the precompiled header 'x/wled.pch' was built")
    assert T._pch_failed("error: input is not a PCH file: 'x/wled.pch'")
    assert T._pch_failed("x/wled.h.gch: not used because `CFX_SIM' not defined [-Werror=invalid-pch]")
    assert not T._pch_failed("aurora_drift.cpp:12:3: error: use of undeclared identifier 'foo'")


def test_the_precompiled_header_is_made_once_for_what_it_was_made_from():
    import build as B
    from native import toolchain as T
    comp, env = T.find_compiler()
    inc = B.include_dirs()
    hstamp, cid = T._header_stamp(inc), T._compiler_id(comp, env)
    flags = T.build_pch(comp, env, inc, hstamp, cid)
    assert flags, "no precompiled header"
    made = flags[1] if flags[0] == "-include-pch" else os.path.join(flags[1], "wled.h.gch")
    assert os.path.exists(made), made
    assert T.build_pch(comp, env, inc, hstamp, cid) == flags          # the same one, not made again


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
