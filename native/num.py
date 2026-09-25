"""One number control (the critique's C7).

The studio had five: a slider showing no value beside a box that did (the
side panel), drag fields (the nodes), sliders with the value on the track
under a grab that could sit on the digits, log sliders with the value
outside the track, and integer sliders whose grab at the minimum read as a
checkbox. Each had to be learnt, and two were misread. Now there is one:

    [      128      ]      the value on the track, in the monospace
    ▔▔▔▔▔▔▔▔▔                a thin fill under it: where it sits in its range

- drag it sideways to change it (Shift: ten times as far, Alt: a hundredth);
- click it - press and let go without moving - to type a value (Enter
  takes it, Escape leaves it); a double click or Ctrl+click does the same;
- Ctrl+wheel over it steps it;
- the unit sits inside, after the value ("120.0 bpm", "0.50 Hz");
- a log field moves by ratio: its drag speed follows its size, and its
  fill is along the log of its range.

A field without a range drags at a hundredth of its size a pixel and has
no fill. It is Dear PyGui's drag field underneath (a click-release does
nothing there, so the handlers here turn one into typing: focus_item puts
a drag field into its text mode with the number selected), and a two-pixel
progress bar under it as the fill.

    num.add("inp_sx", 128, 0, 255, integer=True, callback=...)
    num.set("inp_sx", 200)          # the value and the fill, from outside
"""
import math
import time

import dearpygui.dearpygui as dpg

from native.typeface import px
from native import typeface

FILL_H = 2               # the fill's height at 100%
CLICK_PX = 3             # a press that moves less than this and lets go is a click: typing
CLICK_S = 0.6            # ... within this long

_specs = {}              # item id -> {"lo", "hi", "log", "int", "fill": the fill bar or None, "tag"}
_press = {}              # item id -> (typing-capable press?, mouse x, mouse y, time)
_typing = set()          # items focused for typing by a click: their next deactivation is the typed value's
_registry = None
_themes = {}


def _id(item):
    try:
        return dpg.get_alias_id(item) if isinstance(item, str) else int(item)
    except Exception:
        return item


def _fill_theme():
    """The fill: the accent along the bottom of the field, on nothing."""
    th = _themes.get("fill")
    if th is not None and dpg.does_item_exist(th):
        return th
    from native import chrome
    acc = tuple(chrome.ACCENT[:3])
    with dpg.theme() as th:
        with dpg.theme_component(dpg.mvProgressBar):
            dpg.add_theme_color(dpg.mvThemeCol_FrameBg, acc + (34,), category=dpg.mvThemeCat_Core)
            dpg.add_theme_color(dpg.mvThemeCol_PlotHistogram, acc + (230,), category=dpg.mvThemeCat_Core)
            dpg.add_theme_style(dpg.mvStyleVar_FrameRounding, 0, category=dpg.mvThemeCat_Core)
            dpg.add_theme_style(dpg.mvStyleVar_FramePadding, 0, 0, category=dpg.mvThemeCat_Core)
    _themes["fill"] = th
    return th


def _tight_theme():
    """The field and its fill with no gap between them."""
    th = _themes.get("tight")
    if th is not None and dpg.does_item_exist(th):
        return th
    with dpg.theme() as th:
        with dpg.theme_component(dpg.mvAll):
            dpg.add_theme_style(dpg.mvStyleVar_ItemSpacing, px(8), 0, category=dpg.mvThemeCat_Core)
    _themes["tight"] = th
    return th


def rebind():
    """The fills in the colours in force (a theme change): the theme is made again and bound anew."""
    old = _themes.pop("fill", None)
    th = _fill_theme()
    for s in _specs.values():
        f = s.get("fill")
        if f and dpg.does_item_exist(f):
            dpg.bind_item_theme(f, th)
    if old is not None and dpg.does_item_exist(old):
        dpg.delete_item(old)


def _handlers():
    global _registry
    if _registry is not None and dpg.does_item_exist(_registry):
        return _registry
    with dpg.item_handler_registry() as _registry:
        dpg.add_item_activated_handler(callback=_on_activated)
        dpg.add_item_deactivated_handler(callback=_on_deactivated)
        dpg.add_item_edited_handler(callback=_on_edited)
    return _registry


def _on_activated(sender, item):
    """Pressed (or focused for typing): where and when, to tell a click from a drag."""
    item = _id(item)
    if item in _typing:
        return                                        # the typing a click began
    ctrl = dpg.is_key_down(dpg.mvKey_LControl) or dpg.is_key_down(dpg.mvKey_RControl)
    by_mouse = dpg.is_mouse_button_down(dpg.mvMouseButton_Left) and not ctrl \
        and not dpg.is_mouse_button_double_clicked(dpg.mvMouseButton_Left)
    x, y = dpg.get_mouse_pos(local=False)
    _press[item] = (by_mouse, x, y, time.time())


