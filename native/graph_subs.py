"""Sub-graphs - a mixin of graph_ui's GraphPanel: a sub-graph file as a node type (its pins, settings and stand-in), entering one and back out by the breadcrumb, folding nodes into one."""
import json
import os
import dearpygui.dearpygui as dpg
from native import messages
from native import graph as G
from native import nodeface
from native.nodedefs import library
from native import graph_ui as GU


class GraphSubs:
    # --- sub-graphs as node types ------------------------------------------------------
    def resolve_sub(self, ident):
        """The Graph for a sub-graph node type, by file stem. Cached until
        refresh_lib(), which runs whenever one is saved. None for one that is
        not there, does not read, or is met again while it is being read (a
        sub-graph inside itself, or A in B in A): said, and left out - one of
        them raised through refresh_lib, and so through the studio's start."""
        if ident not in self._subs:
            path = os.path.join(self.sub_dir, ident + ".json")
            if not os.path.exists(path):
                return None
            loading = self.__dict__.setdefault("_sub_loading", set())
            if ident in loading:
                self.status(f"sub-graph '{ident}' contains itself - it is left out where it does", "error",
                            key=f"subgraph:{ident}")
                return None
            loading.add(ident)
            try:
                g = G.load(path, lib=self.lib, resolver=self.resolve_sub)
            except Exception as e:
                self.status(f"sub-graph '{ident}' does not read ({e}): left out - its file is subgraphs/{ident}.json",
                            "error", key=f"subgraph:{ident}")
                return None
            finally:
                loading.discard(ident)
            g.project_dir = self.app.project.path
            self._subs[ident] = g
        return self._subs[ident]

    def _contains(self, ident, target, seen=None):
        """Whether sub-graph `ident` holds a `target` sub node, at any depth."""
        seen = set() if seen is None else seen
        if ident in seen:
            return False
        seen.add(ident)
        g = self._subs.get(ident)
        for n in (g.nodes.values() if g is not None else ()):
            t = n.get("type", "")
            if t.startswith(G.SUB) and (t[len(G.SUB):] == target or self._contains(t[len(G.SUB):], target, seen)):
                return True
        return False

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
        self._keep_open_one(os.path.join(self.sub_dir if sub else self.dir, fname))
        self.refresh_lib()
        if self.graph is None:
            from native import typeface          # no zoom kept yet: the interface's size, to the nearest step
            first = min(GU.ZOOMS, key=lambda z: abs(z - typeface.scale()))
            self.zoom = min(GU.ZOOMS[-1], max(GU.ZOOMS[0], float(self.app.prefs.get("zoom", first))))
        self.offset = [0.0, 0.0]
        d = self.sub_dir if sub else self.dir
        try:
            g = G.load(os.path.join(d, fname), lib=self.lib, resolver=self.resolve_sub)
        except (G.GraphError, OSError) as e:
            # said, and the graph open now left as it is - at the start it raised, and the studio did not open
            self.status(f"{e} - the file is graphs/{fname}" if not sub else f"{e} - the file is subgraphs/{fname}",
                        "error", key=f"graph:{fname}")
            return False
        self.graph = g
        self.graph.project_dir = self.app.project.path
        self.graph.features = self.features()
        self.file = fname
        self.cur_dir = d
        self._undo.clear(); self._redo.clear(); self._last_snap = None; self._undo_desc.clear(); self.ext_sel = []
        self.preview = None
        self.rebuild()
        dpg.configure_item("graph_file", items=self.files())
        dpg.set_value("graph_file", fname if not sub else "")
        self._trail()
        stray = getattr(self.graph, "stray", None) or []
        self.status(("opened the sub-graph " if sub else "opened ") + fname
                    + (f" - {len(stray)} wire(s) to nodes or pins that are not there dropped" if stray else ""),
                    "warn" if stray else "info")
        self.app.refresh_import_buttons()
        return True

    def _keep_open_one(self, opening=None):
        """The graph open now saved before another replaces it, when it has changes: New graph, a library tile,
        a where-used row or an import replaced it unsaved (with Live off, the edits were gone, and its undo with
        them). Not one whose file is gone (renamed, deleted): that is not written back."""
        if self.graph is None or not self.file:
            return
        path = os.path.join(self.cur_dir or self.dir, self.file)
        if not os.path.exists(path):
            return
        if opening and os.path.normcase(os.path.abspath(opening)) == os.path.normcase(os.path.abspath(path)):
            return                                        # the same file opened again: a reload (a lesson reset,
                                                          # a restore) - the file is what is wanted, not saved over
        self._sync_pos()
        try:
            with open(path, encoding="utf-8") as f:
                same = f.read() == json.dumps(self.graph.to_json(), indent=1)
        except OSError:
            same = False
        if not same:
            self.save()

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
            messages.clear(self.app, f"problem:{self._key()}:"); messages.clear(self.app, f"graph:{self._key()}")
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
                        # whole or not at all: written in place, a write cut short left a graph that did not load
                        from native.project import write_atomic
                        write_atomic(p, txt.replace(f'"{G.SUB}{old_stem}"', f'"{G.SUB}{new_stem}"'))
        self.refresh_lib()
        self.open(self.file, sub=(d == self.sub_dir))
        self.status(f"renamed to {name}")
        if self.app.edit_file == old_cpp:
            self.app.edit_file = new_cpp if new_cpp in proj.effect_files() else None
        self.compile()

    # --- sub-graphs: in and out --------------------------------------------------------
    def open_top(self, fname):
        """A graph picked from the pane's list: the sub-graph trail left
        behind (it led to the graph that was open, not to this one)."""
        if self.graph is not None:
            self.save()
        self.stack.clear()
        self.open(fname)

    def enter_sub(self, nid):
        """Open the sub-graph a node stands for; back returns to here."""
        n = self.graph.nodes.get(nid)
        if not n or not n["type"].startswith(G.SUB):
            return
        self.save()
        here = (self.cur_dir, self.file)
        if self.open(n["type"][len(G.SUB):] + ".json", sub=True):
            self.stack.append(here)                       # only once it opened: a failed one left a Back to nowhere
            self._trail()

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

    def _trail(self):
        """The Back button and the breadcrumbs, from the stack as it is now."""
        dpg.configure_item("graph_back", show=bool(self.stack))
        self._crumbs()

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
            dpg.add_text("›", parent="graph_crumbs", color=GU.DIM)
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
            sub.nodes[smap[nid]].update(GU._node_extras(n))
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

    def status(self, msg, kind="info", node=None, key=None, merge=None):
        """A message - the studio's, whichever pane it comes from: to the
        log and the footer's line (messages.py), where a problem with a key
        stays until it is fixed. `node` is where it is about (self.where)."""
        messages.post(self.app, msg, kind, node=node, key=key, merge=merge)

    def where(self, nid):
        """A node as a message points at it: its graph, its id, and whether
        the graph is a sub-graph (they live in a folder of their own)."""
        return (self.file, nid, self.cur_dir == self.sub_dir)

    def pin_words(self, nid, name):
        """A pin or a setting as a message names it: its node and its name in
        words ("Remap #7 out low"), never its key."""
        n = self.graph.nodes.get(nid) if self.graph else None
        return f"{n['type']} #{nid} {nodeface.label(n['type'], name)}" if n else str(name)

    def _key(self):
        """This graph in a message's key: a sub-graph's name apart from a graph's."""
        return ("sub/" if self.cur_dir == self.sub_dir else "") + (self.file or "")

    def goto_node(self, fname, nid, sub=False):
        """A message's node: its graph open in the graph pane, the node
        selected and framed (no node: the whole graph framed). A sub-graph
        opens as if entered from the graph open now, so back returns there."""
        here = self.graph is not None and fname == self.file and (self.cur_dir == self.sub_dir) == bool(sub)
        if not here:
            d = self.sub_dir if sub else self.dir
            if not os.path.exists(os.path.join(d, fname)):
                self.status(f"{fname} is not in this project any more"); return
            here = (self.cur_dir, self.file) if self.graph is not None else None
            if self.graph is not None:
                self.save()
            if not self.open(fname, sub=bool(sub)):
                return                                    # said by open; the trail left as it was
            if sub and here:
                self.stack.append(here)
            elif not sub:
                self.stack.clear()
            self._trail()
        self.app.show_pane("graph")
        if nid is None:
            if self.graph and self.graph.nodes:
                self._frame_view(list(self.graph.nodes))
            return
        if not self.graph or nid not in self.graph.nodes:
            self.status(f"#{nid} is not in {fname} any more"); return
        self.set_selection([nid])
        self._frame_view([nid], most=1.0)
