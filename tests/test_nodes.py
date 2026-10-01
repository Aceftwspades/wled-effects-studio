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
STRUCTURAL = {"Output", "Effect settings", "Note", "Frame", "Scope", "Graph input", "Graph output",
              "Send", "Receive", "Send colour", "Receive colour"}        # the pairs: test_graph joins them
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


def test_a_colour_is_poked_live():
    """A typed colour compiles as three table reads (since 1.4.0, where it
    was a literal and a picked colour rebuilt the effect): poked on the
    running effect, the picture takes it with no rebuild."""
    import numpy as np
    from native.engine import Engine
    g = G.Graph({"name": "Census live colour"}, lib=LIB)
    o = g.add("Output", (0, 0))
    g.nodes[o]["inputs"] = {"color": [255, 0, 0]}
    g.compile()
    slots = {v[2]: k for k, v in g.live.items() if v[:2] == (o, "color")}
    assert set(slots) == {0, 1, 2} and [g.live_init[slots[j]] for j in range(3)] == [255.0, 0.0, 0.0]
    gs, rep = _build({"livecol": g})
    assert rep.ok, rep.link_output[-600:]
    e = Engine(); e.load(rep.library)
    idx = e.names.index(g.name)
    e.select(idx)
    for _ in range(3):
        e.frame()
    lit = np.asarray(e.lit_mask(), bool)
    px = np.asarray(e.rgb())[lit].astype(int)
    assert len(px) and (px[:, 0] > 0).all() and (px[:, 1:] == 0).all()          # red
    for j, c in enumerate((0, 0, 255)):
        assert e.param_set(idx, slots[j], float(c))
    for _ in range(3):
        e.frame()
    lit = np.asarray(e.lit_mask(), bool)
    px = np.asarray(e.rgb())[lit].astype(int)
    assert len(px) and (px[:, 2] > 0).all() and (px[:, :2] == 0).all()          # blue, no rebuild


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


def kit_graph(summed=False):
    """The control kit on one clock: a 2 Hz square made of the time (fract of t x 2 over a
    Threshold at 0.5) fires ADSR, Counter, Hold and Toggle's flip and moves a Slew; the
    saw under it (fract of t x 2) feeds a Gate and a Peak hold. Every node runs whether it
    reaches the Output or not. `summed`: every output added into the palette's index
    instead (the parity test compares colours). Returns the graph and its nodes by name."""
    g = G.Graph({"name": "Census control kit" + (", summed" if summed else "")}, lib=LIB)
    k = {}
    k["t"] = g.add("Time", (0, 0))
    k["m2"] = g.add("Math", (150, 0), {"op": "multiply"}); g.link(k["t"], "t", k["m2"], "a"); g.nodes[k["m2"]]["inputs"] = {"b": 2.0}
    k["saw"] = g.add("Math", (300, 0), {"op": "fract"}); g.link(k["m2"], "result", k["saw"], "a")
    k["sq"] = g.add("Threshold", (450, 0)); g.link(k["saw"], "result", k["sq"], "x"); g.nodes[k["sq"]]["inputs"] = {"at": 0.5}
    k["adsr"] = g.add("ADSR", (600, 0)); g.link(k["sq"], "on", k["adsr"], "gate")
    g.nodes[k["adsr"]]["inputs"] = {"attack": 40.0, "decay": 160.0}
    k["held"] = g.add("ADSR", (600, 700), {"mode": "held"}); g.link(k["sq"], "on", k["held"], "gate")
    g.nodes[k["held"]]["inputs"] = {"attack": 40.0, "decay": 80.0, "sustain": 0.5, "release": 100.0}
    k["gate"] = g.add("Gate", (600, 100)); g.link(k["saw"], "result", k["gate"], "x")
    g.nodes[k["gate"]]["inputs"] = {"high": 0.7, "low": 0.3}
    k["count"] = g.add("Counter", (600, 200)); g.link(k["sq"], "on", k["count"], "trigger")
    k["hold"] = g.add("Hold", (600, 300)); g.link(k["t"], "t", k["hold"], "x"); g.link(k["sq"], "on", k["hold"], "trigger")
    k["peak"] = g.add("Peak hold", (600, 400)); g.link(k["saw"], "result", k["peak"], "x")
    g.nodes[k["peak"]]["inputs"] = {"hold": 100.0, "fall": 2.0}
    k["slew"] = g.add("Slew", (600, 500)); g.link(k["sq"], "value", k["slew"], "x")
    g.nodes[k["slew"]]["inputs"] = {"up": 4.0, "down": 2.0}
    k["flip"] = g.add("Toggle", (600, 600), {"on": False}); g.link(k["sq"], "on", k["flip"], "flip")
    p = g.add("Palette", (800, 0)); o = g.add("Output", (1000, 0))
    if not summed:
        g.link(k["count"], "phase", p, "index")
    else:
        outs = [("adsr", "value"), ("held", "value"), ("gate", "value"), ("count", "phase"), ("hold", "value"),
                ("peak", "value"), ("slew", "value"), ("flip", "on"), ("count", "wrap"), ("gate", "rise")]
        acc = outs[0]
        acc = (k[acc[0]], acc[1])
        for x, (name, out) in enumerate(outs[1:]):
            a = g.add("Add", (700, 800 + 60 * x)); g.link(acc[0], acc[1], a, "a"); g.link(k[name], out, a, "b"); acc = (a, "result")
        f = g.add("Math", (760, 0), {"op": "fract"}); g.link(acc[0], acc[1], f, "a")
        g.link(f, "result", p, "index")
    g.link(p, "color", o, "color")
    return g, k


