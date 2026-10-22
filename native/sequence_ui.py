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

from native import clock, sequence, transition

TAG = "sequence_win"
ROW_H = 30               # a step's row in the list, at the interface size
TL_H = 104               # the timeline's height, until it is sized by its grip (prefs "seq_tl_h")
TL_H_MIN, TL_H_MAX = 80, 640
OV_H = 16                # the overview strip over the timeline: the whole show, and the part the timeline shows
GRIP_H = 9               # the grip under the timeline that sizes it
MIN_SPAN = 0.5           # seconds across the timeline at the closest zoom
ZOOM_STEP = 1.35         # a notch of the wheel, or a click of + or -
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
    app._seq_save_at = None
    _follow(app)
    app.project.save()
    refresh(app)


def _follow(app):
    """The step playing kept as the one playing when the list changes under it (a step added, duplicated,
    moved or deleted before it): the play state holds its index, which then named another step - the
    highlight jumped, the blend came from the wrong step and one was skipped. Found again by identity; gone
    with the list another length (deleted), playing stops; gone with the same length (an undo made new
    copies of the steps), the index stays."""
    p = getattr(app, "_seq_play", None)
    if p is None or p.get("st") is None:
        return
    steps = _steps(app)["steps"]
    k = next((k for k, st in enumerate(steps) if st is p["st"]), None)
    if k is not None:
        p["i"] = k
    elif len(steps) != p.get("n", len(steps)) or not 0 <= p["i"] < len(steps):
        stop(app); app.gp.status("the step playing was removed: stopped")
        return
    else:
        p["st"] = steps[p["i"]]
    p["n"] = len(steps)


# --- the numbers, live -------------------------------------------------------------------------
def _tset(tag, v):
    """A text field's value from outside - not while it is being typed in: the refresh that follows a step
    change while playing, or a look gathered after Add, put the old name back over a name half typed."""
    if dpg.does_item_exist(tag) and not dpg.is_item_active(tag):
        dpg.set_value(tag, v)


def _nset(tag, v):
    """A number field's value from outside - not the one being dragged or typed in (it has its own)."""
    if dpg.does_item_exist(tag) and not dpg.is_item_active(tag):
        num.set(tag, v)


def _queue_save(app):
    """Saved once the numbers settle: a drag is one undo step, not one a frame."""
    app._seq_save_at = time.perf_counter() + 0.5


def _flush_save(app, now=False):
    due = getattr(app, "_seq_save_at", None)
    if due is not None and (now or time.perf_counter() >= due):
        app._seq_save_at = None
        app.project.save()


def _live(app):
    """Every number that follows from the steps, as they are now - the list's lengths and bars, the selected step's
    fields, the show's length - the timeline redrawn and the device line said again, the list not rebuilt (the
    field being dragged keeps its place)."""
    S = _steps(app)
    steps = S["steps"]
    for i, st in enumerate(steps):
        _nset(f"seq_len_{i}", float(st.get("dur", 10)))
        if dpg.does_item_exist(f"seq_bars_{i}"):
            dpg.set_value(f"seq_bars_{i}", _bars_words(app, st.get("dur", 10)))
    sel = getattr(app, "_seq_sel", 0)
    if 0 <= sel < len(steps):
        st = steps[sel]
        _nset("seq_dur", float(st.get("dur", 10)))
        bl = _barlen(app)
        if bl:
            _nset("seq_dur_bars", round(float(st.get("dur", 10)) / bl, 2))
        _nset("seq_trans", float(st.get("trans", 0.7)))
        _nset("seq_bri", int(st.get("bri", 255)))
    _, total = _starts(app)
    _nset("seq_len_all", round(total, 1))
    app._tl_dirty = True
    refresh_sent(app)


def _num_changed(app, key, v, i=None):
    """A step's number changed (the selected step's, or row i's): held seconds, bars, blend, brightness."""
    S = _steps(app)
    steps = S["steps"]
    i = getattr(app, "_seq_sel", 0) if i is None else int(i)
    if not (0 <= i < len(steps)):
        return
    st = steps[i]
    was = float(st.get("dur", 10))
    if key == "dur":
        st["dur"] = round(max(0.1, float(v)), 3)
    elif key == "bars":
        bl = _barlen(app)
        if not bl:
            return
        st["dur"] = round(max(0.1, float(v) * bl), 3)
    elif key == "trans":
        st["trans"] = round(max(0.0, min(float(v), float(st.get("dur", 10)))), 2)
    elif key == "bri":
        st["bri"] = int(v)
    if key in ("dur", "bars") and float(st.get("trans", 0)) > st["dur"]:
        st["trans"] = round(st["dur"], 2)                 # a step made shorter: its blend no longer outlasts it
    _follow_playing(app, i, float(st.get("dur", 10)) - was)
    _live(app)
    _queue_save(app)


def _follow_playing(app, i, delta):
    """The step playing made longer or shorter: its time left follows (it ends where its new length says)."""
    p = getattr(app, "_seq_play", None)
    if not delta or p is None or p["i"] != i:
        return
    if p.get("paused") is not None:
        p["paused"] = max(0.05, p["paused"] + delta)
    else:
        p["next"] = max(clock.now() + 0.05, p["next"] + delta)


def _total_changed(app, v):
    """The show's length set: every step scaled with it, in proportion."""
    steps = _steps(app)["steps"]
    _, total = _starts(app)
    if not steps or total <= 0:
        return
    k = max(0.1, float(v)) / total
    for i, st in enumerate(steps):
        old = float(st.get("dur", 10))
        st["dur"] = round(max(0.1, old * k), 3)
        _follow_playing(app, i, st["dur"] - old)
    _live(app)
    _queue_save(app)


def _tempo_changed(app, bpm=None, bar=None):
    """The tempo or the beats a bar: the bars everywhere follow; a tempo come or gone shows or hides them."""
    S = _steps(app)
    had = bool(_barlen(app))
    if bpm is not None:
        S["bpm"] = round(max(0.0, float(bpm)), 2)
    if bar is not None:
        S["bar"] = max(1, min(16, int(bar)))
    if bool(_barlen(app)) != had:
        _queue_save(app)
        refresh(app)
        return
    _live(app)
    _queue_save(app)


def _id_changed(app, key, v):
    _steps(app)[key] = int(v)
    refresh_sent(app)
    _queue_save(app)


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
    _flush_save(app, now=True)                            # a change still settling: saved first, so it is the one undone
    p = app.project
    key = p.latest(("sequence", "schedule"), redo=redo)    # whichever changed last (it read a stamp nothing wrote)
    if key is None:
        app.gp.status("nothing to " + ("redo" if redo else "undo") + " in the sequence"); return
    (p.redo if redo else p.undo)(key)
    _follow(app)                                          # the steps are new copies now: the playing one kept
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
            _icon_button("seq_rec", "record", "record automation: while the show plays, a slider moved (here or in "
                         "the side panel) is written into the step playing as a curve ramp - over the stretch it was "
                         "moved, the rest of the step as it was. Again: stop recording", lambda: toggle_rec(app))
            weight.need("seq_rec", _has_steps)
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
            num.add("seq_len_all", 0.0, 0.1, 3600, unit="s", digits=1, width=px(100), wide=True, pace=60,
                    callback=lambda s, v: _total_changed(app, v))
            c.tip("the whole show's length: changed, every step stretches or shrinks with it, in proportion")
            c.info("Steps of what the sim shows, each held for a while: played here, and on the device as presets run by a "
                   "playlist. Every number here is live: drag it sideways or click it and type, and the rest follows - the "
                   "list, the timeline, the bars, the show's length. On the timeline: click the ruler to go to a time, click "
                   "a step to select it, drag a step to move it, drag the line after a step to make it longer or shorter (on "
                   "the beats when a tempo is set; Alt: free), drag the little handle where a step's blend ends to set it. Double-click a step to show it in "
                   "the sim, right-click for more. The wheel moves the timeline along the time, Ctrl+wheel zooms at the "
                   "pointer, a middle-button drag moves it; the strip over it is the whole show, the box in it what the "
                   "timeline shows - drag the box, or its sides to zoom; drag the grip under the timeline to make it "
                   "taller. Z: the selected step across it, Shift+Z: the whole show. In the list, drag a row by its name to move it, or drop an effect's "
                   "tile from the Library on it for a step of that effect there. With the frame's "
                   "keyboard: Space plays and pauses, Delete removes the selected step, Ctrl+D duplicates it.")
        # the timeline: the steps as blocks of their own colours along the time, the ruler, bars, beats, the WAV -
        # zoomed and moved along like an arrangement view, the whole show in the overview over it
        with dpg.group(horizontal=True):                    # short, to fit the frame docked narrow
            dpg.add_button(label="-", tag="seq_zoom_out", small=True, callback=lambda: zoom(app, 1 / ZOOM_STEP))
            c.tip("zoom out (Ctrl+wheel over the timeline zooms at the pointer)")
            dpg.add_button(label="+", tag="seq_zoom_in", small=True, callback=lambda: zoom(app, ZOOM_STEP))
            c.tip("zoom in (Ctrl+wheel over the timeline zooms at the pointer)")
            dpg.add_button(label="All", tag="seq_zoom_all", small=True, callback=lambda: fit_all(app))
            c.tip("the whole show across the timeline (Shift+Z)")
            dpg.add_button(label="Step", tag="seq_zoom_step", small=True, callback=lambda: fit_step(app))
            c.tip("the selected step across the timeline, a little either side (Z)")
            dpg.add_checkbox(label="follow", tag="seq_follow", default_value=bool(app.prefs.get("seq_follow", True)),
                             callback=lambda s, v: _set_pref(app, "seq_follow", bool(v)))
            c.tip("while the show plays, the timeline turns the page when the playhead reaches its edge")
            typeface.mono(dpg.add_text("", tag="seq_zoom_words", color=c.DIM))
        dpg.add_drawlist(tag="seq_tl_ov", width=px(600), height=px(OV_H))
        dpg.add_drawlist(tag="seq_tl", width=px(600), height=_tl_height(app))   # its drawing reads its size back
        dpg.add_drawlist(tag="seq_tl_grip", width=px(600), height=px(GRIP_H))
        # the show's audio: tracks of clips under the steps, through the same view (showaudio.py)
        with dpg.group(horizontal=True):
            typeface.label(dpg.add_text("AUDIO", color=c.ACCENT))
            dpg.add_button(label="+ Audio...", tag="seq_audio_add", small=True,
                           callback=lambda: (setattr(app, "_audio_to_track", None), dpg.show_item("seq_audio_dialog")))
            c.tip("an audio file onto the show, at the playhead (or the selected step's start), on a track with room "
                  "there: heard while the show plays, and by its effects; copied into the project")
            dpg.add_button(label="+ Track", tag="seq_track_add", small=True, callback=lambda: add_track(app))
            c.tip("one more track: a lane of its own under the others, for a layer of sound over another")
            dpg.add_text("", tag="seq_audio_words", color=c.DIM)
        dpg.add_drawlist(tag="seq_tl_audio", width=px(600), height=_audio_height(app))
        from native.audio import AUDIO_EXTS
        with dpg.file_dialog(directory_selector=False, show=False, tag="seq_audio_dialog", width=px(620), height=px(420),
                             callback=lambda s, a: add_audio(app, a.get("file_path_name", ""), getattr(app, "_audio_to_track", None))):
            dpg.add_file_extension("{" + ",".join(AUDIO_EXTS) + "}", color=(120, 170, 255))
            dpg.add_file_extension(".*")
        # a drop on the list below its rows: a step moved to the end, or an effect from the Library added there
        with dpg.child_window(tag="seq_rows", height=px(ROW_H * 4 + 12), border=True, payload_type="seq_step",
                              drop_callback=lambda s, a, u: dropped(app, a, None)):
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
            dpg.add_checkbox(label="edit live", tag="seq_edit", callback=lambda s, v: toggle_edit(app, v))
            c.tip("the sim shows the selected step, and every change - here or in the side panel: its effect, "
                  "sliders, palette, layers, mirroring - goes into the step as you make it; while the show plays, into "
                  "the step on the playhead. Off, the sim is free to set up something new for Add from the sim")
        with dpg.group(horizontal=True) as _row:
            form.inline("name")
            dpg.add_input_text(tag="seq_name", width=px(170), on_enter=True, callback=lambda s, v: set_field(app, "name", v))
            form.inline("held")
            num.add("seq_dur", 10.0, 0.1, 600, unit="s", digits=1, width=px(96), wide=True, pace=10,
                    callback=lambda s, v: _num_changed(app, "dur", v))
            c.tip("how long the step is shown, seconds - the bars beside it follow")
            num.add("seq_dur_bars", 4.0, 0.25, 128, unit="bars", digits=2, width=px(96), show=False, wide=True, pace=4,
                    callback=lambda s, v: _num_changed(app, "bars", v))
            c.tip("how long the step is shown, in bars of the tempo (BEATS below) - the seconds follow")
            form.inline("blend")
            num.add("seq_trans", 0.7, 0.0, 30.0, unit="s", digits=1, width=px(86), wide=True, pace=1,
                    callback=lambda s, v: _num_changed(app, "trans", v))
            c.tip("seconds of blend into this step (or drag the handle where it ends on the timeline)")
        form.mono_values(_row)
        with dpg.group(horizontal=True):
            form.inline("brightness")
            num.add("seq_bri", 255, 0, 255, integer=True, width=px(200), callback=lambda s, v: _num_changed(app, "bri", v))
            c.tip("the step's brightness: its preset sets the device's, and the sim shows it so while the sequence plays")
        _build_fx(app, c)
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
            num.add("seq_bpm", 0.0, 0.0, 300.0, unit="bpm", digits=1, width=px(110), wide=True, pace=120,
                    callback=lambda s, v: _tempo_changed(app, bpm=v))
            c.tip("the tempo the steps are laid on: bars on the timeline, lengths in bars, drags on the beats (0: none)")
            dpg.add_button(label="Tap", small=True, callback=lambda: tap(app))
            c.tip("tap tempo: tap on the beat, the bpm from the gaps")
            dpg.add_button(label="Synth's", small=True, callback=lambda: set_tempo(app, bpm=float(getattr(app.syn, "bpm", 120))))
            c.tip("the bpm of the sim's synthetic beat")
            dpg.add_button(label="the file's", small=True, callback=lambda: beats_from_wav(app))
            c.tip("the tempo and the beats found in the audio file playing as live audio (AUDIO > play an audio file)")
            form.inline("beats a bar")
            num.add("seq_bar", 4, 1, 16, integer=True, width=px(60), callback=lambda s, v: _tempo_changed(app, bar=v))
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
            dpg.add_button(label="Render video...", small=True, callback=lambda: __import__("native.render_video", fromlist=["r"]).show(app))
            weight.need(dpg.last_item(), _has_steps)
            c.tip("the show made into an mp4, frame by frame at the size, rate and quality chosen, with its audio - "
                  "into captures/; needs ffmpeg on the path")
        dpg.add_separator()
        with dpg.group(horizontal=True):
            typeface.label(dpg.add_text("ON THE DEVICE", color=c.ACCENT))
            form.inline("presets from")
            num.add("seq_base", 10, 1, 240, integer=True, width=px(70), callback=lambda s, v: _id_changed(app, "base", v))
            c.tip("each step is saved as a preset, ids from here up; ones already there are overwritten")
            form.inline("playlist")
            num.add("seq_pid", 9, 1, 250, integer=True, width=px(70), callback=lambda s, v: _id_changed(app, "pid", v))
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
    total = sum(float(s.get("dur", sequence.DUR_DEFAULT)) for s in steps)
    playing = _play_i(app)
    # the name's column: what the frame's width leaves after the fixed ones (and the list's padding and scrollbar)
    fw = dpg.get_item_rect_size(TAG)[0] or dpg.get_item_configuration(TAG)["width"]
    name_w = max(px(60), int(fw) - px(16 + 52 + 110 + 132 + 48) - px(90))
    if steps:
        with dpg.table(parent="seq_rows", header_row=False, policy=dpg.mvTable_SizingFixedFit, borders_innerH=False,
                       pad_outerX=False, no_host_extendX=True):
            dpg.add_table_column(width_fixed=True, init_width_or_weight=px(16))      # playing / the drag hint
            dpg.add_table_column(width_fixed=True, init_width_or_weight=px(52))      # the look
            dpg.add_table_column(width_stretch=True, init_width_or_weight=1.0)       # the name
            dpg.add_table_column(width_fixed=True, init_width_or_weight=px(110))     # the effect
            dpg.add_table_column(width_fixed=True, init_width_or_weight=px(132))     # the length, live, and its bars
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
                                            drop_callback=lambda s, a, u: dropped(app, a, dpg.get_item_user_data(s)))
                    with dpg.drag_payload(parent=s_, drag_data=i, payload_type="seq_step"):
                        dpg.add_text(f"move {st.get('name', '')}")
                    t_ = dpg.add_text(_c()._fit_text(fx, px(106)), color=c.TEXT if i != playing else c.ACCENT)
                    if len(st.get("segments") or []) > 1:
                        c.tip(fx, item=t_)
                    with dpg.group(horizontal=True, horizontal_spacing=px(4)):
                        num.add(f"seq_len_{i}", float(st.get("dur", 10)), 0.1, 600, unit="s", digits=1, width=px(72), wide=True, pace=10,
                                user_data=i, callback=lambda s, v, u: _num_changed(app, "dur", v, u))
                        dpg.add_text(_bars_words(app, st.get("dur", sequence.DUR_DEFAULT)), tag=f"seq_bars_{i}", color=c.DIM)
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
    dpg.set_value("seq_total", f"{len(steps)} step{'s' if len(steps) != 1 else ''}, the show" if steps else "")
    dpg.configure_item("seq_len_all__num", show=bool(steps)); _nset("seq_len_all", round(total, 1))
    _nset("seq_base", int(S.get("base", 10))); _nset("seq_pid", int(S.get("pid", 9)))
    _tset("seq_show", S.get("name", "Show")); dpg.set_value("seq_repeat", int(S.get("repeat", 0)) == 0)
    dpg.set_value("seq_style", S.get("style", "fade"))
    _nset("seq_bpm", float(S.get("bpm") or 0)); _nset("seq_bar", int(S.get("bar") or 4))
    dpg.set_value("seq_snap", bool(S.get("snap", True)))
    has_tempo = bool(_barlen(app))
    dpg.configure_item("seq_step_card", show=bool(steps))
    dpg.configure_item("seq_dur_bars__num", show=has_tempo)          # a number field shows and hides by its group
    if 0 <= sel < len(steps):
        st = steps[sel]
        dpg.set_value("seq_step_title", f"STEP {sel + 1}")
        _tset("seq_name", st.get("name", "")); _nset("seq_dur", float(st.get("dur", 10)))
        _nset("seq_trans", float(st.get("trans", 0.7)))
        if has_tempo:
            _nset("seq_dur_bars", round(float(st.get("dur", 10)) / _barlen(app), 2))
        _nset("seq_bri", int(st.get("bri", 255)))
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
    app._clip_sel = None
    if getattr(app, "_seq_edit", False) and getattr(app, "_seq_play", None) is not None and _play_i(app) != app._seq_sel:
        # editing while the show plays edits the step on the playhead (_edit_poll keeps the selection there): a step
        # chosen - on the timeline, in the list - is played from, or it was taken back a frame later
        starts = _starts(app)[0]
        if 0 <= app._seq_sel < len(starts):
            seek(app, starts[app._seq_sel])
    _into_view(app, int(i))
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
            c.tip("the ramp's shape: straight, eased at either end or both, up and back to where it began, a jump half "
                  "way - or a curve drawn on the timeline: drag its points, Shift+click the step's lower half for one "
                  "more, right-click one to take it away")
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


