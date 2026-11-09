"""The graph's problems - a mixin of graph_ui's GraphPanel: a build's errors on the nodes that wrote the lines, a graph that does not compile, the marks and category themes on the nodes."""
import os
import dearpygui.dearpygui as dpg
from native import messages
from native import graph as G
from native import nodeface
from native import oops
from native import graph_ui as GU


class GraphProblems:
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

    def build_failed(self, fname, errs):
        """The build of `fname` failed with errs [(path, line, message)]: each error on a line
        a node of this graph wrote goes to that node - its outline, its menu, the problems
        held in the log - as well as to the code pane's list. Nothing when the file is not
        this graph's, or has been edited by hand since it was written. Returns
        {(file name, line): node id} for the errors placed."""
        mf, lines, text = getattr(self, "_line_map", (None, {}, ""))
        if not self.graph or not fname or fname != mf or not lines:
            return {}
        try:
            if self.app.project.read_effect(fname) != text:
                return {}
        except OSError:
            return {}
        key, bad = getattr(self, "_build_problems", (None, {}))
        if key != self._key():
            key, bad = self._key(), {}
        placed = {}
        for path, line, msg in errs:
            nid = lines.get(int(line)) if os.path.basename(path) == fname else None
            if nid is None or nid not in self.graph.nodes:
                continue
            placed[(fname, int(line))] = nid
            if msg.startswith("error") and nid not in bad:
                bad[nid] = "error: does not build - " + msg.split(": ", 1)[-1]
        self._build_problems = (key, bad)
        if bad:
            self._mark_problems()
        return placed

    def build_ok(self, fname):
        """A build of `fname` went through: the nodes it blamed before are clear."""
        if fname == getattr(self, "_line_map", (None,))[0] and self._clear_build_problems():
            self._mark_problems()

    def _clear_build_problems(self):
        """Forget the last build's errors on this graph's nodes, their red outlines with them (the
        caller marks what problems remain). True when there were any."""
        key, bad = getattr(self, "_build_problems", (None, {}))
        self._build_problems = (self._key(), {})
        if key != self._key() or not bad:
            return False
        for nid in bad:
            if self.graph and nid in self.graph.nodes and dpg.does_item_exist(f"gnode_{nid}"):
                self._bind_node_theme(nid, self.graph.nodes[nid])
        return True

    def _mark_problems(self):
        if not self.graph:
            return
        self.problems = self.graph.problems()
        # a failed build's errors on the lines a node wrote (build_failed), while they last
        key, bad = getattr(self, "_build_problems", (None, {}))
        if key == self._key():
            for nid, msg in bad.items():
                if nid in self.graph.nodes and not self.problems.get(nid, "").startswith("error"):
                    self.problems[nid] = msg
        # the errors held in the log while they last: judged again on every
        # change (a rebuild, a hover's dimming), each logged once
        messages.hold(self.app, f"problem:{self._key()}:",
                      {f"problem:{self._key()}:{nid}": (f"{self.graph.nodes[nid]['type']} #{nid}: {msg[7:]}", self.where(nid))
                       for nid, msg in self.problems.items() if msg.startswith("error") and nid in self.graph.nodes})
        for nid, msg in self.problems.items():
            tag = f"gnode_{nid}"
            if not dpg.does_item_exist(tag):
                continue
            kind = "error" if msg.startswith("error") else "warn"
            n = self.graph.nodes[nid]
            # a coloured or framed node keeps its colour theme; the outline wins on top of it
            if kind == "error" or not (n.get("color") or n["type"] == "Frame"):
                dpg.bind_item_theme(tag, self._mark_theme(kind))

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
                oops.swallowed()
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
        self._raise(nid)                                 # imnodes draws a node new to it last: on top
        th = self.themes()
        linked = {(b, inp) for _, _, b, inp in self.graph.links}
        n.setdefault("inputs", {})
        label = self.node_title(n, d)
        collapsed = bool(n.get("collapsed"))
        hide = bool(n.get("hide_pins"))
        width = self.px(GU.NARROW_W if d.get("narrow") else GU.NODE_W)
        if n["type"] != "Frame":
            label, width = self._fit_title(label, width)
        self._node_w[nid] = width
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
                    t = self.px(GU.THUMB)
                    dpg.add_image("preview_thumb_tex", width=t, height=t, tag=f"gthumb_{nid}")
                    dpg.add_text(f"previewing {self.preview[1]}", color=GU.DIM)
            fed_out = {(a, o) for a, o, _, _ in self.graph.links}
            col = 0 if collapsed else self._field_column(d, width, multiline=d.get("multiline", False), type_=n["type"])
            for i in d["inputs"]:
                if hide and (nid, i["name"]) not in linked:
                    continue
                if not self.pin_read(n, i) and (nid, i["name"]) not in linked:
                    continue                              # an operation that does not read it (Math's b for sqrt)
                tag = f"gin_{nid}_{i['name']}"
                with dpg.node_attribute(attribute_type=dpg.mvNode_Attr_Input, tag=tag,
                                        user_data=(nid, i["name"]), shape=dpg.mvNode_PinShape_CircleFilled):
                    # An unconnected input is EDITABLE on the node: the value
                    # it takes stands in for the wire. Connected, the field
                    # hides and the name stays. A checkbox wears its name.
                    is_linked = (nid, i["name"]) in linked
                    shown = nodeface.label(n["type"], i["name"])     # the name people use; the key stays the key
                    if collapsed or i["type"] == "bool":
                        dpg.add_text(shown, tag=tag + "_t", show=is_linked or collapsed)
                        if not collapsed:
                            self._input_widget(nid, n, i, tag + "_w", show=not is_linked)
                    else:
                        with dpg.group(horizontal=True, horizontal_spacing=self._gap()):
                            self._lead(shown, col, tag + "_t")
                            self._input_widget(nid, n, i, tag + "_w", show=not is_linked, width=width - col)
                dpg.bind_item_theme(tag, th.pin[i["type"]])
                self._pins[(nid, "in", i["name"])] = tag
                self._ptype[tag] = i["type"]
            if not collapsed and n["type"] != "Frame":
                paired = {a: (a, b, words) for a, b, words in nodeface.pairs(n["type"])}
                pdefs = {p["name"]: p for p in d["params"]}
                done = set()
                for p in d["params"]:
                    if p["name"] in done or nodeface.is_meta(n["type"], p["name"]):
                        continue                          # the effect's own (a slider's label, where it starts): the properties
                    pr = paired.get(p["name"])
                    q = pdefs.get(pr[1]) if pr else None
                    if q is not None and p["type"] in ("float", "int") and q["type"] == p["type"]:
                        done.add(q["name"])               # one range, one row: "in  [0] -> [1]"
                        with dpg.node_attribute(attribute_type=dpg.mvNode_Attr_Static):
                            self._pair_widget(nid, n, p, q, pr[2], col, width)
                        continue
                    with dpg.node_attribute(attribute_type=dpg.mvNode_Attr_Static):
                        self._param_widget(nid, n, p, multiline=d.get("multiline", False), col=col, width=width)
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
                        dpg.add_text(text, tag=f"gsum_{nid}", color=self.pal()["soft"], wrap=width)
            for o in d["outputs"]:
                if hide and (nid, o["name"]) not in fed_out:
                    continue
                tag = f"gout_{nid}_{o['name']}"
                with dpg.node_attribute(attribute_type=dpg.mvNode_Attr_Output, tag=tag,
                                        user_data=(nid, o["name"]), shape=dpg.mvNode_PinShape_CircleFilled):
                    shown = nodeface.label(n["type"], o["name"])
                    if self.text_w(shown) > width:
                        shown = nodeface.fit_width(shown, width, self.text_w)     # cut, not the node pushed wider
                    dpg.add_text(shown, indent=GU._right(self.text_w(shown), width))
                dpg.bind_item_theme(tag, th.pin[o["type"]])
                self._pins[(nid, "out", o["name"])] = tag
                self._ptype[tag] = o["type"]
        self._bind_node_theme(nid, n)

    @staticmethod
    def pin_read(n, i):
        """Whether the node's settings read input `i`: a pin shown only for
        some operations (nodedefs.SHOWN_WHEN) is not, under any other."""
        w = i.get("when")
        return not w or n.get("params", {}).get(w["param"], w.get("default")) in w["values"]

    GROUP_MARK = "--"

    def _choice_items(self, p):
        """A choice's dropdown rows: its values, or - grouped
        (nodedefs.CHOICE_GROUPS) - each group's name, a row of its own,
        above its values."""
        if not p.get("groups"):
            return list(p["choices"])
        out = []
        for name, vals in p["groups"]:
            out.append(f"{self.GROUP_MARK} {name} {self.GROUP_MARK}")
            out += list(vals)
        return out

    def _choice_cb(self, nid, p, cb):
        """A grouped choice's callback: a group's name picked changes nothing
        (the field goes back to the value)."""
        def pick(sender, val):
            if isinstance(val, str) and val.startswith(self.GROUP_MARK + " "):
                n = self.graph.nodes.get(nid) if self.graph else None
                dpg.set_value(sender, str((n or {}).get("params", {}).get(p["name"], p["default"])))
                return
            cb(sender, val)
        return pick

    def _fit_title(self, label, width):
        """A title within its node, and the width the node is laid out to: a
        narrow node (a knot, a send, a receive) widens to its title, up to a
        whole node's width; a title longer than that is cut with "..." - a
        node never grows past its width for its words (the help line and the
        properties have the title whole)."""
        import math
        tw = math.ceil(self.text_w(label))
        full = self.px(GU.NODE_W)
        if width < tw and width < full:
            width = min(full, tw)
        if tw > width:
            label = nodeface.fit_width(label, width, self.text_w)
        return label, width

    def node_title(self, n, d):
        """A node's title: the name it was given, else its definition's; a
        send, a receive or a graph's pin with its name, a frame its title, a
        control node with its label on the WLED page ("Speed: Rise" - the
        label is edited in the properties, C12); "(muted)" while muted."""
        label = n.get("label") or d.get("label") or n["type"]
        if n["type"] in ("Graph input", "Graph output") or n["type"] in G.SENDS or n["type"] in G.RECEIVES:
            label = f"{n['type']}: {n['params'].get('name', '')}"
        elif n["type"] == "Frame":
            label = str(n["params"].get("title", "group"))
        elif not n.get("label") and n["type"] in nodeface.META:
            lbl = str(n["params"].get("label", "") or "").strip()
            if lbl and lbl != n["type"]:
                label = f"{n['type']}: {lbl}"
        if n.get("muted"):
            label = f"{label} (muted)"
        return label

    def _standin_rows(self, nid):
        """A stand-in's pin rows and their height: the node keeps the
        footprint its full self would have at this zoom (the height
        estimate arrange uses), so the graph's spacing survives zooming
        out - a stand-in is the full node scaled, not a label dropped on
        its corner."""
        n = self.graph.nodes[nid]
        d = self.graph.node_def(n)
        rows = len(d["inputs"]) + len(d["outputs"]) + nodeface.param_rows(n, d)
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
                    dpg.add_text(nodeface.fit_width(text, width, self.text_w), tag=f"gsum_{nid}", color=self.pal()["soft"])
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
        light = self._light()
        key = ("cat", cat, light)
        th = self._node_themes.get(key)
        if th is None:
            r, g, b = self._tint(nodeface.hue(cat), light)
            with dpg.theme() as th:
                with dpg.theme_component(dpg.mvCollapsingHeader):
                    dpg.add_theme_color(dpg.mvThemeCol_Header, (r, g, b, 170))
                    dpg.add_theme_color(dpg.mvThemeCol_HeaderHovered, (min(255, r + 30), min(255, g + 30), min(255, b + 30), 200))
                    dpg.add_theme_color(dpg.mvThemeCol_HeaderActive, (min(255, r + 50), min(255, g + 50), min(255, b + 50), 220))
            self._node_themes[key] = th
        return th
