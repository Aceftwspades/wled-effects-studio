"""The Sequence frame: steps of the sim's state played in turn, and sent
to the device as presets and a playlist (native/sequence.py).

    build(app)       # the window (device_ui.build calls it)
    refresh(app)     # the steps and the selected one's fields
    poll(app)        # per frame: the next step when its time comes
"""
import json
import os
import time
import dearpygui.dearpygui as dpg

from native import sequence

TAG = "sequence_win"


def _c():
    from native import chrome
    return chrome


def _steps(app):
    return app.project.options.setdefault("sequence", {"steps": [], "base": 10, "pid": 9, "name": "Show", "repeat": 0})


def _save(app):
    app.project.save()
    refresh(app)


def build(app):
    c = _c()
    from native import device_ui
    with dpg.window(tag=TAG, show=False, width=620, height=520, no_collapse=True, no_title_bar=True):
        device_ui.header(app, "sequence")
        dpg.add_text("Steps of what the sim shows, each held for a while: played here, and on the device as presets run by a playlist.",
                     color=c.DIM, wrap=0)
        with dpg.group(horizontal=True):
            dpg.add_button(label="+ Add a step from the sim", callback=lambda: add_step(app))
            dpg.add_button(label="Update the step from the sim", callback=lambda: update_step(app))
            dpg.add_button(label="Load the step into the sim", callback=lambda: load_step(app))
        with dpg.child_window(tag="seq_rows", height=170, border=True):
            pass
        with dpg.group(horizontal=True):
            dpg.add_input_text(tag="seq_name", label="name", width=200, on_enter=True, callback=lambda s, v: set_field(app, "name", v))
            dpg.add_input_float(tag="seq_dur", label="seconds", width=80, step=0, format="%.1f", on_enter=True,
                                callback=lambda s, v: set_field(app, "dur", max(0.1, float(v))))
            dpg.add_input_float(tag="seq_trans", label="transition s", width=80, step=0, format="%.1f", on_enter=True,
                                callback=lambda s, v: set_field(app, "trans", max(0.0, float(v))))
        dpg.add_text("", tag="seq_step_desc", color=c.DIM, wrap=0)
        with dpg.group(horizontal=True):
            dpg.add_button(label="Play in the sim", tag="seq_play", callback=lambda: play(app))
            dpg.add_button(label="Stop", callback=lambda: stop(app))
            dpg.add_checkbox(label="repeat", tag="seq_repeat", default_value=False,
                             callback=lambda s, v: (_steps(app).__setitem__("repeat", 0 if v else 1), app.project.save()))
            dpg.add_text("", tag="seq_status", color=c.TEXT)
        dpg.add_separator()
        dpg.add_text("ON THE DEVICE", color=c.ACCENT)
        with dpg.group(horizontal=True):
            dpg.add_input_int(tag="seq_base", label="first preset id", width=70, default_value=10, min_value=1, max_value=240, min_clamped=True,
                              callback=lambda s, v: (_steps(app).__setitem__("base", int(v)), app.project.save()))
            dpg.add_input_int(tag="seq_pid", label="playlist id", width=70, default_value=9, min_value=1, max_value=250, min_clamped=True,
                              callback=lambda s, v: (_steps(app).__setitem__("pid", int(v)), app.project.save()))
            dpg.add_input_text(tag="seq_show", label="name", width=120, default_value="Show", on_enter=True,
                               callback=lambda s, v: (_steps(app).__setitem__("name", v), app.project.save()))
        with dpg.group(horizontal=True):
            dpg.add_button(label="Send presets + playlist", callback=lambda: send(app))
            dpg.add_button(label="Send and run it", callback=lambda: send(app, run=True))
            dpg.add_button(label="Save presets.json...", callback=lambda: dpg.show_item("seq_save_dialog"))
        dpg.add_text("each step a preset (its id from 'presets from'; ones already there are overwritten), the sequence a playlist preset",
                     color=c.DIM, wrap=0)
        dpg.add_text("", tag="seq_log", color=c.DIM, wrap=0)
    with dpg.file_dialog(directory_selector=False, show=False, tag="seq_save_dialog", width=640, height=420,
                         default_filename="presets.json", callback=lambda s, a: save_file(app, a.get("file_path_name", ""))):
        dpg.add_file_extension(".json", color=(150, 150, 220))


