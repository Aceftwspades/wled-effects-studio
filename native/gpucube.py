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

from native.render import FACES6 as FACES, Cam, floor_segments, FLOOR, FLOOR_POOL, FLOOR_STEP, UNLIT, UNLIT_BELOW, DOT_POINT, FLOOR_Z, mirrored, reflection_weight

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


class Layers:
    """The look's layers of a view (look.py): the spill, a pool of the LEDs'
    light drawn under them, and the vignette and the grain drawn over them -
    each a small texture stretched over the view, hidden while its strength
    is 0. under() is called where the drawlist has its background, over()
    after everything that stands in it (a drawlist draws in the order it
    was made); update() once a frame."""

    def __init__(self, tag):
        self.tag = tag
        self.under_item = None
        self.over_items = []
        self._vig_key = None
        self._grain_n = 0
        self._rng = np.random.default_rng(3)
        self._tick = 0

    def _tex(self, name, a):
        """A dynamic texture of this view, made or written: `a` (h, w, 4) float."""
        tex = f"{self.tag}_{name}"
        h, w = a.shape[:2]
        if dpg.does_item_exist(tex):
            cfg = dpg.get_item_configuration(tex)
            if (cfg.get("width"), cfg.get("height")) == (w, h):
                dpg.set_value(tex, a.ravel()); return tex
            return None                                   # a size change: the caller makes it anew
        dpg.add_dynamic_texture(w, h, a.ravel(), tag=tex, parent=registry())
        return tex

    def under(self):
        z = (0, 0)
        self.under_item = dpg.draw_image(self._tex("spill", np.zeros((48, 48, 4), np.float32)), z, z, show=False, parent=self.tag)

    def over(self):
        for q in self.over_items:
            if dpg.does_item_exist(q):
                dpg.delete_item(q)
        z = (0, 0)
        vig, grain = f"{self.tag}_vig", f"{self.tag}_grain"
        if not dpg.does_item_exist(vig):
            self._tex("vig", np.zeros((64, 64, 4), np.float32)); self._vig_key = None
        if not dpg.does_item_exist(grain):
            self._tex("grain", np.zeros((8, 8, 4), np.float32))
        self._grain_n = dpg.get_item_configuration(grain).get("width") or 8      # made again: its texture kept
        self.over_items = [dpg.draw_image(vig, z, z, show=False, parent=self.tag),
                           dpg.draw_image(grain, z, z, show=False, parent=self.tag)]

    def update(self, lk, light, size, w, h):
        """This frame's layers for look `lk` (look.current) and the LEDs'
        light (look.mean_light), in a view `size` square centred in w x h."""
        from native import look
        ox, oy = (w - size) * 0.5, (h - size) * 0.5
        if self.under_item is not None and dpg.does_item_exist(self.under_item):
            if lk.get("spill", 0) > 0 and light is not None:
                self._tex("spill", look.spill_rgba(light[0], light[1], lk))
                pad = size * 0.25
                dpg.configure_item(self.under_item, pmin=(ox - pad, oy - pad), pmax=(ox + size + pad, oy + size + pad), show=True)
            else:
                dpg.configure_item(self.under_item, show=False)
        if len(self.over_items) != 2 or not all(dpg.does_item_exist(q) for q in self.over_items):
            return
        vig, grain = self.over_items
        if lk.get("vignette", 0) > 0:
            key = round(float(lk["vignette"]), 3)
            if key != self._vig_key:
                self._vig_key = key
                self._tex("vig", look.vignette_rgba(lk))
            dpg.configure_item(vig, pmin=(0, 0), pmax=(w, h), show=True)
        else:
            dpg.configure_item(vig, show=False)
        if lk.get("grain", 0) > 0:
            self._tick += 1
            n = int(max(32, min(360, max(w, h) // 2)))
            if n != self._grain_n:                        # a new size: its texture made again
                tex = f"{self.tag}_grain"
                dpg.configure_item(grain, texture_tag=f"{self.tag}_vig")   # off the old texture, so it can go
                if dpg.does_item_exist(tex):
                    dpg.delete_item(tex)
                self._grain_n = n
                dpg.configure_item(grain, texture_tag=self._tex("grain", look.grain_rgba(lk, n, self._rng)))
            elif self._tick % 2 == 0:                     # new grain every other frame
                self._tex("grain", look.grain_rgba(lk, n, self._rng))
            dpg.configure_item(grain, pmin=(0, 0), pmax=(w, h), show=True)
        else:
            dpg.configure_item(grain, show=False)


class CubeQuads:
    def __init__(self, parent, tag, texture):
        self.tag = tag
        self.texture = texture
        self.size = 0
        self.w = self.h = 0
        self.items = {}          # face index -> list of quad ids, row-major
        self._last = None
        self.floor = False       # a faint grid under the cube (the view's toggle)
        self.reflect = 0.0       # the floor a mirror this strong (look.py's reflection)
        self.mirror = {}         # face index -> its reflection's quads, row-major
        with dpg.drawlist(width=10, height=10, tag=tag, parent=parent):
            z = (0, 0)
            # a background picture, drawn first so the faces cover it (see background())
            self.bg_item = dpg.draw_image(texture, z, z, show=False)
            self.bg_key = None
            self.layers = Layers(tag)
            self.layers.under()                           # the look's spill, on the background
            self.floor_items = _floor_items(tag)          # then the floor, which the faces stand on
            for fi, fc in enumerate(FACES):               # the reflection in it, under the faces
                self.mirror[fi] = self._quads(fc, texture)
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
        self.layers.over()                                # the vignette and the grain, over everything

    @staticmethod
    def _quads(fc, texture):
        """A face's N x N quads, hidden, each sampling its part of the net's block."""
        z = (0, 0)
        bx, by = fc["bx"], fc["by"]
        quads = []
        for j in range(N):
            for i in range(N):
                u0, u1 = (bx + i / N) / 3.0, (bx + (i + 1) / N) / 3.0
                v0, v1 = (by + j / N) / 3.0, (by + (j + 1) / N) / 3.0
                quads.append(dpg.draw_image_quad(texture, z, z, z, z, uv1=(u0, v0), uv2=(u1, v0),
                                                 uv3=(u1, v1), uv4=(u0, v1), show=False))
        return quads

    def set_texture(self, texture):
        if texture == self.texture:
            return
        self.texture = texture
        for quads in list(self.items.values()) + list(self.mirror.values()):
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
        key = (round(yaw, 4), round(pitch, 4), round(dist, 3), lk, bool(ortho), self.size, self.w, self.h, bool(six), self.floor,
               round(self.reflect, 3))
        if key == self._last or not self.size:
            return
        self._last = key
        size = self.size
        cam = Cam(yaw, pitch, dist, size, look, ortho, FOV)
        eye = cam.eye
        ox, oy = (self.w - size) * 0.5, (self.h - size) * 0.5
        _place_floor(self.floor_items, self.floor, FLOOR_Z, cam, ox, oy)
        a = np.linspace(-1.0, 1.0, N + 1)
        above = eye[2] > FLOOR_Z + 0.02
        for fi, fc in enumerate(FACES):
            # the face's reflection in the floor, each quad as bright as it is near the floor (a tint's alpha)
            quads = self.mirror[fi]
            c = mirrored(fc["corners"])
            normal = fc["corners"].mean(axis=0) * np.array([1.0, 1.0, -1.0])
            if self.reflect <= 0 or not above or np.dot(normal, c.mean(axis=0) - eye) >= 0 or (fi == 5 and not six):
                for q in quads:
                    dpg.configure_item(q, show=False)
            else:
                self._place(quads, c, cam, ox, oy, a,
                            lambda z: (255, 255, 255, int(255 * min(1.0, 0.55 * self.reflect) * float(reflection_weight(FLOOR_Z - z)))))
        for fi, fc in enumerate(FACES):
            c = fc["corners"]
            centre = c.mean(axis=0)
            quads = self.items[fi]
            if np.dot(centre, centre - eye) >= 0 or (fi == 5 and not six):
                for q in quads:
                    dpg.configure_item(q, show=False)
                continue
            self._place(quads, c, cam, ox, oy, a)

    @staticmethod
    def _place(quads, c, cam, ox, oy, a, tint=None):
        """A face's quads on screen: its corners c spanning a, b in -1..1 the
        way the net block does; `tint(z)` the colour a quad is drawn in by its
        middle's height (the reflection's fade), None for white."""
        o, ea, eb = c[0], c[1] - c[0], c[3] - c[0]
        aa, bb = np.meshgrid(a, a)                            # (N+1, N+1): bb rows, aa cols
        pts = o + ((aa + 1) / 2)[..., None] * ea + ((bb + 1) / 2)[..., None] * eb
        sx, sy, ok, _ = cam.screen(pts.reshape(-1, 3))
        if not ok.all():
            for q in quads:
                dpg.configure_item(q, show=False)
            return
        scr = np.stack([ox + sx, oy + sy], 1).reshape(N + 1, N + 1, 2)
        zz = pts[..., 2]
        k = 0
        for j in range(N):
            for i in range(N):
                p1, p2, p3, p4 = scr[j, i], scr[j, i + 1], scr[j + 1, i + 1], scr[j + 1, i]
                # grown a third of a pixel about its centre: two quads
                # meeting on a non-integer edge otherwise leave a crack
                cx, cy = (p1 + p2 + p3 + p4) / 4.0
                p1, p2, p3, p4 = (q + np.sign(q - (cx, cy)) * 0.35 for q in (p1, p2, p3, p4))
                kw = {} if tint is None else {"color": tint((zz[j, i] + zz[j + 1, i + 1]) * 0.5)}
                dpg.configure_item(quads[k], p1=tuple(p1), p2=tuple(p2), p3=tuple(p3), p4=tuple(p4), show=True, **kw)
                k += 1


class PointQuads:
    """Any geometry on the GPU: an LED a square, its colour a texel. With
    `dots`, an LED that is off is a smaller grey square: each LED has a dot
    behind its own square (made in pairs, so the far-first order holds for
    both), and its square's texel is transparent while it is off - as
    render_points draws it, a dim lit LED full size, an unlit one a dot.

    The view's look (look.py) as the cube has it: with a glow or a diffuser
    (`sprite`) each square is drawn bigger, from a second texture holding a
    soft sprite of each LED's light in a cell of its own; with a
    `reflect`ion, a mirrored copy of every LED in a layer under them (made
    the first time it is wanted), faded with its depth below the floor."""
    LED = 0.42               # the fraction of the LED pitch an emitter covers, as render_points draws it
    DOT = DOT_POINT          # an unlit LED's dot against a lit one's square, as render_points draws it
    COLS = 4096              # the colour texture's width; more LEDs than that take more rows
    SCOLS = 512              # the sprite texture's cells across (each look.SPRITE_K texels)

    def __init__(self, parent, tag, pos):
        self.tag = tag
        self.size = 0
        self.w = self.h = 0
        self._last = None
        self.bg_key = None
        self.pos = None
        self.n = 0
        self.tex = f"{tag}_col"
        self.spr_tex = f"{tag}_spr"
        with dpg.drawlist(width=10, height=10, tag=tag, parent=parent):
            pass
        self.bg_item = None          # made with the first texture, before the squares, so they cover it
        self.floor_items = []        # and the floor after it, before the squares
        self.floor = False
        self.dots = False            # unlit LEDs as dim dots (the view's toggle)
        self.sprite = False          # each LED a sprite of its light (the look's glow or diffuser)
        self.grow = 1.0              # how much bigger a sprite is than the bare square
        self.reflect = 0.0           # the floor a mirror this strong
        self.items = []
        self.dot_items = []
        self.mirror_layer = None
        self.mirror_items = []
        self.dot_tex = f"{tag}_dot"
        self.layers = Layers(tag)
        self.set_points(pos)

    def set_points(self, pos, frame=None):
        """The LEDs' positions: (n, 3), Z up, any units - fitted to `frame`
        ((centre, extent); their own, the way render_points fits them, when
        None). A new count remakes the squares."""
        from native.render import frame_of
        from native.look import SPRITE_K
        pos = np.asarray(pos, np.float32).reshape(-1, 3)
        n = len(pos)
        if n != self.n:
            for q in self.items + self.dot_items + self.floor_items + self.mirror_items:
                dpg.delete_item(q)
            if self.mirror_layer is not None and dpg.does_item_exist(self.mirror_layer):
                dpg.delete_item(self.mirror_layer)
            self.mirror_layer, self.mirror_items = None, []
            # the background picture draws the colour texture until one of its own is set: it goes before its
            # texture does (a texture something still draws cannot be deleted - its name stays taken), and is
            # made again after, before the floor and the squares (a drawlist draws in the order it was made)
            if self.bg_item is not None and dpg.does_item_exist(self.bg_item):
                dpg.delete_item(self.bg_item)
            self.bg_item, self.bg_key, self.floor_items = None, None, []
            for t in (self.tex, self.spr_tex):
                if dpg.does_item_exist(t):
                    dpg.delete_item(t)
            if not dpg.does_item_exist(self.dot_tex):
                dpg.add_static_texture(1, 1, [c / 255.0 for c in UNLIT] + [1.0], tag=self.dot_tex, parent=registry())
            self.n = n
            cols = min(max(1, n), self.COLS)
            rows = max(1, (n + cols - 1) // cols)
            self.cols, self.rows = cols, rows
            dpg.add_dynamic_texture(cols, rows, [0.0, 0.0, 0.0, 1.0] * (cols * rows), tag=self.tex, parent=registry())
            self.scols = min(max(1, n), self.SCOLS)
            self.srows = max(1, (n + self.scols - 1) // self.scols)
            K = SPRITE_K
            dpg.add_dynamic_texture(self.scols * K, self.srows * K, np.zeros(self.scols * K * self.srows * K * 4, np.float32),
                                    tag=self.spr_tex, parent=registry())
            z = (0, 0)
            if self.bg_item is None:
                self.bg_item = dpg.draw_image(self.tex, z, z, show=False, parent=self.tag)
                if self.layers.under_item is not None and dpg.does_item_exist(self.layers.under_item):
                    dpg.delete_item(self.layers.under_item)
                self.layers.under()                       # the look's spill, on the background
                self.floor_items = _floor_items(self.tag)
            self.mirror_layer = dpg.add_draw_layer(parent=self.tag)       # the reflection, under the LEDs
            self.items, self.dot_items = [], []
            for _ in range(n):                            # in pairs: each LED's dot, then its square over it
                self.dot_items.append(dpg.draw_image_quad(self.dot_tex, z, z, z, z, show=False, parent=self.tag))
                self.items.append(dpg.draw_image_quad(self.tex, z, z, z, z, show=False, parent=self.tag))
            self.layers.over()                            # the vignette and the grain, over the squares
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

    def _uv(self, i):
        """LED i's part of the texture it is drawn from: its texel's centre (one colour), or its sprite's cell."""
        if self.sprite:
            cx, cy = i % self.scols, i // self.scols
            u0, u1 = cx / self.scols, (cx + 1) / self.scols
            v0, v1 = cy / self.srows, (cy + 1) / self.srows
            return dict(uv1=(u0, v0), uv2=(u1, v0), uv3=(u1, v1), uv4=(u0, v1), texture_tag=self.spr_tex)
        uv = ((i % self.cols + 0.5) / self.cols, (i // self.cols + 0.5) / self.rows)
        return dict(uv1=uv, uv2=uv, uv3=uv, uv4=uv, texture_tag=self.tex)

    def camera(self, yaw, pitch, dist, look=None, ortho=False, floor_step=None):
        """Every square placed for this camera, far first - and the
        reflection's, mirrored in the floor. Nothing is touched when the
        camera, the size and the look are as they were. `floor_step`:
        (step, origin) of the floor's lines, a shape's round distances."""
        lk = tuple(np.round(np.asarray(look if look is not None else (0, 0, 0), np.float64), 4))
        fs = None if floor_step is None else (round(float(floor_step[0]), 5), tuple(np.round(floor_step[1], 4)))
        key = (round(yaw, 4), round(pitch, 4), round(dist, 3), lk, bool(ortho), fs, self.size, self.w, self.h, self.floor, self.dots,
               self.sprite, round(self.grow, 3), round(self.reflect, 3))
        if key == self._last or not self.size or self.n == 0:
            return
        self._last = key
        size = self.size
        cam = Cam(yaw, pitch, dist, size, look, ortho, FOV)
        ox, oy = (self.w - size) * 0.5, (self.h - size) * 0.5
        zs = self.P[:, 2][np.isfinite(self.P[:, 2])]
        fz = (float(zs.min()) - 0.08) if len(zs) else -1.1
        _place_floor(self.floor_items, self.floor, fz, cam, ox, oy, floor_step)
        grow = self.grow if self.sprite else 1.0
        self._place_mirror(cam, ox, oy, fz, zs, grow)
        sx, sy, ok, depth = cam.screen(self.P)
        sx = ox + sx
        sy = oy + sy
        half = np.maximum(1.0, cam.scale(depth) * (self.LED / self.ext))
        order = np.argsort(np.where(ok, -depth, np.inf))          # far first; the NaN and behind-the-eye last
        for k, i in enumerate(order):
            q, dq = self.items[k], self.dot_items[k]
            hs = half[i] * grow
            if not ok[i] or sx[i] + hs < 0 or sy[i] + hs < 0 or sx[i] - hs > self.w or sy[i] - hs > self.h:
                dpg.configure_item(q, show=False); dpg.configure_item(dq, show=False); continue
            x0, x1, y0, y1 = sx[i] - hs, sx[i] + hs, sy[i] - hs, sy[i] + hs
            dpg.configure_item(q, p1=(x0, y0), p2=(x1, y0), p3=(x1, y1), p4=(x0, y1), show=True, **self._uv(int(i)))
            if self.dots:
                h = max(1.0, half[i] * self.DOT)
                dpg.configure_item(dq, p1=(sx[i] - h, sy[i] - h), p2=(sx[i] + h, sy[i] - h), p3=(sx[i] + h, sy[i] + h),
                                   p4=(sx[i] - h, sy[i] + h), show=True)
            else:
                dpg.configure_item(dq, show=False)

    def _place_mirror(self, cam, ox, oy, fz, zs, grow):
        """The reflection: each LED mirrored in the floor (z = fz), drawn far
        first, its alpha by its height over the floor against the shape's
        own height. Its squares are made the first time a reflection is
        wanted, in the layer kept for them under the LEDs."""
        on = self.reflect > 0 and cam.eye[2] > fz + 0.02 and len(zs)
        if not on:
            for q in self.mirror_items:
                dpg.configure_item(q, show=False)
            return
        if len(self.mirror_items) != self.n:
            z = (0, 0)
            self.mirror_items = [dpg.draw_image_quad(self.tex, z, z, z, z, show=False, parent=self.mirror_layer)
                                 for _ in range(self.n)]
        M = self.P.copy()
        M[:, 2] = 2 * fz - self.P[:, 2]
        sx, sy, ok, depth = cam.screen(M)
        sx = ox + sx
        sy = oy + sy
        half = np.maximum(1.0, cam.scale(depth) * (self.LED / self.ext)) * grow
        tall = max(1e-3, float(zs.max()) - fz)
        alpha = reflection_weight((self.P[:, 2] - fz) / tall * 2.0) * min(1.0, 0.55 * self.reflect)
        order = np.argsort(np.where(ok, -depth, np.inf))
        for k, i in enumerate(order):
            q = self.mirror_items[k]
            a = alpha[i]
            if (not ok[i] or not np.isfinite(a) or a <= 0.01 or sx[i] + half[i] < 0 or sy[i] + half[i] < 0
                    or sx[i] - half[i] > self.w or sy[i] - half[i] > self.h):
                dpg.configure_item(q, show=False); continue
            x0, x1, y0, y1 = sx[i] - half[i], sx[i] + half[i], sy[i] - half[i], sy[i] + half[i]
            dpg.configure_item(q, p1=(x0, y0), p2=(x1, y0), p3=(x1, y1), p4=(x0, y1), show=True,
                               color=(255, 255, 255, int(255 * a)), **self._uv(int(i)))

    def colours(self, rgb, unlit=None, lk=None):
        """The LEDs' colours this frame: (n, 3) uint8, in the positions' order;
        with `unlit` (the view's dim dots) an LED that is off is transparent,
        so its dot behind shows. With `lk`'s glow or diffuser, the sprite
        texture is written instead: each LED's colour in its cell, its
        light's shape (look.sprite_mask) the alpha."""
        from native import look
        rgb = np.asarray(rgb).reshape(-1, 3)
        m = min(len(rgb), self.n)
        sprite = bool(lk) and (lk.get("glow", 0) > 0 or lk.get("diffuse", 0) > 0)
        if sprite != self.sprite or (sprite and abs(look.sprite_grow(lk) - self.grow) > 1e-6):
            self.sprite = sprite
            self.grow = look.sprite_grow(lk) if sprite else 1.0
            self._last = None                             # the squares drawn again, from the other texture
        if sprite:
            K = look.SPRITE_K
            mask = look.sprite_mask(lk, K)
            n = self.scols * self.srows
            col = np.zeros((n, 3), np.float32)
            col[:m] = rgb[:m].astype(np.float32) / 255.0
            lit = np.zeros(n, np.float32)
            lit[:m] = (rgb[:m].max(axis=1) >= UNLIT_BELOW) if unlit is not None else 1.0
            cells = np.empty((self.srows, self.scols, K, K, 4), np.float32)
            cells[..., :3] = col.reshape(self.srows, self.scols, 1, 1, 3)
            cells[..., 3] = mask[None, None] * lit.reshape(self.srows, self.scols, 1, 1)
            dpg.set_value(self.spr_tex, cells.transpose(0, 2, 1, 3, 4).ravel())
            return
        n = self.cols * self.rows
        buf = np.zeros((n, 4), np.float32); buf[:, 3] = 1.0
        buf[:m, :3] = rgb[:m].astype(np.float32) / 255.0
        if unlit is not None:
            buf[:m, 3][rgb[:m].max(axis=1) < UNLIT_BELOW] = 0.0
        dpg.set_value(self.tex, buf.ravel())
