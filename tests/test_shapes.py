"""Shapes: parts into LEDs in wiring order, the grid layout, the readers
for meshes, xLights models and point lists, and the position table the
device gets. Run with  python -m pytest tests  from studio (or the
functions by hand)."""
import os
import struct
import sys
import tempfile

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from native import shapes, shape_io
from native.geometry import Geometry


def test_parts_resolve_in_wiring_order():
    ring = shapes.new_part("ring", n=12)
    strip = shapes.new_part("strip", n=5)
    strip["pos"] = [0, 0, 5]; strip["rot"] = [0, 0, 90]
    pos, nrm, owner = shapes.resolve([ring, strip])
    assert pos.shape == (17, 3) and nrm.shape == (17, 3)
    assert owner.tolist() == [0] * 12 + [1] * 5
    # the strip, turned 90 deg about Z, runs along Y at z = 5
    assert np.allclose(pos[12:, 2], 5.0) and np.allclose(pos[12:, 0], 0.0, atol=1e-5)
    assert pos[12, 1] < pos[16, 1]
    strip["reverse"] = True
    pos2, _, _ = shapes.resolve([ring, strip])
    assert pos2[12, 1] > pos2[16, 1]


def test_panel_serpentine_and_cube_faces():
    panel = shapes.new_part("panel", w=3, h=2, serpentine=True)
    pos, _, _ = shapes.resolve([panel])
    assert pos[0, 0] < pos[2, 0] and pos[3, 0] > pos[5, 0]      # row 1 runs back
    cube = shapes.new_part("cube", B=2)
    pos, nrm, _ = shapes.resolve([cube])
    assert len(pos) == 20 and set(map(tuple, np.round(nrm).astype(int))) == {(0, 1, 0), (-1, 0, 0), (0, 0, 1), (1, 0, 0), (0, -1, 0)}
    six = shapes.new_part("cube", B=2, six=True)
    assert shapes.part_count(six) == 24


def test_grid_layout_and_geometry():
    g = Geometry("shape", parts=[shapes.new_part("panel", w=4, h=3)], layout="grid")
    assert (g.w, g.h) == (4, 3) and g.count == 12
    assert g.phys.tolist() == [0, 1, 2, 3, 7, 6, 5, 4, 8, 9, 10, 11]
    g1 = Geometry("shape", parts=[shapes.new_part("ring", n=8)])
    assert (g1.w, g1.h) == (8, 1)
    t = g1.table()
    assert t[:4] == b"STGM"
    ver, w, h, flags = struct.unpack_from("<BHHH", t, 4)
    assert (ver, w, h, flags) == (1, 8, 1, 3) and len(t) == 11 + 8 * 6 + 8 * 2      # normals and parts
    parts = np.frombuffer(t[11 + 48:], np.uint8).reshape(8, 2)
    assert parts[:, 0].tolist() == [0] * 8 and parts[0, 1] == 0 and parts[-1, 1] == 255
    assert Geometry("cube", B=4).table() is None and Geometry("matrix", w=4, h=4).table() is None
    assert Geometry("sphere", w=8, h=4).table() is not None
    # round-trips through the project file
    g2 = Geometry.from_json(g.to_json())
    assert g2.describe() == g.describe() and g2.phys.tolist() == g.phys.tolist()


def test_reference_draws_but_does_not_light():
    ref = shapes.new_part("reference", vertices=[[0, 0, 0], [1, 0, 0], [1, 1, 0]], edges=[[0, 1], [1, 2]], file="t.obj")
    ref["pos"] = [5, 0, 0]
    pos, nrm, owner = shapes.resolve([ref, shapes.new_part("strip", n=3)])
    assert len(pos) == 3 and owner.tolist() == [1, 1, 1]
    segs = shapes.reference_segments([ref])
    assert segs.shape == (2, 2, 3) and segs[0, 0, 0] == 5.0
    assert len(shapes.resolve([ref])[0]) == 0
    g = Geometry("shape", parts=[ref])
    assert g.count == 1                                          # a placeholder pixel, so the engine has a segment


