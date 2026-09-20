"""Where things are - in the checkout, or in a packaged app.

Three places, and every module asks here rather than working them out
from its own file:

    RES    what ships with the app and is only read: shim/, gen/, runtime/,
           examples/, the docs. The studio folder when run from the tree;
           the bundle's folder when frozen by PyInstaller.
    HOME   what the user makes and the app writes: projects/, build/,
           captures/. The studio folder from the tree. Frozen: the folder
           the exe is in when it can be written to - a portable install
           keeps everything beside itself - else %LOCALAPPDATA%\\WLED
           Effects Studio (a Program Files install).
    TREE   the WLED checkout, when there is one: the repo above studio/,
           or WLED_ROOT. The engine's firmware sources come from it and
           the flash builds in it. Without one, the engine builds from
           runtime/ - the same files, copied in when the app was packaged -
           and the flash says it needs a checkout.
"""
import os
import sys

FROZEN = bool(getattr(sys, "frozen", False))
APP_NAME = "WLED Effects Studio"

if FROZEN:
    RES = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(sys.executable)))
    EXE_DIR = os.path.dirname(os.path.abspath(sys.executable))
else:
    RES = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))    # studio/
    EXE_DIR = RES


def _writable(d):
    try:
        os.makedirs(d, exist_ok=True)
        probe = os.path.join(d, ".write_test")
        with open(probe, "w") as f:
            f.write("ok")
        os.remove(probe)
        return True
    except OSError:
        return False


def _home():
    if not FROZEN or _writable(EXE_DIR):
        return EXE_DIR
    if sys.platform.startswith("win"):
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    elif sys.platform == "darwin":
        base = os.path.expanduser("~/Library/Application Support")
    else:
        base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return os.path.join(base, APP_NAME)


HOME = _home()
PROJECTS = os.path.join(HOME, "projects")
BUILD = os.path.join(HOME, "build")
CAPTURES = os.path.join(HOME, "captures")
RUNTIME = os.path.join(RES, "runtime")


def _tree():
    env = os.environ.get("WLED_ROOT")
    if env and os.path.isdir(os.path.join(env, "wled00")):
        return os.path.abspath(env)
    above = os.path.dirname(RES)
    if not FROZEN and os.path.isdir(os.path.join(above, "wled00")):
        return above
    return None


TREE = _tree()

# the firmware files the engine is compiled from, relative to the tree;
# runtime/ holds the same at these relative paths when there is no tree
RUNTIME_FILES = ("usermods/cube_fx", "wled00/wled_math.cpp", "wled00/src/dependencies/fastled_slim")


def tree_path(rel):
    """A file or folder of the WLED tree by its relative path: from the
    checkout when there is one, else from runtime/."""
    rel = rel.replace("\\", "/")
    if TREE:
        return os.path.join(TREE, *rel.split("/"))
    return os.path.join(RUNTIME, *rel.split("/"))


def firmware_dir():
    """usermods/cube_fx: the effects, the bank, the script VM."""
    return tree_path("usermods/cube_fx")


def has_tree():
    return TREE is not None


def describe():
    return (f"{'packaged' if FROZEN else 'from the tree'}; resources {RES}; home {HOME}; "
            f"WLED tree {TREE or ('none - runtime/ ' + ('present' if os.path.isdir(RUNTIME) else 'missing'))}")
