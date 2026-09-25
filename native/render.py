"""
Software renderer for the cube view.

No GPU. The cube is five FLAT faces, so each one is a single projective warp of
a B x B image - five vectorised numpy operations per frame rather than a quad
per pixel. That removes OpenGL, a windowing toolkit and a driver surface from
the dependency list, and it happens to be the right choice visually as well:
sampling is nearest-neighbour, so the LED grid stays hard-edged instead of being
smoothed into a texture.

The face table is a transcription of surfacePos() in index.html, which is itself
a transcription of cfx_pos() in cube_fx_common.h. This is the one thing that
must not drift - if the simulator disagrees with the firmware about where a
pixel lives, everything judged here is worthless.
"""
import numpy as np

# (block x, block y, origin, edge along a, edge along b) for the five lit faces.
# From surfacePos(bx, by, a, b) with a, b spanning -1..1 across the face:
#     TOP    ( a, -b,  1)      NORTH  ( a,  1,  b)     SOUTH  ( a, -1, -b)
#     WEST   (-1, -b,  a)      EAST   ( 1, -b, -a)
# Corners are evaluated at (a,b) = (-1,-1), (+1,-1), (+1,+1), (-1,+1), which is
# the same winding the net's pixel block uses, so face-local (u,v) maps straight
# onto the block without a flip anywhere.
def _face(bx, by, fn):
    corners = [fn(a, b) for a, b in ((-1, -1), (1, -1), (1, 1), (-1, 1))]
    return dict(bx=bx, by=by, corners=np.array(corners, np.float64))

FACES = [
    _face(1, 1, lambda a, b: (a, -b,  1.0)),   # TOP
    _face(1, 0, lambda a, b: (a,  1.0, b)),    # NORTH
    _face(1, 2, lambda a, b: (a, -1.0, -b)),   # SOUTH
    _face(0, 1, lambda a, b: (-1.0, -b, a)),   # WEST
    _face(2, 1, lambda a, b: (1.0, -b, -a)),   # EAST
]
# the sixth: a lit bottom, in the net's (2,2) corner block (cfx_pos's line for it)
BOTTOM = _face(2, 2, lambda a, b: (a, -b, -1.0))
FACES6 = FACES + [BOTTOM]


def _homography(src, dst):
    """3x3 taking src (4x2) onto dst (4x2)."""
    A, b = [], []
    for (x, y), (u, v) in zip(src, dst):
        A.append([x, y, 1, 0, 0, 0, -u * x, -u * y]); b.append(u)
        A.append([0, 0, 0, x, y, 1, -v * x, -v * y]); b.append(v)
    h = np.linalg.solve(np.asarray(A, np.float64), np.asarray(b, np.float64))
    return np.append(h, 1.0).reshape(3, 3)


def _camera(yaw, pitch, dist, look=None):
    """World -> view. Cube is +Z up, matching the geometry table above. The
    eye circles `look` (the pan, in the fitted -1..1 space; the origin when
    None) at `dist`."""
    cp, sp = np.cos(pitch), np.sin(pitch)
    cy, sy = np.cos(yaw), np.sin(yaw)
    eye = np.array([dist * cp * sy, dist * cp * cy, dist * sp])
    fwd = -eye / np.linalg.norm(eye)
    up0 = np.array([0.0, 0.0, 1.0])
    right = np.cross(fwd, up0)
    n = np.linalg.norm(right)
    right = np.array([1.0, 0.0, 0.0]) if n < 1e-6 else right / n
    up = np.cross(right, fwd)
    if look is not None:
        eye = eye + np.asarray(look, np.float64)
    return eye, np.stack([right, up, -fwd])


ORTHO_BACK = 30.0           # an orthographic eye stands this much farther back: nothing is behind it, the depth order holds


