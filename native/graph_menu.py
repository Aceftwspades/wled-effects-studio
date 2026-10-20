"""The graph's context menu - a mixin of graph_ui's GraphPanel: the rows for whatever was right-clicked (a node, a
pin, a wire, the canvas), each calling the panel's own methods."""
import dearpygui.dearpygui as dpg

from native.typeface import px
from native import graph as G
from native import nodeface
from native.nodedefs import IMPLICIT_SOURCES


class GraphMenu:
    def _fill_ctx_menu(self):
        """The context menu's rows, for whatever was right-clicked."""
        from native.graph_ui import DIM
        dpg.delete_item("graph_ctx", children_only=True)
        kind, nid, name = self._ctx
        n = self.graph.nodes[nid]
        d = self.graph.node_def(n)
        P = "graph_ctx"
        close = lambda: dpg.configure_item(P, show=False)
        keyof = lambda k: (self.app.keys.label(k) if k in self.app.keys.bind else k) if k else ""

        def row(label, fn, key=None):
            # Dear PyGui calls a callback with as many of (sender, app_data,
            # user_data) as it has parameters - a third one with a default
            # is overwritten by user_data, a fourth is an error - so what a
            # row does rides in user_data. Inside a fold (tree node) the row
            # goes to the fold: the container stack says where we are.
            # `key`: an action (its binding shows, as the keymap has it) or
            # the words for a fixed gesture ("Backspace").
            # On top, a menu item: the key in a column at the right, the
            # way the menu bar shows them. In a fold, a selectable of a set
            # width with the key after its words - one that takes the width
            # there is chases the window's own sizing, and the menu grew a
            # few pixels every frame until it met the screen's edge (a menu
            # item in a fold does the same).
            parent = dpg.top_container_stack() or P
            k = keyof(key)
            if parent == P:
                dpg.add_menu_item(label=label, shortcut=k, parent=P, user_data=fn, callback=lambda s, a, u: (close(), u()))
            else:
                dpg.add_selectable(label=f"{label}   {k}" if k else label, parent=parent, user_data=fn, width=px(280),
                                   callback=lambda s, a, u: (close(), u()))

        def sep():
            dpg.add_separator(parent=P)

        def reference():
            if not n["type"].startswith(G.SUB):
                row(f"{n['type']} in the node reference...", lambda: self.open_reference(n["type"]), "node_help")

        if kind == "in":
            linked = any(l[2] == nid and l[3] == name for l in self.graph.links)
            dpg.add_text(f"{n['type']} . {nodeface.label(n['type'], name)}", parent=P, color=DIM)
            pd_ = next((x.get("doc") for x in d["inputs"] if x["name"] == name), None)
            if pd_:
                dpg.add_text(pd_, parent=P, color=self.pal()["soft"], wrap=px(260))
            i = next(x for x in d["inputs"] if x["name"] == name)
            if linked:
                row("disconnect", lambda: self._disconnect_in(nid, name))
            src = (d.get("implicit") or {}).get(name)
            row(f"reset: the pixel's {IMPLICIT_SOURCES[src][1]}" if src and not linked else "reset to default",
                lambda: self._reset_input(nid, name, i), "Backspace")
            if i["type"] == "float" and not linked:
                row("type an expression...", lambda: self.expr_for(nid, name, "input"), "expr")
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
                # a controller's knob onto this typed value (Window > MIDI, OSC and phone lists the rest)
                from native import midi_ui, midi
                t = midi_ui.pin_target(self.app, nid, name)
                row("MIDI learn: move a knob", lambda: midi_ui.learn(self.app, t))
                for k, ctl in midi_ui.mapped_to(self.app, t):
                    row(f"forget {midi.ctl_label(ctl)}", lambda k=k: midi_ui.forget(self.app, k))
            sep()
            reference()
        elif kind == "out":
            outs = [l for l in self.graph.links if l[0] == nid and l[1] == name]
            dpg.add_text(f"{n['type']} . {nodeface.label(n['type'], name)}", parent=P, color=DIM)
            pd_ = next((x.get("doc") for x in d["outputs"] if x["name"] == name), None)
            if pd_:
                dpg.add_text(pd_, parent=P, color=self.pal()["soft"], wrap=px(260))
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
            sep()
            reference()
        else:
            # A node's menu: what it is (a line, and its entry in the
            # reference), then what is done most - duplicate, label, the
            # shape toggles, delete - each with its key, and the rest in
            # folds (colour, settings as pins, sub-graph, more).
            title = self.node_title(n, d)
            head = dpg.add_text(title if title == n["type"] else f"{title}  ({n['type']})", parent=P, color=DIM)
            if d.get("doc"):
                # what it is on the title's hover: the menu opens on what can be done (the critique's C14)
                with dpg.tooltip(head):
                    dpg.add_text(nodeface.first_sentence(d["doc"], 400), wrap=px(360))
            if nid in self.problems:
                m = self.problems[nid]
                dpg.add_text(m, parent=P, color=(235, 80, 70) if m.startswith("error") else (240, 190, 70), wrap=px(300))
            sep()
            if n["type"].startswith(G.SUB):
                row("edit sub-graph", lambda: self.enter_sub(nid), "enter_sub")
                row("unfold: its nodes in place of it", lambda: self.unfold_sub(nid))
            row("duplicate", lambda: self._dup(nid))
            row("duplicate with inputs", lambda: self._dup(nid, True), "duplicate")
            if not n["type"].startswith(G.SUB) and n["type"] not in ("Output", "Effect settings", "Note", "Frame", "Graph input", "Graph output"):
                row("change type... (the wires stay)", lambda: self.pick_type_for(nid))
            row("label this node...", lambda: (self.set_selection([nid]), self.label_selected()), "label_node")
            sep()
            if d["inputs"] or d["params"]:
                row("expand" if n.get("collapsed") else "collapse", lambda: self._collapse(nid), "collapse")
                row("show all pins" if n.get("hide_pins") else "hide unwired pins", lambda: self._toggle(nid, "hide_pins"), "hide_pins")
            row("unmute" if n.get("muted") else "mute (pass through)", lambda: self._toggle(nid, "muted"), "mute")
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
            sep()
            row("delete", lambda: self._delete_node(nid), "delete")
            row("delete and reconnect", lambda: (self.set_selection([nid]), self.dissolve_selected()), "dissolve")
            if any(nid in (l[0], l[2]) for l in self.graph.links):
                row("disconnect all (keep the node)", lambda: self._disconnect_node(nid), "disconnect")
            sep()
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
                    row("copy selection", self.copy, "copy")
                    row("cut selection", self.cut, "cut")
                    row("fold selection into a sub-graph", lambda: self.make_sub_from_selection(None), "fold")
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
            sep()
            reference()
