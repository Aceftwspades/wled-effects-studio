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
import numpy as np

from native import graph as G
from native import nodeface
from native.glyphs import Glyphs
from native.nodedefs import library

DIM = (139, 147, 163)
PIN_COL = {"vector": (190, 120, 235),"float": (110, 190, 250), "color": (250, 170, 90), "bool": (170, 230, 120)}
GREY = (70, 74, 84)
NODE_W = 150            # inner width every node is laid out to
WIRE_COLOURS = [("type colour", None), ("white", (235, 235, 235)), ("red", (235, 80, 70)),
                ("orange", (250, 160, 60)), ("yellow", (240, 220, 80)), ("green", (120, 220, 110)),
                ("cyan", (90, 220, 230)), ("blue", (100, 150, 250)), ("magenta", (230, 100, 220)),
                ("grey", (130, 135, 145))]
CHAR_W = 7.2            # the default font at 13 px, near enough to right-align by


NARROW_W = 46           # a knot: just wide enough for its two pin names
ZOOMS = (0.1, 0.15, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.85, 1.0, 1.2, 1.4, 1.7, 2.0)
OVERVIEW_ZOOM = 0.5     # below this the nodes are stand-ins (Settings > Simplified nodes below)
OVERVIEW_CHOICES = ((0.7, "70%"), (0.5, "50%"), (0.4, "40%"), (0.3, "30%"), (0.0, "never"))
BASE_FONT = 13          # the size everything above is laid out for
HELP_H = 46             # the description box, px: two lines
THUMB = 96              # the preview thumbnail on a node, layout px
PAD = 56                # an XY pad on a node, layout px (its texture is PAD_PX square)
PAD_PX = 56
THUMB_PX = 96           # its texture


def _right(text, width=NODE_W, char_w=CHAR_W):
    """Indent that puts `text` against the node's right edge, so an output's
    name sits beside its pin on the right the way an input's sits beside its
    pin on the left. Inputs left, outputs right, on every node."""
    return max(0, int(width - len(text) * char_w))


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


class PinThemes:
    """One theme per pin type, lit and greyed, and one per link type. Built
    once; bound to attributes and links so the wires are the colour of what
    flows through them and a pin that cannot take the drag goes grey."""
    def __init__(self):
        self.pin, self.grey, self.link = {}, {}, {}
        for t, col in PIN_COL.items():
            self.pin[t] = self._attr_theme(col, col)
            self.grey[t] = self._attr_theme(GREY, GREY)
            with dpg.theme() as th:
                with dpg.theme_component(dpg.mvNodeLink):
                    dpg.add_theme_color(dpg.mvNodeCol_Link, col, category=dpg.mvThemeCat_Nodes)
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