def _on_deactivated(sender, item):
    """Let go: a press that did not move is a click - the field turns into
    typing, the number selected. A field's typing ends here too."""
    item = _id(item)
    if item in _typing:
        _typing.discard(item)                         # the typed value is in (or Escape left it)
        _press.pop(item, None)
        return
    p = _press.pop(item, None)
    if not p or not p[0]:
        return
    x, y = dpg.get_mouse_pos(local=False)
    if abs(x - p[1]) < px(CLICK_PX) and abs(y - p[2]) < px(CLICK_PX) and time.time() - p[3] < CLICK_S \
            and dpg.does_item_exist(item) and dpg.is_item_enabled(item):
        _typing.add(item)
        dpg.focus_item(item)


def _on_edited(sender, item):
    """Dragged or typed: the fill follows, and a log field's pace its size."""
    item = _id(item)
    s = _specs.get(item)
    if not s:
        return
    v = dpg.get_value(item)
    if s["open"]:
        dpg.configure_item(item, speed=_speed(s, v))
    _draw_fill(s, v)


def _speed(s, v):
    """Value a pixel: a range crossed in about one and a half field widths;
    a log field or an open one a hundredth of its size - or of its pace,
    the size it is usually about, while it is near 0 (never under 0.005,
    or a twentieth of a step for an integer)."""
    if s["open"]:
        size = max(abs(float(v or 0.0)), abs(float(s.get("pace") or 0.0)))
        if s["log"]:
            size = max(size, float(s["lo"]))
        return max(0.05 if s["int"] else 0.005, size * 0.01)
    span = float(s["hi"]) - float(s["lo"])
    return max(span / 300.0, 0.02 if s["int"] else 1e-6)


def fraction(s, v):
    """Where `v` sits in the field's range, 0..1 (along the log for a log field)."""
    lo, hi = s["lo"], s["hi"]
    if not s["ranged"] or hi == lo:
        return 0.0
    v = min(max(float(v), float(lo)), float(hi))
    if s["log"] and lo > 0:
        return math.log(v / lo) / math.log(hi / lo)
    return (v - lo) / (hi - lo)


def _draw_fill(s, v):
    f = s.get("fill")
    if f and dpg.does_item_exist(f):
        dpg.set_value(f, fraction(s, v))


def fmt_for(unit="", digits=None, integer=False):
    """The value's format with its unit inside: "%d", "%.2f Hz", "%.5g"."""
    if integer:
        base = "%d"
    elif digits is None:
        base = "%.5g"                                # five significant digits: 12000 stays 12000, not 1.2e+04
    else:
        base = f"%.{int(digits)}f"
    if not unit:
        return base
    unit = unit.replace("%", "%%")                   # a literal percent in a printf format
    return base + ("" if unit in ("°", "×", "%%") else " ") + unit


def add(tag, value, lo=None, hi=None, *, integer=False, log=False, unit="", digits=None, fmt=None, width=-1,
        callback=None, user_data=None, parent=None, show=True, fill=True, fill_h=None, enabled=True,
        wide=False, pace=None):
    """The number control: a drag field (tag) holding `value`, clamped to lo
    and hi (either may be None), with a thin fill under it for where it
    sits when it has both. `wide`: a range too wide to slide across (it
    still clamps; no fill, paced by the value's size, as an open field is).
    `pace`: the size an open field is usually about (its default), for its
    speed while it is near 0. `callback` is the field's own (Dear PyGui's
    sender, value, user_data). Returns the field's tag."""
    if not tag:
        tag = f"num_{dpg.generate_uuid()}"            # a field made without a name gets one: its group and fill hang on it
    kw = {"show": show}
    if parent is not None:
        kw["parent"] = parent
    ranged = lo is not None and hi is not None and not wide
    if log and not (ranged and lo > 0):
        log = False
    s = {"lo": lo, "hi": hi, "ranged": ranged, "log": bool(log), "int": bool(integer), "open": bool(log) or not ranged,
         "pace": pace, "fill": None, "tag": tag}
    cast = int if integer else float
    with dpg.group(tag=f"{tag}__num", **kw) as g:
        field = dict(tag=tag, width=width, default_value=cast(value),
                     format=fmt or fmt_for(unit, digits, integer), speed=_speed(s, value), enabled=enabled)
        if lo is not None or hi is not None:
            # Dear PyGui clamps both ends or neither: an open end is a far one
            far = (1 << 30) if integer else 1e12
            field.update(min_value=cast(lo) if lo is not None else -far, max_value=cast(hi) if hi is not None else far, clamped=True)
        if callback is not None:
            field["callback"] = callback
        if user_data is not None:
            field["user_data"] = user_data
        item = dpg.add_drag_int(**field) if integer else dpg.add_drag_float(**field)
        typeface.mono(item)
        if ranged and fill:
            s["fill"] = dpg.add_progress_bar(tag=f"{tag}__fill", width=width, height=max(1, int(fill_h or px(FILL_H))),
                                             default_value=fraction(s, value), overlay="")
            dpg.bind_item_theme(s["fill"], _fill_theme())
    dpg.bind_item_theme(g, _tight_theme())
    dpg.bind_item_handler_registry(item, _handlers())
    _specs[_id(item)] = s
    return tag


