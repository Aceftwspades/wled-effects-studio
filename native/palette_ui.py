"""The Palettes frame: gradients drawn by hand, kept with the project,
shown in the sim as palettes of their own and sent to the device as WLED
custom palettes.

A palette is stops - a position 0..255 and a colour each, up to 18, as
WLED's `/palette{n}.json` holds them. The sim gets them as ids 200 down
(slot 0 is 200), which is what the device gives them, so an effect set to
one here is set to the same one there. The bar shows the gradient the way
the device will blend it: sixteen entries sampled from the stops, then a
straight blend between entries (FastLED's CRGBPalette16 from a gradient).

    build(app)        # the window (device_ui.build calls it)
    refresh(app)      # the list, the bar, the selected stop's fields
    poll(app)         # per frame: clicks and drags on the bar
    sync(app)         # the palettes into the engine and the combos
"""
import json
import dearpygui.dearpygui as dpg
import numpy as np

from native import flash

TAG = "palettes_win"
MAX_PALETTES = 10
MAX_STOPS = 18


def _c():
    from native import chrome
    return chrome


def _pals(app):
    return app.project.options.setdefault("palettes", [])


def _sel(app):
    pals = _pals(app)
    i = getattr(app, "_pal_sel", 0)
    return min(max(0, i), len(pals) - 1) if pals else -1


def _stops(p):
    return sorted([[int(q[0]), int(q[1]), int(q[2]), int(q[3])] for q in (p.get("stops") or [])], key=lambda q: q[0])


# --- the device's blend --------------------------------------------------------------------
def entries16(stops):
    """The sixteen entries FastLED makes of a gradient (CRGBPalette16::loadDynamicGradientPalette)."""
    st = _stops({"stops": stops}) or [[0, 0, 0, 0], [255, 255, 255, 255]]
    out = []
    for e in range(16):
        pos = e * 16
        a = st[0]
        b = st[-1]
        for k in range(len(st) - 1):
            if st[k][0] <= pos <= st[k + 1][0]:
                a, b = st[k], st[k + 1]; break
        if pos < st[0][0]:
            a = b = st[0]
        if pos > st[-1][0]:
            a = b = st[-1]
        span = max(1, b[0] - a[0])
        f = (pos - a[0]) / span if b[0] > a[0] else 0.0
        out.append([int(a[c] + (b[c] - a[c]) * f) for c in (1, 2, 3)])
    return out


def sample(stops, n=256):
    """The gradient at n positions the way ColorFromPalette (LINEARBLEND) reads it: (n, 3) uint8."""
    ent = np.asarray(entries16(stops), np.float32)
    out = np.zeros((n, 3), np.float32)
    for i in range(n):
        idx = i * 256 // n
        hi, lo = idx >> 4, idx & 15
        e1 = ent[hi]; e2 = ent[(hi + 1) % 16]
        out[i] = e1 + (e2 - e1) * (lo / 16.0)
    return np.clip(out, 0, 255).astype(np.uint8)


def wled_json(p):
    """The file the device reads: {"palette": [pos, r, g, b, ...]}."""
    flat = [v for q in _stops(p)[:MAX_STOPS] for v in q]
    return json.dumps({"palette": flat})


