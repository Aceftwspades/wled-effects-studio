"""The gallery's files from graphs of this repository: for each, its bundle
(the graph pane's Export graph bundle's format), a preview GIF (the cube
turning, on the synth's beat) and its entry in index.json - into a folder
that is the gallery repository's checkout (version.GALLERY_REPO).

    python tests/make_gallery.py OUT_DIR [graph.json ...]   # the examples below when none are named

An entry already in OUT_DIR/index.json keeps its author, description and
tags; its bundle, preview and sha256 are made again. A graph that needs
firmware not every WLED tree has (the IMU driver), or a file of its own
(an Image node's picture), is left out: a gallery bundle carries neither.
"""
import hashlib
import json
import math
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)


EXAMPLES = ("candy_knot", "kaleidoscope", "liquid_tunnel", "maelstrom", "mandelbrot", "moire", "ring_rain",
            "spirals", "truchet_cube", "watershed", "fireworks", "snowstorm", "video_switchboard")
DESCRIPTIONS = {
    "candy_knot": "A striped knot wound round the cube, turning on the beat.",
    "kaleidoscope": "Mirrored wedges of colour folding into each other.",
    "liquid_tunnel": "A reaction-diffusion tunnel that flows towards you.",
    "maelstrom": "A whirlpool of colour pulled into the cube's middle.",
    "mandelbrot": "A slow dive into the Mandelbrot set.",
    "moire": "Two rings of lines sliding over each other into moire patterns.",
    "ring_rain": "Rings that fall and spread across the faces on each beat.",
    "spirals": "Spiral arms turning across every face.",
    "truchet_cube": "Truchet tiles whose curves flip and flow.",
    "watershed": "Water finding its way down the cube's sides.",
    "fireworks": "Bursts launched on the beat, falling as sparks.",
    "snowstorm": "Snow blown round the cube, thicker with the music.",
    "video_switchboard": "A VJ desk for live video: two decks of ten looks (motion trails, a follow spot, "
                         "halftone, thermal...) and a crossfader, each look a sub-graph - auto mix and shuffle run "
                         "a show by themselves.",
}
TAGS = {"video_switchboard": ["video", "2-D", "sub-graphs", "audio"]}
SECONDS, FPS, SIZE = 4.0, 15, 200


def _resolver(lib):
    folder = os.path.join(ROOT, "examples", "subgraphs")

    def resolve(ident):
        from native import graph as G
        p = os.path.join(folder, ident + ".json")
        return G.load(p, lib=lib, resolver=resolve) if os.path.exists(p) else None
    return resolve


def bundle_of(path, lib):
    """The bundle for a graph file of the examples - with every sub-graph it reaches (examples/subgraphs), as the
    graph pane's Export graph bundle makes one - and its needs."""
    from native import graph as G, flash
    resolve = _resolver(lib)
    g = G.load(path, lib=lib, resolver=resolve)
    subs = {}

    def collect(gr):
        for n in gr.nodes.values():
            if n["type"].startswith(G.SUB):
                ident = n["type"][len(G.SUB):]
                if ident not in subs:
                    sub = resolve(ident)
                    if sub is not None:
                        subs[ident] = sub.to_json()
                        collect(sub)
    collect(g)
    req = flash.requirements_of_graph(g, lib, resolve)
    return {"studio_graph": 1, "graph": g.to_json(), "subgraphs": subs, "nodes": {}, "requires": sorted(req)}, g


