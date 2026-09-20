"""The 3-D view on the GPU: the cube as textured faces, every other
geometry as a cloud of squares.

The software renderer (render.py) warps five faces per frame in numpy: 28 ms
at 620 px, the single biggest cost in the app. Dear PyGui's draw_image_quad
maps a texture onto a quad on the GPU, so the cube is drawn as textured
quads instead: each face split into N x N of them, sampling the net texture
(a sub-quad's texture mapping is affine, and eight across a face keeps the
perspective error under a pixel). The CPU projects (N + 1)^2 corners per face,
and only when the camera moves; every frame it uploads the net, which it
was doing for the flat view anyway.

    cube = CubeQuads("cube_win", tag="cube_img")     # a drawlist, sized later
    cube.resize(size)                                # the view's side, px
    cube.camera(yaw, pitch, dist, B)                 # when the camera moves
    ...the net texture is written by the app each frame

Sampling is bilinear (DPG offers no nearest filter), so the net is uploaded
at a few times its size to keep the LED grid crisp; see App.draw.

Every other geometry - a matrix, a strip, a sphere, a shape built of parts
- is PointQuads: an LED is a screen-aligned square (a draw_image_quad too)
whose colour is one texel of a colour texture, N LEDs wide, written once a
frame in one call. The squares are placed - far first, so nearer ones
cover - only when the camera moves; a frame then costs the one upload,
where the software point renderer (render.render_points) loops over every
LED in Python.

    cloud = PointQuads("cube_win", tag="cube_img", pos)   # pos (n, 3), NaN rows skipped
    cloud.resize(size); cloud.camera(yaw, pitch, dist); cloud.colours(rgb)
"""
import numpy as np
import dearpygui.dearpygui as dpg

from native.render import FACES6 as FACES, _camera

N = 8            # sub-quads across a face
FOV = 38.0