# --- build ---------------------------------------------------------------------------------
def build(app):
    c = _c()
    from native import device_ui
    with dpg.window(tag=TAG, show=False, width=560, height=460, no_collapse=True, no_title_bar=True):
        device_ui.header(app, "palettes")
        with dpg.group(horizontal=True):
            dpg.add_button(label="undo", small=True, callback=lambda: undo(app))
            c.tip("the palettes as they were before the last change; Ctrl+Z here does the same, Ctrl+Y redoes")
            dpg.add_button(label="+ New", small=True, callback=lambda: new_palette(app))
            dpg.add_button(label="From the sim's palette", small=True, callback=lambda: from_current(app))
            c.tip("a new one that starts as the palette the sim shows")
            dpg.add_button(label="Copy", small=True, callback=lambda: dup_palette(app))
            dpg.add_button(label="Remove", small=True, callback=lambda: del_palette(app))
            dpg.add_button(label="Use in the sim", small=True, callback=lambda: use_palette(app))
            c.info("Gradients of your own: in the sim as palettes (ids 200 down), on the device as its custom palettes - "
                   "sent by position, so the first here replaces the device's palette0.json, the second its palette1.json.")
        with dpg.child_window(tag="pal_rows", height=120, border=True):
            pass
        with dpg.group(horizontal=True):
            dpg.add_input_text(tag="pal_name", label="name", width=200, on_enter=True, callback=lambda s, v: rename(app, v))
            dpg.add_text("", tag="pal_id", color=c.DIM)
        dpg.add_text("click: a stop  -  drag: move it  -  right-click: remove it", color=c.DIM, wrap=0)
        dpg.add_drawlist(tag="pal_bar", width=520, height=64)
        with dpg.group(horizontal=True):
            dpg.add_color_edit(tag="pal_col", default_value=(255, 255, 255, 255), no_alpha=True, width=200,
                               callback=lambda s, v: set_colour(app, v))
            dpg.add_input_int(tag="pal_pos", label="position", width=80, min_value=0, max_value=255, min_clamped=True, max_clamped=True,
                              callback=lambda s, v: set_pos(app, int(v)))
            dpg.add_button(label="spread evenly", small=True, callback=lambda: spread(app))
        dpg.add_separator()
        with dpg.group(horizontal=True):
            dpg.add_text("ON THE DEVICE", color=c.ACCENT)
            dpg.add_button(label="Send this one", small=True, callback=lambda: send(app, False))
            c.tip("slot n is /palette{n}.json on the device, palette id 200 - n everywhere; the device reloads its custom palettes on upload")
            dpg.add_button(label="Send all", small=True, callback=lambda: send(app, True))
            dpg.add_button(label="Remove this one there", small=True, callback=lambda: remove_there(app))
        dpg.add_text("", tag="pal_log", color=c.DIM, wrap=0)


# --- the list, the bar, the fields ----------------------------------------------------------
def undo(app, redo=False):
    """The palettes back a step (the project journals every change)."""
    ok = app.project.redo("palettes") if redo else app.project.undo("palettes")
    if not ok:
        app.gp.status("nothing to " + ("redo" if redo else "undo") + " in the palettes"); return
    pals = _pals(app)
    app._pal_sel = min(getattr(app, "_pal_sel", 0), max(0, len(pals) - 1)); app._pal_stop = 0
    refresh(app)
    app.gp.status(f"palettes: {'redo' if redo else 'undo'}")


def refresh(app):
    if not dpg.does_item_exist("pal_rows"):
        return
    c = _c()
    pals = _pals(app)
    sel = _sel(app)
    dpg.delete_item("pal_rows", children_only=True)
    for i, p in enumerate(pals):
        with dpg.group(horizontal=True, parent="pal_rows"):
            dpg.add_selectable(label=f"{i:2d}  {p.get('name', '')}", width=200, default_value=(i == sel), user_data=i,
                               callback=lambda s, a, u: (setattr(app, "_pal_sel", u), setattr(app, "_pal_stop", 0), refresh(app)))
            dpg.add_text(f"id {200 - i}, {len(p.get('stops') or [])} stops", color=c.DIM)
            tex = _swatch(app, i, p)
            if tex:
                dpg.add_image(tex, width=120, height=14)
    if not pals:
        dpg.add_text("none yet: + New, or From the sim's palette", parent="pal_rows", color=c.DIM)
    if sel < 0:
        dpg.set_value("pal_name", ""); dpg.set_value("pal_id", "")
        dpg.delete_item("pal_bar", children_only=True)
        return
    p = pals[sel]
    dpg.set_value("pal_name", p.get("name", ""))
    dpg.set_value("pal_id", f"palette id {200 - sel} in the sim and on the device (slot {sel})")
    st = _stops(p)
    k = min(getattr(app, "_pal_stop", 0), len(st) - 1)
    if 0 <= k < len(st):
        dpg.set_value("pal_col", [st[k][1], st[k][2], st[k][3], 255]); dpg.set_value("pal_pos", st[k][0])
    draw_bar(app)


def _swatch(app, i, p):
    """A small texture of the gradient for the list."""
    tag = f"pal_sw_{i}"
    strip = sample(p.get("stops") or [], 120)
    rgba = np.ones((1, 120, 4), np.float32); rgba[0, :, :3] = strip / 255.0
    if dpg.does_item_exist(tag):
        dpg.set_value(tag, rgba.ravel())
    else:
        from native.textures import registry
        dpg.add_dynamic_texture(120, 1, rgba.ravel(), tag=tag, parent=registry())
    return tag