def test_the_control_kit_behaves():
    """ADSR (one shot and held), Gate, Counter, Hold, Peak hold, Slew and Toggle's flip, built
    and run on the kit graph's 2 Hz square, their outputs read back each frame (20 ms)."""
    from native.engine import Engine
    g, k = kit_graph()
    g.compile()
    slot = {v: key for key, v in g.probes.items()}
    gs, rep = _build({"kit": g})
    assert rep.ok, rep.link_output[-600:]
    e = Engine(); e.load(rep.library)
    e.set_now(0)
    e.select(e.names.index(g.name))
    rows = []
    for _ in range(150):                                  # 3 s
        e.frame(20)
        rows.append({v: e.probe(key) for v, key in slot.items()})

    def col(node, out):
        return [r[(k[node], out)] for r in rows]
    sq, saw = col("sq", "value"), col("saw", "result")
    rises = [i for i in range(1, len(sq)) if sq[i] > 0.5 and sq[i - 1] < 0.5]
    assert len(rises) >= 5, rises                         # twice a second
    # Counter: one more on each rise, back to 0 (and wrap) on the fourth
    count, wrap = col("count", "count"), col("count", "wrap")
    for i in rises:
        assert count[i] == (count[i - 1] + 1) % 4, (i, count[i - 1], count[i])
        assert (wrap[i] > 0.5) == (count[i] == 0), (i, count[i], wrap[i])
    assert sum(w > 0.5 for w in wrap) == sum(count[i] == 0 for i in rises)
    # Toggle: flipped on every rise, steady between
    flip = col("flip", "on")
    for a, b in zip(rises, rises[1:]):
        assert flip[a] != flip[a - 1] and len(set(flip[a:b])) == 1
    # Hold: the time as it was at the last rise, the whole way to the next
    hold, t = col("hold", "value"), col("t", "t")
    for a, b in zip(rises, rises[1:]):
        assert all(abs(h - t[a]) < 1e-3 for h in hold[a:b]), (a, hold[a:b][:3], t[a])
    # ADSR one shot: at 1 by the rise's second frame (40 ms attack, 20 ms frames), back to 0 in 160 ms more
    adsr = col("adsr", "value")
    for i in rises[:-1]:
        assert adsr[i] > 0.4 and max(adsr[i:i + 2]) > 0.99, adsr[i:i + 4]
        assert adsr[i + 2] < 1.0 and adsr[i + 10] < 0.01, adsr[i:i + 12]
    # ADSR held: at the sustain while the square is on, released to 0 before the next rise
    held = col("held", "value")
    for a, b in zip(rises, rises[1:]):
        on = [j for j in range(a, b) if sq[j] > 0.5]
        assert abs(held[on[-1]] - 0.5) < 1e-3, held[a:b]
        assert held[b - 1] < 0.01, held[a:b]
    # Gate: on once the saw passes 0.7, off once it falls below 0.3 - never at 0.5 alone
    gate = col("gate", "on")
    for i in range(1, len(gate)):
        if gate[i] > 0.5 and gate[i - 1] < 0.5:
            assert saw[i] >= 0.7
        if gate[i] < 0.5 and gate[i - 1] > 0.5:
            assert saw[i] <= 0.3
    # Peak hold: never under the saw; after the saw drops it holds, then falls 2 a second
    peak = col("peak", "value")
    assert all(pk >= s - 1e-6 for pk, s in zip(peak, saw))
    drops = [i for i in range(1, len(saw)) if saw[i] < saw[i - 1] - 0.5]
    assert drops
    i = drops[0]
    assert abs(peak[i + 3] - peak[i - 1]) < 1e-6                             # held for 100 ms
    assert abs((peak[i + 8] - peak[i + 9]) - 2.0 * 0.02) < 1e-3              # then 2 a second, 20 ms a frame
    # Slew: never more than 4 a second up (0.08 a frame) or 2 down (0.04)
    slew = col("slew", "value")
    for a, b in zip(slew, slew[1:]):
        assert -0.04 - 1e-4 <= b - a <= 0.08 + 1e-4, (a, b)
    assert max(slew) > 0.99 and min(slew[40:]) < 0.5


