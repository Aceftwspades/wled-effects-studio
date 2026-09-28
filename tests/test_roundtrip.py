"""Round trips: what the studio writes, read back the same - graphs,
geometries (every kind, shapes of parts, a polyhedron, points), the
project file, the sequence, the segments, the ledmap, the xLights model;
and the older files the history keeps still open and compile. Run with
python tests/test_roundtrip.py  (or pytest).
"""
import json
import os
import shutil
import sys
import tempfile

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from native import graph as G                      # noqa: E402
from native.nodedefs import library                # noqa: E402
from native.geometry import Geometry               # noqa: E402
from native import shapes, shape_io                # noqa: E402

LIB = library()


def _graph_files():
    out = []
    for d in (os.path.join(ROOT, "examples", "graphs"), os.path.join(ROOT, "projects", "default", "graphs")):
        if os.path.isdir(d):
            out += [os.path.join(d, f) for f in sorted(os.listdir(d)) if f.endswith(".json")]
    return out


def _resolver(project_dir):
    """Sub-graph nodes by file stem, from the project's subgraphs/ (as the panel does)."""
    subs = {}

    def resolve(ident):
        if ident not in subs:
            path = os.path.join(project_dir, "subgraphs", ident + ".json")
            if not os.path.exists(path):
                return None
            subs[ident] = G.load(path, lib=LIB, resolver=resolve)
            subs[ident].project_dir = project_dir
        return subs[ident]
    return resolve


def _canon(d):
    return json.dumps(d, sort_keys=True)


def test_graphs_round_trip():
    """Loaded, written, loaded again: the same JSON, the same C++."""
    tmp = tempfile.mkdtemp()
    bad = []
    try:
        for path in _graph_files():
            pdir = os.path.dirname(os.path.dirname(path))
            res = _resolver(pdir)
            g = G.load(path, lib=LIB, resolver=res)
            g.project_dir = pdir
            try:
                src = g.compile()
            except G.GraphError:
                continue                                    # a graph left broken on purpose (the smoke test's): not the format
            out = os.path.join(tmp, os.path.basename(path))
            G.save(g, out)
            g2 = G.load(out, lib=LIB, resolver=res)
            g2.project_dir = g.project_dir
            if _canon(g2.to_json()) != _canon(g.to_json()):
                bad.append(f"{os.path.basename(path)}: the JSON changed on a round trip")
            elif g2.compile() != src:
                bad.append(f"{os.path.basename(path)}: the C++ changed on a round trip")
            # and the migration is idempotent: migrating a migrated graph changes nothing
            g3 = G.migrate(G.Graph(g2.to_json(), lib=LIB, resolver=res))
            if _canon(g3.to_json()) != _canon(g2.to_json()):
                bad.append(f"{os.path.basename(path)}: migrate() is not idempotent")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    assert not bad, "\n".join(bad)
    assert len(_graph_files()) >= 35


def _geometries():
    yield "strip", Geometry("strip", n=150)
    yield "strip serpentine map", Geometry("strip", n=20, map=list(range(19, -1, -1)))
    yield "matrix", Geometry("matrix", w=32, h=16)
    yield "cube", Geometry("cube", B=16)
    yield "cylinder", Geometry("cylinder", w=24, h=10)
    yield "sphere", Geometry("sphere", w=24, h=12)
    yield "torus", Geometry("torus", w=24, h=8)
    pts = [[float(i), float(i % 3), 0.0] for i in range(30)]
    yield "xyz", Geometry("xyz", points=pts)
    ring = shapes.new_part("ring", n=12); strip = shapes.new_part("strip", n=5); strip["pos"] = [0, 0, 5]; strip["rot"] = [0, 0, 90]
    yield "shape of parts", Geometry("shape", parts=[ring, strip])
    yield "shape soccer ball", Geometry("shape", parts=[shapes.new_part("polyhedron", solid="soccer ball", per_edge=3)])
    panel = shapes.new_part("panel", w=8, h=4)
    yield "shape grid layout", Geometry("shape", parts=[panel], layout="grid")


