"""The compiler without the app: compile, scope, migrate, problems, arrange,
exposed params, sub-graphs. Run with  python -m pytest studio/tests  from
the WLED root, or  python -m pytest tests  from studio.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from native import graph as G                      # noqa: E402
from native.nodedefs import library                # noqa: E402
from native.geometry import Geometry               # noqa: E402

LIB = library()


def starter():
    g = G.Graph({"name": "t"}, lib=LIB)
    return g


def test_library_is_documented():
    from native import nodedocs
    assert nodedocs.gaps() == []


def test_minimal_graph_compiles():
    g = starter()
    c = g.add("Coords", (0, 0)); n = g.add("Noise", (100, 0)); p = g.add("Palette", (200, 0)); o = g.add("Output", (300, 0))
    g.link(c, "u", n, "x"); g.link(c, "v", n, "y")
    g.link(n, LIB["Noise"]["outputs"][0]["name"], p, "index"); g.link(p, "color", o, "color")
    src = g.compile()
    assert "cube_fx_bank.h" in src and "SEGMENT" in src
    assert "gc_st_fallback" not in src or "static float gc_st_fallback[" in src


def test_frame_scope_hoists_slider_maths():
    g = starter()
    a = g.add("Speed", (0, 0)); b = g.add("Intensity", (0, 100)); m = g.add("Multiply", (100, 0))
    p = g.add("Palette", (200, 0)); o = g.add("Output", (300, 0))
    g.link(a, "value", m, "a"); g.link(b, "value", m, "b"); g.link(m, "result", p, "index"); g.link(p, "color", o, "color")
    src = g.compile()
    frame, pixel = src.index("frame scope"), src.index("per pixel")
    assert frame < src.index(f"n{m}_result =") < pixel


def test_type_rule():
    assert G.compatible("float", "float") and G.compatible("bool", "float") and G.compatible("float", "bool")
    assert G.compatible("color", "vector") and G.compatible("vector", "color")
    assert not G.compatible("color", "float")


def test_problems_flag_missing_output():
    g = starter()
    g.add("Noise", (0, 0))
    probs = g.problems()
    assert probs, "a graph with no Output is a problem"


def test_bad_and_stray_wires():
    """A wire between types that do not convert is an error on the node it
    lands on, and the compile names both ends; a wire to a node or a pin
    that is not there (a hand-edited file) is dropped on load and listed."""
    g = starter()
    c = g.add("Coords", (0, 0)); p = g.add("Palette", (200, 0)); o = g.add("Output", (300, 0)); q = g.add("Colour 1", (0, 100))
    g.link(c, "u", p, "index"); g.link(p, "color", o, "color")
    g.links.append((q, "color", p, "brightness"))
    assert "cannot take a color" in g.problems().get(p, "")
    try:
        g.compile(); assert False, "compiled a colour into a number"
    except G.GraphError as e:
        assert "Palette" in str(e) and "Colour 1" in str(e)
    d = g.to_json(); d["links"] = [l for l in d["links"] if l[0] != q]
    d["links"] += [[999, "x", p, "brightness"], [c, "nope", p, "brightness"], [c, "u", p, "nope"]]
    g2 = G.Graph(d, lib=LIB)
    assert len(g2.stray) == 3 and p not in g2.problems() and "SEGMENT" in g2.compile()


def test_wired_input_is_required():
    """Sprites reads the Particles' state through its slots pin: unwired,
    it is a problem on the node and a refusal to compile, not a C++ error."""
    g = starter()
    s = g.add("Sprites", (0, 0)); p = g.add("Palette", (200, 0)); o = g.add("Output", (300, 0))
    g.link(s, "value", p, "index"); g.link(p, "color", o, "color")
    assert "must be wired" in g.problems().get(s, "")
    try:
        g.compile(); assert False, "compiled without its slots"
    except G.GraphError as e:
        assert "slots" in str(e)
    q = g.add("Particles", (-200, 0)); g.link(q, "slots", s, "slots")
    assert s not in g.problems() and "SEGMENT" in g.compile()


def test_exposed_param_becomes_a_pin_and_compiles():
    g = starter()
    c = g.add("Coords", (0, 0)); n = g.add("Noise", (100, 0)); p = g.add("Palette", (200, 0)); o = g.add("Output", (300, 0))
    name = G.exposable(LIB["Noise"])[0]
    g.nodes[n]["expose"] = [name]
    d = g.node_def(g.nodes[n])
    assert name in [i["name"] for i in d["inputs"]] and name not in [q["name"] for q in d["params"]]
    g.link(c, "u", n, "x"); g.link(n, d["outputs"][0]["name"], p, "index"); g.link(p, "color", o, "color")
    assert "SEGMENT" in g.compile()


def test_big_state_has_no_static_fallback():
    g = starter()
    c = g.add("Coords", (0, 0)); r = g.add("Reaction diffusion", (100, 0)); p = g.add("Palette", (200, 0)); o = g.add("Output", (300, 0))
    g.link(c, "u", r, "u"); g.link(c, "v", r, "v"); g.link(r, "v", p, "index"); g.link(p, "color", o, "color")
    src = g.compile()
    assert "gc_st_fallback" not in src and "no room for the state" in src


def test_arrange_spreads_by_depth():
    g = starter()
    a = g.add("Coords", (0, 0)); b = g.add("Noise", (0, 0)); p = g.add("Palette", (0, 0)); o = g.add("Output", (0, 0))
    g.link(a, "u", b, "x"); g.link(b, LIB["Noise"]["outputs"][0]["name"], p, "index"); g.link(p, "color", o, "color")
    g.arrange()
    xs = [g.nodes[i]["pos"][0] for i in (a, b, p, o)]
    assert xs == sorted(xs) and len(set(xs)) == 4


def test_to_json_roundtrip_keeps_wire_meta_and_expose():
    g = starter()
    a = g.add("Coords", (0, 0)); n = g.add("Noise", (100, 0))
    g.link(a, "u", n, "x")
    g.link_meta[(n, "x")] = {"color": [1, 2, 3], "label": "hi"}
    g.nodes[n]["expose"] = [G.exposable(LIB["Noise"])[0]]
    g2 = G.migrate(G.Graph(g.to_json(), lib=LIB))
    assert g2.link_meta[(n, "x")]["label"] == "hi" and g2.nodes[n]["expose"] == g.nodes[n]["expose"]


def test_ledmap_is_the_firmwares_format():
    g = Geometry("cube", B=4)
    m = g.ledmap()
    assert len(m["map"]) == 144 and sum(1 for v in m["map"] if v >= 0) == 80 and m["width"] == 12
    back = Geometry.from_ledmap(m, "t")
    assert (back.phys == g.phys).all()
    wired = Geometry("cube", B=4, faces="T,N,E,S,W", rots="1,0,0,0,0", serpentine=True)
    assert len(set(wired.phys.tolist())) == 80


def test_script_compiles_and_folds_choices():
    from native.script import compile_script, MAGIC
    g = starter()
    c = g.add("Coords", (0, 0)); w = g.add("Wave", (100, 0)); p = g.add("Palette", (200, 0)); o = g.add("Output", (300, 0))
    g.nodes[w]["params"]["shape"] = "triangle"
    g.link(c, "u", w, "x"); g.link(w, "value", p, "index"); g.link(p, "color", o, "color")
    prog = compile_script(g)
    assert prog[:4] == MAGIC and len(prog) > 40


def test_script_parses_static_declarations_and_hex():
    """Two things the xLights example graphs tripped: `static uint16_t x`
    (two type words after static) looped the parser for ever, and
    `0xFFFFu` lost its F digits to the suffix strip."""
    from native.script import tokenize, Parser
    toks = tokenize("{ static uint16_t owed_ = 0; static float acc_ = 0.0f; uint32_t k = 0xFFFFu; }")
    tree = Parser(toks).block()
    assert tree
    nums = [t[1] for t in toks if t[0] == "num"]
    assert 65535.0 in nums


def test_script_lowers_a_curve_first():
    """A Float curve as the first node lowered used to read a name (`env`)
    that only a code node before it would have bound: a NameError, not a
    ScriptError, out of the compiler."""
    from native.script import compile_script, MAGIC
    g = starter()
    f = g.add("Float curve", (100, 0)); p = g.add("Palette", (200, 0)); o = g.add("Output", (300, 0))
    g.link(f, "result", p, "index"); g.link(p, "color", o, "color")     # nothing with code before the curve
    prog = compile_script(g)
    assert prog[:4] == MAGIC


def test_script_names_the_unscriptable_node():
    from native.script import compile_script, ScriptError
    g = starter()
    c = g.add("Coords", (0, 0)); f = g.add("Field", (100, 0)); p = g.add("Palette", (200, 0)); o = g.add("Output", (300, 0))
    g.link(c, "u", f, "u"); g.link(c, "v", f, "v"); g.link(f, "value", p, "index"); g.link(p, "color", o, "color")
    try:
        compile_script(g)
        assert False, "Field should not be scriptable"
    except ScriptError as e:
        assert "Field" in str(e)


def test_segment_blend_modes_follow_the_firmware():
    """Lighten is max, darken min, subtract bottom minus top; the sim's
    compositor is a transcription of blendSegment()."""
    import numpy as np
    from native.engine import Engine
    eng = Engine(); eng.set_geometry(Geometry("matrix", w=16, h=8))
    a = next(i for i, n in enumerate(eng.names) if "Axes" in n)
    b = eng.names.index("Solid Pattern")
    eng.seg_config(1, 0, 0, 16, 8, 255); eng.seg_select(1); eng.select(b, params={"sx": 255, "ix": 0})
    eng.colors(0x4080C0, 0x4080C0, 0x4080C0); eng.seg_select(0); eng.select(a)
    res = {}
    for mode in (0, 1, 3, 8, 9):
        eng.seg_blend(1, mode)
        for _ in range(2): eng.frame(28)
        res[mode] = eng.rgb().astype(int)
    top, bot = res[0], res[1]
    assert (np.abs(res[8] - np.maximum(top, bot)) <= 1).all()
    assert (np.abs(res[9] - np.minimum(top, bot)) <= 1).all()
    assert (np.abs(res[3] - np.clip(bot - top, 0, 255)) <= 1).all()


def test_segment_options_follow_the_firmware():
    """WLED's segment options in the sim: reverse mirrors the strip, offset
    rolls it, grouping and spacing make their pattern, and on a matrix
    reverse Y flips the rows; they travel with segments() for the presets."""
    from native.engine import Engine
    e = Engine(); e.set_geometry(Geometry("matrix", w=16, h=1))
    k = e.names.index("Solid Pattern")
    def run(**opt):
        e.seg_set_options(0, **dict(dict(rev=False, mi=False, rY=False, mY=False, tp=False, grp=1, spc=0, of=0), **opt))
        e.select(k, params={"sx": 3, "ix": 5}); e.colors(0xFF0000, 0x0000FF, 0)
        for _ in range(3): e.frame(28)
        return "".join("R" if p[0] > 0 else ("B" if p[2] > 0 else ".") for p in e.rgb()[0])
    base = run()
    assert run(rev=True) == base[::-1]
    assert run(of=3) == base[-3:] + base[:-3]
    assert run(grp=2, spc=1).startswith("RR.RR.")
    assert e.segments()[0]["options"]["grp"] == 2
    e.set_geometry(Geometry("matrix", w=8, h=4))
    def rows(**opt):
        e.seg_set_options(0, **dict(dict(rev=False, mi=False, rY=False, mY=False, tp=False, grp=1, spc=0, of=0), **opt))
        e.select(k, params={"sx": 3, "ix": 5}); e.colors(0xFF0000, 0x0000FF, 0)
        for _ in range(3): e.frame(28)
        return ["".join("R" if p[0] > 0 else "B" for p in row) for row in e.rgb()]
    assert rows(rY=True) == rows()[::-1]


if __name__ == "__main__":                        # without pytest: every test_ function, in order
    import inspect
    bad = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and inspect.isfunction(fn):
            try:
                fn(); print("ok  ", name)
            except Exception as e:
                bad += 1; print("FAIL", name, repr(e))
    sys.exit(1 if bad else 0)