OFF_PRESET = sequence.OFF_PRESET          # the "Off" preset the off timers call: high, out of the steps' way


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
    from native import device_ui, tasks
    host = app.active_host()
    T = json.loads(json.dumps(_timers(app)))              # the worker's own copy
    if not host:
        device_ui.show(app, "devices"); app.gp.status("choose a device first"); return
    h = host if host.startswith("http") else "http://" + host
    off = any(t.get("what") == "off" for t in T)

    def work():
        # an "off" preset for the off timers, saved as a state that is off. A fixed
        # high id: the playlist's id + 1 used to be it, which is the first step's
        # preset by default (playlist 9, steps from 10) - the off timer then played
        # the first step.
        if off:
            # saving a preset applies its state first, so the device goes dark for
            # the save; it is switched back on after if it was on before
            try:
                was_on = bool(json.loads(urllib.request.urlopen(h + "/json/state", timeout=6).read()).get("on"))
                sequence.psave(h, OFF_PRESET, {"on": False, "n": "Off", "ib": True})   # ib: keep "on" (off) and the brightness in it
                if was_on:
                    urllib.request.urlopen(urllib.request.Request(h + "/json/state", data=b'{"on":true}', headers={"Content-Type": "application/json"}), timeout=6).read()
            except Exception as e:
                return False, f"the off preset was refused: {e}"
        req = urllib.request.Request(h + "/json/cfg", data=json.dumps(timers_json(T)).encode(), headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=6) as r:
                r.read()
            return True, f"{len(T)} timer(s) sent to {host}" + ("; the off preset saved" if off else "")
        except Exception as e:
            return False, f"the device refused the timers: {e}"

    def done(r):
        ok, msg = r
        dpg.set_value("seq_tlog", msg)
        if ok:
            app.gp.status(msg); device_ui.send_log(app, msg)
    # on a worker (native/tasks.py): up to four requests of 6 s each held the whole studio with a device that did not answer
    tasks.run(app, "seq:timers", f"sending the schedule to {host}", work, done)


def read_timers(app):
    from native import devices, device_ui, tasks
    host = app.active_host()
    if not host:
        device_ui.show(app, "devices"); app.gp.status("choose a device first"); return

    def work():
        try:
            return devices._get(host, "/json/cfg", 6)
        except Exception as e:
            return e

    def done(cfg):
        if isinstance(cfg, Exception):
            dpg.set_value("seq_tlog", f"could not read the device's config: {cfg}"); return
        T = []
        pid = int(_steps(app).get("pid", 9))
        for e in (((cfg if isinstance(cfg, dict) else {}).get("timers") or {}).get("ins") or []):
            h = int(e.get("hour", 0)); m = int(e.get("macro", 0))
            T.append({"en": bool(e.get("en", 0)), "when": "sunrise" if h == 255 else ("sunset" if h == 254 else "time"),
                      "hour": 0 if h >= 254 else h, "min": int(e.get("min", 0)), "dow": int(e.get("dow", 127)), "preset": m,
                      "what": "playlist" if m == pid else ("off" if m == OFF_PRESET else "")})     # our own rows recognised
        app.project.options["schedule"] = T
        app.project.save(); refresh_timers(app)
        dpg.set_value("seq_tlog", f"{len(T)} timer(s) read from the device")
    # on a worker (native/tasks.py): a device that did not answer held the whole studio for 6 s
    tasks.run(app, "seq:timers", f"reading the schedule from {host}", work, done)


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
    shape = str(shape if shape is not None else cur[1])
    if shape == "curve":
        # a curve keeps the look it had: its points sampled from the ramp as it was; its end is its last point
        pts = sequence.curve_points(st, key) if cur[1] == "curve" else sequence.to_curve(st, key)
        if end is not None and pts:
            pts[-1][1] = int(end)
        st.setdefault("ramps", {})[key] = {"shape": "curve", "points": pts}
    else:
        st.setdefault("ramps", {})[key] = {"end": int(end if end is not None else cur[0]), "shape": shape}
    _queue_save(app); _ramp_desc(app, st); app._tl_dirty = True; refresh_sent(app)
    if shape != cur[1]:
        refresh_ramps(app, st)


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


# --- editing a step live: the card's EFFECT, the side panel's twin -----------------------------------
# With "edit live" on, the sim IS the selected step: it is loaded, and whatever then changes in the engine - from the
# card's EFFECT here or from the side panel, they call the same handlers - is written back into the step once it
# settles (one undo step a drag, as the numbers are). Both views show the engine; each takes the values it is not
# itself being dragged in. Off, the sim is free again (Add from the sim needs it so). While the show plays (or is
# held at a time) the step edited is the one on the playhead, the selection following it; what its ramps move is
# left out of what is written (_unramped), and nothing is written during a blend between two steps.
SYNC_EVERY = 0.25                                         # s between looks at the engine for changes to keep


def _build_fx(app, c):
    """The card's EFFECT section (hidden until editing): the layers, the effect and palette, the sliders and checks,
    the layer's mirroring and blend - the side panel's controls, for the selected step."""
    with dpg.group(tag="seq_fx", show=False):
        with dpg.group(horizontal=True):
            typeface.label(dpg.add_text("EFFECT", color=c.ACCENT))
            dpg.add_text("", tag="seq_fx_note", color=c.DIM)
        body = dpg.add_group(tag="seq_fx_body")
        dpg.push_container_stack(body)
        with form.row("layer", tip="the step's segments - layers, each its own effect, drawn one over another; the "
                                   "controls below are the chosen one's"):
            dpg.add_combo([], tag="seq_layer", width=-px(70), callback=lambda s, v: (app.seg_pick(v), refresh_fx(app)))
            dpg.add_button(label="+", small=True, callback=lambda: (app.seg_add(), refresh_fx(app)))
            c.tip("a layer more (the right half, as the side panel adds one)")
            dpg.add_button(label="-", small=True, callback=lambda: (app.seg_remove(), refresh_fx(app)))
            c.tip("the last layer away")
        with form.row("effect"):
            dpg.add_combo([], tag="seq_fx_combo", width=-1, callback=lambda s, v: _set_effect(app, v))
        with form.row("palette"):
            dpg.add_combo([], tag="seq_pal_combo", width=-1, callback=lambda s, v: _set_palette(app, v))
        dpg.add_group(tag="seq_params")
        dpg.add_group(tag="seq_opts")
        dpg.pop_container_stack()


def _set_effect(app, v):
    app.on_effect(None, v)
    if dpg.does_item_exist("fx_combo"):
        dpg.set_value("fx_combo", v)                      # the panel's combo: its callback did not run, ours did
    refresh_fx(app)


def _set_palette(app, v):
    app.on_palette(None, v)
    app.sync_palette_combo()


def _set_option(app, key, val):
    app.on_seg_option(key, val)
    app.rebuild_seg_fields()                              # the panel's own checkboxes show it too


def _fx_sig(app):
    """What the card's controls are built for: the effect, the layer and how many, whether the layer is 2-D."""
    e = app.eng
    try:
        x0, y0, x1, y1, op, fx, bm = e.seg_get(e.seg)
    except Exception:
        y0 = y1 = 0
    return (e.idx, e.seg, e.seg_count(), y1 - y0 > 1, len(e.names))


