"""The graph as a thing to keep and hand on - a mixin of graph_ui's GraphPanel: snapshots (the whole graph's
settings as named states, and a morph between two) and bundles (the graph with every sub-graph and user node it
reaches, as one file for another project)."""
import json
import os

import dearpygui.dearpygui as dpg

from native import graph as G
from native import weight


class GraphFiles:
    # --- snapshots: the whole graph's settings as named states, and a morph between two ----
    def snapshot_save(self, name):
        name = (name or "").strip()
        if not self.graph or not name:
            self.status("a name is needed for the snapshot"); return
        self._sync_pos()
        self.graph.take_snapshot(name)
        self.save()
        self.refresh_snapshots()
        scenes = any(n["type"] == "Scenes" for n in self.graph.nodes.values())
        if scenes:
            self.touch()                                 # the Scenes node's table is made when the graph compiles
        self.status(f"snapshot {name!r}: {len(self.graph.nodes)} node(s) kept"
                    + (" - build to put it in the Scenes node's table" if scenes else ""))

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
                self._set_param_widget(nid, k, v)                   # its fields: the node's, and in the properties
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
        from native.graph_ui import DIM
        if not dpg.does_item_exist("snap_rows"):
            return
        dpg.delete_item("snap_rows", children_only=True)
        names = sorted(self.graph.snapshots) if self.graph else []
        for nm in names:
            with dpg.group(horizontal=True, parent="snap_rows"):
                dpg.add_button(label=nm, small=True, user_data=nm, callback=lambda s_, a_, u: self.snapshot_apply(u))
                dpg.add_button(label="update", small=True, user_data=nm, callback=lambda s_, a_, u: self.snapshot_save(u))
                dpg.add_button(label="x", small=True, user_data=nm, callback=lambda s_, a_, u: self.snapshot_delete(u))
                weight.danger(dpg.last_item())
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
        why = _bundle_problem(b)
        if why:
            # checked whole before anything is written: a sub-graph named "..\..\x" was written outside the
            # project, and a bundle wrong part way left the files written before it
            self.status(f"not imported: {why}", "error"); return
        from native.project import write_atomic
        udir = os.path.join(self.app.project.path, "nodes")
        for name, d in b.get("nodes", {}).items():
            os.makedirs(udir, exist_ok=True)
            p = os.path.join(udir, G._ident(name) + ".json")
            if not os.path.exists(p):
                write_atomic(p, json.dumps(d, indent=1))
        for ident, d in b.get("subgraphs", {}).items():
            p = os.path.join(self.sub_dir, ident + ".json")
            if not os.path.exists(p):
                os.makedirs(self.sub_dir, exist_ok=True)
                write_atomic(p, json.dumps(d, indent=1))
            # an existing one of the same name is kept: the import uses it
        g = b["graph"]
        name = g.get("name") or os.path.splitext(os.path.basename(path))[0]
        fname = G._ident(name) + ".json"
        n = 2
        while os.path.exists(os.path.join(self.dir, fname)):
            fname = f"{G._ident(name)}_{n}.json"; n += 1
        write_atomic(os.path.join(self.dir, fname), json.dumps(g, indent=1))
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


def _bundle_problem(b):
    """What makes a bundle unsafe or unreadable to import, in words - None when it is fine. Its sub-graphs'
    names become file names, and its graph references them by those names: they must be plain names."""
    def graph_ok(g):
        return isinstance(g, dict) and isinstance(g.get("nodes", []), list) and isinstance(g.get("links", []), list)
    if not graph_ok(b.get("graph")):
        return "its graph is not one"
    if not isinstance(b.get("nodes", {}), dict) or not isinstance(b.get("subgraphs", {}), dict):
        return "its nodes or sub-graphs are not lists of them"
    for ident, d in b.get("subgraphs", {}).items():
        if not isinstance(ident, str) or not ident or G._ident(ident) != ident.lower():    # no folder, no dots
            return f"a sub-graph's name, {ident!r}, is not a plain name"
        if not graph_ok(d):
            return f"sub-graph {ident!r} is not a graph"
    for name, d in b.get("nodes", {}).items():
        if not isinstance(d, dict):
            return f"node {name!r} is not a node definition"
    return None
