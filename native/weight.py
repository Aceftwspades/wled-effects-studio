"""What a control weighs, and whether there is anything for it to act on
(the critique's C5).

Weights. Every button used to be the same grey slab, so a dialog did not
say which of its buttons it was for. Now each is one of four:
- primary: the one thing a dialog or frame is for, filled in the accent;
- danger: what changes something that cannot be taken back here (a
  device's wiring, a reboot, a deletion), in red;
- quiet: a way out (Cancel, Not now, Close), without a slab;
- secondary: everything else, as before.

    weight.primary(dpg.add_button(label="Start", ...))
    weight.danger(dpg.add_button(label="x", ...))

Needs. An action with nothing to act on - Delete with nothing selected,
Undo with nothing done, Send with no device - is greyed on the menus and
the toolbar. NEEDS names what each wants and poll() keeps them in step. A
key still runs it, and it says why it did nothing.

Empty states. empty(parent, text, [(label, fn), ...]) says what a list
would hold and offers the next step as a button (the first a primary).
"""
import time

import dearpygui.dearpygui as dpg

RED = (226, 76, 76)
_weighted = {}          # item -> kind
_themes = {}            # (kind, colours) -> theme


def _c():
    from native import chrome
    return chrome


def _light():
    return _c().TEXT[0] < 128


def _lum(c):
    return (0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]) / 255.0


def _shift(c, k):
    return tuple(max(0, min(255, int(v + k))) for v in c[:3])


def theme(kind):
    """The theme for a weight, in the colours in force (made once per set)."""
    c = _c()
    key = (kind, tuple(c.ACCENT), tuple(c.TEXT), tuple(c.DIM))
    t = _themes.get(key)
    if t is not None and dpg.does_item_exist(t):
        return t
    light = _light()
    acc = tuple(c.ACCENT[:3])
    if kind == "primary":
        on = (20, 22, 28) if _lum(acc) > 0.62 else (255, 255, 255)
        cols = {dpg.mvThemeCol_Button: acc + (235,), dpg.mvThemeCol_ButtonHovered: _shift(acc, -22 if light else 24) + (255,),
                dpg.mvThemeCol_ButtonActive: _shift(acc, -40 if light else -28) + (255,), dpg.mvThemeCol_Text: on + (255,)}
    elif kind == "danger":
        text = (172, 30, 30) if light else (255, 150, 150)
        cols = {dpg.mvThemeCol_Button: RED + ((34 if light else 54),), dpg.mvThemeCol_ButtonHovered: RED + ((90 if light else 120),),
                dpg.mvThemeCol_ButtonActive: RED + (190,), dpg.mvThemeCol_Text: text + (255,)}
    else:                                              # quiet
        tx = tuple(c.TEXT[:3])
        cols = {dpg.mvThemeCol_Button: (0, 0, 0, 0), dpg.mvThemeCol_ButtonHovered: tx + (26,),
                dpg.mvThemeCol_ButtonActive: tx + (46,), dpg.mvThemeCol_Text: tuple(c.DIM[:3]) + (255,)}
    with dpg.theme() as t:
        for comp in (dpg.mvButton, dpg.mvImageButton):
            with dpg.theme_component(comp):
                for k, v in cols.items():
                    dpg.add_theme_color(k, v, category=dpg.mvThemeCat_Core)
            with dpg.theme_component(comp, enabled_state=False):
                # greyed: the slab and the words faded, whatever the weight
                for k, v in cols.items():
                    dpg.add_theme_color(k, tuple(v[:3]) + (int(v[3] * 0.35) if len(v) > 3 else 90,), category=dpg.mvThemeCat_Core)
    _themes[key] = t
    return t


KINDS = ("primary", "danger", "quiet")


def ensure():
    """The weights' themes for the colours in force, made now. Made later,
    in the middle of building a frame, a theme would become the "last
    item" the next tooltip is hung on (the code says dpg.last_item())."""
    for k in KINDS:
        theme(k)


