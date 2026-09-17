"""The cube view on the GPU.

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
