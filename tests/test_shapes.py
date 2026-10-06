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


def test_projections_put_every_led_in_a_cell():
    """A tree, a column, a ball seen from the front lost their backs to the front's cells; unrolled
    round the shape, or as a globe, every LED has a cell of its own - and the best fit finds that."""
    tree, sphere = [shapes.new_part("tree")], [shapes.new_part("sphere")]
    front = Geometry("shape", parts=tree, layout="grid")                       # a project from before: the front
    assert front.projection == "front" and front.collisions > 0
    around = Geometry("shape", parts=tree, layout="grid", projection="around")
    assert around.collisions == 0 and (around.w, around.h) == (8, 30)           # the eight strands, thirty tiers
    globe = Geometry("shape", parts=sphere, layout="grid", projection="globe")
    assert globe.collisions == 0 and (globe.w, globe.h) == (24, 12)             # the sphere's own rows and columns
    # the front, fitted: a frame's sides sit half a pitch off the grid, which np.round paired up (50 of 100 lost)
    frame = Geometry("shape", parts=[shapes.new_part("frame")], layout="grid", projection="front")
    assert frame.collisions == 0
    for kind, want in (("tree", "around"), ("frame", "front"), ("star", "top"), ("panel", "front")):
        g = Geometry("shape", parts=[shapes.new_part(kind)], layout="grid", projection="auto")
        assert g.projection == want and g.collisions == 0, (kind, g.projection, g.collisions)
    # a grid never past 256 a side, however dense the shape
    dense = Geometry("shape", parts=[shapes.new_part("polyhedron", per_edge=20)], layout="grid", projection="globe")
    assert dense.w <= 256 and dense.h <= 256
    g2 = Geometry.from_json(Geometry("shape", parts=tree, layout="grid", projection="auto").to_json())
    assert g2.projection == "around" and g2.collisions == 0


def _nn(P):
    D = np.linalg.norm(P[:, None] - P[None], axis=2)
    np.fill_diagonal(D, np.inf)
    return D.min(1)


def test_face_outlines_sit_in_their_faces():
    """A solid's faces outlined each on its own: two faces share every edge, so each outline is
    inset into its own face (they were on the edges, every LED on top of the neighbour face's), each
    LED flat in its face and facing the way it does (they faced out from the middle: 68 degrees off
    on a tetrahedron)."""
    for solid in ("tetrahedron", "cube", "octahedron", "icosahedron", "dodecahedron", "soccer ball"):
        part = shapes.new_part("polyhedron", solid=solid, mode="faces", per_edge=5, radius=12.0, inset=0.5)
        pos, nrm, _ = shapes.resolve([part])
        pos, nrm = pos.astype(np.float64), nrm.astype(np.float64)
        V, E, F = shapes.polyhedron(solid)
        Vs = V * np.float32(12.0)
        assert len(pos) == sum(len(f) for f in F) * 5
        assert _nn(pos).min() > 0.1, solid                                      # none on another's spot
        k = 0
        for f in shapes.face_order(Vs, F):
            B, Nb = pos[k:k + len(f) * 5], nrm[k:k + len(f) * 5]
            c = B.mean(0)
            n = np.linalg.svd(B - c)[2][-1]
            n = n if np.dot(n, c) > 0 else -n
            assert np.abs((B - c) @ n).max() < 1e-4, solid                      # flat in its face
            assert np.allclose(Nb, n, atol=1e-3), solid                         # facing as its face does, outward
            k += len(f) * 5
        Vd = Vs.astype(np.float64)
        for a_, b_ in E:                                                       # half a spacing in from every edge
            A, AB = Vd[a_], Vd[b_] - Vd[a_]
            t = np.clip(((pos - A) @ AB) / (AB @ AB), 0, 1)
            assert np.linalg.norm(pos - (A + t[:, None] * AB), axis=1).min() > 0.49, solid
    flat = shapes.new_part("polyhedron", solid="cube", mode="faces", per_edge=4, radius=6.0, inset=0.0)
    p0, _, _ = shapes.resolve([flat])
    assert _nn(p0.astype(np.float64)).min() < 1e-4                           # inset 0: on the edges, as before


