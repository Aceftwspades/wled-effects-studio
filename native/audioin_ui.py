"""The Audio input frame: the device's microphone or line-in module
(native/audioin.py) - a preset per module, the pins, the levels; read
from the device, sent to it, a reboot when the change needs one, and a
level meter that reads what the device hears.

    build(app)      # the window (device_ui.build calls it)
    refresh(app)    # the fields from the project's settings
    poll(app)       # per frame: the meter's readings, the send's result
"""
import json
import queue
import threading
import time
import urllib.request

import dearpygui.dearpygui as dpg

from native import audioin

TAG = "audioin_win"
PIN_TAGS = ("ain_sd", "ain_ws", "ain_sck", "ain_mclk")


def _c():
    from native import chrome
    return chrome


def _st(app):
    return audioin.state(app.project)


def build(app):
    c = _c()
    from native import device_ui
    labels = [label for _, label, _, _ in audioin.PRESETS]
    with dpg.window(tag=TAG, show=False, width=640, height=340, no_collapse=True, no_title_bar=True):
        device_ui.header(app, "audioin")
        dpg.add_text("", tag="ain_desc", color=c.DIM, wrap=600)
        with dpg.group(horizontal=True):
            dpg.add_text("MODULE", color=c.ACCENT)
            dpg.add_combo(labels, tag="ain_preset", width=330, callback=lambda s, v: pick_preset(app, v))
            c.info("What is wired to the device: a microphone, or a line-in module - a PCM1808 / WM8782 ADC breakout, or an ES8388 "
                   "codec board (AudioKit, LyraT) with a line-in jack. The preset sets the type WLED's audioreactive usermod runs, "
                   "the levels a line signal wants, and the pins where the board fixes them.")
            dpg.add_text("", tag="ain_note", color=c.DIM, wrap=0, show=False)
        dpg.add_text("", tag="ain_preset_note", color=c.DIM, wrap=600)
        with dpg.group(horizontal=True):
            dpg.add_text("PINS", color=c.ACCENT)
            for tag, lbl in zip(PIN_TAGS, ("SD", "WS", "SCK", "MCLK")):
                dpg.add_input_int(tag=tag, label=lbl, width=52, step=0, min_value=-1, max_value=48, min_clamped=True, max_clamped=True,
                                  callback=lambda s, v: _pins_edited(app))
            c.tip("the I2S wires: SD the data in (DOUT / ASDOUT on the module), WS the word select (LRCK), SCK the bit clock (BCK); "
                  "MCLK the master clock a line-in ADC or a codec needs (-1: none). -1 = not wired.")
            dpg.add_input_int(tag="ain_sda", label="SDA", width=52, step=0, min_value=-1, max_value=48, min_clamped=True, max_clamped=True,
                              callback=lambda s, v: _pins_edited(app))
            dpg.add_input_int(tag="ain_scl", label="SCL", width=52, step=0, min_value=-1, max_value=48, min_clamped=True, max_clamped=True,
                              callback=lambda s, v: _pins_edited(app))
            c.tip("WLED's I2C pins - an ES8388 or ES7243 is set up over I2C before it sends audio")
        with dpg.group(horizontal=True):
            dpg.add_text("LEVELS", color=c.ACCENT)
            dpg.add_slider_int(tag="ain_gain", label="gain", width=130, min_value=0, max_value=255, callback=lambda s, v: _level_edited(app))
            c.tip("audioreactive's gain, 0..255 (60 is WLED's default for a mic; a line signal is louder and steadier: 40)")
            dpg.add_slider_int(tag="ain_squelch", label="squelch", width=110, min_value=0, max_value=255, callback=lambda s, v: _level_edited(app))
            c.tip("the noise gate: what counts as silence (10 for a mic; 4 for a line-in, which has no room noise)")
            dpg.add_combo(audioin.AGC, tag="ain_agc", label="AGC", width=80, callback=lambda s, v: _level_edited(app))
            c.tip("automatic gain: off, normal, vivid or lazy. A line-in seldom needs it.")
        dpg.add_separator()
        with dpg.group(horizontal=True):
            dpg.add_text("ON THE DEVICE", color=c.ACCENT)
            dpg.add_button(label="Read the device's", small=True, callback=lambda: read_device(app))
            c.tip("what the device's audioreactive is set to now (its type, pins and levels), into these fields")
            dpg.add_button(label="Send the audio input", small=True, callback=lambda: send(app))
            c.tip("over /json/cfg; the levels take at once, a new type or new pins after a reboot (offered when needed)")
            dpg.add_button(label="Reboot the device", small=True, callback=lambda: reboot(app))
            c.tip("restarts the device so a new type or new pins take effect; the LEDs go dark for a few seconds")
            dpg.add_checkbox(label="meter", tag="ain_meter", callback=lambda s, v: _meter(app, bool(v)))
            c.tip("reads the level the device hears, twice a second, while ticked: play something into the line-in and watch it move")
        with dpg.group(horizontal=True):
            dpg.add_progress_bar(tag="ain_level", width=300, default_value=0.0, overlay="")
            dpg.add_text("", tag="ain_source", color=c.DIM, wrap=0)
        dpg.add_text("", tag="ain_flash", color=c.DIM, wrap=600)
        dpg.add_text("", tag="ain_log", color=c.DIM, wrap=600)


