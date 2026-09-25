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

from native.typeface import px
from native import num
from native import typeface
from native import form

from native import weight
import numpy as np

from native import sequence, transition

TAG = "sequence_win"


def _c():
    from native import chrome
    return chrome


def _steps(app):
    return app.project.options.setdefault("sequence", {"steps": [], "base": 10, "pid": 9, "name": "Show", "repeat": 0})


def _has_steps(app):
    return bool(_steps(app).get("steps"))


def _has_sel(app):
    return 0 <= getattr(app, "_seq_sel", 0) < len(_steps(app).get("steps") or [])


def _dev_steps(app):
    return bool(app.active_host()) and _has_steps(app)


def _save(app):
    app.project.save()
    refresh(app)


def undo(app, redo=False):
    """The steps or the schedule back a step - whichever changed last (the
    project journals both); Ctrl+Z with the frame focused, or its button."""
    p = app.project
    keys = [k for k in ("sequence", "schedule") if (p.can_redo(k) if redo else p.can_undo(k))]
    if not keys:
        app.gp.status("nothing to " + ("redo" if redo else "undo") + " in the sequence"); return
    key = keys[0] if len(keys) == 1 else max(keys, key=lambda k: getattr(app, "_seq_touched", {}).get(k, 0))
    (p.redo if redo else p.undo)(key)
    app._tl_dirty = True
    refresh(app); refresh_timers(app)
    app.gp.status(f"{'schedule' if key == 'schedule' else 'sequence'}: {'redo' if redo else 'undo'}")


