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
    effects, options and blend."""
    from native.engine import Engine
    e = Engine(); e.set_geometry(Geometry("matrix", w=16, h=8))
    e.seg_config(1, 2, 1, 14, 7, 160); e.seg_select(1); e.select(e.names.index("Rainbow"), params={"sx": 200, "ix": 30, "pal": 5})
    e.seg_set_options(1, rev=True, mi=True, grp=2); e.seg_blend(1, 3)
    e.seg_select(0)
    segs = json.loads(json.dumps(e.segments()))
    e.load_segments(segs)
    again = e.segments()
    assert len(again) == len(segs) == 2
    for a, b in zip(segs, again):
        for key in ("bounds", "effect", "opacity", "blend", "pal"):
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