class Cam:
    """The 3-D view's camera for one size of view: perspective, or
    orthographic (every depth at the scale the look point has in
    perspective, so switching keeps the picture's size), panned by `look`.
    Positions are in the fitted -1..1 space (see frame_of)."""

    def __init__(self, yaw, pitch, dist, size, look=None, ortho=False, fov=38.0):
        self.dist, self.size, self.ortho = float(dist), float(size), bool(ortho)
        self.look = np.zeros(3) if look is None else np.asarray(look, np.float64)
        self.eye, self.R = _camera(yaw, pitch, dist + (ORTHO_BACK if ortho else 0.0), self.look)
        self.f = (size * 0.5) / np.tan(np.radians(fov) * 0.5)
        self.k = self.f / max(1e-6, self.dist)                  # pixels a unit, orthographic

    def view(self, P):
        """(n, 3) positions -> view space (x right, y up, -z the way it looks)."""
        return (np.asarray(P, np.float64) - self.eye) @ self.R.T

    def screen(self, P):
        """(sx, sy, ok, depth) of (n, 3) positions in the size x size view."""
        c = self.view(P)
        depth = -c[:, 2]
        ok = np.isfinite(depth) & (depth > 0.05)
        if self.ortho:
            return self.size * 0.5 + self.k * c[:, 0], self.size * 0.5 - self.k * c[:, 1], ok, depth
        d = np.where(ok, depth, 1.0)
        return self.size * 0.5 + self.f * c[:, 0] / d, self.size * 0.5 - self.f * c[:, 1] / d, ok, depth

    def scale(self, depth):
        """Pixels a unit at these depths (the LEDs' squares, a handle's reach)."""
        if self.ortho:
            return np.full(np.shape(depth), self.k)
        return self.f / np.where(np.asarray(depth) > 0.05, depth, 1.0)

    def ray(self, sx, sy):
        """The ray through a view pixel: (origin, unit direction), in the fitted space."""
        x, y = sx - self.size * 0.5, -(sy - self.size * 0.5)
        fwd = -self.R[2]
        if self.ortho:
            return self.eye + self.R[0] * (x / self.k) + self.R[1] * (y / self.k), fwd
        d = self.R.T @ np.array([x / self.f, y / self.f, -1.0])
        return self.eye.copy(), d / np.linalg.norm(d)


_GRID = {}


def _grid(size):
    """Screen coordinates, built once per view size and sliced per face.

    np.mgrid per face per frame was allocating two arrays the size of each
    face's bounding box, three times a frame, and they are the same numbers
    every time. float32 throughout as well - the projection needs nothing like
    float64's precision at screen scale, and halving the memory traffic is worth
    more here than the last eight digits.
    """
    g = _GRID.get(size)
    if g is None:
        yy, xx = np.mgrid[0:size, 0:size]
        g = (xx.astype(np.float32) + 0.5, yy.astype(np.float32) + 0.5)
        _GRID[size] = g
    return g


# --- what the view adds (the critique's C16) -------------------------------------------------------
# Unlit LEDs were drawn black on a near-black ground, so a torus running a fire was a black blob with a
# lit rim: an LED that is off is a dim dot now, where the view asks for one, and the shape stands on a
# faint floor. Pictures made elsewhere (the library's and the shape's previews) ask for neither.
UNLIT = (32, 34, 40)        # an LED that is off, as the view draws it: under most lit colours, over black
UNLIT_BELOW = 10            # a colour whose brightest channel is under this is off
DOT = 0.21                  # an unlit dot's radius on a face, in LED pitches
DOT_POINT = 0.4             # a point's unlit dot, against its lit square
FLOOR = (150, 162, 185)     # the floor's lines, faint (their alpha fades out from the middle)
FLOOR_SPAN, FLOOR_STEP, FLOOR_ALPHA = 1.8, 0.45, 0.2


def dotted(net, k, unlit=UNLIT):
    """The net at k times its size, each unlit LED a dot of `unlit` in the
    middle of its k x k block (the rest of it black) - the GPU cube's
    texture, where the software renderer draws the dots itself."""
    big = net.repeat(k, 0).repeat(k, 1)
    off = (net.max(axis=2) < UNLIT_BELOW).repeat(k, 0).repeat(k, 1)
    c = (np.arange(k) + 0.5) / k - 0.5
    cell = (c[:, None] ** 2 + c[None, :] ** 2) <= DOT * DOT * 1.6          # a k x k block's dot, round enough at k = 4
    h, w = net.shape[:2]
    dot = np.tile(cell, (h, w))
    big = big.copy() if not big.flags.writeable else big
    big[off & dot] = unlit
    return big