def build(app):
    c = _c()
    from native import device_ui
    with dpg.window(tag=TAG, show=False, width=px(640), height=px(660), no_collapse=True, no_title_bar=True):
        device_ui.header(app, "sequence")
        with dpg.group(horizontal=True):
            typeface.label(dpg.add_text("STEPS", color=c.ACCENT))
            dpg.add_button(label="undo", small=True, callback=lambda: undo(app))
            c.tip("the steps (or the schedule) as they were before the last change; Ctrl+Z here does the same, Ctrl+Y redoes")
            dpg.add_button(label="+ Add from the sim", small=True, callback=lambda: add_step(app))
            c.tip("a new step: what the sim shows now - effect, sliders, palette, colours, segments")
            dpg.add_button(label="Update from the sim", small=True, callback=lambda: update_step(app))
            weight.need(dpg.last_item(), _has_sel)
            c.tip("the selected step becomes what the sim shows now")
            dpg.add_button(label="Load into the sim", small=True, callback=lambda: load_step(app))
            weight.need(dpg.last_item(), _has_sel)
            c.tip("the sim shows the selected step")
            c.info("Steps of what the sim shows, each held for a while: played here, and on the device as presets run by a playlist. "
                   "The timeline under the list: click a step to select it, drag the line between two to retime the one on the left; "
                   "the faint lines are the bpm's bars, the ticks the beats found in the WAV, the wave the WAV itself.")
        with dpg.child_window(tag="seq_rows", height=px(130), border=True):
            pass
        # the timeline: the steps as blocks along the time, the playhead, bars, the WAV
        dpg.add_drawlist(tag="seq_tl", width=px(600), height=px(54))       # its drawing reads its size back
        with dpg.group(horizontal=True) as _row:
            form.inline("name")
            dpg.add_input_text(tag="seq_name", width=px(180), on_enter=True, callback=lambda s, v: set_field(app, "name", v))
            form.inline("held")
            dpg.add_input_float(tag="seq_dur", width=px(80), step=0, format="%.1f s", on_enter=True,
                                callback=lambda s, v: set_field(app, "dur", max(0.1, float(v))))
            c.tip("how long the step is shown")
            form.inline("blend")
            dpg.add_input_float(tag="seq_trans", width=px(80), step=0, format="%.1f s", on_enter=True,
                                callback=lambda s, v: set_field(app, "trans", max(0.0, float(v))))
            c.tip("seconds of blend into this step")
        form.mono_values(_row)
        with dpg.group(horizontal=True):
            dpg.add_text("", tag="seq_step_desc", color=c.DIM)
        with dpg.group(horizontal=True):
            typeface.label(dpg.add_text("RAMP", color=c.ACCENT))
            dpg.add_combo(["none"], tag="seq_ramp_key", width=px(130), default_value="none",
                          callback=lambda s, v: _ramp_pick(app, _ramp_key(app)))
            c.tip("a slider of the first segment that moves over the step, from the step's value to the end value - "
                  "in the sim as it plays; on the device as sub-steps (a second apiece, up to twelve), since a preset cannot move a slider")
            form.inline("to")
            num.add("seq_ramp_end", 128, 0, 255, integer=True, width=px(140),
                    callback=lambda s, v: set_ramp(app, _ramp_key(app), int(v)))
            c.tip("the value the slider reaches at the step's end")
            dpg.add_combo(list(sequence.RAMP_SHAPES), tag="seq_ramp_shape", width=px(110), default_value="linear",
                          callback=lambda s, v: set_ramp(app, _ramp_key(app), None, v))
            c.tip("the ramp's shape: straight, eased at either end or both, up and back to where it began, or a jump half way")
            dpg.add_button(label="x", small=True, callback=lambda: remove_ramp(app, _ramp_key(app)))
            weight.danger(dpg.last_item())
            c.tip("this slider's ramp off (the others stay)")
            dpg.add_text("", tag="seq_ramp_desc", color=c.DIM)
        with dpg.group(horizontal=True):
            typeface.label(dpg.add_text("PLAY", color=c.ACCENT))
            dpg.add_button(label="Play in the sim", tag="seq_play", small=True, callback=lambda: play(app))
            weight.need(dpg.last_item(), _has_steps)
            dpg.add_button(label="Stop", small=True, callback=lambda: stop(app))
            dpg.add_button(label="Render GIF", small=True, callback=lambda: render(app, "gif"))
            weight.need(dpg.last_item(), _has_steps)
            c.tip("plays the sequence once and records it as a GIF, into captures/")
            dpg.add_button(label="Render video", small=True, callback=lambda: render(app, "mp4"))
            weight.need(dpg.last_item(), _has_steps)
            c.tip("plays the sequence once and records it as an mp4, into captures/ - needs ffmpeg on the path")
            dpg.add_checkbox(label="repeat", tag="seq_repeat", default_value=False,
                             callback=lambda s, v: (_steps(app).__setitem__("repeat", 0 if v else 1), app.project.save()))
            form.inline("blend as")
            dpg.add_combo(transition.STYLES, tag="seq_style", width=px(110), default_value="fade",
                          callback=lambda s, v: (_steps(app).__setitem__("style", v), app.project.save()))
            c.tip("the transition's style, previewed here; on the device the transitions use its own blend-style setting")
            dpg.add_text("", tag="seq_status", color=c.TEXT)
        with dpg.group(horizontal=True):
            typeface.label(dpg.add_text("BEATS", color=c.ACCENT))
            typeface.mono(dpg.add_input_float(tag="seq_bpm", width=px(96), step=0, format="%.1f bpm", default_value=120.0,
                                              callback=lambda: setattr(app, "_tl_dirty", True)))
            dpg.add_button(label="Tap", small=True, callback=lambda: tap(app))
            c.tip("tap tempo: tap on the beat, the bpm from the gaps")
            dpg.add_button(label="Synth's", small=True, callback=lambda: dpg.set_value("seq_bpm", float(getattr(app.syn, "bpm", 120))))
            c.tip("the bpm of the sim's synthetic beat")
            dpg.add_button(label="WAV's", small=True, callback=lambda: beats_from_wav(app))
            c.tip("the tempo and the beats found in the WAV playing as live audio (AUDIO > play a WAV file)")
            form.inline("beats a bar")
            typeface.mono(dpg.add_input_int(tag="seq_bar", width=px(40), step=0, default_value=4, min_value=1, max_value=16, min_clamped=True, max_clamped=True,
                                            callback=lambda: setattr(app, "_tl_dirty", True)))
            dpg.add_button(label="Snap durations to bars", small=True, callback=lambda: snap_durations(app))
            weight.need(dpg.last_item(), _has_steps)
            c.tip("every step's seconds rounded to whole bars, so the sequence changes on the music")
            dpg.add_text("", tag="seq_tap", color=c.DIM)
        dpg.add_separator()
        with dpg.group(horizontal=True):
            typeface.label(dpg.add_text("ON THE DEVICE", color=c.ACCENT))
            form.inline("presets from")
            typeface.mono(dpg.add_input_int(tag="seq_base", width=px(50), step=0, default_value=10, min_value=1, max_value=240, min_clamped=True,
                                            callback=lambda s, v: (_steps(app).__setitem__("base", int(v)), app.project.save())))
            c.tip("each step is saved as a preset, ids from here up; ones already there are overwritten")
            form.inline("playlist")
            typeface.mono(dpg.add_input_int(tag="seq_pid", width=px(50), step=0, default_value=9, min_value=1, max_value=250, min_clamped=True,
                                            callback=lambda s, v: (_steps(app).__setitem__("pid", int(v)), app.project.save())))
            c.tip("the preset id the playlist is saved as")
            form.inline("named")
            dpg.add_input_text(tag="seq_show", width=px(110), default_value="Show", on_enter=True,
                               callback=lambda s, v: (_steps(app).__setitem__("name", v), app.project.save()))
        with dpg.group(horizontal=True):
            dpg.add_button(label="Send presets + playlist", tag="seq_send", small=True, callback=lambda: send(app))
            weight.need(dpg.last_item(), _dev_steps)
            c.tip("about a second a preset: the device writes each one from its main loop, and the next is sent once it has")
            dpg.add_button(label="Send and run it", tag="seq_send_run", small=True, callback=lambda: send(app, run=True))
            weight.primary(dpg.last_item())
            weight.need(dpg.last_item(), _dev_steps)
            dpg.add_button(label="Save presets.json...", small=True, callback=lambda: dpg.show_item("seq_save_dialog"))
            weight.need(dpg.last_item(), _has_steps)
            c.tip("the same presets and playlist as a file, for a device that is not on the network")
        dpg.add_text("", tag="seq_log", color=c.DIM, wrap=0)
        dpg.add_separator()
        # SCHEDULE: WLED's timers - a preset at a time of day, sunrise or sunset, on chosen days
        with dpg.group(horizontal=True):
            typeface.label(dpg.add_text("SCHEDULE", color=c.ACCENT))
            dpg.add_button(label="+ run the playlist at", small=True, callback=lambda: add_timer(app, "playlist"))
            dpg.add_button(label="+ off at", small=True, callback=lambda: add_timer(app, "off"))
            c.tip("a time the lights go off: an Off preset (id 250) is saved on the device and timed")
            dpg.add_button(label="Read the device's", small=True, callback=lambda: read_timers(app))
            weight.need(dpg.last_item(), "device")
            dpg.add_button(label="Send the schedule", small=True, callback=lambda: send_timers(app))
            weight.need(dpg.last_item(), "device")
            c.info("The device's timers - eight, plus sunrise and sunset: what preset runs when, on which days. "
                   "The device needs the time (NTP) for them to fire.")
        with dpg.child_window(tag="seq_timers", height=px(120), border=True):
            pass
        dpg.add_text("", tag="seq_tlog", color=c.DIM, wrap=0)
    with dpg.file_dialog(directory_selector=False, show=False, tag="seq_save_dialog", width=px(640), height=px(420),
                         default_filename="presets.json", callback=lambda s, a: save_file(app, a.get("file_path_name", ""))):
        dpg.add_file_extension(".json", color=(150, 150, 220))
    # the selected step's own fields and its ramp: nothing to edit with no step
    for t in ("seq_name", "seq_dur", "seq_trans", "seq_ramp_key", "seq_ramp_end", "seq_ramp_shape"):
        weight.need(t, _has_sel)


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
            dpg.add_selectable(label=f"{i + 1:2d}  {st.get('name', '')}", width=px(180), default_value=(i == sel), user_data=i,
                               callback=lambda s, a, u: (setattr(app, "_seq_sel", u), refresh(app)))
            dpg.add_text(f"{st.get('dur', 0):.1f} s" + (f" +{st.get('trans', 0):.1f}" if st.get("trans") else ""),
                         color=c.ACCENT if playing and playing["i"] == i else c.DIM)
            dpg.add_text(fx[:40] + ("..." if len(fx) > 40 else ""), color=c.TEXT)
            dpg.add_button(label="up", small=True, user_data=i, callback=lambda s, a, u: move_step(app, u, -1), show=i > 0)
            dpg.add_button(label="down", small=True, user_data=i, callback=lambda s, a, u: move_step(app, u, 1), show=i < len(steps) - 1)
            dpg.add_button(label="x", small=True, user_data=i, callback=lambda s, a, u: del_step(app, u))
            weight.danger(dpg.last_item())
    if not steps:
        weight.empty("seq_rows", "No steps yet: a step is what the sim shows now - its effect, sliders, palette and colours.",
                     [("Add what the sim shows", lambda: add_step(app))])
    app._tl_dirty = True
    dpg.set_value("seq_base", int(S.get("base", 10))); dpg.set_value("seq_pid", int(S.get("pid", 9)))
    dpg.set_value("seq_show", S.get("name", "Show")); dpg.set_value("seq_repeat", int(S.get("repeat", 0)) == 0)
    dpg.set_value("seq_style", S.get("style", "fade"))
    if 0 <= sel < len(steps):
        ramps = steps[sel].get("ramps") or {}
        names = app._ramp_names = _ramp_names(app, steps[sel])       # what the picker's names stand for (_ramp_key)
        dpg.configure_item("seq_ramp_key", items=["none"] + [names[k] for k in RAMP_KEYS])
        first = _ramp_key(app) if _ramp_key(app) in ramps else next(iter(ramps), "none")
        dpg.set_value("seq_ramp_key", names.get(first, "none"))
        if first != "none":
            num.set("seq_ramp_end", sequence.ramp_of(steps[sel], first)[0])
            dpg.set_value("seq_ramp_shape", sequence.ramp_of(steps[sel], first)[1])
        _ramp_desc(app, steps[sel])
        st = steps[sel]
        dpg.set_value("seq_name", st.get("name", "")); dpg.set_value("seq_dur", float(st.get("dur", 10))); dpg.set_value("seq_trans", float(st.get("trans", 0.7)))
        segs = st.get("segments") or []
        names = _ramp_names(app, st)                         # the sliders by the effect's own words (C9)
        dpg.set_value("seq_step_desc", f"step {sel + 1}: {len(segs)} segment(s) - " + "; ".join(
            f"{sg.get('effect', '?')}, {names['sx']} {sg.get('params', {}).get('sx', '?')}, {names['ix']} {sg.get('params', {}).get('ix', '?')},"
            f" palette {sg.get('pal', '?')}" for sg in segs)
            + f"; brightness {st.get('bri', 128)}; {len(steps)} steps, {total:.0f} s in all")
    else:
        dpg.set_value("seq_step_desc", "")
    refresh_timers(app)


