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


def _camera(yaw, pitch, dist):
    """World -> view. Cube is +Z up, matching the geometry table above."""
    cp, sp = np.cos(pitch), np.sin(pitch)
    cy, sy = np.cos(yaw), np.sin(yaw)
    eye = np.array([dist * cp * sy, dist * cp * cy, dist * sp])
    fwd = -eye / np.linalg.norm(eye)
    up0 = np.array([0.0, 0.0, 1.0])
    right = np.cross(fwd, up0)
    n = np.linalg.norm(right)
    right = np.array([1.0, 0.0, 0.0]) if n < 1e-6 else right / n
    up = np.cross(right, fwd)
    return eye, np.stack([right, up, -fwd])


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


def floor_segments(z, span=FLOOR_SPAN, step=FLOOR_STEP, pieces=8):
    """The floor's grid as short segments on the plane z, each with the
    alpha it fades to by its distance from the middle: [(p0, p1, a)]."""
    out = []
    lines = np.arange(-span, span + 1e-6, step)
    ts = np.linspace(-span, span, pieces + 1)
    for c in lines:
        for t0, t1 in zip(ts[:-1], ts[1:]):
            for p0, p1 in (((c, t0, z), (c, t1, z)), ((t0, c, z), (t1, c, z))):
                m = np.hypot((p0[0] + p1[0]) / 2, (p0[1] + p1[1]) / 2)
                a = FLOOR_ALPHA * max(0.0, 1.0 - m / (span * 1.15))
                if a > 0.004:
                    out.append((np.array(p0), np.array(p1), a))
    return out


def _floor(out, eye, R, f, z, off=(0.0, 0.0)):
    """The floor drawn onto a picture: its grid sampled a pixel or so apart
    and blended in, fading out from the middle; from below it is left out."""
    if eye[2] <= z + 0.02:
        return
    size = out.shape[0]
    span = FLOOR_SPAN
    ts = np.linspace(-span, span, max(200, size))
    pts = []
    for c in np.arange(-span, span + 1e-6, FLOOR_STEP):
        pts.append(np.stack([np.full_like(ts, c), ts, np.full_like(ts, z)], 1))
        pts.append(np.stack([ts, np.full_like(ts, c), np.full_like(ts, z)], 1))
    P = np.concatenate(pts)
    cam = (P - eye) @ R.T
    depth = -cam[:, 2]
    ok = depth > 0.05
    d = np.where(ok, depth, 1.0)
    sx = (off[0] + size * 0.5 + f * cam[:, 0] / d).astype(np.int32)
    sy = (off[1] + size * 0.5 - f * cam[:, 1] / d).astype(np.int32)
    ok &= (sx >= 0) & (sx < out.shape[1]) & (sy >= 0) & (sy < out.shape[0])
    a = (FLOOR_ALPHA * np.clip(1.0 - np.hypot(P[:, 0], P[:, 1]) / (span * 1.15), 0.0, 1.0))[ok][:, None]
    ys, xs = sy[ok], sx[ok]
    out[ys, xs] = (out[ys, xs].astype(np.float32) * (1.0 - a) + np.asarray(FLOOR, np.float32) * a).astype(np.uint8)


def render(net_rgb, B, size, yaw, pitch, dist, fov=38.0, bg=(0, 0, 0), six=False, unlit=None, floor=False):
    """Draw the cube from the unfolded net image.

    net_rgb : (3B, 3B, 3) uint8 - the same image the flat view shows
    six     : the bottom face too (seen from below)
    unlit   : a colour an LED that is off is drawn as, a dot in its cell (None: black)
    floor   : a faint grid under the cube
    returns : (size, size, 3) uint8
    """
    out = np.zeros((size, size, 3), np.uint8)
    out[:] = bg
    eye, R = _camera(yaw, pitch, dist)
    f = (size * 0.5) / np.tan(np.radians(fov) * 0.5)
    if floor:
        _floor(out, eye, R, f, -1.1)

    drawn = []
    for fc in (FACES6 if six else FACES):
        c = fc["corners"]
        centre = c.mean(axis=0)
        # Outward normal of a cube face is its own centre direction. Cull when
        # it points away, so at most three faces are ever rasterised.
        if np.dot(centre, centre - eye) >= 0:
            continue
        cam = (c - eye) @ R.T
        if np.any(cam[:, 2] > -0.05):            # behind or through the eye
            continue
        scr = np.stack([size * 0.5 + f * cam[:, 0] / -cam[:, 2],
                        size * 0.5 - f * cam[:, 1] / -cam[:, 2]], axis=1)
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


def project(pos, size, yaw, pitch, dist, fov=38.0, frame=None):
    """Where each position lands in the size x size view: (sx, sy, ok)."""
    c, ext = frame or frame_of(pos)
    P = (np.asarray(pos, np.float32) - c) * (1.0 / ext)
    eye, R = _camera(yaw, pitch, dist)
    cam = (P - eye) @ R.T
    depth = -cam[:, 2]
    ok = np.isfinite(depth) & (depth > 0.05)
    f = (size * 0.5) / np.tan(np.radians(fov) * 0.5)
    d = np.where(ok, depth, 1.0)
    return size * 0.5 + f * cam[:, 0] / d, size * 0.5 - f * cam[:, 1] / d, ok


def unproject(sx, sy, size, yaw, pitch, dist, frame, axis=2, value=0.0, fov=38.0):
    """The point of the plane `axis` = `value` (geometry units) under a
    view pixel, or None when the ray misses it."""
    c, ext = frame
    eye, R = _camera(yaw, pitch, dist)
    f = (size * 0.5) / np.tan(np.radians(fov) * 0.5)
    d = R.T @ np.array([(sx - size * 0.5) / f, -(sy - size * 0.5) / f, -1.0])
    if abs(d[axis]) < 1e-9:
        return None
    t = ((value - c[axis]) / ext - eye[axis]) / d[axis]
    if t <= 0:
        return None
    return (eye + t * d) * ext + c


def render_points(pos, rgb, size, yaw, pitch, dist, fov=38.0, bg=(0, 0, 0), led=0.42, unlit=None, floor=False):
    """Draw any geometry as a cloud of LEDs (an LED that is off a smaller
    square of `unlit` when given; a faint floor under the shape with `floor`).

    pos : (n, 3) float, Z up, in the units Geometry uses (a cube of B pixels a
          face spans +/- B/2); NaN rows are skipped
    rgb : (n, 3) uint8
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
    c, ext = frame_of(pos)
    P = (pos - c) * (1.0 / ext)                 # -1..1
    eye, R = _camera(yaw, pitch, dist)
    cam = (P - eye) @ R.T
    depth = -cam[:, 2]
    ok = np.isfinite(depth) & (depth > 0.05)
    f = (size * 0.5) / np.tan(np.radians(fov) * 0.5)
    sx = size * 0.5 + f * cam[:, 0] / np.where(ok, depth, 1.0)
    sy = size * 0.5 - f * cam[:, 1] / np.where(ok, depth, 1.0)
    # LED half-size on screen: the LED pitch in world units (1/ext per pixel),
    # times led (fraction of the pitch the emitter covers), projected
    half = (f * (led / ext)) / np.where(ok, depth, 1.0)
    if floor:
        _floor(out, eye, R, f, float(np.nanmin(P[:, 2])) - 0.08 if np.isfinite(P[:, 2]).any() else -1.1)
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
