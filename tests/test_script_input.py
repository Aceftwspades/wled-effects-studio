"""The Studio Script effect's program is untrusted input: it reaches the device as /studio.bin over the network.
The firmware's own loader and VM run here in the sim (cube_fx_98_script.cpp, from the WLED checkout), so a program
crafted to break them is refused here as it is there - each in a process of its own, so a crash is a failure, not
the end of the run. Run with  python tests/test_script_input.py  (or pytest).
"""
import os
import struct
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)


def _valid_program():
    """A real program: the first example graph the script compiler takes."""
    from native import graph as G
    from native.script import compile_script, ScriptError
    ex = os.path.join(ROOT, "examples", "graphs")
    for fn in sorted(os.listdir(ex)):
        g = G.load(os.path.join(ex, fn)); g.project_dir = os.path.join(ROOT, "examples")
        try:
            return bytes(compile_script(g))
        except ScriptError:
            continue
    raise AssertionError("no example graph compiles to a script")


def _run_in_child(prog_hex, timeout=120):
    """Load the program into the engine in a process of its own: 'refused', 'loaded', or how it died."""
    code = f"""
import sys, os
sys.path.insert(0, {ROOT!r}); os.chdir({ROOT!r})
from native.engine import Engine
from native.geometry import Geometry
e = Engine(); e.set_geometry(Geometry("matrix", w=16, h=16))
ok = e.script(bytes.fromhex({prog_hex!r}))
si = e.script_effect()
if ok and si is not None:
    e.select(si)
    for _ in range(3):
        e.frame(23)
print("loaded" if ok else "refused")
"""
    p = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=timeout)
    return p.stdout.strip().splitlines()[-1] if p.returncode == 0 and p.stdout.strip() else f"died (rc={p.returncode})"


def test_a_valid_program_still_loads():
    assert _run_in_child(_valid_program().hex()) == "loaded"


def test_lengths_that_wrap_round_are_refused():
    """frameLen and pixelLen are 32-bit fields: 0x80000000 and the rest of 2**32 summed to the file's own size, so
    the length check passed, the frame part was read as it is, and the pixel part was looked for 2 GB further on."""
    prog = bytearray(_valid_program())
    n = len(prog)
    frame_len = 0x80000000
    pixel_len = (n - 19 - frame_len) % (1 << 32)
    prog[11:15] = struct.pack("<I", frame_len)
    prog[15:19] = struct.pack("<I", pixel_len)
    assert _run_in_child(bytes(prog).hex()) == "refused"


def test_a_count_from_the_program_cannot_hang_the_frame():
    """Loop counts are values of the program's own: the Mandelbrot example's 90 iterations made a billion, a frame
    ran for ever (on the device, the watchdog's reset - a boot loop if it was the boot preset). The VM keeps each
    count to what its node allows, and a frame of it comes back."""
    from native import graph as G
    from native.script import compile_script
    g = G.load(os.path.join(ROOT, "examples", "graphs", "mandelbrot.json")); g.project_dir = os.path.join(ROOT, "examples")
    n = next(n for n in g.nodes.values() if n["type"] == "Mandelbrot")
    prog = bytes(compile_script(g))
    was = struct.pack("<f", float(n["params"]["iterations"]))
    assert prog.count(was) == 1, "the iteration count is not one constant of the program"
    prog = prog.replace(was, struct.pack("<f", 1e9))
    try:
        got = _run_in_child(prog.hex(), timeout=60)
    except subprocess.TimeoutExpired:
        got = "a frame did not come back in 60 s"
    assert got == "loaded", got


if __name__ == "__main__":
    import inspect
    bad = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and inspect.isfunction(fn):
            try:
                fn()
                print("ok  ", name)
            except Exception as e:
                bad += 1
                print("FAIL", name, e)
    sys.exit(1 if bad else 0)
