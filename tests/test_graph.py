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
