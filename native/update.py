"""Updates: is there a newer release, and getting it in.

    check()            -> {"tag", "notes", "url", "asset", "newer"} or None (offline, no releases)
    download(asset)    -> the zip's path in HOME/updates, called on a thread
    apply(zip_path)    -> the packaged app replaced by the zip's contents and restarted

The check reads GitHub's releases API for version.REPO (no token; sixty
calls an hour is plenty for once a day) and compares the newest tag with
version.__version__. Applying is Windows and the packaged app only: a
script beside the zip waits for the app to close, unpacks the zip, copies
it over the app's folder - projects, captures and the toolchain left
alone - and starts the app again. From a checkout the answer is git pull;
elsewhere the zip is downloaded and the folder is opened for a copy by
hand. STUDIO_UPDATE_URL points the check at another releases JSON (a
test's).
"""
import json
import os
import subprocess
import sys
import time
import urllib.request

from native import paths, version

TIMEOUT = 8


def api_url():
    return os.environ.get("STUDIO_UPDATE_URL") or f"https://api.github.com/repos/{version.REPO}/releases/latest"


def check():
    """The newest release, or None when there is none to be had."""
    try:
        req = urllib.request.Request(api_url(), headers={"Accept": "application/vnd.github+json", "User-Agent": "wled-effects-studio"})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            d = json.loads(r.read().decode("utf-8", "replace"))
    except Exception:
        return None
    tag = d.get("tag_name") or ""
    asset = next((a.get("browser_download_url") for a in d.get("assets") or []
                  if str(a.get("name", "")).lower().endswith(".zip")), None)
    return {"tag": tag, "notes": (d.get("body") or "").strip(), "url": d.get("html_url") or "", "asset": asset,
            "newer": version.newer(tag), "name": d.get("name") or tag}


def due(prefs, every_s=86400.0):
    """Once a day, when the check is on."""
    if not prefs.get("update_check", True):
        return False
    return time.time() - float(prefs.get("update_checked_at", 0) or 0) >= every_s


def download(asset, progress=None):
    """The release zip into HOME/updates; the path. `progress(done, total)` as it comes."""
    d = os.path.join(paths.HOME, "updates")
    os.makedirs(d, exist_ok=True)
    out = os.path.join(d, "WLED_Effects_Studio.zip")
    req = urllib.request.Request(asset, headers={"User-Agent": "wled-effects-studio"})
    with urllib.request.urlopen(req, timeout=30) as r, open(out + ".part", "wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        done = 0
        while True:
            chunk = r.read(1 << 18)
            if not chunk:
                break
            f.write(chunk); done += len(chunk)
            if progress:
                progress(done, total)
    os.replace(out + ".part", out)
    return out


def can_apply():
    return paths.FROZEN and sys.platform.startswith("win")


def apply(zip_path):
    """The update put in place by a script that outlives the app: waits for
    this process to end, unpacks the zip, copies it over the app's folder
    (projects/, captures/ and toolchain/ untouched), starts the app again.
    Returns the script's path; the caller quits the app."""
    app_dir = paths.EXE_DIR
    updates = os.path.dirname(zip_path)
    unpacked = os.path.join(updates, "unpacked")
    exe = os.path.join(app_dir, "WLED Effects Studio.exe")
    script = os.path.join(updates, "apply.cmd")
    lines = [
        "@echo off",
        "title WLED Effects Studio - updating",
        "echo waiting for the studio to close...",
        ":wait",
        f'tasklist /FI "PID eq {os.getpid()}" 2>nul | find "{os.getpid()}" >nul && (timeout /t 1 /nobreak >nul & goto wait)',
        f'if exist "{unpacked}" rmdir /s /q "{unpacked}"',
        "echo unpacking...",
        f'powershell -NoProfile -ExecutionPolicy Bypass -Command "Expand-Archive -Force \'{zip_path}\' \'{unpacked}\'"',
        f'set "SRC={unpacked}\\WLED Effects Studio"',
        f'if not exist "%SRC%\\WLED Effects Studio.exe" set "SRC={unpacked}"',
        "echo copying in...",
        f'robocopy "%SRC%" "{app_dir}" /E /XD projects captures toolchain updates /NFL /NDL /NJH /NJS /NP >nul',
        "if errorlevel 8 (echo the copy failed - the zip is in the updates folder, unpack it over the app by hand & pause & exit /b 1)",
        f'rmdir /s /q "{unpacked}" 2>nul',
        f'start "" "{exe}"',
        "exit /b 0",
    ]
    with open(script, "w", encoding="utf-8", newline="\r\n") as f:
        f.write("\n".join(lines) + "\n")
    flags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
    subprocess.Popen(["cmd", "/c", script], cwd=updates, creationflags=flags, close_fds=True)
    return script
