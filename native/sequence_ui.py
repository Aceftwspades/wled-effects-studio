"""The Sequence frame: steps of the sim's state played in turn, and sent
to the device as presets and a playlist (native/sequence.py).

    build(app)       # the window (device_ui.build calls it)
    refresh(app)     # the steps and the selected one's fields
    poll(app)        # per frame: the next step when its time comes
    key(app, code)   # Space, Delete, Ctrl+D while the frame has the keyboard
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
ROW_H = 30               # a step's row in the list, at the interface size
TL_H = 104               # the timeline's height
RULER_H = 18             # its time ruler, along the top
BEAT_LANE = 9            # the beats' ticks, along the bottom
LOOK_SPAN = 1.5          # seconds of a step's frames its look is read from (an effect's colours over a moment, not one frame)
LOOK_EVERY = 0.12        # a frame taken for it this often


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


def _fmt_t(t):
    """Seconds as a clock: 0:07, 1:32 (tenths under ten seconds while playing)."""
    t = max(0.0, float(t))
    return f"{int(t // 60)}:{int(t % 60):02d}"


def _barlen(app):
    """A bar's seconds at the sequence's tempo, or None with no tempo."""
    S = _steps(app)
    bpm, bar = float(S.get("bpm") or 0), int(S.get("bar") or 4)
    return 60.0 / bpm * bar if bpm > 0 else None


def _beat(app):
    S = _steps(app)
    bpm = float(S.get("bpm") or 0)
    return 60.0 / bpm if bpm > 0 else None


def _bars_words(app, dur):
    """ "4 bars" (or "2.5 bars") for a duration, at the tempo; "" with none."""
    bl = _barlen(app)
    if not bl:
        return ""
    n = float(dur) / bl
    return f"{n:g} bar" + ("" if abs(n - 1) < 1e-6 else "s") if abs(n - round(n)) < 1e-3 else f"{n:.1f} bars"


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


def _icon_button(tag, icon, tip, callback, size=16):
    from native.icons import texture
    b = dpg.add_image_button(texture(icon, px(size)), tag=tag, width=px(size), height=px(size), callback=callback)
    _c().tip(tip, item=b)
    return b


def build(app):
    c = _c()
    from native import device_ui
    with dpg.window(tag=TAG, show=False, width=px(660), height=px(720), no_collapse=True, no_title_bar=True):
        device_ui.header(app, "sequence")
        # the transport: from the top, play / pause, stop, loop - and where the show is
        with dpg.group(horizontal=True):
            _icon_button("seq_to_start", "to_start", "play from the top", lambda: play(app, 0))
            weight.need("seq_to_start", _has_steps)
            _icon_button("seq_play", "play", "play from the selected step (Space while the frame has the keyboard); "
                         "playing, it pauses and goes on", lambda: play_pause(app))
            weight.need("seq_play", _has_steps)
            _icon_button("seq_stop", "stop", "stop: the sim goes back to running on its own", lambda: stop(app))
            dpg.add_checkbox(label="loop", tag="seq_repeat", default_value=True,
                             callback=lambda s, v: (_steps(app).__setitem__("repeat", 0 if v else 1), app.project.save()))
            c.tip("round again from the first step after the last - on the device too (its playlist repeats)")
            typeface.mono(dpg.add_text("0:00 / 0:00", tag="seq_pos", color=c.TEXT))
            dpg.add_text("", tag="seq_status", color=c.DIM)
        with dpg.group(horizontal=True):
            typeface.label(dpg.add_text("STEPS", color=c.ACCENT))
            dpg.add_button(label="+ Add from the sim", small=True, callback=lambda: add_step(app))
            weight.primary(dpg.last_item())
            c.tip("a new step after the selected one: what the sim shows now - effect, sliders, palette, colours, segments")
            dpg.add_button(label="undo", small=True, callback=lambda: undo(app))
            c.tip("the steps (or the schedule) as they were before the last change; Ctrl+Z here does the same, Ctrl+Y redoes")
            dpg.add_text("", tag="seq_total", color=c.DIM)
            c.info("Steps of what the sim shows, each held for a while: played here, and on the device as presets run by a "
                   "playlist. On the timeline: click the ruler to go to a time, click a step to select it, drag a step to "
                   "move it, drag the line after a step to make it longer or shorter (on the beats when a tempo is set; "
                   "Alt: free), drag the little handle at a step's start for its blend. Double-click a step to show it in "
                   "the sim, right-click for more. In the list, drag a row by its name to move it. With the frame's "
                   "keyboard: Space plays and pauses, Delete removes the selected step, Ctrl+D duplicates it.")
        # the timeline: the steps as blocks of their own colours along the time, the ruler, bars, beats, the WAV
        dpg.add_drawlist(tag="seq_tl", width=px(600), height=px(TL_H))       # its drawing reads its size back
        with dpg.child_window(tag="seq_rows", height=px(ROW_H * 4 + 12), border=True):
            pass
        # the selected step (hidden while there are none: blank fields to nothing)
        dpg.add_group(tag="seq_step_card")
        dpg.push_container_stack("seq_step_card")
        with dpg.group(horizontal=True):
            typeface.label(dpg.add_text("STEP", tag="seq_step_title", color=c.ACCENT))
            dpg.add_button(label="Update from the sim", small=True, callback=lambda: update_step(app))
            weight.need(dpg.last_item(), _has_sel)
            c.tip("the selected step becomes what the sim shows now (its name, length, blend and ramps kept)")
            dpg.add_button(label="Load into the sim", small=True, callback=lambda: load_step(app))
            weight.need(dpg.last_item(), _has_sel)
            c.tip("the sim shows the selected step (double-click it on the timeline does the same)")
            dpg.add_button(label="Duplicate", small=True, callback=lambda: duplicate_step(app))
            weight.need(dpg.last_item(), _has_sel)
            c.tip("a copy of the selected step, after it (Ctrl+D)")
            dpg.add_button(label="Delete", small=True, callback=lambda: del_step(app, getattr(app, "_seq_sel", 0)))
            weight.danger(dpg.last_item())
            weight.need(dpg.last_item(), _has_sel)
            c.tip("the selected step away (Delete); undo brings it back")
        with dpg.group(horizontal=True) as _row:
            form.inline("name")
            dpg.add_input_text(tag="seq_name", width=px(170), on_enter=True, callback=lambda s, v: set_field(app, "name", v))
            form.inline("held")
            dpg.add_input_float(tag="seq_dur", width=px(76), step=0, format="%.1f s", on_enter=True,
                                callback=lambda s, v: set_field(app, "dur", max(0.1, float(v))))
            c.tip("how long the step is shown, seconds")
            dpg.add_input_float(tag="seq_dur_bars", width=px(80), step=0, format="%g bars", on_enter=True, show=False,
                                callback=lambda s, v: set_bars(app, v))
            c.tip("how long the step is shown, in bars of the tempo (BEATS below)")
            form.inline("blend")
            dpg.add_input_float(tag="seq_trans", width=px(70), step=0, format="%.1f s", on_enter=True,
                                callback=lambda s, v: set_field(app, "trans", max(0.0, float(v))))
            c.tip("seconds of blend into this step (drag the handle at the step's start on the timeline)")
        form.mono_values(_row)
        with dpg.group(horizontal=True):
            form.inline("brightness")
            num.add("seq_bri", 255, 0, 255, integer=True, width=px(200), callback=lambda s, v: set_field(app, "bri", int(v)))
            c.tip("the step's brightness: its preset sets the device's, and the sim shows it so while the sequence plays")
        dpg.add_text("", tag="seq_step_desc", color=c.DIM, wrap=0)
        # the step's ramps: each a slider (or the brightness) moving over the step
        with dpg.group(horizontal=True):
            typeface.label(dpg.add_text("RAMPS", color=c.ACCENT))
            dpg.add_combo([], tag="seq_ramp_add", width=px(170), default_value="+ a ramp...",
                          callback=lambda s, v: add_ramp(app, v))
            c.tip("a slider of a segment, or the brightness, moving over the step from its value to an end value - in "
                  "the sim as it plays; on the device as sub-steps (about a second apiece, up to twelve), since a preset "
                  "cannot move a slider")
            dpg.add_text("", tag="seq_ramp_desc", color=c.DIM)
        dpg.add_group(tag="seq_ramps")
        dpg.pop_container_stack()
        # the tempo: bars on the timeline, lengths in bars, drags on the beats
        with dpg.group(horizontal=True):
            typeface.label(dpg.add_text("BEATS", color=c.ACCENT))
            typeface.mono(dpg.add_input_float(tag="seq_bpm", width=px(96), step=0, format="%.1f bpm", default_value=0.0,
                                              on_enter=True, callback=lambda s, v: set_tempo(app, bpm=v)))
            c.tip("the tempo the steps are laid on: bars on the timeline, lengths in bars, drags on the beats (0: none)")
            dpg.add_button(label="Tap", small=True, callback=lambda: tap(app))
            c.tip("tap tempo: tap on the beat, the bpm from the gaps")
            dpg.add_button(label="Synth's", small=True, callback=lambda: set_tempo(app, bpm=float(getattr(app.syn, "bpm", 120))))
            c.tip("the bpm of the sim's synthetic beat")
            dpg.add_button(label="the file's", small=True, callback=lambda: beats_from_wav(app))
            c.tip("the tempo and the beats found in the audio file playing as live audio (AUDIO > play an audio file)")
            form.inline("beats a bar")
            typeface.mono(dpg.add_input_int(tag="seq_bar", width=px(40), step=0, default_value=4, min_value=1, max_value=16, min_clamped=True,
                                            max_clamped=True, on_enter=True, callback=lambda s, v: set_tempo(app, bar=v)))
        with dpg.group(horizontal=True):
            dpg.add_button(label="Snap lengths to bars", small=True, callback=lambda: snap_durations(app))
            weight.need(dpg.last_item(), lambda a: _has_steps(a) and bool(_barlen(a)))
            c.tip("every step's length rounded to whole bars, so the sequence changes on the music")
            dpg.add_checkbox(label="drags on the beats", tag="seq_snap", default_value=True,
                             callback=lambda s, v: (_steps(app).__setitem__("snap", bool(v)), app.project.save()))
            c.tip("a step's end dragged on the timeline lands on a beat (hold Alt for anywhere)")
            form.inline("blend as")
            dpg.add_combo(transition.STYLES, tag="seq_style", width=px(110), default_value="fade",
                          callback=lambda s, v: (_steps(app).__setitem__("style", v), app.project.save()))
            c.tip("the transition's style, previewed here; on the device the transitions use its own blend-style setting")
            dpg.add_text("", tag="seq_tap", color=c.DIM)
        with dpg.group(horizontal=True):
            dpg.add_button(label="Render GIF", small=True, callback=lambda: render(app, "gif"))
            weight.need(dpg.last_item(), _has_steps)
            c.tip("plays the sequence once from the top and records it as a GIF, into captures/")
            dpg.add_button(label="Render video", small=True, callback=lambda: render(app, "mp4"))
            weight.need(dpg.last_item(), _has_steps)
            c.tip("plays the sequence once from the top and records it as an mp4, into captures/ - needs ffmpeg on the path")
        dpg.add_separator()
        with dpg.group(horizontal=True):
            typeface.label(dpg.add_text("ON THE DEVICE", color=c.ACCENT))
            form.inline("presets from")
            typeface.mono(dpg.add_input_int(tag="seq_base", width=px(50), step=0, default_value=10, min_value=1, max_value=240, min_clamped=True,
                                            callback=lambda s, v: (_steps(app).__setitem__("base", int(v)), _save(app))))
            c.tip("each step is saved as a preset, ids from here up; ones already there are overwritten")
            form.inline("playlist")
            typeface.mono(dpg.add_input_int(tag="seq_pid", width=px(50), step=0, default_value=9, min_value=1, max_value=250, min_clamped=True,
                                            callback=lambda s, v: (_steps(app).__setitem__("pid", int(v)), _save(app))))
            c.tip("the preset id the playlist is saved as")
            form.inline("named")
            dpg.add_input_text(tag="seq_show", width=px(110), default_value="Show", on_enter=True,
                               callback=lambda s, v: (_steps(app).__setitem__("name", v), _save(app)))
        with dpg.group(horizontal=True):
            dpg.add_button(label="Send and run it", tag="seq_send_run", small=True, callback=lambda: send(app, run=True))
            weight.primary(dpg.last_item())
            weight.need(dpg.last_item(), _dev_steps)
            dpg.add_button(label="Send presets + playlist", tag="seq_send", small=True, callback=lambda: send(app))
            weight.need(dpg.last_item(), _dev_steps)
            c.tip("about a second a preset: the device writes each one from its main loop, and the next is sent once it has")
            dpg.add_button(label="Save presets.json...", small=True, callback=lambda: dpg.show_item("seq_save_dialog"))
            weight.need(dpg.last_item(), _has_steps)
            c.tip("the same presets and playlist as a file, for a device that is not on the network")
        dpg.add_text("", tag="seq_sent", color=c.DIM, wrap=0)
        dpg.add_text("", tag="seq_log", color=c.DIM, wrap=0)
        # SCHEDULE: WLED's timers - a preset at a time of day, sunrise or sunset, on chosen days
        with dpg.collapsing_header(label="SCHEDULE", tag="seq_sched_head", default_open=False):
            with dpg.group(horizontal=True):
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
    # the timeline's right-click menu
    with dpg.window(tag="seq_ctx", show=False, popup=True, no_title_bar=True, autosize=True):
        pass
    # the selected step's own fields: nothing to edit with no step
    for t in ("seq_name", "seq_dur", "seq_dur_bars", "seq_trans", "seq_bri", "seq_ramp_add"):
        weight.need(t, _has_sel)


# --- the list ----------------------------------------------------------------------------------
def _swatch(parent, st, w, h):
    """A step's look as a strip of its colours (hatched while it has none yet)."""
    cols = sequence.look_colours(st)
    with dpg.drawlist(width=w, height=h, parent=parent) as dl:
        if cols:
            n = len(cols)
            for k, col in enumerate(cols):
                dpg.draw_rectangle((w * k / n, 0), (w * (k + 1) / n + 1, h), color=(0, 0, 0, 0), fill=tuple(col) + (255,))
        else:
            dpg.draw_rectangle((0, 0), (w, h), color=(0, 0, 0, 0), fill=(60, 64, 74, 255))
            for x in range(-h, w, 6):
                dpg.draw_line((x, h), (x + h, 0), color=(90, 96, 110, 255), thickness=1)
        dpg.draw_rectangle((0, 0), (w, h), color=(0, 0, 0, 120), fill=(0, 0, 0, 0))
    return dl


