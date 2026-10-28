"""A gallery on disk for the tests (native/gallery.py): two of the examples'
graphs as entries, each with a small GIF, its index naming them, and a
file:// address to set as STUDIO_GALLERY_URL - no network, no server.

    url = make(folder)       # the folder made, its address returned
"""
import hashlib
import json
import os
import pathlib
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
ENTRIES = (("spirals", "Spirals", "Spiral arms turning."), ("fireworks", "Fireworks", "Bursts on the beat."))


def make(folder, extra=None):
    """The fake gallery in `folder`: its file:// address (ending in /). `extra`: more raw index entries."""
    sys.path.insert(0, ROOT)
    import numpy as np
    from native import gif
    os.makedirs(os.path.join(folder, "effects"), exist_ok=True)
    os.makedirs(os.path.join(folder, "previews"), exist_ok=True)
    entries = []
    for k, (stem, name, desc) in enumerate(ENTRIES):
        g = json.load(open(os.path.join(ROOT, "examples", "graphs", stem + ".json"), encoding="utf-8"))
        g["name"] = name + " (gallery)"                     # not the name of a graph the project may have already
        data = (json.dumps({"studio_graph": 1, "graph": g, "subgraphs": {}, "nodes": {}, "requires": []}, indent=1)
                + "\n").encode("utf-8")
        with open(os.path.join(folder, "effects", stem + ".graph.json"), "wb") as f:
            f.write(data)
        frames = [np.full((32, 48, 3), (40 + 60 * i, 80 * k, 200 - 40 * i), np.uint8) for i in range(4)]
        gif.write(os.path.join(folder, "previews", stem + ".gif"), frames, fps=4)
        entries.append({"id": stem, "name": name + " (gallery)", "author": "the tests", "description": desc,
                        "tags": ["test"], "sha256": hashlib.sha256(data).hexdigest(), "requires": []})
    with open(os.path.join(folder, "index.json"), "w", encoding="utf-8") as f:
        json.dump({"gallery": 1, "entries": entries + list(extra or [])}, f, indent=1)
    # a pack of VJ looks (native/addons.py): a preset and a shader, its picture
    looks = {"Smoke spin.milk": "[preset00]\nzoom=1.02\nper_frame_1=rot = rot + 0.02*max(bass_att - 1, 0);\n",
             "Smoke rings by the tests.glsl": "// NAME: Smoke rings (the tests)\n"
             "void mainImage(out vec4 fragColor, in vec2 fragCoord) {\n    vec2 uv = fragCoord / iResolution.xy;\n"
             "    fragColor = vec4(0.5 + 0.5 * sin(12.0 * length(uv - 0.5) - iTime), uv.x, iMouse.x / iResolution.x, 1.0);\n}\n"}
    os.makedirs(os.path.join(folder, "looks", "smoke-pack"), exist_ok=True)
    items = []
    for name, text in looks.items():
        data = text.encode("utf-8")
        with open(os.path.join(folder, "looks", "smoke-pack", name), "wb") as f:
            f.write(data)
        items.append({"file": name, "author": "the tests", "licence": "test", "sha256": hashlib.sha256(data).hexdigest()})
    os.makedirs(os.path.join(folder, "previews", "packs"), exist_ok=True)
    from PIL import Image
    Image.fromarray(np.full((72, 256, 3), (30, 120, 200), np.uint8)).save(os.path.join(folder, "previews", "packs", "smoke-pack.png"))
    with open(os.path.join(folder, "packs.json"), "w", encoding="utf-8") as f:
        json.dump({"packs": 1, "list": [{"id": "smoke-pack", "name": "Smoke: test looks", "kind": "milkdrop",
                                         "description": "A preset and a shader for the tests.", "licence": "CC BY-NC-SA 3.0",
                                         "noncommercial": True, "items": items}]}, f, indent=1)
    return pathlib.Path(folder).resolve().as_uri() + "/"
