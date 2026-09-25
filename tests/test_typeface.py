"""The interface's type and size without a window (native/typeface.py): the
scale from the prefs or the monitor, clamped and stepped; px(); the
faces this platform has; and the prefs keeping the 3-D view's and the
panel's sizes at 100%, so a size change keeps their proportion.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from native import typeface                         # noqa: E402


def _at(pct):
    typeface._scale = None
    typeface._scale = typeface._clamp(pct / 100.0)
    return typeface.scale()


def test_the_scale_is_clamped_and_stepped():
    assert typeface._clamp(0.5) == 0.8 and typeface._clamp(3.0) == 2.0
    assert typeface._clamp(1.26) == 1.25 and typeface._clamp(1.49) == 1.5      # to 5%
    prefs = {}
    assert typeface.set_scale(prefs, 137) == 135 and prefs["ui_scale"] == 135
    assert typeface.set_scale(prefs, 20) == 80


def test_px_is_the_size_at_the_scale():
    try:
        assert _at(100) == 1.0 and typeface.px(340) == 340
        assert _at(150) == 1.5 and typeface.px(340) == 510 and typeface.px(13) == 20
        assert _at(80) == 0.8 and typeface.px(10) == 8
    finally:
        typeface._scale = None


def test_the_monitor_scale_is_read():
    s = typeface.monitor_scale()
    assert 0.5 <= s <= 4.0, s


def test_the_faces_are_here():
    """The platform's interface face and monospace exist where the studio
    looks (a release runs on Windows; the others fall back)."""
    if sys.platform != "win32":
        return
    for role in ("body", "bold", "mono"):
        assert typeface._pick(role), role


def test_the_body_reads_as_large_as_the_monospace():
    """Dear ImGui's sizes are line heights: Segoe UI's line is 1.33 of its
    em, Consolas' 1.0, so at one "size" the interface's face drew a fifth
    smaller than the code beside it (and than the bitmap face it replaced).
    The roles are set so the body's x-height is the monospace's, within a
    tenth, and each role reads smaller or larger than the next as meant."""
    if sys.platform != "win32":
        return
    from PIL import ImageFont

    def x_height(face, size):
        path = typeface._pick(face)
        big = ImageFont.truetype(path, 1000)
        line = sum(big.getmetrics()) / 1000.0
        bb = ImageFont.truetype(path, size / line * 10).getbbox("x")      # at ten times, for the precision
        return (bb[3] - bb[1]) / 10.0

    body = x_height("body", typeface.SIZES["body"])
    mono = x_height("mono", typeface.SIZES["mono"])
    assert 0.9 <= body / mono <= 1.1, (body, mono)
    assert x_height("body", typeface.SIZES["small"]) < body < x_height("bold", typeface.SIZES["heading"])
    assert body >= 5.8, f"the body's x-height is {body:.1f} px at 100% - the platform's 9 pt is 6"


def test_measure_is_what_dear_pygui_draws():
    """typeface.measure - text placed before a frame has built the atlas
    (the graph's right-aligned pin names, its readouts) - against
    dpg.get_text_size after one, in all three faces at several sizes."""
    if sys.platform != "win32":
        return
    import dearpygui.dearpygui as dpg
    cases = [(face, size, text) for face in ("body", "bold", "mono") for size in (7, 11, 13, 16, 20)
             for text in ("scale", "out_hi", "ON THE DEVICE", "a Wave's period", "0.12345 Hz", "LEDs/s")]
    dpg.create_context()
    try:
        fonts = {(f, s): typeface.at(f, s) for f, s, _ in cases}
        dpg.create_viewport(title="measure", width=200, height=120, x_pos=-4000, y_pos=0)
        dpg.setup_dearpygui()
        with dpg.window():
            dpg.add_text("x")
        dpg.show_viewport()
        for _ in range(3):
            dpg.render_dearpygui_frame()
        bad = []
        for f, s, t in cases:
            real = dpg.get_text_size(t, font=fonts[(f, s)])[0]
            est = typeface.measure(t, f, s)
            if abs(real - est) > 1.0:
                bad.append(f"{f} {s} {t!r}: dpg {real}, measure {est:.2f}")
        assert not bad, "\n".join(bad)
    finally:
        typeface._at.clear()
        dpg.destroy_context()


def test_sizes_in_the_prefs_are_kept_at_100():
    """The 3-D view's side and the panel's width go into the prefs at 100%
    (room.py, app.py): read back at another size they keep their share."""
    src_room = open(os.path.join(ROOT, "native", "room.py"), encoding="utf-8").read()
    src_app = open(os.path.join(ROOT, "native", "app.py"), encoding="utf-8").read()
    assert "px(pip(app)[\"size\"])" in src_room and "def _set_side(" in src_room
    assert 'self.prefs["side_w"] = int(round(self.side_w / typeface.scale()))' in src_app


if __name__ == "__main__":
    import inspect
    bad = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and inspect.isfunction(fn):
            try:
                fn(); print("ok  ", name)
            except Exception as ex:
                bad += 1; print("FAIL", name, str(ex)[:3000])
    sys.exit(1 if bad else 0)
