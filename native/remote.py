"""The studio driven from outside, for the tests: a JSON file of commands (service_command) and a picture of
the window (service_capture), both answered on the main loop's next tick. On only with STUDIO_REMOTE_CONTROL=1,
in a folder of this user's alone (native/scratch.py) - a command runs Python. app.py's main loop calls the two
services; the walkers they drive are native/walk.py."""
import os
import threading
import time

import numpy as np
import dearpygui.dearpygui as dpg

from native import num, typeface, form, messages, scratch
from native import chrome, device_ui, shape_ui, midi_ui, bank_ui, reader_ui, room, weight, view3d, shape_tools, video_ui
from native.geometry import Geometry
from native.walk import _call, process_stats, walk_actions, walk_ctx, walk_frame, walk_menus, write_uiref


# Where a capture is asked for, and where the result is written.
#
# A file rather than a socket or a hotkey because it needs no port, no focus and
# no window manager: anything that can create a file can ask for a frame, and
# the app answers on its next tick. That is also why it is the tests' alone: on
# only with STUDIO_REMOTE_CONTROL=1, in a folder of this user's alone
# (native/scratch.py; GHSA-h8r2-jh8g-f2xh) - a command runs Python.
SHOT_DIR = scratch.DIR
SHOT_REQ = scratch.path("capture.request")
SHOT_PNG = scratch.path("capture.png")
CMD_FILE = scratch.path("command.json")
REMOTE = scratch.remote_control()


def _hook_names(app):
    """What a test hook's line of Python ("py", "check") has in scope."""
    from native import shape_view, shapes, units, shape_gallery, shape_run, shape_fields, shape_checks, shape_start
    from native import camera_map, camera_map_ui
    from native import flash
    from native import library_ui, tutorials
    return {"app": app, "dpg": dpg, "np": np, "flash": flash, "library_ui": library_ui, "tutorials": tutorials, "video_ui": video_ui, "midi_ui": midi_ui, "bank_ui": bank_ui, "reader_ui": reader_ui, "room": room, "chrome": chrome,
            "device_ui": device_ui, "weight": weight, "num": num, "form": form, "typeface": typeface, "messages": messages,
            "view3d": view3d, "shape_ui": shape_ui, "shape_view": shape_view, "shape_tools": shape_tools, "shapes": shapes,
            "units": units, "shape_gallery": shape_gallery, "shape_run": shape_run, "shape_fields": shape_fields,
            "shape_checks": shape_checks, "shape_start": shape_start, "camera_map": camera_map, "camera_map_ui": camera_map_ui}


