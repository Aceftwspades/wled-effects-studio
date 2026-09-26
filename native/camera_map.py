"""Mapping lights by camera (the ninth pass's S18): where each LED of a
string with no pattern is - fairy lights on a real tree - found from films
of it with the LEDs lit one at a time.

The studio plays a **plan**: every LED white (a flash the film's brightness
finds), dark, each LED alone in wiring order for `on` seconds, dark, white
again (a second flash: the film's clock against the studio's, so a camera
that runs a little fast or slow, and the stream's delay, cost nothing).
Filmed from the front, then with the object turned a quarter (or more
sides), each film gives every LED's place on its picture; the sides
together give 3-D:

    turned by angle a (anticlockwise seen from above), a point (x, y, z)
    lands at u = x cos a - y sin a (+ where the turning axis is in the
    picture), v = -z (+ the picture's height offset) - orthographic, the
    camera well back

so x and y come out of two or more sides by least squares, z from all of
them. A side filmed with the camera moved is brought to the first side's
scale by the heights both see. An LED no side found is put between its
neighbours in the wiring; one only one side saw gets its missing depth from
them. The picture's units become real ones by the object's height, which
you measure.

The film comes as a video any camera made, decoded by ffmpeg (two passes:
the brightness of every frame to find the flashes, then only the frames
wanted), or live from a webcam (OpenCV, optional).

    plan = camera_map.Plan(n, on=0.2)
    plan.at(t)                                   # ("all" | "none" | k): what is lit t seconds in
    frames, fps = camera_map.read_video(path)     # or synthetic_video(...) in the tests
    side = camera_map.scan(frames, fps, plan)     # {k: (u, v, conf)}, the dark frame
    pos, found = camera_map.combine([(0, side0), (90, side1)], n)
    part = camera_map.to_part(pos, found, height)  # a points part, sized in the shape's units
"""
import json
import math
import shutil
import subprocess

import numpy as np

SYNC = 1.0            # seconds the flashes last
GAP = 0.6             # seconds dark either side of the LEDs' run
CONF = 10.0           # a spot this many times the picture's noise above it is an LED


