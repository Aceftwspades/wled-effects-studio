"""A soak: the app driven for minutes - effects switched, geometries
swapped, layouts flipped, frames opened and closed, a graph compiled now
and then - with its memory, Dear PyGui's item count and its frame times
sampled along the way, and the run failing if any of them keeps growing.

    python tests/soak.py                # 10 minutes
    python tests/soak.py --minutes 2    # a quick one

Like smoke_app.py it drives the app through its JSON command file
(native/app.py service_command); the `stats` hook prints one line per
sample. Growth is judged on the second half of the run against the
first, so the warm-up (fonts, textures, the first builds) does not
count: more than 60 MB or 25% of RSS, or more than 200 items, is a leak.
"""
import json
import os
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
EXE = os.environ.get("STUDIO_EXE")
ROOT = os.path.dirname(os.path.abspath(EXE)) if EXE else os.path.dirname(HERE)
CMD = os.path.join(tempfile.gettempdir(), "cubefx", "command.json")
LOG = os.path.join(tempfile.gettempdir(), "cubefx", "soak.log")

GEOMETRIES = [{"kind": "cube", "params": {"B": 16}}, {"kind": "matrix", "params": {"w": 32, "h": 16}},
              {"kind": "sphere", "params": {"w": 24, "h": 12}}, {"kind": "strip", "params": {"n": 150}},
              {"kind": "cylinder", "params": {"w": 24, "h": 10}}]
LAYOUTS = ["both", "graph", "edit", "cube", "net"]
FRAMES = ["devices", "shape", "sequence", "library", "palettes", "outputs", "send"]


def send(cmds, wait):
    json.dump(cmds, open(CMD, "w"))
    time.sleep(wait)


def main():
    minutes = float(sys.argv[sys.argv.index("--minutes") + 1]) if "--minutes" in sys.argv else 10.0
    os.makedirs(os.path.dirname(CMD), exist_ok=True)
    project = os.path.join(ROOT, "projects", "default", "project.json")
    saved = open(project, encoding="utf-8").read() if os.path.exists(project) else None
    with open(LOG, "w") as log:
        cmd = [EXE] if EXE else [sys.executable, "-u", "-m", "native.app"]
        env = dict(os.environ, STUDIO_NO_UPDATE_CHECK="1", STUDIO_NO_WELCOME="1")
        proc = subprocess.Popen(cmd, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, env=env)
    t0 = time.time()
    try:
        time.sleep(9 if not EXE else 30)
        send([{"layout": "both"}, {"py": "len(app.eng.names)"}], 1.0)
        names = None
        for l in open(LOG, encoding="utf-8", errors="replace"):
            if l.startswith("py ") and l[3:].strip().isdigit():
                names = int(l[3:].strip())
        n_fx = names or 60
        k = 0
        while time.time() - t0 < minutes * 60 and proc.poll() is None:
            step = []
            step.append({"py": f"app.on_effect(None, app.eng.names[{(k * 7) % n_fx}])"})     # a different effect every time
            if k % 5 == 4:
                step.append({"geometry": GEOMETRIES[(k // 5) % len(GEOMETRIES)]})
            if k % 4 == 3:
                step.append({"layout": LAYOUTS[(k // 4) % len(LAYOUTS)]})
            if k % 6 == 5:
                step.append({"frame": FRAMES[(k // 6) % len(FRAMES)]})
            if k % 6 == 0 and k:
                step.append({"frame_close": FRAMES[((k - 1) // 6) % len(FRAMES)]})
            if k % 15 == 14:
                step += [{"layout": "graph"}, {"graph_open": "box_fire.json"}, {"py": "app.gp.compile()"}]
            if k % 5 == 4:
                step.append({"stats": True})
            send(step, 3.0)
            k += 1
        send([{"geometry": GEOMETRIES[0]}, {"layout": "both"}, {"stats": True}], 2.0)
    finally:
        proc.kill()
        time.sleep(1)
        if saved is not None:
            open(project, "w", encoding="utf-8").write(saved)
    rows = []
    text = open(LOG, encoding="utf-8", errors="replace").read()
    for l in text.splitlines():
        if l.startswith("stats "):
            try:
                rows.append(json.loads(l[6:]))
            except ValueError:
                pass
    crashed = "Traceback" in text
    if len(rows) < 4:
        print(f"soak: FAILED - only {len(rows)} sample(s) (log {LOG})"); return 1
    half = len(rows) // 2
    first, second = rows[:half], rows[half:]
    rss0 = sum(r["rss_mb"] for r in first) / len(first); rss1 = sum(r["rss_mb"] for r in second) / len(second)
    it0 = sum(r["items"] for r in first) / len(first); it1 = sum(r["items"] for r in second) / len(second)
    print(f"soak: {len(rows)} samples over {(time.time() - t0) / 60:.1f} min, {k} steps")
    print(f"  RSS   {rows[0]['rss_mb']:.0f} MB at the start, {rss0:.0f} MB first half, {rss1:.0f} MB second half, {rows[-1]['rss_mb']:.0f} MB at the end")
    print(f"  items {rows[0]['items']} -> {rows[-1]['items']}   effect {rows[-1]['effect_ms']:.2f} ms  app {rows[-1]['app_ms']:.1f} ms  threads {rows[-1]['threads']}")
    bad = []
    if rss1 - rss0 > 60 or rss1 > rss0 * 1.25:
        bad.append(f"RSS grew from {rss0:.0f} to {rss1:.0f} MB between the halves")
    if it1 - it0 > 200:
        bad.append(f"Dear PyGui items grew from {it0:.0f} to {it1:.0f}")
    if crashed:
        bad.append("a traceback in the log")
    print("soak: " + ("ok" if not bad else "FAILED - " + "; ".join(bad)) + f" (log {LOG})")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