class CubeQuads:
    def __init__(self, parent, tag, texture):
        self.tag = tag
        self.texture = texture
        self.size = 0
        self.w = self.h = 0
        self.items = {}          # face index -> list of quad ids, row-major
        self._last = None
        with dpg.drawlist(width=10, height=10, tag=tag, parent=parent):
            z = (0, 0)
            # a background picture, drawn first so the faces cover it (see background())
            self.bg_item = dpg.draw_image(texture, z, z, show=False)
            self.bg_key = None
            for fi, fc in enumerate(FACES):
                quads = []
                bx, by = fc["bx"], fc["by"]
                for j in range(N):
                    for i in range(N):
                        u0, u1 = (bx + i / N) / 3.0, (bx + (i + 1) / N) / 3.0
                        v0, v1 = (by + j / N) / 3.0, (by + (j + 1) / N) / 3.0
                        quads.append(dpg.draw_image_quad(texture, z, z, z, z, uv1=(u0, v0), uv2=(u1, v0),
                                                         uv3=(u1, v1), uv4=(u0, v1), show=False))
                self.items[fi] = quads

    def set_texture(self, texture):
        if texture == self.texture:
            return
        self.texture = texture
        for quads in self.items.values():
            for q in quads:
                dpg.configure_item(q, texture_tag=texture)

    def resize(self, size, w=None, h=None):
        """The cube's square, and the drawlist it sits centred in (a
        drawlist ignores a position, so it fills its pane instead)."""
        w, h = max(size, w or size), max(size, h or size)
        if (size, w, h) != (self.size, self.w, self.h):
            self.size, self.w, self.h = size, w, h
            dpg.configure_item(self.tag, width=w, height=h)
            self._last = None

    def background(self, picture):
        """A (size, size, 3) picture behind the cube, centred like the cube
        is; None (or a colour) takes it away. A texture of its own, remade
        when the picture or the size changes."""
        if not isinstance(picture, np.ndarray) or picture.ndim != 3 or not self.size:
            if self.bg_key is not None:
                dpg.configure_item(self.bg_item, show=False); self.bg_key = None
            return
        key = (id(picture), self.size, self.w, self.h)
        if key == self.bg_key:
            return
        self.bg_key = key
        h, w = picture.shape[:2]
        rgba = np.ones((h, w, 4), np.float32); rgba[:, :, :3] = picture.astype(np.float32) / 255.0
        tex = f"{self.tag}_bg"
        if dpg.does_item_exist(tex):
            cfg = dpg.get_item_configuration(tex)
            if (cfg.get("width"), cfg.get("height")) == (w, h):
                dpg.set_value(tex, rgba.ravel())
            else:
                dpg.delete_item(tex)
        if not dpg.does_item_exist(tex):
            with dpg.texture_registry():
                dpg.add_dynamic_texture(w, h, rgba.ravel(), tag=tex)
        ox, oy = (self.w - self.size) * 0.5, (self.h - self.size) * 0.5
        dpg.configure_item(self.bg_item, texture_tag=tex, pmin=(ox, oy), pmax=(ox + self.size, oy + self.size), show=True)

    def camera(self, yaw, pitch, dist, six=False):
        """Project every corner; a face pointing away is hidden, and so is
        the bottom unless the cube has six. Nothing is touched when the
        camera and size are as they were."""
        key = (round(yaw, 4), round(pitch, 4), round(dist, 3), self.size, self.w, self.h, bool(six))
        if key == self._last or not self.size:
            return
        self._last = key
        size = self.size
        eye, R = _camera(yaw, pitch, dist)
        f = (size * 0.5) / np.tan(np.radians(FOV) * 0.5)
        a = np.linspace(-1.0, 1.0, N + 1)
        for fi, fc in enumerate(FACES):
            c = fc["corners"]
            centre = c.mean(axis=0)
            quads = self.items[fi]
            if np.dot(centre, centre - eye) >= 0 or (fi == 5 and not six):
                for q in quads:
                    dpg.configure_item(q, show=False)
                continue
            # the face's corners span a, b in -1..1 the way the net block does
            o, ea, eb = c[0], c[1] - c[0], c[3] - c[0]
            aa, bb = np.meshgrid(a, a)                            # (N+1, N+1): bb rows, aa cols
            pts = o + ((aa + 1) / 2)[..., None] * ea + ((bb + 1) / 2)[..., None] * eb
            cam = (pts.reshape(-1, 3) - eye) @ R.T
            if np.any(cam[:, 2] > -0.05):
                for q in quads:
                    dpg.configure_item(q, show=False)
                continue
            sx = (self.w - size) * 0.5 + size * 0.5 + f * cam[:, 0] / -cam[:, 2]
            sy = (self.h - size) * 0.5 + size * 0.5 - f * cam[:, 1] / -cam[:, 2]
            scr = np.stack([sx, sy], 1).reshape(N + 1, N + 1, 2)
            k = 0
            for j in range(N):
                for i in range(N):
                    p1, p2, p3, p4 = scr[j, i], scr[j, i + 1], scr[j + 1, i + 1], scr[j + 1, i]
                    # grown a third of a pixel about its centre: two quads
                    # meeting on a non-integer edge otherwise leave a crack
                    cx, cy = (p1 + p2 + p3 + p4) / 4.0
                    p1, p2, p3, p4 = (q + np.sign(q - (cx, cy)) * 0.35 for q in (p1, p2, p3, p4))
                    dpg.configure_item(quads[k], p1=tuple(p1), p2=tuple(p2), p3=tuple(p3), p4=tuple(p4), show=True)
                    k += 1