FLOOR_POOL = 240            # the GPU floor's line items: enough for a floor of any step floor_step gives


def floor_lines(span=FLOOR_SPAN, step=FLOOR_STEP, origin=(0.0, 0.0)):
    """The floor's lines on each axis: every `step` through `origin` (the
    fitted space's place of the world's 0, so a shape's lines fall on round
    distances), within +/- span of the middle."""
    out = []
    for o in origin[:2]:
        first = o + np.ceil((-span - o) / step) * step
        out.append(np.arange(first, span + 1e-6, step))
    return out


def floor_segments(z, span=FLOOR_SPAN, step=FLOOR_STEP, pieces=8, origin=(0.0, 0.0)):
    """The floor's grid as short segments on the plane z, each with the
    alpha it fades to by its distance from the middle: [(p0, p1, a)]."""
    out = []
    xs, ys = floor_lines(span, step, origin)
    ts = np.linspace(-span, span, pieces + 1)
    for c, along_y in [(c, True) for c in xs] + [(c, False) for c in ys]:
        for t0, t1 in zip(ts[:-1], ts[1:]):
            p0, p1 = ((c, t0, z), (c, t1, z)) if along_y else ((t0, c, z), (t1, c, z))
            m = np.hypot((p0[0] + p1[0]) / 2, (p0[1] + p1[1]) / 2)
            a = FLOOR_ALPHA * max(0.0, 1.0 - m / (span * 1.15))
            if a > 0.004:
                out.append((np.array(p0), np.array(p1), a))
    return out[:FLOOR_POOL]


def _floor(out, cam, z, off=(0.0, 0.0), step=FLOOR_STEP, origin=(0.0, 0.0)):
    """The floor drawn onto a picture: its grid sampled a pixel or so apart
    and blended in, fading out from the middle; from below it is left out."""
    if cam.eye[2] <= z + 0.02:
        return
    size = out.shape[0]
    span = FLOOR_SPAN
    ts = np.linspace(-span, span, max(200, size))
    pts = []
    xs, ys = floor_lines(span, step, origin)
    for c in xs:
        pts.append(np.stack([np.full_like(ts, c), ts, np.full_like(ts, z)], 1))
    for c in ys:
        pts.append(np.stack([ts, np.full_like(ts, c), np.full_like(ts, z)], 1))
    P = np.concatenate(pts)
    sx, sy, ok, _ = cam.screen(P)
    sx = (off[0] + sx).astype(np.int32)
    sy = (off[1] + sy).astype(np.int32)
    ok &= (sx >= 0) & (sx < out.shape[1]) & (sy >= 0) & (sy < out.shape[0])
    a = (FLOOR_ALPHA * np.clip(1.0 - np.hypot(P[:, 0], P[:, 1]) / (span * 1.15), 0.0, 1.0))[ok][:, None]
    ys_, xs_ = sy[ok], sx[ok]
    out[ys_, xs_] = (out[ys_, xs_].astype(np.float32) * (1.0 - a) + np.asarray(FLOOR, np.float32) * a).astype(np.uint8)


