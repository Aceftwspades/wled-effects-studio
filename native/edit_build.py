"""The code pane's build - a mixin of App (app.py): the effect saved and compiled on a worker (edit_build), the
result taken on the main loop (poll_build) - the errors shown, at their lines and on the nodes that wrote them, or
the engine swapped for the new library with the effect, its settings and its clock kept (_build_done)."""
import os
import queue
import threading

import dearpygui.dearpygui as dpg

from native import messages


class EditBuild:
    def edit_build(self):
        """Save, then compile on a worker; the result is applied on the main
        thread by poll_build(), because reloading the engine while a frame is
        being drawn from it is not something to do from another thread."""
        if self.building:
            # asked again while one runs (a project switch, an import toggled, Live): kept, and run when it is
            # done - it was dropped, and the running build's library (another project's) was loaded as the result
            self._build_again = True
            return
        self.edit_save()
        self.building = True
        self.build_msg = "compiling..."
        dpg.set_value("edit_status", self.build_msg)
        dpg.delete_item("edit_errors", children_only=True)

        # what to build, read here on the main thread: the worker read self.project and edit_file as it ran,
        # and a project switched meanwhile built the new project's files under the old one's build
        files = [self.project.effect_path(f) for f in self.project.build_files(self.edit_file)]

        def work():
            import build as B
            from native.toolchain import build_engine
            import contextlib, io as _io
            buf = _io.StringIO()
            try:
                with contextlib.redirect_stdout(buf):
                    srcs = B.engine_sources(files)
                inc = B.include_dirs()
                rep = build_engine(srcs, inc, log=lambda *a: None)
            except Exception as e:
                rep = None
                self.build_q.put(("exception", str(e)))
                return
            self.build_q.put(("report", rep))
        threading.Thread(target=work, daemon=True).start()

    def poll_build(self):
        try:
            kind, payload = self.build_q.get_nowait()
        except queue.Empty:
            return
        self.building = False
        try:
            self._build_done(kind, payload)
        finally:
            if self.__dict__.pop("_build_again", False):
                self.edit_build()                        # one asked for while this one ran: now, with what is there now

    def _build_done(self, kind, payload):
        """A build's result on the main thread: the errors shown, or the engine swapped for the new library."""
        if kind == "exception":
            dpg.set_value("edit_status", f"build failed: {payload}")
            messages.post(self, f"build failed: {payload}", "error", key="build:")
            return
        rep = payload
        if not rep.ok:
            # Errors first; warnings only from the project's own files - a
            # warning inside a shared header is not the user's to fix.
            mine = set(self.project.effect_files())
            errs = [e for e in rep.error_lines()
                    if e[2].startswith("error") or os.path.basename(e[0]) in mine]
            errs.sort(key=lambda e: 0 if e[2].startswith("error") else 1)
            dpg.set_value("edit_status", f"{len(errs)} problem(s)")
            # a graph's own C++: an error on a line a node wrote is that node's (an Expression's
            # typed C++, most often) - it goes to the node, and the message points there
            placed = self.gp.build_failed(self.edit_file, errs) if self.edit_file else {}

            def node_of(path, line):
                nid = placed.get((os.path.basename(path), int(line)))
                return (nid, f"{self.gp.graph.nodes[nid]['type']} #{nid}") if nid is not None and self.gp.graph else (None, "")
            first = errs[0] if errs else None
            nid0, words0 = node_of(first[0], first[1]) if first else (None, "")
            if nid0 is not None:
                messages.post(self, f"{self.edit_file}: {len(errs)} problem(s) in the build - {words0}: {first[2]}",
                              "error", key="build:", node=self.gp.where(nid0))
            else:
                messages.post(self, f"{self.edit_file}: {len(errs)} problem(s) in the build" + (f" - {os.path.basename(first[0])}:{first[1]} {first[2]}" if first else ""),
                              "error", key="build:", code=(os.path.basename(first[0]), int(first[1])) if first else None)
            if self.code_ed is not None:
                self.code_ed.err_lines = {int(line) - 1 for path, line, msg in errs
                                          if os.path.basename(path) == self.edit_file and msg.startswith("error")}
                self.code_ed._dirty = True
            for path, line, msg in errs[:30]:
                fn = os.path.basename(path)
                mine_file = fn == self.edit_file
                nid, words = node_of(path, line)
                if nid is not None:                              # a node's line: the row names it and goes to it
                    row = self._error_row(f"{fn}:{line}  {words}: {msg}", self.gp.where(nid),
                                          lambda s, a, u: messages.goto(self, {"node": u}))
                else:
                    row = self._error_row(f"{fn}:{line}  {msg}", int(line) if mine_file else None,
                                          lambda s, a, u: self.goto_line(u) if u else None)
                with dpg.theme() as th:
                    with dpg.theme_component(dpg.mvSelectable):
                        dpg.add_theme_color(dpg.mvThemeCol_Text,
                                            (235, 120, 110) if msg.startswith("error") else (200, 190, 120))
                dpg.bind_item_theme(row, th)
            if not errs and rep.link_output:
                dpg.add_text(rep.link_output[-600:], parent="edit_errors", color=(235, 120, 110), wrap=0)
            return
        # success: swap the engine, keep everything the user had
        want = self.project.effect_title(self.edit_file) if self.edit_file else self.project.selected
        sub = self.gp.standin_on()                       # the edit shown at once as a script (graph_ui.standin)
        clock = self.eng.clock()
        self.eng.reload(rep.library)
        self._ab_reloaded(rep.library)
        dpg.configure_item("fx_combo", items=self.eng.names)
        if not (sub and self.gp.standin_stays(want, self.eng.names) and self.gp.standin_reload(clock)):
            if want in self.eng.names:
                self.eng.select(self.eng.names.index(want))
            if sub:
                self.eng.set_clock(clock)                # the build takes the stand-in's place at the same moment
            self.gp.standin_done(sub)
            dpg.set_value("fx_combo", self.eng.names[self.eng.idx])
            self.rebuild_params()
            self.sync_palette_combo()
        dpg.set_value("edit_status", f"loaded {os.path.basename(rep.library)}  ({self.eng.count} effects)")
        messages.clear(self, "build:")                       # it builds: the build's problem is gone
        if self.edit_file:
            self.gp.build_ok(self.edit_file)                 # and the nodes it was on are clear
        messages.post(self, f"built: {self.eng.count} effects")
