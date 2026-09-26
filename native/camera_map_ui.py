"""The "Map lights by camera" dialog (the ninth pass's S18): the plan played
- in the sim, and on the device while the sim is streamed to it - each
side's film added (a video from any camera, read on a worker thread; or
taken live by a webcam when OpenCV is there), and the points part made
from them (camera_map does the finding and the 3-D).

    camera_map_ui.build(app)     # the window, once (shape_ui.build calls it)
    camera_map_ui.show(app)
    camera_map_ui.poll(app)      # per frame: the plan's lighting, a film's reading coming back, a webcam's pictures
"""
import os
import threading
import time

import numpy as np
import dearpygui.dearpygui as dpg

from native import camera_map as cm, units, typeface, form, num, weight
from native.typeface import px

TAG = "map_win"
ANGLES = ("0°", "90°", "180°", "270°", "45°", "135°", "225°", "315°")
VIDEO = (".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v")
THUMB_W, THUMB_H = 132, 99           # a side's picture in its card (at 100%): the film fitted inside


def _state(app):
    s = getattr(app, "_map", None)
    if s is None:
        s = app._map = {"sides": [], "play": None, "busy": None, "queue": [], "webcam": None}
    return s


def webcam_ok():
    import importlib.util
    try:
        return importlib.util.find_spec("cv2") is not None
    except Exception:
        return False


def build(app):
    from native import chrome
    with dpg.window(tag=TAG, label="Map lights by camera", no_title_bar=True, show=False, autosize=True, no_collapse=True):
        chrome.dialog_header(TAG, "Map lights by camera")
        dpg.add_text("For lights in no pattern - a string wound round a real tree. The device lights its LEDs one at a time "
                     "while a camera films; filmed from two sides or more (the object turned between), their places come out "
                     "in 3-D. One side gives them flat, as it faces the camera.", color=chrome.DIM, wrap=px(590))
        with form.row("LEDs", tip="how many the device has, in wiring order - the same as when each side was filmed"):
            num.add("map_n", 100, 1, 4096, integer=True, wide=True, width=px(120), callback=lambda s, v: _plan_words(app))
        with form.row("each lit for", tip="how long each LED is lit - the same as when each side was filmed; "
                                          "a camera at 30 pictures a second wants 0.15 s or more"):
            num.add("map_on", 0.2, 0.08, 2.0, digits=2, unit="s", width=px(120), callback=lambda s, v: _plan_words(app))
            dpg.add_text("", tag="map_plan_words", color=chrome.DIM)
        with form.row("its height", tip="the object's height, measured: the mapped lights are sized to it"):
            num.add("map_height", 180.0, 1.0, None, digits=1, unit="cm", width=px(120))
        typeface.label(dpg.add_text("1. PLAY THE PLAN WHILE A CAMERA FILMS", color=chrome.ACCENT))
        dpg.add_text("A white flash, each LED in turn, a white flash. Film all of it with the whole object in view, the room "
                     "dark and the camera still (a phone on a tripod will do).", color=chrome.DIM, wrap=px(590))
        with dpg.group(horizontal=True):
            dpg.add_button(label="Play the plan", tag="map_play", callback=lambda: play(app))
            weight.primary("map_play")
            chrome.tip("in the sim - and on the device while the sim is streamed to it (Stream the sim to the device, Ctrl+Shift+T)")
            dpg.add_button(label="Stop", tag="map_stop", callback=lambda: stop(app))
            chrome.tip("the plan stopped part way")
            dpg.add_text("", tag="map_play_words", color=chrome.DIM)
        dpg.add_text("", tag="map_stream_words", color=chrome.DIM, wrap=px(590))
        typeface.label(dpg.add_text("2. EACH SIDE'S FILM", color=chrome.ACCENT))
        dpg.add_text("Film the front first; turn the object a quarter (or to any of the angles), play the plan and film again.",
                     color=chrome.DIM, wrap=px(590))
        dpg.add_text("", tag="map_ff_words", color=chrome.AMBER, wrap=px(590), show=False)
        dpg.add_group(tag="map_sides")
        with dpg.group(horizontal=True):
            dpg.add_button(label="+ a side", callback=lambda: _add_side(app))
            chrome.tip("another side: how far it was turned from the first, then its film")
            dpg.add_button(label="Film with the webcam", tag="map_webcam", callback=lambda: webcam(app))
            chrome.tip("the plan played while the webcam takes its pictures: a side without a video file "
                       "(needs OpenCV: pip install opencv-python)")
        typeface.label(dpg.add_text("3. THE PART", color=chrome.ACCENT))
        with dpg.group(horizontal=True):
            dpg.add_button(label="Make the part", tag="map_make", callback=lambda: make(app))
            weight.primary("map_make")
            chrome.tip("the lights as a points part in the shape, in wiring order: an LED no two sides saw is estimated "
                       "(the shape's checks list them, to drag where they are)")
            dpg.add_text("", tag="map_result", color=chrome.DIM, wrap=px(430))
    with dpg.file_dialog(directory_selector=False, show=False, tag="map_film_dialog", width=px(640), height=px(420),
                         callback=lambda s, a: _film_chosen(app, a.get("file_path_name", ""))):
        for ext in VIDEO:
            dpg.add_file_extension(ext, color=(200, 180, 90))