def test_chain_and_live_copies():
    pts = np.array([[0, 0, 0], [5, 0, 0], [1, 0, 0], [4, 0, 0]], np.float32)
    assert shapes.chain_order(pts, 0).tolist() == [0, 2, 3, 1]
    # copies: a row along X, every other one run back; then an exact mirror across X
    p = shapes.new_part("strip", n=3); p["pos"] = [3, 0, 0]
    p["copies"] = {"n": 3, "step": [10, 0, 0], "zigzag": True}
    pos, _, owner = shapes.resolve([p])
    assert len(pos) == 9 == shapes.part_count(p) and set(owner.tolist()) == {0}
    assert np.allclose(pos[:3, 0], [2, 3, 4]) and np.allclose(pos[3:6, 0], [14, 13, 12]) and np.allclose(pos[6:, 0], [22, 23, 24])
    p["mirror"] = {"x": True}
    pos, _, _ = shapes.resolve([p])
    assert len(pos) == 18 and np.allclose(pos[9:12, 0], [-2, -3, -4])
    # made separate: the same LEDs, in the same order
    q = shapes.separate(p)
    assert [x["kind"] for x in q] == ["strip", "strip", "strip", "points"]
    assert np.allclose(shapes.resolve(q)[0], pos, atol=1e-4)


def _write(name, text, mode="w"):
    d = tempfile.mkdtemp()
    p = os.path.join(d, name)
    with open(p, mode) as f:
        f.write(text)
    return p


def test_mesh_readers():
    obj = _write("box.obj", "v 0 0 0\nv 4 0 0\nv 4 4 0\nv 0 4 0\nf 1 2 3 4\n")
    m = shape_io.read_mesh(obj)
    assert len(m.v) == 4 and len(m.edges) == 4 and len(m.faces) == 1
    pv, _ = shape_io.mesh_leds(m, "vertices", 1.0)
    pe, _ = shape_io.mesh_leds(m, "edges", 1.0)
    ps, ns = shape_io.mesh_leds(m, "surface", 1.0)
    assert len(pv) == 4 and len(pe) == 16 and 20 <= len(ps) <= 30 and ns.shape == (len(ps), 3)
    ply = _write("t.ply", "ply\nformat ascii 1.0\nelement vertex 3\nproperty float x\nproperty float y\nproperty float z\n"
                          "element face 1\nproperty list uchar int vertex_indices\nend_header\n0 0 0\n2 0 0\n0 2 0\n3 0 1 2\n")
    m = shape_io.read_mesh(ply)
    assert len(m.v) == 3 and len(m.edges) == 3
    tris = [((0, 0, 0), (2, 0, 0), (0, 2, 0))]
    b = bytearray(80) + struct.pack("<I", 1)
    for t in tris:
        b += struct.pack("<3f", 0, 0, 1)
        for p in t:
            b += struct.pack("<3f", *p)
        b += b"\x00\x00"
    stl = _write("t.stl", bytes(b), "wb")
    m = shape_io.read_mesh(stl)
    assert len(m.v) == 3 and len(m.faces) == 1


def test_solids_polygons_and_the_soccer_ball():
    """The solids come out with the right counts (a soccer ball: 60
    vertices, 90 edges, 12 pentagons and 20 hexagons); a polygon has
    sides x per_side LEDs; a polyhedron split into parts keeps every
    LED where it was, in either mode."""
    from collections import Counter
    want = {"tetrahedron": (4, 6, {3: 4}), "cube": (8, 12, {4: 6}), "octahedron": (6, 12, {3: 8}),
            "dodecahedron": (20, 30, {5: 12}), "icosahedron": (12, 30, {3: 20}), "soccer ball": (60, 90, {5: 12, 6: 20})}
    for solid, (nv, ne, sides) in want.items():
        V, E, F = shapes.polyhedron(solid)
        assert (len(V), len(E)) == (nv, ne), solid
        assert dict(Counter(len(f) for f in F)) == sides, solid
        assert np.allclose(np.linalg.norm(V, axis=1), 1.0, atol=1e-5)
    assert len(shapes.part_points(shapes.new_part("polygon", sides=6, per_side=5))[0]) == 30
    for mode in ("edges", "faces"):
        part = shapes.new_part("polyhedron", solid="soccer ball", mode=mode, per_edge=3, radius=10.0)
        part["rot"] = [20, 30, 40]; part["pos"] = [1, 2, 3]
        whole, _, _ = shapes.resolve([part])
        pieces = shapes.split_part(part)
        assert len(pieces) == (90 if mode == "edges" else 32)
        split, _, _ = shapes.resolve(pieces)
        assert len(whole) == len(split) and np.allclose(whole, split, atol=1e-2), mode
    # a split face's +Z points outward
    q = shapes.split_part(shapes.new_part("polyhedron", solid="soccer ball", mode="faces", radius=10.0))[0]
    z = shapes.rotation(*q["rot"]) @ np.array([0, 0, 1.0])
    assert np.dot(z, np.asarray(q["pos"]) / np.linalg.norm(q["pos"])) > 0.9


