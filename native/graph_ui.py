"""
The node editor panel: Dear PyGui's node editor over native/graph.py.

Every widget carries user_data naming what it is - (node id, pin name) on a
pin, (node id, param name) on a param - so the callbacks never have to parse
tags. The Graph object is the truth; the widgets are a view of it, rebuilt
whole on open and edited in place otherwise. Positions are read back from the
editor on save.
"""
import json
import os
import time

import dearpygui.dearpygui as dpg

from native.typeface import px
from native import typeface
from native import num
from native import messages

import numpy as np

from native import graph as G
from native import nodeface
from native.glyphs import Glyphs
from native.graph_files import GraphFiles
from native.graph_costs import GraphCosts
from native.graph_menu import GraphMenu
from native.graph_props import GraphProps
from native.nodedefs import library
from native import oops

DIM = (139, 147, 163)
PIN_COL = {"vector": (190, 120, 235),"float": (110, 190, 250), "color": (250, 170, 90), "bool": (170, 230, 120)}
GREY = (70, 74, 84)
NODE_W = 150            # inner width every node is laid out to
WIRE_COLOURS = [("type colour", None), ("white", (235, 235, 235)), ("red", (235, 80, 70)),
                ("orange", (250, 160, 60)), ("yellow", (240, 220, 80)), ("green", (120, 220, 110)),
                ("cyan", (90, 220, 230)), ("blue", (100, 150, 250)), ("magenta", (230, 100, 220)),
                ("grey", (130, 135, 145))]
CHAR_W = 7.2            # Consolas at 13 px: a fallback measure when no face is found
WIRE_FADE = 0.22        # while a node's wires are lit, every other wire keeps this much of its colour
WIRE_LIT = 1.6          # and a lit wire is this much thicker
_STALE = object()       # the wires' lit set not applied (a rebuild, focus mode off): the next poll applies it
# The app theme's minimap colour items, by Dear PyGui colour (app.apply_theme
# fills it): set in place for a faint or a full minimap. Kept here, not in
# app.py - the app runs as __main__, and native.app imported from another
# module is a second copy whose state the running app never filled.
MINIMAP_ITEMS = {}


def minimap_faint(prefs, faint):
    """The minimap drawn faint or full: the app theme's colours for it set
    in place (a theme bound to the node editor does not reach imnodes'
    minimap; set_value on the app theme's items does, the next frame)."""
    from native.theme import minimap_colours
    for t, c in minimap_colours(prefs, faint):
        it = MINIMAP_ITEMS.get(t)
        if it is not None and dpg.does_item_exist(it):
            dpg.set_value(it, c)


NARROW_W = 46           # a knot: just wide enough for its two pin names
ZOOMS = (0.1, 0.15, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.85, 1.0, 1.2, 1.4, 1.7, 2.0)
OVERVIEW_ZOOM = 0.5     # below this the nodes are stand-ins (Settings > Simplified nodes below)
OVERVIEW_CHOICES = ((0.7, "70%"), (0.5, "50%"), (0.4, "40%"), (0.3, "30%"), (0.0, "never"))
BASE_FONT = 13          # a field's value, in the monospace, at 100% zoom
NODE_TEXT = 16          # a node's words - title, pin names, summary - in the interface's face (its body size)
# the fields whose text is a value (set in the monospace); a combo, a checkbox, a swatch show words
VALUE_ITEMS = ("mvAppItemType::mvSliderFloat", "mvAppItemType::mvSliderInt", "mvAppItemType::mvDragFloat",
               "mvAppItemType::mvInputInt", "mvAppItemType::mvInputFloat", "mvAppItemType::mvInputText",
               "mvAppItemType::mvInputFloatMulti", "mvAppItemType::mvDragFloatMulti")
HELP_H = 46             # the description box, px: two lines
THUMB = 96              # the preview thumbnail on a node, layout px
PAD = 56                # an XY pad on a node, layout px (its texture is PAD_PX square)
PAD_PX = 56
THUMB_PX = 96           # its texture


def _right(text_w, width=NODE_W):
    """Indent that puts a text `text_w` wide against the node's right edge,
    so an output's name sits beside its pin on the right the way an input's
    sits beside its pin on the left. Inputs left, outputs right, on every
    node. The width is measured (typeface.measure): the face is proportional."""
    return max(0, int(width - text_w + 0.999))


def _font_file():
    """A monospace TTF the platform is likely to have, for the zoomed
    fonts; None means text stays at 13 px while the boxes still scale."""
    import sys
    cands = {
        "win32":  [r"C:\Windows\Fonts\consola.ttf", r"C:\Windows\Fonts\cour.ttf", r"C:\Windows\Fonts\segoeui.ttf"],
        "darwin": ["/System/Library/Fonts/Menlo.ttc", "/System/Library/Fonts/Monaco.ttf", "/Library/Fonts/Courier New.ttf"],
    }.get(sys.platform, ["/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
                         "/usr/share/fonts/TTF/DejaVuSansMono.ttf", "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf",
                         "/usr/share/fonts/truetype/noto/NotoSansMono-Regular.ttf"])
    for c in cands:
        if os.path.exists(c):
            return c
    return None


from native.graph import compatible          # the one rule for what may feed what
from native.graph_addmenu import GraphAddMenu
from native.graph_actions import GraphActions
from native.graph_fieldkit import GraphFieldKit
from native.graph_overlays import GraphOverlays
from native.graph_problems import GraphProblems
from native.graph_subs import GraphSubs


class PinThemes:
    """One theme per pin type, lit and greyed, and one per link type. Built
    once; bound to attributes and links so the wires are the colour of what
    flows through them and a pin that cannot take the drag goes grey."""
    def __init__(self, light=False):
        # on a light node body the type colours are too pale to read as text,
        # and a little pale as wires: the text darkened, the wires a touch
        self.pin, self.grey, self.link = {}, {}, {}
        for t, col in PIN_COL.items():
            text = tuple(int(c * 0.55) for c in col) if light else col
            wire = tuple(int(c * 0.8) for c in col) if light else col
            self.pin[t] = self._attr_theme(col, text)
            self.grey[t] = self._attr_theme(GREY, GREY)
            with dpg.theme() as th:
                with dpg.theme_component(dpg.mvNodeLink):
                    dpg.add_theme_color(dpg.mvNodeCol_Link, wire, category=dpg.mvThemeCat_Nodes)
                    dpg.add_theme_color(dpg.mvNodeCol_LinkHovered, (255, 255, 255), category=dpg.mvThemeCat_Nodes)
                    dpg.add_theme_color(dpg.mvNodeCol_LinkSelected, (255, 255, 255), category=dpg.mvThemeCat_Nodes)
            self.link[t] = th

    @staticmethod
    def _attr_theme(pin, text):
        with dpg.theme() as th:
            with dpg.theme_component(dpg.mvNodeAttribute):
                dpg.add_theme_color(dpg.mvNodeCol_Pin, pin, category=dpg.mvThemeCat_Nodes)
                dpg.add_theme_color(dpg.mvNodeCol_PinHovered, (255, 255, 255), category=dpg.mvThemeCat_Nodes)
            with dpg.theme_component(dpg.mvText):
                dpg.add_theme_color(dpg.mvThemeCol_Text, text, category=dpg.mvThemeCat_Core)
        return th


