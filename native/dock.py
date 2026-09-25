"""The dock (the critique's C8): the side panel's column, tabbed.

The frames - Devices, Flash, Send, Shape, Sequence, Library, Palettes, LED
outputs, Audio input - opened floating, over the logical and 3-D views: a
sequence or a palette edited over the very picture it changes. They open
in the dock now, a tab each beside the panel's own, in the panel's column;
one tab shows at a time, the column as wide as the tab wants (the panel
its width, each frame the width it was drawn for, or the one it was
dragged to). A frame floats only when asked - the tab strip's float
button, or its grip dragged away - and remembers it: it opens floating
until it is docked again. While the graph has the room, the dock is the
drawer beside the rail, and the rail carries the docked frames' icons.

    dock.open_frame(app, "sequence")     # the menu's way in: docked, unless it floats
    dock.float_frame(app, "sequence")    # a window of its own, over the panes
    dock.dock_frame(app, "sequence")     # back in the dock, its tab in front

The state is the prefs' "dock": {"tabs": [...], "active": "side" | a frame,
"float": [...], "w": {frame: width at 100%}}.
"""
import dearpygui.dearpygui as dpg

from native.typeface import px
from native import typeface

TAB_H = 34                  # the tab strip at 100%
MIN_W = 240                 # a tab's narrowest column, at 100%
NAMES = {"side": "Panel", "devices": "Devices", "flash": "Flash", "send": "Send", "shape": "Shape",
         "sequence": "Sequence", "library": "Library", "palettes": "Palettes", "outputs": "LED outputs",
         "audioin": "Audio input"}
ICONS = {"devices": "devices", "flash": "flash", "send": "send", "shape": "shape", "sequence": "sequence",
         "library": "library", "palettes": "palette", "outputs": "outputs", "audioin": "mic"}

_sig = None                 # what the tab strip was built for


def _frames():
    from native import device_ui
    return device_ui.FRAMES


def state(app):
    """The dock's state in the prefs, made whole."""
    st = app.prefs.setdefault("dock", {})
    st.setdefault("tabs", [])
    st.setdefault("active", "side")
    st.setdefault("float", [])
    st.setdefault("w", {})
    known = _frames()
    st["tabs"] = [t for t in dict.fromkeys(st["tabs"]) if t in known]
    if st["active"] != "side" and st["active"] not in st["tabs"]:
        st["active"] = "side"
    return st


def _save(app):
    from native.project import save_prefs
    save_prefs(app.prefs)


def tabs(app):
    return list(state(app)["tabs"])


def active(app):
    return state(app)["active"]


def in_dock(app, slot):
    return slot in state(app)["tabs"]


def floats(app, slot):
    """Whether the frame opens floating (it was floated, and not docked since)."""
    return slot in state(app)["float"]


def width(app):
    """The column's width for the tab in front: the panel's own, or the frame's."""
    a = active(app)
    if a == "side":
        return app.side_w
    w = state(app)["w"].get(a) or _frames()[a][2]
    vw = max(640, dpg.get_viewport_client_width() or 1280)
    return int(max(px(MIN_W), min(int(vw * 0.6), px(w))))


def set_width(app, w):
    """The column dragged to `w` (px, at the interface size): the tab in
    front keeps it - the panel as its width, a frame as its own at 100%."""
    a = active(app)
    if a == "side":
        app.side_w = w
    else:
        state(app)["w"][a] = int(round(w / typeface.scale()))


def _show_column(app):
    """The dock's column on screen: the panel shown, and while the graph has
    the room, the drawer open beside the rail."""
    from native import room
    if not app.side:
        app.side = True
    if room.rail(app) and not app.prefs.get("graph_panel_open"):
        app.prefs["graph_panel_open"] = True


def open_frame(app, slot):
    """A frame asked for (the menus, the toolbar): into the dock, its tab in
    front - or its window, if it floats."""
    if floats(app, slot):
        _float_window(app, slot)
        return
    dock_frame(app, slot)


def dock_frame(app, slot):
    """A frame into the dock, its tab in front."""
    if slot not in _frames():
        return
    st = state(app)
    if slot not in st["tabs"]:
        st["tabs"].append(slot)
    if slot in st["float"]:
        st["float"].remove(slot)
    st["active"] = slot
    _show_column(app)
    _save(app)
    app.request_layout()


def float_frame(app, slot):
    """A docked frame out into a window of its own, over the panes; it opens so until docked again."""
    if slot not in _frames():
        return                                        # the panel's tab in front: nothing to float (a press as the strip changes)
    st = state(app)
    _leave(app, slot)
    if slot not in st["float"]:
        st["float"].append(slot)
    _save(app)
    _float_window(app, slot)
    app.request_layout()


