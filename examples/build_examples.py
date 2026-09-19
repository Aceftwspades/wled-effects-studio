"""
The example graphs, written out by script so they stay reproducible: five
cube_fx effects rebuilt from nodes. Run from studio:

    python examples/build_examples.py            # writes examples/graphs/*.json
    python examples/build_examples.py --check    # and compiles + builds them

Each is a reading of the C++ original in nodes - the same coordinates, the
same drivers, the same look - not a line-for-line port. Where the original
keeps per-pixel state (Cube Fire's heat field, Matrix Rain's drops) the graph
uses the feedback and hash nodes instead, the way a shader would.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from native import graph as G          # noqa: E402

OUT = os.path.join(HERE, "graphs")


class GB:
    """A graph builder: n() adds a node at a grid column/row, l() links."""
    def __init__(self, name):
        self.g = G.Graph({"name": name})
        self.col_w, self.row_h = 230, 130

    def n(self, type_, col, row, params=None, inputs=None):
        nid = self.g.add(type_, (40 + col * self.col_w, 40 + row * self.row_h), params or {})
        if inputs:
            self.g.nodes[nid]["inputs"] = dict(inputs)
        return nid

    def l(self, a, o, b, i):
        self.g.link(a, o, b, i)
        return b

    def save(self, fname):
        os.makedirs(OUT, exist_ok=True)
        G.migrate(self.g)          # builders written against the float pins get the vector ones
        G.save(self.g, os.path.join(OUT, fname))
        return self.g


# ---------------------------------------------------------------------------
def slab_cut():
    """Cube Slice: spectrum slabs cutting through the solid at a tumbling
    angle, re-aimed on the beat. Position . normal gives the slab number."""
    b = GB("Slab Cut")
    sp = b.n("Speed", 0, 0, {"label": "Tumble speed", "default": 70})
    it = b.n("Intensity", 0, 1, {"label": "Slab width", "default": 100})
    c1 = b.n("Custom 1", 0, 2, {"label": "Slab count", "default": 100})
    c2 = b.n("Custom 2", 0, 3, {"label": "Scroll speed", "default": 80})
    c3 = b.n("Custom 3", 0, 4, {"label": "Bass push", "default": 8})
    k1 = b.n("Check 1", 0, 5, {"label": "Re-aim on beat", "default": True})
    k2 = b.n("Check 2", 0, 6, {"label": "Reverse", "default": False})
    au = b.n("Audio", 0, 7)
    b.n("Effect settings", 0, 8, {"palette": 11, "audio": "frequency"})
    # the tumble: two angles from one running phase, the first kicked by a random on each beat
    rate = b.n("Multiply", 1, 0, inputs={"b": 0.12}); b.l(sp, "value", rate, "a")
    ang = b.n("Integrate", 2, 0, {"wrap": 1.0}); b.l(rate, "result", ang, "rate")
    rnd = b.n("Random hold", 1, 6); b.l(au, "beat", rnd, "trigger")
    re = b.n("Select", 2, 6, inputs={"a": 0.0}); b.l(k1, "on", re, "on"); b.l(rnd, "value", re, "b")
    a = b.n("Add", 3, 0); b.l(ang, "value", a, "a"); b.l(re, "result", a, "b")
    half = b.n("Multiply", 3, 1, inputs={"b": 0.5}); b.l(ang, "value", half, "a")
    bb = b.n("Add", 4, 1, inputs={"b": 0.25}); b.l(half, "result", bb, "a")
    nrm = b.n("Direction to", 5, 0); b.l(a, "result", nrm, "turns_a"); b.l(bb, "result", nrm, "turns_b")
    pos = b.n("Position", 5, 2)
    d = b.n("Dot 3", 6, 1)
    for k in "xyz":
        b.l(pos, k, d, "a" + k); b.l(nrm, k, d, "b" + k)
    # slabs across the solid, scrolling with the music
    pitch = b.n("Remap", 1, 2, {"out_lo": 1.0, "out_hi": 8.0}); b.l(c1, "value", pitch, "x")
    scroll_base = b.n("Multiply", 1, 3, inputs={"b": 2.0}); b.l(c2, "value", scroll_base, "a")
    push = b.n("Multiply", 1, 4, inputs={"b": 4.0}); b.l(c3, "value", push, "a")
    bass_push = b.n("Multiply", 2, 4); b.l(au, "bass", bass_push, "a"); b.l(push, "result", bass_push, "b")
    scroll_rate = b.n("Add", 2, 3); b.l(scroll_base, "result", scroll_rate, "a"); b.l(bass_push, "result", scroll_rate, "b")
    neg = b.n("Multiply", 3, 4, inputs={"b": -1.0}); b.l(scroll_rate, "result", neg, "a")
    signed = b.n("Select", 3, 3); b.l(k2, "on", signed, "on"); b.l(scroll_rate, "result", signed, "a"); b.l(neg, "result", signed, "b")
    scroll = b.n("Integrate", 4, 3, {"wrap": 16.0}); b.l(signed, "result", scroll, "rate")
    dp = b.n("Multiply", 7, 1); b.l(d, "result", dp, "a"); b.l(pitch, "result", dp, "b")
    s = b.n("Subtract", 8, 1); b.l(dp, "result", s, "a"); b.l(scroll, "value", s, "b")
    # the slab profile, the spectrum bin it reads, the palette colour it wears
    sharp = b.n("Remap", 1, 1, {"out_lo": 1.0, "out_hi": 6.0}); b.l(it, "value", sharp, "x")
    prof = b.n("Band", 9, 1); b.l(s, "result", prof, "x"); b.l(sharp, "result", prof, "sharp")
    m16 = b.n("Modulo", 9, 2, inputs={"m": 16.0}); b.l(s, "result", m16, "x")
    idx16 = b.n("Multiply", 10, 2, inputs={"b": 1.0 / 16.0}); b.l(m16, "result", idx16, "a")
    spec = b.n("Spectrum", 11, 2, {"smooth": 0.7}); b.l(idx16, "result", spec, "index")
    lift = b.n("Smoothstep", 12, 2, {"e0": 0.0, "e1": 0.5}); b.l(spec, "level", lift, "x")
    floor_ = b.n("Add", 12, 0, inputs={"b": 0.12}); b.l(lift, "result", floor_, "a")
    lum = b.n("Multiply", 12, 1); b.l(floor_, "result", lum, "a"); b.l(prof, "result", lum, "b")
    fl = b.n("Floor", 9, 3); b.l(s, "result", fl, "x")
    fl16 = b.n("Multiply", 10, 3, inputs={"b": 1.0 / 16.0}); b.l(fl, "result", fl16, "a")
    hue = b.n("Integrate", 10, 4, {"wrap": 1.0}, inputs={"rate": 0.02})
    hh = b.n("Add", 11, 3); b.l(fl16, "result", hh, "a"); b.l(hue, "value", hh, "b")
    pal = b.n("Palette", 12, 3); b.l(hh, "result", pal, "index"); b.l(lum, "result", pal, "brightness")
    out = b.n("Output", 13, 3); b.l(pal, "color", out, "color")
    return b.save("slab_cut.json")


def cell_weave():
    """Cube Cell: nested sines over the 3-D position, one axis per band, the
    sum wrapped so the fold draws the cell walls; a tumble on Check 2."""
    b = GB("Cell Weave")
    sp = b.n("Speed", 0, 0, {"label": "Speed", "default": 128})
    it = b.n("Intensity", 0, 1, {"label": "Drive", "default": 150})
    c1 = b.n("Custom 1", 0, 2, {"label": "Cells X", "default": 200})
    c2 = b.n("Custom 2", 0, 3, {"label": "Cells Y", "default": 64})
    c3 = b.n("Custom 3", 0, 4, {"label": "Cells Z", "default": 26})
    k2 = b.n("Check 2", 0, 5, {"label": "Tumble", "default": True})
    au = b.n("Audio", 0, 6)
    b.n("Effect settings", 0, 7, {"palette": 12, "audio": "frequency"})
    pos = b.n("Position", 1, 6)
    # tumble: two slow rotations, or the raw position
    r1 = b.n("Multiply", 1, 0, inputs={"b": 0.04}); b.l(sp, "value", r1, "a")
    a1 = b.n("Integrate", 2, 0, {"wrap": 1.0}); b.l(r1, "result", a1, "rate")
    r2 = b.n("Multiply", 1, 1, inputs={"b": 0.027}); b.l(sp, "value", r2, "a")
    a2 = b.n("Integrate", 2, 1, {"wrap": 1.0}); b.l(r2, "result", a2, "rate")
    rot1 = b.n("Rotate", 2, 6); b.l(pos, "x", rot1, "x"); b.l(pos, "y", rot1, "y"); b.l(a1, "value", rot1, "turns")
    rot2 = b.n("Rotate", 3, 6); b.l(rot1, "y", rot2, "x"); b.l(pos, "z", rot2, "y"); b.l(a2, "value", rot2, "turns")
    x = b.n("Select", 4, 5); b.l(k2, "on", x, "on"); b.l(pos, "x", x, "a"); b.l(rot1, "x", x, "b")
    y = b.n("Select", 4, 6); b.l(k2, "on", y, "on"); b.l(pos, "y", y, "a"); b.l(rot2, "x", y, "b")
    z = b.n("Select", 4, 7); b.l(k2, "on", z, "on"); b.l(pos, "z", z, "a"); b.l(rot2, "y", z, "b")
    # each axis' cell frequency: its slider, stretched by its band
    def freq(col, row, slider, band):
        base = b.n("Remap", col, row, {"out_lo": 0.05, "out_hi": 0.5}); b.l(slider, "value", base, "x")
        drive = b.n("Multiply", col + 1, row, inputs={"b": 0.8}); b.l(au, band, drive, "a")
        gain = b.n("Add", col + 2, row, inputs={"a": 0.7}); b.l(drive, "result", gain, "b")
        f = b.n("Multiply", col + 3, row); b.l(base, "result", f, "a"); b.l(gain, "result", f, "b")
        return f
    fx = freq(1, 2, c1, "bass"); fy = freq(1, 3, c2, "mid"); fz = freq(1, 4, c3, "treble")
    gx = b.n("Multiply", 5, 5); b.l(x, "result", gx, "a"); b.l(fx, "result", gx, "b")
    gy = b.n("Multiply", 5, 6); b.l(y, "result", gy, "a"); b.l(fy, "result", gy, "b")
    gz = b.n("Multiply", 5, 7); b.l(z, "result", gz, "a"); b.l(fz, "result", gz, "b")
    ph = b.n("Remap", 1, 5, {"out_lo": 0.0, "out_hi": 0.6}); b.l(sp, "value", ph, "x")
    t8 = b.n("Integrate", 2, 5, {"wrap": 1.0}); b.l(ph, "result", t8, "rate")
    # the nested sines, cycled across the axes
    # sin8 in the original is 0..255 - unsigned - so each sine is lifted to 0..1 here
    def nested(col, row, outer, inner):
        s1 = b.n("Add", col, row); b.l(inner, "result", s1, "a"); b.l(t8, "value", s1, "b")
        sn = b.n("Sine", col + 1, row); b.l(s1, "result", sn, "x")
        sc = b.n("Multiply", col + 2, row, inputs={"b": 0.25}); b.l(sn, "result", sc, "a")
        s2 = b.n("Add", col + 3, row); b.l(outer, "result", s2, "a"); b.l(sc, "result", s2, "b")
        sn2 = b.l(s2, "result", b.n("Sine", col + 4, row), "x")
        return b.l(sn2, "result", b.n("Remap", col + 5, row, {"in_lo": -1.0, "in_hi": 1.0}), "x")
    a = nested(6, 5, gx, gy); bb = nested(6, 6, gy, gz); c = nested(6, 7, gz, gx)
    # weights 1, 1/2, 1/2 sum to two: the fold wraps once, drawing one set of walls
    ha = b.n("Multiply", 12, 4, inputs={"b": 1.0}); b.l(a, "result", ha, "a")
    hb = b.n("Multiply", 12, 7, inputs={"b": 0.5}); b.l(bb, "result", hb, "a")
    hc = b.n("Multiply", 12, 8, inputs={"b": 0.5}); b.l(c, "result", hc, "a")
    s1 = b.n("Add", 13, 5); b.l(ha, "result", s1, "a"); b.l(hb, "result", s1, "b")
    s2 = b.n("Add", 13, 6); b.l(s1, "result", s2, "a"); b.l(hc, "result", s2, "b")
    hue = b.n("Integrate", 13, 7, {"wrap": 1.0}, inputs={"rate": 0.01})
    s3 = b.n("Add", 14, 6); b.l(s2, "result", s3, "a"); b.l(hue, "value", s3, "b")
    idx = b.n("Fract", 15, 6); b.l(s3, "result", idx, "x")          # the wrap IS the cell wall
    # brightness: volume, smoothed, through the Drive slider
    env = b.n("Envelope", 1, 7, {"attack": 30.0, "release": 300.0}); b.l(au, "volume", env, "x")
    dr = b.n("Remap", 2, 7, {"out_lo": 0.3, "out_hi": 1.0}); b.l(it, "value", dr, "x")
    bright = b.n("Multiply", 3, 8); b.l(env, "value", bright, "a"); b.l(dr, "result", bright, "b")
    br2 = b.n("Add", 4, 8, inputs={"b": 0.15}); b.l(bright, "result", br2, "a")
    pal = b.n("Palette", 16, 6); b.l(idx, "result", pal, "index"); b.l(br2, "result", pal, "brightness")
    out = b.n("Output", 17, 6); b.l(pal, "color", out, "color")
    return b.save("cell_weave.json")


def truchet():
    """Truchet: each face cut into N x N tiles, each tile a pair of quarter
    circles turned by a hash; the seed re-rolls on the beat, so the maze
    rewires itself."""
    b = GB("Truchet Cube")
    sp = b.n("Speed", 0, 0, {"label": "Flow", "default": 100})
    it = b.n("Intensity", 0, 1, {"label": "Line width", "default": 150})
    c1 = b.n("Custom 1", 0, 2, {"label": "Tiles per face", "default": 40})
    c3 = b.n("Custom 3", 0, 3, {"label": "Seed", "default": 3})
    k1 = b.n("Check 1", 0, 4, {"label": "Rewire on beat", "default": True})
    au = b.n("Audio", 0, 5)
    b.n("Effect settings", 0, 6, {"palette": 11, "audio": "frequency"})
    face = b.n("Cube face", 1, 3)
    nn = b.n("Remap", 1, 2, {"out_lo": 1.0, "out_hi": 8.99}); b.l(c1, "value", nn, "x")
    n = b.n("Floor", 2, 2); b.l(nn, "result", n, "x")
    ta = b.n("Multiply", 2, 3); b.l(face, "a", ta, "a"); b.l(n, "result", ta, "b")
    tb = b.n("Multiply", 2, 4); b.l(face, "b", tb, "a"); b.l(n, "result", tb, "b")
    ca = b.n("Floor", 3, 3); b.l(ta, "result", ca, "x")
    cb = b.n("Floor", 3, 4); b.l(tb, "result", cb, "x")
    la = b.n("Fract", 3, 5); b.l(ta, "result", la, "x")
    lb = b.n("Fract", 3, 6); b.l(tb, "result", lb, "x")
    # one random per tile: face, cell and the seed (which the beat can re-roll)
    rnd = b.n("Random hold", 1, 5); b.l(au, "beat", rnd, "trigger")
    rs = b.n("Select", 2, 5, inputs={"a": 0.0}); b.l(k1, "on", rs, "on"); b.l(rnd, "value", rs, "b")
    seed = b.n("Add", 2, 6); b.l(c3, "value", seed, "a"); b.l(rs, "result", seed, "b")
    f100 = b.n("Multiply", 4, 2, inputs={"b": 100.0}); b.l(face, "face", f100, "a")
    hx = b.n("Add", 4, 3); b.l(ca, "result", hx, "a"); b.l(f100, "result", hx, "b")
    h = b.n("Hash", 5, 3); b.l(hx, "result", h, "x"); b.l(cb, "result", h, "y"); b.l(seed, "result", h, "seed")
    flip = b.n("Threshold", 6, 3, inputs={"at": 0.5}); b.l(h, "value", flip, "x")
    ila = b.n("Subtract", 4, 5, inputs={"a": 1.0}); b.l(la, "result", ila, "b")
    la2 = b.n("Select", 5, 5); b.l(flip, "on", la2, "on"); b.l(la, "result", la2, "a"); b.l(ila, "result", la2, "b")
    # distance to the two arcs, radius 1/2, centred on opposite corners
    len1 = b.n("Length", 6, 5); b.l(la2, "result", len1, "x"); b.l(lb, "result", len1, "y")
    d1a = b.n("Subtract", 7, 5, inputs={"b": 0.5}); b.l(len1, "result", d1a, "a")
    d1 = b.n("Abs", 8, 5); b.l(d1a, "result", d1, "x")
    ila2 = b.n("Subtract", 6, 6, inputs={"a": 1.0}); b.l(la2, "result", ila2, "b")
    ilb = b.n("Subtract", 6, 7, inputs={"a": 1.0}); b.l(lb, "result", ilb, "b")
    len2 = b.n("Length", 7, 6); b.l(ila2, "result", len2, "x"); b.l(ilb, "result", len2, "y")
    d2a = b.n("Subtract", 8, 6, inputs={"b": 0.5}); b.l(len2, "result", d2a, "a")
    d2 = b.n("Abs", 9, 6); b.l(d2a, "result", d2, "x")
    d = b.n("Min", 9, 5); b.l(d1, "result", d, "a"); b.l(d2, "result", d, "b")
    width = b.n("Remap", 1, 1, {"out_lo": 0.06, "out_hi": 0.35}); b.l(it, "value", width, "x")
    dw = b.n("Divide", 10, 5); b.l(d, "result", dw, "a"); b.l(width, "result", dw, "b")
    inv = b.n("Subtract", 11, 5, inputs={"a": 1.0}); b.l(dw, "result", inv, "b")
    line = b.n("Smoothstep", 12, 5); b.l(inv, "result", line, "x")
    # colour flows along the curves: the tile's own hue plus a running phase
    fl = b.n("Multiply", 1, 0, inputs={"b": 0.4}); b.l(sp, "value", fl, "a")
    flow = b.n("Integrate", 2, 0, {"wrap": 1.0}); b.l(fl, "result", flow, "rate")
    hh = b.n("Multiply", 6, 2, inputs={"b": 0.7}); b.l(h, "value", hh, "a")
    hi = b.n("Add", 7, 2); b.l(hh, "result", hi, "a"); b.l(flow, "value", hi, "b")
    pal = b.n("Palette", 13, 5); b.l(hi, "result", pal, "index"); b.l(line, "result", pal, "brightness")
    out = b.n("Output", 14, 5); b.l(pal, "color", out, "color")
    return b.save("truchet_cube.json")


def ring_rain():
    """Matrix Rain on the lid-and-walls ruler: each column its own speed and
    phase from a hash, a bright head and a trail behind it, no drop state."""
    b = GB("Ring Rain")
    sp = b.n("Speed", 0, 0, {"label": "Fall speed", "default": 128})
    it = b.n("Intensity", 0, 1, {"label": "Trail", "default": 128})
    c1 = b.n("Custom 1", 0, 2, {"label": "Columns", "default": 128})
    k1 = b.n("Check 1", 0, 3, {"label": "Bass brightens", "default": True})
    au = b.n("Audio", 0, 4)
    b.n("Effect settings", 0, 5, {"palette": 10, "audio": "volume"})
    ring = b.n("Cube ring", 1, 3)
    ncol = b.n("Remap", 1, 2, {"out_lo": 8.0, "out_hi": 64.0}); b.l(c1, "value", ncol, "x")
    colf = b.n("Multiply", 2, 2); b.l(ring, "around", colf, "a"); b.l(ncol, "result", colf, "b")
    col = b.n("Floor", 3, 2); b.l(colf, "result", col, "x")
    h1 = b.n("Hash", 4, 1, inputs={"y": 0.0, "seed": 1.0}); b.l(col, "result", h1, "x")
    h2 = b.n("Hash", 4, 2, inputs={"y": 1.0, "seed": 1.0}); b.l(col, "result", h2, "x")
    spd = b.n("Remap", 1, 0, {"out_lo": 0.1, "out_hi": 1.5}); b.l(sp, "value", spd, "x")
    vary = b.n("Remap", 5, 1, {"out_lo": 0.3, "out_hi": 1.0}); b.l(h1, "value", vary, "x")
    speed = b.n("Multiply", 6, 1); b.l(vary, "result", speed, "a"); b.l(spd, "result", speed, "b")
    tt = b.n("Integrate", 2, 0, {"wrap": 0.0}, inputs={"rate": 1.0})
    pos = b.n("Multiply", 7, 1); b.l(tt, "value", pos, "a"); b.l(speed, "result", pos, "b")
    ph = b.n("Add", 8, 1); b.l(pos, "result", ph, "a"); b.l(h2, "value", ph, "b")
    head = b.n("Fract", 9, 1); b.l(ph, "result", head, "x")
    # behind the head: 0 at the head, growing up the column (towards the lid)
    rel = b.n("Subtract", 9, 3); b.l(head, "result", rel, "a"); b.l(ring, "depth", rel, "b")
    behind = b.n("Modulo", 10, 3, inputs={"m": 1.0}); b.l(rel, "result", behind, "x")
    inv = b.n("Subtract", 11, 3, inputs={"a": 1.0}); b.l(behind, "result", inv, "b")
    tl = b.n("Remap", 1, 1, {"out_lo": 14.0, "out_hi": 3.0}); b.l(it, "value", tl, "x")
    trail = b.n("Power", 12, 3); b.l(inv, "result", trail, "x"); b.l(tl, "result", trail, "e")
    ishead = b.n("Threshold", 11, 4, inputs={"at": 0.035}); b.l(behind, "result", ishead, "x")
    headm = b.n("Select", 12, 4, inputs={"a": 1.0, "b": 0.0}); b.l(ishead, "on", headm, "on")
    # bass brightens the trails when asked
    bb = b.n("Multiply", 5, 4, inputs={"b": 1.5}); b.l(au, "bass", bb, "a")
    bsel = b.n("Select", 6, 4, inputs={"a": 0.0}); b.l(k1, "on", bsel, "on"); b.l(bb, "result", bsel, "b")
    gain = b.n("Add", 7, 4, inputs={"a": 0.6}); b.l(bsel, "result", gain, "b")
    tb = b.n("Multiply", 13, 3); b.l(trail, "result", tb, "a"); b.l(gain, "result", tb, "b")
    hue = b.n("Multiply", 5, 2, inputs={"b": 0.6}); b.l(h1, "value", hue, "a")
    pal = b.n("Palette", 14, 3); b.l(hue, "result", pal, "index"); b.l(tb, "result", pal, "brightness")
    white = b.n("Colour", 13, 5, {"rgb": [255, 255, 255]})
    mix = b.n("Blend", 15, 4, {"mode": "over"}); b.l(pal, "color", mix, "under"); b.l(white, "color", mix, "over"); b.l(headm, "result", mix, "amount")
    out = b.n("Output", 16, 4); b.l(mix, "color", out, "color")
    return b.save("ring_rain.json")


def box_fire():
    """Cube Fire: a heat field that rises up the walls and pools on the lid.
    The heat is a Field (a number per pixel kept between frames): each pixel
    reads last frame's heat one step down the ring, cools it, and the bottom
    edge is the source. The palette only colours it."""
    b = GB("Box Fire")
    sp = b.n("Speed", 0, 0, {"label": "Rise", "default": 128})
    it = b.n("Intensity", 0, 1, {"label": "Heat", "default": 170})
    c1 = b.n("Custom 1", 0, 2, {"label": "Flicker", "default": 128})
    k1 = b.n("Check 1", 0, 3, {"label": "Bass flare", "default": True})
    au = b.n("Audio", 0, 4)
    tm = b.n("Time", 0, 5)
    b.n("Effect settings", 0, 6, {"palette": 35, "audio": "frequency"})
    ring = b.n("Cube ring", 1, 4)
    # read one step deeper (toward the source) - that is what makes heat rise
    step = b.n("Remap", 1, 0, {"out_lo": 0.012, "out_hi": 0.05}); b.l(sp, "value", step, "x")
    deeper = b.n("Add", 2, 4); b.l(ring, "depth", deeper, "a"); b.l(step, "result", deeper, "b")
    t3 = b.n("Multiply", 1, 5, inputs={"b": 2.0}); b.l(tm, "t", t3, "a")
    wob = b.n("Noise", 2, 5, inputs={"scale": 6.0}); b.l(ring, "around", wob, "x"); b.l(ring, "depth", wob, "y"); b.l(t3, "result", wob, "z")
    wc = b.n("Subtract", 3, 5, inputs={"b": 0.5}); b.l(wob, "value", wc, "a")
    fl = b.n("Remap", 1, 2, {"out_lo": 0.0, "out_hi": 0.05}); b.l(c1, "value", fl, "x")
    wamt = b.n("Multiply", 4, 5); b.l(wc, "result", wamt, "a"); b.l(fl, "result", wamt, "b")
    ar = b.n("Add", 3, 4); b.l(ring, "around", ar, "a"); b.l(wamt, "result", ar, "b")
    uv = b.n("Ring to uv", 4, 4); b.l(ar, "result", uv, "around"); b.l(deeper, "result", uv, "depth")
    heat = b.n("Field", 5, 4, {"field": 0}); b.l(uv, "u", heat, "u"); b.l(uv, "v", heat, "v")
    cool = b.n("Remap", 1, 1, {"out_lo": 0.86, "out_hi": 0.975}); b.l(it, "value", cool, "x")
    hc = b.n("Multiply", 6, 4); b.l(heat, "value", hc, "a"); b.l(cool, "result", hc, "b")
    # the source: the bottom edge smoulders, flickers, and flares with bass
    t4 = b.n("Multiply", 1, 6, inputs={"b": 4.0}); b.l(tm, "t", t4, "a")
    src = b.n("Noise", 2, 6, inputs={"y": 0.3, "scale": 8.0}); b.l(ring, "around", src, "x"); b.l(t4, "result", src, "z")
    bass = b.n("Multiply", 2, 7, inputs={"b": 1.5}); b.l(au, "bass", bass, "a")
    flare = b.n("Select", 3, 7, inputs={"a": 0.0}); b.l(k1, "on", flare, "on"); b.l(bass, "result", flare, "b")
    gain = b.n("Add", 4, 7, inputs={"a": 0.8}); b.l(flare, "result", gain, "b")
    s2 = b.n("Multiply", 5, 6); b.l(src, "value", s2, "a"); b.l(gain, "result", s2, "b")
    edge = b.n("Smoothstep", 5, 7, {"e0": 0.9, "e1": 1.0}); b.l(ring, "depth", edge, "x")
    s3 = b.n("Multiply", 6, 6); b.l(s2, "result", s3, "a"); b.l(edge, "result", s3, "b")
    h2 = b.n("Max", 7, 5); b.l(hc, "result", h2, "a"); b.l(s3, "result", h2, "b")
    keep = b.n("Field write", 8, 6, {"field": 0}); b.l(h2, "result", keep, "value")
    bri = b.n("Smoothstep", 8, 4, {"e0": 0.02, "e1": 0.3}); b.l(h2, "result", bri, "x")
    pal = b.n("Palette", 9, 5); b.l(h2, "result", pal, "index"); b.l(bri, "result", pal, "brightness")
    out = b.n("Output", 10, 5); b.l(pal, "color", out, "color")
    return b.save("box_fire.json")


# ---------------------------------------------------------------------------
# The second five: Maelstrom, Kaleidoscope, Mandelbrot, Watershed, Moire.
# ---------------------------------------------------------------------------
def maelstrom():
    """Maelstrom: a logarithmic spiral sinking into the lid - phase =
    density * log(radius) + arms * azimuth + t, so a constant rate of t is a
    constant rate of zoom. A beat surges the zoom; two seconds without one
    and it eases round and unwinds outward until the next."""
    b = GB("Maelstrom")
    sp = b.n("Speed", 0, 0, {"label": "Zoom", "default": 90})
    it = b.n("Intensity", 0, 1, {"label": "Contrast", "default": 120})
    c1 = b.n("Custom 1", 0, 2, {"label": "Arms", "default": 85})
    c2 = b.n("Custom 2", 0, 3, {"label": "Colour cycle", "default": 40})
    c3 = b.n("Custom 3", 0, 4, {"label": "Density", "default": 10})
    k1 = b.n("Check 1", 0, 5, {"label": "Colour along arms", "default": False})
    au = b.n("Audio", 0, 6)
    b.n("Effect settings", 0, 7, {"palette": 11, "audio": "frequency"})
    ring = b.n("Cube ring", 1, 5)
    # the zoom rate: the slider, a surge on the beat, and the turn-around when the kicks stop
    base = b.n("Remap", 1, 0, {"out_lo": 0.05, "out_hi": 1.2}); b.l(sp, "value", base, "x")
    kick = b.n("Envelope", 1, 6, {"attack": 10.0, "release": 350.0}); b.l(au, "hit", kick, "x")
    surge = b.n("Add", 2, 6, inputs={"a": 1.0}); b.l(kick, "value", surge, "b")
    since = b.n("Integrate", 1, 7, {"wrap": 0.0}, inputs={"rate": 1.0}); b.l(au, "beat", since, "reset")
    gone = b.n("Smoothstep", 2, 7, {"e0": 2.0, "e1": 3.5}); b.l(since, "value", gone, "x")
    dirn = b.n("Remap", 3, 7, {"out_lo": 1.0, "out_hi": -1.0}); b.l(gone, "result", dirn, "x")
    eased = b.n("Envelope", 4, 7, {"attack": 700.0, "release": 700.0}); b.l(dirn, "result", eased, "x")
    r1 = b.n("Multiply", 3, 6); b.l(base, "result", r1, "a"); b.l(surge, "result", r1, "b")
    rate = b.n("Multiply", 5, 6); b.l(r1, "result", rate, "a"); b.l(eased, "value", rate, "b")
    ph = b.n("Integrate", 6, 6, {"wrap": 1.0}); b.l(rate, "result", ph, "rate")
    # the spiral: density * log(radius) + arms * azimuth + phase
    arms = b.n("Remap", 1, 2, {"out_lo": 0.0, "out_hi": 8.99}); b.l(c1, "value", arms, "x")
    narms = b.n("Floor", 2, 2); b.l(arms, "result", narms, "x")
    dens = b.n("Remap", 1, 4, {"out_lo": 0.5, "out_hi": 6.0}); b.l(c3, "value", dens, "x")
    rad = b.n("Add", 2, 5, inputs={"b": 0.02}); b.l(ring, "depth", rad, "a")
    lr = b.n("Log", 3, 5); b.l(rad, "result", lr, "x")
    dl = b.n("Multiply", 4, 4); b.l(lr, "result", dl, "a"); b.l(dens, "result", dl, "b")
    aa = b.n("Multiply", 4, 5); b.l(ring, "around", aa, "a"); b.l(narms, "result", aa, "b")
    ph1 = b.n("Add", 5, 4); b.l(dl, "result", ph1, "a"); b.l(aa, "result", ph1, "b")
    ph2 = b.n("Add", 6, 4); b.l(ph1, "result", ph2, "a"); b.l(ph, "value", ph2, "b")
    # contrast: how sharp the arms are; brightness lifts a little on the surge
    sharp = b.n("Remap", 1, 1, {"out_lo": 0.6, "out_hi": 6.0}); b.l(it, "value", sharp, "x")
    arm = b.n("Band", 7, 4); b.l(ph2, "result", arm, "x"); b.l(sharp, "result", arm, "sharp")
    lift = b.n("Remap", 3, 3, {"out_lo": 0.8, "out_hi": 1.15}); b.l(kick, "value", lift, "x")
    bri = b.n("Multiply", 8, 4); b.l(arm, "result", bri, "a"); b.l(lift, "result", bri, "b")
    # colour: along the arms (perpendicular phase) or across them, cycling
    cyc = b.n("Remap", 1, 3, {"out_lo": 0.0, "out_hi": 0.3}); b.l(c2, "value", cyc, "x")
    hue = b.n("Integrate", 2, 3, {"wrap": 1.0}); b.l(cyc, "result", hue, "rate")
    across = b.n("Multiply", 7, 2, inputs={"b": 0.25}); b.l(ph2, "result", across, "a")
    al1 = b.n("Multiply", 5, 2); b.l(lr, "result", al1, "a"); b.l(narms, "result", al1, "b")
    al2 = b.n("Multiply", 5, 3); b.l(ring, "around", al2, "a"); b.l(dens, "result", al2, "b")
    along = b.n("Subtract", 6, 2); b.l(al1, "result", along, "a"); b.l(al2, "result", along, "b")
    along2 = b.n("Multiply", 7, 3, inputs={"b": 0.08}); b.l(along, "result", along2, "a")
    pick = b.n("Select", 8, 2); b.l(k1, "on", pick, "on"); b.l(across, "result", pick, "a"); b.l(along2, "result", pick, "b")
    idx = b.n("Add", 9, 2); b.l(pick, "result", idx, "a"); b.l(hue, "value", idx, "b")
    pal = b.n("Palette", 10, 3); b.l(idx, "result", pal, "index"); b.l(bri, "result", pal, "brightness")
    out = b.n("Output", 11, 3); b.l(pal, "color", out, "color")
    return b.save("maelstrom.json")


def kaleidoscope():
    """Kaleidoscope: every direction is spun, folded into one fundamental
    domain of a mirror group, and cut by a few offset planes into flat cells
    - the cuts evaluated AFTER the fold, so each cell is mirrored over the
    whole solid. The offsets drift, so cells grow, merge and split."""
    b = GB("Kaleidoscope")
    sp = b.n("Speed", 0, 0, {"label": "Spin", "default": 110})
    it = b.n("Intensity", 0, 1, {"label": "Fill", "default": 128})
    c1 = b.n("Custom 1", 0, 2, {"label": "Drift", "default": 90})
    c2 = b.n("Custom 2", 0, 3, {"label": "Colour mix", "default": 170})
    k1 = b.n("Check 1", 0, 4, {"label": "Beat surge", "default": True})
    au = b.n("Audio", 0, 5)
    b.n("Effect settings", 0, 6, {"palette": 11, "audio": "frequency"})
    d = b.n("Direction", 1, 5)
    # two rotation clocks, then the fold
    ra = b.n("Remap", 1, 0, {"out_lo": 0.0, "out_hi": 0.12}); b.l(sp, "value", ra, "x")
    sa = b.n("Integrate", 2, 0, {"wrap": 1.0}); b.l(ra, "result", sa, "rate")
    rb = b.n("Multiply", 1, 1, inputs={"b": 0.618}); b.l(ra, "result", rb, "a")
    sb = b.n("Integrate", 2, 1, {"wrap": 1.0}); b.l(rb, "result", sb, "rate")
    rot1 = b.n("Rotate", 2, 5); b.l(d, "nx", rot1, "x"); b.l(d, "ny", rot1, "y"); b.l(sa, "value", rot1, "turns")
    rot2 = b.n("Rotate", 3, 5); b.l(rot1, "y", rot2, "x"); b.l(d, "nz", rot2, "y"); b.l(sb, "value", rot2, "turns")
    fold = b.n("Mirror fold", 4, 5, {"symmetry": "octahedral"})
    b.l(rot1, "x", fold, "x"); b.l(rot2, "x", fold, "y"); b.l(rot2, "y", fold, "z")
    # the arrangement: four cut planes with drifting offsets, a bit per side
    dr = b.n("Remap", 1, 2, {"out_lo": 0.0, "out_hi": 0.25}); b.l(c1, "value", dr, "x")
    drift = b.n("Integrate", 2, 2, {"wrap": 1.0}); b.l(dr, "result", drift, "rate")
    # each cut's offset sits at the domain's centroid (the generic direction the
    # mirrors are pointed at) and drifts by a fraction of the domain's spread,
    # so a cut always crosses the domain wherever the symmetry has put it
    cuts = [(0.5774, 0.5774, 0.5774, 0.0, 0.892), (-0.7071, 0.7071, 0.0, 0.29, 0.147),
            (0.2673, -0.5345, 0.8018, 0.61, 0.518), (0.8944, 0.0, -0.4472, 0.83, -0.174)]
    bits = []
    for k, (cx, cy, cz, phs, at0) in enumerate(cuts):
        dot = b.n("Dot 3", 5, 2 + k, inputs={"bx": cx, "by": cy, "bz": cz})
        b.l(fold, "x", dot, "ax"); b.l(fold, "y", dot, "ay"); b.l(fold, "z", dot, "az")
        p_ = b.n("Add", 3, 2 + k, inputs={"b": phs}); b.l(drift, "value", p_, "a")
        off = b.n("Sine", 4, 2 + k); b.l(p_, "result", off, "x")
        off2 = b.n("Remap", 4, 6 + k, {"in_lo": -1.0, "in_hi": 1.0, "out_lo": at0 - 0.22, "out_hi": at0 + 0.22}); b.l(off, "result", off2, "x")
        th = b.n("Threshold", 6, 2 + k); b.l(dot, "result", th, "x"); b.l(off2, "result", th, "at")
        w = b.n("Multiply", 7, 2 + k, inputs={"b": [1.0, 2.0, 4.0, 8.0][k] / 15.0}); b.l(th, "value", w, "a")
        bits.append(w)
    s1 = b.n("Add", 8, 2); b.l(bits[0], "result", s1, "a"); b.l(bits[1], "result", s1, "b")
    s2 = b.n("Add", 8, 3); b.l(bits[2], "result", s2, "a"); b.l(bits[3], "result", s2, "b")
    cell = b.n("Add", 9, 2); b.l(s1, "result", cell, "a"); b.l(s2, "result", cell, "b")
    # colour: the cell id spread over the palette by Colour mix, plus a slow turn
    mix = b.n("Remap", 1, 3, {"out_lo": 0.2, "out_hi": 1.0}); b.l(c2, "value", mix, "x")
    ci = b.n("Multiply", 10, 2); b.l(cell, "result", ci, "a"); b.l(mix, "result", ci, "b")
    hue = b.n("Integrate", 9, 4, {"wrap": 1.0}, inputs={"rate": 0.015})
    idx = b.n("Add", 11, 2); b.l(ci, "result", idx, "a"); b.l(hue, "value", idx, "b")
    # fill, with a beat surge
    fill = b.n("Remap", 1, 4, {"out_lo": 0.25, "out_hi": 1.0}); b.l(it, "value", fill, "x")
    kick = b.n("Envelope", 2, 6, {"attack": 10.0, "release": 300.0}); b.l(au, "hit", kick, "x")
    ks = b.n("Select", 3, 6, inputs={"a": 0.0}); b.l(k1, "on", ks, "on"); b.l(kick, "value", ks, "b")
    sg = b.n("Add", 4, 10, inputs={"a": 1.0}); b.l(ks, "result", sg, "b")
    bri = b.n("Multiply", 10, 4); b.l(fill, "result", bri, "a"); b.l(sg, "result", bri, "b")
    pal = b.n("Palette", 12, 3); b.l(idx, "result", pal, "index"); b.l(bri, "result", pal, "brightness")
    out = b.n("Output", 13, 3); b.l(pal, "color", out, "color")
    return b.save("kaleidoscope.json")


def mandelbrot():
    """Mandelbrot: the direction projected stereographically from the bottom
    pole onto the plane (lid = origin, equator = unit circle), the set drawn
    there around a filament-rich point, breathing in and out - a zoom that
    never has to reset because it never goes deeper than it came."""
    b = GB("Mandelbrot")
    sp = b.n("Speed", 0, 0, {"label": "Zoom", "default": 110})
    it = b.n("Intensity", 0, 1, {"label": "Brightness", "default": 150})
    c1 = b.n("Custom 1", 0, 2, {"label": "Filigree", "default": 180})
    c2 = b.n("Custom 2", 0, 3, {"label": "Locus", "default": 255})
    c3 = b.n("Custom 3", 0, 4, {"label": "Detail", "default": 18})
    k1 = b.n("Check 1", 0, 5, {"label": "Beat surge", "default": True})
    au = b.n("Audio", 0, 6)
    b.n("Effect settings", 0, 7, {"palette": 11, "audio": "frequency"})
    d = b.n("Direction", 1, 5)
    # stereographic: u = x / (1 + z), v = y / (1 + z)
    den = b.n("Add", 2, 6, inputs={"a": 1.0}); b.l(d, "nz", den, "b")
    u = b.n("Divide", 3, 5); b.l(d, "nx", u, "a"); b.l(den, "result", u, "b")
    v = b.n("Divide", 3, 6); b.l(d, "ny", v, "a"); b.l(den, "result", v, "b")
    # the breathing zoom: scale = exp(-(1 + sin(phase)) * depth), turning slowly
    zr = b.n("Remap", 1, 0, {"out_lo": 0.01, "out_hi": 0.2}); b.l(sp, "value", zr, "x")
    kick = b.n("Envelope", 1, 6, {"attack": 10.0, "release": 400.0}); b.l(au, "hit", kick, "x")
    ks = b.n("Select", 2, 7, inputs={"a": 0.0}); b.l(k1, "on", ks, "on"); b.l(kick, "value", ks, "b")
    sg = b.n("Add", 3, 7, inputs={"a": 1.0}); b.l(ks, "result", sg, "b")
    zr2 = b.n("Multiply", 4, 7); b.l(zr, "result", zr2, "a"); b.l(sg, "result", zr2, "b")
    phase = b.n("Integrate", 5, 7, {"wrap": 1.0}); b.l(zr2, "result", phase, "rate")
    sn = b.n("Sine", 6, 7); b.l(phase, "value", sn, "x")
    depth = b.n("Remap", 1, 4, {"out_lo": 0.5, "out_hi": 2.5}); b.l(c3, "value", depth, "x")
    e1 = b.n("Add", 7, 7, inputs={"a": 1.0}); b.l(sn, "result", e1, "b")
    e2 = b.n("Multiply", 8, 7); b.l(e1, "result", e2, "a"); b.l(depth, "result", e2, "b")
    e3 = b.n("Multiply", 9, 7, inputs={"b": -1.0}); b.l(e2, "result", e3, "a")
    scale = b.n("Exp", 10, 7); b.l(e3, "result", scale, "x")
    turn = b.n("Multiply", 6, 8, inputs={"b": 0.5}); b.l(phase, "value", turn, "a")
    # the locus: a line of points worth diving at, picked by the slider
    lx = b.n("Remap", 1, 3, {"out_lo": -0.7453, "out_hi": -0.1011}); b.l(c2, "value", lx, "x")
    ly = b.n("Remap", 2, 3, {"out_lo": 0.1127, "out_hi": 0.9563}); b.l(c2, "value", ly, "x")
    rot = b.n("Rotate", 4, 5); b.l(u, "result", rot, "x"); b.l(v, "result", rot, "y"); b.l(turn, "result", rot, "turns")
    sx = b.n("Multiply", 5, 5); b.l(rot, "x", sx, "a"); b.l(scale, "result", sx, "b")
    sy = b.n("Multiply", 5, 6); b.l(rot, "y", sy, "a"); b.l(scale, "result", sy, "b")
    cx = b.n("Add", 6, 5); b.l(sx, "result", cx, "a"); b.l(lx, "result", cx, "b")
    cy = b.n("Add", 6, 6); b.l(sy, "result", cy, "a"); b.l(ly, "result", cy, "b")
    mb = b.n("Mandelbrot", 7, 5, {"iterations": 90}); b.l(cx, "result", mb, "x"); b.l(cy, "result", mb, "y")
    # colour: escape time round the palette, the inside dark; Filigree sharpens the bands
    fil = b.n("Remap", 1, 2, {"out_lo": 1.0, "out_hi": 6.0}); b.l(c1, "value", fil, "x")
    tm = b.n("Multiply", 8, 5); b.l(mb, "value", tm, "a"); b.l(fil, "result", tm, "b")
    hue = b.n("Integrate", 8, 4, {"wrap": 1.0}, inputs={"rate": 0.03})
    idx = b.n("Add", 9, 5); b.l(tm, "result", idx, "a"); b.l(hue, "value", idx, "b")
    inside = b.n("Threshold", 8, 6, inputs={"at": 0.999}); b.l(mb, "value", inside, "x")
    dim = b.n("Select", 9, 6, inputs={"a": 1.0, "b": 0.12}); b.l(inside, "on", dim, "on")
    br = b.n("Remap", 1, 1, {"out_lo": 0.2, "out_hi": 1.0}); b.l(it, "value", br, "x")
    bri = b.n("Multiply", 10, 6); b.l(dim, "result", bri, "a"); b.l(br, "result", bri, "b")
    pal = b.n("Palette", 11, 5); b.l(idx, "result", pal, "index"); b.l(bri, "result", pal, "brightness")
    out = b.n("Output", 12, 5); b.l(pal, "color", out, "color")
    return b.save("mandelbrot.json")


def watershed():
    """Watershed: a height field over the surface (sinusoids of the position,
    drifting), every pixel draining to its lowest neighbour, water advected
    one hop per frame and summed where threads meet - trunks brighter than
    tributaries. Flow erodes the ground, so channels capture and heal. A beat
    is a downpour."""
    b = GB("Watershed")
    sp = b.n("Speed", 0, 0, {"label": "Drift", "default": 160})
    it = b.n("Intensity", 0, 1, {"label": "Rain", "default": 140})
    c1 = b.n("Custom 1", 0, 2, {"label": "Erosion", "default": 90})
    c2 = b.n("Custom 2", 0, 3, {"label": "Relief", "default": 128})
    k1 = b.n("Check 1", 0, 4, {"label": "Storms on the beat", "default": True})
    au = b.n("Audio", 0, 5)
    tm = b.n("Time", 0, 6)
    b.n("Effect settings", 0, 7, {"palette": 36, "audio": "frequency"})
    pos = b.n("Position", 1, 5)
    co = b.n("Coords", 1, 7)
    # the base ground: three sinusoids of the position, drifting
    dr = b.n("Remap", 1, 0, {"out_lo": 0.0, "out_hi": 0.08}); b.l(sp, "value", dr, "x")
    ph = b.n("Integrate", 2, 0, {"wrap": 1.0}); b.l(dr, "result", ph, "rate")
    def wave(col, row, ax, k, pshift):
        m = b.n("Multiply", col, row, inputs={"b": k}); b.l(pos, ax, m, "a")
        p_ = b.n("Multiply", col, row + 3, inputs={"b": pshift}); b.l(ph, "value", p_, "a")
        a_ = b.n("Add", col + 1, row); b.l(m, "result", a_, "a"); b.l(p_, "result", a_, "b")
        return b.l(a_, "result", b.n("Sine", col + 2, row), "x")
    w1 = wave(2, 1, "x", 0.9, 1.0); w2 = wave(2, 2, "y", 1.3, -0.7); w3 = wave(5, 1, "z", 1.1, 0.5)
    s1 = b.n("Add", 8, 1); b.l(w1, "result", s1, "a"); b.l(w2, "result", s1, "b")
    ground = b.n("Add", 8, 2); b.l(s1, "result", ground, "a"); b.l(w3, "result", ground, "b")
    relief = b.n("Remap", 1, 3, {"out_lo": 0.3, "out_hi": 1.5}); b.l(c2, "value", relief, "x")
    g2 = b.n("Multiply", 9, 2); b.l(ground, "result", g2, "a"); b.l(relief, "result", g2, "b")
    # last frame's water here erodes the ground; the height field is written for next frame
    wprev = b.n("Field", 3, 7, {"field": 1}); b.l(co, "u", wprev, "u"); b.l(co, "v", wprev, "v")
    er = b.n("Remap", 1, 2, {"out_lo": 0.0, "out_hi": 0.6}); b.l(c1, "value", er, "x")
    ero = b.n("Multiply", 4, 7); b.l(wprev, "value", ero, "a"); b.l(er, "result", ero, "b")
    ero2 = b.n("Clamp", 5, 7, {"lo": 0.0, "hi": 1.0}); b.l(ero, "result", ero2, "x")
    height = b.n("Subtract", 10, 2); b.l(g2, "result", height, "a"); b.l(ero2, "result", height, "b")
    b.l(height, "result", b.n("Field write", 11, 2, {"field": 0}), "value")
    # drainage: what flows in, plus this pixel's own rain; sinks pool
    drain = b.n("Drain", 3, 5, {"height_field": 0, "water_field": 1})
    rain = b.n("Remap", 1, 1, {"out_lo": 0.005, "out_hi": 0.06}); b.l(it, "value", rain, "x")
    storm_n = b.n("Noise", 4, 4, inputs={"scale": 3.0}); b.l(pos, "x", storm_n, "x"); b.l(pos, "y", storm_n, "y"); b.l(tm, "t", storm_n, "z")
    cell = b.n("Smoothstep", 5, 4, {"e0": 0.55, "e1": 0.75}); b.l(storm_n, "value", cell, "x")
    kick = b.n("Envelope", 2, 6, {"attack": 5.0, "release": 250.0}); b.l(au, "hit", kick, "x")
    ks = b.n("Select", 3, 6, inputs={"a": 0.0}); b.l(k1, "on", ks, "on"); b.l(kick, "value", ks, "b")
    storm = b.n("Multiply", 6, 4); b.l(cell, "result", storm, "a"); b.l(ks, "result", storm, "b")
    storm2 = b.n("Multiply", 7, 4, inputs={"b": 0.5}); b.l(storm, "result", storm2, "a")
    r2 = b.n("Add", 8, 4); b.l(rain, "result", r2, "a"); b.l(storm2, "result", r2, "b")
    keep = b.n("Select", 4, 5, inputs={"a": 0.95, "b": 0.85}); b.l(drain, "sink", keep, "on")   # a sink pools, soaking away slowly
    inflow = b.n("Multiply", 5, 5); b.l(drain, "water", inflow, "a"); b.l(keep, "result", inflow, "b")
    water = b.n("Add", 9, 4); b.l(inflow, "result", water, "a"); b.l(r2, "result", water, "b")
    wclamp = b.n("Clamp", 10, 4, {"lo": 0.0, "hi": 3.0}); b.l(water, "result", wclamp, "x")
    b.l(wclamp, "result", b.n("Field write", 11, 4, {"field": 1}), "value")
    # colour: trunks bright, headwaters faint; the hue from the ground height
    bri = b.n("Smoothstep", 11, 5, {"e0": 0.003, "e1": 0.25}); b.l(wclamp, "result", bri, "x")
    hi = b.n("Remap", 11, 3, {"in_lo": -1.5, "in_hi": 1.5, "out_lo": 0.0, "out_hi": 0.8}); b.l(height, "result", hi, "x")
    pal = b.n("Palette", 12, 4); b.l(hi, "result", pal, "index"); b.l(bri, "result", pal, "brightness")
    out = b.n("Output", 13, 4); b.l(pal, "color", out, "color")
    return b.save("watershed.json")


def moire():
    """Moire: a polar funnel about the lid, a curl-shaped warp of the 3-D
    point, then two dot lattices - each a product of cosines along two
    directions - at slightly different scales, interfering; the hue from the
    field itself."""
    b = GB("Moire")
    sp = b.n("Speed", 0, 0, {"label": "Flow", "default": 70})
    it = b.n("Intensity", 0, 1, {"label": "Fill", "default": 128})
    c1 = b.n("Custom 1", 0, 2, {"label": "Distort", "default": 128})
    c2 = b.n("Custom 2", 0, 3, {"label": "Scale", "default": 120})
    c3 = b.n("Custom 3", 0, 4, {"label": "Detune", "default": 20})
    k1 = b.n("Check 1", 0, 5, {"label": "Beat surge", "default": True})
    au = b.n("Audio", 0, 6)
    b.n("Effect settings", 0, 7, {"palette": 11, "audio": "frequency"})
    pos = b.n("Position", 1, 5)
    fl = b.n("Remap", 1, 0, {"out_lo": 0.02, "out_hi": 0.4}); b.l(sp, "value", fl, "x")
    p1 = b.n("Integrate", 2, 0, {"wrap": 1.0}); b.l(fl, "result", p1, "rate")
    p2 = b.n("Multiply", 3, 0, inputs={"b": 0.73}); b.l(p1, "value", p2, "a")
    kick = b.n("Envelope", 1, 7, {"attack": 10.0, "release": 300.0}); b.l(au, "hit", kick, "x")
    ks = b.n("Select", 2, 7, inputs={"a": 0.0}); b.l(k1, "on", ks, "on"); b.l(kick, "value", ks, "b")
    surge = b.n("Add", 3, 7, inputs={"a": 1.0}); b.l(ks, "result", surge, "b")
    # 1. the funnel: radius scaled by a travelling sine, angle twisted more near the lid
    dist = b.n("Remap", 1, 2, {"out_lo": 0.0, "out_hi": 0.5}); b.l(c1, "value", dist, "x")
    r_ = b.n("Length", 2, 5); b.l(pos, "x", r_, "x"); b.l(pos, "y", r_, "y")
    rs = b.n("Multiply", 2, 6, inputs={"b": 1.2}); b.l(r_, "result", rs, "a")
    rp = b.n("Subtract", 3, 6); b.l(rs, "result", rp, "a"); b.l(p1, "value", rp, "b")
    rsn = b.n("Sine", 4, 6); b.l(rp, "result", rsn, "x")
    ra = b.n("Multiply", 5, 6); b.l(rsn, "result", ra, "a"); b.l(dist, "result", ra, "b")
    ra2 = b.n("Multiply", 5, 7); b.l(ra, "result", ra2, "a"); b.l(surge, "result", ra2, "b")
    rf = b.n("Add", 6, 6, inputs={"a": 1.0}); b.l(ra2, "result", rf, "b")
    tw1 = b.n("Subtract", 4, 4, inputs={"a": 1.6}); b.l(r_, "result", tw1, "b")
    tw2 = b.n("Multiply", 5, 4); b.l(tw1, "result", tw2, "a"); b.l(dist, "result", tw2, "b")
    tw3 = b.n("Multiply", 6, 4, inputs={"b": 0.5}); b.l(tw2, "result", tw3, "a")
    rot = b.n("Rotate", 7, 5); b.l(pos, "x", rot, "x"); b.l(pos, "y", rot, "y"); b.l(tw3, "result", rot, "turns")
    X = b.n("Multiply", 8, 5); b.l(rot, "x", X, "a"); b.l(rf, "result", X, "b")
    Y = b.n("Multiply", 8, 6); b.l(rot, "y", Y, "a"); b.l(rf, "result", Y, "b")
    # 2. the warp: each axis pushed by a sine of another
    amp = b.n("Multiply", 6, 2, inputs={"b": 0.35}); b.l(dist, "result", amp, "a")
    amp2 = b.n("Multiply", 7, 2); b.l(amp, "result", amp2, "a"); b.l(surge, "result", amp2, "b")
    def push(col, row, src, k, ph):
        m = b.n("Multiply", col, row, inputs={"b": k}); b.l(src[0], src[1], m, "a")
        a_ = b.n("Add", col + 1, row); b.l(m, "result", a_, "a"); b.l(ph, "value", a_, "b")
        sn = b.n("Sine", col + 2, row); b.l(a_, "result", sn, "x")
        w = b.n("Multiply", col + 3, row); b.l(sn, "result", w, "a"); b.l(amp2, "result", w, "b")
        return w
    wx = push(9, 3, (Y, "result"), 0.46, p1); wy = push(9, 4, (pos, "z"), 0.43, p1); wz = push(9, 5, (X, "result"), 0.39, p1)
    X2 = b.n("Add", 13, 5); b.l(X, "result", X2, "a"); b.l(wx, "result", X2, "b")
    Y2 = b.n("Add", 13, 6); b.l(Y, "result", Y2, "a"); b.l(wy, "result", Y2, "b")
    Z2 = b.n("Add", 13, 7); b.l(pos, "z", Z2, "a"); b.l(wz, "result", Z2, "b")
    # 3. two lattices - cosines along two generic directions - and their beat
    sc = b.n("Remap", 1, 3, {"out_lo": 1.5, "out_hi": 6.0}); b.l(c2, "value", sc, "x")
    det = b.n("Remap", 1, 4, {"out_lo": 1.0, "out_hi": 1.12}); b.l(c3, "value", det, "x")
    sc2 = b.n("Multiply", 2, 4); b.l(sc, "result", sc2, "a"); b.l(det, "result", sc2, "b")
    def lattice(col, row, scale, da, db):
        A = b.n("Dot 3", col, row, inputs={"bx": da[0], "by": da[1], "bz": da[2]})
        Bd = b.n("Dot 3", col, row + 1, inputs={"bx": db[0], "by": db[1], "bz": db[2]})
        for n_ in (A, Bd):
            b.l(X2, "result", n_, "ax"); b.l(Y2, "result", n_, "ay"); b.l(Z2, "result", n_, "az")
        sa = b.n("Multiply", col + 1, row); b.l(A, "result", sa, "a"); b.l(scale, "result", sa, "b")
        sb = b.n("Multiply", col + 1, row + 1); b.l(Bd, "result", sb, "a"); b.l(scale, "result", sb, "b")
        pa = b.n("Add", col + 2, row); b.l(sa, "result", pa, "a"); b.l(p2, "result", pa, "b")
        pb = b.n("Subtract", col + 2, row + 1); b.l(sb, "result", pb, "a"); b.l(p1, "value", pb, "b")
        ca = b.n("Cosine", col + 3, row); b.l(pa, "result", ca, "x")
        cb = b.n("Cosine", col + 3, row + 1); b.l(pb, "result", cb, "x")
        g = b.n("Multiply", col + 4, row); b.l(ca, "result", g, "a"); b.l(cb, "result", g, "b")
        return b.l(g, "result", b.n("Power", col + 5, row, inputs={"e": 3.0}), "x")
    g1 = lattice(14, 2, sc, (0.8105, 0.3137, -0.4946), (0.1142, 0.7584, 0.6417))
    g2 = lattice(14, 5, sc2, (0.7300, 0.4500, -0.5100), (0.2100, 0.7100, 0.6700))
    mx = b.n("Max", 20, 3); b.l(g1, "result", mx, "a"); b.l(g2, "result", mx, "b")
    co = b.n("Multiply", 20, 4); b.l(g1, "result", co, "a"); b.l(g2, "result", co, "b")
    m = b.n("Add", 21, 3); b.l(mx, "result", m, "a"); b.l(co, "result", m, "b")
    fill = b.n("Remap", 1, 1, {"out_lo": 0.4, "out_hi": 2.0}); b.l(it, "value", fill, "x")
    lum = b.n("Multiply", 22, 3); b.l(m, "result", lum, "a"); b.l(fill, "result", lum, "b")
    # 4. hue from the field
    hd = b.n("Dot 3", 14, 8, inputs={"bx": 0.3, "by": 0.5, "bz": 0.2})
    b.l(X2, "result", hd, "ax"); b.l(Y2, "result", hd, "ay"); b.l(Z2, "result", hd, "az")
    hue = b.n("Integrate", 15, 9, {"wrap": 1.0}, inputs={"rate": 0.02})
    hi = b.n("Add", 16, 8); b.l(hd, "result", hi, "a"); b.l(hue, "value", hi, "b")
    pal = b.n("Palette", 23, 4); b.l(hi, "result", pal, "index"); b.l(lum, "result", pal, "brightness")
    out = b.n("Output", 24, 4); b.l(pal, "color", out, "color")
    return b.save("moire.json")


# ---------------------------------------------------------------------------
# The third five: Cube Ripples, Cube Chladni, Candy Knot, Gyro Sand, Breakout.
# ---------------------------------------------------------------------------
def ripples():
    """Cube Ripples: each beat drops a point source somewhere on the surface
    and a spherical shell expands from it through 3-D space, so a ring that
    starts on one wall climbs the lid and comes down the far side whole. Its
    colour is the bin that was loudest when it was born."""
    b = GB("Cube Ripples")
    sp = b.n("Speed", 0, 0, {"label": "Speed", "default": 110})
    it = b.n("Intensity", 0, 1, {"label": "Thickness", "default": 90})
    c2 = b.n("Custom 2", 0, 2, {"label": "Persistence", "default": 140})
    au = b.n("Audio", 0, 3)
    b.n("Effect settings", 0, 4, {"palette": 11, "audio": "frequency"})
    lb = b.n("Loudest bin", 1, 3)
    em = b.n("Emitters", 2, 3, {"random": True}, inputs={"life": 5.0}); b.l(au, "beat", em, "trigger"); b.l(lb, "bin", em, "tag")
    pos = b.n("Position", 1, 5)
    speed = b.n("Remap", 1, 0, {"out_lo": 0.15, "out_hi": 1.2}); b.l(sp, "value", speed, "x")
    width = b.n("Remap", 1, 1, {"out_lo": 0.08, "out_hi": 0.45}); b.l(it, "value", width, "x")
    sh = b.n("Shells", 3, 4); b.l(em, "slots", sh, "slots"); b.l(speed, "result", sh, "speed"); b.l(width, "result", sh, "width")
    for k in "xyz":
        b.l(pos, k, sh, k)
    # the trail: last frame's colour kept, so a ring leaves a wake
    prev = b.n("Previous", 3, 6)
    keep = b.n("Remap", 1, 2, {"out_lo": 0.6, "out_hi": 0.93}); b.l(c2, "value", keep, "x")
    faded = b.n("Fade", 4, 6); b.l(prev, "color", faded, "color"); b.l(keep, "result", faded, "keep")
    idx = b.n("Add", 4, 3, inputs={"b": 0.0}); b.l(sh, "tag", idx, "a")
    ring = b.n("Palette", 5, 4); b.l(idx, "result", ring, "index"); b.l(sh, "value", ring, "brightness")
    mix = b.n("Blend", 6, 5, {"mode": "add"}, inputs={"amount": 1.0}); b.l(faded, "color", mix, "under"); b.l(ring, "color", mix, "over")
    out = b.n("Output", 7, 5); b.l(mix, "color", out, "color")
    return b.save("cube_ripples.json")


def chladni():
    """Cube Chladni: the nodal surface of a 3-D standing wave in the solid,
    psi = cos(lX)cos(mY)cos(nZ) - cos(mX)cos(nY)cos(lZ), met by the faces; the
    sand collects where psi is zero. The three mode numbers each follow a
    band's loudest bin, eased, so the figure re-tunes with the music."""
    b = GB("Cube Chladni")
    sp = b.n("Speed", 0, 0, {"label": "Morph speed", "default": 90})
    it = b.n("Intensity", 0, 1, {"label": "Sharpness", "default": 128})
    c1 = b.n("Custom 1", 0, 2, {"label": "Tune", "default": 100})
    c2 = b.n("Custom 2", 0, 3, {"label": "Audio span", "default": 110})
    c3 = b.n("Custom 3", 0, 4, {"label": "Sand-glow", "default": 0})
    au = b.n("Audio", 0, 5)
    b.n("Effect settings", 0, 6, {"palette": 11, "audio": "frequency"})
    pos = b.n("Position", 1, 6)
    base = b.n("Remap", 1, 2, {"out_lo": 0.4, "out_hi": 2.0}); b.l(c1, "value", base, "x")
    span = b.n("Remap", 1, 3, {"out_lo": 0.0, "out_hi": 1.5}); b.l(c2, "value", span, "x")
    ease = b.n("Remap", 1, 0, {"out_lo": 900.0, "out_hi": 60.0}); b.l(sp, "value", ease, "x")
    # three mode numbers: base + the loudest bin of a band, spread by span, eased at Morph speed
    def mode(row, lo, hi, offset):
        lb_ = b.n("Loudest bin", 2, row, {"from": lo, "to": hi})
        sp_ = b.n("Multiply", 3, row); b.l(lb_, "bin", sp_, "a"); b.l(span, "result", sp_, "b")
        t_ = b.n("Add", 4, row, inputs={"b": offset}); b.l(sp_, "result", t_, "a")
        t2 = b.n("Add", 5, row); b.l(t_, "result", t2, "a"); b.l(base, "result", t2, "b")
        e_ = b.n("Envelope", 6, row, {"attack": 400.0, "release": 400.0}); b.l(t2, "result", e_, "x")
        return e_
    L = mode(1, 1, 4, 0.0); M = mode(2, 6, 10, 0.5); N = mode(3, 12, 15, 1.0)
    # cos(k * axis) for each mode and axis
    def cs(col, row, mode_, axis):
        m_ = b.n("Multiply", col, row); b.l(pos, axis, m_, "a"); b.l(mode_, "value", m_, "b")
        h_ = b.n("Multiply", col + 1, row, inputs={"b": 0.5}); b.l(m_, "result", h_, "a")   # cos of half a turn per unit
        c_ = b.n("Cosine", col + 2, row); b.l(h_, "result", c_, "x")
        return b.l(c_, "result", b.n("Remap", col + 3, row, {"out_lo": -1.0, "out_hi": 1.0}), "x")
    lx = cs(7, 0, L, "x"); my = cs(7, 1, M, "y"); nz = cs(7, 2, N, "z")
    mx = cs(7, 3, M, "x"); ny = cs(7, 4, N, "y"); lz = cs(7, 5, L, "z")
    t1a = b.n("Multiply", 11, 0); b.l(lx, "result", t1a, "a"); b.l(my, "result", t1a, "b")
    t1 = b.n("Multiply", 12, 0); b.l(t1a, "result", t1, "a"); b.l(nz, "result", t1, "b")
    t2a = b.n("Multiply", 11, 3); b.l(mx, "result", t2a, "a"); b.l(ny, "result", t2a, "b")
    t2 = b.n("Multiply", 12, 3); b.l(t2a, "result", t2, "a"); b.l(lz, "result", t2, "b")
    psi = b.n("Subtract", 13, 1); b.l(t1, "result", psi, "a"); b.l(t2, "result", psi, "b")
    a = b.n("Abs", 14, 1); b.l(psi, "result", a, "x")
    sharp = b.n("Remap", 1, 1, {"out_lo": 2.0, "out_hi": 14.0}); b.l(it, "value", sharp, "x")
    d = b.n("Multiply", 15, 1); b.l(a, "result", d, "a"); b.l(sharp, "result", d, "b")
    dc = b.n("Clamp", 16, 1, {"lo": 0.0, "hi": 1.0}); b.l(d, "result", dc, "x")
    sand = b.n("Subtract", 17, 0, inputs={"a": 1.0}); b.l(dc, "result", sand, "b")     # bright on the nodes
    glow = b.n("Mix", 18, 1); b.l(sand, "result", glow, "a"); b.l(dc, "result", glow, "b"); b.l(c3, "value", glow, "t")
    # the whole figure fades if the modes come together (psi vanishes)
    dlm = b.n("Subtract", 7, 6); b.l(L, "value", dlm, "a"); b.l(M, "value", dlm, "b")
    spread = b.n("Abs", 8, 6); b.l(dlm, "result", spread, "x")
    sf = b.n("Smoothstep", 9, 6, {"e0": 0.05, "e1": 0.3}); b.l(spread, "result", sf, "x")
    env = b.n("Envelope", 1, 5, {"attack": 30.0, "release": 300.0}); b.l(au, "volume", env, "x")
    dr = b.n("Add", 2, 6, inputs={"b": 0.35}); b.l(env, "value", dr, "a")
    drive = b.n("Multiply", 10, 6); b.l(dr, "result", drive, "a"); b.l(sf, "result", drive, "b")
    lum = b.n("Multiply", 19, 2); b.l(glow, "result", lum, "a"); b.l(drive, "result", lum, "b")
    lbh = b.n("Loudest bin", 17, 3, {"from": 1, "to": 4})
    idx = b.n("Add", 18, 3); b.l(lbh, "bin", idx, "a"); b.l(lum, "result", idx, "b")
    idx2 = b.n("Multiply", 19, 3, inputs={"b": 0.5}); b.l(idx, "result", idx2, "a")
    pal = b.n("Palette", 20, 2); b.l(idx2, "result", pal, "index"); b.l(lum, "result", pal, "brightness")
    out = b.n("Output", 21, 2); b.l(pal, "color", out, "color")
    return b.save("cube_chladni.json")


