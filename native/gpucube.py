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

from native.textures import registry

from native.render import FACES6 as FACES, Cam, floor_segments, FLOOR, FLOOR_POOL, FLOOR_STEP, UNLIT, UNLIT_BELOW, DOT_POINT

N = 8            # sub-quads across a face
FOV = 38.0


def _floor_items(parent):
    """The floor's segments, made hidden - after the background, before
    what stands on it (a drawlist draws in the order it was made); a pool
    of them, as a floor's step (a shape's round distances) sets how many
    it takes."""
    return [dpg.draw_line((0, 0), (0, 0), color=FLOOR + (0,), thickness=1, show=False, parent=parent)
            for _ in range(FLOOR_POOL)]


def _place_floor(items, on, z, cam, ox, oy, step=None):
    """The floor's segments for this camera: faint lines on the plane z,
    fading from the middle; hidden when it is off or seen from below.
    `step`: (step, origin) of its lines in the fitted space."""
    st, org = step or (FLOOR_STEP, (0.0, 0.0))
    segs = floor_segments(z, step=st, origin=org) if on and cam.eye[2] > z + 0.02 else []
    for k, q in enumerate(items):
        if k >= len(segs):
            dpg.configure_item(q, show=False); continue
        p0, p1, a = segs[k]
        sx, sy, ok, _ = cam.screen(np.stack([p0, p1]))
        if not ok.all():
            dpg.configure_item(q, show=False); continue
        dpg.configure_item(q, p1=(ox + sx[0], oy + sy[0]), p2=(ox + sx[1], oy + sy[1]), color=FLOOR + (int(255 * a),), show=True)


