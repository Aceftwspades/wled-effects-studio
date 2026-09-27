"""Every menu item, every context-menu row, every frame's buttons and
every keymap action, invoked, and the log read for failures.

    python tests/walk_menus.py          # from studio; ~3 min; exits 1 on a FAIL or a traceback

Like smoke_app.py it drives the running app through its JSON command file
(native/app.py service_command): `menu_walk` calls each item of the menu
bar in turn (a few are skipped: Quit, the 15 s recording, fullscreen, and
the ones that hand a path to the desktop), `ctx_walk` each row of a node's,
an input's and an output's context menu with the graph put back after each,
`pane_walk` each row of the panes' right-click menus, `frame_walk` each
button of each frame and window (the sends go to the fake WLED device the
test starts; flashing, rendering, cloning and the desktop are skipped),
`action_walk` each keymap action (toggles twice). Not a pytest: it needs
the window and the engine, and it leaves the last project and layout
wherever the walk ended, so the project it started with is put back.

Each walk prints "walk  done  <kind>" at its end: one that is missing is a
walk the app did not live through, and an app that exits before the steps
are done fails the run with its exit code - a crash leaves no traceback.
The app's remote control is turned on for it (STUDIO_REMOTE_CONTROL=1), in
the private scratch folder (native/scratch.py).
"""
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))                  # the studio's own source: native.scratch
from native import scratch                                 # noqa: E402 - the app's private scratch folder
# STUDIO_EXE: the packaged app's exe to test instead of the tree - its
# folder is then the home (projects/, build/) the test saves and restores
EXE = os.environ.get("STUDIO_EXE")
ROOT = os.path.dirname(os.path.abspath(EXE)) if EXE else os.path.dirname(HERE)
CMD = scratch.path("command.json")
LOG = scratch.path("walk.log")

STEPS = [
    ([{"layout": "graph"}, {"graph_open": "box_fire.json"}, {"graph_select": [3]}, {"menu_walk": True}], 20.0),
    # the menu walk opened every project in turn (File > Project): back to the one the rest walks in
    ([{"project": "default"}, {"layout": "graph"}, {"graph_open": "box_fire.json"}, {"action": "select_none"},
      {"ctx_walk": ["node", 3, None]}], 8.0),
    ([{"graph_open": "box_fire.json"}, {"ctx_walk": ["in", "auto", "a"]}], 6.0),
    ([{"graph_open": "box_fire.json"}, {"ctx_walk": ["out", "auto", "result"]}], 6.0),
    ([{"layout": "both"}, {"pane_walk": True}], 4.0),
    # every frame's buttons, with the fake device as the active one so the sends have somewhere to go
    ([{"frame": "devices"}, {"device": "127.0.0.1:8770"}, {"frame_walk": "devices"}], 6.0),
    ([{"frame_walk": "send"}], 8.0),
    ([{"frame_walk": "flash"}], 4.0),
    ([{"frame_walk": "shape"}], 6.0),
    ([{"frame_walk": "sequence"}], 12.0),
    ([{"frame_walk": "library"}], 6.0),
    ([{"frame_walk": "palettes"}], 6.0),
    ([{"frame_walk": "outputs"}], 6.0),
    ([{"frame_walk": "audioin"}], 6.0),
    ([{"frame_walk": "keys_win"}, {"frame_walk": "appearance_win"}], 4.0),
    ([{"frame_walk": "history_win"}, {"frame_walk": "undo_win"}, {"frame_walk": "about_win"}, {"frame_walk": "usermods_win"}], 4.0),
    ([{"frame_walk": "map_win"}, {"py": "camera_map_ui.stop(app)"}], 4.0),
    ([{"project": "default"}, {"layout": "both"}, {"graph_open": "box_fire.json"}, {"frame_walk": "root"}], 10.0),
    # every keymap action
    ([{"project": "default"}, {"layout": "graph"}, {"graph_open": "box_fire.json"}, {"graph_select": [3]}, {"action_walk": True}], 15.0),
]


def send(cmds, wait):
    """A step's commands, once the app has taken the last step's (a walk of a
    big frame outlasts its wait: written over, the step before would never run)."""
    end = time.time() + 240
    while os.path.exists(CMD) and time.time() < end:
        time.sleep(0.2)
    scratch.write_whole(CMD, json.dumps(cmds))            # whole: the app takes it the moment it is there
    time.sleep(wait)


def expected_walks():
    """The "walk  done" lines the steps should bring: one per walk asked for."""
    out = []
    for cmds, _ in STEPS:
        for c in cmds:
            if "menu_walk" in c:
                out.append("menu")
            if "ctx_walk" in c:
                out.append(f"ctx {c['ctx_walk'][0]}")
            if "pane_walk" in c:
                out.append("pane")
            if "frame_walk" in c:
                out.append(f"frame {c['frame_walk']}")
            if "action_walk" in c:
                out.append("act")
    return out


