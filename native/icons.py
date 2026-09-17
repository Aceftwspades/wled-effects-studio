"""Toolbar icons, drawn in code.

Dear PyGui's default font has no symbols and an icon font would be one more
file to ship and license per platform, so each icon is a few strokes on a
unit square, rasterised at 4x and averaged down. White with an alpha mask;
the button tints it, so one texture serves every state (the live toggle is
the same bolt in the accent colour).

    tex = texture("play")           # a static texture tag, made on first use
    dpg.add_image_button(tex, width=16, height=16, tint_color=TEXT)
"""
import math
import numpy as np

SS = 4              # supersampling
W = 0.11            # stroke width, of the unit square: ~1.8 px at 16 px


class Icon:
    def __init__(self, px):
        self.px = px
        S = px * SS
        ys, xs = np.mgrid[0:S, 0:S]
        self.x = (xs + 0.5) / S
        self.y = (ys + 0.5) / S
        self.a = np.zeros((S, S), dtype=np.float32)

    def add(self, m):
        self.a = np.maximum(self.a, m.astype(np.float32))

    def cut(self, m):
        self.a = self.a * (1.0 - m.astype(np.float32))

    # --- strokes and shapes, in unit coordinates, y down --------------------------
    def seg(self, a, b, w=W):
        ax, ay = a
        bx, by = b
        dx, dy = bx - ax, by - ay
        l2 = dx * dx + dy * dy
        t = 0.0 if l2 == 0 else np.clip(((self.x - ax) * dx + (self.y - ay) * dy) / l2, 0.0, 1.0)
        self.add(np.hypot(self.x - (ax + t * dx), self.y - (ay + t * dy)) <= w / 2)

    def path(self, pts, w=W, closed=False):
        for i in range(len(pts) - (0 if closed else 1)):
            self.seg(pts[i], pts[(i + 1) % len(pts)], w)

    def circle(self, c, r):
        self.add(np.hypot(self.x - c[0], self.y - c[1]) <= r)

    def ring(self, c, r, w=W):
        self.add(np.abs(np.hypot(self.x - c[0], self.y - c[1]) - r) <= w / 2)

    def rect(self, x0, y0, x1, y1):
        self.add((self.x >= x0) & (self.x <= x1) & (self.y >= y0) & (self.y <= y1))

    def box(self, x0, y0, x1, y1, w=W):
        self.path([(x0, y0), (x1, y0), (x1, y1), (x0, y1)], w, closed=True)

    def poly(self, pts):
        inside = np.zeros(self.x.shape, dtype=bool)
        n = len(pts)
        for i in range(n):
            (x0, y0), (x1, y1) = pts[i], pts[(i + 1) % n]
            if y0 == y1:
                continue
            cond = (y0 > self.y) != (y1 > self.y)
            xi = x0 + (self.y - y0) * (x1 - x0) / (y1 - y0)
            inside ^= cond & (self.x < xi)
        self.add(inside)

    def arc(self, c, r, a0, a1, w=W, head=None):
        """An arc from angle a0 to a1 (degrees, screen coordinates, so the
        sweep is clockwise on screen); `head` puts an arrowhead at "start"
        or "end", pointing the way the arc runs."""
        ang = np.degrees(np.arctan2(self.y - c[1], self.x - c[0]))
        span = (a1 - a0) % 360.0
        on = ((ang - a0) % 360.0) <= span
        self.add(on & (np.abs(np.hypot(self.x - c[0], self.y - c[1]) - r) <= w / 2))
        if head:
            th = math.radians(a1 if head == "end" else a0)
            p = (c[0] + r * math.cos(th), c[1] + r * math.sin(th))
            d = (-math.sin(th), math.cos(th))                 # travel for increasing angle
            if head == "start":
                d = (-d[0], -d[1])
            n = (-d[1], d[0])
            hl, hw = 0.2, 0.17
            tip = (p[0] + d[0] * hl, p[1] + d[1] * hl)
            base = (p[0] - d[0] * hl * 0.6, p[1] - d[1] * hl * 0.6)
            self.poly([tip, (base[0] + n[0] * hw, base[1] + n[1] * hw), (base[0] - n[0] * hw, base[1] - n[1] * hw)])

    def arrow(self, a, b, w=W, hw=0.14, hl=0.16):
        """A straight arrow from a to b, head at b."""
        dx, dy = b[0] - a[0], b[1] - a[1]
        L = math.hypot(dx, dy) or 1.0
        d = (dx / L, dy / L)
        n = (-d[1], d[0])
        self.seg(a, (b[0] - d[0] * hl * 0.5, b[1] - d[1] * hl * 0.5), w)
        base = (b[0] - d[0] * hl, b[1] - d[1] * hl)
        self.poly([b, (base[0] + n[0] * hw, base[1] + n[1] * hw), (base[0] - n[0] * hw, base[1] - n[1] * hw)])

    def flip(self):
        self.a = self.a[:, ::-1]

    def data(self):
        """RGBA floats, white with the drawn alpha, as add_static_texture wants."""
        S = self.px
        alpha = self.a.reshape(S, SS, S, SS).mean(axis=(1, 3))
        rgba = np.ones((S, S, 4), dtype=np.float32)
        rgba[:, :, 3] = alpha
        return rgba.ravel().tolist()


