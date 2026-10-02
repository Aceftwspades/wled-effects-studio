"""The node tutorials' pictures, and NODES.md with the tutorials in it.

Every lesson in docs/nodes (native/tutorials.py) is compiled as an effect of
its own - "Tutorial <node>" - into one side build of the engine (the app's
build is not touched), run on the gated synth as the CLI's GIFs are, and
recorded: the LEDs as the matrix shows them, and under them the values the
lesson traces, read back from the build's probes. The GIF goes beside the
lesson (docs/nodes/<node>.gif); NODES.md is then written again.

    python tests/make_tutorials.py            # every lesson
    python tests/make_tutorials.py Slew Wave  # only these (NODES.md is still written whole)
"""
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import numpy as np                                        # noqa: E402

SECS, FPS = 4.0, 12                     # a loop long enough to see a beat or two, short enough to stay small
WARM = 5.0                              # seconds run before recording: a slew settled, a trace with history
CELL, GAP = 9, 2                       # an LED's square on the picture, and the dark between two
TRACE_H = 96
BG = (14, 15, 18)
LINE = [(240, 150, 40), (150, 154, 162)]   # one trace: orange; two: the input grey, the node's output orange


def leds(rgb, lit):
    """The logical picture as LEDs: each a CELL square with a GAP between, unlit ones dark."""
    h, w, _ = rgb.shape
    step = CELL + GAP
    img = np.zeros((h * step + GAP, w * step + GAP, 3), np.uint8)
    img[:] = BG
    for y in range(h):
        for x in range(w):
            c = rgb[y, x] if lit[y, x] else (0, 0, 0)
            img[GAP + y * step:GAP + y * step + CELL, GAP + x * step:GAP + x * step + CELL] = c
    return img


def trace_panel(width, series, labels, lo, hi, now):
    """The traced values as lines, the last SECS seconds of each ending at `now` (a sample index)."""
    from PIL import Image, ImageDraw
    im = Image.new("RGB", (width, TRACE_H), BG)
    d = ImageDraw.Draw(im)
    top, bot, left, right = 18, TRACE_H - 8, 6, width - 6
    for v in (0.0, 1.0):
        if lo <= v <= hi:
            y = bot - (v - lo) / (hi - lo) * (bot - top)
            d.line([(left, y), (right, y)], fill=(40, 42, 48))
            d.text((right - 14, y - 11), f"{v:g}", fill=(90, 92, 100))
    n = int(SECS * FPS)
    order = list(range(len(series)))
    if len(series) == 2:
        order = [1, 0]                                # the input under, the node's output on top
    for k in order:
        vals = series[k][max(0, now - n + 1):now + 1]
        col = LINE[0] if len(series) == 1 or k == len(series) - 1 else LINE[1]
        pts = [(right - (len(vals) - 1 - i) * (right - left) / (n - 1), bot - (min(hi, max(lo, v)) - lo) / (hi - lo) * (bot - top))
               for i, v in enumerate(vals)]
        if len(pts) > 1:
            d.line(pts, fill=col, width=2)
    x = left
    for k, lab in enumerate(labels):
        col = LINE[0] if len(series) == 1 or k == len(series) - 1 else LINE[1]
        d.text((x, 3), lab, fill=col)
        x += 8 + d.textlength(lab)
    return np.asarray(im)


def record(eng, lesson, g, title):
    """The lesson's frames: (list of images)."""
    from native.synth import Synth
    from native.nodeface import label
    eng.select(eng.names.index(title), params=lesson.get("fx") or None)
    eng.clear()
    syn = Synth()
    syn.gate_bass = syn.gate_mid = syn.gate_treb = True
    probes = {v: k for k, v in (g.probes or {}).items()}
    keys = [probes.get((nid, name)) for nid, name in lesson["trace"]]
    labels = []
    for nid, name in lesson["trace"]:
        t = g.nodes[nid]["type"]
        labels.append(f"{t} {label(t, name)}")
    step_ms = 1000.0 / FPS
    total = int((WARM + SECS) * FPS)
    series = [[] for _ in keys]
    pics = []
    for i in range(total):
        tgt = eng.sim_ms + step_ms
        while eng.sim_ms < tgt:
            syn.push(eng); eng.frame()
        for s, k in zip(series, keys):
            s.append(eng.probe(k) if k is not None else 0.0)
        if i >= total - int(SECS * FPS):
            pics.append((i, leds(eng.rgb().copy(), eng.lit_mask())))
    frames = []
    if series:
        allv = [v for s in series for v in s]
        lo, hi = min(0.0, min(allv)), max(1.0, max(allv))
    for i, pic in pics:
        if series:
            panel = trace_panel(pic.shape[1], series, labels, lo, hi, i)
            pic = np.concatenate([pic, panel], 0)
        frames.append(pic)
    return frames


def main(only=()):
    from native import tutorials, nodedocs, scratch, gif
    from native.nodedefs import library
    from native.engine import Engine
    from native.geometry import Geometry
    import build as B
    from native.toolchain import build_engine
    lib = library()
    lessons = tutorials.all_lessons()
    if only:
        lessons = {k: v for k, v in lessons.items() if k in only}
    bad = {n: p for n, les in lessons.items() for p in [tutorials.problems(les, lib)] if p}
    if bad:
        for n, p in bad.items():
            print("\n".join(p))
        return 1
    graphs, srcs = {}, []
    for node, les in lessons.items():
        g = tutorials.graph_of(les, lib)
        title = "Tutorial " + node
        src = scratch.path("tutorial_" + tutorials.ident(node) + ".cpp")
        with open(src, "w", encoding="utf-8", newline="\n") as f:
            f.write(g.compile(title=title))
        graphs[node] = (g, title)
        srcs.append(src)
    t0 = time.time()
    if srcs:
        rep = build_engine(B.engine_sources(srcs, log=lambda *a: None), B.include_dirs(), log=print, point_latest=False)
        if not rep.ok:
            print("the tutorials' build failed:")
            for e in rep.error_lines()[:10]:
                print("  ", e)
            return 1
        print(f"built {len(srcs)} tutorial(s) in {time.time() - t0:.0f} s")
        eng = Engine(rep.library)
        for node, les in lessons.items():
            g, title = graphs[node]
            eng.set_geometry(Geometry.from_json(les["shape"]))
            frames = record(eng, les, g, title)
            out = tutorials.picture(node)
            n = gif.write(out, frames, fps=FPS)
            print(f"{node}: {os.path.relpath(out, ROOT)}  {frames[0].shape[1]}x{frames[0].shape[0]}  {n / 1024:.0f} KB")
    path = os.path.join(ROOT, "NODES.md")
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(nodedocs.markdown())
    print("wrote", path)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
