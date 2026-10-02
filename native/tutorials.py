"""A tutorial for every node: why it is there, a small graph built round it,
a picture of that graph running, and changes to try - in NODES.md under the
node's reference, and in the studio, where "Try it" opens the graph live.

A lesson is docs/nodes/<ident>.json, written by hand:

    {"node": "Slew",                       the node it teaches
     "star": 3,                            that node's id in the graph
     "why": ["...", "..."],                when to reach for it, and against what (paragraphs)
     "steps": ["...", "..."],              the graph, wire by wire, and why each is there
     "try": [{"label": "...", "text": "...",
              "set": [[3, "up", 8.0], ...]}],     a change: node id, input or setting, value
     "shape": {"kind": "matrix", "params": {"w": 32, "h": 16}},   optional; this is the default
     "trace": [[2, "beat"], [3, "value"]], optional: values plotted under the picture
     "fx": {"sx": 128, ...},               optional: the sliders the picture is made at
     "graph": {"name": ..., "nodes": [...], "links": [...]}}

The picture (docs/nodes/<ident>.gif) is made from the graph by
tests/make_tutorials.py, never by hand; nodedocs.markdown() puts the
lesson under the node's reference. In the studio a lesson runs in a
project of its own (TUTORIALS), so the person's own work is never written
to: Try it switches there and back, and "Copy into my project" is the only
way a lesson's graph reaches their project.
"""
import json
import os
import re

from native import paths

DIR = os.path.join(paths.RES, "docs", "nodes")
TUTORIALS = "Node tutorials"                 # the project the lessons run in
SHAPE = {"kind": "matrix", "params": {"w": 32, "h": 16}}
SCHEME = "studio:try/"                       # a link the reader runs: studio:try/<ident>[/<n>], studio:tutorial/<what>


def ident(node):
    """A node's file stem: "Beat kick" -> beat_kick."""
    return re.sub(r"[^a-z0-9]+", "_", node.lower()).strip("_")


def by_ident(stem):
    """The node a file stem (or a name) is for: "reaction_diffusion" -> "Reaction diffusion"."""
    p = os.path.join(DIR, ident(stem) + ".json")
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            return json.load(f)["node"]
    return stem


def path(node, ext=".json"):
    return os.path.join(DIR, ident(node) + ext)


def picture(node):
    return path(node, ".gif")


def load(node):
    """The lesson for a node, or None when it has none yet."""
    p = path(node)
    if not os.path.exists(p):
        return None
    with open(p, encoding="utf-8") as f:
        d = json.load(f)
    d.setdefault("shape", SHAPE)
    d.setdefault("try", [])
    d.setdefault("trace", [])
    return d


def all_lessons():
    """{node: lesson} for every lesson in docs/nodes."""
    out = {}
    if os.path.isdir(DIR):
        for f in sorted(os.listdir(DIR)):
            if f.endswith(".json"):
                with open(os.path.join(DIR, f), encoding="utf-8") as fh:
                    d = json.load(fh)
                out[d["node"]] = load(d["node"])
    return out


def graph_of(lesson, lib=None, name=None):
    """The lesson's graph as a Graph; arranged when its nodes have no places."""
    from native import graph as G
    d = json.loads(json.dumps(lesson["graph"]))
    d["name"] = name or d.get("name") or ("Tutorial " + lesson["node"])
    d["implicit"] = 1                             # written now: an unwired coordinate reads the pixel (graph.Graph)
    placed = all("pos" in n for n in d["nodes"])
    for n in d["nodes"]:
        n.setdefault("pos", [0, 0])
    g = G.migrate(G.Graph(d, lib=lib))
    if not placed:
        g.arrange(col_w=220)                      # a lesson is written without places: laid out left to right, close
    if lesson.get("assets"):
        g.project_dir = EXAMPLES                  # its files (an Image's picture) as the examples have them
    return g


EXAMPLES = os.path.join(paths.RES, "examples")


def copy_assets(lesson, project_dir):
    """A lesson's files ("assets": paths under examples/) into a project, where its graph reads them."""
    import shutil
    for rel in lesson.get("assets", []):
        dst = os.path.join(project_dir, rel)
        if not os.path.exists(dst):
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copyfile(os.path.join(EXAMPLES, rel), dst)


