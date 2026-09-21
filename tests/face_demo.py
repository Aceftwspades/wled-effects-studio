"""A graph with every kind of face on it - a Wave with its dot, a Scope,
Steps, Tempo, Integrate (sparklines), a Remap and a Smoothstep (transfer
curves), pattern thumbnails, colour strips, a Bitmap, a Path, a Text -
written into a project for the smoke test (and for looking at). Run:
python tests/face_demo.py [project dir]  - writes graphs/face_demo.json.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from native import graph as G                      # noqa: E402
from native.nodedefs import library                # noqa: E402

NAME = "face_demo"


def build():
    g = G.Graph({"name": NAME}, lib=library())
    t = g.add("Time", (0, 0)); a = g.add("Audio", (0, 200))
    w = g.add("Wave", (250, 0)); g.link(t, "t", w, "x"); g.nodes[w]["inputs"]["cycles"] = 0.5
    sc = g.add("Scope", (500, 0)); g.link(w, "value", sc, "x")
    st = g.add("Steps", (250, 250)); g.link(a, "beat", st, "trigger")
    tp = g.add("Tempo", (250, 600)); g.link(a, "beat", tp, "beat")
    ig = g.add("Integrate", (500, 250)); g.link(w, "value", ig, "rate")
    rm = g.add("Remap", (750, 0)); g.nodes[rm]["params"].update({"out_lo": 2.0, "out_hi": 6.0}); g.link(w, "value", rm, "x")
    ss = g.add("Smoothstep", (750, 250)); g.nodes[ss]["params"].update({"e0": 0.2, "e1": 0.8}); g.link(w, "value", ss, "x")
    c = g.add("Coords", (0, 900)); ck = g.add("Checker", (250, 900)); g.link(c, "u", ck, "x"); g.link(c, "v", ck, "y")
    rp = g.add("Ripple", (500, 900)); vo = g.add("Voronoi", (750, 900))
    cr = g.add("Colour ramp", (1000, 0)); g.link(ss, "result", cr, "t")
    bb = g.add("Blackbody", (1000, 250)); g.nodes[bb]["inputs"]["kelvin"] = 5000.0
    bm = g.add("Bitmap", (1000, 500)); pth = g.add("Path", (1000, 750)); tx = g.add("Text", (1250, 750))
    cp = g.add("Colour pick", (1250, 500)); g.link(st, "value", cp, "index")
    n = g.add("Noise", (500, 500)); g.link(c, "u", n, "x"); g.link(c, "v", n, "y"); g.link(t, "t", n, "z"); g.link(rm, "result", n, "scale")
    p = g.add("Palette", (1250, 0)); g.link(n, "value", p, "index"); g.link(ig, "value", p, "brightness")
    o = g.add("Output", (1500, 0)); g.link(p, "color", o, "color")
    for nid in (rp, vo, bm, pth, tx, cp, bb, cr):
        g.nodes[nid]["label"] = None
    g.compile()                                          # it must build
    return g, {"time": t, "audio": a, "wave": w, "scope": sc, "steps": st, "tempo": tp, "integrate": ig, "remap": rm,
               "smoothstep": ss, "checker": ck, "ripple": rp, "voronoi": vo, "ramp": cr, "blackbody": bb, "bitmap": bm,
               "path": pth, "text": tx, "pick": cp, "noise": n, "palette": p}


def write(project_dir):
    g, ids = build()
    path = os.path.join(project_dir, "graphs", NAME + ".json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    json.dump(g.to_json(), open(path, "w", encoding="utf-8"), indent=1)
    return path, ids


if __name__ == "__main__":
    root = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(HERE), "projects", "default")
    print(write(root)[0])
