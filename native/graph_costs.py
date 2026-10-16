"""What each node of the graph costs - a mixin of graph_ui's GraphPanel: a profiling build run in an engine of its
own for a moment (native/costs.py), and each node's share drawn on it."""
import dearpygui.dearpygui as dpg

from native import graph as G
from native import typeface


class GraphCosts:
    # --- what each node costs (native/costs.py) ------------------------------------------------
    def measure_costs(self):
        """A profiling build of the graph run in an engine of its own for a moment: each node then
        says its share of the frame and its time on the device (the speed factor), until the graph
        is compiled again. The app's engine is not touched; the build and the run are on a worker,
        holding the app's build flag so that two builds never share the generated sources."""
        if not self.graph:
            self.status("open a graph first"); return
        if getattr(self, "_cost_job", None) or self.app.building:
            self.status("a build is running - measure when it is done"); return
        title = self.graph.name
        try:
            src = self.graph.compile(profile=True)
            slots = list(self.graph.prof_nodes)
            fsrc = self.graph.compile(title=title + " frame", profile="frame")   # its twin timing the frame alone
        except G.GraphError as e:
            self.status(f"{self.file} does not compile: {e}", "error"); return
        if len(slots) <= 2:
            self.status("nothing to measure: the graph has no nodes that compute"); return
        from native import scratch
        paths = []
        for suffix, text in (("", src), ("_frame", fsrc)):
            paths.append(scratch.path("profile_" + G._ident(title) + suffix + ".cpp"))
            with open(paths[-1], "w", encoding="utf-8", newline="\n") as f:
                f.write(text)
        app = self.app
        job = {"file": self._key(), "result": None}
        geometry, colors = app.project.geometry, tuple(app.seg_cols)
        fx, pal, pal_source = dict(app.eng.fx), app.eng.pal, app.eng.pal_source

        def work():
            try:
                import build as B
                from native.toolchain import build_engine
                from native import costs
                try:
                    rep = build_engine(B.engine_sources(paths, log=lambda *a: None), B.include_dirs(),
                                       log=lambda *a: None, point_latest=False)
                finally:
                    app.building = False
                if not rep.ok:
                    errs = [e for e in rep.error_lines() if e[2].startswith("error")]
                    job["result"] = ("error", "the profiling build failed" + (f": {errs[0][2]}" if errs else ""))
                    return
                job["result"] = ("ok", costs.run(rep.library, title, slots, geometry, colors, fx, pal, pal_source,
                                                 frame_title=title + " frame"))
            except Exception as e:
                job["result"] = ("error", f"could not measure: {e}")
            finally:
                app.building = False                      # an import failing before the build left it set for good:
                                                          # every build after was refused as "a build is running"
        self._cost_job = job
        app.building = True
        import threading
        threading.Thread(target=work, daemon=True).start()
        self.status("measuring what each node costs: a profiling build, then a moment's run...")

    def _poll_cost_job(self):
        job = getattr(self, "_cost_job", None)
        if not job or job["result"] is None:
            return
        self._cost_job = None
        kind, res = job["result"]
        if kind != "ok":
            self.status(res, "error"); return
        if job["file"] != self._key() or not self.graph:
            return                                       # another graph since: this one's numbers are not it
        self._costs = dict(res, file=job["file"])
        factor = float(self.app.prefs.get("device_factor", 60.0))
        top = sorted(((nid, v) for nid, v in res["nodes"].items() if nid in self.graph.nodes), key=lambda kv: -kv[1][0])[:3]
        words = ", ".join(f"{self.graph.nodes[nid]['type']} #{nid} {s * 100:.0f}%" for nid, (s, ms) in top)
        self.status(f"the effect's own work: {res['frame_ms']:.2f} ms a frame here, ~{res['frame_ms'] * factor:.1f} ms on the device "
                    f"(x{factor:.0f}) - {words}; the rest (each pixel's coordinates, the drawing) {res['rest'] * 100:.0f}%",
                    node=self.where(top[0][0]) if top else None)

    def _poll_costs_draw(self):
        """Each measured node's share of the frame and its time on the device, over its top-right
        corner, with a bar as long as the share of the node's width; what costs a quarter or more
        in the warning colour. Kept off what covers it, as the readouts are."""
        for it in getattr(self, "_cost_items", []):
            if dpg.does_item_exist(it):
                dpg.delete_item(it)
        self._cost_items = []
        c = getattr(self, "_costs", None)
        if not c or not self.graph or c.get("file") != self._key():
            return
        if self.app.layout != "graph" or not self.app.ui or self.zoom < 0.5 or self.overview():
            return
        if dpg.is_item_shown("graph_menu") or dpg.is_item_shown("graph_ctx") or self._overlay_paused():
            return                                       # (moving: the costs would trail their nodes)
        pane = self.app._screen_rect("graph_win")
        if not pane:
            return
        if not dpg.does_item_exist("wire_labels"):
            dpg.add_viewport_drawlist(front=True, tag="wire_labels")
        eh = dpg.get_item_rect_size("node_editor")[1]
        x0, y0, x1, y1 = pane[0] + 9, pane[3] - 9 - eh, pane[2] - 9, pane[3] - 9
        cover = getattr(self, "_cover_now", None) or self._cover()
        factor = float(self.app.prefs.get("device_factor", 60.0))
        size = max(9, int(10 * self.zoom))
        P = self.pal()
        for nid, (share, ms) in c["nodes"].items():
            tag = f"gnode_{nid}"
            if nid not in self.graph.nodes or not dpg.does_item_exist(tag):
                continue
            st = dpg.get_item_state(tag)
            (nx0, ny0), (nx1, _) = st.get("rect_min", (0, 0)), st.get("rect_max", (0, 0))
            if nx1 <= nx0:
                continue
            text = f"{share * 100:.0f}%  ~{ms * factor:.1f} ms" if share >= 0.005 else "<1%"
            w = typeface.measure(text, "mono", size)
            x, y = nx1 - w, ny0 - size - 6
            if x < x0 or x + w > x1 or y < y0 or ny0 > y1:
                continue
            if self._covered((min(x, nx0), y, nx1, ny0), cover, nid):
                continue
            col = P["cost_hot"] if share >= 0.25 else P["live"]
            self._cost_items.append(self._draw_text((x, y), text, parent="wire_labels", color=col, size=size))
            bw = max(1.0, (nx1 - nx0) * min(1.0, share))
            self._cost_items.append(dpg.draw_rectangle((nx1 - bw, ny0 - 4), (nx1, ny0 - 2), parent="wire_labels",
                                                       color=(0, 0, 0, 0), fill=col))
