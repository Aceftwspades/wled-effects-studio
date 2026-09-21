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
sys.path.insert(0, HERE)
# STUDIO_EXE: the packaged app's exe to test instead of the tree - its
# folder is then the home (projects/, build/) the test saves and restores
EXE = os.environ.get("STUDIO_EXE")
ROOT = os.path.dirname(os.path.abspath(EXE)) if EXE else os.path.dirname(HERE)
CMD = os.path.join(tempfile.gettempdir(), "cubefx", "command.json")
LOG = os.path.join(tempfile.gettempdir(), "cubefx", "smoke.log")

STEPS = [
    ([{"layout": "both"}, {"effect": "Maelstrom"}], 1.5),
    # a graph compiled and built: the toolchain works (the bundled one in a packaged run) and box_fire.cpp exists for the code steps
    ([{"layout": "graph"}, {"graph_open": "box_fire.json"}, {"py": "app.gp.compile()"}], 20.0),
    ([{"expect": ["edit_status", "loaded cubefx_"]}, {"graph_zoom": 1.0}, {"key": "Home"}, {"speed": 0.5}], 1.5),
    ([{"expect": ["stat_txt", "speed 1/2x"]}, {"action": "speed_up"}, {"action": "speed_up"}, {"action": "speed_up"}], 1.0),
    ([{"expect": ["stat_txt", "speed 4x"]}, {"action": "speed_reset"}], 0.5),
    # two nodes folded into a sub-graph, entered, and back by the breadcrumb
    ([{"graph_open": "box_fire.json"}, {"graph_selected": [1, 2]}, {"py": "app.gp.make_sub_from_selection('smoke_sub')"},
      {"py": "app.gp.enter_sub(next(i for i, n in app.gp.graph.nodes.items() if n['type'] == 'sub:smoke_sub'))"}], 2.0),
    ([{"expect": ["graph_status", "sub-graph smoke_sub"]}, {"py": "dpg.is_item_shown('graph_crumbs')"}, {"py": "app.gp.back(1)"}], 1.0),
    ([{"expect": ["graph_status", "box_fire.json"]}, {"graph_undo": True}], 0.5),
    ([{"graph_selected": [1, 2]}, {"action": "align_left"}, {"action": "arrange"}, {"graph_undo": True}, {"graph_undo": True}], 1.0),
    ([{"graph_hover": ["out", 1, "value"]}, {"graph_hover": ["node", 9, ""]}], 0.6),
    ([{"gp_call": ["set_focus_mode", [True]]}, {"gp_call": ["set_focus_mode", [False]]}, {"graph_selected": []}], 0.6),
    ([{"script_preview": True}], 3.0),
    ([{"layout": "edit"}, {"open": "box_fire.cpp"}, {"ed_goto": 30}, {"ed_type": "// smoke"}, {"ed_key": ["Return", False, False]},
      {"find": "gc_sat"}, {"action": "find_next"}, {"action": "undo"}, {"action": "undo"}], 1.5),
    ([{"layout": "both"}, {"geometry": {"kind": "matrix", "params": {"w": 32, "h": 16}}}, {"seg": "add"},
      {"seg": {"k": 1, "x0": 8, "y0": 4, "x1": 24, "y1": 12, "opacity": 160, "blend": 10}}, {"seg": "remove"},
      {"seg": "undo"}, {"py": "app.eng.seg_count()"}, {"expect": ["graph_status", "segments: undo"]}, {"seg": "remove"}], 1.5),
    ([{"geometry": {"kind": "cube", "params": {"B": 16}}}, {"compare": "Rainbow"}], 2.0),
    ([{"compare": ""}, {"sweep": ["sx", 3, False, False]}], 3.5),
    ([{"sweep": None}, {"key": "Q"}, {"key": "Q"}, {"key": "E"}, {"key": "E"}, {"key": "W"}, {"key": "W"}], 1.5),
    ([{"chrome": "shortcuts"}, {"chrome": "frames"}, {"chrome": "flash"}, {"feature": ["imu", False]}, {"feature": ["audio", "none"]},
      {"feature": ["imu", True]}, {"feature": ["audio", "pcm"]}, {"chrome": "usermods"}, {"usermod": ["add", "Temperature"]},
      {"usermod": ["off", "Temperature"]}, {"usermod": ["remove", "Temperature"]}, {"chrome": "about"}], 1.0),
    ([{"appearance": {"light": True}}, {"appearance": {"light": False}}], 1.0),
    ([{"gpu": False}, {"gpu": True}, {"gpu_net": False}, {"gpu_net": True}], 1.5),
    ([{"ui": False}, {"ui": True}, {"layout": "graph"}, {"measure": True}, {"randomise": True}], 1.0),
    ([{"layout": "both"}, {"arrangement": [["main", "cube"], ["side"]]}, {"pane_move": ["cube", "side", "top"]},
      {"pane_move": ["side", "main", "left"]}, {"pane_move": ["cube", "main", "centre"]}, {"layout": "graph"},
      {"layout": "edit"}, {"arrangement": [["main"], ["cube"], ["side"]]}], 2.5),
    # the Device frames: floating, docked by the button and by a grip drop, floated again
    ([{"layout": "graph"}, {"frame": "devices"}, {"frame": "send"}, {"frame": "flash"}, {"dock": ["devices", True]},
      {"pane_move": ["send", "cube", "bottom"]}, {"pane_move": ["flash", "side", "top"]}, {"pane_move": ["devices", "main", "right"]},
      {"dock": ["devices", False]}, {"dock": ["send", False]}, {"dock": ["flash", False]},
      {"arrangement": [["main"], ["cube", "props"], ["side"]]}], 3.0),
    # the shape editor: parts added, one placed by a click on the 3-D view, the grid layout, undo, and back to the cube
    ([{"layout": "both"}, {"frame": "shape"}, {"shape": ["clear"]}, {"shape": ["add", "ring"]}, {"shape": ["add", "panel"]},
      {"shape": ["add", "cube"]}, {"shape": ["select", 1]}, {"shape": ["place", 120, 120]}, {"shape": ["layout", "grid"]},
      {"shape": ["layout", "strip"]}, {"shape": ["undo"]}, {"shape": ["segments"]}, {"seg": "remove"}, {"seg": "remove"},
      {"shape": ["preview", "parts", 1]}, {"shape": ["xmodel", "projects/default/export/_smoke.xmodel"]},
      {"dock": ["shape", True]}, {"dock": ["shape", False]},
      {"geometry": {"kind": "cube", "params": {"B": 16}}}], 4.0),
    # live output to the fake device on this machine, and the wiring test
    ([{"frame": "send"}, {"stream": "127.0.0.1"}, {"wiring_test": "chase"}, {"wiring_test": "index"}, {"wiring_test": "part"},
      {"wiring_test": "output"}, {"wiring_test": "white"}, {"wiring_test": "off"}], 4.0),
    ([{"stream": False}], 1.0),
    # every send to a device, against the fake WLED: the script, the settings, the shape, the ledmap
    ([{"frame": "devices"}, {"device": "127.0.0.1:8770"}, {"scan": "all"}], 6.0),
    ([{"layout": "graph"}, {"graph_open": "fan.json"}, {"py": "app.send_script()"}], 6.0),
    ([{"expect": ["send_status", "the device is running it"]}, {"effect": "Rainbow"}, {"py": "app.push_settings()"}], 3.0),
    ([{"expect": ["edit_status", "Rainbow"]}, {"py": "app.send_shape(True)"}, {"py": "app.send_ledmap(True)"}], 4.0),
    ([{"expect": ["edit_status", "ledmap"]}], 0.5),
    # a sequence: two steps from the sim, played, a step loaded back, one deleted
    ([{"frame": "sequence"}, {"effect": "Rainbow"}, {"seq": ["add"]}, {"effect": "Ace 3-D Maelstrom"}, {"seq": ["add"]},
      {"seq": ["field", "dur", 1.0]}, {"seq": ["play"]}], 3.0),
    # the sequence and the schedule sent to the fake: presets, the playlist, the timers with their Off preset
    ([{"seq": ["stop"]}, {"seq": ["load", 0]}, {"seq": ["ramp", "sx", 250]}, {"py": "__import__('native.sequence_ui', fromlist=['x']).send(app, run=True)"}], 22.0),
    ([{"expect": ["seq_log", "saved on the device"]}, {"seq": ["timer", "playlist"]}, {"seq": ["timer", "off"]},
      {"py": "__import__('native.sequence_ui', fromlist=['x']).send_timers(app)"}], 6.0),
    ([{"expect": ["seq_tlog", "timer(s) sent"]}, {"py": "__import__('native.sequence_ui', fromlist=['x']).read_timers(app)"}], 3.0),
    ([{"expect": ["seq_tlog", "read from the device"]}, {"seq": ["del", 1]}, {"seq": ["del", 0]}, {"seq": ["timer_del", 1]}, {"seq": ["timer_del", 0]},
      {"seq": ["tap"]}, {"seq": ["snap", 120.0, 4]}, {"camera": "front"}, {"camera": ["save", 1]}, {"camera": "isometric"}], 1.5),
    # undo in the frames: a deleted step comes back, and goes again on redo
    ([{"py": "len(app.project.options['sequence']['steps'])"}, {"seq": ["undo"]}, {"py": "len(app.project.options['sequence']['steps'])"},
      {"seq": ["redo"]}, {"py": "len(app.project.options['sequence']['steps'])"}, {"expect": ["graph_status", "sequence: redo"]}], 1.0),
    # custom palettes: one made, a stop added, used by the sim, one from the sim's palette, both removed
    ([{"frame": "palettes"}, {"cpal": ["new"]}, {"cpal": ["stop", 64, 0, 0, 255]}, {"cpal": ["use"]}, {"cpal": ["current"]},
      {"py": "__import__('native.palette_ui', fromlist=['x']).send(app, True)"}], 3.0),
    ([{"expect": ["pal_log", "palette(s) sent"]}, {"py": "__import__('native.palette_ui', fromlist=['x']).remove_there(app)"},
      {"cpal": ["del"]}, {"cpal": ["del"]}, {"cpal": ["undo"]}, {"py": "len(app.project.options.get('palettes') or [])"},
      {"expect": ["graph_status", "palettes: undo"]}, {"cpal": ["del"]}], 2.0),
    # LED outputs and power: the wiring split three ways, the limiter previewed and off again, the device's read and sent
    ([{"frame": "outputs"}, {"outputs": ["split", "one"]}, {"outputs": ["split", "count"]}, {"outputs": ["limit", 850]},
      {"outputs": ["abl", True]}, {"outputs": ["abl", False]}, {"outputs": ["limit", 0]},
      {"py": "__import__('native.outputs_ui', fromlist=['x']).read_device(app)"}], 3.0),
    ([{"expect": ["out_log", "output(s) read"]}, {"py": "__import__('native.outputs_ui', fromlist=['x']).send(app)"}], 3.0),
    ([{"expect": ["out_log", "sent"]}], 0.5),
    # the audio input: the device's read, a line-in preset sent (the reboot offered), the meter read
    ([{"frame": "audioin"}, {"audioin": ["read"]}], 2.0),
    ([{"expect": ["ain_log", "audio input read"]}, {"audioin": ["preset", "pcm1808"]}, {"audioin": ["pins", [13, 15, 14, 4]]},
      {"audioin": ["send"]}], 3.0),
    ([{"expect": ["ain_log", "after a reboot"]}, {"py": "dpg.hide_item('confirm_dialog')"}, {"audioin": ["meter", True]}], 2.5),
    ([{"expect": ["ain_source", "I2S digital"]}, {"audioin": ["meter", False]}, {"audioin": ["preset", "inmp441"]}], 1.0),
    # sad paths: a wire between types that do not convert, a graph with no output, a C++ effect that does not
    # compile, a device that is off - a status line each, never a traceback
    ([{"layout": "graph"}, {"py": "app.gp.new('sad_smoke')"},
      {"py": "app.gp.graph.links.append((next(i for i, n in app.gp.graph.nodes.items() if n['type'] == 'Speed'), 'value', "
             "next(i for i, n in app.gp.graph.nodes.items() if n['type'] == 'Output'), 'color'))"}, {"py": "app.gp.compile()"}], 3.0),
    ([{"expect": ["graph_status", "cannot take a float"]},
      {"py": "[app.gp._delete_node(i) for i, n in list(app.gp.graph.nodes.items()) if n['type'] == 'Output']"}, {"py": "app.gp.compile()"}], 3.0),
    ([{"expect": ["graph_status", "exactly one Output"]}, {"graph_open": "box_fire.json"}, {"py": "app.gp.compile(False)"},
      {"layout": "edit"}, {"open": "box_fire.cpp"}, {"ed_goto": 30},
      {"ed_type": "this is not C++ ;"}, {"ed_key": ["Return", False, False]}, {"py": "app.edit_build()"}], 12.0),
    ([{"expect": ["edit_status", "problem"]}, {"action": "undo"}, {"action": "undo"}, {"layout": "graph"}, {"graph_open": "fan.json"},
      {"device": "127.0.0.1:1"}, {"py": "app.send_script()"}], 8.0),
    ([{"expect": ["graph_status", "failed"]}, {"device": "127.0.0.1:8770"}], 1.0),
    # a problem report bundled, the project zipped (both land in captures/; the test removes them)
    ([{"report": True}, {"py": "app.export_project_zip()"}, {"expect": ["edit_status", "project zipped"]}], 3.0),
    # the library: thumbnails made for the graphs, the frame docked and floated
    ([{"frame": "library"}, {"dock": ["library", True]}, {"dock": ["library", False]}], 5.0),
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
    gdir = os.path.join(ROOT, "projects", "default", "graphs")
    sdir = os.path.join(ROOT, "projects", "default", "subgraphs")
    subs_before = set(os.listdir(sdir)) if os.path.isdir(sdir) else set()
    caps_before = set(os.listdir(os.path.join(ROOT, "captures"))) if os.path.isdir(os.path.join(ROOT, "captures")) else set()
    before = set(os.listdir(gdir)) if os.path.isdir(gdir) else set()      # a first run makes the project
    STUDIO_FILE = os.path.join(ROOT, "projects", "studio.json")   # the prefs: a saved view would otherwise stay
    saved_prefs = open(STUDIO_FILE, encoding="utf-8").read() if os.path.exists(STUDIO_FILE) else None
    from fake_wled import FakeWled                          # the device every send goes to, and the DDP receiver
    ddp = FakeWled(port=8770, ddp_port=4048).start()
    with open(LOG, "w") as log:
        # the console variant of the packaged app keeps its stdout, which is the log the test reads
        cmd = [EXE] if EXE else [sys.executable, "-u", "-m", "native.app"]
        env = dict(os.environ, STUDIO_NO_UPDATE_CHECK="1")
        proc = subprocess.Popen(cmd, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, env=env)
    try:
        time.sleep(9 if not EXE else 30)                 # the packaged app unpacks itself first
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
            open(STUDIO_FILE, "w", encoding="utf-8").write(saved_prefs)
        for f in (set(os.listdir(gdir)) if os.path.isdir(gdir) else set()) - before:
            if before:                                                         # a project made by this run keeps its examples
                os.remove(os.path.join(gdir, f))                               # the import's copy
    text = open(LOG, encoding="utf-8", errors="replace").read()
    ddp.stop()
    print(f"ddp: {ddp.ddp_packets} packets, {ddp.ddp_frames} frames received from the stream; "
          f"the fake got {len(ddp.files)} file(s), {len(ddp.presets) - 1} preset(s), {len(ddp.cfg['timers']['ins'])} timer(s)")
    bad = [l for l in text.splitlines() if "Traceback" in l or "Error:" in l or "command file:" in l]
    if "remote control" not in text:
        bad.append("the app's output was not captured (no 'remote control' line): a buffered stdout, or the wrong exe")
    if ddp.ddp_frames < 10:
        bad.append(f"the DDP stream sent {ddp.ddp_frames} frames; 10 or more expected")
    bad += [l for l in text.splitlines() if "EXPECT FAILED" in l]
    rep = next((l.split(None, 1)[1].strip() for l in text.splitlines() if l.startswith("report ")), "")
    if not rep or not os.path.exists(rep):
        bad.append("Help > Report a problem made no zip")
    else:
        import zipfile
        names = zipfile.ZipFile(rep).namelist()
        for want in ("version.json", "doctor.txt", "machine.json", "project.json", "README.txt"):
            if want not in names:
                bad.append(f"the report zip lacks {want}")
        os.remove(rep)
    for f in (set(os.listdir(sdir)) if os.path.isdir(sdir) else set()) - subs_before:
        os.remove(os.path.join(sdir, f))                        # the sub-graph the fold made
    for f in (set(os.listdir(os.path.join(ROOT, "captures"))) if os.path.isdir(os.path.join(ROOT, "captures")) else set()) - caps_before:
        if f.endswith(".zip"):                                  # the project zip the run made
            os.remove(os.path.join(ROOT, "captures", f))
    for name in ("/studio.bin", "/ledmap.json", "/geometry.bin"):
        if name not in ddp.files:
            bad.append(f"the fake device never received {name}")
    if bad:
        print("smoke: FAILED")
        i = text.find("Traceback")
        print(text[i - 200:i + 1500] if i >= 0 else "\n".join(bad[:20]))
        return 1
    print(f"smoke: ok ({len(STEPS)} steps, log {LOG})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
