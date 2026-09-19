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
import urllib.request


def capture(eng, colours, bri=128, name="", dur=10.0, trans=0.7):
    segs = eng.segments()
    return {"name": name or (segs[0]["effect"] if segs else "step"), "dur": float(dur), "trans": float(trans),
            "bri": int(bri), "colors": [int(c) for c in colours], "segments": segs, "cols": eng.cols, "rows": eng.rows}


def apply(eng, step):
    """The step's state into the sim; the caller refreshes the panel."""
    segs = step.get("segments") or []
    if segs:
        eng.load_segments(segs)
    cols = step.get("colors")
    if cols and len(cols) == 3:
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
    the device has no such effect."""
    fx = _find(names, sg.get("effect", ""))
    if fx is None:
        return None
    b = sg.get("bounds") or [0, 0, 1, 1]
    p = sg.get("params") or {}
    d = {"id": k, "start": int(b[0]), "stop": int(b[2]), "fx": fx,
         "sx": int(p.get("sx", 128)), "ix": int(p.get("ix", 128)), "c1": int(p.get("c1", 128)), "c2": int(p.get("c2", 128)),
         "c3": int(p.get("c3", 16)), "o1": bool(p.get("o1")), "o2": bool(p.get("o2")), "o3": bool(p.get("o3")),
         "bri": int(sg.get("opacity", 255)), "bm": int(sg.get("blend", 0)), "on": True,
         "col": [[(c >> 16) & 255, (c >> 8) & 255, c & 255] for c in colours]}
    if is2d:
        d["startY"], d["stopY"] = int(b[1]), int(b[3])
    pal = sg.get("pal")
    if isinstance(pal, int) and 0 <= pal < len(pals):
        d["pal"] = pal                       # a palette id means the same on both sides (the sim carries WLED's set)
    return d


def to_wled(steps, names, pals, base=10, pid=9, name="Show", repeat=0):
    """(presets, playlist): the presets as {id: state} and the playlist
    preset, ready for psave or a presets.json. Steps with no effect the
    device has are left out (returned in presets[None] as a list of names)."""
    presets, ids, missing = {}, [], []
    for i, st in enumerate(steps):
        is2d = int(st.get("rows", 1)) > 1
        segs = [segment_json(k, sg, names, pals, is2d, st.get("colors") or [0xFFA000, 0, 0]) for k, sg in enumerate(st.get("segments") or [])]
        if not segs or any(s is None for s in segs):
            missing.append(st.get("name", f"step {i + 1}"))
            continue
        pid_i = base + i
        presets[pid_i] = {"n": st.get("name", f"step {i + 1}"), "on": True, "bri": int(st.get("bri", 128)),
                          "transition": int(round(float(st.get("trans", 0.7)) * 10)), "mainseg": 0, "seg": segs}
        ids.append(pid_i)
    kept = [st for i, st in enumerate(steps) if base + i in presets]
    playlist = {"n": name, "playlist": {"ps": ids, "dur": [max(1, int(round(float(st["dur"]) * 10))) for st in kept],
                                        "transition": [int(round(float(st.get("trans", 0.7)) * 10)) for st in kept],
                                        "repeat": int(repeat), "end": 0, "r": False}}
    if missing:
        presets[None] = missing
    return presets, playlist


def send(host, presets, playlist, pid):
    """The presets and the playlist onto the device, one psave each. (ok, message)."""
    host = host.strip().rstrip("/")
    if not host.startswith("http"):
        host = "http://" + host
    n = 0
    for k, state in presets.items():
        if k is None:
            continue
        body = dict(state); body.update({"psave": int(k), "ib": True, "sb": True})
        req = urllib.request.Request(host + "/json/state", data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=6) as r:
                r.read()
            n += 1
        except Exception as e:
            return False, f"preset {k} ({state.get('n')}) refused: {e}"
    body = {"psave": int(pid), "n": playlist["n"], "playlist": playlist["playlist"]}
    req = urllib.request.Request(host + "/json/state", data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=6) as r:
            r.read()
    except Exception as e:
        return False, f"{n} presets saved, the playlist refused: {e}"
    skipped = presets.get(None) or []
    return True, f"{n} presets ({min(presets) if n else '-'}..{max(k for k in presets if k is not None) if n else '-'}) and playlist {pid} '{playlist['n']}' saved on the device" + (f"; skipped, no such effect there: {', '.join(skipped)}" if skipped else "")


def presets_file(presets, playlist, pid):
    """A presets.json the device's UI could import (or the file uploaded over /upload)."""
    out = {"0": {}}
    for k, state in presets.items():
        if k is not None:
            out[str(k)] = state
    out[str(pid)] = playlist
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
