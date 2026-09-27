"""The studio's scratch folder: crash.txt, the popouts' window places, the
launcher's log - and, for the tests alone, the remote-control command file
and the frame capture.

Per user and private (GHSA-h8r2-jh8g-f2xh). It used to be <tmp>/cubefx, and
on Linux and macOS <tmp> is /tmp, shared by every account on the machine:
another user could make that folder first and hand the app commands (one of
them runs Python), read what it captured, or leave a link where it writes.
Now it is:

- on Windows, <%TEMP%>/cubefx: %TEMP% is the user's own already;
- elsewhere $XDG_RUNTIME_DIR/cubefx (a folder the system makes for the user
  alone), or <tmp>/cubefx-<uid>: made 0700 and checked - a real folder, not
  a link, owned by this user, no one else let in. One that fails the check
  is not used (DIR is None, and what would go there is left out).

Files in it are opened without following links (O_NOFOLLOW where the
system has it). Remote control - the command file the tests drive the app
with, and the capture - is on only when STUDIO_REMOTE_CONTROL=1 is set: the
tests set it, nobody else needs it.
"""
import os
import stat
import tempfile
import time

NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)


def _private(path):
    """path made (0700) when missing; True when it is a real folder that is
    this user's alone. A folder with group or other rights was not made
    here (a mode only loses bits to the umask), so it is refused, not fixed."""
    try:
        os.makedirs(path, mode=0o700, exist_ok=True)
        st = os.lstat(path)
    except OSError:
        return False
    if not stat.S_ISDIR(st.st_mode):                  # a link to somewhere else, or a file
        return False
    if hasattr(os, "getuid"):
        if st.st_uid != os.getuid() or st.st_mode & 0o077:
            return False
    return True


def candidates():
    """Where the folder may be, in order of preference."""
    if os.name == "nt":
        return [os.path.join(tempfile.gettempdir(), "cubefx")]
    out = []
    run = os.environ.get("XDG_RUNTIME_DIR", "")
    if run and os.path.isabs(run) and os.path.isdir(run):          # the system's to make, never made here
        out.append(os.path.join(run, "cubefx"))
    out.append(os.path.join(tempfile.gettempdir(), f"cubefx-{os.getuid()}"))
    return out


def find():
    for d in candidates():
        if _private(d):
            return d
    return None


DIR = find()


def path(name):
    """A file in the folder, or None when there is no folder to be had."""
    return os.path.join(DIR, name) if DIR else None


def remote_control():
    """The tests' remote control (the command file, the capture): only when
    asked for, and only in a folder of this user's alone."""
    return os.environ.get("STUDIO_REMOTE_CONTROL", "") not in ("", "0") and DIR is not None


def _open(p, flags, mode=0o600):
    if not NOFOLLOW and os.path.islink(p):            # Windows: no O_NOFOLLOW - looked at first
        raise OSError(f"{p} is a link")
    return os.open(p, flags | NOFOLLOW | getattr(os, "O_BINARY", 0), mode)


def read_text(p):
    """A file's text, not through a link."""
    fd = _open(p, os.O_RDONLY)
    with os.fdopen(fd, "rb") as f:
        return f.read().decode("utf-8")


def write_text(p, text, append=False):
    """Text written (or added) to a file, not through a link, readable by this user alone."""
    flags = os.O_WRONLY | os.O_CREAT | (os.O_APPEND if append else os.O_TRUNC)
    fd = _open(p, flags)
    with os.fdopen(fd, "ab" if append else "wb") as f:
        f.write(text.encode("utf-8"))


def write_whole(p, text):
    """A file written whole: into <p>.tmp, then moved over p, so a reader
    never finds it half written - the tests' command file, which the app
    takes (and removes) the moment it is there. On Windows a reader that
    has the file open holds the move off for a moment: tried again."""
    tmp = p + ".tmp"
    write_text(tmp, text)
    for _ in range(40):
        try:
            os.replace(tmp, p)
            return
        except PermissionError:
            time.sleep(0.05)
    os.replace(tmp, p)