# --- the schedule: WLED's timers ----------------------------------------------------------------
DAYS = ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"]
WHEN = ["time", "sunrise", "sunset"]


def _timers(app):
    return app.project.options.setdefault("schedule", [])


OFF_PRESET = 250          # the "Off" preset the off timers call: high, out of the steps' way


def add_timer(app, what):
    T = _timers(app)
    if len(T) >= 10:
        app.gp.status("ten timers is what the device holds"); return
    S = _steps(app)
    pid = int(S.get("pid", 9))
    T.append({"en": True, "when": "time", "hour": 18 if what == "playlist" else 23, "min": 0, "dow": 127,
              "preset": pid if what == "playlist" else OFF_PRESET, "what": what})
    app.project.save(); refresh_timers(app)


def refresh_timers(app):
    if not dpg.does_item_exist("seq_timers"):
        return
    c = _c()
    T = _timers(app)
    dpg.delete_item("seq_timers", children_only=True)
    for k, t in enumerate(T):
        cb = lambda s, v, u: _tfield(app, u[0], u[1], v)
        at_time = t.get("when", "time") == "time"
        with dpg.group(horizontal=True, parent="seq_timers") as _row:
            dpg.add_checkbox(default_value=bool(t.get("en", True)), user_data=(k, "en"), callback=cb)
            dpg.add_combo(WHEN, width=px(80), default_value=t.get("when", "time"), user_data=(k, "when"), callback=cb)
            if not at_time:
                form.inline("offset")                    # sunrise or sunset, give or take minutes
            dpg.add_input_int(width=px(40), step=0, default_value=int(t.get("hour", 0)), min_value=0, max_value=23, user_data=(k, "hour"), on_enter=True, callback=cb,
                              show=at_time)
            if at_time:
                dpg.add_text(":", color=c.DIM)
            dpg.add_input_int(width=px(45), step=0, default_value=int(t.get("min", 0)), min_value=-120, max_value=120, user_data=(k, "min"), on_enter=True, callback=cb)
            if not at_time:
                dpg.add_text("min", color=c.DIM)
            form.inline("preset")
            dpg.add_input_int(width=px(45), step=0, default_value=int(t.get("preset", 1)), min_value=0, max_value=250, user_data=(k, "preset"), on_enter=True, callback=cb)
            typeface.small(dpg.add_text("off" if t.get("what") == "off" else ("playlist" if t.get("what") == "playlist" else ""), color=c.DIM))
            # the days as toggles, lit when on: seven checkboxes with their words ran off the frame
            with dpg.group(horizontal=True, horizontal_spacing=px(2)):
                for d in range(7):
                    dpg.add_selectable(label=DAYS[d], width=px(26), default_value=bool(int(t.get("dow", 127)) >> d & 1),
                                       user_data=(k, f"d{d}"), callback=cb)
                    c.tip(("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")[d])
            dpg.add_button(label="x", small=True, user_data=k, callback=lambda s, a, u: del_timer(app, u))
            weight.danger(dpg.last_item())
        form.mono_values(_row)
    if not T:
        weight.empty("seq_timers", "No timers: the device runs the playlist, or goes off, at a time of day.",
                     [("Run the playlist at...", lambda: add_timer(app, "playlist"))], lead=False)