def refresh(app):
    if not dpg.does_item_exist("ain_preset"):
        return
    st = _st(app)
    label, spec, note = audioin.PRESET.get(st.get("preset"), audioin.PRESET["inmp441"])
    dpg.set_value("ain_preset", label)
    dpg.set_value("ain_preset_note", note)
    pins = (list(st.get("pins") or []) + [-1] * 4)[:4]
    for tag, v in zip(PIN_TAGS, pins):
        dpg.set_value(tag, int(v))
    dpg.configure_item("ain_mclk", enabled=audioin.uses_mclk(st))
    i2c = (list(st.get("i2c") or []) + [-1, -1])[:2]
    dpg.set_value("ain_sda", int(i2c[0])); dpg.set_value("ain_scl", int(i2c[1]))
    for t in ("ain_sda", "ain_scl"):
        dpg.configure_item(t, show=audioin.needs_i2c(st))
    on = int(st.get("type", 1)) < 254
    for t in PIN_TAGS + ("ain_gain", "ain_squelch", "ain_agc"):
        dpg.configure_item(t, enabled=on)
    dpg.set_value("ain_gain", int(st.get("gain", 60)))
    dpg.set_value("ain_squelch", int(st.get("squelch", 10)))
    dpg.set_value("ain_agc", audioin.AGC[int(st.get("agc", 0)) % 4])
    dpg.set_value("ain_desc", audioin.describe(st))
    fl = audioin.flags(st)
    dpg.set_value("ain_flash", "a fresh flash boots with these (the studio's env carries them as flags: " + " ".join(fl) + ")" if fl
                  else "set the pins (or read the device's) and a fresh flash boots with them; until then the firmware keeps its own defaults")


def pick_preset(app, label):
    key = next((k for k, l, _, _ in audioin.PRESETS if l == label), None)
    if key is None:
        return
    st = _st(app)
    audioin.apply_preset(st, key)
    app.project.save(); refresh(app)
    app.gp.status(f"audio input: {audioin.describe(st)}")


def _pins_edited(app):
    st = _st(app)
    st["pins"] = [int(dpg.get_value(t)) for t in PIN_TAGS]
    st["i2c"] = [int(dpg.get_value("ain_sda")), int(dpg.get_value("ain_scl"))]
    app.project.save(); refresh(app)


def _level_edited(app):
    st = _st(app)
    st["gain"] = int(dpg.get_value("ain_gain")); st["squelch"] = int(dpg.get_value("ain_squelch"))
    st["agc"] = audioin.AGC.index(dpg.get_value("ain_agc")) if dpg.get_value("ain_agc") in audioin.AGC else 0
    app.project.save(); refresh(app)


