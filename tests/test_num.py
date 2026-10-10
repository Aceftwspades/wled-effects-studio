"""The one number control (native/num.py): its formats, its fill, its pace,
set / configure / step from outside, and the press that turns into typing
(the mouse stubbed: a press let go where it began is a click, one that
moved is a drag). Run with python tests/test_num.py  (or pytest).
"""
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import dearpygui.dearpygui as dpg                 # noqa: E402

from native import num, typeface                 # noqa: E402


def test_formats_carry_the_unit_inside():
    assert num.fmt_for() == "%.5g"
    assert num.fmt_for("bpm", integer=True) % 120 == "120 bpm"
    assert num.fmt_for("Hz", 2) % 1.5 == "1.50 Hz"
    assert num.fmt_for("%", integer=True) % 150 == "150%"          # a percent sign is doubled in the format
    assert num.fmt_for("×", 2) % 1.5 == "1.50×" and num.fmt_for("°", 1) % 90 == "90.0°"


def _spec(lo, hi, log=False, integer=False, pace=None):
    ranged = lo is not None and hi is not None
    return {"lo": lo, "hi": hi, "ranged": ranged, "log": log, "int": integer, "open": log or not ranged, "pace": pace}


def test_the_fill_is_where_the_value_sits():
    assert num.fraction(_spec(0, 255), 51) == 0.2
    assert num.fraction(_spec(0, 255), 999) == 1.0 and num.fraction(_spec(0, 255), -5) == 0.0
    assert abs(num.fraction(_spec(0.01, 100, log=True), 1.0) - 0.5) < 1e-9       # a log range's middle is its geometric mean
    assert num.fraction(_spec(None, None), 5) == 0.0


def test_the_pace():
    """A range in about a field and a half; an open field by its size, or
    its pace while near 0; a log field by its size."""
    assert abs(num._speed(_spec(0, 300), 10) - 1.0) < 1e-9
    assert num._speed(_spec(None, None), 0) == 0.005
    assert abs(num._speed(_spec(None, None, pace=10.0), 0) - 0.1) < 1e-9
    assert abs(num._speed(_spec(None, None), 50) - 0.5) < 1e-9
    assert abs(num._speed(_spec(0.01, 100, log=True), 20) - 0.2) < 1e-9


def test_callbacks_take_what_they_ask_for():
    got = []
    num._call(lambda: got.append(0), 1, 2, 3)
    num._call(lambda s, v: got.append((s, v)), 1, 2, 3)
    num._call(lambda s, v, u: got.append((s, v, u)), 1, 2, 3)
    num._call(lambda *a: got.append(a), 1, 2, 3)
    assert got == [0, (1, 2), (1, 2, 3), (1, 2, 3)]


def _context():
    dpg.create_context()
    typeface._scale = 1.0
    typeface._at.clear(); typeface._fonts.clear()      # fonts belong to a context: a new one makes its own
    dpg.add_window(tag="w")


def test_set_configure_and_step_in_a_window():
    _context()
    try:
        calls = []
        num.add("f", 100, 0, 200, integer=True, parent="w", callback=lambda s, v: calls.append(v))
        assert dpg.get_item_type("f").endswith("DragInt") and dpg.does_item_exist("f__fill")
        assert abs(dpg.get_value("f__fill") - 0.5) < 1e-6
        num.set("f", 50.4)
        assert dpg.get_value("f") == 50 and abs(dpg.get_value("f__fill") - 0.25) < 1e-6
        num.configure("f", hi=100)
        assert dpg.get_item_configuration("f")["max_value"] == 100 and abs(dpg.get_value("f__fill") - 0.5) < 1e-6
        assert num.step("f", 3) == 53 and calls == [53]            # a step fires the field's own callback
        num.set("f", 99); num.step("f", 5)
        assert dpg.get_value("f") == 100                           # clamped at the end
        num.add("g", 3.0, None, None, parent="w", unit="Hz")
        assert not dpg.does_item_exist("g__fill") and num.is_num("g")    # no range: no fill
        num.add("h", 5, 1, None, integer=True, parent="w")
        cfg = dpg.get_item_configuration("h")
        assert cfg["min_value"] == 1 and cfg["clamped"] and not dpg.does_item_exist("h__fill")    # one end clamps
        dpg.delete_item("w", children_only=True)
        num.prune()
        assert not num.is_num("f")
    finally:
        dpg.destroy_context()
        num._specs.clear(); num._press.clear(); num._typing.clear()
        num._registry = None; num._themes.clear()