def is_num(item):
    return _id(item) in _specs


def set(tag, v):                                       # noqa: A001 - the module's verb, as num.set
    """The value from outside - a MIDI knob, a sweep, a sequence's ramp - and the fill with it."""
    if not dpg.does_item_exist(tag):
        return
    s = _specs.get(_id(tag))
    if s and s["int"]:
        v = int(round(float(v)))
    dpg.set_value(tag, v)
    if s:
        _draw_fill(s, v)
        if s["open"]:
            dpg.configure_item(tag, speed=_speed(s, v))


def configure(tag, lo=None, hi=None):
    """A new range for the field (the scrub's grows with the history): its
    clamp, its pace and its fill follow."""
    s = _specs.get(_id(tag))
    if not s or not dpg.does_item_exist(tag):
        return
    if lo is not None:
        s["lo"] = lo
    if hi is not None:
        s["hi"] = hi
    if s["fill"]:
        s["ranged"] = s["lo"] is not None and s["hi"] is not None
        s["open"] = s["log"] or not s["ranged"]
    kw = {}
    if s["lo"] is not None:
        kw["min_value"] = int(s["lo"]) if s["int"] else float(s["lo"])
    if s["hi"] is not None:
        kw["max_value"] = int(s["hi"]) if s["int"] else float(s["hi"])
    v = dpg.get_value(tag)
    dpg.configure_item(tag, speed=_speed(s, v), **kw)
    _draw_fill(s, v)


def forget(tag):
    """A field that is gone (its parent rebuilt): its record goes."""
    i = _id(tag)
    _specs.pop(i, None); _press.pop(i, None); _typing.discard(i)


def prune():
    """Records of fields that no longer exist, dropped (a rebuild deletes them wholesale)."""
    for i in [i for i in _specs if not dpg.does_item_exist(i)]:
        _specs.pop(i, None); _press.pop(i, None); _typing.discard(i)


def hovered():
    """The number field under the pointer, or None."""
    for i, s in _specs.items():
        if dpg.does_item_exist(i) and dpg.is_item_shown(i) and dpg.is_item_hovered(i):
            return i
    return None


def step(item, notches):
    """Ctrl+wheel: `notches` steps - one for an integer field, a hundredth
    of the range for a bounded one, 5% for a log one or an open one."""
    s = _specs.get(_id(item))
    if not s or not dpg.does_item_exist(item) or not dpg.is_item_enabled(item):
        return None
    v = float(dpg.get_value(item))
    lo, hi = s["lo"], s["hi"]
    if s["int"]:
        v = v + notches
    elif s["open"]:
        v = v * (1.05 ** notches) if v else (0.01 * notches)
    else:
        v = v + notches * (hi - lo) / 100.0
    if lo is not None:
        v = max(float(lo), v)
    if hi is not None:
        v = min(float(hi), v)
    set(item, v)
    fire(item)
    return dpg.get_value(item)


def _call(cb, *args):
    """A callback called as Dear PyGui calls one: with as many of (sender,
    app_data, user_data) as it takes - defaulted parameters count, as they
    do there."""
    import inspect
    try:
        ps = list(inspect.signature(cb).parameters.values())
    except (TypeError, ValueError):
        return cb(*args)
    if any(p.kind == p.VAR_POSITIONAL for p in ps):
        return cb(*args)
    n = sum(1 for p in ps if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD))
    return cb(*args[:min(n, len(args))])


def fire(item):
    """The field's callback with its value now, as if it had been dragged there."""
    if not dpg.does_item_exist(item):
        return
    cb = dpg.get_item_callback(item)
    if cb:
        _call(cb, item, dpg.get_value(item), dpg.get_item_user_data(item))