def test_aim_and_euler():
    """aim_rotation lands a part's axis on a direction (any axis, any
    direction, the opposite one too); euler_of round-trips rotation()."""
    for rot in ([10, 20, 30], [0, 90, 0], [-45, 60, 120]):
        R = shapes.rotation(*rot)
        assert np.allclose(R, shapes.rotation(*shapes.euler_of(R)), atol=1e-5)
    for ax, d in (((1, 0, 0), (0, 0, 1)), ((0, 0, 1), (1, 1, 0)), ((0, 0, 1), (0, 0, -1)), ((0, -1, 0), (0.3, -0.5, 0.8))):
        R = shapes.rotation(*shapes.aim_rotation(ax, d, 33.0))
        assert np.allclose(R @ np.asarray(ax, float), np.asarray(d, float) / np.linalg.norm(d), atol=1e-4)
    p = shapes.aimed(shapes.new_part("polygon"), (0, 0, 1), 9.0)
    assert p["pos"] == [0.0, 0.0, 9.0]
    p = shapes.aimed(shapes.new_part("strip", n=4), (0, 1, 0), 5.0)
    pos, _, _ = shapes.resolve([p])
    assert np.allclose(pos[:, 0], 0, atol=1e-4) and np.allclose(pos[:, 2], 0, atol=1e-4)      # the strip now runs along Y


def test_xlights_layout():
    """An xLights layout: a matrix, a line, a custom model and a poly line
    come out with their counts where they stand; a kind the reader does
    not know is a strip and named."""
    xml = ('<xrgb><models>'
           '<model name="M" DisplayAs="Horiz Matrix" parm1="4" parm2="8" WorldPosX="0" WorldPosY="100" WorldPosZ="0" ScaleX="2" ScaleY="2"/>'
           '<model name="L" DisplayAs="Single Line" parm1="1" parm2="10" WorldPosX="-50" WorldPosY="0" WorldPosZ="0" X2="100" Y2="0" Z2="0"/>'
           '<model name="C" DisplayAs="Custom" parm1="3" parm2="2" CustomModel="1,,2;,3," WorldPosX="5" WorldPosY="5" WorldPosZ="5"/>'
           '<model name="P" DisplayAs="Poly Line" parm1="1" parm2="6" PointData="0,0,0,10,0,0"/>'
           '<model name="X" DisplayAs="Icicles" parm1="2" parm2="5" ScaleX="10"/>'
           '</models></xrgb>')
    d = tempfile.mkdtemp(); path = os.path.join(d, "xlights_rgbeffects.xml")
    open(path, "w").write(xml)
    parts, notes = shape_io.read_layout(path)
    counts = {q["name"]: shapes.part_count(q) for q in parts}
    assert counts == {"M": 32, "L": 10, "C": 3, "P": 6, "X": 10}
    pos, _, owner = shapes.resolve(parts)
    m = pos[owner == 0]
    assert abs(float(m[:, 2].mean()) - 100) < 1e-3 and abs(float(m[:, 0].max() - m[:, 0].min()) - 14) < 1e-3   # 8 wide at 2 apart, Y up -> Z up
    line = pos[owner == 1]
    assert abs(float(line[:, 0].min()) + 50) < 1e-3 and abs(float(line[:, 0].max()) - 50) < 1e-3
    assert any("X" in n for n in notes)


def test_xlights_models_as_the_kinds_they_are():
    """xLights' trees, stars, arches, spinners and window frames come in as
    the tree, star, arch, spokes and frame parts - their LEDs all there."""
    xml = ('<xrgb><models>'
           '<model name="T" DisplayAs="Tree 360" parm1="4" parm2="50" parm3="1" ScaleX="60" ScaleY="180" TreeSpiralRotations="0.5"/>'
           '<model name="S" DisplayAs="Star" parm1="1" parm2="50" parm3="5" ScaleX="40"/>'
           '<model name="A" DisplayAs="Arches" parm1="3" parm2="20" ScaleX="90" ScaleY="20"/>'
           '<model name="W" DisplayAs="Window Frame" parm1="20" parm2="10" parm3="20" ScaleX="80" ScaleY="40"/>'
           '<model name="R" DisplayAs="Spinner" parm1="1" parm2="10" parm3="6" ScaleX="30"/>'
           '</models></xrgb>')
    d = tempfile.mkdtemp(); path = os.path.join(d, "xlights_rgbeffects.xml")
    open(path, "w").write(xml)
    parts, notes = shape_io.read_layout(path)
    kinds = {q["name"]: q["kind"] for q in parts}
    assert kinds == {"T": "tree", "S": "star", "A 1": "arch", "A 2": "arch", "A 3": "arch", "W": "frame", "R": "spokes"}, kinds
    counts = {q["name"]: shapes.part_count(q) for q in parts}
    assert counts["T"] == 200 and counts["S"] == 50 and counts["A 2"] == 20 and counts["W"] == 60 and counts["R"] == 60, counts
    t = [q for q in parts if q["name"] == "T"][0]
    pos, _, _ = shapes.resolve([t])
    assert abs(float(np.ptp(pos[:, 2])) - 180) < 1.0 and abs(t["params"]["turns"] - 0.5) < 1e-9
    w = [q for q in parts if q["name"] == "W"][0]
    wp, _, _ = shapes.resolve([w])
    assert abs(float(np.ptp(wp[:, 0])) - 80) < 0.5                     # 80 wide: the sides' LEDs stand on its edges