def show(app):
    from native import chrome
    if not dpg.does_item_exist(TAG):
        return
    s = _state(app)
    if s["play"] is None and s["busy"] is None:
        g = app.project.geometry
        S = app.project.options.get("outputs") or {}
        outs = sum(int(o.get("len", 0) or 0) for o in (S.get("outs") or []))
        num.set("map_n", outs or (g.count if g is not None and g.kind == "shape" and g.count > 1 else 100))
    if not s["sides"]:
        _add_side(app)
    _plan_words(app)
    _sides(app)
    dpg.set_value("map_ff_words", "ffmpeg is not on the PATH, so a video cannot be read: install it (ffmpeg.org) and restart "
                  "the studio" + (", or film with the webcam" if webcam_ok() else ""))
    dpg.configure_item("map_ff_words", show=not cm.ffmpeg())
    dpg.configure_item("map_webcam", show=webcam_ok())
    chrome._centre(TAG, 620, 720)
    dpg.show_item(TAG)


def _plan(app):
    return cm.Plan(int(dpg.get_value("map_n")), on=float(dpg.get_value("map_on")), off=0.05)


def _plan_words(app):
    if dpg.does_item_exist("map_plan_words"):
        p = _plan(app)
        m, sec = divmod(int(round(p.total)), 60)
        dpg.set_value("map_plan_words", f"the plan takes {m} min {sec} s" if m else f"the plan takes {sec} s")


# --- playing the plan ---------------------------------------------------------------------------
def play(app, record=None):
    """The plan on: the wiring test driven through it (the sim shows it; the
    device while the sim is streamed); `record`: a webcam taking pictures meanwhile."""
    s = _state(app)
    if s["play"] is not None:
        stop(app)
    s["play"] = {"plan": _plan(app), "t0": time.perf_counter() + 0.4, "record": record}
    app.wiring_start("index")
    app.wiring.mode = "off"
    app.gp.status("the plan is playing: film it" + ("" if getattr(app, "ddp", None) is not None else
                                                   " (the sim only: stream the sim to light the device)"))


def stop(app):
    s = _state(app)
    app._map_frame = None
    if s["play"] is not None:
        rec = s["play"].get("record")
        if rec is not None:
            rec["stop"] = True
        s["play"] = None
        app.wiring_stop()
        if dpg.does_item_exist("map_play_words"):
            dpg.set_value("map_play_words", "stopped")
        app.gp.status("the plan stopped")