def test_geometries_round_trip():
    """to_json / from_json: the same kind and parameters, the same LEDs in
    the same places and the same wiring order, for every kind."""
    bad = []
    for name, g in _geometries():
        d = json.loads(json.dumps(g.to_json()))         # through text, as project.json holds it
        g2 = Geometry.from_json(d)
        if _canon(g2.to_json()) != _canon(g.to_json()):
            bad.append(f"{name}: the JSON changed"); continue
        if (g2.w, g2.h, g2.count) != (g.w, g.h, g.count):
            bad.append(f"{name}: size {g2.w}x{g2.h}/{g2.count} vs {g.w}x{g.h}/{g.count}"); continue
        if not np.array_equal(np.asarray(g2.lit), np.asarray(g.lit)) or not np.array_equal(np.asarray(g2.phys), np.asarray(g.phys)):
            bad.append(f"{name}: the lit mask or the wiring order changed"); continue
        a, b = np.asarray(g.pos, float), np.asarray(g2.pos, float)
        if not np.allclose(np.nan_to_num(a), np.nan_to_num(b), atol=1e-6):
            bad.append(f"{name}: positions moved")
    assert not bad, "\n".join(bad)


def test_ledmap_round_trip():
    """A matrix's and a strip's ledmap.json read back as the same wiring."""
    for g in (Geometry("matrix", w=16, h=8, serpentine=True), Geometry("strip", n=40, map=list(range(39, -1, -1)))):
        d = json.loads(json.dumps(g.ledmap()))
        g2 = Geometry.from_ledmap(d)
        assert (g2.w, g2.h) == (g.w, g.h) and np.array_equal(np.asarray(g2.phys), np.asarray(g.phys)), g.kind
        assert d["map"] == g2.ledmap()["map"]


def test_project_round_trip():
    """A project saved and opened again: geometry, options, the imported list."""
    from native.project import Project
    tmp = tempfile.mkdtemp()
    try:
        p = Project(os.path.join(tmp, "rt"))
        p.geometry = Geometry("sphere", w=24, h=12)
        p.options["device"] = "127.0.0.1:8770"
        p.options["sequence"] = {"steps": [{"name": "a", "dur": 5.0, "rows": 24, "colors": [1, 2, 3], "segments": []}], "base": 10, "pid": 9, "name": "Show", "repeat": 0}
        p.options["palettes"] = [{"name": "Test", "stops": [[0, 255, 0, 0], [255, 0, 0, 255]]}]
        p.imported = ["a.cpp"]
        p.save()
        q = Project(os.path.join(tmp, "rt"))
        assert _canon(q.geometry.to_json()) == _canon(p.geometry.to_json())
        assert q.options == p.options and q.imported == p.imported
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_project_option_undo():
    """Every save that changes the sequence, the schedule, the palettes or
    the segments keeps what it was: undo and redo walk them, per option,
    and a change after an undo drops the redo."""
    from native.project import Project
    tmp = tempfile.mkdtemp()
    try:
        p = Project(os.path.join(tmp, "u"))
        assert not p.can_undo("palettes")
        p.options["palettes"] = [{"name": "a", "stops": []}]; p.save()
        p.options["palettes"] = [{"name": "a", "stops": []}, {"name": "b", "stops": []}]; p.save()
        p.options["sequence"] = {"steps": [1]}; p.save()
        assert p.can_undo("palettes") and p.can_undo("sequence") and not p.can_undo("segments")
        assert p.undo("palettes") and [q["name"] for q in p.options["palettes"]] == ["a"]
        assert p.options["sequence"] == {"steps": [1]}                  # the other option untouched
        assert p.redo("palettes") and [q["name"] for q in p.options["palettes"]] == ["a", "b"]
        assert p.undo("palettes") and p.undo("palettes") and "palettes" not in p.options    # back to none at all
        assert not p.undo("palettes")
        p.options["palettes"] = [{"name": "c", "stops": []}]; p.save()
        assert not p.can_redo("palettes")                                  # a new change after an undo: the redo is gone
        q = Project(os.path.join(tmp, "u"))                                # what is on disk is the latest
        assert [x["name"] for x in q.options["palettes"]] == ["c"] and not q.can_undo("palettes")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_project_zip_round_trip():
    """A project zipped and unzipped: the same files, the history and the
    export left behind, a taken name numbered, a stray zip refused."""
    from native.project import Project, zip_project, unzip_project
    from native import project as P
    tmp = tempfile.mkdtemp()
    was = P.PROJECTS
    try:
        P.PROJECTS = os.path.join(tmp, "projects")
        p = Project(os.path.join(P.PROJECTS, "zipme"))
        p.geometry = Geometry("matrix", w=16, h=8); p.options["palettes"] = [{"name": "x", "stops": []}]; p.save()
        open(os.path.join(p.path, "effects", "one.cpp"), "w").write("// one")
        os.makedirs(os.path.join(p.path, "history", "graphs", "g"), exist_ok=True)
        open(os.path.join(p.path, "history", "graphs", "g", "1.json"), "w").write("{}")
        open(os.path.join(p.path, "export", "ledmap.json"), "w").write("{}")
        z = zip_project(p, os.path.join(tmp, "zipme.zip"))
        dest = unzip_project(z)
        assert os.path.basename(dest) == "zipme_2"                         # the name was taken
        q = Project(dest)
        assert _canon(q.geometry.to_json()) == _canon(p.geometry.to_json()) and q.options["palettes"] == p.options["palettes"]
        assert open(os.path.join(dest, "effects", "one.cpp")).read() == "// one"
        assert sorted(os.listdir(os.path.join(dest, "graphs"))) == sorted(os.listdir(os.path.join(p.path, "graphs")))
        assert not os.path.exists(os.path.join(dest, "history")) and not os.path.exists(os.path.join(dest, "export", "ledmap.json"))
        import zipfile
        bad = os.path.join(tmp, "bad.zip")
        with zipfile.ZipFile(bad, "w") as zz:
            zz.writestr("readme.txt", "nothing")
        try:
            unzip_project(bad); assert False, "took a zip that is no project"
        except ValueError as e:
            assert "not a project zip" in str(e)
    finally:
        P.PROJECTS = was
        shutil.rmtree(tmp, ignore_errors=True)


