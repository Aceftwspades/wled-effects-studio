"""What each node costs (TouchDesigner's cook times; wled-toy has only the whole frame's).

A profiling build of the graph (graph.compile(profile=True)) times each node's code between two
reads of the CPU's tick counter, and times the whole frame and two reads with nothing between. It
runs in an engine of its own - the app's is never touched - for a moment on the synth; each
node's share of the frame is its ticks less the reads' own cost, over the frame's ticks less every
read's; the clock's rate makes that milliseconds here, and the calibrated speed factor (Send frame
> Calibrate) milliseconds on the device. What is left of the frame - the coordinates each pixel
is given, the drawing - is `rest`.

The device's own proportions can differ: a division, a sine or an exp costs more there, next to a
multiply, than it does here. The shares say where the time goes; the milliseconds are an estimate.

    rep = costs.run(library, "My Graph", prof_nodes, geometry, colors, fx, pal, pal_source)
    rep["nodes"][nid] -> (share of the frame, ms here); rep["rest"], rep["frame_ms"]
"""
import time


def analyse(prof_nodes, before, after, ticks_per_ms, frame_ticks=None):
    """The costs from two readings of the profile's sums, `before` and `after` a run - lists of
    (ticks, runs) by slot, in prof_nodes' order (a node id per slot, the last two the reads' own
    cost and the whole frame). A sub-graph's slots go to its node. `frame_ticks`: the frame's
    own time, from a build that times only the frame - without it, the instrumented frame less
    every read's cost, which takes off too much (the reads overlap the work round them).
    Returns {"nodes": {nid: (share, ms)}, "rest": share, "frame_ms": ms, "frames": n,
    "instrumented_ms": the profiling build's own frame, its reads and all}."""
    d = [(b[0] - a[0], b[1] - a[1]) for a, b in zip(before, after)]
    if len(d) < 2:
        return {"nodes": {}, "rest": 1.0, "frame_ms": 0.0, "frames": 0}
    (null_t, null_n), (whole_t, whole_n) = d[-2], d[-1]
    over = null_t / null_n if null_n else 0.0             # two reads and an add, each time a slot is timed
    per = {}
    for nid, (t, n) in zip(prof_nodes[:-2], d[:-2]):
        if nid is not None:
            per[nid] = per.get(nid, 0.0) + max(0.0, t - over * n)
    frames = max(1, whole_n)
    if frame_ticks:
        clean = max(1e-9, frame_ticks * frames)               # the frame's own time, over this run's frames
    else:
        reads = sum(n for _, n in d[:-1])                 # every timing inside the frame, the null's too
        clean = max(1e-9, whole_t - over * reads)
    nodes = {nid: c / clean for nid, c in per.items()}
    total = sum(nodes.values())
    if total > 1.0:                                       # the reads' cost is an average: never more than all
        nodes = {nid: s / total for nid, s in nodes.items()}
    frame_ms = clean / frames / ticks_per_ms if ticks_per_ms else 0.0
    return {"nodes": {nid: (s, s * frame_ms) for nid, s in nodes.items()},
            "rest": max(0.0, 1.0 - sum(nodes.values())), "frame_ms": frame_ms, "frames": whole_n,
            "instrumented_ms": whole_t / frames / ticks_per_ms if ticks_per_ms else 0.0}


def run(library, title, prof_nodes, geometry=None, colors=None, fx=None, pal=None, pal_source=None,
        frames=60, warm=10, dt=23, frame_title=None):
    """Load a profiling build, run `title` for `warm` frames and then `frames` more on the synth,
    and give analyse()'s answer for those. `frame_title`: the same effect timing only its frame
    (compile(profile="frame")), in the same build - run first, for the frame's own time. The
    engine is let go of after."""
    from native.engine import Engine, _unload
    from native.synth import Synth
    e = Engine(library)
    try:
        if geometry is not None:
            e.set_geometry(geometry)
        if colors:
            e.colors(*colors)
        if pal_source is not None:
            e.pal_source = pal_source
        if title not in e.names:
            raise RuntimeError(f"{title} is not in the profiling build")
        params = dict(fx or {}, pal=pal if pal is not None else 0)
        frame_ticks = None
        if frame_title and frame_title in e.names:
            e.select(e.names.index(frame_title), params=dict(params))
            syn = Synth()
            for _ in range(warm):
                syn.push(e); e.frame(dt)
            a0 = e.prof(1)
            for _ in range(frames):
                syn.push(e); e.frame(dt)
            a1 = e.prof(1)
            if a1[1] > a0[1]:
                frame_ticks = (a1[0] - a0[0]) / (a1[1] - a0[1])
        e.select(e.names.index(title), params=dict(params))
        syn = Synth()
        n = len(prof_nodes)
        for _ in range(warm):
            syn.push(e); e.frame(dt)
        before = [e.prof(k) for k in range(n)]
        c0, t0 = e.prof_clock(), time.perf_counter()
        for _ in range(frames):
            syn.push(e); e.frame(dt)
        c1, t1 = e.prof_clock(), time.perf_counter()
        after = [e.prof(k) for k in range(n)]
        rate = (c1 - c0) / max(1e-9, (t1 - t0) * 1000.0) if c0 is not None and c1 is not None else 0.0
        return analyse(prof_nodes, before, after, rate, frame_ticks)
    finally:
        lib = e.lib
        e.lib = None
        if lib is not None:
            _unload(lib)
