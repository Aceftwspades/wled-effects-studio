"""The "Map lights by camera" dialog (the ninth pass's S18): the plan played
- in the sim, and on the device while the sim is streamed to it - each
side's film added (a video from any camera, read on a worker thread), or
each side mapped live by a webcam - the studio lights each step and takes
its picture itself, no film and no clock (after Lightwork, PWRFLcreative) -
and the points part made from them (camera_map does the finding and the
3-D). The plan lights one LED at a time, or every LED at once by binary
codes (seconds, not minutes, for a long string); the camera's live view
calibrates the finding (threshold, LED brightness, blob distance and size);
a map goes out to, and comes in from, Lightwork's layout CSV.

    camera_map_ui.build(app)     # the window, once (shape_ui.build calls it)
    camera_map_ui.show(app)
    camera_map_ui.poll(app)      # per frame: the plan's lighting, a film's reading coming back, a webcam's pictures
"""
import os
import threading
import time

import numpy as np
import dearpygui.dearpygui as dpg

from native import camera_map as cm, units, typeface, form, num, weight, video
from native.typeface import px

TAG = "map_win"
ANGLES = ("0°", "90°", "180°", "270°", "45°", "135°", "225°", "315°")
VIDEO = (".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v")
THUMB_W, THUMB_H = 132, 99           # a side's picture in its card (at 100%): the film fitted inside


def _state(app):
    s = getattr(app, "_map", None)
    if s is None:
        s = app._map = {"sides": [], "play": None, "busy": None, "queue": [], "cam": None,
                        "live": None, "calib": None}
    return s


def webcam_ok():
    """A webcam can be read: through ffmpeg (the video module's), no OpenCV needed."""
    return bool(video.ffmpeg())


