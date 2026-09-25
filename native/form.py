"""Forms that read left to right (the critique's C6).

Dear PyGui draws a control's label after it: "Box Fire  v effect",
"[slider] 128 Rise", "R:255 G:160 B:0 [swatch] primary" - labels hugging
controls of different widths, so they never lined up, and a lookup was a
search along a ragged edge. A form row here is its label in a column of
its own, right-aligned against the control after it:

         project [default          v]
          effect [Box Fire         v]
         palette [* Random Cycle   v]

    with form.row("palette"):
        dpg.add_combo(..., width=-1)

A row's numbers - an input, a drag, a slider's box - are set in the
monospace as it closes (typeface: field values line up, a changing one
does not shift its neighbours). A checkbox keeps its words after it, in
the control column (form.check). Where a row holds several fields, each
is led by its own words (form.inline). A colour is a swatch and its hex
(form.colour); the picker, under the swatch, has R, G and B.
"""
from contextlib import contextmanager

import dearpygui.dearpygui as dpg

from native.typeface import px
from native import typeface

LABEL_W = 108            # the label column at 100%: "1-D effects as" fits, a longer label is cut with its whole on hover
GAP = 8                  # between the label and its control (the theme's item spacing)
# the fields whose text is a value: set in the monospace when their row closes
VALUE_ITEMS = ("mvAppItemType::mvInputInt", "mvAppItemType::mvInputFloat", "mvAppItemType::mvInputDouble",
               "mvAppItemType::mvDragInt", "mvAppItemType::mvDragFloat", "mvAppItemType::mvSliderInt",
               "mvAppItemType::mvSliderFloat", "mvAppItemType::mvInputIntMulti", "mvAppItemType::mvInputFloatMulti",
               "mvAppItemType::mvInputDoubleMulti", "mvAppItemType::mvDragIntMulti", "mvAppItemType::mvDragFloatMulti",
               "mvAppItemType::mvSliderIntMulti", "mvAppItemType::mvSliderFloatMulti")


def _dim():
    from native import chrome
    return chrome.DIM


def label(text, width=None, tip=None, color=None):
    """The label column, in a horizontal group before its control: `text`
    right-aligned in a column `width` wide (at 100%), in the dim of a
    label; cut at a word, with "...", when it is longer, the whole of it on
    hover (with `tip`, if any, under it)."""
    import math
    # [spacer][gap][label][gap][control]: the control starts at the column's width plus a gap, so the
    # spacer is the column less a gap and the label - never under a pixel, or the row would start short
    w = px(width or LABEL_W)
    room = w - px(GAP) - 1
    full = str(text)
    shown = full
    if typeface.measure(full) > room:
        from native import nodeface
        shown = nodeface.fit_width(full, room, typeface.measure)
    tw = math.ceil(typeface.measure(shown))           # Dear ImGui rounds a text's width up
    dpg.add_spacer(width=max(1, w - px(GAP) - tw))
    t = dpg.add_text(shown, color=color or _dim())
    if shown != full or tip:
        words = "\n".join(w for w in ((full if shown != full else ""), (tip or "")) if w)
        with dpg.tooltip(t):
            dpg.add_text(words, wrap=px(360))
    return t


def indent(width=None):
    """The label column left empty: what follows sits under the controls."""
    dpg.add_spacer(width=px(width or LABEL_W))


def mono_values(item):
    """Every value field under `item`, in the monospace."""
    for k in dpg.get_item_children(item, 1) or []:
        t = dpg.get_item_type(k)
        if t in VALUE_ITEMS:
            typeface.mono(k)
        elif t.endswith("::mvGroup"):
            mono_values(k)


@contextmanager
def row(text, tip=None, width=None, parent=None, tag=None, show=True):
    """A form row: `text` in the label column, then the controls the block
    adds (a width of -1 fills the rest of the row). The row's value fields
    are set in the monospace as it closes."""
    kw = {"horizontal": True, "horizontal_spacing": px(GAP), "show": show}
    if parent is not None:
        kw["parent"] = parent
    if tag is not None:
        kw["tag"] = tag
    with dpg.group(**kw) as g:
        label(text, width, tip)
        yield g
    mono_values(g)


