"""
Headless driver for the native engine.

    python -m native.cli --list
    python -m native.cli --measure "spectral fountain" --ms 25000
    python -m native.cli --measure soap --sweep c3=50,120,210
    python -m native.cli --snapshot "black hole" --at 6000,14000,22000 --scale 6

Deterministic by construction: the clock advances in fixed steps and the audio
comes from the same generator the browser build uses, so a measurement here is
comparable with one taken there. That was not true of the browser harness on its
own - requestAnimationFrame is throttled when the tab is not frontmost, and
measurements taken that way were quietly meaningless.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from native.engine import Engine, stats            # noqa: E402
from native.synth import Synth                     # noqa: E402
from native import png                             # noqa: E402

STEP = 23           # ms per frame, matching the browser build's fixed quantum
WARM = 60           # discarded frames - the same count harness.js uses, so a
                    # native run and a browser run sample the same instants


def _apply(eng, spec):
    """--set sx=200,o1=1 -> parameter overrides."""
    if not spec:
        return
    over = {}
    for kv in spec.split(","):
        if "=" in kv:
            k, v = kv.split("=", 1)
            over[k.strip()] = int(v)
    eng.fx.update({k: v for k, v in over.items() if k in eng.fx})
    if "pal" in over:
        eng.pal = over["pal"]
    eng.push()


def run(eng, syn, ms, sample_every=None, flat=False):
    """Step the engine, returning per-sample stats over lit pixels and the lid."""
    lit = eng.lit_mask(flat=flat or bool(eng.fx.get("o3")))
    lid = eng.lid_mask()
    out = []
    frames = int(ms / STEP) + WARM
    for f in range(frames):
        syn.push(eng)
        eng.frame(STEP)
        if f < WARM:
            continue
        if sample_every and (f - WARM) % sample_every:
            continue
        rgb = eng.rgb()
        out.append({"t": eng.sim_ms, "all": stats(rgb, lit), "lid": stats(rgb, lid)})
    return out


def average(rows, key="all"):
    if not rows:
        return {}
    keys = rows[0][key].keys()
    return {k: round(sum(r[key][k] for r in rows) / len(rows), 1) for k in keys}


def swing(rows, key="all"):
    """Standard deviation of each measure ACROSS the run - the consistency of an
    effect over time, as distinct from its structure within one frame."""
    if not rows:
        return {}
    out = {}
    for k in rows[0][key]:
        v = [r[key][k] for r in rows]
        m = sum(v) / len(v)
        out[k] = round((sum((x - m) ** 2 for x in v) / len(v)) ** 0.5, 1)
    return out


def main():
    ap = argparse.ArgumentParser(prog="native.cli")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--measure", metavar="EFFECT")
    ap.add_argument("--snapshot", metavar="EFFECT")
    ap.add_argument("--gif", metavar="EFFECT",
                    help="animated preview. a still cannot show motion")
    ap.add_argument("--secs", type=float, default=15.0)
    ap.add_argument("--fps", type=int, default=15)
    ap.add_argument("--view", default="both", choices=("net", "cube", "both"))
    ap.add_argument("--size", type=int, default=160, help="cube render px")
    ap.add_argument("--spin", type=float, default=0.0,
                    help="turns of yaw over the whole clip")
    ap.add_argument("--ms", type=int, default=20000)
    ap.add_argument("--at", default="", help="snapshot times in ms, comma separated")
    ap.add_argument("--scale", type=int, default=6)
    ap.add_argument("--out", default="shot")
    ap.add_argument("--set", default="", help="sx=200,c3=90,o1=1")
    ap.add_argument("--sweep", default="", help="c3=50,120,210")
    ap.add_argument("--faceB", type=int, default=16)
    ap.add_argument("--every", type=int, default=40, help="sample every N frames")
    ap.add_argument("--live", type=float, metavar="SECONDS",
                    help="capture system audio and print band levels, to check "
                         "the loopback path before wiring it to anything")
    a = ap.parse_args()

    if a.live:
        import time
        from native.audio import LiveAudio
        live = LiveAudio()
        print(f"capturing: {live.name}  @{live.rate} Hz, {live.channels} ch")
        eng = Engine()
        t0, beats = time.time(), 0
        try:
            while time.time() - t0 < a.live:
                hit = live.push(eng)
                beats += hit
                bars = "".join(" .:-=+*#@"[min(8, int(v) * 9 // 256)] for v in eng.fft)
                print(f"\r[{bars}] level {live.level:5.1f}  beats {beats:3d}",
                      end="", flush=True)
                time.sleep(0.03)
        finally:
            live.close()
            print()
        return

    eng = Engine()
    if a.list:
        for i, n in enumerate(eng.names):
            print(f"{i:3d}  {n}")
        return

    target = a.measure or a.snapshot or a.gif
    if not target:
        ap.print_help()
        return
    eng.resize(a.faceB)
    idx = eng.find(target)

    if a.gif:
        import time
        import numpy as np
        from native import render, gif
        eng.select(idx)
        _apply(eng, a.set)
        syn = Synth()
        # Gated, so mid and treble carry transients too. An effect judged on a
        # steady tone is being judged on the half of its behaviour that does
        # not move.
        syn.gate_bass = syn.gate_mid = syn.gate_treb = True

        for _ in range(40):                       # settle before recording
            syn.push(eng); eng.frame()

        nfr = max(1, int(a.secs * a.fps))
        step_ms = 1000.0 / a.fps
        frames, t0 = [], time.time()
        for i in range(nfr):
            # Advance the SIMULATED clock by one output frame, in the engine's
            # own fixed steps, so the clip runs at true speed rather than at
            # whatever this machine renders at.
            tgt = eng.sim_ms + step_ms
            while eng.sim_ms < tgt:
                syn.push(eng); eng.frame()
            net = eng.rgb().copy()
            if not eng.fx.get("o3"):
                net[~eng.lit_mask()] = 0
            parts = []
            if a.view in ("net", "both"):
                sc = max(1, a.size // eng.rows)
                parts.append(net.repeat(sc, 0).repeat(sc, 1))
            if a.view in ("cube", "both"):
                yaw = -0.6 + (2 * np.pi * a.spin * i) / nfr
                parts.append(render.render(net, eng.B, a.size, yaw, 0.75, 4.6))
            if len(parts) == 1:
                frames.append(parts[0])
            else:
                h = max(p.shape[0] for p in parts)
                can = np.zeros((h, sum(p.shape[1] for p in parts) + 8, 3), np.uint8)
                x = 0
                for p in parts:
                    y = (h - p.shape[0]) // 2
                    can[y:y + p.shape[0], x:x + p.shape[1]] = p
                    x += p.shape[1] + 8
                frames.append(can)
        out = a.out if a.out.endswith(".gif") else a.out + ".gif"
        n = gif.write(out, frames, fps=a.fps)
        print(f"{out}  {len(frames)} frames  {frames[0].shape[1]}x{frames[0].shape[0]}"
              f"  {n/1024:.0f} KB  ({time.time()-t0:.1f}s)")
        return

    if a.snapshot:
        times = [int(x) for x in a.at.split(",") if x.strip()] or [8000]
        eng.select(idx)
        _apply(eng, a.set)
        syn = Synth()
        files, nxt = [], 0
        for f in range(int(max(times) / STEP) + 4):
            syn.push(eng)
            eng.frame(STEP)
            if nxt < len(times) and eng.sim_ms >= times[nxt]:
                p = f"{a.out}_{times[nxt]}.png"
                png.write_rgb(p, eng.rgb(), a.scale)
                files.append(p)
                nxt += 1
        print(json.dumps({"effect": eng.names[idx], "wrote": files}, indent=1))
        return

    # --measure, optionally as a sweep over one parameter
    runs = {}
    if a.sweep:
        k, vals = a.sweep.split("=", 1)
        for v in vals.split(","):
            eng.select(idx)
            _apply(eng, a.set)
            eng.fx[k.strip()] = int(v)
            eng.push()
            rows = run(eng, Synth(), a.ms, a.every)
            runs[f"{k.strip()}={v}"] = {"all": average(rows), "lid": average(rows, "lid"),
                                        "swing": swing(rows)}
    else:
        eng.select(idx)
        _apply(eng, a.set)
        rows = run(eng, Synth(), a.ms, a.every)
        runs["run"] = {"all": average(rows), "lid": average(rows, "lid"),
                       "swing": swing(rows)}

    print(json.dumps({"effect": eng.names[idx], "faceB": a.faceB,
                      "ms": a.ms, "results": runs}, indent=1))


if __name__ == "__main__":
    main()
