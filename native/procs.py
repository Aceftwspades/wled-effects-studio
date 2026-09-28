"""Child processes without a console window.

On Windows a process with no console of its own - the packaged windowed
exe, or pythonw - gives every console child it starts a NEW console
window. The compiler is a console program, so a Live rebuild flashed a
black box over the graph, once per translation unit, on every edit.
CREATE_NO_WINDOW stops that; the child's output still comes back
through the pipes, which is the only way the studio reads it anyway.

Everything the app starts goes through here:

    procs.run([compiler, ...], capture_output=True, text=True)
    procs.popen(args, stdout=subprocess.PIPE)

Elsewhere (Linux, macOS) the flag does not exist and these are
subprocess.run and subprocess.Popen exactly. The packaged app on Linux
puts its library path back as it starts (restore_library_path), so its
children never see the app's own copies of shared libraries.
"""
import os
import subprocess
import sys

# CREATE_NO_WINDOW: no console for a console child. Not CREATE_NEW_CONSOLE,
# and not DETACHED_PROCESS, which leaves the child without stdio handles.
FLAGS = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
if os.environ.get("STUDIO_CONSOLE_CHILDREN"):
    FLAGS = 0            # a diagnostic: children get their console back, to watch a build go by


def child_env(env=None, frozen=None, platform=None):
    """The environment for a child of the packaged app on Linux. PyInstaller's
    bootloader puts the app's own library folder first on LD_LIBRARY_PATH
    (keeping what it was in LD_LIBRARY_PATH_ORIG): a system compiler, ffmpeg
    or PlatformIO started with that would load the app's copies of shared
    libraries in place of their own. The path as it was goes back; anywhere
    else `env` is returned as it came (None: the parent's)."""
    frozen = getattr(sys, "frozen", False) if frozen is None else frozen
    if not (frozen and (platform or sys.platform).startswith("linux")):
        return env
    e = dict(os.environ if env is None else env)
    orig = e.get("LD_LIBRARY_PATH_ORIG")
    if orig is not None:
        e["LD_LIBRARY_PATH"] = orig
    else:
        e.pop("LD_LIBRARY_PATH", None)
    return e


def restore_library_path():
    """Once, as the packaged app starts: its environment's library path as it
    was before the bootloader, so every child - the compiler, ffmpeg,
    PlatformIO, the browser a link opens - gets its own libraries. The app
    itself is unaffected (a process reads the path once, when it starts)."""
    e = child_env()
    if e is None:
        return
    if "LD_LIBRARY_PATH" in e:
        os.environ["LD_LIBRARY_PATH"] = e["LD_LIBRARY_PATH"]
    else:
        os.environ.pop("LD_LIBRARY_PATH", None)


def kwargs(extra=None):
    """The creationflags to pass a child, merged with what the caller has."""
    kw = dict(extra or {})
    if FLAGS:
        kw["creationflags"] = kw.get("creationflags", 0) | FLAGS
    return kw


def run(*args, **kw):
    return subprocess.run(*args, **kwargs(kw))


def popen(*args, **kw):
    return subprocess.Popen(*args, **kwargs(kw))