def used_in(node):
    """The example graphs that use a node: [(file, title)]."""
    d = os.path.join(paths.RES, "examples", "graphs")
    out = []
    if os.path.isdir(d):
        for f in sorted(os.listdir(d)):
            if not f.endswith(".json"):
                continue
            try:
                g = json.load(open(os.path.join(d, f), encoding="utf-8"))
            except Exception:
                continue
            if any(n.get("type") == node for n in g.get("nodes", [])):
                out.append((f, g.get("name") or f[:-5]))
    return out


def problems(lesson, lib):
    """What is wrong with a lesson, in words; empty when nothing is. Its node
    and star agree, the graph compiles, every change names a pin or setting
    there, and the words say what each of the node's inputs and settings is
    for (by the name the node shows)."""
    from native import graph as G
    from native.nodeface import label
    node = lesson.get("node")
    out = []
    if node not in lib:
        return [f"{node}: no such node"]
    try:
        g = graph_of(lesson, lib)
    except Exception as e:
        return [f"{node}: the graph does not load ({e})"]
    star = g.nodes.get(lesson.get("star"))
    if star is None or star["type"] != node:
        out.append(f"{node}: star #{lesson.get('star')} is not a {node} node")
    try:
        g.compile()
    except G.GraphError as e:
        out.append(f"{node}: the graph does not compile ({e})")
    for k, t in enumerate(lesson.get("try", []), 1):
        for nid, name, _ in t.get("set", []):
            n = g.nodes.get(nid)
            d = g.node_def(n) if n else None
            if d is None or not any(p["name"] == name for p in d["inputs"] + d["params"]):
                out.append(f"{node}: try {k} sets #{nid} {name}, which is not there")
    for nid, name in lesson.get("trace", []):
        n = g.nodes.get(nid)
        d = g.node_def(n) if n else None
        if d is None or not any(p["name"] == name for p in d["outputs"]):
            out.append(f"{node}: the trace's #{nid} {name} is not an output there")
    words = " ".join(lesson.get("why", []) + lesson.get("steps", [])
                     + [t.get("label", "") + " " + t.get("text", "") for t in lesson.get("try", [])]).lower()
    d = lib[node]
    for p in d["inputs"] + d["params"]:
        shown = label(node, p["name"]).lower()
        if shown not in words:                        # by the name the node shows, not its key
            out.append(f"{node}: the lesson never says what {shown!r} does")
    for key in ("why", "steps"):
        if not lesson.get(key):
            out.append(f"{node}: no {key}")
    return out


def markdown(node, lesson):
    """The lesson's part of the node's entry in NODES.md: lines of Markdown."""
    out = ["**Why use it**", ""]
    for para in lesson["why"]:
        out += [para, ""]
    out += ["**Tutorial**", ""]
    pic = picture(node)
    if os.path.exists(pic):
        cap = lesson.get("caption") or f"{node}: the tutorial's graph running"
        out += [f"![{cap}](docs/nodes/{os.path.basename(pic)})", ""]
    for k, s in enumerate(lesson["steps"], 1):
        out.append(f"{k}. {s}")
    out += ["", f"[Try it in the studio]({SCHEME}{ident(node)}): the graph opens live in the {TUTORIALS} project; "
                "your own project is saved and comes back with **Back to my project**.", ""]
    if lesson["try"]:
        out += ["**Try this**", ""]
        for k, t in enumerate(lesson["try"], 1):
            out.append(f"- [{t['label']}]({SCHEME}{ident(node)}/{k}): {t['text']}")
        out.append("")
    used = used_in(node)
    if used:
        out += ["**Used in**", "", ", ".join(f"{title} (`{f}`)" for f, title in used), ""]
    return out


# --- in the studio -------------------------------------------------------------------------
# app._tutorial: {"node", "file", "back": (project path, graph file or None)} while a lesson is open

def tutorials_path():
    from native.project import project_path
    return project_path(TUTORIALS)


def active(app):
    """The lesson open now, or None: the app is in the tutorials project with one open."""
    t = getattr(app, "_tutorial", None)
    if not t:
        return None
    if os.path.normcase(os.path.abspath(app.project.path)) != os.path.normcase(os.path.abspath(tutorials_path())):
        app._tutorial = None                     # the person went elsewhere: the lesson is over
        _restore(app, t)
        return None
    return t