def candy_knot():
    """Candy Knot: a (p, q) torus knot seen from the centre, tumbling; the
    tube striped along its length, glossy where the light catches it, and a
    thin seam shows through the dark bands. Beats surge the band duty."""
    b = GB("Candy Knot")
    sp = b.n("Speed", 0, 0, {"label": "Tumble", "default": 80})
    it = b.n("Intensity", 0, 1, {"label": "Fill", "default": 128})
    c1 = b.n("Custom 1", 0, 2, {"label": "Thickness", "default": 170})
    c2 = b.n("Custom 2", 0, 3, {"label": "Bands", "default": 90})
    k1 = b.n("Check 1", 0, 4, {"label": "Beat surge", "default": True})
    k2 = b.n("Check 2", 0, 5, {"label": "Seam", "default": True})
    au = b.n("Audio", 0, 6)
    b.n("Effect settings", 0, 7, {"palette": 11, "audio": "frequency"})
    d = b.n("Direction", 1, 5)
    # the tumble: two slow spins, and a flow along the knot
    ra = b.n("Remap", 1, 0, {"out_lo": 0.01, "out_hi": 0.2}); b.l(sp, "value", ra, "x")
    sa = b.n("Integrate", 2, 0, {"wrap": 1.0}); b.l(ra, "result", sa, "rate")
    rb = b.n("Multiply", 1, 1, inputs={"b": 0.8}); b.l(ra, "result", rb, "a")
    sb = b.n("Integrate", 2, 1, {"wrap": 1.0}); b.l(rb, "result", sb, "rate")
    rf = b.n("Multiply", 1, 2, inputs={"b": 0.43}); b.l(ra, "result", rf, "a")
    kick = b.n("Envelope", 1, 6, {"attack": 10.0, "release": 300.0}); b.l(au, "hit", kick, "x")
    ks = b.n("Select", 2, 6, inputs={"a": 0.0}); b.l(k1, "on", ks, "on"); b.l(kick, "value", ks, "b")
    fk = b.n("Multiply", 2, 7, inputs={"b": 0.6}); b.l(ks, "result", fk, "a")
    fr = b.n("Add", 3, 7); b.l(rf, "result", fr, "a"); b.l(fk, "result", fr, "b")
    flow = b.n("Integrate", 4, 7, {"wrap": 1.0}); b.l(fr, "result", flow, "rate")
    rot1 = b.n("Rotate", 2, 5); b.l(d, "nx", rot1, "x"); b.l(d, "ny", rot1, "y"); b.l(sa, "value", rot1, "turns")
    rot2 = b.n("Rotate", 3, 5); b.l(rot1, "y", rot2, "x"); b.l(d, "nz", rot2, "y"); b.l(sb, "value", rot2, "turns")
    tube = b.n("Remap", 1, 3, {"out_lo": 0.16, "out_hi": 0.38}); b.l(c1, "value", tube, "x")
    knot = b.n("Torus knot", 4, 5, {"p": 2, "q": 3, "R": 0.62, "r": 0.3})
    b.l(rot1, "x", knot, "nx"); b.l(rot2, "x", knot, "ny"); b.l(rot2, "y", knot, "nz"); b.l(tube, "result", knot, "tube")
    # bands along the knot: on for `duty` of each, the surge widening them
    nb = b.n("Remap", 1, 4, {"out_lo": 6.0, "out_hi": 40.0}); b.l(c2, "value", nb, "x")
    g1 = b.n("Multiply", 5, 3); b.l(knot, "along", g1, "a"); b.l(nb, "result", g1, "b")
    g2 = b.n("Add", 6, 3); b.l(g1, "result", g2, "a"); b.l(flow, "value", g2, "b")
    gf = b.n("Fract", 7, 3); b.l(g2, "result", gf, "x")
    duty = b.n("Remap", 3, 6, {"out_lo": 0.5, "out_hi": 0.7}); b.l(ks, "result", duty, "x")
    onb = b.n("Threshold", 8, 3); b.l(duty, "result", onb, "x"); b.l(gf, "result", onb, "at")   # on when duty >= gf
    # colour: one palette entry per band, drifting
    bi = b.n("Floor", 5, 2); b.l(g1, "result", bi, "x")
    bh = b.n("Multiply", 6, 2, inputs={"b": 0.13}); b.l(bi, "result", bh, "a")
    hue = b.n("Integrate", 6, 1, {"wrap": 1.0}, inputs={"rate": 0.02})
    idx = b.n("Add", 7, 2); b.l(bh, "result", idx, "a"); b.l(hue, "value", idx, "b")
    # lighting: a fixed lamp, gloss where the normal faces it
    lamp = b.n("Dot 3", 5, 5, inputs={"bx": 0.3, "by": -0.25, "bz": 0.92}); b.l(knot, "Nx", lamp, "ax"); b.l(knot, "Ny", lamp, "ay"); b.l(knot, "Nz", lamp, "az")
    lit = b.n("Clamp", 6, 5, {"lo": 0.0, "hi": 1.0}); b.l(lamp, "result", lit, "x")
    diff = b.n("Remap", 7, 5, {"out_lo": 0.45, "out_hi": 1.0}); b.l(lit, "result", diff, "x")
    gloss = b.n("Power", 7, 6, inputs={"e": 8.0}); b.l(lit, "result", gloss, "x")
    fill = b.n("Remap", 1, 7, {"out_lo": 0.3, "out_hi": 1.0}); b.l(it, "value", fill, "x")
    band_l = b.n("Multiply", 8, 5); b.l(diff, "result", band_l, "a"); b.l(fill, "result", band_l, "b")
    # the seam: a thin line down the tube's centre, showing through the dark bands
    seam_c = b.n("Threshold", 5, 7, inputs={"at": 0.18}); b.l(knot, "edge", seam_c, "x")
    seam_on = b.n("Not", 6, 8); b.l(seam_c, "on", seam_on, "on")
    seam_k = b.n("Select", 7, 8, inputs={"a": 0.0}); b.l(k2, "on", seam_k, "on"); b.l(seam_on, "result", seam_k, "b")
    seam_l = b.n("Multiply", 8, 8, inputs={"b": 0.8}); b.l(seam_k, "result", seam_l, "a")
    lum = b.n("Select", 9, 5); b.l(onb, "on", lum, "on"); b.l(seam_l, "result", lum, "a"); b.l(band_l, "result", lum, "b")
    hit = b.n("Multiply", 10, 5); b.l(lum, "result", hit, "a"); b.l(knot, "on", hit, "b")
    col = b.n("Palette", 11, 4); b.l(idx, "result", col, "index"); b.l(hit, "result", col, "brightness")
    white = b.n("Colour", 10, 6, {"rgb": [255, 255, 255]})
    gl2 = b.n("Multiply", 9, 6); b.l(gloss, "result", gl2, "a"); b.l(knot, "on", gl2, "b")
    gl3 = b.n("Multiply", 10, 7, inputs={"b": 0.7}); b.l(gl2, "result", gl3, "a")
    shiny = b.n("Blend", 12, 5, {"mode": "add"}); b.l(col, "color", shiny, "under"); b.l(white, "color", shiny, "over"); b.l(gl3, "result", shiny, "amount")
    out = b.n("Output", 13, 5); b.l(shiny, "color", out, "color")
    return b.save("candy_knot.json")


