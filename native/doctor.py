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
OPTIONAL = (("sounddevice", "sounddevice", "live audio capture"),
            ("pyaudiowpatch", "pyaudiowpatch", "capturing what the PC plays (Windows loopback)"))


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
    for mod, pkg, what in OPTIONAL:
        try:
            m = importlib.import_module(mod); out.append((True, f"{pkg} {_ver(m)} ({what})", ""))
        except Exception:
            out.append((None, f"{pkg} not installed - {what} is off", f"{pip} {pkg}"))
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