def test_project_json_that_does_not_read_is_kept():
    """A project.json that does not parse - one stray comma, from a hand
    edit, a merge or a sync tool - is not wiped by the next save: a
    .bad-<time> copy keeps it byte for byte, load_error says so for the app
    to show, and the save after is written whole (issue #5)."""
    from native.project import Project
    tmp = tempfile.mkdtemp()
    try:
        p = Project(os.path.join(tmp, "p"))
        p.options = {"palettes": [{"name": "mine"}], "segments": [1, 2, 3], "sequence": ["step"]}
        p.save()
        broken = open(p.file, encoding="utf-8").read().rstrip().rstrip("}") + ",}"
        open(p.file, "w", encoding="utf-8").write(broken)
        q = Project(p.path)
        assert q.options == {} and q.load_error and "project.json.bad-" in q.load_error, q.load_error
        q.selected = "x"
        q.save()                                                           # any ordinary save
        bad = [f for f in os.listdir(p.path) if f.startswith("project.json.bad-")]
        assert len(bad) == 1, bad
        kept = open(os.path.join(p.path, bad[0]), encoding="utf-8").read()
        assert kept == broken
        assert json.loads(kept[:-2] + "}")["options"]["palettes"] == [{"name": "mine"}]
        assert json.load(open(p.file, encoding="utf-8"))["selected"] == "x"
        assert not os.path.exists(p.file + ".tmp")                          # written whole: the temporary moved over it
        r = Project(p.path)
        assert r.load_error is None and r.selected == "x"
        # not a JSON object at all: the same
        open(p.file, "w", encoding="utf-8").write("[1, 2]")
        s = Project(p.path)
        assert s.load_error and len([f for f in os.listdir(p.path) if f.startswith("project.json.bad-")]) == 2
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_project_settings_kept_in_the_history():
    """What project.json held is kept in history/project/ (File > History
    lists it): at the first save of a session, then at most every
    HISTORY_EVERY seconds - the settings are saved at every change."""
    from native.project import Project
    from native import history
    tmp = tempfile.mkdtemp()
    try:
        p = Project(os.path.join(tmp, "h"))
        p.options["palettes"] = [{"name": "a", "stops": []}]; p.save()      # keeps the new project's defaults
        p.options["palettes"] = [{"name": "b", "stops": []}]; p.save()      # too soon: not kept
        vs = history.versions(p, "project", "project")
        assert len(vs) == 1 and "palettes" not in json.load(open(vs[0][0], encoding="utf-8"))["options"]
        p._kept_at = 0.0                                                    # the interval gone by
        p.options["palettes"] = [{"name": "c", "stops": []}]; p.save()
        vs = history.versions(p, "project", "project")
        assert len(vs) == 2
        assert [x["name"] for x in json.load(open(vs[0][0], encoding="utf-8"))["options"]["palettes"]] == ["b"]
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_project_zip_keeps_to_its_folder():
    """A project zip's entries land in the project's folder or nowhere: a
    drive letter (os.path.join on Windows would drop the folder for it), an
    NTFS stream name, a climb with .. or backslashes are left out (issue #8)."""
    import ntpath
    import zipfile
    from native.project import unzip_project, _inside
    from native import project as P
    tmp = tempfile.mkdtemp()
    was = P.PROJECTS
    try:
        P.PROJECTS = os.path.join(tmp, "projects")
        z = os.path.join(tmp, "evil.zip")
        with zipfile.ZipFile(z, "w") as zz:
            zz.writestr("proj/project.json", "{}")
            zz.writestr("proj/D:/x.txt", "another drive")
            zz.writestr("proj/effects/a.cpp:ads", "a hidden stream")
            zz.writestr("proj/..\\..\\evil.txt", "a climb, Windows' way")
            zz.writestr("proj/effects/../../evil2.txt", "a climb")
            zz.writestr("proj/effects/./ok.cpp", "// fine")
        dest = unzip_project(z)
        landed = sorted(os.path.relpath(os.path.join(d, f), tmp) for d, _, fs in os.walk(tmp) for f in fs)
        want = sorted(["evil.zip", os.path.join("projects", "proj", "project.json"),
                       os.path.join("projects", "proj", "effects", "ok.cpp")])
        assert landed == want, landed
        assert os.path.basename(dest) == "proj"
        # the join the guard is there for, as Windows makes it (on any machine)
        assert ntpath.join(r"C:\studio\projects\proj", "D:", "x.txt") == "D:x.txt"
        assert _inside(dest, "D:/x.txt") is None and _inside(dest, "C:/x.txt") is None
        assert _inside(dest, "graphs/a.json") == os.path.realpath(os.path.join(dest, "graphs", "a.json"))
        assert _inside(dest, "") is None and _inside(dest, "/etc/passwd") is None and _inside(dest, "\\x") is None
    finally:
        P.PROJECTS = was
        shutil.rmtree(tmp, ignore_errors=True)


