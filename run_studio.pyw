"""WLED Effects Studio - the desktop shortcut's launcher, with no console window.

Run by pythonw (the shortcut: pythonw.exe run_studio.pyw; a double-click
on this file does the same). From its own folder it builds the engine once
when there is none, then starts the studio - both without a console - and
waits for it. A dev tool that dies silently is worse than one that never
started, so it does not: if the engine will not build, or the studio does
not start or ends with an error, the reason comes up in a message box, and
the whole of it is in %TEMP%\\cubefx\\launch.log (the studio's own output,
which Help > Report a problem also takes). run_studio.cmd still starts it
in a console, for when that is wanted.
"""
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
LOG = os.path.join(tempfile.gettempdir(), "cubefx", "launch.log")
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _say(title, text):
    """The reason in a message box (on top, so it is not lost behind other windows)."""
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, text, title, 0x10 | 0x40000)       # MB_ICONERROR | MB_TOPMOST
    except Exception:
        pass


def _tail(n=14):
    try:
        lines = open(LOG, encoding="utf-8", errors="replace").read().splitlines()
    except OSError:
        return ""
    return "\n".join(lines[-n:])


def _run(args, log):
    return subprocess.call(args, cwd=HERE, stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                           creationflags=NO_WINDOW)


def main():
    os.chdir(HERE)
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    py = sys.executable                                    # pythonw: what it starts has no console either
    with open(LOG, "w", encoding="utf-8", errors="replace") as log:
        # the engine: build/latest names the DLL to load (native/toolchain.py); the legacy cubefx.dll counts too
        if not os.path.exists(os.path.join(HERE, "build", "latest")) and not os.path.exists(os.path.join(HERE, "cubefx.dll")):
            log.write("no engine built yet - building it once, this takes a minute...\n"); log.flush()
            if _run([py, "build.py", "--native-only"], log) != 0:
                log.flush()
                _say("WLED Effects Studio: the engine did not build",
                     _tail() + f"\n\nThe whole of it: {LOG}\npython -m native.doctor says what is missing.")
                return 1
        code = _run([py, "-u", "-m", "native.app"], log)
    if code != 0:
        _say("WLED Effects Studio stopped with an error",
             _tail() + f"\n\nThe whole of it: {LOG} (and %TEMP%\\cubefx\\crash.txt)."
             "\nMissing packages: pip install -r requirements.txt; python -m native.doctor says what is missing.")
    return code


if __name__ == "__main__":
    sys.exit(main())