def service_command(app):
    """Drive the running app from outside, the same way a capture is asked
    for: a JSON file of commands, applied on the next tick and removed.

        [{"geometry": {"kind": "sphere", "params": {"w": 32, "h": 16}}},
         {"effect": "Rainbow"}, {"layout": "edit"}, {"open": "my_effect.cpp"},
         {"code": "...whole file..."}, {"build": true}, {"param": ["sx", 200]}]

    It exists so the app can be tested without a hand on the mouse - every
    panel here was checked by writing this file and reading the capture.
    Off unless STUDIO_REMOTE_CONTROL=1 (REMOTE): the "py" and "check"
    commands run Python, so the file is the tests' alone. A batch that
    starts with {"wait_build": true} waits for a build in hand to be loaded
    (the file is left until then), however long this machine takes.
    """
    if not REMOTE:
        return
    try:
        if not os.path.exists(CMD_FILE):
            return
        import json
        # A file the test is moving in this very moment is locked on Windows
        # (a sharing violation, Errno 13): it is taken next frame. Treated as
        # a broken file it was removed, and a CI run's steps never ran.
        try:
            text = scratch.read_text(CMD_FILE)
        except PermissionError:
            return
        if not text.strip():
            return                                    # still being written: next frame
        cmds = json.loads(text)
        if isinstance(cmds, list) and cmds and isinstance(cmds[0], dict) and cmds[0].get("wait_build") and app.building:
            return                                    # the build first: the batch is taken on a later frame
        try:
            os.remove(CMD_FILE)
        except PermissionError:
            return                                    # held a moment longer: taken next frame - once, when it goes
        # the messages a test may expect: those posted since the last batch began
        # (what it did, the wait after it, and this batch so far)
        app._msg_since, app._msg_batch = getattr(app, "_msg_batch", 0), messages.seq()
    except Exception as e:
        print(f"command file: {e}")
        try:
            os.remove(CMD_FILE)
        except OSError:
            pass
        return
    for c in cmds if isinstance(cmds, list) else [cmds]:
        try:
            if "geometry" in c:
                g = Geometry.from_json(c["geometry"])
                app.apply_geometry(g)
                dpg.set_value("geom_kind", g.kind)
                app.rebuild_geom_fields()
            if "effect" in c:
                if c["effect"] not in app.eng.names:     # the step's other commands would work on the wrong effect
                    raise ValueError(f"no effect named {c['effect']!r} in this build ({app.eng.count} effects)")
                app.on_effect(None, c["effect"])
                dpg.set_value("fx_combo", c["effect"])
            if "palette_run" in c:                      # test hook: the command palette's first row for this text, run
                chrome.show_palette(app); dpg.set_value("palette_text", c["palette_run"])
                chrome._palette_fill(app, c["palette_run"]); chrome.palette_enter(app)
            if c.get("measure"):                        # test hook: print pane and content sizes
                for t in ("root", "toolbar", "net_win", "cube_win", "edit_win", "graph_win", "side_win", "footer", "node_editor"):
                    if dpg.does_item_exist(t):
                        print("measure", t, "pos", dpg.get_item_pos(t), "size", dpg.get_item_rect_size(t),
                              "conf", dpg.get_item_configuration(t).get("height"))
                print("measure prof polls/sim/draw/render ms", [round(x, 1) for x in getattr(app, "_prof_avg", [])])
                print("measure drops", getattr(app.drops, "ok", None), getattr(app.drops, "error", ""))
                print("measure layout", app.layout, "ui", app.ui, "playing", app.playing, "scrub_row", dpg.does_item_exist("scrub_row") and dpg.is_item_shown("scrub_row"), len(app.history_frames))
                print("measure viewport", dpg.get_viewport_client_width(), dpg.get_viewport_client_height(),
                      "footer rect", dpg.get_item_rect_min("footer"), dpg.get_item_rect_max("footer"))
            if "key" in c:                              # test hook: a key press, by mvKey_ name
                if c.get("over") != "panel":            # ... as if over the canvas (the hooks have no pointer)
                    app._canvas_hold = time.time() + 0.5
                else:                                   # ... or on the panel: not where the real pointer happens to be
                    app._panel_hold = time.time() + 0.5
                if c.get("over") == "view":             # ... or on the 3-D view, where its own keys apply
                    app._view_hold = time.time() + 0.5
                app.on_key(None, getattr(dpg, "mvKey_" + c["key"]))
                app._canvas_hold = 0.0
                app._view_hold = 0.0
                app._panel_hold = 0.0
            if "action" in c:                           # test hook: a keymap action by name
                app.run_action(c["action"])
            if "bind" in c:                             # test hook: [action, binding]
                app.keys.set(*c["bind"]); chrome.refresh_keys(app)
            if "state" in c:                            # test hook: print an item's state
                print("state", c["state"], dpg.get_item_state(c["state"]), "pos", dpg.get_item_pos(c["state"]))
                for k in (dpg.get_item_children(c["state"], 1) or [])[:2]:
                    print("  child", dpg.get_item_type(k), dpg.get_item_state(k))
            if "chrome" in c:                           # test hook: a chrome action by name
                {"new": lambda: app.new_effect(), "rename": app.rename_current, "open": lambda: chrome.show_open(app),
                 "device": lambda: chrome.show_device(app), "editor": lambda: chrome.show_editor(app),
                 "shortcuts": lambda: chrome.show_keys(app), "about": lambda: chrome.show_about(app), "snapshots": lambda: chrome.show_snapshots(app),
                 "search": app.search_nodes, "name_ok": lambda: chrome._name_ok(app),
                 "frames": lambda: chrome.show_frames(app), "flash": lambda: chrome.show_flash(app),
                 "usermods": lambda: chrome.show_usermods(app), "devices": lambda: device_ui.show(app, "devices"),
                 "send": lambda: device_ui.show(app, "send"),
                 "flash_start": lambda: chrome.start_flash(app)}[c["chrome"]]()
            if "flash_opts" in c:                       # test hook: {"env":..., "host":..., "build":..., "upload":...}
                o = c["flash_opts"]
                for k, tag in (("env", "flash_env"), ("build", "flash_build"), ("upload", "flash_upload")):
                    if k in o:
                        dpg.set_value(tag, o[k])
                if "host" in o:
                    app.add_device(o["host"]); app.set_active_device(o["host"])
            if "dock" in c:                             # test hook: [slot, True to dock / False to float]
                (app.dock_slot if c["dock"][1] else app.undock_slot)(c["dock"][0])
            if "frame" in c:                            # test hook: show a Device frame by name
                device_ui.show(app, c["frame"])
            if "frame_close" in c:                      # test hook: close one
                device_ui.close(app, c["frame_close"])
            if "wled" in c:                             # test hook: ["fetch", dest] | ["use", folder]
                (lambda op: (dpg.set_value("wled_dest", op[1]), device_ui.fetch_wled(app)) if op[0] == "fetch" else device_ui.use_wled(app, op[1]))(c["wled"])
            if "check" in c:                            # test hook: an expression that must be true (graded as expect is)
                try:
                    v = eval(c["check"], _hook_names(app))
                except Exception as e:
                    v = f"raised {e!r}"
                print(("check ok     " if v is True or (v and not isinstance(v, str)) else "EXPECT FAILED check ") + f"{c['check'][:90]}: {v!r}"[:200])
            if "expect" in c:                           # test hook: [tag, substring] - the value of a text/status item must contain it
                tag, sub = c["expect"]                  # "messages": one posted since the last batch began must
                if tag == "messages":
                    val = " | ".join(e["text"] for e in messages.LOG if e.get("seq", 0) > app._msg_since) or "(no message)"
                else:
                    val = str(dpg.get_value(tag)) if dpg.does_item_exist(tag) else "(no such item)"
                print(("expect ok   " if sub in val else "EXPECT FAILED ") + f"{tag} has {sub!r}: {val[:120]!r}")
            if "report" in c:                           # test hook: Help > Report a problem, the zip's path printed
                chrome.report_problem(app); print("report", getattr(app, "_report_path", ""))
            if "update" in c:                           # test hook: "check" (the dialog when newer), "show", "get"
                {"check": lambda: chrome.check_updates(app, by_hand=True), "show": lambda: chrome.show_update(app),
                 "get": lambda: chrome.get_update(app)}[c["update"]]()
            if "scan" in c:                             # test hook: a device scan ("all" | "sweep" | "mdns")
                app.scan_devices(c["scan"])
            if c.get("randomise"):                      # test hook: throw the sliders and the palette
                app.randomise()
            if "camera" in c:                           # test hook: a camera name, [yaw, pitch, dist], or ["save", slot]
                v = c["camera"]
                app.save_view(v[1]) if isinstance(v, list) and v and v[0] == "save" else app.set_camera(v)
            if "background" in c:                       # test hook: a picture's path, or "" to clear
                app.set_background(c["background"])
            if "audioin" in c:                          # test hook: ["preset", key] | ["read"] | ["send"] | ["meter", bool] | ["pins", [sd, ws, sck, mclk]]
                from native import audioin_ui as AI, audioin as A
                op = c["audioin"]
                if op[0] == "preset": A.apply_preset(A.state(app.project), op[1]); app.project.save(); AI.refresh(app)
                elif op[0] == "read": AI.read_device(app)
                elif op[0] == "send": AI.send(app)
                elif op[0] == "meter": dpg.set_value("ain_meter", bool(op[1])); AI._meter(app, bool(op[1]))
                elif op[0] == "pins": A.state(app.project)["pins"] = list(op[1]); app.project.save(); AI.refresh(app)
            if "outputs" in c:                          # test hook: ["split", "one"|"parts"|"count"] | ["abl", true] | ["limit", mA]
                from native import outputs_ui as OU
                op = c["outputs"]
                if op[0] == "split": OU.do_split(app, op[1])
                elif op[0] == "abl": OU._set(app, "abl_preview", bool(op[1]))
                elif op[0] == "limit": OU._set(app, "max_ma", int(op[1]))
            if "cpal" in c:                             # test hook: ["new"] | ["current"] | ["stop", pos, r, g, b] | ["use"] | ["del"]
                from native import palette_ui as PU
                op = c["cpal"]
                if op[0] == "new": PU.new_palette(app)
                elif op[0] == "current": PU.from_current(app)
                elif op[0] == "use": PU.use_palette(app)
                elif op[0] == "del": PU.del_palette(app)
                elif op[0] == "undo": PU.undo(app)
                elif op[0] == "redo": PU.undo(app, True)
                elif op[0] == "stop":
                    p = PU._pals(app)[PU._sel(app)]; p.setdefault("stops", []).append([int(op[1]), int(op[2]), int(op[3]), int(op[4])])
                    PU._changed(app); PU.refresh(app)
            if "library" in c:                          # test hook: ["previews", seconds, [files]] | ["refresh"]
                from native import library_ui as LU
                op = c["library"]
                if op[0] == "previews": LU.generate_previews(app, op[1] if len(op) > 1 else None, op[2] if len(op) > 2 else None)
                else: LU.refresh(app)
            if "seq" in c:                              # test hook: ["add"] | ["update"] | ["load", i] | ["del", i] | ["play", i?] | ["stop"] | ["field", key, v] | ["seek", t] | ["pause"] | ["dup", i] | ["move", i, j] | ["select", i]
                from native import sequence_ui as SQ
                op = c["seq"]
                {"add": lambda: SQ.add_step(app), "update": lambda: SQ.update_step(app), "load": lambda: SQ.load_step(app, op[1]),
                 "timer": lambda: SQ.add_timer(app, op[1]), "timer_del": lambda: SQ.del_timer(app, op[1]),
                 "snap": lambda: SQ.snap_durations(app, op[1], op[2]), "tap": lambda: SQ.tap(app),
                 "wav_beats": lambda: SQ.beats_from_wav(app), "undo": lambda: SQ.undo(app), "redo": lambda: SQ.undo(app, True),
                 "ramp": lambda: SQ.set_ramp(app, op[1], op[2], op[3] if len(op) > 3 else None),   # [key, end, shape?]
                 "ramp_del": lambda: SQ.remove_ramp(app, op[1]),
                 "del": lambda: SQ.del_step(app, op[1]), "play": lambda: SQ.play(app, *op[1:]), "stop": lambda: SQ.stop(app),
                 "seek": lambda: SQ.seek(app, op[1]), "pause": lambda: SQ.play_pause(app), "dup": lambda: SQ.duplicate_step(app, op[1]),
                 "move": lambda: SQ.move_to(app, op[1], op[2]), "select": lambda: SQ.select(app, op[1]),
                 "field": lambda: SQ.set_field(app, op[1], op[2])}[op[0]]()
            if "stream" in c:                           # test hook: a host to stream to over DDP, or false to stop
                app.stream_start(c["stream"], 30) if c["stream"] else app.stream_stop()
            if "wiring_test" in c:                      # test hook: a wiring test mode, or "off"
                app.wiring_stop() if c["wiring_test"] == "off" else app.wiring_start(c["wiring_test"])
            if "py" in c:                               # test hook: a line of Python with `app` and `dpg` in scope, printed
                try:
                    print("py", repr(eval(c["py"], _hook_names(app))))
                except Exception:
                    import traceback; traceback.print_exc()
            if "shape" in c:                            # test hook: ["add", kind] | ["import", path] | ["place", vx, vy] | ["layout", "grid"] | ["undo"]
                op = c["shape"]
                if op[0] == "add": shape_ui.add_part(app, op[1])
                elif op[0] == "clear": shape_ui._apply(app, parts=[])
                elif op[0] == "segments": shape_ui.segments_per_part(app)
                elif op[0] == "preview": shape_ui.generate_preview(app, op[1] if len(op) > 1 else None, op[2] if len(op) > 2 else None)
                elif op[0] == "xmodel": shape_ui.export_xmodel(app, op[1])
                elif op[0] == "aim": (dpg.set_value("shape_aim_dir", list(op[2]) + [0.0]), dpg.set_value("shape_aim_dist", float(op[3])),
                                      shape_ui.aim_part(app, shape_ui._sel(app), op[1]))      # ["aim", how, [dx, dy, dz], dist]
                elif op[0] == "split": shape_ui.split_polyhedron(app, shape_ui._sel(app))
                elif op[0] == "nudge": (shape_ui.nudge(app, shape_ui._sel(app), **op[1]), shape_ui._poll_pending(app, force=True))
                elif op[0] == "param": shape_ui.set_param(app, shape_ui._sel(app), op[1], op[2])
                elif op[0] == "import": shape_ui.import_file(app, op[1])
                elif op[0] == "reference": app._shape_ref = True; shape_ui.import_file(app, op[1])
                elif op[0] == "layout": shape_ui._apply(app, layout=op[1])
                elif op[0] == "undo": shape_ui.undo(app)
                elif op[0] == "mark": shape_ui.select(app, [int(i) for i in op[1]])     # the selection (it was the list's ticks)
                elif op[0] == "align": shape_ui.align_parts(app, int(op[1]))
                elif op[0] == "spread": shape_ui.distribute_parts(app, int(op[1]))
                elif op[0] == "match": shape_ui.match_parts(app, op[1])
                elif op[0] == "select": shape_ui.select(app, [int(op[1])])
                elif op[0] == "place":
                    app._shape_place = True
                    st = dpg.get_item_state("cube_img"); (x0, y0) = st["rect_min"]
                    shape_ui.click(app, at=(x0 + op[1], y0 + op[2]))
            if "gp_call" in c:                          # test hook: [method of the graph panel, args]
                getattr(app.gp, c["gp_call"][0])(*c["gp_call"][1])
            if c.get("script_preview"):
                app.preview_script()
            if "seg" in c:                              # test hook: "add" | "remove" | k | {"k":..,"x0":..}
                v = c["seg"]
                if v == "add": app.seg_add()
                elif v == "remove": app.seg_remove()
                elif v == "undo": app.seg_undo()
                elif v == "redo": app.seg_undo(True)
                elif isinstance(v, dict):
                    app.eng.seg_config(v["k"], v["x0"], v["y0"], v["x1"], v["y1"], v.get("opacity", 255))
                    if "blend" in v: app.eng.seg_blend(v["k"], v["blend"])
                    app.save_segments(); app.rebuild_seg_fields()
                else: app.seg_pick(f"{int(v)}:")
            if "ed_key" in c:                           # test hook: [key name, ctrl, shift] into the editor
                app.code_ed.focus = True
                app.code_ed.key(getattr(dpg, "mvKey_" + c["ed_key"][0]), bool(c["ed_key"][1]), bool(c["ed_key"][2]))
            if "ed_type" in c:                          # test hook: characters typed into the editor
                app.code_ed.focus = True
                app.code_ed._on_chars(None, c["ed_type"])
            if "ed_goto" in c:
                app.goto_line(int(c["ed_goto"]))
            if "drop" in c:                             # test hook: a path, as if dropped on the window
                app.take_file(c["drop"])
            if "gpu_net" in c:
                app.set_gpu_net(bool(c["gpu_net"]))
            if "gpu" in c:                              # test hook: the GPU cube view on or off
                app.set_gpu_cube(bool(c["gpu"]))
            if "appearance" in c:                       # test hook: {"light": bool, "accent": [r,g,b]}
                app.set_appearance(c["appearance"].get("light"), c["appearance"].get("accent"))
            if "ledmap_file" in c:
                app.import_ledmap(path=c["ledmap_file"])
            if "wiring" in c:
                app.show_wiring = bool(c["wiring"])
            if "sweep" in c:                            # test hook: [key, secs, loop, record] or null to stop
                app.start_sweep(*c["sweep"]) if c["sweep"] else app.stop_sweep()
            if "wav" in c:
                app.start_file_audio(c["wav"])
            if "scrub" in c:
                app.scrub = int(c["scrub"])
            if "compare" in c:                          # test hook: an effect name, or "" to stop
                app.start_ab(c["compare"]) if c["compare"] else app.stop_ab()
            if c.get("compare_before"):                 # test hook: B keeps the build as it is now
                app.start_ab_before()
            if "chrome_call" in c:                      # test hook: [function in chrome, args]
                getattr(chrome, c["chrome_call"][0])(app, *c["chrome_call"][1])
            if "frame_gradient" in c:                   # test hook: [kind, key]
                app.prefs.setdefault("frames", {})[c["frame_gradient"][0]] = c["frame_gradient"][1]
                chrome.apply_frames(app); chrome.refresh_frames(app)
            if "frame_style" in c:                      # test hook: "outline", "gradient" or "turning"
                chrome.set_frame_style(app, c["frame_style"])
            if "name_text" in c:
                dpg.set_value("name_input", c["name_text"])
            if "graph_zoom" in c:                       # test hook: zoom level, optionally about a screen point
                z = c["graph_zoom"]
                app.gp.set_zoom(z[0], tuple(z[1])) if isinstance(z, list) else app.gp.set_zoom(z)
            if "split" in c:                            # test hook: [layout, fraction] or ["side", px]
                k, v = c["split"]
                if k == "side": app.side_w = int(v)
                else: app.splits[k] = float(v)
                app.request_layout()
            if "viewport" in c:                         # test hook: resize the window (fires the resize callback)
                dpg.set_viewport_width(int(c["viewport"][0])); dpg.set_viewport_height(int(c["viewport"][1]))
            if "ui" in c:                               # test hook: H, the presentation toggle
                app.ui = bool(c["ui"]); app.request_layout()
            if "arrangement" in c:                      # test hook: the panes' places
                app.set_arrangement(c["arrangement"])
            if "pane_move" in c:                        # test hook: a grip drop, [slot, target, zone]
                app.move_slot(*c["pane_move"])
            if "section" in c:                          # test hook: [key, open] | [key, target, zone] | "reset"
                v = c["section"]
                if v == "reset":
                    app.sec_reset()
                elif len(v) == 2:
                    app.sec_set(*v)
                else:
                    app.sec_move(*v)
            if "feature" in c:                          # test hook: [key, value] of the feature picker
                app.set_feature(*c["feature"])
            if "usermod" in c:                          # test hook: ["add"|"remove"|"on"|"off"|"import", name or path]
                what, name = c["usermod"]
                {"add": app.add_usermod, "remove": app.remove_usermod, "import": app.import_usermod,
                 "on": lambda n: app.set_usermod(n, True), "off": lambda n: app.set_usermod(n, False)}[what](name)
            if "click" in c and os.name == "nt":        # test hook: a real click at viewport [x, y] (menus need one)
                import ctypes
                u32 = ctypes.windll.user32
                hwnd = u32.FindWindowW(None, "WLED Effects Studio")
                if hwnd:
                    u32.SetForegroundWindow(hwnd)
                    import ctypes.wintypes as wt
                    pt = wt.POINT(0, 0); u32.ClientToScreen(hwnd, ctypes.byref(pt))
                    x, y = int(pt.x + c["click"][0]), int(pt.y + c["click"][1])
                else:
                    vx, vy = dpg.get_viewport_pos()
                    x, y = int(vx + c["click"][0]), int(vy + c["click"][1])
                u32.SetCursorPos(x, y)
                import time as _tm; _tm.sleep(0.1)                                 # a frame of hovering first
                if len(c["click"]) > 2 and c["click"][2] == "right":
                    u32.mouse_event(8, 0, 0, 0, 0); u32.mouse_event(16, 0, 0, 0, 0)
                else:
                    u32.mouse_event(2, 0, 0, 0, 0); u32.mouse_event(4, 0, 0, 0, 0)
                print("click at", x, y, "hwnd", hwnd)
            if "active" in c:                           # test hook: the active window and an item's state
                aw = dpg.get_active_window()
                print("active window", aw, dpg.get_item_alias(aw) if aw and dpg.does_item_exist(aw) else "?",
                      "item", c["active"], dpg.get_item_state(c["active"]) if dpg.does_item_exist(c["active"]) else None)
            if "sec_drag" in c:                         # test hook: [key, x, y] - the grip pressed, dragged to (x, y), released
                key, x, y = c["sec_drag"]
                app._sec_drag = key; app._sec_target = None
                st = dpg.get_item_state(f"sec_{key}")
                if "rect_min" in st:
                    app._ghost_start(st["rect_min"][0], st["rect_min"][1], st["rect_size"][0], st["rect_size"][1], dpg.get_value(f"sec_{key}_title"))
                app._sec_target = app.sec_zone(x, y)
                if not c.get("hold"):
                    app.on_mouse_release(None, None)
            if "sel" in c:                              # test hook: print the selection
                print("SEL clicked", app.gp._clicked(), "ext", app.gp.ext_sel, "picker", app._picker)
            if "combos" in c:                           # test hook: every visible combo's state
                for i in [i for i in dpg.get_all_items() if dpg.get_item_type(i).endswith("::mvCombo")]:
                    st = dpg.get_item_state(i)
                    if st.get("visible"):
                        print("combo", dpg.get_item_alias(i) or i, dpg.get_value(i), st)
            if "device" in c:                           # test hook: the active device's address (listed and chosen)
                app.add_device(c["device"]); app.set_active_device(c["device"])
            if "menu_walk" in c:                        # test hook: every menu item's callback, in turn; failures printed
                walk_menus(app, c["menu_walk"] if isinstance(c["menu_walk"], list) else [])
            if "ctx_walk" in c:                         # test hook: every row of a context menu ["node"|"in"|"out", nid, pin]
                walk_ctx(app, *c["ctx_walk"])
            if "uiref" in c:                            # test hook: the reference section of GUIDE.md written from the live menus, keys and buttons
                print("uiref", write_uiref(app, c["uiref"] if isinstance(c["uiref"], str) else None))
            if "speed" in c:                            # test hook: the playback speed, a factor
                app.set_speed(float(c["speed"]))
            if "stats" in c:                            # test hook: one line of the process - memory, items, frame times (the soak reads it)
                print("stats", json.dumps(process_stats(app)))
            if "items" in c:                            # test hook: Dear PyGui's items counted by type under their nearest named ancestor
                from collections import Counter
                cnt = Counter()
                for i in dpg.get_all_items():
                    p, owner = i, ""
                    for _ in range(12):
                        p = dpg.get_item_parent(p)
                        if not p:
                            break
                        owner = dpg.get_item_alias(p) or ""
                        if owner:
                            break
                    cnt[(dpg.get_item_type(i).split("::")[-1], owner)] += 1
                print("items", json.dumps([[t, o, n] for (t, o), n in cnt.most_common(int(c["items"]) if isinstance(c["items"], int) and c["items"] > 1 else 30)]))
            if "frame_walk" in c:                       # test hook: every button of a frame (or a window, or "root"), clicked
                walk_frame(app, c["frame_walk"])
            if "action_walk" in c:                      # test hook: every keymap action run (toggles twice), the graph put back
                walk_actions(app, c["action_walk"] if isinstance(c["action_walk"], list) else [])
            if "pane_walk" in c:                        # test hook: every row of every pane's right-click menu
                for pane, tag in app.pane_menus.items():
                    for k in dpg.get_item_children(tag, 1) or []:
                        lbl = dpg.get_item_configuration(k).get("label", "")
                        if "Pop out" in lbl or "Record" in lbl or "external" in lbl or "Compile" in lbl:
                            print(f"pane  skip  {pane} > {lbl}"); continue
                        print(f"pane  {_call(k, lbl):5s} {pane} > {lbl}")
                        for w in dpg.get_windows():
                            if dpg.get_item_alias(w) not in ("root", "") and dpg.is_item_shown(w) and dpg.get_item_alias(w).endswith(("_win", "_dialog")):
                                dpg.hide_item(w)
                print("walk  done  pane")
            if "menus" in c:                            # test hook: every menu's state (an open one shows)
                for m in [i for i in dpg.get_all_items() if dpg.get_item_type(i).endswith("::mvMenu")]:
                    st = dpg.get_item_state(m)
                    kids = dpg.get_item_children(m, 1) or []
                    print("menu", dpg.get_item_configuration(m).get("label"), st, "first child", dpg.get_item_state(kids[0]) if kids else None)
            if "tool" in c:                             # test hook: [press|drag|release|right, where, mods] - shape_tools.test_hook
                shape_tools.test_hook(app, c["tool"])
            if "led_at" in c:                           # test hook: [k, "hover"|"leave"|"move"|"click"|"right"|"shift"|"ctrl"|None] - LED k (wiring order) on the 3-D view
                from native import shape_view
                k = int(c["led_at"][0]); how = c["led_at"][1] if len(c["led_at"]) > 1 else None
                v = shape_view.view(app); g = shape_view.drawn(app)
                if v is None or g is None:
                    print("led_at none")
                else:
                    W, owner = shape_view.wiring(g)
                    sx, sy, ok, _ = shape_view.project(v, W[[k]])
                    x, y = int(round(float(sx[0]))), int(round(float(sy[0])))
                    print("led_at", k, x, y, "part", int(owner[k]), "ok", bool(ok[0]))
                    if how in ("hover", "leave"):
                        app._test_pointer = (x, y) if how == "hover" else None   # the pointer's stand-in (shape_view.pointer)
                    elif how and os.name == "nt":
                        import ctypes, ctypes.wintypes as wt, time as _tm
                        u32 = ctypes.windll.user32
                        hwnd = u32.FindWindowW(None, "WLED Effects Studio")
                        pt = wt.POINT(0, 0)
                        if hwnd:
                            u32.SetForegroundWindow(hwnd); u32.ClientToScreen(hwnd, ctypes.byref(pt))
                        u32.SetCursorPos(pt.x + x, pt.y + y)
                        u32.mouse_event(1, 0, 0, 0, 0)              # a real (zero) move: the window hears the pointer arrive
                        print("led_at foreground", u32.GetForegroundWindow() == hwnd)
                        if how != "move":
                            vk = {"shift": 0x10, "ctrl": 0x11}.get(how)

                            def _press(vk=vk, how=how):         # on a thread: a frame of hovering first, the loop drawing
                                _tm.sleep(0.12)
                                if vk:
                                    u32.keybd_event(vk, 0, 0, 0); _tm.sleep(0.05)
                                if how == "right":
                                    u32.mouse_event(8, 0, 0, 0, 0); _tm.sleep(0.05); u32.mouse_event(16, 0, 0, 0, 0)
                                else:
                                    u32.mouse_event(2, 0, 0, 0, 0); _tm.sleep(0.05); u32.mouse_event(4, 0, 0, 0, 0)
                                if vk:
                                    _tm.sleep(0.05); u32.keybd_event(vk, 0, 2, 0)
                            threading.Thread(target=_press, daemon=True).start()
            if "move" in c and os.name == "nt":         # test hook: the real pointer to viewport [x, y], no click
                import ctypes, ctypes.wintypes as wt
                u32 = ctypes.windll.user32
                hwnd = u32.FindWindowW(None, "WLED Effects Studio")
                pt = wt.POINT(0, 0)
                if hwnd:
                    u32.SetForegroundWindow(hwnd); u32.ClientToScreen(hwnd, ctypes.byref(pt))
                u32.SetCursorPos(pt.x + int(c["move"][0]), pt.y + int(c["move"][1]))
            if "pad" in c:                              # test hook: [k, fx, fy] - the k-th XY pad set to a point (0..1 across, 0..1 up)
                pads = list(app.gp._pads)
                k, fx, fy = c["pad"]
                if 0 <= int(k) < len(pads):
                    app.gp._pad_apply(pads[int(k)], float(fx), float(fy)); app.gp._pad_stroke = None
                    print("pad", sorted(app.gp.graph.nodes[app.gp._pads[pads[int(k)]][0]]["inputs"].items()))
            if "drag" in c and os.name == "nt":         # test hook: a real drag [x0, y0, x1, y1, "left"|"middle"]
                import ctypes, ctypes.wintypes as wt, time as _tm
                u32 = ctypes.windll.user32
                hwnd = u32.FindWindowW(None, "WLED Effects Studio")
                pt = wt.POINT(0, 0)
                if hwnd:
                    u32.SetForegroundWindow(hwnd); u32.ClientToScreen(hwnd, ctypes.byref(pt))
                x0, y0, x1, y1 = (int(v) for v in c["drag"][:4])
                down, up = (0x20, 0x40) if (len(c["drag"]) > 4 and c["drag"][4] == "middle") else (2, 4)
                hold = float(c.get("hold") or 0)          # seconds the button stays down at the end, for a capture mid-drag

                def _do(px=pt.x, py=pt.y):                # on a thread: the loop keeps drawing while the mouse moves
                    u32.SetCursorPos(px + x0, py + y0); _tm.sleep(0.15)
                    u32.mouse_event(down, 0, 0, 0, 0); _tm.sleep(0.1)
                    for k in range(1, 21):
                        u32.SetCursorPos(px + x0 + (x1 - x0) * k // 20, py + y0 + (y1 - y0) * k // 20); _tm.sleep(0.03)
                    _tm.sleep(hold)
                    u32.mouse_event(up, 0, 0, 0, 0)
                threading.Thread(target=_do, daemon=True).start()
            if "confirm" in c:                          # test hook: press button k of the open question box
                chrome.confirm_pick(app, int(c["confirm"]))
            if "export_usermod" in c:                   # test hook: with or without the dependencies
                app.export_usermod(bool(c["export_usermod"]))
            if "popout" in c:                           # test hook: [view, on]
                app.set_popout(*c["popout"])
            if "layout" in c:
                app.layout = c["layout"]; app.ui = bool(c.get("with_ui", True)); app.request_layout()
            if "open" in c:
                app.edit_open(c["open"])
            if "new" in c:
                app.edit_new(c["new"])
            if "code" in c:
                dpg.set_value("code", c["code"]); app.on_code_edit(None, c["code"])
            if c.get("build"):
                app.edit_build()
            if "param" in c:
                k, v = c["param"]
                app.eng.fx[k] = int(v); app.eng.push()
                app.rebuild_params()
            if "map1d2d" in c:
                app.on_map1d2d(None, c["map1d2d"]); dpg.set_value("map1d2d", c["map1d2d"])
            if "view" in c:
                app.yaw, app.pitch, app.dist = c["view"]
            if "graph_open" in c:
                app.gp.open(c["graph_open"])
            if "graph_new" in c:
                app.gp.new(c["graph_new"])
            if "graph_add" in c:
                app.gp.add_node(c["graph_add"])
            if "graph_link" in c:
                a, out, b, inp = c["graph_link"]
                app.gp.snapshot(); app.gp.graph.link(a, out, b, inp); app.gp.rebuild()
            if "viewport" in c:                         # test hook: the window's size
                dpg.set_viewport_width(int(c["viewport"][0])); dpg.set_viewport_height(int(c["viewport"][1])); app.request_layout()
            if "graph_pos" in c:                        # test hook: a node's place in graph units
                nid, x, y = c["graph_pos"]
                app.gp._sync_pos(); app.gp.graph.nodes[int(nid)]["pos"] = [float(x), float(y)]; app.gp.rebuild()
            if "graph_input" in c:                      # test hook: an unwired input's typed value
                nid, name, val = c["graph_input"]
                app.gp.snapshot(); app.gp.graph.nodes[int(nid)].setdefault("inputs", {})[name] = val; app.gp.rebuild()
            if "graph_param" in c:
                nid, name, val = c["graph_param"]
                app.gp.snapshot(); app.gp.graph.nodes[int(nid)]["params"][name] = val; app.gp.rebuild()
            if c.get("graph_build"):
                app.gp.compile()
            if "import" in c:                           # test hook: put a file on the effects list
                f = c["import"] or app.edit_file
                if f and not app.project.is_imported(f):
                    app.toggle_import(f)
            if "unimport" in c:
                f = c["unimport"] or app.edit_file
                if f and app.project.is_imported(f):
                    app.toggle_import(f)
            if "rename" in c:
                app.edit_rename(c["rename"])
            if "graph_rename" in c:
                app.gp.rename(c["graph_rename"])
            if "project" in c:
                app.new_project(c["project"])
            if c.get("screenshot"):
                app.shot_req = True
            if "graph_export" in c:                     # test hook: True / False answers the dependencies question
                app.gp.export_bundle(c["graph_export"] if isinstance(c["graph_export"], bool) else None)
            if "graph_import" in c:
                app.gp.import_bundle(c["graph_import"], sure=True)    # the test's own file: not asked
            if "meta" in c:
                for k, v in c["meta"].items():
                    dpg.set_value(k, v)
                app.meta_write()
            if "find" in c:
                dpg.set_value("find_text", c["find"]); app.find()
            if "replace" in c:
                dpg.set_value("replace_text", c["replace"]); app.replace_all()
            if "graph_hover" in c:                      # test hook: help for a pin or node, as hovering would
                kind, nid, name = c["graph_hover"]
                if nid == "auto":                       # the first node that has the pin (a fold and its undo renumber them)
                    side = "inputs" if kind == "in" else "outputs"
                    nid = next(k for k in sorted(app.gp.graph.nodes)
                               if any(x["name"] == name for x in app.gp.graph.node_def(app.gp.graph.nodes[k]).get(side, [])))
                n = app.gp.graph.nodes[int(nid)]; d = app.gp.graph.node_def(n)
                if kind == "node":
                    app.gp.help(f"{d.get('label') or n['type']}: {d.get('doc', '')}")
                    app.gp._help_hold = time.time() + 3.0
                else:
                    app.gp.hover_pin(kind, int(nid), name, hold=3.0)      # a plot beside a frame-scope output, held 3 s
            if "graph_image_convert" in c:
                app.gp.image_to_bitmap(int(c["graph_image_convert"]))
            if "graph_preview" in c:
                if c["graph_preview"]:
                    nid, name = c["graph_preview"]; app.gp.preview_pin(int(nid), name)
                else:
                    app.gp.stop_preview()
            if "graph_toggle" in c:                     # test hook: [node, flag]
                app.gp._toggle(int(c["graph_toggle"][0]), c["graph_toggle"][1])
            if c.get("graph_arrange"):
                app.gp.arrange()
            if "graph_connect" in c:                    # test hook: [a, b] as F would with them selected
                a, b = c["graph_connect"]
                import dearpygui.dearpygui as _d
                _orig = _d.get_selected_nodes
                _d.get_selected_nodes = lambda ed: [f"gnode_{a}", f"gnode_{b}"]
                try:
                    app.gp.connect_selected()
                finally:
                    _d.get_selected_nodes = _orig
            if "palette" in c:                          # test hook: the command palette with this text
                chrome.show_palette(app); dpg.set_value("palette_text", c["palette"]); chrome._palette_fill(app, c["palette"])
            if "graph_select" in c:                     # test hook: the key selection, as A / Ctrl+[ would
                app.gp.set_selection([int(x) for x in c["graph_select"]])
            if "graph_selected" in c:                   # test hook: a selection, held until cleared with []
                app.gp._test_sel = [int(x) for x in c["graph_selected"]] or None
            if "calibrate" in c:                        # test hook: the speed factor measured against the active device
                app.calibrate_factor()
            if "expr" in c:                             # test hook: [nid, name, "input"|"param", text] - an expression into a field
                nid, name, kind, text = c["expr"]
                print("expr", app.gp.apply_expr(int(nid), name, kind, text))
            if "midi" in c:                             # test hook: a MIDI message's bytes, as if the port sent them
                app.midi.inject([int(b) for b in c["midi"]])
            if "osc" in c:                              # test hook: [address, value...] as if a sender sent it
                app.osc.inject(*c["osc"])
            if "midi_learn" in c:                       # test hook: a target to learn next (see midi_ui.targets), or null to cancel
                midi_ui.learn(app, c["midi_learn"])
            if "snap" in c:                             # test hook: ["save", name] | ["apply", name] | ["morph", a, b, t] | ["del", name]
                op = c["snap"]
                if op[0] == "save": app.gp.snapshot_save(op[1])
                elif op[0] == "apply": app.gp.snapshot_apply(op[1])
                elif op[0] == "morph": app.gp.snapshot_apply(op[1], op[2], float(op[3]))
                elif op[0] == "del": app.gp.snapshot_delete(op[1])
            if "paint" in c:                            # test hook: [row, col, digit] painted into the Bitmap node the properties pane shows
                ed = getattr(app.gp, "_bitmap_ed", None)
                if ed:
                    n, rows = app.gp._bitmap_rows(ed["nid"], ed["name"]); r, col, ch = c["paint"]
                    rows[r] = rows[r][:col] + str(ch) + rows[r][col + 1:]; app.gp._bitmap_set(rows, None); app.gp._sync_pos(); app.gp.rebuild()
                    print("paint", app.gp.graph.nodes[ed["nid"]]["params"][ed["name"]])
            if "graph_collapse" in c:
                app.gp._collapse(int(c["graph_collapse"]))
            if "graph_colour" in c:
                nid, col = c["graph_colour"]; app.gp._set_colour(int(nid), col)
            if "graph_insert" in c:
                nid, name, t = c["graph_insert"]; app.gp._insert_before(int(nid), name, t)
            if "graph_move" in c:                       # test hook: move a node (as a drag would)
                nid, x, y = c["graph_move"]; dpg.set_item_pos(f"gnode_{int(nid)}", [x, y])
            if "graph_undo" in c:
                app.gp.undo()
            if "graph_redo" in c:
                app.gp.redo()
            if "graph_copy" in c:
                sel = [int(x) for x in c["graph_copy"]]
                import dearpygui.dearpygui as _d
                _orig = _d.get_selected_nodes
                _d.get_selected_nodes = lambda ed: [f"gnode_{i}" for i in sel if _d.does_item_exist(f"gnode_{i}")]
                try:
                    app.gp.copy()
                finally:
                    _d.get_selected_nodes = _orig
            if "graph_paste" in c:
                app.gp.paste()
            if "graph_auto" in c:
                app.gp.set_auto(bool(c["graph_auto"]))
            if "graph_menu" in c:                       # test hook: the right-click menu at x, y
                app.gp._menu_pos = tuple(c["graph_menu"])
                app.gp._pending = None
                app.gp.show_add_menu(tuple(c["graph_menu"]), focus=False)   # a focused box keeps its own text
            if "graph_search" in c:                     # test hook: type in the add menu's search box
                dpg.set_value("graph_search", c["graph_search"]); app.gp._search(None, c["graph_search"])
            if c.get("graph_search_enter"):
                app.gp._search_enter(None, dpg.get_value("graph_search"))
            if "graph_drop" in c:                       # test hook: a wire from (node, out) dropped at x, y
                nid, out, x, y = c["graph_drop"]
                t = app.gp._ptype.get(app.gp._pins[(int(nid), "out", out)])
                app.gp._menu_pos = (x, y); app.gp._pending = (int(nid), out, t)
                app.gp.show_add_menu((x + 40, y + 120), only=app.gp._consumers(t, limit=60))
            if c.get("graph_menu_hide"):
                dpg.configure_item("graph_menu", show=False); dpg.configure_item("graph_ctx", show=False)
            if "graph_ctx" in c:                        # test hook: context menu for a pin or node
                kind, nid, name, x, y = c["graph_ctx"]
                app.gp._ctx = (kind, int(nid), name); app.gp._fill_ctx_menu()
                dpg.configure_item("graph_ctx", show=True); dpg.set_item_pos("graph_ctx", [x, y])
            if "graph_select" in c:                     # test hook: select nodes by id
                app.gp._test_selection = [int(x) for x in c["graph_select"]]
            if "graph_fold" in c:
                sel = getattr(app.gp, "_test_selection", [])
                import dearpygui.dearpygui as _d
                _orig = _d.get_selected_nodes
                _d.get_selected_nodes = lambda ed: [f"gnode_{i}" for i in sel if _d.does_item_exist(f"gnode_{i}")]
                try:
                    app.gp.make_sub_from_selection(c["graph_fold"])
                finally:
                    _d.get_selected_nodes = _orig
            if "graph_enter" in c:
                app.gp.enter_sub(int(c["graph_enter"]))
            if c.get("graph_back"):
                app.gp.back()
            if "graph_wire" in c:                       # test hook: colour the wire into (node, input)
                nid, name, col = c["graph_wire"]
                app.gp._set_wire([(int(nid), name)], tuple(col) if col else None)
            if c.get("graph_release"):
                app.gp.on_release()
            if "graph_press" in c:                      # test hook: a drag from an output pin type
                app.gp._drag_type = c["graph_press"]
                th = app.gp.themes()
                from native.graph_ui import compatible
                for (nid, kind, name), tag in app.gp._pins.items():
                    if kind == "in":
                        t = app.gp._ptype.get(tag)
                        dpg.bind_item_theme(tag, th.pin[t] if compatible(app.gp._drag_type, t) else th.grey[t])
        except Exception as e:
            import traceback
            where = traceback.extract_tb(e.__traceback__)[-1]
            print(f"command {c}: {type(e).__name__}: {e} (at {os.path.basename(where.filename)}:{where.lineno} in {where.name})")



def service_capture():
    """Write a PNG of THIS APP'S OWN window if one has been asked for.

    dpg.output_frame_buffer hands back the frame Dear PyGui just rendered, so
    what lands in the file is the viewport and nothing else - no other window,
    no desktop, no wallpaper, and nothing at all when the app is not running.
    That scoping is the whole reason it is done this way. The obvious
    alternative, a screen or window grab through the Windows API, photographs
    whatever happens to be in front of it: asked to check this app's theme it
    once returned a locked machine's lock screen instead, which is nobody's
    business and was never the thing being asked for. A frame buffer cannot
    make that mistake, because the app has nothing else to give.

    Must be called from inside the render loop - the buffer does not exist
    outside it.
    """
    if not REMOTE:                          # the tests' too (STUDIO_REMOTE_CONTROL=1): a picture of the window
        return
    try:
        if not os.path.exists(SHOT_REQ):
            return
        os.remove(SHOT_REQ)                 # first, so a failure cannot loop
        dpg.output_frame_buffer(SHOT_PNG)
    except Exception as e:                  # a capture must never kill the app
        print(f"capture failed: {e}")