def refresh(app):
    if not dpg.does_item_exist("seq_rows"):
        return
    c = _c()
    from native.icons import texture
    S = _steps(app)
    steps = S["steps"]
    sel = min(getattr(app, "_seq_sel", 0), len(steps) - 1)
    app._seq_sel = max(0, sel)
    dpg.delete_item("seq_rows", children_only=True)
    total = sum(float(s.get("dur", 0)) for s in steps)
    playing = _play_i(app)
    # the name's column: what the frame's width leaves after the fixed ones (and the list's padding and scrollbar)
    fw = dpg.get_item_rect_size(TAG)[0] or dpg.get_item_configuration(TAG)["width"]
    name_w = max(px(60), int(fw) - px(16 + 52 + 110 + 118 + 48) - px(90))
    if steps:
        with dpg.table(parent="seq_rows", header_row=False, policy=dpg.mvTable_SizingFixedFit, borders_innerH=False,
                       pad_outerX=False, no_host_extendX=True):
            dpg.add_table_column(width_fixed=True, init_width_or_weight=px(16))      # playing / the drag hint
            dpg.add_table_column(width_fixed=True, init_width_or_weight=px(52))      # the look
            dpg.add_table_column(width_stretch=True, init_width_or_weight=1.0)       # the name
            dpg.add_table_column(width_fixed=True, init_width_or_weight=px(110))     # the effect
            dpg.add_table_column(width_fixed=True, init_width_or_weight=px(118))     # the length
            dpg.add_table_column(width_fixed=True, init_width_or_weight=px(48))      # duplicate, delete
            for i, st in enumerate(steps):
                fx = ", ".join(sg.get("effect", "?") for sg in st.get("segments") or [])
                with dpg.table_row(height=px(ROW_H - 6)):
                    # the one playing in the accent (an icon here set its row's words off their line)
                    dpg.add_text(f"{i + 1}", color=c.ACCENT if i == playing else c.DIM)
                    with dpg.group():                                # level with the row's words
                        dpg.add_spacer(height=px(2))
                        _swatch(dpg.last_container(), st, px(48), px(16))
                    s_ = dpg.add_selectable(label=_c()._fit_text(str(st.get("name", "")), name_w), default_value=(i == sel),
                                            user_data=i, payload_type="seq_step",
                                            callback=lambda s, a, u: select(app, u),
                                            # the row dropped on is the sender (the user_data does not come
                                            # with a drop under the studio's own callback loop)
                                            drop_callback=lambda s, a, u: move_to(app, a, dpg.get_item_user_data(s)))
                    with dpg.drag_payload(parent=s_, drag_data=i, payload_type="seq_step"):
                        dpg.add_text(f"move {st.get('name', '')}")
                    t_ = dpg.add_text(_c()._fit_text(fx, px(106)), color=c.TEXT if i != playing else c.ACCENT)
                    if len(st.get("segments") or []) > 1:
                        c.tip(fx, item=t_)
                    words = f"{float(st.get('dur', 0)):.1f} s"
                    bw = _bars_words(app, st.get("dur", 0))
                    if bw:
                        words += f"  {bw}"
                    typeface.mono(dpg.add_text(words, color=c.DIM))
                    with dpg.group(horizontal=True, horizontal_spacing=px(4)):
                        b = dpg.add_image_button(texture("duplicate", px(13)), width=px(13), height=px(13), user_data=i,
                                                 callback=lambda s, a, u: duplicate_step(app, u))
                        c.tip("a copy of this step, after it", item=b)
                        b = dpg.add_image_button(texture("trash", px(13)), width=px(13), height=px(13), user_data=i,
                                                 callback=lambda s, a, u: del_step(app, u))
                        weight.danger(b)
                        c.tip("this step away (undo brings it back)", item=b)
    else:
        weight.empty("seq_rows", "No steps yet: a step is what the sim shows now - its effect, sliders, palette and colours.",
                     [("Add what the sim shows", lambda: add_step(app))])
    # the list as tall as its steps, four to eight rows
    dpg.configure_item("seq_rows", height=px(ROW_H * max(3, min(8, len(steps))) + 20))    # the cells' padding: no scrollbar for 8 px
    app._tl_dirty = True
    dpg.set_value("seq_total", f"{len(steps)} step{'s' if len(steps) != 1 else ''}, {_fmt_t(total)}" if steps else "")
    dpg.set_value("seq_base", int(S.get("base", 10))); dpg.set_value("seq_pid", int(S.get("pid", 9)))
    dpg.set_value("seq_show", S.get("name", "Show")); dpg.set_value("seq_repeat", int(S.get("repeat", 0)) == 0)
    dpg.set_value("seq_style", S.get("style", "fade"))
    dpg.set_value("seq_bpm", float(S.get("bpm") or 0)); dpg.set_value("seq_bar", int(S.get("bar") or 4))
    dpg.set_value("seq_snap", bool(S.get("snap", True)))
    has_tempo = bool(_barlen(app))
    dpg.configure_item("seq_step_card", show=bool(steps))
    dpg.configure_item("seq_dur_bars", show=has_tempo)
    if 0 <= sel < len(steps):
        st = steps[sel]
        dpg.set_value("seq_step_title", f"STEP {sel + 1}")
        dpg.set_value("seq_name", st.get("name", "")); dpg.set_value("seq_dur", float(st.get("dur", 10)))
        dpg.set_value("seq_trans", float(st.get("trans", 0.7)))
        if has_tempo:
            dpg.set_value("seq_dur_bars", round(float(st.get("dur", 10)) / _barlen(app), 2))
        num.set("seq_bri", int(st.get("bri", 255)))
        segs = st.get("segments") or []
        words = [_slider_words(app, sg.get("effect")) for sg in segs]    # each segment's sliders by its effect's words (C9)
        dpg.set_value("seq_step_desc", f"{len(segs)} segment(s): " + "; ".join(
            f"{sg.get('effect', '?')}, {w['sx']} {sg.get('params', {}).get('sx', '?')}, {w['ix']} {sg.get('params', {}).get('ix', '?')},"
            f" palette {sg.get('pal', '?')}" for sg, w in zip(segs, words)))
        refresh_ramps(app, st)
    else:
        dpg.set_value("seq_step_title", "STEP")
        dpg.set_value("seq_step_desc", "")
        dpg.delete_item("seq_ramps", children_only=True)
        dpg.set_value("seq_ramp_desc", "")
    refresh_sent(app)
    refresh_timers(app)