def _arrange(app, lesson, t):
    """The room for a lesson: the side panel folded, the 3-D view in the bottom-left corner (the
    page covers the right), a flat shape seen from the front. What it was is kept in
    t["was"] for _restore - the first lesson's, when one follows another."""
    from native import room, view3d
    if "was" not in t:
        t["was"] = {"panel": app.prefs.get("graph_panel_open"), "pip": dict(room.pip(app)), "cam": view3d.saved(app)}
    room.fold_panel(app)
    room.pip(app).update(corner="bl", tucked=False, max=False)
    if lesson["shape"]["kind"] in ("matrix", "strip"):
        view3d.preset(app, "front", animate=False)
    else:
        view3d.home(app, animate=False)
    app.request_layout()
    t["framed"] = 0                              # the graph framed once the layout has settled (poll)


def _restore(app, t):
    """The person's layout as it was before the lesson: the panel, the 3-D view's corner, the camera."""
    from native import room, view3d
    was = (t or {}).get("was")
    if not was:
        return
    app.prefs["graph_panel_open"] = was["panel"]
    room.pip(app).clear(); room.pip(app).update(was["pip"])
    room._save(app)
    try:
        view3d.restore(app, was["cam"])
    except Exception:
        pass
    app.request_layout()


def poll(app):
    """Per frame while the reader is up: the lesson's graph framed into the part of the canvas the
    page leaves in view, once the folded panel and the page's column have settled."""
    import dearpygui.dearpygui as dpg
    t = active(app)
    if not t or t.get("framed") is None or not app.gp.graph:
        return
    t["framed"] += 1
    if t["framed"] < 12:
        return
    t["framed"] = None
    if not dpg.does_item_exist("node_editor"):
        return
    ex, ey = dpg.get_item_rect_min("node_editor")
    ew, eh = dpg.get_item_rect_size("node_editor")
    right = ex + ew
    if dpg.does_item_exist("reader_win") and dpg.is_item_shown("reader_win"):
        right = min(right, dpg.get_item_pos("reader_win")[0] - 8)
    from native import room
    from native.typeface import px
    pip_h = px(room.pip(app)["size"]) if room.pip_on(app) else 0
    app.gp._frame_view(list(app.gp.graph.nodes), most=1.0, room=(max(200, right - ex), max(200, eh - pip_h)))


def _write(app, lesson):
    """The lesson's graph, as written, into the tutorials project's graphs: (file name)."""
    from native import graph as G
    g = graph_of(lesson, app.gp.lib)
    fname = "tutorial_" + ident(lesson["node"]) + ".json"
    G.save(g, os.path.join(app.gp.dir, fname))
    return fname


def try_it(app, node, change=None):
    """Open a node's lesson live: the person's project saved and left, the tutorials project
    opened, the lesson's graph written fresh into it and opened, its node selected and the
    graph framed, Live on, the shape the lesson wants. `change`: a "Try this" number, applied
    after (the lesson already open stays as it is and only the change is made)."""
    from native.geometry import Geometry
    lesson = load(node)
    if lesson is None:
        app.gp.status(f"{node} has no tutorial yet"); return False
    t = active(app)
    if t is None or t["node"] != node or change is None:
        if t is None:
            back = (app.project.path, app.gp.file if app.gp.graph is not None and app.gp.cur_dir == app.gp.dir else None)
        else:
            back = t["back"]
        here = os.path.normcase(os.path.abspath(app.project.path)) == os.path.normcase(os.path.abspath(tutorials_path()))
        if not here:
            app.switch_project(tutorials_path(), create=not os.path.isdir(tutorials_path()))
        geom = Geometry.from_json(lesson["shape"])
        if app.project.geometry.to_json() != geom.to_json():
            app.apply_geometry(geom)
        copy_assets(lesson, app.project.path)
        if lesson.get("video") and getattr(app, "video_src", None) is None:
            from native import video_ui
            video_ui.start(app, lesson["video"])  # a Video lesson needs a picture: the test pattern, unless one plays
        if lesson.get("colours"):                 # the three pickers a lesson about them is shown with
            for i, c in enumerate(lesson["colours"][:3]):
                app.on_color(i, ((c >> 16) & 255, (c >> 8) & 255, c & 255))
            app.refresh_colours()
        fname = _write(app, lesson)
        dpg_refresh_files(app)
        app.gp.open(fname)
        app._tutorial = dict(t or {}, node=node, file=fname, back=back)
        app.show_pane("graph")
        _arrange(app, lesson, app._tutorial)
        app.gp.set_selection([lesson["star"]])
        app.build_current()                       # running at once, Live on or off
        from native import reader_ui
        if reader_ui.S.doc != "NODES.md" or not reader_ui.shown():
            reader_ui.open_doc(app, "NODES.md", node)          # Try it from elsewhere: the page comes too
        reader_ui.beside(app, True)               # the page at the side, the graph and the LEDs in view
        reader_ui.tutorial_bar(app)
    if change is not None:
        apply_change(app, lesson, change)
    else:
        app.gp.status(f"the {node} tutorial: change its inputs and settings and watch - "
                      "Back to my project (in the reader) returns you")
    return True


