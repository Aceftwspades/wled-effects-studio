"""The properties pane - a mixin of graph_ui's GraphPanel: the selected node's settings and unwired inputs as a
form beside the canvas (kept in step with the fields on the node), its metadata rows, and the two editors that open
in it - the Bitmap's pixel painter and the curve editor."""
import dearpygui.dearpygui as dpg

from native.typeface import px
from native import typeface
from native import num
from native import graph as G
from native import nodeface


class GraphProps:
    def _prop_width(self):
        """A field's width in the properties: the pane less a form row's label column."""
        from native import form
        W = int(dpg.get_item_rect_size("graph_props")[0] or 0) or px(360)
        return max(px(120), W - px(form.LABEL_W) - px(form.GAP) - px(14))

    def _prop_section(self, title, nid, n, specs, kind):
        """A list of fields in the properties, one form row each: the
        settings (kind "param") or the typed inputs ("input"), made as the
        node's own are and edited through the same callbacks - so either one
        edited, the other follows (_mirror)."""
        from native.graph_ui import DIM
        from native import form
        P = "graph_props"
        typeface.label(dpg.add_text(title, parent=P, color=self.pal()["dim"]))
        fw = self._prop_width()
        vals = n["params"] if kind == "param" else n.get("inputs", {})
        note = bool(self.graph.node_def(n).get("multiline"))       # a Note: its text over lines, as on the node
        for s in specs:
            words = nodeface.label(n["type"], s["name"])
            v = vals.get(s["name"], s.get("default", 0))
            ud = (nid, s["name"])
            if kind == "param" and s["type"] in ("text", "file") and (s.get("lines") or note or len(str(v)) > 40):
                # a long text: its name, then its box across the pane - a row a line for a setting kept as rows (a
                # Bitmap's) and for a Note, one line for the rest (an expression, a path: a new line means nothing)
                lines = bool(s.get("lines")) or (note and s["type"] == "text")
                dpg.add_text(words, parent=P, color=DIM)
                w = dpg.add_input_text(parent=P, width=-1, multiline=lines, height=px(120) if lines else 0,
                                       default_value=str(v).replace("/", "\n") if s.get("lines") else str(v),
                                       user_data=ud, callback=self._on_param)
                typeface.mono(w)
                self._widgets.add(w)
                continue
            if kind == "param" and s["type"] == "ramp":
                dpg.add_text(words, parent=P, color=DIM)
                with dpg.group(parent=P):
                    self._ramp_widget(nid, n, s, v)
                continue
            with form.row(words, parent=P):
                self._prop_field(nid, n, s, v, ud, kind, fw)

    def _prop_field(self, nid, n, s, v, ud, kind, fw):
        cb = self._on_param if kind == "param" else self._on_input
        t = s["type"]
        if t == "bool":
            w = dpg.add_checkbox(default_value=bool(v), user_data=ud, callback=cb)
        elif kind == "input" and t == "float":
            w = self._number_widget(s, G.as_float(v), None, ud, cb, True, fw, words=self._implicit_words(nid, s["name"]))
        elif kind == "input" and t == "vector" and self._implicit_words(nid, s["name"]):
            w = self._implicit_button(self._implicit_words(nid, s["name"]), None, ud, fw, True)
        elif kind == "input" and t == "vector":
            vv = [float(c) for c in (list(v) + [0, 0, 0])[:3]] if isinstance(v, (list, tuple)) else [float(v)] * 3
            w = dpg.add_input_floatx(width=fw, size=3, default_value=vv + [0.0], format="%.2f", user_data=ud, callback=cb)
        elif kind == "input":
            rgb = list(v)[:3] if isinstance(v, (list, tuple)) else [0, 0, 0]
            w = dpg.add_color_edit([int(c) for c in rgb] + [255], no_label=True, no_alpha=True, no_inputs=True,
                                   user_data=ud, callback=cb)
        else:
            self._param_field(nid, n, s, v, ud, cb, fw)           # a number, a choice, a colour, a text, a file: as on the node
            return
        dpg.bind_item_theme(w, self._field_theme())
        self._value_face(w)
        self._widgets.add(w)

    def _poll_props(self):
        from native.graph_ui import DIM
        if not dpg.does_item_exist("graph_props") or not self.graph:
            return
        sel = self._selected()
        key = (self.file, sel[0]) if sel else None
        if key == getattr(self, "_props_for", "unset"):
            return
        self._props_for = key
        # the pane is always there (its own pane, sized by the layout): what
        # changes is what it says, never the editor beside it
        self._widgets.difference_update(getattr(self, "_props_widgets", set()))
        self._props_widgets = set()
        dpg.delete_item("graph_props", children_only=True)
        num.prune()                                      # the last node's number fields are gone
        if not sel:
            dpg.add_text("select a node: its settings and the values of its free inputs are edited here",
                         parent="graph_props", color=DIM, wrap=0)
            return
        nid = sel[0]
        n = self.graph.nodes.get(nid)
        if not n:
            return
        try:
            d = self.graph.node_def(n)
        except G.GraphError as e:
            # selected, a node whose type is not there: said here - it raised every frame, in the main loop
            typeface.heading(dpg.add_text(f"{n['type']} #{nid}", parent="graph_props"))
            dpg.add_text(f"{e} - put the file back, or delete the node", parent="graph_props", color=DIM, wrap=0)
            return
        title = f"{n.get('label') or d.get('label') or n['type']} #{nid}"
        if n.get("label"):
            title += f"  ({n['type']})"
        typeface.heading(dpg.add_text(title, parent="graph_props"))
        if len(sel) > 1:
            typeface.small(dpg.add_text(f"and {len(sel) - 1} more selected", parent="graph_props", color=DIM))
        curves = [p for p in d["params"] if p["type"] == "curve"]
        meta = [p for p in d["params"] if nodeface.is_meta(n["type"], p["name"])]
        before = set(self._widgets)
        if meta:
            self._meta_rows(nid, n, meta)
        self._curve_ed = None
        self._bitmap_ed = None
        if n["type"] == "Bitmap":
            # the bitmap painted: a grid of cells, the left button sets the pen's digit, the right clears
            self._build_bitmap_editor(nid, "rows")
        for p in curves:
            # a curve drawn by hand: click to add a point, drag one, right-click to take it out
            dpg.add_text(f"{nodeface.label(n['type'], p['name'])} - click to add a point, drag to move, right-click to remove",
                         parent="graph_props", color=DIM, wrap=0)
            W = max(px(200), int(dpg.get_item_rect_size("graph_props")[0] or px(300)) - px(24))
            H = px(180)
            tag = dpg.add_drawlist(width=W, height=H, parent="graph_props")
            self._curve_ed = {"nid": nid, "name": p["name"], "tag": tag, "W": W, "H": H, "drag": None, "was": False, "rwas": False}
            self._curve_draw()
        # every other setting, and the value of every input nothing is wired to - as the node has them
        params, inputs = self.editable(nid)
        drawn = {p["name"] for p in meta + curves} | ({"rows"} if n["type"] == "Bitmap" else set())
        params = [p for p in params if p["name"] not in drawn]
        if params:
            self._prop_section("SETTINGS", nid, n, params, "param")
        if inputs:
            self._prop_section("INPUTS", nid, n, inputs, "input")
        self._props_widgets = set(self._widgets) - before
        if not (params or inputs or meta or curves or n["type"] == "Bitmap"):
            dpg.add_text("nothing to set on this node: its pins take what is wired to them",
                         parent="graph_props", color=DIM, wrap=0)

    def _meta_rows(self, nid, n, meta):
        """A control node's settings that are the effect's, not the graph's
        (nodeface.META): what WLED's page names the slider or the box, and
        where it starts. Edited here; the node's title carries the name."""
        from native import form
        box = n["type"].startswith("Check")
        typeface.label(dpg.add_text("ON THE WLED PAGE", parent="graph_props", color=self.pal()["dim"]))
        for p in meta:
            v = n["params"].get(p["name"], p["default"])
            ud = (nid, p["name"])
            if p["type"] == "bool":
                form.check("ticked at the start", parent="graph_props", default_value=bool(v), user_data=ud,
                           callback=self._on_param)
                continue
            with form.row("named" if p["name"] == "label" else "starts at", parent="graph_props"):
                if p["type"] == "text":
                    dpg.add_input_text(default_value=str(v), width=-1, user_data=ud, callback=self._on_param)
                else:
                    num.add(None, int(v), p.get("min"), p.get("max"), integer=True, width=-1, callback=self._on_param,
                            user_data=ud)
        form.note(f"the {'box' if box else 'slider'} the effect shows on the WLED page: its name, and where it "
                  "starts when the effect is picked", parent="graph_props")

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
        from native.graph_ui import DIM
        n, rows = self._bitmap_rows(nid, name)
        if n is None:
            return
        dpg.add_text(f"{name} - paint: the left button sets the pen's digit (a colour slot for Colour pick), the right "
                     "empties a pixel (a dot); drag to paint a run", parent="graph_props", color=DIM, wrap=0)
        with dpg.group(horizontal=True, parent="graph_props"):
            dpg.add_text("pen", color=DIM)
            dpg.add_combo(list(self.BITMAP_STATES), tag="bitmap_pen", width=px(44), default_value="1",
                          callback=lambda s, v: self._bitmap_ed.__setitem__("pen", v))
            dpg.add_button(label="empty", small=True, callback=lambda: self._bitmap_fill("."))
            dpg.add_button(label="fill", small=True, callback=lambda: self._bitmap_fill(None))
        with dpg.group(horizontal=True, parent="graph_props"):
            dpg.add_text("size", color=DIM)
            for lbl, dc, dr in (("+col", 1, 0), ("-col", -1, 0), ("+row", 0, 1), ("-row", 0, -1)):
                dpg.add_button(label=lbl, small=True, user_data=(dc, dr), callback=lambda s, a, u: self._bitmap_resize(*u))
        W = max(px(200), int(dpg.get_item_rect_size("graph_props")[0] or px(300)) - px(24))
        cols, nrows = len(rows[0]), len(rows)
        cell = max(px(6), min(px(28), W // cols, px(200) // nrows))
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
                    self._draw_text((c * cell + cell * 0.3, r * cell + cell * 0.12), ch, size=max(8, cell - 6), color=(20, 22, 26, 255), parent=tag)

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
        # A stroke starts only with a press on the grid itself: a box selection
        # or a node dragged on the canvas, passing under the properties, painted
        # the cells it crossed; so did a click on a menu lying over the grid.
        if dpg.is_mouse_button_clicked(0) or dpg.is_mouse_button_clicked(1):
            ed["armed"] = inside and dpg.is_item_hovered(ed["tag"])
        if (down or rdown) and inside and ed.get("armed"):
            ch = "." if rdown else ed["pen"]
            if ed["stroke"] is None:                     # the first cell of a stroke: one undo step for the whole stroke
                self.touch(); self.snapshot("paint bitmap")
                ed["stroke"] = set()
            if (r, c) not in ed["stroke"] and rows[r][c] != ch:
                rows[r] = rows[r][:c] + ch + rows[r][c + 1:]
                self._bitmap_set(rows, None)
                ed["stroke"].add((r, c))
                self._bitmap_draw()
        elif not down and not rdown:
            ed["armed"] = False
            if ed["stroke"] is not None:                 # the stroke ends: the node and the code follow
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
        P = self.pal()
        dpg.draw_rectangle((0, 0), (W - 1, H - 1), color=P["plot_edge"], fill=P["plot_bg"], parent=tag)
        for k in range(1, 4):
            dpg.draw_line((k * W / 4, 0), (k * W / 4, H - 1), color=P["grid"], parent=tag)
            dpg.draw_line((0, k * H / 4), (W - 1, k * H / 4), color=P["grid"], parent=tag)
        prev = None
        for x in range(0, W, 2):
            t = x / max(1, W - 1)
            y = (1.0 - max(0.0, min(1.0, self._curve_at(pts, t)))) * (H - 1)
            if prev is not None:
                dpg.draw_line(prev, (x, y), color=P["live"], thickness=2, parent=tag)
            prev = (x, y)
        for k, q in enumerate(pts):
            c = (255, 180, 60, 255) if k == ed.get("drag") else P["point"]
            dpg.draw_circle((q[0] * (W - 1), (1.0 - q[1]) * (H - 1)), 5, color=c, fill=c, parent=tag)
            self._draw_text((min(W - 60, q[0] * (W - 1) + 8), max(2, (1.0 - q[1]) * (H - 1) - 16)), f"{q[0]:.2f}, {q[1]:.2f}", size=12,
                          color=P["dim"], parent=tag)

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
        press = pressed or rpressed or (down and not ed["was"]) or (rdown and not ed["rwas"])
        if press and not dpg.is_item_hovered(ed["tag"]):
            inside = False                     # a press counts on the curve itself, not through a menu or a list over it
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
        # not while a point is dragged: taking one away shortened the list under the dragged index, and each frame
        # then raised IndexError in the main loop until the button was let go
        if (rpressed or (rdown and not ed["rwas"])) and inside and len(pts) > 2 and ed["drag"] is None:
            k = nearest()
            if k is not None:
                self.touch(); self.snapshot(("curve", ed["nid"], ed["name"], k, "del"))
                pts.pop(k); n["params"][ed["name"]] = pts
                self._sync_pos(); self.rebuild()
        ed["was"], ed["rwas"] = down, rdown
        if down and ed["drag"] is not None or inside:
            self._curve_draw()