def select(app, i):
    app._seq_sel = int(i)
    refresh(app)


# --- the ramps ---------------------------------------------------------------------------------
def refresh_ramps(app, st):
    """The selected step's ramps, a row each: what moves, from where to where, how; and the picker of one more."""
    c = _c()
    dpg.delete_item("seq_ramps", children_only=True)
    names = app._ramp_names = _ramp_names(app, st)
    ramps = st.get("ramps") or {}
    free = [lab for k, lab in names.items() if k not in ramps]
    dpg.configure_item("seq_ramp_add", items=free)
    dpg.set_value("seq_ramp_add", "+ a ramp...")
    for k in ramps:
        end, shape = sequence.ramp_of(st, k)
        with dpg.group(horizontal=True, parent="seq_ramps"):
            dpg.add_text(_c()._fit_text(names.get(k, k), px(150)), color=c.TEXT)
            typeface.mono(dpg.add_text(f"{sequence.ramp_value(st, k, 0):>3} ->", color=c.DIM))
            num.add(f"seq_ramp_end_{k}", end, 0, 255, integer=True, width=px(140), user_data=k,
                    callback=lambda s, v, u: set_ramp(app, u, int(v)))
            dpg.add_combo(list(sequence.RAMP_SHAPES), width=px(110), default_value=shape, user_data=k,
                          callback=lambda s, v, u: set_ramp(app, u, None, v))
            c.tip("the ramp's shape: straight, eased at either end or both, up and back to where it began, or a jump half way")
            b = dpg.add_button(label="x", small=True, user_data=k, callback=lambda s, a, u: remove_ramp(app, u))
            weight.danger(b)
            c.tip("this ramp off (the others stay)", item=b)
    _ramp_desc(app, st)