def main():
    if not scratch.DIR:
        print("walk: no private scratch folder to drive the app through (native/scratch.py)")
        return 1
    prefs = os.path.join(ROOT, "projects", "studio.json")
    saved_prefs = open(prefs, encoding="utf-8").read() if os.path.exists(prefs) else None
    project = os.path.join(ROOT, "projects", "default", "project.json")
    saved = open(project, encoding="utf-8").read() if os.path.exists(project) else None
    graph = os.path.join(ROOT, "projects", "default", "graphs", "box_fire.json")
    saved_graph = open(graph, encoding="utf-8").read() if os.path.exists(graph) else None
    gdir = os.path.join(ROOT, "projects", "default", "graphs")
    before = set(os.listdir(gdir)) if os.path.isdir(gdir) else set()
    caps_before = set(os.listdir(os.path.join(ROOT, "captures"))) if os.path.isdir(os.path.join(ROOT, "captures")) else set()
    from fake_wled import FakeWled
    dev = FakeWled(port=8770, ddp_port=4048).start()      # where the frames' sends go
    with open(LOG, "w") as log:
        # the console variant of the packaged app keeps its stdout, which is the log the test reads
        cmd = [EXE] if EXE else [sys.executable, "-u", "-m", "native.app"]
        env = dict(os.environ, STUDIO_NO_UPDATE_CHECK="1", STUDIO_NO_WELCOME="1", STUDIO_REMOTE_CONTROL="1")
        proc = subprocess.Popen(cmd, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, env=env)
    early = None
    try:
        time.sleep(9 if not EXE else 30)                 # the packaged app unpacks itself first
        for k, (cmds, wait) in enumerate(STEPS):
            if proc.poll() is not None:
                early = f"the app exited early (code {proc.returncode}) before step {k + 1} of {len(STEPS)}"
                print(early); break
            send(cmds, wait)
        if early is None:
            end = time.time() + 60                       # the last walk's rows still coming: its end line, or the app's
            while time.time() < end and proc.poll() is None and "walk  done  act" not in open(LOG, encoding="utf-8", errors="replace").read():
                time.sleep(0.5)
            if proc.poll() is not None:
                early = f"the app exited early (code {proc.returncode}) during the last step"
    finally:
        proc.kill()
        dev.stop()
        time.sleep(1)
        if saved is not None:
            open(project, "w", encoding="utf-8").write(saved)
        if saved_graph is not None:
            open(graph, "w", encoding="utf-8").write(saved_graph)
        if saved_prefs is not None:
            open(prefs, "w", encoding="utf-8").write(saved_prefs)
        for f in (set(os.listdir(gdir)) if os.path.isdir(gdir) else set()) - before:
            os.remove(os.path.join(gdir, f))
        cap = os.path.join(ROOT, "captures")                # the report and the project zip the menu rows made
        for f in (set(os.listdir(cap)) if os.path.isdir(cap) else set()) - caps_before:
            if f.endswith(".zip"):
                os.remove(os.path.join(cap, f))
    text = open(LOG, encoding="utf-8", errors="replace").read()
    lines = [l for l in text.splitlines() if l.startswith(("menu ", "ctx ", "pane ", "frame ", "act ")) and len(l.split()) > 1
             and l.split()[1] in ("ok", "skip", "gone", "off", "FAIL")]
    # a row that was "gone" by the time its turn came is a menu rebuilt by an
    # earlier row (the Add menu's sub-graphs after one was entered), not a
    # failure - an exception would show as a traceback below
    bad = [l for l in lines if " FAIL" in l] + [l for l in text.splitlines() if "Traceback" in l]
    bad += [l for l in text.splitlines() if l.startswith("command ")]          # a step's command that raised: its walk never ran
    if early:
        bad.append(early)
    done = [l.split(None, 2)[2].strip() for l in text.splitlines() if l.startswith("walk  done  ")]
    for want in expected_walks():
        if want in done:
            done.remove(want)
        else:
            bad.append(f"the {want} walk never finished (no 'walk  done  {want}' line)")
    gone = [l for l in lines if " gone" in l]
    if gone:
        print(f"  {len(gone)} row(s) were gone by their turn (a menu rebuilt on the way): " + "; ".join(l.split(None, 2)[2] for l in gone[:4]))
    ok = sum(1 for l in lines if l.split()[1] == "ok")
    print(f"walk: {ok} ok, {sum(1 for l in lines if l.split()[1] == 'skip')} skipped, {len(bad)} bad ({len(lines)} rows, log {LOG})")
    for l in bad[:30]:
        print("  " + l)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