class Plan:
    """What is lit when, from 0 to `total` seconds."""

    def __init__(self, n, on=0.2, off=0.05, sync=SYNC, gap=GAP):
        self.n, self.on, self.off, self.sync, self.gap = max(1, int(n)), float(on), float(off), float(sync), float(gap)
        self.step = self.on + self.off
        self.first = self.sync + self.gap                      # LED 0 comes on here
        self.end = self.first + self.n * self.step + self.gap  # the closing flash starts here
        self.total = self.end + self.sync

    def at(self, t):
        """What is lit t seconds in: "all" (a flash), an LED's index, or "none"."""
        if t < 0 or t >= self.total:
            return "none"
        if t < self.sync or t >= self.end:
            return "all"
        k = int((t - self.first) // self.step)
        if 0 <= k < self.n and (t - self.first) - k * self.step < self.on:
            return k
        return "none"

    def lit_time(self, k):
        """When LED k is best caught: well into its time on (the stream's and the camera's delay allowed for)."""
        return self.first + k * self.step + self.on * 0.62

    def dark_time(self):
        return self.sync + self.gap * 0.5


# --- the film: decoded to grey frames ---------------------------------------------------------
def ffmpeg():
    return shutil.which("ffmpeg")


def _probe(path):
    """(width, height, fps) of a video, from ffprobe (or ffmpeg's own words)."""
    from native import procs
    fp = shutil.which("ffprobe")
    if fp:
        out = procs.run([fp, "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height,avg_frame_rate",
                              "-of", "json", path], capture_output=True, text=True, timeout=60)
        s = json.loads(out.stdout or "{}").get("streams", [{}])[0]
        num, _, den = str(s.get("avg_frame_rate", "30/1")).partition("/")
        fps = float(num) / float(den or 1) if float(den or 1) else 30.0
        return int(s.get("width", 0)), int(s.get("height", 0)), fps
    out = procs.run([ffmpeg(), "-i", path], capture_output=True, text=True, timeout=60).stderr
    import re
    m = re.search(r"(\d{2,5})x(\d{2,5})[^\n]*?(\d+(?:\.\d+)?) fps", out)
    if not m:
        raise ValueError("could not read the video's size and rate")
    return int(m.group(1)), int(m.group(2)), float(m.group(3))


def _frames(path, across):
    """Grey frames `across` pixels wide, one at a time, through ffmpeg."""
    w0, h0, fps = _probe(path)
    h = max(2, int(round(h0 * across / max(1, w0))) // 2 * 2)
    cmd = [ffmpeg(), "-v", "error", "-i", path, "-vf", f"scale={across}:{h},format=gray", "-f", "rawvideo", "-pix_fmt", "gray", "-"]
    from native import procs
    p = procs.popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    size = across * h
    try:
        while True:
            buf = p.stdout.read(size)
            if len(buf) < size:
                break
            yield np.frombuffer(buf, np.uint8).reshape(h, across)
    finally:
        p.stdout.close()
        p.wait()


def read_video(path, plan, across=320, log=lambda m: None):
    """A film analysed the lean way, scaled to `across` pixels wide: one pass
    for every frame's brightness (the flashes), a second keeping only the
    frames the plan wants. (frames: {index: grey frame}, fps, times: {what:
    frame index})."""
    if not ffmpeg():
        raise ValueError("reading a video needs ffmpeg (on the PATH)")
    _, _, fps = _probe(path)
    bright = []
    for f in _frames(path, across):
        bright.append(float(f.mean()))
        if len(bright) % 300 == 0:
            log(f"{len(bright) / fps:.0f} s of the film read")
    bright = np.asarray(bright, np.float64)
    log(f"{len(bright)} frames at {fps:g} fps: finding the LEDs")
    want = frame_times(bright, fps, plan)
    need = set(want.values())
    last = max(need)
    keep = {}
    for i, f in enumerate(_frames(path, across)):
        if i in need:
            keep[i] = f.astype(np.float32)
        if i >= last:
            break
    return keep, fps, want


def resample(frames, stamps, fps=30.0):
    """Frames taken at uneven times (a webcam's) as a film at a steady `fps`:
    for each tick the frame nearest it (the same frame again where the camera
    fell behind) - so the plan's times land on the right pictures."""
    t = np.asarray(stamps, np.float64)
    if len(t) < 2:
        return list(frames), fps
    ticks = np.arange(t[0], t[-1], 1.0 / fps)
    idx = np.clip(np.searchsorted(t, ticks), 1, len(t) - 1)
    idx = np.where(np.abs(t[idx - 1] - ticks) <= np.abs(t[idx] - ticks), idx - 1, idx)
    return [frames[i] for i in idx], fps


def find_flashes(bright, fps, plan):
    """The two flashes in a film's brightness: (first's start, last's start) in seconds."""
    b = np.asarray(bright, np.float64)
    if len(b) < 4:
        raise ValueError("the film is too short")
    lo, hi = np.percentile(b, 5), float(b.max())
    if hi - lo < 1.0:
        raise ValueError("no flash in the film: was the object in view, lit by the plan?")
    on = b > lo + 0.5 * (hi - lo)
    runs, start = [], None
    for i, v in enumerate(np.append(on, False)):
        if v and start is None:
            start = i
        elif not v and start is not None:
            runs.append((start, i)); start = None
    long_enough = [(a, z) for a, z in runs if (z - a) / fps >= plan.sync * 0.5]
    if len(long_enough) < 2:
        raise ValueError("the two flashes were not both found: film from before the plan starts to after it ends")
    return long_enough[0][0] / fps, long_enough[-1][0] / fps


def frame_times(bright, fps, plan):
    """{"dark": frame, k: frame for each LED}: the plan's times on the film's clock (the flashes pin both ends)."""
    t0, t1 = find_flashes(bright, fps, plan)
    scale = (t1 - t0) / plan.end
    to_frame = lambda p: int(round((t0 + p * scale) * fps))
    out = {"dark": to_frame(plan.dark_time())}
    for k in range(plan.n):
        out[k] = to_frame(plan.lit_time(k))
    return out


# --- an LED on a picture ----------------------------------------------------------------------
def _box(a, r):
    """A box blur of radius r (a cumulative sum each way)."""
    if r <= 0:
        return a
    k = 2 * r + 1
    p = np.pad(a, r, mode="edge")
    c = np.cumsum(np.cumsum(p, 0), 1)
    c = np.pad(c, ((1, 0), (1, 0)))
    return (c[k:, k:] - c[:-k, k:] - c[k:, :-k] + c[:-k, :-k]) / (k * k)


def detect(lit, dark):
    """The lit LED on a picture against the dark one: (u, v, conf) - its
    centre in pixels (sub-pixel), and how far it stands above the noise:
    the brightest spot of the difference, softened, in units of the
    difference's own spread (its median absolute deviation - a lit spot
    does not move it; the noise's highest spot on a picture this size is
    some four or five of them, an LED tens)."""
    d = np.asarray(lit, np.float32) - np.asarray(dark, np.float32)
    s = _box(_box(d, 1), 1)
    k = int(np.argmax(s))
    y, x = divmod(k, s.shape[1])
    peak = float(s[y, x])
    med = float(np.median(s))
    spread = 1.4826 * float(np.median(np.abs(s - med))) + 1e-3
    conf = (peak - med) / spread if peak - med >= 6.0 else 0.0      # and a few grey levels at least
    y0, y1, x0, x1 = max(0, y - 3), min(s.shape[0], y + 4), max(0, x - 3), min(s.shape[1], x + 4)
    w = s[y0:y1, x0:x1]
    w = np.clip(w - peak * 0.5, 0, None)
    if w.sum() > 0:
        ys, xs = np.mgrid[y0:y1, x0:x1]
        return float((xs * w).sum() / w.sum()), float((ys * w).sum() / w.sum()), conf
    return float(x), float(y), conf


def scan(frames, fps, plan, times=None, log=lambda m: None):
    """One side: every LED's place on its pictures. `frames`: a list of grey
    frames, or {index: frame} with `times` (read_video's). ({k: (u, v, conf)}, the dark frame)."""
    if times is None:
        bright = [float(np.asarray(f).mean()) for f in frames]
        times = frame_times(bright, fps, plan)
        frames = {i: np.asarray(f, np.float32) for i, f in enumerate(frames)}
    dark = frames.get(times["dark"])
    if dark is None:
        raise ValueError("the dark frame is missing")
    out = {}
    for k in range(plan.n):
        f = frames.get(times.get(k))
        if f is None:
            continue
        u, v, c = detect(f, dark)
        if c >= CONF:
            out[k] = (u, v, c)
    log(f"{len(out)} of {plan.n} LEDs found")
    return out, dark


# --- the sides together: 3-D ------------------------------------------------------------------
def combine(sides, n, iterations=12):
    """Sides [(angle in degrees, {k: (u, v, conf)})] into (pos (n, 3), found
    (n,) bool): x and y by least squares over the sides that saw an LED (the
    turning axis's place in each picture worked out as it goes), z from the
    pictures' heights; the pictures in the first side's pixels, a side filmed
    from elsewhere brought to its scale by the LEDs both see. An LED no side
    saw goes between its wiring neighbours; one only one side saw takes its
    unseen depth from theirs."""
    sides = [(float(a), {k: v for k, v in dict(s).items() if 0 <= k < n}) for a, s in sides if s]    # a count lowered since: the rest dropped
    sides = [(a, s) for a, s in sides if s]
    if not sides:
        raise ValueError("no side has any LED found")
    if len(sides) == 1:
        return _flat(sides[0], n)
    # every side in the first side's pixels: v' = a v + b from the LEDs both see (u scales the same)
    base = sides[0][1]
    norm = []
    for ang, s in sides:
        both = [k for k in s if k in base]
        a, b = 1.0, 0.0
        if len(both) >= 8 and s is not base:
            v0 = np.asarray([base[k][1] for k in both]); v1 = np.asarray([s[k][1] for k in both])
            A = np.stack([v1, np.ones_like(v1)], 1)
            (a, b), *_ = np.linalg.lstsq(A, v0, rcond=None)
            if not (0.2 < abs(a) < 5.0):
                a, b = 1.0, float(np.median(v0 - v1))
        norm.append((math.radians(ang), {k: (u * a, v * a + b) for k, (u, v, _) in s.items()}))
    # z: the mean height over the sides (up is -v)
    z = np.full(n, np.nan)
    for k in range(n):
        vs = [s[k][1] for _, s in norm if k in s]
        if vs:
            z[k] = -float(np.mean(vs))
    # x, y: u_i = x cos a_i - y sin a_i + c_i, the c_i (the axis's column) found as it goes
    c = np.asarray([np.median([u for u, _ in s.values()]) for _, s in norm])
    x = np.full(n, np.nan); y = np.full(n, np.nan)
    seen = [[i for i, (_, s) in enumerate(norm) if k in s] for k in range(n)]
    for _ in range(iterations):
        for k in range(n):
            if len(seen[k]) >= 2:
                A = np.asarray([[math.cos(norm[i][0]), -math.sin(norm[i][0])] for i in seen[k]])
                r = np.asarray([norm[i][1][k][0] - c[i] for i in seen[k]])
                (x[k], y[k]), *_ = np.linalg.lstsq(A, r, rcond=None)
        for i, (a, s) in enumerate(norm):
            res = [s[k][0] - (x[k] * math.cos(a) - y[k] * math.sin(a)) for k in s if np.isfinite(x[k])]
            if res and i > 0:
                c[i] = float(np.median(res))
    full = np.isfinite(x) & np.isfinite(z)
    # seen by one side only: its depth from the wiring neighbours, the rest from its picture
    for k in range(n):
        if not full[k] and len(seen[k]) == 1:
            i = seen[k][0]
            a = norm[i][0]
            depth = _neighbour(x * math.sin(a) + y * math.cos(a), full, k)        # along this side's line of sight
            along = norm[i][1][k][0] - c[i]
            if depth is not None:
                x[k] = along * math.cos(a) + depth * math.sin(a)
                y[k] = -along * math.sin(a) + depth * math.cos(a)
    pos = np.stack([x, y, z], 1)
    found = np.isfinite(pos).all(1)
    # seen by none (or half-known with nothing to borrow): between the wiring neighbours
    good = np.nonzero(found)[0]
    if len(good) == 0:
        raise ValueError("no LED was seen from enough sides to place it")
    _between(pos, found)
    return pos, full


def _between(pos, found):
    """Each LED not found put between the nearest found ones either side in the wiring (in place)."""
    good = np.nonzero(found)[0]
    for k in range(len(pos)):
        if not found[k]:
            before = good[good < k]; after = good[good > k]
            if len(before) and len(after):
                a, b = before[-1], after[0]
                t = (k - a) / (b - a)
                pos[k] = pos[a] + (pos[b] - pos[a]) * t
            else:
                pos[k] = pos[before[-1]] if len(before) else pos[after[0]]


def _flat(side, n):
    """One side only: the LEDs flat in the plane that side faces (no depth) -
    right for a window, a wall, a sign; a second side makes it 3-D."""
    ang, s = side
    a = math.radians(ang)
    pos = np.full((n, 3), np.nan)
    for k, (u, v, _) in s.items():
        if 0 <= k < n:
            pos[k] = (u * math.cos(a), -u * math.sin(a), -v)
    full = np.isfinite(pos).all(1)
    if not full.any():
        raise ValueError("no LED was found on the film")
    _between(pos, full)
    return pos, full


def _neighbour(values, full, k):
    """A value at k from the nearest fully known LEDs either side in the wiring (their mean, or the one there is)."""
    good = np.nonzero(full)[0]
    if len(good) == 0:
        return None
    before = good[good < k]; after = good[good > k]
    picks = ([values[before[-1]]] if len(before) else []) + ([values[after[0]]] if len(after) else [])
    return float(np.mean(picks)) if picks else None


def to_part(pos, found, height=None, name="mapped lights"):
    """A points part: the positions centred on the floor, Z up, sized so the
    object is `height` tall (the shape's units), or its LEDs a spacing apart
    as the wiring runs (median) when no height is given."""
    from native import shapes
    P = np.asarray(pos, np.float64).copy()
    P -= [(P[:, 0].min() + P[:, 0].max()) / 2, (P[:, 1].min() + P[:, 1].max()) / 2, P[:, 2].min()]
    if height:
        span = float(np.ptp(P[:, 2])) or 1.0
        P *= float(height) / span
    else:
        steps = np.linalg.norm(np.diff(P, axis=0), axis=1)
        med = float(np.median(steps[steps > 0])) if np.any(steps > 0) else 1.0
        P /= med
    q = shapes.new_part("points", points=np.round(P, 4).tolist())
    q["name"] = name
    q["guessed"] = [int(k) for k in np.nonzero(~np.asarray(found, bool))[0]]    # placed between neighbours: worth a look
    return q


# --- a synthetic camera, for the tests (and a demonstration) -----------------------------------
def synthetic_video(P, plan, angle, fps=30.0, size=(240, 320), noise=2.0, hide=(), scale=None, offset=(0.0, 0.0), seed=0):
    """Frames of a film of points P (n, 3) lit by the plan, the object turned
    `angle` degrees, the camera far off (orthographic): a dark room, the lit
    LEDs as soft spots, the flashes lighting them all; `hide`: LEDs out of
    this side's sight."""
    rs = np.random.RandomState(seed)
    P = np.asarray(P, np.float64)
    h, w = size
    a = math.radians(angle)
    X = P[:, 0] * math.cos(a) - P[:, 1] * math.sin(a)
    s = scale or 0.8 * min(h, w) / max(1e-6, float(np.ptp(P[:, 2]) or 1.0))
    u = w / 2 + X * s + offset[0]
    v = h / 2 - (P[:, 2] - P[:, 2].mean()) * s + offset[1]
    ys, xs = np.mgrid[0:h, 0:w].astype(np.float32)
    hidden = set(hide)

    def spot(k, level):
        return level * np.exp(-((xs - u[k]) ** 2 + (ys - v[k]) ** 2) / (2 * 1.6 ** 2))

    base = 12.0 + rs.normal(0, noise, (h, w)).astype(np.float32)
    frames = []
    for i in range(int(plan.total * fps) + 2):
        t = i / fps
        what = plan.at(t)
        f = base + rs.normal(0, noise, (h, w)).astype(np.float32)
        if what == "all":
            for k in range(len(P)):
                if k not in hidden:
                    f += spot(k, 160.0)
            f += 40.0                                            # the room lit a little by them all
        elif isinstance(what, int) and what not in hidden:
            f += spot(what, 200.0)
        frames.append(np.clip(f, 0, 255).astype(np.uint8))
    return frames
