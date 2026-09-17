"""Rotating angular-gradient frames around what is active.

The frame is an angular (conic) gradient drawn as four thin strips around a
rectangle plus four wider, fainter ones outside them for a glow, the corners
rounded by a few small quads each, turning slowly. One texture holds the
gradient; each piece is an image quad whose texture coordinates are its own
position rotated about the rectangle's centre, so the pieces read as one
gradient and turning it is a matter of new coordinates each frame - a few
dozen small updates per frame per rectangle, nothing redrawn.

Two kinds of frame, each with its own gradient: "sel" (the selected nodes)
and "focus" (the pane last clicked in). A gradient is a list of stops,
[position 0..1, r, g, b], read around the circle - cyclic, the last stop
blending back into the first, or mirrored (0 -> 1 -> 0 around the circle),
which makes any palette seamless.

    frames = Frames()                                  # after the viewport exists
    frames.set_gradient("sel", stops, mirror=False)
    frames.update([(x0, y0, x1, y1, clip, alpha, "sel"), ...])   # every frame
"""
import math
import time
import numpy as np
import dearpygui.dearpygui as dpg

# The studio's own: the theme's blue, a violet, a pink, an amber, a mint.
DEFAULT_STOPS = [[0.0, 90, 169, 230], [0.2, 150, 120, 255], [0.4, 255, 110, 170],
                 [0.6, 255, 170, 80], [0.8, 90, 230, 200]]
SIZE = 128
BORDER = 2
GLOW = 5
RADIUS = 5                                   # the corners' rounding, unless the rect says (a pane's is 5)
ARC_N = 5                                    # quads per rounded corner, per ring
PER_RECT = 8 + 4 * ARC_N * 2                 # strips and corner pieces a rectangle takes
TURNS_PER_S = 0.1
POOL = {"sel": PER_RECT * 7, "focus": PER_RECT * 2}      # pieces, split round any dialog


def sample(stops, t, mirror=False):
    """The gradient's colour at t (0..1), as (r, g, b)."""
    srt = sorted(stops, key=lambda s: s[0])
    if not srt:
        return (255, 255, 255)
    if mirror:
        t = 1.0 - abs(2.0 * (t % 1.0) - 1.0)
        if t <= srt[0][0]:
            return tuple(int(v) for v in srt[0][1:4])
        if t >= srt[-1][0]:
            return tuple(int(v) for v in srt[-1][1:4])
    else:
        t = t % 1.0
        if t < srt[0][0] or t >= srt[-1][0]:
            # across the seam: the last stop round to the first
            a, b = srt[-1], srt[0]
            span = (b[0] + 1.0) - a[0]
            f = ((t - a[0]) % 1.0) / span if span > 1e-6 else 0.0
            return tuple(int(a[i] + (b[i] - a[i]) * f) for i in (1, 2, 3))
    for i in range(len(srt) - 1):
        a, b = srt[i], srt[i + 1]
        if a[0] <= t <= b[0]:
            f = (t - a[0]) / (b[0] - a[0]) if b[0] > a[0] else 0.0
            return tuple(int(a[k] + (b[k] - a[k]) * f) for k in (1, 2, 3))
    return tuple(int(v) for v in srt[-1][1:4])


def conic(stops, mirror=False):
    """The gradient around a SIZE x SIZE square, as texture floats."""
    ys, xs = np.mgrid[0:SIZE, 0:SIZE]
    ang = (np.arctan2(ys - SIZE / 2 + 0.5, xs - SIZE / 2 + 0.5) / (2 * math.pi)) % 1.0
    # 256 samples round the circle, then a lookup - the sampler is scalar
    table = np.array([sample(stops, k / 256.0, mirror) for k in range(256)], dtype=np.float32) / 255.0
    idx = np.clip((ang * 256).astype(int), 0, 255)
    rgb = table[idx]
    rgba = np.concatenate([rgb, np.ones((SIZE, SIZE, 1), dtype=np.float32)], axis=2)
    return rgba.ravel().tolist()


