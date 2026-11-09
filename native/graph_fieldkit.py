"""The richer fields on a node - a mixin of graph_ui's GraphPanel: a modulator's range under the pin it feeds, the XY pads (two typed inputs as one point), a colour ramp's gradient and stops, and the scopes."""
import os
import dearpygui.dearpygui as dpg
from native.typeface import px
from native import typeface
from native import num
from native import graph as G
from native import nodeface
from native.nodedefs import IMPLICIT_SOURCES
from native import oops
from native import graph_ui as GU


class GraphFieldKit:
    # --- the modulation range on the field --------------------------------------------
    def mod_ranges(self):
        """[(remap id, fed node, fed input)] for every input a modulator's
        Remap feeds - the Remap a "modulate with" made, or any Remap
        labelled with a ±."""
        out = []
        for a, o, b, i in self.graph.links:
            n = self.graph.nodes.get(a)
            if n and n["type"] == "Remap" and o == "result" and (n.get("modulator") or "\u00b1" in str(n.get("label") or "")):
                out.append((a, b, i))
        return out

    def _draw_mod_ranges(self, pane, size):
        """Under a modulated input's name: a bar from the Remap's out_lo to
        out_hi with the live value on it and the two numbers at its ends.
        Ctrl+wheel over an end nudges it (the Remap's setting changes)."""
        self._mod_bars = {}
        if not self.graph:
            return
        x0, y0, x1, y1 = pane
        small = max(8, int(9 * self.zoom))
        for r, b, inp in self.mod_ranges():
            if b not in self.graph.nodes or self.graph.nodes[b].get("collapsed"):
                continue
            pt = self._pin_point(b, "in", inp)
            if not pt:
                continue
            rn = self.graph.nodes[r]
            lo, hi = float(rn["params"].get("out_lo", 0.0)), float(rn["params"].get("out_hi", 1.0))
            mw = max(40.0, 64.0 * self.zoom)
            bx, by = pt[0] + 12, pt[1] + size * 0.75
            if bx < x0 or bx + mw > x1 or by < y0 or by + small + 4 > y1:
                continue
            cover = getattr(self, "_cover_now", None)
            if cover and self._covered((bx, by, bx + mw, by + small + 4), cover, b):
                continue                                 # its node is under another, a window, the minimap
            k = self._probe_k(r, "out", "result")
            v = self._probe_now(k)
            f = None if v is None or hi == lo else max(0.0, min(1.0, (v - min(lo, hi)) / abs(hi - lo)))
            items = self._readout_items
            P = self.pal()
            items.append(dpg.draw_rectangle((bx, by), (bx + mw, by + 3), parent="wire_labels", color=(0, 0, 0, 0), fill=P["meter_bg"]))
            if f is not None:
                items.append(dpg.draw_rectangle((bx, by), (bx + mw * f, by + 3), parent="wire_labels", color=(0, 0, 0, 0), fill=P["mod"]))
                items.append(dpg.draw_circle((bx + mw * f, by + 1.5), 2.5, parent="wire_labels", color=(0, 0, 0, 0), fill=P["mod_dot"]))
            items.append(self._draw_text((bx, by + 4), nodeface._fmt(lo), parent="wire_labels", size=small, color=P["mod_text"]))
            t = nodeface._fmt(hi)
            items.append(self._draw_text((bx + mw - typeface.measure(t, "mono", small), by + 4), t, parent="wire_labels", size=small, color=P["mod_text"]))
            self._mod_bars[(bx, by, bx + mw, by + small + 4)] = r

    def _step_mod_range(self, direction):
        """Ctrl+wheel over a range bar: the end the pointer is nearer, by
        a fiftieth of the range (the Remap's out_lo or out_hi)."""
        bars = getattr(self, "_mod_bars", None)
        if not bars:
            return False
        mx, my = dpg.get_mouse_pos(local=False)
        for (bx0, by0, bx1, by1), r in bars.items():
            if bx0 - 4 <= mx <= bx1 + 4 and by0 - 4 <= my <= by1:
                rn = self.graph.nodes.get(r)
                if not rn:
                    return False
                lo, hi = float(rn["params"].get("out_lo", 0.0)), float(rn["params"].get("out_hi", 1.0))
                key = "out_lo" if mx < (bx0 + bx1) / 2 else "out_hi"
                step = (abs(hi - lo) or 1.0) / 50.0 * (1 if direction > 0 else -1)
                self.snapshot(("modrange", r, key))
                rn["params"][key] = round(rn["params"].get(key, 0.0) + step, 5)
                self._set_param_widget(r, key, rn["params"][key])
                self._refresh_summary(r)
                self.touch()
                self.status(f"{rn.get('label') or 'Remap'}: {nodeface._fmt(rn['params']['out_lo'])} .. {nodeface._fmt(rn['params']['out_hi'])}")
                return True
        return False

    def reset_hovered(self):
        """Backspace over a value box: the default again."""
        h = self._hovered_field()
        if not h or not self.graph:
            return False
        w, nid, name, kind = h
        n = self.graph.nodes[nid]
        d = self.graph.node_def(n)
        self.snapshot()
        if kind == "param":
            p = next(p for p in d["params"] if p["name"] == name)
            n["params"][name] = p["default"]
        else:
            n.setdefault("inputs", {}).pop(name, None)
        self.touch()
        self._sync_pos(); self.rebuild()
        self.status(f"{self.pin_words(nid, name)}: back to its default", node=self.where(nid))
        return True

    def step_hovered(self, direction):
        """Ctrl+wheel over a dropdown: the next or previous choice; over a
        slider or a drag field: a step - one for an integer, a hundredth
        of the range or of the value for a float; over a modulation range
        bar, the nearer end by a fiftieth of the range."""
        if self._step_mod_range(direction):
            return True
        h = self._hovered_field()
        if not h or not self.graph:
            return False
        w, nid, name, kind = h
        t = dpg.get_item_type(w)
        if num.is_num(w):
            num.step(w, 1 if direction > 0 else -1)        # the field's own callback takes it (num.step fires it)
            return True
        if not t.endswith("Combo"):
            return False
        items = dpg.get_item_configuration(w).get("items") or []
        if not items:
            return False
        cur = dpg.get_value(w)
        k = (items.index(cur) + (1 if direction > 0 else -1)) % len(items) if cur in items else 0
        dpg.set_value(w, items[k])
        self._on_param(w, items[k])
        return True

    def _param_widget(self, nid, n, p, multiline=False, col=0, width=None):
        v = n["params"].get(p["name"], p["default"])
        ud = (nid, p["name"])
        cb = self._on_param
        width = width or self.px(GU.NODE_W)
        if p["type"] in self.NAMED["param"] and not (p["type"] == "text" and (multiline or p.get("lines"))):
            # the setting's name in the node's column, the field after it
            with dpg.group(horizontal=True, horizontal_spacing=self._gap()):
                self._lead(nodeface.label(n["type"], p["name"]), col)
                self._param_field(nid, n, p, v, ud, cb, width - col)
            return
        if p["type"] == "text" and (multiline or p.get("lines")):
            # rows of a bitmap are '/'-separated in the param and shown as lines
            shown = str(v).replace("/", "\n") if p.get("lines") else str(v)
            w = dpg.add_input_text(width=width, height=self.px(90 if not p.get("lines") else 150), multiline=True,
                                   default_value=shown, user_data=ud, callback=cb)
            self._widgets.add(w)
            return
        if p["type"] == "bool":
            w = dpg.add_checkbox(label=nodeface.label(n["type"], p["name"]), default_value=bool(v), user_data=ud, callback=cb)
        elif p["type"] == "ramp":
            self._ramp_widget(nid, n, p, v, width)
            return
        elif p["type"] == "curve":
            self._curve_widget(nid, n, p, v, width)
            return
        else:
            return
        dpg.bind_item_theme(w, self._field_theme())
        self._value_face(w)
        self._widgets.add(w)

    def _pair_widget(self, nid, n, p, q, words, col, width):
        """Two settings that are one range on one row (nodeface.PAIRS): the
        row's words in the node's column, then the two fields with an arrow
        between - "in  [0] -> [1]" - each the one number control."""
        g = self._gap()
        arrow = "\u2192"
        aw = int(self.text_w(arrow) + 0.999)
        fw = max(self.px(24), int((width - col - aw - 2 * g) / 2))
        with dpg.group(horizontal=True, horizontal_spacing=g):
            self._lead(words, col)
            for k, r in enumerate((p, q)):
                if k:
                    dpg.add_text(arrow, color=self.pal()["dim"])
                self._param_field(nid, n, r, n["params"].get(r["name"], r["default"]), (nid, r["name"]), self._on_param, fw)

    def _param_field(self, nid, n, p, v, ud, cb, fw):
        """A setting's field, `fw` wide, after its name: a number the one
        control; a choice, a colour, a text, a file as their own."""
        if p["type"] == "float":
            w = self._number_widget(p, G.as_float(v), None, ud, cb, True, fw)
        elif p["type"] == "int" and n["type"] == "Effect settings" and p["name"] == "palette":
            # the default palette by name, not by number
            names = [f"{i}  {name}" for name, i in self._palette_names()]
            cur = next((s_ for s_ in names if s_.split("  ", 1)[0] == str(int(v))), f"{int(v)}  ?")
            w = dpg.add_combo(names, width=fw, default_value=cur, user_data=ud,
                              callback=lambda s_, a_: cb(s_, int(str(a_).split("  ", 1)[0])))
        elif p["type"] == "int":
            w = self._number_widget(p, int(v), None, ud, cb, True, fw, integer=True)
        elif p["type"] == "choice":
            w = dpg.add_combo(self._choice_items(p), width=fw, default_value=str(v), user_data=ud,
                              callback=self._choice_cb(nid, p, cb) if p.get("groups") else cb)
        elif p["type"] == "color":
            rgb = list(v)[:3] if isinstance(v, (list, tuple)) else [255, 255, 255]
            # the swatch alone, as a colour input's is: its picker has the hex and R, G and B
            w = dpg.add_color_edit([int(c) for c in rgb] + [255], no_label=True, no_alpha=True,
                                   no_inputs=True, user_data=ud, callback=cb)
        elif p["type"] == "text":
            w = dpg.add_input_text(width=fw, default_value=str(v), user_data=ud, callback=cb)
        elif p["type"] == "file":
            w = dpg.add_input_text(width=max(self.px(20), fw - self.px(30)), default_value=str(v), user_data=ud, callback=cb)
            dpg.add_button(label="...", small=True, user_data=(nid, p["name"]),
                           callback=lambda s_, a_, u_: self._pick_file(u_))
        else:
            return
        dpg.bind_item_theme(w, self._field_theme())
        self._value_face(w)
        self._widgets.add(w)

    def _field_theme(self):
        """The look of a value field on a node: a box a shade lighter than the
        node's body (a thing to drag or type in), a slider's grab a narrow
        translucent bar so the value written across it stays readable.
        One theme per colour scheme; remade when the scheme changes."""
        from native import chrome
        from native.theme import theme_colors, theme_is_light
        cols = theme_colors(self.app.prefs); light = theme_is_light(self.app.prefs)
        key = (cols["frame"], cols["accent"], light)
        th = self._field_themes.get(key)
        if th is None:
            fr = tuple((min(255, c + 12) if not light else max(0, c - 12)) for c in cols["frame"])
            ac = tuple(chrome.ACCENT[:3])
            with dpg.theme() as th:
                with dpg.theme_component(dpg.mvAll):
                    dpg.add_theme_color(dpg.mvThemeCol_FrameBg, fr + (255,), category=dpg.mvThemeCat_Core)
                    dpg.add_theme_color(dpg.mvThemeCol_FrameBgHovered, tuple(min(255, c + 8) for c in fr) + (255,), category=dpg.mvThemeCat_Core)
                    dpg.add_theme_color(dpg.mvThemeCol_SliderGrab, ac + (70,), category=dpg.mvThemeCat_Core)
                    dpg.add_theme_color(dpg.mvThemeCol_SliderGrabActive, ac + (140,), category=dpg.mvThemeCat_Core)
                    dpg.add_theme_style(dpg.mvStyleVar_GrabMinSize, 3, category=dpg.mvThemeCat_Core)   # a thin mark: the digits read through it
            self._field_themes[key] = th
        return th

    def _number_widget(self, spec, v, tag, ud, cb, show, width=None, integer=False, words=None):
        """A number on a node: the one control (num.py) - the value and its
        unit on the track in the monospace, drag it, click it to type, a
        thin fill for where it sits in the definition's range (along the
        log of it for a log one, which moves by ratio). A range too wide to
        slide across still clamps, and paces by the value's size, as an
        open field does from its default."""
        unit = spec.get("unit") or ""
        if unit.lower() == spec["name"].lower():
            unit = ""                                        # "1.2 Hz  hz" says it twice
        lo, hi = spec.get("min"), spec.get("max")
        lo = None if lo is None else (int(lo) if integer else float(lo))
        hi = None if hi is None else (int(hi) if integer else float(hi))
        log = spec.get("scale") == "log"
        wide = lo is not None and hi is not None and (hi - lo) > (512 if integer else 1000.0) and not log
        try:
            pace = abs(float(spec.get("default") or 0.0))
        except (TypeError, ValueError):
            pace = None
        # an unwired coordinate that reads the pixel shows where from ("position x") until a number
        # is dragged or typed into it (_mirror turns it back into a number then)
        w = num.add(tag, int(v) if integer else float(v), lo, hi, integer=integer, log=log, unit=unit, width=width or self.px(96),
                    callback=cb, user_data=ud, show=show, fill_h=max(1, self.px(2)), wide=wide, pace=pace,
                    fmt=words.replace("%", "%%") if words else None, fill=not words)
        return w

    def _implicit_words(self, nid, name):
        """What an unwired, untyped coordinate pin reads (nodedefs.IMPLICIT): "position x", "u" - or None."""
        src = self.graph.implicit_pins(nid).get(name) if self.graph else None
        return IMPLICIT_SOURCES[src][1] if src else None

    def _implicit_button(self, words, tag, ud, width, show):
        """A vector pin that reads the pixel: its words on a button, which gives it a typed value."""
        kw = {"tag": tag} if tag else {}
        w = dpg.add_button(label=words, width=width, user_data=ud, show=show, callback=self._implicit_to_typed, **kw)
        with dpg.tooltip(w):
            dpg.add_text(f"unwired: the pixel's {words}, as the Position node gives it - click to type a value "
                         "instead (reset the pin to read the pixel again)", wrap=px(300))
        return w

    def _implicit_to_typed(self, sender, app_data, ud):
        """The implicit button pressed: the pin takes its default as a typed value, drawn as fields."""
        nid, name = ud
        n = self.graph.nodes.get(nid) if self.graph else None
        if not n:
            return
        self.snapshot(("in", nid, name))
        spec = next((i for i in self.graph.node_def(n)["inputs"] if i["name"] == name), {})
        n.setdefault("inputs", {})[name] = list(spec.get("default") or [0.0, 0.0, 0.0])
        self.touch()
        self.rebuild()

    def _typed_fields(self, nid, name):
        """A pin that read the pixel has a value typed on it now: its fields show the number again."""
        n = self.graph.nodes.get(nid) if self.graph else None
        spec = next((i for i in self.graph.node_def(n)["inputs"] if i["name"] == name), None) if n else None
        if not spec or spec["type"] != "float":
            return
        unit = spec.get("unit") or ""
        if unit.lower() == spec["name"].lower():
            unit = ""
        for w in list(self._widgets):
            if dpg.does_item_exist(w) and dpg.get_item_user_data(w) == (nid, name) and num.is_num(w):
                dpg.configure_item(w, format=num.fmt_for(unit))

    def _palette_names(self):
        """[(name, id)] the sim knows, for the Effect settings' palette."""
        try:
            return self.app.eng.palette_list()
        except Exception:
            oops.swallowed()
            return [("Default", 0)]

    # --- the XY pads: two typed inputs as one point on a small square -----------------------
    def _pad_widget(self, nid, n, a, b, lo, hi):
        from native.textures import registry
        tex = f"gpad_{nid}_{a}_tex"
        if not dpg.does_item_exist(tex):
            dpg.add_dynamic_texture(GU.PAD_PX, GU.PAD_PX, [0.0, 0.0, 0.0, 1.0] * (GU.PAD_PX * GU.PAD_PX), tag=tex, parent=registry())
        size = self.px(GU.PAD)
        with dpg.group(horizontal=True):
            btn = dpg.add_image_button(tex, width=size, height=size, frame_padding=0, user_data=(nid, a, b, lo, hi))
            with dpg.tooltip(btn):
                dpg.add_text(f"{a} and {b} as one point, {lo:g}..{hi:g}: drag to set both (the fields above follow); "
                             "the fields still take a typed value", wrap=px(260))
            stem = a[:-2] if a.endswith(("_u", "_x")) else a.rstrip("xu")
            dpg.add_text(stem or f"{a} {b}", color=GU.DIM)
        self._pads[btn] = (nid, a, b, float(lo), float(hi), tex)
        self._pad_draw(btn)

    def _pad_values(self, nid, a, b):
        n = self.graph.nodes.get(nid)
        d = self.graph.node_def(n)
        da = next((i.get("default", 0.0) for i in d["inputs"] if i["name"] == a), 0.0)
        db = next((i.get("default", 0.0) for i in d["inputs"] if i["name"] == b), 0.0)
        return float(n["inputs"].get(a, da)), float(n["inputs"].get(b, db))

    def _pad_draw(self, btn):
        import numpy as np
        nid, a, b, lo, hi, tex = self._pads[btn]
        if nid not in self.graph.nodes or not dpg.does_item_exist(tex):
            return
        x, y = self._pad_values(nid, a, b)
        img = np.empty((GU.PAD_PX, GU.PAD_PX, 4), np.float32)
        img[:] = (0.11, 0.12, 0.14, 1.0)
        for k in (GU.PAD_PX // 4, GU.PAD_PX // 2, 3 * GU.PAD_PX // 4):
            img[k, :, :3] = (0.2, 0.21, 0.24); img[:, k, :3] = (0.2, 0.21, 0.24)
        if lo < 0.0 < hi:                                     # the zero lines, when the range crosses zero
            k = int(round((0.0 - lo) / (hi - lo) * (GU.PAD_PX - 1)))
            img[GU.PAD_PX - 1 - k, :, :3] = (0.3, 0.32, 0.36); img[:, k, :3] = (0.3, 0.32, 0.36)
        img[0, :, :3] = img[-1, :, :3] = img[:, 0, :3] = img[:, -1, :3] = (0.27, 0.29, 0.32)
        fx = (max(lo, min(hi, x)) - lo) / (hi - lo); fy = (max(lo, min(hi, y)) - lo) / (hi - lo)
        cx, cy = int(round(fx * (GU.PAD_PX - 1))), int(round((1.0 - fy) * (GU.PAD_PX - 1)))
        from native import chrome
        col = tuple(c / 255.0 for c in chrome.ACCENT[:3])
        yy, xx = np.ogrid[:GU.PAD_PX, :GU.PAD_PX]
        dot = (xx - cx) ** 2 + (yy - cy) ** 2 <= 9
        img[dot, :3] = col
        img[cy, :, :3] = img[cy, :, :3] * 0.5 + np.array(col) * 0.5
        img[:, cx, :3] = img[:, cx, :3] * 0.5 + np.array(col) * 0.5
        dpg.set_value(tex, img.ravel())

    def _poll_pads(self):
        """A pad held: the point under the pointer into both inputs, the
        fields and the picture following; one undo step per stroke."""
        if not self.graph:
            return
        active = None
        for btn, (nid, a, b, lo, hi, tex) in list(self._pads.items()):
            if dpg.does_item_exist(btn) and dpg.is_item_active(btn) and nid in self.graph.nodes:
                active = btn; break
        if active is None:
            if self._pad_stroke is not None:
                self._pad_stroke = None
                self._sync_pos()
            return
        st = dpg.get_item_state(active)
        if "rect_min" not in st:
            return
        (x0, y0), (w, h) = st["rect_min"], st["rect_size"]
        mx, my = dpg.get_mouse_pos(local=False)
        fx = max(0.0, min(1.0, (mx - x0) / max(1.0, w - 1))); fy = max(0.0, min(1.0, 1.0 - (my - y0) / max(1.0, h - 1)))
        self._pad_apply(active, fx, fy)

    def _pad_apply(self, btn, fx, fy):
        """The pad's point (0..1 across, 0..1 up) into its two inputs, the
        fields and the picture; the first change of a stroke takes the undo step."""
        nid, a, b, lo, hi, tex = self._pads[btn]
        x, y = lo + fx * (hi - lo), lo + fy * (hi - lo)
        cur = self._pad_values(nid, a, b)
        if abs(cur[0] - x) < 1e-6 and abs(cur[1] - y) < 1e-6:
            return
        if self._pad_stroke != btn:
            self.touch(); self.snapshot(("pad", nid, a))
            self._pad_stroke = btn
        n = self.graph.nodes[nid]
        n.setdefault("inputs", {})[a] = round(x, 4); n["inputs"][b] = round(y, 4)
        for name, val in ((a, x), (b, y)):
            self._set_param_widget(nid, name, float(val))         # its fields: the node's, and in the properties
        was_dirty = self._dirty
        self.touch()
        if self.live_poke(nid, a, x) and self.live_poke(nid, b, y) and not was_dirty:
            self._dirty = 0.0                            # the running effect follows the dot: no rebuild
        self._pad_draw(btn)

    def _pick_file(self, target):
        """The file dialog, for a node's file param; the choice lands in the
        param (relative to the project when it is inside it) and rebuilds."""
        self._file_target = target
        if not dpg.does_item_exist("graph_file_dialog"):
            with dpg.file_dialog(directory_selector=False, show=False, tag="graph_file_dialog", width=px(640), height=px(440),
                                 callback=lambda s_, a_: self._file_picked(a_.get("file_path_name", ""))):
                for ext, col in ((".png", (120, 200, 120)), (".jpg", (120, 200, 120)), (".jpeg", (120, 200, 120)),
                                 (".gif", (120, 200, 120)), (".bmp", (120, 200, 120)), (".*", (180, 180, 180))):
                    dpg.add_file_extension(ext, color=col)
        dpg.show_item("graph_file_dialog")

    def _file_picked(self, path):
        if not path or not getattr(self, "_file_target", None) or not self.graph:
            return
        nid, name = self._file_target
        if nid not in self.graph.nodes:
            return
        proj = self.app.project.path
        try:
            rel = os.path.relpath(path, proj)
            if not rel.startswith(".."):
                path = rel.replace("\\", "/")
        except ValueError:
            pass
        self.snapshot(); self._sync_pos()
        self.graph.nodes[nid]["params"][name] = path
        self.rebuild()
        self.status(f"{os.path.basename(path)}")

    def image_to_bitmap(self, nid):
        """An Image node becomes a Bitmap and a Colour pick, wired the same:
        the picture as digits you can edit, its palette as colours you can
        change. Up to eight colours; the image is re-quantised to fit."""
        from native.nodedefs import load_image_indexed
        n = self.graph.nodes.get(nid)
        if not n or n["type"] != "Image":
            return
        p = n["params"]
        path = str(p.get("file", "")).strip()
        if path and not os.path.isabs(path):
            path = os.path.join(self.app.project.path, path)
        if not path or not os.path.exists(path):
            self.status("the Image node has no file"); return
        w, h = int(p.get("width", 16)), int(p.get("height", 16))
        try:
            idx, palette = load_image_indexed(path, w, h, min(8, int(p.get("colours", 8))), bool(p.get("alpha_clear", True)))
        except Exception as e:
            self.status(f"cannot read the image: {e}"); return
        rows = "/".join("".join("." if idx[y * w + x] == 255 else str(min(9, idx[y * w + x])) for x in range(w)) for y in range(h))
        self.snapshot(); self._sync_pos()
        g = self.graph
        pos = n["pos"]
        bm = g.add("Bitmap", (pos[0], pos[1]), {"rows": rows})
        cp = g.add("Colour pick", (pos[0] + 240, pos[1]), {f"c{k}": list(palette[k]) if k < len(palette) else [0, 0, 0] for k in range(8)})
        mk = g.add("Mask", (pos[0] + 480, pos[1]))
        g.link(bm, "slot", cp, "index"); g.link(cp, "color", mk, "color"); g.link(bm, "on", mk, "mask")
        # the same wires in and out
        for a, o, b_, i in [l for l in g.links if l[2] == nid]:
            if i in ("u", "v"):
                g.link(a, o, bm, i)
        for a, o, b_, i in [l for l in g.links if l[0] == nid]:
            src = {"color": (mk, "color"), "slot": (bm, "slot"), "on": (bm, "on")}.get(o)
            if src:
                g.link(src[0], src[1], b_, i)
        for k in ("u", "v"):
            if k in n.get("inputs", {}):
                g.nodes[bm]["inputs"][k] = n["inputs"][k]
        g.remove(nid)
        self.rebuild()
        self.status(f"image -> Bitmap ({w} x {h}, {len(palette)} colours) + Colour pick")

    # --- a colour ramp on the node: the gradient drawn, then a row per stop -----------
    def _ramp_widget(self, nid, n, p, stops, width=None):
        """`width`: the node's (in the properties, 220 at this zoom)."""
        stops = [list(st) for st in (stops or p["default"])]
        W, H = int(width or self.px(220)), self.px(14)
        with dpg.drawlist(width=W, height=H):
            srt = sorted(stops, key=lambda st: st[0])
            for x in range(0, W, 2):
                t = x / max(1, W - 1)
                r, g, b = self._ramp_colour(srt, t, str(n["params"].get("mode", "linear")))
                dpg.draw_rectangle((x, 0), (x + 2, H), color=(r, g, b, 255), fill=(r, g, b, 255))
        for k, st in enumerate(stops):
            with dpg.group(horizontal=True):
                w1 = num.add(None, float(st[0]), 0.0, 1.0, digits=2, width=self.px(56), user_data=(nid, p["name"], k, "pos"),
                             callback=self._on_ramp, fill_h=max(1, self.px(2)))
                w2 = dpg.add_color_edit([int(st[1]), int(st[2]), int(st[3]), 255], width=self.px(60), no_alpha=True, no_inputs=True,
                                        user_data=(nid, p["name"], k, "col"), callback=self._on_ramp)
                self._value_face(w1)
                self._widgets.update((w1, w2))
                if len(stops) > 2:
                    dpg.add_button(label="-", small=True, user_data=(nid, p["name"], k, "del"), callback=self._on_ramp)
        dpg.add_button(label="+ stop", small=True, user_data=(nid, p["name"], -1, "add"), callback=self._on_ramp)

    def _curve_widget(self, nid, n, p, pts, width=None):
        pts = sorted([list(q) for q in (pts or p["default"])], key=lambda q: q[0])
        W, H = int(width or self.px(GU.NODE_W)), self.px(80)
        with dpg.drawlist(width=W, height=H):
            P = self.pal()
            dpg.draw_rectangle((0, 0), (W - 1, H - 1), color=P["plot_edge"])
            prev = None
            for x in range(0, W, 2):
                t = x / max(1, W - 1)
                y = (1.0 - max(0.0, min(1.0, self._curve_at(pts, t)))) * (H - 1)
                if prev is not None:
                    dpg.draw_line(prev, (x, y), color=P["live"], thickness=1.5)
                prev = (x, y)
            for q in pts:
                dpg.draw_circle((q[0] * (W - 1), (1.0 - q[1]) * (H - 1)), 3, color=P["point"], fill=P["point"])
        for k, q in enumerate(pts):
            with dpg.group(horizontal=True):
                w1 = num.add(None, float(q[0]), 0.0, 1.0, digits=2, width=self.px(56), user_data=(nid, p["name"], k, "x"),
                             callback=self._on_curve, fill_h=max(1, self.px(2)))
                w2 = num.add(None, float(q[1]), 0.0, 1.0, digits=2, width=self.px(56), user_data=(nid, p["name"], k, "y"),
                             callback=self._on_curve, fill_h=max(1, self.px(2)))
                self._value_face(w1); self._value_face(w2)
                self._widgets.update((w1, w2))
                if len(pts) > 2:
                    dpg.add_button(label="-", small=True, user_data=(nid, p["name"], k, "del"), callback=self._on_curve)
        dpg.add_button(label="+ point", small=True, user_data=(nid, p["name"], -1, "add"), callback=self._on_curve)

    @staticmethod
    def _curve_at(pts, t):
        if t <= pts[0][0]:
            return pts[0][1]
        if t >= pts[-1][0]:
            return pts[-1][1]
        for i in range(len(pts) - 1):
            a, b = pts[i], pts[i + 1]
            if a[0] <= t <= b[0]:
                f = (t - a[0]) / (b[0] - a[0]) if b[0] > a[0] else 0.0
                f = f * f * (3 - 2 * f)
                return a[1] + (b[1] - a[1]) * f
        return pts[-1][1]

    def _on_curve(self, sender, val, ud):
        nid, name, k, what = ud
        n = self.graph.nodes[nid]
        pts = sorted([list(q) for q in n["params"].get(name) or []], key=lambda q: q[0])
        self.touch(); self.snapshot(("curve", nid, name, k, what))
        if what == "x":
            pts[k][0] = max(0.0, min(1.0, float(val)))
        elif what == "y":
            pts[k][1] = float(val)
        elif what == "del":
            pts.pop(k)
        elif what == "add":
            pts.append([0.5, 0.5])
        n["params"][name] = pts
        self._sync_pos(); self.rebuild()

    @staticmethod
    def _ramp_colour(srt, t, mode):
        if t <= srt[0][0]:
            return srt[0][1:4]
        if t >= srt[-1][0]:
            return srt[-1][1:4]
        for i in range(len(srt) - 1):
            a, b = srt[i], srt[i + 1]
            if a[0] <= t <= b[0]:
                f = (t - a[0]) / (b[0] - a[0]) if b[0] > a[0] else 0.0
                if mode == "constant":
                    f = 0.0
                elif mode == "ease":
                    f = f * f * (3 - 2 * f)
                return [int(a[j] + (b[j] - a[j]) * f) for j in (1, 2, 3)]
        return srt[-1][1:4]

    def _on_ramp(self, sender, val, ud):
        nid, name, k, what = ud
        n = self.graph.nodes[nid]
        stops = [list(st) for st in n["params"].get(name) or []]
        self.touch(); self.snapshot(("ramp", nid, name, k, what))
        if what == "pos":
            stops[k][0] = max(0.0, min(1.0, float(val)))
        elif what == "col":
            stops[k][1:4] = [int(round(c * 255)) if c <= 1.0 else int(c) for c in val[:3]]
        elif what == "del":
            stops.pop(k)
        elif what == "add":
            stops.append([1.0, 255, 255, 255])
        n["params"][name] = stops
        if what in ("del", "add") or True:
            self._sync_pos(); self.rebuild()      # the strip redraws with the stops

    def _on_param(self, sender, val):
        self.touch()
        nid, name = dpg.get_item_user_data(sender)
        self.snapshot(("param", nid, name))
        if isinstance(val, str) and "\n" in val:
            d = self.graph.node_def(self.graph.nodes[nid])
            spec = next((p for p in d["params"] if p["name"] == name), {})
            val = val.replace("\r", "")
            if spec.get("lines"):
                val = val.replace("\n", "/")                   # a bitmap's lines back to rows
            elif not d.get("multiline"):
                val = val.replace("\n", " ")                   # pasted into a line of text: in an expression "/" divides
            # a Note's text keeps its lines
        if isinstance(val, (list, tuple)) and len(val) >= 3 and all(isinstance(x, float) for x in val):
            val = [int(round(x * 255)) if x <= 1.0 else int(x) for x in val[:3]]
        self.graph.nodes[nid]["params"][name] = val
        self._mirror(sender, nid, name, val)             # the node's field, or its properties', follows the other
        self._refresh_summary(nid)
        for k in self._same_type_selected(nid):
            self.graph.nodes[k]["params"][name] = val
            self._mirror(None, k, name, val)
            self._refresh_summary(k)
        if self.graph.nodes[nid]["type"] == "Frame" and name in ("title", "colour"):
            self._sync_pos(); self.rebuild()
        elif any((i.get("when") or {}).get("param") == name
                 for k in [nid] + list(self._same_type_selected(nid)) for i in self.graph.node_def(self.graph.nodes[k])["inputs"]):
            self._sync_pos(); self.rebuild()                # a pin it reads comes or goes (Math's b)
        if self.graph.nodes[nid]["type"] in ("Graph input", "Graph output") and name in ("name", "type"):
            if name == "type":
                # the pin changed type: its wires no longer fit
                self.graph.links = [l for l in self.graph.links if l[0] != nid and l[2] != nid]
            self.rebuild()
        elif name == "name" and (self.graph.nodes[nid]["type"] in G.SENDS or self.graph.nodes[nid]["type"] in G.RECEIVES):
            t = self.graph.nodes[nid]["type"]
            dpg.configure_item(f"gnode_{nid}", label=f"{t}: {val}")   # the title names the pair
        elif name == "label" and nodeface.is_meta(self.graph.nodes[nid]["type"], name) and dpg.does_item_exist(f"gnode_{nid}"):
            n = self.graph.nodes[nid]
            dpg.configure_item(f"gnode_{nid}", label=self.node_title(n, self.graph.node_def(n)))   # "Speed: Rise"

    def set_param(self, nid, name, val):
        """A setting changed from outside the node (a tutorial's "Try this"): one undo step, the
        node's fields and the properties follow, and the graph is rebuilt as after any edit -
        a setting changes the code, so there is no live poke for it."""
        n = self.graph.nodes.get(nid) if self.graph else None
        if n is None:
            return False
        self.touch(); self.snapshot(("param", nid, name))
        n["params"][name] = val
        self._mirror(None, nid, name, val)
        self._refresh_summary(nid)
        if any((i.get("when") or {}).get("param") == name for i in self.graph.node_def(n)["inputs"]):
            self._sync_pos(); self.rebuild()                # a pin it reads comes or goes
        if not self.auto:
            self.app.build_current()                       # seen at once, Live on or off
        return True

    def _make_link(self, a, out, b, inp):
        ta, tb = self._pins.get((a, "out", out)), self._pins.get((b, "in", inp))
        if not ta or not tb:
            return
        lid = dpg.add_node_link(ta, tb, parent="node_editor")
        meta = self.graph.link_meta.get((b, inp)) or {}
        col = meta.get("color")
        thin = self.scopes().get(a) == "frame"           # control rate: one value a frame, drawn thinner
        if col or thin:
            th = self._wire_theme(tuple(col) if col else GU.PIN_COL.get(self._ptype.get(ta, "float"), GU.PIN_COL["float"]), thin=thin)
        else:
            th = self.themes().link[self._ptype.get(ta, "float")]
        dpg.bind_item_theme(lid, th)
        self.links[lid] = (b, inp)
        self._link_normal[lid] = th
        base = tuple(col) if col else GU.PIN_COL.get(self._ptype.get(ta, "float"), GU.PIN_COL["float"])
        self._link_style[lid] = (tuple(base[:3]), thin)
        self._show_input(b, inp, True)

    def _wire_theme(self, col, thin=False, mode="normal"):
        """A wire's theme: its colour; thin for a frame-scope source (a
        value once a frame - control rate - against the per-pixel wires).
        `mode` "lit" - a node's own wires while it is under the pointer or
        selected: brighter and thicker - or "faded": every other wire
        meanwhile, a trace of its colour."""
        light = self._light()
        key = (tuple(col[:3]), thin, self.zoom if (thin or mode == "lit") else None, light, mode)
        th = self._wire_themes.get(key)
        if th is None:
            shown = tuple(int(c * 0.8) for c in col[:3]) if light else tuple(col[:3])   # a touch darker on a light canvas
            if mode == "lit":                        # toward white on a dark canvas, deeper on a light one
                shown = tuple(int(c * 0.72) for c in shown) if light else tuple(int(c + (255 - c) * 0.35) for c in shown)
            alpha = int(255 * GU.WIRE_FADE) if mode == "faded" else 255
            with dpg.theme() as th:
                with dpg.theme_component(dpg.mvNodeLink):
                    dpg.add_theme_color(dpg.mvNodeCol_Link, shown + (alpha,), category=dpg.mvThemeCat_Nodes)
                    dpg.add_theme_color(dpg.mvNodeCol_LinkHovered, (255, 255, 255), category=dpg.mvThemeCat_Nodes)
                    dpg.add_theme_color(dpg.mvNodeCol_LinkSelected, (255, 255, 255), category=dpg.mvThemeCat_Nodes)
                    if thin or mode == "lit":
                        dpg.add_theme_style(dpg.mvNodeStyleVar_LinkThickness,
                                            max(1.0, (1.4 if thin else 3.0) * self.zoom * (GU.WIRE_LIT if mode == "lit" else 1.0)),
                                            category=dpg.mvThemeCat_Nodes)
            self._wire_themes[key] = th
        return th

    def scopes(self):
        """{nid: "frame" | "pixel"} for the graph as it is now, from the
        plan (no codegen); cached until the next edit; {} when the graph
        cannot be planned."""
        if not self.graph:
            return {}
        c = self._scope_cache
        if c and c[0] == self.edits and c[2] is self.graph:
            return c[1]
        try:
            _, _, scope, _, _, _ = self.graph.plan()
        except Exception:
            oops.swallowed()
            scope = {}
        if scope and self.graph.has_sends():
            # the plan joins the pairs away: a Send takes what feeds it, a Receive its Send
            src = {(b, i): a for a, _, b, i in self.graph.links}
            for nid, n in self.graph.nodes.items():
                if n["type"] in G.SENDS:
                    scope[nid] = scope.get(src.get((nid, "in")), "frame")
            for rcv, snd in self.graph._send_pairs().items():
                scope[rcv] = scope.get(snd, "frame")
        self._scope_cache = (self.edits, scope, self.graph)
        return scope
