"""The bench: a build sheet for a shape, and a template to build it on.

    html = sheet(geometry, outputs_opts, title, checks=[...])   # one printable page, nothing to load
    svg = template(geometry, hole_mm=0.0)                         # the LEDs at 1:1, in millimetres

**The build sheet** gathers what the studio already knows into the page
taken to the workbench: a diagram of the shape (each part in its colour
and number, the data in, the feeds, the leads between parts), and per
part in wiring order - its LEDs' numbers, the strip to cut for it, where
its data comes in, the lead to the next; the outputs (pins and LED
ranges); the power plan (power_plan.py) with the wire for each feed and
the supply; and the checks still open. It is a self-contained HTML file
- open it, print it.

**The template** is the shape seen flat at its real size - the view in
which it spreads widest (front, side or above) - as an SVG in
millimetres: every LED a mark (or a hole of the diameter given, for a
drilling template), numbered, each part's line, and a 100 mm bar to check
the print came out at actual size. Printed at 100 % (tiled across sheets
for a big piece) or cut on a plotter or a laser, it is where each LED
goes.
"""
import html
import time

import numpy as np

from native import shapes, units, power_plan


def _flat_axes(pos):
    """The two axes the shape spreads widest on, seen flat: front (X, Z), side (Y, Z) or above (X, Y),
    and the view's name. The axis it is thinnest along is the one looked down."""
    ext = np.ptp(pos, axis=0) if len(pos) else np.ones(3)
    thin = int(np.argmin(ext))
    if thin == 1:
        return (0, 2), "front"
    if thin == 0:
        return (1, 2), "side"
    return (0, 1), "above"


def _part_rows(g, parts, pos, owner, sp):
    """Per part in wiring order: its numbers, its strip, where its data comes in, the lead on."""
    mm = units.mm(sp)
    rows = []
    for k, part in enumerate(parts):
        idx = np.nonzero(owner == k)[0]
        if len(idx) == 0:
            continue
        a, b = int(idx[0]), int(idx[-1])
        pitch = float(part.get("params", {}).get("pitch", 1.0)) or 1.0
        strip_mm = len(idx) * pitch * mm                    # each LED owns a spacing of strip
        p0 = pos[a]
        nxt = idx[-1] + 1
        lead = None
        if nxt < len(pos):
            gap = float(np.linalg.norm(pos[nxt] - pos[b])) - pitch
            if gap > 0.25:
                lead = gap
        rows.append({"n": k + 1, "name": part.get("name") or part["kind"], "kind": part["kind"], "leds": len(idx),
                     "first": a, "last": b, "strip_mm": strip_mm, "in_at": p0, "lead": lead, "hidden": bool(part.get("hidden"))})
    return rows


def _colour(k):
    from native.shape_view import part_colour
    c = part_colour(k)
    return "#%02x%02x%02x" % (int(c[0]), int(c[1]), int(c[2]))


def _diagram(pos, owner, parts, plan, w_px=760, h_px=420):
    """The shape seen flat, as SVG: LEDs in their parts' colours, part numbers, IN, the feeds, the leads."""
    (ia, ib), view = _flat_axes(pos)
    x, y = pos[:, ia], pos[:, ib]
    if view == "above":
        y = -y
    lo_x, hi_x, lo_y, hi_y = x.min(), x.max(), y.min(), y.max()
    s = min((w_px - 60) / max(hi_x - lo_x, 1e-6), (h_px - 60) / max(hi_y - lo_y, 1e-6))
    X = (x - lo_x) * s + 30
    Y = h_px - ((y - lo_y) * s + 30)
    r = max(1.6, min(5.0, s * 0.3))
    out = [f'<svg viewBox="0 0 {w_px} {h_px}" xmlns="http://www.w3.org/2000/svg" class="diagram">',
           f'<rect width="{w_px}" height="{h_px}" fill="#11131a"/>']
    # the wiring through each part, faint, and the leads between parts dashed
    for k in sorted(set(owner.tolist())):
        idx = np.nonzero(owner == k)[0]
        pts = " ".join(f"{X[i]:.1f},{Y[i]:.1f}" for i in idx)
        out.append(f'<polyline points="{pts}" fill="none" stroke="{_colour(k)}" stroke-opacity="0.35" stroke-width="1"/>')
    for i in range(len(pos) - 1):
        if owner[i] != owner[i + 1]:
            out.append(f'<line x1="{X[i]:.1f}" y1="{Y[i]:.1f}" x2="{X[i + 1]:.1f}" y2="{Y[i + 1]:.1f}" stroke="#8a8f9c" '
                       f'stroke-dasharray="4 3" stroke-width="1"/>')
    for i in range(len(pos)):
        out.append(f'<circle cx="{X[i]:.1f}" cy="{Y[i]:.1f}" r="{r:.1f}" fill="{_colour(int(owner[i]))}"/>')
    for k in sorted(set(owner.tolist())):
        idx = np.nonzero(owner == k)[0]
        cx, cy = X[idx].mean(), Y[idx].mean()
        out.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="10" fill="#11131a" stroke="{_colour(k)}"/>'
                   f'<text x="{cx:.1f}" y="{cy + 4:.1f}" text-anchor="middle" font-size="11" fill="#f0f0f4">{k + 1}</text>')
    if plan is not None:
        for run in plan.runs:
            for f in run["feeds"]:
                out.append(f'<circle cx="{X[f]:.1f}" cy="{Y[f]:.1f}" r="{r + 4:.1f}" fill="none" stroke="#ffb846" stroke-width="2"/>')
    out.append(f'<text x="{X[0] + 8:.1f}" y="{Y[0] - 8:.1f}" font-size="12" font-weight="bold" fill="#ffffff">IN</text>')
    out.append(f'<text x="10" y="{h_px - 10}" font-size="11" fill="#8a8f9c">seen from the {view}; amber rings: power feeds; '
               f'dashed: leads between parts</text></svg>')
    return "".join(out), view