def refresh_fx(app):
    """The card's EFFECT built again for what the engine holds now (the values then follow in _sync_fx)."""
    if not dpg.does_item_exist("seq_fx"):
        return
    e = app.eng
    labels = app.seg_labels()
    dpg.configure_item("seq_layer", items=labels)
    dpg.set_value("seq_layer", labels[e.seg] if e.seg < len(labels) else "")
    dpg.configure_item("seq_fx_combo", items=e.names)
    dpg.set_value("seq_fx_combo", e.names[e.idx] if 0 <= e.idx < len(e.names) else "")
    dpg.configure_item("seq_pal_combo", items=[p[0] for p in e.palette_list()])
    dpg.set_value("seq_pal_combo", app.palette_name_for(e.pal))
    dpg.delete_item("seq_params", children_only=True)
    dpg.delete_item("seq_opts", children_only=True)
    num.prune()
    app.param_rows("seq_params", prefix="seqp_")
    x0, y0, x1, y1, op, fx, bm = e.seg_get(e.seg)
    is2d = y1 - y0 > 1
    o = e.seg_options(e.seg)
    rows = [(("mi", "mirror"), ("rev", "reverse")) + ((("tp", "swap XY"),) if is2d else ())]
    if is2d:
        rows.append((("mY", "mirror Y"), ("rY", "reverse Y")))
    for row in rows:
        with form.under(parent="seq_opts"):
            for key, label in row:
                dpg.add_checkbox(label=label, tag=f"seqo_{key}", default_value=bool(o[key]), user_data=key,
                                 callback=lambda s, v, u: _set_option(app, u, bool(v)))
    if e.seg_count() > 1:
        with form.row("opacity", parent="seq_opts"):
            num.add("seqo_opacity", op, 0, 255, integer=True, width=-1,
                    callback=lambda s, v: app.on_seg_field(s, v, "opacity"))
        modes = e.BLEND_MODES
        with form.row("blend mode", parent="seq_opts", tip="how this layer lands on the ones under it"):
            dpg.add_combo(modes, tag="seqo_blend", width=-1, default_value=modes[bm if bm < len(modes) else 0],
                          callback=lambda s, v: (app.on_seg_blend(modes.index(v)), app.rebuild_seg_fields()))
    app._seq_fx_sig = _fx_sig(app)


def _sync_fx(app):
    """Both views to the engine's values: the card's and the panel's sliders, checks, palette and the layer's
    options - each one not being dragged or typed in. An effect, a layer or the layers changed: the card again."""
    e = app.eng
    if _fx_sig(app) != getattr(app, "_seq_fx_sig", None):
        refresh_fx(app)
    for k in ("sx", "ix", "c1", "c2", "c3"):
        v = int(e.fx.get(k, 0))
        for tag in (f"inp_{k}", f"seqp_{k}"):
            if dpg.does_item_exist(tag) and not dpg.is_item_active(tag) and int(dpg.get_value(tag)) != v:
                num.set(tag, v)
    for k in ("o1", "o2", "o3"):
        v = bool(e.fx.get(k, 0))
        for tag in (f"inp_chk_{k}", f"seqp_chk_{k}"):
            if dpg.does_item_exist(tag) and bool(dpg.get_value(tag)) != v:
                dpg.set_value(tag, v)
    name = app.palette_name_for(e.pal)
    for tag in ("seq_pal_combo", "pal_combo"):
        if dpg.does_item_exist(tag) and dpg.get_value(tag) != name:
            dpg.set_value(tag, name)
    o = e.seg_options(e.seg)
    for key in ("mi", "rev", "tp", "mY", "rY"):
        tag = f"seqo_{key}"
        if dpg.does_item_exist(tag) and bool(dpg.get_value(tag)) != bool(o[key]):
            dpg.set_value(tag, bool(o[key]))


def _edit_index(app):
    """The step Edit live edits now: the selected one, or while the show plays (or is held at a time) the one on
    the playhead - the one the sim shows. None while not editing, and during a blend between two steps (the sim
    shows neither then)."""
    if not getattr(app, "_seq_edit", False) or getattr(app, "_transition", None) is not None:
        return None
    if getattr(app, "_seq_play", None) is not None:
        return _play_i(app)
    return getattr(app, "_seq_sel", 0)


def _editable(app):
    return _edit_index(app) is not None


def _unramped(segs, st):
    """The engine's segments with every slider the step's ramps move put back to the step's own value: while the
    show plays a ramp moves it each frame, and that is the playback, not an edit to keep - nor is a slider being
    recorded (it goes in as a curve once the take is done)."""
    ramps = list(st.get("ramps") or {}) + [k for (s_, k) in _REC.takes if s_ == id(st)]
    if not ramps:
        return segs
    out = json.loads(json.dumps(segs))
    own = st.get("segments") or []
    for k in ramps:
        seg, slider = sequence.ramp_target(k)
        if 0 <= seg < min(len(out), len(own)):
            mine = (own[seg].get("params") or {}).get(slider)
            if mine is not None:
                out[seg].setdefault("params", {})[slider] = mine
    return out


def toggle_edit(app, on):
    if not on:
        edit_commit(app)                                  # a change of the last quarter second: kept
    app._seq_edit = bool(on)
    app._seq_edit_step = None                             # loaded on the next poll
    if dpg.does_item_exist("seq_fx"):
        dpg.configure_item("seq_fx", show=bool(on))
    if on:
        app.gp.status("editing the selected step live: the sim shows it, and changes here or in the side panel go into it")
    else:
        _flush_save(app, now=True)
        app.gp.status("the sim is free again: the step keeps what it was given")


def _edit_poll(app):
    """The step and the sim kept as one while editing: the selected step loaded when it is not the one shown, the
    engine's state written into it when it changes, both views kept to the engine."""
    if not getattr(app, "_seq_edit", False):
        return
    if not (app.docked("sequence") or (dpg.does_item_exist(TAG) and dpg.is_item_shown(TAG))):
        # the frame closed: off - the side panel went on writing into a step nothing on screen showed
        if dpg.does_item_exist("seq_edit"):
            dpg.set_value("seq_edit", False)
        toggle_edit(app, False)
        return
    if dpg.does_item_exist("seq_edit") and not dpg.get_value("seq_edit"):
        dpg.set_value("seq_edit", True)
    steps = _steps(app)["steps"]
    sel = _edit_index(app)
    if sel is None or not (0 <= sel < len(steps)):
        app._seq_look_due = None                          # blending between steps: no look of an edit gathered meanwhile
        app._seq_edit_step = None                         # (the last change was kept): the next step taken up after it
        _fx_body(app, False, getattr(app, "_seq_sel", 0))
        return
    playing = getattr(app, "_seq_play", None) is not None
    if playing and getattr(app, "_seq_sel", -1) != sel:
        select(app, sel)                                  # playing: the selection follows the playhead, card and all
    _fx_body(app, True, sel)
    st = steps[sel]
    now = time.perf_counter()
    if getattr(app, "_seq_edit_step", None) is not st:
        edit_commit(app)                                  # another step: the last change kept in the one left
        _flush_save(app, now=True)
        if not playing:
            load_step(app, sel, quiet=True)               # playing, the show has loaded it already (and its blend)
        app._seq_edit_step = st
        app._seq_edit_base = (_unramped(app.eng.segments(), st), [int(c) for c in app.seg_cols])
        app._seq_edit_at = now
        refresh_fx(app)
        if dpg.does_item_exist("seq_fx_note"):
            dpg.set_value("seq_fx_note", f"step {sel + 1}, live{' on the playhead' if playing else ''} - here or in the side panel")
        return
    _sync_fx(app)
    if now - getattr(app, "_seq_edit_at", 0.0) < SYNC_EVERY:
        due = getattr(app, "_seq_look_due", None)
        if due is not None and now >= due and not num.busy():
            app._seq_look_due = None
            _gather_look(app, st)                         # its look again, once the changes have settled
            app._seq_look["edit"] = True
        return
    app._seq_edit_at = now
    edit_commit(app)


def edit_commit(app):
    """The engine's segments and colours into the step being edited, when they changed since last time: from
    the poll (a quarter second apart), and from whatever is about to load something else into the sim - another
    step selected, editing turned off, play and seek - so the last change before it is kept."""
    st = getattr(app, "_seq_edit_step", None)
    if st is None or not getattr(app, "_seq_edit", False) or not any(s is st for s in _steps(app)["steps"]):
        return
    cur = (_unramped(app.eng.segments(), st), [int(c) for c in app.seg_cols])
    if cur == getattr(app, "_seq_edit_base", None):
        return
    app._seq_edit_base = cur
    segs, cols = cur
    old = (st.get("segments") or [{}])[0].get("effect")
    st["segments"] = json.loads(json.dumps(segs))
    st["colors"] = list(cols)
    if st.get("name") == old and segs:                    # a name that was its effect's follows the effect
        st["name"] = segs[0].get("effect") or st.get("name")
    app._seq_look_due = time.perf_counter() + 1.2
    _queue_save(app)
    app._tl_dirty = True
    app._seq_rows_dirty = True


def _fx_body(app, editable, sel):
    """The EFFECT controls shown while they edit the step; during a blend between two steps they edit nothing (the
    sim shows neither), so they are put away for it and the note says so."""
    if not dpg.does_item_exist("seq_fx_body") or dpg.is_item_shown("seq_fx_body") == editable:
        return
    dpg.configure_item("seq_fx_body", show=editable)
    dpg.set_value("seq_fx_note", f"step {sel + 1}, live - here or in the side panel" if editable else
                  "blending into the next step - it is edited once the blend is done")


def _gather_look(app, st):
    """The sim's frames for a moment, from now, as the step's look - while the sim goes on showing the effect it
    showed when this began (another effect picked meanwhile: the gathering stops, the look as it was)."""
    app._seq_look = {"st": st, "idx": app.eng.idx, "until": time.perf_counter() + LOOK_SPAN, "next": 0.0, "frames": []}


def _take_look(app):
    g = getattr(app, "_seq_look", None)
    if g is None:
        return
    i = _edit_index(app)
    steps_ = _steps(app)["steps"]
    if g.get("edit") and (i is None or not (0 <= i < len(steps_)) or steps_[i] is not g.get("st")):
        app._seq_look = None                              # an edit's look, and the sim taken over meanwhile: dropped
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


# AI: below section was generated by an AI
def dropped(app, data, row):
    """Something let go on the step list: on a row (`row`), or below the rows (None, the end). A step's row moves
    there; an effect's tile from the Library ("fx", name, graph file) is a new step there."""
    if isinstance(data, (list, tuple)) and len(data) >= 2 and data[0] == "fx":
        add_effect(app, data[1], at=row)
        return
    if isinstance(data, int):
        move_to(app, data, len(_steps(app)["steps"]) - 1 if row is None else row)


def add_effect(app, name, at=None):
    """An effect (a Library tile dropped on the list) as a new step at `at` - its row's place, or the end: the sim
    runs it, and the step is what the sim then shows, as "Add what the sim shows" makes one, its look gathered over
    the next moment. A show playing stops first (the sim is the new step's); a step being edited live keeps its last
    change and is let go, so the switch is not written into it."""
    if name not in (app.eng.names or []):
        app.gp.status(f"{name}: not in the sim's effects - click its tile to build it, then drag it")
        return
    if getattr(app, "_seq_play", None) is not None:
        stop(app)
    if getattr(app, "_seq_edit", False):
        edit_commit(app)
        app._seq_edit_step = None                     # the next poll loads the new step, which is the sim already
    app.on_effect(None, name)
    if dpg.does_item_exist("fx_combo"):
        dpg.set_value("fx_combo", name)
    S = _steps(app)
    st = sequence.capture(app.eng, app.seg_cols, 255, "", 10.0, 0.7)
    n = len(S["steps"])
    at = n if at is None else max(0, min(n, int(at)))
    S["steps"].insert(at, st)
    app._seq_sel = at
    _gather_look(app, st)
    _save(app)
    app.gp.status(f"step {at + 1} added from the Library: {st['name']}")
# AI: end


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
    left = p["paused"] if p.get("paused") is not None else max(0.0, p["next"] - clock.now())
    return starts[p["i"]] + float(steps[p["i"]].get("dur", 10)) - left


def play(app, i=0, offset=0.0):
    """The show from step i (offset seconds into it), the sim following it."""
    edit_commit(app)                                      # the step being edited keeps its last change first
    _rec_flush(app)
    S = _steps(app)
    if not S["steps"]:
        app.gp.status("no steps to play"); return
    i = max(0, min(len(S["steps"]) - 1, int(i)))
    dur = float(S["steps"][i].get("dur", 10))
    app._transition = None
    app._seq_play = {"i": i, "next": clock.now() + max(0.05, dur - offset), "paused": None,
                     "st": S["steps"][i], "n": len(S["steps"])}
    app.playing = True
    live = getattr(app, "live", None)
    if live is not None and hasattr(live, "t0"):
        live.t0 = clock.now() - (_starts(app)[0][i] + offset)   # the WAV from the same moment, with the sequence
    load_step(app, i, quiet=True)
    _sync_transport(app)
    refresh(app)


def play_pause(app):
    """The transport's button: play from the selected step; while playing, pause; paused, go on."""
    p = getattr(app, "_seq_play", None)
    if p is None:
        play(app, getattr(app, "_seq_sel", 0))
    elif p.get("paused") is None:
        _rec_flush(app)                                   # a take ends with the pause
        p["paused"] = max(0.0, p["next"] - clock.now())
        app.playing = False
        app.gp.status("sequence paused")
    else:
        p["next"] = clock.now() + p["paused"]; p["paused"] = None
        app.playing = True
        live = getattr(app, "live", None)
        if live is not None and hasattr(live, "t0"):
            live.t0 = clock.now() - (position(app) or 0.0)
    _sync_transport(app)