class Frames:
    def __init__(self):
        if not dpg.does_item_exist("icon_registry"):
            dpg.add_texture_registry(tag="icon_registry")
        self.tex = {}
        self.quads = {}
        self.shown = {}
        with dpg.viewport_drawlist(front=True, tag="glow_front"):
            for kind, n in POOL.items():
                self.tex[kind] = dpg.add_dynamic_texture(SIZE, SIZE, conic(DEFAULT_STOPS), parent="icon_registry")
                z = (0, 0)
                self.quads[kind] = [dpg.draw_image_quad(self.tex[kind], z, z, z, z, show=False) for _ in range(n)]
                self.shown[kind] = 0

    def set_gradient(self, kind, stops, mirror=False):
        if kind in self.tex:
            dpg.set_value(self.tex[kind], conic(stops, mirror))

    @staticmethod
    def _radius(x0, y0, x1, y1, r=RADIUS):
        return max(0.0, min(r, (x1 - x0) / 2.0, (y1 - y0) / 2.0))

    @classmethod
    def _strips(cls, x0, y0, x1, y1, radius=RADIUS):
        """The straight parts, stopping short of the corners by the radius."""
        b, g = BORDER, GLOW
        r = cls._radius(x0, y0, x1, y1, radius)
        yield (x0 + r, y0 - b, x1 - r, y0, 255)
        yield (x0 + r, y1, x1 - r, y1 + b, 255)
        yield (x0 - b, y0 + r, x0, y1 - r, 255)
        yield (x1, y0 + r, x1 + b, y1 - r, 255)
        o = b + g
        yield (x0 + r, y0 - o, x1 - r, y0 - b, 70)
        yield (x0 + r, y1 + b, x1 - r, y1 + o, 70)
        yield (x0 - o, y0 + r, x0 - b, y1 - r, 70)
        yield (x1 + b, y0 + r, x1 + o, y1 - r, 70)

    @classmethod
    def _corners(cls, x0, y0, x1, y1, radius=RADIUS):
        """The rounded corners: for each, ARC_N quads round the border ring
        and ARC_N round the glow ring, as (p1, p2, p3, p4, alpha). The
        radius is the framed thing's own corner radius, so the border ring
        wraps its corner concentrically."""
        b, g = BORDER, GLOW
        r = cls._radius(x0, y0, x1, y1, radius)
        centres = ((x0 + r, y0 + r, math.pi), (x1 - r, y0 + r, 1.5 * math.pi),
                   (x1 - r, y1 - r, 0.0), (x0 + r, y1 - r, 0.5 * math.pi))
        for cx, cy, a0 in centres:
            for (ri, ro, a) in ((r, r + b, 255), (r + b, r + b + g, 70)):
                for k in range(ARC_N):
                    t0 = a0 + (math.pi / 2) * k / ARC_N
                    t1 = a0 + (math.pi / 2) * (k + 1) / ARC_N
                    c0, s0, c1, s1 = math.cos(t0), math.sin(t0), math.cos(t1), math.sin(t1)
                    yield ((cx + ri * c0, cy + ri * s0), (cx + ro * c0, cy + ro * s0),
                           (cx + ro * c1, cy + ro * s1), (cx + ri * c1, cy + ri * s1), a)

    @staticmethod
    def _subtract(r, holes):
        """The parts of rectangle r outside every hole - the drawing is in
        the foreground, so a window over it would otherwise be drawn on."""
        out = [r]
        for (hx0, hy0, hx1, hy1) in holes:
            nxt = []
            for (x0, y0, x1, y1) in out:
                if hx1 <= x0 or hx0 >= x1 or hy1 <= y0 or hy0 >= y1:
                    nxt.append((x0, y0, x1, y1)); continue
                if y0 < hy0:
                    nxt.append((x0, y0, x1, min(y1, hy0)))
                if y1 > hy1:
                    nxt.append((x0, max(y0, hy1), x1, y1))
                my0, my1 = max(y0, hy0), min(y1, hy1)
                if x0 < hx0:
                    nxt.append((x0, my0, min(x1, hx0), my1))
                if x1 > hx1:
                    nxt.append((max(x0, hx1), my0, x1, my1))
            out = [q for q in nxt if q[2] > q[0] and q[3] > q[1]]
        return out

    def update(self, rects, holes=()):
        """rects: (x0, y0, x1, y1, clip, alpha, kind[, radius]) - clip a rect
        to keep the strips inside (or None), alpha 0..1 scaling the frame,
        radius the framed thing's corner rounding. holes: rectangles
        (windows over the top) the strips are cut around."""
        th = (time.perf_counter() * TURNS_PER_S * 2 * math.pi) % (2 * math.pi)
        c, s = math.cos(th), math.sin(th)
        used = {k: 0 for k in self.quads}
        for rect in rects:
            x0, y0, x1, y1, clip, alpha, kind = rect[:7]
            radius = rect[7] if len(rect) > 7 else RADIUS
            quads = self.quads.get(kind)
            if quads is None:
                continue
            cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
            size = max(1.0, max(x1 - x0, y1 - y0))

            def uv(px, py):
                dx, dy = (px - cx) / size, (py - cy) / size
                return (0.5 + 0.3 * (dx * c - dy * s), 0.5 + 0.3 * (dx * s + dy * c))

            for (sx0, sy0, sx1, sy1, a) in self._strips(x0, y0, x1, y1, radius):
                if clip:
                    sx0, sy0 = max(sx0, clip[0]), max(sy0, clip[1])
                    sx1, sy1 = min(sx1, clip[2]), min(sy1, clip[3])
                    if sx1 <= sx0 or sy1 <= sy0:
                        continue
                for (sx0, sy0, sx1, sy1) in self._subtract((sx0, sy0, sx1, sy1), holes):
                    k = used[kind]
                    if k >= len(quads):
                        break
                    dpg.configure_item(quads[k], p1=(sx0, sy0), p2=(sx1, sy0), p3=(sx1, sy1), p4=(sx0, sy1),
                                       uv1=uv(sx0, sy0), uv2=uv(sx1, sy0), uv3=uv(sx1, sy1), uv4=uv(sx0, sy1),
                                       color=(255, 255, 255, int(a * alpha)), show=True)
                    used[kind] = k + 1
            # the corners: a piece is drawn whole or not at all - one outside
            # the clip, or under a window, is left out
            for (p1, p2, p3, p4, a) in self._corners(x0, y0, x1, y1, radius):
                bx0 = min(p[0] for p in (p1, p2, p3, p4)); bx1 = max(p[0] for p in (p1, p2, p3, p4))
                by0 = min(p[1] for p in (p1, p2, p3, p4)); by1 = max(p[1] for p in (p1, p2, p3, p4))
                if clip and (bx0 < clip[0] or by0 < clip[1] or bx1 > clip[2] or by1 > clip[3]):
                    continue
                if any(not (hx1 <= bx0 or hx0 >= bx1 or hy1 <= by0 or hy0 >= by1) for (hx0, hy0, hx1, hy1) in holes):
                    continue
                k = used[kind]
                if k >= len(quads):
                    break
                dpg.configure_item(quads[k], p1=p1, p2=p2, p3=p3, p4=p4, uv1=uv(*p1), uv2=uv(*p2), uv3=uv(*p3), uv4=uv(*p4),
                                   color=(255, 255, 255, int(a * alpha)), show=True)
                used[kind] = k + 1
        for kind, quads in self.quads.items():
            for j in range(used[kind], self.shown[kind]):
                dpg.configure_item(quads[j], show=False)
            self.shown[kind] = used[kind]