def _drive(app):
    """Per frame while playing: what the plan has lit now - into the wiring
    test (the sim), and as the device's own frame while streaming (the plan's
    LEDs in the device's wiring order, whatever geometry the sim has)."""
    s = _state(app)
    p = s["play"]
    t = time.perf_counter() - p["t0"]
    plan = p["plan"]
    wt = getattr(app, "wiring", None)
    if wt is None:                                   # play pressed: the effect took the buffer back
        stop(app); return
    what = plan.at(t) if t >= 0 else "none"
    if what == "all":
        wt.mode = "white"
    elif isinstance(what, int) and what < wt.n:
        wt.mode = "index"; wt.index = what
    else:
        wt.mode = "off"                              # dark (an LED past the sim's count lights on the device only)
    frame = np.zeros((plan.n, 3), np.uint8)
    if what == "all":
        frame[:] = 255
    elif isinstance(what, int):
        frame[what] = 255
    app._map_frame = frame.tobytes()
    left = max(0.0, plan.total - t)
    if dpg.does_item_exist("map_play_words"):
        dpg.set_value("map_play_words", (f"LED {what + 1} of {plan.n}" if isinstance(what, int) else ("flash" if what == "all" else "dark"))
                      + f" - {int(left) // 60}:{int(left) % 60:02d} left")
    if t > plan.total + 0.3:
        rec = p.get("record")
        s["play"] = None
        app._map_frame = None
        app.wiring_stop()
        if dpg.does_item_exist("map_play_words"):
            dpg.set_value("map_play_words", "played")
        if rec is not None:
            rec["stop"] = True
        app.gp.status("the plan has played" + ("" if rec is not None else ": add the film of this side"))


# --- the sides ----------------------------------------------------------------------------------
def _add_side(app):
    s = _state(app)
    used = {side["angle"] for side in s["sides"]}
    s["sides"].append({"angle": next((a for a in ANGLES if a not in used), "0°"), "found": None, "words": "no film yet",
                       "thumb": None})
    _sides(app)


def _drop_side(app, k):
    s = _state(app)
    if 0 <= k < len(s["sides"]) and (s["busy"] is None or s["busy"]["k"] != k):
        gone = s["sides"].pop(k)
        s["queue"] = [(j - (j > k), w, what) for j, w, what in s["queue"] if j != k]
        if s["busy"] is not None and s["busy"]["k"] > k:
            s["busy"]["k"] -= 1
        _sides(app)
        _forget(gone.get("thumb"))


def _sides(app):
    """The sides as cards, four to a row: the turn, its picture with the LEDs found marked, its film, what was found."""
    from native import chrome
    from native.icons import texture
    if not dpg.does_item_exist("map_sides"):
        return
    s = _state(app)
    dpg.delete_item("map_sides", children_only=True)
    w, h = px(THUMB_W), px(THUMB_H)
    row = None
    for i, side in enumerate(s["sides"]):
        if i % 4 == 0:
            row = dpg.add_group(horizontal=True, horizontal_spacing=px(12), parent="map_sides")
        with dpg.group(parent=row):
            with dpg.group(horizontal=True):
                dpg.add_text(f"side {i + 1}", color=chrome.TEXT)
                dpg.add_combo(ANGLES, default_value=side["angle"], width=px(62), user_data=i,
                              callback=lambda sn, v, k: s["sides"][k].__setitem__("angle", v))
                chrome.tip("how far the object was turned from the first side, anticlockwise seen from above")
                if len(s["sides"]) > 1:
                    dpg.add_image_button(texture("close", px(12)), width=px(12), height=px(12), frame_padding=2, tint_color=chrome.DIM,
                                         user_data=i, callback=lambda sn, a, k: _drop_side(app, k))
                    chrome.tip("this side gone")
            th = side.get("thumb")
            if th is not None and dpg.does_item_exist(th[0]):
                dpg.add_image(th[0], width=th[1], height=th[2])
            else:
                with dpg.drawlist(width=w, height=h):
                    dpg.draw_rectangle((1, 1), (w - 1, h - 1), color=tuple(chrome.LINE[:3]) + (255,), rounding=3)
                    size = px(13)
                    tw = typeface.measure("no film yet", "body", size)
                    typeface.draw_text(((w - tw) / 2, (h - size) / 2), "no film yet", size, color=tuple(chrome.DIM[:3]) + (255,))
            dpg.add_button(label="Add its film...", width=w, user_data=i, callback=lambda sn, a, k: _choose_film(app, k))
            chrome.tip("a video of this side filmed while the plan played (mp4, mov, avi, mkv, webm) - read with ffmpeg")
            dpg.add_text(side["words"] if side["words"] != "no film yet" else "", color=chrome.DIM, wrap=w, tag=f"map_side_words_{i}")