def seek(app, t):
    """The show at t seconds: its step in the sim, playing on from there (or held there while paused or stopped)."""
    edit_commit(app)
    _rec_flush(app)
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
    app._seq_play = {"i": i, "next": clock.now() + left, "paused": left if held else None,
                     "st": S["steps"][i], "n": len(S["steps"])}
    app.playing = not held
    live = getattr(app, "live", None)
    if live is not None and hasattr(live, "t0"):
        live.t0 = clock.now() - t
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
    _rec_flush(app)                                       # a take ends with the show, and recording with it
    if _REC.armed:
        _REC.armed = False
        _rec_button(app)
    app._transition = None
    app._seq_bri = None
    app._seq_edit_step = None                             # editing: the selected step shown again (not the last played)
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
    segment is the one shown - and the step's brightness (or its ramp). A slider being recorded is the hand's."""
    steps = _steps(app)["steps"]
    if not (0 <= i < len(steps)):
        return
    st = steps[i]
    ramps = st.get("ramps") or {}
    app._seq_bri = sequence.ramp_value(st, sequence.BRI, t) if sequence.BRI in ramps else int(st.get("bri", 255))
    changed = False
    for k in ramps:
        if k == sequence.BRI or k in _REC.held:
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
    _flush_save(app)
    _poll_audio(app)
    _edit_poll(app)
    _poll_send(app)
    _take_look(app)
    if dpg.is_item_shown(TAG):
        _hold_scroll(app)
        if not overview_mouse(app) and not grip_mouse(app) and not audio_mouse(app):
            timeline_mouse(app)
        _follow_head(app)
        fw = (dpg.get_item_rect_size(TAG)[0], _c().scrollbar_w(TAG))
        if fw[0] and fw != getattr(app, "_tl_frame_w", None):
            app._tl_frame_w = fw; app._tl_dirty = True          # laid out, resized, a scrollbar come or gone: it follows
            app._seq_rows_dirty = True                          # the names fitted to the new width too
        if getattr(app, "_seq_rows_dirty", False) and not num.busy():   # not under a number being typed in: it waits
            app._seq_rows_dirty = False; refresh(app)
        pl = getattr(app, "_seq_play", None)
        state = (pl is not None, pl is not None and pl.get("paused") is not None, pl["i"] if pl is not None else None)
        if getattr(app, "_tl_dirty", True) or getattr(app, "_tl_hover_was", None) != getattr(app, "_tl_hover", None)                 or state != getattr(app, "_tl_state_was", None) or (pl is not None and not dpg.does_item_exist("seq_tl_head")):
            draw_timeline(app); draw_overview(app); app._tl_dirty = False; app._tl_hover_was = getattr(app, "_tl_hover", None)
            app._tl_state_was = state
        elif getattr(app, "_seq_play", None) is not None:
            _move_head(app); _move_ov_head(app); _move_au_head(app)   # playing: the playheads move, the rest stays (redrawn every
                                                            # frame it was 2 ms of each)
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
    now = clock.now()
    if now >= p["next"]:
        i = p["i"] + 1
        if i >= len(steps):
            if int(S.get("repeat", 0)) != 0 or p.get("once"):
                stop(app); app.gp.status("sequence done"); return
            i = 0
            live = getattr(app, "live", None)
            if live is not None and hasattr(live, "t0"):
                live.t0 = now                                # round again: the WAV from its start with it
        edit_commit(app)                                  # editing live: the step leaving keeps its last change
        _rec_flush(app)                                   # recording: the take on the step leaving goes into it
        prev = steps[p["i"]] if 0 <= p["i"] < len(steps) else None
        p["i"] = i
        p["st"], p["n"] = steps[i], len(steps)
        app._tl_dirty = True                                # the step playing is underlined: drawn again
        p["next"] = now + float(steps[i].get("dur", 10))
        trans = float(steps[i].get("trans", sequence.TRANS_DEFAULT))       # as the device's playlist blends it
        if prev is not None and trans > 0:
            app.transition_start(prev, trans, S.get("style", "fade"))
        load_step(app, i, quiet=True)
        _REC.applied = None                               # the next step's values are playback's, not the hand's
        app._seq_rows_dirty = True
    i = p["i"]
    if 0 <= i < len(steps):
        dur = float(steps[i].get("dur", 10)) or 1.0
        t = 1.0 - max(0.0, p["next"] - now) / dur
        _rec_poll(app, i, t)
        _apply_ramps(app, i, t)
        _REC.applied = (i, app.eng.idx, app.eng.seg, dict(app.eng.fx))   # what playback left: a difference next frame is the hand's


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
        d = float(s.get("dur", 10)); spans.append((t, d, float(s.get("trans", sequence.TRANS_DEFAULT)))); t += d
    return x0, y0, w, h, max(t, _extent(app)) if t > 0 else t, spans


def _lanes(h):
    """The timeline's bands, top to bottom: (ruler bottom, blocks top, blocks bottom)."""
    return px(RULER_H), px(RULER_H) + 2, h - px(BEAT_LANE) - 2


def _ruler_step(total, w):
    """Seconds between the ruler's labelled ticks: the first of the usual steps that leaves room for the labels."""
    for s in (0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300):
        if s * w / max(total, 1e-6) >= px(46):
            return s
    return 600


WAVE_RES = 20000             # the WAV's loudness kept at this many points (fewer for a short file)