def add_ramp(app, label):
    """A ramp on the selected step for the slider (or the brightness) the picker names, ending where it starts."""
    S = _steps(app); sel = getattr(app, "_seq_sel", 0)
    if not (0 <= sel < len(S["steps"])):
        return
    st = S["steps"][sel]
    key = next((k for k, lab in (getattr(app, "_ramp_names", None) or {}).items() if lab == label), None)
    if key is None:
        return
    st.setdefault("ramps", {})[key] = {"end": sequence.ramp_value(st, key, 0), "shape": "linear"}
    app.project.save(); app._tl_dirty = True; refresh(app)


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
                    dpg.add_selectable(label=DAYS[d], width=px(24), default_value=bool(int(t.get("dow", 127)) >> d & 1),
                                       user_data=(k, f"d{d}"), callback=cb)
                    c.tip(("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")[d])
            dpg.add_button(label="x", small=True, user_data=k, callback=lambda s, a, u: del_timer(app, u))
            weight.danger(dpg.last_item())
        form.mono_values(_row)
    if not T:
        weight.empty("seq_timers", "No timers: the device runs the playlist, or goes off, at a time of day.",
                     [("Run the playlist at...", lambda: add_timer(app, "playlist"))], lead=False)
    if dpg.does_item_exist("seq_sched_head"):                # how many, on the header that folds it away
        dpg.configure_item("seq_sched_head", label=f"SCHEDULE - {len(T)} timer{'s' if len(T) != 1 else ''}" if T else "SCHEDULE")


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


# --- the steps ---------------------------------------------------------------------------------
def _undimmed(app):
    """The sim's frame as the effect draws it (a playing step's brightness aside): a step's look."""
    try:
        return app._frame_rgb_inner(app.eng)
    except Exception:
        return app.frame_rgb()


def add_step(app):
    """What the sim shows now, as a new step after the selected one (at the end with none)."""
    S = _steps(app)
    st = sequence.capture(app.eng, app.seg_cols, 255, "", 10.0, 0.7, rgb=_undimmed(app))
    at = getattr(app, "_seq_sel", -1) + 1 if S["steps"] else 0
    at = max(0, min(len(S["steps"]), at))
    S["steps"].insert(at, st)
    app._seq_sel = at
    _gather_look(app, st)
    _save(app)
    app.gp.status(f"step {at + 1} added: {st['name']}")


def update_step(app):
    S = _steps(app)
    i = getattr(app, "_seq_sel", 0)
    if 0 <= i < len(S["steps"]):
        old = S["steps"][i]
        st = sequence.capture(app.eng, app.seg_cols, int(old.get("bri", 255)), old.get("name"), old.get("dur", 10),
                              old.get("trans", 0.7), rgb=_undimmed(app))
        if old.get("ramps"):
            st["ramps"] = old["ramps"]                   # the step's own settings stay; what it shows is the sim's
        S["steps"][i] = st
        _gather_look(app, st)
        _save(app)


def duplicate_step(app, i=None):
    S = _steps(app)
    i = getattr(app, "_seq_sel", 0) if i is None else i
    if 0 <= i < len(S["steps"]):
        cp = json.loads(json.dumps(S["steps"][i]))
        cp["name"] = f"{cp.get('name', 'step')} (copy)"
        S["steps"].insert(i + 1, cp)
        app._seq_sel = i + 1
        _save(app)
        app.gp.status(f"step {i + 1} duplicated")


RAMP_KEYS = ("sx", "ix", "c1", "c2", "c3")
GENERIC = {"sx": "Speed", "ix": "Intensity", "c1": "Custom 1", "c2": "Custom 2", "c3": "Custom 3"}


def _slider_words(app, effect):
    """{slider key: its name} for an effect - its own words where it has
    them (C9: no keys on screen), two the same told apart by the slider's
    place."""
    labels = []
    if effect in (app.eng.names or []):
        labels = app.eng.meta[app.eng.names.index(effect)].get("labels") or []
    out, seen = {}, set()
    for i, k in enumerate(RAMP_KEYS):
        lab = (labels[i] if i < len(labels) else "").strip()
        lab = lab if lab and lab != "!" else GENERIC[k]
        if lab in seen or lab == "none":
            lab = f"{lab} ({GENERIC[k]})"
        seen.add(lab); out[k] = lab
    return out


def _ramp_names(app, step):
    """{ramp key: what the ramps call it}: the brightness, then the step's sliders by their effect's words - every
    segment's, each led by the segment's number, when the step has more than one (sequence.ramp_key)."""
    segs = step.get("segments") or [{}]
    out = {sequence.BRI: "Brightness"}
    for s, sg in enumerate(segs):
        for k, lab in _slider_words(app, sg.get("effect")).items():
            out[sequence.ramp_key(s, k)] = f"{s}: {lab}" if len(segs) > 1 else lab
    return out


def set_ramp(app, key, end=None, shape=None):
    """A ramp on the selected step: its end value and / or shape."""
    S = _steps(app); sel = getattr(app, "_seq_sel", 0)
    if key in (None, "none") or not (0 <= sel < len(S["steps"])):
        return
    st = S["steps"][sel]
    cur = sequence.ramp_of(st, key) or (sequence.ramp_value(st, key, 0), "linear")
    st.setdefault("ramps", {})[key] = {"end": int(end if end is not None else cur[0]),
                                       "shape": str(shape if shape is not None else cur[1])}
    app.project.save(); _ramp_desc(app, st); app._tl_dirty = True


def remove_ramp(app, key):
    S = _steps(app); sel = getattr(app, "_seq_sel", 0)
    if key in (None, "none") or not (0 <= sel < len(S["steps"])):
        return
    st = S["steps"][sel]
    (st.get("ramps") or {}).pop(key, None)
    if not st.get("ramps"):
        st.pop("ramps", None)
    app.project.save(); app._tl_dirty = True; refresh(app)


def _ramp_desc(app, st):
    ramps = st.get("ramps") or {}
    dpg.set_value("seq_ramp_desc", f"{len(sequence.sub_steps(st))} sub-steps on the device" if ramps else
                  "none: the step holds still")


def load_step(app, i=None, quiet=False):
    S = _steps(app)
    i = getattr(app, "_seq_sel", 0) if i is None else i
    if 0 <= i < len(S["steps"]):
        sequence.apply(app.eng, S["steps"][i])
        app.seg_cols = [int(c) for c in app.eng._colors]         # the current segment's, as the step left them
        app.refresh_colours()
        dpg.set_value("fx_combo", app.eng.names[app.eng.idx])
        app.rebuild_params(); app.sync_palette_combo(); app.rebuild_seg_fields()
        if not S["steps"][i].get("look"):
            _gather_look(app, S["steps"][i])                # one made before looks: read as it shows
        if _play_i(app) is None and not quiet:
            app.gp.status(f"the sim shows step {i + 1}: {S['steps'][i].get('name')}")


def _gather_look(app, st):
    """The sim's frames for a moment, from now, as the step's look - while the sim goes on showing the effect it
    showed when this began (another effect picked meanwhile: the gathering stops, the look as it was)."""
    app._seq_look = {"st": st, "idx": app.eng.idx, "until": time.perf_counter() + LOOK_SPAN, "next": 0.0, "frames": []}


def _take_look(app):
    g = getattr(app, "_seq_look", None)
    if g is None:
        return
    now = time.perf_counter()
    if app.eng.idx != g["idx"]:
        app._seq_look = None; return
    if now >= g["next"]:
        g["next"] = now + LOOK_EVERY
        f = np.asarray(_undimmed(app))
        g["frames"].append(f[::2, ::2] if f.shape[0] > 8 and f.shape[1] > 8 else f)
    if now < g["until"]:
        return
    app._seq_look = None
    shapes = {f.shape for f in g["frames"]}
    if len(shapes) != 1:
        return                                            # the geometry changed under it
    lk = sequence.look(np.stack(g["frames"]))
    if lk and any(st is g["st"] for st in _steps(app)["steps"]):
        g["st"]["look"] = lk
        _save_quiet(app)
        app._seq_rows_dirty = True; app._tl_dirty = True