def _tfield(app, k, key, v):
    T = _timers(app)
    if not (0 <= k < len(T)):
        return
    t = T[k]
    if key.startswith("d") and key[1:].isdigit():
        d = int(key[1:]); dow = int(t.get("dow", 127))
        t["dow"] = (dow | (1 << d)) if v else (dow & ~(1 << d))
    elif key in ("hour", "min", "preset"):
        t[key] = int(v)
    elif key == "en":
        t["en"] = bool(v)
    else:
        t[key] = v
    app.project.save(); refresh_timers(app)


def del_timer(app, k):
    T = _timers(app)
    if 0 <= k < len(T):
        T.pop(k); app.project.save(); refresh_timers(app)


def timers_json(T):
    """WLED's timers.ins: hour 255 is sunrise, 254 sunset, with min the offset; dow bits Mon..Sun."""
    ins = []
    for t in T:
        when = t.get("when", "time")
        hour = 255 if when == "sunrise" else (254 if when == "sunset" else int(t.get("hour", 0)))
        ins.append({"en": 1 if t.get("en", True) else 0, "hour": hour, "min": int(t.get("min", 0)), "macro": int(t.get("preset", 0)),
                    "dow": int(t.get("dow", 127)) & 127, "start": {"mon": 1, "day": 1}, "end": {"mon": 12, "day": 31}})
    return {"timers": {"ins": ins}}


def send_timers(app):
    import urllib.request
    from native import device_ui
    host = app.active_host()
    T = _timers(app)
    if not host:
        device_ui.show(app, "devices"); app.gp.status("choose a device first"); return
    h = host if host.startswith("http") else "http://" + host
    # an "off" preset for the off timers, saved as a state that is off. A fixed
    # high id: the playlist's id + 1 used to be it, which is the first step's
    # preset by default (playlist 9, steps from 10) - the off timer then played
    # the first step.
    if any(t.get("what") == "off" for t in T):
        # saving a preset applies its state first, so the device goes dark for
        # the save; it is switched back on after if it was on before
        try:
            was_on = bool(json.loads(urllib.request.urlopen(h + "/json/state", timeout=6).read()).get("on"))
            sequence.psave(h, OFF_PRESET, {"on": False, "n": "Off", "ib": True})   # ib: keep "on" (off) and the brightness in it
            if was_on:
                urllib.request.urlopen(urllib.request.Request(h + "/json/state", data=b'{"on":true}', headers={"Content-Type": "application/json"}), timeout=6).read()
        except Exception as e:
            dpg.set_value("seq_tlog", f"the off preset was refused: {e}"); return
    req = urllib.request.Request(h + "/json/cfg", data=json.dumps(timers_json(T)).encode(), headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=6) as r:
            r.read()
        msg = f"{len(T)} timer(s) sent to {host}" + ("; the off preset saved" if any(t.get("what") == "off" for t in T) else "")
    except Exception as e:
        msg = f"the device refused the timers: {e}"
    dpg.set_value("seq_tlog", msg); app.gp.status(msg); device_ui.send_log(app, msg)