def _wave(app):
    """The WAV's loudness, 0..1, at WAVE_RES points across the file, as a running sum (a column's mean is then two
    reads, whatever the zoom): made once a file - made for each zoom, a long file stalled every wheel notch."""
    from native import audio
    live = getattr(app, "live", None)
    if not isinstance(live, audio.FileAudio):
        return None
    if getattr(app, "_wave_key", None) != id(live):
        res = max(1, min(WAVE_RES, len(live.samples) // 16))
        n = len(live.samples) // res
        if n < 1:
            return None
        a = np.abs(live.samples[:n * res].reshape(res, n)).mean(1)
        a = a / (a.max() or 1.0)
        app._wave_key, app._wave = id(live), np.concatenate([[0.0], np.cumsum(a)])
    return app._wave


def wave_columns(cs, seconds, t0, sx, w, end, every=2):
    """The wave's columns on the timeline: (x, loudness 0..1) every `every` pixels from its left edge to `end`
    seconds, each the mean of the loudness over the time the column covers. `cs` is _wave's running sum over
    the file's `seconds`."""
    res = len(cs) - 1
    if res < 1 or seconds <= 0 or sx <= 0:
        return np.zeros(0), np.zeros(0)
    xs = np.arange(0, int(w), every, dtype=np.float64)
    ta = t0 + xs / sx
    keep = ta <= end
    xs, ta = xs[keep], ta[keep]
    tb = np.minimum(ta + every / sx, end)
    i0 = np.clip((ta / seconds * res).astype(int), 0, res - 1)
    i1 = np.clip(np.ceil(tb / seconds * res).astype(int), i0 + 1, res)
    return xs, (cs[i1] - cs[i0]) / (i1 - i0)


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


# AI: below section was generated by an AI
# --- the timeline's view: where it starts and how much of the show it shows -----------------------
def _tl_height(app):
    """The timeline's height on screen: as its grip left it (prefs "seq_tl_h", at the interface size 1), else TL_H."""
    try:
        h = float(app.prefs.get("seq_tl_h", TL_H))
    except (TypeError, ValueError):
        h = TL_H
    return px(max(TL_H_MIN, min(TL_H_MAX, h)))


def _set_pref(app, key, value):
    from native.project import save_prefs
    app.prefs[key] = value
    save_prefs(app.prefs)


def _view(app, total, w):
    """(t0, sx): the time at the timeline's left edge and its pixels a second. The whole show until it is zoomed;
    zoomed, app._tl_view {"t0", "span"} is kept inside the show (and the show's length, should it shrink)."""
    v = getattr(app, "_tl_view", None)
    if not v or total <= 0 or v["span"] >= total:
        if v is not None and total > 0 and v["span"] >= total:
            app._tl_view = None
        return 0.0, w / max(total, 1e-6)
    span = max(MIN_SPAN, float(v["span"]))
    t0 = max(0.0, min(total - span, float(v["t0"])))
    v["span"], v["t0"] = span, t0
    return t0, w / span


def _span_now(app):
    """(t0, span, total) the timeline shows now."""
    total = _extent(app) if _starts(app)[1] > 0 else 0.0
    v = getattr(app, "_tl_view", None)
    if not v or total <= 0:
        return 0.0, total, total
    span = max(MIN_SPAN, min(total, float(v["span"])))
    return max(0.0, min(total - span, float(v["t0"]))), span, total


def set_view(app, t0, span):
    """The timeline to show `span` seconds from `t0`: the whole show again when that is all of it."""
    total = _extent(app) if _starts(app)[1] > 0 else 0.0
    if total <= 0:
        return
    span = max(MIN_SPAN, float(span))
    if span >= total - 1e-6:
        app._tl_view = None
    else:
        app._tl_view = {"t0": max(0.0, min(total - span, float(t0))), "span": span}
    app._tl_dirty = True


def zoom(app, factor, at=None):
    """Zoomed in by `factor` (below 1: out), the time `at` (the middle when not given) staying where it is."""
    t0, span, total = _span_now(app)
    if total <= 0:
        return
    at = t0 + span / 2 if at is None else at
    new = max(MIN_SPAN, min(total, span / factor))
    set_view(app, at - (at - t0) * new / max(span, 1e-6), new)


def fit_all(app):
    app._tl_view = None
    app._tl_dirty = True


def fit_step(app, i=None):
    """The step (the selected one) across the timeline, a twentieth of it either side."""
    starts, total = _starts(app)
    i = getattr(app, "_seq_sel", 0) if i is None else i
    if not (0 <= i < len(starts)):
        return
    d = float(_steps(app)["steps"][i].get("dur", 10))
    set_view(app, starts[i] - d * 0.05, d * 1.1)


def _into_view(app, i):
    """A step selected off the zoomed timeline (in the list, say) brought onto it, its start a tenth in."""
    if getattr(app, "_tl_view", None) is None:
        return
    starts, total = _starts(app)
    if not (0 <= i < len(starts)):
        return
    t0, span, _ = _span_now(app)
    d = float(_steps(app)["steps"][i].get("dur", 10))
    if starts[i] + d < t0 or starts[i] > t0 + span:
        set_view(app, starts[i] - span * 0.1, span)


def _follow_head(app):
    """Playing and zoomed, with follow on: the page turned when the playhead reaches the timeline's right edge (or
    is behind its left), as an arrangement view does - not every frame, so the blocks stand still to be read."""
    if getattr(app, "_tl_view", None) is None or not app.prefs.get("seq_follow", True):
        return
    p = getattr(app, "_seq_play", None)
    if p is None or p.get("paused") is not None or getattr(app, "_tl_drag", None) is not None:
        return
    at = position(app)
    if at is None:
        return
    t0, span, _ = _span_now(app)
    if at > t0 + span * 0.98 or at < t0:
        set_view(app, at - span * 0.02, span)


def _over(tag):
    """The pointer over a drawlist of the frame (its rectangle, while it is shown)."""
    if not dpg.does_item_exist(tag) or not dpg.is_item_visible(tag):
        return False
    (x0, y0), (w, h) = dpg.get_item_rect_min(tag), dpg.get_item_rect_size(tag)
    mx, my = dpg.get_mouse_pos(local=False)
    return x0 <= mx <= x0 + w and y0 <= my <= y0 + h


def _hold_scroll(app):
    """The frame does not scroll with the wheel while the pointer is over the timeline or its strip and the wheel is
    theirs - zoomed in (it moves along the time), or with Ctrl (it zooms): it moved the frame under them as well.
    The whole show shown, the plain wheel scrolls the frame as it does anywhere in it."""
    ctrl = dpg.is_key_down(dpg.mvKey_LControl) or dpg.is_key_down(dpg.mvKey_RControl)
    zoomed = getattr(app, "_tl_view", None) is not None
    over = (zoomed or ctrl) and any(_over(t) for t in ("seq_tl", "seq_tl_ov", "seq_tl_grip", "seq_tl_audio"))
    if over != getattr(app, "_tl_held", False):
        app._tl_held = over
        dpg.configure_item(TAG, no_scroll_with_mouse=over)


def wheel(app, delta):
    """The wheel over the timeline or its strip: along the time; with Ctrl, a zoom at the pointer. True when it was
    the timeline's."""
    if not dpg.does_item_exist(TAG) or not dpg.is_item_shown(TAG) or not _has_steps(app):
        return False
    if not (_over("seq_tl") or _over("seq_tl_ov") or _over("seq_tl_audio")):
        return False
    t0, span, total = _span_now(app)
    if total <= 0:
        return True
    ctrl = dpg.is_key_down(dpg.mvKey_LControl) or dpg.is_key_down(dpg.mvKey_RControl)
    if ctrl:
        g = _tl_geometry(app)
        at = None
        if g is not None and _over("seq_tl"):
            mx = dpg.get_mouse_pos(local=False)[0]
            at = t0 + (mx - g[0]) / max(1.0, g[2]) * span
        zoom(app, ZOOM_STEP ** (1 if delta > 0 else -1), at)
    elif getattr(app, "_tl_view", None) is not None:
        set_view(app, t0 - (1 if delta > 0 else -1) * span * 0.12, span)
    else:
        return False                                      # the whole show shown: the frame's to scroll
    return True


def _zoom_words(app):
    if not dpg.does_item_exist("seq_zoom_words"):
        return
    t0, span, total = _span_now(app)
    if total <= 0 or getattr(app, "_tl_view", None) is None:
        dpg.set_value("seq_zoom_words", "the whole show" if total > 0 else "")
    else:
        dpg.set_value("seq_zoom_words", f"{_fmt_t(t0)} - {_fmt_t(t0 + span)} of {_fmt_t(total)}")


def _last_colour(st):
    cols = sequence.look_colours(st)
    return cols[-1] if cols else (70, 76, 90)


def draw_timeline(app):
    """The steps as blocks of their own colours along the time, names and lengths on them, the blend into each as a
    wedge from the colour before, the ramps' curves in their lower half; the ruler with the time; the bars at the
    tempo; the beats found in the WAV as ticks; the WAV's wave; the playhead; where a dragged step would land. All of
    it through the view (_view): the part of the show the timeline shows, at its zoom."""
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
            for t in ("seq_tl", "seq_tl_ov", "seq_tl_grip", "seq_tl_audio"):
                if dpg.does_item_exist(t):
                    dpg.configure_item(t, width=want)
            w = want
    _zoom_words(app)
    rb, top, bot = _lanes(h)
    dl = "seq_tl"
    dpg.draw_rectangle((0, 0), (w, h), color=(0, 0, 0, 0), fill=(0, 0, 0, 70), parent=dl)
    dpg.draw_rectangle((0, 0), (w, rb), color=(0, 0, 0, 0), fill=(255, 255, 255, 10), parent=dl)
    if total <= 0:
        typeface.draw_text((px(8), top + (bot - top) / 2 - px(8)), "the timeline: the steps along the time - add one from the sim",
                           px(14), color=c.DIM, parent=dl)
        draw_audio(app, 0.0, w / max(_extent(app), 1.0), 0.0)
        return
    t0, sx = _view(app, total, w)
    t1 = t0 + w / sx

    def X(t):
        return (t - t0) * sx
    steps = _steps(app)["steps"]
    # the WAV's wave, faint behind the blocks (the WAV plays from 0 when the sequence starts)
    from native import audio
    live = getattr(app, "live", None)
    if isinstance(live, audio.FileAudio) and live.seconds > 0:
        cs = _wave(app)
        if cs is not None:
            mid = (top + bot) / 2
            xs, amp = wave_columns(cs, live.seconds, t0, sx, w, min(live.seconds, total))   # as far as the sequence goes
            for x, a in zip(xs.tolist(), (amp * (bot - top) * 0.5).tolist()):
                dpg.draw_line((x, mid - a), (x, mid + a), color=(255, 255, 255, 34), thickness=1, parent=dl)
    # the steps (those on screen; the one before the first keeps its colour for the blend into it)
    sel = min(getattr(app, "_seq_sel", 0), len(spans) - 1)
    hover = getattr(app, "_tl_hover", None)
    prev_end = None
    for i, (t, d, tr) in enumerate(spans):
        st = steps[i]
        if t + d < t0 or t > t1:
            prev_end = _last_colour(st)
            continue
        a, b = X(t) + 1, X(t + d) - 1
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
        # its name, shortened to fit, kept at the timeline's left edge when the block starts before it; its length
        # on the right where there is room
        la, lb = max(a, 0.0), min(b, float(w))
        room = lb - la - px(10)
        name = str(st.get("name", ""))
        length = f"{d:.1f}s" if d < 10 else f"{d:.0f}s"
        lw = typeface.measure(length, "mono", px(11))
        if room > lw + px(30):
            typeface.draw_text((lb - lw - px(5), top + px(3)), length, px(11), face="mono", color=(230, 233, 240, 170), parent=dl)
            room -= lw + px(8)
        if room > px(14):
            shown = _fit_measured(name, room, px(13))
            typeface.draw_text((la + px(5), top + px(2)), shown, px(13), color=(245, 247, 250, 240), parent=dl)
        # the ramps: each a curve over the block's lower half, the brightness dashed - finer the wider it is drawn
        rtop, rbot = _ramp_band(top, bot)
        n = int(max(24, min(400, (b - a) / 4)))
        for j, k in enumerate(st.get("ramps") or {}):
            if b - a < 12:
                break
            pts = [(a + 2 + (b - a - 4) * q / n, rbot - (rbot - rtop) * sequence.ramp_value(st, k, q / n) / 255.0) for q in range(n + 1)]
            dpg.draw_polyline(pts, color=(255, 255, 255, 230 - 45 * j) if k != sequence.BRI else (255, 220, 120, 220),
                              thickness=2, parent=dl)
        # the selected one outlined; the one playing underlined; a curve's points on it, as handles
        if i == sel:
            dpg.draw_rectangle((a, top), (b, bot), color=c.ACCENT, thickness=2, parent=dl)
            for _k, _j, hx, hy in _curve_handles(app, st, a, b, top, bot):
                dpg.draw_circle((hx, hy), px(4), color=(255, 255, 255, 230), fill=tuple(c.ACCENT[:3]) + (255,),
                                thickness=1.5, parent=dl)
        if i == _play_i(app):
            dpg.draw_rectangle((a, bot - px(3)), (b, bot), color=(0, 0, 0, 0), fill=(255, 255, 255, 230), parent=dl)
    # the bars at the tempo, faint across everything; the bars' numbers on the ruler where there is room
    bl = _barlen(app)
    end_w = typeface.measure(_fmt_t(total), "mono", px(10)) + px(10)     # the end's time keeps the ruler's right end
    if bl and bl * sx >= 4:
        nbar = int(t0 // bl)
        every = max(1, int(np.ceil(px(28) / (bl * sx))))
        t = nbar * bl
        nbar += 1
        while t <= min(total, t1) + 1e-6:
            x = X(t)
            dpg.draw_line((x, rb), (x, bot), color=(255, 255, 255, 26), thickness=1, parent=dl)
            if (nbar - 1) % every == 0 and x >= 0 and x + px(16) < w - end_w:
                typeface.draw_text((x + 2, 1), str(nbar), px(10), face="mono", color=(255, 210, 120, 150), parent=dl)
            t += bl; nbar += 1
    # the ruler: ticks and the time
    rs = _ruler_step(w / sx, w)
    t = np.floor(t0 / rs) * rs
    while t <= min(total, t1) + 1e-6:
        x = X(t)
        if x >= -1:
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
        if t0 <= bt <= min(total, t1):
            dpg.draw_line((X(bt), h - px(BEAT_LANE)), (X(bt), h - 1), color=(255, 200, 80, 150), thickness=1, parent=dl)
    # where a dragged step would go
    drag = getattr(app, "_tl_drag", None)
    if drag and drag[0] == "move" and drag[3] is not None:
        j = drag[3]
        xs = [X(st_) for st_, _, _ in spans] + [X(total)]
        x = xs[j] if j <= drag[1] else xs[min(len(xs) - 1, j + 1)]
        dpg.draw_line((x, top - 2), (x, bot + 2), color=c.ACCENT, thickness=px(3), parent=dl)
    # the playhead, with its time
    at = position(app)
    app._tl_scale = (sx, h, t0)                             # for _move_head, between redraws
    if at is not None:
        x = X(at)
        dpg.draw_line((x, 0), (x, h), color=(255, 255, 255, 240), thickness=2, parent=dl, tag="seq_tl_head")
        dpg.draw_triangle((x - px(5), 0), (x + px(5), 0), (x, px(7)), color=(0, 0, 0, 0), fill=(255, 255, 255, 240), parent=dl,
                          tag="seq_tl_head_tri")
    elif hover and hover[0] == "ruler":
        x = X(hover[1])
        dpg.draw_line((x, 0), (x, h), color=(255, 255, 255, 90), thickness=1, parent=dl)
        lab = _fmt_t(hover[1])
        typeface.draw_text((min(x + 3, w - px(30)), rb + 2), lab, px(10), face="mono", color=(255, 255, 255, 200), parent=dl)
    draw_audio(app, t0, sx, total)
    # the grip under it: a short bar in the middle, to drag
    if dpg.does_item_exist("seq_tl_grip"):
        dpg.delete_item("seq_tl_grip", children_only=True)
        gh = px(GRIP_H)
        hot = getattr(app, "_tl_grip", None) is not None or _over("seq_tl_grip")
        dpg.draw_rectangle((w / 2 - px(24), gh / 2 - 1.5), (w / 2 + px(24), gh / 2 + 1.5), color=(0, 0, 0, 0),
                           fill=(255, 255, 255, 150 if hot else 60), rounding=2, parent="seq_tl_grip")


def _move_head(app):
    """The playhead to where the show is now, the rest of the timeline as it was drawn."""
    at, sh = position(app), getattr(app, "_tl_scale", None)
    if at is None or sh is None or not dpg.does_item_exist("seq_tl_head"):
        app._tl_dirty = True
        return
    sx, h, t0 = sh
    x = (at - t0) * sx
    dpg.configure_item("seq_tl_head", p1=(x, 0), p2=(x, h))
    if dpg.does_item_exist("seq_tl_head_tri"):
        dpg.configure_item("seq_tl_head_tri", p1=(x - px(5), 0), p2=(x + px(5), 0), p3=(x, px(7)))


# --- the overview: the whole show, and the box of what the timeline shows -------------------------
def _ov_geometry(app):
    """(x0, y0, w, h, total, spans) of the overview strip, or None."""
    g = _tl_geometry(app)
    if g is None or not dpg.does_item_exist("seq_tl_ov"):
        return None
    (x0, y0) = dpg.get_item_state("seq_tl_ov").get("rect_min") or (0, 0)
    cfg = dpg.get_item_configuration("seq_tl_ov")
    return x0, y0, cfg["width"], cfg["height"], g[4], g[5]


def draw_overview(app):
    """The whole show in a strip: each step its colours, the selected one marked, the playhead, and a box round the
    part the timeline shows (all of it until zoomed)."""
    g = _ov_geometry(app)
    if g is None:
        return
    x0, y0, w, h, total, spans = g
    c = _c()
    dl = "seq_tl_ov"
    dpg.delete_item(dl, children_only=True)
    dpg.draw_rectangle((0, 0), (w, h), color=(0, 0, 0, 0), fill=(0, 0, 0, 90), parent=dl)
    if total <= 0:
        return
    k = w / total
    steps = _steps(app)["steps"]
    sel = getattr(app, "_seq_sel", -1)
    for i, (t, d, tr) in enumerate(spans):
        _fill_look(steps[i], t * k, (t + d) * k - (1 if d * k > 3 else 0), 3, h - 3, dl, 200)
        if i == sel:
            dpg.draw_rectangle((t * k, h - 3), ((t + d) * k, h), color=(0, 0, 0, 0), fill=c.ACCENT, parent=dl)
    at = position(app)
    app._ov_scale = (k, h)                                  # for _move_ov_head, between redraws
    if at is not None:
        dpg.draw_line((at * k, 0), (at * k, h), color=(255, 255, 255, 230), thickness=1.5, parent=dl, tag="seq_ov_head")
    t0, span, _ = _span_now(app)
    a, b = t0 * k, (t0 + span) * k
    dpg.draw_rectangle((0, 0), (a, h), color=(0, 0, 0, 0), fill=(0, 0, 0, 120), parent=dl)       # what is off the timeline,
    dpg.draw_rectangle((b, 0), (w, h), color=(0, 0, 0, 0), fill=(0, 0, 0, 120), parent=dl)       # darker
    dpg.draw_rectangle((a, 0.5), (max(a + 3, b), h - 0.5), color=(255, 255, 255, 200), thickness=1.5, rounding=2, parent=dl)


def _move_ov_head(app):
    """The overview's playhead to where the show is now, the strip as it was drawn (drawn again when it has none)."""
    at, sc = position(app), getattr(app, "_ov_scale", None)
    if at is None or sc is None or not dpg.does_item_exist("seq_ov_head"):
        if at is not None:
            draw_overview(app)
        return
    k, h = sc
    dpg.configure_item("seq_ov_head", p1=(at * k, 0), p2=(at * k, h))


def overview_mouse(app):
    """The overview's pointer: the box dragged moves the timeline along the show, its sides zoom it; a press
    beside the box brings that part of the show onto the timeline. True while the overview has the mouse."""
    drag = getattr(app, "_tl_ov", None)
    g = _ov_geometry(app)
    if g is None:
        app._tl_ov = None
        return False
    x0, y0, w, h, total, spans = g
    if total <= 0:
        return False
    k = w / total
    mx, my = dpg.get_mouse_pos(local=False)
    t_at = (mx - x0) / k
    t0, span, _ = _span_now(app)
    if drag is not None:
        if not dpg.is_mouse_button_down(dpg.mvMouseButton_Left):
            app._tl_ov = None
            return True
        kind, grab, a0, s0 = drag
        if kind == "box":
            set_view(app, a0 + (t_at - grab), s0)
        elif kind == "left":
            end = a0 + s0
            start = max(0.0, min(end - MIN_SPAN, t_at))
            set_view(app, start, end - start)
        elif kind == "right":
            set_view(app, a0, max(MIN_SPAN, min(total, t_at) - a0))
        return True
    if not (x0 <= mx <= x0 + w and y0 <= my <= y0 + h) or not dpg.is_mouse_button_clicked(dpg.mvMouseButton_Left):
        return False
    a, b = t0 * k + x0, (t0 + span) * k + x0
    if abs(mx - a) <= px(5):
        app._tl_ov = ("left", t_at, t0, span)
    elif abs(mx - b) <= px(5):
        app._tl_ov = ("right", t_at, t0, span)
    elif a <= mx <= b:
        app._tl_ov = ("box", t_at, t0, span)
    else:                                                    # beside it: that part brought on, and dragged from there
        set_view(app, t_at - span / 2, span)
        t0, span, _ = _span_now(app)
        app._tl_ov = ("box", t_at, t0, span)
    return True


def grip_mouse(app):
    """The grip under the timeline dragged up or down: the timeline's height, kept for next time. True while it
    has the mouse."""
    drag = getattr(app, "_tl_grip", None)
    my = dpg.get_mouse_pos(local=False)[1]
    if drag is not None:
        y0, h0 = drag
        h = int(max(px(TL_H_MIN), min(px(TL_H_MAX), h0 + (my - y0))))
        if h != dpg.get_item_configuration("seq_tl")["height"]:
            dpg.configure_item("seq_tl", height=h)
            app._tl_dirty = True
        if not dpg.is_mouse_button_down(dpg.mvMouseButton_Left):
            app._tl_grip = None
            _set_pref(app, "seq_tl_h", round(h / max(px(100), 1) * 100))      # at the interface size 1
            app._tl_dirty = True
        return True
    if _over("seq_tl_grip") and dpg.is_mouse_button_clicked(dpg.mvMouseButton_Left):
        app._tl_grip = (my, dpg.get_item_configuration("seq_tl")["height"])
        app._tl_dirty = True
        return True
    hot = _over("seq_tl_grip")
    if hot != getattr(app, "_tl_grip_hot", False):
        app._tl_grip_hot = hot
        app._tl_dirty = True
    return False
# AI: end


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


# AI: below section was generated by an AI
def _ramp_band(top, bot):
    """The lower half of a block, where the ramps' curves are drawn: (top, bottom)."""
    return top + (bot - top) * 0.5, bot - px(3)


def _curve_handles(app, st, a, b, top, bot):
    """[(ramp key, point index, x, y)] of the step's curve points, in the timeline's own coordinates."""
    rtop, rbot = _ramp_band(top, bot)
    out = []
    if b - a < 12:
        return out
    for k in (st.get("ramps") or {}):
        r = sequence.ramp_of(st, k)
        if r is None or r[1] != "curve":
            continue
        for j, (t, v) in enumerate(sequence.curve_points(st, k)):
            out.append((k, j, a + 2 + (b - a - 4) * t, rbot - (rbot - rtop) * v / 255.0))
    return out


def _sel_block(app, g):
    """(index, step, a, b, top, bot) of the selected step's block in the timeline's coordinates, or None."""
    x0, y0, w, h, total, spans = g
    sel = getattr(app, "_seq_sel", -1)
    steps = _steps(app)["steps"]
    if total <= 0 or not (0 <= sel < len(spans)):
        return None
    t0, sx = _view(app, total, w)
    t, d, _ = spans[sel]
    _, top, bot = _lanes(h)
    return sel, steps[sel], (t - t0) * sx + 1, (t + d - t0) * sx - 1, top, bot


def _curve_at(app, g, mx, my):
    """A curve point of the selected step under the pointer: (ramp key, index), or None."""
    blk = _sel_block(app, g)
    if blk is None:
        return None
    _, st, a, b, top, bot = blk
    x, y = mx - g[0], my - g[1]
    best = None
    for k, j, hx, hy in _curve_handles(app, st, a, b, top, bot):
        dd = (hx - x) ** 2 + (hy - y) ** 2
        if dd <= px(7) ** 2 and (best is None or dd < best[0]):
            best = (dd, k, j)
    return (best[1], best[2]) if best else None


def _curve_from(app, g, mx, my):
    """Where the pointer is along the selected step's curve lane: (t 0..1, value 0..255), or None off it."""
    blk = _sel_block(app, g)
    if blk is None:
        return None
    _, st, a, b, top, bot = blk
    rtop, rbot = _ramp_band(top, bot)
    x, y = mx - g[0], my - g[1]
    if not (a <= x <= b and top <= y <= bot) or b - a < 12:
        return None
    t = (x - a - 2) / max(1.0, b - a - 4)
    v = (rbot - y) / max(1.0, rbot - rtop) * 255.0
    return max(0.0, min(1.0, t)), int(round(max(0.0, min(255.0, v))))


def _curve_keys(st):
    return [k for k in (st.get("ramps") or {}) if (sequence.ramp_of(st, k) or (0, ""))[1] == "curve"]


def curve_add(app, t, v, key=None):
    """One more point on the selected step's curve (`key`, or the curve whose line passes nearest), at (t, v)."""
    S = _steps(app); sel = getattr(app, "_seq_sel", -1)
    if not (0 <= sel < len(S["steps"])):
        return False
    st = S["steps"][sel]
    keys = _curve_keys(st)
    if not keys or not 0.0 < t <= 1.0:
        return False
    if key is None:
        key = min(keys, key=lambda k: abs(sequence.ramp_value(st, k, t) - v))
    pts = sequence.curve_points(st, key)
    if len(pts) >= sequence.CURVE_MAX or any(abs(p[0] - t) < 0.01 for p in pts):
        return False
    pts.append([round(t, 4), int(v)])
    pts.sort(key=lambda q: q[0])
    st["ramps"][key] = {"shape": "curve", "points": pts}
    _curve_changed(app, st)
    return True


def curve_move(app, key, j, t, v):
    """A curve point of the selected step moved to (t, v): between its neighbours, the last one held at the end."""
    S = _steps(app); sel = getattr(app, "_seq_sel", -1)
    if not (0 <= sel < len(S["steps"])):
        return
    st = S["steps"][sel]
    pts = sequence.curve_points(st, key)
    if not 0 <= j < len(pts):
        return
    lo = pts[j - 1][0] + 0.01 if j > 0 else 0.01
    hi = pts[j + 1][0] - 0.01 if j + 1 < len(pts) else 1.0
    pts[j] = [1.0 if j == len(pts) - 1 else round(max(lo, min(hi, t)), 4), int(max(0, min(255, v)))]
    st["ramps"][key] = {"shape": "curve", "points": pts}
    _curve_changed(app, st, save=False)


def curve_remove(app, key, j):
    """A curve point of the selected step away; a curve keeps its last point (its end)."""
    S = _steps(app); sel = getattr(app, "_seq_sel", -1)
    if not (0 <= sel < len(S["steps"])):
        return False
    st = S["steps"][sel]
    pts = sequence.curve_points(st, key)
    if len(pts) <= 1 or not 0 <= j < len(pts) - 1:
        return False
    pts.pop(j)
    st["ramps"][key] = {"shape": "curve", "points": pts}
    _curve_changed(app, st)
    return True


def _curve_changed(app, st, save=True):
    if save:
        _queue_save(app)
    _ramp_desc(app, st)
    app._tl_dirty = True
    for k in (st.get("ramps") or {}):
        if dpg.does_item_exist(f"seq_ramp_end_{k}"):
            num.set(f"seq_ramp_end_{k}", sequence.ramp_of(st, k)[0])   # a curve's end field follows its last point
    refresh_sent(app)
# AI: end


def _hit(app, g, mx, my):
    """What the pointer is on: ("ruler", t) | ("end", i) | ("blend", i) | ("block", i) | None."""
    x0, y0, w, h, total, spans = g
    if not (x0 <= mx <= x0 + w and y0 <= my <= y0 + h) or total <= 0:
        return None
    t0, sx = _view(app, total, w)
    x, y = mx - x0 + t0 * sx, my - y0                      # x along the whole show, at this zoom
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
    by a click and moved by a drag; a double-click shows it in the sim; a right-click opens its menu. On the
    selected step a curve ramp's points are dragged, Shift+click adds one, a right-click on one takes it away.
    Zoomed in, a middle-button drag moves the timeline along the show (the wheel too: wheel())."""
    g = _tl_geometry(app)
    if g is None:
        return
    x0, y0, w, h, total, spans = g
    mx, my = dpg.get_mouse_pos(local=False)
    down = dpg.is_mouse_button_down(dpg.mvMouseButton_Left)
    drag = getattr(app, "_tl_drag", None)
    t0, sx = _view(app, total, w) if total > 0 else (0.0, 1.0)
    t_at = max(0.0, t0 + (mx - x0) / sx) if total > 0 else 0.0
    # the middle button: the timeline moved along the show, as a hand drags it
    pan = getattr(app, "_tl_pan", None)
    if pan is not None:
        if dpg.is_mouse_button_down(dpg.mvMouseButton_Middle):
            set_view(app, pan[1] - (mx - pan[0]) / sx, pan[2])
        else:
            app._tl_pan = None
        return
    if (dpg.is_mouse_button_clicked(dpg.mvMouseButton_Middle) and total > 0 and getattr(app, "_tl_view", None) is not None
            and ((x0 <= mx <= x0 + w and y0 <= my <= y0 + h) or _over("seq_tl_audio"))):
        v0, span, _ = _span_now(app)
        app._tl_pan = (mx, v0, span)
        return
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
                    was = float(steps[i].get("dur", 10))
                    steps[i]["dur"] = round(max(0.25, end - start), 3)
                    _follow_playing(app, i, steps[i]["dur"] - was)
                    _live(app)                                   # the fields and the list follow the drag
            elif kind == "blend":
                i, start = drag[1], drag[2]
                if 0 <= i < len(steps):
                    steps[i]["trans"] = round(max(0.0, min(float(steps[i].get("dur", 10)), t_at - start)), 2)
                    _live(app)
            elif kind == "curve":
                blk = _sel_block(app, g)
                if blk is not None:
                    _, _, a, b, top, bot = blk
                    rtop, rbot = _ramp_band(top, bot)
                    t = (mx - x0 - a - 2) / max(1.0, b - a - 4)
                    v = (rbot - (my - y0)) / max(1.0, rbot - rtop) * 255.0
                    curve_move(app, drag[1], drag[2], t, int(round(v)))
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
            elif kind in ("end", "blend", "curve"):
                _save(app)
            elif kind == "block":
                select(app, drag[1])
            app._tl_dirty = True
        return
    # a curve's point on the selected step comes before the step under it: dragged, or taken away by a right-click;
    # Shift+click on the step's lower half puts one more there
    pt = _curve_at(app, g, mx, my)
    if pt is not None and dpg.is_mouse_button_clicked(dpg.mvMouseButton_Right):
        curve_remove(app, *pt); return
    if pt is not None and dpg.is_mouse_button_clicked(dpg.mvMouseButton_Left):
        app._tl_drag = ("curve", pt[0], pt[1]); return
    shift = dpg.is_key_down(dpg.mvKey_LShift) or dpg.is_key_down(dpg.mvKey_RShift)
    if shift and dpg.is_mouse_button_clicked(dpg.mvMouseButton_Left):
        at = _curve_from(app, g, mx, my)
        if at is not None and at[0] > 0.0 and curve_add(app, *at):
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


# AI: below section was generated by an AI
# --- recording automation ----------------------------------------------------------------------
# Armed, while the show plays: each frame the sliders of the layer shown are held against what playback left in
# them the frame before (the step's values, its ramps' at that moment). A difference is the hand's - the card's
# field, the side panel's, MIDI, the phone - and from then until it has been still for HOLD_S the slider is
# recorded: its value at the step's moment each frame, and the ramp (if any) leaves it alone. When the step ends,
# or the show stops or pauses, or recording is turned off, each take goes into its step as a curve ramp
# (sequence.record_into): as recorded over the stretch it was moved, as it was elsewhere.
HOLD_S = 0.4                                              # a slider still this long is let go (its take goes on)


class _Rec:
    armed = False
    takes = {}                                            # (id of the step, key) -> [(t, value)]
    steps = {}                                            # id of the step -> the step
    held = {}                                             # key -> when it last moved
    applied = None                                        # (step, effect, layer, fx) as playback left them


_REC = _Rec()


def toggle_rec(app, on=None):
    """Recording armed or not; armed while stopped, the show plays from the selected step."""
    on = (not _REC.armed) if on is None else bool(on)
    if not on:
        _rec_flush(app)
    _REC.armed = on
    _REC.held, _REC.applied = {}, None
    _rec_button(app)
    if on:
        if getattr(app, "_seq_play", None) is None:
            play(app, getattr(app, "_seq_sel", 0))
        elif app._seq_play.get("paused") is not None:
            play_pause(app)
        app.gp.status("recording automation: move a slider while the show plays - it goes into the step playing")
    else:
        app.gp.status("recording off")


def _rec_button(app):
    if dpg.does_item_exist("seq_rec"):
        dpg.configure_item("seq_rec", tint_color=(255, 90, 80, 255) if _REC.armed else (255, 255, 255, 255))


def _rec_key(seg, slider):
    return slider if seg == 0 else f"{seg}:{slider}"


def _rec_poll(app, i, t):
    """This frame's part of a take: the sliders the hand moved, and those it holds, at the step's moment t."""
    if not _REC.armed or getattr(app, "_transition", None) is not None:
        return
    steps = _steps(app)["steps"]
    if not (0 <= i < len(steps)):
        return
    st = steps[i]
    now = clock.now()
    seg = app.eng.seg
    was = _REC.applied
    if was is not None and was[:3] == (i, app.eng.idx, seg):   # the same step, effect and layer as last frame
        for slider in sequence.RAMP_KEYS:
            if app.eng.fx.get(slider) != was[3].get(slider):
                _REC.held[_rec_key(seg, slider)] = now      # moved since playback left it: the hand's
    for key, at in list(_REC.held.items()):
        if now - at > HOLD_S:
            del _REC.held[key]
            continue
        s_, slider = sequence.ramp_target(key)
        if s_ != seg:
            continue
        take = _REC.takes.setdefault((id(st), key), [])
        v = int(app.eng.fx.get(slider, 0))
        if not take or t > take[-1][0] + 1e-4:
            take.append((t, v))
    if any(sid == id(st) for sid, _ in _REC.takes):
        _REC.steps[id(st)] = st
    app._tl_dirty = True


def _rec_flush(app):
    """Every take into its step, as a curve ramp; saved as one undo step."""
    takes, _REC.takes, _REC.held = _REC.takes, {}, {}
    steps_by, _REC.steps = _REC.steps, {}
    _REC.applied = None
    done = 0
    for (sid, key), samples in takes.items():
        st = steps_by.get(sid)
        if st is None or len(samples) < 2 or not any(s is st for s in _steps(app)["steps"]):
            continue
        seg, slider = sequence.ramp_target(key)
        segs = st.get("segments") or []
        if not 0 <= seg < len(segs):
            continue
        start, pts = sequence.record_into(st, key, samples)
        segs[seg].setdefault("params", {})[slider] = start
        st.setdefault("ramps", {})[key] = {"shape": "curve", "points": pts}
        done += 1
    if done:
        _save(app)
        app._tl_dirty = True
        sel = getattr(app, "_seq_sel", 0)
        steps = _steps(app)["steps"]
        if 0 <= sel < len(steps) and dpg.does_item_exist("seq_ramps"):
            refresh_ramps(app, steps[sel])
        app.gp.status(f"automation recorded: {done} curve{'s' if done != 1 else ''}")
# AI: end


# AI: below section was generated by an AI
# --- the show's audio: tracks of clips under the steps (native/showaudio.py) ---------------------------------------
# Drawn in their own strip under the timeline, through the same view - zoomed, moved, followed with it - and used
# the way the steps are: a clip dragged to move it (on the beats, or onto a step's start; Alt: free; up or down to
# another track), its ends to trim it, the handles at its top corners for its fades; a right-click for its menu. Each
# track a lane: its name and its mute (M) at its left. Heard while the show plays, and heard by the effects.
LANE_H = 46              # a track's lane
LANE_HEAD = 15           # its top band: the name and M
AUDIO_EMPTY_H = 24       # the strip with no track yet


def _tracks(app):
    from native import showaudio
    return showaudio.tracks(_steps(app))


def _extent(app):
    """How far the timeline reaches: the steps, or the last clip when it ends after them."""
    from native import showaudio
    return max(_starts(app)[1], showaudio.length(_steps(app)))


def _audio_height(app):
    n = len(_tracks(app))
    return px(LANE_H) * n if n else px(AUDIO_EMPTY_H)


def add_track(app):
    T = _tracks(app)
    T.append({"name": f"Track {len(T) + 1}", "mute": False, "gain": 1.0, "clips": []})
    _save(app)
    _audio_changed(app)
    return len(T) - 1


def _project_copy(app, path):
    """The file in the project's assets/audio (a copy; one of the same name and other sound gets a number): its
    path from the project's folder."""
    import shutil
    from native.features import _same_file
    adir = os.path.join(app.project.path, "assets", "audio")
    os.makedirs(adir, exist_ok=True)
    name = os.path.basename(path)
    dst = os.path.join(adir, name)
    if os.path.abspath(dst) != os.path.abspath(path):
        stem, ext = os.path.splitext(name)
        n = 2
        while os.path.exists(dst) and not _same_file(dst, path):
            name = f"{stem}_{n}{ext}"; dst = os.path.join(adir, name); n += 1
        if not os.path.exists(dst):
            shutil.copyfile(path, dst)
    return "assets/audio/" + name


def add_audio(app, path, ti=None, at=None):
    """An audio file onto the show: copied into the project, decoded on a worker, then a clip of all of it - at the
    playhead (or the selected step's start), on the selected clip's track or the first with room there (a new
    track when none has)."""
    from native import showaudio, tasks
    if not path or not os.path.isfile(path):
        return False
    try:
        rel = _project_copy(app, path)
    except OSError as e:
        app.gp.status(f"could not copy {os.path.basename(path)}: {e}", "warn"); return False
    full = os.path.join(app.project.path, rel)
    if at is None:
        pos = position(app)
        starts = _starts(app)[0]
        sel = getattr(app, "_seq_sel", 0)
        at = pos if pos is not None else (starts[sel] if 0 <= sel < len(starts) else 0.0)

    def work():
        snd = showaudio.sound(full, wait=True)
        if snd is None:
            raise RuntimeError(showaudio.error(full) or "it could not be read")
        return snd

    def done(snd):
        T = _tracks(app)
        k = ti
        if k is None and getattr(app, "_clip_sel", None) is not None and app._clip_sel[0] < len(T):
            k = app._clip_sel[0]
        if k is None:
            end = at + snd.seconds
            k = next((j for j, tr in enumerate(T)
                      if all(showaudio.clip_end(c) <= at or float(c.get("at", 0)) >= end for c in tr.get("clips") or [])), None)
        if k is None:
            k = add_track(app)
        T[k].setdefault("clips", []).append({"file": rel, "at": round(float(at), 3), "in": 0.0,
                                             "len": round(snd.seconds, 3), "gain": 1.0})
        app._clip_sel = (k, len(T[k]["clips"]) - 1)
        _save(app)
        _audio_changed(app)
        app.gp.status(f"{os.path.basename(rel)}: {snd.seconds:.1f} s on {T[k].get('name', 'a track')} at {_fmt_t(at)}")
    return tasks.run(app, "seq_audio", f"reading {os.path.basename(path)}", work, done)


def _audio_changed(app):
    """The lanes drawn again, and the speakers given the clips anew (_poll_audio)."""
    app._tl_dirty = True
    app._audio_key = None
    if dpg.does_item_exist("seq_tl_audio"):
        h = _audio_height(app)
        if dpg.get_item_configuration("seq_tl_audio")["height"] != h:
            dpg.configure_item("seq_tl_audio", height=h)


def _lane_geometry(app):
    """(x0, y0, w, h) of the audio strip on screen, or None."""
    if not dpg.does_item_exist("seq_tl_audio") or not dpg.is_item_shown(TAG):
        return None
    (x0, y0) = dpg.get_item_state("seq_tl_audio").get("rect_min") or (0, 0)
    cfg = dpg.get_item_configuration("seq_tl_audio")
    return x0, y0, cfg["width"], cfg["height"]


def _clip_rect(app, ti, ci, t0, sx):
    """(a, b, top, bot) of a clip in the strip's own coordinates."""
    c = _tracks(app)[ti]["clips"][ci]
    top = ti * px(LANE_H) + px(LANE_HEAD)
    return (float(c.get("at", 0)) - t0) * sx, (float(c.get("at", 0)) + float(c.get("len", 0)) - t0) * sx, top, \
        (ti + 1) * px(LANE_H) - 2


def _wave_peaks(snd, cin, at, t0, sx, a, b, every=2):
    """(xs, loudness 0..1) of a clip's wave across [a, b) of the strip: the loudest in each column's stretch."""
    from native import showaudio
    xs = np.arange(max(0, int(a)), int(b), every, dtype=np.float64)
    if not len(xs):
        return xs, xs
    per = showaudio.RATE / float(showaudio.PEAK)                 # points a second
    ta = cin + (t0 + xs / sx - at)
    i0 = np.clip((ta * per).astype(int), 0, len(snd.peaks) - 1)
    i1 = np.clip(((ta + every / sx) * per).astype(int) + 1, i0 + 1, len(snd.peaks))
    ok = (ta >= 0) & (ta <= snd.seconds)
    vals = np.array([snd.peaks[s:e].max() for s, e in zip(i0.tolist(), i1.tolist())], np.float32)
    vals[~ok] = 0.0
    vals /= max(snd.loudest, 1e-4)                               # drawn to the file's own loudest, as a DAW draws it
    return xs, vals


def draw_audio(app, t0, sx, total):
    """The tracks' lanes: each clip a block on its time, its wave in it, its fades as lines down to its ends (the
    handles at its top corners), its name; the track's name and M at its left; the bars, the playhead."""
    from native import showaudio
    if not dpg.does_item_exist("seq_tl_audio"):
        return
    c = _c()
    dl = "seq_tl_audio"
    dpg.delete_item(dl, children_only=True)
    w = dpg.get_item_configuration(dl)["width"]
    h = _audio_height(app)
    T = _tracks(app)
    dpg.draw_rectangle((0, 0), (w, h), color=(0, 0, 0, 0), fill=(0, 0, 0, 55), parent=dl)
    if not T:
        typeface.draw_text((px(8), px(4)), "the show's audio: + Audio... puts a file at the playhead, on a track of its own",
                           px(12), color=c.DIM, parent=dl)
        return
    X = lambda t: (t - t0) * sx                                        # noqa: E731
    bl = _barlen(app)
    if bl and bl * sx >= 4:                                            # the bars, as over the steps
        t = np.floor(t0 / bl) * bl
        while X(t) <= w:
            dpg.draw_line((X(t), 0), (X(t), h), color=(255, 255, 255, 18), thickness=1, parent=dl)
            t += bl
    sel = getattr(app, "_clip_sel", None)
    root = app.project.path
    for ti, tr in enumerate(T):
        y0, y1 = ti * px(LANE_H), (ti + 1) * px(LANE_H)
        dpg.draw_rectangle((0, y0), (w, y1), color=(0, 0, 0, 0), fill=(255, 255, 255, 8 if ti % 2 else 3), parent=dl)
        dpg.draw_line((0, y1 - 0.5), (w, y1 - 0.5), color=(255, 255, 255, 22), thickness=1, parent=dl)
        muted = bool(tr.get("mute"))
        col = (120, 170, 255) if not muted else (110, 110, 118)
        for ci, (cl, (fi, fo)) in enumerate(zip(tr.get("clips") or [], showaudio.fades(tr))):
            a, b, top, bot = _clip_rect(app, ti, ci, t0, sx)
            if b < 0 or a > w:
                continue
            at, ln, cin = float(cl.get("at", 0)), float(cl.get("len", 0)), float(cl.get("in", 0))
            dpg.draw_rectangle((a, top), (b, bot), color=(0, 0, 0, 0), fill=col + (55,), rounding=3, parent=dl)
            snd = showaudio.sound(os.path.join(root, cl.get("file", "")))
            mid, half = (top + bot) / 2, (bot - top) / 2 - 1
            if snd is not None:
                xs, v = _wave_peaks(snd, cin, at, t0, sx, max(a, 0), min(b, w))
                g = showaudio.envelope((t0 + xs / sx - at).astype(np.float32), ln, fi, fo) if len(xs) else xs
                for x, k in zip(xs.tolist(), (v * g * half).tolist()):
                    if k > 0.4:
                        dpg.draw_line((x, mid - k), (x, mid + k), color=col + (200,), thickness=1, parent=dl)
            else:
                err = showaudio.error(os.path.join(root, cl.get("file", "")))
                typeface.draw_text((max(a, 0) + px(4), mid - px(6)), ("cannot be read: " + err) if err else "reading...",
                                   px(11), color=c.AMBER if err else c.DIM, parent=dl)
            # the fades: a line from the clip's top corner to its foot, the handle at the corner
            if fi > 0:
                dpg.draw_line((a, bot), (X(at + fi), top), color=(255, 255, 255, 150), thickness=1, parent=dl)
            if fo > 0:
                dpg.draw_line((b, bot), (X(at + ln - fo), top), color=(255, 255, 255, 150), thickness=1, parent=dl)
            if b - a > px(16):
                for hx, auto in ((X(at + fi), "fade_in" not in cl), (X(at + ln - fo), "fade_out" not in cl)):
                    dpg.draw_rectangle((hx - px(3), top), (hx + px(3), top + px(6)), color=(255, 255, 255, 220),
                                       fill=(30, 34, 42, 255) if auto else (255, 255, 255, 220), parent=dl)
            name = os.path.basename(cl.get("file", ""))
            room = min(b, w) - max(a, 0) - px(10)
            if room > px(20):
                typeface.draw_text((max(a, 0) + px(4), top + px(1)), _fit_measured(name, room, px(11)), px(11),
                                   color=(235, 238, 245, 210), parent=dl)
            if sel == (ti, ci):
                dpg.draw_rectangle((a, top), (b, bot), color=c.ACCENT, thickness=2, rounding=3, parent=dl)
        # the track's head, over its lane's left end: its name and M
        tw = typeface.measure(str(tr.get("name", "")), "body", px(11))
        dpg.draw_rectangle((0, y0), (tw + px(30), y0 + px(LANE_HEAD)), color=(0, 0, 0, 0), fill=(20, 22, 28, 220), parent=dl)
        dpg.draw_rectangle((px(3), y0 + px(2)), (px(15), y0 + px(13)), color=(255, 255, 255, 140),
                           fill=(230, 160, 60, 255) if muted else (0, 0, 0, 0), rounding=2, parent=dl)
        typeface.draw_text((px(5), y0 + px(1)), "M", px(10), face="mono", color=(20, 20, 20, 255) if muted else (230, 233, 240, 220), parent=dl)
        typeface.draw_text((px(20), y0 + px(1)), str(tr.get("name", "")), px(11), color=(230, 233, 240, 220), parent=dl)
    drag = getattr(app, "_au_drag", None)
    if drag and drag[0] == "move" and drag[5] is not None:            # the track a clip would go to
        ty = drag[5] * px(LANE_H)
        dpg.draw_rectangle((0, ty), (w, ty + px(LANE_H)), color=c.ACCENT, thickness=1, parent=dl)
    at = position(app)
    app._au_scale = (sx, h, t0)
    if at is not None:
        dpg.draw_line((X(at), 0), (X(at), h), color=(255, 255, 255, 240), thickness=2, parent=dl, tag="seq_au_head")


def _move_au_head(app):
    at, sc = position(app), getattr(app, "_au_scale", None)
    if at is None or sc is None or not dpg.does_item_exist("seq_au_head"):
        return
    sx, h, t0 = sc
    x = (at - t0) * sx
    dpg.configure_item("seq_au_head", p1=(x, 0), p2=(x, h))


def _audio_hit(app, mx, my):
    """What the pointer is on in the strip: ("mute", ti) | ("fade_in" | "fade_out" | "trim_l" | "trim_r" |
    "clip", ti, ci) | ("lane", ti, t) | None."""
    g = _lane_geometry(app)
    if g is None:
        return None
    x0, y0, w, h = g
    if not (x0 <= mx <= x0 + w and y0 <= my <= y0 + h):
        return None
    T = _tracks(app)
    x, y = mx - x0, my - y0
    ti = int(y // px(LANE_H))
    if not (0 <= ti < len(T)):
        return None
    if x <= px(16) and y - ti * px(LANE_H) <= px(LANE_HEAD):
        return ("mute", ti)
    gt = _tl_geometry(app)
    t0, sx = _view(app, gt[4] if gt else _extent(app), w)
    from native import showaudio
    tr = T[ti]
    for ci in reversed(range(len(tr.get("clips") or []))):         # the last drawn, on top, first
        a, b, top, bot = _clip_rect(app, ti, ci, t0, sx)
        cl = tr["clips"][ci]
        fi, fo = showaudio.fades(tr)[ci]
        at, ln = float(cl.get("at", 0)), float(cl.get("len", 0))
        if top - px(2) <= y <= top + px(8):
            if abs(x - (at + fi - t0) * sx) <= px(5):
                return ("fade_in", ti, ci)
            if abs(x - (at + ln - fo - t0) * sx) <= px(5):
                return ("fade_out", ti, ci)
        if top <= y <= bot:
            if abs(x - a) <= px(4):
                return ("trim_l", ti, ci)
            if abs(x - b) <= px(4):
                return ("trim_r", ti, ci)
            if a <= x <= b:
                return ("clip", ti, ci)
    return ("lane", ti, t0 + x / sx)


def _snap(app, t, exclude=None):
    """A time put on the beat when a tempo is set and snapping is on (Alt: free), or onto a step's start or a
    clip's end within a few pixels."""
    if dpg.is_key_down(dpg.mvKey_LAlt) or dpg.is_key_down(dpg.mvKey_RAlt):
        return t
    g = _tl_geometry(app)
    sx = _view(app, g[4], g[2])[1] if g else 10.0
    from native import showaudio
    marks = list(_starts(app)[0]) + [_starts(app)[1]]
    for ti, tr in enumerate(_tracks(app)):
        for ci, c in enumerate(tr.get("clips") or []):
            if (ti, ci) != exclude:
                marks += [float(c.get("at", 0)), showaudio.clip_end(c)]
    near = min(marks, key=lambda m: abs(m - t), default=None)
    if near is not None and abs(near - t) * sx <= px(8):
        return near
    beat = _beat(app)
    if beat and _steps(app).get("snap", True):
        return round(t / beat) * beat
    return t


def audio_mouse(app):
    """The strip's pointer: a clip pressed is selected and dragged - its body moves it (and to another track, up or
    down), an end trims it, a top corner's handle sets that fade; M mutes the track; a right-click a clip's or a
    track's menu; a double-click on a clip plays from its start. True while the strip has the mouse."""
    from native import showaudio
    g = _lane_geometry(app)
    drag = getattr(app, "_au_drag", None)
    mx, my = dpg.get_mouse_pos(local=False)
    if drag is not None:
        if g is None:
            app._au_drag = None
            return False
        x0, y0, w, h = g
        gt = _tl_geometry(app)
        t0, sx = _view(app, gt[4] if gt else _extent(app), w)
        t = t0 + (mx - x0) / sx
        kind, ti, ci, grab, orig = drag[:5]
        T = _tracks(app)
        if not (0 <= ti < len(T) and 0 <= ci < len(T[ti].get("clips") or [])):
            app._au_drag = None
            return True
        cl = T[ti]["clips"][ci]
        snd = showaudio.sound(os.path.join(app.project.path, cl.get("file", "")))
        full = snd.seconds if snd is not None else orig["in"] + orig["len"]
        if dpg.is_mouse_button_down(dpg.mvMouseButton_Left):
            if kind == "move":
                at = _snap(app, max(0.0, orig["at"] + (t - grab)), (ti, ci))
                cl["at"] = round(max(0.0, at), 3)
                to = int((my - y0) // px(LANE_H))
                app._au_drag = drag[:5] + ((to if 0 <= to < len(T) and to != ti else None),)
            elif kind == "trim_l":
                at = _snap(app, t, (ti, ci))
                at = max(orig["at"] - orig["in"], min(orig["at"] + orig["len"] - 0.05, at))
                d = at - orig["at"]
                cl["at"], cl["in"], cl["len"] = round(at, 3), round(orig["in"] + d, 3), round(orig["len"] - d, 3)
            elif kind == "trim_r":
                end = _snap(app, t, (ti, ci))
                cl["len"] = round(max(0.05, min(full - orig["in"], end - orig["at"])), 3)
            elif kind == "fade_in":
                cl["fade_in"] = round(max(0.0, min(orig["len"], t - orig["at"])), 3)
            elif kind == "fade_out":
                cl["fade_out"] = round(max(0.0, min(orig["len"], orig["at"] + orig["len"] - t)), 3)
            app._tl_dirty = True
            app._audio_key = None
        else:
            app._au_drag = None
            to = drag[5] if len(drag) > 5 else None
            if kind == "move" and to is not None:                    # onto another track
                T[to].setdefault("clips", []).append(T[ti]["clips"].pop(ci))
                app._clip_sel = (to, len(T[to]["clips"]) - 1)
            _save(app)
            _audio_changed(app)
        return True
    hit = _audio_hit(app, mx, my)
    if hit is None:
        return False
    if dpg.is_mouse_button_clicked(dpg.mvMouseButton_Right):
        if hit[0] in ("clip", "trim_l", "trim_r", "fade_in", "fade_out"):
            _clip_menu(app, hit[1], hit[2])
        elif hit[0] in ("lane", "mute"):
            _track_menu(app, hit[1])
        return True
    if not dpg.is_mouse_button_clicked(dpg.mvMouseButton_Left):
        return False
    if hit[0] == "mute":
        tr = _tracks(app)[hit[1]]
        tr["mute"] = not tr.get("mute")
        _save(app); _audio_changed(app)
        return True
    if hit[0] == "lane":
        app._clip_sel = None
        app._tl_dirty = True
        return False                                             # an empty lane: the timeline's own (a middle drag)
    ti, ci = hit[1], hit[2]
    cl = _tracks(app)[ti]["clips"][ci]
    app._clip_sel = (ti, ci)
    if dpg.is_mouse_button_double_clicked(dpg.mvMouseButton_Left):
        seek(app, float(cl.get("at", 0)))
        return True
    g = _lane_geometry(app)
    gt = _tl_geometry(app)
    t0, sx = _view(app, gt[4] if gt else _extent(app), g[2])
    kind = {"clip": "move"}.get(hit[0], hit[0])
    app._au_drag = (kind, ti, ci, t0 + (mx - g[0]) / sx,
                    {"at": float(cl.get("at", 0)), "in": float(cl.get("in", 0)), "len": float(cl.get("len", 0))}, None)
    app._tl_dirty = True
    return True


def _menu(app, title, items):
    c = _c()
    dpg.delete_item("seq_ctx", children_only=True)
    dpg.add_text(c._fit_text(title, px(220)), parent="seq_ctx", color=c.DIM)
    for label, fn in items:
        dpg.add_selectable(label=label, parent="seq_ctx", callback=lambda s, a, u: (dpg.hide_item("seq_ctx"), u()), user_data=fn)
    x, y = dpg.get_mouse_pos(local=False)
    dpg.set_item_pos("seq_ctx", [x, y])
    dpg.show_item("seq_ctx")


def _clip_menu(app, ti, ci):
    app._clip_sel = (ti, ci)
    T = _tracks(app)
    cl = T[ti]["clips"][ci]

    def auto():
        cl.pop("fade_in", None); cl.pop("fade_out", None); _save(app); _audio_changed(app)

    def dup():
        import copy
        d = copy.deepcopy(cl)
        d["at"] = round(float(cl.get("at", 0)) + float(cl.get("len", 0)), 3)
        T[ti]["clips"].append(d); app._clip_sel = (ti, len(T[ti]["clips"]) - 1); _save(app); _audio_changed(app)

    def delete():
        T[ti]["clips"].pop(ci); app._clip_sel = None; _save(app); _audio_changed(app)

    def new_track():
        k = add_track(app)
        T[k]["clips"].append(T[ti]["clips"].pop(ci)); app._clip_sel = (k, 0); _save(app); _audio_changed(app)

    def play_here():
        seek(app, float(cl.get("at", 0)))
        p = getattr(app, "_seq_play", None)
        if p is not None and p.get("paused") is not None:
            play_pause(app)                                       # held there: on from it

    _menu(app, os.path.basename(cl.get("file", "")), [
        ("Play from its start", play_here),
        ("Automatic fades", auto), ("Duplicate after it", dup), ("To a new track", new_track), ("Delete", delete)])


def _track_menu(app, ti):
    T = _tracks(app)
    tr = T[ti]

    def mute():
        tr["mute"] = not tr.get("mute"); _save(app); _audio_changed(app)

    def remove():
        T.pop(ti); app._clip_sel = None; _save(app); _audio_changed(app)

    def add():
        app._audio_to_track = ti
        dpg.show_item("seq_audio_dialog")

    _menu(app, str(tr.get("name", "")), [("Unmute" if tr.get("mute") else "Mute", mute), ("Add audio here...", add),
                                         ("Remove the track and its clips", remove)])


def delete_clip(app):
    sel = getattr(app, "_clip_sel", None)
    T = _tracks(app)
    if sel is None or not (0 <= sel[0] < len(T) and 0 <= sel[1] < len(T[sel[0]].get("clips") or [])):
        return False
    T[sel[0]]["clips"].pop(sel[1])
    app._clip_sel = None
    _save(app); _audio_changed(app)
    return True


def _poll_audio(app):
    """The speakers kept to the show: the clips given anew when they change, the show's place and whether it plays
    every frame. A player is made once there is a clip; it stays silent with its reason when it cannot sound."""
    import json
    from native import showaudio
    T = _tracks(app)
    has = any(tr.get("clips") for tr in T)
    pl = getattr(app, "_show_player", None)
    if not has:
        if pl is not None:
            pl.sync(None, False)
        return
    if pl is None:
        pl = app._show_player = showaudio.Player()
        if pl.error:
            app.gp.status(pl.error, "warn")
    key = (json.dumps(T, sort_keys=True, default=str), showaudio.decoding(), len(showaudio._CACHE))
    if key != getattr(app, "_audio_key", None):
        app._audio_key = key
        app._audio_resolved = showaudio.resolve(_steps(app), app.project.path)
        pl.set(app._audio_resolved)
        app._tl_dirty = True                                     # a file decoded since: its wave drawn
    p = getattr(app, "_seq_play", None)
    from native import render_video
    if render_video.rendering(app):
        pl.sync(None, False)                                     # a video rendering: its sound goes into the file
        return
    pl.sync(position(app), p is not None and p.get("paused") is None)


def show_source(app):
    """What the effects hear while the show plays or is held at a time and has audio: its mix where it is
    (showaudio.ShowAudio), in place of the synth or the live audio; None otherwise."""
    if getattr(app, "_seq_play", None) is None or not getattr(app, "_audio_resolved", None):
        return None
    src = getattr(app, "_show_src", None)
    if src is None:
        from native import showaudio
        src = app._show_src = showaudio.ShowAudio(lambda: getattr(app, "_audio_resolved", []), lambda: position(app))
    return src
# AI: end


# --- the keys ------------------------------------------------------------------------------------
def key(app, code):
    """The frame's own keys while it has the keyboard (not while a box is typed in): Space plays and pauses,
    Delete removes the selected step, Ctrl+D duplicates it, Z zooms the timeline to the selected step and Shift+Z
    to the whole show. True when the key was the frame's."""
    if not dpg.does_item_exist(TAG) or not dpg.is_item_shown(TAG) or app.typing() or app.undo_target() != "sequence":
        return False
    ctrl = dpg.is_key_down(dpg.mvKey_LControl) or dpg.is_key_down(dpg.mvKey_RControl)
    if code == dpg.mvKey_Spacebar and not ctrl and _has_steps(app):
        play_pause(app); return True
    if code == dpg.mvKey_Delete and getattr(app, "_clip_sel", None) is not None and delete_clip(app):
        return True                                       # a clip selected: the clip
    if code == dpg.mvKey_Delete and _has_sel(app):
        del_step(app, getattr(app, "_seq_sel", 0)); return True
    if code == dpg.mvKey_D and ctrl and _has_sel(app):
        duplicate_step(app); return True
    if code == dpg.mvKey_Z and not ctrl and _has_steps(app):
        shift = dpg.is_key_down(dpg.mvKey_LShift) or dpg.is_key_down(dpg.mvKey_RShift)
        fit_all(app) if shift else fit_step(app)
        return True
    return False


# --- the device --------------------------------------------------------------------------------
def _resolve(app, host=None, S=None):
    """(presets, playlist, error) against the device's own effect and palette lists - the active device and the
    project's steps, or a host and a copy of the steps given (from a worker, which reads nothing of the app)."""
    S = _steps(app) if S is None else S
    host = app.active_host() if host is None else host
    from native import devices
    try:
        names = devices._get(host, "/json/effects", 5)
        pals = devices._get(host, "/json/palettes", 5)
    except Exception as e:
        return None, None, f"could not read the device's lists: {e}"
    try:
        presets, playlist = sequence.to_wled(S["steps"], names, pals, int(S.get("base", 10)), int(S.get("pid", 9)), S.get("name", "Show"), int(S.get("repeat", 0)))
    except ValueError as e:
        return None, None, str(e)                            # the device could not hold it: said, nothing sent
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
    snap = json.loads(json.dumps(S))                      # the steps as they are now: the worker reads its copy
    pid = int(S.get("pid", 9))
    fp = sequence.fingerprint(S)
    dpg.set_value("seq_log", f"sending the presets and the playlist to {host}...")
    for t in ("seq_send", "seq_send_run"):
        if dpg.does_item_exist(t):
            dpg.configure_item(t, enabled=False)

    def work():
        sent = None
        try:
            # the device's lists read here too: two requests of up to 5 s each, on the main loop, froze the studio
            presets, playlist, err = _resolve(app, host, snap)
            if err:
                app._seq_sent_now = None
                app._seq_send_result = err
                return
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
    if err and presets is None and app.active_host() and not err.startswith("could not read"):
        app.gp.status(f"not saved: {err}"); return
    if err:
        # no device to resolve names against: the sim's own effect list, which matches a device flashed from this project
        names, pals = app.eng.names, list(range(256))
        try:
            presets, playlist = sequence.to_wled(S["steps"], names, pals, int(S.get("base", 10)), int(S.get("pid", 9)), S.get("name", "Show"), int(S.get("repeat", 0)))
        except ValueError as e:
            app.gp.status(f"not saved: {e}"); return
        note = " (effect ids are the sim's: right for a device flashed from this project)"
    else:
        note = " (effect ids resolved against the device)"
    open(path, "w", encoding="utf-8").write(sequence.presets_file(presets, playlist, int(S.get("pid", 9))))
    app.gp.status(f"presets.json saved to {os.path.basename(path)}" + note)