def _host(app):
    from native import device_ui
    host = app.active_host()
    if not host:
        device_ui.show(app, "devices"); app.gp.status("choose a device first")
    return host


def _post(host, path, body, timeout=8):
    h = host if host.startswith("http") else "http://" + host
    req = urllib.request.Request(h + path, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def read_device(app):
    from native import devices
    host = _host(app)
    if not host:
        return
    try:
        cfg = devices._get(host, "/json/cfg", 6)
    except Exception as e:
        dpg.set_value("ain_log", f"could not read the device's config: {e}"); return
    st = _st(app)
    if "AudioReactive" not in ((cfg.get("um") or {})):
        dpg.set_value("ain_log", "the device has no audioreactive usermod in its config - flash it with audio on first"); return
    st.update(audioin.from_wled_cfg(cfg, st))
    app.project.save(); refresh(app)
    msg = f"the device's audio input read: {audioin.describe(st)}"
    dpg.set_value("ain_log", msg); app.gp.status(msg)


def send(app):
    from native import device_ui, devices
    host = _host(app)
    if not host:
        return
    st = _st(app)
    before = None
    try:
        before = audioin.from_wled_cfg(devices._get(host, "/json/cfg", 6))
    except Exception:
        pass
    body = audioin.wled_cfg(st)
    try:
        _post(host, "/json/cfg", body)
    except Exception as e:
        msg = f"the device refused the config: {e}"
        dpg.set_value("ain_log", msg); app.gp.status(msg); return
    msg = f"audio input sent to {host}: {audioin.describe(st)}"
    if before is None or audioin.needs_reboot(before, st):
        msg += " - a new type or new pins take effect after a reboot"
        _c().confirm(app, "Audio input", "The device's audioreactive takes a new type or new pins on its next boot. Reboot it now? "
                     "(the LEDs go dark for a few seconds)", [("Reboot", lambda: reboot(app)), ("Later", None)])
    dpg.set_value("ain_log", msg); app.gp.status(msg); device_ui.send_log(app, msg)


def reboot(app):
    host = _host(app)
    if not host:
        return
    try:
        _post(host, "/json/state", {"rb": True}, timeout=5)
        msg = f"{host} is rebooting - back in a few seconds"
    except Exception as e:
        msg = f"the reboot request failed: {e}"
    dpg.set_value("ain_log", msg); app.gp.status(msg)


# --- the meter: the level the device hears, on a thread while ticked ---------------------
def _meter(app, on):
    if not on:
        app._ain_meter = None
        if dpg.does_item_exist("ain_level"):
            dpg.set_value("ain_level", 0.0); dpg.configure_item("ain_level", overlay="")
        return
    host = _host(app)
    if not host:
        dpg.set_value("ain_meter", False); return
    from native import devices
    q = app._ain_meter = queue.Queue()
    stop = q                                              # the thread stops when the app's queue is no longer this one

    def work():
        while getattr(app, "_ain_meter", None) is stop:
            try:
                info = devices._get(host, "/json/info", 3)
                q.put(audioin.level_of(info))
            except Exception as e:
                q.put((None, f"no answer from {host}: {e}"))
            time.sleep(0.5)
    threading.Thread(target=work, daemon=True).start()


def poll(app):
    q = getattr(app, "_ain_meter", None)
    if q is None or not dpg.does_item_exist("ain_level"):
        return
    got = None
    try:
        while True:
            got = q.get_nowait()
    except queue.Empty:
        pass
    if got is None:
        return
    level, src = got
    if level is None:
        dpg.set_value("ain_level", 0.0); dpg.configure_item("ain_level", overlay="no level")
    else:
        dpg.set_value("ain_level", max(0.0, min(1.0, level / 255.0))); dpg.configure_item("ain_level", overlay=f"{int(level)} / 255")
    dpg.set_value("ain_source", src or "")