class GraphPanel(GraphSubs, GraphProblems, GraphOverlays, GraphFieldKit, GraphActions, GraphAddMenu, Glyphs, GraphFiles, GraphCosts, GraphMenu, GraphProps):
    def __init__(self, app):
        self.app = app
        self.lib = library(self._user_nodes())
        self.graph = None
        self.file = None
        self.cur_dir = None      # graphs/ or subgraphs/ - where `file` lives
        self.stack = []          # (dir, file) to return to from a sub-graph
        self._subs = {}          # ident -> Graph, loaded on demand
        self.links = {}          # dpg link id -> (b, inp)
        self._pins = {}          # (node, "in"/"out", name) -> attribute tag
        self._ptype = {}         # attribute tag -> pin type
        self._add_count = 0
        self._themes = None      # PinThemes, built lazily (needs a context)
        self._wire_themes = {}   # (r,g,b) -> a link theme in that colour
        self._ctx = None         # what the context menu is about: ("in"|"out"|"node", ...)
        self._undo = []          # JSON snapshots of the graph before each edit
        self._redo = []
        self._last_snap = None   # (key, time) of the last snapshot, to coalesce slider drags
        self._widgets = set()    # every value widget on a node, so keys know when one is typed in
        self._pads = {}          # image button -> (nid, a, b, lo, hi, texture): the XY pads on the nodes
        self._field_themes = {}  # (frame, accent, light) -> the theme a node's value fields wear
        self._glyph_init()       # the glyphs' live state and the probes' history (glyphs.py)
        self._pad_stroke = None  # the pad being dragged, for one undo step a stroke
        # --- zoom ---------------------------------------------------------------------
        # The node editor cannot zoom, so the panel does: every size it lays
        # nodes out with is multiplied by `zoom`, positions included, and the
        # editor gets a font and a style theme scaled to match. Stored node
        # positions never change with zoom; `offset` (graph units) shifts the
        # whole picture so the point under the cursor stays put, since the
        # editor's own panning cannot be set from code - only watched, which
        # `pan` does, through the middle-mouse drags that move it.
        self.zoom = 1.0
        self.offset = [0.0, 0.0]
        self.pan = [0.0, 0.0]
        self._mid_last = None
        self._node_font = None   # the node's words at this zoom, bound to each node as it is made
        self._val_font = None    # a field's value at this zoom (the monospace)
        self._standin_line = {}  # nid -> the height a stand-in gives its summary line (0: none)
        self._node_w = {}        # nid -> the width its node is laid out to at this zoom (_fit_title)
        self._font_file = _font_file()
        self._zoom_themes = {}   # zoom -> node-editor style theme
        self._node_themes = {}   # (r,g,b) -> a node theme with that title bar
        self.focus_mode = False  # dim everything but the selection and its neighbours
        self.edits = 0           # bumped by touch(); what the autosave watches
        self._focus_sel = None
        self._link_normal = {}   # dpg link id -> the theme it wears when not dimmed
        self._link_style = {}    # dpg link id -> (its colour, thin): what its lit and faded themes are made from
        self._wires_lit = _STALE # the wires (b, inp) lit now - a node's under the pointer and the selection's - or None
        self._wires_at = 0.0
        self._hover_cache = (0.0, None)
        self._mini_faint = True  # the minimap drawn faint: the pointer is not at its corner
        self._mini_applied = None  # (faint, the theme's colour item) last set: set again when either changes
        self._mini_corner = "br"
        self._mini_at = 0.0
        self._label_items = []   # the wire labels drawn last frame
        self._readout_items = [] # the live readouts drawn last frame, on the frame-scope output pins
        self._depth = []         # node ids in imnodes' drawing order, the last on top (_raise, _covered)
        self._scope_cache = None # (edits, {nid: scope}) - the plan's scopes for the graph as it is now
        self._mark_themes = {}   # "error"/"warn" -> outline theme
        self.problems = {}       # node id -> message, from the last rebuild
        self.preview = None      # (node, output) routed to Output instead of the graph's own
        self._frame_last = {}    # frame node -> its position last poll
        self._frame_drag = {}    # frame node -> the nodes moving with it, while it moves
        # Selected by key (A, Ctrl+[, ...): imnodes owns the click selection
        # and cannot be told to select, so these wear an outline of their
        # own and are moved along when a clicked one is dragged.
        self.ext_sel = []
        self._ext_last = {}      # node -> its position last poll, while ext_sel has nodes
        self._knife = None       # (x0, y0) while a Ctrl+right-drag cuts wires
        self._splice = None      # (node, link, a, out, b, inp, my_in, my_out) while a dragged node sits over a wire
        self._add_preview = None # the node type the add menu is describing, in its column beside the list
        self._menu_entries_cache = None
        self._press_pos = {}     # node -> position at the last press (a drop onto a wire)
        self._undo_desc = []     # what each undo snapshot precedes
        self.auto = bool(app.prefs.get("live", True))    # Live: rebuild after every edit - on unless turned off (kept)
        self._dirty = 0.0        # time of the last edit not yet built, 0 when clean
        self._queued = False     # a build asked for while one was running: made when it lands (poll)
        # the edit at once (standin): the effect file the script stands in for, its bytecode, the
        # edit it was tried at and the one it shows, the edit the build in hand was made from, and
        # (file, bytecode) of what is on screen when that is known - a build that took the stand-in's place
        self._standin_for = None
        self._standin_prog = b""
        self._standin_at = -1
        self._standin_shows = -1
        self._built_at = -1
        self._shown = None
        self._drag_type = None   # type of the output being dragged, if any
        self._drag_from = None   # (node, output) being dragged, for a drop on empty space
        self._press_at = (0, 0)
        self._pending = None     # (node, output, type): the new node gets wired from here
        self._menu_pos = (60, 60)

    # --- files -------------------------------------------------------------------
    @property
    def dir(self):
        d = os.path.join(self.app.project.path, "graphs")
        os.makedirs(d, exist_ok=True)
        return d

    def _user_nodes(self):
        out = []
        d = os.path.join(self.app.project.path, "nodes")
        if os.path.isdir(d):
            import json
            for f in sorted(os.listdir(d)):
                if f.endswith(".json"):
                    try:
                        out.append(json.load(open(os.path.join(d, f), encoding="utf-8")))
                    except Exception as e:
                        print(f"user node {f}: {e}")
        return out

    @property
    def sub_dir(self):
        d = os.path.join(self.app.project.path, "subgraphs")
        os.makedirs(d, exist_ok=True)
        return d

    def files(self):
        return sorted(f for f in os.listdir(self.dir) if f.endswith(".json"))

    def sub_files(self):
        return sorted(f for f in os.listdir(self.sub_dir) if f.endswith(".json"))

    # --- help: what is under the pointer ---------------------------------------------
    # A tooltip inside a node crashes the node editor, so the help is a
    # line of its own under the pane's row: hover a pin and it names the pin
    # and says what to plug in or what comes out; hover a node's title and
    # it says what the node is for. Checked a few times a second.
    def help(self, text):
        if dpg.does_item_exist("graph_help") and dpg.get_value("graph_help") != text:
            dpg.set_value("graph_help", text)

    # --- properties: the selected node's settings and typed inputs, and its long text ----
    PROP_KINDS = ("float", "int", "choice", "color", "text", "file", "bool", "ramp", "curve")

    def editable(self, nid):
        """(settings, typed inputs) a node's properties can set: its settings,
        and its inputs with a value of their own - not wired. Both empty for a
        node with neither (Time, Pixel...)."""
        n = self.graph.nodes.get(nid) if self.graph else None
        if n is None:
            return [], []
        try:
            d = self.graph.node_def(n)
        except G.GraphError:
            return [], []                                 # a type that is not there (its file gone): nothing to set
        wired = {l[3] for l in self.graph.links if l[2] == nid}
        params = [p for p in d.get("params", []) if p["type"] in self.PROP_KINDS]
        inputs = [i for i in d.get("inputs", []) if i["name"] not in wired and i["type"] in ("float", "bool", "vector", "color")
                  and self.pin_read(n, i)]                 # not one the operation leaves unread (Math's b for sqrt)
        return params, inputs

    def _mirror(self, sender, nid, name, val, pads=True):
        """An edit shown everywhere the value is: on the node and in its
        properties (both are fields of (nid, name)), the one edited left alone
        - and any XY pad drawn from it. A setting kept as rows ("/" between
        them: a Bitmap's) is shown a row a line."""
        n = self.graph.nodes.get(nid) if self.graph else None
        spec = next((p for p in self.graph.node_def(n)["params"] if p["name"] == name), None) if n else None
        shown = val.replace("/", "\n") if spec and spec.get("lines") and isinstance(val, str) else val
        if n and name in (n.get("inputs") or {}) and name in ((self.graph.node_def(n).get("implicit")) or {}):
            self._typed_fields(nid, name)               # it read the pixel until now (the one edited too)
        for w in list(self._widgets):
            if w != sender and dpg.does_item_exist(w) and dpg.get_item_user_data(w) == (nid, name):
                self._show_value(w, shown)
        for btn, pad in list(self._pads.items()) if pads else ():
            if pad[0] == nid and name in (pad[1], pad[2]):
                self._pad_draw(btn)

    def _poll_help(self):
        now = time.time()
        if now - getattr(self, "_help_at", 0.0) < 0.15:
            return
        self._help_at = now
        if not self.graph or not dpg.does_item_exist("node_editor") or not dpg.is_item_shown("node_editor"):
            return
        if not dpg.is_item_hovered("node_editor") or now < getattr(self, "_help_hold", 0.0):
            return                                    # (a hold: the tests' hover, which has no pointer)
        for (nid, kind, name), tag in self._pins.items():
            if dpg.does_item_exist(tag) and dpg.is_item_hovered(tag):
                if nid in self.graph.nodes:
                    self.hover_pin(kind, nid, name)
                return
        if now > getattr(self, "_hover_hold", 0.0):
            self._hover_out = None
        for nid, n in self.graph.nodes.items():
            tag = f"gnode_{nid}"
            if dpg.does_item_exist(tag) and dpg.is_item_hovered(tag):
                d = self.graph.node_def(n)
                note = G.feature_note(d.get("needs"), self.graph.features if hasattr(self.graph, "features") else None)
                text = self.summary(nid)
                self.help((f"[{note}]  " if note else "") + f"{d.get('label') or n['type']}"
                          + (f"  [{text}]" if text else "") + f": {d.get('doc', '')}")
                return
        self.help("")

    def hover_pin(self, kind, nid, name, hold=0.0):
        """The help for a pin under the pointer, and - for a frame-scope
        output - its plot beside the pin for as long as it is hovered
        (`hold` seconds at least: the test hook has no pointer)."""
        n = self.graph.nodes[nid]
        d = self.graph.node_def(n)
        pins = d["inputs"] if kind == "in" else d["outputs"]
        p = next((x for x in pins if x["name"] == name), None)
        live = self.live_value(nid, kind, name)
        what = (p or {}).get("doc", "")
        arrow = "<-" if kind == "in" else "->"
        self._hover_out = (nid, name) if kind == "out" and (getattr(self, "_probe_scope", {}) or {}).get(nid) == "frame" else None
        self._hover_hold = time.time() + hold
        self.help(f"{d.get('label') or n['type']} {arrow} {nodeface.label(n['type'], name)} ({(p or {}).get('type', '')})"
                  + (f" = {live}" if live is not None else "") + (f": {what}" if what else ""))

    # --- build the widgets from the graph -----------------------------------------
    def themes(self):
        if self._themes is None:
            self._themes = PinThemes(self._light())
        return self._themes

    # --- colours for the theme in force ---------------------------------------------------
    def _light(self):
        from native.theme import theme_is_light
        return theme_is_light(self.app.prefs)

    @staticmethod
    def _tint(col, light):
        """A title bar's hue as it reads on the theme: dark hues under light
        text on a dark theme; the same hue mixed with white under dark text
        on a light one."""
        return tuple(int(c + (255 - c) * 0.55) for c in col[:3]) if light else tuple(col[:3])

    def pal(self):
        """What the graph draws with, for the theme in force: readouts,
        glyph lines and labels, plot boxes, the wire labels, the range bars.
        On a dark theme these are the colours they always were."""
        from native.theme import theme_colors
        cols = theme_colors(self.app.prefs)
        light = self._light()
        key = (tuple(cols["frame"]), tuple(cols["line"]), tuple(cols["text"]), tuple(cols["dim"]), tuple(cols["accent"]), light)
        if getattr(self, "_pal_key", None) != key:
            acc = tuple(cols["accent"])
            live = tuple(int(c * 0.8) for c in acc) if light else (110, 190, 250)
            self._pal_key = key
            self._pal = {
                "light": light,
                "live": live + (255,), "live_line": live + (220,),
                "text": tuple(cols["text"]) + (255,), "dim": tuple(cols["dim"]) + (255,),
                "soft": tuple(cols["dim"]) if light else (170, 178, 192),
                "plot_bg": tuple(cols["frame"]) + (220,), "plot_edge": tuple(cols["line"]) + (255,),
                "grid": tuple(cols["line"]) + (255,),
                "meter_bg": tuple(cols["line"]) + (255,),
                "mod": (130, 90, 200, 255) if light else (190, 150, 250, 255),
                "mod_text": (100, 80, 150, 255) if light else (150, 140, 190, 255),
                "mod_dot": (90, 60, 160, 255) if light else (240, 232, 255, 255),
                "popup": tuple(cols["panel"]) + (240,), "popup_edge": tuple(cols["line"]) + (255,),
                "point": tuple(cols["text"]) + (255,) if light else (255, 255, 255, 255),
                "cost_hot": (190, 120, 20, 255) if light else (240, 190, 70, 255),     # a node that costs a quarter of the frame
            }
        return self._pal

    def on_theme_change(self):
        """Settings > Appearance changed the theme: every theme made from its
        colours is made again, and the graph rebuilt so no widget keeps the
        old one (the value fields were left near-black on a light theme)."""
        self._themes = None
        self._node_themes.clear()
        self._wire_themes.clear()
        self._mini_applied = None                    # the minimap's colours are the new theme's: faint or full again
        self._pal_key = None
        if dpg.does_item_exist("graph_help"):
            dpg.configure_item("graph_help", color=self.pal()["soft"])
        self._rebind_cat_headers()
        if self.graph and dpg.does_item_exist("node_editor"):
            self._sync_pos()
            self.rebuild()

    def _rebind_cat_headers(self):
        """The add menu's category headers in the hues of the theme in force."""
        if not dpg.does_item_exist("graph_cats"):
            return
        on = self.app.prefs.get("cat_colours", True)
        for k in dpg.get_item_children("graph_cats", 1) or []:
            if dpg.does_item_exist(k) and dpg.get_item_type(k).endswith("CollapsingHeader"):
                cat = dpg.get_item_label(k)
                if cat in nodeface.CATEGORY_HUES:
                    dpg.bind_item_theme(k, self._cat_header_theme(cat) if on else 0)

    # --- undo / redo -----------------------------------------------------------------
    # Every edit first pushes the graph as JSON. Cheap - a graph is a few KB -
    # and it makes every mutation, however it was reached, undoable with one
    # line at the top of it. A slider or text param being dragged or typed
    # would push a snapshot per tick; edits to the same key within a second
    # share one, so undo steps back over the drag, not each pixel of it.
    UNDO_MAX = 200

    # --- zoom: sizes, coordinates -----------------------------------------------------------
    def px(self, v):
        """A layout size at the current zoom."""
        return int(round(v * self.zoom))

    def text_w(self, text):
        """How wide the node's words are drawn at this zoom, px."""
        if not self._font_file:
            return len(text) * CHAR_W
        return typeface.measure(text, "body", self._font_px())

    def _disp(self, pos):
        """Graph units -> the editor's grid, where nodes are placed."""
        return [(pos[0] + self.offset[0]) * self.zoom, (pos[1] + self.offset[1]) * self.zoom]

    def _graph(self, disp):
        return [disp[0] / self.zoom - self.offset[0], disp[1] / self.zoom - self.offset[1]]

    def editor_origin(self):
        """The node editor's top-left on the screen. Dear PyGui reports none
        for it (its rect_min reads 0, 0, so a pan measured against that took
        in the editor's own place, and Home put the graph's corner at the
        screen's (20, 20), over the rows above the canvas). It fills its pane
        to the bottom, less the pane's padding (the theme's 10), and its
        height is its own."""
        r = self.app._screen_rect("graph_win") if dpg.does_item_exist("graph_win") else None
        if not r or not dpg.does_item_exist("node_editor"):
            return (0.0, 0.0)
        eh = dpg.get_item_rect_size("node_editor")[1]
        return (r[0] + 10.0, r[3] - 10.0 - eh)

    def _measure_pan(self):
        """The editor's own panning, read off a node: where imnodes drew it
        against where it was placed. Counting middle-drags misses the
        editor's own moves (it pans itself when a node is dragged to an
        edge), and a wrong pan puts the zoom off the pointer."""
        if not self.graph or not dpg.does_item_exist("node_editor"):
            return
        ex, ey = self.editor_origin()
        for nid in self.graph.nodes:
            tag = f"gnode_{nid}"
            if not dpg.does_item_exist(tag):
                continue
            st = dpg.get_item_state(tag)
            if "rect_min" not in st or st["rect_min"] == [0, 0]:
                continue
            px, py = dpg.get_item_pos(tag)
            self.pan = [st["rect_min"][0] - ex - px, st["rect_min"][1] - ey - py]
            return

    def _to_graph(self, screen):
        """A screen point -> graph units, allowing for the editor's panning as
        far as it has been watched."""
        self._measure_pan()
        ex, ey = self.editor_origin()
        return self._graph([screen[0] - ex - self.pan[0], screen[1] - ey - self.pan[1]])

    def _font_px(self):
        """The node's words at this zoom, px: never under 6, nor under 8 for a
        stand-in's title while it is still to be read."""
        return max(8 if (self.overview() and self.zoom >= 0.3) else 6, int(NODE_TEXT * self.zoom)) if self._font_file else BASE_FONT

    def _value_px(self):
        """A field's value at this zoom, px."""
        return max(6, int(BASE_FONT * self.zoom)) if self._font_file else BASE_FONT

    def features(self):
        """The project's firmware features (flash.py): what the picker ticked."""
        from native import flash
        return flash.features_of(self.app.project)

    def _feature_off(self, type_):
        """True for a node type whose feature this project leaves out."""
        d = self.lib.get(type_) or {}
        return bool(G.feature_note(d.get("needs"), self.features()))

    def refresh_features(self):
        """The picker changed: the graph's marks and the add menu follow."""
        if self.graph:
            self.graph.features = self.features()
            self._mark_problems()
        self.fill_add_menu()

    def overview(self):
        """Zoomed out past the setting: the nodes are stand-ins - a title
        and the wired pins, no values - for finding your way, not editing."""
        return self.zoom < float(self.app.prefs.get("overview_zoom", OVERVIEW_ZOOM))

    def set_overview_zoom(self, z):
        self.app.prefs["overview_zoom"] = float(z)
        from native.project import save_prefs
        save_prefs(self.app.prefs)
        if self.graph:
            self._sync_pos(); self.rebuild()
        self.status("simplified nodes below " + (f"{int(z * 100)}%" if z else "- never"))

    def font_at(self, size, face="mono"):
        """A face at a size (made once, shared with the rest of the studio):
        drawn text takes the font bound to it. The graph's drawn figures are
        in the monospace; words (a wire's label) in the interface's face."""
        if not self._font_file:
            return None
        return typeface.at(face, size)

    def _draw_text(self, pos, text, size=13, face="mono", **kw):
        t = dpg.draw_text(pos, text, size=size, **kw)
        f = self.font_at(size, face)
        if f is not None:
            dpg.bind_item_font(t, f)
        return t

    def _font(self):
        """The node's words at this zoom (the interface's face). Never larger
        than the zoom asks for: text that outgrows the boxes widens every
        node, so 50% came out a little bigger than 50%. A 6 px font at the
        far end is for seeing the shape of a graph, not reading it;
        stand-ins keep 8 px so their titles still can be."""
        if not self._font_file:
            return None
        f = typeface.at("body", self._font_px())
        if f is None:
            self._font_file = None
        return f

    def _value_font(self):
        """A field's value at this zoom, in the monospace: figures that line
        up, and a changing one does not shift its neighbours."""
        return typeface.at("mono", self._value_px()) if self._font_file else None

    def _value_face(self, w):
        """A field whose text is a value, set in the monospace at the zoom."""
        f = getattr(self, "_val_font", None)
        if f is not None and w and dpg.does_item_exist(w) and dpg.get_item_type(w) in VALUE_ITEMS:
            dpg.bind_item_font(w, f)

    def _zoom_styles(self):
        """The styles the zoom scales, added to the theme component open
        now. Dear PyGui 2.3 does not hand an editor's theme (or font) down
        to its nodes, so every theme a node can wear - its colour, its
        category, dimmed, marked - carries these too, keyed by the zoom."""
        z = self.zoom
        dpg.add_theme_style(dpg.mvNodeStyleVar_NodePadding, 8 * z, 8 * z, category=dpg.mvThemeCat_Nodes)
        dpg.add_theme_style(dpg.mvNodeStyleVar_PinCircleRadius, 4 * z, category=dpg.mvThemeCat_Nodes)
        dpg.add_theme_style(dpg.mvNodeStyleVar_PinHoverRadius, 10 * z, category=dpg.mvThemeCat_Nodes)
        dpg.add_theme_style(dpg.mvNodeStyleVar_LinkThickness, 3 * z, category=dpg.mvThemeCat_Nodes)
        dpg.add_theme_style(dpg.mvNodeStyleVar_NodeCornerRounding, 4 * z, category=dpg.mvThemeCat_Nodes)
        dpg.add_theme_style(dpg.mvStyleVar_FramePadding, 4 * z, 3 * z, category=dpg.mvThemeCat_Core)
        dpg.add_theme_style(dpg.mvStyleVar_ItemSpacing, 8 * z, 4 * z, category=dpg.mvThemeCat_Core)
        dpg.add_theme_style(dpg.mvStyleVar_ItemInnerSpacing, 4 * z, 4 * z, category=dpg.mvThemeCat_Core)

    def _zoom_theme(self):
        z = self.zoom
        th = self._zoom_themes.get(z)
        if th is None:
            with dpg.theme() as th:
                with dpg.theme_component(dpg.mvNodeEditor):
                    dpg.add_theme_style(dpg.mvNodeStyleVar_GridSpacing, 24 * z, category=dpg.mvThemeCat_Nodes)
                with dpg.theme_component(dpg.mvAll):
                    self._zoom_styles()
            self._zoom_themes[z] = th
        return th

    def set_zoom(self, z, at=None):
        """Zoom to z, keeping the screen point `at` (or the editor's centre)
        over the same spot of the graph."""
        z = min(ZOOMS[-1], max(ZOOMS[0], float(z)))
        if not self.graph or not dpg.does_item_exist("node_editor"):
            self.zoom = z
            return
        self._sync_pos()
        self._measure_pan()
        ex, ey = self.editor_origin()
        if at is None:
            w, h = dpg.get_item_rect_size("node_editor")
            at = (ex + w / 2, ey + h / 2)
        cx, cy = at[0] - ex - self.pan[0], at[1] - ey - self.pan[1]       # the cursor on the grid
        old = self.zoom
        self.offset[0] += cx * (1.0 / z - 1.0 / old)
        self.offset[1] += cy * (1.0 / z - 1.0 / old)
        self.zoom = z
        self.rebuild()
        self.app.prefs["zoom"] = z
        from native.project import save_prefs
        save_prefs(self.app.prefs)
        self.status(f"zoom {int(z * 100)}%")

    def zoom_step(self, direction, at=None):
        i = min(range(len(ZOOMS)), key=lambda k: abs(ZOOMS[k] - self.zoom))
        i = max(0, min(len(ZOOMS) - 1, i + (1 if direction > 0 else -1)))
        if ZOOMS[i] != self.zoom:
            self.set_zoom(ZOOMS[i], at)

    def on_mid_drag(self, delta):
        """The editor pans on a middle-mouse drag; keep count so screen
        points can still be turned into graph points."""
        if not dpg.does_item_exist("node_editor") or not dpg.is_item_hovered("node_editor"):
            return
        if self._mid_last is None:
            self._mid_last = (0.0, 0.0)
        self.pan[0] += delta[0] - self._mid_last[0]
        self.pan[1] += delta[1] - self._mid_last[1]
        self._mid_last = (delta[0], delta[1])

    def on_mid_release(self):
        self._mid_last = None

    def _sync_pos(self):
        """The nodes' positions from the editor, in graph units - only where
        a node was moved: the editor holds whole pixels, so at a small zoom
        reading an unmoved node back would creep it a unit or two a time."""
        if not self.graph:
            return
        for nid, n in self.graph.nodes.items():
            tag = f"gnode_{nid}"
            if dpg.does_item_exist(tag):
                shown = dpg.get_item_pos(tag)
                want = self._disp(n.get("pos", [0, 0]))
                if abs(shown[0] - want[0]) > 1.0 or abs(shown[1] - want[1]) > 1.0:
                    n["pos"] = self._graph(shown)

    def snapshot(self, key=None):
        """Call before changing the graph. `key` names a continuous edit."""
        if not self.graph:
            return
        now = time.time()
        if key is not None and self._last_snap and self._last_snap[0] == key and now - self._last_snap[1] < 1.0:
            self._last_snap = (key, now)
            return
        self._last_snap = (key, now)
        self._sync_pos()
        self._undo.append(json.dumps(self.graph.to_json()))
        # what the edit was, from the method asking - for the history list
        import sys
        who = sys._getframe(1).f_code.co_name
        desc = key[0] if isinstance(key, tuple) else (key or who)
        self._undo_desc.append(str(desc).replace("_", " ").strip())
        del self._undo[:-self.UNDO_MAX]
        del self._undo_desc[:-self.UNDO_MAX]
        self._redo.clear()

    def _restore(self, snap):
        self.graph = G.Graph(json.loads(snap), lib=self.lib, resolver=self.resolve_sub)
        self.graph.project_dir = self.app.project.path
        self.graph.features = self.features()
        self._last_snap = None
        self.rebuild()

    def undo(self):
        if not self._undo:
            self.status("nothing to undo"); return
        self._sync_pos()
        self._redo.append(json.dumps(self.graph.to_json()))
        self._restore(self._undo.pop())
        if self._undo_desc:
            self._undo_desc.pop()
        self.status(f"undo ({len(self._undo)} more)")

    def redo(self):
        if not self._redo:
            self.status("nothing to redo"); return
        self._sync_pos()
        self._undo.append(json.dumps(self.graph.to_json()))
        self._undo_desc.append("redo")
        self._restore(self._redo.pop())
        self.status("redo")

    def undo_steps(self):
        """The history list, oldest first: what each undo step takes back."""
        return list(self._undo_desc[-len(self._undo):]) if self._undo else []

    def undo_to(self, k):
        """Back k steps (the history list's row)."""
        for _ in range(max(0, int(k))):
            if not self._undo:
                break
            self.undo()

    def nudge(self, dx, dy):
        """Move the selected nodes by a step - the arrow keys."""
        sel = self._selected()
        if not sel:
            return
        self.snapshot("nudge")
        for nid in sel:
            t = f"gnode_{nid}"
            if not dpg.does_item_exist(t):
                continue                                  # a node of a type that is not there: not drawn, not moved
            x, y = dpg.get_item_pos(t)
            dpg.set_item_pos(t, [x + dx * self.zoom, y + dy * self.zoom])
        self._sync_pos()

    def home(self):
        """Frame the whole graph: the zoom the largest step it fits at, its
        top-left in the editor's corner. Only the view changes - the editor
        cannot be panned from code, so the panel's own view offset carries
        it; no node moves and there is nothing to undo."""
        if not self.graph or not self.graph.nodes:
            return
        self._frame_view(list(self.graph.nodes))
        self.status(f"the whole graph, at {int(self.zoom * 100)}%")

    def shift_view(self, dx):
        """The canvas's left edge moved dx to the right on the screen (the
        panel opened beside it on the left): the view moves back as far, so
        no node moves on the screen."""
        if not dx or not self.graph or not self.zoom:
            return
        self._sync_pos()
        self.offset[0] -= dx / self.zoom
        self.rebuild()

    def _frame_view(self, nids, most=1.0, room=None):
        """The view fitted to these nodes: the zoom the largest step their box
        fits at (no more than `most`), and the offset that puts the box's
        top-left 20 px in from the editor's corner. `room`: (w, h) of the
        canvas to fit in, when less of it is seen (a tutorial's page over it). A node's place on screen
        is (pos + offset) x zoom + the editor's own pan, so the offset is
        worked back from the pan measured now."""
        self._sync_pos()
        self._measure_pan()
        boxes = [(self.graph.nodes[n]["pos"], self._node_size(n)) for n in nids if n in self.graph.nodes]
        if not boxes:
            return
        x0 = min(p[0] for p, _ in boxes); y0 = min(p[1] for p, _ in boxes)
        x1 = max(p[0] + sz[0] for p, sz in boxes); y1 = max(p[1] + sz[1] for p, sz in boxes)
        w, h = room or (dpg.get_item_rect_size("node_editor") if dpg.does_item_exist("node_editor") else (0, 0))
        if w <= 0 or h <= 0:
            # not drawn yet (the layout changed to the graph this frame): the pane's size as the layout set it,
            # less its padding and the row above the canvas - a guess of 800 x 600 framed a big graph at 20%
            w, h = (dpg.get_item_width("graph_win") or 0, dpg.get_item_height("graph_win") or 0) \
                if dpg.does_item_exist("graph_win") else (0, 0)
            w, h = (w - px(20), h - px(58)) if w > 60 and h > 200 else (800, 600)
        fit = min((w - 40) / max(1.0, x1 - x0), (h - 40) / max(1.0, y1 - y0))
        z = min(most, max([zz for zz in ZOOMS if zz <= fit] or [ZOOMS[0]]))
        self.zoom = z
        pan = getattr(self, "pan", None) or [0.0, 0.0]
        self.offset = [(20.0 - pan[0]) / z - x0, (20.0 - pan[1]) / z - y0]
        self.app.prefs["zoom"] = z
        self.rebuild()

    # --- selection by key --------------------------------------------------------------------
    def set_selection(self, nids):
        """The selection becomes these (by key: imnodes' own is cleared)."""
        if not self.graph:
            return
        if dpg.does_item_exist("node_editor"):
            dpg.clear_selected_nodes("node_editor")
        self.ext_sel = [n for n in nids if n in self.graph.nodes]
        self._ext_last = {n: tuple(dpg.get_item_pos(f"gnode_{n}")) for n in self.ext_sel if dpg.does_item_exist(f"gnode_{n}")}
        for nid, n in self.graph.nodes.items():
            if dpg.does_item_exist(f"gnode_{nid}"):
                self._bind_node_theme(nid, n)
        self._focus_sel = None                                  # focus mode follows

    def end_key_selection(self):
        """The key selection (ext_sel) over; imnodes' own left as it is."""
        if not self.graph:
            return
        self.ext_sel = []
        self._ext_last = {}
        for nid, n in self.graph.nodes.items():
            if dpg.does_item_exist(f"gnode_{nid}"):
                self._bind_node_theme(nid, n)
        self._focus_sel = None

    def select_all(self):
        self.set_selection(list(self.graph.nodes) if self.graph else [])
        self.status(f"{len(self.ext_sel)} nodes selected")

    def select_none(self):
        self.set_selection([])
        self.status("nothing selected")

    def select_invert(self):
        if not self.graph:
            return
        cur = set(self._selected())
        self.set_selection([n for n in self.graph.nodes if n not in cur])
        self.status(f"{len(self.ext_sel)} nodes selected")

    def select_linked(self, direction):
        """Everything feeding the selection ("up"), fed by it ("down") or
        both ("both") - the whole chain, not just the neighbours."""
        if not self.graph:
            return
        sel = self._selected()
        if not sel:
            self.status("select a node first"); return
        keep = set(sel)
        grow = True
        while grow:
            grow = False
            for a, _, b, _ in self.graph.links:
                if direction in ("up", "both") and b in keep and a not in keep:
                    keep.add(a); grow = True
                if direction in ("down", "both") and a in keep and b not in keep:
                    keep.add(b); grow = True
        self.set_selection([n for n in self.graph.nodes if n in keep])
        self.status(f"{len(keep)} nodes: the selection and what it is {'fed by' if direction == 'up' else 'feeding' if direction == 'down' else 'wired to'}")

    def _poll_ext_sel(self):
        """A clicked node dragged carries the key-selected ones with it."""
        if not self.ext_sel or not self.graph:
            return
        clicked = set(self._clicked())
        mover = next((n for n in self.ext_sel if n in clicked and n in self._ext_last), None)
        if mover is None:
            self._ext_last = {n: tuple(dpg.get_item_pos(f"gnode_{n}")) for n in self.ext_sel if dpg.does_item_exist(f"gnode_{n}")}
            return
        cur = tuple(dpg.get_item_pos(f"gnode_{mover}"))
        last = self._ext_last[mover]
        dx, dy = cur[0] - last[0], cur[1] - last[1]
        if dx or dy:
            for n in self.ext_sel:
                if n in clicked or not dpg.does_item_exist(f"gnode_{n}"):
                    continue
                x, y = dpg.get_item_pos(f"gnode_{n}")
                dpg.set_item_pos(f"gnode_{n}", [x + dx, y + dy])
        self._ext_last = {n: tuple(dpg.get_item_pos(f"gnode_{n}")) for n in self.ext_sel if dpg.does_item_exist(f"gnode_{n}")}

    def frame_selected(self):
        """The selection filling the editor: the graph shifted so its box
        starts at the top left, the zoom the largest step it fits at."""
        sel = self._selected()
        if not sel:
            self.home(); return
        self._frame_view(sel, 1.0 if len(sel) > 1 else 1.5)
        self.status(f"framed {len(sel)} node(s) at {int(self.zoom * 100)}%")

    GRID = 20                    # graph units; the editor's grid squares

    def snap_selected(self):
        """The selected nodes onto the grid."""
        sel = self._selected()
        if not sel:
            return
        self._sync_pos()
        g = self.GRID
        for n in sel:
            p = self.graph.nodes[n]["pos"]
            p[0] = round(p[0] / g) * g; p[1] = round(p[1] / g) * g
            if dpg.does_item_exist(f"gnode_{n}"):
                dpg.set_item_pos(f"gnode_{n}", self._disp(p))
        self._frame_last = {nid: tuple(self._disp(n["pos"])) for nid, n in self.graph.nodes.items() if n["type"] == "Frame"}

    def toggle_snap(self):
        on = not self.app.prefs.get("snap")
        self.app.prefs["snap"] = on
        from native.project import save_prefs
        save_prefs(self.app.prefs)
        if on:
            self.snap_selected()
        self.status("snap to grid on (Ctrl while dragging: the other way)" if on else "snap to grid off")

    def dissolve_selected(self):
        """Delete with reconnect: a node goes, and what fed its first wired
        input feeds whatever its outputs fed, where the types allow."""
        sel = self._selected()
        if not sel:
            self.status("select nodes first"); return
        self.snapshot(); self._sync_pos()
        joined = 0
        for nid in sel:
            if nid not in self.graph.nodes:
                continue
            src = next(((a, o) for a, o, b, i in self.graph.links if b == nid), None)
            outs = [(b, i) for a, o, b, i in self.graph.links if a == nid and b not in sel]
            if src and outs:
                a, o = src
                at = next((x["type"] for x in self.graph.node_def(self.graph.nodes[a])["outputs"] if x["name"] == o), "float")
                for b, i in outs:
                    bt = next((x["type"] for x in self.graph.node_def(self.graph.nodes[b])["inputs"] if x["name"] == i), "float")
                    if compatible(at, bt):
                        self.graph.link(a, o, b, i); joined += 1
            self.graph.remove(nid)
        self.ext_sel = []
        self.rebuild()
        self.status(f"{len(sel)} node(s) dissolved, {joined} wire(s) joined")

    def swap_inputs(self):
        """The first two inputs of each selected node change places: their
        wires and their typed values, where the types allow."""
        sel = self._selected()
        if not sel:
            self.status("select a node first"); return
        self.snapshot(); self._sync_pos()
        done = 0
        for nid in sel:
            d = self.graph.node_def(self.graph.nodes[nid])
            ins = d["inputs"]
            if len(ins) < 2 or not compatible(ins[0]["type"], ins[1]["type"]) or not compatible(ins[1]["type"], ins[0]["type"]):
                continue
            a, b = ins[0]["name"], ins[1]["name"]
            la = next((l for l in self.graph.links if l[2] == nid and l[3] == a), None)
            lb = next((l for l in self.graph.links if l[2] == nid and l[3] == b), None)
            self.graph.unlink(nid, a); self.graph.unlink(nid, b)
            if la:
                self.graph.link(la[0], la[1], nid, b)
            if lb:
                self.graph.link(lb[0], lb[1], nid, a)
            vals = self.graph.nodes[nid].setdefault("inputs", {})
            va, vb = vals.get(a), vals.get(b)
            vals.pop(a, None); vals.pop(b, None)
            if va is not None: vals[b] = va
            if vb is not None: vals[a] = vb
            done += 1
        self.rebuild()
        self.status(f"inputs swapped on {done} node(s)" if done else "no selected node has two inputs of one kind")

    def set_label(self, nid, text):
        """A name of your own over the node's type (blank: the type again)."""
        if nid not in self.graph.nodes:
            return
        self.snapshot(); self._sync_pos()
        text = (text or "").strip()
        if text:
            self.graph.nodes[nid]["label"] = text
        else:
            self.graph.nodes[nid].pop("label", None)
        self.rebuild()

    def label_selected(self):
        sel = self._selected()
        if not sel:
            self.status("select a node first"); return
        from native import chrome
        n = self.graph.nodes[sel[0]]
        chrome.ask(self.app, "Node label", f"a label for this {n['type']} (blank: its type)", n.get("label", ""),
                   lambda v: self.set_label(sel[0], v))

    def frame_selection(self, title=None):
        """A Frame drawn round the selected nodes, with room to spare."""
        sel = [n for n in self._selected() if self.graph.nodes[n]["type"] != "Frame"]
        if not sel:
            self.status("select nodes first"); return
        self._sync_pos()
        self.snapshot()
        boxes = [(self.graph.nodes[n]["pos"], self._node_size(n)) for n in sel]
        pad = 24
        x0 = min(p[0] for p, _ in boxes) - pad; y0 = min(p[1] for p, _ in boxes) - pad - 30
        x1 = max(p[0] + sz[0] for p, sz in boxes) + pad; y1 = max(p[1] + sz[1] for p, sz in boxes) + pad
        fid = self.graph.add("Frame", (x0, y0), {"title": title or "group", "w": int(x1 - x0), "h": int(y1 - y0)})
        self.rebuild()
        self.status(f"framed {len(sel)} node(s)")
        return fid

    def typing(self):
        """True while a value box on a node has the keyboard."""
        return any(dpg.does_item_exist(w) and dpg.is_item_active(w) for w in self._widgets)

    # --- copy / cut / paste ----------------------------------------------------------
    # The clipboard is the selected nodes and the wires between them, as
    # graph JSON, held on the app so it survives switching graphs and going
    # into a sub-graph. Pasting gives fresh ids and nudges the copies so they
    # do not land exactly on the originals.
    def _selected(self):
        """The selection: what imnodes has, then what the keys added."""
        if not self.graph:
            return []
        if getattr(self, "_test_sel", None):            # the remote-control hooks stand in for a click
            return [i for i in self._test_sel if i in self.graph.nodes]
        out = []
        for tag in dpg.get_selected_nodes("node_editor"):
            nid = dpg.get_item_user_data(tag)
            if nid in self.graph.nodes and nid not in out:
                out.append(nid)
        for nid in self.ext_sel:
            if nid in self.graph.nodes and nid not in out:
                out.append(nid)
        return out

    def _clicked(self):
        """imnodes' own selection only."""
        if not self.graph:
            return []
        out = []
        for tag in dpg.get_selected_nodes("node_editor"):
            nid = dpg.get_item_user_data(tag)
            if nid in self.graph.nodes:
                out.append(nid)
        return out

    def copy(self):
        sel = self._selected()
        if not sel:
            self.status("select nodes to copy"); return
        self._sync_pos()
        S = set(sel)
        nodes = [json.loads(json.dumps(self.graph.nodes[n])) for n in sel]
        links = [list(l) for l in self.graph.links if l[0] in S and l[2] in S]
        meta = {f"{b}:{i}": m for (b, i), m in self.graph.link_meta.items() if b in S}
        self.app.clipboard = {"nodes": nodes, "links": links, "meta": meta}
        self.status(f"copied {len(nodes)} node(s)")

    def cut(self):
        sel = self._selected()
        if not sel:
            return
        self.copy()
        self.snapshot()
        for nid in sel:
            self.graph.remove(nid)
        self.rebuild()
        self.status(f"cut {len(sel)} node(s)")

    def paste(self, at=None):
        clip = getattr(self.app, "clipboard", None)
        if not clip or not self.graph:
            self.status("nothing to paste"); return
        self.snapshot()
        ids = {}
        xs = [n["pos"][0] for n in clip["nodes"]]; ys = [n["pos"][1] for n in clip["nodes"]]
        if at is not None:
            dx, dy = at[0] - min(xs), at[1] - min(ys)
        else:
            dx = dy = 40
        for n in clip["nodes"]:
            t = n["type"]
            if t not in self.lib and not t.startswith(G.SUB):
                continue
            new = self.graph.add(t, (n["pos"][0] + dx, n["pos"][1] + dy), dict(n.get("params", {})))
            self.graph.nodes[new]["inputs"] = dict(n.get("inputs", {}))
            self.graph.nodes[new].update(_node_extras(n))        # before the wires: an exposed pin is one
            ids[n["id"]] = new
        for a, o, b, i in clip["links"]:
            if a in ids and b in ids:
                self.graph.link(ids[a], o, ids[b], i)
                m = clip["meta"].get(f"{b}:{i}")
                if m:
                    self.graph.link_meta[(ids[b], i)] = dict(m)
        self.rebuild()
        self.status(f"pasted {len(ids)} node(s)")

    # --- live preview ------------------------------------------------------------------
    # Every edit marks the graph dirty; poll() - called each frame from the
    # main loop - waits until the edits pause for a moment, then compiles and
    # builds on the worker exactly as the button does. The 3-D view keeps
    # running the previous build meanwhile, and the swap keeps the sliders,
    # palette and colours, so the effect just changes under the cursor a
    # second or two after the wire lands.
    AUTO_DELAY = 0.5

    def touch(self):
        self._dirty = time.time()
        self.edits += 1                 # counts every edit; the autosave compares, never scans

    def set_auto(self, on):
        self.auto = bool(on)
        if self.app.prefs.get("live", True) != self.auto:
            self.app.prefs["live"] = self.auto               # the next session starts so
            from native.project import save_prefs
            save_prefs(self.app.prefs)
        if self.auto:
            self.touch()

    def poll(self):
        self._poll_frames()
        self._poll_ext_sel()
        self._poll_splice()
        self._poll_add_preview()
        self._poll_help()
        self._poll_props()
        self._poll_curve_edit()
        self._poll_bitmap_edit()
        self._poll_pads()
        self._poll_focus()
        self._poll_wires()
        self._poll_minimap()
        self._poll_labels()
        self._record_probes()
        self._poll_readouts()
        self._poll_cost_job()
        self._poll_costs_draw()
        self._poll_glyphs()
        if self._queued and not self.app.building:
            self._queued = False                     # a build asked for during the last one
            self.compile()
            return
        if not self.auto or not self._dirty or not self.graph:
            return
        quiet = time.time() - self._dirty
        if quiet >= self.SCRIPT_DELAY and self._standin_at != self.edits:
            self.standin()                           # the edit on the cube now; its build follows
        if quiet < self.AUTO_DELAY:
            return
        if self.app.building:
            return                    # tried again next frame; the last edit wins
        self._dirty = 0.0
        self.compile(auto=True)

    # --- the edit at once ----------------------------------------------------------------
    # A native build takes a second or three; the script VM (native/script.py) runs the same
    # graph from bytecode compiled in a few milliseconds. So an edit that is to be built shows
    # at once: the sim's Studio Script effect runs it under the graph's own name, sliders and
    # palette, and the build, when it lands, takes its place at the same clock
    # (app.poll_build) - the swap is not seen. A graph the script cannot run (a node it does
    # not have) waits for its build, as before; so does a comparison (A/B), which is of builds.
    SCRIPT_DELAY = 0.15

    def _build_target(self):
        """(graph, effect file) a build from the pane makes: the graph, or the pin preview's copy."""
        if not self.graph:
            return None, None
        if self.preview:
            g = self._preview_graph()
            if g is not None:
                return g, self.PREVIEW_FILE
        return self.graph, os.path.splitext(self.file)[0] + ".cpp"

    def standin(self, g=None, fname=None):
        """The graph (or `g`, for effect file `fname`) run as a script in place of its build
        until that lands; True when it is on the cube. Quietly False when it cannot be, or
        when what is on the cube runs this graph already (an edit that changed no code)."""
        app = self.app
        self._standin_at = self.edits
        if g is None:
            g, fname = self._build_target()
        eng = app.eng
        if g is None or getattr(app, "ab", None) is not None or not eng.names:
            return False
        si = eng.script_effect()
        if si is None:
            return False
        from native.script import compile_script, settings_of, GraphError
        try:
            if self._engine_has(fname, g.compile()):
                if self.standin_on():
                    self._standin_back()             # an edit undone before its build: the build is the graph again
                return False                         # the engine runs this code already (a zoom, a label, an open)
            prog = compile_script(g)
        except GraphError:                           # a node the script does not have, or a graph that does not check: the build alone shows it
            return False
        except Exception:
            oops.swallowed()
            return False
        title = app.project.effect_title(fname)
        on = eng.idx == si and self._standin_for == fname
        if self._shown == (fname, prog) and (on or eng.names[eng.idx] == title):
            if on:
                self._standin_shows = self.edits     # running it: a reload would only start it again
            return on                                # the cube shows this graph already
        if not eng.script(prog):
            return False
        self._standin_for, self._standin_prog, self._standin_shows = fname, prog, self.edits
        self._shown = (fname, prog)
        if not on:                                   # running already, the VM starts a new program itself
            st = settings_of(g)                      # what the build will start with (its metadata's defaults)
            pal = st.pop("pal")
            clock = eng.clock()
            eng.select(si, params=dict(st, pal=pal))
            eng.set_clock(clock)                     # a pattern that follows the time carries on
            self._standin_ui()
        return True

    def _standin_ui(self):
        """The effect list and the sliders name the graph's effect, not the Studio Script running it:
        the build's own labels when the engine has one, the script's until then."""
        app, eng = self.app, self.app.eng
        title = app.project.effect_title(self._standin_for)
        own = eng.meta[eng.names.index(title)] if title in eng.names else None
        dpg.set_value("fx_combo", title if own else eng.names[eng.idx])
        app.rebuild_params(meta=own)
        app.sync_palette_combo()

    def standin_on(self):
        """The stand-in is what the cube shows."""
        eng = self.app.eng
        return self._standin_for is not None and bool(eng.names) and eng.idx == eng.script_effect()

    def standin_stays(self, want, names):
        """When a build lands under the stand-in: True if the stand-in keeps the cube - it shows
        edits made while the build compiled, or the build has no effect of the graph's to show."""
        if want != self.app.project.effect_title(self._standin_for):
            return False                             # another effect was built: it is the one to show
        return self._standin_shows > self._built_at or want not in names

    def standin_reload(self, clock):
        """The stand-in into the engine's new library (a build landed under it and it stays)."""
        eng = self.app.eng
        si = eng.script_effect()
        if si is None or not eng.script(self._standin_prog):
            self._standin_for = None
            return False
        if eng.idx != si:
            eng.select(si, params=dict(eng.fx, pal=eng.pal))
        eng.set_clock(clock)
        self._standin_ui()
        return True

    def _engine_has(self, fname, src):
        """The engine runs this very code for `fname`: the file holds it, the engine has the
        effect, and its library was built after the file was written. An edit that changed no
        code - a zoom, a move, a label, opening the graph - has nothing to build or stand in for."""
        eng, proj = self.app.eng, self.app.project
        lib = getattr(eng, "library", None)
        if not lib or not fname or proj.effect_title(fname) not in (eng.names or []):
            return False
        try:
            if proj.read_effect(fname) != src:
                return False
            return os.path.getmtime(lib) >= os.path.getmtime(proj.effect_path(fname))
        except OSError:
            return False

    def _standin_back(self):
        """The stand-in off the cube for the build the engine has, at the same clock."""
        app, eng = self.app, self.app.eng
        title = app.project.effect_title(self._standin_for)
        if title in eng.names:
            clock = eng.clock()
            eng.select(eng.names.index(title))
            eng.set_clock(clock)
            dpg.set_value("fx_combo", title)
            app.rebuild_params()
            app.sync_palette_combo()
        self.standin_done(False)

    def standin_done(self, replaced=True):
        """A build landed and took the stand-in's place (replaced), or landed with something else
        on the cube: either way the cube shows a build now - the stand-in's edit when they match."""
        same = replaced and self._standin_for is not None and self._standin_shows == self._built_at
        self._shown = (self._standin_for, self._standin_prog) if same else None
        self._standin_for = None

    def rebuild(self):
        self.touch()
        self.app._color_edits = None                    # the nodes' dropdowns and swatches are new
        # the editor's own selection dies with the nodes it is rebuilt from
        # (a zoom, an edit): it carries on as the key selection, outlined
        keep = self._clicked()
        if keep:
            self.ext_sel = [n for n in dict.fromkeys(list(self.ext_sel) + keep)]
        props = [w for w in getattr(self, "_props_widgets", ()) if dpg.does_item_exist(w)]
        self._widgets.clear(); self._pads.clear(); self._glyph_clear(); self._glyph_pal = None
        # The properties' fields are not the editor's: they stay, and their
        # twins on the new nodes still follow them. They are drawn again from
        # the graph (an undo, a wire, a node's type) unless one is in use - a
        # Frame's title typed there rebuilds the editor at every key.
        self._widgets.update(props)
        if not any(dpg.is_item_active(w) for w in props):
            self._props_for = "unset"
        self._standin_line.clear()
        dpg.delete_item("node_editor", children_only=True)
        num.prune()                                      # the old nodes' number fields are gone
        self.links.clear(); self._pins.clear(); self._ptype.clear(); self._link_normal.clear()
        self._link_style.clear(); self._wires_lit = _STALE
        self._focus_sel = None
        if not self.graph:
            return
        f = self._font()
        self._node_font = f
        self._val_font = self._value_font()
        if f is not None:
            dpg.bind_item_font("node_editor", f)         # (Dear PyGui 2.3 does not hand an editor's font down: each node binds it too)
        dpg.bind_item_theme("node_editor", self._zoom_theme())
        # frames first: nodes draw in creation order, so a frame made first
        # sits behind the nodes inside it
        self._depth = []
        for nid, n in sorted(self.graph.nodes.items(), key=lambda kv: kv[1]["type"] != "Frame"):
            self._make_node(nid, n)
        self._frame_last = {nid: tuple(self._disp(n["pos"])) for nid, n in self.graph.nodes.items() if n["type"] == "Frame"}
        self._frame_drag.clear()
        # a wire to a pin that no longer exists - a sub-graph's input was
        # renamed or removed - is dropped rather than kept invisibly. A node
        # whose type is not there (its sub-graph or user node file gone) has
        # no pins drawn at all: its wires are kept, undrawn, as Graph keeps
        # them - dropped and saved, they were gone when the file came back
        drawn = {nid for nid in self.graph.nodes if dpg.does_item_exist(f"gnode_{nid}")}
        stale = [l for l in self.graph.links if l[0] in drawn and l[2] in drawn and
                 ((l[0], "out", l[1]) not in self._pins or (l[2], "in", l[3]) not in self._pins)]
        if stale:
            self.graph.links = [l for l in self.graph.links if l not in stale]
            self.status(f"dropped {len(stale)} wire(s) to pins that no longer exist")
        for a, out, b, inp in self.graph.links:
            if a in drawn and b in drawn:
                self._make_link(a, out, b, inp)
        self._mark_problems()
        # imnodes keeps its selection as slots in its node pool, and the
        # pool hands freed slots to the new nodes - so after a rebuild its
        # "selected" would be whichever nodes landed in those slots. It is
        # cleared; the selection lives on in ext_sel.
        dpg.clear_selected_nodes("node_editor")
        dpg.clear_selected_links("node_editor")
        self._ext_last = {n: tuple(dpg.get_item_pos(f"gnode_{n}")) for n in self.ext_sel if dpg.does_item_exist(f"gnode_{n}")}
        self._focus_sel = None

    # --- presets --------------------------------------------------------------------------
    # A node as it is set up now, saved by name, to drop in again. Global
    # (studio.json): a tool, not a project file. One whose type this project
    # does not have (a sub-graph elsewhere) is left out of the menus.
    def presets(self):
        return {k: v for k, v in (self.app.prefs.get("presets") or {}).items()
                if v.get("type") in self.lib}

    def save_preset(self, nid, name):
        n = self.graph.nodes.get(nid)
        name = (name or "").strip()
        if not n or not name:
            self.status("a name is needed for the preset"); return
        p = {"type": n["type"], "params": dict(n.get("params") or {})}
        for k in ("color", "collapsed", "hide_pins", "expose"):
            if n.get(k):
                p[k] = n[k]
        self.app.prefs.setdefault("presets", {})[name] = p
        from native.project import save_prefs
        save_prefs(self.app.prefs)
        self.fill_add_menu()
        self.status(f"preset {name} saved")

    def delete_preset(self, name):
        (self.app.prefs.get("presets") or {}).pop(name, None)
        from native.project import save_prefs
        save_prefs(self.app.prefs)
        self.fill_add_menu()

    def add_preset(self, name, pos):
        p = self.presets().get(name)
        if not p or not self.graph:
            return None
        self.snapshot()
        nid = self.graph.add(p["type"], pos, params=dict(p.get("params") or {}))
        for k in ("color", "collapsed", "hide_pins", "expose"):
            if p.get(k):
                self.graph.nodes[nid][k] = p[k]
        self._make_node(nid, self.graph.nodes[nid])
        return nid

    def _node_theme(self, col, frame=False, sel=False):
        """A node theme whose title bar is `col` (None: the default look); a
        frame's body is a wash of the same colour so the nodes inside still
        read through it; `sel` adds the key-selection outline."""
        light = self._light()
        key = (col, frame, sel, self.zoom, light)
        th = self._node_themes.get(key)
        if th is None:
            if col is not None and not frame:
                col = self._tint(col, light)             # dark title text needs a light bar under it
            with dpg.theme() as th:
                with dpg.theme_component(dpg.mvAll):
                    self._zoom_styles()
                with dpg.theme_component(dpg.mvNode):
                    if sel:
                        from native import chrome
                        dpg.add_theme_color(dpg.mvNodeCol_NodeOutline, tuple(chrome.ACCENT[:3]) + (255,), category=dpg.mvThemeCat_Nodes)
                        dpg.add_theme_style(dpg.mvNodeStyleVar_NodeBorderThickness, 3, category=dpg.mvThemeCat_Nodes)
                    if col is None:
                        self._node_themes[key] = th
                        return th
                    r, g, b = col
                    dpg.add_theme_color(dpg.mvNodeCol_TitleBar, (r, g, b, 255), category=dpg.mvThemeCat_Nodes)
                    dpg.add_theme_color(dpg.mvNodeCol_TitleBarHovered, (min(255, r + 30), min(255, g + 30), min(255, b + 30), 255),
                                        category=dpg.mvThemeCat_Nodes)
                    dpg.add_theme_color(dpg.mvNodeCol_TitleBarSelected, (min(255, r + 50), min(255, g + 50), min(255, b + 50), 255),
                                        category=dpg.mvThemeCat_Nodes)
                    if frame:
                        dpg.add_theme_color(dpg.mvNodeCol_NodeBackground, (r, g, b, 40), category=dpg.mvThemeCat_Nodes)
                        dpg.add_theme_color(dpg.mvNodeCol_NodeBackgroundHovered, (r, g, b, 55), category=dpg.mvThemeCat_Nodes)
                        dpg.add_theme_color(dpg.mvNodeCol_NodeBackgroundSelected, (r, g, b, 70), category=dpg.mvThemeCat_Nodes)
                        if not sel:
                            dpg.add_theme_color(dpg.mvNodeCol_NodeOutline, (r, g, b, 160), category=dpg.mvThemeCat_Nodes)
            self._node_themes[key] = th
        return th

    # --- frames ---------------------------------------------------------------------
    # A Frame is an ordinary node with nothing in it but a spacer of its size,
    # its body tinted by theme. Nodes are not parented to it - imnodes has no
    # groups - so poll() watches the frame's position: when it moves, the nodes
    # whose corner was inside it are moved by the same amount. Nodes in the
    # current selection are left alone, since the drag moves them already.
    def _frame_body(self, nid, n):
        w = int(n["params"].get("w", 400)); h = int(n["params"].get("h", 300))
        with dpg.node_attribute(attribute_type=dpg.mvNode_Attr_Static):
            dpg.add_spacer(width=self.px(w), height=max(1, self.px(h - 40)))
            with dpg.group(horizontal=True, horizontal_spacing=self._gap()):
                dpg.add_text("size", color=DIM)             # the frame's size, wide by high
                w_ = dpg.add_input_int(width=self.px(70), default_value=w, step=0, user_data=(nid, "w"),
                                       callback=self._on_param)
                dpg.add_text("×", color=DIM)
                h_ = dpg.add_input_int(width=self.px(70), default_value=h, step=0, user_data=(nid, "h"),
                                       callback=self._on_param)
                self._value_face(w_); self._value_face(h_)
                self._widgets.update((w_, h_))

    def _frame_rect(self, nid, pos=None):
        n = self.graph.nodes[nid]
        x, y = pos if pos is not None else dpg.get_item_pos(f"gnode_{nid}")
        return x, y, x + self.px(int(n["params"].get("w", 400)) + 16), y + self.px(int(n["params"].get("h", 300)) + 30)

    def _poll_frames(self):
        if not self.graph or not self._frame_last:
            return
        selected = {dpg.get_item_user_data(t) for t in dpg.get_selected_nodes("node_editor")}
        for fid, last in list(self._frame_last.items()):
            tag = f"gnode_{fid}"
            if not dpg.does_item_exist(tag):
                continue
            cur = tuple(dpg.get_item_pos(tag))
            dx, dy = cur[0] - last[0], cur[1] - last[1]
            if dx == 0 and dy == 0:
                self._frame_drag.pop(fid, None)
                continue
            if fid not in self._frame_drag:
                x0, y0, x1, y1 = self._frame_rect(fid, last)
                members = []
                for nid in self.graph.nodes:
                    if nid == fid or nid in selected or self.graph.nodes[nid]["type"] == "Frame":
                        continue
                    t = f"gnode_{nid}"
                    if dpg.does_item_exist(t):
                        px, py = dpg.get_item_pos(t)
                        if x0 <= px <= x1 and y0 <= py <= y1:
                            members.append(nid)
                self._frame_drag[fid] = members
            for nid in self._frame_drag[fid]:
                t = f"gnode_{nid}"
                if dpg.does_item_exist(t):
                    px, py = dpg.get_item_pos(t)
                    dpg.set_item_pos(t, [px + dx, py + dy])
            self._frame_last[fid] = cur

    # a field's name before it, in the interface's face; the node's fields start together (C7)
    NAMED = {"input": ("float", "vector", "color"), "param": ("float", "int", "choice", "color", "text", "file")}

    def _gap(self):
        return max(2, self.px(6))

    def _field_column(self, d, width, multiline=False, type_=None):
        """Where the node's fields start: its widest field name as drawn at
        this zoom (the name people use, nodeface.label), and a gap - never
        more than half the node (a longer name is cut there, the whole of it
        in the pin's help)."""
        names = [nodeface.label(type_, i["name"]) for i in d["inputs"] if i["type"] in self.NAMED["input"]]
        pnames = {p["name"] for p in d["params"]}
        pair_words = {}                                  # a pair's first key -> its row's words; its second -> None
        for a, b, words in nodeface.pairs(type_):
            if a in pnames and b in pnames:
                pair_words[a], pair_words[b] = words, None
        for p in d["params"]:
            if p["type"] not in self.NAMED["param"] or (p["type"] == "text" and (multiline or p.get("lines"))):
                continue
            if nodeface.is_meta(type_, p["name"]) or pair_words.get(p["name"], "") is None:
                continue
            names.append(pair_words.get(p["name"]) or nodeface.label(type_, p["name"]))
        if not names:
            return 0
        return min(int(width * 0.5), int(max(self.text_w(nm) for nm in names) + 0.999) + 2 * self._gap() + 1 + max(2, self.px(3)))   # _lead's margin

    def _lead(self, name, col, tag=None):
        """A field's name in the row open now, and the space that brings
        the field to the node's column."""
        import math
        g = self._gap()
        # a margin for the measure: a face on Linux or macOS draws a name a pixel or two wider than
        # it measures, and the field after it was pushed past the node's edge (the gallery test)
        m = min(max(2, self.px(3)), max(0, col - 2 * g - 1 - math.ceil(self.text_w(name))))   # never a name cut for it
        room = col - 2 * g - 1 - m
        shown = name if self.text_w(name) <= room else nodeface.fit_width(name, max(1, room), self.text_w)
        if not shown.endswith("...") and len(name) <= 2:
            shown = name                 # no room even for "..." (a knot's "in" in a wider face): whole beats a letter
        kw = {"tag": tag} if tag else {}
        t = dpg.add_text(shown, **kw)
        pad = col - 2 * g - m - math.ceil(self.text_w(shown))
        if pad >= 1:
            dpg.add_spacer(width=pad)
        return t

    def _show_value(self, w, val):
        """A field shows a value set from outside - a knob, a pad, a morph,
        a typed expression: a number's fill with it, a colour as the swatch
        takes it."""
        if not dpg.does_item_exist(w):
            return
        try:
            if num.is_num(w):
                num.set(w, val)
            elif dpg.get_item_type(w).endswith("ColorEdit"):
                dpg.set_value(w, [c / 255.0 for c in list(val)[:3]] + [1.0])
            elif dpg.get_item_type(w).endswith("InputFloatMulti") and isinstance(val, (list, tuple)) and len(val) == 3:
                dpg.set_value(w, list(val) + [0.0])
            elif dpg.get_item_type(w).endswith("Combo") and isinstance(val, int) and not isinstance(val, bool):
                # a number shown by name (the Effect settings' palette: "11  Rainbow")
                items = dpg.get_item_configuration(w).get("items") or []
                dpg.set_value(w, next((s for s in items if str(s).split("  ", 1)[0] == str(val)), str(val)))
            else:
                dpg.set_value(w, val)
        except Exception:
            oops.swallowed()

    def _input_widget(self, nid, n, i, tag, show, width=None):
        """The editable stand-in for an unconnected input pin: after its
        name, as wide as the node leaves it."""
        v = n["inputs"].get(i["name"], i.get("default", 0))
        ud = (nid, i["name"])
        fw = width or self.px(96)
        words = self._implicit_words(nid, i["name"])        # the pin reads the pixel: its field says from where
        if i["type"] == "float":
            w = self._number_widget(i, G.as_float(v), tag, ud, self._on_input, show, fw, words=words)
        elif i["type"] == "vector" and words:
            w = self._implicit_button(words, tag, ud, fw, show)
        elif i["type"] == "bool":
            w = dpg.add_checkbox(label=nodeface.label(n["type"], i["name"]), tag=tag, default_value=bool(v), user_data=ud,
                             callback=self._on_input, show=show)
        elif i["type"] == "vector":
            vv = [float(c) for c in (list(v) + [0, 0, 0])[:3]] if isinstance(v, (list, tuple)) else [float(v)] * 3
            w = dpg.add_input_floatx(tag=tag, width=fw, size=3, default_value=vv + [0.0],
                                     format="%.2f", user_data=ud, callback=self._on_input, show=show)
        else:
            rgb = list(v)[:3] if isinstance(v, (list, tuple)) else [0, 0, 0]
            w = dpg.add_color_edit([int(c) for c in rgb] + [255], tag=tag, no_label=True,
                               no_alpha=True, no_inputs=True, user_data=ud, callback=self._on_input, show=show)
        dpg.bind_item_theme(w, self._field_theme())
        self._value_face(w)
        self._widgets.add(w)

    def _same_type_selected(self, nid):
        """Alt held: the other selected nodes of this node's type - an edit
        lands on all of them."""
        if not (dpg.is_key_down(dpg.mvKey_LAlt) or dpg.is_key_down(dpg.mvKey_RAlt)):
            return []
        t = self.graph.nodes[nid]["type"]
        return [k for k in self._selected() if k != nid and self.graph.nodes[k]["type"] == t]

    def live_values(self):
        """The typed values of the pins the built effect reads from its table,
        as they stand: [(node id, pin, value)], a colour as [r, g, b] - for
        another engine running the same build (A/B's before and after)."""
        live = getattr(self, "_live", None) or {}
        out = []
        for nid, name in sorted({(k[0], k[1]) for k in live}):
            n = self.graph.nodes.get(nid) if self.graph else None
            if not n or name not in (n.get("inputs") or {}):
                continue                                 # at its default: the table has it from the build
            v = n["inputs"][name]
            if isinstance(v, int) and not isinstance(v, bool) and (nid, name, 0) in live:
                v = [(v >> 16) & 255, (v >> 8) & 255, v & 255]      # a colour kept as one number
            out.append((nid, name, v))
        return out

    def live_poke(self, nid, name, val, eng=None, live=None):
        """The typed value into the running effect's parameter table, so the
        picture follows the drag with no rebuild. True when it landed: the
        effect built from this graph is in the engine and has run. A
        vector or a colour (r, g, b 0..255) pokes three slots; a bool one.
        `eng` another engine running the same build, `live` the slots of
        that build (A/B's before and after)."""
        live = live if live is not None else getattr(self, "_live", None)
        if not live or not getattr(self, "_probes_for", None):
            return False
        eng = eng or self.app.eng
        title = self.app.project.effect_title(self._probes_for)
        if title not in eng.names:
            return False
        idx = eng.names.index(title)
        if eng.idx != idx:
            return False                                 # something else is on screen (the script preview, another effect): as before
        if isinstance(val, (list, tuple)):
            slots = [(live.get((nid, name, j)), float(c)) for j, c in enumerate(list(val)[:3])]
            n = self.graph.nodes.get(nid)
            if n and next((i["type"] for i in self.graph.node_def(n)["inputs"] if i["name"] == name), "") == "color":
                slots = [(k, max(0.0, min(255.0, round(c)))) for k, c in slots]    # the C++ casts them to bytes
        else:
            slots = [(live.get((nid, name, None)), (1.0 if val else 0.0) if isinstance(val, bool) else float(val))]
        if any(k is None for k, _ in slots):
            return False
        return all(eng.param_set(idx, k, v) for k, v in slots)

    def set_input_live(self, nid, name, val):
        """A typed value set from outside the node (a MIDI knob): the graph,
        the field on the node, and the running effect - no rebuild when the
        poke lands, as with a drag."""
        n = self.graph.nodes.get(nid) if self.graph else None
        if n is None:
            return False
        d = self.graph.node_def(n)
        ptype = next((i["type"] for i in d["inputs"] if i["name"] == name), "float")
        if ptype == "bool":
            val = bool(val)
        elif ptype == "float":
            val = round(float(val), 5)
        if n.get("inputs", {}).get(name) == val:
            return True
        was_dirty = self._dirty
        self.touch(); self.snapshot(("midi", nid, name))    # a knob's stroke is one undo step
        n.setdefault("inputs", {})[name] = val
        self._mirror(None, nid, name, val)                 # its fields - the node's, the properties' - and its pads
        if self.live_poke(nid, name, val) and not was_dirty:
            self._dirty = 0.0
        self._refresh_summary(nid)
        return True

    def _on_input(self, sender, val):
        was_dirty = self._dirty
        self.touch()
        nid, name = dpg.get_item_user_data(sender)
        self.snapshot(("in", nid, name))
        d = self.graph.node_def(self.graph.nodes[nid])
        ptype = next((i["type"] for i in d["inputs"] if i["name"] == name), "float")
        if ptype == "vector":
            val = [float(x) for x in list(val)[:3]]
        elif isinstance(val, (list, tuple)) and len(val) >= 3 and all(isinstance(x, float) for x in val):
            val = [int(round(x * 255)) if x <= 1.0 else int(x) for x in val[:3]]
        self.graph.nodes[nid].setdefault("inputs", {})[name] = val
        self._mirror(sender, nid, name, val)             # the node's field, or its properties', follows the other
        poked = self.live_poke(nid, name, val)          # a colour too, since 1.4.0: picked with no rebuild
        for k in self._same_type_selected(nid):
            self.graph.nodes[k].setdefault("inputs", {})[name] = val
            poked = poked and self.live_poke(k, name, val)
            self._mirror(None, k, name, val)
        if poked and not was_dirty:
            self._dirty = 0.0                            # the running effect has the value: nothing to rebuild
            shown = (f"#{int(val[0]) & 255:02X}{int(val[1]) & 255:02X}{int(val[2]) & 255:02X}" if ptype == "color"
                     else val if not isinstance(val, float) else round(val, 4))
            self.status(f"{self.graph.nodes[nid]['type']} #{nid} {nodeface.label(self.graph.nodes[nid]['type'], name)}: "
                        f"{shown} - live", node=self.where(nid), merge=f"live:{nid}:{name}")
        self._refresh_summary(nid)

    def _show_input(self, b, inp, linked):
        """A wire in or out: the pin's field hides or comes back. Its name
        stays either way - a checkbox's is on it, so it shows alone while wired."""
        tag, w = f"gin_{b}_{inp}", f"gin_{b}_{inp}_w"
        if not dpg.does_item_exist(w):                      # a stand-in has no value box (nor a folded node)
            if dpg.does_item_exist(tag + "_t"):
                dpg.configure_item(tag + "_t", show=linked)
            return
        dpg.configure_item(f"{w}__num" if dpg.does_item_exist(f"{w}__num") else w, show=not linked)
        if dpg.get_item_type(w).endswith("Checkbox") and dpg.does_item_exist(tag + "_t"):
            dpg.configure_item(tag + "_t", show=linked)
        words = None if linked or not num.is_num(w) else self._implicit_words(b, inp)
        if words:                                           # unwired and nothing typed: it reads the pixel again
            dpg.configure_item(w, format=words.replace("%", "%%"))

    def _hovered_field(self):
        """(widget, nid, name, kind) for the value box under the pointer."""
        for w in self._widgets:
            if dpg.does_item_exist(w) and dpg.is_item_hovered(w):
                ud = dpg.get_item_user_data(w)
                if isinstance(ud, tuple) and len(ud) == 2 and ud[0] in self.graph.nodes:
                    nid, name = ud
                    kind = "param" if any(p["name"] == name for p in self.graph.node_def(self.graph.nodes[nid])["params"]) else "input"
                    return w, nid, name, kind
        return None

    def _set_param_widget(self, nid, name, val):
        """A value set from outside (an expression, a snapshot, a pad): every field of (nid, name)."""
        self._mirror(None, nid, name, val, pads=False)

    def expr_hovered(self):
        """= over a value box: the expression box for it."""
        h = self._hovered_field()
        if not h or not self.graph:
            return False
        w, nid, name, kind = h
        return self.expr_for(nid, name, kind)

    def expr_names(self, nid):
        """The names an expression may use on this node: its typed inputs
        and numeric settings, by name."""
        n = self.graph.nodes[nid]
        d = self.graph.node_def(n)
        wired = {i for b, i in ((l[2], l[3]) for l in self.graph.links) if b == nid}
        names = {}
        for i in d["inputs"]:
            if i["type"] == "float" and i["name"] not in wired:
                try:
                    names[i["name"].replace(" ", "_")] = float(n.get("inputs", {}).get(i["name"], i.get("default", 0.0)))
                except (TypeError, ValueError):
                    pass
        for p in d["params"]:
            if p["type"] in ("float", "int"):
                try:
                    names[p["name"].replace(" ", "_")] = float(n["params"].get(p["name"], p.get("default", 0.0)))
                except (TypeError, ValueError):
                    pass
        # the names as shown work too, in words joined by _ ("in_low" for in_lo); a key wins a clash
        for key in list(names):
            shown = nodeface.label(n["type"], key).replace(" ", "_").replace("-", "_")
            names.setdefault(shown, names[key])
        return names

    def expr_for(self, nid, name, kind):
        """The expression box for a number on a node (a typed input or a
        numeric setting), at the pointer, holding the value it has."""
        if not self.graph or nid not in self.graph.nodes or not dpg.does_item_exist("expr_win"):
            return False
        n = self.graph.nodes[nid]
        d = self.graph.node_def(n)
        if kind == "param":
            p = next((p for p in d["params"] if p["name"] == name), None)
            if not p or p["type"] not in ("float", "int"):
                return False
            cur = n["params"].get(name, p.get("default", 0))
        else:
            i = next((i for i in d["inputs"] if i["name"] == name), None)
            if not i or i["type"] != "float":
                return False
            cur = n.get("inputs", {}).get(name, i.get("default", 0.0))
        self._expr_target = (nid, name, kind)
        dpg.set_value("expr_label", f"{n['type']} . {nodeface.label(n['type'], name)} =")
        dpg.set_value("expr_text", f"{float(cur):g}" if isinstance(cur, (int, float)) else str(cur))
        x, y = dpg.get_mouse_pos(local=False)
        dpg.configure_item("expr_win", show=True)
        dpg.set_item_pos("expr_win", [x + 8, y + 8])
        dpg.focus_item("expr_text")
        self.status(f"{nodeface.label(n['type'], name)}: type an expression and press Enter (Escape leaves it)")
        return True

    def expr_enter(self, text):
        """Enter in the box: the expression worked out and set."""
        t = getattr(self, "_expr_target", None)
        dpg.configure_item("expr_win", show=False)
        if not t:
            return
        self.apply_expr(*t, text)

    def apply_expr(self, nid, name, kind, text):
        """`text` evaluated with the node's own numbers as names (and x,
        the value the field has) and set - a typed input poked live, a
        setting the way its widget would set it. Returns the value, or
        None with the reason in the status."""
        from native import expr
        if not self.graph or nid not in self.graph.nodes:
            return None
        n = self.graph.nodes[nid]
        d = self.graph.node_def(n)
        names = self.expr_names(nid)
        key = name.replace(" ", "_")
        names["x"] = names.get(key, 0.0)
        try:
            v = expr.evaluate(text, names)
        except expr.ExprError as e:
            self.status(f"{self.pin_words(nid, name)}: {e}", node=self.where(nid)); return None
        if kind == "param":
            p = next((p for p in d["params"] if p["name"] == name), None)
            if p is None:
                return None
            if p["type"] == "int":
                v = int(round(v))
            if p.get("min") is not None:
                v = max(p["min"], v)
            if p.get("max") is not None:
                v = min(p["max"], v)
            self.snapshot(("expr", nid, name))
            n["params"][name] = v
            self._set_param_widget(nid, name, v)
            self._refresh_summary(nid)
            self.touch()
            self.status(f"{self.pin_words(nid, name)} = {v:g}  ({text})", node=self.where(nid))
        else:
            i = next((i for i in d["inputs"] if i["name"] == name), None)
            if i is None:
                return None
            if i.get("min") is not None:
                v = max(float(i["min"]), v)
            if i.get("max") is not None:
                v = min(float(i["max"]), v)
            self.set_input_live(nid, name, v)
            self.status(f"{self.pin_words(nid, name)} = {v:g}  ({text})", node=self.where(nid))
        return v

    # --- editing callbacks ------------------------------------------------------------
    def on_link(self, sender, app_data):
        self.touch()
        out_attr, in_attr = app_data
        a, out = dpg.get_item_user_data(out_attr)
        b, inp = dpg.get_item_user_data(in_attr)
        ta, tb = self._ptype.get(out_attr), self._ptype.get(in_attr)
        if ta and tb and not compatible(ta, tb):
            self.status(f"cannot connect {ta} to {tb}")
            return
        self.snapshot()
        pre = self.scopes()                                # the scopes before this wire (a loop has none)
        # replace whatever fed this input
        for lid, (bb, ii) in list(self.links.items()):
            if bb == b and ii == inp:
                dpg.delete_item(lid); self.links.pop(lid, None)
        d = self.graph.link_with_delay(a, out, b, inp, pre)
        if d is not None:
            # the wire closed a loop: a Delay went on it, so the loop carries last frame's value
            self.rebuild()
            self.status("that wire closed a loop: a Delay on it hands last frame's value round (undo takes both out)")
            return
        self._make_link(a, out, b, inp)
        self._props_for = "unset"                          # a wired input leaves the properties' list

    def on_delink(self, sender, app_data):
        self.touch()
        self.snapshot()
        lid = app_data
        b, inp = self.links.pop(lid, (None, None))
        if b is not None:
            self.graph.unlink(b, inp)
            self._show_input(b, inp, False)
            self._props_for = "unset"                      # a freed input joins the properties' list
        dpg.delete_item(lid)

    # --- greying out while a wire is dragged -----------------------------------------
    # Dear PyGui does not say when a link drag begins, but it does say what is
    # hovered: a press over an output pin is the start of a drag from it, and
    # every input that cannot take that type goes grey until the release.
    def on_press(self):
        if not self.graph or not dpg.does_item_exist("node_editor") or not dpg.is_item_shown("node_editor"):
            return
        ctrl = dpg.is_key_down(dpg.mvKey_LControl) or dpg.is_key_down(dpg.mvKey_RControl)
        shift = dpg.is_key_down(dpg.mvKey_LShift) or dpg.is_key_down(dpg.mvKey_RShift)
        alt = dpg.is_key_down(dpg.mvKey_LAlt) or dpg.is_key_down(dpg.mvKey_RAlt)
        over = next((nid for nid in self.graph.nodes
                     if dpg.does_item_exist(f"gnode_{nid}") and dpg.is_item_hovered(f"gnode_{nid}")), None)
        if over is None:
            over = self._node_at(dpg.get_mouse_pos(local=False))   # over one of its widgets, the node is not "hovered"
        if alt and over is not None:
            self.detach(over); return
        if ctrl and shift and over is not None:
            # Ctrl+Shift+click previews the node's first output; again, the next one
            outs = [o["name"] for o in self.graph.node_def(self.graph.nodes[over])["outputs"]]
            if outs:
                k = (outs.index(self.preview[1]) + 1) % len(outs) if self.preview and self.preview[0] == over and self.preview[1] in outs else 0
                self.preview_pin(over, outs[k])
            return
        if dpg.is_item_hovered("node_editor") and not ctrl and not shift and self.ext_sel and over not in self.ext_sel \
                and not getattr(self.app, "_popup_click", False):
            # a plain click elsewhere: the key selection is over. imnodes' own
            # is left as the click made it: this runs a frame after imnodes took
            # the click, and clearing it too took away the node just clicked -
            # after a zoom, which carries the selection on by key, a second
            # node clicked was never selected
            self.end_key_selection()
        # where every node is now: a node dragged onto a wire is spliced in on release
        self._press_pos = {nid: tuple(dpg.get_item_pos(f"gnode_{nid}")) for nid in self.graph.nodes if dpg.does_item_exist(f"gnode_{nid}")}
        self._node_press = over is not None          # a press on a node: the drag that follows moves the selection
        if over is not None and dpg.is_item_hovered(f"gnode_{over}"):
            self._raise(over)                        # imnodes brings a node clicked on (not on one of its fields) to the front
        self._drag_kind = None
        # The pin pressed: its attribute hovered (the label), or the pointer
        # within imnodes' hover radius of the circle itself, which sits just
        # outside the node - where a wire is naturally grabbed.
        mp = dpg.get_mouse_pos(local=False)
        hit, best = None, None
        for (nid, kind, name), tag in self._pins.items():
            if not dpg.does_item_exist(tag):
                continue
            if dpg.is_item_hovered(tag) or self._on_pin_label(tag, mp):
                hit, best = (nid, kind, name, tag), -1.0
                break
            pt = self._pin_point(nid, kind, name)
            if pt is not None:
                d = ((pt[0] - mp[0]) ** 2 + (pt[1] - mp[1]) ** 2) ** 0.5
                if d <= self.px(12) and (best is None or d < best):
                    hit, best = (nid, kind, name, tag), d
        if hit is None:
            return
        nid, kind, name, tag = hit
        self._drag_type = self._ptype.get(tag)
        self._drag_from = (nid, name)
        self._drag_kind = kind
        self._press_at = mp
        th = self.themes()
        other = "in" if self._drag_kind == "out" else "out"
        for (nid, kind, name), tag in self._pins.items():
            if kind == other and dpg.does_item_exist(tag):
                t = self._ptype.get(tag)
                ok = compatible(self._drag_type, t) if self._drag_kind == "out" else compatible(t, self._drag_type)
                dpg.bind_item_theme(tag, th.pin[t] if ok else th.grey[t])

    def on_release(self):
        # a clicked frame comes to the front and would then take the clicks
        # meant for the nodes inside it: send it back behind them
        if self.graph and self._frame_last and dpg.does_item_exist("node_editor"):
            for fid in self._frame_last:
                if dpg.does_item_exist(f"gnode_{fid}") and dpg.is_item_hovered(f"gnode_{fid}"):
                    self._sync_pos(); self.rebuild()
                    break
        self._node_press = False
        if self._drag_type is None:
            if self.graph and self._press_pos:
                moved = [nid for nid, p in self._press_pos.items()
                         if dpg.does_item_exist(f"gnode_{nid}") and tuple(dpg.get_item_pos(f"gnode_{nid}")) != p]
                self._press_pos = {}
                if moved:
                    ctrl = dpg.is_key_down(dpg.mvKey_LControl) or dpg.is_key_down(dpg.mvKey_RControl)
                    if bool(self.app.prefs.get("snap")) != ctrl:
                        self.snap_selected()
                    if len(moved) == 1 and self._splice and self._splice[0] == moved[0]:
                        self._splice_apply()
            self._splice_clear()
            return
        t, frm = self._drag_type, self._drag_from
        self._drag_type = self._drag_from = None
        th = self.themes()
        for (nid, kind, name), tag in self._pins.items():
            if dpg.does_item_exist(tag):
                dpg.bind_item_theme(tag, th.pin[self._ptype.get(tag, "float")])
        # A wire dropped on empty editor: offer the nodes it could feed (or,
        # from an input, the nodes that could feed it), and wire the one
        # chosen. Over a pin or a node the drop is DPG's (a link or nothing);
        # a short drag is a click on the pin.
        mx, my = dpg.get_mouse_pos(local=False)
        if abs(mx - self._press_at[0]) + abs(my - self._press_at[1]) < 12:
            return
        # the editor reports no hover while a wire is being dragged: its
        # rectangle says whether the drop is inside it
        er = self.editor_rect()
        if er is None or not (er[0] <= mx <= er[2] and er[1] <= my <= er[3]):
            return
        for (nid, kind, name), tag in self._pins.items():
            if dpg.does_item_exist(tag) and dpg.is_item_hovered(tag):
                return
        for nid in self.graph.nodes:
            if dpg.does_item_exist(f"gnode_{nid}") and dpg.is_item_hovered(f"gnode_{nid}"):
                # dropped on a node's body: its first free pin that fits
                if nid != frm[0]:
                    self._wire_to_body(frm, t, nid, getattr(self, "_drag_kind", "out"))
                return
        gx, gy = self._to_graph((mx, my))
        self._menu_pos = (gx - 20, gy - 10)
        if getattr(self, "_drag_kind", "out") == "in":
            self._pending = ("into", frm[0], frm[1], t)
            self.show_add_menu((mx, my), only=self._producers(t, limit=60))
        else:
            self._pending = (frm[0], frm[1], t)
            self.show_add_menu((mx, my), only=self._consumers(t, limit=60))

    def panning(self):
        """True while the canvas is being dragged (middle button): every
        node moves with the pointer."""
        return dpg.is_mouse_button_down(dpg.mvMouseButton_Middle) and dpg.does_item_exist("node_editor")             and dpg.is_item_hovered("node_editor")

    def dragging_nodes(self):
        """True while a press that began on a node is held: the selection
        is moving with the pointer."""
        return bool(getattr(self, "_node_press", False)) and dpg.is_mouse_button_down(dpg.mvMouseButton_Left)             and self._drag_type is None

    def editor_rect(self):
        """The node editor on screen (x0, y0, x1, y1): it reports no position
        of its own - it is the bottom of its pane, its height from its size."""
        pane = self.app._screen_rect("graph_win") if hasattr(self.app, "_screen_rect") else None
        if not pane or not dpg.does_item_exist("node_editor"):
            return None
        eh = dpg.get_item_rect_size("node_editor")[1]
        return (pane[0] + 9, pane[3] - 9 - eh, pane[2] - 9, pane[3] - 9)

    def _on_pin_label(self, tag, mp):
        """The pointer on a pin's label text (an attribute reports no hover
        of its own worth having)."""
        kids = dpg.get_item_children(tag, 1) or []
        if not kids or not dpg.does_item_exist(kids[0]):
            return False
        st = dpg.get_item_state(kids[0])
        if "rect_min" not in st or "rect_max" not in st:
            return False
        (x0, y0), (x1, y1) = st["rect_min"], st["rect_max"]
        return x0 - 2 <= mp[0] <= x1 + 2 and y0 - 2 <= mp[1] <= y1 + 2

    def _node_at(self, mp):
        """The node whose rectangle holds the point - the one drawn on top
        where nodes overlap (it took the first made, the one underneath) -
        or None."""
        if not self.graph:
            return None
        order = [n for n in reversed(self._depth) if n in self.graph.nodes]
        for nid in order + [n for n in self.graph.nodes if n not in self._depth]:
            tag = f"gnode_{nid}"
            if not dpg.does_item_exist(tag):
                continue
            st = dpg.get_item_state(tag)
            if "rect_min" not in st or "rect_max" not in st:
                continue
            (x0, y0), (x1, y1) = st["rect_min"], st["rect_max"]
            if x0 <= mp[0] <= x1 and y0 <= mp[1] <= y1 and self.graph.nodes[nid]["type"] != "Frame":
                return nid
        return None

    def _wire_to_body(self, frm, t, nid, kind):
        """A wire from `frm` dropped on node `nid`: the first free input that
        takes it (from an output), or the first output that feeds it."""
        d = self.graph.node_def(self.graph.nodes[nid])
        wired = {(b, i) for _, _, b, i in self.graph.links}
        if kind == "out":
            inp = next((i["name"] for i in d["inputs"] if (nid, i["name"]) not in wired and compatible(t, i["type"])), None)
            if inp is None:
                inp = next((i["name"] for i in d["inputs"] if compatible(t, i["type"])), None)
            if inp is None:
                self.status("no input there takes it"); return
            if self._would_loop([(frm[0], frm[1], nid, inp)]):
                self.status("that would make a loop - a value can only come round through a Delay (wire it to an input, and one goes on it)", "warning"); return
            self.snapshot(); self.graph.link(frm[0], frm[1], nid, inp)
        else:
            out = next((o["name"] for o in d["outputs"] if compatible(o["type"], t)), None)
            if out is None:
                self.status("no output there fits"); return
            if self._would_loop([(nid, out, frm[0], frm[1])]):
                self.status("that would make a loop - a value can only come round through a Delay (wire it to an input, and one goes on it)", "warning"); return
            self.snapshot(); self.graph.link(nid, out, frm[0], frm[1])
        self.rebuild()

    def _would_loop(self, links):
        """Whether these wires would close a loop with no Delay in it - tried, then taken back. A splice or a
        wire dropped on a node's body linked as it was: the graph then failed every compile ("cycle through
        node ...") until undone; a wire dropped on a pin gets a Delay instead (link_with_delay)."""
        saved, meta = list(self.graph.links), dict(self.graph.link_meta)
        for l in links:
            self.graph.link(*l)
        try:
            self.graph._order()
            loop = False
        except G.GraphError:
            loop = True
        self.graph.links, self.graph.link_meta = saved, meta
        return loop

    def _wire_points(self, lid):
        """A wire's polyline on screen, sampled along the curve imnodes draws."""
        b, inp = self.links.get(lid, (None, None))
        if b is None:
            return None
        a = next((l[0] for l in self.graph.links if l[2] == b and l[3] == inp), None)
        out = next((l[1] for l in self.graph.links if l[2] == b and l[3] == inp), None)
        if a is None:
            return None
        p0 = self._pin_point(a, "out", out); p1 = self._pin_point(b, "in", inp)
        if p0 is None or p1 is None:
            return None
        d = max(50.0, abs(p1[0] - p0[0]) * 0.5)
        c0, c1 = (p0[0] + d, p0[1]), (p1[0] - d, p1[1])
        pts = []
        for k in range(17):
            u = k / 16.0; v = 1 - u
            pts.append((v ** 3 * p0[0] + 3 * v * v * u * c0[0] + 3 * v * u * u * c1[0] + u ** 3 * p1[0],
                        v ** 3 * p0[1] + 3 * v * v * u * c0[1] + 3 * v * u * u * c1[1] + u ** 3 * p1[1]))
        return pts

    @staticmethod
    def _seg_dist(p, a, b):
        ax, ay = a; bx, by = b; px, py = p
        dx, dy = bx - ax, by - ay
        L = dx * dx + dy * dy
        t = 0.0 if L == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / L))
        return ((ax + t * dx - px) ** 2 + (ay + t * dy - py) ** 2) ** 0.5

    @staticmethod
    def _segs_cross(a, b, c, d):
        def orient(p, q, r):
            return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])
        return (orient(a, b, c) * orient(a, b, d) < 0) and (orient(c, d, a) * orient(c, d, b) < 0)

    # --- splicing a dragged node into a wire ---------------------------------------------
    # While one node is being dragged and the POINTER is over a wire the node
    # could sit on, that wire lights up and the wiring it would become is
    # drawn - the source to the node's input, the node's output on to the
    # wire's old end. Let go there and it is done; anywhere else, nothing.
    # The pointer, not the node's body: a node carried across a wire on its
    # way somewhere else must not catch on it.
    def _poll_splice(self):
        if not self.graph or not self.dragging_nodes():
            self._splice_clear(); return
        moved = [nid for nid, p in self._press_pos.items()
                 if dpg.does_item_exist(f"gnode_{nid}") and tuple(dpg.get_item_pos(f"gnode_{nid}")) != p]
        if len(moved) != 1 or self.graph.nodes[moved[0]]["type"] == "Frame":
            self._splice_clear(); return
        nid = moved[0]
        d = self.graph.node_def(self.graph.nodes[nid])
        if not d["inputs"] or not d["outputs"]:
            self._splice_clear(); return
        mp = dpg.get_mouse_pos(local=False)
        best = None
        for lid, (b, inp) in list(self.links.items()):
            if b == nid or not dpg.does_item_exist(lid):
                continue
            a = next((l[0] for l in self.graph.links if l[2] == b and l[3] == inp), None)
            if a is None or a == nid:
                continue
            pts = self._wire_points(lid)
            if not pts:
                continue
            dist = min(self._seg_dist(mp, pts[k], pts[k + 1]) for k in range(len(pts) - 1))
            if dist <= 10 and (best is None or dist < best[0]):
                best = (dist, lid, a, b, inp)
        if best is None:
            self._splice_clear(); return
        _, lid, a, b, inp = best
        out = next(l[1] for l in self.graph.links if l[2] == b and l[3] == inp)
        at = next((o["type"] for o in self.graph.node_def(self.graph.nodes[a])["outputs"] if o["name"] == out), "float")
        bt = next((i["type"] for i in self.graph.node_def(self.graph.nodes[b])["inputs"] if i["name"] == inp), "float")
        wired = {(x, i) for _, _, x, i in self.graph.links}
        my_in = next((i["name"] for i in d["inputs"] if (nid, i["name"]) not in wired and compatible(at, i["type"])), None)
        my_out = next((o["name"] for o in d["outputs"] if compatible(o["type"], bt)), None)
        if my_in is None or my_out is None:
            self._splice_clear(); return
        want = (nid, lid, a, out, b, inp, my_in, my_out)
        if self._splice != want:
            self._splice_clear()
            self._splice = want
            dpg.bind_item_theme(lid, self._dim_wire())         # the wire that would go fades; the new wiring is drawn
            self.status(f"drop to splice into {self.pin_words(a, out)} -> {self.pin_words(b, inp)}")
        # the wiring it would become, drawn over the nodes, following the node
        p_src = self._pin_point(a, "out", out)
        p_in = self._pin_point(nid, "in", my_in) or self._node_edge(nid, "in")
        p_out = self._pin_point(nid, "out", my_out) or self._node_edge(nid, "out")
        p_dst = self._pin_point(b, "in", inp)
        self._splice_draw([(p_src, p_in), (p_out, p_dst)])

    # AI: below section was generated by an AI
    def _splice_draw(self, curves):
        """The splice's curves, each the shape imnodes gives a wire, drawn as the runs of it that are on the canvas:
        inside the editor and out from under the windows floating over it and the minimap. They are on a viewport
        drawlist in front of everything, and a wire's far end off the canvas (zoomed in) ran over the pane's frame,
        the toolbar, the side panel and the 3-D view."""
        if not dpg.does_item_exist("splice_lines"):
            return
        dpg.delete_item("splice_lines", children_only=True)
        ed = self.editor_rect()
        if not ed:
            return
        over = list(self.app.overlay_holes()) if hasattr(self.app, "overlay_holes") else []
        mini = self.minimap_rect()
        if mini:
            over.append(mini)

        def shown(x, y):
            return (ed[0] <= x <= ed[2] and ed[1] <= y <= ed[3]
                    and not any(r[0] <= x <= r[2] and r[1] <= y <= r[3] for r in over))

        from native import chrome
        col = tuple(chrome.ACCENT[:3]) + (235,)          # the accent as it is now (Appearance may change it)
        for p0, p1 in curves:
            if not p0 or not p1:
                continue
            dd = max(50.0, abs(p1[0] - p0[0]) * 0.5)
            c0, c1 = (p0[0] + dd, p0[1]), (p1[0] - dd, p1[1])
            # sampled about every 3 px along the control polygon: a run ends within a sample of an edge
            span = (abs(c0[0] - p0[0]) + abs(c1[0] - c0[0]) + abs(p1[0] - c1[0])
                    + abs(c1[1] - c0[1]) + abs(p1[1] - p0[1]))
            n = int(max(24, min(600, span / 3)))
            run = []
            for k in range(n + 1):
                u = k / n; v = 1 - u
                x = v ** 3 * p0[0] + 3 * v * v * u * c0[0] + 3 * v * u * u * c1[0] + u ** 3 * p1[0]
                y = v ** 3 * p0[1] + 3 * v * v * u * c0[1] + 3 * v * u * u * c1[1] + u ** 3 * p1[1]
                if shown(x, y):
                    run.append((x, y))
                    continue
                if len(run) > 1:
                    dpg.draw_polyline(run, parent="splice_lines", thickness=self.px(4), color=col)
                run = []
            if len(run) > 1:
                dpg.draw_polyline(run, parent="splice_lines", thickness=self.px(4), color=col)
    # AI: end

    def _node_edge(self, nid, side):
        """A point on a node's left or right edge, for a pin it hides."""
        st = dpg.get_item_state(f"gnode_{nid}")
        if "rect_min" not in st:
            return None
        (x0, y0), (x1, y1) = st["rect_min"], st["rect_max"]
        return (x0 if side == "in" else x1, (y0 + y1) / 2)

    def _splice_clear(self):
        if self._splice:
            lid = self._splice[1]
            self._splice = None
            self._restyle_wire(lid)                  # its own theme, or lit or faded as the others
        if dpg.does_item_exist("splice_lines"):
            dpg.delete_item("splice_lines", children_only=True)

    def _splice_apply(self):
        """The drop: the node into the wire, the node downstream pushed
        right if the two now overlap."""
        nid, lid, a, out, b, inp, my_in, my_out = self._splice
        self._splice_clear()
        if nid not in self.graph.nodes or a not in self.graph.nodes or b not in self.graph.nodes:
            return
        if self._would_loop([(a, out, nid, my_in), (nid, my_out, b, inp)]):
            self.status("that would make a loop - a value can only come round through a Delay (wire it to an input, and one goes on it)", "warning"); return
        self.snapshot(); self._sync_pos()
        self.graph.link(a, out, nid, my_in)
        self.graph.link(nid, my_out, b, inp)
        pn, sn = self.graph.nodes[nid]["pos"], self._node_size(nid)
        pb, sb = self.graph.nodes[b]["pos"], self._node_size(b)
        if pb[0] < pn[0] + sn[0] + 20 and pb[0] + sb[0] > pn[0] and abs(pb[1] - pn[1]) < max(sn[1], sb[1]):
            self.graph.nodes[b]["pos"][0] = pn[0] + sn[0] + 40
        self.rebuild()
        self.status(f"spliced into the wire {self.pin_words(a, out)} -> {self.pin_words(b, inp)}", node=self.where(nid))

    def knife_start(self):
        """Ctrl+right-drag: the line drawn cuts every wire it crosses."""
        if not self.graph or not dpg.does_item_exist("node_editor") or not dpg.is_item_hovered("node_editor"):
            return False
        self._knife = tuple(dpg.get_mouse_pos(local=False))
        return True

    def knife_drag(self):
        if not self._knife or not dpg.does_item_exist("knife_line"):
            return
        mx, my = dpg.get_mouse_pos(local=False)
        dpg.configure_item("knife_line", p1=self._knife, p2=(mx, my), show=True)

    def knife_end(self):
        if not self._knife:
            return
        a = self._knife; b = tuple(dpg.get_mouse_pos(local=False))
        self._knife = None
        if dpg.does_item_exist("knife_line"):
            dpg.configure_item("knife_line", show=False)
        if abs(b[0] - a[0]) + abs(b[1] - a[1]) < 8 or not self.graph:
            return
        cut = []
        for lid, (nb, inp) in list(self.links.items()):
            pts = self._wire_points(lid)
            if pts and any(self._segs_cross(a, b, pts[k], pts[k + 1]) for k in range(len(pts) - 1)):
                cut.append((nb, inp))
        if not cut:
            self.status("the knife crossed no wire"); return
        self.snapshot()
        for nb, inp in cut:
            self.graph.unlink(nb, inp)
        self.rebuild()
        self.status(f"{len(cut)} wire(s) cut")

    def delete_selected(self):
        """The selection gone: what imnodes has and what the keys added (A,
        Ctrl+[ ...) - it used to take imnodes' alone, and a selection made
        by key stayed."""
        sel = self._selected() if self.graph else []
        if not sel:
            self.status("select nodes first"); return
        self.snapshot()
        self.ext_sel = []
        for nid in sel:
            self.graph.remove(nid)
        # drawn again from the graph, as cut and dissolve are. Deleting the
        # node items one by one left a wire from a removed node's OUTPUT in
        # the editor (Dear PyGui does not take it with the node), tied to a
        # freed pin: the next rebuild - an undo, a zoom - crashed on it
        # (issue #4). The nodes that lost an input wire get its field back too.
        self.rebuild()
        self.status(f"deleted {len(sel)} node(s)")

    # --- compile -------------------------------------------------------------------------
    # --- pin preview ---------------------------------------------------------------------
    # "Preview this output" builds the graph with that pin shown instead of
    # the Output: a colour straight, a float or bool as a grey level. The
    # effect is a draft named Preview; the graph's own file is untouched,
    # and every compile while the preview is on shows the pin.
    PREVIEW_FILE = "_preview.cpp"

    def preview_pin(self, nid, name):
        self.preview = (nid, name)
        self.status(f"previewing {self.graph.nodes[nid]['type']} . {nodeface.label(self.graph.nodes[nid]['type'], name)}")
        self._sync_pos(); self.rebuild()               # the node grows a thumbnail
        self.compile()

    def _thumb_texture(self):
        if not dpg.does_item_exist("preview_thumb_tex"):
            from native.textures import registry
            dpg.add_raw_texture(THUMB_PX, THUMB_PX, np.zeros(THUMB_PX * THUMB_PX * 4, np.float32),
                                format=dpg.mvFormat_Float_rgba, tag="preview_thumb_tex", parent=registry())

    def update_thumb(self, net):
        """The previewed node's picture: the net, resampled to the thumbnail
        (nearest, so the LEDs stay square)."""
        if not self.preview or not dpg.does_item_exist(f"gthumb_{self.preview[0]}") or net is None:
            return
        h, w = net.shape[:2]
        ys = (np.arange(THUMB_PX) * h // THUMB_PX)
        xs = (np.arange(THUMB_PX) * w // THUMB_PX)
        small = net[ys][:, xs]
        buf = self._thumb_buf if getattr(self, "_thumb_buf", None) is not None else np.ones((THUMB_PX, THUMB_PX, 4), np.float32)
        self._thumb_buf = buf
        np.multiply(small, np.float32(1.0 / 255.0), out=buf[..., :3], casting="unsafe")
        dpg.set_value("preview_thumb_tex", buf.reshape(-1))

    def stop_preview(self):
        self.preview = None
        p = self.app.project
        if self.PREVIEW_FILE in p.effect_files():
            os.remove(p.effect_path(self.PREVIEW_FILE))
        self._sync_pos(); self.rebuild()
        self.compile()

    def _preview_graph(self):
        """A copy of the graph with the previewed pin driving a fresh Output."""
        nid, name = self.preview
        if nid not in self.graph.nodes:
            self.preview = None
            return None
        g = G.Graph(self.graph.to_json(), lib=self.lib, resolver=self.resolve_sub)
        g.project_dir = self.app.project.path
        for o in [m for m, n in g.nodes.items() if n["type"] == "Output"]:
            g.remove(o)
        d = g.node_def(g.nodes[nid])
        t = next((o["type"] for o in d["outputs"] if o["name"] == name), "float")
        pos = g.nodes[nid]["pos"]
        out = g.add("Output", (pos[0] + 400, pos[1]))
        if t == "color":
            g.link(nid, name, out, "color")
        else:
            hsv = g.add("HSV", (pos[0] + 200, pos[1]))
            g.nodes[hsv]["inputs"] = {"h": 0.0, "s": 0.0}
            g.link(nid, name, hsv, "v")
            g.link(hsv, "color", out, "color")
        g.name = "Preview"
        return g

    def compile(self, and_build=True, auto=False):
        """Graph -> effects/<graph>.cpp -> the normal build and reload. `auto`:
        Live's - nothing is written or built when the engine runs this code
        already (an edit that changed none: a zoom, a label, the graph opened)."""
        if not self.graph:
            return
        self.save()
        g = self.graph
        fname = os.path.splitext(self.file)[0] + ".cpp"
        if self.preview:
            g = self._preview_graph()
            if g is not None:
                fname = self.PREVIEW_FILE
        try:
            src = (g or self.graph).compile()
            same = auto and and_build and not self.preview and self._engine_has(fname, src)
            self._probes = dict(getattr(g or self.graph, "probes", {}) or {})
            self._probe_scope = dict(getattr(g or self.graph, "last_scope", {}) or {})
            self._probes_for = fname
            self._live = {v: k for k, v in (getattr(g or self.graph, "live", {}) or {}).items()}   # (nid, input, comp) -> slot
            # which node wrote each line, for a build that fails (build_failed); the text too, so a
            # file edited by hand since is not blamed on the nodes
            self._line_map = (fname, dict(getattr(g or self.graph, "line_nodes", None) or {}), src)
            if not same:
                self._clear_build_problems()                   # new text: the last build's word on it is old
                self._costs = None                             # and what each node cost was measured on the old
        except G.GraphError as e:
            self._mark_problems()
            at = messages.held(f"problem:{self._key()}:")
            if at:
                # the nodes' problems are held already and say where: this is their consequence, and goes to the first
                self.status(f"{self.file} does not compile: {e}", "error", node=at[0]["node"])
            else:                                                            # held until it does; goes to the graph
                self.status(f"{self.file} does not compile: {e}", "error", key=f"graph:{self._key()}",
                            node=(self.file, None, self.cur_dir == self.sub_dir))
            return None
        messages.clear(self.app, f"graph:{self._key()}")
        self._mark_problems()
        if same:
            if self.standin_on():
                self._standin_back()                             # an edit undone before its build: the build is the graph
            return fname                                         # the engine runs this code: nothing to write or build
        self.app.project.write_effect(fname, src)
        if and_build and self._standin_at != self.edits:
            self.standin(g or self.graph, fname)                 # the edit on the cube while it builds
        self.status(f"wrote {fname}" + (f" (previewing {self.preview[1]} of #{self.preview[0]})" if self.preview else "")
                    + (" - the sim runs it as a script until its build lands" if and_build and self.standin_on() else ""))
        if and_build:
            if self.app.building:
                self._queued = True                              # made when the build in hand lands (poll)
            else:
                self._built_at = self.edits                      # the graph as this build has it
            # the code pane follows: edit_build saves what the pane holds, and
            # that must be this file, not whatever was open before
            self.app.edit_open(fname)
            self.app.edit_build()
        return fname

    def regenerate(self, files):
        """The C++ of every listed effect that comes from a graph, written
        afresh by the compiler as it is now - before an export or a flash,
        so an old generation never ships. Returns the names regenerated."""
        if self.graph:
            self.save()
        self.refresh_lib()
        done = []
        for fname in files:
            path = os.path.join(self.dir, os.path.splitext(fname)[0] + ".json")
            if not os.path.exists(path):
                continue
            try:
                g = G.load(path, lib=self.lib, resolver=self.resolve_sub)
                g.project_dir = self.app.project.path
                self.app.project.write_effect(fname, g.compile())
                done.append(fname)
            except Exception as e:
                self.status(f"{fname}: {e}")
        return done

    def type_names(self):
        cats = {}
        # editing a sub-graph: neither itself nor one that holds it is offered - either made it contain itself
        here = self.file[:-5] if self.cur_dir == self.sub_dir and self.file else None
        for n, d in self.lib.items():
            if here and n.startswith(G.SUB) and (n[len(G.SUB):] == here or self._contains(n[len(G.SUB):], here)):
                continue
            cats.setdefault(d["cat"], []).append(n)
        out = []
        for c in ("controls", "signals", "coords", "generate", "maths", "colour", "graph", "subgraphs", "custom", "output"):
            out += [f"{c} / {n}" for n in sorted(cats.pop(c, []))]
        for c, ns in sorted(cats.items()):
            out += [f"{c} / {n}" for n in sorted(ns)]
        return out


def _node_extras(n):
    """What a node carries besides its type, place, settings and typed inputs - exposed pins, mute, label,
    colour, folded, hidden pins, a modulator, and whatever is added later - as copies. Paste and folding into
    a sub-graph rebuilt nodes from the four alone: an exposed pin was gone (and the wire to it dropped), and a
    muted node folded away ran."""
    import copy
    return {k: copy.deepcopy(v) for k, v in n.items() if k not in ("id", "type", "pos", "params", "inputs")}


def build_panel(app, panel):
    """The graph pane's widgets. Called once from build()."""
    # One row: which graph (the messages are the footer's, in every layout -
    # messages.py). Everything else is on the menus and the toolbar
    # (chrome.py) or the right-click menu.
    from native.chrome import grip
    grip("graph_win")
    with dpg.group(horizontal=True):
        dpg.add_button(label="< back", tag="graph_back", show=False, callback=lambda: panel.back())
        with dpg.group(horizontal=True, tag="graph_crumbs", show=False):     # inside a sub-graph: the trail down to it
            pass
        dpg.add_combo(panel.files(), tag="graph_file", width=px(220), default_value=panel.file or "",
                      callback=lambda s, v: panel.open_top(v))
    with dpg.file_dialog(directory_selector=False, show=False, tag="graph_import_dialog", width=px(620), height=px(420),
                         callback=lambda s, a: panel.import_bundle(a.get("file_path_name", ""))):
        dpg.add_file_extension(".json", color=(120, 200, 120))
        dpg.add_file_extension(".*")
    # The description box: a fixed height, whatever the text - a line that
    # grew and shrank with each hover moved the editor under the pointer.
    # The bar under it drags to resize; the height is remembered.
    with dpg.child_window(tag="graph_help_box", height=int(__import__("native.project", fromlist=["x"]).pref_num(app.prefs, "help_h", HELP_H)), border=False,
                          no_scrollbar=True, no_scroll_with_mouse=True):
        dpg.add_text("", tag="graph_help", color=(170, 178, 192), wrap=0)
    dpg.add_button(label="", tag="help_split", width=-1, height=px(5))
    with dpg.node_editor(tag="node_editor", callback=panel.on_link, delink_callback=panel.on_delink,
                         minimap=bool(app.prefs.get("minimap", True)), minimap_location=dpg.mvNodeMiniMap_Location_BottomRight,
                         width=-1, height=-1):
        pass
    # The right-click menu: a small window shown at the pointer, categories as
    # collapsing headers, a node per line. A window rather than a popup so it
    # can be positioned exactly and dismissed by the click that adds.
    # an expression typed into a field: a small box at the pointer (= over a value, or a menu row)
    with dpg.window(tag="expr_win", show=False, no_title_bar=True, no_resize=True, no_move=True, autosize=True, popup=True):
        dpg.add_text("", tag="expr_label", color=DIM)
        typeface.mono(dpg.add_input_text(tag="expr_text", width=px(240), on_enter=True, callback=lambda s, v: app.gp.expr_enter(v)))
        dpg.add_text("2*pi, x*2 (x: the value now), sqrt(2), min(a, 4)...", tag="expr_hint", color=DIM, wrap=px(240))
    with dpg.window(tag="graph_ctx", show=False, no_title_bar=True, no_resize=True, no_move=True,
                    autosize=True, popup=True):
        pass
    with dpg.window(tag="graph_menu", show=False, no_title_bar=True, no_resize=True, no_move=True,
                    autosize=True, popup=True):
        pass
    panel.fill_add_menu()
