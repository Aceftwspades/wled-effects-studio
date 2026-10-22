"""A sequence: steps of the sim's state, each held for a while, played in
the sim and sent to the device as WLED presets and a playlist.

A step is what the sim shows at the moment it is captured - every
segment's effect, sliders, palette, bounds, opacity and blend, the
colours, the brightness - with a name, a duration and a transition time.
The sim plays the steps in turn (a cut at each change; WLED's transition
runs on the device). Sent, each step becomes a preset (`psave`, from a
base id) and the sequence a playlist preset that runs them with their
durations and transitions - what the device's own UI would have needed a
dozen screens for.

    step = capture(eng, colours, bri, name, dur, trans)
    apply(eng, step)                                # into the sim
    presets, playlist = to_wled(steps, names, pals, base=10, pid=9, name="Show", repeat=0)
"""
import json
import math
import time
import urllib.request


def capture(eng, colours, bri=255, name="", dur=10.0, trans=0.7, rgb=None):
    """A step: the engine's segments as they are now; `rgb`, the frame it shows (rows, cols, 3), gives it its look."""
    segs = eng.segments()
    st = {"name": name or (segs[0]["effect"] if segs else "step"), "dur": float(dur), "trans": float(trans),
          "bri": int(bri), "colors": [int(c) for c in colours], "segments": segs, "cols": eng.cols, "rows": eng.rows}
    if rgb is not None:
        lk = look(rgb)
        if lk:
            st["look"] = lk
    return st


# --- a step's look: what it shows, as a strip of colours -------------------------------------------
LOOK_N = 24                       # colours across a step's look


def look(rgb, n=LOOK_N):
    """The colours a frame shows - or a stack of frames over time, (T, rows, cols, 3) - left to right, as hex
    ("rrggbb" n times): each of n bands across by the mean of its lit pixels' brighter part, so an effect's colours
    rather than the black between them (a meteor's trail, a fire's flames). "" for nothing to read."""
    import numpy as np
    a = np.asarray(rgb, dtype=np.float32)
    if a.ndim == 4:
        a = a.reshape(-1, a.shape[2], 3)                   # the frames one above the other: the same bands over time
    if a.ndim != 3 or a.shape[1] < 1:
        return ""
    cols = a.shape[1]
    w = np.array([0.299, 0.587, 0.114], np.float32)
    out = []
    for k in range(n):
        x0, x1 = k * cols // n, max(k * cols // n + 1, (k + 1) * cols // n)
        px = a[:, x0:x1].reshape(-1, 3)
        lum = px @ w
        lit = px[lum > 12]                                 # the lit ones (a dark band stays dark)
        if len(lit) == 0:
            out.append("000000"); continue
        llum = lit @ w
        keep = lit[llum >= np.percentile(llum, 50)]
        c = keep.mean(0)
        out.append("%02x%02x%02x" % tuple(int(max(0, min(255, round(v)))) for v in c))
    return "".join(out)


def look_colours(step):
    """A step's look as [(r, g, b)], or None when it has none yet."""
    lk = str(step.get("look") or "")
    if len(lk) < 6 or len(lk) % 6:
        return None
    try:
        return [tuple(int(lk[i + j:i + j + 2], 16) for j in (0, 2, 4)) for i in range(0, len(lk), 6)]
    except ValueError:
        return None


def fingerprint(S):
    """What a send puts on the device, as a short hash: the steps (their looks aside) and the playlist's settings -
    a send remembers it, and a change since shows as one."""
    import hashlib
    steps = [{k: v for k, v in st.items() if k != "look"} for st in S.get("steps") or []]
    body = json.dumps([steps, S.get("base", 10), S.get("pid", 9), S.get("name", "Show"), S.get("repeat", 0)], sort_keys=True)
    return hashlib.sha1(body.encode("utf-8")).hexdigest()[:12]