class PointQuads:
    """Any geometry on the GPU: an LED a square, its colour a texel."""
    LED = 0.42               # the fraction of the LED pitch an emitter covers, as render_points draws it
    COLS = 4096              # the colour texture's width; more LEDs than that take more rows

    def __init__(self, parent, tag, pos):
        self.tag = tag
        self.size = 0
        self.w = self.h = 0
        self._last = None
        self.bg_key = None
        self.pos = None
        self.n = 0
        self.tex = f"{tag}_col"
        with dpg.drawlist(width=10, height=10, tag=tag, parent=parent):
            pass
        self.bg_item = None          # made with the first texture, before the squares, so they cover it
        self.items = []
        self.set_points(pos)

    def set_points(self, pos):
        """The LEDs' positions: (n, 3), Z up, any units - fitted to the frame
        the way render_points fits them. A new count remakes the squares."""
        from native.render import frame_of
        pos = np.asarray(pos, np.float32).reshape(-1, 3)
        n = len(pos)
        if n != self.n:
            for q in self.items:
                dpg.delete_item(q)
            if dpg.does_item_exist(self.tex):
                dpg.delete_item(self.tex)
            self.n = n
            cols = min(max(1, n), self.COLS)
            rows = max(1, (n + cols - 1) // cols)
            self.cols, self.rows = cols, rows
            with dpg.texture_registry():
                dpg.add_dynamic_texture(cols, rows, [0.0, 0.0, 0.0, 1.0] * (cols * rows), tag=self.tex)
            z = (0, 0)
            if self.bg_item is None:
                self.bg_item = dpg.draw_image(self.tex, z, z, show=False, parent=self.tag)
            self.items = [dpg.draw_image_quad(self.tex, z, z, z, z, show=False, parent=self.tag) for _ in range(n)]
        self.pos = pos
        c, ext = frame_of(pos)
        self.P = (pos - c) * (1.0 / (ext or 1.0))
        self.ext = ext or 1.0
        self._last = None

    def resize(self, size, w=None, h=None):
        w, h = max(size, w or size), max(size, h or size)
        if (size, w, h) != (self.size, self.w, self.h):
            self.size, self.w, self.h = size, w, h
            dpg.configure_item(self.tag, width=w, height=h)
            self._last = None

    background = CubeQuads.background

    def camera(self, yaw, pitch, dist):
        """Every square placed for this camera, far first. Nothing is touched
        when the camera and size are as they were."""
        key = (round(yaw, 4), round(pitch, 4), round(dist, 3), self.size, self.w, self.h)
        if key == self._last or not self.size or self.n == 0:
            return
        self._last = key
        size = self.size
        eye, R = _camera(yaw, pitch, dist)
        cam = (self.P - eye) @ R.T
        depth = -cam[:, 2]
        ok = np.isfinite(depth) & (depth > 0.05)
        f = (size * 0.5) / np.tan(np.radians(FOV) * 0.5)
        d = np.where(ok, depth, 1.0)
        ox, oy = (self.w - size) * 0.5, (self.h - size) * 0.5
        sx = ox + size * 0.5 + f * cam[:, 0] / d
        sy = oy + size * 0.5 - f * cam[:, 1] / d
        half = np.maximum(1.0, (f * (self.LED / self.ext)) / d)
        order = np.argsort(np.where(ok, -depth, np.inf))          # far first; the NaN and behind-the-eye last
        cols, rows = self.cols, self.rows
        for k, i in enumerate(order):
            q = self.items[k]
            if not ok[i] or sx[i] + half[i] < 0 or sy[i] + half[i] < 0 or sx[i] - half[i] > self.w or sy[i] - half[i] > self.h:
                dpg.configure_item(q, show=False); continue
            x0, x1, y0, y1 = sx[i] - half[i], sx[i] + half[i], sy[i] - half[i], sy[i] + half[i]
            uv = ((int(i) % cols + 0.5) / cols, (int(i) // cols + 0.5) / rows)     # one texel's centre: one colour
            dpg.configure_item(q, p1=(x0, y0), p2=(x1, y0), p3=(x1, y1), p4=(x0, y1), uv1=uv, uv2=uv, uv3=uv, uv4=uv, show=True)

    def colours(self, rgb):
        """The LEDs' colours this frame: (n, 3) uint8, in the positions' order."""
        rgb = np.asarray(rgb).reshape(-1, 3)
        n = self.cols * self.rows
        buf = np.zeros((n, 4), np.float32); buf[:, 3] = 1.0
        m = min(len(rgb), self.n)
        buf[:m, :3] = rgb[:m].astype(np.float32) / 255.0
        dpg.set_value(self.tex, buf.ravel())
