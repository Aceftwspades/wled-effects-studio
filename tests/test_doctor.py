"""python -m native.doctor on each platform (native/doctor.py): the Windows
loopback package asked for on Windows only; sounddevice installed without
the PortAudio library (Linux) sent to the system's package, not to pip; the
MIDI package's build needs named on Linux. Run on any machine: the platform
and the failing import are stood in for.
Run with  python tests/test_doctor.py  (or pytest)."""
import importlib.abc
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from native import doctor


class _NoPortAudio(importlib.abc.MetaPathFinder):
    """sounddevice as Linux has it without PortAudio: the package there, its library not."""
    def find_spec(self, name, path=None, target=None):
        if name == "sounddevice":
            raise OSError("PortAudio library not found")
        return None


def test_the_windows_loopback_only_on_windows():
    names = lambda plat: [pkg for _, pkg, _ in doctor.optional(plat)]
    assert "pyaudiowpatch" in names("win32")
    assert "pyaudiowpatch" not in names("linux") and "pyaudiowpatch" not in names("darwin")
    assert {"sounddevice", "python-rtmidi"} <= set(names("linux"))


def test_the_fix_for_each_way_a_package_is_off():
    fix = doctor.optional_fix("sounddevice", OSError("PortAudio library not found"), "linux")
    assert "PortAudio" in fix and "libportaudio2" in fix and "pip" not in fix
    assert doctor.optional_fix("sounddevice", ImportError("No module named 'sounddevice'"), "linux", pip="pip install") == "pip install sounddevice"
    assert "ALSA" in doctor.optional_fix("python-rtmidi", ImportError("x"), "linux")
    assert doctor.optional_fix("python-rtmidi", ImportError("x"), "win32", pip="pip install") == "pip install python-rtmidi"


def test_the_doctor_on_linux_without_portaudio():
    saved_platform, saved_mod = sys.platform, sys.modules.pop("sounddevice", None)
    finder = _NoPortAudio()
    sys.meta_path.insert(0, finder)
    sys.platform = "linux"
    try:
        rows = doctor.check()
    finally:
        sys.platform = saved_platform
        sys.meta_path.remove(finder)
        if saved_mod is not None:
            sys.modules["sounddevice"] = saved_mod
    lines = [line for _, line, _ in rows]
    assert not any("pyaudiowpatch" in line for line in lines), lines
    sd = next(r for r in rows if r[1].startswith("sounddevice"))
    assert sd[0] is None and "cannot load its library" in sd[1] and "PortAudio" in sd[2], sd


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