# --- the icons ----------------------------------------------------------------------
def _new(ic):
    ic.path([(0.24, 0.1), (0.56, 0.1), (0.74, 0.28), (0.74, 0.9), (0.24, 0.9)], closed=True)
    ic.path([(0.56, 0.1), (0.56, 0.28), (0.74, 0.28)])
    ic.seg((0.49, 0.5), (0.49, 0.76)); ic.seg((0.36, 0.63), (0.62, 0.63))

def _open(ic):
    ic.path([(0.1, 0.24), (0.38, 0.24), (0.47, 0.34), (0.9, 0.34), (0.9, 0.82), (0.1, 0.82)], closed=True)

def _save(ic):
    ic.path([(0.14, 0.14), (0.76, 0.14), (0.86, 0.24), (0.86, 0.86), (0.14, 0.86)], closed=True)
    ic.box(0.3, 0.14, 0.66, 0.38, w=0.08)
    ic.box(0.3, 0.58, 0.7, 0.86, w=0.08)

def _build(ic):
    # a hammer: the handle down-left, the head across the top-right
    ic.seg((0.2, 0.88), (0.56, 0.52), w=0.13)
    c, u, v = (0.64, 0.36), (0.2, 0.2), (0.11, -0.11)
    ic.poly([(c[0] - u[0] - v[0], c[1] - u[1] - v[1]), (c[0] + u[0] - v[0], c[1] + u[1] - v[1]),
             (c[0] + u[0] + v[0], c[1] + u[1] + v[1]), (c[0] - u[0] + v[0], c[1] - u[1] + v[1])])

def _live(ic):
    ic.poly([(0.56, 0.06), (0.26, 0.56), (0.48, 0.56), (0.4, 0.94), (0.74, 0.42), (0.52, 0.42)])

def _undo(ic):
    ic.arc((0.5, 0.58), 0.28, -150, 20, head="start")

def _redo(ic):
    _undo(ic); ic.flip()

def _play(ic):
    ic.poly([(0.28, 0.16), (0.28, 0.84), (0.86, 0.5)])

def _pause(ic):
    ic.rect(0.24, 0.16, 0.42, 0.84); ic.rect(0.58, 0.16, 0.76, 0.84)

def _step(ic):
    ic.rect(0.16, 0.16, 0.3, 0.84); ic.poly([(0.4, 0.16), (0.4, 0.84), (0.9, 0.5)])

def _restart(ic):
    ic.arc((0.5, 0.52), 0.3, -50, 230, head="end")

def _net(ic):
    ic.box(0.12, 0.12, 0.88, 0.88, w=0.09)
    ic.seg((0.37, 0.12), (0.37, 0.88), w=0.07); ic.seg((0.63, 0.12), (0.63, 0.88), w=0.07)
    ic.seg((0.12, 0.37), (0.88, 0.37), w=0.07); ic.seg((0.12, 0.63), (0.88, 0.63), w=0.07)

def _cube(ic):
    hexa = [(0.5, 0.08), (0.86, 0.29), (0.86, 0.71), (0.5, 0.92), (0.14, 0.71), (0.14, 0.29)]
    ic.path(hexa, w=0.09, closed=True)
    for p in ((0.86, 0.29), (0.14, 0.29), (0.5, 0.92)):
        ic.seg((0.5, 0.5), p, w=0.09)