def draw_bar(app):
    if not dpg.does_item_exist("pal_bar"):
        return
    dpg.delete_item("pal_bar", children_only=True)
    sel = _sel(app)
    if sel < 0:
        return
    p = _pals(app)[sel]
    W, H = 520, 64
    cols = sample(p.get("stops") or [], 128)
    for i in range(128):
        x0 = int(i * W / 128); x1 = int((i + 1) * W / 128)
        col = tuple(int(v) for v in cols[i]) + (255,)
        dpg.draw_rectangle((x0, 4), (x1, H - 18), color=col, fill=col, parent="pal_bar")
    dpg.draw_rectangle((0, 4), (W - 1, H - 18), color=(70, 74, 82, 255), parent="pal_bar")
    k = getattr(app, "_pal_stop", 0)
    for j, q in enumerate(_stops(p)):
        x = q[0] * (W - 1) / 255.0
        col = (255, 210, 90, 255) if j == k else (235, 235, 235, 255)
        dpg.draw_triangle((x, H - 16), (x - 6, H - 4), (x + 6, H - 4), color=col, fill=col, parent="pal_bar")
        dpg.draw_line((x, 4), (x, H - 16), color=col, thickness=1, parent="pal_bar")


def poll(app):
    """Clicks and drags on the bar: add a stop, move one, take one out."""
    if not dpg.does_item_exist("pal_bar") or not dpg.is_item_shown(TAG):
        return
    sel = _sel(app)
    if sel < 0:
        return
    st = dpg.get_item_state("pal_bar")
    if "rect_min" not in st:
        return
    (x0, y0) = st["rect_min"]; W, H = 520, 64
    mx, my = dpg.get_mouse_pos(local=False)
    inside = x0 <= mx <= x0 + W and y0 <= my <= y0 + H
    pos = int(max(0, min(255, round((mx - x0) * 255.0 / (W - 1)))))
    down = dpg.is_mouse_button_down(0)
    pressed, rpressed = dpg.is_mouse_button_clicked(0), dpg.is_mouse_button_clicked(1)
    ed = app.__dict__.setdefault("_pal_ed", {"drag": None, "was": False})
    p = _pals(app)[sel]
    stops = _stops(p)
    def nearest():
        best, bk = 8, None
        for k, q in enumerate(stops):
            d = abs(q[0] * (W - 1) / 255.0 - (mx - x0))
            if d < best:
                best, bk = d, k
        return bk
    if (pressed or (down and not ed["was"])) and inside and ed["drag"] is None:
        k = nearest()
        if k is None and len(stops) < MAX_STOPS:
            col = sample(stops, 256)[pos]
            stops.append([pos, int(col[0]), int(col[1]), int(col[2])]); stops.sort(key=lambda q: q[0])
            k = next(i for i, q in enumerate(stops) if q[0] == pos)
            p["stops"] = stops
            _changed(app)
        if k is not None:
            ed["drag"] = k; app._pal_stop = k; ed["moved"] = False
            refresh(app)
    elif down and ed["drag"] is not None:
        k = ed["drag"]
        if 0 <= k < len(stops) and stops[k][0] != pos:
            stops[k][0] = pos
            stops.sort(key=lambda q: q[0])
            k = next(i for i, q in enumerate(stops) if q[0] == pos); ed["drag"] = k; app._pal_stop = k
            p["stops"] = stops; ed["moved"] = True
            _changed(app, save=False); draw_bar(app); dpg.set_value("pal_pos", pos)
    elif not down and ed["drag"] is not None:
        ed["drag"] = None
        if ed.get("moved"):
            app.project.save()
    if rpressed and inside and len(stops) > 2:
        k = nearest()
        if k is not None:
            stops.pop(k); p["stops"] = stops; app._pal_stop = max(0, k - 1)
            _changed(app); refresh(app)
    ed["was"] = down


# --- edits ---------------------------------------------------------------------------------
def _changed(app, save=True):
    if save:
        app.project.save()
    sync(app)


def sync(app):
    """The palettes into the engine and the combos; the sim's choice kept."""
    pals = _pals(app)
    if app.eng.custom_palettes(pals):
        app.reload_palettes()
        app.eng.push()
    for i, p in enumerate(pals):
        _swatch(app, i, p)


def new_palette(app):
    pals = _pals(app)
    if len(pals) >= MAX_PALETTES:
        app.gp.status("ten custom palettes is what the device holds"); return
    pals.append({"name": f"Custom {len(pals) + 1}", "stops": [[0, 0, 0, 0], [128, 255, 0, 0], [255, 255, 255, 0]]})
    app._pal_sel = len(pals) - 1; app._pal_stop = 0
    _changed(app); refresh(app)