def weigh(item, kind):
    """A button given a weight ("primary", "danger", "quiet"); the button back."""
    if item is None or not dpg.does_item_exist(item):
        return item
    _weighted[item] = kind
    dpg.bind_item_theme(item, theme(kind))
    return item


def primary(item):
    return weigh(item, "primary")


def danger(item):
    return weigh(item, "danger")


def quiet(item):
    return weigh(item, "quiet")


def plain(item):
    """A button back to no weight (a toggle's other state: the theme's own button)."""
    if item is None or not dpg.does_item_exist(item):
        return item
    _weighted.pop(item, None)
    dpg.bind_item_theme(item, 0)
    return item


def kind_of(item):
    return _weighted.get(item)


def rebind():
    """After a theme change: every weighted button in the new colours (and
    the ones deleted since, forgotten)."""
    ensure()
    for item, kind in list(_weighted.items()):
        if dpg.does_item_exist(item):
            dpg.bind_item_theme(item, theme(kind))
        else:
            del _weighted[item]


# --- empty states ---------------------------------------------------------------------------
def empty(parent, text, steps=(), wrap=0, lead=True):
    """What an empty list would hold, and the next step as a button - the
    first a primary when this is the list the frame is about (`lead`; a
    frame's second list keeps its steps plain, so one thing stands out).
    The group back."""
    c = _c()
    with dpg.group(parent=parent) as g:
        dpg.add_text(text, color=c.DIM, wrap=wrap)
        if steps:
            with dpg.group(horizontal=True):
                for k, (label, fn) in enumerate(steps):
                    b = dpg.add_button(label=label, user_data=fn, callback=lambda s, a, u: u())
                    if k == 0 and lead:
                        primary(b)
    return g


# --- what an action needs -----------------------------------------------------------------------
# action -> the need: "graph" a graph open; "sel" a node selected ("sel2",
# "sel3": two, three); "clip" something copied, and a graph to paste into;
# "undo" / "redo" something to take back or bring back where Undo acts
# (App.undo_target); "device" a device chosen; "stream" a device, or the
# stream running (to stop it); "sub" a sub-graph selected or entered;
# "preview" a pin being previewed; "repeat" an action to repeat.
NEEDS = {
    "delete": "sel", "duplicate": "sel", "cut": "sel", "copy": "sel", "mute": "sel", "collapse": "sel",
    "hide_pins": "sel", "dissolve": "sel", "disconnect": "sel", "label_node": "sel", "frame_selected": "graph",
    "frame_sel": "sel", "select_none": "sel", "select_up": "sel", "select_down": "sel", "select_linked": "sel",
    "swap_inputs": "sel", "fold": "sel2", "connect": "sel2",
    "align_left": "sel2", "align_right": "sel2", "align_top": "sel2", "align_bottom": "sel2",
    "distribute_x": "sel3", "distribute_y": "sel3",
    "paste": "clip", "arrange": "graph", "frame_all": "graph", "select_all": "graph", "select_invert": "graph",
    "undo": "undo", "redo": "redo",
    "push": "device", "script_send": "device", "stream": "stream",
    "enter_sub": "sub", "stop_preview": "preview", "repeat": "repeat",
}
WHY = {"graph": "no graph is open", "sel": "select a node first", "sel2": "select two nodes or more",
       "sel3": "select three nodes or more", "clip": "nothing copied yet", "undo": "nothing to undo",
       "redo": "nothing to redo", "device": "no device: Window > Devices... to choose one",
       "stream": "no device: Window > Devices... to choose one", "sub": "select a sub-graph node (or enter one)",
       "preview": "no pin is being previewed", "repeat": "nothing to repeat yet"}


class _State:
    def __init__(self):
        self.last = {}           # action -> whether it was enabled
        self.item_last = {}      # item -> whether it was enabled
        self.at = 0.0


_item_needs = {}         # a frame's button -> a need's name, or fn(app) -> bool