def _save_quiet(app):
    """Saved without an undo step of its own: a look arriving after its step was added - Undo then takes the step
    away, not the look."""
    p = app.project
    was = getattr(p, "_restoring", False)
    p._restoring = True
    try:
        p.save()
    finally:
        p._restoring = was


def del_step(app, i):
    S = _steps(app)
    if 0 <= i < len(S["steps"]):
        S["steps"].pop(i)
        app._seq_sel = min(i, len(S["steps"]) - 1)
        p = getattr(app, "_seq_play", None)
        if p is not None and p["i"] >= len(S["steps"]):
            stop(app)
        _save(app)


def move_step(app, i, d):
    move_to(app, i, i + d)


def move_to(app, i, j):
    """Step i to place j (the others shifting), the selection with it."""
    S = _steps(app)
    n = len(S["steps"])
    if not (0 <= i < n) or i == j:
        return
    j = max(0, min(n - 1, int(j)))
    st = S["steps"].pop(i)
    S["steps"].insert(j, st)
    app._seq_sel = j
    _save(app)


def set_field(app, key, value):
    S = _steps(app)
    i = getattr(app, "_seq_sel", 0)
    if 0 <= i < len(S["steps"]):
        S["steps"][i][key] = value
        _save(app)


def set_bars(app, bars):
    bl = _barlen(app)
    if bl:
        set_field(app, "dur", round(max(0.25, float(bars)) * bl, 3))


# --- beats: the steps on the music's bars --------------------------------------------------------
def set_tempo(app, bpm=None, bar=None):
    """The sequence's tempo (kept with it): bars on the timeline, lengths in bars, drags on the beats."""
    S = _steps(app)
    if bpm is not None:
        S["bpm"] = round(max(0.0, float(bpm)), 2)
    if bar is not None:
        S["bar"] = max(1, min(16, int(bar)))
    app.project.save(); refresh(app)


def beats_from_wav(app):
    """The bpm and the beat marks from the audio file the sim plays as live audio."""
    from native import audio
    live = getattr(app, "live", None)
    if not isinstance(live, audio.FileAudio):
        app.gp.status("play an audio file first: AUDIO > play an audio file..."); return
    got = audio.beats_of(live.samples, live.rate)
    if not got:
        app.gp.status("no beat found in the file"); return
    bpm, first, beats = got
    app._seq_beats = beats
    set_tempo(app, bpm=bpm)
    dpg.set_value("seq_tap", f"{_c()._fit_text(live.name, px(150))}: {bpm:.1f} bpm, {len(beats)} beats")
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
        set_tempo(app, bpm=round(bpm, 1)); dpg.set_value("seq_tap", f"{len(taps)} taps: {bpm:.1f} bpm")
    else:
        dpg.set_value("seq_tap", "tap again on the beat")


def snap_durations(app, bpm=None, bar=None):
    """Every step's seconds rounded to whole bars of the bpm (a step never
    shorter than one bar), so the sequence changes on the music."""
    S = _steps(app)
    if bpm is not None or bar is not None:
        S["bpm"] = float(bpm or S.get("bpm") or 120.0); S["bar"] = int(bar or S.get("bar") or 4)
    bpm = float(S.get("bpm") or 0) or 120.0
    bar = int(S.get("bar") or 4)
    if bpm <= 0:
        return
    beat = 60.0 / bpm; barlen = beat * bar
    for st in S["steps"]:
        st["dur"] = round(max(barlen, round(float(st.get("dur", 10)) / barlen) * barlen), 3)
    S["bpm"], S["bar"] = bpm, bar
    app.project.save(); refresh(app)
    app.gp.status(f"lengths on {bar}-beat bars at {bpm:.1f} bpm ({barlen:.2f} s a bar)")


# --- playing in the sim --------------------------------------------------------------------
def _starts(app):
    """Each step's start, seconds into the show, and the show's length."""
    t, out = 0.0, []
    for st in _steps(app)["steps"]:
        out.append(t); t += float(st.get("dur", 10))
    return out, t


def _play_i(app):
    p = getattr(app, "_seq_play", None)
    return p["i"] if p is not None and p["i"] >= 0 else None


def position(app):
    """Seconds into the show while it plays or is paused, else None."""
    p = getattr(app, "_seq_play", None)
    if p is None or p["i"] < 0:
        return None
    starts, _ = _starts(app)
    steps = _steps(app)["steps"]
    if p["i"] >= len(steps):
        return None
    left = p["paused"] if p.get("paused") is not None else max(0.0, p["next"] - time.perf_counter())
    return starts[p["i"]] + float(steps[p["i"]].get("dur", 10)) - left


def play(app, i=0, offset=0.0):
    """The show from step i (offset seconds into it), the sim following it."""
    S = _steps(app)
    if not S["steps"]:
        app.gp.status("no steps to play"); return
    i = max(0, min(len(S["steps"]) - 1, int(i)))
    dur = float(S["steps"][i].get("dur", 10))
    app._transition = None
    app._seq_play = {"i": i, "next": time.perf_counter() + max(0.05, dur - offset), "paused": None}
    app.playing = True
    live = getattr(app, "live", None)
    if live is not None and hasattr(live, "t0"):
        live.t0 = time.perf_counter() - (_starts(app)[0][i] + offset)   # the WAV from the same moment, with the sequence
    load_step(app, i, quiet=True)
    _sync_transport(app)
    refresh(app)


def play_pause(app):
    """The transport's button: play from the selected step; while playing, pause; paused, go on."""
    p = getattr(app, "_seq_play", None)
    if p is None:
        play(app, getattr(app, "_seq_sel", 0))
    elif p.get("paused") is None:
        p["paused"] = max(0.0, p["next"] - time.perf_counter())
        app.playing = False
        app.gp.status("sequence paused")
    else:
        p["next"] = time.perf_counter() + p["paused"]; p["paused"] = None
        app.playing = True
        live = getattr(app, "live", None)
        if live is not None and hasattr(live, "t0"):
            live.t0 = time.perf_counter() - (position(app) or 0.0)
    _sync_transport(app)


def seek(app, t):
    """The show at t seconds: its step in the sim, playing on from there (or held there while paused or stopped)."""
    S = _steps(app)
    starts, total = _starts(app)
    if not S["steps"] or total <= 0:
        return
    t = max(0.0, min(total - 0.01, float(t)))
    i = max(k for k, s in enumerate(starts) if s <= t)
    off = t - starts[i]
    p = getattr(app, "_seq_play", None)
    held = p is None or p.get("paused") is not None
    left = max(0.05, float(S["steps"][i].get("dur", 10)) - off)
    if p is None or p["i"] != i:
        load_step(app, i, quiet=True)
        app._transition = None
    app._seq_play = {"i": i, "next": time.perf_counter() + left, "paused": left if held else None}
    app.playing = not held
    live = getattr(app, "live", None)
    if live is not None and hasattr(live, "t0"):
        live.t0 = time.perf_counter() - t
    _apply_ramps(app, i, off / max(0.05, float(S["steps"][i].get("dur", 10))))
    _sync_transport(app)
    app._tl_dirty = True; app._seq_rows_dirty = True


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
    play(app, 0)
    app._seq_play["once"] = True
    app.start_rec(total, fmt)
    app.gp.status(f"rendering {total:.0f} s of the sequence to {fmt}...")


def stop(app):
    app._transition = None
    app._seq_bri = None
    if getattr(app, "_seq_play", None) is not None:
        app._seq_play = None
        app.playing = True
        dpg.set_value("seq_status", "")
        app.gp.status("sequence stopped")
        _sync_transport(app)
        refresh(app)


