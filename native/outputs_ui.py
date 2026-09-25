"""The Outputs frame: the wiring split into the device's LED outputs
(native/outputs.py), the power the frame draws, WLED's brightness
limiter previewed, and both sent to the device.

    build(app)      # the window (device_ui.build calls it)
    refresh(app)    # the rows from the project's outputs
    poll(app)       # per frame: the power line
"""
import json
import dearpygui.dearpygui as dpg

from native.typeface import px
from native import typeface

from native import outputs, weight

TAG = "outputs_win"


def _c():
    from native import chrome
    return chrome


def _state(app):
    return app.project.options.setdefault("outputs", {"outs": [], "ma_per_led": outputs.LED_MA_DEFAULT,
                                                       "max_ma": outputs.MAX_MA_DEFAULT, "abl_preview": False})


def build(app):
    c = _c()
    from native import device_ui
    with dpg.window(tag=TAG, show=False, width=px(680), height=px(460), no_collapse=True, no_title_bar=True):
        device_ui.header(app, "outputs")
        dpg.add_text("", tag="out_desc", color=c.DIM, wrap=0)
        with dpg.group(horizontal=True):
            typeface.label(dpg.add_text("SPLIT", color=c.ACCENT))
            dpg.add_button(label="one output", small=True, callback=lambda: do_split(app, "one"))
            dpg.add_button(label="one per part", small=True, callback=lambda: do_split(app, "parts"))
            dpg.add_button(label="by count:", small=True, callback=lambda: do_split(app, "count"))
            dpg.add_input_int(tag="out_per", width=px(60), step=0, default_value=300, min_value=1, min_clamped=True)
            dpg.add_button(label="+ output", small=True, callback=lambda: add_output(app))
            dpg.add_button(label="Read the device's", small=True, callback=lambda: read_device(app))
            weight.need(dpg.last_item(), "device")
            c.info("The wiring split into the device's LED outputs: a pin, a start and a count each, the LED type and colour order, "
                   "reversed or not. Sent as the device's LED config.")
        with dpg.child_window(tag="out_rows", height=px(170), border=True):
            pass
        with dpg.group(horizontal=True):
            typeface.label(dpg.add_text("POWER", color=c.ACCENT))
            dpg.add_input_int(tag="out_ledma", label="mA per LED", width=px(60), step=0, min_value=0, max_value=255, min_clamped=True, max_clamped=True,
                              callback=lambda s, v: _set(app, "ma_per_led", int(v)))
            dpg.add_input_int(tag="out_maxma", label="supply mA", width=px(70), step=0, min_value=0, max_value=65000, min_clamped=True, max_clamped=True,
                              callback=lambda s, v: _set(app, "max_ma", int(v)))
            c.tip("0: no limit")
            dpg.add_checkbox(label="limiter in the sim", tag="out_abl",
                             callback=lambda s, v: _set(app, "abl_preview", bool(v)))
        with dpg.group(horizontal=True):
            dpg.add_text("", tag="out_power", color=c.TEXT, wrap=0)
            c.info("What this frame draws, by WLED's own maths: full white is the mA per LED (55 is WLED's default; ~12 for WS2815 at 12 V). "
                   "The supply less the ESP's 120 mA is what the device's auto brightness limiter dims to fit; the sim previews that dimming.")
        dpg.add_separator()
        with dpg.group(horizontal=True):
            typeface.label(dpg.add_text("ON THE DEVICE", color=c.ACCENT))
            dpg.add_button(label="Send outputs + power limit", small=True, callback=lambda: send(app))
            weight.primary(dpg.last_item())
            weight.need(dpg.last_item(), lambda a: bool(a.active_host()) and bool(_state(a).get("outs")))
            c.tip("over /json/cfg; the device re-initialises its outputs (reboot it if it does not)")
        dpg.add_text("", tag="out_log", color=c.DIM, wrap=0)


def refresh(app):
    if not dpg.does_item_exist("out_rows"):
        return
    c = _c()
    S = _state(app)
    g = app.project.geometry
    outs = S["outs"]
    covered = sum(o["len"] for o in outs)
    dpg.set_value("out_desc", f"{g.describe()}; {len(outs)} output(s) cover {covered} of {g.count}"
                  + ("" if covered == g.count else f" - {'short by' if covered < g.count else 'over by'} {abs(g.count - covered)}"))
    dpg.set_value("out_ledma", int(S.get("ma_per_led", 55))); dpg.set_value("out_maxma", int(S.get("max_ma", 850)))
    dpg.set_value("out_abl", bool(S.get("abl_preview")))
    dpg.delete_item("out_rows", children_only=True)
    types = [t[1] for t in outputs.TYPES]; orders = [o[1] for o in outputs.ORDERS]
    cb = lambda s, v, u: _field(app, u[0], u[1], v)
    for k, o in enumerate(outs):
        with dpg.group(horizontal=True, parent="out_rows"):
            dpg.add_text(f"{k + 1:2d}", color=c.DIM)
            dpg.add_input_text(width=px(90), default_value=o.get("name", ""), user_data=(k, "name"), on_enter=True, callback=cb)
            dpg.add_input_int(label="pin", width=px(50), step=0, default_value=int(o["pin"]), min_value=0, max_value=48, user_data=(k, "pin"), on_enter=True, callback=cb)
            dpg.add_input_int(label="start", width=px(60), step=0, default_value=int(o["start"]), min_value=0, user_data=(k, "start"), on_enter=True, callback=cb)
            dpg.add_input_int(label="LEDs", width=px(60), step=0, default_value=int(o["len"]), min_value=1, user_data=(k, "len"), on_enter=True, callback=cb)
            dpg.add_combo(types, width=px(130), default_value=next((t[1] for t in outputs.TYPES if t[0] == o.get("type", 22)), types[0]),
                          user_data=(k, "type"), callback=cb)
            dpg.add_combo(orders, width=px(60), default_value=next((n for i, n in outputs.ORDERS if i == o.get("order", 0)), "GRB"),
                          user_data=(k, "order"), callback=cb)
            dpg.add_checkbox(label="rev", default_value=bool(o.get("rev")), user_data=(k, "rev"), callback=cb)
            dpg.add_button(label="x", small=True, user_data=k, callback=lambda s, a, u: del_output(app, u))
            weight.danger(dpg.last_item())
    if not outs:
        weight.empty("out_rows", "No outputs yet: the wiring as one output, one per part, so many LEDs each - or the device's own.",
                     [("One output", lambda: do_split(app, "one")), ("Read the device's", lambda: read_device(app))])