@contextmanager
def under(width=None, parent=None, tag=None, show=True):
    """A row whose label column is empty: checkboxes and buttons that
    belong to the form, lined up under its controls."""
    kw = {"horizontal": True, "horizontal_spacing": px(GAP), "show": show}
    if parent is not None:
        kw["parent"] = parent
    if tag is not None:
        kw["tag"] = tag
    with dpg.group(**kw) as g:
        indent(width)
        yield g
    mono_values(g)


def check(text, width=None, parent=None, **kw):
    """A checkbox in the control column, its words after it (a checkbox's
    words are what it turns on: they stay with it)."""
    with under(width, parent=parent):
        return dpg.add_checkbox(label=text, **kw)


def note(text, width=None, **kw):
    """A line about the form - what a shape amounts to, why a row is empty -
    under its controls, in the dim of a hint, wrapped at the window's edge."""
    kw.setdefault("color", _dim())
    kw.setdefault("wrap", 0)
    return dpg.add_text(text, indent=px(width or LABEL_W) + px(GAP), **kw)


def inline(text, color=None):
    """Words leading the field after them, in a row of several fields:
    "name [   ]  seconds [0.0]  transition [0.7]"."""
    return dpg.add_text(text, color=color or _dim())


# --- a colour: its swatch, then its hex ----------------------------------------------------
def hex_of(rgb):
    return "#%02X%02X%02X" % tuple(int(c) for c in rgb[:3])


def parse_hex(text):
    """(r, g, b) from "#FFA000", "ffa000", "#fa0" or "255,160,0"; None when it is none of them."""
    s = str(text or "").strip()
    if "," in s:
        try:
            parts = [int(float(p)) for p in s.split(",")]
        except ValueError:
            return None
        return tuple(max(0, min(255, p)) for p in parts[:3]) if len(parts) >= 3 else None
    s = s.lstrip("#")
    if len(s) == 3:
        s = "".join(c * 2 for c in s)
    if len(s) != 6:
        return None
    try:
        return tuple(int(s[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return None


def _rgb255(val):
    """A colour edit's value (0..1 floats, or 0..255) as 0..255 ints."""
    return tuple(int(round(c * 255)) if c <= 1.0 else int(c) for c in list(val)[:3])


def swatch(tag, rgb, callback):
    """A colour's swatch (a click opens the picker, with R, G and B), then
    its hex (mono; typing "#FFA000", "fa0" or "255,160,0" and Enter sets
    it), in the row open now. `callback(rgb)` gets 0..255 ints from either;
    set_colour(tag, rgb) moves both from outside."""
    def from_swatch(s, v):
        c = _rgb255(v)
        dpg.set_value(f"{tag}_hex", hex_of(c))
        callback(c)

    def from_hex(s, v):
        c = parse_hex(v)
        if c is None:
            dpg.set_value(f"{tag}_hex", hex_of(_rgb255(dpg.get_value(tag))))    # not a colour: as it was
            return
        dpg.set_value(tag, list(c) + [255])
        dpg.set_value(f"{tag}_hex", hex_of(c))
        callback(c)
    dpg.add_color_edit(list(rgb[:3]) + [255], tag=tag, no_alpha=True, no_inputs=True, no_label=True,
                       callback=from_swatch)
    typeface.mono(dpg.add_input_text(tag=f"{tag}_hex", default_value=hex_of(rgb), width=px(84), on_enter=True,
                                     callback=from_hex))
    return tag


def colour(text, rgb, tag, callback, tip=None, width=None, parent=None):
    """A colour row: `text` in the label column, then the swatch and its hex."""
    with row(text, tip, width, parent=parent, tag=f"{tag}_row"):
        swatch(tag, rgb, callback)
    return tag


def set_colour(tag, rgb):
    """A colour row shows `rgb` (0..255), swatch and hex."""
    if dpg.does_item_exist(tag):
        dpg.set_value(tag, list(rgb[:3]) + [255])
    if dpg.does_item_exist(f"{tag}_hex"):
        dpg.set_value(f"{tag}_hex", hex_of(rgb))