def _sync_transport(app):
    """The play button as what it does now: play, or pause while playing."""
    from native.icons import texture
    p = getattr(app, "_seq_play", None)
    playing = p is not None and p.get("paused") is None
    if dpg.does_item_exist("seq_play"):
        dpg.configure_item("seq_play", texture_tag=texture("pause" if playing else "play", px(16)))
    app._tl_dirty = True


def _apply_ramps(app, i, t):
    """The step's ramps at t (0..1) into the sim - each slider on its segment, the panel's field with it when that
    segment is the one shown - and the step's brightness (or its ramp)."""
    steps = _steps(app)["steps"]
    if not (0 <= i < len(steps)):
        return
    st = steps[i]
    ramps = st.get("ramps") or {}
    app._seq_bri = sequence.ramp_value(st, sequence.BRI, t) if sequence.BRI in ramps else int(st.get("bri", 255))
    changed = False
    for k in ramps:
        if k == sequence.BRI:
            continue
        v = sequence.ramp_value(st, k, t)
        seg, slider = sequence.ramp_target(k)
        if seg == app.eng.seg:
            if app.eng.fx.get(slider) != v:
                app.eng.fx[slider] = v; changed = True
                num.set(f"inp_{slider}", v)
        elif 0 <= seg < app.eng.seg_count():
            app.eng.seg_push(seg, {slider: v})
    if changed:
        app.eng.push()


def poll(app):
    _poll_send(app)
    _take_look(app)
    if dpg.is_item_shown(TAG):
        timeline_mouse(app)
        fw = (dpg.get_item_rect_size(TAG)[0], _c().scrollbar_w(TAG))
        if fw[0] and fw != getattr(app, "_tl_frame_w", None):
            app._tl_frame_w = fw; app._tl_dirty = True          # laid out, resized, a scrollbar come or gone: it follows
            app._seq_rows_dirty = True                          # the names fitted to the new width too
        if getattr(app, "_seq_rows_dirty", False):
            app._seq_rows_dirty = False; refresh(app)
        if getattr(app, "_seq_play", None) is not None or getattr(app, "_tl_dirty", True) or getattr(app, "_tl_hover_was", None) != getattr(app, "_tl_hover", None):
            draw_timeline(app); app._tl_dirty = False; app._tl_hover_was = getattr(app, "_tl_hover", None)
        _show_position(app)
    p = getattr(app, "_seq_play", None)
    if p is None:
        return
    S = _steps(app)
    steps = S["steps"]
    if not steps:
        stop(app); return
    if p.get("paused") is not None:
        return
    now = time.perf_counter()
    if now >= p["next"]:
        i = p["i"] + 1
        if i >= len(steps):
            if int(S.get("repeat", 0)) != 0 or p.get("once"):
                stop(app); app.gp.status("sequence done"); return
            i = 0
            live = getattr(app, "live", None)
            if live is not None and hasattr(live, "t0"):
                live.t0 = now                                # round again: the WAV from its start with it
        prev = steps[p["i"]] if 0 <= p["i"] < len(steps) else None
        p["i"] = i
        p["next"] = now + float(steps[i].get("dur", 10))
        if prev is not None and float(steps[i].get("trans", 0)) > 0:
            app.transition_start(prev, float(steps[i]["trans"]), S.get("style", "fade"))
        load_step(app, i, quiet=True)
        app._seq_rows_dirty = True
    i = p["i"]
    if 0 <= i < len(steps):
        dur = float(steps[i].get("dur", 10)) or 1.0
        _apply_ramps(app, i, 1.0 - max(0.0, p["next"] - now) / dur)


def _show_position(app):
    """The transport's clock and the playing step's words."""
    _, total = _starts(app)
    at = position(app)
    if dpg.does_item_exist("seq_pos"):
        dpg.set_value("seq_pos", f"{_fmt_t(at or 0.0)} / {_fmt_t(total)}")
    i = _play_i(app)
    steps = _steps(app)["steps"]
    if dpg.does_item_exist("seq_status"):
        p = getattr(app, "_seq_play", None)
        if i is not None and i < len(steps):
            dpg.set_value("seq_status", _c()._fit_text(f"{'paused at' if p.get('paused') is not None else 'playing'} "
                                                       f"step {i + 1}: {steps[i].get('name', '')}", px(260)))
        else:
            dpg.set_value("seq_status", "")


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


def _lanes(h):
    """The timeline's bands, top to bottom: (ruler bottom, blocks top, blocks bottom)."""
    return px(RULER_H), px(RULER_H) + 2, h - px(BEAT_LANE) - 2


def _ruler_step(total, w):
    """Seconds between the ruler's labelled ticks: the first of the usual steps that leaves room for the labels."""
    for s in (0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300):
        if s * w / max(total, 1e-6) >= px(46):
            return s
    return 600


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


def _fill_look(st, a, b, top, bot, parent, alpha=255):
    """A block filled with the step's colours across it (a quiet grey while it has no look yet)."""
    cols = sequence.look_colours(st)
    if not cols:
        dpg.draw_rectangle((a, top), (b, bot), color=(0, 0, 0, 0), fill=(70, 76, 90, alpha), parent=parent)
        return (70, 76, 90)
    n = len(cols)
    wdt = max(1.0, b - a)
    for k, col in enumerate(cols):
        x0, x1 = a + wdt * k / n, a + wdt * (k + 1) / n
        dpg.draw_rectangle((x0, top), (x1 + 0.6, bot), color=(0, 0, 0, 0), fill=tuple(col) + (alpha,), parent=parent)
    return cols[-1]