METHODS = (("sequence", "one LED at a time"), ("binary", "every LED at once, by code"))
CAM_W, CAM_H = 320, 240               # the camera's picture as mapping reads it (all of it, barred where narrower)


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
        with form.row("how", tip="one LED at a time: slow for a long string, sure where LEDs are close or blend; "
                                 "every LED at once by code (Lightwork's binary mode): each LED flashes its own address "
                                 "in a few pictures - seconds for hundreds - wants a darker room"):
            dpg.add_combo([n for _, n in METHODS], tag="map_method", default_value=METHODS[0][1], width=px(220),
                          callback=lambda s_, v: _plan_words(app))
        with form.row("LED brightness", tip="how bright the plan lights the LEDs, 0..255: lower it if the camera flares "
                                            "(a lit LED a blot, its neighbours run into it)"):
            num.add("map_bright", 255, 8, 255, integer=True, width=px(120))
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
        typeface.label(dpg.add_text("OR MAP LIVE WITH A WEBCAM", color=chrome.ACCENT))
        dpg.add_text("The studio lights each step on the device (streamed) and takes the webcam's picture itself - no film. "
                     "Calibrate first: the view shows what is found.", color=chrome.DIM, wrap=px(590))
        with dpg.group(horizontal=True):
            dpg.add_combo([], tag="map_cam", width=px(250))
            dpg.add_button(label="Find", tag="map_cam_find", callback=lambda: find_cameras(app))
            chrome.tip("the webcams ffmpeg can open on this computer")
            dpg.add_button(label="Calibrate", tag="map_calib", callback=lambda: calibrate(app))
            chrome.tip("every LED lit, the camera's view with the LEDs found marked: set the threshold, the LED brightness, "
                       "the blob distance and size until the count is right; again: stop")
            dpg.add_button(label="Map live", tag="map_live", callback=lambda: live(app))
            weight.primary("map_live")
            chrome.tip("the plan stepped through with the webcam: each step lit, let settle, pictured - the next side without "
                       "an empty slot gets it")
        from native.textures import registry
        if not dpg.does_item_exist("map_cam_tex"):
            dpg.add_dynamic_texture(CAM_W, CAM_H, [0.0] * (CAM_W * CAM_H * 4), tag="map_cam_tex", parent=registry())
        with dpg.group(horizontal=True):
            dpg.add_image("map_cam_tex", width=px(CAM_W), height=px(CAM_H), tag="map_cam_view")
            with dpg.group():
                with form.row("threshold", width=px(110), tip="how far above the picture's noise a spot must stand to be an "
                                                              "LED (the noise's spread): higher - only bright, sure spots"):
                    num.add("map_conf", cm.CONF, 3.0, 60.0, digits=1, width=px(110))
                with form.row("apart", width=px(110), tip="the least distance between two LEDs found, in the picture's pixels "
                                                          "(of 320 across): flare and doubles closer than this are dropped"):
                    num.add("map_dist", 4.0, 1.0, 40.0, digits=1, unit="px", width=px(110))
                with form.row("largest", width=px(110), tip="the most pixels a spot may cover at half its height: LEDs run "
                                                            "together, a lamp, a window are not an LED (0: any size)"):
                    num.add("map_area", 0, 0, 2000, integer=True, unit="px", width=px(110))
                with form.row("settle", width=px(110), tip="pictures waited after each step before one is taken (Lightwork's "
                                                           "frame skip): more for a slow camera or a long stream delay"):
                    num.add("map_settle", 3, 1, 15, integer=True, width=px(110))
                dpg.add_text("", tag="map_cam_words", color=chrome.DIM, wrap=px(220))
        typeface.label(dpg.add_text("3. THE PART", color=chrome.ACCENT))
        with dpg.group(horizontal=True):
            dpg.add_button(label="Make the part", tag="map_make", callback=lambda: make(app))
            weight.primary("map_make")
            chrome.tip("the lights as a points part in the shape, in wiring order: an LED no two sides saw is estimated "
                       "(the shape's checks list them, to drag where they are)")
            dpg.add_text("", tag="map_result", color=chrome.DIM, wrap=px(430))
        with dpg.group(horizontal=True):
            dpg.add_button(label="Save CSV (Lightwork)", tag="map_csv_out", callback=lambda: export_csv(app))
            chrome.tip("the shape's LEDs as Lightwork's layout CSV - address,x,y,z, each 0..1 - for Lightwork's scraper, "
                       "MadMapper or TouchDesigner; into the project's export folder")
            dpg.add_button(label="Import CSV...", tag="map_csv_in", callback=lambda: dpg.show_item("map_csv_dialog"))
            chrome.tip("a Lightwork layout CSV (address,x,y,z) as a points part, sized to its height above")
    with dpg.file_dialog(directory_selector=False, show=False, tag="map_csv_dialog", width=px(640), height=px(420),
                         callback=lambda s, a: import_csv(app, a.get("file_path_name", ""))):
        dpg.add_file_extension(".csv", color=(200, 180, 90))
        dpg.add_file_extension(".*")
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
    dpg.set_value("map_ff_words", "ffmpeg is not on the PATH, so neither a video nor a webcam can be read: install it "
                  "(ffmpeg.org) and restart the studio")
    dpg.configure_item("map_ff_words", show=not cm.ffmpeg())
    chrome._centre(TAG, 620, 720)
    dpg.show_item(TAG)


# AI: below section was generated by an AI
def _method(app):
    words = dpg.get_value("map_method") if dpg.does_item_exist("map_method") else METHODS[0][1]
    return next((k for k, n in METHODS if n == words), "sequence")


def _plan(app):
    return cm.make_plan(_method(app), int(dpg.get_value("map_n")), on=float(dpg.get_value("map_on")), off=0.05)


def _found_settings():
    """The calibration's settings, for every finding (a film's, live)."""
    area = int(dpg.get_value("map_area")) if dpg.does_item_exist("map_area") else 0
    return dict(conf=float(dpg.get_value("map_conf")) if dpg.does_item_exist("map_conf") else cm.CONF,
                min_dist=float(dpg.get_value("map_dist")) if dpg.does_item_exist("map_dist") else 4.0,
                max_area=area or None)


def _bright(app):
    return int(dpg.get_value("map_bright")) if dpg.does_item_exist("map_bright") else 255