def test_sequence_presets_file_round_trip():
    """The presets.json the sequence writes is the presets and the playlist it sent."""
    from native import sequence
    steps = [{"name": f"step {i}", "dur": 5.0 + i, "trans": 0.5, "rows": 48, "colors": [0xFF0000, 0, 0],
              "segments": [{"effect": "Rainbow", "params": {"sx": 10 * i}, "bounds": [0, 0, 48, 48], "pal": 11}]} for i in range(3)]
    names = ["Solid", "Rainbow", "Scan"]
    presets, playlist = sequence.to_wled(steps, names, list(range(256)), base=20, pid=19, name="Show", repeat=0)
    d = json.loads(sequence.presets_file(presets, playlist, 19))
    assert sorted(int(k) for k in d if k != "0") == [19, 20, 21, 22]
    assert d["19"]["playlist"]["ps"] == [20, 21, 22] and d["21"]["seg"][0]["sx"] == 10
    for k, st in presets.items():
        if k is not None:
            assert d[str(k)] == st


def test_segments_round_trip():
    """The engine's segments saved and loaded back: the same bounds,
    effects, options, blend and each one's own colours."""
    from native.engine import Engine
    e = Engine(); e.set_geometry(Geometry("matrix", w=16, h=8))
    e.colors(0xFF0000, 0x00FF00, 0)
    e.seg_config(1, 2, 1, 14, 7, 160); e.seg_select(1); e.select(e.names.index("Rainbow"), params={"sx": 200, "ix": 30, "pal": 5})
    e.seg_set_options(1, rev=True, mi=True, grp=2); e.seg_blend(1, 3)
    e.colors(0x0000FF, 0, 0x112233)
    e.seg_select(0)
    segs = json.loads(json.dumps(e.segments()))
    assert segs[0]["colors"] == [0xFF0000, 0x00FF00, 0] and segs[1]["colors"] == [0x0000FF, 0, 0x112233]
    e.load_segments(segs)
    again = e.segments()
    assert len(again) == len(segs) == 2
    for a, b in zip(segs, again):
        for key in ("bounds", "effect", "opacity", "blend", "pal", "colors"):
            assert a.get(key) == b.get(key), (key, a.get(key), b.get(key))
        assert a.get("params", {}).get("sx") == b.get("params", {}).get("sx")
        assert a.get("options") == b.get("options"), (a.get("options"), b.get("options"))


