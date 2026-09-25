"""The interface's type and size (the critique's C2).

The studio was set in Dear PyGui's built-in 13-px bitmap face, a
debugging font with Latin-1 and nothing else, at one size. It is set now
in the platform's interface face (Segoe UI, Helvetica or DejaVu Sans) in
five roles - a heading for a frame's title, a label for the capitals over
a group of controls, the body, small print for captions, and a monospace
for code, figures and field values (Consolas, Menlo or DejaVu Sans Mono).

The sizes are Dear ImGui's, which are line heights, not ems: Segoe UI's
line is 1.33 of its em, so "14" drew a 10.5-px em, smaller than the
bitmap face it replaced and than Consolas beside it. The body is 16, the
platform's own 9 pt (a 12-px em); Consolas' line is its em, so 13 matches
it, x-height for x-height.

And at a size: Settings > Appearance > Interface size, 80-200%, first
taken from the monitor's own scale. The process says it is DPI aware, so
Windows no longer stretches a 100% picture over a 150% screen (blurred);
the studio draws at the size instead. Every size in the interface is
laid out at 100% and passes through px():

    dpg.add_combo(..., width=px(200))

A size change takes a restart: the faces are made once, and so is every
control. The graph keeps its own zoom (its faces at() the zoomed sizes),
the pictures their own pixels.
"""
import os
import sys

import dearpygui.dearpygui as dpg

# role: (face, size at 100% - a Dear ImGui size, the line's height)
ROLES = {
    "body": ("body", 16),        # everything that says nothing else
    "small": ("body", 14),       # captions: a count, a size, a key beside what it belongs to
    "label": ("bold", 14),       # the capitals over a group of controls (STEPS, ON THE DEVICE)
    "heading": ("bold", 20),     # a frame's title
    "mono": ("mono", 13),        # code, logs, figures that change as you watch, field values
}
SIZES = {role: size for role, (_, size) in ROLES.items()}
MIN, MAX = 0.8, 2.0

_FILES = {
    "win32": {"body": [r"C:\Windows\Fonts\segoeui.ttf"], "bold": [r"C:\Windows\Fonts\seguisb.ttf", r"C:\Windows\Fonts\segoeuib.ttf"],
              "mono": [r"C:\Windows\Fonts\consola.ttf", r"C:\Windows\Fonts\cour.ttf"]},
    "darwin": {"body": ["/System/Library/Fonts/Helvetica.ttc", "/Library/Fonts/Arial.ttf"],
               "bold": ["/System/Library/Fonts/Helvetica.ttc", "/Library/Fonts/Arial Bold.ttf"],
               "mono": ["/System/Library/Fonts/Menlo.ttc", "/System/Library/Fonts/Monaco.ttf"]},
}
_LINUX = {"body": ["/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/TTF/DejaVuSans.ttf",
                   "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf"],
          "bold": ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf"],
          "mono": ["/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", "/usr/share/fonts/TTF/DejaVuSansMono.ttf",
                   "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf"]}

_scale = None
_fonts = {}          # role -> font, at the interface size
_at = {}             # (face, px) -> font, for the graph's zoom
_metrics = {}        # (face, px) -> the face in Pillow, for measuring; (face, "line") -> its line per em


def monitor_scale():
    """The primary monitor's own scale (1.0 at 96 DPI), where the platform
    says; 1.0 where it does not."""
    if os.name == "nt":
        try:
            import ctypes
            pct = ctypes.windll.shcore.GetScaleFactorForDevice(0)       # 100, 125, 150...
            if pct and pct > 0:
                return pct / 100.0
        except Exception:
            pass
    return 1.0


def _clamp(s):
    return max(MIN, min(MAX, round(float(s) * 20) / 20.0))      # to 5%


def scale():
    """The interface size in force (1.0 is 100%): the prefs' ui_scale (a
    percentage), else the monitor's. Fixed for the run."""
    global _scale
    if _scale is None:
        pct = None
        try:
            from native.project import load_prefs
            pct = load_prefs().get("ui_scale")
        except Exception:
            pass
        _scale = _clamp((pct / 100.0) if isinstance(pct, (int, float)) and pct > 0 else monitor_scale())
    return _scale


def set_scale(prefs, pct):
    """The interface size for the next start (a restart applies it)."""
    prefs["ui_scale"] = int(round(_clamp(pct / 100.0) * 100))
    return prefs["ui_scale"]