def gyro_sand():
    """Gyro Sand: grains poured in at the lid fall the way gravity says - the
    IMU's when one is fitted, else straight down, tilted by two sliders - and
    pile up on the bottom edge. A falling-sand automaton on a Field, gathered
    per pixel: a grain arrives from the cell against gravity, stays if the cell
    along gravity is full or the floor. Beats pour a burst."""
    b = GB("Gyro Sand")
    sp = b.n("Speed", 0, 0, {"label": "Pour rate", "default": 120})
    it = b.n("Intensity", 0, 1, {"label": "Glow", "default": 150})
    c1 = b.n("Custom 1", 0, 2, {"label": "Tilt X", "default": 200})
    c2 = b.n("Custom 2", 0, 3, {"label": "Tilt Y", "default": 190})
    k1 = b.n("Check 1", 0, 4, {"label": "Beat bursts", "default": True})
    au = b.n("Audio", 0, 5)
    tm = b.n("Time", 0, 6)
    b.n("Effect settings", 0, 7, {"palette": 8, "audio": "volume"})
    pos = b.n("Position", 1, 5)
    co = b.n("Coords", 1, 7)
    tx = b.n("Remap", 1, 2, {"out_lo": -0.8, "out_hi": 0.8}); b.l(c1, "value", tx, "x")
    ty = b.n("Remap", 1, 3, {"out_lo": -0.8, "out_hi": 0.8}); b.l(c2, "value", ty, "x")
    g0 = b.n("Gravity", 2, 3); b.l(tx, "result", g0, "tilt_x"); b.l(ty, "result", g0, "tilt_y")
    # gravity along the surface: the part that points into the face does
    # nothing to a grain lying on it, so it is removed - on the lid a grain
    # slides the way the cube is tilted, on a wall it falls
    face = b.n("Cube face", 1, 11)
    gn = b.n("Dot 3", 2, 11); b.l(g0, "gx", gn, "ax"); b.l(g0, "gy", gn, "ay"); b.l(g0, "gz", gn, "az")
    b.l(face, "nx", gn, "bx"); b.l(face, "ny", gn, "by"); b.l(face, "nz", gn, "bz")
    class _T: pass
    g = _T()
    for k, ax in enumerate("xyz"):
        m_ = b.n("Multiply", 3, 10 + k); b.l(gn, "result", m_, "a"); b.l(face, "n" + ax, m_, "b")
        t_ = b.n("Subtract", 4, 10 + k); b.l(g0, "g" + ax, t_, "a"); b.l(m_, "result", t_, "b")
        setattr(g, ax, t_)
    # one pixel along gravity and against it, as positions, then as pixels
    step = b.n("Divide", 2, 5, inputs={"a": 2.6, "b": 16.0})      # a pixel and a bit of a 16-face, so the lid's middle moves too
    def along(col, row, sign, src=None):
        """One step along (sign=1) or against gravity from a position - the
        pixel's own, or one already stepped - as a position and a pixel."""
        outs = []
        for k, ax in enumerate("xyz"):
            m_ = b.n("Multiply", col, row + k); b.l(getattr(g, ax), "result", m_, "a"); b.l(step, "result", m_, "b")
            s_ = b.n("Multiply", col + 1, row + k, inputs={"b": sign}); b.l(m_, "result", s_, "a")
            a_ = b.n("Add", col + 2, row + k)
            if src is None: b.l(pos, ax, a_, "a")
            else:           b.l(src[k], "result", a_, "a")
            b.l(s_, "result", a_, "b")
            outs.append(a_)
        uv = b.n("Position to uv", col + 3, row)
        for k, ax in enumerate("xyz"):
            b.l(outs[k], "result", uv, ax)
        return uv, outs
    below, bpos = along(3, 5, 1.0)
    above, apos = along(3, 8, -1.0)
    # The two steps are not each other's inverse once pushed back onto the
    # surface, so a grain only moves when both cells agree: it arrives from
    # above if above's own "below" is this pixel, and it leaves only if
    # below's own "above" is this pixel. Nothing is lost between the two.
    ba, _ = along(3, 14, 1.0, src=apos)       # below of above
    ab, _ = along(3, 17, -1.0, src=bpos)      # above of below
    def same_pixel(col, row, uv):
        du = b.n("Subtract", col, row); b.l(uv, "u", du, "a"); b.l(co, "u", du, "b")
        dv = b.n("Subtract", col, row + 1); b.l(uv, "v", dv, "a"); b.l(co, "v", dv, "b")
        ln = b.n("Length", col + 1, row); b.l(du, "result", ln, "x"); b.l(dv, "result", ln, "y")
        near = b.n("Threshold", col + 2, row, inputs={"at": 0.006}); b.l(ln, "result", near, "x")   # on = a different pixel
        return b.l(near, "on", b.n("Not", col + 3, row), "on")
    eqA = same_pixel(7, 14, ba)
    eqB = same_pixel(7, 17, ab)
    here = b.n("Field", 2, 8, {"field": 0}); b.l(co, "u", here, "u"); b.l(co, "v", here, "v")
    fb = b.n("Field", 7, 5, {"field": 0}); b.l(below, "u", fb, "u"); b.l(below, "v", fb, "v")
    fa = b.n("Field", 7, 8, {"field": 0}); b.l(above, "u", fa, "u"); b.l(above, "v", fa, "v")
    # the floor: past the bottom edge (no bottom face) or off the surface downward
    bz = b.n("Threshold", 8, 6, inputs={"at": -0.999}); b.l(bpos[2], "result", bz, "x")   # on = still on the cube
    floor = b.n("Not", 9, 6); b.l(bz, "on", floor, "on")
    fbs = b.n("Threshold", 8, 5, inputs={"at": 0.5}); b.l(fb, "value", fbs, "x")
    solid = b.n("Max", 9, 5); b.l(fbs, "value", solid, "a"); b.l(floor, "result", solid, "b")
    hs = b.n("Threshold", 8, 8, inputs={"at": 0.5}); b.l(here, "value", hs, "x")
    leaves = b.n("Multiply", 10, 4); b.l(eqB, "result", leaves, "a")        # below will take it
    inv_solid = b.n("Subtract", 10, 3, inputs={"a": 1.0}); b.l(solid, "result", inv_solid, "b")
    b.l(inv_solid, "result", leaves, "b")
    hold = b.n("Subtract", 11, 4, inputs={"a": 1.0}); b.l(leaves, "result", hold, "b")
    stays0 = b.n("Multiply", 10, 5); b.l(hs, "value", stays0, "a"); b.l(hold, "result", stays0, "b")
    # the bottom edge soaks grains away slowly, so the pile never jams the
    # whole flow: what the pour puts in, the floor takes out
    soak_h = b.n("Hash", 11, 10); b.l(co, "v", soak_h, "x"); b.l(co, "u", soak_h, "y"); b.l(tm, "t", soak_h, "seed")
    soak_p = b.n("Threshold", 12, 10, inputs={"at": 0.06}); b.l(soak_h, "value", soak_p, "x")   # on = keeps (94%)
    soak = b.n("Select", 13, 10, inputs={"a": 1.0}); b.l(floor, "result", soak, "on"); b.l(soak_p, "value", soak, "b")
    stays = b.n("Multiply", 11, 5); b.l(stays0, "result", stays, "a"); b.l(soak, "result", stays, "b")
    fas = b.n("Threshold", 8, 9, inputs={"at": 0.5}); b.l(fa, "value", fas, "x")
    empty = b.n("Not", 9, 8); b.l(hs, "on", empty, "on")
    arr0 = b.n("Multiply", 10, 8); b.l(fas, "value", arr0, "a"); b.l(empty, "result", arr0, "b")
    arrives = b.n("Multiply", 11, 8); b.l(arr0, "result", arrives, "a"); b.l(eqA, "result", arrives, "b")
    # the pour: grains appear near the lid's centre at the pour rate, more on a beat
    rate = b.n("Remap", 1, 0, {"out_lo": 0.0, "out_hi": 0.35}); b.l(sp, "value", rate, "x")
    kick = b.n("Envelope", 1, 6, {"attack": 5.0, "release": 200.0}); b.l(au, "hit", kick, "x")
    ks = b.n("Select", 2, 6, inputs={"a": 0.0}); b.l(k1, "on", ks, "on"); b.l(kick, "value", ks, "b")
    r2 = b.n("Add", 2, 7); b.l(rate, "result", r2, "a"); b.l(ks, "result", r2, "b")
    ring = b.n("Cube ring", 1, 8)
    top = b.n("Threshold", 3, 11, inputs={"at": 0.22}); b.l(ring, "depth", top, "x")     # on = away from the lid centre
    at_top = b.n("Not", 4, 11); b.l(top, "on", at_top, "on")
    hsh = b.n("Hash", 3, 12); b.l(co, "u", hsh, "x"); b.l(co, "v", hsh, "y"); b.l(tm, "t", hsh, "seed")
    pour_on = b.n("Threshold", 4, 12); b.l(r2, "result", pour_on, "x"); b.l(hsh, "value", pour_on, "at")   # rate >= hash
    pour = b.n("Multiply", 5, 12); b.l(pour_on, "value", pour, "a"); b.l(at_top, "result", pour, "b")
    s1 = b.n("Max", 11, 6); b.l(stays, "result", s1, "a"); b.l(arrives, "result", s1, "b")
    grain = b.n("Max", 12, 6); b.l(s1, "result", grain, "a"); b.l(pour, "result", grain, "b")
    b.l(grain, "result", b.n("Field write", 13, 6, {"field": 0}), "value")
    # colour: by height along gravity, the pile darker than the falling grains
    h = b.n("Dot 3", 12, 8); b.l(pos, "x", h, "ax"); b.l(pos, "y", h, "ay"); b.l(pos, "z", h, "az"); b.l(g0, "gx", h, "bx"); b.l(g0, "gy", h, "by"); b.l(g0, "gz", h, "bz")
    hi = b.n("Remap", 13, 8, {"in_lo": -1.0, "in_hi": 1.0, "out_lo": 0.15, "out_hi": 0.8}); b.l(h, "result", hi, "x")
    glow = b.n("Remap", 1, 1, {"out_lo": 0.3, "out_hi": 1.0}); b.l(it, "value", glow, "x")
    bri = b.n("Multiply", 13, 7); b.l(grain, "result", bri, "a"); b.l(glow, "result", bri, "b")
    pal = b.n("Palette", 14, 7); b.l(hi, "result", pal, "index"); b.l(bri, "result", pal, "brightness")
    out = b.n("Output", 15, 7); b.l(pal, "color", out, "color")
    return b.save("gyro_sand.json")