def from_current(app):
    """The sim's current palette sampled into stops of its own."""
    pals = _pals(app)
    if len(pals) >= MAX_PALETTES:
        app.gp.status("ten custom palettes is what the device holds"); return
    try:
        cols = [int(app.eng.lib.simPalColor(int(app.eng.pal), i * 255 // 7)) for i in range(8)]
        stops = [[i * 255 // 7, (c >> 16) & 255, (c >> 8) & 255, c & 255] for i, c in enumerate(cols)]
    except Exception as e:
        app.gp.status(f"could not read the palette: {e}"); return
    pals.append({"name": f"{app.palette_name_for(app.eng.pal)} copy", "stops": stops})
    app._pal_sel = len(pals) - 1; app._pal_stop = 0
    _changed(app); refresh(app)


def dup_palette(app):
    pals = _pals(app); sel = _sel(app)
    if sel < 0 or len(pals) >= MAX_PALETTES:
        return
    q = json.loads(json.dumps(pals[sel])); q["name"] = q.get("name", "") + " copy"
    pals.insert(sel + 1, q); app._pal_sel = sel + 1
    _changed(app); refresh(app)


def del_palette(app):
    pals = _pals(app); sel = _sel(app)
    if sel < 0:
        return
    pals.pop(sel); app._pal_sel = min(sel, len(pals) - 1); app._pal_stop = 0
    _changed(app); refresh(app)


def rename(app, name):
    sel = _sel(app)
    if sel >= 0:
        _pals(app)[sel]["name"] = str(name).strip() or f"Custom {sel + 1}"
        _changed(app); refresh(app)


def set_colour(app, v):
    sel = _sel(app)
    if sel < 0:
        return
    p = _pals(app)[sel]; st = _stops(p); k = min(getattr(app, "_pal_stop", 0), len(st) - 1)
    if k < 0:
        return
    r, g, b = [int(round(x * 255)) if isinstance(x, float) and x <= 1.0 else int(x) for x in v[:3]]
    st[k][1:4] = [max(0, min(255, r)), max(0, min(255, g)), max(0, min(255, b))]
    p["stops"] = st
    _changed(app); draw_bar(app); _swatch(app, sel, p)


def set_pos(app, pos):
    sel = _sel(app)
    if sel < 0:
        return
    p = _pals(app)[sel]; st = _stops(p); k = min(getattr(app, "_pal_stop", 0), len(st) - 1)
    if k < 0:
        return
    st[k][0] = max(0, min(255, int(pos))); st.sort(key=lambda q: q[0]); p["stops"] = st
    app._pal_stop = next(i for i, q in enumerate(st) if q[0] == max(0, min(255, int(pos))))
    _changed(app); refresh(app)


def spread(app):
    sel = _sel(app)
    if sel < 0:
        return
    p = _pals(app)[sel]; st = _stops(p)
    for i, q in enumerate(st):
        q[0] = int(round(i * 255 / max(1, len(st) - 1)))
    p["stops"] = st
    _changed(app); refresh(app)


def use_palette(app):
    sel = _sel(app)
    if sel < 0:
        return
    app.eng.pal = 200 - sel
    app.eng.push(); app.sync_palette_combo()
    app.gp.status(f"the sim uses {_pals(app)[sel].get('name')} (palette {200 - sel})")


# --- the device --------------------------------------------------------------------------------
def send(app, all_):
    from native import device_ui
    host = app.active_host()
    if not host:
        device_ui.show(app, "devices"); app.gp.status("choose a device first"); return
    pals = _pals(app); sel = _sel(app)
    todo = list(enumerate(pals)) if all_ else ([(sel, pals[sel])] if sel >= 0 else [])
    n = 0
    for i, p in todo:
        ok, msg = flash.send_file(host, f"/palette{i}.json", wled_json(p).encode())
        if not ok:
            dpg.set_value("pal_log", msg); app.gp.status(msg); return
        n += 1
    msg = f"{n} palette(s) sent to {host}; the device reloaded its custom palettes (ids {200 - todo[0][0]}..{200 - todo[-1][0]})" if todo else "nothing to send"
    dpg.set_value("pal_log", msg); app.gp.status(msg); device_ui.send_log(app, msg)


def remove_there(app):
    import urllib.request
    host = app.active_host(); sel = _sel(app)
    if not host or sel < 0:
        return
    h = host if host.startswith("http") else "http://" + host
    req = urllib.request.Request(h + "/json/state", data=json.dumps({"rmcpal": sel}).encode(), headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=6) as r:
            r.read()
        msg = f"palette slot {sel} removed from the device"
    except Exception as e:
        msg = f"could not remove it: {e}"
    dpg.set_value("pal_log", msg); app.gp.status(msg)
