"""What this machine has and lacks for the studio:  python -m native.doctor

Python, the packages, a C++ compiler for the engine and the effects,
the engine itself, the WLED checkout or the runtime folder that stands
in for it, PlatformIO for the flash, ffmpeg for videos - and the one
line that fixes each thing missing. Exit code 1 when the app cannot run.
"""
import importlib
import os
import shutil
import sys

from native import paths

REQUIRED = (("numpy", "numpy"), ("dearpygui", "dearpygui"), ("PIL", "pillow"))


def optional(platform=None):
    """(module, package, what it is for): the optional packages this platform can have - the
    Windows loopback only on Windows (requirements.txt installs it nowhere else)."""
    platform = platform or sys.platform
    out = [("sounddevice", "sounddevice", "live audio capture")]
    if platform == "win32":
        out.append(("pyaudiowpatch", "pyaudiowpatch", "capturing what the PC plays (Windows loopback)"))
    out.append(("rtmidi", "python-rtmidi", "a MIDI controller's knobs on the sliders"))
    return out


def optional_fix(pkg, error, platform=None, pip="python -m pip install"):
    """How to get an optional package working: pip for one that is not there - but sounddevice
    installed without PortAudio (Linux, where it does not bring the library) needs the system's."""
    platform = platform or sys.platform
    if pkg == "sounddevice" and isinstance(error, OSError) and "portaudio" in str(error).lower():
        return ("install PortAudio: libportaudio2 (Debian, Ubuntu), portaudio (Arch, Fedora, Homebrew) - "
                "the sounddevice package is there already")
    if pkg == "python-rtmidi" and platform.startswith("linux"):
        return (f"{pip} python-rtmidi  (where there is no wheel for this Python it builds from source: a C++ compiler "
                "and the ALSA headers - libasound2-dev, alsa-lib-devel - and JACK's if you have it)")
    return f"{pip} {pkg}"


def _ver(mod):
    return getattr(mod, "__version__", None) or getattr(mod, "VERSION", "") or "present"


def check():
    """[(ok, line, fix)]: what was looked at, whether it is there, how to get it."""
    out = []
    v = sys.version_info
    ok = v >= (3, 10)
    out.append((ok, f"Python {v.major}.{v.minor}.{v.micro}" + ("" if ok else " - 3.10 or newer needed"), "" if ok else "install Python 3.10+ from python.org"))
    pip = f"{os.path.basename(sys.executable)} -m pip install"
    for mod, pkg in REQUIRED:
        try:
            m = importlib.import_module(mod); out.append((True, f"{pkg} {_ver(m)}", ""))
        except Exception:
            out.append((False, f"{pkg} missing", f"{pip} {pkg}"))
    for mod, pkg, what in optional():
        try:
            m = importlib.import_module(mod)
            line = f"{pkg} {_ver(m)} ({what})"
            if pkg == "sounddevice" and sys.platform.startswith("linux"):
                line += " - what the PC plays: a PipeWire / PulseAudio \"Monitor of ...\" input in the panel's LIVE, where it lists one"
            out.append((True, line, ""))
        except Exception as e:
            gone = isinstance(e, OSError)             # there, but a library of the system's is not
            out.append((None, f"{pkg} {'cannot load its library' if gone else 'not installed'} - {what} is off",
                        optional_fix(pkg, e, pip=pip)))
    # the compiler
    try:
        from native.toolchain import find_compiler, bundled_compiler
        c, _ = find_compiler()
        out.append((True, f"compiler: {c}" + (" (bundled)" if bundled_compiler() else ""), ""))
    except Exception as e:
        out.append((None, f"no C++ compiler: {e}", "Windows: install emsdk (its clang) and the MSVC Build Tools, or put a MinGW-w64 in toolchain/ beside the app; "
                                                     "Linux/macOS: clang or gcc. Without one, effects cannot be built - viewing and the examples still work"))
    # the engine
    from native.toolchain import latest_library
    lib = latest_library()
    out.append((bool(lib), f"engine: {os.path.basename(lib) if lib else 'not built'}", "" if lib else "python build.py --native-only  (needs the compiler)"))
    # the firmware sources
    if paths.TREE:
        out.append((True, f"WLED checkout: {paths.TREE}", ""))
    elif os.path.isdir(paths.RUNTIME):
        out.append((True, f"no WLED checkout; runtime/ stands in ({paths.RUNTIME}) - the flash needs a checkout: set WLED_ROOT", ""))
    else:
        out.append((False, "neither a WLED checkout nor runtime/: the engine cannot be built", "run  python build.py --runtime  from a checkout, or set WLED_ROOT"))
    # the flash
    pio = shutil.which("pio") or shutil.which("platformio") or next((p for p in (os.path.expanduser("~/.platformio/penv/Scripts/pio.exe"), os.path.expanduser("~/.platformio/penv/bin/pio")) if os.path.exists(p)), None)
    out.append((None if not pio else True, f"PlatformIO: {pio or 'not found - the flash is off'}", "" if pio else "pip install platformio  (and a WLED checkout)"))
    ff = shutil.which("ffmpeg")
    out.append((None if not ff else True, f"ffmpeg: {ff or 'not found - recordings are GIFs only'}", "" if ff else "install ffmpeg and put it on the path"))
    out.append((True, f"home (projects, build, captures): {paths.HOME}", ""))
    out.append((True, f"resources: {paths.RES}" + (" (packaged)" if paths.FROZEN else ""), ""))
    return out


def main():
    rows = check()
    bad = 0
    for ok, line, fix in rows:
        mark = "ok  " if ok else ("--  " if ok is None else "MISSING")
        print(f"{mark:8s}{line}")
        if fix and ok is not True:
            print(f"        -> {fix}")
        if ok is False:
            bad += 1
    print("\nthe studio can run" if not bad else f"\n{bad} thing(s) to fix before the studio runs")
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