def _both(ic):
    ic.box(0.06, 0.2, 0.46, 0.8, w=0.09); ic.box(0.54, 0.2, 0.94, 0.8, w=0.09)

def _code(ic):
    ic.path([(0.36, 0.22), (0.1, 0.5), (0.36, 0.78)])
    ic.path([(0.64, 0.22), (0.9, 0.5), (0.64, 0.78)])
    ic.seg((0.42, 0.86), (0.58, 0.14), w=0.09)

def _graph(ic):
    ic.seg((0.22, 0.3), (0.78, 0.5), w=0.08); ic.seg((0.22, 0.7), (0.78, 0.5), w=0.08)
    for c in ((0.22, 0.3), (0.22, 0.7), (0.78, 0.5)):
        ic.circle(c, 0.14)

def _zoom_in(ic):
    ic.ring((0.42, 0.42), 0.27); ic.seg((0.62, 0.62), (0.9, 0.9), w=0.14)
    ic.seg((0.42, 0.28), (0.42, 0.56), w=0.09); ic.seg((0.28, 0.42), (0.56, 0.42), w=0.09)

def _zoom_out(ic):
    ic.ring((0.42, 0.42), 0.27); ic.seg((0.62, 0.62), (0.9, 0.9), w=0.14)
    ic.seg((0.28, 0.42), (0.56, 0.42), w=0.09)

def _frame_all(ic):
    L = 0.24
    for x, sx in ((0.1, 1), (0.9, -1)):
        for y, sy in ((0.1, 1), (0.9, -1)):
            ic.seg((x, y), (x + sx * L, y)); ic.seg((x, y), (x, y + sy * L))

def _camera(ic):
    ic.box(0.08, 0.3, 0.92, 0.86, w=0.09)
    ic.rect(0.34, 0.16, 0.66, 0.34)
    ic.ring((0.5, 0.58), 0.15, w=0.09)

def _record(ic):
    ic.ring((0.5, 0.5), 0.36, w=0.08); ic.circle((0.5, 0.5), 0.2)

def _trash(ic):
    ic.seg((0.14, 0.26), (0.86, 0.26)); ic.rect(0.38, 0.12, 0.62, 0.26)
    ic.path([(0.22, 0.26), (0.28, 0.9), (0.72, 0.9), (0.78, 0.26)])
    ic.seg((0.42, 0.4), (0.43, 0.76), w=0.07); ic.seg((0.58, 0.4), (0.57, 0.76), w=0.07)

def _arrange(ic):
    for x, ys in ((0.1, (0.16, 0.6)), (0.42, (0.38,)), (0.74, (0.16, 0.6))):
        for y in ys:
            ic.rect(x, y, x + 0.16, y + 0.24)
    ic.seg((0.26, 0.28), (0.42, 0.5), w=0.06); ic.seg((0.26, 0.72), (0.42, 0.5), w=0.06)
    ic.seg((0.58, 0.5), (0.74, 0.28), w=0.06); ic.seg((0.58, 0.5), (0.74, 0.72), w=0.06)

def _fold(ic):
    ic.box(0.1, 0.22, 0.9, 0.88, w=0.08)
    ic.rect(0.24, 0.4, 0.44, 0.7); ic.rect(0.56, 0.4, 0.76, 0.7)

def _export(ic):
    ic.path([(0.14, 0.58), (0.14, 0.88), (0.86, 0.88), (0.86, 0.58)])
    ic.arrow((0.5, 0.72), (0.5, 0.1))

def _import(ic):
    ic.path([(0.14, 0.58), (0.14, 0.88), (0.86, 0.88), (0.86, 0.58)])
    ic.arrow((0.5, 0.08), (0.5, 0.7))

def _send(ic):
    ic.poly([(0.08, 0.46), (0.92, 0.1), (0.62, 0.92), (0.46, 0.6)])
    ic.cut(np.hypot(ic.x - 0.55, ic.y - 0.5) <= 0.03)

def _external(ic):
    ic.path([(0.5, 0.16), (0.14, 0.16), (0.14, 0.86), (0.84, 0.86), (0.84, 0.5)])
    ic.arrow((0.44, 0.56), (0.86, 0.14))
    ic.seg((0.58, 0.14), (0.86, 0.14)); ic.seg((0.86, 0.14), (0.86, 0.42))