def read_timers(app):
    from native import devices, device_ui
    host = app.active_host()
    if not host:
        device_ui.show(app, "devices"); app.gp.status("choose a device first"); return
    try:
        cfg = devices._get(host, "/json/cfg", 6)
    except Exception as e:
        dpg.set_value("seq_tlog", f"could not read the device's config: {e}"); return
    T = []
    pid = int(_steps(app).get("pid", 9))
    for e in ((cfg.get("timers") or {}).get("ins") or []):
        h = int(e.get("hour", 0)); m = int(e.get("macro", 0))
        T.append({"en": bool(e.get("en", 0)), "when": "sunrise" if h == 255 else ("sunset" if h == 254 else "time"),
                  "hour": 0 if h >= 254 else h, "min": int(e.get("min", 0)), "dow": int(e.get("dow", 127)), "preset": m,
                  "what": "playlist" if m == pid else ("off" if m == OFF_PRESET else "")})     # our own rows recognised
    app.project.options["schedule"] = T
    app.project.save(); refresh_timers(app)
    dpg.set_value("seq_tlog", f"{len(T)} timer(s) read from the device")


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


RAMP_KEYS = ("sx", "ix", "c1", "c2", "c3")
GENERIC = {"sx": "Speed", "ix": "Intensity", "c1": "Custom 1", "c2": "Custom 2", "c3": "Custom 3"}


def _ramp_names(app, step):
    """{key: the slider's name} for the step's first segment's effect - its
    own words where it has them (C9: no keys on screen), two the same told
    apart by the slider's place."""
    segs = step.get("segments") or []
    fx = segs[0].get("effect") if segs else None
    labels = []
    if fx in (app.eng.names or []):
        labels = app.eng.meta[app.eng.names.index(fx)].get("labels") or []
    out, seen = {}, set()
    for i, k in enumerate(RAMP_KEYS):
        lab = (labels[i] if i < len(labels) else "").strip()
        lab = lab if lab and lab != "!" else GENERIC[k]
        if lab in seen or lab == "none":
            lab = f"{lab} ({GENERIC[k]})"
        seen.add(lab); out[k] = lab
    return out


def _ramp_key(app):
    """The key of the slider the RAMP picker shows ("none" for none)."""
    shown = dpg.get_value("seq_ramp_key") if dpg.does_item_exist("seq_ramp_key") else "none"
    return next((k for k, lab in (getattr(app, "_ramp_names", None) or {}).items() if lab == shown), "none")


def _ramp_pick(app, key):
    """The RAMP combo: the key's end value into the slider, or the ramp removed."""
    S = _steps(app); sel = getattr(app, "_seq_sel", 0)
    if not (0 <= sel < len(S["steps"])):
        return
    st = S["steps"][sel]
    ramps = st.get("ramps") or {}
    if key == "none":
        refresh(app); return                                 # the picker back to none: the ramps stay (x removes one)
    if key not in ramps:
        segs = st.get("segments") or []
        ramps[key] = {"end": int((segs[0].get("params") or {}).get(key, 128)) if segs else 128, "shape": "linear"}
        st["ramps"] = ramps; app.project.save()
    end, shape = sequence.ramp_of(st, key)
    num.set("seq_ramp_end", end); dpg.set_value("seq_ramp_shape", shape); refresh(app)


def set_ramp(app, key, end=None, shape=None):
    """A slider's ramp on the selected step: its end value and / or shape."""
    S = _steps(app); sel = getattr(app, "_seq_sel", 0)
    if key == "none" or not (0 <= sel < len(S["steps"])):
        return
    st = S["steps"][sel]
    cur = sequence.ramp_of(st, key) or (int(dpg.get_value("seq_ramp_end")), "linear")
    st.setdefault("ramps", {})[key] = {"end": int(end if end is not None else cur[0]),
                                       "shape": str(shape if shape is not None else cur[1])}
    app.project.save(); _ramp_desc(app, st); app._tl_dirty = True


def remove_ramp(app, key):
    S = _steps(app); sel = getattr(app, "_seq_sel", 0)
    if key == "none" or not (0 <= sel < len(S["steps"])):
        return
    st = S["steps"][sel]
    (st.get("ramps") or {}).pop(key, None)
    if not st.get("ramps"):
        st.pop("ramps", None)
    app.project.save(); app._tl_dirty = True; refresh(app)


def _ramp_desc(app, st):
    ramps = st.get("ramps") or {}
    if not ramps:
        dpg.set_value("seq_ramp_desc", ""); return
    n = len(sequence.sub_steps(st))
    names = _ramp_names(app, st)
    dpg.set_value("seq_ramp_desc", ", ".join(f"{names.get(k, k)} {sequence.ramp_value(st, k, 0)} -> {sequence.ramp_of(st, k)[0]} "
                                             f"{sequence.ramp_of(st, k)[1]}" for k in ramps) + f"; {n} sub-steps on the device")


def load_step(app, i=None):
    S = _steps(app)
    i = getattr(app, "_seq_sel", 0) if i is None else i
    if 0 <= i < len(S["steps"]):
        sequence.apply(app.eng, S["steps"][i])
        app.seg_cols = [int(c) for c in S["steps"][i].get("colors") or app.seg_cols]
        app.refresh_colours()
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