def test_xmodel_round_trip():
    """A panel written as an xLights model reads back with the same LEDs in the same order."""
    tmp = tempfile.mkdtemp()
    try:
        g = Geometry("shape", parts=[shapes.new_part("panel", w=6, h=4)], layout="grid")
        path = os.path.join(tmp, "p.xmodel")
        shape_io.write_xmodel(g, path, name="Panel")
        m = shape_io.read_xmodel(path)
        assert m["grid"][0:2] == (6, 4) and len(m["order"]) == g.count == 24
        assert sorted(m["order"]) == list(range(1, 25))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_history_versions_still_open():
    """Every older graph the history keeps (projects/*/history/graphs)
    loads, migrates and compiles - the format has only grown."""
    n, bad = 0, []
    pdir = os.path.join(ROOT, "projects")
    for proj in (os.listdir(pdir) if os.path.isdir(pdir) else []):
        hdir = os.path.join(pdir, proj, "history", "graphs")
        if not os.path.isdir(hdir):
            continue
        for stem in sorted(os.listdir(hdir)):
            for fn in sorted(os.listdir(os.path.join(hdir, stem))):
                if not fn.endswith(".json"):
                    continue
                n += 1
                path = os.path.join(hdir, stem, fn)
                try:
                    g = G.load(path, lib=LIB, resolver=_resolver(os.path.join(pdir, proj)))
                    g.project_dir = os.path.join(pdir, proj)
                    g.problems()
                    if any(x["type"] == "Output" for x in g.nodes.values()):
                        g.compile()
                except G.GraphError:
                    pass                                    # the graph's own trouble (a wire, a sub-graph gone): reported, not a crash
                except Exception as e:
                    bad.append(f"{proj}/{stem}/{fn}: {type(e).__name__}: {e}")
    print(f"  {n} history version(s) opened")
    assert not bad, "\n".join(bad[:20])


def test_history_says_what_changed():
    """File > History's changes: a code effect as a diff, a graph as its
    nodes, wires and settings, the project's settings as the keys that
    differ (not the time it was saved)."""
    from native import history
    rows = history.changes("effects", "a\nb\nc\n", "a\nB\nc\nd\n")
    assert ("-", "-b") in rows and ("+", "+B") in rows and ("+", "+d") in rows, rows
    assert any(t == "@" for t, _ in rows), rows
    assert history.changes("effects", "x\n", "x\n")[0][1].startswith("no change")

    old = {"name": "g", "nodes": [{"id": 1, "type": "Time", "params": {"speed": 1.0}, "pos": [0, 0]},
                                  {"id": 2, "type": "Output", "pos": [200, 0]},
                                  {"id": 3, "type": "Noise", "pos": [100, 90]}],
           "links": [[1, "t", 2, "hue"], [3, "value", 2, "bri"]]}
    new = json.loads(json.dumps(old))
    new["nodes"][0]["params"]["speed"] = 2.5                    # a setting
    new["nodes"][1]["pos"] = [240, 10]                          # moved only
    new["nodes"] = [n for n in new["nodes"] if n["id"] != 3]    # a node gone, and its wire
    new["nodes"].append({"id": 4, "type": "Sparkle", "label": "glints", "pos": [100, 90]})
    new["links"] = [[1, "t", 2, "hue"], [4, "value", 2, "bri"]]
    rows = history.changes("graphs", json.dumps(old), json.dumps(new))
    text = "\n".join(f"{t} {l}" for t, l in rows)
    assert "~ Time #1 speed: 1.0 -> 2.5" in text, text
    assert "+ glints #4 added" in text and "- Noise #3 gone" in text, text
    assert "+ wire glints #4 value -> Output #2 bri" in text and "- wire Noise #3 value -> Output #2 bri" in text, text
    assert "1 node(s) moved" in text, text

    p_old = {"geometry": {"kind": "cube", "B": 16}, "options": {"fps": 40}, "saved": "2026-09-27 10:00:00"}
    p_new = {"geometry": {"kind": "cube", "B": 16}, "options": {"fps": 60, "gamma": 2.2}, "saved": "2026-09-27 11:00:00"}
    rows = history.changes("project", json.dumps(p_old), json.dumps(p_new))
    assert ("~", "options.fps: 40 -> 60") in rows and ("+", "options.gamma: 2.2") in rows, rows
    assert not any("saved" in l for _, l in rows), rows
    p_new = dict(p_old, saved="2026-09-27 12:00:00")
    assert history.changes("project", json.dumps(p_old), json.dumps(p_new))[0][1].startswith("no change")


if __name__ == "__main__":
    import inspect
    failed = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and inspect.isfunction(fn):
            try:
                fn(); print("ok  ", name)
            except Exception as e:
                failed += 1; print("FAIL", name, str(e)[:2000])
    sys.exit(1 if failed else 0)