def _gear(ic):
    ic.ring((0.5, 0.5), 0.24, w=0.16)
    for k in range(8):
        th = math.radians(k * 45)
        c = (0.5 + 0.37 * math.cos(th), 0.5 + 0.37 * math.sin(th))
        u = (0.1 * math.cos(th), 0.1 * math.sin(th)); v = (-0.08 * math.sin(th), 0.08 * math.cos(th))
        ic.poly([(c[0] - u[0] - v[0], c[1] - u[1] - v[1]), (c[0] + u[0] - v[0], c[1] + u[1] - v[1]),
                 (c[0] + u[0] + v[0], c[1] + u[1] + v[1]), (c[0] - u[0] + v[0], c[1] - u[1] + v[1])])

def _search(ic):
    ic.ring((0.42, 0.42), 0.27); ic.seg((0.62, 0.62), (0.9, 0.9), w=0.14)

def _rename(ic):
    ic.seg((0.1, 0.9), (0.9, 0.9), w=0.08)
    c, u, v = (0.52, 0.42), (0.24, -0.24), (0.09, 0.09)          # the body, a rotated bar
    ic.poly([(c[0] - u[0] - v[0], c[1] - u[1] - v[1]), (c[0] + u[0] - v[0], c[1] + u[1] - v[1]),
             (c[0] + u[0] + v[0], c[1] + u[1] + v[1]), (c[0] - u[0] + v[0], c[1] - u[1] + v[1])])
    ic.poly([(0.14, 0.8), (0.19, 0.57), (0.37, 0.75)])            # the point

def _mute(ic):
    ic.poly([(0.12, 0.38), (0.32, 0.38), (0.56, 0.16), (0.56, 0.84), (0.32, 0.62), (0.12, 0.62)])
    ic.seg((0.66, 0.38), (0.9, 0.62), w=0.09); ic.seg((0.9, 0.38), (0.66, 0.62), w=0.09)


ICONS = {
    "new": _new, "open": _open, "save": _save, "build": _build, "live": _live,
    "undo": _undo, "redo": _redo, "play": _play, "pause": _pause, "step": _step, "restart": _restart,
    "net": _net, "cube": _cube, "both": _both, "code": _code, "graph": _graph,
    "zoom_in": _zoom_in, "zoom_out": _zoom_out, "frame_all": _frame_all,
    "camera": _camera, "record": _record, "trash": _trash, "arrange": _arrange, "fold": _fold,
    "export": _export, "import": _import, "send": _send, "external": _external, "gear": _gear,
    "search": _search, "rename": _rename, "mute": _mute,
}

_made = {}


def texture(name, px=16):
    """The static texture for an icon, made the first time it is asked for."""
    import dearpygui.dearpygui as dpg
    key = (name, px)
    tag = _made.get(key)
    if tag and dpg.does_item_exist(tag):
        return tag
    if not dpg.does_item_exist("icon_registry"):
        dpg.add_texture_registry(tag="icon_registry")
    ic = Icon(px)
    ICONS[name](ic)
    tag = dpg.add_static_texture(px, px, ic.data(), parent="icon_registry")
    _made[key] = tag
    return tag


def sheet(path, px=16, scale=4):
    """Every icon on one PNG, for eyeballing them."""
    from native.png import write_rgb
    names = list(ICONS)
    cols = 8
    rows = (len(names) + cols - 1) // cols
    cell = px * scale + 8
    img = np.full((rows * cell, cols * cell, 3), 24, dtype=np.uint8)
    for i, n in enumerate(names):
        ic = Icon(px)
        ICONS[n](ic)
        a = np.array(ic.data(), dtype=np.float32).reshape(px, px, 4)[:, :, 3]
        big = np.kron(a, np.ones((scale, scale), dtype=np.float32))
        r, c = divmod(i, cols)
        y0, x0 = r * cell + 4, c * cell + 4
        for ch, v in enumerate((215, 219, 227)):
            img[y0:y0 + px * scale, x0:x0 + px * scale, ch] = (24 + (v - 24) * big).astype(np.uint8)
    write_rgb(path, img)


if __name__ == "__main__":
    import sys
    sheet(sys.argv[1] if len(sys.argv) > 1 else "icons.png")
    print("wrote", sys.argv[1] if len(sys.argv) > 1 else "icons.png")