def apply(eng, step):
    """The step's state into the sim; the caller refreshes the panel."""
    segs = step.get("segments") or []
    if segs:
        # a step saved on another shape: its bounds clamped to this one, so
        # a segment never lands off the matrix (WLED would drop it)
        fixed = []
        for sg in segs:
            b = sg.get("bounds")
            if b and (b[2] > eng.cols or b[3] > eng.rows or b[0] >= eng.cols or b[1] >= eng.rows):
                sg = dict(sg, bounds=[min(int(b[0]), eng.cols - 1), min(int(b[1]), eng.rows - 1),
                                      min(int(b[2]), eng.cols), min(int(b[3]), eng.rows)])
            fixed.append(sg)
        eng.load_segments(fixed)
    # the step's colours - the panel's when it was captured - unless its segments carry their own (since 1.4.0)
    cols = step.get("colors")
    own = any(isinstance(sg.get("colors"), (list, tuple)) and len(sg["colors"]) == 3 for sg in segs)
    if cols and len(cols) == 3 and not own:
        eng.colors(*[int(c) for c in cols])


def _find(names, want):
    """An index in the device's list by name (a family prefix tolerated)."""
    w = str(want).split("@")[0].strip().lower()
    clean = [str(n).split("@")[0].strip().lower() for n in names]
    if w in clean:
        return clean.index(w)
    return next((i for i, n in enumerate(clean) if n.endswith(" " + w) or w.endswith(" " + n)), None)


def segment_json(k, sg, names, pals, is2d, colours):
    """One segment of a step as WLED's /json/state wants it; None when
    the device has no such effect. Its colours are its own when it carries
    them (since 1.4.0), else `colours`."""
    fx = _find(names, sg.get("effect", ""))
    if fx is None:
        return None
    b = sg.get("bounds") or [0, 0, 1, 1]
    p = sg.get("params") or {}
    own = sg.get("colors")
    cols = own if isinstance(own, (list, tuple)) and len(own) == 3 else colours
    d = {"id": k, "start": int(b[0]), "stop": int(b[2]), "fx": fx,
         "sx": int(p.get("sx", 128)), "ix": int(p.get("ix", 128)), "c1": int(p.get("c1", 128)), "c2": int(p.get("c2", 128)),
         "c3": int(p.get("c3", 16)), "o1": bool(p.get("o1")), "o2": bool(p.get("o2")), "o3": bool(p.get("o3")),
         "bri": int(sg.get("opacity", 255)), "bm": int(sg.get("blend", 0)), "on": True,
         "col": [[(int(c) >> 16) & 255, (int(c) >> 8) & 255, int(c) & 255] for c in cols]}
    if is2d:
        d["startY"], d["stopY"] = int(b[1]), int(b[3])
    for key, v in (sg.get("options") or {}).items():          # rev, mi, rY, mY, tp, grp, spc, of - WLED's own names
        d[key] = bool(v) if key in ("rev", "mi", "rY", "mY", "tp") else int(v)
    pal = sg.get("pal")
    if isinstance(pal, int) and 0 <= pal < len(pals):
        d["pal"] = pal                       # a palette id means the same on both sides (the sim carries WLED's set)
    return d


RAMP_KEYS = ("sx", "ix", "c1", "c2", "c3")
BRI = "bri"                      # a ramp of the step's brightness (the whole show's, as WLED's presets set it)
VJF = "vjf"                      # a ramp of a VJ step's crossfader, 0..255 (vj.py; the sim's only - not the device's)
RAMP_SHAPES = ("linear", "ease in", "ease out", "ease in-out", "up and back", "step", "curve")
CURVE_MAX = 16                   # a curve's points at most (a lane drawn on the timeline: a handful is plenty)


def ramp_key(seg, slider):
    """A ramp's key in a step's ramps: the slider's for the first segment
    (as every ramp was before they had a segment), "k:slider" for segment k."""
    return slider if int(seg) == 0 else f"{int(seg)}:{slider}"


def ramp_target(key):
    """(segment, slider) a ramp's key names; (0, key) for a plain one; (-1, "bri") for the brightness."""
    if str(key) == BRI:
        return -1, BRI
    if ":" in str(key):
        seg, slider = str(key).split(":", 1)
        try:
            return int(seg), slider
        except ValueError:
            return 0, slider
    return 0, str(key)