def sheet(g, outputs_opts=None, title="", checks=(), project=""):
    """The build sheet as one HTML page."""
    sp = g.params
    parts = sp.get("parts") or []
    pos, _, owner = shapes.resolve(parts)
    pos = np.asarray(pos, np.float64)
    owner = np.asarray(owner)
    n = len(pos)
    esc = html.escape
    show = lambda v: esc(units.show(v, sp))                 # noqa: E731
    plan = power_plan.plan(pos, 1.0, units.mm(sp), power_plan.settings(sp, outputs_opts)) if n else None
    rows = _part_rows(g, parts, pos, owner, sp) if n else []
    diagram, view = _diagram(pos, owner, parts, plan) if n else ("", "front")
    box = np.ptp(pos, axis=0) if n else np.zeros(3)
    total_strip = sum(r["strip_mm"] for r in rows)
    h = []
    h.append(f"<!doctype html><html><head><meta charset='utf-8'><title>{esc(title or 'Build sheet')}</title><style>"
             "body{font:13px/1.45 -apple-system,'Segoe UI',Helvetica,Arial,sans-serif;color:#1d1f26;margin:28px;max-width:900px}"
             "h1{font-size:22px;margin:0 0 4px}h2{font-size:15px;margin:22px 0 6px;border-bottom:1px solid #d6d8de;padding-bottom:3px}"
             ".sub{color:#5d6270}table{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums}"
             "th,td{text-align:left;padding:4px 8px;border-bottom:1px solid #e6e7eb;vertical-align:top}th{font-weight:600;color:#5d6270}"
             ".sw{display:inline-block;width:10px;height:10px;border-radius:5px;margin-right:6px;vertical-align:-1px}"
             ".diagram{width:100%;height:auto;border-radius:6px}ul{margin:4px 0 0 18px;padding:0}"
             ".warn{color:#a15c00}@media print{body{margin:10mm}h2{break-after:avoid}table,svg{break-inside:avoid}}"
             "</style></head><body>")
    h.append(f"<h1>{esc(title or 'Build sheet')}</h1>")
    h.append(f"<div class='sub'>{esc(project)} - {time.strftime('%Y-%m-%d %H:%M')} - {n} LEDs in {len(rows)} part(s), "
             f"{units.density(sp):g} LEDs a metre, {show(box[0])} x {show(box[1])} x {show(box[2])}; "
             f"{total_strip / 1000.0:.2f} m of strip</div>")
    if diagram:
        h.append(f"<h2>The shape, seen from the {esc(view)}</h2>{diagram}")
    h.append("<h2>Parts, in wiring order</h2><table><tr><th>#</th><th>part</th><th>LEDs</th><th>numbers</th>"
             "<th>strip to cut</th><th>data in at</th><th>lead to the next</th></tr>")
    for r in rows:
        p = r["in_at"]
        h.append(f"<tr><td><span class='sw' style='background:{_colour(r['n'] - 1)}'></span>{r['n']}</td>"
                 f"<td>{esc(r['name'])} <span class='sub'>({esc(r['kind'])}{', hidden' if r['hidden'] else ''})</span></td>"
                 f"<td>{r['leds']}</td><td>{r['first']} - {r['last']}</td><td>{r['strip_mm'] / 1000.0:.3f} m</td>"
                 f"<td>{show(p[0])}, {show(p[1])}, {show(p[2])}</td><td>{show(r['lead']) if r['lead'] else '-'}</td></tr>")
    h.append("</table><div class='sub'>Positions are from the shape's middle (x across, y back, z up). LED numbers count from 0 "
             "in wiring order - the device's own.</div>")
    outs = (outputs_opts or {}).get("outs") or []
    if outs:
        h.append("<h2>Outputs</h2><table><tr><th>output</th><th>pin</th><th>LEDs</th><th>numbers</th><th>reversed</th></tr>")
        for o in outs:
            h.append(f"<tr><td>{esc(str(o.get('name', '')))}</td><td>GPIO {o.get('pin')}</td><td>{o.get('len')}</td>"
                     f"<td>{o.get('start')} - {int(o.get('start', 0)) + int(o.get('len', 0)) - 1}</td><td>{'yes' if o.get('rev') else 'no'}</td></tr>")
        h.append("</table>")
    if plan is not None:
        h.append("<h2>Power</h2><ul>" + "".join(f"<li>{esc(s)}</li>" for s in plan.lines(sp)) + "</ul>")
        per_feed = plan.amps / max(1, plan.feeds())
        awg, mm2 = power_plan.wire_for(per_feed * 1.5)                # a feed can carry its neighbours' share too
        h.append(f"<div>Feed power in at LED{'s' if plan.feeds() > 1 else ''} "
                 f"<b>{', '.join(str(f) for f in plan.feed_list)}</b>: each feed about {per_feed:.1f} A - "
                 f"{awg} AWG ({mm2:g} mm&sup2;) wire from the supply, + and GND both.</div>")
        h.append("<table><tr><th>run of strip</th><th>LEDs</th><th>length</th><th>feeds on it</th><th>worst drop</th></tr>")
        for k, run in enumerate(plan.runs):
            h.append(f"<tr><td>{k + 1}</td><td>{run['leds']} ({run['first']} - {run['end'] - 1})</td><td>{run['metres']:.2f} m</td>"
                     f"<td>{', '.join(str(f) for f in run['feeds']) or '- (through the lead before it)'}</td>"
                     f"<td>{run['drop']:.2f} V</td></tr>")
        h.append("</table><div class='sub'>Typical strip figures - check them against your strip's sheet. Leads between runs "
                 "carry the power on (+, GND and data together). Tie every supply's GND to the controller's.</div>")
    if checks:
        h.append("<h2>Before you build</h2><ul>" + "".join(f"<li class='{'warn' if k == 'warn' else ''}'>{esc(t)}</li>"
                                                      for k, t in checks) + "</ul>")
    h.append("</body></html>")
    return "".join(h)