def breakout():
    """Breakout, as far as a per-pixel graph will go: the ball is two
    triangle waves on the ring (it bounces off the sides and the top), the
    paddle at the bottom edge follows it, and the bricks are a Field seeded
    on the first frame and cleared where the ball has passed. The ball does
    not bounce off the bricks - that would need the game's own loop."""
    b = GB("Breakout")
    sp = b.n("Speed", 0, 0, {"label": "Ball speed", "default": 120})
    it = b.n("Intensity", 0, 1, {"label": "Glow", "default": 200})
    c1 = b.n("Custom 1", 0, 2, {"label": "Paddle width", "default": 110})
    c2 = b.n("Custom 2", 0, 3, {"label": "Brick depth", "default": 140})
    b.n("Effect settings", 0, 4, {"palette": 11, "audio": "none"})
    fr = b.n("Frame count", 0, 5)
    ring = b.n("Cube ring", 1, 5)
    co = b.n("Coords", 1, 7)
    # the ball: around bounces wall to wall, depth bounces rim to bottom
    rate = b.n("Remap", 1, 0, {"out_lo": 0.05, "out_hi": 0.6}); b.l(sp, "value", rate, "x")
    ta = b.n("Integrate", 2, 0, {"wrap": 1.0}); b.l(rate, "result", ta, "rate")
    r13 = b.n("Multiply", 1, 1, inputs={"b": 0.77}); b.l(rate, "result", r13, "a")
    tb = b.n("Integrate", 2, 1, {"wrap": 1.0}); b.l(r13, "result", tb, "rate")
    bx = b.n("Wave", 3, 0, {"shape": "triangle"}, inputs={"cycles": 1.0}); b.l(ta, "value", bx, "x")
    by0 = b.n("Wave", 3, 1, {"shape": "triangle"}, inputs={"cycles": 1.0}); b.l(tb, "value", by0, "x")
    by = b.n("Remap", 4, 1, {"out_lo": 0.05, "out_hi": 0.93}); b.l(by0, "value", by, "x")
    # distance from this pixel to the ball, on the ring (around wraps)
    da = b.n("Subtract", 2, 5); b.l(ring, "around", da, "a"); b.l(bx, "value", da, "b")
    daw = b.n("Modulo", 3, 5, inputs={"m": 1.0}); b.l(da, "result", daw, "x")
    dam = b.n("Subtract", 4, 5, inputs={"b": 0.5}); b.l(daw, "result", dam, "a")
    dax = b.n("Abs", 5, 5); b.l(dam, "result", dax, "x")
    dx = b.n("Subtract", 6, 5, inputs={"a": 0.5}); b.l(dax, "result", dx, "b")     # 0..0.5 wrapped distance
    dd = b.n("Subtract", 2, 6); b.l(ring, "depth", dd, "a"); b.l(by, "result", dd, "b")
    dxs = b.n("Multiply", 7, 5, inputs={"b": 4.0}); b.l(dx, "result", dxs, "a")     # around is 4 faces long
    dist = b.n("Length", 8, 5); b.l(dxs, "result", dist, "x"); b.l(dd, "result", dist, "y")
    ball = b.n("Smoothstep", 9, 5, {"e0": 0.09, "e1": 0.02}); b.l(dist, "result", ball, "x")
    # the paddle: a bar at the bottom edge under the ball
    pw = b.n("Remap", 1, 2, {"out_lo": 0.02, "out_hi": 0.09}); b.l(c1, "value", pw, "x")
    pin = b.n("Threshold", 9, 7); b.l(pw, "result", pin, "x"); b.l(dx, "result", pin, "at")          # on when width >= dx
    prow = b.n("Threshold", 3, 7, inputs={"at": 0.94}); b.l(ring, "depth", prow, "x")
    paddle = b.n("Multiply", 10, 7); b.l(pin, "value", paddle, "a"); b.l(prow, "value", paddle, "b")
    # the bricks: a field, full on the first frame down to Brick depth, cleared where the ball is
    bd = b.n("Remap", 1, 3, {"out_lo": 0.15, "out_hi": 0.6}); b.l(c2, "value", bd, "x")
    inrow = b.n("Threshold", 3, 8); b.l(bd, "result", inrow, "x"); b.l(ring, "depth", inrow, "at")     # depth <= brick depth
    rim = b.n("Threshold", 3, 9, inputs={"at": 0.1}); b.l(ring, "depth", rim, "x")                     # not the lid's middle
    seed = b.n("Multiply", 4, 8); b.l(inrow, "value", seed, "a"); b.l(rim, "value", seed, "b")
    old = b.n("Field", 4, 9, {"field": 0}); b.l(co, "u", old, "u"); b.l(co, "v", old, "v")
    hitb = b.n("Threshold", 9, 6, inputs={"at": 0.5}); b.l(ball, "result", hitb, "x")
    nothit = b.n("Not", 10, 6); b.l(hitb, "on", nothit, "on")
    kept = b.n("Multiply", 5, 9); b.l(old, "value", kept, "a"); b.l(nothit, "result", kept, "b")
    brick = b.n("Select", 6, 8); b.l(fr, "first", brick, "on"); b.l(kept, "result", brick, "a"); b.l(seed, "result", brick, "b")
    b.l(brick, "result", b.n("Field write", 7, 8, {"field": 0}), "value")
    # colour: bricks by row, the paddle and ball white
    row = b.n("Multiply", 7, 9, inputs={"b": 3.0}); b.l(ring, "depth", row, "a")
    bpal = b.n("Palette", 8, 9); b.l(row, "result", bpal, "index"); b.l(brick, "result", bpal, "brightness")
    white = b.n("Colour", 10, 8, {"rgb": [255, 255, 255]})
    glow = b.n("Remap", 1, 1, {"out_lo": 0.3, "out_hi": 1.0}); b.l(it, "value", glow, "x")
    pb = b.n("Max", 11, 6); b.l(ball, "result", pb, "a"); b.l(paddle, "result", pb, "b")
    pbg = b.n("Multiply", 12, 6); b.l(pb, "result", pbg, "a"); b.l(glow, "result", pbg, "b")
    mix = b.n("Blend", 13, 7, {"mode": "over"}); b.l(bpal, "color", mix, "under"); b.l(white, "color", mix, "over"); b.l(pbg, "result", mix, "amount")
    out = b.n("Output", 14, 7); b.l(mix, "color", out, "color")
    return b.save("breakout.json")


