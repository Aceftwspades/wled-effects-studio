"""The studio's theme as data: the seven colour roles, the presets, the colours in force for the prefs, light or
dark, and the graph minimap's colours from them. Kept out of app.py so the panels that need them do not import
app.py - run as __main__, a second copy of it."""
import dearpygui.dearpygui as dpg


# The theme is seven colours. The presets are starting points; Settings >
# Appearance edits any of them and keeps the result (prefs["theme"]).
THEME_ROLES = (("bg", "background", "behind everything"),
               ("panel", "panels", "the panes and dialogs"),
               ("frame", "controls", "boxes, sliders, nodes"),
               ("line", "lines", "borders and separators"),
               ("text", "text", "what you read"),
               ("dim", "dim text", "hints and secondary text"),
               ("accent", "accent", "whatever is on: checks, grabs, the active view"))
THEME_PRESETS = {
    "dark":       {"bg": (14, 16, 20), "panel": (21, 24, 30), "frame": (29, 33, 41), "line": (36, 41, 50),
                   "text": (222, 226, 234), "dim": (128, 137, 152), "accent": (90, 169, 230)},
    "light":      {"bg": (232, 234, 238), "panel": (246, 247, 249), "frame": (222, 225, 231), "line": (200, 205, 214),
                   "text": (30, 34, 42), "dim": (110, 118, 132), "accent": (60, 130, 200)},
    "soft light": {"bg": (196, 200, 208), "panel": (214, 218, 225), "frame": (188, 194, 204), "line": (166, 173, 186),
                   "text": (28, 32, 40), "dim": (92, 100, 116), "accent": (50, 120, 190)},
    "slate":      {"bg": (30, 34, 42), "panel": (38, 43, 53), "frame": (48, 54, 66), "line": (58, 65, 79),
                   "text": (220, 224, 232), "dim": (140, 148, 164), "accent": (110, 190, 170)},
}


def theme_colors(prefs=None):
    """The seven colours in force: the preset (light / dark, or a named
    one), then any the editor changed."""
    t = (prefs or {}).get("theme") or {}
    name = t.get("preset") or ("light" if t.get("light") else "dark")
    cols = dict(THEME_PRESETS.get(name) or THEME_PRESETS["dark"])
    for k, v in (t.get("colors") or {}).items():
        if k in cols and isinstance(v, (list, tuple)) and len(v) >= 3:
            cols[k] = tuple(int(c) for c in v[:3])
    if t.get("accent") and not (t.get("colors") or {}).get("accent"):
        cols["accent"] = tuple(int(c) for c in t["accent"][:3])          # the older setting
    return cols


def theme_is_light(prefs=None):
    """Light or dark, by the background: it decides which way controls lift."""
    bg = theme_colors(prefs)["bg"]
    return (bg[0] + bg[1] + bg[2]) / 3 > 128


def minimap_colours(prefs=None, faint=False):
    """The graph's minimap: a slab of the canvas, the nodes as nodes, the
    view in the accent - or, faint, the same as a trace over the graph, as
    it is drawn until the pointer comes to its corner (graph_ui). Pairs of
    (Dear PyGui colour, RGBA)."""
    cols = theme_colors(prefs)
    light = theme_is_light(prefs)
    bg, frame, line, dim, accent = (tuple(cols[k]) for k in ("bg", "frame", "line", "dim", "accent"))
    lift = (lambda c, k: tuple(min(255, v + k) for v in c)) if not light else (lambda c, k: tuple(max(0, v - k) for v in c))
    # (colour, the alpha drawn full, the alpha drawn faint)
    rows = ((dpg.mvNodesCol_MiniMapBackground, lift(bg, 6), 225, 40),
            (dpg.mvNodesCol_MiniMapBackgroundHovered, lift(bg, 10), 240, 240),
            (dpg.mvNodesCol_MiniMapOutline, line, 255, 60),
            (dpg.mvNodesCol_MiniMapOutlineHovered, lift(line, 24), 255, 255),
            (dpg.mvNodesCol_MiniMapNodeBackground, lift(frame, 14), 255, 80),
            (dpg.mvNodesCol_MiniMapNodeBackgroundHovered, lift(frame, 28), 255, 255),
            (dpg.mvNodesCol_MiniMapNodeBackgroundSelected, accent, 255, 140),
            (dpg.mvNodesCol_MiniMapNodeOutline, lift(frame, 30), 255, 70),
            (dpg.mvNodesCol_MiniMapLink, dim, 190, 50),
            (dpg.mvNodesCol_MiniMapLinkSelected, accent, 255, 110),
            (dpg.mvNodesCol_MiniMapCanvas, accent, 28, 8),
            (dpg.mvNodesCol_MiniMapCanvasOutline, accent, 200, 90))
    return [(t, tuple(c[:3]) + ((af if faint else a),)) for t, c, a, af in rows]