def test_the_kinds_people_light():
    """Each kind of the ninth pass: its LEDs, spaced as it says."""
    def step(part):
        pos, _ = shapes.part_points(part)
        return pos, np.linalg.norm(np.diff(pos, axis=0), axis=1)
    pos, d = step(shapes.new_part("helix", n=40, radius=3.0, height=10.0))
    assert len(pos) == 40 and np.allclose(d, 1.0, atol=0.01) and abs(float(np.ptp(pos[:, 2])) - 10.0) < 1e-6   # a spacing along the curve
    pos, d = step(shapes.new_part("spiral", n=80, gap=2.0))
    assert len(pos) == 80 and d.min() > 0.9 and d.max() <= 1.0 + 1e-6 and abs(float(np.ptp(pos[:, 2]))) < 1e-9
    pos, d = step(shapes.new_part("arch", n=21))
    assert len(pos) == 21 and np.allclose(d, d[0], atol=1e-3) and abs(float(pos[:, 2].min())) < 1e-6        # the feet on the floor
    pos, _ = step(shapes.new_part("tree", strands=6, per_strand=20, height=30.0, base=20.0, top=2.0))
    assert len(pos) == 120 and abs(float(np.ptp(pos[:, 2])) - 30.0) < 1e-6
    assert pos[19, 2] > pos[0, 2] and pos[20, 2] > pos[39, 2]                                              # up one strand, down the next
    pos, d = step(shapes.new_part("star", points=5, per_edge=4))
    assert len(pos) == 40 and np.allclose(d[:3], 1.0, atol=1e-6)
    pos, _ = step(shapes.new_part("rings", counts="1,8,12"))
    assert len(pos) == 21 and np.allclose(pos[0], 0.0)
    pos, _ = step(shapes.new_part("frame", w=10, h=5, bottom=False))
    assert len(pos) == 20 and abs(float(pos[:, 2].min()) + 2.5) > 0.4                                     # no bottom row
    pos, _ = step(shapes.new_part("spokes", spokes=4, per_spoke=5, zigzag=True))
    assert len(pos) == 20 and abs(np.linalg.norm(pos[5]) - 5.0) < 1e-6 and abs(np.linalg.norm(pos[9]) - 1.0) < 1e-6   # back in along the second
    pos, _ = step(shapes.new_part("formula", n=11, x="i", y="t*10", z="n"))
    assert np.allclose(pos[:, 0], np.arange(11)) and np.allclose(pos[:, 1], np.arange(11)) and np.allclose(pos[:, 2], 11)
    assert shapes.formula_error(shapes.new_part("formula", x="1/0")) and not shapes.formula_error(shapes.new_part("formula"))


def test_beats_of_a_click_track():
    """A 128 bpm click track: the tempo within a beat a minute, the first beat near the first click."""
    from native import audio
    rate = 22050; secs = 20.0; bpm = 128.0
    t = np.arange(int(rate * secs)) / rate
    x = 0.05 * np.sin(2 * np.pi * 110 * t)
    for k in range(int(secs * bpm / 60.0)):
        s0 = int((0.25 + k * 60.0 / bpm) * rate)
        x[s0:s0 + 800] += np.exp(-np.arange(800) / 120.0) * 0.8
    got = audio.beats_of(x.astype(np.float32), rate)
    assert got is not None
    found, first, beats = got
    assert abs(found - bpm) < 1.0 and abs(first - 0.25) < 0.05 and len(beats) > 30