def main(argv):
    if not argv:
        print(__doc__); return 2
    out = os.path.abspath(argv[0])
    files = argv[1:] or [os.path.join(ROOT, "examples", "graphs", n + ".json") for n in EXAMPLES]
    import build as B
    from native import gallery, gif, render, flash, scratch
    from native.nodedefs import library
    from native.toolchain import build_engine
    from native.engine import Engine
    from native.synth import Synth
    lib = library()
    os.makedirs(os.path.join(out, "effects"), exist_ok=True)
    os.makedirs(os.path.join(out, "previews"), exist_ok=True)
    idx_path = os.path.join(out, "index.json")
    old = {}
    if os.path.exists(idx_path):
        old = {e["id"]: e for e in json.load(open(idx_path, encoding="utf-8")).get("entries", [])}
    items, srcs = [], []
    for path in files:
        bundle, g = bundle_of(path, lib)
        nonstd = [k for k in bundle["requires"] if not flash.DEPENDENCIES.get(k, {}).get("standard", True)]
        if nonstd or any(n["type"] == "Image" for n in g.nodes.values()):
            print(f"left out {os.path.basename(path)}: needs {', '.join(nonstd) or 'a file of its own'}")
            continue
        stem = os.path.splitext(os.path.basename(path))[0]
        eid = gallery.make_id(g.name or stem)
        title = "Gallery " + (g.name or stem)
        src = scratch.path(f"gallery_{eid}.cpp")
        with open(src, "w", encoding="utf-8", newline="\n") as f:
            f.write(g.compile(title=title))
        srcs.append(src)
        items.append((eid, stem, g, bundle, title))
    t0 = time.time()
    rep = build_engine(B.engine_sources(srcs, log=lambda *a: None), B.include_dirs(), log=lambda *a: None,
                       point_latest=False)
    if not rep.ok:
        for e in rep.error_lines()[:10]:
            print("  ", e)
        return 1
    print(f"built {len(srcs)} in {time.time() - t0:.0f} s")
    eng = Engine(rep.library)
    eng.resize(16)
    from native.video import TestPattern
    tp = TestPattern()                                    # what a Video node sees while the previews are made
    entries = []
    import numpy as np
    from native.geometry import Geometry
    for eid, stem, g, bundle, title in items:
        # a video graph on a flat matrix, the picture as it is: on the cube the picture lies across the unfolded
        # net, and what moves in it mostly falls where there are no faces
        flat = any(n["type"] == "Video" for n in g.flatten().nodes.values()) if g.nodes else False
        if flat:
            eng.set_geometry(Geometry("matrix", w=48, h=27))
        else:
            eng.resize(16)
        k = eng.find(title)
        eng.select(k)
        syn = Synth()
        syn.gate_bass = syn.gate_mid = syn.gate_treb = True
        for f in range(40):
            syn.push(eng); eng.video(tp.frame_at(f * 0.04)); eng.frame()
        frames, n = [], int(SECONDS * FPS)
        for i in range(n):
            tgt = eng.sim_ms + 1000.0 / FPS
            while eng.sim_ms < tgt:
                syn.push(eng); eng.video(tp.frame_at(eng.sim_ms / 1000.0)); eng.frame()
            net = eng.rgb().copy()
            if flat:
                frames.append(np.repeat(np.repeat(net, 5, 0), 5, 1).astype(np.uint8))
                continue
            net[~eng.lit_mask()] = 0
            frames.append(render.render(net, eng.B, SIZE, -0.6 + 2 * math.pi * 0.25 * i / n, 0.75, 4.6))
        gif.write(os.path.join(out, "previews", eid + ".gif"), frames, fps=FPS)
        data = (json.dumps(bundle, indent=1) + "\n").encode("utf-8")
        with open(os.path.join(out, "effects", eid + ".graph.json"), "wb") as f:
            f.write(data)
        prev = old.get(eid, {})
        entries.append({"id": eid, "name": g.name or stem,
                        "author": prev.get("author", "WLED Effects Studio examples"),
                        "description": prev.get("description", DESCRIPTIONS.get(stem, "")),
                        "tags": prev.get("tags", TAGS.get(stem, ["3-D", "cube"])),
                        "sha256": hashlib.sha256(data).hexdigest(), "requires": bundle["requires"]})
        print(f"{eid}: {len(data) // 1024} KB, preview {os.path.getsize(os.path.join(out, 'previews', eid + '.gif')) // 1024} KB")
    keep = [e for i, e in old.items() if i not in {x["id"] for x in entries}]
    with open(idx_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump({"gallery": 1, "entries": sorted(keep + entries, key=lambda e: e["name"].lower())}, f, indent=1)
        f.write("\n")
    print(f"{idx_path}: {len(keep) + len(entries)} entries")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