def template(g, hole_mm=0.0, numbers=True):
    """The shape seen flat at 1:1 as an SVG in millimetres (see the module's notes): (svg text, view, width mm, height mm)."""
    sp = g.params
    parts = sp.get("parts") or []
    pos, _, owner = shapes.resolve(parts)
    pos = np.asarray(pos, np.float64)
    if len(pos) == 0:
        raise ValueError("the shape has no LEDs")
    owner = np.asarray(owner)
    (ia, ib), view = _flat_axes(pos)
    mm = units.mm(sp)
    x, y = pos[:, ia] * mm, pos[:, ib] * mm
    y = -y                                                  # up the page (above: north at the top)
    margin = 15.0
    x0, y0 = x.min() - margin, y.min() - margin
    W = float(np.ptp(x) + 2 * margin)
    H = float(np.ptp(y) + 2 * margin + 20.0)              # room for the scale bar and the note
    X, Y = x - x0, y - y0
    r = hole_mm / 2.0 if hole_mm > 0 else 1.0
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W:.2f}mm" height="{H:.2f}mm" viewBox="0 0 {W:.3f} {H:.3f}">',
           '<g fill="none" stroke="#9aa0ad" stroke-width="0.25">']
    for k in sorted(set(owner.tolist())):
        idx = np.nonzero(owner == k)[0]
        out.append('<polyline points="' + " ".join(f"{X[i]:.2f},{Y[i]:.2f}" for i in idx) + '"/>')
    out.append('</g><g stroke="#000" stroke-width="0.25" fill="none">')
    for i in range(len(pos)):
        out.append(f'<circle cx="{X[i]:.2f}" cy="{Y[i]:.2f}" r="{r:.2f}"/>')
        if hole_mm <= 0:                                    # a mark: a cross to centre a drill or an LED on
            out.append(f'<path d="M{X[i] - 1.8:.2f} {Y[i]:.2f}h3.6M{X[i]:.2f} {Y[i] - 1.8:.2f}v3.6"/>')
    out.append("</g>")
    if numbers:
        fs = max(1.6, min(4.0, mm * 0.22))
        out.append(f'<g font-family="Helvetica,Arial,sans-serif" font-size="{fs:.2f}" fill="#333">')
        for i in range(len(pos)):
            out.append(f'<text x="{X[i] + r + 0.6:.2f}" y="{Y[i] - r - 0.4:.2f}">{i}</text>')
        out.append("</g>")
    by = H - 12.0
    out.append(f'<g stroke="#000" stroke-width="0.4"><path d="M{margin:.2f} {by:.2f}h100M{margin:.2f} {by - 2:.2f}v4'
               f'M{margin + 100:.2f} {by - 2:.2f}v4"/></g>'
               f'<text x="{margin:.2f}" y="{by + 6:.2f}" font-family="Helvetica,Arial,sans-serif" font-size="3.5">100 mm - '
               f'print at actual size (100 %); seen from the {view}; LED numbers in wiring order from 0</text></svg>')
    return "".join(out), view, W, H