def _light(app, lit, n):
    """The LEDs to light now - None (dark), "all", an index or an (n,) bool mask - in the sim's wiring test and as
    the device's own frame while streaming, at the plan's LED brightness."""
    wt = getattr(app, "wiring", None)
    b = _bright(app)
    m = np.zeros(n, bool)
    if isinstance(lit, str) and lit == "all":
        m[:] = True
    elif isinstance(lit, np.ndarray):
        m = np.asarray(lit, bool)[:n]
    elif lit is not None:
        m[int(lit)] = True
    if wt is not None:
        wt.colour = (b, b, b)
        wt.mode, wt.mask = ("mask", m) if m.any() else ("off", None)
    frame = np.zeros((n, 3), np.uint8)
    frame[m] = b
    app._map_frame = frame.tobytes()


def _plan_words(app):
    if dpg.does_item_exist("map_plan_words"):
        p = _plan(app)
        m, sec = divmod(int(round(p.total)), 60)
        dpg.set_value("map_plan_words", f"the plan takes {m} min {sec} s" if m else f"the plan takes {sec} s")
# AI: end


# --- playing the plan ---------------------------------------------------------------------------
def play(app):
    """The plan on: the wiring test driven through it (the sim shows it; the
    device while the sim is streamed), to be filmed."""
    s = _state(app)
    if s["play"] is not None:
        stop(app)
    s["play"] = {"plan": _plan(app), "t0": time.perf_counter() + 0.4}
    app.wiring_start("index")
    app.wiring.mode = "off"
    app.gp.status("the plan is playing: film it" + ("" if getattr(app, "ddp", None) is not None else
                                                   " (the sim only: stream the sim to light the device)"))


def stop(app):
    s = _state(app)
    app._map_frame = None
    if s["play"] is not None:
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
    _light(app, plan.lit(t) if t >= 0 else None, plan.n)   # an LED past the sim's count lights on the device only
    left = max(0.0, plan.total - t)
    if dpg.does_item_exist("map_play_words"):
        now = (f"LED {what + 1} of {plan.n}" if isinstance(what, int) else
               f"bit {what[1] + 1} of {plan.bits}{' inverted' if what[2] else ''}" if isinstance(what, tuple) else
               ("flash" if what == "all" else "dark"))
        dpg.set_value("map_play_words", now + f" - {int(left) // 60}:{int(left) % 60:02d} left")
    if t > plan.total + 0.3:
        s["play"] = None
        app._map_frame = None
        app.wiring_stop()
        if dpg.does_item_exist("map_play_words"):
            dpg.set_value("map_play_words", "played")
        app.gp.status("the plan has played: add the film of this side")


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
    settings = _found_settings()
    _analyse(app, k, lambda plan, log: _from_video(path, plan, log, settings), name)


def _from_video(path, plan, log, settings=None):
    keep, fps, times = cm.read_video(path, plan, across=320, log=log)
    return cm.scan(keep, fps, plan, times=times, log=log, **(settings or {}))


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


# AI: below section was generated by an AI
# --- the webcam (ffmpeg): calibration and mapping live -------------------------------------------------
def find_cameras(app):
    cams = [n for n, _ in video.webcams()]
    dpg.configure_item("map_cam", items=cams)
    if cams and dpg.get_value("map_cam") not in cams:
        dpg.set_value("map_cam", cams[0])
    _cam_words(f"{len(cams)} camera(s) found" if cams else
               ("no camera found" if video.ffmpeg() else "a webcam needs ffmpeg on the PATH (ffmpeg.org)"))
    return cams


def _cam_words(text):
    if dpg.does_item_exist("map_cam_words"):
        dpg.set_value("map_cam_words", text)


def _open_cam(app):
    """The chosen webcam, open (the one already open if it is that one)."""
    s = _state(app)
    name = dpg.get_value("map_cam") or (find_cameras(app) or [None])[0]
    if not name:
        _cam_words("no camera: Find, or plug one in"); return None
    cam = s["cam"]
    if cam is not None and cam.label == name and cam.error is None:
        return cam
    if cam is not None:
        cam.close()
    try:
        s["cam"] = video.open_source("webcam", name=name, width=CAM_W, height=CAM_H, fit=True)
    except Exception as e:
        s["cam"] = None
        _cam_words(str(e)); return None
    return s["cam"]