def ramp_of(step, key):
    """(end, shape) of a slider's ramp on the step, or None: a ramp is an
    end value (a graph saved before shapes) or {"end", "shape"} - and a
    curve's {"shape": "curve", "points": [[t, value], ...]}, whose end is
    its last point's value."""
    r = (step.get("ramps") or {}).get(key)
    if r is None:
        return None
    if isinstance(r, dict):
        shape = str(r.get("shape", "linear"))
        if shape == "curve":
            pts = curve_points(step, key)
            return (pts[-1][1] if pts else int(r.get("end", 128))), shape
        return int(r.get("end", 128)), shape
    return int(r), "linear"


# AI: below section was generated by an AI
# A curve: an automation lane (the feature review's fourth, STUDIO.md: xLights' value curves) - a ramp whose value
# runs through points drawn on the timeline instead of one of the fixed shapes. The step's own value is where it
# starts (t = 0); the points follow, straight between them, the last held to the end.
def curve_points(step, key):
    """A curve ramp's points, [[t, value]] in order: t in (0, 1], value 0..255, at most CURVE_MAX; [] for none."""
    r = (step.get("ramps") or {}).get(key)
    if not isinstance(r, dict):
        return []
    out = []
    for p in (r.get("points") or [])[:CURVE_MAX]:
        try:
            t, v = float(p[0]), float(p[1])
        except (TypeError, ValueError, IndexError):
            continue
        if t == t and v == v:
            out.append([max(0.0, min(1.0, t)), int(round(max(0.0, min(255.0, v))))])
    out.sort(key=lambda q: q[0])
    return [q for q in out if q[0] > 0.0]


def curve_value(start, pts, t):
    """The value at t (0..1) along `start` (at 0) and the points, straight between them."""
    t = max(0.0, min(1.0, float(t)))
    prev_t, prev_v = 0.0, float(start)
    for pt, pv in pts:
        if t <= pt:
            f = (t - prev_t) / (pt - prev_t) if pt > prev_t else 1.0
            return prev_v + (pv - prev_v) * f
        prev_t, prev_v = pt, float(pv)
    return prev_v


def to_curve(step, key, n=4):
    """The ramp on `key` as a curve that looks as it did: its value sampled at n points across the step."""
    return [[round(j / n, 4), ramp_value(step, key, j / n)] for j in range(1, n + 1)]


def thin(pts, n):
    """At most n of the points [(t, v)] (in t order, the first and last kept), the ones that matter most: from the
    two ends, each time the point farthest (in value) from the line through the ones kept is added - the
    Ramer-Douglas-Peucker idea, by count - until n are kept or every one left is within a step of the line."""
    if len(pts) <= n:
        return list(pts)
    keep = [0, len(pts) - 1]
    while len(keep) < n:
        keep.sort()
        best, at = 1.0, None
        for a, b in zip(keep, keep[1:]):
            (ta, va), (tb, vb) = pts[a], pts[b]
            for k in range(a + 1, b):
                t, v = pts[k]
                f = (t - ta) / (tb - ta) if tb > ta else 0.0
                err = abs(v - (va + (vb - va) * f))
                if err > best:
                    best, at = err, k
        if at is None:
            break
        keep.append(at)
    return [pts[k] for k in sorted(keep)]