def draw_timeline(app):
    """The steps as blocks of their own colours along the time, names and lengths on them, the blend into each as a
    wedge from the colour before, the ramps' curves in their lower half; the ruler with the time; the bars at the
    tempo; the beats found in the WAV as ticks; the WAV's wave; the playhead; where a dragged step would land."""
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
        want = max(200, int(fw) - 24 - c.scrollbar_w(TAG))      # clear of the scrollbar too: past it, the frame scrolled sideways
        if abs(want - w) > 4:
            dpg.configure_item("seq_tl", width=want); w = want
    rb, top, bot = _lanes(h)
    dl = "seq_tl"
    dpg.draw_rectangle((0, 0), (w, h), color=(0, 0, 0, 0), fill=(0, 0, 0, 70), parent=dl)
    dpg.draw_rectangle((0, 0), (w, rb), color=(0, 0, 0, 0), fill=(255, 255, 255, 10), parent=dl)
    if total <= 0:
        typeface.draw_text((px(8), top + (bot - top) / 2 - px(8)), "the timeline: the steps along the time - add one from the sim",
                           px(14), color=c.DIM, parent=dl)
        return
    sx = w / total
    steps = _steps(app)["steps"]
    # the WAV's wave, faint behind the blocks (the WAV plays from 0 when the sequence starts)
    from native import audio
    live = getattr(app, "live", None)
    if isinstance(live, audio.FileAudio) and live.seconds > 0:
        cols = max(50, min(int(w), 600))
        wave = _wave(app, cols)
        if wave is not None:
            span = min(live.seconds, total)                 # only as far as the sequence goes
            n = int(cols * span / live.seconds)
            mid = (top + bot) / 2
            for k in range(n):
                x = k * (span * sx) / max(1, n)
                a = float(wave[k]) * (bot - top) * 0.5
                dpg.draw_line((x, mid - a), (x, mid + a), color=(255, 255, 255, 34), thickness=1, parent=dl)
    # the steps
    sel = min(getattr(app, "_seq_sel", 0), len(spans) - 1)
    hover = getattr(app, "_tl_hover", None)
    prev_end = None
    for i, (t, d, tr) in enumerate(spans):
        a, b = t * sx + 1, (t + d) * sx - 1
        st = steps[i]
        last = _fill_look(st, a, b, top, bot, dl, 235)
        # a dark band along the top for the name, the look still showing through
        dpg.draw_rectangle((a, top), (b, top + px(18)), color=(0, 0, 0, 0), fill=(0, 0, 0, 110), parent=dl)
        if hover == ("block", i):
            dpg.draw_rectangle((a, top), (b, bot), color=(0, 0, 0, 0), fill=(255, 255, 255, 28), parent=dl)
        # the blend into it: a wedge of the colour before it, narrowing over the blend's seconds
        if tr > 0 and prev_end is not None:
            bw = min(b - a, tr * sx)
            dpg.draw_triangle((a, top + px(18)), (a + bw, bot), (a, bot), color=(0, 0, 0, 0), fill=tuple(prev_end) + (200,), parent=dl)
            dpg.draw_line((a, top + px(18)), (a + bw, bot), color=(255, 255, 255, 120), thickness=1, parent=dl)
        if tr > 0 and b - a > px(14):
            hx = a + min(b - a, tr * sx)                     # the blend's handle: where its wedge ends, at the bottom
            dpg.draw_circle((hx, bot - px(5)), px(4), color=(255, 255, 255, 200), fill=(30, 34, 42, 255),
                            thickness=1.5, parent=dl)
        prev_end = last
        # its name, shortened to fit; its length on the right where there is room
        room = b - a - px(10)
        name = str(st.get("name", ""))
        length = f"{d:.1f}s" if d < 10 else f"{d:.0f}s"
        lw = typeface.measure(length, "mono", px(11))
        if room > lw + px(30):
            typeface.draw_text((b - lw - px(5), top + px(3)), length, px(11), face="mono", color=(230, 233, 240, 170), parent=dl)
            room -= lw + px(8)
        if room > px(14):
            shown = _fit_measured(name, room, px(13))
            typeface.draw_text((a + px(5), top + px(2)), shown, px(13), color=(245, 247, 250, 240), parent=dl)
        # the ramps: each a curve over the block's lower half, the brightness dashed
        rtop, rbot = top + (bot - top) * 0.5, bot - px(3)
        for j, k in enumerate(st.get("ramps") or {}):
            if b - a < 12:
                break
            pts = [(a + 2 + (b - a - 4) * q / 24, rbot - (rbot - rtop) * sequence.ramp_value(st, k, q / 24) / 255.0) for q in range(25)]
            dpg.draw_polyline(pts, color=(255, 255, 255, 230 - 45 * j) if k != sequence.BRI else (255, 220, 120, 220),
                              thickness=2, parent=dl)
        # the selected one outlined; the one playing underlined
        if i == sel:
            dpg.draw_rectangle((a, top), (b, bot), color=c.ACCENT, thickness=2, parent=dl)
        if i == _play_i(app):
            dpg.draw_rectangle((a, bot - px(3)), (b, bot), color=(0, 0, 0, 0), fill=(255, 255, 255, 230), parent=dl)
    # the bars at the tempo, faint across everything; the bars' numbers on the ruler where there is room
    bl = _barlen(app)
    end_w = typeface.measure(_fmt_t(total), "mono", px(10)) + px(10)     # the end's time keeps the ruler's right end
    if bl and bl * sx >= 4:
        t, nbar = 0.0, 1
        every = max(1, int(np.ceil(px(28) / (bl * sx))))
        while t <= total + 1e-6:
            dpg.draw_line((t * sx, rb), (t * sx, bot), color=(255, 255, 255, 26), thickness=1, parent=dl)
            if (nbar - 1) % every == 0 and t * sx + px(16) < w - end_w:
                typeface.draw_text((t * sx + 2, 1), str(nbar), px(10), face="mono", color=(255, 210, 120, 150), parent=dl)
            t += bl; nbar += 1
    # the ruler: ticks and the time
    rs = _ruler_step(total, w)
    t = 0.0
    while t <= total + 1e-6:
        x = t * sx
        dpg.draw_line((x, rb - px(6)), (x, rb), color=(255, 255, 255, 90), thickness=1, parent=dl)
        lab = _fmt_t(t) if rs >= 1 else f"{t:.1f}"
        lw = typeface.measure(lab, "mono", px(10))
        if x + lw + 2 < w and not (bl and bl * sx >= 4):          # with a tempo the ruler numbers the bars instead
            typeface.draw_text((x + 2, 2), lab, px(10), face="mono", color=c.DIM, parent=dl)
        t += rs
    if bl and bl * sx >= 4:                                   # with bars numbered, the end's time alone, on the right
        end = _fmt_t(total)
        typeface.draw_text((w - typeface.measure(end, "mono", px(10)) - 3, 2), end, px(10), face="mono", color=c.DIM, parent=dl)
    # the beats found in the WAV
    for bt in getattr(app, "_seq_beats", None) or []:
        if bt <= total:
            dpg.draw_line((bt * sx, h - px(BEAT_LANE)), (bt * sx, h - 1), color=(255, 200, 80, 150), thickness=1, parent=dl)
    # where a dragged step would go
    drag = getattr(app, "_tl_drag", None)
    if drag and drag[0] == "move" and drag[3] is not None:
        j = drag[3]
        xs = [s * sx for s, _, _ in spans] + [total * sx]
        x = xs[j] if j <= drag[1] else xs[min(len(xs) - 1, j + 1)]
        dpg.draw_line((x, top - 2), (x, bot + 2), color=c.ACCENT, thickness=px(3), parent=dl)
    # the playhead, with its time
    at = position(app)
    if at is not None:
        x = at * sx
        dpg.draw_line((x, 0), (x, h), color=(255, 255, 255, 240), thickness=2, parent=dl)
        dpg.draw_triangle((x - px(5), 0), (x + px(5), 0), (x, px(7)), color=(0, 0, 0, 0), fill=(255, 255, 255, 240), parent=dl)
    elif hover and hover[0] == "ruler":
        x = hover[1] * sx
        dpg.draw_line((x, 0), (x, h), color=(255, 255, 255, 90), thickness=1, parent=dl)
        lab = _fmt_t(hover[1])
        typeface.draw_text((min(x + 3, w - px(30)), rb + 2), lab, px(10), face="mono", color=(255, 255, 255, 200), parent=dl)


def _fit_measured(text, width, size):
    """text shortened with "..." to fit `width` drawn at `size` (typeface.measure: works before a frame too)."""
    if typeface.measure(text, "body", size) <= width:
        return text
    lo, hi = 0, len(text)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if typeface.measure(text[:mid].rstrip() + "...", "body", size) <= width:
            lo = mid
        else:
            hi = mid - 1
    return text[:lo].rstrip() + "..." if lo else ""


def _hsv(h, s, v):
    import colorsys
    r, g, b = colorsys.hsv_to_rgb((h % 360) / 360.0, s, v)
    return (int(r * 255), int(g * 255), int(b * 255))


def _hit(app, g, mx, my):
    """What the pointer is on: ("ruler", t) | ("end", i) | ("blend", i) | ("block", i) | None."""
    x0, y0, w, h, total, spans = g
    if not (x0 <= mx <= x0 + w and y0 <= my <= y0 + h) or total <= 0:
        return None
    sx = w / total
    x, y = mx - x0, my - y0
    rb, top, bot = _lanes(h)
    if y < rb:
        return ("ruler", max(0.0, min(total, x / sx)))
    for i, (t, d, tr) in enumerate(spans):
        if tr > 0 and abs(x - (t * sx + min(d, tr) * sx)) <= px(6) and abs(y - (bot - px(5))) <= px(7):
            return ("blend", i)
    for i, (t, d, tr) in enumerate(spans):
        if abs((t + d) * sx - x) <= px(5) and top <= y <= bot:
            return ("end", i)
    for i, (t, d, tr) in enumerate(spans):
        if t * sx <= x < (t + d) * sx:
            return ("block", i)
    return None