def _close_cam(app):
    s = _state(app)
    if s["cam"] is not None:
        s["cam"].close()
        s["cam"] = None


def _grey(frame):
    return np.asarray(frame, np.float32) @ np.asarray([0.299, 0.587, 0.114], np.float32)


def _show(grey, spots=()):
    """The camera's picture in the view, the LEDs found marked."""
    from native import chrome
    if not dpg.does_item_exist("map_cam_tex"):
        return
    g = np.clip(np.asarray(grey, np.float32), 0, 255)
    rgb = np.stack([g, g, g], -1)
    acc = np.asarray(chrome.ACCENT[:3], np.float32)
    for u, v, _ in spots:
        x, y = int(round(u)), int(round(v))
        for dx, dy in ((-3, 0), (3, 0), (0, -3), (0, 3), (-2, 0), (2, 0), (0, -2), (0, 2)):
            if 0 <= y + dy < CAM_H and 0 <= x + dx < CAM_W:
                rgb[y + dy, x + dx] = acc
    rgba = np.concatenate([rgb / 255.0, np.ones((CAM_H, CAM_W, 1), np.float32)], -1)
    dpg.set_value("map_cam_tex", rgba.ravel())


def _step_box(app, lit, n):
    """A step: lit now, its picture to be taken once `settle` new pictures have come."""
    cam = _state(app)["cam"]
    _light(app, lit, n)
    return {"after": cam.n + max(1, int(dpg.get_value("map_settle")))}


def calibrate(app):
    """Every LED lit and the camera's view, the LEDs found marked and counted - against a dark picture taken
    first; again: stopped."""
    s = _state(app)
    if s["calib"] is not None:
        _stop_calib(app); return
    if s["live"] is not None or s["play"] is not None:
        app.gp.status("a plan is running: stop it first"); return
    if _open_cam(app) is None:
        return
    n = int(dpg.get_value("map_n"))
    app.wiring_start("index")
    s["calib"] = {"n": n, "phase": "dark", "dark": None, "step": _step_box(app, None, n)}
    dpg.configure_item("map_calib", label="Stop")
    _cam_words("the dark picture...")


def _stop_calib(app):
    s = _state(app)
    s["calib"] = None
    app._map_frame = None
    app.wiring_stop()
    if dpg.does_item_exist("map_calib"):
        dpg.configure_item("map_calib", label="Calibrate")


def _poll_calib(app):
    s = _state(app)
    c = s["calib"]
    cam = s["cam"]
    if cam is None or cam.error:
        _stop_calib(app); _cam_words(f"the camera stopped: {cam.error if cam else 'closed'}"); return
    frame, n = cam.latest()
    if frame is None or n < c["step"]["after"]:
        return
    g = _grey(frame)
    if c["phase"] == "dark":
        c["dark"] = g
        c["phase"] = "lit"
        c["step"] = _step_box(app, "all", c["n"])
        return
    c["step"]["after"] = n + 1                                  # every new picture from here on
    spots = cm.find_blobs(g, c["dark"], limit=c["n"] * 2 + 8, **_found_settings())
    _show(g, spots)
    _cam_words(f"{len(spots)} found of {c['n']} LEDs"
               + (" - too many: raise the threshold, lower the LED brightness or darken the room" if len(spots) > c["n"] else
                  " - too few: lower the threshold, or the distance apart" if len(spots) < c["n"] * 0.9 else " - ready to map"))


def live(app):
    """The plan stepped through with the webcam: each step lit, settled, pictured; read as the next empty side."""
    s = _state(app)
    if s["live"] is not None:
        _end_live(app, "stopped"); return
    if s["calib"] is not None:
        _stop_calib(app)
    if s["play"] is not None:
        stop(app)
    if _open_cam(app) is None:
        return
    k = next((i for i, side in enumerate(s["sides"]) if side["found"] is None), None)
    if k is None:
        _add_side(app); k = len(s["sides"]) - 1
    plan = _plan(app)
    app.wiring_start("index")
    steps = plan.steps()
    s["live"] = {"k": k, "plan": plan, "steps": steps, "i": 0, "frames": {}, "step": _step_box(app, steps[0][1], plan.n)}
    dpg.configure_item("map_live", label="Stop")
    s["sides"][k]["words"] = "mapping live..."
    _sides(app)


