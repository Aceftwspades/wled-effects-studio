"""Messages that stay (native/messages.py): a problem held while it lasts
and logged once however often it is judged again, a readout that moves
kept to one line, a repeat counted, the kinds, the footer's short line,
the log as text - and, on a frame drawn off screen, the footer's row a
line of its own, its words level with its buttons. Run with
python tests/test_messages.py  (or pytest).
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import dearpygui.dearpygui as dpg                 # noqa: E402

from native import messages, typeface            # noqa: E402


class App:
    """What messages reads of the studio: the project it is about."""
    class project:
        path = "projects/default"


APP = App()


def _reset():
    messages.LOG.clear()
    messages.HELD.clear()
    messages._st.update(shown=None, dirty=False, filled=0.0)


def _context():
    dpg.create_context()
    typeface._scale = 1.0
    typeface._at.clear(); typeface._fonts.clear()      # fonts belong to a context: a new one makes its own


def test_a_problem_is_logged_once_while_it_lasts():
    """Judged again on every change, a graph's problem stays one entry; one
    that reads differently now is logged; one fixed goes from the held."""
    _reset(); _context()
    try:
        items = {"problem:g.json:7": ("Remap #7: x cannot take a colour", ("g.json", 7, False))}
        for _ in range(5):
            messages.hold(APP, "problem:g.json:", items)
        assert len(messages.LOG) == 1 and list(messages.HELD) == ["problem:g.json:7"]
        assert messages.LOG[0]["kind"] == "error" and messages.LOG[0]["node"] == ("g.json", 7, False)
        items["problem:g.json:9"] = ("Output #9: more than one Output", ("g.json", 9, False))
        messages.hold(APP, "problem:g.json:", items)
        assert len(messages.LOG) == 2 and len(messages.HELD) == 2
        items["problem:g.json:7"] = ("Remap #7: x cannot take a vector", ("g.json", 7, False))
        messages.hold(APP, "problem:g.json:", items)
        assert len(messages.LOG) == 3 and messages.HELD["problem:g.json:7"]["text"].endswith("vector")
        messages.hold(APP, "problem:other.json:", {})                  # another graph's judgement leaves these alone
        assert len(messages.HELD) == 2
        messages.hold(APP, "problem:g.json:", {})                      # all fixed
        assert not messages.HELD and len(messages.LOG) == 3            # the log keeps what happened
    finally:
        dpg.destroy_context()


def test_a_keyed_problem_posted_again_is_counted_and_comes_last():
    _reset(); _context()
    try:
        messages.post(APP, "g.json does not compile: no Output", "error", key="graph:g.json")
        messages.post(APP, "g.json saved")
        messages.post(APP, "g.json does not compile: no Output", "error", key="graph:g.json")
        assert [e["text"] for e in messages.LOG] == ["g.json saved", "g.json does not compile: no Output"]
        assert messages.LOG[-1]["n"] == 2 and messages.HELD["graph:g.json"] is messages.LOG[-1]
        assert messages.clear(APP, "graph:") == 1 and not messages.HELD
    finally:
        dpg.destroy_context()


def test_readouts_merge_and_repeats_count():
    _reset(); _context()
    try:
        for v in (0.5, 0.53, 0.61):
            messages.post(APP, f"Noise #12 scale: {v} - live", merge="live:12:scale")
        assert len(messages.LOG) == 1 and messages.LOG[0]["text"] == "Noise #12 scale: 0.61 - live"
        messages.post(APP, "Noise #12 octaves: 2 - live", merge="live:12:octaves")      # another readout: a line of its own
        assert len(messages.LOG) == 2
        messages.post(APP, "choose a device first"); messages.post(APP, "choose a device first")
        assert len(messages.LOG) == 3 and messages.LOG[-1]["n"] == 2
        # two messages that only share a first word are two messages (MIDI learn's, one after the other)
        messages.post(APP, "MIDI: CC 7 ch 1 -> Speed"); messages.post(APP, "MIDI: CC 8 ch 2 -> Intensity")
        assert len(messages.LOG) == 5
    finally:
        dpg.destroy_context()


def test_kinds():
    _reset(); _context()
    try:
        messages.post(APP, "could not read the palette: bad header")
        messages.post(APP, "dropped 2 wire(s) to pins that no longer exist")
        messages.post(APP, "g.json saved")
        messages.post(APP, "held", key="x:1")
        assert [e["kind"] for e in messages.LOG] == ["warn", "warn", "info", "error"]
    finally:
        dpg.destroy_context()


def test_the_line_is_short_and_the_log_is_whole():
    long = ("that wire closed a loop: a Delay on it hands last frame's value round; undo takes both out, "
            "and the loop's other wires stay as they were")
    s = messages.short(long)
    assert s == "that wire closed a loop: a Delay on it hands last frame's value round"
    assert len(messages.short("word " * 60)) <= messages.SHORT
    _reset(); _context()
    try:
        messages.post(APP, long)
        messages.post(APP, "Remap #7: x cannot take a colour", key="problem:g.json:7")
        text = messages.dump()
        assert text.startswith("problems:") and long in text and "(x" not in text
    finally:
        dpg.destroy_context()


def test_clear_leaves_the_problems():
    _reset(); _context()
    try:
        messages.post(APP, "g.json saved")
        messages.post(APP, "Remap #7: x cannot take a colour", key="problem:g.json:7")
        messages.post(APP, "zoom 100%")
        messages.clear_recent(APP)
        assert [e["text"] for e in messages.LOG] == ["Remap #7: x cannot take a colour"] and len(messages.HELD) == 1
        messages.clear(APP, "problem:g.json:")
        messages.clear_recent(APP)
        assert not messages.LOG and messages.dump() == ""
    finally:
        dpg.destroy_context()


def test_the_footer_row_is_a_line_of_its_own():
    """The problems button hides with its tooltip: Dear PyGui keeps a
    tooltip as the next item in a row, and a row whose first item drawn is
    a tooltip goes on the line above (the footer then measured a row short
    and the panes hid it). The line is a button so its words sit level with
    the buttons' (a text after a small button sits lower)."""
    if sys.platform != "win32":
        return
    _reset(); _context()
    try:
        with dpg.window(tag="w", width=600, height=200):
            with dpg.group(tag="foot"):
                dpg.add_text("the stats line", tag="stats")
                messages.build(APP, "foot")
        dpg.create_viewport(title="messages", width=640, height=240, x_pos=-4000, y_pos=0)
        dpg.setup_dearpygui()
        dpg.show_viewport()

        def frames():
            for _ in range(3):
                dpg.render_dearpygui_frame()

        frames()
        top = dpg.get_item_rect_min("stats")[1]
        row = dpg.get_item_rect_min("msg_log_btn")[1]
        assert row > top, "nothing held: the log button went up onto the stats line"
        messages.post(APP, "g.json saved")
        frames()
        assert dpg.is_item_shown("msg_line") and dpg.get_item_rect_min("msg_line")[1] == row
        messages.post(APP, "Remap #7: x cannot take a colour", "error", key="problem:g.json:7")
        frames()
        assert dpg.get_item_configuration("msg_problems")["label"] == "1 problem"
        assert dpg.get_item_rect_min("msg_problems")[1] == row and dpg.get_item_rect_min("msg_log_btn")[1] == row
        messages.clear(APP, "problem:")
        frames()
        assert not dpg.is_item_shown("msg_problems") and dpg.get_item_rect_min("msg_log_btn")[1] == row
        assert dpg.get_item_rect_size("msg_row")[1] > 0
    finally:
        dpg.destroy_context()


def test_a_note_leaves_the_line():
    _reset(); _context()
    try:
        with dpg.window(tag="w"):
            with dpg.group(tag="foot"):
                messages.build(APP, "foot")
        messages.post(APP, "g.json saved")
        messages.post(APP, "Remap #7: x cannot take a colour", "error")
        messages.LOG[-1]["t"] -= 3600                                  # an error stays, however old
        messages.poll(APP)
        assert dpg.is_item_shown("msg_line")
        messages.post(APP, "g.json saved again")
        messages.LOG[-1]["t"] -= messages.LINGER["info"] + 1
        messages.poll(APP)
        assert not dpg.is_item_shown("msg_line") and len(messages.LOG) == 3
    finally:
        dpg.destroy_context()


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
