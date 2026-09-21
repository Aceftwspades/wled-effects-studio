"""The node census: every node in the library, alone in a minimal graph,
compiled to C++, that C++ built by the toolchain into one engine, each
effect run for a moment; then the same graphs through the script compiler
and the Studio Script effect, for those the script subset can express.
A node that cannot be added, compiled, built or run fails the census by
name. Run with  python tests/test_nodes.py  (or pytest); a minute or two,
mostly the build.
"""
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from native import graph as G                      # noqa: E402
from native.nodedefs import library                # noqa: E402

LIB = library()
OUT = os.path.join(ROOT, "build", "census")

# structural nodes: nothing to compute, or only meaningful inside a sub-graph
STRUCTURAL = {"Output", "Effect settings", "Note", "Frame", "Graph input", "Graph output"}
# nodes whose C++ is expected to be missing something at the defaults, and why
KNOWN = {}


def census_graph(name, d):
    """`name` alone, every output of it reaching the Output: floats (and
    bools) summed into one Palette index, vectors through Vector split,
    colours blended over that palette colour. An input that must be wired
    (Sprites' slots) gets the node it names."""
    g = G.Graph({"name": "Census " + name}, lib=LIB)
    g.project_dir = os.path.join(ROOT, "examples")
    n = g.add(name, (0, 0))
    if d.get("wired"):
        pin, src = d["wired"]
        s = g.add(src.split()[0], (-260, 0)); g.link(s, "slots", n, pin)
    fl, col = None, None                                  # the float fold, the colour fold
    x = 260
    for o in d["outputs"]:
        src, pin = n, o["name"]
        if o["type"] == "color":
            if col is None:
                col = (n, pin)
            else:
                b = g.add("Blend", (x, 100)); g.link(col[0], col[1], b, "under"); g.link(n, pin, b, "over"); col = (b, "color"); x += 200
            continue
        if o["type"] == "vector":
            s = g.add("Vector split", (x, 0)); g.link(n, o["name"], s, "v"); src, pin = s, "x"; x += 200
        if fl is None:
            fl = (src, pin)
        else:
            a = g.add("Add", (x, 0)); g.link(fl[0], fl[1], a, "a"); g.link(src, pin, a, "b"); fl = (a, "result"); x += 200
    if not d["outputs"]:                                  # a sink (Field write): fed from the coordinates, and read back
        c = g.add("Coords", (-260, 0))
        if d["inputs"]:
            g.link(c, "u", n, d["inputs"][0]["name"])
        if name == "Field write":
            f = g.add("Field", (x, 0)); fl = (f, "value"); x += 200
        else:
            fl = (c, "u")
    p = g.add("Palette", (x, 0)); x += 200
    if fl is not None:
        g.link(fl[0], fl[1], p, "index")
    last = (p, "color")
    if col is not None:
        b = g.add("Blend", (x, 0)); g.link(p, "color", b, "under"); g.link(col[0], col[1], b, "over"); last = (b, "color"); x += 200
    o = g.add("Output", (x, 0)); g.link(last[0], last[1], o, "color")
    return g


def graphs():
    return {name: census_graph(name, d) for name, d in LIB.items() if name not in STRUCTURAL}


def test_every_node_compiles_to_cpp():
    bad = []
    for name, g in graphs().items():
        try:
            src = g.compile()
            probs = g.problems()
            if probs:
                bad.append(f"{name}: problems {probs}")
            elif "SEGMENT" not in src:
                bad.append(f"{name}: no segment code")
        except Exception as e:
            bad.append(f"{name}: {type(e).__name__}: {e}")
    assert not bad, "\n".join(bad)


def _build(gs=None):
    """One engine with every census effect in it (or the graphs given -
    the parity test adds the examples). The roster holds 256:
    the census's come first (the stock effects are registered on demand,
    after), so it is the tail of the stock 1-D list that is left off.
    build/latest is left alone: the app, and the other tests, keep the
    engine they had."""
    import build as B
    from native.toolchain import build_engine
    os.makedirs(OUT, exist_ok=True)
    srcs = []
    gs = graphs() if gs is None else gs
    for name, g in gs.items():
        p = os.path.join(OUT, "".join(ch if ch.isalnum() else "_" for ch in name) + ".cpp")
        open(p, "w", encoding="utf-8", newline="\n").write(g.compile())
        srcs.append(p)
    rep = build_engine(B.engine_sources(srcs, log=lambda *a: None), B.include_dirs(), log=lambda *a: None, point_latest=False)
    return gs, rep


def test_every_node_builds_and_runs():
    """One engine of them all; each effect selected and run for 40 frames
    with the fake audio - the build's errors named by node, a crash by the
    effect that was running."""
    import numpy as np
    from native.engine import Engine
    from native.synth import Synth
    t0 = time.time()
    gs, rep = _build()
    if not rep.ok:
        errs = [f"{os.path.basename(e[0])}:{e[1]} {e[2]}" for e in rep.error_lines() if e[2].startswith("error")]
        assert False, "the build failed:\n" + "\n".join(errs[:40]) + "\n" + rep.link_output[-600:]
    print(f"  built {len(gs)} effects in {time.time() - t0:.0f} s")
    e = Engine(); e.load(rep.library)
    missing = [g.name for g in gs.values() if g.name not in e.names]
    assert not missing, f"built but not in the roster: {missing}"
    dark = []
    for name, g in gs.items():
        e.select(e.names.index(g.name))
        syn = Synth()
        for _ in range(40):
            syn.push(e); e.frame()
        rgb = np.asarray(e.rgb())
        assert rgb.shape[-1] == 3 and rgb.dtype == np.uint8, name
        if not (rgb.max(axis=2) > 8).any():
            dark.append(name)
    # a node at its defaults may well be black (a zero, an empty slot); noted, not failed
    print(f"  dark at the defaults: {', '.join(dark) or 'none'}")