def test_the_sound_nodes_read_what_they_hear():
    """Waveform, Notes, Onset, Timbre, Silence and Spectrum history, built, fed through the
    engine's audio slots as the studio feeds them (the PCM, the pitch classes, the bands, the
    volume) and read back through the probes."""
    import numpy as np
    from native.engine import Engine
    g = G.Graph({"name": "Census sound"}, lib=LIB)
    k = {}
    k["wave"] = g.add("Waveform", (0, 0)); g.nodes[k["wave"]]["inputs"] = {"index": 0.25}
    k["notes"] = g.add("Notes", (0, 150), {"smooth": 0.0}); g.nodes[k["notes"]]["inputs"] = {"index": 7.5 / 12.0}
    k["onset"] = g.add("Onset", (0, 300))
    k["timbre"] = g.add("Timbre", (0, 450))
    k["quiet"] = g.add("Silence", (0, 600)); g.nodes[k["quiet"]]["inputs"] = {"threshold": 0.05, "hold": 0.2, "fade": 0.2}
    k["hist"] = g.add("Spectrum history", (0, 750)); g.nodes[k["hist"]]["inputs"] = {"index": 0.0, "age": 0.0}
    k["old"] = g.add("Spectrum history", (0, 900)); g.nodes[k["old"]]["inputs"] = {"index": 0.0, "age": 1.0}
    p = g.add("Palette", (300, 0)); o = g.add("Output", (500, 0))
    g.link(k["timbre"], "brightness", p, "index"); g.link(p, "color", o, "color")
    g.compile()
    slot = {v: key for key, v in g.probes.items()}
    gs, rep = _build({"sound": g})
    assert rep.ok, rep.link_output[-600:]
    e = Engine(); e.load(rep.library)
    e.set_now(0)
    e.select(e.names.index(g.name))

    def read(node, out):
        return e.probe(slot[(k[node], out)])

    def bands(v):
        for i in range(16):
            e.fft[i] = int(v[i]) if hasattr(v, "__len__") else int(v)
    # the waveform: a ramp -127..127 across the 256 points, read a quarter of the way
    e.pcm(np.linspace(-127.0, 127.0, 256))
    # the notes: G strongest
    pc = np.full(12, 0.1, np.float32); pc[7] = 1.0
    e.chroma(pc, 0.3)
    bands(128); e.audio(200.0, 0)
    e.frame(20)
    assert abs(read("wave", "sample") - (-0.5)) < 0.02, read("wave", "sample")
    assert abs(read("wave", "level") - 0.5) < 0.02
    assert abs(read("notes", "level") - 1.0) < 1e-4 and abs(read("notes", "note") - 7.0 / 12.0) < 1e-4
    assert read("notes", "clarity") > 0.3, read("notes", "clarity")
    # timbre: all bands alike - the middle, as flat as can be
    assert abs(read("timbre", "brightness") - 0.5) < 0.01 and read("timbre", "noisiness") > 0.95
    assert read("quiet", "sound") > 0.5 and read("quiet", "mix") > 0.99
    # all in the bass: bright 0, a tone not a hiss
    bands([255] + [0] * 15)
    for _ in range(3):
        e.frame(20)
    assert read("timbre", "brightness") < 0.01 and read("timbre", "noisiness") < 0.2, (read("timbre", "brightness"), read("timbre", "noisiness"))
    # the history: now is the bass band's 1.0
    assert abs(read("hist", "level") - 1.0) < 1e-3
    # onsets: a murmur that moves a little (so each frame is a new reading), then a hit
    rng = np.random.default_rng(3)
    fired = []
    for f in range(80):
        base = 40 + rng.integers(-3, 4, 16)
        if f == 60:
            base = base + 150
        bands(np.clip(base, 0, 255))
        e.frame(20)
        fired.append(read("onset", "onset") > 0.5)
    assert not any(fired[30:60]), [i for i, x in enumerate(fired) if x]      # once it has learnt the murmur
    assert any(fired[60:63]), fired[58:66]
    # silence: the volume gone - on for the hold, then off, mix falling to 0 over the fade
    e.audio(0.0, 0)
    qs = []
    for _ in range(30):
        e.frame(20)
        qs.append((read("quiet", "sound"), read("quiet", "quiet"), read("quiet", "mix")))
    assert qs[5][0] > 0.5 and qs[-1][0] < 0.5 and qs[-1][2] < 0.01 and abs(qs[-1][1] - 0.6) < 0.05, qs[::5]
    assert qs[12][2] < 1.0 and qs[12][2] > 0.0, qs[8:16]
    # the history two seconds back: the murmur, while now is the last reading (the bands hold through the quiet)
    assert abs(read("old", "level") - 40.0 / 255.0) < 0.03, read("old", "level")