def test_ramps_become_sub_steps():
    """A step with a slider ramp: the device gets a sub-step a second, the
    slider stepping from the step's value to the end; without a ramp the
    step is itself."""
    from native import sequence
    st = {"name": "fade", "dur": 6.0, "trans": 0.5, "segments": [{"effect": "Rainbow", "params": {"sx": 20}, "bounds": [0, 0, 16, 1]}], "ramps": {"sx": 220}}
    subs = sequence.sub_steps(st)
    assert len(subs) == 6 and [q["segments"][0]["params"]["sx"] for q in subs] == [20, 60, 100, 140, 180, 220]
    assert subs[0]["trans"] == 0.5 and subs[1]["trans"] == 0.0 and abs(sum(q["dur"] for q in subs) - 6.0) < 1e-6
    assert sequence.sub_steps({"name": "plain", "dur": 3, "segments": st["segments"]}) == [{"name": "plain", "dur": 3, "segments": st["segments"]}]
    assert sequence.ramp_value(st, "sx", 0.5) == 120


def test_align_spread_match():
    parts = [shapes.new_part("ring", n=6) for _ in range(4)]
    for k, p in enumerate(parts):
        p["pos"] = [k * 3.0 + (1.0 if k == 2 else 0.0), float(k), 0.0]; p["scale"] = 1.0 + k
    out = shapes.aligned(parts, [1, 2, 3], 0, axis=1)
    assert [p["pos"][1] for p in out] == [0.0, 0.0, 0.0, 0.0] and [p["pos"][0] for p in out] == [0.0, 3.0, 7.0, 9.0]
    out = shapes.distributed(parts, [0, 1, 2, 3], axis=0)
    assert [p["pos"][0] for p in out] == [0.0, 3.0, 6.0, 9.0] and parts[2]["pos"][0] == 7.0     # the input untouched
    assert shapes.distributed(parts, [0, 1], axis=0) == parts
    out = shapes.matched(parts, [0, 1, 2, 3], 3, "scale")
    assert all(p["scale"] == 4.0 for p in out)
    out = shapes.matched(parts, [1], 0, "rot"); assert out[1]["rot"] == parts[0]["rot"]


def test_positions_export_reads_back():
    """The positions CSV of a shape of parts: one row an LED in wiring order,
    the part named; read back, the same points in the same order."""
    ring = shapes.new_part("ring", n=8); strip = shapes.new_part("strip", n=4); strip["pos"] = [0, 0, 3]
    g = Geometry("shape", parts=[ring, strip])
    path = _write("pos.csv", "")
    n = shape_io.write_points(g, path)
    assert n == 12
    lines = [l for l in open(path, encoding="utf-8") if not l.startswith("#")]
    assert len(lines) == 12 and lines[0].strip().endswith(",0,0,ring") and lines[-1].strip().endswith(",11,1,strip")
    pts, order = shape_io.read_points(path)
    assert pts.shape == (12, 3) and order is not None and list(order) == list(range(12))
    assert np.allclose(pts, np.asarray(g.pos)[np.asarray(g.phys)], atol=1e-3)
    assert shape_io.write_points(Geometry("cube", B=4), path) == 5 * 16       # a cube's five faces, the corners unlit


def test_xmodel_and_points():
    xm = _write("arrow.xmodel", '<custommodel name="Arrow" parm1="5" parm2="3" Depth="1" CustomModel=",,1,,;6,5,4,3,2;,,7,," />')
    m = shape_io.read_xmodel(xm)
    assert m["order"] == [1, 2, 3, 4, 5, 6, 7] and m["grid"][0:2] == (5, 3)
    assert m["grid"][2] == [-1, -1, 0, -1, -1, 5, 4, 3, 2, 1, -1, -1, 6, -1, -1]
    g = Geometry("shape", parts=[dict(shapes.new_part("points", points=m["points"].tolist()), name="arrow")],
                 layout="grid", grid=[m["grid"][0], m["grid"][1], m["grid"][2]])
    assert (g.w, g.h, g.count) == (5, 3, 7)
    csv = _write("p.csv", "x,y,z,i\n0,0,0,2\n1,0,0,1\n2,0,0,3\n")
    pts, order = shape_io.read_points(csv)
    assert pts[:, 0].tolist() == [1.0, 0.0, 2.0]


if __name__ == "__main__":
    import inspect
    bad = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and inspect.isfunction(fn):
            try:
                fn(); print("ok  ", name)
            except Exception as e:
                bad += 1; print("FAIL", name, repr(e))
    sys.exit(1 if bad else 0)