def test_a_click_turns_into_typing_and_a_drag_does_not():
    _context()
    stub = {"down": True, "pos": (100.0, 50.0)}
    focused = []
    real = (dpg.is_mouse_button_down, dpg.get_mouse_pos, dpg.focus_item, dpg.is_mouse_button_double_clicked, dpg.is_key_down)
    try:
        dpg.is_mouse_button_down = lambda b: stub["down"]
        dpg.get_mouse_pos = lambda local=False: stub["pos"]
        dpg.focus_item = lambda item: focused.append(item)
        dpg.is_mouse_button_double_clicked = lambda b: False
        dpg.is_key_down = lambda k: False
        num.add("f", 10, 0, 100, integer=True, parent="w")
        i = dpg.get_alias_id("f")
        # a press let go where it began: typing, the number selected
        num._on_activated(None, i)
        stub["down"] = False
        num._on_deactivated(None, i)
        assert focused == [i] and i in num._typing
        # the typing's own activation and its end (Enter): no second focus
        num._on_activated(None, i)
        num._on_deactivated(None, i)
        assert focused == [i] and i not in num._typing
        # a press that moves: a drag, no typing
        stub["down"] = True; stub["pos"] = (100.0, 50.0)
        num._on_activated(None, i)
        stub["down"] = False; stub["pos"] = (140.0, 50.0)
        num._on_deactivated(None, i)
        assert focused == [i]
        # a click whose focus never took (the field never became active): the next press is a press, not swallowed
        stub["down"] = True; stub["pos"] = (100.0, 50.0)
        num._typing[i] = time.time() - 5
        num._on_activated(None, i)
        stub["down"] = False
        num._on_deactivated(None, i)
        assert focused == [i, i] and i in num._typing
    finally:
        (dpg.is_mouse_button_down, dpg.get_mouse_pos, dpg.focus_item, dpg.is_mouse_button_double_clicked, dpg.is_key_down) = real
        dpg.destroy_context()
        num._specs.clear(); num._press.clear(); num._typing.clear()
        num._registry = None; num._themes.clear()


def test_focus_puts_a_drag_field_into_typing():
    """What the click leans on: Dear PyGui's focus_item puts a drag field
    into its text mode (checked on a frame drawn off screen)."""
    if sys.platform != "win32":
        return
    dpg.create_context()
    try:
        with dpg.window(tag="w"):
            dpg.add_drag_float(tag="d", default_value=1.5, format="%.2f Hz")
        dpg.create_viewport(title="num", width=200, height=100, x_pos=-4000, y_pos=0)
        dpg.setup_dearpygui()
        dpg.show_viewport()
        for _ in range(3):
            dpg.render_dearpygui_frame()
        dpg.focus_item("d")
        for _ in range(3):
            dpg.render_dearpygui_frame()
        assert dpg.is_item_active("d") and dpg.is_item_focused("d")
    finally:
        dpg.destroy_context()


def test_a_field_in_a_scrolling_list_types_after_one_above_it():
    """A field in a child window (a scrolling list) under a window whose own field was typed in last: focus_item
    puts it into typing too - Dear PyGui flattens a child's navigation into its parent's, and then the parent's
    field took the focus back (checked on frames drawn off screen)."""
    if sys.platform != "win32":
        return
    dpg.create_context()
    typeface._scale = 1.0
    typeface._at.clear(); typeface._fonts.clear()
    try:
        with dpg.window(tag="w", width=300, height=300):
            with dpg.child_window(tag="kid", height=80):
                for k in range(8):
                    num.add(f"row{k}", 2.0, 0.1, 600, unit="s", digits=1, width=80, wide=True)
            num.add("below", 1.0, 0.0, 30.0, unit="s", digits=1, width=80, wide=True)
        assert not dpg.get_item_configuration("kid")["flattened_navigation"]
        dpg.create_viewport(title="num", width=320, height=320, x_pos=-4000, y_pos=0)
        dpg.setup_dearpygui()
        dpg.show_viewport()
        for _ in range(3):
            dpg.render_dearpygui_frame()
        dpg.focus_item("below")
        for _ in range(3):
            dpg.render_dearpygui_frame()
        assert dpg.is_item_active("below")
        dpg.focus_item("row1")
        for _ in range(3):
            dpg.render_dearpygui_frame()
        assert dpg.is_item_active("row1") and not dpg.is_item_active("below")
    finally:
        dpg.destroy_context()
        num._specs.clear(); num._press.clear(); num._typing.clear(); num._unflat.clear()
        num._registry = None; num._themes.clear()


if __name__ == "__main__":
    import inspect
    bad = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and inspect.isfunction(fn):
            try:
                fn(); print("ok  ", name)
            except Exception as ex:
                bad += 1; print("FAIL", name, repr(ex)[:3000])
    sys.exit(1 if bad else 0)
