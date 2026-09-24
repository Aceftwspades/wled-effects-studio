"""What a node draws on its face - the part of GraphPanel that makes the
graph read like a rack. A mixin: graph_ui's GraphPanel inherits it.

Static glyphs are drawn from the node's typed values (nodeface.py does
the sums) and redrawn when a value changes: a transfer curve on the
one-in one-out maths nodes, colour strips, pattern thumbnails, a
bitmap's pixels, an image, a text, a path. Live glyphs follow the
running effect through the probes the build plants: the audio bars,
a dot riding the Wave, the marker on a strip, the Noise scrolling with
its z, the lit step of a Steps node, sparklines, the Scope node's plot,
and the plot beside a hovered pin. Every probe's last ten seconds are
kept in one ring buffer, recorded once a frame.
"""
import math
import os

import numpy as np
import dearpygui.dearpygui as dpg

from native import nodeface
from native.textures import registry

HIST_N = 600            # samples kept per probe: ten seconds at 60 frames
HIST_MAX = 256          # probes a build can plant (graph.py)
PATCH = (48, 24)        # a thumbnail's texture, px
GLOW_S = 0.15           # a light's afterglow, seconds


class Glyphs:
    # the node types that draw a glyph (the panel asks `in self.GLYPHS`)
    GLYPHS = frozenset(["Palette", "Audio", "Spectrum", "FFT bin", "Wave", "Noise", "Colour ramp", "Blackbody", "Colour pick",
                        "Bitmap", "States", "Image", "Text", "Path", "Scope"]
                       + list(nodeface.PATTERNS) + [k for k, v in nodeface.TRANSFER.items() if v[0]] + list(nodeface.SPARK))
    STRIPS = ("Palette", "Colour ramp", "Blackbody", "Colour pick")

    def _glyph_init(self):
        self._live_glyphs = {}          # nid -> kind: what _poll_glyphs updates
        self._glyph_bufs = {}           # nid -> the texture's buffer (kept alive)
        self._hist = np.zeros((HIST_MAX, HIST_N), np.float32)
        self._hist_i = 0
        self._hist_n = 0
        self._hist_for = None           # the build the ring holds values of
        self._lit = {}                  # (nid, out) -> when a bool output was last on
        self._hover_out = None          # (nid, out) whose plot the readouts draw
        self._step_lit = {}             # nid -> (widget, k) lit on a Steps node

    def _glyph_clear(self):
        self._live_glyphs.clear(); self._glyph_bufs.clear(); self._step_lit.clear()

    # --- the probes' history ---------------------------------------------------------------
    def _record_probes(self):
        """Every probe's value this frame into the ring, when the effect on
        screen is this graph's last build (else the ring is left, and
        starts over when the build comes back)."""
        probes = getattr(self, "_probes", None)
        pf = getattr(self, "_probes_for", None)
        if not probes or not pf or not self.graph:
            return False
        eng = self.app.eng
        if not eng.names or eng.names[eng.idx] != self.app.project.effect_title(pf):
            return False
        if self._hist_for is not pf and self._hist_for != pf:
            self._hist[:] = 0.0; self._hist_n = 0; self._hist_for = pf
        i = self._hist_i
        for k in probes:
            if k < HIST_MAX:
                self._hist[k, i] = eng.probe(k)
        self._hist_i = (i + 1) % HIST_N
        self._hist_n = min(HIST_N, self._hist_n + 1)
        return True

    def _probe_k(self, nid, kind, name):
        """The probe of an output, or of an input's source; None when none."""
        probes = getattr(self, "_probes", None) or {}
        if kind == "in":
            src = next(((l[0], l[1]) for l in self.graph.links if l[2] == nid and l[3] == name), None)
            if src is None:
                return None
            nid, name = src
        return next((k for k, v in probes.items() if v == (nid, name)), None)

    def _probe_now(self, k):
        if k is None or self._hist_n == 0:
            return None
        return float(self._hist[k, (self._hist_i - 1) % HIST_N])

    def _series(self, k, n):
        """The last n samples of probe k, oldest first (fewer while the ring fills)."""
        n = max(2, min(HIST_N, int(n), self._hist_n))
        i = self._hist_i
        idx = (np.arange(i - n, i) % HIST_N)
        return self._hist[k, idx]

    def _live_in(self, nid, name, default):
        """An input's value now: its source's probe, else what is typed."""
        k = self._probe_k(nid, "in", name)
        v = self._probe_now(k)
        if v is not None:
            return v
        n = self.graph.nodes[nid]
        try:
            return float(n.get("inputs", {}).get(name, default))
        except (TypeError, ValueError):
            return default

    def _frame_source(self, nid, name):
        """True when the input's source runs once a frame (a per-pixel one
        has no single value to show)."""
        src = next((l[0] for l in self.graph.links if l[2] == nid and l[3] == name), None)
        if src is None:
            return True
        return (getattr(self, "_probe_scope", {}) or {}).get(src) == "frame"

    # --- making the glyph -------------------------------------------------------------------
    def _wired_of(self, nid):
        return {i for b, i in ((l[2], l[3]) for l in self.graph.links) if b == nid}

    def _glyph_widget(self, nid, n):
        """The glyph under the node's fields, made inside a static attribute."""
        t = n["type"]
        W = self.px(150)
        d = self.graph.node_def(n)
        tag = f"gglyph_{nid}"
        if t in self.STRIPS:
            with dpg.drawlist(width=W, height=self.px(10), tag=tag):
                pass
            self._live_glyphs[nid] = "strip"
        elif t in ("Audio", "Spectrum", "FFT bin"):
            H = self.px(22)
            with dpg.drawlist(width=W, height=H, tag=tag):
                for k in range(16):
                    x0 = k * W / 16
                    dpg.draw_rectangle((x0 + 1, H - 1), (x0 + W / 16 - 1, H - 1), color=(0, 0, 0, 0), fill=self.pal()["live_line"], tag=f"{tag}_{k}")
            self._live_glyphs[nid] = "bars"
        elif t == "Wave":
            with dpg.drawlist(width=W, height=self.px(22), tag=tag):
                pass
            self._live_glyphs[nid] = "wave"
        elif t == "Noise" or t in nodeface.PATTERNS or t == "Image":
            self._patch_texture(nid)
            dpg.add_image(f"{tag}_tex", width=self.px(PATCH[0]), height=self.px(PATCH[1]), tag=tag)
            if t == "Noise":
                self._live_glyphs[nid] = "noise"
        elif t in nodeface.TRANSFER:
            with dpg.drawlist(width=W, height=self.px(28), tag=tag):
                pass
        elif t in ("Bitmap", "States"):
            rows, cell = self._bitmap_cells(n, W)
            with dpg.drawlist(width=W, height=max(2, cell * len(rows)), tag=tag):
                pass
        elif t == "Text":
            with dpg.drawlist(width=W, height=self.px(22), tag=tag):
                pass
        elif t == "Path":
            with dpg.drawlist(width=W, height=self.px(36), tag=tag):
                pass
        elif t == "Scope":
            with dpg.drawlist(width=W, height=self.px(48), tag=tag):
                pass
            self._live_glyphs[nid] = "scope"
        elif t in nodeface.SPARK:
            with dpg.drawlist(width=W, height=self.px(22), tag=tag):
                pass
            self._live_glyphs[nid] = "spark"
        else:
            return
        self._glyph_draw(nid, n, d)

    def _patch_texture(self, nid):
        tag = f"gglyph_{nid}_tex"
        if not dpg.does_item_exist(tag):
            buf = np.zeros((PATCH[1], PATCH[0], 4), np.float32); buf[..., 3] = 1.0
            self._glyph_bufs[nid] = buf
            dpg.add_raw_texture(PATCH[0], PATCH[1], buf.reshape(-1), format=dpg.mvFormat_Float_rgba, tag=tag, parent=registry())
        elif nid not in self._glyph_bufs:
            buf = np.zeros((PATCH[1], PATCH[0], 4), np.float32); buf[..., 3] = 1.0
            self._glyph_bufs[nid] = buf
        return tag

    def _patch_set(self, nid, a, tint=(0.25, 0.35, 0.55), gain=(0.6, 0.55, 0.45)):
        """A 0..1 patch onto the node's texture, in the studio's blue."""
        buf = self._glyph_bufs.get(nid)
        tag = f"gglyph_{nid}_tex"
        if buf is None or not dpg.does_item_exist(tag):
            return
        a = np.asarray(a, np.float32)
        if a.ndim == 2:
            for c in range(3):
                buf[..., c] = tint[c] + gain[c] * a
        else:
            buf[..., :3] = a[..., :3]
        dpg.set_value(tag, buf.reshape(-1))

    def _refresh_glyph(self, nid):
        """A typed value or setting changed: the static face again."""
        if not self.graph or nid not in self.graph.nodes or not dpg.does_item_exist(f"gglyph_{nid}"):
            return
        n = self.graph.nodes[nid]
        try:
            d = self.graph.node_def(n)
        except Exception:
            return
        self._glyph_draw(nid, n, d)

    def _glyph_draw(self, nid, n, d):
        t = n["type"]
        tag = f"gglyph_{nid}"
        wired = self._wired_of(nid)
        if t in self.STRIPS:
            self._draw_strip(nid, n, d, wired)
        elif t == "Wave":
            self._draw_wave(nid, n, d, wired)
        elif t == "Noise" or t in nodeface.PATTERNS:
            a = nodeface.pattern(n, d, wired, PATCH)
            if a is not None:
                self._patch_set(nid, a)
        elif t == "Image":
            self._draw_image(nid, n)
        elif t in nodeface.TRANSFER:
            self._draw_transfer(nid, n, d, wired)
        elif t in ("Bitmap", "States"):
            self._draw_bitmap(nid, n, d)
        elif t == "Text":
            dpg.delete_item(tag, children_only=True)
            text = str(n["params"].get("text", ""))
            dpg.draw_text((2, 1), text[:24], size=self.px(18), color=self.pal()["text"], parent=tag)
        elif t == "Path":
            self._draw_path(nid, n, d)
        elif t == "Scope" or t in nodeface.SPARK:
            self._draw_spark(nid, [], None, None, scope=(t == "Scope"))

    # --- the static faces ----------------------------------------------------------------------
    def _draw_strip(self, nid, n, d, wired):
        tag = f"gglyph_{nid}"
        dpg.delete_item(tag, children_only=True)
        W, H = dpg.get_item_configuration(tag)["width"], dpg.get_item_configuration(tag)["height"]
        if n["type"] == "Palette":
            try:
                cols = self.app.eng.palette_swatch(self.app.eng.pal, 24)
            except Exception:
                return
        else:
            cols = nodeface.ramp_strip(n, d, 24)
        if not cols:
            return
        k = len(cols)
        for i, (r, g, b) in enumerate(cols):
            dpg.draw_rectangle((i * W / k, 0), ((i + 1) * W / k + 1, H), color=(0, 0, 0, 0), fill=(r, g, b, 255), parent=tag)
        m = nodeface.strip_marker(n, d, wired)
        x = 0.0 if m is None else m * W
        dpg.draw_line((x, 0), (x, H), color=(255, 255, 255, 230 if m is not None else 0), thickness=max(1, self.px(1.5)), parent=tag, tag=f"{tag}_mark")

    @staticmethod
    def _wave_y(shape, x):
        if shape == "sine":
            return 0.5 + 0.5 * math.sin(x * 2 * math.pi)
        if shape == "triangle":
            return 1.0 - abs(2.0 * x - 1.0)
        if shape == "square":
            return 1.0 if x < 0.5 else 0.0
        return x                                            # saw

    def _draw_wave(self, nid, n, d, wired):
        tag = f"gglyph_{nid}"
        dpg.delete_item(tag, children_only=True)
        W, H = dpg.get_item_configuration(tag)["width"], dpg.get_item_configuration(tag)["height"]
        shape = str(n["params"].get("shape", "sine"))
        pts = [(x * (W - 2) + 1, (1.0 - self._wave_y(shape, x)) * (H - 6) + 3) for x in (k / 40.0 for k in range(41))]
        dpg.draw_polyline(pts, color=self.pal()["live_line"], thickness=max(1, self.px(1.5)), parent=tag)
        dpg.draw_circle((-10, -10), max(2, self.px(3)), color=(0, 0, 0, 0), fill=self.pal()["point"], parent=tag, tag=f"{tag}_dot")

    def _draw_transfer(self, nid, n, d, wired):
        tag = f"gglyph_{nid}"
        dpg.delete_item(tag, children_only=True)
        W, H = dpg.get_item_configuration(tag)["width"], dpg.get_item_configuration(tag)["height"]
        pts = nodeface.transfer(n, d, wired)
        if not pts:
            return
        ys = [y for _, y in pts]
        lo, hi = min(ys), max(ys)
        if hi - lo < 1e-9:
            lo, hi = lo - 0.5, hi + 0.5
        # the baseline (y = 0) when it is in range, so the curve's sign reads
        if lo < 0.0 < hi:
            by = 2 + (1.0 - (0.0 - lo) / (hi - lo)) * (H - 4)
            dpg.draw_line((1, by), (W - 1, by), color=self.pal()["grid"], parent=tag)
        poly = [(1 + k * (W - 2) / (len(pts) - 1), 2 + (1.0 - (y - lo) / (hi - lo)) * (H - 4)) for k, (_, y) in enumerate(pts)]
        dpg.draw_polyline(poly, color=self.pal()["live_line"], thickness=max(1, self.px(1.5)), parent=tag)
        size = max(7, self.px(9))
        if size >= 8:
            dpg.draw_text((W - 26 * size / 9, 0), nodeface._fmt(hi), size=size, color=self.pal()["dim"], parent=tag)
            dpg.draw_text((W - 26 * size / 9, H - size - 1), nodeface._fmt(lo), size=size, color=self.pal()["dim"], parent=tag)

    TINTS = [(235, 235, 235), (110, 190, 250), (250, 170, 90), (170, 230, 120), (250, 110, 120), (190, 120, 235),
             (250, 230, 100), (90, 220, 210), (240, 150, 200), (160, 160, 90)]

    def _bitmap_cells(self, n, W):
        """The rows of a Bitmap (a States node's first state) and the cell
        size that fits them under the node: at most 10 px, at most 60 tall."""
        text = str(n["params"].get("rows" if n["type"] == "Bitmap" else "states", "")).split("|")[0].replace("\n", "/")
        rows = [r for r in text.split("/")] or ["0"]
        w = max(1, max(len(r) for r in rows))
        cell = max(2, min(self.px(10), int(W / w), int(self.px(60) / max(1, len(rows)))))
        return rows, cell

    def _draw_bitmap(self, nid, n, d):
        tag = f"gglyph_{nid}"
        dpg.delete_item(tag, children_only=True)
        W = dpg.get_item_configuration(tag)["width"]
        rows, cell = self._bitmap_cells(n, W)
        dpg.configure_item(tag, height=max(2, cell * len(rows)))
        for r, row in enumerate(rows):
            for c, ch in enumerate(row):
                on = ch.isdigit()
                fill = self.TINTS[int(ch)] + (255,) if on else (28, 30, 36, 255)
                dpg.draw_rectangle((c * cell, r * cell), ((c + 1) * cell - 1, (r + 1) * cell - 1), color=(0, 0, 0, 0), fill=fill, parent=tag)

    def _draw_image(self, nid, n):
        path = str(n["params"].get("file", "") or "")
        if not path:
            self._patch_set(nid, np.zeros((PATCH[1], PATCH[0]), np.float32)); return
        cands = [path, os.path.join(self.app.project.path, path)]
        try:
            from PIL import Image
            p = next((c for c in cands if os.path.isfile(c)), None)
            if p is None:
                raise FileNotFoundError(path)
            im = Image.open(p).convert("RGB")
            im.thumbnail(PATCH)
            canvas = Image.new("RGB", PATCH, (20, 22, 27))
            canvas.paste(im, ((PATCH[0] - im.width) // 2, (PATCH[1] - im.height) // 2))
            a = np.asarray(canvas, np.float32) / 255.0
            self._patch_set(nid, a)
        except Exception:
            self._patch_set(nid, np.zeros((PATCH[1], PATCH[0]), np.float32))

    def _draw_path(self, nid, n, d):
        tag = f"gglyph_{nid}"
        dpg.delete_item(tag, children_only=True)
        W, H = dpg.get_item_configuration(tag)["width"], dpg.get_item_configuration(tag)["height"]
        pts = []
        for chunk in str(n["params"].get("points", "")).split(";"):
            try:
                xs = [float(v) for v in chunk.split(",")]
                if len(xs) >= 2:
                    pts.append((xs[0], xs[1]))
            except ValueError:
                continue
        if len(pts) < 2:
            return
        if n["params"].get("closed"):
            pts.append(pts[0])
        x0, x1 = min(p[0] for p in pts), max(p[0] for p in pts)
        y0, y1 = min(p[1] for p in pts), max(p[1] for p in pts)
        sx, sy = (x1 - x0) or 1.0, (y1 - y0) or 1.0
        s = min((W - 6) / sx, (H - 6) / sy)
        ox, oy = (W - sx * s) / 2, (H - sy * s) / 2
        poly = [(ox + (x - x0) * s, H - oy - (y - y0) * s) for x, y in pts]
        dpg.draw_polyline(poly, color=self.pal()["live_line"], thickness=max(1, self.px(1.5)), parent=tag)
        dpg.draw_circle(poly[0], max(2, self.px(2.5)), color=(0, 0, 0, 0), fill=self.pal()["point"], parent=tag)

    def _draw_spark(self, nid, ys, lo, hi, scope=False):
        """A rolling plot in the node: the samples given (oldest first)
        over the range lo..hi (autoscaled when None); the Scope's has its
        min and max written."""
        tag = f"gglyph_{nid}"
        if not dpg.does_item_exist(tag):
            return
        W, H = dpg.get_item_configuration(tag)["width"], dpg.get_item_configuration(tag)["height"]
        if not dpg.does_item_exist(f"{tag}_line"):
            dpg.delete_item(tag, children_only=True)
            P = self.pal()
            dpg.draw_rectangle((0, 0), (W, H), color=(0, 0, 0, 0), fill=P["plot_bg"], parent=tag)
            dpg.draw_polyline([(0, H / 2), (W, H / 2)], color=P["live_line"], thickness=max(1, self.px(1.2)), parent=tag, tag=f"{tag}_line")
            if scope:
                dpg.draw_text((2, 0), "", size=max(8, self.px(9)), color=P["dim"], parent=tag, tag=f"{tag}_hi")
                dpg.draw_text((2, H - max(8, self.px(9)) - 1), "", size=max(8, self.px(9)), color=P["dim"], parent=tag, tag=f"{tag}_lo")
        if len(ys) < 2:
            return
        if lo is None or hi is None:
            lo, hi = float(min(ys)), float(max(ys))
            if hi - lo < 1e-6:
                lo, hi = lo - 0.5, hi + 0.5
        pts = [(k * (W - 2) / (len(ys) - 1) + 1, 2 + (1.0 - (min(hi, max(lo, float(y))) - lo) / (hi - lo)) * (H - 4)) for k, y in enumerate(ys)]
        dpg.configure_item(f"{tag}_line", points=pts)
        if scope and dpg.does_item_exist(f"{tag}_hi"):
            dpg.configure_item(f"{tag}_hi", text=nodeface._fmt(hi))
            dpg.configure_item(f"{tag}_lo", text=nodeface._fmt(lo))

    # --- each frame: the live ones -------------------------------------------------------------
    def _poll_glyphs(self):
        if not self.graph or self.zoom < 0.7 or not self._live_glyphs:
            return
        eng = self.app.eng
        if getattr(self, "_glyph_pal", None) != eng.pal:
            self._glyph_pal = eng.pal
            for nid, n in self.graph.nodes.items():
                if n["type"] == "Palette":
                    self._refresh_glyph(nid)
        try:
            bands = [float(v) / 255.0 for v in eng.fft]
        except Exception:
            bands = None
        frame = (self._hist_i - 1) % HIST_N
        for nid, kind in list(self._live_glyphs.items()):
            tag = f"gglyph_{nid}" if kind != "steps" else f"gnode_{nid}"    # a Steps node's face is its sliders
            if not dpg.does_item_exist(tag) or nid not in self.graph.nodes:
                self._live_glyphs.pop(nid, None); continue
            n = self.graph.nodes[nid]
            try:
                if kind == "bars":
                    self._poll_bars(nid, n, tag, bands)
                elif kind == "wave":
                    self._poll_wave(nid, n, tag)
                elif kind == "strip":
                    self._poll_strip(nid, n, tag)
                elif kind == "noise":
                    self._poll_noise(nid, n, frame)
                elif kind == "steps":
                    self._poll_steps(nid, n)
                elif kind in ("spark", "scope"):
                    self._poll_spark(nid, n, kind == "scope")
            except Exception as e:
                self._live_glyphs.pop(nid, None)
                print(f"glyph {kind} on node {nid} stopped: {e!r}")

    def _poll_bars(self, nid, n, tag, bands):
        if bands is None:
            return
        H = dpg.get_item_configuration(tag)["height"]; W = dpg.get_item_configuration(tag)["width"]
        mine = int(n["params"].get("bin", -1)) if n["type"] == "FFT bin" else -1
        for k, v in enumerate(bands[:16]):
            bt = f"{tag}_{k}"
            if dpg.does_item_exist(bt):
                x0 = k * W / 16
                dpg.configure_item(bt, pmin=(x0 + 1, H - 1 - v * (H - 2)), pmax=(x0 + W / 16 - 1, H - 1),
                                   fill=(255, 190, 70, 240) if k == mine else self.pal()["live_line"])

    def _poll_wave(self, nid, n, tag):
        dot = f"{tag}_dot"
        if not dpg.does_item_exist(dot):
            return
        if not self._frame_source(nid, "x") or self._probe_k(nid, "in", "x") is None and "x" in self._wired_of(nid):
            dpg.configure_item(dot, center=(-10, -10)); return
        x = self._live_in(nid, "x", 0.0)
        cyc = self._live_in(nid, "cycles", 3.0)
        ph = self._live_in(nid, "phase", 0.0)
        f = x * cyc + ph
        f -= math.floor(f)
        W, H = dpg.get_item_configuration(tag)["width"], dpg.get_item_configuration(tag)["height"]
        y = self._wave_y(str(n["params"].get("shape", "sine")), f)
        dpg.configure_item(dot, center=(f * (W - 2) + 1, (1.0 - y) * (H - 6) + 3))

    def _poll_strip(self, nid, n, tag):
        mark = f"{tag}_mark"
        if not dpg.does_item_exist(mark):
            return
        pin = {"Palette": "index", "Colour ramp": "t", "Blackbody": "kelvin", "Colour pick": "index"}[n["type"]]
        k = self._probe_k(nid, "in", pin)
        if k is None or not self._frame_source(nid, pin):
            return                                          # typed: the marker drawn with the strip stands
        v = self._probe_now(k)
        if v is None:
            return
        d = self.graph.node_def(n)
        m = nodeface.strip_marker(n, d, self._wired_of(nid), live=v)
        if m is None:
            return
        W, H = dpg.get_item_configuration(tag)["width"], dpg.get_item_configuration(tag)["height"]
        dpg.configure_item(mark, p1=(m * W, 0), p2=(m * W, H), color=(255, 255, 255, 230))

    def _poll_noise(self, nid, n, frame):
        if frame % 2:
            return                                          # every other frame is plenty for a thumbnail
        k = self._probe_k(nid, "in", "z")
        if k is None or not self._frame_source(nid, "z"):
            return
        z = self._probe_now(k)
        if z is None or abs(z - getattr(self, "_noise_z", {}).get(nid, 1e9)) < 1e-4:
            return
        self.__dict__.setdefault("_noise_z", {})[nid] = z
        d = self.graph.node_def(n)
        live = {"z": z}
        for pin in ("scale",):
            kk = self._probe_k(nid, "in", pin)
            if kk is not None:
                live[pin] = self._probe_now(kk)
        a = nodeface.pattern(n, d, self._wired_of(nid), PATCH, live=live)
        if a is not None:
            self._patch_set(nid, a)

    def _lit_theme(self):
        light = self.pal()["light"]
        th = self._node_themes.get(("lit", light))
        if th is None:
            # the step playing now: an accent field, its grab in the ink that reads on it
            bg = (150, 190, 230, 255) if light else (70, 110, 150, 255)
            grab = (30, 60, 100, 255) if light else (240, 244, 250, 255)
            with dpg.theme() as th:
                with dpg.theme_component(dpg.mvAll):
                    dpg.add_theme_color(dpg.mvThemeCol_FrameBg, bg)
                    dpg.add_theme_color(dpg.mvThemeCol_SliderGrab, grab)
            self._node_themes[("lit", light)] = th
        return th

    def _poll_steps(self, nid, n):
        k = self._probe_k(nid, "out", "step")
        v = self._probe_now(k)
        if v is None:
            return
        step = int(round(v)) + 1
        was = self._step_lit.get(nid)
        if was and was[1] == step:
            return
        if was and dpg.does_item_exist(was[0]):
            dpg.bind_item_theme(was[0], self._field_theme() if hasattr(self, "_field_theme") else 0)
        w = next((w for w in self._widgets if dpg.does_item_exist(w) and dpg.get_item_user_data(w) == (nid, f"s{step}")), None)
        if w is not None:
            dpg.bind_item_theme(w, self._lit_theme())
            self._step_lit[nid] = (w, step)

    def _poll_spark(self, nid, n, scope):
        if scope:
            k = self._probe_k(nid, "in", "x")
            secs = float(n["params"].get("seconds", 3.0) or 3.0)
        else:
            k = self._probe_k(nid, "out", nodeface.SPARK[n["type"]])
            secs = nodeface.SPARK_SECONDS
        if k is None or self._hist_n < 2:
            return
        ys = self._series(k, secs * 60.0)
        if len(ys) > 120:
            ys = ys[:: max(1, len(ys) // 120)]
        rng = None if scope else nodeface.out_range(n, self.graph.node_def(n), nodeface.SPARK[n["type"]])
        lo, hi = (None, None) if rng is None else rng
        self._draw_spark(nid, list(ys), lo, hi, scope=scope)

    # --- lights, meters and the hover plot, drawn with the readouts ------------------------------
    def _light_level(self, nid, name, on, now):
        """A bool output's brightness: full while on, fading for GLOW_S after."""
        key = (nid, name)
        if on:
            self._lit[key] = now
            return 1.0
        last = self._lit.get(key)
        if last is None:
            return 0.0
        return max(0.0, 1.0 - (now - last) / GLOW_S)

    def _draw_hover_plot(self, pane, size):
        """The last three seconds of the hovered frame-scope output, in a
        box beside its pin; items go on the readouts' list."""
        ho = self._hover_out
        if not ho or not self.graph or self._hist_n < 2:
            return
        nid, name = ho
        k = self._probe_k(nid, "out", name)
        if k is None:
            return
        pt = self._pin_point(nid, "out", name)
        if not pt:
            return
        x0, y0, x1, y1 = pane
        W, H = self.px(150), self.px(46)
        bx = pt[0] + self.px(14)
        if bx + W > x1:
            bx = pt[0] - self.px(14) - W - self.px(60)
        by = min(max(y0, pt[1] - H / 2), y1 - H)
        ys = self._series(k, nodeface.SPARK_SECONDS * 60.0)
        if len(ys) > 150:
            ys = ys[:: max(1, len(ys) // 150)]
        lo, hi = float(min(ys)), float(max(ys))
        if hi - lo < 1e-6:
            lo, hi = lo - 0.5, hi + 0.5
        items = self._readout_items
        P = self.pal()
        items.append(dpg.draw_rectangle((bx, by), (bx + W, by + H), color=P["popup_edge"], fill=P["popup"], parent="wire_labels"))
        pts = [(bx + 1 + i * (W - 2) / (len(ys) - 1), by + 2 + (1.0 - (float(y) - lo) / (hi - lo)) * (H - 4)) for i, y in enumerate(ys)]
        items.append(dpg.draw_polyline(pts, color=P["live_line"], thickness=1.5, parent="wire_labels"))
        items.append(dpg.draw_text((bx + 3, by), nodeface._fmt(hi), size=size, color=P["dim"], parent="wire_labels"))
        items.append(dpg.draw_text((bx + 3, by + H - size - 1), nodeface._fmt(lo), size=size, color=P["dim"], parent="wire_labels"))
        items.append(dpg.draw_text((bx + W - 3 * size, by + H - size - 1), f"{nodeface.SPARK_SECONDS:g} s", size=size, color=P["dim"], parent="wire_labels"))