def test_live_parameters_poke_the_running_effect():
    """A typed input compiles as a table read; the studio pokes the table
    of the running effect and the picture changes with no rebuild; an
    effect that has not run yet has no table bound and says so."""
    import numpy as np
    from native.engine import Engine
    g = G.Graph({"name": "Census live probe"}, lib=LIB)
    c = g.add("Coords", (0, 0)); m = g.add("Multiply", (100, 0)); p = g.add("Palette", (200, 0)); o = g.add("Output", (300, 0))
    g.link(c, "u", m, "a"); g.link(m, "result", p, "index"); g.link(p, "color", o, "color")
    g.nodes[m]["inputs"] = {"b": 1.0}
    src = g.compile()
    assert "GC_PARAM_TABLE float gc_param[" in src and (m, "b", None) in {v: k for k, v in g.live.items()}
    slot = next(k for k, v in g.live.items() if v == (m, "b", None))
    gs, rep = _build({"live": g})
    assert rep.ok, rep.link_output[-600:]
    e = Engine(); e.load(rep.library)
    idx = e.names.index(g.name)
    assert not e.param_set(idx, slot, 0.5)                   # not run yet: no table bound
    e.select(idx)
    for _ in range(3):
        e.frame()
    before = np.asarray(e.rgb()).copy()
    assert e.param_set(idx, slot, 0.0)                       # index = u * 0: one colour everywhere
    for _ in range(3):
        e.frame()
    after = np.asarray(e.rgb())
    lit = np.asarray(e.lit_mask(), bool)
    assert not np.array_equal(before, after)
    assert len({tuple(px) for px in after[lit]}) == 1 and len({tuple(px) for px in before[lit]}) > 1


def test_tempo_follows_the_synth():
    """A Tempo fed by Audio's beat measures the synth's bpm within a few
    percent after ten seconds of beats, and its bar phase runs 0..1 over
    four beats."""
    from native.engine import Engine
    from native.synth import Synth
    g = G.Graph({"name": "Census tempo probe"}, lib=LIB)
    a = g.add("Audio", (0, 0)); tp = g.add("Tempo", (200, 0)); p = g.add("Palette", (400, 0)); o = g.add("Output", (600, 0))
    g.link(a, "beat", tp, "beat"); g.link(tp, "bar", p, "index"); g.link(p, "color", o, "color")
    g.compile()
    slot_bpm = next(k for k, v in g.probes.items() if v == (tp, "bpm"))
    slot_bar = next(k for k, v in g.probes.items() if v == (tp, "bar"))
    gs, rep = _build({"tempo": g})
    assert rep.ok, rep.link_output[-600:]
    e = Engine(); e.load(rep.library)
    e.select(e.names.index(g.name))
    syn = Synth(bpm=132)
    bars = []
    for _ in range(int(10.0 / 0.023)):
        syn.push(e); e.frame()
        bars.append(e.probe(slot_bar))
    bpm = e.probe(slot_bpm)
    assert abs(bpm - 132) < 132 * 0.05, bpm
    assert min(bars[-100:]) < 0.1 and max(bars[-100:]) > 0.9         # the bar phase sweeps 0..1


def test_every_node_scripts_or_says_why():
    """The script compiler takes each graph or refuses it as a ScriptError
    (never anything else); what it takes runs in the Script effect."""
    from native.script import compile_script, settings_of, ScriptError
    from native.engine import Engine
    from native.synth import Synth
    from native.toolchain import latest_library
    e = Engine(); e.load(latest_library())
    si = e.script_effect()
    assert si is not None, "the engine has no Studio Script effect"
    took, refused, bad = [], [], []
    for name, g in graphs().items():
        try:
            prog = compile_script(g)
        except ScriptError as ex:
            refused.append(f"{name} ({str(ex)[:50]})"); continue
        except Exception as ex:
            bad.append(f"{name}: {type(ex).__name__}: {ex}"); continue
        if not e.script(prog):
            bad.append(f"{name}: the engine did not take the script"); continue
        st = settings_of(g); pal = st.pop("pal")
        e.select(si, params=dict(st, pal=pal))
        syn = Synth()
        for _ in range(30):
            syn.push(e); e.frame(28)
        took.append(name)
    print(f"  scripted {len(took)}, refused {len(refused)}: {', '.join(refused)}")
    assert not bad, "\n".join(bad)
    assert len(took) >= 60, "the script subset shrank"


if __name__ == "__main__":
    import inspect
    bad = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and inspect.isfunction(fn):
            try:
                fn(); print("ok  ", name)
            except Exception as ex:
                bad += 1; print("FAIL", name, str(ex)[:3000])
    sys.exit(1 if bad else 0)