def test_a_mesh_surface_is_a_pitch_apart():
    """LEDs over a mesh: a flat region a regular grid a pitch apart and half a pitch in from its
    border (a 10 x 10 square: 100, not 153 a 0.77 apart); a triangulated cube the same as a cube of
    squares; a thin triangle and a curved surface thinned, no two LEDs nearer than 0.98 of a pitch."""
    def mesh(V, F):
        m = shape_io.Mesh()
        m.v = np.asarray(V, np.float32)
        m.faces = [list(f) for f in F]
        return m.finish()
    sq = mesh([[0, 0, 0], [10, 0, 0], [10, 10, 0], [0, 10, 0]], [[0, 1, 2], [0, 2, 3]])
    P, N = shape_io.mesh_leds(sq, "surface", 1.0)
    assert len(P) == 100 and abs(_nn(P.astype(np.float64)).min() - 1.0) < 1e-6
    assert np.allclose(P[:, 0].min(), 0.5) and np.allclose(P[:, 0].max(), 9.5) and np.allclose(N, [0, 0, 1])
    C = np.array([[0, 0, 0], [10, 0, 0], [10, 10, 0], [0, 10, 0], [0, 0, 10], [10, 0, 10], [10, 10, 10], [0, 10, 10]], float)
    Q = [[0, 3, 2, 1], [4, 5, 6, 7], [0, 1, 5, 4], [1, 2, 6, 5], [2, 3, 7, 6], [3, 0, 4, 7]]
    quads, _ = shape_io.mesh_leds(mesh(C, Q), "surface", 1.0)
    tris, tn = shape_io.mesh_leds(mesh(C, [t for q in Q for t in ([q[0], q[1], q[2]], [q[0], q[2], q[3]])]), "surface", 1.0)
    assert len(quads) == len(tris) == 600 and (np.einsum("ij,ij->i", tn, tris - 5.0) > 0).all()
    thin, _ = shape_io.mesh_leds(mesh([[0, 0, 0], [20, 0, 0], [20, 2, 0]], [[0, 1, 2]]), "surface", 1.0)
    assert _nn(thin.astype(np.float64)).min() >= 0.97 and 15 <= len(thin) <= 40
    R, nu, nv = 5.0, 24, 12
    V = [[0, 0, R]] + [[R * np.sin(np.pi * i / nv) * np.cos(2 * np.pi * j / nu), R * np.sin(np.pi * i / nv) * np.sin(2 * np.pi * j / nu),
                        R * np.cos(np.pi * i / nv)] for i in range(1, nv) for j in range(nu)] + [[0, 0, -R]]
    F = [[0, 1 + j, 1 + (j + 1) % nu] for j in range(nu)]
    for i in range(nv - 2):
        for j in range(nu):
            a, b = 1 + i * nu + j, 1 + i * nu + (j + 1) % nu
            F += [[a, a + nu, b + nu], [a, b + nu, b]]
    F += [[len(V) - 1, 1 + (nv - 2) * nu + (j + 1) % nu, 1 + (nv - 2) * nu + j] for j in range(nu)]
    ball, bn = shape_io.mesh_leds(mesh(V, F), "surface", 1.0)
    d = _nn(ball.astype(np.float64))
    assert d.min() >= 0.97 and np.median(d) < 1.15 and 200 <= len(ball) <= 330
    assert np.abs(np.linalg.norm(ball, axis=1) - 5.0).max() < 0.15 and (np.einsum("ij,ij->i", bn, ball) > 0).all()


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
    assert len(pv) == 4 and len(pe) == 16 and len(ps) == 16 and ns.shape == (len(ps), 3)     # 4 x 4 a pitch apart
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