def test_the_profile_finds_the_heavy_node():
    """A profiling build of a graph with a Noise of six octaves and an Add beside it, and its twin
    timing only the frame, run in an engine of their own (costs.run): the Noise takes far more of
    the frame than the Add, the shares and the rest make the whole frame, and the frame's own
    time is the twin's - under the instrumented build's, which pays for every node's reads."""
    import build as B
    from native import costs
    from native.toolchain import build_engine
    from native.geometry import Geometry
    g = G.Graph({"name": "Census profile"}, lib=LIB)
    n = g.add("Noise", (0, 0), {"octaves": 6})
    a = g.add("Add", (0, 200)); g.nodes[a]["inputs"] = {"b": 0.25}
    c = g.add("Coords", (-200, 200)); g.link(c, "u", a, "a")
    m = g.add("Add", (200, 0)); g.link(n, "value", m, "a"); g.link(a, "result", m, "b")
    p = g.add("Palette", (400, 0)); o = g.add("Output", (600, 0)); g.link(m, "result", p, "index"); g.link(p, "color", o, "color")
    os.makedirs(OUT, exist_ok=True)
    paths = [os.path.join(OUT, "profile_census.cpp"), os.path.join(OUT, "profile_census_frame.cpp")]
    open(paths[0], "w", encoding="utf-8", newline="\n").write(g.compile(profile=True))
    slots = list(g.prof_nodes)
    open(paths[1], "w", encoding="utf-8", newline="\n").write(g.compile(title=g.name + " frame", profile="frame"))
    rep = build_engine(B.engine_sources(paths, log=lambda *x: None), B.include_dirs(), log=lambda *x: None, point_latest=False)
    assert rep.ok, rep.link_output[-600:]
    got = costs.run(rep.library, g.name, slots, geometry=Geometry("cube", B=16), frames=30, warm=5,
                    frame_title=g.name + " frame")
    share = {nid: s for nid, (s, ms) in got["nodes"].items()}
    assert share[n] > 5 * share[a], share
    assert share[n] > 0.2, share
    assert abs(sum(share.values()) + got["rest"] - 1.0) < 1e-6 and got["frame_ms"] > 0.0, got
    # the twin's frame is the effect's own: under the instrumented one's (the reads' cost and all)
    assert 0.0 < got["frame_ms"] < got["instrumented_ms"], got


