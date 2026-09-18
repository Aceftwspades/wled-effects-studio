"""Every menu item and every context-menu row, invoked, and the log read
for failures.

    python tests/walk_menus.py          # from studio; ~90 s; exits 1 on a FAIL or a traceback

Like smoke_app.py it drives the running app through its JSON command file
(native/app.py service_command): `menu_walk` calls each item of the menu
bar in turn (a few are skipped: Quit, the 15 s recording, fullscreen, and
the ones that hand a path to the desktop), `ctx_walk` each row of a node's,
an input's and an output's context menu with the graph put back after each,
`pane_walk` each row of the panes' right-click menus. Not a pytest: it
needs the window and the engine, and it leaves the last project and layout
wherever the walk ended, so the project it started with is put back.
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
LOG = os.path.join(tempfile.gettempdir(), "cubefx", "walk.log")

STEPS = [
    ([{"layout": "graph"}, {"graph_open": "box_fire.json"}, {"graph_select": [3]}, {"menu_walk": True}], 20.0),
    ([{"layout": "graph"}, {"graph_open": "box_fire.json"}, {"action": "select_none"}, {"ctx_walk": ["node", 3, None]}], 8.0),
    ([{"graph_open": "box_fire.json"}, {"ctx_walk": ["in", 3, "a"]}], 6.0),
    ([{"graph_open": "box_fire.json"}, {"ctx_walk": ["out", 3, "result"]}], 6.0),
    ([{"layout": "both"}, {"pane_walk": True}], 4.0),
]


def send(cmds, wait):
    json.dump(cmds, open(CMD, "w"))
    time.sleep(wait)


def main():
    os.makedirs(os.path.dirname(CMD), exist_ok=True)
    prefs = os.path.join(ROOT, "projects", "studio.json")
    saved_prefs = open(prefs, encoding="utf-8").read() if os.path.exists(prefs) else None
    project = os.path.join(ROOT, "projects", "default", "project.json")
    saved = open(project, encoding="utf-8").read() if os.path.exists(project) else None
    graph = os.path.join(ROOT, "projects", "default", "graphs", "box_fire.json")
    saved_graph = open(graph, encoding="utf-8").read() if os.path.exists(graph) else None
    gdir = os.path.join(ROOT, "projects", "default", "graphs")
    before = set(os.listdir(gdir))
    with open(LOG, "w") as log:
        proc = subprocess.Popen([sys.executable, "-u", "-m", "native.app"], cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
    try:
        time.sleep(9)
        for cmds, wait in STEPS:
            if proc.poll() is not None:
                print("the app exited early"); break
            send(cmds, wait)
    finally:
        proc.kill()
        time.sleep(1)
        if saved is not None:
            open(project, "w", encoding="utf-8").write(saved)
        if saved_graph is not None:
            open(graph, "w", encoding="utf-8").write(saved_graph)
        if saved_prefs is not None:
            open(prefs, "w", encoding="utf-8").write(saved_prefs)
        for f in set(os.listdir(gdir)) - before:
            os.remove(os.path.join(gdir, f))
    text = open(LOG, encoding="utf-8", errors="replace").read()
    lines = [l for l in text.splitlines() if l.startswith(("menu ", "ctx ", "pane "))]
    bad = [l for l in lines if " FAIL" in l or " gone" in l] + [l for l in text.splitlines() if "Traceback" in l]
    ok = sum(1 for l in lines if l.split()[1] == "ok")
    print(f"walk: {ok} ok, {sum(1 for l in lines if l.split()[1] == 'skip')} skipped, {len(bad)} bad ({len(lines)} rows, log {LOG})")
    for l in bad[:30]:
        print("  " + l)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
