"""Drive the running app through its main flows and fail on any traceback.

The app takes commands from a JSON file (native/app.py service_command),
which is how every panel here was checked without a hand on the mouse.
This launches the app, walks the layouts, opens a graph and a code effect,
exercises the editor, segments, A/B, sweep, the script preview, the
dialogs and the keys, then reads the app's log for tracebacks.

    python tests/smoke_app.py          # from studio; ~60 s; exits 1 on a traceback

It is deliberately not a pytest: it needs the window, the engine and a
minute; run it before a release, not on every save.
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
LOG = os.path.join(tempfile.gettempdir(), "cubefx", "smoke.log")

STEPS = [
    ([{"layout": "both"}, {"effect": "Maelstrom"}], 1.5),
    ([{"layout": "graph"}, {"graph_open": "box_fire.json"}, {"graph_zoom": 1.0}, {"key": "Home"}], 1.5),
    ([{"graph_selected": [1, 2]}, {"action": "align_left"}, {"action": "arrange"}, {"graph_undo": True}, {"graph_undo": True}], 1.0),
    ([{"graph_hover": ["out", 1, "value"]}, {"graph_hover": ["node", 9, ""]}], 0.6),
    ([{"gp_call": ["set_focus_mode", [True]]}, {"gp_call": ["set_focus_mode", [False]]}, {"graph_selected": []}], 0.6),
    ([{"script_preview": True}], 3.0),
    ([{"layout": "edit"}, {"open": "box_fire.cpp"}, {"ed_goto": 30}, {"ed_type": "// smoke"}, {"ed_key": ["Return", False, False]},
      {"find": "gc_sat"}, {"action": "find_next"}, {"action": "undo"}, {"action": "undo"}], 1.5),
    ([{"layout": "both"}, {"geometry": {"kind": "matrix", "params": {"w": 32, "h": 16}}}, {"seg": "add"},
      {"seg": {"k": 1, "x0": 8, "y0": 4, "x1": 24, "y1": 12, "opacity": 160, "blend": 10}}, {"seg": "remove"}], 1.5),
    ([{"geometry": {"kind": "cube", "params": {"B": 16}}}, {"compare": "Rainbow"}], 2.0),
    ([{"compare": ""}, {"sweep": ["sx", 3, False, False]}], 3.5),
    ([{"sweep": None}, {"key": "Q"}, {"key": "Q"}, {"key": "E"}, {"key": "E"}, {"key": "W"}, {"key": "W"}], 1.5),
    ([{"chrome": "shortcuts"}, {"chrome": "frames"}, {"chrome": "flash"}, {"feature": ["imu", False]}, {"feature": ["audio", "none"]},
      {"feature": ["imu", True]}, {"feature": ["audio", "pcm"]}, {"chrome": "about"}], 1.0),
    ([{"appearance": {"light": True}}, {"appearance": {"light": False}}], 1.0),
    ([{"gpu": False}, {"gpu": True}, {"gpu_net": False}, {"gpu_net": True}], 1.5),
    ([{"ui": False}, {"ui": True}, {"layout": "graph"}, {"measure": True}], 1.0),
    ([{"layout": "both"}, {"arrangement": [["main", "cube"], ["side"]]}, {"pane_move": ["cube", "side", "top"]},
      {"pane_move": ["side", "main", "left"]}, {"pane_move": ["cube", "main", "centre"]}, {"layout": "graph"},
      {"layout": "edit"}, {"arrangement": [["main"], ["cube"], ["side"]]}], 2.5),
    ([{"graph_open": "gyro_sand.json"}, {"graph_export": None}, {"confirm": 0}, {"feature": ["imu", False]},
      {"graph_import": "projects/default/export/gyro_sand.graph.json"}, {"confirm": 0}, {"export_usermod": True}], 3.0),
    ([{"layout": "both"}, {"popout": ["cube", True]}, {"layout": "graph"}], 5.0),
    ([{"popout": ["net", True]}, {"layout": "both"}], 4.0),
    ([{"popout": ["cube", False]}, {"popout": ["net", False]}], 2.0),
    ([{"section": ["geometry", False]}, {"section": ["audio", "effect", "above"]}, {"section": ["parameters", "live", "below"]},
      {"section": ["geometry", True]}, {"section": "reset"}], 1.5),
    ([{"layout": "graph"}, {"graph_open": "box_fire.json"}, {"action": "select_all"}, {"action": "frame_selected"},
      {"graph_select": [3]}, {"action": "select_up"}, {"action": "select_down"}, {"action": "select_invert"}, {"action": "select_none"},
      {"graph_select": [4]}, {"action": "swap_inputs"}, {"action": "frame_sel"}, {"action": "snap"}, {"action": "snap"},
      {"gp_call": ["set_label", [4, "my node"]]}, {"action": "dissolve"}, {"action": "undo_history"}, {"action": "repeat"},
      {"palette": "sel"}, {"key": "Escape"}, {"graph_zoom": 0.2}, {"action": "frame_all"}, {"graph_zoom": 1.0}, {"graph_undo": True}, {"graph_undo": True}, {"graph_undo": True}, {"graph_undo": True}], 3.0),
]


def send(cmds, wait):
    json.dump(cmds, open(CMD, "w"))
    time.sleep(wait)


def main():
    os.makedirs(os.path.dirname(CMD), exist_ok=True)
    project = os.path.join(ROOT, "projects", "default", "project.json")
    saved = open(project, encoding="utf-8").read() if os.path.exists(project) else None
    graph = os.path.join(ROOT, "projects", "default", "graphs", "box_fire.json")
    saved_graph = open(graph, encoding="utf-8").read() if os.path.exists(graph) else None
    before = set(os.listdir(os.path.join(ROOT, "projects", "default", "graphs")))
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
        for f in set(os.listdir(os.path.join(ROOT, "projects", "default", "graphs"))) - before:
            os.remove(os.path.join(ROOT, "projects", "default", "graphs", f))     # the import's copy
    text = open(LOG, encoding="utf-8", errors="replace").read()
    bad = [l for l in text.splitlines() if "Traceback" in l or "Error:" in l or "command file:" in l]
    if bad:
        print("smoke: FAILED")
        i = text.find("Traceback")
        print(text[i - 200:i + 1500] if i >= 0 else "\n".join(bad[:20]))
        return 1
    print(f"smoke: ok ({len(STEPS)} steps, log {LOG})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
