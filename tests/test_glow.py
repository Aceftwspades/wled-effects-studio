"""The frames' holes for open menus (native/glow.py clamp_popup): a menu is
where ImGui puts it - moved back inside the window, so a long list rises over
the item it hangs from (File > Open graph's did, and the frames ran through
its top). Run with  python tests/test_glow.py  (or pytest).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from native import glow                                    # noqa: E402


def test_a_menu_that_fits_stays_where_it_was_asked():
    assert glow.clamp_popup(340, 178, 150, 200, 1280, 840) == (340, 178)


def test_a_long_menu_rises_to_fit():
    x, y = glow.clamp_popup(340, 178, 150, 760, 1280, 840)
    assert (x, y) == (340, 840 - glow.POPUP_PAD - 760)


def test_one_taller_than_the_window_starts_at_its_top():
    assert glow.clamp_popup(340, 178, 150, 2000, 1280, 840)[1] == glow.POPUP_PAD


def test_one_past_the_right_edge_moves_left():
    assert glow.clamp_popup(1200, 100, 150, 100, 1280, 840)[0] == 1280 - glow.POPUP_PAD - 150


if __name__ == "__main__":
    import inspect
    bad = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and inspect.isfunction(fn):
            try:
                fn(); print("ok  ", name)
            except Exception as e:
                bad += 1; print("FAIL", name, repr(e))
    sys.exit(1 if bad else 0)
