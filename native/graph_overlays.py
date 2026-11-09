"""What is drawn over the graph - a mixin of graph_ui's GraphPanel: focus mode, a node's wires lit, the minimap, wire labels, and what an overlay covers."""
import time
import dearpygui.dearpygui as dpg
from native.typeface import px
from native import typeface
from native import graph as G
from native import nodeface
from native import graph_ui as GU


class GraphOverlays:
    # --- focus mode -------------------------------------------------------------------
    # Everything but the selection and what it is wired to goes dim, so a
    # busy graph can be read one piece at a time. Themes are rebound when
    # the selection changes; nothing is rebuilt.
    def _dim_theme(self):
        light = self._light()
        th = self._node_themes.get(("dim", self.zoom, light))
        if th is None:
            from native.theme import theme_colors
            cols = theme_colors(self.app.prefs)
            bg, frame, line, dim = (tuple(cols[k]) for k in ("bg", "frame", "line", "dim"))
            # faded toward the canvas: what is out of focus sinks into the ground
            fade = lambda c, f: tuple(int(a + (b - a) * f) for a, b in zip(c, bg))
            with dpg.theme() as th:
                with dpg.theme_component(dpg.mvNode):
                    dpg.add_theme_color(dpg.mvNodeCol_NodeBackground, fade(frame, 0.5) + (110,), category=dpg.mvThemeCat_Nodes)
                    dpg.add_theme_color(dpg.mvNodeCol_NodeBackgroundHovered, fade(frame, 0.4) + (130,), category=dpg.mvThemeCat_Nodes)
                    dpg.add_theme_color(dpg.mvNodeCol_TitleBar, fade(line, 0.4) + (110,), category=dpg.mvThemeCat_Nodes)
                    dpg.add_theme_color(dpg.mvNodeCol_TitleBarHovered, fade(line, 0.3) + (130,), category=dpg.mvThemeCat_Nodes)
                    dpg.add_theme_color(dpg.mvNodeCol_NodeOutline, line + (60,), category=dpg.mvThemeCat_Nodes)
                    dpg.add_theme_color(dpg.mvNodeCol_Pin, fade(dim, 0.4) + (120,), category=dpg.mvThemeCat_Nodes)
                with dpg.theme_component(dpg.mvAll):
                    dpg.add_theme_color(dpg.mvThemeCol_Text, fade(dim, 0.45), category=dpg.mvThemeCat_Core)
                    dpg.add_theme_color(dpg.mvThemeCol_FrameBg, fade(frame, 0.5) + (80,), category=dpg.mvThemeCat_Core)
                    self._zoom_styles()
            self._node_themes[("dim", self.zoom, light)] = th
        return th

    def _dim_wire(self):
        return self._wire_theme((44, 49, 60))

    def set_focus_mode(self, on):
        self.focus_mode = bool(on)
        self._focus_sel = None
        self._wires_lit = GU._STALE                 # focus mode rules the wires while it is on; off, they are lit afresh
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

    # --- a node's wires lit -----------------------------------------------------------------
    # While the pointer rests on a node (or a pin) and while nodes are
    # selected, their wires are drawn brighter and thicker and every other
    # wire fades to a trace of its colour, so one node's connections read
    # in a busy graph (the critique's C11) - the nodes stay as they are
    # (focus mode, which dims them too, rules the wires while it is on).
    # Nothing is rebuilt: the wires' themes change when what is lit does.
    def wire_light(self):
        return bool(self.app.prefs.get("wire_light", True))

    def set_wire_light(self, on):
        """View > Light a node's wires, kept in the prefs."""
        from native.project import save_prefs
        self.app.prefs["wire_light"] = bool(on)
        save_prefs(self.app.prefs)
        self._wires_lit = GU._STALE
        if dpg.does_item_exist("menu_wire_light"):
            dpg.set_value("menu_wire_light", bool(on))
        self.status("a node's wires lit while it is under the pointer or selected, the rest faded" if on
                    else "every wire drawn as it is, whatever is selected")

    def _hover_target(self):
        """What the pointer rests on in the editor: ("pin", node, "in"/"out",
        name), ("node", node) - a frame only where no node is - or None;
        looked up at most every twentieth of a second."""
        now = time.time()
        at, what = self._hover_cache
        if now - at < 0.05:
            return what
        what = None
        if self.graph and dpg.does_item_exist("node_editor") and dpg.is_item_shown("node_editor") \
                and dpg.is_item_hovered("node_editor"):
            for (nid, kind, name), tag in self._pins.items():
                if dpg.does_item_exist(tag) and dpg.is_item_hovered(tag):
                    what = ("pin", nid, kind, name)
                    break
            else:
                # a frame holds nodes: the node over it wins
                for nid, n in sorted(self.graph.nodes.items(), key=lambda kv: kv[1]["type"] == "Frame"):
                    tag = f"gnode_{nid}"
                    if dpg.does_item_exist(tag) and dpg.is_item_hovered(tag):
                        what = ("node", nid)
                        break
        self._hover_cache = (now, what)
        return what

    def _lit_wires(self, sel, hov):
        """The wires (b, inp) to light: the selected nodes', and the hovered
        pin's or node's (a frame's own - none - lights nothing)."""
        out = set()
        for a, o, b, i in self.graph.links:
            if a in sel or b in sel:
                out.add((b, i))
        if hov and hov[0] == "pin":
            _, nid, kind, name = hov
            out |= {(b, i) for a, o, b, i in self.graph.links
                    if (kind == "out" and a == nid and o == name) or (kind == "in" and b == nid and i == name)}
        elif hov:
            nid = hov[1]
            out |= {(b, i) for a, o, b, i in self.graph.links if a == nid or b == nid}
        return out

    def _poll_wires(self):
        now = time.time()
        if now - self._wires_at < 0.05:
            return
        self._wires_at = now
        if not self.graph or self.focus_mode or self._drag_type is not None or not self.links:
            return                                   # (a wire being dragged: its pins say what fits)
        if not dpg.does_item_exist("node_editor") or not dpg.is_item_shown("node_editor"):
            return
        lit = None
        if self.wire_light():
            keys = self._lit_wires(set(self._selected()), self._hover_target())
            lit = frozenset(keys) if keys else None
        if lit == self._wires_lit:
            return
        self._wires_lit = lit
        for lid in list(self.links):
            self._restyle_wire(lid)

    def _restyle_wire(self, lid):
        """A wire in the theme it wears now: dimmed as the one a dragged node
        would splice into; lit or faded while a node's wires are lit; else
        its own."""
        if not dpg.does_item_exist(lid):
            return
        if self._splice and self._splice[1] == lid:
            dpg.bind_item_theme(lid, self._dim_wire())
            return
        lit = self._wires_lit if self._wires_lit is not GU._STALE else None
        style = self._link_style.get(lid)
        if lit is None or style is None or self.focus_mode:
            dpg.bind_item_theme(lid, self._link_normal.get(lid, 0))
            return
        dpg.bind_item_theme(lid, self._wire_theme(style[0], style[1], "lit" if self.links.get(lid) in lit else "faded"))

    def wire_state(self, b, inp):
        """"lit", "faded" or "normal" - how the wire into (b, inp) is drawn now."""
        lit = self._wires_lit if self._wires_lit is not GU._STALE else None
        if lit is None:
            return "normal"
        return "lit" if (b, inp) in lit else "faded"

    # --- the minimap ---------------------------------------------------------------------
    # imnodes' own (a click on it pans the view): faint over the graph until
    # the pointer comes to its corner, drawn full while it is there. Its
    # corner is View > Minimap's (room.minimap_corner). Only the app's theme
    # colours it - a theme bound to the node editor never reaches it (a
    # probe: its background stayed the app theme's under an editor theme of
    # another colour) - so the app theme's own colour items are set in place.
    def minimap_rect(self):
        """Where the minimap can be on the screen, (x0, y0, x1, y1): imnodes
        gives it a fifth of the editor each way at its corner, in from the
        edges by its offset (it fits the graph's shape inside that). None
        while it is off."""
        if not self.graph or not self.app.prefs.get("minimap", True) or not dpg.does_item_exist("node_editor"):
            return None
        w, h = dpg.get_item_rect_size("node_editor")
        if w <= 0 or h <= 0:
            return None
        ex, ey = self.editor_origin()
        mw, mh, off = w * 0.2, h * 0.2, 4.0
        c = self._mini_corner
        x0 = ex + w - off - mw if c[1] == "r" else ex + off
        y0 = ey + h - off - mh if c[0] == "b" else ey + off
        return (x0, y0, x0 + mw, y0 + mh)

    def _poll_minimap(self):
        now = time.time()
        if now - self._mini_at < 0.05:
            return
        self._mini_at = now
        if not dpg.does_item_exist("node_editor") or not dpg.is_item_shown("node_editor"):
            return
        r = self.minimap_rect()
        faint = True
        if r is not None:
            mx, my = dpg.get_mouse_pos(local=False)
            faint = not (r[0] <= mx <= r[2] and r[1] <= my <= r[3])
        now_applied = (faint, GU.MINIMAP_ITEMS.get(dpg.mvNodesCol_MiniMapBackground))
        if now_applied != self._mini_applied:
            self._mini_faint = faint
            self._mini_applied = now_applied
            GU.minimap_faint(self.app.prefs, faint)

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

    # --- what covers an overlay --------------------------------------------------------
    # The readouts, the range bars and the wire labels are drawn on a viewport drawlist in
    # front of everything, clipped to the pane only - so the numbers of a pin under another
    # node, or under the 3-D view in the graph's corner, showed through it. imnodes draws the
    # nodes in an order of its own - the order they were made (a rebuild makes the frames
    # first), a node new to it last, and a node clicked on brought to the front - which the
    # panel keeps as _depth; an overlay is left out where a node above its own covers it, or
    # a window floating over the pane (App.overlay_holes), or the minimap.
    def _raise(self, nid):
        if nid in self._depth:
            self._depth.remove(nid)
        self._depth.append(nid)

    def _cover(self):
        """This frame's covers: {node: its rectangle} (frames left out: a frame is a
        wash the nodes and wires show through), {node: its place in the drawing order},
        and the rectangles drawn over the whole editor."""
        pad = self.px(8)                               # the node's body is its content rect padded
        rects = {}
        for nid, n in self.graph.nodes.items():
            tag = f"gnode_{nid}"
            if n.get("type") == "Frame" or not dpg.does_item_exist(tag):
                continue
            st = dpg.get_item_state(tag)
            (x0, y0), (x1, y1) = st.get("rect_min", (0, 0)), st.get("rect_max", (0, 0))
            if x1 > x0 and y1 > y0:
                rects[nid] = (x0 - pad, y0 - pad, x1 + pad, y1 + pad)
        order = {nid: k for k, nid in enumerate(self._depth)}
        over = list(self.app.overlay_holes()) if hasattr(self.app, "overlay_holes") else []
        mini = self.minimap_rect()
        if mini:
            over.append(mini)
        return rects, order, over

    def _covered(self, box, cover, nid=None, nodes=True):
        """Is `box` (x0, y0, x1, y1) covered: by a window, the minimap - or, with `nodes`,
        a node drawn above `nid`'s (any node, when nid is None: a wire is under them all)."""
        rects, order, over = cover

        def meets(r):
            return box[0] < r[2] and r[0] < box[2] and box[1] < r[3] and r[1] < box[3]
        if any(meets(r) for r in over):
            return True
        if not nodes:
            return False
        mine = order.get(nid, -1) if nid is not None else -1
        return any(m != nid and (nid is None or order.get(m, -1) > mine) and meets(r) for m, r in rects.items())

    # AI: below section was generated by an AI
    OVERLAY_SETTLE = 0.12        # seconds the overlays stay away after the canvas stops moving

    def _overlay_paused(self):
        """True while the canvas moves - dragged with the middle button, nodes dragged, the zoom changed,
        or any node's place on screen changing (a framing, a key's pan) - and for a moment after. The
        overlays (the readouts, range bars, hover plot, wire labels, costs) are placed from the nodes'
        rectangles as imnodes drew them the frame before, so while everything moves they trail a frame
        behind and land on the nodes next to theirs; away until it is still, they never stand wrong."""
        now = time.time()
        moved = self.panning() or self.dragging_nodes() or self.zoom != getattr(self, "_overlay_zoom", self.zoom)
        self._overlay_zoom = self.zoom
        ref = next((f"gnode_{nid}" for nid in (self.graph.nodes if self.graph else ())
                    if dpg.does_item_exist(f"gnode_{nid}")), None)
        at = tuple(dpg.get_item_state(ref).get("rect_min", (0, 0))) if ref else None
        if at is not None and at != getattr(self, "_overlay_ref", at):
            moved = True                                  # a node's place changed since the last frame
        self._overlay_ref = at
        if moved:
            self._overlay_moved = now
        return now - getattr(self, "_overlay_moved", 0.0) < self.OVERLAY_SETTLE
    # AI: end

    def _poll_readouts(self):
        """The live value on every frame-scope output pin of the effect on
        screen - one number a frame each, read from the probes the build
        planted (as a synth's meters: always on, not on hover). Away while
        the canvas moves (_overlay_paused)."""
        for it in self._readout_items:
            if dpg.does_item_exist(it):
                dpg.delete_item(it)
        self._readout_items = []
        if not self.graph or self.app.layout != "graph" or not self.app.ui or self.zoom < 0.7:
            return
        if self._overlay_paused():
            return
        if dpg.is_item_shown("graph_menu") or dpg.is_item_shown("graph_ctx") or self.overview():
            return
        pane = self.app._screen_rect("graph_win")
        if not pane:
            return
        eh = dpg.get_item_rect_size("node_editor")[1]
        x0, y0, x1, y1 = pane[0] + 9, pane[3] - 9 - eh, pane[2] - 9, pane[3] - 9
        size = max(9, int(11 * self.zoom))
        self._cover_now = cover = self._cover()          # the range bars and the hover plot use it too
        probes = getattr(self, "_probes", None) or {}
        eng = self.app.eng
        live = bool(probes) and bool(getattr(self, "_probes_for", None)) and bool(eng.names)             and eng.names[eng.idx] == self.app.project.effect_title(self._probes_for or "")
        if not live:
            self._draw_mod_ranges((x0, y0, x1, y1), size)      # the ranges stand without a running build; the dot needs one
            return
        scope = getattr(self, "_probe_scope", {}) or {}
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
                cx, cy = ax - 10 - self.text_w(name) - 6 - r, ay
                if cx - r < x0 or cx + r > x1 or cy - r < y0 or cy + r > y1:
                    continue
                if self._covered((cx - 1.8 * r, cy - 1.8 * r, cx + 1.8 * r, cy + 1.8 * r), cover, nid):
                    continue
                fill = (int(70 + 100 * lvl), int(76 + 154 * lvl), int(88 + 32 * lvl), 255)
                self._readout_items.append(dpg.draw_circle((cx, cy), r, parent="wire_labels", color=(30, 33, 40, 255), fill=fill))
                if lvl > 0.02:
                    self._readout_items.append(dpg.draw_circle((cx, cy), r * (1.0 + 0.8 * lvl), parent="wire_labels",
                                                               color=(170, 230, 120, int(110 * lvl)), thickness=1.0))
                continue
            text = f"{v:.3g}" if abs(v) < 1e5 else f"{v:.2e}"
            # left of the pin's name, inside the node: the name is right-aligned to the pin
            w = typeface.measure(text, "mono", size)
            rx = ax - 10 - self.text_w(name) - 6 - w
            ry = ay - size * 0.55
            if rx < x0 or rx + w > x1 or ry < y0 or ry + size > y1:
                continue
            rng = nodeface.out_range(n, d, name) if d else None
            mw = max(w, 24 * self.zoom)
            if self._covered((min(rx, rx + w - mw), ry, rx + w, ry + size + (3 if rng else 0)), cover, nid):
                continue                                 # under a node above this one, a window, the minimap
            self._readout_items.append(self._draw_text((rx, ry), text, parent="wire_labels", color=self.pal()["live"], size=size))
            if rng and ry + size + 3 < y1:
                # a meter under the number: how far along its range the value is
                lo, hi = rng
                f = max(0.0, min(1.0, (v - lo) / (hi - lo))) if hi > lo else 0.0
                mx = rx + w - mw
                self._readout_items.append(dpg.draw_rectangle((mx, ry + size + 1), (mx + mw, ry + size + 3), parent="wire_labels",
                                                              color=(0, 0, 0, 0), fill=self.pal()["meter_bg"]))
                self._readout_items.append(dpg.draw_rectangle((mx, ry + size + 1), (mx + mw * f, ry + size + 3), parent="wire_labels",
                                                              color=(0, 0, 0, 0), fill=self.pal()["live"]))
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
        if dpg.is_item_shown("graph_menu") or dpg.is_item_shown("graph_ctx") or self._overlay_paused():
            return                                       # (moving: the labels would trail the wires)
        labelled =[(k, m["label"]) for k, m in self.graph.link_meta.items() if m.get("label")]
        if not labelled:
            return
        pane = self.app._screen_rect("graph_win")
        if not pane:
            return
        eh = dpg.get_item_rect_size("node_editor")[1]
        x0, y0, x1, y1 = pane[0] + 9, pane[3] - 9 - eh, pane[2] - 9, pane[3] - 9
        ends = {(l[2], l[3]): (l[0], l[1]) for l in self.graph.links}
        cover = self._cover()
        for (b, inp), text in labelled:
            src = ends.get((b, inp))
            if not src:
                continue
            pa, pb = self._pin_point(src[0], "out", src[1]), self._pin_point(b, "in", inp)
            if not pa or not pb:
                continue
            (ax, ay), (bx, by) = pa, pb
            mx, my = (ax + bx) / 2, (ay + by) / 2
            size = typeface.size_of("small")             # a wire's own name: words, in the interface's face
            w, hh = typeface.measure(text, "body", size) + px(10), size / 2 + px(2)
            if mx - w / 2 < x0 or mx + w / 2 > x1 or my - hh < y0 or my + hh > y1:
                continue
            if self._covered((mx - w / 2, my - hh, mx + w / 2, my + hh), cover):
                continue                                 # a wire runs under every node: so does its label
            edge, fill, ink = self.pal()["popup_edge"], self.pal()["popup"], self.pal()["text"]
            if self.wire_state(b, inp) == "faded":         # its wire faded while another node's are lit: it fades too
                edge, fill, ink = edge[:3] + (60,), fill[:3] + (80,), ink[:3] + (90,)
            self._label_items.append(dpg.draw_rectangle((mx - w / 2, my - hh), (mx + w / 2, my + hh), parent="wire_labels",
                                                        color=edge, fill=fill, rounding=4))
            self._label_items.append(self._draw_text((mx - w / 2 + px(5), my - size / 2), text, parent="wire_labels",
                                                   color=ink, size=size, face="body"))