def _float_window(app, slot):
    from native import chrome, device_ui
    tag, _, w, h = _frames()[slot]
    if not dpg.does_item_exist(tag):
        return
    was = dpg.is_item_shown(tag) and not in_dock(app, slot)
    dpg.configure_item(tag, no_move=False, no_resize=False, width=px(w), height=px(h), show=True)
    device_ui.chrome_for(app, slot, docked=False)
    if not was:
        chrome._centre(tag, w, h)
    device_ui.place_header(tag, px(w), False)
    try:
        dpg.set_y_scroll(tag, 0)
    except Exception:
        pass
    dpg.focus_item(tag)


def _leave(app, slot):
    """A frame's tab out of the dock; the one beside it comes to the front."""
    st = state(app)
    if slot not in st["tabs"]:
        return
    k = st["tabs"].index(slot)
    st["tabs"].remove(slot)
    if st["active"] == slot:
        st["active"] = st["tabs"][min(k, len(st["tabs"]) - 1)] if st["tabs"] else "side"


def close_frame(app, slot):
    """A frame away - its tab, or its window."""
    if slot not in _frames():
        return
    tag = _frames()[slot][0]
    _leave(app, slot)
    _save(app)
    if dpg.does_item_exist(tag):
        dpg.hide_item(tag)
    app.request_layout()


def activate(app, key):
    """A tab to the front: "side" for the panel, or a docked frame."""
    st = state(app)
    if key != "side" and key not in st["tabs"]:
        return
    if st["active"] != key:
        st["active"] = key
        _save(app)
    _show_column(app)
    app.request_layout()


def migrate(app, arrangement):
    """Frames an older arrangement placed among the panes: into the dock,
    and the arrangement without them."""
    frames = _frames()
    moved = [s for c in arrangement for s in c if s in frames]
    if not moved:
        return arrangement
    st = state(app)
    for s in moved:
        if s not in st["tabs"]:
            st["tabs"].append(s)
    cols = [[s for s in c if s not in frames] for c in arrangement]
    return [c for c in cols if c]


# --- the tab strip ---------------------------------------------------------------------------
def build(app):
    """The tab strip over the dock's column (placed by place())."""
    with dpg.child_window(tag="dock_tabs", parent="panes_row", width=px(300), height=px(TAB_H), show=False,
                          no_scrollbar=True, no_scroll_with_mouse=True, border=False):
        pass
    theme(app)


def theme(app):
    """The strip's tabs in the theme's colours: the one in front on the
    panel's ground, its name in the accent - the page it is the tab of -
    the others on the controls' shade, their names dim. (Dear PyGui's own
    tab bar gave its first tab all the width the others left.)"""
    from native import chrome
    from native.app import theme_colors
    cols = theme_colors(app.prefs)
    panel, frame = tuple(cols["panel"]), tuple(cols["frame"])
    acc, dim, text = tuple(chrome.ACCENT[:3]), tuple(cols["dim"]), tuple(cols["text"])
    lift = lambda c, d: tuple(max(0, min(255, x + d)) for x in c)
    old = [getattr(app, n, None) for n in ("_dock_theme", "_dock_on", "_dock_off")]
    with dpg.theme() as strip:
        with dpg.theme_component(dpg.mvAll):
            dpg.add_theme_color(dpg.mvThemeCol_ChildBg, (0, 0, 0, 0), category=dpg.mvThemeCat_Core)
            dpg.add_theme_style(dpg.mvStyleVar_WindowPadding, 0, px(4), category=dpg.mvThemeCat_Core)
            dpg.add_theme_style(dpg.mvStyleVar_ItemSpacing, px(2), 0, category=dpg.mvThemeCat_Core)
    with dpg.theme() as on:
        with dpg.theme_component(dpg.mvAll):
            for c, v in ((dpg.mvThemeCol_Button, panel + (255,)), (dpg.mvThemeCol_ButtonHovered, lift(panel, 10) + (255,)),
                         (dpg.mvThemeCol_ButtonActive, lift(panel, 16) + (255,)), (dpg.mvThemeCol_Text, acc + (255,))):
                dpg.add_theme_color(c, v, category=dpg.mvThemeCat_Core)
    with dpg.theme() as off:
        with dpg.theme_component(dpg.mvAll):
            for c, v in ((dpg.mvThemeCol_Button, frame + (255,)), (dpg.mvThemeCol_ButtonHovered, lift(frame, 12) + (255,)),
                         (dpg.mvThemeCol_ButtonActive, lift(frame, 20) + (255,)), (dpg.mvThemeCol_Text, dim + (255,))):
                dpg.add_theme_color(c, v, category=dpg.mvThemeCat_Core)
    app._dock_theme, app._dock_on, app._dock_off, app._dock_text = strip, on, off, text
    if dpg.does_item_exist("dock_tabs"):
        dpg.bind_item_theme("dock_tabs", strip)
    for t in old:
        if t is not None and dpg.does_item_exist(t):
            dpg.delete_item(t)
    global _sig
    _sig = None                                       # rebuilt with the new colours


