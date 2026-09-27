"""python -m native.cli with what a person mistypes (issue #10): an effect
that is not there (with the near names), a --set that is not name=number,
--fps 0 - each a one-line error and exit code 2 from argparse, never a
traceback. Needs a built engine (the effect's name is looked up in it).
Run with  python tests/test_cli.py  (or pytest)."""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _cli(*args):
    r = subprocess.run([sys.executable, "-m", "native.cli", *args], cwd=ROOT, capture_output=True, text=True, timeout=120)
    return r.returncode, r.stdout + r.stderr


def test_mistakes_are_one_line_not_a_traceback():
    for args, words in [(("--measure", "no such effect"), "no effect matching 'no such effect'"),
                        (("--measure", "maelstrm"), "did you mean"),
                        (("--measure", "solid", "--set", "sx=abc"), "--set: sx='abc'"),
                        (("--measure", "solid", "--set", "sx"), "is not name=number"),
                        (("--measure", "solid", "--sweep", "c3=a,b"), "--sweep"),
                        (("--snapshot", "solid", "--at", "1,x"), "--at"),
                        (("--gif", "solid", "--fps", "0"), "argument --fps"),
                        (("--gif", "solid", "--fps", "-2"), "argument --fps"),
                        (("--gif", "solid", "--scale", "0"), "argument --scale"),
                        (("--measure", "solid", "--ms", "nan"), "argument --ms")]:
        code, out = _cli(*args)
        assert code == 2 and words in out and "Traceback" not in out, (args, code, out[-600:])


def test_a_measure_still_runs():
    code, out = _cli("--measure", "solid", "--ms", "500", "--sweep", "sx=10,200")
    assert code == 0 and '"sx=10"' in out and '"sx=200"' in out, out[-600:]


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