# --- beats: the steps on the music's bars --------------------------------------------------------
def beats_from_wav(app):
    """The bpm and the beat marks from the WAV the sim plays as live audio."""
    from native import audio
    live = getattr(app, "live", None)
    if not isinstance(live, audio.FileAudio):
        app.gp.status("play a WAV file first: AUDIO > play a WAV file..."); return
    got = audio.beats_of(live.samples, live.rate)
    if not got:
        app.gp.status("no beat found in the file"); return
    bpm, first, beats = got
    dpg.set_value("seq_bpm", bpm); app._seq_beats = beats
    dpg.set_value("seq_tap", f"{live.name}: {bpm:.1f} bpm, {len(beats)} beats")
    app.gp.status(f"{bpm:.1f} bpm from {live.name}")


def tap(app):
    """Tap tempo: the bpm from the gaps between taps (the last eight; a pause of two seconds starts over)."""
    now = time.perf_counter()
    taps = getattr(app, "_taps", [])
    if taps and now - taps[-1] > 2.0:
        taps = []
    taps.append(now); taps = taps[-8:]; app._taps = taps
    if len(taps) >= 2:
        bpm = 60.0 * (len(taps) - 1) / (taps[-1] - taps[0])
        dpg.set_value("seq_bpm", round(bpm, 1)); dpg.set_value("seq_tap", f"{len(taps)} taps: {bpm:.1f} bpm")
    else:
        dpg.set_value("seq_tap", "tap again on the beat")


def snap_durations(app, bpm=None, bar=None):
    """Every step's seconds rounded to whole bars of the bpm (a step never
    shorter than one bar), so the sequence changes on the music."""
    S = _steps(app)
    bpm = float(bpm or dpg.get_value("seq_bpm") or 120.0)
    bar = int(bar or dpg.get_value("seq_bar") or 4)
    if bpm <= 0:
        return
    beat = 60.0 / bpm; barlen = beat * bar
    for st in S["steps"]:
        st["dur"] = round(max(barlen, round(float(st.get("dur", 10)) / barlen) * barlen), 3)
    app.project.save(); refresh(app)
    app.gp.status(f"durations on {bar}-beat bars at {bpm:.1f} bpm ({barlen:.2f} s a bar)")


# --- playing in the sim --------------------------------------------------------------------
def play(app):
    S = _steps(app)
    if not S["steps"]:
        app.gp.status("no steps to play"); return
    app._seq_play = {"i": -1, "next": 0.0, "t0": time.perf_counter()}
    app.playing = True
    live = getattr(app, "live", None)
    if live is not None and hasattr(live, "t0"):
        live.t0 = time.perf_counter()                    # the WAV from its start, with the sequence
    poll(app)


def render(app, fmt="gif"):
    """The sequence played once from the top, recorded for its whole length - a GIF or an mp4."""
    S = _steps(app)
    total = sum(float(st.get("dur", 10)) for st in S["steps"])
    if total <= 0:
        app.gp.status("no steps to render"); return
    if getattr(app, "rec", None) is not None:
        app.gp.status("a recording is already going"); return
    if fmt == "mp4" and not app.has_ffmpeg():
        app.gp.status("a video needs ffmpeg on the path - not found"); return
    was = int(S.get("repeat", 0))
    S["repeat"] = 1                                       # once through, then stop
    play(app)
    S["repeat"] = was
    app._seq_play["once"] = True
    app.start_rec(total, fmt)
    app.gp.status(f"rendering {total:.0f} s of the sequence to {fmt}...")


def stop(app):
    app._transition = None
    if getattr(app, "_seq_play", None) is not None:
        app._seq_play = None
        dpg.set_value("seq_status", "")
        app.gp.status("sequence stopped")
        refresh(app)


def poll(app):
    _poll_send(app)
    if dpg.is_item_shown(TAG):
        timeline_mouse(app)
        fw = dpg.get_item_rect_size(TAG)[0]
        if fw and fw != getattr(app, "_tl_frame_w", None):
            app._tl_frame_w = fw; app._tl_dirty = True          # laid out, or resized: the timeline follows
        if getattr(app, "_seq_play", None) is not None or getattr(app, "_tl_dirty", True):
            draw_timeline(app); app._tl_dirty = False
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
            if int(S.get("repeat", 0)) != 0 or p.get("once"):
                stop(app); app.gp.status("sequence done"); return
            i = 0
        prev = steps[p["i"]] if 0 <= p["i"] < len(steps) else None
        p["i"] = i
        p["next"] = now + float(steps[i].get("dur", 10))
        app._seq_sel = i
        if prev is not None and float(steps[i].get("trans", 0)) > 0:
            app.transition_start(prev, float(steps[i]["trans"]), S.get("style", "fade"))
        load_step(app, i)
        refresh(app)
    i = p["i"]
    if 0 <= i < len(steps) and dpg.does_item_exist("seq_status"):
        dpg.set_value("seq_status", f"step {i + 1}/{len(steps)}: {steps[i].get('name')}, {max(0.0, p['next'] - now):.1f} s left")
    if 0 <= i < len(steps) and steps[i].get("ramps"):
        # the ramps: the first segment's sliders move with the time into the step
        dur = float(steps[i].get("dur", 10)) or 1.0
        t = 1.0 - max(0.0, p["next"] - now) / dur
        changed = False
        for k in steps[i]["ramps"]:
            v = sequence.ramp_value(steps[i], k, t)
            if app.eng.seg == 0 and app.eng.fx.get(k) != v:
                app.eng.fx[k] = v; changed = True
                num.set(f"inp_{k}", v)
        if changed:
            app.eng.push()