# ---------------------------------------------------------------------------
# The fourth five: Cube Axes, Liquid Tunnel, Question Block, Feigenbaum, Liquid.
# ---------------------------------------------------------------------------
def cube_axes():
    """Cube Axes: the position as colour - red is x, green y, blue z. The
    calibration effect: if a face comes out the wrong way round, this shows it."""
    b = GB("Cube Axes")
    b.n("Effect settings", 0, 0, {"palette": 11, "dimensions": "2-D"})
    pos = b.n("Position", 0, 1)
    r = b.n("Remap", 1, 0, {"in_lo": -1.0, "in_hi": 1.0}); b.l(pos, "x", r, "x")
    g = b.n("Remap", 1, 1, {"in_lo": -1.0, "in_hi": 1.0}); b.l(pos, "y", g, "x")
    bl = b.n("Remap", 1, 2, {"in_lo": -1.0, "in_hi": 1.0}); b.l(pos, "z", bl, "x")
    c = b.n("Combine", 2, 1); b.l(r, "result", c, "r"); b.l(g, "result", c, "g"); b.l(bl, "result", c, "b")
    out = b.n("Output", 3, 1); b.l(c, "color", out, "color")
    return b.save("cube_axes.json")


def liquid_tunnel():
    """Liquid Tunnel: stereographic radius about the lid gives ln(r), the
    Mercator coordinate, so a scroll along it is a zoom down a tunnel; a
    Gray-Scott medium grows tendrils in that chart, folded by a dihedral
    symmetry, and lit as a height field with a Fresnel rim."""
    b = GB("Liquid Tunnel")
    sp = b.n("Speed", 0, 0, {"label": "Flow", "default": 80})
    it = b.n("Intensity", 0, 1, {"label": "Fill", "default": 128})
    c1 = b.n("Custom 1", 0, 2, {"label": "Medium", "default": 100})
    c2 = b.n("Custom 2", 0, 3, {"label": "Gloss", "default": 150})
    c3 = b.n("Custom 3", 0, 4, {"label": "Symmetry", "default": 2})
    k1 = b.n("Check 1", 0, 5, {"label": "Beat surge", "default": True})
    k2 = b.n("Check 2", 0, 6, {"label": "Fresnel", "default": True})
    au = b.n("Audio", 0, 7)
    b.n("Effect settings", 0, 8, {"palette": 11, "audio": "frequency"})
    d = b.n("Direction", 1, 6)
    # stereographic from the bottom pole: r = sqrt(u^2 + v^2) with u = x/(1+z)
    den = b.n("Add", 2, 7, inputs={"a": 1.02}); b.l(d, "nz", den, "b")
    u = b.n("Divide", 3, 6); b.l(d, "nx", u, "a"); b.l(den, "result", u, "b")
    v = b.n("Divide", 3, 7); b.l(d, "ny", v, "a"); b.l(den, "result", v, "b")
    r = b.n("Length", 4, 6); b.l(u, "result", r, "x"); b.l(v, "result", r, "y")
    rc = b.n("Clamp", 5, 6, {"lo": 0.06, "hi": 3.0}); b.l(r, "result", rc, "x")      # the vanishing point is clamped
    lr = b.n("Log", 6, 6); b.l(rc, "result", lr, "x")
    # the azimuth, folded: symmetry n mirrors the tunnel n times round
    ang = b.n("Coords", 1, 8)
    sym = b.n("Remap", 1, 3, {"out_lo": 1.0, "out_hi": 6.99}); b.l(c3, "value", sym, "x")
    nsym = b.n("Floor", 2, 3); b.l(sym, "result", nsym, "x")
    az = b.n("Multiply", 4, 8); b.l(d, "nx", az, "a")      # placeholder replaced below
    # azimuth from u, v directly
    b.g.remove(az)
    atan_ = b.n("Rotate", 4, 8, inputs={"turns": 0.0}); b.l(u, "result", atan_, "x"); b.l(v, "result", atan_, "y")
    # a turn count from the direction: use Cube ring's around (same azimuth)
    ring = b.n("Cube ring", 1, 9)
    ta = b.n("Multiply", 5, 8); b.l(ring, "around", ta, "a"); b.l(nsym, "result", ta, "b")
    tf = b.n("Fract", 6, 8); b.l(ta, "result", tf, "x")
    tri = b.n("Wave", 7, 8, {"shape": "triangle"}, inputs={"cycles": 1.0, "phase": 0.0}); b.l(tf, "result", tri, "x")   # the mirror
    # the medium, scrolled down the tunnel at Flow (a kick surges it)
    fl = b.n("Remap", 1, 0, {"out_lo": 0.02, "out_hi": 0.5}); b.l(sp, "value", fl, "x")
    kick = b.n("Envelope", 1, 7, {"attack": 10.0, "release": 350.0}); b.l(au, "hit", kick, "x")
    ks = b.n("Select", 2, 5, inputs={"a": 0.0}); b.l(k1, "on", ks, "on"); b.l(kick, "value", ks, "b")
    sg = b.n("Add", 3, 5, inputs={"a": 1.0}); b.l(ks, "result", sg, "b")
    fr = b.n("Multiply", 4, 5); b.l(fl, "result", fr, "a"); b.l(sg, "result", fr, "b")
    scroll = b.n("Integrate", 5, 5, {"wrap": 1.0}); b.l(fr, "result", scroll, "rate")
    lscaled = b.n("Multiply", 7, 6, inputs={"b": 0.35}); b.l(lr, "result", lscaled, "a")      # ln r spans ~ -2.8..1.1
    lv = b.n("Add", 8, 6); b.l(lscaled, "result", lv, "a"); b.l(scroll, "value", lv, "b")
    lvf = b.n("Fract", 9, 6); b.l(lv, "result", lvf, "x")
    feed = b.n("Remap", 1, 2, {"out_lo": 0.03, "out_hi": 0.055}); b.l(c1, "value", feed, "x")
    med = b.n("Reaction diffusion", 10, 7, {"feed": 0.037, "kill": 0.06, "steps": 2, "seed": 0.02})
    b.l(tri, "value", med, "u"); b.l(lvf, "result", med, "v")
    # a height field lit by a fake normal: the medium's V, its slope along the tunnel (a second read a step on)
    lv2 = b.n("Add", 8, 7, inputs={"b": 0.03}); b.l(lv, "result", lv2, "a")
    lvf2 = b.n("Fract", 9, 7); b.l(lv2, "result", lvf2, "x")
    med2 = b.n("Reaction diffusion", 10, 9, {"feed": 0.037, "kill": 0.06, "steps": 2, "seed": 0.02})
    b.l(tri, "value", med2, "u"); b.l(lvf2, "result", med2, "v")
    slope = b.n("Subtract", 11, 8); b.l(med2, "v", slope, "a"); b.l(med, "v", slope, "b")
    gl = b.n("Remap", 1, 4, {"out_lo": 0.0, "out_hi": 14.0}); b.l(c2, "value", gl, "x")
    shade = b.n("Multiply", 12, 8); b.l(slope, "result", shade, "a"); b.l(gl, "result", shade, "b")
    lit = b.n("Add", 13, 8, inputs={"a": 0.5}); b.l(shade, "result", lit, "b")
    litc = b.n("Clamp", 14, 8, {"lo": 0.0, "hi": 1.0}); b.l(lit, "result", litc, "x")
    # fresnel: the rim of the tunnel (large r) glows
    fres = b.n("Smoothstep", 6, 9, {"e0": 1.2, "e1": 2.6}); b.l(rc, "result", fres, "x")
    fs = b.n("Select", 7, 9, inputs={"a": 0.0}); b.l(k2, "on", fs, "on"); b.l(fres, "result", fs, "b")
    fs2 = b.n("Multiply", 8, 9, inputs={"b": 0.35}); b.l(fs, "result", fs2, "a")
    # brightness: the medium's V, shaded, plus the rim; hue from position down the tunnel
    fill = b.n("Remap", 1, 1, {"out_lo": 0.4, "out_hi": 1.6}); b.l(it, "value", fill, "x")
    vlift = b.n("Smoothstep", 11, 7, {"e0": 0.03, "e1": 0.3}); b.l(med, "v", vlift, "x")
    body = b.n("Multiply", 12, 7); b.l(vlift, "result", body, "a"); b.l(litc, "result", body, "b")
    body2 = b.n("Multiply", 13, 7); b.l(body, "result", body2, "a"); b.l(fill, "result", body2, "b")
    bri = b.n("Add", 14, 7); b.l(body2, "result", bri, "a"); b.l(fs2, "result", bri, "b")
    hue = b.n("Integrate", 12, 6, {"wrap": 1.0}, inputs={"rate": 0.03})
    hi = b.n("Add", 13, 6); b.l(lvf, "result", hi, "a"); b.l(hue, "value", hi, "b")
    hi2 = b.n("Multiply", 14, 6, inputs={"b": 0.5}); b.l(hi, "result", hi2, "a")
    pal = b.n("Palette", 15, 7); b.l(hi2, "result", pal, "index"); b.l(bri, "result", pal, "brightness")
    out = b.n("Output", 16, 7); b.l(pal, "color", out, "color")
    return b.save("liquid_tunnel.json")


