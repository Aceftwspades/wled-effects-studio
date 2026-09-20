"""Getting a WLED checkout when there is none: the flash needs one.

    fetch(dest, log)      -> the checkout at dest: git clone when git is on
                             the path, else the branch's zip from GitHub,
                             unpacked; log(line) as it goes; raises on failure
    remember(dest)        -> the path into the prefs, where paths.py finds
                             it next start (WLED_ROOT still wins)
    default_dest()        -> where to put it: WLED beside the app's home

The fork is version.WLED_REPO on its branch (the firmware side: the
cube_fx usermod, the PlatformIO environments the studio flashes).
"""
import json
import os
import shutil
import subprocess
import sys
import urllib.request
import zipfile

from native import paths, version

BRANCH = "playground"


def default_dest():
    return os.path.join(os.path.dirname(paths.HOME) if paths.FROZEN else os.path.dirname(paths.RES), "WLED")


def has_git():
    return bool(shutil.which("git"))


def fetch(dest, log=print):
    """The fork's branch into `dest` (which must not exist, or be empty)."""
    dest = os.path.abspath(dest)
    if os.path.isdir(dest) and os.listdir(dest):
        if os.path.isdir(os.path.join(dest, "wled00")):
            log(f"{dest} is a WLED checkout already"); return dest
        raise RuntimeError(f"{dest} exists and is not empty")
    url = f"https://github.com/{version.WLED_REPO}"
    if has_git():
        log(f"git clone --branch {BRANCH} --depth 1 {url} {dest}")
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        p = subprocess.Popen(["git", "clone", "--branch", BRANCH, "--depth", "1", "--progress", url + ".git", dest],
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, creationflags=flags)
        for line in p.stdout:
            line = line.strip("\r\n")
            if line:
                log(line.split("\r")[-1])
        if p.wait() != 0:
            raise RuntimeError("git clone failed - the lines above say why")
    else:
        # no git: the branch as GitHub's zip, unpacked; not a repository, but PlatformIO does not mind
        zurl = f"{url}/archive/refs/heads/{BRANCH}.zip"
        tmp = dest + ".zip"
        log(f"no git on the path: downloading {zurl}")
        req = urllib.request.Request(zurl, headers={"User-Agent": "wled-effects-studio"})
        with urllib.request.urlopen(req, timeout=60) as r, open(tmp, "wb") as f:
            done = 0
            while True:
                chunk = r.read(1 << 18)
                if not chunk:
                    break
                f.write(chunk); done += len(chunk)
                if done % (8 << 20) < (1 << 18):
                    log(f"  {done / 1e6:.0f} MB")
        log("unpacking...")
        parent = os.path.dirname(dest)
        with zipfile.ZipFile(tmp) as z:
            top = z.namelist()[0].split("/")[0]
            z.extractall(parent)
        os.remove(tmp)
        os.replace(os.path.join(parent, top), dest)
    if not os.path.isdir(os.path.join(dest, "wled00")):
        raise RuntimeError(f"{dest} has no wled00/ - not a WLED tree")
    log(f"WLED checkout ready: {dest}")
    return dest


def remember(dest):
    """The path into the prefs (projects/studio.json, ui.wled_root)."""
    p = os.path.join(paths.PROJECTS, "studio.json")
    try:
        d = json.load(open(p, encoding="utf-8"))
    except Exception:
        d = {}
    d.setdefault("ui", {})["wled_root"] = dest
    os.makedirs(paths.PROJECTS, exist_ok=True)
    json.dump(d, open(p, "w", encoding="utf-8"), indent=1)
    os.environ["WLED_ROOT"] = dest


def restart():
    """The app again, as it was started; the caller then stops this one."""
    args = [sys.executable] if paths.FROZEN else [sys.executable, "-m", "native.app"]
    flags = getattr(subprocess, "DETACHED_PROCESS", 0)
    subprocess.Popen(args, cwd=paths.RES, creationflags=flags, close_fds=True)
