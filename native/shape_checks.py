"""Checks as you build (the ninth pass's S16): what in a shape is likely a
mistake, or will matter on the bench - each in words, with a "show me".

- LEDs on the same spot: two parts laid over each other, a copy on top of
  its part (within a quarter of a spacing);
- a long lead between one part's last LED and the next's first (a metre
  and more: a data wire that long may want a buffer, or a sacrificial LED
  near the controller);
- a grid layout that leaves LEDs dark (seen from the front, one behind
  another shares its cell);
- the LED outputs (the Outputs frame) carrying another count than the shape;
- the current at full white, against the brightness limiter's ceiling;
- a formula that does not work out, a part with no LEDs, parts hidden;
- LEDs of lights mapped by camera that no two sides of the films saw (their
  places estimates, to drag where they are).

    shape_checks.run(app)          # [Check(kind "warn"|"info", text, show)]
    shape_checks.refresh(app)      # the frame's CHECKS lines, from run()
"""
import numpy as np
import dearpygui.dearpygui as dpg

from native import shapes, units, view3d
from native.typeface import px

NEAR = 0.25           # two LEDs nearer than this (spacings) are on one spot
LONG_CM = 100.0       # a lead this long (cm) is worth a word


class Check:
    def __init__(self, kind, text, show=None):
        self.kind, self.text, self.show = kind, text, show


def _overlaps(W):
    """Index pairs of LEDs nearer than NEAR: a grid of NEAR cells, each against itself and its neighbours."""
    W = np.asarray(W, np.float64)
    ok = np.isfinite(W).all(1)
    idx = np.nonzero(ok)[0]
    if len(idx) < 2:
        return []
    keys = np.floor(W[idx] / NEAR).astype(np.int64)
    cells = {}
    for i, k in zip(idx, map(tuple, keys)):
        cells.setdefault(k, []).append(i)
    pairs = []
    offs = [(a, b, c) for a in (-1, 0, 1) for b in (-1, 0, 1) for c in (-1, 0, 1)]
    for k, members in cells.items():
        for o in offs:
            other = cells.get((k[0] + o[0], k[1] + o[1], k[2] + o[2]))
            if not other:
                continue
            for i in members:
                for j in other:
                    if j > i and float(np.linalg.norm(W[i] - W[j])) < NEAR:
                        pairs.append((i, j))
        if len(pairs) > 5000:
            break
    return pairs