def question_block():
    """Question Block: every face wears the 16 x 16 sprite. A beat bumps the
    block, then the item reel spins and slows, then the item shows for a hold,
    then the block is back. The cycle is one clock reset by the beat; the reel
    is a decelerating count into three items."""
    b = GB("Question Block")
    sp = b.n("Speed", 0, 0, {"label": "Reel speed", "default": 140})
    it = b.n("Intensity", 0, 1, {"label": "Brightness", "default": 140})
    c1 = b.n("Custom 1", 0, 2, {"label": "Hold time", "default": 110})
    k1 = b.n("Check 1", 0, 3, {"label": "Hit on beat", "default": True})
    au = b.n("Audio", 0, 4)
    b.n("Effect settings", 0, 5, {"palette": 11, "audio": "volume", "dimensions": "2-D"})
    face = b.n("Cube face", 1, 4)
    # the clock since the last hit - a hit counts only when the block is idle,
    # which needs last frame's clock: the one loop, through a Delay
    spin_t = b.n("Remap", 1, 0, {"out_lo": 3.0, "out_hi": 0.8}); b.l(sp, "value", spin_t, "x")
    hold = b.n("Remap", 1, 2, {"out_lo": 0.8, "out_hi": 4.0}); b.l(c1, "value", hold, "x")
    endr = b.n("Add", 2, 2); b.l(spin_t, "result", endr, "a"); b.l(hold, "result", endr, "b")
    hit = b.n("Select", 1, 3, inputs={"a": False, "b": True}); b.l(k1, "on", hit, "on")
    beat_on = b.n("Multiply", 2, 3); b.l(au, "beat", beat_on, "a"); b.l(hit, "result", beat_on, "b")
    last = b.n("Delay", 2, 4)
    idle = b.n("Threshold", 3, 4); b.l(last, "value", idle, "x"); b.l(endr, "result", idle, "at")     # on = the cycle is over
    go = b.n("Multiply", 3, 2); b.l(beat_on, "result", go, "a"); b.l(idle, "value", go, "b")
    since = b.n("Integrate", 3, 3, {"wrap": 0.0}, inputs={"rate": 1.0}); b.l(go, "result", since, "reset")
    b.l(since, "value", last, "x")
    # phases: bump 0..0.25 s, spin to `spin`, result to `spin + hold`, then idle
    bump = b.n("Threshold", 4, 2, inputs={"at": 0.25}); b.l(since, "value", bump, "x")           # on = past the bump
    spinning = b.n("Threshold", 4, 3); b.l(spin_t, "result", spinning, "x"); b.l(since, "value", spinning, "at")   # on = still spinning
    showing = b.n("Threshold", 4, 4); b.l(endr, "result", showing, "x"); b.l(since, "value", showing, "at")        # on = still within the show
    # the reel: a decelerating count, frozen after spin_t
    prog = b.n("Divide", 5, 3); b.l(since, "value", prog, "a"); b.l(spin_t, "result", prog, "b")
    pc = b.n("Clamp", 6, 3, {"lo": 0.0, "hi": 1.0}); b.l(prog, "result", pc, "x")
    ease = b.n("Smoothstep", 7, 3, {"e0": 0.0, "e1": 1.0}); b.l(pc, "result", ease, "x")
    steps = b.n("Multiply", 8, 3, inputs={"b": 7.0}); b.l(ease, "result", steps, "a")
    stepi = b.n("Floor", 9, 3); b.l(steps, "result", stepi, "x")
    item = b.n("Modulo", 10, 3, inputs={"m": 3.0}); b.l(stepi, "result", item, "x")
    # the bump lifts the sprite; the sprite's own row/column from the face
    lift = b.n("Select", 5, 2, inputs={"a": 0.12, "b": 0.0}); b.l(bump, "on", lift, "on")
    vb = b.n("Add", 6, 2); b.l(face, "b", vb, "a"); b.l(lift, "result", vb, "b")
    vflip = b.n("Subtract", 7, 2, inputs={"a": 1.0}); b.l(vb, "result", vflip, "b")      # rows run top-down
    # the sprites: the block, and three items the reel lands on
    block = b.n("Bitmap", 8, 5, {"rows": "0000000000000000/0111111111111110/0102222222222010/0122223333222210/0122233223322210/0122233223322210/0122222233222210/0122222332222210/0122223322222210/0122223322222210/0122222222222210/0122222332222210/0122222332222210/0102222222222010/0111111111111110/0000000000000000"})
    mush = b.n("Bitmap", 8, 6, {"rows": "................/................/.....000000...../...0000000000.../..002220022200../..002220022200../.000222002220000/.00000000000000./.00000000000000./..000000000000../...1111111111.../...1222222221.../...1222222221.../...1111111111.../................/................"})
    star = b.n("Bitmap", 8, 7, {"rows": "................/.......00......./......0000....../......0000....../0000000000000000/.00000000000000./..000000000000../...0000000000.../...0000000000.../..00000..00000../..0000....0000../.000........000./.00..........00./................/................/................"})
    coin = b.n("Bitmap", 8, 8, {"rows": "................/................/......0000....../....00000000..../...0000000000.../...0000220000.../...0000220000.../...0000220000.../...0000220000.../...0000220000.../...0000000000.../....00000000..../......0000....../................/................/................"})
    for bm in (block, mush, star, coin):
        b.l(face, "a", bm, "u"); b.l(vflip, "result", bm, "v")
    cblock = b.n("Colour pick", 9, 5, {"c0": [70, 35, 0], "c1": [255, 185, 70], "c2": [230, 140, 20], "c3": [255, 250, 225]}); b.l(block, "slot", cblock, "index")
    cmush = b.n("Colour pick", 9, 6, {"c0": [225, 40, 25], "c1": [235, 195, 150], "c2": [255, 255, 255], "c3": [0, 0, 0]}); b.l(mush, "slot", cmush, "index")
    cstar = b.n("Colour pick", 9, 7, {"c0": [255, 220, 0], "c1": [255, 255, 255], "c2": [255, 150, 0], "c3": [0, 0, 0]}); b.l(star, "slot", cstar, "index")
    ccoin = b.n("Colour pick", 9, 8, {"c0": [255, 195, 0], "c1": [165, 110, 0], "c2": [255, 255, 200], "c3": [0, 0, 0]}); b.l(coin, "slot", ccoin, "index")
    # which item: 0 mushroom, 1 star, 2 coin; masked by its own transparency
    is1 = b.n("Threshold", 10, 6, inputs={"at": 0.5}); b.l(item, "result", is1, "x")
    is2 = b.n("Threshold", 10, 7, inputs={"at": 1.5}); b.l(item, "result", is2, "x")
    m_m = b.n("Mask", 10, 5); b.l(cmush, "color", m_m, "color"); b.l(mush, "on", m_m, "mask")
    m_s = b.n("Mask", 10, 8); b.l(cstar, "color", m_s, "color"); b.l(star, "on", m_s, "mask")
    m_c = b.n("Mask", 10, 9); b.l(ccoin, "color", m_c, "color"); b.l(coin, "on", m_c, "mask")
    pick1 = b.n("Blend", 11, 6, {"mode": "over"}); b.l(m_m, "color", pick1, "under"); b.l(m_s, "color", pick1, "over"); b.l(is1, "value", pick1, "amount")
    pick2 = b.n("Blend", 12, 7, {"mode": "over"}); b.l(pick1, "color", pick2, "under"); b.l(m_c, "color", pick2, "over"); b.l(is2, "value", pick2, "amount")
    # the block shows when idle or bumping; the item while spinning or showing
    m_b = b.n("Mask", 10, 4); b.l(cblock, "color", m_b, "color"); b.l(block, "on", m_b, "mask")
    active = b.n("Multiply", 11, 3); b.l(bump, "value", active, "a"); b.l(showing, "value", active, "b")   # past the bump and still within the show
    shown = b.n("Blend", 13, 5, {"mode": "over"}); b.l(m_b, "color", shown, "under"); b.l(pick2, "color", shown, "over"); b.l(active, "result", shown, "amount")
    bri = b.n("Remap", 1, 1, {"out_lo": 0.25, "out_hi": 1.0}); b.l(it, "value", bri, "x")
    lit = b.n("Scale", 14, 5); b.l(shown, "color", lit, "color"); b.l(bri, "result", lit, "by")
    out = b.n("Output", 15, 5); b.l(lit, "color", out, "color")
    return b.save("question_block.json")


def feigenbaum():
    """Feigenbaum: the bifurcation diagram of x -> x^2 + c, drawn on the
    stereographic plane about the lid, its parameter window shrinking toward
    the Myrberg-Feigenbaum point at -1.401155 and its orbit window with it,
    at the two ratios that make the picture map onto itself one doubling
    later - the endless zoom into the fig tree."""
    b = GB("Feigenbaum")
    sp = b.n("Speed", 0, 0, {"label": "Zoom speed", "default": 90})
    it = b.n("Intensity", 0, 1, {"label": "Brightness", "default": 210})
    c1 = b.n("Custom 1", 0, 2, {"label": "Spread", "default": 120})
    c2 = b.n("Custom 2", 0, 3, {"label": "Trail", "default": 170})
    k1 = b.n("Check 1", 0, 4, {"label": "Beat surge", "default": True})
    au = b.n("Audio", 0, 5)
    b.n("Effect settings", 0, 6, {"palette": 11, "audio": "frequency"})
    d = b.n("Direction", 1, 5)
    den = b.n("Add", 2, 6, inputs={"a": 1.05}); b.l(d, "nz", den, "b")
    u = b.n("Divide", 3, 5); b.l(d, "nx", u, "a"); b.l(den, "result", u, "b")
    v = b.n("Divide", 3, 6); b.l(d, "ny", v, "a"); b.l(den, "result", v, "b")
    uu = b.n("Remap", 4, 5, {"in_lo": -2.4, "in_hi": 2.4}); b.l(u, "result", uu, "x")
    vv = b.n("Remap", 4, 6, {"in_lo": -2.4, "in_hi": 2.4}); b.l(v, "result", vv, "x")
    # the zoom phase, wrapping: one doubling per wrap
    zr = b.n("Remap", 1, 0, {"out_lo": 0.03, "out_hi": 0.3}); b.l(sp, "value", zr, "x")
    kick = b.n("Envelope", 1, 6, {"attack": 10.0, "release": 400.0}); b.l(au, "hit", kick, "x")
    ks = b.n("Select", 2, 4, inputs={"a": 0.0}); b.l(k1, "on", ks, "on"); b.l(kick, "value", ks, "b")
    sg = b.n("Add", 3, 4, inputs={"a": 1.0}); b.l(ks, "result", sg, "b")
    zr2 = b.n("Multiply", 4, 4); b.l(zr, "result", zr2, "a"); b.l(sg, "result", zr2, "b")
    t = b.n("Integrate", 5, 4, {"wrap": 1.0}); b.l(zr2, "result", t, "rate")
    # the windows: c about -1.401155, width W0 * delta^-t; x about 0, width X0 * alpha^-t
    sc = b.n("Remap", 1, 2, {"out_lo": 0.4, "out_hi": 2.6}); b.l(c1, "value", sc, "x")
    ld = b.n("Multiply", 6, 3, inputs={"b": -1.5411}); b.l(t, "value", ld, "a")        # ln(4.6692)
    wd = b.n("Exp", 7, 3); b.l(ld, "result", wd, "x")
    wc = b.n("Multiply", 8, 3, inputs={"b": 0.06}); b.l(wd, "result", wc, "a")
    wc2 = b.n("Multiply", 9, 3); b.l(wc, "result", wc2, "a"); b.l(sc, "result", wc2, "b")
    la = b.n("Multiply", 6, 4, inputs={"b": -0.9175}); b.l(t, "value", la, "a")        # ln(2.5029)
    wa = b.n("Exp", 7, 4); b.l(la, "result", wa, "x")
    wx = b.n("Multiply", 8, 4, inputs={"b": 1.2}); b.l(wa, "result", wx, "a")
    clo = b.n("Subtract", 10, 2, inputs={"a": -1.401155}); b.l(wc2, "result", clo, "b")
    chi = b.n("Add", 10, 3, inputs={"a": -1.401155}); b.l(wc2, "result", chi, "b")
    xlo = b.n("Multiply", 10, 4, inputs={"b": -1.0}); b.l(wx, "result", xlo, "a")
    bif = b.n("Bifurcation", 11, 5, {"trail": 0.93, "orbits": 10})
    b.l(uu, "result", bif, "u"); b.l(vv, "result", bif, "v")
    b.l(clo, "result", bif, "c_lo"); b.l(chi, "result", bif, "c_hi"); b.l(xlo, "result", bif, "x_lo"); b.l(wx, "result", bif, "x_hi")
    tr = b.n("Remap", 1, 3, {"out_lo": 0.6, "out_hi": 0.97}); b.l(c2, "value", tr, "x")
    # (the trail is a param; the slider is shown for parity and drives the glow instead)
    gain = b.n("Remap", 1, 1, {"out_lo": 0.4, "out_hi": 3.0}); b.l(it, "value", gain, "x")
    g2 = b.n("Multiply", 12, 5); b.l(bif, "density", g2, "a"); b.l(gain, "result", g2, "b")
    g3 = b.n("Multiply", 13, 5); b.l(g2, "result", g3, "a"); b.l(tr, "result", g3, "b")
    bri = b.n("Smoothstep", 14, 5, {"e0": 0.0, "e1": 0.25}); b.l(g3, "result", bri, "x")
    hue = b.n("Integrate", 12, 6, {"wrap": 1.0}, inputs={"rate": 0.02})
    hi = b.n("Add", 13, 6); b.l(vv, "result", hi, "a"); b.l(hue, "value", hi, "b")
    pal = b.n("Palette", 15, 5); b.l(hi, "result", pal, "index"); b.l(bri, "result", pal, "brightness")
    out = b.n("Output", 16, 5); b.l(pal, "color", out, "color")
    return b.save("feigenbaum.json")