def render(net_rgb, B, size, yaw, pitch, dist, fov=38.0, bg=(0, 0, 0), six=False, unlit=None, floor=False,
           look=None, ortho=False):
    """Draw the cube from the unfolded net image.

    net_rgb : (3B, 3B, 3) uint8 - the same image the flat view shows
    six     : the bottom face too (seen from below)
    unlit   : a colour an LED that is off is drawn as, a dot in its cell (None: black)
    floor   : a faint grid under the cube
    look, ortho : the camera's pan and projection (see Cam)
    returns : (size, size, 3) uint8
    """
    out = np.zeros((size, size, 3), np.uint8)
    out[:] = bg
    cam = Cam(yaw, pitch, dist, size, look, ortho, fov)
    eye = cam.eye
    if floor:
        _floor(out, cam, -1.1)

    drawn = []
    for fc in (FACES6 if six else FACES):
        c = fc["corners"]
        centre = c.mean(axis=0)
        # Outward normal of a cube face is its own centre direction. Cull when
        # it points away, so at most three faces are ever rasterised.
        if np.dot(centre, centre - eye) >= 0:
            continue
        sx, sy, ok, _ = cam.screen(c)
        if not ok.all():                         # behind or through the eye
            continue
        scr = np.stack([sx, sy], axis=1)
        drawn.append((float(np.linalg.norm(centre - eye)), fc, scr))

    # Painter's algorithm: far faces first. With a convex solid and backface
    # culling this is exact, no z-buffer needed.
    for _, fc, scr in sorted(drawn, key=lambda t: -t[0]):
        x0 = max(0, int(np.floor(scr[:, 0].min())))
        x1 = min(size, int(np.ceil(scr[:, 0].max())) + 1)
        y0 = max(0, int(np.floor(scr[:, 1].min())))
        y1 = min(size, int(np.ceil(scr[:, 1].max())) + 1)
        if x1 <= x0 or y1 <= y0:
            continue

        # Screen -> face-local pixel coordinates, applied by inverse mapping so
        # every output pixel is written exactly once and no seams open up.
        src = np.array([[0, 0], [B, 0], [B, B], [0, B]], np.float64)
        try:
            H = _homography(scr, src)
        except np.linalg.LinAlgError:            # degenerate, face edge-on
            continue

        # Sliced from the cached grid, and kept two-dimensional the whole way.
        # The previous version did out[y0:y1, x0:x1].reshape(-1, 3), which on a
        # non-contiguous view is a silent COPY - so every face paid for a copy
        # out, a scatter, and a copy back. Indexing the view with a 2-D boolean
        # mask writes straight into the output.
        gx, gy = _grid(size)
        sx_ = gx[y0:y1, x0:x1]
        sy_ = gy[y0:y1, x0:x1]
        Hf = H.astype(np.float32)
        u = Hf[0, 0] * sx_ + Hf[0, 1] * sy_ + Hf[0, 2]
        v = Hf[1, 0] * sx_ + Hf[1, 1] * sy_ + Hf[1, 2]
        w = Hf[2, 0] * sx_ + Hf[2, 1] * sy_ + Hf[2, 2]
        np.copysign(np.maximum(np.abs(w), 1e-12), w, out=w)
        u /= w
        v /= w
        inside = (u >= 0) & (u < B) & (v >= 0) & (v < B)
        if not inside.any():
            continue
        ui = u[inside].astype(np.int32)
        vi = v[inside].astype(np.int32)
        np.clip(ui, 0, B - 1, out=ui)
        np.clip(vi, 0, B - 1, out=vi)
        block = net_rgb[fc["by"] * B:(fc["by"] + 1) * B,
                        fc["bx"] * B:(fc["bx"] + 1) * B]
        px_ = block[vi, ui]
        if unlit is not None:
            # an LED that is off: a dim dot in the middle of its cell, black round it
            fu, fv = u[inside] - ui - 0.5, v[inside] - vi - 0.5
            px_ = px_.copy()
            px_[(px_.max(axis=1) < UNLIT_BELOW) & (fu * fu + fv * fv <= DOT * DOT)] = unlit
        out[y0:y1, x0:x1][inside] = px_
    return out


def texture_rgba(frame):
    """An (h, w, 3) uint8 frame as the flat RGBA floats a Dear PyGui texture takes."""
    h, w = frame.shape[:2]
    out = np.ones((h, w, 4), np.float32)
    out[:, :, :3] = frame.astype(np.float32) / 255.0
    return out.ravel()


def frame_of(pos):
    """How render_points fits a geometry: (centre, extent) - the middle of
    its bounding box, and the largest distance from there along an axis."""
    pos = np.asarray(pos, np.float32)
    if len(pos) == 0 or not np.isfinite(pos).any():
        return np.zeros(3, np.float32), 1.0
    c = (np.nanmin(pos, 0) + np.nanmax(pos, 0)) * 0.5
    e = float(np.nanmax(np.abs(pos - c)))
    return c.astype(np.float32), (e if e > 0 else 1.0)