def _field(app, k, key, value):
    S = _state(app)
    if not (0 <= k < len(S["outs"])):
        return
    o = S["outs"][k]
    if key == "type":
        o["type"] = next((t[0] for t in outputs.TYPES if t[1] == value), 22)
    elif key == "order":
        o["order"] = next((i for i, n in outputs.ORDERS if n == value), 0)
    elif key in ("pin", "start", "len"):
        o[key] = int(value)
    elif key == "rev":
        o["rev"] = bool(value)
    else:
        o[key] = str(value)
    app.project.save()
    refresh(app)


def _set(app, key, value):
    _state(app)[key] = value
    app.project.save()
    if key != "abl_preview":
        refresh(app)


def do_split(app, by):
    from native import shapes
    S = _state(app)
    g = app.project.geometry
    parts = None
    if by == "parts":
        if g.kind != "shape" or g.params.get("layout") == "grid":
            app.gp.status("one per part needs a shape on the strip layout (a part is a run of LEDs there)"); return
        parts = [(p.get("name", p["kind"]), shapes.part_count(p)) for p in (g.params.get("parts") or [])]
    S["outs"] = outputs.split(g.count, parts, by, int(dpg.get_value("out_per") or 300))
    app.project.save(); refresh(app)


def add_output(app):
    S = _state(app)
    start = sum(o["len"] for o in S["outs"])
    S["outs"].append(outputs.new_output(outputs.DEFAULT_PINS[len(S["outs"]) % len(outputs.DEFAULT_PINS)], start, max(1, app.project.geometry.count - start), len(S["outs"])))
    app.project.save(); refresh(app)


def del_output(app, k):
    S = _state(app)
    if 0 <= k < len(S["outs"]):
        S["outs"].pop(k); app.project.save(); refresh(app)


def read_device(app):
    from native import devices, device_ui
    host = app.active_host()
    if not host:
        device_ui.show(app, "devices"); app.gp.status("choose a device first"); return
    try:
        cfg = devices._get(host, "/json/cfg", 6)
    except Exception as e:
        dpg.set_value("out_log", f"could not read the device's config: {e}"); return
    outs, ledma, maxma = outputs.from_wled_cfg(cfg)
    S = _state(app); S["outs"] = outs; S["ma_per_led"] = ledma; S["max_ma"] = maxma
    app.project.save(); refresh(app)
    dpg.set_value("out_log", f"the device's {len(outs)} output(s) read: " + ", ".join(f"pin {o['pin']} x{o['len']}" for o in outs))


def send(app):
    import urllib.request
    from native import device_ui
    host = app.active_host()
    S = _state(app)
    if not host:
        device_ui.show(app, "devices"); app.gp.status("choose a device first"); return
    if not S["outs"]:
        dpg.set_value("out_log", "no outputs to send"); return
    body = outputs.wled_cfg(S["outs"], int(S.get("ma_per_led", 55)), int(S.get("max_ma", 850)))
    h = host if host.startswith("http") else "http://" + host
    req = urllib.request.Request(h + "/json/cfg", data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=8) as r:
            r.read()
        msg = f"{len(S['outs'])} output(s), {body['hw']['led']['total']} LEDs, {S.get('max_ma', 0)} mA limit sent to {host}"
    except Exception as e:
        msg = f"the device refused the config: {e}"
    dpg.set_value("out_log", msg); app.gp.status(msg); device_ui.send_log(app, msg)


def poll(app):
    """The power line: the current the shown frame draws, each frame while the frame shows."""
    if not dpg.does_item_exist("out_power") or not dpg.is_item_shown(TAG):
        return
    pw = getattr(app, "_power", None)
    if pw is None:
        return
    ma, scale, limit = pw
    a = ma / 1000.0
    line = f"this frame: {a:.2f} A" + (f" of a {limit / 1000.0:.2f} A supply" if limit else " (no limit set)")
    if limit and scale < 1.0:
        line += f" - the device would dim it to {int(scale * 100)}%"
    elif limit:
        line += " - within the limit"
    dpg.set_value("out_power", line)
    dpg.configure_item("out_power", color=_c().RED if (limit and scale < 0.6) else (_c().AMBER if (limit and scale < 1.0) else _c().TEXT))
