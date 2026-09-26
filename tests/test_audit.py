"""Audits: every effect in the roster run on every geometry kind without
the engine faulting; which of WLED's stock effects the sim leaves out and
why, each with a reason; the GPU view's placement of every LED and
every cube face corner against the software renderer's projection, for
every geometry kind and several cameras; and every child process the app
starts, which must not open a console window over it. Run with
python tests/test_audit.py  (or pytest).
"""
import ast
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from native.geometry import Geometry               # noqa: E402

GEOMETRIES = [("strip", {"n": 150}), ("matrix", {"w": 32, "h": 16}), ("cube", {"B": 16}), ("cylinder", {"w": 24, "h": 10}),
              ("sphere", {"w": 24, "h": 12}), ("torus", {"w": 24, "h": 8}),
              ("xyz", {"points": [[float(i % 7), float(i // 7), float(i % 3)] for i in range(40)]})]


def test_every_effect_runs_on_every_geometry():
    """Five frames of each - a null read in an effect (three audio effects
    wrote to slots the sim did not provide) is an OSError here, a crash
    on the device's sim page."""
    from native.engine import Engine
    from native.synth import Synth
    e = Engine()
    bad, n = [], 0
    for kind, params in GEOMETRIES:
        e.set_geometry(Geometry(kind, **params))
        for i, name in enumerate(e.names):
            try:
                e.select(i)
                syn = Synth()
                for _ in range(5):
                    syn.push(e); e.frame()
                n += 1
            except OSError as ex:
                bad.append(f"{name} on {kind}: {ex}")
    print(f"  {n} effect x geometry runs")
    assert not bad, "\n".join(bad[:20])


def test_stock_skips_are_explained():
    """Every stock effect the sim leaves out is named with the reason, in
    build.py (the 2-D ones) or gen/stock1d_skip.json (the 1-D ones, from
    the compiler's own words); and the list stays short."""
    import build as B
    two_d = dict(B.STOCK_SKIP)
    p = os.path.join(ROOT, "gen", "stock1d_skip.json")
    one_d = json.load(open(p, encoding="utf-8")).get("skip", {}) if os.path.exists(p) else {}
    print(f"  2-D stock effects left out ({len(two_d)}):")
    for k, why in sorted(two_d.items()):
        print(f"    {k}: {why}")
    print(f"  1-D stock effects left out ({len(one_d)}):")
    for k, why in sorted(one_d.items()):
        print(f"    {k}: {why[:90]}")
    assert all(isinstance(v, str) and v.strip() for v in two_d.values()), "a 2-D skip without a reason"
    assert all(isinstance(v, str) and v.strip() for v in one_d.values()), "a 1-D skip without a reason"
    assert len(two_d) <= 6 and len(one_d) <= 24, "more stock effects left out than before - the extractor regressed?"


def _cameras():
    for yaw in (0.3, 1.2, 2.5, 4.0):
        for pitch in (-0.4, 0.2, 0.7):
            yield yaw, pitch, 3.2


# a call marked this way keeps its own flags: the two that must outlive the
# studio (the restart after a checkout, the updater's copy).
ON_PURPOSE = "console: on purpose"


def test_no_child_opens_a_console_window():
    """Every subprocess the app starts goes through native/procs.py.

    On Windows a process with no console of its own - the packaged
    windowed exe - gives each console child a NEW console window, so a
    Live rebuild flashed a black box over the graph, once per translation
    unit, on every edit. procs.run / procs.popen pass CREATE_NO_WINDOW;
    this fails when a new call site forgets."""
    bad = []
    for d, _, files in os.walk(os.path.join(ROOT, "native")):
        for f in sorted(files):
            if not f.endswith(".py"):
                continue
            path = os.path.join(d, f)
            rel = os.path.relpath(path, ROOT).replace("\\", "/")
            src = open(path, encoding="utf-8").read()
            if rel == "native/procs.py":
                continue
            tree = ast.parse(src, rel)
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                    continue
                if node.func.attr not in ("run", "Popen", "call", "check_call", "check_output"):
                    continue
                if not (isinstance(node.func.value, ast.Name) and node.func.value.id == "subprocess"):
                    continue
                lines = src.splitlines()[node.lineno - 1:(node.end_lineno or node.lineno)]
                if any(ON_PURPOSE in l for l in lines):
                    continue
                bad.append(f"{rel}:{node.lineno} subprocess.{node.func.attr} - use procs.run / procs.popen")
    assert not bad, "child processes that would open a console window:\n" + "\n".join(bad)


SIZE_KW = {"width", "height", "wrap", "indent", "init_width_or_weight", "horizontal_spacing", "thickness"}
# placeholders sized again before they are seen: the code editor's (and its invisible key catcher), the GPU
# view's drawlists, the popout's first image
SIZE_OK = {("native/codeedit.py", "__init__"), ("native/gpucube.py", "__init__"), ("native/popout.py", "frame")}


def _literal(v):
    return isinstance(v, ast.Constant) and isinstance(v.value, (int, float)) and not isinstance(v.value, bool) and v.value > 2


def test_every_control_size_is_at_the_interface_size():
    """A control's width, height or wrap - a dialog's, a swatch's, a drawn
    line's thickness, a drawn text's size - is laid out at 100% and given
    through typeface.px(): Settings > Appearance > Interface size scales
    them with the type. A new literal would stay 100% at 150% - a combo too
    narrow for its words. So would a helper's default (tip's wrap). Hairlines
    (2 px or less) and the placeholders in SIZE_OK are left; the graph's
    nodes are sized by its own zoom (self.px); a floatx's size is a count."""
    bad = []
    for d, _, files in os.walk(os.path.join(ROOT, "native")):
        for f in sorted(files):
            if not f.endswith(".py"):
                continue
            path = os.path.join(d, f)
            rel = os.path.relpath(path, ROOT).replace("\\", "/")
            src = open(path, encoding="utf-8").read()
            stack = []

            class V(ast.NodeVisitor):
                def visit_FunctionDef(self, n):
                    a = n.args
                    pairs = list(zip(a.args[len(a.args) - len(a.defaults):], a.defaults)) + \
                        [(k, v) for k, v in zip(a.kwonlyargs, a.kw_defaults) if v is not None]
                    for arg, dv in pairs:
                        if arg.arg in ("width", "height", "wrap", "indent") and _literal(dv):
                            bad.append(f"{rel}:{n.lineno} def {n.name}({arg.arg}={dv.value}) - None, then px({dv.value})")
                    stack.append(n.name); self.generic_visit(n); stack.pop()

                def visit_Call(self, n):
                    fn = n.func
                    if isinstance(fn, ast.Attribute) and isinstance(fn.value, ast.Name) and fn.value.id == "dpg" \
                            and (rel, stack[-1] if stack else "") not in SIZE_OK:
                        kws = SIZE_KW | ({"size"} if fn.attr == "draw_text" else set())
                        for k in n.keywords:
                            if k.arg in kws and _literal(k.value):
                                bad.append(f"{rel}:{n.lineno} dpg.{fn.attr}({k.arg}={k.value.value}) - px({k.value.value})")
                    self.generic_visit(n)
            V().visit(ast.parse(src, rel))
    assert not bad, "sizes that would not follow the interface size:\n" + "\n".join(bad)


FIELDS = {"add_combo", "add_input_text", "add_input_int", "add_input_float", "add_input_double", "add_input_intx",
          "add_input_floatx", "add_drag_int", "add_drag_float", "add_drag_intx", "add_drag_floatx", "add_slider_int",
          "add_slider_float", "add_color_edit", "add_listbox"}
# every field's words come before it now, the graph's node fields too (C7); nothing is excused
LABEL_AFTER_OK = set()


def test_no_field_is_labelled_after_itself():
    """Forms read left to right (C6): a field's words come before it - in a
    form row's label column (native/form.py) or leading it in a row of
    several - never as Dear PyGui's label, drawn after the control, where
    labels hugged fields of different widths and never lined up. A text
    straight after a field in a row (a horizontal group, form.row,
    form.under) - its label, the old way - fails too; a unit belongs inside
    the field's format. A line under a field (a hint, a caption) is not a
    label, nor is a separator between two fields (:, =, x)."""
    bad = []

    def made(node):
        """The dpg call an expression makes, through typeface.mono(...) and the like."""
        c = node.value if isinstance(node, (ast.Expr, ast.Assign)) else None
        while isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute) and c.func.attr in ("mono", "small", "label", "heading") and c.args:
            c = c.args[0]
        return c if isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute) else None

    def opens_row(item):
        """A `with` that opens a row: dpg.group(horizontal=True), form.row, form.under."""
        c = item.context_expr
        if not (isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)):
            return None
        if c.func.attr in ("row", "under") and isinstance(c.func.value, ast.Name) and c.func.value.id == "form":
            return True
        if c.func.attr == "group":
            return any(k.arg == "horizontal" and isinstance(k.value, ast.Constant) and k.value.value for k in c.keywords)
        if c.func.attr in ("child_window", "window", "tooltip", "table_row", "table", "collapsing_header", "tree_node"):
            return False
        return None

    def scan(body, rel, in_row):
        for a, b in zip(body, body[1:]):
            ca, cb = made(a), made(b)
            if in_row and ca is not None and cb is not None and ca.func.attr in FIELDS and cb.func.attr == "add_text" \
                    and cb.args and isinstance(cb.args[0], ast.Constant) and str(cb.args[0].value).strip() not in ("", ":", "=", "×"):
                bad.append(f"{rel}:{b.lineno} a text after dpg.{ca.func.attr} in a row: {cb.args[0].value!r} - before it, or inside its format")
        for st in body:
            if isinstance(st, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                scan(st.body, rel, False)
            elif isinstance(st, ast.With):
                row = in_row
                for item in st.items:
                    r = opens_row(item)
                    if r is not None:
                        row = r
                scan(st.body, rel, row)
            else:
                for field in ("body", "orelse", "finalbody"):
                    sub = getattr(st, field, None)
                    if isinstance(sub, list) and sub and isinstance(sub[0], ast.stmt):
                        scan(sub, rel, in_row)
                for h in getattr(st, "handlers", []) or []:
                    scan(h.body, rel, in_row)

    for d, _, files in os.walk(os.path.join(ROOT, "native")):
        for f in sorted(files):
            if not f.endswith(".py"):
                continue
            path = os.path.join(d, f)
            rel = os.path.relpath(path, ROOT).replace("\\", "/")
            if rel in LABEL_AFTER_OK:
                continue
            tree = ast.parse(open(path, encoding="utf-8").read(), rel)
            for node in ast.walk(tree):
                c = node if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) else None
                if c is not None and c.func.attr in FIELDS:
                    lab = next((k.value for k in c.keywords if k.arg == "label"), None)
                    if lab is not None and not (isinstance(lab, ast.Constant) and (lab.value in ("", None) or str(lab.value).startswith("##"))):
                        bad.append(f"{rel}:{c.lineno} dpg.{c.func.attr}(label=...) - its words in form.row / form.inline, before it")
            scan(tree.body, rel, False)
    assert not bad, "fields labelled after themselves:\n" + "\n".join(bad)


def test_every_number_is_the_one_control():
    """One number control (C7, native/num.py): the value on the track,
    drag, click to type, a fill for where it sits. A slider (a grab over
    the digits, or no digits at all) or a bare drag field made elsewhere
    would be a sixth kind again. Typed fields (input_int, input_float) stay
    for numbers that are typed - pins, ids, counts - and a drag of three
    (a position) for a vector."""
    bad = []
    for d, _, files in os.walk(os.path.join(ROOT, "native")):
        for f in sorted(files):
            if not f.endswith(".py"):
                continue
            rel = os.path.relpath(os.path.join(d, f), ROOT).replace("\\", "/")
            if rel == "native/num.py":
                continue
            for node in ast.walk(ast.parse(open(os.path.join(d, f), encoding="utf-8").read(), rel)):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name) \
                        and node.func.value.id == "dpg" and node.func.attr in ("add_slider_int", "add_slider_float", "add_slider_double",
                                                                               "add_drag_int", "add_drag_float", "add_drag_double"):
                    bad.append(f"{rel}:{node.lineno} dpg.{node.func.attr} - num.add")
    assert not bad, "number controls not the one control:\n" + "\n".join(bad)


def test_gpu_points_match_the_software_projection():
    """Every LED square the GPU path places sits where render.project puts
    the LED, for every geometry kind and camera - the two are the same
    maths, and must stay so."""
    import dearpygui.dearpygui as dpg
    from native.gpucube import PointQuads
    from native.render import project, frame_of, _camera
    dpg.create_context()
    bad = []
    try:
        with dpg.window(tag="w"):
            pass
        for kind, params in GEOMETRIES:
            g = Geometry(kind, **params)
            pos = np.asarray(g.pos, np.float32)[np.asarray(g.lit, bool)]
            pq = PointQuads("w", f"pq_{kind}", pos)
            size = 400
            pq.resize(size)
            for yaw, pitch, dist in _cameras():
                pq.camera(yaw, pitch, dist)
                sx, sy, ok = project(pos, size, yaw, pitch, dist, frame=frame_of(pos))
                # the k-th square shows the k-th farthest LED: read each square's centre and match it to its LED
                eye, R = _camera(yaw, pitch, dist)
                P = (pos - frame_of(pos)[0]) / frame_of(pos)[1]
                depth = -((P - eye) @ R.T)[:, 2]
                order = np.argsort(np.where(ok, -depth, np.inf))
                worst, checked = 0.0, 0
                for k, i in enumerate(order):
                    if not ok[i]:
                        continue
                    cfg = dpg.get_item_configuration(pq.items[k])
                    if not cfg.get("show"):
                        continue                              # off the frame: not placed
                    cx = (cfg["p1"][0] + cfg["p3"][0]) * 0.5; cy = (cfg["p1"][1] + cfg["p3"][1]) * 0.5
                    worst = max(worst, abs(cx - sx[i]), abs(cy - sy[i])); checked += 1
                if worst > 0.01:
                    bad.append(f"{kind} yaw {yaw} pitch {pitch}: a square {worst:.3f} px from its LED")
                if checked < len(pos) // 2:
                    bad.append(f"{kind} yaw {yaw} pitch {pitch}: only {checked} of {len(pos)} squares placed")
            dpg.delete_item(f"pq_{kind}")
    finally:
        dpg.destroy_context()
    assert not bad, "\n".join(bad)


def test_gpu_points_take_a_new_count_and_a_pan():
    """The cloud made again for another count (a part added: its colour
    texture deleted while the background picture drew it had left the name
    taken), and placed with a pan and the orthographic projection where
    render.project puts them."""
    import dearpygui.dearpygui as dpg
    from native.gpucube import PointQuads
    from native.render import project, frame_of
    dpg.create_context()
    try:
        with dpg.window(tag="w"):
            pass
        pos = np.random.RandomState(3).uniform(-5, 5, (40, 3)).astype(np.float32)
        pq = PointQuads("w", "pq_count", pos)
        pq.resize(400)
        for n in (60, 25, 60):                                   # more, fewer, more again
            p = np.random.RandomState(n).uniform(-5, 5, (n, 3)).astype(np.float32)
            pq.set_points(p)
            pq.colours(np.full((n, 3), 200, np.uint8))
            assert pq.n == n and len(pq.items) == n
        look, fr = (0.2, -0.1, 0.05), frame_of(p)
        for ortho in (False, True):
            pq.camera(-0.6, 0.75, 4.6, look=look, ortho=ortho)
            sx, sy, ok = project(p, 400, -0.6, 0.75, 4.6, frame=fr, look=look, ortho=ortho)
            shown = [dpg.get_item_configuration(q) for q in pq.items if dpg.get_item_configuration(q).get("show")]
            centres = [((c["p1"][0] + c["p3"][0]) / 2, (c["p1"][1] + c["p3"][1]) / 2) for c in shown]
            want = [(float(x), float(y)) for x, y, o in zip(sx, sy, ok) if o and 0 <= x <= 400 and 0 <= y <= 400]
            assert len(centres) >= len(want) - 2, (ortho, len(centres), len(want))
            assert all(any(abs(a - cx) < 0.02 and abs(b - cy) < 0.02 for cx, cy in centres) for a, b in want), ortho
    finally:
        dpg.destroy_context()


def test_gpu_cube_faces_match_the_software_projection():
    """The cube's faces on the GPU: each visible face's corner cells land
    on render()'s projection of the face corners, camera after camera."""
    import dearpygui.dearpygui as dpg
    from native.gpucube import CubeQuads, FACES, N
    from native.render import _camera
    dpg.create_context()
    bad = []
    try:
        with dpg.window(tag="w"):
            pass
        with dpg.texture_registry():
            dpg.add_dynamic_texture(48, 48, [0.0] * (48 * 48 * 4), tag="tex")
        cq = CubeQuads("w", "cq", "tex")
        size = 400
        cq.resize(size)
        f = (size * 0.5) / np.tan(np.radians(38.0) * 0.5)
        for yaw, pitch, dist in _cameras():
            cq.camera(yaw, pitch, dist)
            eye, R = _camera(yaw, pitch, dist)
            for fi, fc in enumerate(FACES):
                c = fc["corners"]
                if np.dot(c.mean(axis=0), c.mean(axis=0) - eye) >= 0 or fi == 5:
                    continue                                  # culled on both sides
                cam = (c - eye) @ R.T
                scr = np.stack([size * 0.5 + f * cam[:, 0] / -cam[:, 2], size * 0.5 - f * cam[:, 1] / -cam[:, 2]], 1)
                # the software renderer's face corners, against the outer corners of the GPU's corner cells
                quads = cq.items[fi]
                first, last = dpg.get_item_configuration(quads[0]), dpg.get_item_configuration(quads[N * N - 1])
                if not first.get("show"):
                    bad.append(f"face {fi} yaw {yaw} pitch {pitch}: hidden on the GPU, drawn in software"); continue
                gpu = np.array([first["p1"], last["p3"]])          # corner 0 and corner 2, each grown 0.35 px outward
                want = np.array([scr[0], scr[2]])
                err = float(np.abs(gpu - want).max())
                if err > 0.6:
                    bad.append(f"face {fi} yaw {yaw} pitch {pitch}: corners {err:.2f} px apart")
    finally:
        dpg.destroy_context()
    assert not bad, "\n".join(bad)


def test_the_view_draws_unlit_leds_as_dots_and_a_floor():
    """C16: where the view asks, an LED that is off is a dim dot - on a
    cube's face, in a point cloud (smaller than a lit LED), in the GPU
    cube's texture, behind a GPU point whose own square goes transparent -
    and the shape stands on a faint floor, left out when seen from below.
    Asked for neither, the renderers draw what they always did."""
    import dearpygui.dearpygui as dpg
    from native import render
    from native.gpucube import PointQuads
    B = 8
    off = np.zeros((3 * B, 3 * B, 3), np.uint8)
    lit = np.full_like(off, 200)
    plain = render.render(off, B, 240, 0.6, 0.5, 5.0)
    assert not plain.any()                                     # all off, asked for nothing: black
    dots = render.render(off, B, 240, 0.6, 0.5, 5.0, unlit=render.UNLIT)
    faces = render.render(lit, B, 240, 0.6, 0.5, 5.0).any(axis=2).sum()
    grey = (dots == render.UNLIT).all(axis=2).sum()
    assert 0.05 < grey / faces < 0.3, grey / faces            # dots, not tiles: black round each
    floor = render.render(off, B, 240, 0.6, 0.5, 5.0, floor=True)
    assert floor.any() and not render.render(off, B, 240, 0.6, -0.5, 5.0, floor=True).any()   # from below: none
    d = render.dotted(off, 4)
    assert d.shape == (3 * B * 4, 3 * B * 4, 3) and (d == render.UNLIT).all(axis=2).sum() == (3 * B) ** 2 * 4
    assert not (render.dotted(lit, 4) == render.UNLIT).all(axis=2).any()
    pos = np.array([[-2.0, 0.0, 0.0], [2.0, 0.0, 0.0]], np.float32)
    rgb = np.array([[255, 0, 0], [0, 0, 0]], np.uint8)
    img = render.render_points(pos, rgb, 240, 0.0, 0.0, 5.0, unlit=render.UNLIT)
    red, grey = (img == (255, 0, 0)).all(axis=2).sum(), (img == render.UNLIT).all(axis=2).sum()
    assert 0 < grey < red / 2, (grey, red)
    dpg.create_context()
    try:
        with dpg.window(tag="w"):
            pass
        pq = PointQuads("w", "pq_dots", pos)
        pq.resize(240)
        pq.dots = True
        pq.camera(0.0, 0.0, 5.0)
        dot = [dpg.get_item_configuration(q) for q in pq.dot_items]
        sq = [dpg.get_item_configuration(q) for q in pq.items]
        assert all(c["show"] for c in dot + sq)
        assert all(abs(dc["p3"][0] - dc["p1"][0]) < abs(sc["p3"][0] - sc["p1"][0]) for dc, sc in zip(dot, sq))
        pq.colours(rgb, unlit=render.UNLIT)
        tex = np.asarray(dpg.get_value(pq.tex)).reshape(-1, 4)
        assert tex[0, 3] == 1.0 and tex[1, 3] == 0.0           # the unlit LED's square transparent: its dot shows
        pq.dots = False
        pq.camera(0.0, 0.0, 5.0)
        assert not any(dpg.get_item_configuration(q)["show"] for q in pq.dot_items)
    finally:
        dpg.destroy_context()


if __name__ == "__main__":
    import inspect
    failed = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and inspect.isfunction(fn):
            try:
                fn(); print("ok  ", name)
            except Exception as e:
                failed += 1; print("FAIL", name, str(e)[:2000])
    sys.exit(1 if failed else 0)