def dpg_refresh_files(app):
    import dearpygui.dearpygui as dpg
    if dpg.does_item_exist("graph_file"):
        dpg.configure_item("graph_file", items=app.gp.files())


def apply_change(app, lesson, k):
    """A "Try this" change (numbered from 1) made to the open lesson: inputs as a knob sets
    them (live), settings as the properties do; the node selected so its values show."""
    try:
        t = lesson["try"][int(k) - 1]
    except (IndexError, ValueError):
        return False
    gp = app.gp
    for nid, name, val in t["set"]:
        n = gp.graph.nodes.get(nid) if gp.graph else None
        if n is None:
            continue
        d = gp.graph.node_def(n)
        if any(p["name"] == name for p in d["inputs"]):
            gp.set_input_live(nid, name, val)
        else:
            gp.set_param(nid, name, val)
    gp.set_selection([t["set"][0][0]] if t["set"] else [lesson["star"]])
    gp.status(f"tried: {t['label']} - {t['text']}")
    return True


def reset(app):
    """The open lesson as it was written: its graph rewritten and opened again."""
    t = active(app)
    if t is None:
        return False
    return try_it(app, t["node"])


def back(app):
    """The person's own project again, and the graph they had open."""
    t = getattr(app, "_tutorial", None)
    if not t:
        return False
    proj, fname = t["back"]
    app._tutorial = None
    if os.path.isdir(proj):
        app.switch_project(proj)
        if fname and os.path.exists(os.path.join(app.gp.dir, fname)):
            app.gp.open(fname)
    _restore(app, t)                             # the panel, the 3-D view's corner and the camera as they were
    from native import reader_ui
    reader_ui.tutorial_bar(app)
    return True


def copy_to_project(app):
    """The lesson's graph, as it is now, into the person's own project as a new graph; then
    back there with it open."""
    from native import graph as G
    t = active(app)
    if t is None or app.gp.graph is None:
        return False
    app.gp.save()
    g = app.gp.graph
    proj, _ = t["back"]
    gdir = os.path.join(proj, "graphs")
    os.makedirs(gdir, exist_ok=True)
    stem = ident(t["node"]) + "_tutorial"
    fname, n = stem + ".json", 2
    while os.path.exists(os.path.join(gdir, fname)):
        fname, n = f"{stem}_{n}.json", n + 1
    title = f"{t['node']} tutorial" + (f" {n - 1}" if n > 2 else "")
    d = g.to_json()
    d["name"] = title
    with open(os.path.join(gdir, fname), "w", encoding="utf-8") as f:
        json.dump(d, f, indent=1)
    t["back"] = (proj, fname)
    back(app)
    app.gp.status(f"the {t['node']} tutorial's graph is {fname} in your project")
    return fname


def follow(app, target):
    """A studio: link from the reader. True when it was one."""
    if target.startswith(SCHEME):
        rest = target[len(SCHEME):]
        stem, _, k = rest.partition("/")
        node = by_ident(stem)                # a link names the node by its file stem: Markdown targets have no spaces
        try_it(app, node, int(k) if k else None)
        return True
    if target == "studio:tutorial/back":
        back(app); return True
    if target == "studio:tutorial/reset":
        reset(app); return True
    if target == "studio:tutorial/copy":
        copy_to_project(app); return True
    return False