def refresh(app):
    if not dpg.does_item_exist("seq_rows"):
        return
    c = _c()
    S = _steps(app)
    steps = S["steps"]
    sel = min(getattr(app, "_seq_sel", 0), len(steps) - 1)
    dpg.delete_item("seq_rows", children_only=True)
    total = sum(float(s.get("dur", 0)) for s in steps)
    playing = getattr(app, "_seq_play", None)
    for i, st in enumerate(steps):
        fx = ", ".join(sg.get("effect", "?") for sg in st.get("segments") or [])
        with dpg.group(horizontal=True, parent="seq_rows"):
            dpg.add_selectable(label=f"{i + 1:2d}  {st.get('name', '')}", width=180, default_value=(i == sel), user_data=i,
                               callback=lambda s, a, u: (setattr(app, "_seq_sel", u), refresh(app)))
            dpg.add_text(f"{st.get('dur', 0):.1f} s" + (f" +{st.get('trans', 0):.1f}" if st.get("trans") else ""),
                         color=c.ACCENT if playing and playing["i"] == i else c.DIM)
            dpg.add_text(fx[:40] + ("..." if len(fx) > 40 else ""), color=c.TEXT)
            dpg.add_button(label="up", small=True, user_data=i, callback=lambda s, a, u: move_step(app, u, -1), show=i > 0)
            dpg.add_button(label="down", small=True, user_data=i, callback=lambda s, a, u: move_step(app, u, 1), show=i < len(steps) - 1)
            dpg.add_button(label="x", small=True, user_data=i, callback=lambda s, a, u: del_step(app, u))
    if not steps:
        dpg.add_text("no steps yet: set the sim up (effect, sliders, palette, segments) and add a step", parent="seq_rows", color=c.DIM)
    dpg.set_value("seq_base", int(S.get("base", 10))); dpg.set_value("seq_pid", int(S.get("pid", 9)))
    dpg.set_value("seq_show", S.get("name", "Show")); dpg.set_value("seq_repeat", int(S.get("repeat", 0)) == 0)
    if 0 <= sel < len(steps):
        st = steps[sel]
        dpg.set_value("seq_name", st.get("name", "")); dpg.set_value("seq_dur", float(st.get("dur", 10))); dpg.set_value("seq_trans", float(st.get("trans", 0.7)))
        segs = st.get("segments") or []
        dpg.set_value("seq_step_desc", f"step {sel + 1}: {len(segs)} segment(s) - " + "; ".join(
            f"{sg.get('effect', '?')} sx {sg.get('params', {}).get('sx', '?')} ix {sg.get('params', {}).get('ix', '?')} pal {sg.get('pal', '?')}" for sg in segs)
            + f"; bri {st.get('bri', 128)}; {len(steps)} steps, {total:.0f} s in all")
    else:
        dpg.set_value("seq_step_desc", "")


# --- steps -------------------------------------------------------------------------------------
def add_step(app):
    S = _steps(app)
    st = sequence.capture(app.eng, app.seg_cols, int(getattr(app, "bri", 128)), "", 10.0, 0.7)
    S["steps"].append(st)
    app._seq_sel = len(S["steps"]) - 1
    _save(app)
    app.gp.status(f"step {len(S['steps'])} added: {st['name']}")


def update_step(app):
    S = _steps(app)
    i = getattr(app, "_seq_sel", 0)
    if 0 <= i < len(S["steps"]):
        old = S["steps"][i]
        st = sequence.capture(app.eng, app.seg_cols, int(getattr(app, "bri", 128)), old.get("name"), old.get("dur", 10), old.get("trans", 0.7))
        S["steps"][i] = st
        _save(app)


def load_step(app, i=None):
    S = _steps(app)
    i = getattr(app, "_seq_sel", 0) if i is None else i
    if 0 <= i < len(S["steps"]):
        sequence.apply(app.eng, S["steps"][i])
        app.seg_cols = [int(c) for c in S["steps"][i].get("colors") or app.seg_cols]
        dpg.set_value("fx_combo", app.eng.names[app.eng.idx])
        app.rebuild_params(); app.sync_palette_combo(); app.rebuild_seg_fields()
        if getattr(app, "_seq_play", None) is None:
            app.gp.status(f"the sim shows step {i + 1}: {S['steps'][i].get('name')}")