def liquid():
    """Liquid: a plane cuts the solid and everything below it is wet. The
    plane's tilt is a spring that a beat kicks, so it sloshes and settles;
    ripples ride the surface; the lid becomes a pool when the level sits
    below it. One dot product per pixel is the whole trick."""
    b = GB("Liquid")
    sp = b.n("Speed", 0, 0, {"label": "Ripple speed", "default": 130})
    it = b.n("Intensity", 0, 1, {"label": "Surface", "default": 140})
    c1 = b.n("Custom 1", 0, 2, {"label": "Fill", "default": 130})
    c2 = b.n("Custom 2", 0, 3, {"label": "Slosh", "default": 120})
    c3 = b.n("Custom 3", 0, 4, {"label": "Ripple size", "default": 14})
    k1 = b.n("Check 1", 0, 5, {"label": "Bass fills", "default": True})
    k2 = b.n("Check 2", 0, 6, {"label": "Splash on beat", "default": True})
    au = b.n("Audio", 0, 7)
    tm = b.n("Time", 0, 8)
    b.n("Effect settings", 0, 9, {"palette": 9, "audio": "frequency"})
    pos = b.n("Position", 1, 6)
    # the tilt: two springs kicked by the beat, alternating sides
    sl = b.n("Remap", 1, 3, {"out_lo": 0.0, "out_hi": 1.4}); b.l(c2, "value", sl, "x")
    ks = b.n("Select", 1, 7, inputs={"a": 0.0}); b.l(k2, "on", ks, "on"); b.l(au, "hit", ks, "b")
    kk = b.n("Multiply", 2, 7); b.l(ks, "result", kk, "a"); b.l(sl, "result", kk, "b")
    side = b.n("Random hold", 2, 8); b.l(au, "beat", side, "trigger")
    sgn = b.n("Remap", 3, 8, {"out_lo": -1.0, "out_hi": 1.0}); b.l(side, "value", sgn, "x")
    kx = b.n("Multiply", 3, 7); b.l(kk, "result", kx, "a"); b.l(sgn, "result", kx, "b")
    ky = b.n("Multiply", 4, 8, inputs={"b": 0.6}); b.l(kk, "result", ky, "a")
    tx = b.n("Spring", 4, 6, {"hz": 0.9, "damping": 0.12}, inputs={"target": 0.0}); b.l(kx, "result", tx, "kick")
    ty = b.n("Spring", 5, 7, {"hz": 1.1, "damping": 0.12}, inputs={"target": 0.0}); b.l(ky, "result", ty, "kick")
    # height above the plane: n = (tx, ty, 1) . pos, normalised
    ln = b.n("Length", 6, 7, inputs={"z": 1.0}); b.l(tx, "value", ln, "x"); b.l(ty, "value", ln, "y")
    h0 = b.n("Dot 3", 6, 5, inputs={"bz": 1.0}); b.l(pos, "x", h0, "ax"); b.l(pos, "y", h0, "ay"); b.l(pos, "z", h0, "az"); b.l(tx, "value", h0, "bx"); b.l(ty, "value", h0, "by")
    h = b.n("Divide", 7, 5); b.l(h0, "result", h, "a"); b.l(ln, "result", h, "b")
    # the level: Fill, plus bass when asked
    lev0 = b.n("Remap", 1, 2, {"out_lo": -1.0, "out_hi": 1.1}); b.l(c1, "value", lev0, "x")
    bass = b.n("Envelope", 1, 5, {"attack": 30.0, "release": 400.0}); b.l(au, "bass", bass, "x")
    bs = b.n("Select", 2, 5, inputs={"a": 0.0}); b.l(k1, "on", bs, "on"); b.l(bass, "value", bs, "b")
    bs2 = b.n("Multiply", 3, 5, inputs={"b": 0.5}); b.l(bs, "result", bs2, "a")
    lev = b.n("Add", 4, 4); b.l(lev0, "result", lev, "a"); b.l(bs2, "result", lev, "b")
    # ripples on the surface
    rs = b.n("Remap", 1, 0, {"out_lo": 0.2, "out_hi": 2.0}); b.l(sp, "value", rs, "x")
    ph = b.n("Integrate", 2, 0, {"wrap": 1.0}); b.l(rs, "result", ph, "rate")
    rsz = b.n("Remap", 1, 4, {"out_lo": 0.02, "out_hi": 0.14}); b.l(c3, "value", rsz, "x")
    w1 = b.n("Multiply", 2, 1, inputs={"b": 1.7}); b.l(pos, "x", w1, "a")
    w1p = b.n("Add", 3, 1); b.l(w1, "result", w1p, "a"); b.l(ph, "value", w1p, "b")
    s1 = b.n("Sine", 4, 1); b.l(w1p, "result", s1, "x")
    w2 = b.n("Multiply", 2, 2, inputs={"b": 2.3}); b.l(pos, "y", w2, "a")
    w2p = b.n("Subtract", 3, 2); b.l(w2, "result", w2p, "a"); b.l(ph, "value", w2p, "b")
    s2 = b.n("Sine", 4, 2); b.l(w2p, "result", s2, "x")
    rip0 = b.n("Add", 5, 1); b.l(s1, "result", rip0, "a"); b.l(s2, "result", rip0, "b")
    rip = b.n("Multiply", 6, 1); b.l(rip0, "result", rip, "a"); b.l(rsz, "result", rip, "b")
    # sgn > 0 dry, < 0 wet; the meniscus a bright band around 0
    sg0 = b.n("Subtract", 8, 5); b.l(h, "result", sg0, "a"); b.l(lev, "result", sg0, "b")
    sgn_ = b.n("Subtract", 9, 5); b.l(sg0, "result", sgn_, "a"); b.l(rip, "result", sgn_, "b")
    sw = b.n("Remap", 1, 1, {"out_lo": 0.02, "out_hi": 0.12}); b.l(it, "value", sw, "x")
    wet = b.n("Threshold", 10, 4); b.l(sw, "result", wet, "x"); b.l(sgn_, "result", wet, "at")      # on = surface width >= sgn (wet or meniscus)
    depth = b.n("Multiply", 10, 6, inputs={"b": -1.0}); b.l(sgn_, "result", depth, "a")
    dsat = b.n("Clamp", 11, 6, {"lo": 0.0, "hi": 1.5}); b.l(depth, "result", dsat, "x")
    body_b = b.n("Remap", 12, 6, {"in_lo": 0.0, "in_hi": 1.5, "out_lo": 0.85, "out_hi": 0.35}); b.l(dsat, "result", body_b, "x")
    body_i = b.n("Remap", 12, 7, {"in_lo": 0.0, "in_hi": 1.5, "out_lo": 0.45, "out_hi": 0.75}); b.l(dsat, "result", body_i, "x")
    ripi = b.n("Multiply", 11, 8, inputs={"b": 0.6}); b.l(rip, "result", ripi, "a")
    idx = b.n("Add", 13, 7); b.l(body_i, "result", idx, "a"); b.l(ripi, "result", idx, "b")
    body = b.n("Palette", 14, 6); b.l(idx, "result", body, "index"); b.l(body_b, "result", body, "brightness")
    men_d = b.n("Abs", 11, 4); b.l(sgn_, "result", men_d, "x")
    men_n = b.n("Divide", 12, 4); b.l(men_d, "result", men_n, "a"); b.l(sw, "result", men_n, "b")
    men = b.n("Smoothstep", 13, 4, {"e0": 1.0, "e1": 0.0}); b.l(men_n, "result", men, "x")
    white = b.n("Colour", 13, 5, {"rgb": [210, 245, 255]})
    surf = b.n("Blend", 15, 5, {"mode": "over"}); b.l(body, "color", surf, "under"); b.l(white, "color", surf, "over"); b.l(men, "result", surf, "amount")
    vis = b.n("Mask", 16, 5); b.l(surf, "color", vis, "color"); b.l(wet, "value", vis, "mask")
    out = b.n("Output", 17, 5); b.l(vis, "color", out, "color")
    return b.save("liquid.json")


def smiley():
    """An image on every face: the Image node bakes assets/smiley.png into
    the effect at compile time. Right-click it for 'convert to Bitmap +
    Colour pick' and the picture becomes editable pixel art."""
    b = GB("Smiley")
    b.n("Effect settings", 0, 0, {"palette": 11, "dimensions": "2-D"})
    face = b.n("Cube face", 0, 1)
    img = b.n("Image", 1, 1, {"file": "assets/smiley.png", "width": 16, "height": 16, "colours": 6})
    b.l(face, "a", img, "u"); b.l(face, "b", img, "v")
    out = b.n("Output", 2, 1); b.l(img, "color", out, "color")
    return b.save("smiley.json")


def fireworks():
    """Fireworks: on each beat a burst of sparks leaves the middle of the lid
    with a random spread, falls down the walls under gravity and fades; a
    trickle of embers in between. The colour is the bin that was loudest at
    the burst; the wake is last frame faded."""
    b = GB("Fireworks")
    sp = b.n("Speed", 0, 0, {"label": "Launch speed", "default": 140})
    it = b.n("Intensity", 0, 1, {"label": "Burst size", "default": 150})
    c1 = b.n("Custom 1", 0, 2, {"label": "Gravity", "default": 120})
    c2 = b.n("Custom 2", 0, 3, {"label": "Trail", "default": 150})
    k1 = b.n("Check 1", 0, 4, {"label": "Bursts on the beat", "default": True})
    au = b.n("Audio", 0, 5)
    b.n("Effect settings", 0, 6, {"palette": 11, "audio": "frequency"})
    pos = b.n("Position", 1, 6)
    lb = b.n("Loudest bin", 1, 5)
    bb = b.n("Select", 1, 4, inputs={"a": False, "b": True}); b.l(k1, "on", bb, "on")
    burst = b.n("Multiply", 2, 4); b.l(au, "beat", burst, "a"); b.l(bb, "result", burst, "b")
    n = b.n("Remap", 1, 1, {"out_lo": 3.0, "out_hi": 24.0}); b.l(it, "value", n, "x")
    spd = b.n("Remap", 1, 0, {"out_lo": 0.4, "out_hi": 2.5}); b.l(sp, "value", spd, "x")
    grav = b.n("Remap", 1, 2, {"out_lo": -0.2, "out_hi": -3.0}); b.l(c1, "value", grav, "x")
    gv = b.n("Vector", 2, 2, inputs={"x": 0.0, "y": 0.0}); b.l(grav, "result", gv, "z")
    pt = b.n("Particles", 3, 3, {"max": 48, "random_pos": False, "on_surface": True, "floor": "die"},
             inputs={"rate": 2.0, "pos": [0.0, 0.0, 1.0], "velocity": [0.0, 0.0, 0.3], "drag": 0.3, "life": 2.5})
    b.l(burst, "result", pt, "burst"); b.l(n, "result", pt, "burst_count"); b.l(spd, "result", pt, "spread")
    b.l(gv, "v", pt, "gravity"); b.l(lb, "bin", pt, "tag")
    spr = b.n("Sprites", 4, 5, {"falloff": "soft"}, inputs={"size": 0.3}); b.l(pt, "slots", spr, "slots"); b.l(pos, "pos", spr, "pos")
    fade = b.n("Subtract", 5, 6, inputs={"a": 1.0}); b.l(spr, "age", fade, "b")
    hot = b.n("Smoothstep", 5, 5, {"e0": 0.0, "e1": 0.5}); b.l(spr, "value", hot, "x")
    bri = b.n("Multiply", 6, 5); b.l(hot, "result", bri, "a"); b.l(fade, "result", bri, "b")
    pal = b.n("Palette", 7, 5); b.l(spr, "tag", pal, "index"); b.l(bri, "result", pal, "brightness")
    prev = b.n("Previous", 6, 7)
    keep = b.n("Remap", 1, 3, {"out_lo": 0.5, "out_hi": 0.92}); b.l(c2, "value", keep, "x")
    fd = b.n("Fade", 7, 7); b.l(prev, "color", fd, "color"); b.l(keep, "result", fd, "keep")
    mix = b.n("Blend", 8, 6, {"mode": "max"}); b.l(fd, "color", mix, "under"); b.l(pal, "color", mix, "over")
    out = b.n("Output", 9, 6); b.l(mix, "color", out, "color")
    return b.save("fireworks.json")




# ---------------------------------------------------------------------------
# xLights' effects the firmware lacks, as graphs: Meteors, Spirals, Pinwheel,
# Curtain, Marquee, Shockwave, Butterfly, Snowstorm. Each in the studio's own
# terms - a hash a column, a wave on an angle, a beat kick on a radius.
def meteors():
    """Meteors: columns each falling at their own speed with a bright head
    and a fading tail, the palette colour a column's own."""
    b = GB("Meteors")
    sp = b.n("Speed", 0, 0, {"label": "Fall speed", "default": 128})
    it = b.n("Intensity", 0, 1, {"label": "Tail", "default": 120})
    c1 = b.n("Custom 1", 0, 2, {"label": "Columns", "default": 96})
    b.n("Effect settings", 0, 4, {"palette": 11, "dimensions": "both"})
    co = b.n("Coords", 1, 2)
    ncol = b.n("Remap", 1, 1, {"out_lo": 4.0, "out_hi": 32.0}); b.l(c1, "value", ncol, "x")
    cf = b.n("Multiply", 2, 1); b.l(co, "u", cf, "a"); b.l(ncol, "result", cf, "b")
    col = b.n("Floor", 3, 1); b.l(cf, "result", col, "x")
    h1 = b.n("Hash", 4, 0, inputs={"y": 0.0, "seed": 3.0}); b.l(col, "result", h1, "x")
    h2 = b.n("Hash", 4, 1, inputs={"y": 1.0, "seed": 3.0}); b.l(col, "result", h2, "x")
    spd = b.n("Remap", 1, 0, {"out_lo": 0.15, "out_hi": 1.6}); b.l(sp, "value", spd, "x")
    vary = b.n("Remap", 5, 0, {"out_lo": 0.4, "out_hi": 1.0}); b.l(h1, "value", vary, "x")
    speed = b.n("Multiply", 6, 0); b.l(vary, "result", speed, "a"); b.l(spd, "result", speed, "b")
    tt = b.n("Integrate", 2, 0, {"wrap": 0.0}, inputs={"rate": 1.0})
    pos = b.n("Multiply", 7, 0); b.l(tt, "value", pos, "a"); b.l(speed, "result", pos, "b")
    ph = b.n("Add", 8, 0); b.l(pos, "result", ph, "a"); b.l(h2, "value", ph, "b")
    head = b.n("Fract", 9, 0); b.l(ph, "result", head, "x")
    rel = b.n("Subtract", 9, 2); b.l(head, "result", rel, "a"); b.l(co, "v", rel, "b")
    behind = b.n("Modulo", 10, 2, inputs={"m": 1.0}); b.l(rel, "result", behind, "x")
    inv = b.n("Subtract", 11, 2, inputs={"a": 1.0}); b.l(behind, "result", inv, "b")
    tl = b.n("Remap", 1, 3, {"out_lo": 16.0, "out_hi": 3.0}); b.l(it, "value", tl, "x")
    tail = b.n("Power", 12, 2); b.l(inv, "result", tail, "x"); b.l(tl, "result", tail, "e")
    ishead = b.n("Threshold", 11, 3, inputs={"at": 0.04}); b.l(behind, "result", ishead, "x")
    headm = b.n("Select", 12, 3, inputs={"a": 1.0, "b": 0.0}); b.l(ishead, "on", headm, "on")
    pal = b.n("Palette", 13, 2); b.l(h1, "value", pal, "index"); b.l(tail, "result", pal, "brightness")
    white = b.n("Colour", 13, 3, {"rgb": [255, 255, 255]})
    mix = b.n("Blend", 14, 2, {"mode": "over"}); b.l(pal, "color", mix, "under"); b.l(white, "color", mix, "over"); b.l(headm, "result", mix, "amount")
    out = b.n("Output", 15, 2); b.l(mix, "color", out, "color")
    return b.save("meteors.json")


def spirals():
    """Spirals: arms wound round the centre, turning; the twist slider
    winds them tighter, intensity sets how many."""
    b = GB("Spirals")
    sp = b.n("Speed", 0, 0, {"label": "Turn speed", "default": 100})
    it = b.n("Intensity", 0, 1, {"label": "Arms", "default": 80})
    c1 = b.n("Custom 1", 0, 2, {"label": "Twist", "default": 128})
    b.n("Effect settings", 0, 4, {"palette": 11, "dimensions": "both"})
    co = b.n("Coords", 1, 2)
    arms = b.n("Remap", 1, 1, {"out_lo": 1.0, "out_hi": 6.0}); b.l(it, "value", arms, "x")
    armsf = b.n("Floor", 2, 1); b.l(arms, "result", armsf, "x")
    tw = b.n("Remap", 1, 3, {"out_lo": -3.0, "out_hi": 3.0}); b.l(c1, "value", tw, "x")
    ang = b.n("Multiply", 2, 2, inputs={"b": 0.15915}); b.l(co, "angle", ang, "a")           # turns
    a2 = b.n("Multiply", 3, 2); b.l(ang, "result", a2, "a"); b.l(armsf, "result", a2, "b")
    r2 = b.n("Multiply", 3, 3); b.l(co, "r", r2, "a"); b.l(tw, "result", r2, "b")
    spd = b.n("Remap", 1, 0, {"out_lo": -1.0, "out_hi": 1.0}); b.l(sp, "value", spd, "x")
    tt = b.n("Integrate", 2, 0, {"wrap": 0.0}); b.l(spd, "result", tt, "rate")
    s1 = b.n("Add", 4, 2); b.l(a2, "result", s1, "a"); b.l(r2, "result", s1, "b")
    s2 = b.n("Subtract", 5, 2); b.l(s1, "result", s2, "a"); b.l(tt, "value", s2, "b")
    wv = b.n("Wave", 6, 2, {"shape": "sine"}, inputs={"cycles": 1.0}); b.l(s2, "result", wv, "x")
    sharp = b.n("Smoothstep", 7, 2, {"e0": 0.35, "e1": 0.75}); b.l(wv, "value", sharp, "x")
    idx = b.n("Add", 7, 3); b.l(co, "r", idx, "a"); b.l(tt, "value", idx, "b")
    pal = b.n("Palette", 8, 2); b.l(idx, "result", pal, "index"); b.l(sharp, "result", pal, "brightness")
    out = b.n("Output", 9, 2); b.l(pal, "color", out, "color")
    return b.save("spirals.json")