def px(n):
    """A size laid out at 100%, at the interface size."""
    return int(round(n * scale()))


def dpi_aware():
    """Before the window is made: draw at the monitor's size rather than be
    stretched to it (Windows; elsewhere the platform does it)."""
    if os.name != "nt":
        return False
    try:
        import ctypes
        try:
            return ctypes.windll.shcore.SetProcessDpiAwareness(2) == 0      # per monitor
        except Exception:
            return bool(ctypes.windll.user32.SetProcessDPIAware())
    except Exception:
        return False


def _pick(face):
    files = _FILES.get(sys.platform, _LINUX)
    return next((f for f in files[face] if os.path.exists(f)), None)


def size_of(role):
    """A role's size at the interface size, px."""
    return px(ROLES[role][1])


def fonts():
    """{role: font} at the interface size, made once; a missing face is
    None (the built-in one stands in)."""
    if _fonts:
        return _fonts
    for role, (face, _) in ROLES.items():
        _fonts[role] = at(face, size_of(role))
    return _fonts


def font(role):
    return fonts().get(role)


def at(face, size):
    """A face ("body", "bold", "mono") at a size in px, made once: what the
    graph sets its nodes in at its zoom. None when the face is missing."""
    size = max(6, int(round(size)))
    key = (face, size)
    if key not in _at:
        f, path = None, _pick(face)
        if path:
            try:
                with dpg.font_registry():
                    f = dpg.add_font(path, size)
            except Exception:
                f = None
        _at[key] = f
    return _at[key]


def _measurer(face, size):
    """The face in FreeType at the em that makes Dear ImGui's size (a
    line's height: Segoe UI's line is 1.33 em), hinted as it is: the same
    glyph advances, to the pixel (checked against dpg.get_text_size at
    ten sizes in all three faces). None when the face or Pillow is missing."""
    key = (face, size)
    if key in _metrics:
        return _metrics[key]
    f, path = None, _pick(face)
    if path:
        try:
            from PIL import ImageFont
            line = _metrics.get((face, "line"))
            if line is None:
                a, d = ImageFont.truetype(path, 1000).getmetrics()
                line = _metrics[(face, "line")] = float(a + d) / 1000.0
            f = ImageFont.truetype(path, size / line)
        except Exception:
            f = None
    _metrics[key] = f
    return f


def measure(text, face="body", size=None):
    """How wide `text` is drawn in a face at a size (px; the body's at the
    interface size when none is given), as Dear ImGui sets it - also before
    a frame has built the font atlas, which dpg.get_text_size needs."""
    if size is None:
        size = size_of("body")
    size = max(6, int(round(size)))
    f = _measurer(face, size)
    if f is None:
        return len(text) * size * (0.6 if face == "mono" else 0.5)
    return float(f.getlength(text))


def advance(face="body", size=None):
    """A character's advance in a face at a size (the body's at the
    interface size when none is given), px, remembered: what reader.wrap_lines
    takes to wrap a text as Dear ImGui will, before it is drawn."""
    if size is None:
        size = size_of("body")
    known = {}

    def adv(ch):
        w = known.get(ch)
        if w is None:
            w = known[ch] = measure(ch, face, size)
        return w
    return adv


def draw_text(pos, text, size, face="body", **kw):
    """Text drawn on a drawlist in a face made at its size: drawn text takes
    only the font bound to it (not its drawlist's), and a face scaled from
    another size is soft. Words in "body", figures in "mono"."""
    t = dpg.draw_text(pos, text, size=size, **kw)
    f = at(face, size)
    if f is not None:
        dpg.bind_item_font(t, f)
    return t


def bind():
    """The body face for everything that says nothing else."""
    f = font("body")
    if f:
        dpg.bind_font(f)
    return f


def use(role, item):
    """An item set in a role's face (see ROLES); the item back, so it wraps
    the call that made it: typeface.use("label", dpg.add_text("STEPS"))."""
    f = font(role)
    if f and item is not None and dpg.does_item_exist(item):
        dpg.bind_item_font(item, f)
    return item


def mono(item):
    """Code, a log, figures that change as you watch, a field's value."""
    return use("mono", item)


def small(item):
    """A caption: a count, a size, a key, beside what it belongs to."""
    return use("small", item)


def label(item):
    """The capitals over a group of controls."""
    return use("label", item)


def heading(item):
    """A frame's title."""
    return use("heading", item)