class GraphPanel(Glyphs):
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
        self._log_sliders = {}   # slider -> unit: the sliders that hold a logarithm (set_value takes a log)
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
        self._fonts = {}         # px size -> font
        self._node_font = None   # the font at this zoom, bound to each node as it is made
        self._standin_line = {}  # nid -> the height a stand-in gives its summary line (0: none)
        self._font_file = _font_file()
        self._zoom_themes = {}   # zoom -> node-editor style theme
        self._node_themes = {}   # (r,g,b) -> a node theme with that title bar
        self.focus_mode = False  # dim everything but the selection and its neighbours
        self.edits = 0           # bumped by touch(); what the autosave watches
        self._focus_sel = None
        self._link_normal = {}   # dpg link id -> the theme it wears when not dimmed
        self._label_items = []   # the wire labels drawn last frame
        self._readout_items = [] # the live readouts drawn last frame, on the frame-scope output pins
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
        self._add_preview = None # the node type the add menu is describing in the properties pane
        self._menu_entries_cache = None
        self._press_pos = {}     # node -> position at the last press (a drop onto a wire)
        self._undo_desc = []     # what each undo snapshot precedes
        self.auto = False        # live preview: rebuild after every edit
        self._dirty = 0.0        # time of the last edit not yet built, 0 when clean
        self._queued = False     # an edit landed while a build was running
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

    # --- sub-graphs as node types ------------------------------------------------------
    def resolve_sub(self, ident):
        """The Graph for a sub-graph node type, by file stem. Cached until
        refresh_lib(), which runs whenever one is saved."""
        if ident not in self._subs:
            path = os.path.join(self.sub_dir, ident + ".json")
            if not os.path.exists(path):
                return None
            self._subs[ident] = G.load(path, lib=self.lib, resolver=self.resolve_sub)
            self._subs[ident].project_dir = self.app.project.path
        return self._subs[ident]

    def refresh_lib(self):
        """Rebuild the library: the built-ins, the user nodes, and one node
        type per sub-graph file, its pins read from the boundary nodes."""
        self._subs.clear()
        self.lib = library(self._user_nodes())
        for f in self.sub_files():
            ident = f[:-5]
            sub = self.resolve_sub(ident)
            if sub is not None:
                self.lib[G.SUB + ident] = G.sub_def(ident, sub)
        if self.graph is not None:
            self.graph.lib = self.lib
        if dpg.does_item_exist("graph_add_type"):
            dpg.configure_item("graph_add_type", items=self.type_names())
        self.fill_add_menu()

    def new(self, name):
        name = (name or "").strip() or "New Graph"
        fname = G._ident(name) + ".json"
        n = 2
        while os.path.exists(os.path.join(self.dir, fname)):
            fname = f"{G._ident(name)}_{n}.json"; n += 1
        g = G.starter(name, lib=self.lib, resolver=self.resolve_sub)
        G.save(g, os.path.join(self.dir, fname))
        self.open(fname)

    def open(self, fname, sub=False):
        if not fname:
            return
        self.refresh_lib()
        if self.graph is None:
            self.zoom = min(ZOOMS[-1], max(ZOOMS[0], float(self.app.prefs.get("zoom", 1.0))))
        self.offset = [0.0, 0.0]
        d = self.sub_dir if sub else self.dir
        self.graph = G.load(os.path.join(d, fname), lib=self.lib, resolver=self.resolve_sub)
        self.graph.project_dir = self.app.project.path
        self.graph.features = self.features()
        self.file = fname
        self.cur_dir = d
        self._undo.clear(); self._redo.clear(); self._last_snap = None; self._undo_desc.clear(); self.ext_sel = []
        self.preview = None
        self.rebuild()
        dpg.configure_item("graph_file", items=self.files())
        dpg.set_value("graph_file", fname if not sub else "")
        dpg.configure_item("graph_back", show=bool(self.stack))
        self._crumbs()
        stray = getattr(self.graph, "stray", None) or []
        self.status(("sub-graph " if sub else "") + fname
                    + (f" - {len(stray)} wire(s) to nodes or pins that are not there dropped" if stray else ""))
        self.app.refresh_import_buttons()

    def save(self):
        if not self.graph:
            return
        # the nodes' places as the editor shows them, back in graph units: the
        # editor's grid is the graph scaled by the zoom and shifted by the pan,
        # and writing the grid position raw halved a graph at 50% on every
        # save (and every Live compile saves) until it was a heap at the origin
        self._sync_pos()
        path = os.path.join(self.cur_dir or self.dir, self.file)
        if os.path.exists(path):
            from native import history
            import json
            try:
                old = open(path, encoding="utf-8").read()
            except OSError:
                old = ""
            if old != json.dumps(self.graph.to_json(), indent=1):
                history.keep(self.app.project, "subgraphs" if self.cur_dir == self.sub_dir else "graphs",
                             self.file[:-5], ".json", old)
        G.save(self.graph, path)
        self.status(f"{self.file} saved")
        if self.cur_dir == self.sub_dir:
            self._subs.pop(self.file[:-5], None)     # its pins may have changed

    def effect_file(self):
        """The effect file this graph generates, or None with no graph open."""
        return os.path.splitext(self.file)[0] + ".cpp" if self.file else None

    def rename(self, name):
        """The graph, its file and its generated effect take a new name. A
        sub-graph's name is also its node type, so every graph that uses it
        is rewritten to the new one."""
        name = (name or "").strip()
        if not name or not self.graph:
            self.status("type the new name in the box first")
            return
        self.save()
        old_stem = os.path.splitext(self.file)[0]
        new_stem = G._ident(name)
        d = self.cur_dir or self.dir
        n = 2
        while new_stem != old_stem and os.path.exists(os.path.join(d, new_stem + ".json")):
            new_stem = f"{G._ident(name)}_{n}"; n += 1
        self.graph.name = name
        if new_stem != old_stem:
            os.remove(os.path.join(d, self.file))
            self.file = new_stem + ".json"
        G.save(self.graph, os.path.join(d, self.file))
        proj = self.app.project
        old_cpp, new_cpp = old_stem + ".cpp", new_stem + ".cpp"
        if old_cpp in proj.effect_files():
            if new_cpp != old_cpp and new_cpp in proj.effect_files():
                os.remove(proj.effect_path(new_cpp))
            proj.rename_effect(old_cpp, name)      # keeps the list entry, regenerated below anyway
        if d == self.sub_dir and new_stem != old_stem:
            # the node type changed: rewrite every graph that uses this sub-graph
            for gd in (self.dir, self.sub_dir):
                for f in os.listdir(gd):
                    if not f.endswith(".json") or (gd == d and f == self.file):
                        continue
                    p = os.path.join(gd, f)
                    txt = open(p, encoding="utf-8").read()
                    if f'"{G.SUB}{old_stem}"' in txt:
                        open(p, "w", encoding="utf-8").write(txt.replace(f'"{G.SUB}{old_stem}"', f'"{G.SUB}{new_stem}"'))
        self.refresh_lib()
        self.open(self.file, sub=(d == self.sub_dir))
        self.status(f"renamed to {name}")
        if self.app.edit_file == old_cpp:
            self.app.edit_file = new_cpp if new_cpp in proj.effect_files() else None
        self.compile()

    # --- sub-graphs: in and out --------------------------------------------------------
    def enter_sub(self, nid):
        """Open the sub-graph a node stands for; back returns to here."""
        n = self.graph.nodes.get(nid)
        if not n or not n["type"].startswith(G.SUB):
            return
        self.save()
        self.stack.append((self.cur_dir, self.file))
        self.open(n["type"][len(G.SUB):] + ".json", sub=True)

    def back(self, levels=1):
        """Up one sub-graph (or `levels`), to where the trail came from."""
        if not self.stack:
            return
        self.save()
        for _ in range(max(1, levels)):
            if not self.stack:
                break
            d, f = self.stack.pop()
        self.open(f, sub=(d == self.sub_dir))

    def _crumbs(self):
        """The breadcrumbs: every graph on the way down, each a button
        back to it, then the one open - shown inside a sub-graph only."""
        if not dpg.does_item_exist("graph_crumbs"):
            return
        dpg.delete_item("graph_crumbs", children_only=True)
        if not self.stack:
            dpg.configure_item("graph_crumbs", show=False); return
        depth = len(self.stack)
        for k, (d, f) in enumerate(self.stack):
            dpg.add_button(label=os.path.splitext(f)[0], small=True, parent="graph_crumbs", user_data=depth - k,
                           callback=lambda s, a, u: self.back(u))
            dpg.add_text("›", parent="graph_crumbs", color=DIM)
        from native import chrome
        dpg.add_text(os.path.splitext(self.file or "")[0], parent="graph_crumbs", color=chrome.ACCENT)
        dpg.configure_item("graph_crumbs", show=True)

    def make_sub_from_selection(self, name=None):
        """The selected nodes become one sub-graph node. Wires crossing the
        boundary become the new node's pins - a Graph input for each link
        coming in, named after the pin it fed; a Graph output for each
        distinct output feeding out, named after it - and the parent is
        rewired through the new node in their place."""
        if not self.graph:
            return
        sel = [nid for nid in self._selected() if nid in self.graph.nodes and self.graph.nodes[nid]["type"] not in ("Output",)]
        if not sel:
            self.status("select the nodes to fold first")
            return
        self.snapshot()
        self.save()                                   # positions
        g = self.graph
        S = set(sel)
        name = (name or "").strip() or f"Sub {len(self.sub_files()) + 1}"
        ident = G._ident(name)
        while os.path.exists(os.path.join(self.sub_dir, ident + ".json")):
            ident += "_2"
        sub = G.Graph({"name": name}, lib=self.lib, resolver=self.resolve_sub)
        # the chosen nodes, moved so the group starts near the origin
        x0 = min(g.nodes[n]["pos"][0] for n in S); y0 = min(g.nodes[n]["pos"][1] for n in S)
        smap = {}
        for nid in sel:
            n = g.nodes[nid]
            smap[nid] = sub.add(n["type"], (n["pos"][0] - x0 + 260, n["pos"][1] - y0 + 40), dict(n.get("params", {})))
            sub.nodes[smap[nid]]["inputs"] = dict(n.get("inputs", {}))
        for a, o, b, i in g.links:
            if a in S and b in S:
                sub.link(smap[a], o, smap[b], i)
        # boundary: in
        in_pins, in_nodes = {}, {}     # (a, o) outside -> pin name ; pin -> Graph input id
        y = 40
        for a, o, b, i in g.links:
            if a not in S and b in S:
                key = (a, o)
                if key not in in_pins:
                    pin = i
                    k = 2
                    while pin in in_nodes:
                        pin = f"{i}{k}"; k += 1
                    t = next((x["type"] for x in g.node_def(g.nodes[a])["outputs"] if x["name"] == o), "float")
                    in_pins[key] = pin
                    in_nodes[pin] = sub.add("Graph input", (20, y), {"name": pin, "type": t, "default": 0.0}); y += 135
                sub.link(in_nodes[in_pins[key]], "value", smap[b], i)
        # boundary: out
        out_pins, out_nodes = {}, {}
        y = 40
        xmax = max(sub.nodes[n]["pos"][0] for n in smap.values()) + 260 if smap else 500
        for a, o, b, i in g.links:
            if a in S and b not in S:
                key = (a, o)
                if key not in out_pins:
                    pin = o
                    k = 2
                    while pin in out_nodes:
                        pin = f"{o}{k}"; k += 1
                    t = next((x["type"] for x in g.node_def(g.nodes[a])["outputs"] if x["name"] == o), "float")
                    out_pins[key] = pin
                    out_nodes[pin] = sub.add("Graph output", (xmax, y), {"name": pin, "type": t}); y += 110
                    sub.link(smap[a], o, out_nodes[pin], "value")
        G.save(sub, os.path.join(self.sub_dir, ident + ".json"))
        self.refresh_lib()
        # the parent: one node where the group was
        cx = sum(g.nodes[n]["pos"][0] for n in S) / len(S); cy = sum(g.nodes[n]["pos"][1] for n in S) / len(S)
        new = g.add(G.SUB + ident, (cx, cy))
        outer_in = [(a, o, b, i) for a, o, b, i in g.links if a not in S and b in S]
        outer_out = [(a, o, b, i) for a, o, b, i in g.links if a in S and b not in S]
        for nid in sel:
            g.remove(nid)
        for a, o, b, i in outer_in:
            g.link(a, o, new, in_pins[(a, o)])
        for a, o, b, i in outer_out:
            g.link(new, out_pins[(a, o)], b, i)
        self.rebuild()
        self.save()
        self.status(f"folded {len(sel)} nodes into sub-graph '{name}'")

    def status(self, msg):
        if dpg.does_item_exist("graph_status"):
            dpg.set_value("graph_status", msg)

    # --- help: what is under the pointer ---------------------------------------------
    # A tooltip inside a node crashes the node editor, so the help is a
    # line of its own under the status: hover a pin and it names the pin
    # and says what to plug in or what comes out; hover a node's title and
    # it says what the node is for. Checked a few times a second.
    def help(self, text):
        if dpg.does_item_exist("graph_help") and dpg.get_value("graph_help") != text:
            dpg.set_value("graph_help", text)

    # --- properties: the selected node's long text, in a wide box under the toolbar ----
    def _poll_props(self):
        if not dpg.does_item_exist("graph_props") or not self.graph:
            return
        if self._add_preview is not None:
            return                                        # the add menu is describing a node there
        sel = self._selected()
        key = (self.file, sel[0]) if sel else None
        if key == getattr(self, "_props_for", "unset"):
            return
        self._props_for = key
        # the pane is always there (its own pane, sized by the layout): what
        # changes is what it says, never the editor beside it
        dpg.delete_item("graph_props", children_only=True)
        if not sel:
            dpg.add_text("select a node: its longer settings (text, files) are edited here",
                         parent="graph_props", color=DIM, wrap=0)
            return
        nid = sel[0]
        n = self.graph.nodes.get(nid)
        if not n:
            return
        d = self.graph.node_def(n)
        title = f"{n.get('label') or d.get('label') or n['type']} #{nid}"
        if n.get("label"):
            title += f"  ({n['type']})"
        dpg.add_text(title, parent="graph_props")
        if len(sel) > 1:
            dpg.add_text(f"and {len(sel) - 1} more selected", parent="graph_props", color=DIM)
        long_ = [p for p in d["params"] if p["type"] in ("text", "file") and not p.get("lines") is False]
        curves = [p for p in d["params"] if p["type"] == "curve"]
        self._curve_ed = None
        self._bitmap_ed = None
        if n["type"] == "Bitmap":
            # the bitmap painted: a grid of cells, the left button sets the pen's digit, the right clears
            self._build_bitmap_editor(nid, "rows")
        for p in curves:
            # a curve drawn by hand: click to add a point, drag one, right-click to take it out
            dpg.add_text(f"{p['name']} - click to add a point, drag to move, right-click to remove", parent="graph_props", color=DIM, wrap=0)
            W = max(200, int(dpg.get_item_rect_size("graph_props")[0] or 300) - 24)
            H = 180
            tag = dpg.add_drawlist(width=W, height=H, parent="graph_props")
            self._curve_ed = {"nid": nid, "name": p["name"], "tag": tag, "W": W, "H": H, "drag": None, "was": False, "rwas": False}
            self._curve_draw()
        if not long_ and not curves:
            dpg.add_text("all of this node's settings are on the node", parent="graph_props",
                         color=DIM, wrap=0)
            return
        for p in long_:
            v = str(n["params"].get(p["name"], p["default"]))
            shown = v.replace("/", "\n") if p.get("lines") else v
            dpg.add_text(p["name"], parent="graph_props", color=DIM)
            dpg.add_input_text(parent="graph_props", width=-1, multiline=bool(p.get("lines")) or len(v) > 60,
                               height=self.px(120) if p.get("lines") else 0, default_value=shown,
                               user_data=(nid, p["name"]), callback=self._on_prop)

    # --- the bitmap painter in the properties pane ----------------------------------------
    BITMAP_STATES = "0123456789"

    def _bitmap_rows(self, nid, name):
        n = self.graph.nodes.get(nid) if self.graph else None
        if not n:
            return None, None
        d = self.graph.node_def(n)
        p = next((q for q in d["params"] if q["name"] == name), None)
        text = str(n["params"].get(name, p["default"] if p else "")).replace("\n", "/")
        rows = [r for r in text.split("/")]
        if not rows:
            rows = ["0"]
        w = max(1, max(len(r) for r in rows))
        rows = [(r + "." * w)[:w] for r in rows]           # a dot is an empty pixel; a digit a coloured slot
        return n, rows

    def _build_bitmap_editor(self, nid, name):
        n, rows = self._bitmap_rows(nid, name)
        if n is None:
            return
        dpg.add_text(f"{name} - paint: the left button sets the pen's digit (a colour slot for Colour pick), the right "
                     "empties a pixel (a dot); drag to paint a run", parent="graph_props", color=DIM, wrap=0)
        with dpg.group(horizontal=True, parent="graph_props"):
            dpg.add_text("pen", color=DIM)
            dpg.add_combo(list(self.BITMAP_STATES), tag="bitmap_pen", width=44, default_value="1",
                          callback=lambda s, v: self._bitmap_ed.__setitem__("pen", v))
            dpg.add_button(label="empty", small=True, callback=lambda: self._bitmap_fill("."))
            dpg.add_button(label="fill", small=True, callback=lambda: self._bitmap_fill(None))
        with dpg.group(horizontal=True, parent="graph_props"):
            dpg.add_text("size", color=DIM)
            for lbl, dc, dr in (("+col", 1, 0), ("-col", -1, 0), ("+row", 0, 1), ("-row", 0, -1)):
                dpg.add_button(label=lbl, small=True, user_data=(dc, dr), callback=lambda s, a, u: self._bitmap_resize(*u))
        W = max(200, int(dpg.get_item_rect_size("graph_props")[0] or 300) - 24)
        cols, nrows = len(rows[0]), len(rows)
        cell = max(6, min(28, W // cols, 200 // nrows))
        tag = dpg.add_drawlist(width=cols * cell + 1, height=nrows * cell + 1, parent="graph_props")
        self._bitmap_ed = {"nid": nid, "name": name, "tag": tag, "cell": cell, "pen": "1", "was": False, "rwas": False, "stroke": None}
        self._bitmap_draw()

    def _bitmap_draw(self):
        ed = self._bitmap_ed
        if not ed or not dpg.does_item_exist(ed["tag"]):
            return
        n, rows = self._bitmap_rows(ed["nid"], ed["name"])
        if n is None:
            return
        cell, tag = ed["cell"], ed["tag"]
        dpg.delete_item(tag, children_only=True)
        # ten slots, ten tints (Colour pick gives each its colour; here they are told apart)
        tints = [(235, 235, 235), (110, 190, 250), (250, 170, 90), (170, 230, 120), (250, 110, 120), (190, 120, 235),
                 (250, 230, 100), (90, 220, 210), (240, 150, 200), (160, 160, 90)]
        for r, row in enumerate(rows):
            for c, ch in enumerate(row):
                on = ch.isdigit()
                fill = tints[int(ch)] + (255,) if on else (28, 30, 36, 255)
                dpg.draw_rectangle((c * cell, r * cell), ((c + 1) * cell, (r + 1) * cell), color=(60, 64, 74, 255), fill=fill, parent=tag)
                if on and cell >= 12 and ch != "1":
                    dpg.draw_text((c * cell + cell * 0.3, r * cell + cell * 0.12), ch, size=max(8, cell - 6), color=(20, 22, 26, 255), parent=tag)

    def _bitmap_set(self, rows, text):
        n = self.graph.nodes[self._bitmap_ed["nid"]]
        n["params"][self._bitmap_ed["name"]] = text if text is not None else "/".join(rows)

    def _bitmap_resize(self, dc, dr):
        ed = self._bitmap_ed
        n, rows = self._bitmap_rows(ed["nid"], ed["name"])
        if n is None:
            return
        w, h = len(rows[0]) + dc, len(rows) + dr
        if w < 1 or h < 1 or w > 64 or h > 64:
            return
        self.touch(); self.snapshot("bitmap size")
        rows = [(r + "." * w)[:w] for r in rows][:h] + ["." * w] * max(0, h - len(rows))
        self._bitmap_set(rows, None)
        self._sync_pos(); self.rebuild()

    def _bitmap_fill(self, ch):
        ed = self._bitmap_ed
        n, rows = self._bitmap_rows(ed["nid"], ed["name"])
        if n is None:
            return
        self.touch(); self.snapshot("bitmap fill")
        if ch is None:                                    # fill: every pixel the pen's digit
            ch = ed["pen"]
        rows = [ch * len(r) for r in rows]
        self._bitmap_set(rows, None)
        self._sync_pos(); self.rebuild()

    def _poll_bitmap_edit(self):
        ed = getattr(self, "_bitmap_ed", None)
        if not ed or not dpg.does_item_exist(ed["tag"]) or not self.graph or ed["nid"] not in self.graph.nodes:
            return
        st = dpg.get_item_state(ed["tag"])
        if "rect_min" not in st:
            return
        (x0, y0) = st["rect_min"]
        n, rows = self._bitmap_rows(ed["nid"], ed["name"])
        if n is None:
            return
        cell = ed["cell"]
        mx, my = dpg.get_mouse_pos(local=False)
        c, r = int((mx - x0) // cell), int((my - y0) // cell)
        inside = 0 <= r < len(rows) and 0 <= c < len(rows[0]) and mx >= x0 and my >= y0
        down, rdown = dpg.is_mouse_button_down(0), dpg.is_mouse_button_down(1)
        if (down or rdown) and inside:
            ch = "." if rdown else ed["pen"]
            if ed["stroke"] is None:                     # the first cell of a stroke: one undo step for the whole stroke
                self.touch(); self.snapshot("paint bitmap")
                ed["stroke"] = set()
            if (r, c) not in ed["stroke"] and rows[r][c] != ch:
                rows[r] = rows[r][:c] + ch + rows[r][c + 1:]
                self._bitmap_set(rows, None)
                ed["stroke"].add((r, c))
                self._bitmap_draw()
        elif not down and not rdown and ed["stroke"] is not None:   # the stroke ends: the node and the code follow
            ed["stroke"] = None
            self._sync_pos(); self.rebuild()

    # --- the curve editor in the properties pane -------------------------------------------
    def _curve_pts(self):
        ed = self._curve_ed
        n = self.graph.nodes.get(ed["nid"]) if self.graph else None
        if not n:
            return None, None
        d = self.graph.node_def(n)
        p = next((q for q in d["params"] if q["name"] == ed["name"]), None)
        pts = sorted([list(q) for q in (n["params"].get(ed["name"]) or (p["default"] if p else [[0, 0], [1, 1]]))], key=lambda q: q[0])
        return n, pts

    def _curve_draw(self):
        ed = self._curve_ed
        if not ed or not dpg.does_item_exist(ed["tag"]):
            return
        n, pts = self._curve_pts()
        if n is None:
            return
        W, H, tag = ed["W"], ed["H"], ed["tag"]
        dpg.delete_item(tag, children_only=True)
        dpg.draw_rectangle((0, 0), (W - 1, H - 1), color=(70, 74, 82, 255), fill=(24, 26, 30, 255), parent=tag)
        for k in range(1, 4):
            dpg.draw_line((k * W / 4, 0), (k * W / 4, H - 1), color=(50, 54, 62, 255), parent=tag)
            dpg.draw_line((0, k * H / 4), (W - 1, k * H / 4), color=(50, 54, 62, 255), parent=tag)
        prev = None
        for x in range(0, W, 2):
            t = x / max(1, W - 1)
            y = (1.0 - max(0.0, min(1.0, self._curve_at(pts, t)))) * (H - 1)
            if prev is not None:
                dpg.draw_line(prev, (x, y), color=(110, 190, 250, 255), thickness=2, parent=tag)
            prev = (x, y)
        for k, q in enumerate(pts):
            c = (255, 210, 90, 255) if k == ed.get("drag") else (255, 255, 255, 255)
            dpg.draw_circle((q[0] * (W - 1), (1.0 - q[1]) * (H - 1)), 5, color=c, fill=c, parent=tag)
            dpg.draw_text((min(W - 60, q[0] * (W - 1) + 8), max(2, (1.0 - q[1]) * (H - 1) - 16)), f"{q[0]:.2f}, {q[1]:.2f}", size=12,
                          color=(160, 165, 175, 255), parent=tag)

    def _poll_curve_edit(self):
        ed = getattr(self, "_curve_ed", None)
        if not ed or not dpg.does_item_exist(ed["tag"]) or not self.graph or ed["nid"] not in self.graph.nodes:
            return
        st = dpg.get_item_state(ed["tag"])
        if "rect_min" not in st:
            return
        (x0, y0) = st["rect_min"]
        W, H = ed["W"], ed["H"]
        mx, my = dpg.get_mouse_pos(local=False)
        inside = x0 <= mx <= x0 + W and y0 <= my <= y0 + H
        t = max(0.0, min(1.0, (mx - x0) / max(1, W - 1)))
        v = max(0.0, min(1.0, 1.0 - (my - y0) / max(1, H - 1)))
        down, rdown = dpg.is_mouse_button_down(0), dpg.is_mouse_button_down(1)
        pressed, rpressed = dpg.is_mouse_button_clicked(0), dpg.is_mouse_button_clicked(1)   # a click within one frame still counts
        n, pts = self._curve_pts()
        if n is None:
            return
        def nearest():
            best, bk = 12.0, None
            for k, q in enumerate(pts):
                d = ((q[0] * (W - 1) - (mx - x0)) ** 2 + ((1.0 - q[1]) * (H - 1) - (my - y0)) ** 2) ** 0.5
                if d < best:
                    best, bk = d, k
            return bk
        if (pressed or (down and not ed["was"])) and inside and ed["drag"] is None:   # press: pick a point up, or put one down
            k = nearest()
            if k is None:
                self.touch(); self.snapshot(("curve", ed["nid"], ed["name"], -1, "add"))
                pts.append([t, v]); pts.sort(key=lambda q: q[0])
                k = pts.index([t, v])
                n["params"][ed["name"]] = pts
            ed["drag"] = k
            ed["moved"] = False
        elif down and ed["drag"] is not None:                  # drag: the point follows, kept between its neighbours
            k = ed["drag"]
            lo = pts[k - 1][0] + 0.001 if k > 0 else 0.0
            hi = pts[k + 1][0] - 0.001 if k < len(pts) - 1 else 1.0
            pts[k] = [max(lo, min(hi, t)), v]
            n["params"][ed["name"]] = pts
            ed["moved"] = True
        elif not down and ed["drag"] is not None:              # release: the node's own widget and the code follow
            if ed.get("moved"):
                self.touch(); self.snapshot(("curve", ed["nid"], ed["name"], ed["drag"], "move"))
            ed["drag"] = None
            self._sync_pos(); self.rebuild()
        if (rpressed or (rdown and not ed["rwas"])) and inside and len(pts) > 2:
            k = nearest()
            if k is not None:
                self.touch(); self.snapshot(("curve", ed["nid"], ed["name"], k, "del"))
                pts.pop(k); n["params"][ed["name"]] = pts
                self._sync_pos(); self.rebuild()
        ed["was"], ed["rwas"] = down, rdown
        if down and ed["drag"] is not None or inside:
            self._curve_draw()

    def _on_prop(self, sender, val):
        nid, name = dpg.get_item_user_data(sender)
        if nid not in self.graph.nodes:
            return
        self.touch(); self.snapshot(("prop", nid, name))
        if isinstance(val, str) and "\n" in val:
            val = val.replace("\r", "").replace("\n", "/")
        self.graph.nodes[nid]["params"][name] = val
        # the node's own box shows the same text
        for w in list(self._widgets):
            if dpg.does_item_exist(w) and dpg.get_item_user_data(w) == (nid, name):
                try:
                    dpg.set_value(w, val.replace("/", "\n") if isinstance(val, str) and "/" in val and "\n" not in val and dpg.get_item_configuration(w).get("multiline") else val)
                except Exception:
                    pass

    def _poll_help(self):
        now = time.time()
        if now - getattr(self, "_help_at", 0.0) < 0.15:
            return
        self._help_at = now
        if not self.graph or not dpg.does_item_exist("node_editor") or not dpg.is_item_shown("node_editor"):
            return
        if not dpg.is_item_hovered("node_editor"):
            return
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
        self.help(f"{d.get('label') or n['type']} {arrow} {name} ({(p or {}).get('type', '')})"
                  + (f" = {live}" if live is not None else "") + (f": {what}" if what else ""))

    # --- build the widgets from the graph -----------------------------------------
    def themes(self):
        if self._themes is None:
            self._themes = PinThemes()
        return self._themes

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

    @property
    def char_w(self):
        return CHAR_W * self.zoom if self._font_file else CHAR_W

    def _disp(self, pos):
        """Graph units -> the editor's grid, where nodes are placed."""
        return [(pos[0] + self.offset[0]) * self.zoom, (pos[1] + self.offset[1]) * self.zoom]

    def _graph(self, disp):
        return [disp[0] / self.zoom - self.offset[0], disp[1] / self.zoom - self.offset[1]]

    def _measure_pan(self):
        """The editor's own panning, read off a node: where imnodes drew it
        against where it was placed. Counting middle-drags misses the
        editor's own moves (it pans itself when a node is dragged to an
        edge), and a wrong pan puts the zoom off the pointer."""
        if not self.graph or not dpg.does_item_exist("node_editor"):
            return
        ex, ey = dpg.get_item_rect_min("node_editor")
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
        ex, ey = dpg.get_item_rect_min("node_editor")
        return self._graph([screen[0] - ex - self.pan[0], screen[1] - ey - self.pan[1]])

    def _font_px(self):
        return max(8 if (self.overview() and self.zoom >= 0.3) else 6, int(BASE_FONT * self.zoom)) if self._font_file else BASE_FONT

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

    def _font(self):
        if not self._font_file:
            return None
        # Never larger than the zoom asks for: text that outgrows the boxes
        # widens every node, so 50% came out a little bigger than 50%. A
        # 6 px font at the far end is for seeing the shape of a graph, not
        # reading it; stand-ins keep 8 px so their titles still can be.
        size = max(8 if (self.overview() and self.zoom >= 0.3) else 6, int(BASE_FONT * self.zoom))
        f = self._fonts.get(size)
        if f is None:
            try:
                with dpg.font_registry():
                    f = dpg.add_font(self._font_file, size)
            except Exception:
                self._font_file = None
                return None
            self._fonts[size] = f
        return f

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
        ex, ey = dpg.get_item_rect_min("node_editor")
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
            x, y = dpg.get_item_pos(t)
            dpg.set_item_pos(t, [x + dx * self.zoom, y + dy * self.zoom])
        self._sync_pos()

    def home(self):
        """Bring the graph back to the origin: the editor cannot be panned
        from code, so the nodes move instead, their top-left to (20, 20)."""
        if not self.graph or not self.graph.nodes:
            return
        self._sync_pos()
        self.snapshot()
        self.offset = [0.0, 0.0]
        x0 = min(n["pos"][0] for n in self.graph.nodes.values())
        y0 = min(n["pos"][1] for n in self.graph.nodes.values())
        for nid, n in self.graph.nodes.items():
            n["pos"] = [n["pos"][0] - x0 + 20, n["pos"][1] - y0 + 20]
            if dpg.does_item_exist(f"gnode_{nid}"):
                dpg.set_item_pos(f"gnode_{nid}", self._disp(n["pos"]))
        self._frame_last = {nid: tuple(self._disp(n["pos"])) for nid, n in self.graph.nodes.items() if n["type"] == "Frame"}

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
        self._sync_pos()
        self.snapshot()
        boxes = [(self.graph.nodes[n]["pos"], self._node_size(n)) for n in sel]
        x0 = min(p[0] for p, _ in boxes); y0 = min(p[1] for p, _ in boxes)
        x1 = max(p[0] + sz[0] for p, sz in boxes); y1 = max(p[1] + sz[1] for p, sz in boxes)
        for n in self.graph.nodes.values():
            n["pos"] = [n["pos"][0] - x0 + 20, n["pos"][1] - y0 + 20]
        self.offset = [0.0, 0.0]
        w, h = dpg.get_item_rect_size("node_editor") if dpg.does_item_exist("node_editor") else (0, 0)
        if w <= 0 or h <= 0:                             # not drawn since a rebuild: the pane's size, less its rows
            w, h = dpg.get_item_rect_size("graph_win") if dpg.does_item_exist("graph_win") else (0, 0)
            w, h = (w, max(200, h - 160)) if w > 60 and h > 200 else (800, 600)
        fit = min((w - 40) / max(1.0, x1 - x0), (h - 40) / max(1.0, y1 - y0))
        z = max([zz for zz in ZOOMS if zz <= fit] or [ZOOMS[0]])
        self.zoom = min(1.0, z) if len(sel) > 1 else min(z, 1.5)
        self.rebuild()
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
        self._poll_labels()
        self._record_probes()
        self._poll_readouts()
        self._poll_glyphs()
        if not self.auto or not self._dirty or not self.graph:
            return
        if time.time() - self._dirty < self.AUTO_DELAY:
            return
        if self.app.building:
            return                    # tried again next frame; the last edit wins
        self._dirty = 0.0
        self.compile()

    def rebuild(self):
        self.touch()
        self.app._color_edits = None                    # the nodes' dropdowns and swatches are new
        # the editor's own selection dies with the nodes it is rebuilt from
        # (a zoom, an edit): it carries on as the key selection, outlined
        keep = self._clicked()
        if keep:
            self.ext_sel = [n for n in dict.fromkeys(list(self.ext_sel) + keep)]
        self._widgets.clear(); self._pads.clear(); self._log_sliders.clear(); self._glyph_clear(); self._glyph_pal = None
        self._standin_line.clear()
        dpg.delete_item("node_editor", children_only=True)
        self.links.clear(); self._pins.clear(); self._ptype.clear(); self._link_normal.clear()
        self._focus_sel = None
        if not self.graph:
            return
        f = self._font()
        self._node_font = f
        if f is not None:
            dpg.bind_item_font("node_editor", f)         # (Dear PyGui 2.3 does not hand an editor's font down: each node binds it too)
        dpg.bind_item_theme("node_editor", self._zoom_theme())
        # frames first: nodes draw in creation order, so a frame made first
        # sits behind the nodes inside it
        for nid, n in sorted(self.graph.nodes.items(), key=lambda kv: kv[1]["type"] != "Frame"):
            self._make_node(nid, n)
        self._frame_last = {nid: tuple(self._disp(n["pos"])) for nid, n in self.graph.nodes.items() if n["type"] == "Frame"}
        self._frame_drag.clear()
        # a wire to a pin that no longer exists - a sub-graph's input was
        # renamed or removed - is dropped rather than kept invisibly
        stale = [l for l in self.graph.links
                 if (l[0], "out", l[1]) not in self._pins or (l[2], "in", l[3]) not in self._pins]
        if stale:
            self.graph.links = [l for l in self.graph.links if l not in stale]
            self.status(f"dropped {len(stale)} wire(s) to pins that no longer exist")
        for a, out, b, inp in self.graph.links:
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

    # --- validation ---------------------------------------------------------------------
    # Problems are painted on the node - a red outline for what stops the
    # compile, amber for what only looks wrong - and listed in the status
    # line, so a broken graph says where before a build is tried.
    def _mark_theme(self, kind):
        th = self._mark_themes.get((kind, self.zoom))
        if th is None:
            col = (235, 80, 70) if kind == "error" else (240, 190, 70)
            with dpg.theme() as th:
                with dpg.theme_component(dpg.mvNode):
                    dpg.add_theme_color(dpg.mvNodeCol_NodeOutline, col, category=dpg.mvThemeCat_Nodes)
                    dpg.add_theme_style(dpg.mvNodeStyleVar_NodeBorderThickness, 2.5, category=dpg.mvThemeCat_Nodes)
                with dpg.theme_component(dpg.mvAll):
                    self._zoom_styles()
            self._mark_themes[(kind, self.zoom)] = th
        return th

    def _mark_problems(self):
        if not self.graph:
            return
        self.problems = self.graph.problems()
        errs = []
        for nid, msg in self.problems.items():
            tag = f"gnode_{nid}"
            if not dpg.does_item_exist(tag):
                continue
            kind = "error" if msg.startswith("error") else "warn"
            n = self.graph.nodes[nid]
            # a coloured or framed node keeps its colour theme; the outline wins on top of it
            if kind == "error" or not (n.get("color") or n["type"] == "Frame"):
                dpg.bind_item_theme(tag, self._mark_theme(kind))
            if kind == "error":
                errs.append(f"{n['type']} #{nid}: {msg[7:]}")
        if errs:
            self.status("; ".join(errs)[:200])

    def summary(self, nid):
        """One line on what the node computes now (nodeface.summary), with
        the palette's name where a node reads the palette."""
        n = self.graph.nodes.get(nid)
        if n is None:
            return ""
        try:
            d = self.graph.node_def(n)
        except G.GraphError:
            return ""
        wired = {i for b, i in ((l[2], l[3]) for l in self.graph.links) if b == nid}
        extra = {}
        if n["type"] in ("Palette", "Palette source", "Effect settings"):
            try:
                extra["palette"] = self.app.palette_name_for(self.app.eng.pal)
            except Exception:
                pass
        return nodeface.summary(n, d, wired, extra)

    def _refresh_summary(self, nid):
        """The line - and the glyph - follow a typed value as it is dragged."""
        tag = f"gsum_{nid}"
        if dpg.does_item_exist(tag):
            dpg.set_value(tag, self.summary(nid))
        self._refresh_glyph(nid)

    def _make_node(self, nid, n):
        try:
            d = self.graph.node_def(n)
        except G.GraphError as e:
            self.status(str(e)); return
        th = self.themes()
        linked = {(b, inp) for _, _, b, inp in self.graph.links}
        n.setdefault("inputs", {})
        label = n.get("label") or d.get("label") or n["type"]
        if n["type"] in ("Graph input", "Graph output") or n["type"] in G.SENDS or n["type"] in G.RECEIVES:
            label = f"{n['type']}: {n['params'].get('name', '')}"
        if n["type"] == "Frame":
            label = str(n["params"].get("title", "group"))
        collapsed = bool(n.get("collapsed"))
        hide = bool(n.get("hide_pins"))
        if n.get("muted"):
            label = f"{label} (muted)"
        width = self.px(NARROW_W if d.get("narrow") else NODE_W)
        if self.overview() and n["type"] != "Frame":
            self._make_standin(nid, n, d, label, width)
            return
        with dpg.node(label=label, parent="node_editor", pos=self._disp(n.get("pos", [0, 0])), tag=f"gnode_{nid}",
                      user_data=nid):
            if getattr(self, "_node_font", None):
                dpg.bind_item_font(f"gnode_{nid}", self._node_font)
            if n["type"] == "Frame":
                self._frame_body(nid, n)
            with dpg.node_attribute(attribute_type=dpg.mvNode_Attr_Static):
                dpg.add_spacer(width=width, height=1)
            if self.preview and self.preview[0] == nid:
                # the previewed node wears a small picture of what its pin
                # draws - the net, as the cube shows it - refreshed each frame
                with dpg.node_attribute(attribute_type=dpg.mvNode_Attr_Static):
                    self._thumb_texture()
                    t = self.px(THUMB)
                    dpg.add_image("preview_thumb_tex", width=t, height=t, tag=f"gthumb_{nid}")
                    dpg.add_text(f"previewing {self.preview[1]}", color=DIM)
            fed_out = {(a, o) for a, o, _, _ in self.graph.links}
            for i in d["inputs"]:
                if hide and (nid, i["name"]) not in linked:
                    continue
                tag = f"gin_{nid}_{i['name']}"
                with dpg.node_attribute(attribute_type=dpg.mvNode_Attr_Input, tag=tag,
                                        user_data=(nid, i["name"]), shape=dpg.mvNode_PinShape_CircleFilled):
                    # An unconnected input is EDITABLE on the node: the value
                    # it takes stands in for the wire. Connected, the widget
                    # hides and the name stays.
                    is_linked = (nid, i["name"]) in linked
                    dpg.add_text(i["name"], tag=tag + "_t", show=is_linked or collapsed)
                    if not collapsed:
                        self._input_widget(nid, n, i, tag + "_w", show=not is_linked)
                dpg.bind_item_theme(tag, th.pin[i["type"]])
                self._pins[(nid, "in", i["name"])] = tag
                self._ptype[tag] = i["type"]
            if not collapsed and n["type"] != "Frame":
                for p in d["params"]:
                    with dpg.node_attribute(attribute_type=dpg.mvNode_Attr_Static):
                        self._param_widget(nid, n, p, multiline=d.get("multiline", False))
                for a, b, lo, hi in d.get("pads", []):
                    if (nid, a) in linked or (nid, b) in linked or hide:
                        continue                               # wired: the pins say it; the pad is for typed values
                    with dpg.node_attribute(attribute_type=dpg.mvNode_Attr_Static):
                        self._pad_widget(nid, n, a, b, lo, hi)
                if n["type"] in self.GLYPHS and self.zoom >= 0.7:
                    with dpg.node_attribute(attribute_type=dpg.mvNode_Attr_Static):
                        self._glyph_widget(nid, n)
                elif n["type"] == "Steps":
                    self._live_glyphs[nid] = "steps"             # its sliders are its face: the current one lights
            if collapsed and n["type"] != "Frame":
                # folded: the function it computes, in one line, is its body
                text = self.summary(nid)
                if text:
                    with dpg.node_attribute(attribute_type=dpg.mvNode_Attr_Static):
                        dpg.add_text(text, tag=f"gsum_{nid}", color=(170, 178, 192), wrap=width)
            for o in d["outputs"]:
                if hide and (nid, o["name"]) not in fed_out:
                    continue
                tag = f"gout_{nid}_{o['name']}"
                with dpg.node_attribute(attribute_type=dpg.mvNode_Attr_Output, tag=tag,
                                        user_data=(nid, o["name"]), shape=dpg.mvNode_PinShape_CircleFilled):
                    dpg.add_text(o["name"], indent=_right(o["name"], width, self.char_w))
                dpg.bind_item_theme(tag, th.pin[o["type"]])
                self._pins[(nid, "out", o["name"])] = tag
                self._ptype[tag] = o["type"]
        self._bind_node_theme(nid, n)

    def _standin_rows(self, nid):
        """A stand-in's pin rows and their height: the node keeps the
        footprint its full self would have at this zoom (the height
        estimate arrange uses), so the graph's spacing survives zooming
        out - a stand-in is the full node scaled, not a label dropped on
        its corner."""
        n = self.graph.nodes[nid]
        d = self.graph.node_def(n)
        rows = len(d["inputs"]) + len(d["outputs"]) + (0 if n.get("collapsed") else len(d["params"]))
        est = 56 + 27 * max(1, rows)
        linked = {(b, inp) for _, _, b, inp in self.graph.links}
        fed_out = {(a, o) for a, o, _, _ in self.graph.links}
        pins = [("in", i) for i in d["inputs"] if (nid, i["name"]) in linked] +                [("out", o) for o in d["outputs"] if (nid, o["name"]) in fed_out]
        body = self.px(est) - self._font_px() - 4 * self.px(8) - self.px(4) * (len(pins) + 1)
        body -= self._standin_line.get(nid, 0)             # the summary's line, when the stand-in shows one
        row_h = max(1, int(body / max(1, len(pins))))
        return pins, row_h, max(1, body - row_h * len(pins))

    def _make_standin(self, nid, n, d, label, width):
        """The node zoomed far out: its title over one row per wired pin (so
        the wires still have ends), nothing to edit; as tall as the full
        node would be at this zoom. The title's font stops at 8 px."""
        th = self.themes()
        text = self.summary(nid) if self.zoom >= 0.3 else ""
        line = self._font_px() + self.px(4)
        self._standin_line[nid] = line if text else 0
        pins, row_h, rest = self._standin_rows(nid)
        if text and pins and row_h < self._font_px():
            # no room under the title: the pins' rows come first
            text = ""; self._standin_line[nid] = 0
            pins, row_h, rest = self._standin_rows(nid)
        with dpg.node(label=label, parent="node_editor", pos=self._disp(n.get("pos", [0, 0])), tag=f"gnode_{nid}",
                      user_data=nid):
            if getattr(self, "_node_font", None):
                dpg.bind_item_font(f"gnode_{nid}", self._node_font)
            with dpg.node_attribute(attribute_type=dpg.mvNode_Attr_Static):
                if text:
                    # the function under the title, in a line of its own
                    dpg.add_text(text[:max(1, int(width / max(1.0, self.char_w)))], tag=f"gsum_{nid}", color=(150, 158, 172))
                else:
                    dpg.add_spacer(width=width, height=1)
            for kind, p in pins:
                tag = f"g{kind}_{nid}_{p['name']}"
                with dpg.node_attribute(attribute_type=dpg.mvNode_Attr_Input if kind == "in" else dpg.mvNode_Attr_Output,
                                        tag=tag, user_data=(nid, p["name"]), shape=dpg.mvNode_PinShape_CircleFilled):
                    dpg.add_spacer(width=width, height=row_h, tag=tag + "_t" if kind == "in" else 0)
                dpg.bind_item_theme(tag, th.pin[p["type"]])
                self._pins[(nid, kind, p["name"])] = tag
                self._ptype[tag] = p["type"]
            with dpg.node_attribute(attribute_type=dpg.mvNode_Attr_Static):
                dpg.add_spacer(width=width, height=rest)
        self._bind_node_theme(nid, n)

    def _bind_node_theme(self, nid, n):
        """The node's own look: muted grey, its colour, a frame's wash; an
        outline when the keys selected it."""
        col = n.get("color")
        sel = nid in self.ext_sel
        if n.get("muted"):
            dpg.bind_item_theme(f"gnode_{nid}", self._node_theme((70, 74, 82), sel=sel))
        elif col:
            dpg.bind_item_theme(f"gnode_{nid}", self._node_theme(tuple(col), sel=sel))
        elif n["type"] == "Frame":
            dpg.bind_item_theme(f"gnode_{nid}", self._node_theme(tuple(n["params"].get("colour", [90, 110, 160]))[:3], frame=True, sel=sel))
        elif self.app.prefs.get("cat_colours", True):
            # a face per category: the title bar in the category's hue
            try:
                cat = self.graph.node_def(n).get("cat", "graph")
            except G.GraphError:
                cat = "graph"
            dpg.bind_item_theme(f"gnode_{nid}", self._node_theme(nodeface.hue(cat), sel=sel))
        else:
            dpg.bind_item_theme(f"gnode_{nid}", self._node_theme(None, sel=sel))

    def rebind_themes(self):
        """Every node's look again (the category colours switched)."""
        if not self.graph:
            return
        for nid, n in self.graph.nodes.items():
            if dpg.does_item_exist(f"gnode_{nid}"):
                self._bind_node_theme(nid, n)

    def _cat_header_theme(self, cat):
        """The add menu's category header in the category's hue."""
        key = ("cat", cat)
        th = self._node_themes.get(key)
        if th is None:
            r, g, b = nodeface.hue(cat)
            with dpg.theme() as th:
                with dpg.theme_component(dpg.mvCollapsingHeader):
                    dpg.add_theme_color(dpg.mvThemeCol_Header, (r, g, b, 170))
                    dpg.add_theme_color(dpg.mvThemeCol_HeaderHovered, (min(255, r + 30), min(255, g + 30), min(255, b + 30), 200))
                    dpg.add_theme_color(dpg.mvThemeCol_HeaderActive, (min(255, r + 50), min(255, g + 50), min(255, b + 50), 220))
            self._node_themes[key] = th
        return th

    # --- focus mode -------------------------------------------------------------------
    # Everything but the selection and what it is wired to goes dim, so a
    # busy graph can be read one piece at a time. Themes are rebound when
    # the selection changes; nothing is rebuilt.
    def _dim_theme(self):
        th = self._node_themes.get(("dim", self.zoom))
        if th is None:
            with dpg.theme() as th:
                with dpg.theme_component(dpg.mvNode):
                    dpg.add_theme_color(dpg.mvNodeCol_NodeBackground, (24, 27, 34, 110), category=dpg.mvThemeCat_Nodes)
                    dpg.add_theme_color(dpg.mvNodeCol_NodeBackgroundHovered, (26, 30, 38, 130), category=dpg.mvThemeCat_Nodes)
                    dpg.add_theme_color(dpg.mvNodeCol_TitleBar, (30, 34, 42, 110), category=dpg.mvThemeCat_Nodes)
                    dpg.add_theme_color(dpg.mvNodeCol_TitleBarHovered, (34, 39, 48, 130), category=dpg.mvThemeCat_Nodes)
                    dpg.add_theme_color(dpg.mvNodeCol_NodeOutline, (36, 41, 50, 60), category=dpg.mvThemeCat_Nodes)
                    dpg.add_theme_color(dpg.mvNodeCol_Pin, (60, 66, 78, 120), category=dpg.mvThemeCat_Nodes)
                with dpg.theme_component(dpg.mvAll):
                    dpg.add_theme_color(dpg.mvThemeCol_Text, (78, 84, 96), category=dpg.mvThemeCat_Core)
                    dpg.add_theme_color(dpg.mvThemeCol_FrameBg, (26, 29, 36, 80), category=dpg.mvThemeCat_Core)
                    self._zoom_styles()
            self._node_themes[("dim", self.zoom)] = th
        return th

    def _dim_wire(self):
        return self._wire_theme((44, 49, 60))

    def set_focus_mode(self, on):
        self.focus_mode = bool(on)
        self._focus_sel = None
        if not self.focus_mode and self.graph:
            self._apply_focus(None)
        self.status("focus mode: the selection and its neighbours lit" if on else "focus mode off")

    def _poll_focus(self):
        if not self.focus_mode or not self.graph:
            return
        sel = set(self._selected())
        if sel == self._focus_sel:
            return
        self._focus_sel = sel
        keep = set(sel)
        for a, out, b, inp in self.graph.links:
            if a in sel:
                keep.add(b)
            if b in sel:
                keep.add(a)
        self._apply_focus(keep if sel else None)

    def _apply_focus(self, keep):
        """keep: the nodes left lit; None lights everything."""
        th = self.themes()
        for nid, n in self.graph.nodes.items():
            if not dpg.does_item_exist(f"gnode_{nid}"):
                continue
            lit = keep is None or nid in keep
            if lit:
                self._bind_node_theme(nid, n)
            else:
                dpg.bind_item_theme(f"gnode_{nid}", self._dim_theme())
            for (pn, kind, name), tag in self._pins.items():
                if pn == nid and dpg.does_item_exist(tag):
                    t = self._ptype.get(tag, "float")
                    dpg.bind_item_theme(tag, th.pin[t] if lit else th.grey[t])
        ends = {(l[2], l[3]): l[0] for l in self.graph.links}
        for lid, (b, inp) in self.links.items():
            if not dpg.does_item_exist(lid):
                continue
            a = ends.get((b, inp))
            lit = keep is None or a in keep or b in keep
            dpg.bind_item_theme(lid, self._link_normal.get(lid, 0) if lit else self._dim_wire())
        if keep is not None:
            self._mark_problems()

    # --- wire labels ---------------------------------------------------------------------
    # A label on a wire is text drawn over the editor at the wire's middle,
    # between the two pins' positions as they are this frame. It lives in
    # the link's meta, beside its colour.
    def set_wire_label(self, b, inp, text):
        self.snapshot(); self._sync_pos()
        meta = dict(self.graph.link_meta.get((b, inp)) or {})
        text = (text or "").strip()
        if text:
            meta["label"] = text
        else:
            meta.pop("label", None)
        if meta:
            self.graph.link_meta[(b, inp)] = meta
        else:
            self.graph.link_meta.pop((b, inp), None)
        self.touch()

    def live_value(self, nid, kind, name):
        """The value on a pin as the running effect has it, when the effect on
        the cube is this graph's last build; an input's is its source's, or
        its own setting when unwired. None when there is nothing to say."""
        probes = getattr(self, "_probes", None)
        if not probes or not self.graph:
            return None
        eng = self.app.eng
        want = self.app.project.effect_title(getattr(self, "_probes_for", "") or "") if getattr(self, "_probes_for", None) else None
        if not want or eng.names[eng.idx] != want:
            return None
        if kind == "in":
            src = next(((l[0], l[1]) for l in self.graph.links if l[2] == nid and l[3] == name), None)
            if src is None:
                n = self.graph.nodes[nid]
                v = n.get("inputs", {}).get(name) if isinstance(n.get("inputs"), dict) else None
                return None if v is None else (f"{v:.3f}" if isinstance(v, float) else str(v))
            nid, name = src
        k = next((k for k, v in probes.items() if v == (nid, name)), None)
        if k is None:
            return None
        v = eng.probe(k)
        d = self.graph.node_def(self.graph.nodes[nid])
        t = next((o["type"] for o in d["outputs"] if o["name"] == name), "float")
        if t == "bool":
            return "true" if v > 0.5 else "false"
        return f"{v:.3f}" + ("" if getattr(self, "_probe_scope", {}).get(nid) == "frame" else " (centre pixel)")

    def _pin_point(self, nid, kind, name):
        """Where a pin's circle is on screen: an attribute reports no
        rectangle, but its text does, and the circle sits on the node's
        edge at that height."""
        tag = self._pins.get((nid, kind, name))
        if not tag or not dpg.does_item_exist(tag) or not dpg.does_item_exist(f"gnode_{nid}"):
            return None
        kids = dpg.get_item_children(tag, 1) or []
        if not kids:
            return None
        st = dpg.get_item_state(kids[0])
        nd = dpg.get_item_state(f"gnode_{nid}")
        if "rect_min" not in nd:
            return None
        if "rect_min" not in st or "rect_max" not in st:
            # a stand-in's spacer reports no rectangle: the pin's row is
            # counted down from the node's title
            pins, row_h, _ = self._standin_rows(nid)
            row = next((r for r, (kd, p) in enumerate(pins) if kd == kind and p["name"] == name), 0)
            top = nd["rect_min"][1] + self.px(8) * 2 + self._font_px() + self.px(4) + self._standin_line.get(nid, 0)
            y = top + row * (row_h + self.px(4)) + row_h / 2
        else:
            y = (st["rect_min"][1] + st["rect_max"][1]) / 2
        pad = self.px(8)
        x = nd["rect_max"][0] + pad if kind == "out" else nd["rect_min"][0] - pad
        return (x, y)

    def _poll_readouts(self):
        """The live value on every frame-scope output pin of the effect on
        screen - one number a frame each, read from the probes the build
        planted (as a synth's meters: always on, not on hover)."""
        for it in self._readout_items:
            if dpg.does_item_exist(it):
                dpg.delete_item(it)
        self._readout_items = []
        if not self.graph or self.app.layout != "graph" or not self.app.ui or self.zoom < 0.7:
            return
        if dpg.is_item_shown("graph_menu") or dpg.is_item_shown("graph_ctx") or self.overview():
            return
        pane = self.app._screen_rect("graph_win")
        if not pane:
            return
        eh = dpg.get_item_rect_size("node_editor")[1]
        x0, y0, x1, y1 = pane[0] + 9, pane[3] - 9 - eh, pane[2] - 9, pane[3] - 9
        size = max(9, int(11 * self.zoom))
        probes = getattr(self, "_probes", None) or {}
        eng = self.app.eng
        live = bool(probes) and bool(getattr(self, "_probes_for", None)) and bool(eng.names)             and eng.names[eng.idx] == self.app.project.effect_title(self._probes_for or "")
        if not live:
            self._draw_mod_ranges((x0, y0, x1, y1), size)      # the ranges stand without a running build; the dot needs one
            return
        scope = getattr(self, "_probe_scope", {}) or {}
        cw = self.char_w
        now = time.time()
        if not dpg.does_item_exist("wire_labels"):
            dpg.add_viewport_drawlist(front=True, tag="wire_labels")
        for k, (nid, name) in probes.items():
            if scope.get(nid) != "frame" or nid not in self.graph.nodes or self.graph.nodes[nid].get("collapsed"):
                continue
            pt = self._pin_point(nid, "out", name)
            if not pt:
                continue
            ax, ay = pt
            v = eng.probe(k)
            n = self.graph.nodes[nid]
            try:
                d = self.graph.node_def(n)
                t = next((o["type"] for o in d["outputs"] if o["name"] == name), "float")
            except G.GraphError:
                d, t = None, "float"
            if t == "bool":
                # a light, not a word: on is bright, off is dim, and a one-frame hit glows out over 150 ms
                lvl = self._light_level(nid, name, v > 0.5, now)
                r = max(3.0, 4.0 * self.zoom)
                cx, cy = ax - 10 - len(name) * cw - 6 - r, ay
                if cx - r < x0 or cx + r > x1 or cy - r < y0 or cy + r > y1:
                    continue
                fill = (int(70 + 100 * lvl), int(76 + 154 * lvl), int(88 + 32 * lvl), 255)
                self._readout_items.append(dpg.draw_circle((cx, cy), r, parent="wire_labels", color=(30, 33, 40, 255), fill=fill))
                if lvl > 0.02:
                    self._readout_items.append(dpg.draw_circle((cx, cy), r * (1.0 + 0.8 * lvl), parent="wire_labels",
                                                               color=(170, 230, 120, int(110 * lvl)), thickness=1.0))
                continue
            text = f"{v:.3g}" if abs(v) < 1e5 else f"{v:.2e}"
            # left of the pin's name, inside the node: the name is right-aligned to the pin
            w = len(text) * size * 0.6
            rx = ax - 10 - len(name) * cw - 6 - w
            ry = ay - size * 0.55
            if rx < x0 or rx + w > x1 or ry < y0 or ry + size > y1:
                continue
            self._readout_items.append(dpg.draw_text((rx, ry), text, parent="wire_labels", color=(110, 190, 250, 255), size=size))
            rng = nodeface.out_range(n, d, name) if d else None
            if rng and ry + size + 3 < y1:
                # a meter under the number: how far along its range the value is
                lo, hi = rng
                f = max(0.0, min(1.0, (v - lo) / (hi - lo))) if hi > lo else 0.0
                mw = max(w, 24 * self.zoom)
                mx = rx + w - mw
                self._readout_items.append(dpg.draw_rectangle((mx, ry + size + 1), (mx + mw, ry + size + 3), parent="wire_labels",
                                                              color=(0, 0, 0, 0), fill=(50, 56, 68, 255)))
                self._readout_items.append(dpg.draw_rectangle((mx, ry + size + 1), (mx + mw * f, ry + size + 3), parent="wire_labels",
                                                              color=(0, 0, 0, 0), fill=(110, 190, 250, 255)))
        self._draw_mod_ranges((x0, y0, x1, y1), size)
        self._draw_hover_plot((x0, y0, x1, y1), size)

    def _poll_labels(self):
        if not dpg.does_item_exist("wire_labels"):
            dpg.add_viewport_drawlist(front=True, tag="wire_labels")
        for it in self._label_items:
            if dpg.does_item_exist(it):
                dpg.delete_item(it)
        self._label_items = []
        if not self.graph or self.app.layout != "graph" or not self.app.ui:
            return
        if dpg.is_item_shown("graph_menu") or dpg.is_item_shown("graph_ctx"):
            return
        labelled = [(k, m["label"]) for k, m in self.graph.link_meta.items() if m.get("label")]
        if not labelled:
            return
        pane = self.app._screen_rect("graph_win")
        if not pane:
            return
        eh = dpg.get_item_rect_size("node_editor")[1]
        x0, y0, x1, y1 = pane[0] + 9, pane[3] - 9 - eh, pane[2] - 9, pane[3] - 9
        ends = {(l[2], l[3]): (l[0], l[1]) for l in self.graph.links}
        for (b, inp), text in labelled:
            src = ends.get((b, inp))
            if not src:
                continue
            pa, pb = self._pin_point(src[0], "out", src[1]), self._pin_point(b, "in", inp)
            if not pa or not pb:
                continue
            (ax, ay), (bx, by) = pa, pb
            mx, my = (ax + bx) / 2, (ay + by) / 2
            w = len(text) * 7 + 10
            if mx - w / 2 < x0 or mx + w / 2 > x1 or my - 9 < y0 or my + 9 > y1:
                continue
            self._label_items.append(dpg.draw_rectangle((mx - w / 2, my - 9), (mx + w / 2, my + 9), parent="wire_labels",
                                                        color=(60, 66, 80, 255), fill=(20, 23, 29, 235), rounding=4))
            self._label_items.append(dpg.draw_text((mx - w / 2 + 5, my - 7), text, parent="wire_labels",
                                                   color=(200, 206, 216, 255), size=13))

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
        key = (col, frame, sel, self.zoom)
        th = self._node_themes.get(key)
        if th is None:
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
            with dpg.group(horizontal=True):
                w_ = dpg.add_input_int(label="w", width=self.px(70), default_value=w, step=0, user_data=(nid, "w"),
                                       callback=self._on_param)
                h_ = dpg.add_input_int(label="h", width=self.px(70), default_value=h, step=0, user_data=(nid, "h"),
                                       callback=self._on_param)
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

    def _input_widget(self, nid, n, i, tag, show):
        """The editable stand-in for an unconnected input pin."""
        v = n["inputs"].get(i["name"], i.get("default", 0))
        ud = (nid, i["name"])
        if i["type"] == "float":
            w = self._number_widget(i, float(v), tag, ud, self._on_input, show)
        elif i["type"] == "bool":
            w = dpg.add_checkbox(label=i["name"], tag=tag, default_value=bool(v), user_data=ud,
                             callback=self._on_input, show=show)
        elif i["type"] == "vector":
            vv = [float(c) for c in (list(v) + [0, 0, 0])[:3]] if isinstance(v, (list, tuple)) else [float(v)] * 3
            w = dpg.add_input_floatx(label=i["name"], tag=tag, width=self.px(120), size=3, default_value=vv + [0.0],
                                     format="%.2f", user_data=ud, callback=self._on_input, show=show)
        else:
            rgb = list(v)[:3] if isinstance(v, (list, tuple)) else [0, 0, 0]
            w = dpg.add_color_edit([int(c) for c in rgb] + [255], label=i["name"], tag=tag, width=self.px(90),
                               no_alpha=True, no_inputs=True, user_data=ud, callback=self._on_input, show=show)
        dpg.bind_item_theme(w, self._field_theme())
        self._widgets.add(w)

    def _same_type_selected(self, nid):
        """Alt held: the other selected nodes of this node's type - an edit
        lands on all of them."""
        if not (dpg.is_key_down(dpg.mvKey_LAlt) or dpg.is_key_down(dpg.mvKey_RAlt)):
            return []
        t = self.graph.nodes[nid]["type"]
        return [k for k in self._selected() if k != nid and self.graph.nodes[k]["type"] == t]

    def live_poke(self, nid, name, val):
        """The typed value into the running effect's parameter table, so the
        picture follows the drag with no rebuild. True when it landed: the
        effect built from this graph is in the engine and has run. A
        vector pokes three slots; a bool one."""
        live = getattr(self, "_live", None)
        if not live or not getattr(self, "_probes_for", None):
            return False
        eng = self.app.eng
        title = self.app.project.effect_title(self._probes_for)
        if title not in eng.names:
            return False
        idx = eng.names.index(title)
        if eng.idx != idx:
            return False                                 # something else is on screen (the script preview, another effect): as before
        if isinstance(val, (list, tuple)):
            slots = [(live.get((nid, name, j)), float(c)) for j, c in enumerate(list(val)[:3])]
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
        w = f"gin_{nid}_{name}_w"
        if dpg.does_item_exist(w):
            try:
                if w in self._log_sliders:
                    import math
                    dpg.set_value(w, math.log(max(1e-9, float(val)))); self._log_label(w, float(val), self._log_sliders[w])
                else:
                    dpg.set_value(w, val)
            except Exception:
                pass
        for btn, pad in list(self._pads.items()):          # a pad showing this pin follows
            if pad[0] == nid and name in (pad[1], pad[2]):
                self._pad_draw(btn)
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
        poked = ptype != "color" and self.live_poke(nid, name, val)
        for k in self._same_type_selected(nid):
            self.graph.nodes[k].setdefault("inputs", {})[name] = val
            poked = poked and self.live_poke(k, name, val)
            w = f"gin_{k}_{name}_w"
            if dpg.does_item_exist(w):
                dpg.set_value(w, val if ptype != "color" else [c / 255.0 for c in val] + [1.0])
        if poked and not was_dirty:
            self._dirty = 0.0                            # the running effect has the value: nothing to rebuild
            self.status(f"{name}: {val if not isinstance(val, float) else round(val, 4)} - live")
        self._refresh_summary(nid)

    def _show_input(self, b, inp, linked):
        tag = f"gin_{b}_{inp}"
        if dpg.does_item_exist(tag + "_t"):
            dpg.configure_item(tag + "_t", show=linked)
        if dpg.does_item_exist(tag + "_w"):                 # a stand-in has no value box
            dpg.configure_item(tag + "_w", show=not linked)

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
        for w in self._widgets:
            if dpg.does_item_exist(w) and dpg.get_item_user_data(w) == (nid, name):
                try:
                    if dpg.get_item_type(w).endswith("ColorEdit"):
                        dpg.set_value(w, [c / 255.0 for c in list(val)[:3]] + [1.0])
                    elif w in self._log_sliders:
                        import math
                        dpg.set_value(w, math.log(max(1e-9, float(val)))); self._log_label(w, float(val), self._log_sliders[w])
                    else:
                        dpg.set_value(w, val)
                except Exception:
                    pass

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
        dpg.set_value("expr_label", f"{n['type']} . {name} =")
        dpg.set_value("expr_text", f"{float(cur):g}" if isinstance(cur, (int, float)) else str(cur))
        x, y = dpg.get_mouse_pos(local=False)
        dpg.configure_item("expr_win", show=True)
        dpg.set_item_pos("expr_win", [x + 8, y + 8])
        dpg.focus_item("expr_text")
        self.status(f"{name}: type an expression and press Enter (Escape leaves it)")
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
            self.status(f"{name}: {e}"); return None
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
            self.status(f"{name} = {v:g}  ({text})")
        else:
            i = next((i for i in d["inputs"] if i["name"] == name), None)
            if i is None:
                return None
            if i.get("min") is not None:
                v = max(float(i["min"]), v)
            if i.get("max") is not None:
                v = min(float(i["max"]), v)
            self.set_input_live(nid, name, v)
            self.status(f"{name} = {v:g}  ({text})")
        return v

    # --- the modulation range on the field --------------------------------------------
    def mod_ranges(self):
        """[(remap id, fed node, fed input)] for every input a modulator's
        Remap feeds - the Remap a "modulate with" made, or any Remap
        labelled with a ±."""
        out = []
        for a, o, b, i in self.graph.links:
            n = self.graph.nodes.get(a)
            if n and n["type"] == "Remap" and o == "result" and (n.get("modulator") or "\u00b1" in str(n.get("label") or "")):
                out.append((a, b, i))
        return out

    def _draw_mod_ranges(self, pane, size):
        """Under a modulated input's name: a bar from the Remap's out_lo to
        out_hi with the live value on it and the two numbers at its ends.
        Ctrl+wheel over an end nudges it (the Remap's setting changes)."""
        self._mod_bars = {}
        if not self.graph:
            return
        x0, y0, x1, y1 = pane
        small = max(8, int(9 * self.zoom))
        for r, b, inp in self.mod_ranges():
            if b not in self.graph.nodes or self.graph.nodes[b].get("collapsed"):
                continue
            pt = self._pin_point(b, "in", inp)
            if not pt:
                continue
            rn = self.graph.nodes[r]
            lo, hi = float(rn["params"].get("out_lo", 0.0)), float(rn["params"].get("out_hi", 1.0))
            mw = max(40.0, 64.0 * self.zoom)
            bx, by = pt[0] + 12, pt[1] + size * 0.75
            if bx < x0 or bx + mw > x1 or by < y0 or by + small + 4 > y1:
                continue
            k = self._probe_k(r, "out", "result")
            v = self._probe_now(k)
            f = None if v is None or hi == lo else max(0.0, min(1.0, (v - min(lo, hi)) / abs(hi - lo)))
            items = self._readout_items
            items.append(dpg.draw_rectangle((bx, by), (bx + mw, by + 3), parent="wire_labels", color=(0, 0, 0, 0), fill=(50, 56, 68, 255)))
            if f is not None:
                items.append(dpg.draw_rectangle((bx, by), (bx + mw * f, by + 3), parent="wire_labels", color=(0, 0, 0, 0), fill=(190, 150, 250, 255)))
                items.append(dpg.draw_circle((bx + mw * f, by + 1.5), 2.5, parent="wire_labels", color=(0, 0, 0, 0), fill=(240, 232, 255, 255)))
            items.append(dpg.draw_text((bx, by + 4), nodeface._fmt(lo), parent="wire_labels", size=small, color=(150, 140, 190, 255)))
            t = nodeface._fmt(hi)
            items.append(dpg.draw_text((bx + mw - len(t) * small * 0.6, by + 4), t, parent="wire_labels", size=small, color=(150, 140, 190, 255)))
            self._mod_bars[(bx, by, bx + mw, by + small + 4)] = r

    def _step_mod_range(self, direction):
        """Ctrl+wheel over a range bar: the end the pointer is nearer, by
        a fiftieth of the range (the Remap's out_lo or out_hi)."""
        bars = getattr(self, "_mod_bars", None)
        if not bars:
            return False
        mx, my = dpg.get_mouse_pos(local=False)
        for (bx0, by0, bx1, by1), r in bars.items():
            if bx0 - 4 <= mx <= bx1 + 4 and by0 - 4 <= my <= by1:
                rn = self.graph.nodes.get(r)
                if not rn:
                    return False
                lo, hi = float(rn["params"].get("out_lo", 0.0)), float(rn["params"].get("out_hi", 1.0))
                key = "out_lo" if mx < (bx0 + bx1) / 2 else "out_hi"
                step = (abs(hi - lo) or 1.0) / 50.0 * (1 if direction > 0 else -1)
                self.snapshot(("modrange", r, key))
                rn["params"][key] = round(rn["params"].get(key, 0.0) + step, 5)
                self._set_param_widget(r, key, rn["params"][key])
                self._refresh_summary(r)
                self.touch()
                self.status(f"{rn.get('label') or 'Remap'}: {nodeface._fmt(rn['params']['out_lo'])} .. {nodeface._fmt(rn['params']['out_hi'])}")
                return True
        return False

    def reset_hovered(self):
        """Backspace over a value box: the default again."""
        h = self._hovered_field()
        if not h or not self.graph:
            return False
        w, nid, name, kind = h
        n = self.graph.nodes[nid]
        d = self.graph.node_def(n)
        self.snapshot()
        if kind == "param":
            p = next(p for p in d["params"] if p["name"] == name)
            n["params"][name] = p["default"]
        else:
            n.setdefault("inputs", {}).pop(name, None)
        self.touch()
        self._sync_pos(); self.rebuild()
        self.status(f"{name}: back to its default")
        return True

    def step_hovered(self, direction):
        """Ctrl+wheel over a dropdown: the next or previous choice; over a
        slider or a drag field: a step - one for an integer, a hundredth
        of the range or of the value for a float; over a modulation range
        bar, the nearer end by a fiftieth of the range."""
        if self._step_mod_range(direction):
            return True
        h = self._hovered_field()
        if not h or not self.graph:
            return False
        w, nid, name, kind = h
        t = dpg.get_item_type(w)
        if t.endswith(("SliderFloat", "SliderInt", "DragFloat", "DragInt")):
            cfg = dpg.get_item_configuration(w)
            cur = dpg.get_value(w)
            if t.endswith("Int"):
                step = 1
            elif w in self._log_sliders:
                step = (cfg.get("max_value") - cfg.get("min_value")) / 100.0      # a hundredth of the log range: a ratio
            else:
                lo, hi = cfg.get("min_value"), cfg.get("max_value")
                step = (hi - lo) / 100.0 if t.endswith("SliderFloat") and hi is not None and hi > lo else max(0.01, abs(cur) * 0.01)
            val = cur + (step if direction > 0 else -step)
            if cfg.get("clamped") or t.endswith("Slider"):
                lo, hi = cfg.get("min_value"), cfg.get("max_value")
                if lo is not None and hi is not None and hi > lo:
                    val = max(lo, min(hi, val))
            val = int(round(val)) if t.endswith("Int") else round(val, 6)
            dpg.set_value(w, val)
            if w in self._log_sliders:
                import math
                val = math.exp(val); self._log_label(w, val, self._log_sliders[w])
            (self._on_param if kind == "param" else self._on_input)(w, val)
            return True
        if not t.endswith("Combo"):
            return False
        items = dpg.get_item_configuration(w).get("items") or []
        if not items:
            return False
        cur = dpg.get_value(w)
        k = (items.index(cur) + (1 if direction > 0 else -1)) % len(items) if cur in items else 0
        dpg.set_value(w, items[k])
        self._on_param(w, items[k])
        return True

    def _param_widget(self, nid, n, p, multiline=False):
        v = n["params"].get(p["name"], p["default"])
        ud = (nid, p["name"])
        cb = self._on_param
        if p["type"] == "text" and (multiline or p.get("lines")):
            # rows of a bitmap are '/'-separated in the param and shown as lines
            shown = str(v).replace("/", "\n") if p.get("lines") else str(v)
            w = dpg.add_input_text(width=self.px(220), height=self.px(90 if not p.get("lines") else 150), multiline=True,
                                   default_value=shown, user_data=ud, callback=cb)
            self._widgets.add(w)
            return
        if p["type"] == "float":
            w = self._number_widget(p, float(v), None, ud, cb, True)
        elif p["type"] == "int" and n["type"] == "Effect settings" and p["name"] == "palette":
            # the default palette by name, not by number
            names = [f"{i}  {name}" for name, i in self._palette_names()]
            cur = next((s_ for s_ in names if s_.split("  ", 1)[0] == str(int(v))), f"{int(v)}  ?")
            w = dpg.add_combo(names, label=p["name"], width=self.px(120), default_value=cur, user_data=ud,
                              callback=lambda s_, a_: cb(s_, int(str(a_).split("  ", 1)[0])))
        elif p["type"] == "int":
            lo, hi = p.get("min"), p.get("max")
            if lo is not None and hi is not None and int(hi) - int(lo) <= 512:
                w = dpg.add_slider_int(label=p["name"], width=self.px(96), default_value=int(v), min_value=int(lo), max_value=int(hi),
                                       clamped=True, user_data=ud, callback=cb)
            else:
                w = dpg.add_input_int(label=p["name"], width=self.px(78), default_value=int(v), step=0,
                                  min_value=int(p.get("min", -1 << 30)), max_value=int(p.get("max", 1 << 30)),
                                  min_clamped="min" in p, max_clamped="max" in p, user_data=ud, callback=cb)
        elif p["type"] == "bool":
            w = dpg.add_checkbox(label=p["name"], default_value=bool(v), user_data=ud, callback=cb)
        elif p["type"] == "choice":
            w = dpg.add_combo(p["choices"], label=p["name"], width=self.px(90), default_value=str(v), user_data=ud, callback=cb)
        elif p["type"] == "color":
            rgb = list(v)[:3] if isinstance(v, (list, tuple)) else [255, 255, 255]
            w = dpg.add_color_edit([int(c) for c in rgb] + [255], label=p["name"], width=self.px(110), no_alpha=True,
                               user_data=ud, callback=cb)
        elif p["type"] == "ramp":
            self._ramp_widget(nid, n, p, v)
            return
        elif p["type"] == "curve":
            self._curve_widget(nid, n, p, v)
            return
        elif p["type"] == "text":
            w = dpg.add_input_text(label=p["name"], width=self.px(100), default_value=str(v), user_data=ud, callback=cb)
        elif p["type"] == "file":
            with dpg.group(horizontal=True):
                w = dpg.add_input_text(label=p["name"], width=self.px(120), default_value=str(v), user_data=ud, callback=cb)
                dpg.add_button(label="...", small=True, user_data=(nid, p["name"]),
                               callback=lambda s_, a_, u_: self._pick_file(u_))
        else:
            return
        dpg.bind_item_theme(w, self._field_theme())
        self._widgets.add(w)

    def _field_theme(self):
        """The look of a value field on a node: a box a shade lighter than the
        node's body (a thing to drag or type in), a slider's grab a narrow
        translucent bar so the value written across it stays readable.
        One theme per colour scheme; remade when the scheme changes."""
        from native import chrome
        from native.app import theme_colors, theme_is_light
        cols = theme_colors(self.app.prefs); light = theme_is_light(self.app.prefs)
        key = (cols["frame"], cols["accent"], light)
        th = self._field_themes.get(key)
        if th is None:
            fr = tuple((min(255, c + 12) if not light else max(0, c - 12)) for c in cols["frame"])
            ac = tuple(chrome.ACCENT[:3])
            with dpg.theme() as th:
                with dpg.theme_component(dpg.mvAll):
                    dpg.add_theme_color(dpg.mvThemeCol_FrameBg, fr + (255,), category=dpg.mvThemeCat_Core)
                    dpg.add_theme_color(dpg.mvThemeCol_FrameBgHovered, tuple(min(255, c + 8) for c in fr) + (255,), category=dpg.mvThemeCat_Core)
                    dpg.add_theme_color(dpg.mvThemeCol_SliderGrab, ac + (90,), category=dpg.mvThemeCat_Core)
                    dpg.add_theme_color(dpg.mvThemeCol_SliderGrabActive, ac + (160,), category=dpg.mvThemeCat_Core)
                    dpg.add_theme_style(dpg.mvStyleVar_GrabMinSize, 6, category=dpg.mvThemeCat_Core)
            self._field_themes[key] = th
        return th

    def _number_widget(self, spec, v, tag, ud, cb, show):
        """A number on a node: a slider when the definition gives a range (a
        log-scaled one moves by ratio - the widget holds the value's log
        and the callback maps it back), else a drag field paced by the
        value's size; the unit, if any, written after the value."""
        import math
        unit = spec.get("unit") or ""
        fmt = "%.5g" + (f" {unit}" if unit else "")          # five significant digits: 12000 K stays 12000, not 1.2e+04
        lo, hi = spec.get("min"), spec.get("max")
        kw = {"label": spec["name"], "user_data": ud, "show": show}
        if tag:
            kw["tag"] = tag
        if unit.lower() == spec["name"].lower():
            unit, fmt = "", "%.5g"                           # "1.2 Hz  hz" says it twice
        if lo is not None and hi is not None and (float(hi) - float(lo) <= 1000.0 or spec.get("scale") == "log"):
            lo, hi = float(lo), float(hi)
            if spec.get("scale") == "log" and lo > 0 and hi > lo:
                # the slider holds log(value): its travel is by ratio, the value shown by the label's format
                lv = math.log(max(lo, min(hi, v if v > 0 else lo)))
                w = dpg.add_slider_float(width=self.px(96), default_value=lv, min_value=math.log(lo), max_value=math.log(hi), clamped=True,
                                         format="", callback=lambda s_, a_: (self._log_label(s_, math.exp(a_), unit), cb(s_, math.exp(a_))), **kw)
                self._log_label(w, v, unit)
                self._log_sliders[w] = unit
                return w
            return dpg.add_slider_float(width=self.px(96), default_value=max(lo, min(hi, v)), min_value=lo, max_value=hi, clamped=True,
                                        format=fmt, callback=cb, **kw)
        return dpg.add_drag_float(width=self.px(78), default_value=v, speed=self._drag_speed(v, spec.get("default")), format=fmt, callback=cb, **kw)

    def _log_label(self, w, v, unit):
        """A log slider shows no value of its own (it holds a logarithm): the value goes in its label."""
        if dpg.does_item_exist(w):
            ud = dpg.get_item_user_data(w)
            name = ud[1] if isinstance(ud, tuple) else ""
            dpg.configure_item(w, label=f"{v:.5g}{(' ' + unit) if unit else ''}  {name}")

    @staticmethod
    def _drag_speed(v, default=None):
        """How much a drag field moves per pixel: a hundredth of the value's
        size, never under 0.005 - a big number moves in big steps, a small
        one finely."""
        try:
            m = max(abs(float(v or 0.0)), abs(float(default or 0.0)))
        except (TypeError, ValueError):
            m = 1.0
        return max(0.005, m * 0.01)

    def _palette_names(self):
        """[(name, id)] the sim knows, for the Effect settings' palette."""
        try:
            return self.app.eng.palette_list()
        except Exception:
            return [("Default", 0)]

    # --- the XY pads: two typed inputs as one point on a small square -----------------------
    def _pad_widget(self, nid, n, a, b, lo, hi):
        from native.textures import registry
        tex = f"gpad_{nid}_{a}_tex"
        if not dpg.does_item_exist(tex):
            dpg.add_dynamic_texture(PAD_PX, PAD_PX, [0.0, 0.0, 0.0, 1.0] * (PAD_PX * PAD_PX), tag=tex, parent=registry())
        size = self.px(PAD)
        with dpg.group(horizontal=True):
            btn = dpg.add_image_button(tex, width=size, height=size, frame_padding=0, user_data=(nid, a, b, lo, hi))
            with dpg.tooltip(btn):
                dpg.add_text(f"{a} and {b} as one point, {lo:g}..{hi:g}: drag to set both (the fields above follow); "
                             "the fields still take a typed value", wrap=260)
            stem = a[:-2] if a.endswith(("_u", "_x")) else a.rstrip("xu")
            dpg.add_text(stem or f"{a} {b}", color=DIM)
        self._pads[btn] = (nid, a, b, float(lo), float(hi), tex)
        self._pad_draw(btn)

    def _pad_values(self, nid, a, b):
        n = self.graph.nodes.get(nid)
        d = self.graph.node_def(n)
        da = next((i.get("default", 0.0) for i in d["inputs"] if i["name"] == a), 0.0)
        db = next((i.get("default", 0.0) for i in d["inputs"] if i["name"] == b), 0.0)
        return float(n["inputs"].get(a, da)), float(n["inputs"].get(b, db))

    def _pad_draw(self, btn):
        import numpy as np
        nid, a, b, lo, hi, tex = self._pads[btn]
        if nid not in self.graph.nodes or not dpg.does_item_exist(tex):
            return
        x, y = self._pad_values(nid, a, b)
        img = np.empty((PAD_PX, PAD_PX, 4), np.float32)
        img[:] = (0.11, 0.12, 0.14, 1.0)
        for k in (PAD_PX // 4, PAD_PX // 2, 3 * PAD_PX // 4):
            img[k, :, :3] = (0.2, 0.21, 0.24); img[:, k, :3] = (0.2, 0.21, 0.24)
        if lo < 0.0 < hi:                                     # the zero lines, when the range crosses zero
            k = int(round((0.0 - lo) / (hi - lo) * (PAD_PX - 1)))
            img[PAD_PX - 1 - k, :, :3] = (0.3, 0.32, 0.36); img[:, k, :3] = (0.3, 0.32, 0.36)
        img[0, :, :3] = img[-1, :, :3] = img[:, 0, :3] = img[:, -1, :3] = (0.27, 0.29, 0.32)
        fx = (max(lo, min(hi, x)) - lo) / (hi - lo); fy = (max(lo, min(hi, y)) - lo) / (hi - lo)
        cx, cy = int(round(fx * (PAD_PX - 1))), int(round((1.0 - fy) * (PAD_PX - 1)))
        from native import chrome
        col = tuple(c / 255.0 for c in chrome.ACCENT[:3])
        yy, xx = np.ogrid[:PAD_PX, :PAD_PX]
        dot = (xx - cx) ** 2 + (yy - cy) ** 2 <= 9
        img[dot, :3] = col
        img[cy, :, :3] = img[cy, :, :3] * 0.5 + np.array(col) * 0.5
        img[:, cx, :3] = img[:, cx, :3] * 0.5 + np.array(col) * 0.5
        dpg.set_value(tex, img.ravel())

    def _poll_pads(self):
        """A pad held: the point under the pointer into both inputs, the
        fields and the picture following; one undo step per stroke."""
        if not self.graph:
            return
        active = None
        for btn, (nid, a, b, lo, hi, tex) in list(self._pads.items()):
            if dpg.does_item_exist(btn) and dpg.is_item_active(btn) and nid in self.graph.nodes:
                active = btn; break
        if active is None:
            if self._pad_stroke is not None:
                self._pad_stroke = None
                self._sync_pos()
            return
        st = dpg.get_item_state(active)
        if "rect_min" not in st:
            return
        (x0, y0), (w, h) = st["rect_min"], st["rect_size"]
        mx, my = dpg.get_mouse_pos(local=False)
        fx = max(0.0, min(1.0, (mx - x0) / max(1.0, w - 1))); fy = max(0.0, min(1.0, 1.0 - (my - y0) / max(1.0, h - 1)))
        self._pad_apply(active, fx, fy)

    def _pad_apply(self, btn, fx, fy):
        """The pad's point (0..1 across, 0..1 up) into its two inputs, the
        fields and the picture; the first change of a stroke takes the undo step."""
        nid, a, b, lo, hi, tex = self._pads[btn]
        x, y = lo + fx * (hi - lo), lo + fy * (hi - lo)
        cur = self._pad_values(nid, a, b)
        if abs(cur[0] - x) < 1e-6 and abs(cur[1] - y) < 1e-6:
            return
        if self._pad_stroke != btn:
            self.touch(); self.snapshot(("pad", nid, a))
            self._pad_stroke = btn
        n = self.graph.nodes[nid]
        n.setdefault("inputs", {})[a] = round(x, 4); n["inputs"][b] = round(y, 4)
        for name, val in ((a, x), (b, y)):
            w_ = f"gin_{nid}_{name}_w"
            if dpg.does_item_exist(w_):
                dpg.set_value(w_, float(val))
        was_dirty = self._dirty
        self.touch()
        if self.live_poke(nid, a, x) and self.live_poke(nid, b, y) and not was_dirty:
            self._dirty = 0.0                            # the running effect follows the dot: no rebuild
        self._pad_draw(btn)

    def _pick_file(self, target):
        """The file dialog, for a node's file param; the choice lands in the
        param (relative to the project when it is inside it) and rebuilds."""
        self._file_target = target
        if not dpg.does_item_exist("graph_file_dialog"):
            with dpg.file_dialog(directory_selector=False, show=False, tag="graph_file_dialog", width=640, height=440,
                                 callback=lambda s_, a_: self._file_picked(a_.get("file_path_name", ""))):
                for ext, col in ((".png", (120, 200, 120)), (".jpg", (120, 200, 120)), (".jpeg", (120, 200, 120)),
                                 (".gif", (120, 200, 120)), (".bmp", (120, 200, 120)), (".*", (180, 180, 180))):
                    dpg.add_file_extension(ext, color=col)
        dpg.show_item("graph_file_dialog")

    def _file_picked(self, path):
        if not path or not getattr(self, "_file_target", None) or not self.graph:
            return
        nid, name = self._file_target
        if nid not in self.graph.nodes:
            return
        proj = self.app.project.path
        try:
            rel = os.path.relpath(path, proj)
            if not rel.startswith(".."):
                path = rel.replace("\\", "/")
        except ValueError:
            pass
        self.snapshot(); self._sync_pos()
        self.graph.nodes[nid]["params"][name] = path
        self.rebuild()
        self.status(f"{os.path.basename(path)}")

    def image_to_bitmap(self, nid):
        """An Image node becomes a Bitmap and a Colour pick, wired the same:
        the picture as digits you can edit, its palette as colours you can
        change. Up to eight colours; the image is re-quantised to fit."""
        from native.nodedefs import load_image_indexed
        n = self.graph.nodes.get(nid)
        if not n or n["type"] != "Image":
            return
        p = n["params"]
        path = str(p.get("file", "")).strip()
        if path and not os.path.isabs(path):
            path = os.path.join(self.app.project.path, path)
        if not path or not os.path.exists(path):
            self.status("the Image node has no file"); return
        w, h = int(p.get("width", 16)), int(p.get("height", 16))
        try:
            idx, palette = load_image_indexed(path, w, h, min(8, int(p.get("colours", 8))), bool(p.get("alpha_clear", True)))
        except Exception as e:
            self.status(f"cannot read the image: {e}"); return
        rows = "/".join("".join("." if idx[y * w + x] == 255 else str(min(9, idx[y * w + x])) for x in range(w)) for y in range(h))
        self.snapshot(); self._sync_pos()
        g = self.graph
        pos = n["pos"]
        bm = g.add("Bitmap", (pos[0], pos[1]), {"rows": rows})
        cp = g.add("Colour pick", (pos[0] + 240, pos[1]), {f"c{k}": list(palette[k]) if k < len(palette) else [0, 0, 0] for k in range(8)})
        mk = g.add("Mask", (pos[0] + 480, pos[1]))
        g.link(bm, "slot", cp, "index"); g.link(cp, "color", mk, "color"); g.link(bm, "on", mk, "mask")
        # the same wires in and out
        for a, o, b_, i in [l for l in g.links if l[2] == nid]:
            if i in ("u", "v"):
                g.link(a, o, bm, i)
        for a, o, b_, i in [l for l in g.links if l[0] == nid]:
            src = {"color": (mk, "color"), "slot": (bm, "slot"), "on": (bm, "on")}.get(o)
            if src:
                g.link(src[0], src[1], b_, i)
        for k in ("u", "v"):
            if k in n.get("inputs", {}):
                g.nodes[bm]["inputs"][k] = n["inputs"][k]
        g.remove(nid)
        self.rebuild()
        self.status(f"image -> Bitmap ({w} x {h}, {len(palette)} colours) + Colour pick")

    # --- a colour ramp on the node: the gradient drawn, then a row per stop -----------
    def _ramp_widget(self, nid, n, p, stops):
        stops = [list(st) for st in (stops or p["default"])]
        W, H = self.px(220), self.px(14)
        with dpg.drawlist(width=W, height=H):
            srt = sorted(stops, key=lambda st: st[0])
            for x in range(0, W, 2):
                t = x / max(1, W - 1)
                r, g, b = self._ramp_colour(srt, t, str(n["params"].get("mode", "linear")))
                dpg.draw_rectangle((x, 0), (x + 2, H), color=(r, g, b, 255), fill=(r, g, b, 255))
        for k, st in enumerate(stops):
            with dpg.group(horizontal=True):
                w1 = dpg.add_input_float(width=self.px(56), default_value=float(st[0]), step=0, format="%.2f",
                                         user_data=(nid, p["name"], k, "pos"), callback=self._on_ramp)
                w2 = dpg.add_color_edit([int(st[1]), int(st[2]), int(st[3]), 255], width=self.px(60), no_alpha=True, no_inputs=True,
                                        user_data=(nid, p["name"], k, "col"), callback=self._on_ramp)
                self._widgets.update((w1, w2))
                if len(stops) > 2:
                    dpg.add_button(label="-", small=True, user_data=(nid, p["name"], k, "del"), callback=self._on_ramp)
        dpg.add_button(label="+ stop", small=True, user_data=(nid, p["name"], -1, "add"), callback=self._on_ramp)

    def _curve_widget(self, nid, n, p, pts):
        pts = sorted([list(q) for q in (pts or p["default"])], key=lambda q: q[0])
        W, H = self.px(160), self.px(80)
        with dpg.drawlist(width=W, height=H):
            dpg.draw_rectangle((0, 0), (W - 1, H - 1), color=(70, 74, 82, 255))
            prev = None
            for x in range(0, W, 2):
                t = x / max(1, W - 1)
                y = (1.0 - max(0.0, min(1.0, self._curve_at(pts, t)))) * (H - 1)
                if prev is not None:
                    dpg.draw_line(prev, (x, y), color=(110, 190, 250, 255), thickness=1.5)
                prev = (x, y)
            for q in pts:
                dpg.draw_circle((q[0] * (W - 1), (1.0 - q[1]) * (H - 1)), 3, color=(255, 255, 255, 255), fill=(255, 255, 255, 255))
        for k, q in enumerate(pts):
            with dpg.group(horizontal=True):
                w1 = dpg.add_input_float(width=self.px(56), default_value=float(q[0]), step=0, format="%.2f",
                                         user_data=(nid, p["name"], k, "x"), callback=self._on_curve)
                w2 = dpg.add_input_float(width=self.px(56), default_value=float(q[1]), step=0, format="%.2f",
                                         user_data=(nid, p["name"], k, "y"), callback=self._on_curve)
                self._widgets.update((w1, w2))
                if len(pts) > 2:
                    dpg.add_button(label="-", small=True, user_data=(nid, p["name"], k, "del"), callback=self._on_curve)
        dpg.add_button(label="+ point", small=True, user_data=(nid, p["name"], -1, "add"), callback=self._on_curve)

    @staticmethod
    def _curve_at(pts, t):
        if t <= pts[0][0]:
            return pts[0][1]
        if t >= pts[-1][0]:
            return pts[-1][1]
        for i in range(len(pts) - 1):
            a, b = pts[i], pts[i + 1]
            if a[0] <= t <= b[0]:
                f = (t - a[0]) / (b[0] - a[0]) if b[0] > a[0] else 0.0
                f = f * f * (3 - 2 * f)
                return a[1] + (b[1] - a[1]) * f
        return pts[-1][1]

    def _on_curve(self, sender, val, ud):
        nid, name, k, what = ud
        n = self.graph.nodes[nid]
        pts = sorted([list(q) for q in n["params"].get(name) or []], key=lambda q: q[0])
        self.touch(); self.snapshot(("curve", nid, name, k, what))
        if what == "x":
            pts[k][0] = max(0.0, min(1.0, float(val)))
        elif what == "y":
            pts[k][1] = float(val)
        elif what == "del":
            pts.pop(k)
        elif what == "add":
            pts.append([0.5, 0.5])
        n["params"][name] = pts
        self._sync_pos(); self.rebuild()

    @staticmethod
    def _ramp_colour(srt, t, mode):
        if t <= srt[0][0]:
            return srt[0][1:4]
        if t >= srt[-1][0]:
            return srt[-1][1:4]
        for i in range(len(srt) - 1):
            a, b = srt[i], srt[i + 1]
            if a[0] <= t <= b[0]:
                f = (t - a[0]) / (b[0] - a[0]) if b[0] > a[0] else 0.0
                if mode == "constant":
                    f = 0.0
                elif mode == "ease":
                    f = f * f * (3 - 2 * f)
                return [int(a[j] + (b[j] - a[j]) * f) for j in (1, 2, 3)]
        return srt[-1][1:4]

    def _on_ramp(self, sender, val, ud):
        nid, name, k, what = ud
        n = self.graph.nodes[nid]
        stops = [list(st) for st in n["params"].get(name) or []]
        self.touch(); self.snapshot(("ramp", nid, name, k, what))
        if what == "pos":
            stops[k][0] = max(0.0, min(1.0, float(val)))
        elif what == "col":
            stops[k][1:4] = [int(round(c * 255)) if c <= 1.0 else int(c) for c in val[:3]]
        elif what == "del":
            stops.pop(k)
        elif what == "add":
            stops.append([1.0, 255, 255, 255])
        n["params"][name] = stops
        if what in ("del", "add") or True:
            self._sync_pos(); self.rebuild()      # the strip redraws with the stops

    def _on_param(self, sender, val):
        self.touch()
        nid, name = dpg.get_item_user_data(sender)
        self.snapshot(("param", nid, name))
        if isinstance(val, str) and "\n" in val:
            val = val.replace("\r", "").replace("\n", "/")      # a bitmap's lines back to rows
        if isinstance(val, (list, tuple)) and len(val) >= 3 and all(isinstance(x, float) for x in val):
            val = [int(round(x * 255)) if x <= 1.0 else int(x) for x in val[:3]]
        self.graph.nodes[nid]["params"][name] = val
        self._refresh_summary(nid)
        for k in self._same_type_selected(nid):
            self.graph.nodes[k]["params"][name] = val
            self._set_param_widget(k, name, val)
            self._refresh_summary(k)
        if self.graph.nodes[nid]["type"] == "Frame" and name in ("title", "colour"):
            self._sync_pos(); self.rebuild()
        if self.graph.nodes[nid]["type"] in ("Graph input", "Graph output") and name in ("name", "type"):
            if name == "type":
                # the pin changed type: its wires no longer fit
                self.graph.links = [l for l in self.graph.links if l[0] != nid and l[2] != nid]
            self.rebuild()
        elif name == "name" and (self.graph.nodes[nid]["type"] in G.SENDS or self.graph.nodes[nid]["type"] in G.RECEIVES):
            t = self.graph.nodes[nid]["type"]
            dpg.configure_item(f"gnode_{nid}", label=f"{t}: {val}")   # the title names the pair

    def _make_link(self, a, out, b, inp):
        ta, tb = self._pins.get((a, "out", out)), self._pins.get((b, "in", inp))
        if not ta or not tb:
            return
        lid = dpg.add_node_link(ta, tb, parent="node_editor")
        meta = self.graph.link_meta.get((b, inp)) or {}
        col = meta.get("color")
        thin = self.scopes().get(a) == "frame"           # control rate: one value a frame, drawn thinner
        if col or thin:
            th = self._wire_theme(tuple(col) if col else PIN_COL.get(self._ptype.get(ta, "float"), PIN_COL["float"]), thin=thin)
        else:
            th = self.themes().link[self._ptype.get(ta, "float")]
        dpg.bind_item_theme(lid, th)
        self.links[lid] = (b, inp)
        self._link_normal[lid] = th
        self._show_input(b, inp, True)

    def _wire_theme(self, col, thin=False):
        """A wire's theme: its colour; thin for a frame-scope source (a
        value once a frame - control rate - against the per-pixel wires)."""
        key = (col, thin, self.zoom if thin else None)
        th = self._wire_themes.get(key)
        if th is None:
            with dpg.theme() as th:
                with dpg.theme_component(dpg.mvNodeLink):
                    dpg.add_theme_color(dpg.mvNodeCol_Link, col, category=dpg.mvThemeCat_Nodes)
                    dpg.add_theme_color(dpg.mvNodeCol_LinkHovered, (255, 255, 255), category=dpg.mvThemeCat_Nodes)
                    dpg.add_theme_color(dpg.mvNodeCol_LinkSelected, (255, 255, 255), category=dpg.mvThemeCat_Nodes)
                    if thin:
                        dpg.add_theme_style(dpg.mvNodeStyleVar_LinkThickness, max(1.0, 1.4 * self.zoom), category=dpg.mvThemeCat_Nodes)
            self._wire_themes[key] = th
        return th

    def scopes(self):
        """{nid: "frame" | "pixel"} for the graph as it is now, from the
        plan (no codegen); cached until the next edit; {} when the graph
        cannot be planned."""
        if not self.graph:
            return {}
        c = self._scope_cache
        if c and c[0] == self.edits and c[2] is self.graph:
            return c[1]
        try:
            _, _, scope, _, _, _ = self.graph.plan()
        except Exception:
            scope = {}
        if scope and self.graph.has_sends():
            # the plan joins the pairs away: a Send takes what feeds it, a Receive its Send
            src = {(b, i): a for a, _, b, i in self.graph.links}
            for nid, n in self.graph.nodes.items():
                if n["type"] in G.SENDS:
                    scope[nid] = scope.get(src.get((nid, "in")), "frame")
            for rcv, snd in self.graph._send_pairs().items():
                scope[rcv] = scope.get(snd, "frame")
        self._scope_cache = (self.edits, scope, self.graph)
        return scope

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

    def on_delink(self, sender, app_data):
        self.touch()
        self.snapshot()
        lid = app_data
        b, inp = self.links.pop(lid, (None, None))
        if b is not None:
            self.graph.unlink(b, inp)
            self._show_input(b, inp, False)
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
        if dpg.is_item_hovered("node_editor") and not ctrl and not shift and self.ext_sel and over not in self.ext_sel                 and not getattr(self.app, "_popup_click", False):
            self.set_selection([])                     # a plain click elsewhere: the key selection is over
        # where every node is now: a node dragged onto a wire is spliced in on release
        self._press_pos = {nid: tuple(dpg.get_item_pos(f"gnode_{nid}")) for nid in self.graph.nodes if dpg.does_item_exist(f"gnode_{nid}")}
        self._node_press = over is not None          # a press on a node: the drag that follows moves the selection
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
        """The node whose rectangle holds the point, or None."""
        if not self.graph:
            return None
        for nid in self.graph.nodes:
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
            self.snapshot(); self.graph.link(frm[0], frm[1], nid, inp)
        else:
            out = next((o["name"] for o in d["outputs"] if compatible(o["type"], t)), None)
            if out is None:
                self.status("no output there fits"); return
            self.snapshot(); self.graph.link(nid, out, frm[0], frm[1])
        self.rebuild()

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
            self.status(f"drop to splice into {a} . {out} -> {b} . {inp}")
        # the wiring it would become, drawn over everything, following the node
        p_src = self._pin_point(a, "out", out)
        p_in = self._pin_point(nid, "in", my_in) or self._node_edge(nid, "in")
        p_out = self._pin_point(nid, "out", my_out) or self._node_edge(nid, "out")
        p_dst = self._pin_point(b, "in", inp)
        for tag, p0, p1 in (("splice_a", p_src, p_in), ("splice_b", p_out, p_dst)):
            if dpg.does_item_exist(tag) and p0 and p1:
                dd = max(50.0, abs(p1[0] - p0[0]) * 0.5)
                dpg.configure_item(tag, p1=p0, p2=(p0[0] + dd, p0[1]), p3=(p1[0] - dd, p1[1]), p4=p1, show=True)

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
            if dpg.does_item_exist(lid):
                dpg.bind_item_theme(lid, self._link_normal.get(lid, 0))
            self._splice = None
        for tag in ("splice_a", "splice_b"):
            if dpg.does_item_exist(tag):
                dpg.configure_item(tag, show=False)

    def _splice_apply(self):
        """The drop: the node into the wire, the node downstream pushed
        right if the two now overlap."""
        nid, lid, a, out, b, inp, my_in, my_out = self._splice
        self._splice_clear()
        if nid not in self.graph.nodes or a not in self.graph.nodes or b not in self.graph.nodes:
            return
        self.snapshot(); self._sync_pos()
        self.graph.link(a, out, nid, my_in)
        self.graph.link(nid, my_out, b, inp)
        pn, sn = self.graph.nodes[nid]["pos"], self._node_size(nid)
        pb, sb = self.graph.nodes[b]["pos"], self._node_size(b)
        if pb[0] < pn[0] + sn[0] + 20 and pb[0] + sb[0] > pn[0] and abs(pb[1] - pn[1]) < max(sn[1], sb[1]):
            self.graph.nodes[b]["pos"][0] = pn[0] + sn[0] + 40
        self.rebuild()
        self.status(f"spliced into the wire ({a} . {out} -> {b} . {inp})")

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

    # --- the right-click menus -------------------------------------------------------------
    def open_menu(self):
        """Right click: over a pin, the pin's menu; over a node, the node's;
        over empty editor, the add-node menu at the pointer."""
        if not dpg.does_item_exist("node_editor") or not dpg.is_item_hovered("node_editor"):
            return
        mx, my = dpg.get_mouse_pos(local=False)
        for (nid, kind, name), tag in self._pins.items():
            if dpg.does_item_exist(tag) and dpg.is_item_hovered(tag):
                self._ctx = (kind, nid, name)
                self._fill_ctx_menu()
                dpg.configure_item("graph_ctx", show=True); dpg.set_item_pos("graph_ctx", [mx, my])
                return
        for nid in list(self.graph.nodes) if self.graph else []:
            tag = f"gnode_{nid}"
            if dpg.does_item_exist(tag) and dpg.is_item_hovered(tag):
                self._ctx = ("node", nid, None)
                self._fill_ctx_menu()
                dpg.configure_item("graph_ctx", show=True); dpg.set_item_pos("graph_ctx", [mx, my])
                return
        gx, gy = self._to_graph((mx, my))
        self._menu_pos = (gx - 20, gy - 10)
        self._pending = None
        self.show_add_menu((mx, my))

    def show_add_menu(self, at, only=None, focus=True):
        """The add menu at a screen position, its search box focused and
        empty. `only` narrows it to those node types (a dropped wire)."""
        self._only = only
        self._fill_quick()
        dpg.set_value("graph_search", "")
        self._search("graph_search", "")
        dpg.configure_item("graph_menu", show=True)
        dpg.set_item_pos("graph_menu", list(at))
        if focus:
            dpg.focus_item("graph_search")

    def _search(self, sender, text):
        """Filter the add menu: with text, a flat list of matches on name or
        description; without, the categories (or the dropped wire's list)."""
        text = (text or "").strip().lower()
        only = getattr(self, "_only", None)
        flat = bool(text) or only is not None
        dpg.configure_item("graph_cats", show=not flat)
        dpg.configure_item("graph_hits", show=flat)
        if not flat:
            return
        dpg.delete_item("graph_hits", children_only=True)
        self._menu_entries_cache = None
        names = only if only is not None else [n.split(" / ", 1)[1] for n in self.type_names()]
        names = [n for n in names if not self._feature_off(n)]
        if only is None:
            names = ["preset:" + p for p in sorted(self.presets())] + names
        hits = []
        for n in names:
            d = self.lib.get(n, {})
            lbl = d.get("label", n) if not n.startswith("preset:") else n[7:] + "  (preset)"
            if not text or text in lbl.lower() or text in n.lower() or text in d.get("doc", "").lower():
                hits.append((0 if text and lbl.lower().startswith(text) else 1, lbl, n))
        if text:
            hits.sort()                    # else the given order: most useful first
        if only is not None and not text:
            dpg.add_text("connect to a new", parent="graph_hits", color=DIM)
        for _, lbl, n in hits[:24]:
            dpg.add_selectable(label=lbl, parent="graph_hits", user_data=n,
                               callback=lambda s, a, u: self.add_node_at_menu(u))
        if not hits:
            dpg.add_text("no match", parent="graph_hits", color=DIM)
        rows = min(len(hits), 24) + (1 if only is not None and not text else 0)
        dpg.configure_item("graph_hits", height=max(30, 21 * max(rows, 1) + 12))

    def _search_enter(self, sender, text):
        """Enter in the search box adds the first hit."""
        kids = dpg.get_item_children("graph_hits", 1) or []
        for k in kids:
            u = dpg.get_item_user_data(k)
            if u:
                self.add_node_at_menu(u)
                return

    def _fill_ctx_menu(self):
        """The context menu's rows, for whatever was right-clicked."""
        dpg.delete_item("graph_ctx", children_only=True)
        kind, nid, name = self._ctx
        n = self.graph.nodes[nid]
        d = self.graph.node_def(n)
        P = "graph_ctx"
        close = lambda: dpg.configure_item(P, show=False)

        def row(label, fn):
            # Dear PyGui calls a callback with as many of (sender, app_data,
            # user_data) as it has parameters - a third one with a default
            # is overwritten by user_data, a fourth is an error - so what a
            # row does rides in user_data. Inside a fold (tree node) the row
            # goes to the fold: the container stack says where we are.
            # A set width: a selectable with none takes the width there is,
            # and in a window that sizes itself to its content the two chase
            # each other - the menu grew a few pixels every frame until it met
            # the screen's edge, once a fold was opened.
            parent = dpg.top_container_stack() or P
            dpg.add_selectable(label=label, parent=parent, user_data=fn, width=280, callback=lambda s, a, u: (close(), u()))

        if kind == "in":
            linked = any(l[2] == nid and l[3] == name for l in self.graph.links)
            dpg.add_text(f"{n['type']} . {name}", parent=P, color=DIM)
            pd_ = next((x.get("doc") for x in d["inputs"] if x["name"] == name), None)
            if pd_:
                dpg.add_text(pd_, parent=P, color=(170, 178, 192), wrap=260)
            i = next(x for x in d["inputs"] if x["name"] == name)
            if linked:
                row("disconnect", lambda: self._disconnect_in(nid, name))
            row("reset to default", lambda: self._reset_input(nid, name, i))
            if i["type"] == "float" and not linked:
                row("type an expression...", lambda: self.expr_for(nid, name, "input"))
            if linked:
                from native import chrome
                lbl = (self.graph.link_meta.get((nid, name)) or {}).get("label", "")
                with dpg.tree_node(label="this wire", parent=P):
                    row("relabel..." if lbl else "label...",
                        lambda: chrome.ask(self.app, "Wire label", "a few words on what this wire carries", lbl,
                                           lambda v: self.set_wire_label(nid, name, v)))
                    if lbl:
                        row("remove the label", lambda: self.set_wire_label(nid, name, ""))
                    self._colour_rows(dpg.last_container(), [(nid, name)])
                a, out = next((l[0], l[1]) for l in self.graph.links if l[2] == nid and l[3] == name)
                at = next((o["type"] for o in self.graph.node_def(self.graph.nodes[a])["outputs"] if o["name"] == out), "float")
                between = self._between(at, i["type"])
                if between:
                    with dpg.tree_node(label="insert on the wire", parent=P):
                        for t in between[:8]:
                            row(f"  {t}", lambda t=t: self._insert_before(nid, name, t))
            # expose this input as a control: a slider or checkbox node, wired in
            ctrls = ["Speed", "Intensity", "Custom 1", "Custom 2", "Custom 3"] if i["type"] != "bool" \
                    else ["Check 1", "Check 2", "Check 3"]
            if i["type"] != "color":
                with dpg.tree_node(label="drive with a slider", parent=P):
                    for c in ctrls:
                        row(f"  {c}", lambda c=c: self._drive_with(nid, name, c))
            if i["type"] == "float" and (nid, name) not in {(l[2], l[3]) for l in self.graph.links}:
                # modulation as a gesture: a source and a folded Remap about the value typed here
                with dpg.tree_node(label="modulate with", parent=P):
                    for label, src in self.MODULATORS:
                        row(f"  {label}", lambda src=src: self.modulate(nid, name, src))
            if i["type"] in ("float", "bool") and not linked and self.file:
                # a controller's knob onto this typed value (Playback > MIDI controller lists the rest)
                from native import midi_ui, midi
                t = midi_ui.pin_target(self.app, nid, name)
                row("MIDI learn: move a knob", lambda: midi_ui.learn(self.app, t))
                for k, ctl in midi_ui.mapped_to(self.app, t):
                    row(f"forget {midi.ctl_label(ctl)}", lambda k=k: midi_ui.forget(self.app, k))
        elif kind == "out":
            outs = [l for l in self.graph.links if l[0] == nid and l[1] == name]
            dpg.add_text(f"{n['type']} . {name}", parent=P, color=DIM)
            pd_ = next((x.get("doc") for x in d["outputs"] if x["name"] == name), None)
            if pd_:
                dpg.add_text(pd_, parent=P, color=(170, 178, 192), wrap=260)
            o = next(x for x in d["outputs"] if x["name"] == name)
            if self.preview == (nid, name):
                row("stop previewing this output", self.stop_preview)
            else:
                row("preview this output", lambda: self.preview_pin(nid, name))
            if outs:
                row(f"disconnect all ({len(outs)})", lambda: self._disconnect_out(nid, name))
                with dpg.tree_node(label="these wires' colour", parent=P):
                    self._colour_rows(dpg.last_container(), [(l[2], l[3]) for l in outs])
            with dpg.tree_node(label="connect to a new node", parent=P, default_open=True):
                for t in self._consumers(o["type"]):
                    row(f"  {t}", lambda t=t: self._connect_new(nid, name, o["type"], t))
        else:
            # A node's menu: what is done most on top - duplicate, label,
            # the shape toggles - and the rest in folds (delete, colour,
            # settings as pins, sub-graph, more), which open in place.
            dpg.add_text(n.get("label") or d.get("label") or n["type"], parent=P, color=DIM)
            if d.get("doc"):
                dpg.add_text(d["doc"], parent=P, color=(170, 178, 192), wrap=300)
            if nid in self.problems:
                m = self.problems[nid]
                dpg.add_text(m, parent=P, color=(235, 80, 70) if m.startswith("error") else (240, 190, 70))
            if n["type"].startswith(G.SUB):
                row("edit sub-graph", lambda: self.enter_sub(nid))
                row("unfold: its nodes in place of it", lambda: self.unfold_sub(nid))
            row("duplicate", lambda: self._dup(nid))
            row("duplicate with inputs", lambda: self._dup(nid, True))
            if not n["type"].startswith(G.SUB) and n["type"] not in ("Output", "Effect settings", "Note", "Frame", "Graph input", "Graph output"):
                row("change type... (the wires stay)", lambda: self.pick_type_for(nid))
            row("label this node...", lambda: (self.set_selection([nid]), self.label_selected()))
            if d["inputs"] or d["params"]:
                row("expand" if n.get("collapsed") else "collapse", lambda: self._collapse(nid))
                row("show all pins" if n.get("hide_pins") else "hide unwired pins", lambda: self._toggle(nid, "hide_pins"))
            row("unmute" if n.get("muted") else "mute (pass through)", lambda: self._toggle(nid, "muted"))
            if d.get("params") or d.get("inputs"):
                row("reset settings to defaults", lambda: self.reset_node(nid))
            wired_ = {i_ for b_, i_ in ((l[2], l[3]) for l in self.graph.links) if b_ == nid}
            nums = [(i_["name"], "input") for i_ in d["inputs"] if i_["type"] == "float" and i_["name"] not in wired_] \
                 + [(p_["name"], "param") for p_ in d["params"] if p_["type"] in ("float", "int")]
            if nums:
                with dpg.tree_node(label="type an expression for", parent=P):
                    for nm, kd in nums:
                        row(f"  {nm}", lambda nm=nm, kd=kd: self.expr_for(nid, nm, kd))
            if n["type"] == "Image":
                row("convert to Bitmap + Colour pick", lambda: self.image_to_bitmap(nid))
            selected = bool(self._selected())
            with dpg.tree_node(label="delete", parent=P):
                row("delete", lambda: self._delete_node(nid))
                row("delete and reconnect", lambda: (self.set_selection([nid]), self.dissolve_selected()))
                row("disconnect all (keep the node)", lambda: self._disconnect_node(nid))
            with dpg.tree_node(label="colour", parent=P):
                self._node_colour_rows(dpg.last_container(), nid)
            base = self.lib.get(n["type"])
            exp = n.get("expose") or []
            free = [p for p in G.exposable(base) if p not in exp] if base and G.exposable(base) else []
            if free or exp:
                with dpg.tree_node(label="settings as pins", parent=P):
                    if free:
                        dpg.add_text("expose a setting as a pin", color=DIM)
                        for p in free:
                            row(f"  {p}", lambda p=p: self._expose(nid, p, True))
                    if exp:
                        dpg.add_text("back to a setting", color=DIM)
                        for p in exp:
                            row(f"  {p}", lambda p=p: self._expose(nid, p, False))
            if self.cur_dir == self.sub_dir and d["params"] and not n["type"].startswith(G.SUB):
                # inside a sub-graph: a setting can be promoted to the sub node outside
                prom = n.get("promote") or []
                pfree = [p["name"] for p in d["params"] if p["name"] not in prom and p["type"] not in ("file",)]
                if pfree or prom:
                    with dpg.tree_node(label="promote to the sub-graph node", parent=P):
                        for p in pfree:
                            row(f"  promote {p}", lambda p=p: self._promote(nid, p, True))
                        for p in prom:
                            row(f"  keep {p} inside", lambda p=p: self._promote(nid, p, False))
            with dpg.tree_node(label="selection and sub-graph" if selected else "more", parent=P):
                if selected:
                    row("copy selection", self.copy)
                    row("cut selection", self.cut)
                    row("fold selection into a sub-graph", lambda: self.make_sub_from_selection(None))
                    with dpg.tree_node(label="merge selection through", parent=P):
                        for op in ("Add", "Subtract", "Multiply", "Min", "Max", "Mix", "Blend"):
                            row(f"  {op}", lambda op=op: self.merge_selected(op))
                if not n["type"].startswith(G.SUB) and n["type"] not in ("Frame", "Note", "Knot"):
                    from native import chrome
                    row("save as a preset...", lambda: chrome.ask(self.app, "Node preset", "a name for this node as it is set up",
                                                                  "", lambda v: self.save_preset(nid, v)))
                row("where is this type used", lambda: self.show_where_used(n["type"]))
                row("remove from favourites" if n["type"] in self.app.prefs.get("fav_nodes", []) else "add to favourites",
                    lambda: self.toggle_favourite(n["type"]))

    def where_used(self, type_):
        """Every graph and sub-graph in the project with a node of this type,
        with how many: [(file, is_sub, count)]."""
        import json
        out = []
        for d, sub in ((self.dir, False), (self.sub_dir, True)):
            for f in sorted(os.listdir(d)):
                if not f.endswith(".json"):
                    continue
                try:
                    nodes = json.load(open(os.path.join(d, f), encoding="utf-8")).get("nodes", [])
                except Exception:
                    continue
                n = sum(1 for x in nodes if x.get("type") == type_)
                if n:
                    out.append((f, sub, n))
        return out

    def show_where_used(self, type_):
        """The list, in a small window: a click opens that graph."""
        P = "where_win"
        if not dpg.does_item_exist(P):
            dpg.add_window(tag=P, label="Where used", width=360, height=300, show=False, no_collapse=True)
        dpg.delete_item(P, children_only=True)
        label = self.lib.get(type_, {}).get("label") or (type_[len(G.SUB):] + " (sub-graph)" if type_.startswith(G.SUB) else type_)
        dpg.add_text(label, parent=P, color=(90, 169, 230))
        rows = self.where_used(type_)
        if not rows:
            dpg.add_text("used in no graph", parent=P, color=DIM)
        for f, sub, n in rows:
            dpg.add_selectable(label=f"{f[:-5]}{'  (sub-graph)' if sub else ''}   x{n}", parent=P, user_data=(f, sub), width=300,
                               callback=lambda s, a, u: (dpg.hide_item(P), self.app.show_layout("graph"), self.open(u[0], sub=u[1])))
        vw, vh = dpg.get_viewport_client_width(), dpg.get_viewport_client_height()
        dpg.configure_item(P, pos=(vw // 2 - 180, vh // 3), show=True)

    def _promote(self, nid, name, on):
        """A setting of a node inside a sub-graph becomes a setting of the
        sub-graph's node outside, or stops being one."""
        n = self.graph.nodes[nid]
        self.touch(); self.snapshot(); self._sync_pos()
        prom = [x for x in n.get("promote") or [] if x != name]
        if on:
            prom.append(name)
        if prom:
            n["promote"] = prom
        else:
            n.pop("promote", None)
        self.save()                                  # the sub node outside reads it from the file
        self.refresh_lib()
        self.rebuild()
        self.status(f"{name}: {'a setting of the sub-graph node now' if on else 'kept inside'}")

    def _expose(self, nid, name, on):
        """A param becomes an input pin (its value the pin's default), or
        goes back to being a setting - any wire into it dropped."""
        n = self.graph.nodes[nid]
        self.touch(); self.snapshot(); self._sync_pos()
        exp = [x for x in n.get("expose") or [] if x != name]
        if on:
            exp.append(name)
        else:
            self.graph.unlink(nid, name)
        if exp:
            n["expose"] = exp
        else:
            n.pop("expose", None)
        self.rebuild()
        self.status(f"{name}: {'a pin now' if on else 'a setting again'}")

    def _node_colour_rows(self, P, nid):
        dpg.add_text("node colour", parent=P, color=DIM)
        for chunk in (WIRE_COLOURS[:5], WIRE_COLOURS[5:]):
            with dpg.group(parent=P, horizontal=True):
                for label, col in chunk:
                    if col is None:
                        dpg.add_button(label="auto", small=True,
                                       callback=lambda: (self._hide_menus(), self._set_colour(nid, None)))
                    else:
                        dpg.add_color_button(default_value=list(col) + [255], width=18, height=18, no_border=True,
                                             user_data=col, callback=lambda s, a, u: (self._hide_menus(), self._set_colour(nid, u)))

    def _set_colour(self, nid, col):
        self.snapshot(); self._sync_pos()
        if col is None:
            self.graph.nodes[nid].pop("color", None)
        else:
            self.graph.nodes[nid]["color"] = list(col)
        self.rebuild()

    def _collapse(self, nid):
        self.snapshot(); self._sync_pos()
        n = self.graph.nodes[nid]
        n["collapsed"] = not n.get("collapsed")
        self.rebuild()

    def _between(self, at, bt):
        """Node types that can sit on a wire of type at -> bt: an input that
        takes `at`, an output that gives `bt`."""
        prefer = ["Knot", "Knot colour", "Scale", "Multiply", "Add", "Remap", "Smoothstep", "Clamp", "Abs", "Fade",
                  "Blend", "Mask", "Mix", "Select", "Threshold", "Expression", "Colour expression"]
        out = []
        for name in prefer + sorted(self.lib):
            d = self.lib.get(name)
            if not d or name in out or d.get("decor"):
                continue
            if any(compatible(at, i["type"]) for i in d["inputs"]) and any(compatible(o["type"], bt) for o in d["outputs"]):
                out.append(name)
        return out

    def _insert_before(self, nid, name, new_type):
        """Splice a node into the wire feeding this input."""
        self.snapshot(); self._sync_pos()
        a, out = next((l[0], l[1]) for l in self.graph.links if l[2] == nid and l[3] == name)
        d = self.lib[new_type]
        bt = next(i["type"] for i in self.graph.node_def(self.graph.nodes[nid])["inputs"] if i["name"] == name)
        at = next(o["type"] for o in self.graph.node_def(self.graph.nodes[a])["outputs"] if o["name"] == out)
        inp = next(i["name"] for i in d["inputs"] if compatible(at, i["type"]))
        outp = next(o["name"] for o in d["outputs"] if compatible(o["type"], bt))
        pa, pb = self.graph.nodes[a]["pos"], self.graph.nodes[nid]["pos"]
        new = self.graph.add(new_type, ((pa[0] + pb[0]) / 2, (pa[1] + pb[1]) / 2 + 20))
        self.graph.link(a, out, new, inp)
        self.graph.link(new, outp, nid, name)
        self.rebuild()

    def _colour_rows(self, P, keys):
        dpg.add_text("wire colour", parent=P, color=DIM)
        # two rows of five, so the swatches never run past the menu's edge
        for chunk in (WIRE_COLOURS[:5], WIRE_COLOURS[5:]):
            with dpg.group(parent=P, horizontal=True):
                for label, col in chunk:
                    if col is None:
                        dpg.add_button(label="auto", small=True,
                                       user_data=keys, callback=lambda s, a, u: (self._hide_menus(), self._set_wire(u, None)))
                    else:
                        dpg.add_color_button(default_value=list(col) + [255], width=18, height=18, no_border=True,
                                             user_data=(keys, col), callback=lambda s, a, u: (self._hide_menus(), self._set_wire(*u)))

    def _set_wire(self, keys, col):
        self.snapshot()
        for k in keys:
            if col is None:
                self.graph.link_meta.pop(k, None)
            else:
                self.graph.link_meta[k] = {"color": list(col)}
        self.rebuild()

    def _disconnect_in(self, nid, name):
        self.snapshot(); self.graph.unlink(nid, name); self.rebuild()

    def _disconnect_out(self, nid, name):
        self.snapshot(); self.graph.unlink_out(nid, name); self.rebuild()

    def _disconnect_node(self, nid):
        self.snapshot()
        for l in [l for l in self.graph.links if l[0] == nid or l[2] == nid]:
            self.graph.unlink(l[2], l[3])
        self.rebuild()

    def _reset_input(self, nid, name, i):
        self.snapshot()
        self.graph.nodes[nid].setdefault("inputs", {}).pop(name, None)
        self.rebuild()

    # --- snapshots: the whole graph's settings as named states, and a morph between two ----
    def snapshot_save(self, name):
        name = (name or "").strip()
        if not self.graph or not name:
            self.status("a name is needed for the snapshot"); return
        self._sync_pos()
        self.graph.take_snapshot(name)
        self.save()
        self.refresh_snapshots()
        self.status(f"snapshot {name!r}: {len(self.graph.nodes)} node(s) kept")

    def snapshot_apply(self, name, other=None, t=0.0, live=True):
        """A snapshot (or the morph between two) onto the graph: typed
        values poked into the running effect where they can be, the fields
        set, and a rebuild only when a setting changed."""
        if not self.graph or name not in self.graph.snapshots:
            return
        before = {nid: json.dumps(n.get("params") or {}, sort_keys=True) for nid, n in self.graph.nodes.items()}
        if t == 0.0 or other is None:
            self.snapshot(("snapshot", name))
        touched = self.graph.apply_snapshot(name, other, t)
        params_changed = any(json.dumps(self.graph.nodes[nid].get("params") or {}, sort_keys=True) != before[nid] for nid in touched)
        all_live = True
        for nid in touched:
            n = self.graph.nodes[nid]
            for k, v in (n.get("inputs") or {}).items():
                w = f"gin_{nid}_{k}_w"
                if dpg.does_item_exist(w):
                    try:
                        dpg.set_value(w, v if not isinstance(v, (list, tuple)) or len(v) != 3 else list(v) + [0.0])
                    except Exception:
                        pass
                if live and not isinstance(v, (list, tuple)) or (isinstance(v, (list, tuple)) and len(v) == 3):
                    all_live = self.live_poke(nid, k, v) and all_live
        for btn in list(self._pads):
            self._pad_draw(btn)
        if params_changed or not all_live:
            self._sync_pos(); self.rebuild()
        else:
            self.touch(); self._dirty = 0.0
        self.status(f"snapshot {name!r}" + (f" -> {other!r} at {t:.2f}" if other else "") + (" (settings changed: rebuilt)" if params_changed else ""))

    def snapshot_delete(self, name):
        if self.graph and name in self.graph.snapshots:
            self.graph.snapshots.pop(name); self.save(); self.refresh_snapshots()
            self.status(f"snapshot {name!r} removed")

    def refresh_snapshots(self):
        if not dpg.does_item_exist("snap_rows"):
            return
        dpg.delete_item("snap_rows", children_only=True)
        names = sorted(self.graph.snapshots) if self.graph else []
        for nm in names:
            with dpg.group(horizontal=True, parent="snap_rows"):
                dpg.add_button(label=nm, small=True, user_data=nm, callback=lambda s_, a_, u: self.snapshot_apply(u))
                dpg.add_button(label="update", small=True, user_data=nm, callback=lambda s_, a_, u: self.snapshot_save(u))
                dpg.add_button(label="x", small=True, user_data=nm, callback=lambda s_, a_, u: self.snapshot_delete(u))
        if not names:
            dpg.add_text("none yet: type a name and Save", parent="snap_rows", color=DIM)
        for tag in ("snap_a", "snap_b"):
            if dpg.does_item_exist(tag):
                dpg.configure_item(tag, items=names)
                if dpg.get_value(tag) not in names:
                    dpg.set_value(tag, names[0] if names else "")

    def snapshot_morph(self, t):
        a, b = dpg.get_value("snap_a"), dpg.get_value("snap_b")
        if not self.graph or a not in self.graph.snapshots or b not in self.graph.snapshots:
            return
        self.snapshot_apply(a, b, float(t))

    # a source, its output, and its own settings: what "modulate with" offers
    MODULATORS = [("the time (a slow ramp)", ("Time", "t", {})),
                  ("an LFO - a sine of the time", ("lfo", "value", {})),
                  ("the volume", ("Audio", "volume", {})), ("the bass", ("Audio", "bass", {})),
                  ("the mid", ("Audio", "mid", {})), ("the treble", ("Audio", "treble", {})),
                  ("the beat's hit", ("Audio", "hit", {})), ("a random hold on the beat", ("hold", "value", {})),
                  ("the beat's phase (a Tempo)", ("tempo", "phase", {})), ("the bar's phase (a Tempo)", ("tempo", "bar", {}))]

    def modulate(self, nid, name, src):
        """Bitwig's gesture: a modulator onto a value. The typed value stays
        the centre - a Remap, folded so it is one small node, takes the
        source's 0..1 to value - amount .. value + amount (a quarter of the
        value, or 0.25 about zero) and feeds the pin; the source is one
        already in the graph, or a new one to the left. An LFO is a Wave
        of the time; a random hold is one triggered by the beat."""
        if nid not in self.graph.nodes:
            return
        n = self.graph.nodes[nid]
        d = self.graph.node_def(n)
        i = next((q for q in d["inputs"] if q["name"] == name), None)
        if i is None:
            return
        self.snapshot("modulate")
        v = float(n.get("inputs", {}).get(name, i.get("default", 0.0)) or 0.0)
        amount = abs(v) * 0.25 if abs(v) > 1e-6 else 0.25
        px, py = n["pos"]
        kind, out, _ = src
        if kind == "lfo":                                    # a Wave of the time, in frame scope: the LFO
            t = self._find_or_add("Time", (px - 660, py))
            w = self.graph.add("Wave", (px - 440, py)); self.graph.nodes[w]["params"]["shape"] = "sine"
            self.graph.nodes[w]["inputs"]["cycles"] = 0.25   # a cycle every four seconds
            self.graph.link(t, "t", w, "x")
            source, sout = w, "value"
        elif kind == "hold":
            a = self._find_or_add("Audio", (px - 660, py))
            h = self.graph.add("Random hold", (px - 440, py))
            self.graph.link(a, "beat", h, "trigger")
            source, sout = h, "value"
        elif kind == "tempo":                                # musical time: a Tempo fed by the beat
            a = self._find_or_add("Audio", (px - 660, py))
            tp = next((m["id"] for m in self.graph.nodes.values() if m["type"] == "Tempo"), None)
            if tp is None:
                tp = self.graph.add("Tempo", (px - 440, py)); self.graph.link(a, "beat", tp, "beat")
            source, sout = tp, out
        else:
            source, sout = self._find_or_add(kind, (px - 440, py)), out
        r = self.graph.add("Remap", (px - 220, py))
        self.graph.nodes[r]["params"].update({"in_lo": 0.0, "in_hi": 1.0, "out_lo": round(v - amount, 4), "out_hi": round(v + amount, 4)})
        self.graph.nodes[r]["collapsed"] = True
        self.graph.nodes[r]["label"] = f"{name} \u00b1{amount:.3g}"
        self.graph.nodes[r]["modulator"] = True             # the fed pin draws this Remap's range as its own
        self.graph.link(source, sout, r, "x")
        self.graph.link(r, "result", nid, name)
        self.rebuild()
        self.status(f"{name} modulated by {self.graph.nodes[source]['type']}: {v - amount:.3g} .. {v + amount:.3g} (the Remap's out_lo / out_hi set the range)")

    def _find_or_add(self, type_, pos):
        existing = next((m["id"] for m in self.graph.nodes.values() if m["type"] == type_), None)
        return existing if existing is not None else self.graph.add(type_, (max(0, pos[0]), pos[1]))

    def _drive_with(self, nid, name, ctrl):
        """A control node feeding this input - reuse one already in the graph,
        else add one just to the left."""
        self.snapshot()
        existing = next((m["id"] for m in self.graph.nodes.values() if m["type"] == ctrl), None)
        if existing is None:
            pos = self.graph.nodes[nid]["pos"]
            existing = self.graph.add(ctrl, (max(0, pos[0] - 220), pos[1]))
        out = self.lib[ctrl]["outputs"][0]["name"]
        self.graph.link(existing, out, nid, name)
        self.rebuild()

    def _producers(self, t, limit=14):
        """Node types with an output that can feed a pin of type t, most useful first."""
        prefer = ["Noise", "Wave", "Coords", "Direction", "Position", "Time", "Audio", "Speed", "Intensity", "Palette",
                  "HSV", "Colour ramp", "Number", "Colour", "Integrate", "Hash", "Voronoi", "Gradient"]
        out = []
        for name in prefer + sorted(self.lib):
            d = self.lib.get(name)
            if not d or name in out or not d["outputs"] or d.get("decor"):
                continue
            if any(compatible(o["type"], t) for o in d["outputs"]):
                out.append(name)
        return out[:limit]

    def _consumers(self, t, limit=14):
        """Node types with a first input this output can feed, most useful first."""
        prefer = ["Palette", "Blend", "Mask", "Scale", "HSV", "Add", "Multiply", "Mix", "Remap",
                  "Smoothstep", "Wave", "Noise", "Select", "Threshold", "Output", "Split", "Fade"]
        out = []
        for name in prefer + sorted(self.lib):
            d = self.lib.get(name)
            if not d or name in out or not d["inputs"]:
                continue
            if any(compatible(t, i["type"]) for i in d["inputs"]):
                out.append(name)
        return out[:limit]

    def _connect_new(self, nid, out_name, t, new_type):
        self.snapshot()
        d = self.lib[new_type]
        inp = next(i["name"] for i in d["inputs"] if compatible(t, i["type"]))
        pos = self.graph.nodes[nid]["pos"]
        new = self.graph.add(new_type, (pos[0] + 230, pos[1]))
        self.graph.link(nid, out_name, new, inp)
        self.rebuild()

    def _dup(self, nid, with_links=False):
        self.snapshot(); self._sync_pos(); self.graph.duplicate(nid, with_links=with_links); self.rebuild()

    def change_type(self, nid, new_type):
        """The node as another type, its wires kept where they fit."""
        if nid not in self.graph.nodes or new_type not in self.lib:
            return
        self.snapshot("change type"); self._sync_pos()
        was = self.graph.nodes[nid]["type"]
        dropped = self.graph.retype(nid, new_type)
        self._note_recent(new_type)
        self.rebuild()
        self.status(f"#{nid}: {was} is now {new_type}" + (f" - {dropped} wire(s) had no pin to go to" if dropped else ""))

    def pick_type_for(self, nid):
        """The add menu, but the pick replaces this node."""
        if nid not in self.graph.nodes:
            return
        pos = self.graph.nodes[nid]["pos"]
        self._menu_pos = pos
        self._pending = ("replace", nid)
        try:
            at = dpg.get_mouse_pos(local=False)
        except Exception:
            at = (200, 200)
        self.show_add_menu(at)

    def merge_selected(self, op="Add"):
        """The selected nodes' first outputs through Add / Subtract / ...
        / Blend nodes, left to right; the result selected."""
        sel = [nid for nid in self._selected() if nid in self.graph.nodes]
        sel.sort(key=lambda i: self.graph.nodes[i]["pos"][0])
        if len(sel) < 2:
            self.status("select two nodes or more to merge"); return
        self.snapshot("merge"); self._sync_pos()
        try:
            made = self.graph.merge(sel, op)
        except G.GraphError as e:
            self._undo.pop(); self._undo_desc.pop()
            self.status(f"merge: {e}"); return
        self.rebuild()
        self.set_selection(made[-1:])
        self.status(f"{len(sel)} nodes merged through {op}" + (f" ({len(made)} of them)" if len(made) > 1 else ""))

    def unfold_sub(self, nid):
        """The sub-graph node replaced by its contents, in place."""
        n = self.graph.nodes.get(nid)
        if not n or not n["type"].startswith(G.SUB):
            return
        self.snapshot("unfold"); self._sync_pos()
        try:
            new = self.graph.unfold(nid)
        except G.GraphError as e:
            self._undo.pop(); self._undo_desc.pop()
            self.status(f"unfold: {e}"); return
        self.rebuild()
        self.set_selection(new)
        self.status(f"{n['type'][len(G.SUB):]} unfolded: {len(new)} node(s) in its place")

    def reset_node(self, nid):
        """Every setting and every typed input value back to the library's
        defaults; the wires, the label and the exposed pins stay."""
        n = self.graph.nodes.get(nid)
        if n is None:
            return
        self.snapshot("reset node"); self._sync_pos()
        try:
            d = self.graph.node_def(n)
        except G.GraphError:
            return
        n["params"] = {p["name"]: (list(p["default"]) if isinstance(p["default"], (list, tuple)) else p["default"])
                       for p in d.get("params", []) if "default" in p}
        n["inputs"] = {}
        self.rebuild()
        self.status(f"{d['name']} #{nid}: settings back to their defaults")

    def _toggle(self, nid, flag):
        self.snapshot(); self._sync_pos()
        n = self.graph.nodes[nid]
        n[flag] = not n.get(flag)
        if not n[flag]:
            n.pop(flag, None)
        self.rebuild()

    def toggle_selected(self, flag):
        sel = self._selected()
        if not sel:
            self.status("select nodes first"); return
        self.snapshot(); self._sync_pos()
        on = not all(self.graph.nodes[i].get(flag) for i in sel)
        for i in sel:
            if on:
                self.graph.nodes[i][flag] = True
            else:
                self.graph.nodes[i].pop(flag, None)
        self.rebuild()

    def arrange(self):
        """Arrange the selection when there is one of two or more nodes, the
        whole graph otherwise."""
        if not self.graph:
            return
        sel = self._selected()
        self.snapshot(); self._sync_pos()
        if len(sel) >= 2:
            self.graph.arrange(only=sel)
            self.rebuild()
            self.status(f"arranged {len(sel)} nodes")
            return
        self.offset = [0.0, 0.0]
        self.graph.arrange()
        self.rebuild()
        self.status("arranged")

    def align(self, how):
        """The selected nodes on one edge or one centre line: left, right,
        top, bottom, centre_x, centre_y."""
        sel = self._selected()
        if len(sel) < 2:
            self.status("select two or more nodes to align"); return
        self.snapshot(); self._sync_pos()
        boxes = {}
        for nid in sel:
            n = self.graph.nodes[nid]
            w, h = self._node_size(nid)
            boxes[nid] = (n["pos"][0], n["pos"][1], n["pos"][0] + w, n["pos"][1] + h)
        x0 = min(b[0] for b in boxes.values()); x1 = max(b[2] for b in boxes.values())
        y0 = min(b[1] for b in boxes.values()); y1 = max(b[3] for b in boxes.values())
        for nid, (bx0, by0, bx1, by1) in boxes.items():
            n = self.graph.nodes[nid]
            w, h = bx1 - bx0, by1 - by0
            if how == "left":       n["pos"][0] = x0
            elif how == "right":    n["pos"][0] = x1 - w
            elif how == "top":      n["pos"][1] = y0
            elif how == "bottom":   n["pos"][1] = y1 - h
            elif how == "centre_x": n["pos"][0] = (x0 + x1) / 2 - w / 2
            elif how == "centre_y": n["pos"][1] = (y0 + y1) / 2 - h / 2
        self.rebuild()
        self.status(f"aligned {len(sel)} nodes: {how.replace('_', ' ')}")

    def distribute(self, axis):
        """The selected nodes spread evenly between the first and the last
        along x or y, by their gaps."""
        sel = self._selected()
        if len(sel) < 3:
            self.status("select three or more nodes to distribute"); return
        self.snapshot(); self._sync_pos()
        k = 0 if axis == "x" else 1
        sizes = {nid: self._node_size(nid)[k] for nid in sel}
        order = sorted(sel, key=lambda i: self.graph.nodes[i]["pos"][k])
        first, last = self.graph.nodes[order[0]], self.graph.nodes[order[-1]]
        span = (last["pos"][k] + sizes[order[-1]]) - first["pos"][k]
        total = sum(sizes[i] for i in order)
        gap = (span - total) / (len(order) - 1)
        x = first["pos"][k]
        for nid in order:
            self.graph.nodes[nid]["pos"][k] = x
            x += sizes[nid] + gap
        self.rebuild()
        self.status(f"distributed {len(sel)} nodes along {axis}")

    def _node_size(self, nid):
        """A node's size in graph units, from the widget when it is on screen."""
        tag = f"gnode_{nid}"
        if dpg.does_item_exist(tag):
            st = dpg.get_item_state(tag)
            if "rect_size" in st and st["rect_size"][0] > 0:
                return (st["rect_size"][0] / self.zoom, st["rect_size"][1] / self.zoom)
        return (NODE_W, 120)

    def detach(self, nid):
        """Alt-click: a node loses every wire, in and out, and stays put."""
        self.snapshot(); self._disconnect_node(nid)

    def connect_selected(self):
        """F: the first selected node's first output feeds the second's first
        unwired input of a type that fits."""
        sel = self._selected()
        if len(sel) < 2:
            self.status("select two nodes: the source first, then the target"); return
        a, b = sel[0], sel[1]
        da, db = self.graph.node_def(self.graph.nodes[a]), self.graph.node_def(self.graph.nodes[b])
        wired = {(x, i) for _, _, x, i in self.graph.links}
        for o in da["outputs"]:
            for i in db["inputs"]:
                if (b, i["name"]) not in wired and compatible(o["type"], i["type"]):
                    self.snapshot(); self.graph.link(a, o["name"], b, i["name"]); self.rebuild()
                    self.status(f"{da.get('label') or da['name']} . {o['name']} -> {i['name']}"); return
        self.status("no free input fits")

    def disconnect_selected(self):
        """Every wire in and out of the selected nodes; the nodes stay."""
        sel = self._selected()
        if not sel:
            self.status("select nodes first"); return
        self.snapshot()
        for nid in sel:
            for l in [l for l in self.graph.links if l[0] == nid or l[2] == nid]:
                self.graph.unlink(l[2], l[3])
        self.rebuild()
        self.status(f"{len(sel)} node(s) disconnected")

    def _delete_node(self, nid):
        self.snapshot(); self.graph.remove(nid); self.rebuild()

    def fill_add_menu(self):
        """The right-click add menu, rebuilt whenever the library changes so
        new sub-graphs appear in it."""
        if not dpg.does_item_exist("graph_menu"):
            return
        dpg.delete_item("graph_menu", children_only=True)
        cats = {}
        for name in self.type_names():
            c, n = name.split(" / ", 1)
            cats.setdefault(c, []).append(n)
        with dpg.group(horizontal=True, parent="graph_menu"):
            dpg.add_button(label="undo", small=True, callback=lambda: (self._hide_menus(), self.undo()))
            dpg.add_button(label="redo", small=True, callback=lambda: (self._hide_menus(), self.redo()))
            dpg.add_button(label="paste here", small=True,
                           callback=lambda: (self._hide_menus(), self.paste(self._menu_pos)))
            dpg.add_button(label="arrange", small=True, callback=lambda: (self._hide_menus(), self.arrange()))
        dpg.add_input_text(tag="graph_search", parent="graph_menu", hint="search nodes", width=200,
                           callback=self._search, on_enter=False)
        # on_enter would stop the per-keystroke callback; Enter is read separately
        dpg.add_text("add node", parent="graph_menu", color=DIM)
        # child windows rather than groups: a collapsing header stretches to
        # its parent, and an autosized popup would stretch with it
        dpg.add_child_window(tag="graph_hits", parent="graph_menu", show=False, width=230, height=60,
                             border=False)
        with dpg.child_window(tag="graph_cats", parent="graph_menu", width=230, height=430, border=False):
            # the last few added and the starred ones sit on top; refilled each open
            dpg.add_group(tag="graph_quick")
            self._fill_quick()
            pre = self.presets()
            if pre:
                with dpg.collapsing_header(label="presets", default_open=True):
                    for name in sorted(pre):
                        with dpg.group(horizontal=True):
                            dpg.add_selectable(label=name, user_data="preset:" + name, width=180,
                                               callback=lambda s, a, u: self.add_node_at_menu(u))
                            dpg.add_button(label="x", small=True, user_data=name,
                                           callback=lambda s, a, u: self.delete_preset(u))
            hidden = 0
            for c, names in cats.items():
                with dpg.collapsing_header(label=c, default_open=(c in ("generate", "colour", "subgraphs"))) as hdr:
                    if self.app.prefs.get("cat_colours", True):
                        dpg.bind_item_theme(hdr, self._cat_header_theme(c))
                    for n in names:
                        if self._feature_off(n):
                            hidden += 1
                            continue
                        lbl = self.lib[n].get("label", n) if n in self.lib else n
                        dpg.add_selectable(label=lbl, user_data=n,
                                           callback=lambda s, a, u: self.add_node_at_menu(u))
            if hidden:
                dpg.add_text(f"{hidden} node(s) hidden: their feature is off in Flash > Features", color=DIM, wrap=220)
        self._widgets.add("graph_search")

    # --- a node hovered in the add menu is described in the properties pane ---------------
    def _menu_entries(self):
        """Every selectable in the add menu, with the type it adds."""
        out = []
        def walk(item):
            for k in dpg.get_item_children(item, 1) or []:
                if not dpg.does_item_exist(k):
                    continue
                if dpg.get_item_type(k).endswith("::mvSelectable") and dpg.get_item_user_data(k):
                    out.append(k)
                else:
                    walk(k)
        for root in ("graph_hits", "graph_cats"):
            if dpg.does_item_exist(root):
                walk(root)
        return out

    def _poll_add_preview(self):
        """While the add menu is up, the node under the pointer is described
        in the properties pane; the menu gone, the pane goes back to the
        selection."""
        if not dpg.does_item_exist("graph_menu") or not dpg.is_item_shown("graph_menu"):
            if self._add_preview is not None:
                self._add_preview = None
                self._menu_entries_cache = None
                self._props_for = "unset"                 # the pane back to the selection
            return
        if self._menu_entries_cache is None:
            self._menu_entries_cache = self._menu_entries()
        hovered = None
        for k in self._menu_entries_cache:
            if dpg.does_item_exist(k) and dpg.is_item_hovered(k):
                hovered = dpg.get_item_user_data(k); break
        if hovered is None or hovered == self._add_preview:
            return
        self._add_preview = hovered
        self.describe_type(hovered)

    def describe_type(self, type_):
        """A node type in the properties pane: what it is, its pins and
        settings, each with its words."""
        if not dpg.does_item_exist("graph_props"):
            return
        dpg.delete_item("graph_props", children_only=True)
        self._props_for = ("preview", type_)
        if type_.startswith("preset:"):
            dpg.add_text(f"preset: {type_[7:]}", parent="graph_props")
            dpg.add_text("a node saved with its settings, from a node's menu", parent="graph_props", color=DIM, wrap=0)
            return
        d = self.lib.get(type_)
        if not d:
            return
        dpg.add_text(d.get("label") or type_, parent="graph_props")
        dpg.add_text(f"{d.get('cat', '')} - runs per {d.get('scope', 'pixel')}", parent="graph_props", color=DIM)
        if d.get("doc"):
            dpg.add_text(d["doc"], parent="graph_props", wrap=0)
        for title, items in (("inputs", d.get("inputs", [])), ("outputs", d.get("outputs", [])), ("settings", d.get("params", []))):
            if not items:
                continue
            dpg.add_text(title, parent="graph_props", color=DIM)
            for p in items:
                line = f"  {p['name']} ({p.get('type', '')})"
                if p.get("doc"):
                    line += f": {p['doc']}"
                dpg.add_text(line, parent="graph_props", wrap=0)

    def _fill_quick(self):
        """Favourites (starred in a node's menu) and the recently added, at
        the top of the add menu."""
        if not dpg.does_item_exist("graph_quick"):
            return
        dpg.delete_item("graph_quick", children_only=True)
        self._menu_entries_cache = None
        favs = [n for n in self.app.prefs.get("fav_nodes", []) if n in self.lib]
        rec = [n for n in self.app.prefs.get("recent_nodes", []) if n in self.lib and n not in favs]
        for title, names in (("favourites", favs), ("recent", rec)):
            if not names:
                continue
            with dpg.collapsing_header(label=title, default_open=True, parent="graph_quick"):
                for n in names:
                    dpg.add_selectable(label=self.lib[n].get("label", n), user_data=n,
                                       callback=lambda s, a, u: self.add_node_at_menu(u))

    def _note_recent(self, type_):
        if type_ not in self.lib or self.lib[type_].get("decor"):
            return
        rec = [n for n in self.app.prefs.get("recent_nodes", []) if n != type_]
        self.app.prefs["recent_nodes"] = ([type_] + rec)[:6]
        from native.project import save_prefs
        save_prefs(self.app.prefs)

    def toggle_favourite(self, type_):
        favs = list(self.app.prefs.get("fav_nodes", []))
        if type_ in favs:
            favs.remove(type_); self.status(f"{type_}: no longer a favourite")
        else:
            favs.append(type_); self.status(f"{type_}: a favourite, at the top of the add menu")
        self.app.prefs["fav_nodes"] = favs
        from native.project import save_prefs
        save_prefs(self.app.prefs)

    def _hide_menus(self):
        for t in ("graph_menu", "graph_ctx"):
            if dpg.does_item_exist(t):
                dpg.configure_item(t, show=False)

    def add_node_at_menu(self, type_):
        self.touch()
        dpg.configure_item("graph_menu", show=False)
        if not self.graph:
            return
        if self._pending and self._pending[0] == "replace":     # change a node's type: the pick replaces it
            _, old = self._pending
            self._pending = None
            if type_ in self.lib and old in self.graph.nodes:
                self.change_type(old, type_)
            return
        if type_.startswith("preset:"):
            nid = self.add_preset(type_[7:], self._menu_pos)
            if nid is None:
                return
            type_ = self.graph.nodes[nid]["type"]
        elif type_ not in self.lib:
            return
        else:
            self.snapshot()
            nid = self.graph.add(type_, self._menu_pos)
            self._make_node(nid, self.graph.nodes[nid])
            self._note_recent(type_)
        if type_ == "Frame":
            self._sync_pos(); self.rebuild()      # behind the nodes it now covers
        if self._pending and self._pending[0] == "into":
            _, b, inp, t = self._pending
            self._pending = None
            d = self.graph.node_def(self.graph.nodes[nid])
            out = next((o["name"] for o in d["outputs"] if compatible(o["type"], t)), None)
            if out and b in self.graph.nodes:
                self.graph.link(nid, out, b, inp)
                self.rebuild()
        elif self._pending:
            a, out, t = self._pending
            self._pending = None
            d = self.graph.node_def(self.graph.nodes[nid])
            inp = next((i["name"] for i in d["inputs"] if compatible(t, i["type"])), None)
            if inp and a in self.graph.nodes:
                self.graph.link(a, out, nid, inp)
                self.rebuild()

    def add_node(self, type_):
        self.touch()
        if not self.graph or type_ not in self.lib:
            return
        self.snapshot()
        self._add_count += 1
        pos = (60 + 30 * (self._add_count % 8), 60 + 30 * (self._add_count % 8))
        nid = self.graph.add(type_, pos)
        self._make_node(nid, self.graph.nodes[nid])
        return nid

    def delete_selected(self):
        if not self.graph or not dpg.get_selected_nodes("node_editor"):
            return
        self.snapshot()
        for tag in dpg.get_selected_nodes("node_editor"):
            nid = dpg.get_item_user_data(tag)
            self.graph.remove(nid)
            for lid, (b, inp) in list(self.links.items()):
                if b == nid or not dpg.does_item_exist(lid):
                    self.links.pop(lid, None)
            dpg.delete_item(tag)
        # links from the removed node's outputs are gone with the node in DPG;
        # rebuild the link map from the editor's truth
        alive = set(dpg.get_item_children("node_editor", 0) or [])
        for lid in list(self.links):
            if lid not in alive:
                self.links.pop(lid, None)

    # --- compile -------------------------------------------------------------------------
    # --- sharing a graph -----------------------------------------------------------------
    # One JSON with the graph and every sub-graph it reaches (and user nodes
    # it uses), so a graph can be handed to someone else's project.
    def export_bundle(self, with_deps=None):
        """The graph, its sub-graphs and user nodes as one file. A graph
        leaning on a feature that is not every WLED tree's (the IMU driver)
        asks whether to carry that firmware in the bundle too; `with_deps`
        answers without asking (a test, or the box's button)."""
        if not self.graph:
            return
        from native import flash, chrome
        req = flash.requirements_of_graph(self.graph, self.lib, self.resolve_sub)
        ours = sorted(k for k in req if k in flash.DEPENDENCIES and not flash.DEPENDENCIES[k]["standard"])
        if ours and with_deps is None:
            what = ", ".join(flash.DEPENDENCIES[k]["label"] for k in ours)
            chrome.confirm(self.app, "Export graph bundle",
                           f"This graph uses nodes that need {what} - firmware that is not part of every WLED tree. "
                           "Include those usermod files in the bundle, so whoever opens it can build?",
                           [("Include them", lambda: self.export_bundle(True)),
                            ("Just the graph", lambda: self.export_bundle(False)), ("Cancel", None)])
            return
        self.save()
        subs = {}
        def collect(g):
            for n in g.nodes.values():
                if n["type"].startswith(G.SUB):
                    ident = n["type"][len(G.SUB):]
                    if ident not in subs:
                        sub = self.resolve_sub(ident)
                        if sub is not None:
                            subs[ident] = sub.to_json()
                            collect(sub)
        collect(self.graph)
        user = {}
        udir = os.path.join(self.app.project.path, "nodes")
        for g in [self.graph] + [G.Graph(d, lib=self.lib) for d in subs.values()]:
            for n in g.nodes.values():
                p = os.path.join(udir, G._ident(n["type"]) + ".json")
                if os.path.exists(p) and n["type"] not in user:
                    user[n["type"]] = json.load(open(p, encoding="utf-8"))
        bundle = {"studio_graph": 1, "graph": self.graph.to_json(), "subgraphs": subs, "nodes": user,
                  "requires": sorted(req)}
        if with_deps and ours:
            bundle["usermods"] = flash.dependency_files(ours)
        out = os.path.join(self.app.project.path, "export")
        os.makedirs(out, exist_ok=True)
        path = os.path.join(out, os.path.splitext(self.file)[0] + ".graph.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(bundle, f, indent=1)
        self.status(f"exported {os.path.basename(path)} ({len(subs)} sub-graph(s), {len(user)} user node(s)"
                    + (f", {len(bundle.get('usermods', {}))} firmware file(s)" if with_deps and ours else "")
                    + (f"; needs {', '.join(sorted(req))}" if req else "") + ")")
        return path

    def import_bundle(self, path):
        try:
            b = json.load(open(path, encoding="utf-8"))
        except Exception as e:
            self.status(f"cannot read {path}: {e}"); return
        if not isinstance(b, dict) or "graph" not in b:
            # a plain graph file is fine too
            b = {"graph": b, "subgraphs": {}, "nodes": {}} if isinstance(b, dict) and "nodes" in b else None
            if b is None:
                self.status("not a graph file"); return
        udir = os.path.join(self.app.project.path, "nodes")
        for name, d in b.get("nodes", {}).items():
            os.makedirs(udir, exist_ok=True)
            p = os.path.join(udir, G._ident(name) + ".json")
            if not os.path.exists(p):
                json.dump(d, open(p, "w", encoding="utf-8"), indent=1)
        for ident, d in b.get("subgraphs", {}).items():
            p = os.path.join(self.sub_dir, ident + ".json")
            if not os.path.exists(p):
                json.dump(d, open(p, "w", encoding="utf-8"), indent=1)
            # an existing one of the same name is kept: the import uses it
        g = b["graph"]
        name = g.get("name") or os.path.splitext(os.path.basename(path))[0]
        fname = G._ident(name) + ".json"
        n = 2
        while os.path.exists(os.path.join(self.dir, fname)):
            fname = f"{G._ident(name)}_{n}.json"; n += 1
        json.dump(g, open(os.path.join(self.dir, fname), "w", encoding="utf-8"), indent=1)
        self.refresh_lib()
        self.open(fname)
        self.status(f"imported {name} as {fname}")
        self.check_requirements(b)

    def check_requirements(self, bundle):
        """An imported graph's needs against the project's features: what
        the project leaves out is offered - turned on, and the bundled
        firmware files installed where this tree lacks them."""
        from native import flash, chrome
        req = set(bundle.get("requires") or [])
        if self.graph:
            req |= flash.requirements_of_graph(self.graph, self.lib, self.resolve_sub)
        missing = flash.missing_features(self.app.project, req)
        if not missing:
            return
        files = bundle.get("usermods") or {}
        what = ", ".join(flash.DEPENDENCIES.get(k, {}).get("label", k) for k in sorted(missing))
        text = (f"This graph needs {what}, which this project's features leave out (Flash > Features). "
                "Turn the feature on for this project"
                + (f" and install the {len(files)} firmware file(s) the bundle carries, where this tree lacks them" if files else "")
                + "?")

        def enable():
            written = flash.install_dependency_files(files)
            for k in sorted(missing):
                self.app.set_feature(k, "stock" if k == "audio" else True)
            self.status(f"features on: {', '.join(sorted(missing))}" + (f"; installed {', '.join(written)}" if written else ""))
        chrome.confirm(self.app, "This graph needs more than the project has", text,
                       [("Turn on", enable), ("Leave as is", None)])

    # --- pin preview ---------------------------------------------------------------------
    # "Preview this output" builds the graph with that pin shown instead of
    # the Output: a colour straight, a float or bool as a grey level. The
    # effect is a draft named Preview; the graph's own file is untouched,
    # and every compile while the preview is on shows the pin.
    PREVIEW_FILE = "_preview.cpp"

    def preview_pin(self, nid, name):
        self.preview = (nid, name)
        self.status(f"previewing {self.graph.nodes[nid]['type']} . {name}")
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

    def compile(self, and_build=True):
        """Graph -> effects/<graph>.cpp -> the normal build and reload."""
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
            self._probes = dict(getattr(g or self.graph, "probes", {}) or {})
            self._probe_scope = dict(getattr(g or self.graph, "last_scope", {}) or {})
            self._probes_for = fname
            self._live = {v: k for k, v in (getattr(g or self.graph, "live", {}) or {}).items()}   # (nid, input, comp) -> slot
        except G.GraphError as e:
            self.status(f"graph: {e}")
            self._mark_problems()
            return None
        self.app.project.write_effect(fname, src)
        self.status(f"wrote {fname}" + (f" (previewing {self.preview[1]} of #{self.preview[0]})" if self.preview else ""))
        if and_build:
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

    def import_effect(self):
        """The graph's effect joins the list - generated first if it has not
        been - or leaves it."""
        f = self.effect_file()
        if not f:
            return
        if f not in self.app.project.effect_files() and not self.app.project.is_imported(f):
            if self.compile(and_build=False) is None:
                return
        self.app.toggle_import(f)

    def type_names(self):
        cats = {}
        for n, d in self.lib.items():
            cats.setdefault(d["cat"], []).append(n)
        out = []
        for c in ("controls", "signals", "coords", "generate", "maths", "colour", "graph", "subgraphs", "custom", "output"):
            out += [f"{c} / {n}" for n in sorted(cats.pop(c, []))]
        for c, ns in sorted(cats.items()):
            out += [f"{c} / {n}" for n in sorted(ns)]
        return out


def build_panel(app, panel):
    """The graph pane's widgets. Called once from build()."""
    # One row: which graph, and the status line. Everything else is on the
    # menus and the toolbar (chrome.py) or the right-click menu.
    from native.chrome import grip
    grip("graph_win")
    with dpg.group(horizontal=True):
        dpg.add_button(label="< back", tag="graph_back", show=False, callback=lambda: panel.back())
        with dpg.group(horizontal=True, tag="graph_crumbs", show=False):     # inside a sub-graph: the trail down to it
            pass
        dpg.add_combo(panel.files(), tag="graph_file", width=220, default_value=panel.file or "",
                      callback=lambda s, v: panel.open(v))
        dpg.add_text("", tag="graph_status", color=DIM)
    with dpg.file_dialog(directory_selector=False, show=False, tag="graph_import_dialog", width=620, height=420,
                         callback=lambda s, a: panel.import_bundle(a.get("file_path_name", ""))):
        dpg.add_file_extension(".json", color=(120, 200, 120))
        dpg.add_file_extension(".*")
    # The description box: a fixed height, whatever the text - a line that
    # grew and shrank with each hover moved the editor under the pointer.
    # The bar under it drags to resize; the height is remembered.
    with dpg.child_window(tag="graph_help_box", height=int(app.prefs.get("help_h", HELP_H)), border=False,
                          no_scrollbar=True, no_scroll_with_mouse=True):
        dpg.add_text("", tag="graph_help", color=(170, 178, 192), wrap=0)
    dpg.add_button(label="", tag="help_split", width=-1, height=5)
    with dpg.node_editor(tag="node_editor", callback=panel.on_link, delink_callback=panel.on_delink,
                         minimap=True, minimap_location=dpg.mvNodeMiniMap_Location_BottomRight,
                         width=-1, height=-1):
        pass
    # The right-click menu: a small window shown at the pointer, categories as
    # collapsing headers, a node per line. A window rather than a popup so it
    # can be positioned exactly and dismissed by the click that adds.
    # an expression typed into a field: a small box at the pointer (= over a value, or a menu row)
    with dpg.window(tag="expr_win", show=False, no_title_bar=True, no_resize=True, no_move=True, autosize=True, popup=True):
        dpg.add_text("", tag="expr_label", color=DIM)
        dpg.add_input_text(tag="expr_text", width=240, on_enter=True, callback=lambda s, v: app.gp.expr_enter(v))
        dpg.add_text("2*pi, x*2 (x: the value now), sqrt(2), min(a, 4)...", tag="expr_hint", color=DIM, wrap=240)
    with dpg.window(tag="graph_ctx", show=False, no_title_bar=True, no_resize=True, no_move=True,
                    autosize=True, popup=True):
        pass
    with dpg.window(tag="graph_menu", show=False, no_title_bar=True, no_resize=True, no_move=True,
                    autosize=True, popup=True):
        pass
    panel.fill_add_menu()