def record_into(step, key, samples):
    """A slider's moves recorded while the step played - samples [(t 0..1, value 0..255)] in time order - into the
    step: its ramp on `key` becomes a curve that runs as it did outside the recorded stretch and as recorded within
    it, thinned to CURVE_MAX points. (start value, points): the start is the step's own value, which the recording
    sets when it began at the step's start."""
    samples = [(max(0.0, min(1.0, float(t))), max(0, min(255, int(round(v))))) for t, v in samples]
    if not samples:
        return ramp_value(step, key, 0.0), curve_points(step, key)
    ta, tb = samples[0][0], samples[-1][0]
    eps = 1e-3
    dense = [(j / 64.0, float(ramp_value(step, key, j / 64.0))) for j in range(65)]
    before = [(t, v) for t, v in dense if t < ta - eps]
    after = [(t, v) for t, v in dense if t > tb + eps]
    if before:
        before.append((ta - eps, float(ramp_value(step, key, ta - eps))))       # the curve as it was, up to the take
    if after:
        after.insert(0, (tb + eps, float(ramp_value(step, key, tb + eps))))     # and from where it ended
    pts = before + [(t, float(v)) for t, v in samples] + after
    if pts[0][0] > 0.0:
        pts.insert(0, (0.0, pts[0][1]))
    if pts[-1][0] < 1.0:
        pts.append((1.0, pts[-1][1]))
    kept = thin(pts, CURVE_MAX + 1)                       # the start at t = 0, then the curve's points
    start = int(round(kept[0][1]))
    return start, [[round(t, 4), int(round(v))] for t, v in kept[1:] if t > 0.0]
# AI: end


def shape_t(shape, t):
    """How far along a ramp of `shape` the value is at t (0..1)."""
    t = max(0.0, min(1.0, float(t)))
    if shape == "ease in":
        return t * t
    if shape == "ease out":
        return 1.0 - (1.0 - t) ** 2
    if shape == "ease in-out":
        return t * t * (3.0 - 2.0 * t)
    if shape == "up and back":
        return 0.5 - 0.5 * math.cos(t * 2 * math.pi)        # there at the middle, back at the end
    if shape == "step":
        return 0.0 if t < 0.5 else 1.0
    return t


def ramp_value(step, key, t):
    """The slider a ramp's key names (on its segment) at t (0..1) into the
    step: from the step's value to the ramp's end, along the ramp's shape."""
    segs = step.get("segments") or []
    seg, slider = ramp_target(key)
    if slider == BRI:
        start = int(step.get("bri", 255))
    elif slider == VJF:
        start = int(round(float((step.get("vj") or {}).get("fader", 0.0)) * 255))
    else:
        start = int((segs[seg].get("params") or {}).get(slider, 128)) if 0 <= seg < len(segs) else 128
    r = ramp_of(step, key)
    if r is None:
        return start
    end, shape = r
    if shape == "curve":
        return int(round(curve_value(start, curve_points(step, key), t)))
    return int(round(start + (end - start) * shape_t(shape, t)))


def sub_steps(step):
    """A step with ramps as the steps the device can play: the slider held
    at each of n values in turn, a step apiece (WLED presets cannot move a
    slider). n from the duration - a second a sub-step, 2..12 - so a
    playlist stays under its hundred entries."""
    segs = step.get("segments") or []
    ramps = {k: v for k, v in (step.get("ramps") or {}).items()
             if k == BRI or (ramp_target(k)[1] in RAMP_KEYS and ramp_target(k)[0] < len(segs))}
    if not ramps or not segs:
        return [step]
    dur = float(step.get("dur", 10))
    n = max(2, min(12, int(dur)))
    shapes = {ramp_of(step, k)[1] for k in ramps}
    if "up and back" in shapes:
        n = max(n, 7)
        if n % 2 == 0:                                       # an odd count lands a sample on the top of the curve:
            n = n + 1 if n < 12 else n - 1                   # 8, 10 and 12 stayed even and peaked short of it
    elif "ease in-out" in shapes:
        n = max(n, 6)                                        # a curve needs the samples to read as one
    ts = [j / (n - 1) for j in range(n)]
    lens = [dur / n] * n
    if "curve" in shapes:
        # a drawn curve: a sample on each of its points (the even ones only between them), as far as twelve go, and
        # each held from half way to the one before to half way to the next - evenly spaced, the samples missed
        # the points and a peak drawn at 255 played as 227
        pins = sorted({round(p[0], 4) for k in ramps if ramp_of(step, k)[1] == "curve" for p in curve_points(step, k)})
        pins = sorted(set([0.0] + pins))[:12]
        fill = [t for t in ts if all(abs(t - p) > 0.5 / max(1, n - 1) for p in pins)]
        ts = sorted(set(pins + fill[:max(0, 12 - len(pins))]))
        n = len(ts)
        edges = [0.0] + [(ts[j] + ts[j + 1]) / 2 for j in range(n - 1)] + [1.0]
        lens = [dur * (edges[j + 1] - edges[j]) for j in range(n)]
    out = []
    for j in range(n):
        t = ts[j]
        q = json.loads(json.dumps(step))
        q["dur"] = round(lens[j], 3)
        q["name"] = f"{step.get('name', 'step')} {j + 1}/{n}"
        if j > 0:
            q["trans"] = 0.0
        for k in ramps:
            seg, slider = ramp_target(k)
            if slider == BRI:
                q["bri"] = ramp_value(step, k, t)
            else:
                q["segments"][seg].setdefault("params", {})[slider] = ramp_value(step, k, t)
        q.pop("ramps", None)
        out.append(q)
    return out