# --- the timeline ---------------------------------------------------------------------------------
def _tl_geometry(app):
    """(x0, y0, w, h, total seconds, [(start, dur, trans)]) of the timeline, or None."""
    if not dpg.does_item_exist("seq_tl") or not dpg.is_item_shown(TAG):
        return None
    st = dpg.get_item_state("seq_tl")
    cfg = dpg.get_item_configuration("seq_tl")
    # the size it was given, not the one last drawn: drawn before its first
    # layout it measured 0 high, and its text sat above its own top edge
    (x0, y0) = st.get("rect_min") or (0, 0)
    w, h = cfg["width"], cfg["height"]
    steps = _steps(app)["steps"]
    spans, t = [], 0.0
    for s in steps:
        d = float(s.get("dur", 10)); spans.append((t, d, float(s.get("trans", 0)))); t += d
    return x0, y0, w, h, t, spans


def _tl_playhead(app, total):
    """Seconds into the sequence while it plays, else None."""
    p = getattr(app, "_seq_play", None)
    if p is None or p["i"] < 0:
        return None
    steps = _steps(app)["steps"]
    before = sum(float(s.get("dur", 10)) for s in steps[:p["i"]])
    return before + float(steps[p["i"]].get("dur", 10)) - max(0.0, p["next"] - time.perf_counter())


def _wave(app, cols):
    """The WAV's loudness in `cols` columns (0..1 each), cached per file."""
    from native import audio
    live = getattr(app, "live", None)
    if not isinstance(live, audio.FileAudio):
        return None
    key = (id(live), cols)
    if getattr(app, "_wave_key", None) != key:
        n = len(live.samples) // cols
        if n < 1:
            return None
        a = np.abs(live.samples[:n * cols].reshape(cols, n)).mean(1)
        app._wave_key, app._wave = key, a / (a.max() or 1.0)
    return app._wave


def draw_timeline(app):
    """The steps as blocks along the time, the transition into each shaded,
    the selected one outlined; the WAV's wave behind; bar lines at the
    bpm; the beats found in the WAV as ticks; the playhead."""
    g = _tl_geometry(app)
    if g is None:
        return
    x0, y0, w, h, total, spans = g
    c = _c()
    dpg.delete_item("seq_tl", children_only=True)
    if dpg.does_item_exist(TAG):
        # the frame's width as drawn, or as configured before its first
        # layout (then it measures 0, and the timeline came out 200 px)
        fw = dpg.get_item_rect_size(TAG)[0] or dpg.get_item_configuration(TAG)["width"]
        want = max(200, int(fw) - 24)
        if abs(want - w) > 4:
            dpg.configure_item("seq_tl", width=want); w = want
    dpg.draw_rectangle((0, 0), (w, h), color=(0, 0, 0, 0), fill=(0, 0, 0, 60), parent="seq_tl")
    if total <= 0:
        typeface.draw_text((6, h / 2 - px(8)), "the timeline: the steps along the time", px(14), color=c.DIM, parent="seq_tl"); return
    sx = w / total
    # the WAV's wave, over the sequence's time (the WAV plays from 0 when the sequence starts)
    from native import audio
    live = getattr(app, "live", None)
    if isinstance(live, audio.FileAudio) and live.seconds > 0:
        cols = max(50, min(int(w), 600))
        wave = _wave(app, cols)
        if wave is not None:
            span = min(live.seconds, total)                 # only as far as the sequence goes
            n = int(cols * span / live.seconds)
            for k in range(n):
                x = k * (span * sx) / max(1, n)
                a = float(wave[k]) * (h * 0.45)
                dpg.draw_line((x, h / 2 - a), (x, h / 2 + a), color=(120, 140, 170, 70), thickness=1, parent="seq_tl")
    # the bars
    bpm = float(dpg.get_value("seq_bpm") or 0) if dpg.does_item_exist("seq_bpm") else 0
    bar = int(dpg.get_value("seq_bar") or 4) if dpg.does_item_exist("seq_bar") else 4
    if bpm > 0:
        barlen = 60.0 / bpm * bar
        if barlen * sx >= 4:
            t = 0.0
            while t <= total:
                dpg.draw_line((t * sx, 0), (t * sx, h), color=(255, 255, 255, 22), thickness=1, parent="seq_tl"); t += barlen
    for b in getattr(app, "_seq_beats", None) or []:
        if b <= total:
            dpg.draw_line((b * sx, h - 6), (b * sx, h), color=(255, 200, 80, 140), thickness=1, parent="seq_tl")
    # the steps
    sel = min(getattr(app, "_seq_sel", 0), len(spans) - 1)
    for i, (t, d, tr) in enumerate(spans):
        a, b = t * sx, (t + d) * sx
        hue = (i * 47) % 360
        col = _hsv(hue, 0.5, 0.55) + (150,)
        dpg.draw_rectangle((a + 1, 4), (b - 1, h - 10), color=(0, 0, 0, 0), fill=col, parent="seq_tl")
        if tr > 0:
            dpg.draw_rectangle((a + 1, 4), (min(b - 1, (t + tr) * sx), h - 10), color=(0, 0, 0, 0), fill=(255, 255, 255, 40), parent="seq_tl")
        if i == sel:
            dpg.draw_rectangle((a + 1, 4), (b - 1, h - 10), color=c.ACCENT, thickness=1.5, parent="seq_tl")
        name = str(_steps(app)["steps"][i].get("name", ""))
        if b - a > typeface.measure(name[:12], "body", px(14)) + px(10):      # a step's name, in words, where it fits
            typeface.draw_text((a + px(5), px(6)), name[:12], px(14), color=(235, 238, 245, 220), parent="seq_tl")
        st = _steps(app)["steps"][i]
        for j, k in enumerate(st.get("ramps") or {}):
            # the ramp's curve across the block: the slider's 0..255 over the block's lower half
            if b - a < 12:
                break
            top, bot = 4 + (h - 14) * 0.45, h - 12
            pts = [(a + 1 + (b - a - 2) * q / 24, bot - (bot - top) * sequence.ramp_value(st, k, q / 24) / 255.0) for q in range(25)]
            dpg.draw_polyline(pts, color=(255, 255, 255, 200 - 40 * j), thickness=1.5, parent="seq_tl")
            if b - a > 40:
                typeface.draw_text((a + px(5), top - px(13)), _ramp_names(app, st).get(k, k), px(12), color=(235, 238, 245, 160),
                                   parent="seq_tl")
    # the playhead
    at = _tl_playhead(app, total)
    if at is not None:
        dpg.draw_line((at * sx, 0), (at * sx, h), color=(255, 255, 255, 230), thickness=2, parent="seq_tl")
    # the time scale
    typeface.draw_text((2, h - px(14)), "0", px(11), face="mono", color=c.DIM, parent="seq_tl")
    end = f"{total:.0f} s"                           # the time scale's figures, the end right-aligned by its measured width
    typeface.draw_text((w - typeface.measure(end, "mono", px(11)) - 2, h - px(14)), end, px(11), face="mono", color=c.DIM, parent="seq_tl")


