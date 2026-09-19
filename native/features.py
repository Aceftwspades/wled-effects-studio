"""What the app does beyond running one effect: segments, A/B, the slider
sweep, the scripted runtime and the device, the geometry extras, files from
the desktop. A mixin of App (app.py) - the methods read and write the same
attributes; they live here so app.py stays the window, the loop and the
views. Nothing here is called from outside the app.
"""
import json
import os
import shutil
import threading
import time
import numpy as np
import dearpygui.dearpygui as dpg

from native import chrome, device_ui, devices, live_out
from native.project import save_prefs
from native.engine import Engine
from native.geometry import Geometry
from native.dropfiles import classify


class Features:
    def on_geom_wiring(self, sender, val):
        """A panel option on the cube: the wiring changes, the picture does not."""
        key = dpg.get_item_user_data(sender)
        g = self.project.geometry
        params = dict(g.params); params[key] = bool(val)
        if g.kind == "cube" and not params.get("faces"):
            params["faces"] = "N,W,T,E,S,B" if params.get("six") else "N,W,T,E,S"
        self.apply_geometry(Geometry(g.kind, **params))
    def import_ledmap(self, path=None, host=None):
        """A WLED ledmap, from a file or fetched from the device, becomes the
        geometry: a matrix with its gaps and wiring, or a strip."""
        import json
        try:
            if host:
                import urllib.request
                host = host.strip().rstrip("/")
                if not host.startswith("http"):
                    host = "http://" + host
                with urllib.request.urlopen(host + "/ledmap.json", timeout=5) as r:
                    d = json.loads(r.read().decode("utf-8", "replace"))
                source = host + "/ledmap.json"
            else:
                d = json.load(open(path, encoding="utf-8"))
                source = os.path.basename(path)
            g = Geometry.from_ledmap(d, source)
        except Exception as e:
            msg = f"could not read the ledmap: {e}"
            dpg.set_value("geom_desc", msg); self.gp.status(msg); return
        self.apply_geometry(g)
        dpg.set_value("geom_kind", g.kind)
        self.rebuild_geom_fields()
        self.gp.status(f"geometry from {source}: {g.describe()}")
    # --- files dropped on the window -----------------------------------------
    def poll_drops(self):
        drop = getattr(self, "drops", None)
        if not drop:
            return
        for path in drop.take():
            self.take_file(path)
    def check_code_requirements(self, text):
        """A C++ effect's needs, by the helpers it calls, against the
        project's features."""
        from native import flash
        missing = flash.missing_features(self.project, flash.requirements_of_code(text))
        if not missing:
            return
        what = ", ".join(flash.DEPENDENCIES[k]["label"] for k in sorted(missing))
        chrome.confirm(self, "This effect needs more than the project has",
                       f"This effect calls on {what}, which this project's features leave out (Flash > Features). "
                       "Turn the feature on for this project?",
                       [("Turn on", lambda: [self.set_feature(k, "stock" if k == "audio" else True) for k in sorted(missing)]),
                        ("Leave as is", None)])

    def take_file(self, path):
        """A file from the desktop: a graph or bundle opens in the graph pane,
        a .cpp becomes a code effect, an image an Image node in the graph,
        an XYZ file or a ledmap the geometry, a WAV the audio."""
        kind = classify(path)
        name = os.path.basename(path)
        if kind == "graph":
            self.gp.import_bundle(path)
            self.show_layout("graph")
        elif kind == "code":
            fname = os.path.basename(path)
            if not fname.endswith(".cpp"):
                fname += ".cpp"
            n = 2
            stem = fname[:-4]
            while fname in self.project.effect_files():
                fname = f"{stem}_{n}.cpp"; n += 1
            text = open(path, encoding="utf-8", errors="replace").read()
            self.project.write_effect(fname, text)
            self.open_code(fname)
            self.check_code_requirements(text)
        elif kind == "image":
            adir = os.path.join(self.project.path, "assets")
            os.makedirs(adir, exist_ok=True)
            dst = os.path.join(adir, name)
            if os.path.abspath(dst) != os.path.abspath(path):
                shutil.copyfile(path, dst)
            if not self.gp.graph:
                self.gp.status(f"{name} copied to assets/ - open a graph to place it"); return
            self.show_layout("graph")
            nid = self.gp.add_node("Image")
            if nid is not None:
                self.gp.graph.nodes[nid]["params"]["file"] = "assets/" + name
                self.gp.rebuild()
            self.gp.status(f"{name} as an Image node")
        elif kind == "xyz":
            self.on_xyz_file(None, {"file_path_name": path})
        elif kind == "ledmap":
            self.import_ledmap(path=path)
        elif kind == "wav":
            self.start_file_audio(path)
        else:
            self.gp.status(f"{name}: not a graph, .cpp, image, XYZ, ledmap or WAV")
            return
        self.gp.status(f"{name}: {kind}")
    # --- segments ----------------------------------------------------------------
    def seg_labels(self):
        out = []
        for k in range(self.eng.seg_count()):
            x0, y0, x1, y1, op, fx, bm = self.eng.seg_get(k)
            name = self.eng.names[fx] if 0 <= fx < len(self.eng.names) else "?"
            out.append(f"{k}: {x0},{y0} - {x1},{y1}  {name}")
        return out
    def rebuild_seg_fields(self):
        if not dpg.does_item_exist("seg_fields"):
            return
        labels = self.seg_labels()
        dpg.configure_item("seg_combo", items=labels)
        dpg.set_value("seg_combo", labels[self.eng.seg] if self.eng.seg < len(labels) else "")
        dpg.delete_item("seg_fields", children_only=True)
        if self.eng.seg_count() < 2:
            dpg.add_text("one segment, the whole strip - + adds another", parent="seg_fields", color=(139, 147, 163), wrap=0)
            return
        x0, y0, x1, y1, op, fx, bm = self.eng.seg_get(self.eng.seg)
        for row in ((("x0", x0), ("y0", y0)), (("x1", x1), ("y1", y1))):
            with dpg.group(horizontal=True, parent="seg_fields"):
                for key, val in row:
                    dpg.add_input_int(label=key, width=60, default_value=val, user_data=key, on_enter=True, step=0,
                                      callback=self.on_seg_field)
        dpg.add_slider_int(label="opacity", parent="seg_fields", width=200, min_value=0, max_value=255, default_value=op,
                           callback=lambda s, v: self.on_seg_field(s, v, "opacity"))
        # WLED's per-segment blend mode ("bm"): how this segment lands on the ones under it
        modes = self.eng.BLEND_MODES
        dpg.add_combo(modes, label="blend mode", parent="seg_fields", width=200, default_value=modes[bm if bm < len(modes) else 0],
                      callback=lambda s, v: self.on_seg_blend(modes.index(v)))
    def on_seg_blend(self, mode):
        self.eng.seg_blend(self.eng.seg, mode)
        self.save_segments()
    def on_seg_field(self, sender, val, key=None):
        key = key or dpg.get_item_user_data(sender)
        k = self.eng.seg
        x0, y0, x1, y1, op, fx, bm = self.eng.seg_get(k)
        cur = {"x0": x0, "y0": y0, "x1": x1, "y1": y1, "opacity": op}
        cur[key] = int(val)
        self.eng.seg_config(k, cur["x0"], cur["y0"], cur["x1"], cur["y1"], cur["opacity"])
        self.save_segments()
        self.rebuild_seg_fields()
    def seg_pick(self, label):
        try:
            k = int(str(label).split(":")[0])
        except ValueError:
            return
        self.eng.seg_select(k)
        dpg.set_value("fx_combo", self.eng.names[self.eng.idx])
        self.rebuild_params()
        self.sync_palette_combo()
        self.rebuild_seg_fields()
    def seg_add(self):
        n = self.eng.seg_count()
        if n >= 8:
            self.gp.status("eight segments is the most"); return
        w, h = self.eng.cols, self.eng.rows
        # the new one takes the right half of the strip (or the bottom, on a strip)
        if w >= h:
            self.eng.seg_config(n, w // 2, 0, w, h, 255)
        else:
            self.eng.seg_config(n, 0, h // 2, w, h, 255)
        self.eng.seg_select(n)
        self.save_segments()
        dpg.set_value("fx_combo", self.eng.names[self.eng.idx])
        self.rebuild_params(); self.sync_palette_combo(); self.rebuild_seg_fields()
    def seg_remove(self):
        n = self.eng.seg_count()
        if n <= 1:
            return
        self.eng.seg_truncate(n - 1)
        self.save_segments()
        dpg.set_value("fx_combo", self.eng.names[self.eng.idx])
        self.rebuild_params(); self.sync_palette_combo(); self.rebuild_seg_fields()
    def save_segments(self):
        self.project.options["segments"] = self.eng.segments() if self.eng.seg_count() > 1 else []
        self.project.save()
    def restore_segments(self):
        segs = self.project.options.get("segments") or []
        if len(segs) > 1:
            try:
                self.eng.load_segments(segs)
            except Exception as e:
                self.gp.status(f"segments not restored: {e}")
        self.rebuild_seg_fields()
    def _draw_segments(self):
        """The segments' bounds over the net, the current one in the accent,
        when there is more than one."""
        if not dpg.does_item_exist("seg_overlay"):
            dpg.add_viewport_drawlist(front=True, tag="seg_overlay")
        for it in getattr(self, "_seg_items", []):
            if dpg.does_item_exist(it):
                dpg.delete_item(it)
        self._seg_items = []
        if self.eng.seg_count() < 2 or not (self.ui and self.layout in ("both", "net") and dpg.does_item_exist("net_img")):
            return
        st = dpg.get_item_state("net_img")
        if "rect_min" not in st:
            return
        ox, oy = st["rect_min"]
        sc = self.net_scale
        ry = self.net_image().shape[0] / max(1, self.eng.rows) * sc
        for k in range(self.eng.seg_count()):
            x0, y0, x1, y1, op, fx, bm = self.eng.seg_get(k)
            col = (90, 169, 230, 255) if k == self.eng.seg else (255, 184, 70, 200)
            self._seg_items.append(dpg.draw_rectangle((ox + x0 * sc, oy + y0 * ry), (ox + x1 * sc, oy + y1 * ry),
                                                      parent="seg_overlay", color=col, thickness=2))
            self._seg_items.append(dpg.draw_text((ox + x0 * sc + 4, oy + y0 * ry + 2), str(k), parent="seg_overlay",
                                                 color=col, size=14))
    # --- the scripted runtime ---------------------------------------------------------
    def compile_current_script(self):
        """The current graph as bytecode, or None with the reason in the status."""
        from native.script import compile_script, ScriptError
        if not self.gp.graph:
            self.gp.status("open a graph first"); return None
        try:
            self.gp.save()
            return compile_script(self.gp.graph)         # flattens sub-graphs itself
        except Exception as e:
            self.gp.status(f"not scriptable - {e}"); return None
    def preview_script(self):
        """Run the current graph as a script in the sim's Studio Script
        effect - what the device will run - with the graph's own settings."""
        from native.script import settings_of
        prog = self.compile_current_script()
        if prog is None:
            return
        si = self.eng.script_effect()
        if si is None:
            self.gp.status("this engine build has no Studio Script effect"); return
        if not self.eng.script(prog):
            self.gp.status("the engine did not take the script"); return
        st = settings_of(self.gp.graph)
        pal = st.pop("pal")
        self.eng.select(si, params=dict(st, pal=pal))
        dpg.set_value("fx_combo", self.eng.names[si])
        self.rebuild_params(); self.sync_palette_combo()
        self.gp.status(f"running as a script: {len(prog)} bytes")
    def send_script(self):
        """The current graph to the active device as /studio.bin, then the
        Studio Script effect selected there with the graph's settings."""
        from native import flash
        from native.script import settings_of
        host = self.active_host()
        if not host:
            device_ui.show(self, "devices"); self.gp.status("choose a device first"); return
        prog = self.compile_current_script()
        if prog is None:
            return
        ok, msg = flash.send_script(host, prog)
        self.gp.status(msg)
        if not ok:
            device_ui.send_log(self, msg); return
        st = settings_of(self.gp.graph)
        params = {k: st[k] for k in ("sx", "ix", "c1", "c2", "c3")}
        params.update({k: bool(st[k]) for k in ("o1", "o2", "o3")})
        pal = self.palette_name_for(st["pal"])
        ok2, msg2 = flash.push_settings(host, "Studio Script", params, pal, self.seg_cols)
        msg = msg + ("; " + msg2 if not ok2 else "; the device is running it")
        self.gp.status(msg); device_ui.send_log(self, msg)
        self.probe_active()
    def push_settings(self):
        """The effect on the cube here, with its sliders, checkboxes, palette
        and colours, becomes the active device's first segment."""
        from native import flash
        host = self.active_host()
        if not host:
            device_ui.show(self, "devices"); self.gp.status("choose a device first"); return
        f = self.eng.fx
        params = {k: f.get(k) for k in ("sx", "ix", "c1", "c2", "c3")}
        params.update({k: bool(f.get(k)) for k in ("o1", "o2", "o3")})
        bm, op = 0, 255
        if self.eng.seg_count() >= 1:
            g = self.eng.seg_get(self.eng.seg); bm, op = g[6], g[4]
        ok, msg = flash.push_settings(host, self.eng.names[self.eng.idx], params,
                                      self.palette_name_for(self.eng.pal), self.seg_cols, seg_id=self.eng.seg, blend=bm, opacity=op,
                                      six=self.eng.six if self.project.geometry.kind == "cube" else None)
        dpg.set_value("edit_status", msg); self.gp.status(msg); device_ui.send_log(self, msg)
        self.probe_active()

    # --- live output: the sim's frames to the device, and the wiring test ------------
    def stream_start(self, host=None, fps=30):
        """The sim's frames to the device over DDP as they are drawn."""
        host = devices.clean_host(host or self.active_host())
        if not host:
            device_ui.show(self, "devices"); self.gp.status("choose a device first"); return False
        self.stream_stop()
        self.ddp = live_out.DdpOut(host)
        self._ddp_fps = max(1.0, float(fps))
        self._ddp_next = 0.0
        self.gp.status(f"streaming to {host} over DDP at {int(fps)} fps - the device shows the sim while this runs")
        device_ui.refresh_live(self)
        return True

    def stream_stop(self):
        d = getattr(self, "ddp", None)
        if d is not None:
            d.close(); self.ddp = None
            self.gp.status(f"stream stopped after {d.frames} frames; the device goes back to its effect in a couple of seconds")
            device_ui.refresh_live(self)

    def poll_stream(self):
        """After each draw: the wiring test's pattern into the engine's
        buffer (paused, so it stays), then the frame to the device."""
        wt = getattr(self, "wiring", None)
        if wt is not None and self.playing:
            self.wiring_stop(); wt = None                  # play pressed: the effect takes the buffer back
            if dpg.does_item_exist("wt_mode"):
                dpg.set_value("wt_mode", "off")
        if wt is not None:
            now = time.perf_counter()
            dt = min(0.25, now - getattr(self, "_wt_last", now)); self._wt_last = now
            cols = wt.frame(dt)
            px = self.eng.pixels().reshape(-1)
            px[:] = 0
            phys = np.asarray(self.project.geometry.phys, int)
            k = min(len(phys), len(cols))
            px[phys[:k]] = (cols[:k, 0].astype(np.uint32) << 16) | (cols[:k, 1].astype(np.uint32) << 8) | cols[:k, 2].astype(np.uint32)
            if dpg.does_item_exist("wt_status"):
                dpg.set_value("wt_status", wt.describe())
        d = getattr(self, "ddp", None)
        if d is None:
            return
        now = time.perf_counter()
        if now < self._ddp_next:
            return
        self._ddp_next = now + 1.0 / self._ddp_fps
        d.send(live_out.frame_bytes(self.eng.rgb(), self.project.geometry.phys))
        if dpg.does_item_exist("live_status") and d.frames % 15 == 0:
            dpg.set_value("live_status", f"{d.frames} frames, {d.bytes // 1024} KB sent" + (f"; {d.errors} send errors: {d.last_error}" if d.errors else ""))

    def wiring_start(self, mode="chase"):
        """The wiring test: playback pauses and the pattern takes the buffer."""
        g = self.project.geometry
        owner = getattr(g, "owner", None) if g.kind == "shape" else None
        names = [p.get("name", p["kind"]) for p in (g.params.get("parts") or [])] if g.kind == "shape" else []
        wt = getattr(self, "wiring", None)
        if wt is None or wt.n != g.count:
            wt = live_out.WiringTest(g.count, owner, names)
            self._wt_was_playing = self.playing
        wt.mode = mode
        self.wiring = wt
        self.playing = False
        if dpg.does_item_exist("wt_mode"):
            dpg.set_value("wt_mode", mode)
        self._wt_last = time.perf_counter()
        self.gp.status(f"wiring test: {mode} - the sim shows it, and the device when streaming")

    def wiring_stop(self):
        if getattr(self, "wiring", None) is not None:
            self.wiring = None
            self.playing = bool(getattr(self, "_wt_was_playing", True))
            self.gp.status("wiring test off")

    # --- the devices: the list, the active one, scans and probes ---------------------
    # The list is the app's (prefs["devices"]: a network is not a project's);
    # the ACTIVE device - where every send and the flash go - is the
    # project's `device` option, as the single address field was before.
    @property
    def devices(self):
        return self.prefs.setdefault("devices", [])

    def active_host(self):
        return devices.clean_host(self.project.options.get("device", ""))

    def active_device(self):
        host = self.active_host()
        return next((d for d in self.devices if d["host"] == host), None)

    def set_active_device(self, host):
        host = devices.clean_host(host)
        self.project.options["device"] = host
        self.project.save()
        self._active_state = None
        device_ui.refresh_devices(self)
        self.gp.status(f"active device: {host}" if host else "no active device")
        if host:
            self.probe_active()

    def _merge_device(self, d):
        """A probed device into the list (by host), keeping the name a user gave it."""
        for i, old in enumerate(self.devices):
            if old["host"] == d["host"]:
                self.devices[i] = dict(old, **d)
                break
        else:
            self.devices.append(d)
        save_prefs(self.prefs)

    def add_device(self, host):
        """An address typed in: asked what it is on a worker, then listed;
        the first device becomes the active one."""
        host = devices.clean_host(host)
        if not host:
            return
        if dpg.does_item_exist("dev_add_host"):
            dpg.set_value("dev_add_host", "")
        if not any(d["host"] == host for d in self.devices):
            self._merge_device({"host": host, "name": host, "reachable": True})
        if not self.active_host():
            self.set_active_device(host)
        self.refresh_devices_info(only=host)
        device_ui.refresh_devices(self)

    def remove_device(self, host):
        self.prefs["devices"] = [d for d in self.devices if d["host"] != host]
        save_prefs(self.prefs)
        if self.active_host() == host:
            self.set_active_device("")
        device_ui.refresh_devices(self)

    def scan_devices(self, mode="all"):
        """mDNS, the known devices' node lists and a sweep of the subnet,
        on a worker; the finds arrive through poll_devices."""
        if getattr(self, "_scan", None) and not self._scan.done:
            return
        self._scan = devices.Scan(mode, known_hosts=[d["host"] for d in self.devices])
        self._scan.start()
        if dpg.does_item_exist("dev_scan"):
            dpg.configure_item("dev_scan", enabled=False); dpg.configure_item("dev_scan_stop", enabled=True)
            dpg.set_value("dev_status", "scanning...")
        self.gp.status("scanning the network for WLED devices...")

    def stop_scan(self):
        if getattr(self, "_scan", None):
            self._scan.cancel()

    def refresh_devices_info(self, only=None):
        """Every listed device (or one) asked again what it is."""
        probes = getattr(self, "_probes", None)
        if probes is None:
            probes = self._probes = []
        for d in self.devices:
            if only and d["host"] != only:
                continue
            p = devices.Probe(d["host"]); p.start(); probes.append(p)

    def probe_active(self):
        host = self.active_host()
        if host:
            self.refresh_devices_info(only=host)

    def open_device_page(self):
        host = self.active_host()
        if host:
            import webbrowser
            webbrowser.open(f"http://{host}/")

    def poll_devices(self):
        """Per frame: a scan's lines and finds, and probes' answers, into
        the list and the frames."""
        scan = getattr(self, "_scan", None)
        changed = False
        if scan is not None:
            n = 0
            while n < 20:
                try:
                    kind, v = scan.q.get_nowait()
                except Exception:
                    break
                n += 1
                if kind == "log":
                    device_ui.dev_log(self, v)
                elif kind == "device":
                    self._merge_device(v); changed = True
                elif kind == "done":
                    if dpg.does_item_exist("dev_scan"):
                        dpg.configure_item("dev_scan", enabled=True); dpg.configure_item("dev_scan_stop", enabled=False)
                    self.gp.status(f"scan done: {v} device(s) answered")
                    if v and not self.active_host():
                        self.set_active_device(self.devices[0]["host"])
                    self._scan = None; changed = True
                    break
        for p in list(getattr(self, "_probes", None) or []):
            while True:
                try:
                    kind, v = p.q.get_nowait()
                except Exception:
                    break
                if kind == "device":
                    if v:
                        self._merge_device(v)
                    else:
                        for d in self.devices:
                            if d["host"] == p.host:
                                d["reachable"] = False
                    changed = True
                elif kind == "state" and p.host == self.active_host():
                    self._active_state = v; changed = True
            if p.done and p.q.empty():
                self._probes.remove(p)
        if changed:
            device_ui.refresh_devices(self)
    # --- A/B: two effects side by side ------------------------------------------
    # The engine is one strip in one DLL, so a second effect needs a second
    # engine: the same library copied under another name (the loader gives
    # one process one instance per FILE). B gets A's geometry, colours and
    # audio each frame; the view splits, the camera is shared.
    def _b_library(self):
        lib = self.eng.library
        self._ab_n += 1
        root, ext = os.path.splitext(lib)
        path = f"{root}_b{self._ab_n}{ext}"
        shutil.copyfile(lib, path)
        return path
    def start_ab(self, name):
        if name not in self.eng.names:
            return
        self._gpu_was = None
        try:
            if self.ab is None:
                self.ab = Engine(self._b_library())
            self._ab_sync()
            self.ab.select(self.ab.names.index(name))
        except Exception as e:
            self.gp.status(f"cannot compare: {e}"); self.ab = None; return
        self.ab_name = name
        self.request_layout()
        self.gp.status(f"A: {self.eng.names[self.eng.idx]}   B: {name}")
    def stop_ab(self):
        self.ab = None
        self.ab_name = None
        self.request_layout()
    def _ab_sync(self):
        """B follows A's geometry, colours and palette source."""
        if not self.ab:
            return
        try:
            self.ab.set_geometry(self.project.geometry)
            self.ab.colors(*self.seg_cols)
            self.ab.pal_source = self.eng.pal_source
            if dpg.does_item_exist("map1d2d"):
                self.ab.set_map1d2d(["strip", "bars", "arcs", "corner"].index(dpg.get_value("map1d2d")))
        except Exception:
            pass
    def _ab_reloaded(self, library):
        """The library was rebuilt: B takes a fresh copy and its effect back."""
        if not self.ab:
            return
        try:
            self.ab.reload(self._b_library())
            self._ab_sync()
            if self.ab_name in self.ab.names:
                self.ab.select(self.ab.names.index(self.ab_name))
        except Exception as e:
            self.gp.status(f"comparison dropped: {e}"); self.ab = None
    # --- the loop ------------------------------------------------------------
    # --- sweep: a slider driven through its range ----------------------------------
    def start_sweep(self, key, secs, loop=True, record=False):
        if key not in self.eng.fx:
            return
        self.sweep = {"key": key, "secs": max(1.0, float(secs)), "t0": time.perf_counter(), "loop": loop,
                      "was": self.eng.fx[key]}
        self.playing = True
        if record:
            self.start_rec(self.sweep["secs"])
        self.gp.status(f"sweeping {key} over {secs:.0f} s" + (", looping" if loop else ""))
    def stop_sweep(self, restore=True):
        if self.sweep and restore:
            self.eng.fx[self.sweep["key"]] = self.sweep["was"]
            self.eng.push(); self.rebuild_params()
        self.sweep = None
    def _poll_sweep(self):
        sw = self.sweep
        if not sw:
            return
        t = (time.perf_counter() - sw["t0"]) / sw["secs"]
        if t >= 1.0 and not sw["loop"]:
            self.stop_sweep(); return
        phase = t % 1.0
        hi = 31 if sw["key"] == "c3" else 255
        v = int(round(hi * (1.0 - abs(2.0 * phase - 1.0))))        # up, then back down
        if v != self.eng.fx.get(sw["key"]):
            self.eng.fx[sw["key"]] = v
            self.eng.push()
            for tag in (f"sld_{sw['key']}", f"inp_{sw['key']}"):
                if dpg.does_item_exist(tag):
                    dpg.set_value(tag, v)
    def _draw_wiring(self):
        """The wiring order as a line through the net's pixels, first LED
        marked, when asked for and the net is on screen."""
        if not dpg.does_item_exist("wiring_overlay"):
            dpg.add_viewport_drawlist(front=True, tag="wiring_overlay")
        for it in self._wiring_items:
            if dpg.does_item_exist(it):
                dpg.delete_item(it)
        self._wiring_items = []
        if not (self.show_wiring and self.ui and self.layout in ("both", "net") and dpg.does_item_exist("net_img")):
            return
        g = self.eng.geom
        if g is None or g.phys is None or len(g.phys) < 2:
            return
        st = dpg.get_item_state("net_img")
        if "rect_min" not in st:
            return
        x0, y0 = st["rect_min"]
        sc = self.net_scale
        w = g.w
        rows = self.net_image().shape[0]
        ry = rows / max(1, g.h)                      # a strip is drawn tall
        pts = [(x0 + (i % w + 0.5) * sc, y0 + ((i // w) * ry + ry / 2) * sc) for i in g.phys]
        self._wiring_items.append(dpg.draw_polyline(pts, parent="wiring_overlay", color=(90, 169, 230, 150), thickness=1))
        self._wiring_items.append(dpg.draw_circle(pts[0], max(3, sc / 2), parent="wiring_overlay",
                                                  color=(255, 184, 70, 255), fill=(255, 184, 70, 200)))
        self._wiring_items.append(dpg.draw_circle(pts[-1], max(3, sc / 2), parent="wiring_overlay",
                                                  color=(255, 96, 96, 255), fill=(255, 96, 96, 200)))