class CubeQuads:
    def __init__(self, parent, tag, texture):
        self.tag = tag
        self.texture = texture
        self.size = 0
        self.w = self.h = 0
        self.items = {}          # face index -> list of quad ids, row-major
        self._last = None
        self.floor = False       # a faint grid under the cube (the view's toggle)
        with dpg.drawlist(width=10, height=10, tag=tag, parent=parent):
            z = (0, 0)
            # a background picture, drawn first so the faces cover it (see background())
            self.bg_item = dpg.draw_image(texture, z, z, show=False)
            self.bg_key = None
            self.floor_items = _floor_items(tag)          # then the floor, which the faces stand on
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
            dpg.add_dynamic_texture(w, h, rgba.ravel(), tag=tex, parent=registry())
        ox, oy = (self.w - self.size) * 0.5, (self.h - self.size) * 0.5
        dpg.configure_item(self.bg_item, texture_tag=tex, pmin=(ox, oy), pmax=(ox + self.size, oy + self.size), show=True)

    def camera(self, yaw, pitch, dist, six=False, look=None, ortho=False):
        """Project every corner; a face pointing away is hidden, and so is
        the bottom unless the cube has six. Nothing is touched when the
        camera and size are as they were."""
        lk = tuple(np.round(np.asarray(look if look is not None else (0, 0, 0), np.float64), 4))
        key = (round(yaw, 4), round(pitch, 4), round(dist, 3), lk, bool(ortho), self.size, self.w, self.h, bool(six), self.floor)
        if key == self._last or not self.size:
            return
        self._last = key
        size = self.size
        cam = Cam(yaw, pitch, dist, size, look, ortho, FOV)
        eye = cam.eye
        ox, oy = (self.w - size) * 0.5, (self.h - size) * 0.5
        _place_floor(self.floor_items, self.floor, -1.1, cam, ox, oy)
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
            sx, sy, ok, _ = cam.screen(pts.reshape(-1, 3))
            if not ok.all():
                for q in quads:
                    dpg.configure_item(q, show=False)
                continue
            scr = np.stack([ox + sx, oy + sy], 1).reshape(N + 1, N + 1, 2)
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
    """Any geometry on the GPU: an LED a square, its colour a texel. With
    `dots`, an LED that is off is a smaller grey square: each LED has a dot
    behind its own square (made in pairs, so the far-first order holds for
    both), and its square's texel is transparent while it is off - as
    render_points draws it, a dim lit LED full size, an unlit one a dot."""
    LED = 0.42               # the fraction of the LED pitch an emitter covers, as render_points draws it
    DOT = DOT_POINT          # an unlit LED's dot against a lit one's square, as render_points draws it
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
        self.floor_items = []        # and the floor after it, before the squares
        self.floor = False
        self.dots = False            # unlit LEDs as dim dots (the view's toggle)
        self.items = []
        self.dot_items = []
        self.dot_tex = f"{tag}_dot"
        self.set_points(pos)

    def set_points(self, pos, frame=None):
        """The LEDs' positions: (n, 3), Z up, any units - fitted to `frame`
        ((centre, extent); their own, the way render_points fits them, when
        None). A new count remakes the squares."""
        from native.render import frame_of
        pos = np.asarray(pos, np.float32).reshape(-1, 3)
        n = len(pos)
        if n != self.n:
            for q in self.items + self.dot_items:
                dpg.delete_item(q)
            if dpg.does_item_exist(self.tex):
                dpg.delete_item(self.tex)
            if not dpg.does_item_exist(self.dot_tex):
                dpg.add_static_texture(1, 1, [c / 255.0 for c in UNLIT] + [1.0], tag=self.dot_tex, parent=registry())
            self.n = n
            cols = min(max(1, n), self.COLS)
            rows = max(1, (n + cols - 1) // cols)
            self.cols, self.rows = cols, rows
            dpg.add_dynamic_texture(cols, rows, [0.0, 0.0, 0.0, 1.0] * (cols * rows), tag=self.tex, parent=registry())
            z = (0, 0)
            if self.bg_item is None:
                self.bg_item = dpg.draw_image(self.tex, z, z, show=False, parent=self.tag)
                self.floor_items = _floor_items(self.tag)
            self.items, self.dot_items = [], []
            for _ in range(n):                            # in pairs: each LED's dot, then its square over it
                self.dot_items.append(dpg.draw_image_quad(self.dot_tex, z, z, z, z, show=False, parent=self.tag))
                self.items.append(dpg.draw_image_quad(self.tex, z, z, z, z, show=False, parent=self.tag))
        self.pos = pos
        self.frame = frame
        c, ext = frame or frame_of(pos)
        self.P = (pos - c) * (1.0 / (ext or 1.0))
        self.ext = ext or 1.0
        self._last = None

    def set_frame(self, frame):
        """The same LEDs fitted by another frame (the view's, held while a
        shape is built, or eased to a new one)."""
        if frame is self.frame or (frame is not None and self.frame is not None and np.array_equal(frame[0], self.frame[0])
                                   and frame[1] == self.frame[1]):
            return
        self.set_points(self.pos, frame)

    def resize(self, size, w=None, h=None):
        w, h = max(size, w or size), max(size, h or size)
        if (size, w, h) != (self.size, self.w, self.h):
            self.size, self.w, self.h = size, w, h
            dpg.configure_item(self.tag, width=w, height=h)
            self._last = None

    background = CubeQuads.background

    def camera(self, yaw, pitch, dist, look=None, ortho=False, floor_step=None):
        """Every square placed for this camera, far first. Nothing is touched
        when the camera and size are as they were. `floor_step`: (step,
        origin) of the floor's lines, a shape's round distances."""
        lk = tuple(np.round(np.asarray(look if look is not None else (0, 0, 0), np.float64), 4))
        fs = None if floor_step is None else (round(float(floor_step[0]), 5), tuple(np.round(floor_step[1], 4)))
        key = (round(yaw, 4), round(pitch, 4), round(dist, 3), lk, bool(ortho), fs, self.size, self.w, self.h, self.floor, self.dots)
        if key == self._last or not self.size or self.n == 0:
            return
        self._last = key
        size = self.size
        cam = Cam(yaw, pitch, dist, size, look, ortho, FOV)
        ox, oy = (self.w - size) * 0.5, (self.h - size) * 0.5
        zs = self.P[:, 2][np.isfinite(self.P[:, 2])]
        _place_floor(self.floor_items, self.floor, (float(zs.min()) - 0.08) if len(zs) else -1.1, cam, ox, oy, floor_step)
        sx, sy, ok, depth = cam.screen(self.P)
        sx = ox + sx
        sy = oy + sy
        half = np.maximum(1.0, cam.scale(depth) * (self.LED / self.ext))
        order = np.argsort(np.where(ok, -depth, np.inf))          # far first; the NaN and behind-the-eye last
        cols, rows = self.cols, self.rows
        for k, i in enumerate(order):
            q, dq = self.items[k], self.dot_items[k]
            if not ok[i] or sx[i] + half[i] < 0 or sy[i] + half[i] < 0 or sx[i] - half[i] > self.w or sy[i] - half[i] > self.h:
                dpg.configure_item(q, show=False); dpg.configure_item(dq, show=False); continue
            x0, x1, y0, y1 = sx[i] - half[i], sx[i] + half[i], sy[i] - half[i], sy[i] + half[i]
            uv = ((int(i) % cols + 0.5) / cols, (int(i) // cols + 0.5) / rows)     # one texel's centre: one colour
            dpg.configure_item(q, p1=(x0, y0), p2=(x1, y0), p3=(x1, y1), p4=(x0, y1), uv1=uv, uv2=uv, uv3=uv, uv4=uv, show=True)
            if self.dots:
                h = max(1.0, half[i] * self.DOT)
                dpg.configure_item(dq, p1=(sx[i] - h, sy[i] - h), p2=(sx[i] + h, sy[i] - h), p3=(sx[i] + h, sy[i] + h),
                                   p4=(sx[i] - h, sy[i] + h), show=True)
            else:
                dpg.configure_item(dq, show=False)

    def colours(self, rgb, unlit=None):
        """The LEDs' colours this frame: (n, 3) uint8, in the positions' order;
        with `unlit` (the view's dim dots) an LED that is off is transparent,
        so its dot behind shows."""
        rgb = np.asarray(rgb).reshape(-1, 3)
        n = self.cols * self.rows
        buf = np.zeros((n, 4), np.float32); buf[:, 3] = 1.0
        m = min(len(rgb), self.n)
        buf[:m, :3] = rgb[:m].astype(np.float32) / 255.0
        if unlit is not None:
            buf[:m, 3][rgb[:m].max(axis=1) < UNLIT_BELOW] = 0.0
        dpg.set_value(self.tex, buf.ravel())