def del_step(app, i):
    S = _steps(app)
    if 0 <= i < len(S["steps"]):
        S["steps"].pop(i)
        app._seq_sel = min(i, len(S["steps"]) - 1)
        _save(app)


def move_step(app, i, d):
    S = _steps(app)
    j = i + d
    if 0 <= i < len(S["steps"]) and 0 <= j < len(S["steps"]):
        S["steps"][i], S["steps"][j] = S["steps"][j], S["steps"][i]
        app._seq_sel = j
        _save(app)


def set_field(app, key, value):
    S = _steps(app)
    i = getattr(app, "_seq_sel", 0)
    if 0 <= i < len(S["steps"]):
        S["steps"][i][key] = value
        _save(app)


# --- playing in the sim --------------------------------------------------------------------
def play(app):
    S = _steps(app)
    if not S["steps"]:
        app.gp.status("no steps to play"); return
    app._seq_play = {"i": -1, "next": 0.0}
    app.playing = True
    poll(app)


def stop(app):
    if getattr(app, "_seq_play", None) is not None:
        app._seq_play = None
        dpg.set_value("seq_status", "")
        app.gp.status("sequence stopped")
        refresh(app)


def poll(app):
    p = getattr(app, "_seq_play", None)
    if p is None:
        return
    S = _steps(app)
    steps = S["steps"]
    if not steps:
        stop(app); return
    now = time.perf_counter()
    if now >= p["next"]:
        i = p["i"] + 1
        if i >= len(steps):
            if int(S.get("repeat", 0)) != 0:
                stop(app); app.gp.status("sequence done"); return
            i = 0
        p["i"] = i
        p["next"] = now + float(steps[i].get("dur", 10))
        app._seq_sel = i
        load_step(app, i)
        refresh(app)
    i = p["i"]
    if 0 <= i < len(steps) and dpg.does_item_exist("seq_status"):
        dpg.set_value("seq_status", f"step {i + 1}/{len(steps)}: {steps[i].get('name')}, {max(0.0, p['next'] - now):.1f} s left")


# --- the device --------------------------------------------------------------------------------
def _resolve(app):
    """(presets, playlist) against the active device's own effect and palette lists."""
    S = _steps(app)
    host = app.active_host()
    from native import devices
    try:
        names = devices._get(host, "/json/effects", 5)
        pals = devices._get(host, "/json/palettes", 5)
    except Exception as e:
        return None, None, f"could not read the device's lists: {e}"
    presets, playlist = sequence.to_wled(S["steps"], names, pals, int(S.get("base", 10)), int(S.get("pid", 9)), S.get("name", "Show"), int(S.get("repeat", 0)))
    return presets, playlist, None


def send(app, run=False):
    from native import device_ui
    S = _steps(app)
    host = app.active_host()
    if not host:
        device_ui.show(app, "devices"); app.gp.status("choose a device first"); return
    if not S["steps"]:
        app.gp.status("no steps to send"); return
    presets, playlist, err = _resolve(app)
    if err:
        dpg.set_value("seq_log", err); return
    ok, msg = sequence.send(host, presets, playlist, int(S.get("pid", 9)))
    if ok and run:
        ok2, msg2 = sequence.start(host, int(S.get("pid", 9)))
        msg += "; " + msg2
    dpg.set_value("seq_log", msg); app.gp.status(msg); device_ui.send_log(app, msg)


def save_file(app, path):
    if not path:
        return
    S = _steps(app)
    presets, playlist, err = _resolve(app) if app.active_host() else (None, None, "no device")
    if err:
        # no device to resolve names against: the sim's own effect list, which matches a device flashed from this project
        names, pals = app.eng.names, list(range(256))
        presets, playlist = sequence.to_wled(S["steps"], names, pals, int(S.get("base", 10)), int(S.get("pid", 9)), S.get("name", "Show"), int(S.get("repeat", 0)))
        note = " (effect ids are the sim's: right for a device flashed from this project)"
    else:
        note = " (effect ids resolved against the device)"
    open(path, "w", encoding="utf-8").write(sequence.presets_file(presets, playlist, int(S.get("pid", 9))))
    app.gp.status(f"presets.json saved to {os.path.basename(path)}" + note)
