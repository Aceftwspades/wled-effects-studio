"""Projects - a mixin of app.py's App: the project's features, opening, making and switching projects, and their list."""
import os
import dearpygui.dearpygui as dpg
from native import messages
from native.project import Project, list_projects, project_path, remember_project, PROJECTS
from native import chrome, device_ui, shape_ui, tasks
from native import vj_state
from native import pads_state


class AppProjects:
    # --- projects ---------------------------------------------------------------------
    # One folder per project under studio/projects/ (or anywhere, by path).
    # Switching swaps the project object, applies its geometry, re-lists its
    # effects and graphs, and rebuilds the engine for its effects list.
    def set_feature(self, key, value):
        """The flash dialog's picker: a feature on or off for this project;
        the graph's nodes that lean on it follow."""
        from native import flash
        f = flash.features_of(self.project)
        f[key] = value
        self.project.options["features"] = f
        self.project.save()
        self.gp.refresh_features()
        chrome.refresh_usermods(self)

    def set_usermod(self, name, on):
        """The manager's checkbox: a usermod built or left out for this
        project, whatever the environment says."""
        from native import flash
        f = flash.features_of(self.project)
        f["usermods"][name] = bool(on)
        self.project.options["features"] = f
        self.project.save()
        chrome.refresh_usermods(self)

    def add_usermod(self, name):
        """A usermod from this tree onto the project's list, on."""
        from native import flash
        if name not in flash.usermod_dirs():
            self.gp.status(f"no usermods/{name} in this tree"); return
        self.set_usermod(name, True)
        self.gp.status(f"{name} added to the project's usermods")

    def remove_usermod(self, name):
        """Off the project's list (the folder stays in the tree); one the
        environment builds goes back to the environment's say."""
        from native import flash
        f = flash.features_of(self.project)
        f["usermods"].pop(name, None)
        self.project.options["features"] = f
        self.project.save()
        chrome.refresh_usermods(self)
        self.gp.status(f"{name} removed from the project's list")

    def import_usermod(self, path):
        """A folder or a zip from anywhere, into the tree and onto the list."""
        from native import flash
        try:
            name = flash.import_usermod(path)
        except Exception as e:
            self.gp.status(f"could not import: {e}")
            if dpg.does_item_exist("um_status"):
                dpg.set_value("um_status", f"could not import: {e}")
            return
        self.set_usermod(name, True)
        self.gp.status(f"imported usermods/{name}")

    def report_project_load(self):
        """A project.json that did not read, said where it cannot be missed:
        a problem in the messages and a dialog. The project then runs on
        the defaults, its old settings kept in project.json.bad-<time>."""
        err = getattr(self.project, "load_error", None)
        messages.clear(self, "project:load")
        if err:
            print("project:", err)
            messages.post(self, err, "error", key="project:load")
            chrome.confirm(self, "The project's settings did not read", err, [("OK", None)])

    def _leave_project(self):
        """The project about to be closed left whole: the pads and controls held let go (what a hold changed put
        back), the desk a show's VJ steps took over put back, and what waits to be saved (a VJ knob, a modulator
        turned, a pad's typed label, the mixer's fader) saved into it - not into the next one."""
        from native import modulate, pads, pads_ui, vj, vj_ui
        try:
            pads.let_go(self)
        except Exception:
            import traceback
            traceback.print_exc()
        if vj_state.of(self).by_show:
            vj.restore_desk(self)
            self.project.save()                          # the desk, not the step's decks, is what it keeps
        vj_ui._flush_save(self, now=True)
        modulate._flush(self, 0.0, force=True)
        pads_ui._flush(self)
        if getattr(self, "_mixer_save_at", None) is not None:
            self._mixer_save_at = None
            self.project.save()

    def _enter_project(self):
        """Nothing of the last project's run state reaching the next: its pads' held controls, the phone's holds, a
        learn waiting, a drag; the Modulators dialog shows the new project's."""
        from native import modulate
        P = pads_state.of(self)
        P.forget("rt", "remote", "learn", "drag")
        if P.hw_rt:                                  # the controller's notes held (its lights and output stay)
            P.hw_rt.get("held", {}).clear()
        modulate.reset(self)
        modulate.refresh(self)

    def switch_project(self, path, create=False):
        path = project_path(path)
        if not create and not os.path.isdir(path):
            dpg.set_value("edit_status", f"no project at {path}"); return
        if self.edit_dirty:
            self.edit_save()
        if self.gp.graph:
            self.gp.save()
        self._leave_project()
        self.project = Project(path)
        self._enter_project()
        messages.clear(self, "")                         # the last project's problems are not this one's
        shape_ui.forget(self)                            # nor its shape's undo steps and selection
        self._code_undo, self._code_redo = [], []        # nor the code pane's (they reached the next file opened)
        self.report_project_load()
        if create:
            from native import flash
            self.project.options["features"] = dict(flash.NEW_DEFAULTS)     # no hardware assumed until ticked
        remember_project(path)
        self.edit_file = None
        self.gp.graph = None; self.gp.file = None; self.gp.stack.clear()
        self.apply_geometry(self.project.geometry)
        dpg.set_value("geom_kind", self.project.geometry.kind)
        self.rebuild_geom_fields()
        self.restore_segments()
        dpg.configure_item("edit_file", items=self.project.effect_files()); dpg.set_value("edit_file", "")
        dpg.set_value("code", "")
        self.gp.refresh_lib()
        dpg.configure_item("graph_file", items=self.gp.files()); dpg.set_value("graph_file", "")
        self.gp.rebuild()
        self.refresh_import_buttons()
        self.refresh_project_list()
        self._active_state = None
        device_ui.refresh_devices(self)
        from native import palette_ui
        palette_ui.sync(self); palette_ui.refresh(self)
        from native import vj, vj_ui
        vj.project_changed(self); vj_ui.project_changed(self); vj_ui.refresh(self)
        name = os.path.basename(path)
        dpg.set_value("edit_status", f"project {name}"); self.gp.status(f"project {name}")
        # the engine holds the previous project's drafts: build this one's list
        self.edit_build()

    def send_ledmap(self, sure=False):
        """The ledmap to the device - its wiring changes, so it asks first."""
        host = self.active_host()
        if not host:
            device_ui.show(self, "devices"); self.gp.status("choose a device first"); return
        g = self.project.geometry
        if not sure:
            chrome.confirm(self, "Send the ledmap?",
                           f"The device at {host} will map its LEDs as this project's geometry does ({g.describe()}): "
                           "its picture changes, and a wiring that is not the device's leaves it dark or scrambled until "
                           "the ledmap is removed. Send it?",
                           [("Send", lambda: self.send_ledmap(True), "danger"), ("Cancel", None)])
            return
        from native import tasks

        def done(msg):
            dpg.set_value("edit_status", msg); self.gp.status(msg); device_ui.send_log(self, msg)
        # on a worker, as send_shape's: a device that does not answer held the whole studio for the upload's 5 s
        lm = self.project.geometry.ledmap()           # made here: the worker must not read a geometry being changed
        tasks.run(self, "send:ledmap", f"sending the ledmap to {host}", lambda: self.project.send_ledmap(host, lm), done)

    def send_shape(self, sure=False):
        """The geometry to the device: its ledmap (the wiring), and its
        position table when it is a shape cfx_pos has no rule for."""
        from native import flash
        host = self.active_host()
        if not host:
            device_ui.show(self, "devices"); self.gp.status("choose a device first"); return
        g = self.project.geometry
        if not sure:
            chrome.confirm(self, "Send the shape?",
                           f"The device at {host} gets this project's ledmap ({g.describe()}) and, for a shape, the "
                           "positions table the effects read. Its wiring changes with the ledmap. Send both?",
                           [("Send", lambda: self.send_shape(True), "danger"), ("Cancel", None)])
            return
        lm = g.ledmap()                               # made here, as the worker must not read a geometry being changed

        def work():                                   # on a worker: a device that does not answer froze the studio
            msg = self.project.send_ledmap(host, lm)
            ok, msg2 = flash.send_geometry(host, g)
            return msg + "; " + msg2

        def done(msg):
            dpg.set_value("edit_status", msg); self.gp.status(msg); device_ui.send_log(self, msg)
        tasks.run(self, "send:shape", f"sending the shape to {host}", work, done)

    def new_project(self, name):
        name = (name or "").strip()
        if not name:
            dpg.set_value("edit_status", "type a project name first"); return
        path = project_path(name)
        if os.path.isdir(path):
            self.switch_project(path); return
        self.switch_project(path, create=True)

    def export_project_zip(self):
        """The project as one zip in captures/ - to keep, or to hand over."""
        from native.project import zip_project
        if self.edit_dirty:
            self.edit_save()
        if self.gp.graph:
            self.gp.save()
        self.project.save()
        try:
            path = zip_project(self.project)
        except Exception as e:
            self.gp.status(f"project zip failed: {e}"); return
        msg = f"project zipped: {path} ({os.path.getsize(path) // 1024} KB)"
        dpg.set_value("edit_status", msg); self.gp.status(msg)

    def import_project_zip(self, path, sure=False):
        """A project zip into projects/, opened. Asked first: its effects are C++ that opening it builds and runs
        on this computer (`sure`: asked already)."""
        from native.project import unzip_project
        if not path:
            return
        if not sure:
            from native.graph_files import trust_words
            chrome.confirm(self, "Open this project?", trust_words("project", os.path.basename(path)),
                           [("Open it", lambda: self.import_project_zip(path, True)), ("Cancel", None)])
            return
        try:
            dest = unzip_project(path)
        except Exception as e:
            self.gp.status(f"project import failed: {e}"); return
        self.switch_project(dest)
        self.gp.status(f"project imported: {os.path.basename(dest)}")

    def refresh_project_list(self):
        if dpg.does_item_exist("project_combo"):
            names = list_projects()
            cur = os.path.basename(self.project.path)
            if os.path.dirname(self.project.path) != PROJECTS and cur not in names:
                names.append(self.project.path)
                cur = self.project.path
            dpg.configure_item("project_combo", items=names)
            dpg.set_value("project_combo", cur)