def pinwheel():
    """Pinwheel: blades from the centre, turning; the duty slider makes the
    blades thin or fat, the colour goes round with them."""
    b = GB("Pinwheel")
    sp = b.n("Speed", 0, 0, {"label": "Turn speed", "default": 100})
    it = b.n("Intensity", 0, 1, {"label": "Blade width", "default": 128})
    c1 = b.n("Custom 1", 0, 2, {"label": "Blades", "default": 80})
    b.n("Effect settings", 0, 4, {"palette": 11, "dimensions": "both"})
    co = b.n("Coords", 1, 2)
    n = b.n("Remap", 1, 3, {"out_lo": 2.0, "out_hi": 12.0}); b.l(c1, "value", n, "x")
    nf = b.n("Floor", 2, 3); b.l(n, "result", nf, "x")
    duty = b.n("Remap", 1, 1, {"out_lo": 0.1, "out_hi": 0.9}); b.l(it, "value", duty, "x")
    spd = b.n("Remap", 1, 0, {"out_lo": -1.0, "out_hi": 1.0}); b.l(sp, "value", spd, "x")
    tt = b.n("Integrate", 2, 0, {"wrap": 0.0}); b.l(spd, "result", tt, "rate")
    ang = b.n("Multiply", 2, 2, inputs={"b": 0.15915}); b.l(co, "angle", ang, "a")
    st = b.n("Stripes", 3, 2); b.l(ang, "result", st, "x"); b.l(nf, "result", st, "count"); b.l(tt, "value", st, "phase"); b.l(duty, "result", st, "duty")
    idx = b.n("Add", 3, 1); b.l(ang, "result", idx, "a"); b.l(tt, "value", idx, "b")
    fade = b.n("Subtract", 3, 3, inputs={"a": 1.0}); b.l(co, "r", fade, "b")
    br = b.n("Multiply", 4, 2); b.l(st, "value", br, "a"); b.l(fade, "result", br, "b")
    pal = b.n("Palette", 5, 2); b.l(idx, "result", pal, "index"); b.l(br, "result", pal, "brightness")
    out = b.n("Output", 6, 2); b.l(pal, "color", out, "color")
    return b.save("pinwheel.json")


def curtain():
    """Curtain: the colour revealed from the middle out to the edges and
    covered again, a gradient down the drop; intensity sets how far it opens."""
    b = GB("Curtain")
    sp = b.n("Speed", 0, 0, {"label": "Open speed", "default": 80})
    it = b.n("Intensity", 0, 1, {"label": "Opens to", "default": 255})
    b.n("Effect settings", 0, 3, {"palette": 11, "dimensions": "both"})
    co = b.n("Coords", 1, 2)
    spd = b.n("Remap", 1, 0, {"out_lo": 0.05, "out_hi": 0.8}); b.l(sp, "value", spd, "x")
    tt = b.n("Integrate", 2, 0, {"wrap": 0.0}); b.l(spd, "result", tt, "rate")
    tri = b.n("Wave", 3, 0, {"shape": "triangle"}, inputs={"cycles": 1.0}); b.l(tt, "value", tri, "x")
    far = b.n("Remap", 1, 1, {"out_lo": 0.2, "out_hi": 1.0}); b.l(it, "value", far, "x")
    open_ = b.n("Multiply", 4, 0); b.l(tri, "value", open_, "a"); b.l(far, "result", open_, "b")
    ax = b.n("Abs", 2, 2); b.l(co, "cx", ax, "x")
    edge = b.n("Subtract", 5, 1); b.l(open_, "result", edge, "a"); b.l(ax, "result", edge, "b")   # lit inside the opening: the curtain draws back to reveal the colour
    soft = b.n("Smoothstep", 6, 1, {"e0": 0.0, "e1": 0.08}); b.l(edge, "result", soft, "x")
    idx = b.n("Add", 5, 2); b.l(co, "v", idx, "a"); b.l(tt, "value", idx, "b")
    pal = b.n("Palette", 7, 2); b.l(idx, "result", pal, "index"); b.l(soft, "result", pal, "brightness")
    out = b.n("Output", 8, 2); b.l(pal, "color", out, "color")
    return b.save("curtain.json")


def marquee():
    """Marquee: a theatre chase, bulbs on and off along the strip and
    marching; intensity sets how many are lit, the palette colours them."""
    b = GB("Marquee")
    sp = b.n("Speed", 0, 0, {"label": "March speed", "default": 128})
    it = b.n("Intensity", 0, 1, {"label": "Bulbs lit", "default": 128})
    c1 = b.n("Custom 1", 0, 2, {"label": "Bulbs", "default": 64})
    k1 = b.n("Check 1", 0, 3, {"label": "Reverse", "default": False})
    b.n("Effect settings", 0, 4, {"palette": 11, "dimensions": "both"})
    co = b.n("Coords", 1, 2)
    n = b.n("Remap", 1, 3, {"out_lo": 4.0, "out_hi": 24.0}); b.l(c1, "value", n, "x")
    nf = b.n("Floor", 2, 3); b.l(n, "result", nf, "x")
    duty = b.n("Remap", 1, 1, {"out_lo": 0.15, "out_hi": 0.85}); b.l(it, "value", duty, "x")
    spd = b.n("Remap", 1, 0, {"out_lo": 0.2, "out_hi": 3.0}); b.l(sp, "value", spd, "x")
    neg = b.n("Multiply", 2, 0, inputs={"b": -1.0}); b.l(spd, "result", neg, "a")
    dir_ = b.n("Select", 3, 0); b.l(k1, "on", dir_, "on"); b.l(neg, "result", dir_, "a"); b.l(spd, "result", dir_, "b")
    tt = b.n("Integrate", 4, 0, {"wrap": 0.0}); b.l(dir_, "result", tt, "rate")
    st = b.n("Stripes", 3, 2); b.l(co, "u", st, "x"); b.l(nf, "result", st, "count"); b.l(tt, "value", st, "phase"); b.l(duty, "result", st, "duty")
    pal = b.n("Palette", 4, 2); b.l(co, "u", pal, "index"); b.l(st, "value", pal, "brightness")
    out = b.n("Output", 5, 2); b.l(pal, "color", out, "color")
    return b.save("marquee.json")


def shockwave():
    """Shockwave: rings racing out from the centre, and a kick on the beat
    that throws the next one; intensity sets the ring's width."""
    b = GB("Shockwave")
    sp = b.n("Speed", 0, 0, {"label": "Ring speed", "default": 128})
    it = b.n("Intensity", 0, 1, {"label": "Ring width", "default": 100})
    c1 = b.n("Custom 1", 0, 2, {"label": "Rings", "default": 64})
    au = b.n("Audio", 0, 3)
    b.n("Effect settings", 0, 4, {"palette": 11, "dimensions": "both", "audio": "volume"})
    co = b.n("Coords", 1, 2)
    n = b.n("Remap", 1, 3, {"out_lo": 1.0, "out_hi": 5.0}); b.l(c1, "value", n, "x")
    spd = b.n("Remap", 1, 0, {"out_lo": 0.3, "out_hi": 2.5}); b.l(sp, "value", spd, "x")
    tt = b.n("Integrate", 2, 0, {"wrap": 0.0}); b.l(spd, "result", tt, "rate")
    kick = b.n("Beat kick", 3, 0, inputs={"throw": 0.5}); b.l(au, "beat", kick, "beat")
    t2 = b.n("Add", 4, 0); b.l(tt, "value", t2, "a"); b.l(kick, "phase", t2, "b")
    rr = b.n("Multiply", 2, 2); b.l(co, "r", rr, "a"); b.l(n, "result", rr, "b")
    ph = b.n("Subtract", 3, 2); b.l(rr, "result", ph, "a"); b.l(t2, "result", ph, "b")
    fr = b.n("Fract", 4, 2); b.l(ph, "result", fr, "x")
    w = b.n("Remap", 1, 1, {"out_lo": 0.05, "out_hi": 0.5}); b.l(it, "value", w, "x")
    band = b.n("Subtract", 5, 2, inputs={"a": 1.0}); b.l(fr, "result", band, "b")
    pw = b.n("Divide", 6, 2); b.l(band, "result", pw, "a"); b.l(w, "result", pw, "b")
    ring = b.n("Smoothstep", 7, 2, {"e0": 0.0, "e1": 1.0}); b.l(pw, "result", ring, "x")
    inv = b.n("Subtract", 8, 2, inputs={"a": 1.0}); b.l(ring, "result", inv, "b")
    fade = b.n("Subtract", 5, 3, inputs={"a": 1.2}); b.l(co, "r", fade, "b")
    br = b.n("Multiply", 9, 2); b.l(inv, "result", br, "a"); b.l(fade, "result", br, "b")
    pal = b.n("Palette", 10, 2); b.l(co, "r", pal, "index"); b.l(br, "result", pal, "brightness")
    out = b.n("Output", 11, 2); b.l(pal, "color", out, "color")
    return b.save("shockwave.json")


def butterfly():
    """Butterfly: xLights' own - the colour from (x^2 - y^2) sin(t + (x + y)k)
    over x^2 + y^2 - the wings folding as it turns."""
    b = GB("Butterfly")
    sp = b.n("Speed", 0, 0, {"label": "Speed", "default": 100})
    it = b.n("Intensity", 0, 1, {"label": "Detail", "default": 128})
    b.n("Effect settings", 0, 3, {"palette": 11, "dimensions": "both"})
    co = b.n("Coords", 1, 2)
    spd = b.n("Remap", 1, 0, {"out_lo": 0.1, "out_hi": 1.5}); b.l(sp, "value", spd, "x")
    tt = b.n("Integrate", 2, 0, {"wrap": 0.0}); b.l(spd, "result", tt, "rate")
    k = b.n("Remap", 1, 1, {"out_lo": 1.0, "out_hi": 8.0}); b.l(it, "value", k, "x")
    xx = b.n("Multiply", 2, 2); b.l(co, "cx", xx, "a"); b.l(co, "cx", xx, "b")
    yy = b.n("Multiply", 2, 3); b.l(co, "cy", yy, "a"); b.l(co, "cy", yy, "b")
    diff = b.n("Subtract", 3, 2); b.l(xx, "result", diff, "a"); b.l(yy, "result", diff, "b")
    summ = b.n("Add", 3, 3, inputs={"b": 0.05}); b.l(xx, "result", summ, "a"); b.l(yy, "result", summ, "b")
    xy = b.n("Add", 3, 4); b.l(co, "cx", xy, "a"); b.l(co, "cy", xy, "b")
    xyk = b.n("Multiply", 4, 4); b.l(xy, "result", xyk, "a"); b.l(k, "result", xyk, "b")
    arg = b.n("Add", 5, 4); b.l(xyk, "result", arg, "a"); b.l(tt, "value", arg, "b")
    sn = b.n("Wave", 6, 4, {"shape": "sine"}, inputs={"cycles": 1.0}); b.l(arg, "result", sn, "x")
    num = b.n("Multiply", 7, 3); b.l(diff, "result", num, "a"); b.l(sn, "value", num, "b")
    an = b.n("Abs", 8, 3); b.l(num, "result", an, "x")
    ratio = b.n("Divide", 9, 3); b.l(an, "result", ratio, "a"); b.l(summ, "result", ratio, "b")
    idx = b.n("Add", 10, 3); b.l(ratio, "result", idx, "a"); b.l(tt, "value", idx, "b")
    pal = b.n("Palette", 11, 3); b.l(idx, "result", pal, "index")
    out = b.n("Output", 12, 3); b.l(pal, "color", out, "color")
    return b.save("butterfly.json")


def snowstorm():
    """Snowstorm: flakes drifting down through noise, a twinkle on top,
    over a cold dark ground; intensity is how much snow."""
    b = GB("Snowstorm")
    sp = b.n("Speed", 0, 0, {"label": "Fall speed", "default": 100})
    it = b.n("Intensity", 0, 1, {"label": "Snow", "default": 128})
    c1 = b.n("Custom 1", 0, 2, {"label": "Wind", "default": 100})
    b.n("Effect settings", 0, 4, {"palette": 0, "dimensions": "both"})
    co = b.n("Coords", 1, 2)
    spd = b.n("Remap", 1, 0, {"out_lo": 0.1, "out_hi": 1.2}); b.l(sp, "value", spd, "x")
    tt = b.n("Integrate", 2, 0, {"wrap": 0.0}); b.l(spd, "result", tt, "rate")
    wind = b.n("Remap", 1, 3, {"out_lo": -0.5, "out_hi": 0.5}); b.l(c1, "value", wind, "x")
    wt = b.n("Multiply", 2, 3); b.l(wind, "result", wt, "a"); b.l(tt, "value", wt, "b")
    y = b.n("Subtract", 3, 2); b.l(co, "v", y, "a"); b.l(tt, "value", y, "b")
    x = b.n("Add", 3, 3); b.l(co, "u", x, "a"); b.l(wt, "result", x, "b")
    nz = b.n("Noise", 4, 2, {"octaves": 2}, inputs={"scale": 9.0, "z": 0.0}); b.l(x, "result", nz, "x"); b.l(y, "result", nz, "y")
    thr = b.n("Remap", 1, 1, {"out_lo": 0.78, "out_hi": 0.55}); b.l(it, "value", thr, "x")
    sub = b.n("Subtract", 4, 3); b.l(nz, "value", sub, "a"); b.l(thr, "result", sub, "b")
    flake = b.n("Smoothstep", 5, 2, {"e0": 0.0, "e1": 0.12}); b.l(sub, "result", flake, "x")
    tw = b.n("Sparkle", 5, 3, inputs={"density": 0.08, "seed": 2.0})
    lit = b.n("Max", 6, 2); b.l(flake, "result", lit, "a"); b.l(tw, "value", lit, "b")
    white = b.n("Colour", 6, 3, {"rgb": [235, 240, 255]})
    ground = b.n("Colour", 6, 4, {"rgb": [4, 8, 24]})
    mix = b.n("Blend", 7, 3, {"mode": "over"}); b.l(ground, "color", mix, "under"); b.l(white, "color", mix, "over"); b.l(lit, "result", mix, "amount")
    out = b.n("Output", 8, 3); b.l(mix, "color", out, "color")
    return b.save("snowstorm.json")


ALL = [slab_cut, cell_weave, truchet, ring_rain, box_fire, maelstrom, kaleidoscope, mandelbrot, watershed, moire,
       ripples, chladni, candy_knot, gyro_sand, breakout, cube_axes, liquid_tunnel, question_block, feigenbaum, liquid,
       smiley, fireworks, meteors, spirals, pinwheel, curtain, marquee, shockwave, butterfly, snowstorm]
STATIC_EXTRA = {"Smiley"}


STATIC = {"Cube Axes", "Smiley", "Question Block"}   # still by design (the block holds its item at the end of the run)


def check():
    """Compile every example to C++, build them all into one engine, run
    each for a moment with the fake audio and report lit pixels and motion.
    First, though: every node must be documented, or the check fails."""
    from native.nodedocs import gaps
    missing = gaps()
    if missing:
        print("  undocumented nodes or pins - write them in native/nodedocs.py:", ", ".join(missing))
        return False
    import numpy as np
    sys.path.insert(0, os.path.dirname(HERE))
    import build as B
    from native.toolchain import build_engine
    from native.engine import Engine
    tmp = os.path.join(HERE, "_check"); os.makedirs(tmp, exist_ok=True)
    srcs = []
    for fn in sorted(os.listdir(OUT)):
        g = G.load(os.path.join(OUT, fn))
        g.project_dir = HERE                              # examples/assets/... resolves
        p = os.path.join(tmp, fn[:-5] + ".cpp")
        open(p, "w", encoding="utf-8", newline="\n").write(g.compile())
        srcs.append(p)
    rep = build_engine(B.engine_sources(srcs, log=lambda *a: None),
                       [os.path.join(B.HERE, "shim"), os.path.join(B.ROOT, "usermods", "cube_fx"), B.GEN],
                       log=lambda *a: None)
    if not rep.ok:
        for e in rep.error_lines():
            if e[2].startswith("error"): print("  ", os.path.basename(e[0]), e[1], e[2])
        print(rep.link_output[-800:]); return False
    e = Engine(); e.load(rep.library)
    from native.synth import Synth
    syn = Synth()
    ok = True
    for fn in sorted(os.listdir(OUT)):
        name = G.load(os.path.join(OUT, fn)).name
        e.select(e.names.index(name))
        syn = Synth()                         # the beat clock follows the effect's own time
        frames = []
        for k in range(160):                  # long enough for the slow ones to get going
            syn.push(e)                       # the fake music: bins, volume, beats
            e.frame(); frames.append(np.asarray(e.rgb()).copy())
        lit = float((frames[-1].max(axis=2) > 8).mean())
        motion = float(np.abs(frames[-1].astype(int) - frames[-20].astype(int)).mean())
        good = lit > 0.03 and (motion > 0.2 or name in STATIC)
        ok &= good
        print(f"  {name:14s} lit {lit*100:5.1f}%  motion {motion:6.2f}  {'ok' if good else 'FLAT'}")
    # the scripted runtime: every example that the script subset can express
    # runs in the Studio Script effect too, and must light something
    from native.script import compile_script, settings_of, ScriptError
    si = e.script_effect()
    n_ok = n_no = 0
    for fn in sorted(os.listdir(OUT)):
        g = G.load(os.path.join(OUT, fn)); g.project_dir = HERE
        try:
            prog = compile_script(g)
        except ScriptError as ex:
            n_no += 1; continue
        if si is None or not e.script(prog):
            print(f"  script {g.name}: the engine did not take it"); ok = False; continue
        st = settings_of(g); pal = st.pop("pal")
        e.select(si, params=dict(st, pal=pal))
        s2 = Synth()
        for _ in range(60):
            s2.push(e); e.frame(28)
        lit = float((e.rgb().sum(axis=2) > 0).mean())
        if lit < 0.02:
            print(f"  script {g.name}: dark"); ok = False
        n_ok += 1
    print(f"  scripts: {n_ok} of {n_ok + n_no} examples run in the Studio Script effect")
    return ok


if __name__ == "__main__":
    for f in ALL:
        g = f(); print("wrote", g.name)
    if "--check" in sys.argv:
        sys.exit(0 if check() else 1)
