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
subprocess.run and subprocess.Popen exactly.
"""
import os
import subprocess

# CREATE_NO_WINDOW: no console for a console child. Not CREATE_NEW_CONSOLE,
# and not DETACHED_PROCESS, which leaves the child without stdio handles.
FLAGS = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
if os.environ.get("STUDIO_CONSOLE_CHILDREN"):
    FLAGS = 0            # a diagnostic: children get their console back, to watch a build go by


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