# what a step without its own value has - what a new step is given (sequence_ui.add_step): the device and the
# sim read the same, where an older or hand-edited project left one out (128 / 0.7 s on the device, 255 / no
# blend in the sim, and a missing length raised in the export)
BRI_DEFAULT, DUR_DEFAULT, TRANS_DEFAULT = 255, 10.0, 0.7

LAST_PRESET = 250          # WLED keeps presets 1..250 (presets.cpp: 251-254 are refused, 255 is a temporary one)
OFF_PRESET = 250           # the schedule's "Off" preset: never a step's
MAX_ENTRIES = 100          # a playlist's entries the device plays (playlist.cpp cuts the rest)


def preset_ids(n, base, pid):
    """n preset ids from `base` up, past the playlist's own id and the Off preset; ValueError when they
    would run past the device's last one (steps would have overwritten the playlist, or been refused)."""
    ids, k = [], max(1, int(base))
    while len(ids) < n:
        if k > LAST_PRESET - 1:
            raise ValueError(f"{n} presets from id {base} run past {LAST_PRESET - 1} (the playlist is {pid}, "
                             f"the Off preset {OFF_PRESET}): start lower, or fewer steps or ramps")
        if k not in (int(pid), OFF_PRESET):
            ids.append(k)
        k += 1
    return ids


def to_wled(steps, names, pals, base=10, pid=9, name="Show", repeat=0):
    """(presets, playlist): the presets as {id: state} and the playlist
    preset, ready for psave or a presets.json. Steps with no effect the
    device has are left out (returned in presets[None] as a list of names);
    a step with a ramp becomes its sub-steps. ValueError when the device
    could not hold it: ids past its last, or more entries than it plays."""
    steps = [q for st in steps for q in sub_steps(st)]
    if len(steps) > MAX_ENTRIES:
        raise ValueError(f"{len(steps)} entries (ramps play as a step a second): a WLED playlist plays "
                         f"{MAX_ENTRIES} - fewer or shorter ramped steps")
    slot = preset_ids(len(steps), base, pid)
    presets, ids, missing = {}, [], []
    for i, st in enumerate(steps):
        is2d = int(st.get("rows", 1)) > 1
        segs = [segment_json(k, sg, names, pals, is2d, st.get("colors") or [0xFFA000, 0, 0]) for k, sg in enumerate(st.get("segments") or [])]
        if not segs or any(s is None for s in segs):
            missing.append(st.get("name", f"step {i + 1}"))
            continue
        pid_i = slot[i]
        presets[pid_i] = {"n": st.get("name", f"step {i + 1}"), "on": True, "bri": int(st.get("bri", BRI_DEFAULT)),
                          "transition": int(round(float(st.get("trans", TRANS_DEFAULT)) * 10)), "mainseg": 0, "seg": segs}
        ids.append(pid_i)
    kept = [st for i, st in enumerate(steps) if slot[i] in presets]
    playlist = {"n": name, "playlist": {"ps": ids, "dur": [max(1, int(round(float(st.get("dur", DUR_DEFAULT)) * 10))) for st in kept],
                                        "transition": [int(round(float(st.get("trans", TRANS_DEFAULT)) * 10)) for st in kept],
                                        "repeat": int(repeat), "end": 0, "r": False}}
    if missing:
        presets[None] = missing
    return presets, playlist


