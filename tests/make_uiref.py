"""GUIDE.md's reference section (every menu item with its key, every key
action, every button with its tooltip) written from the running app:

    python tests/make_uiref.py

Run it after adding a menu item, an action or a button; tests/test_docs.py
fails until the guide names the new thing.
"""
import json
import os
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CMD = os.path.join(tempfile.gettempdir(), "cubefx", "command.json")
LOG = os.path.join(tempfile.gettempdir(), "cubefx", "uiref.log")


def main():
    os.makedirs(os.path.dirname(CMD), exist_ok=True)
    project = os.path.join(ROOT, "projects", "default", "project.json")
    saved = open(project, encoding="utf-8").read() if os.path.exists(project) else None
    with open(LOG, "w") as log:
        proc = subprocess.Popen([sys.executable, "-u", "-m", "native.app"], cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
                                env=dict(os.environ, STUDIO_NO_UPDATE_CHECK="1"))
    try:
        time.sleep(9)
        # a shape of parts, so the side panel's and the shape frame's per-part buttons exist; the
        # frames built (they are made on first show); then the section written
        json.dump([{"geometry": {"kind": "shape", "params": {"parts": [{"kind": "points", "name": "points", "params": {"points": [[0, 0, 0], [1, 0, 0], [2, 0, 0]]},
                                                                        "pos": [0, 0, 0], "rot": [0, 0, 0], "scale": 1.0, "reverse": False}]}}},
                   {"frame": "devices"}, {"frame": "flash"}, {"frame": "send"}, {"frame": "shape"}, {"frame": "sequence"},
                   {"frame": "library"}, {"frame": "palettes"}, {"frame": "outputs"}], open(CMD, "w"))
        time.sleep(5)
        json.dump([{"uiref": os.path.join(ROOT, "GUIDE.md")}], open(CMD, "w"))
        time.sleep(3)
    finally:
        proc.kill()
        time.sleep(1)
        if saved is not None:
            open(project, "w", encoding="utf-8").write(saved)
    text = open(LOG, encoding="utf-8", errors="replace").read()
    line = next((l for l in text.splitlines() if l.startswith("uiref ")), None)
    print(line or "uiref: the app wrote nothing - see " + LOG)
    return 0 if line else 1


if __name__ == "__main__":
    sys.exit(main())
