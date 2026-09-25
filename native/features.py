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

from native.typeface import px
from native import num
from native import typeface
from native import form

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
    # --- the LED under the pointer (the footer names it) --------------------------------
    def led_at(self, mx, my):
        """The LED under a screen point in the logical net or the 3-D view:
        (wiring index, logical index, part name or "", (x, y, z)) or None.
        In the net the picture is the logical grid scaled; in the 3-D view
        the nearest projected LED within a few pixels (the nearer one of
        two that overlap)."""
        import numpy as np
        from native import render
        g = self.eng.geom
        if g is None:
            return None
        pos = np.asarray(g.pos, np.float32).reshape(-1, 3)
        lit = np.asarray(g.lit, bool)
        phys = np.asarray(g.phys, int)
        inv = getattr(self, "_phys_inv", None)
        if inv is None or len(inv) != len(pos) or getattr(self, "_phys_inv_for", None) is not g:
            inv = np.full(len(pos), -1, int); inv[phys] = np.arange(len(phys))
            self._phys_inv, self._phys_inv_for = inv, g
        li = None
        if dpg.does_item_exist("net_img") and dpg.is_item_shown("net_win"):
            st = dpg.get_item_state("net_img")
            if "rect_min" in st:
                (x0, y0), (w, h) = st["rect_min"], st["rect_size"]
                if w > 0 and h > 0 and x0 <= mx < x0 + w and y0 <= my < y0 + h:
                    cols, rows = self.eng.cols, self.eng.rows
                    px = int((mx - x0) / w * cols); py = int((my - y0) / h * rows) if rows > 1 else 0
                    cand = py * cols + px
                    if 0 <= cand < len(pos) and lit[cand]:
                        li = cand
        if li is None and dpg.does_item_exist("cube_img") and dpg.is_item_shown("cube_win"):
            st = dpg.get_item_state("cube_img")
            if "rect_min" in st:
                (x0, y0), (w, h) = st["rect_min"], st["rect_size"]
                q = getattr(self, "point_quads", None) or getattr(self, "cube_quads", None)
                if q is not None and getattr(q, "size", 0):
                    x0 += (w - q.size) * 0.5; y0 += (h - q.size) * 0.5; w = h = q.size
                if w > 0 and x0 <= mx < x0 + w and y0 <= my < y0 + h:
                    vpos = np.asarray(self.view_positions(), np.float32).reshape(-1, 3)
                    if len(vpos) == len(pos):
                        from native import view3d
                        frame = view3d.frame(self) if g.kind != "cube" else render.frame_of(vpos)
                        cam = view3d.cam(self, float(w))
                        P = (vpos - frame[0]) / frame[1]
                        sx, sy, ok, depth = cam.screen(P)
                        if g.kind == "cube":
                            # a face turned away is hidden: its LEDs are not under the pointer (a cube face's
                            # normal is the axis its LEDs sit at the end of)
                            ax = np.argmax(np.abs(np.nan_to_num(P)), axis=1)
                            nrm = np.zeros_like(P); nrm[np.arange(len(P)), ax] = np.sign(np.nan_to_num(P)[np.arange(len(P)), ax])
                            ok = ok & (((cam.eye - P) * nrm).sum(1) > 0)
                        d = np.hypot(sx + x0 - mx, sy + y0 - my)
                        d[~ok | ~lit] = np.inf
                        k = int(np.argmin(d))
                        if np.isfinite(d[k]):
                            # within most of the way to the next LED on screen: the pitch as it is drawn here
                            dd = np.hypot(sx - sx[k], sy - sy[k]); dd[k] = np.inf; dd[~ok | ~lit] = np.inf
                            pitch = float(dd.min()) if np.isfinite(dd.min()) else 8.0
                            reach = max(4.0, 0.75 * pitch)
                            if d[k] <= reach:
                                # the point cloud hides nothing behind a face: of those under the pointer, the one
                                # drawn on top - the nearest the eye
                                near = np.nonzero(d <= reach)[0]
                                li = int(near[np.argmin(depth[near])]) if len(near) > 1 else k
        if li is None:
            return None
        part = ""
        if g.kind == "shape" and getattr(g, "owner", None) is not None and inv[li] >= 0 and inv[li] < len(g.owner):
            parts = g.params.get("parts") or []
            pi = int(g.owner[inv[li]])
            part = parts[pi].get("name", "") if pi < len(parts) else ""
        x, y, z = (float(v) for v in pos[li])
        return int(inv[li]), int(li), part, (x, y, z)

    def hover_text(self):
        """One footer phrase for the LED under the pointer, or ""."""
        try:
            mx, my = dpg.get_mouse_pos(local=False)
            hit = self.led_at(mx, my)
        except Exception:
            return ""
        if hit is None:
            return ""
        k, li, part, (x, y, z) = hit
        g = self.eng.geom
        where = f"{li % self.eng.cols},{li // self.eng.cols}" if self.eng.rows > 1 else str(li)
        return f"   LED {k}" + (f" ({part})" if part else "") + f" at {where}" + (f", {x:.2f} {y:.2f} {z:.2f}" if g is not None and g.kind != "matrix" else "")

    def rebuild_seg_fields(self):
        if not dpg.does_item_exist("seg_fields"):
            return
        labels = self.seg_labels()
        dpg.configure_item("seg_combo", items=labels)
        dpg.set_value("seg_combo", labels[self.eng.seg] if self.eng.seg < len(labels) else "")
        dpg.delete_item("seg_fields", children_only=True)
        if self.eng.seg_count() < 2:
            form.note("one segment, the whole strip - + adds another", parent="seg_fields")
            return
        x0, y0, x1, y1, op, fx, bm = self.eng.seg_get(self.eng.seg)
        for lab, row in (("from", (("x0", x0), ("y0", y0))), ("to", (("x1", x1), ("y1", y1)))):
            with form.row(lab, parent="seg_fields", tip="the segment's corner on the net: x along, y down"):
                for key, val in row:
                    form.inline(key[0])
                    dpg.add_input_int(width=px(60), default_value=val, user_data=key, on_enter=True, step=0,
                                      callback=self.on_seg_field)
        with form.row("opacity", parent="seg_fields"):
            num.add(None, op, 0, 255, integer=True, width=-1, callback=lambda s, v: self.on_seg_field(s, v, "opacity"))
        # WLED's per-segment blend mode ("bm"): how this segment lands on the ones under it
        modes = self.eng.BLEND_MODES
        with form.row("blend mode", parent="seg_fields", tip="how this segment lands on the ones under it"):
            dpg.add_combo(modes, width=-1, default_value=modes[bm if bm < len(modes) else 0],
                          callback=lambda s, v: self.on_seg_blend(modes.index(v)))
        self._seg_option_rows(y1 - y0 > 1)
    def _seg_option_rows(self, is2d):
        """WLED's segment options, as its UI has them: reverse and mirror (X, and
        Y on a matrix), transpose, grouping, spacing, offset."""
        o = self.eng.seg_options(self.eng.seg)
        rows = [(("rev", "reverse"), ("mi", "mirror")) + ((("tp", "swap XY"),) if is2d else ())]
        if is2d:
            rows.append((("rY", "reverse Y"), ("mY", "mirror Y")))
        for row in rows:
            with form.under(parent="seg_fields"):
                for key, label in row:
                    dpg.add_checkbox(label=label, default_value=bool(o[key]), user_data=key,
                                     callback=lambda s, v, u: self.on_seg_option(u, bool(v)))
        with form.row("group", parent="seg_fields"):
            for j, (key, label, lo, hi) in enumerate((("grp", "group", 1, 255), ("spc", "space", 0, 255), ("of", "offset", 0, 65535))):
                if j:
                    form.inline(label)
                dpg.add_input_int(width=px(50), step=0, default_value=int(o[key]), min_value=lo, max_value=hi, min_clamped=True, max_clamped=True,
                                  on_enter=True, user_data=key, callback=lambda s, v, u: self.on_seg_option(u, int(v)))
            chrome.info("WLED's segment options: reverse runs the effect the other way, mirror folds it, transpose swaps the axes; "
                        "group lights that many LEDs as one, space leaves that many dark between, offset rotates along the strip.")
    def on_seg_option(self, key, val):
        self.eng.seg_set_options(self.eng.seg, **{key: val})
        self.save_segments()
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
    def seg_undo(self, redo=False):
        """The segments back a step (the project keeps what each save changed)."""
        ok = self.project.redo("segments") if redo else self.project.undo("segments")
        if not ok:
            self.gp.status("nothing to undo in the segments"); return
        segs = self.project.options.get("segments") or []
        if len(segs) > 1:
            self.eng.load_segments(segs)
        else:
            self.eng.seg_truncate(1); self.eng.seg_select(0)
        dpg.set_value("fx_combo", self.eng.names[self.eng.idx])
        self.rebuild_params(); self.sync_palette_combo(); self.rebuild_seg_fields()
        self.gp.status(f"segments: {'redo' if redo else 'undo'}")
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
            self._seg_items.append(typeface.draw_text((ox + x0 * sc + 4, oy + y0 * ry + 2), str(k), px(14), face="mono",
                                                      parent="seg_overlay", color=col))
    # --- the scripted runtime ---------------------------------------------------------
    def compile_current_script(self):
        """The current graph as bytecode, or None with the reason in the status."""
        from native.script import compile_script
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
                                      six=self.eng.six if self.project.geometry.kind == "cube" else None,
                                      options=self.eng.seg_options(self.eng.seg))
        dpg.set_value("edit_status", msg); self.gp.status(msg); device_ui.send_log(self, msg)
        self.probe_active()

    def overlay_holes(self, over=None):
        """The screen rectangles nothing may be drawn over: every window
        floating over the panes, the dialogs, the open menus - the same
        list the gradient frames keep off (poll_glow). over="cube": for
        what is drawn on the 3-D view, whose own window (in its corner of
        the graph, room.py) is no hole to it."""
        holes = getattr(self, "_holes", None)
        if holes is None:
            try:
                holes = self.compute_holes()
            except Exception:
                holes = []
        if over == "cube":
            from native import room
            h = room.cube_hole(self)
            if h:
                holes = [q for q in holes if max(abs(a - b) for a, b in zip(q, h)) > 6]
        return list(holes)

    # --- the 3-D view's surroundings: camera presets, saved views, a background picture --
    def set_camera(self, name_or_view):
        """A named camera (isometric, front, back, left, right, top, below:
        view3d.PRESETS), a saved view by its slot, or (yaw, pitch, dist[,
        look x y z, ortho])."""
        from native import view3d
        if isinstance(name_or_view, str) and name_or_view in view3d.PRESETS:
            view3d.preset(self, name_or_view)
            return
        v = name_or_view if not isinstance(name_or_view, str) else (self.prefs.get("views") or {}).get(name_or_view)
        if not v:
            return
        view3d.restore(self, v)
        self.gp.status(f"camera: {name_or_view if isinstance(name_or_view, str) else 'set'}")

    def save_view(self, slot):
        from native import view3d
        views = self.prefs.setdefault("views", {})
        views[str(slot)] = view3d.saved(self)
        save_prefs(self.prefs)
        self.gp.status(f"view {slot} saved")

    def set_background(self, path):
        """A picture behind the 3-D view (the room, the house), dimmed so
        the LEDs stand out; an empty path clears it."""
        self.prefs["view_bg"] = path or ""
        save_prefs(self.prefs)
        self._bg_cache = {}
        self.gp.status(f"background: {os.path.basename(path)}" if path else "background cleared")

    def view_background(self, size):
        """The background at the view's size: a (size, size, 3) picture, or black."""
        path = self.prefs.get("view_bg") or ""
        if not path:
            return (0, 0, 0)
        cache = getattr(self, "_bg_cache", None)
        if cache is None:
            cache = self._bg_cache = {}
        key = (path, int(size))
        if key not in cache:
            try:
                from PIL import Image
                im = Image.open(path).convert("RGB")
                w, h = im.size
                side = min(w, h)
                im = im.crop(((w - side) // 2, (h - side) // 2, (w - side) // 2 + side, (h - side) // 2 + side)).resize((int(size), int(size)), Image.BILINEAR)
                cache[key] = (np.asarray(im, np.float32) * float(self.prefs.get("view_bg_dim", 0.45))).astype(np.uint8)
            except Exception as e:
                self.gp.status(f"background not read: {e}")
                cache[key] = (0, 0, 0)
        return cache[key]

    # --- randomise: the sliders, the checks and the palette thrown --------------------
    def randomise(self, palette=True):
        """xLights' random button: every slider of the effect somewhere new,
        the checks a coin each, the palette any of them - for exploring."""
        import random
        f = self.eng.fx
        for k in ("sx", "ix", "c1", "c2"):
            f[k] = random.randint(0, 255)
        f["c3"] = random.randint(0, 31)
        for k in ("o1", "o2", "o3"):
            f[k] = random.randint(0, 1)
        if palette:
            pals = self.eng.palette_list()
            if pals:
                self.eng.pal = random.choice(pals)[1]
        self.eng.push()
        self.rebuild_params(); self.sync_palette_combo()
        self.gp.status(f"randomised: speed {f['sx']} intensity {f['ix']} customs {f['c1']} {f['c2']} {f['c3']}, palette {self.palette_name_for(self.eng.pal)}")

    # --- the picture, with a transition in progress blended in ------------------------
    # A sequence step change with a transition time keeps the old step
    # running in a second engine and blends the two pictures the way the
    # device does (native/transition.py) until the time is up; every view,
    # the stream and the stats read the blended picture through here.
    def frame_rgb(self, eng=None):
        eng = eng or self.eng
        tr = getattr(self, "_transition", None)
        if eng is not self.eng:
            return eng.rgb()
        if tr is None:
            return self._limited(eng.rgb())
        prog = (time.perf_counter() - tr["t0"]) / max(0.05, tr["dur"])
        if prog >= 1.0:
            self._transition = None
            return eng.rgb()
        from native import transition
        try:
            return self._limited(transition.blend(tr["old"].rgb(), eng.rgb(), prog, tr["style"]))
        except Exception:
            self._transition = None
            return eng.rgb()

    def _limited(self, rgb):
        """The picture dimmed as the device's brightness limiter would dim
        it, when the Outputs frame asks for the preview."""
        pw = getattr(self, "_power", None)
        if pw and pw[1] < 1.0 and (self.project.options.get("outputs") or {}).get("abl_preview"):
            return (np.asarray(rgb, np.float32) * pw[1]).astype(np.uint8)
        return rgb

    def poll_power(self):
        """The current the frame draws, every few frames (the Outputs frame's numbers)."""
        from native import outputs
        S = self.project.options.get("outputs") or {}
        n = getattr(self, "_power_n", 0) + 1
        self._power_n = n
        if n % 4:
            return
        try:
            ma, scale = outputs.power(self.eng.rgb(), self.project.geometry.phys, int(S.get("ma_per_led", outputs.LED_MA_DEFAULT)),
                                      int(S.get("max_ma", outputs.MAX_MA_DEFAULT)), int(getattr(self, "bri", 255)))
            self._power = (ma, scale, int(S.get("max_ma", outputs.MAX_MA_DEFAULT)))
        except Exception:
            self._power = None

    def transition_start(self, old_state, dur, style="fade"):
        """The old step into the second engine; the blend runs `dur` seconds."""
        from native import sequence
        try:
            eng2 = self.second_engine("transition")
        except Exception as e:
            self.gp.status(f"no second engine for the transition: {e}"); return
        try:
            if eng2.cols != self.eng.cols or eng2.rows != self.eng.rows:
                eng2.set_geometry(self.project.geometry)
            sequence.apply(eng2, old_state)
        except Exception as e:
            self.gp.status(f"transition skipped: {e}"); return
        self._transition = {"t0": time.perf_counter(), "dur": float(dur), "style": style, "old": eng2}

    def poll_transition(self):
        """The old step keeps running in its engine while the blend lasts."""
        tr = getattr(self, "_transition", None)
        if tr is None or not self.playing:
            return
        try:
            tr["old"].fft[:] = self.eng.fft[:]
            tr["old"].audio(*getattr(self.eng, "last_audio", (0.0, 0)))
            tr["old"].frame(23)
        except Exception:
            self._transition = None

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
        self.poll_transition()
        self.poll_power()
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
        d.send(live_out.frame_bytes(self.frame_rgb(), self.project.geometry.phys))
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
        outs = (self.project.options.get("outputs") or {}).get("outs") or []
        wt.outputs = [(int(o.get("start", 0)), int(o.get("len", 0))) for o in outs]
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

    # --- the device speed factor, measured -------------------------------------------
    def calibrate_factor(self):
        """The footer's device fps stops being a guess: the current effect's
        settings go to the device, its fps is read from /json/info a few
        times over three seconds, and the factor (how many times slower
        than this PC the device is) is set from the device's ms a frame
        against this PC's for the same effect - kept with what was
        measured, and the footer says "measured"."""
        import statistics
        host = self.active_host()
        if not host:
            device_ui.show(self, "devices"); self.gp.status("choose a device first"); return
        if self.frame_ms <= 0.0:
            self.gp.status("no frame time measured here yet - let the effect run a moment"); return
        self.push_settings()
        pc_ms = float(self.frame_ms)
        name = self.eng.names[self.eng.idx]
        self.gp.status(f"calibrating: reading the device's fps for {name}...")

        def run():
            fps = []
            for _ in range(4):
                time.sleep(0.8)
                st = devices.state(host, timeout=3.0)
                if st and st.get("fps"):
                    fps.append(float(st["fps"]))
            self._calib_result = (host, name, pc_ms, statistics.median(fps) if fps else None)
        threading.Thread(target=run, daemon=True).start()

    def poll_calibration(self):
        r = getattr(self, "_calib_result", None)
        if r is None:
            return
        self._calib_result = None
        host, name, pc_ms, fps = r
        if not fps:
            self.gp.status(f"calibration: {host} reported no fps (is the effect running there?)"); return
        factor = max(1.0, min(5000.0, (1000.0 / fps) / max(1e-3, pc_ms)))
        self.prefs["device_factor"] = round(factor, 1)
        self.prefs["device_factor_measured"] = {"host": host, "effect": name, "fps": round(fps, 1), "pc_ms": round(pc_ms, 3),
                                                "date": time.strftime("%Y-%m-%d")}
        save_prefs(self.prefs)
        self.gp.status(f"speed factor measured: {name} runs at {fps:.0f} fps on {host}, {pc_ms:.2f} ms here - x{factor:.0f}")
        device_ui.send_log(self, f"speed factor x{factor:.0f} from {name} at {fps:.0f} fps on the device")

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
    def _b_library(self, purpose="b"):
        """A copy of the current library for a second engine. A DLL loaded
        twice by its path is the SAME module - one set of statics - so each
        engine needs a file of its own; one per purpose per build
        (cubefx_338_shape.dll), so the copies do not pile up."""
        lib = self.eng.library
        root, ext = os.path.splitext(lib)
        path = f"{root}_{purpose}{ext}"
        if not os.path.exists(path):
            shutil.copyfile(lib, path)
        return path

    def second_engine(self, purpose):
        """A second engine for a purpose - "shape" (the shape's preview),
        "library" (the thumbnails), "library_gen" (the previews of every
        effect, on a thread), "transition" (the old step during a blend) -
        made once and kept, its library swapped when the sim's is rebuilt.
        Without the pool every preview made another engine on another copy
        of the DLL, none of them ever let go."""
        from native.engine import Engine
        pool = self.__dict__.setdefault("_engines", {})
        eng, src = pool.get(purpose, (None, None))
        if eng is None:
            eng = Engine(self._b_library(purpose))
        elif src != self.eng.library:
            eng.reload(self._b_library(purpose))      # unloads the old copy for the prune
        pool[purpose] = (eng, self.eng.library)
        return eng
    def start_ab(self, name):
        if name not in self.eng.names:
            return
        self._gpu_was = None
        try:
            if self.ab is None:
                self.ab = Engine(self._b_library("ab"))
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
            self.ab.reload(self._b_library("ab"))
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
            num.set(f"inp_{sw['key']}", v)
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
        # a viewport drawlist draws over every window: the line is broken
        # wherever a floating frame, a dialog or a menu covers the net
        holes = self.overlay_holes()
        def clear(p):
            return not any(a <= p[0] <= c_ and b <= p[1] <= d for a, b, c_, d in holes)
        run = []
        for p in pts:
            if clear(p):
                run.append(p)
            else:
                if len(run) > 1:
                    self._wiring_items.append(dpg.draw_polyline(run, parent="wiring_overlay", color=(90, 169, 230, 150), thickness=1))
                run = []
        if len(run) > 1:
            self._wiring_items.append(dpg.draw_polyline(run, parent="wiring_overlay", color=(90, 169, 230, 150), thickness=1))
        for p, col in ((pts[0], (255, 184, 70)), (pts[-1], (255, 96, 96))):
            if clear(p):
                self._wiring_items.append(dpg.draw_circle(p, max(3, sc / 2), parent="wiring_overlay",
                                                          color=col + (255,), fill=col + (200,)))
