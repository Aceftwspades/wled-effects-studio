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
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
from native import scratch                                 # noqa: E402 - the app's private scratch folder
CMD = scratch.path("command.json")
LOG = scratch.path("uiref.log")


def main():
    if not scratch.DIR:
        print("uiref: no private scratch folder to drive the app through (native/scratch.py)")
        return 1
    project = os.path.join(ROOT, "projects", "default", "project.json")
    saved = open(project, encoding="utf-8").read() if os.path.exists(project) else None
    prefs = os.path.join(ROOT, "projects", "studio.json")     # the zoom set below would otherwise stay
    saved_prefs = open(prefs, encoding="utf-8").read() if os.path.exists(prefs) else None
    with open(LOG, "w") as log:
        proc = subprocess.Popen([sys.executable, "-u", "-m", "native.app"], cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
                                env=dict(os.environ, STUDIO_NO_UPDATE_CHECK="1", STUDIO_NO_WELCOME="1", STUDIO_REMOTE_CONTROL="1"))
    try:
        time.sleep(9)
        # a shape of parts, so the side panel's and the shape frame's per-part buttons exist; the
        # frames built (they are made on first show); the graph at 100%, since the zoom button's
        # label is the zoom (the reference would say whatever the last session left); then the
        # section written
        scratch.write_whole(CMD, json.dumps([{"geometry": {"kind": "shape", "params": {"parts": [{"kind": "points", "name": "points", "params": {"points": [[0, 0, 0], [1, 0, 0], [2, 0, 0]]},
                                                                        "pos": [0, 0, 0], "rot": [0, 0, 0], "scale": 1.0, "reverse": False}]}}},
                   {"frame": "devices"}, {"frame": "flash"}, {"frame": "send"}, {"frame": "shape"}, {"frame": "sequence"},
                   {"frame": "library"}, {"frame": "palettes"}, {"frame": "outputs"}, {"graph_zoom": 1.0}]))
        time.sleep(5)
        scratch.write_whole(CMD, json.dumps([{"uiref": os.path.join(ROOT, "GUIDE.md")}]))
        time.sleep(3)
    finally:
        proc.kill()
        time.sleep(1)
        if saved is not None:
            open(project, "w", encoding="utf-8").write(saved)
        if saved_prefs is not None:
            open(prefs, "w", encoding="utf-8").write(saved_prefs)
    text = open(LOG, encoding="utf-8", errors="replace").read()
    line = next((l for l in text.splitlines() if l.startswith("uiref ")), None)
    print(line or "uiref: the app wrote nothing - see " + LOG)
    return 0 if line else 1


if __name__ == "__main__":
    sys.exit(main())