def project(pos, size, yaw, pitch, dist, fov=38.0, frame=None, look=None, ortho=False):
    """Where each position lands in the size x size view: (sx, sy, ok)."""
    c, ext = frame or frame_of(pos)
    P = (np.asarray(pos, np.float32) - c) * (1.0 / ext)
    sx, sy, ok, _ = Cam(yaw, pitch, dist, size, look, ortho, fov).screen(P)
    return sx, sy, ok


def unproject(sx, sy, size, yaw, pitch, dist, frame, axis=2, value=0.0, fov=38.0, look=None, ortho=False):
    """The point of the plane `axis` = `value` (geometry units) under a
    view pixel, or None when the ray misses it."""
    c, ext = frame
    o, d = Cam(yaw, pitch, dist, size, look, ortho, fov).ray(sx, sy)
    if abs(d[axis]) < 1e-9:
        return None
    t = ((value - c[axis]) / ext - o[axis]) / d[axis]
    if t <= 0:
        return None
    return (o + t * d) * ext + c


def render_points(pos, rgb, size, yaw, pitch, dist, fov=38.0, bg=(0, 0, 0), led=0.42, unlit=None, floor=False,
                  frame=None, look=None, ortho=False, floor_step=None):
    """Draw any geometry as a cloud of LEDs (an LED that is off a smaller
    square of `unlit` when given; a faint floor under the shape with `floor`).

    pos : (n, 3) float, Z up, in the units Geometry uses (a cube of B pixels a
          face spans +/- B/2); NaN rows are skipped
    rgb : (n, 3) uint8
    frame : (centre, extent) the positions are fitted by (frame_of theirs when None)
    look, ortho : the camera's pan and projection (see Cam)
    floor_step : (step, origin) of the floor's lines in the fitted space (the default floor when None)
    Each LED is a square whose screen size follows its depth, painted far to
    near so nearer ones cover. No lighting, no smoothing: the point of the view
    is to see the LEDs, and an LED is a hard-edged square of one colour.
    """
    out = np.zeros((size, size, 3), np.uint8)
    out[:] = bg
    n = len(pos)
    if n == 0:
        return out
    # scale so a shape of any pixel count fills the same frame as the cube, centred
    c, ext = frame or frame_of(pos)
    P = (pos - c) * (1.0 / ext)                 # -1..1
    cam = Cam(yaw, pitch, dist, size, look, ortho, fov)
    sx, sy, ok, depth = cam.screen(P)
    # LED half-size on screen: the LED pitch in world units (1/ext per pixel),
    # times led (fraction of the pitch the emitter covers), projected
    half = cam.scale(depth) * (led / ext)
    if floor:
        st, org = floor_step or (FLOOR_STEP, (0.0, 0.0))
        _floor(out, cam, float(np.nanmin(P[:, 2])) - 0.08 if np.isfinite(P[:, 2]).any() else -1.1, step=st, origin=org)
    off = (np.asarray(rgb).max(axis=1) < UNLIT_BELOW) if unlit is not None else None
    order = np.argsort(-depth)                  # far first
    for i in order:
        if not ok[i]:
            continue
        if off is not None and off[i]:
            h = max(1, int(round(half[i] * DOT_POINT)))         # off: a dim dot, smaller than a lit LED
            x0 = int(sx[i]) - h; x1 = int(sx[i]) + h
            y0 = int(sy[i]) - h; y1 = int(sy[i]) + h
            if x1 <= 0 or y1 <= 0 or x0 >= size or y0 >= size:
                continue
            out[max(0, y0):min(size, y1), max(0, x0):min(size, x1)] = unlit
            continue
        h = max(1, int(round(half[i])))
        x0 = int(sx[i]) - h; x1 = int(sx[i]) + h
        y0 = int(sy[i]) - h; y1 = int(sy[i]) + h
        if x1 <= 0 or y1 <= 0 or x0 >= size or y0 >= size:
            continue
        out[max(0, y0):min(size, y1), max(0, x0):min(size, x1)] = rgb[i]
    return out