def need(item, what):
    """A frame's button greyed while it has nothing to act on: `what` is a
    need's name ("device", "sel"...) or fn(app) -> bool. The button back."""
    if item is not None and dpg.does_item_exist(item):
        _item_needs[item] = what
    return item


S = _State()


def _undo_state(app):
    try:
        t = app.undo_target()
    except Exception:
        return True, True
    gp, p = app.gp, app.project
    if t == "graph":
        return bool(gp._undo), bool(gp._redo)
    if t == "code":
        return bool(getattr(app, "_code_undo", None)), bool(getattr(app, "_code_redo", None))
    if t == "shape":
        return bool(getattr(app, "_shape_undo", None)), False
    if t == "sequence":
        return (p.can_undo("sequence") or p.can_undo("schedule")), (p.can_redo("sequence") or p.can_redo("schedule"))
    if t == "palettes":
        return p.can_undo("palettes"), p.can_redo("palettes")
    return True, True


def state(app):
    """Each need, met or not, now."""
    gp = app.gp
    g = gp.graph
    sel = gp._selected() if g else []
    u, r = _undo_state(app)
    host = bool(app.active_host())
    sub = bool(getattr(gp, "stack", None)) or any(str(g.nodes[n]["type"]).startswith("sub:") for n in sel if n in g.nodes) if g else False
    return {"graph": bool(g), "sel": len(sel) >= 1, "sel2": len(sel) >= 2, "sel3": len(sel) >= 3,
            "clip": bool(getattr(app, "clipboard", None)) and bool(g), "undo": bool(u), "redo": bool(r),
            "device": host, "stream": host or getattr(app, "ddp", None) is not None, "sub": sub,
            "preview": getattr(gp, "preview", None) is not None, "repeat": bool(getattr(app, "_last_action", None))}


def tint(on):
    """A toolbar icon's tint: the text colour, or faded while it has
    nothing to act on."""
    c = _c()
    return tuple(c.TEXT[:3]) + ((255,) if on else (70,))


def tint_of(item):
    """The tint a toolbar icon should have now (chrome's re-tint asks)."""
    try:
        return tint(dpg.get_item_configuration(item).get("enabled", True))
    except Exception:
        return tint(True)


def enabled(app, action, st=None):
    need = NEEDS.get(action)
    if need is None:
        return True
    return bool((st or state(app)).get(need, True))


def poll(app, every=0.2):
    """The menus' and the toolbar's actions, and the frames' buttons, greyed
    while they have nothing to act on - a few times a second, and only what
    changed is touched."""
    now = time.time()
    if now - S.at < every:
        return
    S.at = now
    st = state(app)
    for item, what in list(_item_needs.items()):
        if not dpg.does_item_exist(item):
            del _item_needs[item]
            S.item_last.pop(item, None)
            continue
        try:
            on = bool(what(app)) if callable(what) else bool(st.get(what, True))
        except Exception:
            on = True
        if S.item_last.get(item) != on:
            S.item_last[item] = on
            dpg.configure_item(item, enabled=on)
    tb = getattr(app, "_tb_btn", {})
    for action, need in NEEDS.items():
        on = bool(st.get(need, True))
        if S.last.get(action) == on:
            continue
        S.last[action] = on
        for tag in (f"mi_{action}", tb.get(action)):
            if tag is not None and dpg.does_item_exist(tag):
                dpg.configure_item(tag, enabled=on)
        b = tb.get(action)
        if b is not None and dpg.does_item_exist(b):
            dpg.configure_item(b, tint_color=tint(on))       # an image button looks the same off: its icon fades
        tt = f"tbtip_{action}"
        if dpg.does_item_exist(tt) and hasattr(app, "_tips"):
            b = app.keys.label(action)
            dpg.set_value(tt, app._tips.get(action, "") + (f"  {b}" if b else "") + ("" if on else f"  ({WHY.get(need, '')})"))
