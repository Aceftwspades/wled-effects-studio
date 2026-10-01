"""Every node in the library on one graph, and what each must look like on
it: its fields inside the node, its pins on the node's edges - an input's
row starting at the left, an output's name against the right - and a name
too long for its place cut with "...", never pushing the node wider. The
smoke writes the gallery into its project, opens it, and asks check(app) at
two zooms; run alone it writes graphs/node_gallery.json to look at:

    python tests/node_gallery.py [project dir]
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from native import graph as G                      # noqa: E402
from native.nodedefs import library                # noqa: E402

NAME = "node_gallery"
COLS = 8                 # nodes a row
PITCH_X = 240            # graph units between columns: a node is 150 inside, its padding and a gap besides
GAP_Y = 60               # between rows, below the tallest node of the row
SLACK = 1.5              # px: a measure's rounding


def _height(d):
    """A node's height in graph units, roughly - its rows (pins, settings) and a face."""
    rows = len(d["inputs"]) + len(d["outputs"]) + len(d["params"])
    return 70 + 30 * rows + (120 if d.get("multiline") or d.get("pads") else 0)


def build(lib=None):
    """The gallery: one of each node type, in rows by category, every name
    and setting as the library makes it."""
    lib = lib or library()
    g = G.Graph({"name": NAME}, lib=lib)
    order = ("controls", "signals", "coords", "generate", "maths", "colour", "graph", "custom", "output")
    types = sorted(lib, key=lambda t: (order.index(lib[t]["cat"]) if lib[t]["cat"] in order else len(order), t))
    ids, x, y, row_h = {}, 0, 0, 0
    for k, t in enumerate(types):
        if k and k % COLS == 0:
            x, y, row_h = 0, y + row_h + GAP_Y, 0
        ids[t] = g.add(t, (x, y))
        row_h = max(row_h, _height(lib[t]))
        x += PITCH_X
    return g, ids


def write(project_dir):
    g, ids = build()
    path = os.path.join(project_dir, "graphs", NAME + ".json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    json.dump(g.to_json(), open(path, "w", encoding="utf-8"), indent=1)
    return path, ids


# --- what the nodes must look like ----------------------------------------------------------
def _items(item):
    """Every item under `item`, depth first."""
    import dearpygui.dearpygui as dpg
    out = []
    for slot in (0, 1, 2, 3):
        for ch in dpg.get_item_children(item, slot) or []:
            out.append(ch)
            out += _items(ch)
    return out


def _rect(item):
    import dearpygui.dearpygui as dpg
    st = dpg.get_item_state(item)
    if "rect_min" not in st or "rect_max" not in st:
        return None
    (x0, y0), (x1, y1) = st["rect_min"], st["rect_max"]
    return None if x1 <= x0 and y1 <= y0 else (x0, y0, x1, y1)


def check(app):
    """What is wrong with the nodes on screen as the gallery shows them:
    a list of "<type> #<id>: <what>" lines, empty when every node is right.
    A node's box (its rect) is its content: the width it is laid out to -
    NODE_W at this zoom, a narrow node's NARROW_W or as much more as its
    title needs, up to NODE_W - and nothing in it may reach past that: a
    name, a field, a face; nor may a title push the box wider. A name cut
    short ends in "..."; an output's name ends at the right edge, where its
    pin is, and an input's row starts at the left, at its pin. A Frame is a
    box of the user's size, left out."""
    import dearpygui.dearpygui as dpg
    from native import graph_ui as GU
    from native import nodeface
    gp = app.gp
    bad = []
    seen = set()
    for nid, n in sorted(gp.graph.nodes.items()):
        seen.add(n["type"])
        if n["type"] == "Frame":
            continue
        tag = f"gnode_{nid}"
        nr = _rect(tag) if dpg.does_item_exist(tag) else None
        who = f"{n['type']} #{nid}"
        if nr is None:
            bad.append(f"{who}: not drawn"); continue
        d = gp.graph.node_def(n)
        lo, full = gp.px(GU.NARROW_W if d.get("narrow") else GU.NODE_W), gp.px(GU.NODE_W)
        width = gp._node_w.get(nid)
        if width is None or not lo <= width <= full:
            bad.append(f"{who}: laid out {width} wide, not {lo}..{full}"); continue
        left, right = nr[0], nr[0] + width
        if nr[2] - nr[0] > width + SLACK:
            bad.append(f"{who}: {nr[2] - nr[0] - width:.0f} px wider than it is laid out to (its title, or a field)")
        for it in _items(tag):
            r = _rect(it)
            if r is None or not dpg.is_item_shown(it):
                continue
            if r[2] > right + SLACK or r[0] < left - SLACK:
                kind = dpg.get_item_type(it).split("::")[-1]
                what = dpg.get_value(it) if kind == "mvText" else kind
                bad.append(f"{who}: {what!r} from {r[0] - left:.0f} to {r[2] - left:.0f} px, outside its 0..{width}")
        for i in d["inputs"]:
            t = f"gin_{nid}_{i['name']}_t"
            if dpg.does_item_exist(t) and dpg.is_item_shown(t):
                r = _rect(t)
                if r is not None and abs(r[0] - left) > SLACK:
                    bad.append(f"{who}: input {i['name']!r} starts {r[0] - left:.0f} px in from its pin")
                full_name, shown = nodeface.label(n["type"], i["name"]), str(dpg.get_value(t))
                if shown != full_name and not shown.endswith("..."):
                    bad.append(f"{who}: input {i['name']!r} cut to {shown!r} with no '...'")
        for o in d["outputs"]:
            t = f"gout_{nid}_{o['name']}"
            kids = dpg.get_item_children(t, 1) if dpg.does_item_exist(t) else []
            r = _rect(kids[0]) if kids else None
            if r is not None and abs(r[2] - right) > SLACK + 1:
                bad.append(f"{who}: output {o['name']!r} ends {right - r[2]:.0f} px short of its pin")
            if kids:
                full_name, shown = nodeface.label(n["type"], o["name"]), str(dpg.get_value(kids[0]))
                if shown != full_name and not shown.endswith("..."):
                    bad.append(f"{who}: output {o['name']!r} cut to {shown!r} with no '...'")
    missing = sorted(set(library()) - seen)                 # the library's own (a project's custom nodes aside)
    if missing:
        bad.append(f"not in the gallery: {', '.join(missing)}")
    return bad


if __name__ == "__main__":
    root = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(HERE), "projects", "default")
    print(write(root)[0])