def timeline_mouse(app):
    """The pointer on the timeline: the ruler goes to a time (and scrubs while held); a step's end is dragged to
    retime it (on the beats when a tempo is set; Alt: free), its blend handle to set the blend; a step is selected
    by a click and moved by a drag; a double-click shows it in the sim; a right-click opens its menu."""
    g = _tl_geometry(app)
    if g is None:
        return
    x0, y0, w, h, total, spans = g
    mx, my = dpg.get_mouse_pos(local=False)
    down = dpg.is_mouse_button_down(dpg.mvMouseButton_Left)
    drag = getattr(app, "_tl_drag", None)
    sx = w / total if total > 0 else 1.0
    t_at = max(0.0, (mx - x0) / sx) if total > 0 else 0.0
    if drag is not None:
        steps = _steps(app)["steps"]
        kind = drag[0]
        if down:
            if kind == "scrub":
                seek(app, min(total, t_at))
            elif kind == "end":
                i, start = drag[1], drag[2]
                end = t_at
                beat = _beat(app)
                alt = dpg.is_key_down(dpg.mvKey_LAlt) or dpg.is_key_down(dpg.mvKey_RAlt)
                if beat and _steps(app).get("snap", True) and not alt:
                    end = round(end / beat) * beat                   # on the beat
                if 0 <= i < len(steps):
                    steps[i]["dur"] = round(max(0.25, end - start), 3)
                    app._tl_dirty = True
            elif kind == "blend":
                i, start = drag[1], drag[2]
                if 0 <= i < len(steps):
                    steps[i]["trans"] = round(max(0.0, min(float(steps[i].get("dur", 10)), t_at - start)), 2)
                    app._tl_dirty = True
            elif kind in ("block", "move"):
                if kind == "block" and abs(mx - drag[2]) > px(6):
                    app._tl_drag = drag = ("move", drag[1], drag[2], None)
                if drag[0] == "move":
                    j = next((k for k, (t, d, tr) in enumerate(spans) if t <= t_at < t + d), len(spans) - 1)
                    app._tl_drag = ("move", drag[1], drag[2], j)
                    app._tl_dirty = True
        else:
            app._tl_drag = None
            if kind == "move" and drag[3] is not None and drag[3] != drag[1]:
                move_to(app, drag[1], drag[3])
            elif kind in ("end", "blend"):
                app.project.save(); refresh(app)
            elif kind == "block":
                select(app, drag[1])
            app._tl_dirty = True
        return
    hit = _hit(app, g, mx, my)
    app._tl_hover = hit if hit and hit[0] in ("block",) else (("ruler", round(hit[1], 1)) if hit and hit[0] == "ruler" else None)
    if hit is None:
        return
    if dpg.is_mouse_button_clicked(dpg.mvMouseButton_Right) and hit[0] in ("block", "end", "blend"):
        _context(app, hit[1]); return
    if not dpg.is_mouse_button_clicked(dpg.mvMouseButton_Left):
        return
    if dpg.is_mouse_button_double_clicked(dpg.mvMouseButton_Left) and hit[0] == "block":
        app._tl_drag = None
        select(app, hit[1]); load_step(app, hit[1]); return
    if hit[0] == "ruler":
        app._tl_drag = ("scrub",); seek(app, hit[1])
    elif hit[0] == "end":
        app._tl_drag = ("end", hit[1], spans[hit[1]][0])
    elif hit[0] == "blend":
        app._tl_drag = ("blend", hit[1], spans[hit[1]][0])
    elif hit[0] == "block":
        app._tl_drag = ("block", hit[1], mx)


def _context(app, i):
    """A step's menu on the timeline."""
    c = _c()
    select(app, i)
    dpg.delete_item("seq_ctx", children_only=True)
    st = _steps(app)["steps"][i]
    dpg.add_text(c._fit_text(f"step {i + 1}: {st.get('name', '')}", px(220)), parent="seq_ctx", color=c.DIM)
    for label, fn in (("Play from here", lambda: play(app, i)), ("Show it in the sim", lambda: load_step(app, i)),
                      ("Update from the sim", lambda: update_step(app)), ("Add from the sim after it", lambda: add_step(app)),
                      ("Duplicate", lambda: duplicate_step(app, i)), ("Delete", lambda: del_step(app, i))):
        dpg.add_selectable(label=label, parent="seq_ctx", callback=lambda s, a, u: (dpg.hide_item("seq_ctx"), u()), user_data=fn)
    x, y = dpg.get_mouse_pos(local=False)
    dpg.set_item_pos("seq_ctx", [x, y])
    dpg.show_item("seq_ctx")


# --- the keys ------------------------------------------------------------------------------------
def key(app, code):
    """The frame's own keys while it has the keyboard (not while a box is typed in): Space plays and pauses,
    Delete removes the selected step, Ctrl+D duplicates it. True when the key was the frame's."""
    if not dpg.does_item_exist(TAG) or not dpg.is_item_shown(TAG) or app.typing() or app.undo_target() != "sequence":
        return False
    ctrl = dpg.is_key_down(dpg.mvKey_LControl) or dpg.is_key_down(dpg.mvKey_RControl)
    if code == dpg.mvKey_Spacebar and not ctrl and _has_steps(app):
        play_pause(app); return True
    if code == dpg.mvKey_Delete and _has_sel(app):
        del_step(app, getattr(app, "_seq_sel", 0)); return True
    if code == dpg.mvKey_D and ctrl and _has_sel(app):
        duplicate_step(app); return True
    return False


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
    fp = sequence.fingerprint(S)
    dpg.set_value("seq_log", f"sending {n} preset(s) and the playlist to {host}...")
    for t in ("seq_send", "seq_send_run"):
        if dpg.does_item_exist(t):
            dpg.configure_item(t, enabled=False)

    def work():
        sent = None
        try:
            ok, msg = sequence.send(host, presets, playlist, pid)
            if ok:
                sent = (host, fp)
            if ok and run:
                ok2, msg2 = sequence.start(host, pid)
                msg += "; " + msg2
        except Exception as e:                            # the buttons come back and the log says, whatever went wrong
            msg = f"send failed: {e}"
        app._seq_sent_now = sent
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
    sent = getattr(app, "_seq_sent_now", None)
    if sent:
        host, fp = sent
        d = next((d for d in app.devices if d.get("host") == host), {})
        _steps(app)["sent"] = {"host": host, "name": d.get("name") or host, "fp": fp, "when": time.strftime("%Y-%m-%d %H:%M")}
        app.project.save()
    dpg.set_value("seq_log", msg); app.gp.status(msg); device_ui.send_log(app, msg)
    refresh_sent(app)


def refresh_sent(app):
    """Whether the device has this show: sent as it is now, changed since, or not sent yet."""
    if not dpg.does_item_exist("seq_sent"):
        return
    c = _c()
    S = _steps(app)
    sent = S.get("sent")
    if not S["steps"]:
        dpg.set_value("seq_sent", ""); return
    if not sent:
        dpg.set_value("seq_sent", "not sent to a device yet"); dpg.configure_item("seq_sent", color=c.DIM); return
    same = sent.get("fp") == sequence.fingerprint(S)
    where = sent.get("name") or sent.get("host")
    if same:
        dpg.set_value("seq_sent", f"on {where} as it is here (sent {sent.get('when', '')})")
        dpg.configure_item("seq_sent", color=c.GREEN)
    else:
        dpg.set_value("seq_sent", f"changed since it was sent to {where} ({sent.get('when', '')}) - send it again to update it")
        dpg.configure_item("seq_sent", color=c.AMBER)


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