def _labels_fit(names, w):
    """Whether the tabs fit as words in `w`: each name and its padding, a
    close for a frame's, the float button at the end."""
    pad = 2 * px(7) + px(2)
    need = sum(typeface.measure(n) + pad for n in names) + (len(names) - 1) * (px(18) + px(2)) + px(60)
    return need <= w


def _fill(app, w):
    """The tabs for the dock's state: the panel's, then one per docked frame
    with its close, and at the strip's right the float button for the frame
    in front. Words while they fit, the frames' icons when they do not."""
    global _sig
    from native import chrome
    from native.icons import texture
    st = state(app)
    names = [NAMES["side"]] + [NAMES.get(s, s) for s in st["tabs"]]
    words = _labels_fit(names, w)
    sig = (tuple(st["tabs"]), st["active"], words, int(w))
    if sig == _sig or not dpg.does_item_exist("dock_tabs"):
        return
    _sig = sig
    dpg.delete_item("dock_tabs", children_only=True)
    on, off = app._dock_on, app._dock_off
    with dpg.group(horizontal=True, parent="dock_tabs"):
        for key in ["side"] + st["tabs"]:
            front = key == st["active"]
            if words or key == "side":
                b = dpg.add_button(label=NAMES.get(key, key), tag=f"dock_tab_{key}", user_data=key,
                                   callback=lambda s, a, u: activate(app, u))
            else:
                b = dpg.add_image_button(texture(ICONS.get(key, "gear"), px(16)), tag=f"dock_tab_{key}", width=px(16), height=px(16),
                                         user_data=key, tint_color=chrome.ACCENT if front else app._dock_text,
                                         callback=lambda s, a, u: activate(app, u))
            dpg.bind_item_theme(b, on if front else off)
            chrome.tip(f"{NAMES.get(key, key)}" + (" - in front" if front else " - brings it to the front"), item=b)
            if key != "side":
                x = dpg.add_button(label="x", tag=f"dock_close_{key}", small=True, user_data=key,
                                   callback=lambda s, a, u: close_frame(app, u))
                dpg.bind_item_theme(x, on if front else off)
                chrome.tip(f"close {NAMES.get(key, key)} (the menus open it again)", item=x)
    if st["active"] != "side":
        fb = dpg.add_button(label="float", tag="dock_float", parent="dock_tabs", small=True, pos=(max(0, w - px(52)), px(6)),
                            callback=lambda: float_frame(app, active(app)))
        chrome.tip("float the frame in front: a window of its own over the panes (it opens so until docked again)", item=fb)


def poll(app):
    """Nothing to watch: the strip's buttons act as they are pressed."""
    return


# --- where it goes ------------------------------------------------------------------------------
def place(app, rect):
    """The dock at (x, y, w, h): the tab strip at its top when a frame is in
    it, and the tab in front below - the panel, or the frame, placed as a
    pane; the other docked frames hidden."""
    from native import device_ui
    x, y, w, h = rect
    st = state(app)
    strip = bool(st["tabs"]) and app.ui
    th = px(TAB_H) if strip else 0
    if dpg.does_item_exist("dock_tabs"):
        dpg.configure_item("dock_tabs", show=strip, width=w, height=th if strip else 1)
        if strip:
            _fill(app, w)
            dpg.set_item_pos("dock_tabs", [x, y])
    cy, ch = y + th, max(1, h - th)
    a = st["active"]
    dpg.configure_item("side_win", show=app.ui and a == "side")
    if a == "side":
        dpg.configure_item("side_win", width=w, height=ch)
        dpg.set_item_pos("side_win", [x, cy])
        if dpg.does_item_exist("grip_side_win"):
            dpg.set_item_pos("grip_side_win", [w - px(40 + 14), px(8)])
    for slot in st["tabs"]:
        tag = _frames()[slot][0]
        if not dpg.does_item_exist(tag):
            continue
        if slot == a and app.ui:
            dpg.configure_item(tag, show=True, no_move=True, no_resize=True, width=w, height=ch)
            dpg.set_item_pos(tag, [x, cy])
            device_ui.chrome_for(app, slot, docked=True)
            device_ui.place_header(tag, w, True)
        else:
            dpg.configure_item(tag, show=False)


def hide(app):
    """The dock's column away (the panel hidden, the drawer folded,
    presentation): its strip and its frames with it; floating frames stay."""
    if dpg.does_item_exist("dock_tabs"):
        dpg.configure_item("dock_tabs", show=False)
    for slot in tabs(app):
        tag = _frames()[slot][0]
        if dpg.does_item_exist(tag):
            dpg.configure_item(tag, show=False)


def rect_of_tabs():
    """The strip's rectangle on the screen, or None (for drops and holes)."""
    if not dpg.does_item_exist("dock_tabs") or not dpg.is_item_shown("dock_tabs"):
        return None
    x, y = dpg.get_item_pos("dock_tabs")
    w, h = dpg.get_item_rect_size("dock_tabs")
    return x, y, x + w, y + h