def _end_live(app, words=None):
    s = _state(app)
    lv = s["live"]
    s["live"] = None
    app._map_frame = None
    app.wiring_stop()
    if dpg.does_item_exist("map_live"):
        dpg.configure_item("map_live", label="Map live")
    if words and lv is not None and lv["k"] < len(s["sides"]):
        s["sides"][lv["k"]]["words"] = words
        _sides(app)


def _poll_live(app):
    s = _state(app)
    lv = s["live"]
    cam = s["cam"]
    if cam is None or cam.error:
        _end_live(app, f"the camera stopped: {cam.error if cam else 'closed'}"); return
    frame, n = cam.latest()
    if frame is None or n < lv["step"]["after"]:
        return
    what, _ = lv["steps"][lv["i"]]
    g = _grey(frame)
    lv["frames"][what] = g
    _show(g)
    lv["i"] += 1
    if dpg.does_item_exist("map_play_words"):
        dpg.set_value("map_play_words", f"live: picture {lv['i']} of {len(lv['steps'])}")
    if lv["i"] < len(lv["steps"]):
        lv["step"] = _step_box(app, lv["steps"][lv["i"]][1], lv["plan"].n)
        return
    frames, plan, k = lv["frames"], lv["plan"], lv["k"]
    _end_live(app)
    times = {w: w for w, _ in plan.steps()}
    settings = _found_settings()
    _analyse(app, k, lambda p_, log: cm.scan(frames, None, plan, times=times, log=log, **settings), "the webcam, live")


# --- Lightwork's layout CSV ----------------------------------------------------------------------------
def export_csv(app):
    """The shape's LEDs, in wiring order, as Lightwork's layout CSV in the project's export folder."""
    g = app.project.geometry
    if g is None or g.pos is None:
        dpg.set_value("map_result", "no shape to save"); return None
    order = g.phys if getattr(g, "phys", None) is not None else np.arange(len(g.pos))
    pos = np.asarray(g.pos, np.float64)[np.asarray(order)]
    found = np.isfinite(pos).all(1)
    if not found.any():
        dpg.set_value("map_result", "the shape has no LED positions"); return None
    out = os.path.join(app.project.path, "export", "lightwork_layout.csv")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        f.write(cm.to_csv(pos, found))
    words = f"{int(found.sum())} LEDs saved as Lightwork's layout: {out}"
    dpg.set_value("map_result", words)
    app.gp.status(words)
    return out


def import_csv(app, path):
    """A Lightwork layout CSV as a points part (sized to the height above)."""
    from native import shape_gallery
    if not path:
        return False
    try:
        pos, found = cm.from_csv(open(path, encoding="utf-8").read())
    except Exception as e:
        dpg.set_value("map_result", f"could not read {os.path.basename(path)}: {e}"); return False
    cm._between(pos, found) if found.any() and not found.all() else None
    g = app.project.geometry
    sp = g.params if g is not None and g.kind == "shape" else {}
    height = units.from_unit(float(dpg.get_value("map_height")), dict(sp, unit="cm"))
    flat = float(np.ptp(pos[found][:, 2])) < 1e-9
    q = cm.to_part(pos, found, height=None if flat else height, name=os.path.splitext(os.path.basename(path))[0])
    shape_gallery.add(app, q, close=False)
    words = f"{int(found.sum())} LEDs from {os.path.basename(path)}" + (f", {int((~found).sum())} missing put between neighbours" if not found.all() else "")
    dpg.set_value("map_result", words)
    app.gp.status(words)
    return True
# AI: end


# --- per frame, and the part ---------------------------------------------------------------------
def poll(app):
    s = getattr(app, "_map", None)
    if s is None:
        return
    if s["play"] is not None:
        _drive(app)
    if s["calib"] is not None:
        _poll_calib(app)
    if s["live"] is not None:
        _poll_live(app)
    if s["cam"] is not None and s["calib"] is None and s["live"] is None and not dpg.is_item_shown(TAG):
        _close_cam(app)                                      # the window closed: the camera off
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