def test_the_scenes_fade_on_the_engine():
    """Built and run: the effect starts on the first scene (b 0, though b was typed 0.7), holds it
    while the Threshold is off, then fades b to the chorus's 1 over the half second after t passes
    1 s - the S-curve near the middle half way - and holds it."""
    import test_graph as TG
    from native.engine import Engine
    g, k = TG.scenes_graph()
    g.name = "Census scenes"
    g.compile()
    slot = next(key for key, v in g.probes.items() if v == (k["a"], "result"))
    gs, rep = _build({"scenes": g})
    assert rep.ok, rep.link_output[-600:]
    e = Engine(); e.load(rep.library)
    e.set_now(0)
    e.select(e.names.index(g.name))
    vals = []
    for _ in range(100):                                  # 2 s at 20 ms
        e.frame(20)
        vals.append(e.probe(slot))
    assert all(abs(v) < 1e-6 for v in vals[1:45]), vals[:45]               # the first scene: 0, not the typed 0.7
    mid = vals[63]                                         # ~0.26 s into the half-second fade
    assert 0.2 < mid < 0.8, vals[48:80]
    assert all(b >= a - 1e-6 for a, b in zip(vals[48:80], vals[49:81]))   # rising all the way
    assert all(abs(v - 1.0) < 1e-6 for v in vals[80:]), vals[76:]


def test_text_in_a_face_of_this_machine():
    """The Text node in the 5x7 font and in a face of this machine's at a
    height: white scaled by its level on a 64 x 16 matrix - the 5x7 all
    or nothing on its 7 centred rows, the face with smooth edges (levels
    between) inside its 12; with no face to draw with, the 5x7 again."""
    import numpy as np
    from native.engine import Engine
    from native.geometry import Geometry
    from native import nodedefs
    gs = {}
    for font in ("5x7", "sans"):
        g = G.Graph({"name": f"Census text {font}"}, lib=LIB)
        c = g.add("Coords", (0, 0)); t = g.add("Text", (200, 0)); w = g.add("Colour", (200, 200))
        s = g.add("Scale", (400, 0)); o = g.add("Output", (600, 0))
        g.nodes[t]["params"].update(text="Hi!", font=font, height=12, loop=False, row=-1)
        g.nodes[w]["params"]["rgb"] = [255, 255, 255]
        g.link(c, "u", t, "u"); g.link(c, "v", t, "v"); g.link(w, "color", s, "color"); g.link(t, "level", s, "by")
        g.link(s, "color", o, "color")
        gs[font] = g
    if nodedefs.text_drawn("Hi!", "body", 12) is None:
        print("  no face to draw with here: the 5x7 alone")
        gs.pop("sans")
    _, rep = _build(gs)
    assert rep.ok, rep.link_output[-600:]
    e = Engine(); e.load(rep.library)
    e.set_geometry(Geometry("matrix", w=64, h=16))
    lit = {}
    for font, g in gs.items():
        e.select(e.names.index(g.name))
        e.frame()
        m = np.asarray(e.rgb()).reshape(16, 64, 3).max(axis=2)
        rows = np.nonzero(m.max(axis=1) > 0)[0]
        lit[font] = (m, rows)
    m, rows = lit["5x7"]
    assert set(np.unique(m)) <= {0, 255} and rows.min() >= 4 and rows.max() <= 10, (np.unique(m), rows)
    if "sans" in lit:
        m, rows = lit["sans"]
        mid = ((m > 0) & (m < 255)).sum()
        assert mid > 0 and rows.min() >= 2 and rows.max() <= 13 and (m == 255).sum() > 0, (mid, rows)
    fallback = nodedefs.codegen_text({"params": {"text": "Hi", "font": "no such face"}})
    assert "tx_[10]" in fallback                                       # an unknown font: the 5x7's two glyphs


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
    assert len(took) >= 108, "the script subset shrank"          # 93 before 1.4.0; 111 with the second VM


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