def test_audio_files_of_every_kind():
    """A 16-bit WAV read as it is; a float WAV (which Python's wave module
    refuses) and an MP3 and a FLAC made from it through ffmpeg, each the same
    tone at the same pace - and a clear refusal of the rest without ffmpeg."""
    import shutil, subprocess, tempfile, wave
    from native import audio
    tmp = tempfile.mkdtemp()
    try:
        rate = 22050
        t = np.arange(rate * 2) / rate
        x = (0.5 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)
        pcm = os.path.join(tmp, "tone.wav")
        with wave.open(pcm, "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate)
            w.writeframes((x * 32767).astype(np.int16).tobytes())
        a, r = audio.load(pcm)
        assert r == rate and len(a) == len(x) and abs(float(np.abs(a).max()) - 0.5) < 0.01
        assert audio.FileAudio(pcm).seconds == 2.0
        ff = shutil.which("ffmpeg")
        if not ff:
            try:
                audio.decode(pcm.replace(".wav", ".mp3"), ffmpeg=None)
                assert False, "decoded with no ffmpeg"
            except RuntimeError as e:
                assert "ffmpeg" in str(e)
            print("  (no ffmpeg: the MP3, FLAC and float WAV left out)")
            return
        for name, args in (("tone_f32.wav", ["-c:a", "pcm_f32le"]), ("tone.mp3", ["-b:a", "128k"]), ("tone.flac", [])):
            out = os.path.join(tmp, name)
            subprocess.run([ff, "-v", "error", "-y", "-i", pcm] + args + [out], check=True)
            a, r = audio.load(out)
            secs = len(a) / r
            # the same two seconds (an MP3 carries a little padding) at the same loudness
            assert abs(secs - 2.0) < 0.1 and abs(float(np.abs(a).max()) - 0.5) < 0.03, (name, secs, float(np.abs(a).max()))
            assert audio.FileAudio(out).seconds > 1.9
        try:
            wave.open(os.path.join(tmp, "tone_f32.wav")).close()
            assert False, "the wave module read a float WAV after all"
        except wave.Error:
            pass                                        # which is why load takes those through ffmpeg
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


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


def test_a_mesh_in_millimetres_is_refused_with_a_pitch():
    """A mesh reading that would place more LEDs than MESH_MAX is refused
    before any is placed - a 1 m triangle drawn in millimetres at pitch 1 is
    half a million - with a round pitch that gives about MESH_AIM (issue #7)."""
    import time
    m = shape_io.Mesh()
    m.v = np.array([[0, 0, 0], [1000, 0, 0], [0, 1000, 0]], np.float32)
    m.faces = [[0, 1, 2]]
    m.finish()
    assert abs(shape_io.mesh_estimate(m, "surface", 1.0) - 501501) < 2000
    t0 = time.perf_counter()
    try:
        shape_io.mesh_leds(m, "surface", 1.0)
        raise AssertionError("placed half a million LEDs")
    except shape_io.TooManyLeds as e:
        assert time.perf_counter() - t0 < 1.0 and e.pitch and "millimetres" in str(e), e
        pitch = e.pitch
    pts, _ = shape_io.mesh_leds(m, "surface", pitch)
    assert 0 < len(pts) <= shape_io.MESH_AIM * 1.2, (pitch, len(pts))
    assert abs(len(pts) - shape_io.mesh_estimate(m, "surface", pitch)) <= 0.1 * len(pts)
    e_pitch = shape_io.mesh_pitch_for(m, "edges", 1.0)                 # along the edges: 3,414 mm of them
    assert len(shape_io.mesh_leds(m, "edges", e_pitch)[0]) <= shape_io.MESH_AIM * 1.2
    assert len(shape_io.mesh_leds(m, "edges", 10.0)[0]) > 300           # under the cap: as it was
    assert shape_io._round_up(13.0) == 20.0 and shape_io._round_up(2.2) == 2.5 and shape_io._round_up(0.03) == 0.05


def test_points_that_are_not_numbers_are_left_out():
    """nan and inf rows - a script's division by zero - are left out of a
    points file and an xyz geometry, and counted; one inf used to turn every
    position of an xyz geometry into NaN, and the device's table to zeros."""
    g = Geometry("xyz", points=[[0, 0, 0], [1, 1, 1], [2, 0, 1], [float("inf"), 0, 0]])
    assert g.count == 3 and np.isfinite(g.pos).all()
    txt = _write("bad.csv", "\n".join(["x,y,z", "0,0,0", "1,nan,0", "2,0,inf", "1e999,0,0", "3,0,0", "4,5", ""]))
    info = {}
    pts, _ = shape_io.read_points(txt, info)
    assert pts[:, 0].tolist() == [0.0, 3.0] and info["skipped"] == 3
    g = Geometry.from_xyz_file(txt)
    assert g.count == 2 and g.skipped == 4 and np.isfinite(g.pos).all()   # and the row short of a column
    js = _write("bad.json", '[[0, 0, 0], [NaN, 1, 2], {"x": 1, "y": Infinity, "z": 0}, [5, 5, 5]]')
    g = Geometry.from_xyz_file(js)
    assert g.count == 2 and g.skipped == 2


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
