"""What the graph's menus do to nodes and wires - a mixin of graph_ui's GraphPanel: help and where a type is used, promoting and exposing settings, colours, inserting, disconnecting, resetting, driving an input with a control, changing a node's type, merging, unfolding, arranging, aligning and distributing."""
import os
import dearpygui.dearpygui as dpg
from native.typeface import px
from native import graph as G
from native import nodeface
from native import oops
from native.graph import compatible          # the one rule for what may feed what
from native import graph_ui as GU


class GraphActions:
    def help_here(self):
        """F1 in the graph: the node reference at the node under the
        pointer, else at the selected one; with neither, the guide's
        chapter on making an effect."""
        from native import reader_ui
        nid = None
        if dpg.does_item_exist("node_editor") and dpg.is_item_hovered("node_editor"):
            nid = self._node_at(dpg.get_mouse_pos(local=False))
        if nid is None:
            sel = self._selected()
            nid = sel[0] if sel else None
        if nid is not None and self.graph and nid in self.graph.nodes:
            return self.open_reference(self.graph.nodes[nid]["type"])
        reader_ui.open_doc(self.app, "GUIDE.md", "Making an effect")
        self.status("F1 over a node (or with one selected) opens that node's entry")
        return False

    def open_reference(self, type_):
        """The node reference (Help > Node reference) at this type's entry;
        a sub-graph has none of its own - the guide on them instead."""
        from native import reader_ui
        if type_.startswith(G.SUB):
            reader_ui.open_doc(self.app, "GUIDE.md", "Making an effect")
            self.status(f"{type_[len(G.SUB):]} is a sub-graph of this project: its own nodes are in the reference")
            return False
        if reader_ui.open_doc(self.app, "NODES.md", type_):
            return True
        self.status(f"{type_} has no entry in the node reference")
        return False

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
                    oops.swallowed()
                    continue
                n = sum(1 for x in nodes if x.get("type") == type_)
                if n:
                    out.append((f, sub, n))
        return out

    def show_where_used(self, type_):
        """The list, in a small window: a click opens that graph."""
        P = "where_win"
        if not dpg.does_item_exist(P):
            dpg.add_window(tag=P, label="Where used", width=px(360), height=px(300), show=False, no_collapse=True)
        dpg.delete_item(P, children_only=True)
        label = self.lib.get(type_, {}).get("label") or (type_[len(G.SUB):] + " (sub-graph)" if type_.startswith(G.SUB) else type_)
        dpg.add_text(label, parent=P, color=(90, 169, 230))
        rows = self.where_used(type_)
        if not rows:
            dpg.add_text("used in no graph", parent=P, color=GU.DIM)
        for f, sub, n in rows:
            dpg.add_selectable(label=f"{f[:-5]}{'  (sub-graph)' if sub else ''}   x{n}", parent=P, user_data=(f, sub), width=px(300),
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
        self.status(f"{self.pin_words(nid, name)}: {'a setting of the sub-graph node now' if on else 'kept inside'}")

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
        self.status(f"{self.pin_words(nid, name)}: {'a pin now' if on else 'a setting again'}", node=self.where(nid))

    def _node_colour_rows(self, P, nid):
        dpg.add_text("node colour", parent=P, color=GU.DIM)
        for chunk in (GU.WIRE_COLOURS[:5], GU.WIRE_COLOURS[5:]):
            with dpg.group(parent=P, horizontal=True):
                for label, col in chunk:
                    if col is None:
                        dpg.add_button(label="auto", small=True,
                                       callback=lambda: (self._hide_menus(), self._set_colour(nid, None)))
                    else:
                        dpg.add_color_button(default_value=list(col) + [255], width=px(18), height=px(18), no_border=True,
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
        dpg.add_text("wire colour", parent=P, color=GU.DIM)
        # two rows of five, so the swatches never run past the menu's edge
        for chunk in (GU.WIRE_COLOURS[:5], GU.WIRE_COLOURS[5:]):
            with dpg.group(parent=P, horizontal=True):
                for label, col in chunk:
                    if col is None:
                        dpg.add_button(label="auto", small=True,
                                       user_data=keys, callback=lambda s, a, u: (self._hide_menus(), self._set_wire(u, None)))
                    else:
                        dpg.add_color_button(default_value=list(col) + [255], width=px(18), height=px(18), no_border=True,
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
        self.graph.nodes[r]["label"] = f"{nodeface.label(n['type'], name)} \u00b1{amount:.3g}"
        self.graph.nodes[r]["modulator"] = True             # the fed pin draws this Remap's range as its own
        self.graph.link(source, sout, r, "x")
        self.graph.link(r, "result", nid, name)
        self.rebuild()
        self.status(f"{self.pin_words(nid, name)} modulated by {self.graph.nodes[source]['type']}: {v - amount:.3g} .. {v + amount:.3g} "
                    f"(the Remap's out low and out high set the range)", node=self.where(nid))

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
            oops.swallowed()
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

    def space_out(self):
        """The nodes that run into the one above them in their column pushed down (the selection's, or all), the
        layout otherwise kept - a graph laid out before its nodes grew a curve or a meter under their fields."""
        if not self.graph:
            return
        sel = self._selected()
        self.snapshot(); self._sync_pos()
        heights, widths = {}, {}
        if not self.overview():                       # stand-ins are smaller than the nodes: the model's sizes then
            for nid in self.graph.nodes:
                st = dpg.get_item_state(f"gnode_{nid}") if dpg.does_item_exist(f"gnode_{nid}") else {}
                if st.get("rect_size") and st["rect_size"][0] > 0:
                    widths[nid], heights[nid] = st["rect_size"][0] / self.zoom, st["rect_size"][1] / self.zoom
        moved = self.graph.space_out(heights, widths, only=set(sel) if len(sel) >= 2 else None)
        if moved:
            self.rebuild()
            self.status(f"spaced out: {len(moved)} node(s) moved down, clear of the one above")
        else:
            self.status("no node runs into another")

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
        return (GU.NODE_W, 120)

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
                    self.status(f"{da.get('label') or da['name']} . {nodeface.label(self.graph.nodes[a]['type'], o['name'])} -> "
                                f"{nodeface.label(self.graph.nodes[b]['type'], i['name'])}"); return
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
