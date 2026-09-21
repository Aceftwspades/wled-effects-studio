"""Script / C++ parity: the same graph as its compiled effect and as the
Studio Script effect's bytecode, run in the same engine from the same
reset with the same fake audio, frame by frame; a graph whose two
renderings drift apart names a divergence between the script compiler
or the VM and the C++ templates. Over the node census's graphs and the
scriptable examples. Run with  python tests/test_parity.py  (or pytest).
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)

from native import graph as G                      # noqa: E402

FRAMES = 40
MEAN_MAX = 4.0          # mean absolute difference over the frame, 0..255
FRAC_MAX = 0.06         # share of pixels off by more than 24 in a channel


def _graphs():
    import test_nodes as T
    gs = dict(T.graphs())
    ex = os.path.join(ROOT, "examples", "graphs")
    for fn in sorted(os.listdir(ex)):
        g = G.load(os.path.join(ex, fn)); g.project_dir = os.path.join(ROOT, "examples")
        gs["example " + fn] = g
    return gs


def is_random(g):
    """A graph with a node that draws random numbers: its two sides differ
    by design (the VM's generator is not the firmware's), so it is run,
    but its distance is not judged."""
    import re
    for n in g.nodes.values():
        try:
            code = g.node_def(n).get("code", "")
        except Exception:
            continue
        if re.search(r"gc_rnd|random8|random16|hw_random|random\(", code):
            return True
    return False


def compare(e, si, g, prog, frames=FRAMES):
    """(mean abs diff, fraction of pixels far off) over the last ten frames of both runs."""
    import numpy as np
    from native.synth import Synth
    from native.script import settings_of

    def run(select):
        # a warm-up frame that lands the clock on 0, so the effect's own dt store
        # (fx_dt8's static) reads 23 ms on the first real frame on both sides - a
        # fresh store, or one left by an earlier run, would give 250
        select(); e.set_now(2 ** 32 - 23); e.frame()
        select(); e.set_now(0)
        syn = Synth(); out = []
        for k in range(frames):
            syn.push(e); e.frame()
            if k >= frames - 10:
                out.append(np.asarray(e.rgb()).astype(int))
        return out
    a = run(lambda: e.select(e.names.index(g.name)))
    st = settings_of(g); pal = st.pop("pal")
    b = run(lambda: (e.script(prog), e.select(si, params=dict(st, pal=pal))))
    mean = float(np.mean([np.abs(x - y).mean() for x, y in zip(a, b)]))
    frac = float(np.mean([(np.abs(x - y).max(axis=2) > 24).mean() for x, y in zip(a, b)]))
    return mean, frac


def test_script_matches_cpp():
    import test_nodes as T
    from native.engine import Engine
    from native.script import compile_script, ScriptError
    gs = _graphs()
    gs, rep = T._build(gs)
    assert rep.ok, "the build failed: " + rep.link_output[-600:]
    e = Engine(); e.load(rep.library)
    si = e.script_effect()
    assert si is not None
    rows, bad = [], []
    for name, g in gs.items():
        if g.name not in e.names:
            bad.append(f"{name}: not in the roster"); continue
        try:
            prog = compile_script(g)
        except ScriptError:
            continue
        mean, frac = compare(e, si, g, prog)
        rows.append((name + (" (random)" if is_random(g) else ""), mean, frac))
        if is_random(g):
            continue
        if mean > MEAN_MAX or frac > FRAC_MAX:
            bad.append(f"{name}: mean {mean:.2f}, {frac * 100:.1f}% of pixels far off")
    rows.sort(key=lambda r: -r[1])
    print(f"  {len(rows)} graphs compared; the widest apart:")
    for name, mean, frac in rows[:12]:
        print(f"    {name:34s} mean {mean:6.2f}  far {frac * 100:5.1f}%")
    assert not bad, "\n".join(bad)


if __name__ == "__main__":
    import inspect
    failed = 0
    for n, fn in list(globals().items()):
        if n.startswith("test_") and inspect.isfunction(fn):
            try:
                fn(); print("ok  ", n)
            except Exception as ex:
                failed += 1; print("FAIL", n, str(ex)[:3000])
    sys.exit(1 if failed else 0)