def run(app):
    """The shape's checks, most pressing first."""
    from native import shape_ui, shape_view, device_ui
    g = app.project.geometry
    parts = shape_ui._parts(app)
    if not parts or g.kind != "shape":
        return []
    sp = g.params
    out = []
    W, owner = shape_view.wiring(g)
    # LEDs on one spot
    pairs = _overlaps(W)
    if pairs:
        leds = sorted({i for p in pairs for i in p})
        who = sorted({int(owner[i]) for i in leds})
        names = ", ".join(parts[k].get("name", parts[k]["kind"]) for k in who[:3]) + (" ..." if len(who) > 3 else "")
        pts = W[leds]
        out.append(Check("warn", f"{len(leds)} LEDs sit on another ({names})",
                         lambda: (shape_ui.select(app, who), view3d.frame_points(app, pts))))
    # long leads
    R = shape_view.runs(owner)
    order = sorted(R.items(), key=lambda kv: kv[1][0])
    for (k0, (a0, b0)), (k1, (a1, b1)) in zip(order, order[1:]):
        gap = float(np.linalg.norm(W[a1] - W[b0 - 1])) - shape_view._spacing(W, a0, b0, a1, b1)
        if units.to_unit(gap, dict(sp, unit="cm")) >= LONG_CM:
            ends = W[[b0 - 1, a1]]
            out.append(Check("warn", f"the lead from {parts[k0].get('name', parts[k0]['kind'])} to {parts[k1].get('name', parts[k1]['kind'])} "
                             f"is {units.show(gap, sp)}: a data wire that long may want a buffer, or a sacrificial LED near the controller",
                             lambda e=ends, ks=(k0, k1): (shape_ui.select(app, list(ks)), view3d.frame_points(app, e))))
    # a grid layout seen from the front: an LED behind another shares its cell, and the cell keeps the first
    lost = int(getattr(g, "collisions", 0) or 0) if sp.get("layout") == "grid" else 0
    if lost:
        out.append(Check("warn", f"the grid layout puts {lost} LEDs behind others, seen from the front: they get no pixel and "
                         "stay dark - a 3-D shape wants the strip layout (THE EFFECTS SEE), with effects made for any shape",
                         lambda: shape_ui.select(app, [])))
    # the outputs' count
    S = app.project.options.get("outputs") or {}
    outs = S.get("outs") or []
    if outs:
        total = sum(int(o.get("len", 0) or 0) for o in outs)
        if total != g.count:
            out.append(Check("warn", f"the LED outputs carry {total} LEDs, the shape has {g.count}",
                             lambda: device_ui.show(app, "outputs")))
    # formulas, empty parts
    for k, q in enumerate(parts):
        if q.get("kind") == "formula":
            err = shapes.formula_error(q)
            if err:
                out.append(Check("warn", f"{q.get('name', 'formula')}: {err}", lambda k=k: shape_ui.select(app, [k])))
        elif q.get("kind") != "reference" and shapes.part_count(q) == 0:
            out.append(Check("warn", f"{q.get('name', q['kind'])} has no LEDs", lambda k=k: shape_ui.select(app, [k])))
    # lights mapped by camera: the LEDs no two sides saw, their places estimated
    for k, q in enumerate(parts):
        m = shapes.local_count(q)
        guess = sorted({int(i) for i in (q.get("guessed") or []) if 0 <= int(i) < m})
        if guess:
            pts = np.asarray(shapes.placed(q)[0])[:m][guess]
            out.append(Check("info", f"{q.get('name', 'mapped lights')}: {len(guess)} LED(s) no two sides of the films saw - "
                             "their places are estimates, ringed while it is selected (BY HAND's place drags them where they are)",
                             lambda k=k, pts=pts: (shape_ui.select(app, [k]), view3d.frame_points(app, pts))))
    # the current at full white
    from native import outputs
    ma = int(S.get("ma_per_led", outputs.LED_MA_DEFAULT))
    ceiling = int(S.get("max_ma", outputs.MAX_MA_DEFAULT))
    full = g.count * ma / 1000.0
    if ceiling and full * 1000 > ceiling:
        out.append(Check("info", f"at full white the {g.count} LEDs would draw {full:.1f} A; the limiter keeps it to "
                         f"{ceiling / 1000.0:.1f} A (the Outputs frame sets it)", lambda: device_ui.show(app, "outputs")))
    hidden = [k for k, q in enumerate(parts) if q.get("hidden")]
    if hidden:
        out.append(Check("info", f"{len(hidden)} part(s) hidden while you build", lambda: shape_ui.select(app, hidden)))
    return out


def refresh(app):
    """The frame's CHECKS lines: a word each and a "show me", or that all is well."""
    if not dpg.does_item_exist("shape_checks"):
        return
    from native import chrome
    dpg.delete_item("shape_checks", children_only=True)
    try:
        found = run(app)
    except Exception as e:                                   # a check must never cost the frame
        found = [Check("info", f"the checks could not run: {e}")]
    app._shape_checks = found
    if not found:
        app._shape_warns = 0
        return
    warns = sum(1 for f in found if f.kind == "warn")
    for f in found[:5]:
        with dpg.group(horizontal=True, parent="shape_checks"):
            dpg.add_text("!" if f.kind == "warn" else "i", color=chrome.AMBER if f.kind == "warn" else chrome.DIM)
            dpg.add_text(f.text, color=chrome.TEXT if f.kind == "warn" else chrome.DIM, wrap=px(430))
            if f.show is not None:
                dpg.add_button(label="show me", small=True, user_data=f.show, callback=lambda s, a, u: u())
    if len(found) > 5:
        dpg.add_text(f"and {len(found) - 5} more", parent="shape_checks", color=chrome.DIM)
    if warns > getattr(app, "_shape_warns", 0):              # a word on the footer when there is newly more to look at
        app.gp.status(f"the shape: {warns} thing(s) to look at - see the Shape frame's checks")
    app._shape_warns = warns