def _host(host):
    host = host.strip().rstrip("/")
    return host if host.startswith("http") else "http://" + host


def _pmt(host, timeout):
    """When the device last wrote its presets file, by its own clock (whole seconds)."""
    with urllib.request.urlopen(_host(host) + "/json/info", timeout=timeout) as r:
        return int((json.loads(r.read()).get("fs") or {}).get("pmt", 0))


def psave(host, k, body, timeout=6.0, gap=1.1):
    """One preset saved on the device, and WAITED for. A psave answers
    "success" at once but the write happens in the device's main loop, and
    a second psave arriving before it replaces the one pending - fired
    back to back, only the first of a run lands. So: send, then watch the
    presets file's modified time (info.fs.pmt) move. Not by reading
    presets.json: a GET of the file while the device rewrites it loses the
    write. pmt is whole seconds, so saves are kept `gap` apart to make each
    one's tick visible. Raises on a refusal or a timeout."""
    host = _host(host)
    before = _pmt(host, timeout)
    body = dict(body); body["psave"] = int(k)
    req = urllib.request.Request(host + "/json/state", data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    sent = time.time()
    with urllib.request.urlopen(req, timeout=timeout) as r:
        r.read()
    while time.time() - sent < timeout:
        time.sleep(0.3)
        try:
            if _pmt(host, timeout) != before:
                time.sleep(max(0.0, gap - (time.time() - sent)))     # into the next second before the next save
                return
        except Exception:
            pass
    # pmt is whole seconds: a write in the same second as one just before it
    # leaves it as it was. By now the device has long written or dropped it,
    # so one read of the file is safe - it is the polling during the write
    # that loses it.
    try:
        with urllib.request.urlopen(host + "/presets.json", timeout=timeout) as r:
            if str(int(k)) in json.loads(r.read()):
                return
    except Exception:
        pass
    raise TimeoutError(f"preset {k} was accepted but never written")


def send(host, presets, playlist, pid):
    """The presets and the playlist onto the device, one psave each. (ok, message)."""
    n = 0
    for k, state in presets.items():
        if k is None:
            continue
        try:
            psave(host, k, dict(state, ib=True, sb=True))
            n += 1
        except Exception as e:
            return False, f"preset {k} ({state.get('n')}) refused: {e}"
    try:
        # "o": the object itself is the preset (WLED's "API command" form) -
        # without it the device stores its current state under the id and
        # the playlist is lost; "on" so the playlist switches the lights on
        psave(host, pid, {"n": playlist["n"], "playlist": playlist["playlist"], "on": True, "o": True})
    except Exception as e:
        return False, f"{n} presets saved, the playlist refused: {e}"
    skipped = presets.get(None) or []
    ids = [k for k in presets if k is not None]
    span = f"{min(ids)}..{max(ids)}" if ids else "-"
    return True, f"{n} presets ({span}) and playlist {pid} '{playlist['n']}' saved on the device" + (f"; skipped, no such effect there: {', '.join(skipped)}" if skipped else "")


def presets_file(presets, playlist, pid):
    """A presets.json the device's UI could import (or the file uploaded over /upload)."""
    out = {"0": {}}
    for k, state in presets.items():
        if k is not None:
            out[str(k)] = state
    out[str(pid)] = dict(playlist, on=True)              # as send() saves it: the playlist switches the lights on
    return json.dumps(out, indent=1)


def start(host, pid):
    """Run the playlist preset now."""
    host = host.strip().rstrip("/")
    if not host.startswith("http"):
        host = "http://" + host
    req = urllib.request.Request(host + "/json/state", data=json.dumps({"ps": int(pid)}).encode(), headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=6) as r:
            r.read()
        return True, f"playlist {pid} running on the device"
    except Exception as e:
        return False, f"could not start it: {e}"
