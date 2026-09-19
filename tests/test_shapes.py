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


def test_chain_mirror_array():
    pts = np.array([[0, 0, 0], [5, 0, 0], [1, 0, 0], [4, 0, 0]], np.float32)
    assert shapes.chain_order(pts, 0).tolist() == [0, 2, 3, 1]
    p = shapes.new_part("strip", n=3); p["pos"] = [3, 0, 0]
    m = shapes.mirrored(p, 0)
    assert m["pos"][0] == -3
    arr = shapes.arrayed(p, 3, [10, 0, 0])
    assert [q["pos"][0] for q in arr] == [13, 23]


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