def _hsv(h, s, v):
    import colorsys
    r, g, b = colorsys.hsv_to_rgb((h % 360) / 360.0, s, v)
    return (int(r * 255), int(g * 255), int(b * 255))


def timeline_mouse(app):
    """Clicks and drags on the timeline: a click selects the step under the
    pointer; a press within a few pixels of the line between two steps
    picks it up, and the step on its left is retimed as it is dragged."""
    g = _tl_geometry(app)
    if g is None:
        return
    x0, y0, w, h, total, spans = g
    mx, my = dpg.get_mouse_pos(local=False)
    inside = x0 <= mx <= x0 + w and y0 <= my <= y0 + h
    down = dpg.is_mouse_button_down(dpg.mvMouseButton_Left)
    drag = getattr(app, "_tl_drag", None)
    if drag is not None:
        if down:
            t = max(0.0, (mx - x0) / (w / total) if total > 0 else 0.0)
            i, start = drag
            steps = _steps(app)["steps"]
            if 0 <= i < len(steps):
                steps[i]["dur"] = round(max(0.5, t - start), 2)
                draw_timeline(app)
        else:
            app._tl_drag = None
            app.project.save(); refresh(app)
        return
    if not inside or total <= 0:
        app._tl_was_down = down; return
    was = getattr(app, "_tl_was_down", False)
    app._tl_was_down = down
    if down and not was:                                  # a press: a boundary, or a step
        sx = w / total
        for i, (t, d, tr) in enumerate(spans):
            if abs((t + d) * sx - (mx - x0)) <= 5:
                app._tl_drag = (i, t); return
        for i, (t, d, tr) in enumerate(spans):
            if t * sx <= mx - x0 < (t + d) * sx:
                app._seq_sel = i; refresh(app); return


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
    """The steps as presets and a playlist onto the device - on a thread,
    since each preset is waited for (about a second apiece)."""
    import threading
    from native import device_ui
    S = _steps(app)
    host = app.active_host()
    if not host:
        device_ui.show(app, "devices"); app.gp.status("choose a device first"); return
    if not S["steps"]:
        app.gp.status("no steps to send"); return
    if getattr(app, "_seq_send", None) is not None and app._seq_send.is_alive():
        app.gp.status("a send is still going"); return
    presets, playlist, err = _resolve(app)
    if err:
        dpg.set_value("seq_log", err); return
    pid = int(S.get("pid", 9))
    n = sum(1 for k in presets if k is not None)
    dpg.set_value("seq_log", f"sending {n} preset(s) and the playlist to {host}...")
    for t in ("seq_send", "seq_send_run"):
        if dpg.does_item_exist(t):
            dpg.configure_item(t, enabled=False)

    def work():
        try:
            ok, msg = sequence.send(host, presets, playlist, pid)
            if ok and run:
                ok2, msg2 = sequence.start(host, pid)
                msg += "; " + msg2
        except Exception as e:                            # the buttons come back and the log says, whatever went wrong
            msg = f"send failed: {e}"
        app._seq_send_result = msg
    app._seq_send = threading.Thread(target=work, daemon=True); app._seq_send.start()


def _poll_send(app):
    msg = getattr(app, "_seq_send_result", None)
    if msg is None:
        return
    from native import device_ui
    app._seq_send_result = None
    for t in ("seq_send", "seq_send_run"):
        if dpg.does_item_exist(t):
            dpg.configure_item(t, enabled=True)
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