def _forget(thumb):
    """A side's old picture let go, once no image shows it."""
    if thumb is not None and dpg.does_item_exist(thumb[0]):
        dpg.delete_item(thumb[0])


def _choose_film(app, k):
    _state(app)["film_for"] = k
    dpg.show_item("map_film_dialog")


def _film_chosen(app, path):
    s = _state(app)
    k = s.get("film_for", 0)
    if not path or not (0 <= k < len(s["sides"])):
        return
    if not cm.ffmpeg():
        s["sides"][k]["words"] = "reading a video needs ffmpeg on the PATH"; _sides(app); return
    name = os.path.basename(path)
    _analyse(app, k, lambda plan, log: _from_video(path, plan, log), name)


def _from_video(path, plan, log):
    keep, fps, times = cm.read_video(path, plan, across=320, log=log)
    return cm.scan(keep, fps, plan, times=times, log=log)


def _analyse(app, k, work, what):
    """A side's film read on a worker thread (one at a time, the rest waiting
    their turn); its result comes back through poll()."""
    s = _state(app)
    side = s["sides"][k]
    side["what"] = what
    if s["busy"] is not None:
        s["queue"].append((k, work, what))
        side["words"] = f"{what}: waiting its turn"
        _sides(app); return
    plan = _plan(app)
    side["words"] = f"reading {what}..."
    _sides(app)
    box = {"k": k, "log": "", "shown": "", "result": None, "error": None, "n": plan.n}

    def run():
        try:
            box["result"] = work(plan, lambda m: box.__setitem__("log", m))
        except Exception as e:
            box["error"] = str(e) or type(e).__name__
    s["busy"] = box
    threading.Thread(target=run, daemon=True).start()


def _thumb(k, dark, found):
    """The side's dark picture brightened, the LEDs found marked on it: (texture, width, height) to show."""
    from native.textures import registry
    from native import chrome, render
    img = np.clip(np.asarray(dark, np.float32) * 1.6, 0, 255)
    rgb = np.stack([img, img, img], 2).astype(np.uint8)
    acc = np.asarray(chrome.ACCENT[:3], np.uint8)
    for u, v, _ in found.values():
        x, y = int(round(u)), int(round(v))
        rgb[max(0, y - 1):y + 2, max(0, x - 1):x + 2] = acc
    tag = f"map_thumb_{k}_{dpg.generate_uuid()}"          # a new name each time: an image may still show the last
    dpg.add_static_texture(rgb.shape[1], rgb.shape[0], render.texture_rgba(rgb), tag=tag, parent=registry())
    h, w = rgb.shape[:2]
    f = min(px(THUMB_W) / w, px(THUMB_H) / h)
    return tag, max(1, int(w * f)), max(1, int(h * f))


# --- the webcam (OpenCV, optional) ----------------------------------------------------------------
def webcam(app, index=0):
    """The plan played while the webcam's pictures are taken: a side without a video file."""
    if not webcam_ok():
        app.gp.status("the webcam needs OpenCV: pip install opencv-python (a video from any camera works without it)"); return
    s = _state(app)
    if s["webcam"] is not None:
        app.gp.status("the webcam is already filming"); return
    k = next((i for i, side in enumerate(s["sides"]) if side["found"] is None), None)
    if k is None:
        _add_side(app); k = len(s["sides"]) - 1
    rec = {"frames": [], "times": [], "stop": False, "error": None}

    def grab():
        import cv2
        cam = cv2.VideoCapture(index)
        try:
            if not cam.isOpened():
                rec["error"] = f"no webcam at index {index}"; return
            while not rec["stop"]:
                ok, f = cam.read()
                if not ok:
                    continue
                g = cv2.cvtColor(f, cv2.COLOR_BGR2GRAY)
                h, w = g.shape
                rec["frames"].append(cv2.resize(g, (320, max(2, int(h * 320 / w)))))
                rec["times"].append(time.perf_counter())
        except Exception as e:
            rec["error"] = str(e)
        finally:
            cam.release()
    rec["thread"] = threading.Thread(target=grab, daemon=True)
    rec["thread"].start()
    s["webcam"] = {"k": k, "rec": rec}
    play(app, record=rec)
    s["sides"][k]["words"] = "filming with the webcam..."
    _sides(app)


def _webcam_done(app):
    """The webcam's pictures, once the plan has played and the camera let go: evened out and read as a side."""
    s = _state(app)
    w = s["webcam"]
    rec = w["rec"]
    if rec["error"] and s["play"] is not None and s["play"].get("record") is rec:
        stop(app)                                            # no camera: the plan need not run on
    if not rec["stop"] or rec["thread"].is_alive():
        return
    s["webcam"] = None
    k = w["k"]
    if k >= len(s["sides"]):
        return
    if rec["error"] or len(rec["frames"]) < 10:
        s["sides"][k]["words"] = rec["error"] or "the webcam gave no pictures"; _sides(app); return
    frames, fps = cm.resample(rec["frames"], rec["times"], 30.0)
    _analyse(app, k, lambda plan, log: cm.scan(frames, fps, plan, log=log), "the webcam's pictures")


# --- per frame, and the part ---------------------------------------------------------------------
def poll(app):
    s = getattr(app, "_map", None)
    if s is None:
        return
    if s["play"] is not None:
        _drive(app)
    if s["webcam"] is not None:
        _webcam_done(app)
    box = s["busy"]
    if box is not None:
        if box["result"] is None and box["error"] is None:
            if box["log"] != box["shown"] and dpg.does_item_exist(f"map_side_words_{box['k']}"):
                box["shown"] = box["log"]
                dpg.set_value(f"map_side_words_{box['k']}", f"reading {s['sides'][box['k']].get('what', 'the film')}: {box['log']}")
        else:
            s["busy"] = None
            side = s["sides"][box["k"]] if box["k"] < len(s["sides"]) else None
            if side is not None:
                what = side.get("what", "the film")
                if box["error"]:
                    side["words"] = f"{what}: could not read it - {box['error']}"
                    side["found"] = None
                else:
                    found, dark = box["result"]
                    side["found"] = found
                    side["words"] = f"{what}: {len(found)} of {box['n']} LEDs found"
                    old, side["thumb"] = side.get("thumb"), _thumb(box["k"], dark, found)
            _sides(app)
            if side is not None and not box["error"]:
                _forget(old)
            if s["queue"]:
                k, work, what = s["queue"].pop(0)
                if k < len(s["sides"]):
                    _analyse(app, k, work, what)
    if dpg.does_item_exist("map_stream_words") and dpg.is_item_shown(TAG):
        _plan_words(app)                                     # a count or time set from outside (MIDI, a hook) as well as typed
        d = getattr(app, "ddp", None)
        dpg.set_value("map_stream_words", f"streaming to {app.active_host()}: the device lights the plan too" if d is not None
                      else "not streaming: only the sim shows the plan - Stream the sim to the device (Ctrl+Shift+T) to light it")


def make(app):
    """The sides' LEDs as a points part in the shape (the geometry becomes the shape if it was not)."""
    from native import shape_gallery
    s = _state(app)
    sides = [(float(side["angle"].rstrip("°")), side["found"]) for side in s["sides"] if side.get("found")]
    if not sides:
        dpg.set_value("map_result", "no side has a film read yet"); return
    n = _plan(app).n
    try:
        pos, full = cm.combine(sides, n)
    except Exception as e:
        dpg.set_value("map_result", f"could not place them: {e}"); return
    g = app.project.geometry
    sp = g.params if g is not None and g.kind == "shape" else {}
    height = units.from_unit(float(dpg.get_value("map_height")), dict(sp, unit="cm"))
    shape_gallery.add(app, cm.to_part(pos, full, height=height), close=False)
    seen = int(np.count_nonzero(full))
    if len(sides) == 1:
        words = (f"{n} LEDs, flat as the one side faces the camera: {seen} found"
                 + (f", {n - seen} placed between their neighbours" if n > seen else "") + " - film another side for 3-D")
    else:
        words = (f"{n} LEDs: {seen} seen from two sides or more"
                 + (f", {n - seen} estimated (the shape's checks list them)" if n > seen else ""))
    dpg.set_value("map_result", words)
    app.gp.status(f"mapped lights: {words}")
