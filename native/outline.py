"""LEDs along drawn strokes - an SVG's (svg_import.py) or lettering traced
from a font - for the shape kind "outline": a neon sign, a logo, a word.

    strokes = text_strokes("OPEN", font, height_mm=200, style="center")  # [svg_import.Stroke]
    paths, closed = fit(strokes, unit_mm, size=None)                     # into the shape's units, centred
    order = wiring(paths, closed, how="shortest")                        # which stroke after which, reversed or not
    pos = leds(paths, closed, pitch=1.0, order)                          # the LEDs, in wiring order, on X-Z

**A strip's spacing is fixed.** An LED strip cannot stretch to fit a
stroke, so the LEDs go a pitch apart along each stroke and the length
left over (less than a pitch) is split between the stroke's two ends - a
straight run lit the way it would be cut. A closed stroke (an O, a
circle) puts its leftover in the one gap where the strip's two ends meet.
A stroke shorter than half a pitch is a dot (below).

**The wiring between strokes**: in the drawing's own order, or the
shortest - each next stroke the nearest end to where the last one
finished, run whichever way that end says (a closed stroke starts at its
nearest point). The jumps between strokes are the leads a builder solders,
and on a sign they are short when the order is the shortest.

**A dot is one LED.** A stroke shorter than half a pitch - an i's dot, a
full stop, a small mark in a logo - gets a single LED at its middle: on a
sign that is what such a mark is.

**Text**: the words drawn with a font at a high resolution and traced -
as **outlines** (the letters' edges: channel letters, edge-lit acrylic) by
marching squares, or as one **centre** stroke a letter (neon: the line a
glass tube would follow) by thinning the letters to a one-pixel skeleton
(Zhang & Suen, "A fast parallel algorithm for thinning digital patterns",
CACM 27(3), 1984) and following it into strokes. Both smoothed and
simplified (Ramer-Douglas-Peucker) so the LEDs run along curves, not
staircase pixels.
"""
import glob
import math
import os
import sys

import numpy as np

from native import svg_import

STYLES = (("center", "one stroke a letter (neon)"), ("outline", "the letters' outlines"))


# --- LEDs along strokes ------------------------------------------------------------------------
def _resample(pts, closed, pitch):
    """LEDs a pitch apart along a polyline, the leftover split between its ends (open) or left at
    the join (closed); a stroke shorter than half a pitch, one LED at its middle (a dot)."""
    pts = np.asarray(pts, np.float64)
    if closed:
        pts = np.vstack([pts, pts[:1]])
    seg = np.diff(pts, axis=0)
    L = np.linalg.norm(seg, axis=1)
    total = float(L.sum())
    if len(pts) == 0:
        return np.zeros((0, 2))
    if total < pitch * 0.5 or len(pts) < 2:
        return pts.mean(0, keepdims=True)                   # a dot: one LED
    if closed:
        n = max(1, int(total // pitch))
        d = np.arange(n) * pitch                                    # from the start; the gap where the ends meet
    else:
        n = int(total // pitch) + 1
        d = np.arange(n) * pitch + (total - (n - 1) * pitch) / 2.0  # centred: the leftover split
    cum = np.concatenate([[0.0], np.cumsum(L)])
    i = np.clip(np.searchsorted(cum, d, side="right") - 1, 0, len(seg) - 1)
    t = np.where(L[i] > 0, (d - cum[i]) / np.where(L[i] > 0, L[i], 1.0), 0.0)
    return pts[i] + seg[i] * t[:, None]


def wiring(paths, closed, how="shortest"):
    """[(stroke index, reversed, start rotation)] in wiring order: the drawing's order, or each next
    stroke the one with an end (any point of a closed one) nearest where the last finished."""
    n = len(paths)
    if how != "shortest" or n < 2:
        return [(k, False, 0) for k in range(n)]
    left = set(range(n))
    out = []
    at = None
    while left:
        best = None
        for k in left:
            P = np.asarray(paths[k])
            if at is None:
                # the first: the stroke with the left-most, top-most start (a sign's wiring starts at its left)
                cand = [(float(P[0, 0]) * 1e3 - float(P[0, 1]), False, 0)]
            elif closed[k]:
                j = int(np.argmin(np.linalg.norm(P - at, axis=1)))
                cand = [(float(np.linalg.norm(P[j] - at)), False, j)]
            else:
                cand = [(float(np.linalg.norm(P[0] - at)), False, 0), (float(np.linalg.norm(P[-1] - at)), True, 0)]
            for c in cand:
                if best is None or c[0] < best[0]:
                    best = (c[0], k, c[1], c[2])
        _, k, rev, rot = best
        left.discard(k)
        out.append((k, rev, rot))
        P = np.asarray(paths[k])
        at = P[rot] if closed[k] else (P[0] if rev else P[-1])
    return out


def leds(paths, closed, pitch=1.0, order=None):
    """Every stroke's LEDs in wiring order: (positions N x 3 on the X-Z plane - the drawing stands
    facing the camera, its y down turned to Z up - and which stroke each LED is on)."""
    order = order if order is not None else [(k, False, 0) for k in range(len(paths))]
    pos, owner = [], []
    for k, rev, rot in order:
        P = np.asarray(paths[k], np.float64)
        if closed[k] and rot:
            P = np.vstack([P[rot:], P[:rot]])
        if rev:
            P = P[::-1]
        L = _resample(P, closed[k], pitch)
        if len(L):
            pos.append(np.stack([L[:, 0], np.zeros(len(L)), L[:, 1]], 1))
            owner += [k] * len(L)
    if not pos:
        return np.zeros((0, 3), np.float32), []
    return np.concatenate(pos).astype(np.float32), owner


def counts(paths, closed, pitch=1.0):
    """(LEDs, dots - strokes too short for a run, one LED each): what an import comes to."""
    n = dots = 0
    for P, c in zip(paths, closed):
        P = np.asarray(P, np.float64)
        n += len(_resample(P, c, pitch))
        seg = np.diff(np.vstack([P, P[:1]]) if c else P, axis=0)
        dots += float(np.linalg.norm(seg, axis=1).sum()) < pitch * 0.5
    return n, dots


def fit(strokes, unit_mm, size=None):
    """Strokes in millimetres (y down) into the shape's units (a unit = `unit_mm`, the LED spacing),
    y turned up and the whole centred; `size` (units) scales the drawing's width to it instead of
    keeping its real size. (paths, closed)."""
    if not strokes:
        return [], []
    allp = np.concatenate([s.points for s in strokes])
    lo, hi = allp.min(0), allp.max(0)
    mid = (lo + hi) / 2.0
    k = 1.0 / unit_mm
    if size:
        k = float(size) / max(float(hi[0] - lo[0]), 1e-9)
    paths = [[[(p[0] - mid[0]) * k, -(p[1] - mid[1]) * k] for p in s.points] for s in strokes]
    return paths, [bool(s.closed) for s in strokes]


# --- the parts --------------------------------------------------------------------------------------
_TEXT_CACHE = {}


def default_font():
    """A font every computer the studio runs on has, by name: the first of these there is."""
    f = fonts()
    for name in ("arial", "Arial", "segoeui", "DejaVuSans", "Helvetica", "LiberationSans-Regular", "NotoSans-Regular"):
        if name in f:
            return name
    return next(iter(f), "")


def part_paths(p):
    """A "text" or "outline" part's strokes in the shape's units (centred, y up): an outline's as they
    were read; a text part's traced from its font, cached by what it says."""
    if "text" not in p:
        return [list(map(list, s)) for s in (p.get("paths") or [])], [bool(c) for c in (p.get("closed") or [])]
    text = str(p.get("text") or "").replace("\\n", "\n")      # typed \n is a new line
    name = str(p.get("font") or "") or default_font()
    style = "outline" if p.get("style") == "outline" else "center"
    height = max(0.5, float(p.get("height", 12.0) or 12.0))
    key = (text, name, style, round(height, 4))
    hit = _TEXT_CACHE.get(key)
    if hit is None:
        path = fonts().get(name) or fonts().get(default_font())
        strokes = text_strokes(text, path, height_mm=height, style=style) if text.strip() and path else []
        hit = fit(strokes, unit_mm=1.0)                    # height is in the shape's units already
        if len(_TEXT_CACHE) > 24:
            _TEXT_CACHE.clear()
        _TEXT_CACHE[key] = hit
    return hit


# --- text ------------------------------------------------------------------------------------------
_FONTS = None


def fonts():
    """{name: path} of the fonts on this computer (TrueType and OpenType), read once."""
    global _FONTS
    if _FONTS is not None:
        return _FONTS
    if sys.platform.startswith("win"):
        dirs = [os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts"),
                os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "Windows", "Fonts")]
    elif sys.platform == "darwin":
        dirs = ["/System/Library/Fonts", "/Library/Fonts", os.path.expanduser("~/Library/Fonts")]
    else:
        dirs = ["/usr/share/fonts", "/usr/local/share/fonts", os.path.expanduser("~/.local/share/fonts"),
                os.path.expanduser("~/.fonts")]
    out = {}
    for d in dirs:
        for f in glob.glob(os.path.join(d, "**", "*.[to]tf"), recursive=True) + glob.glob(os.path.join(d, "**", "*.tt[cf]"), recursive=True):
            out.setdefault(os.path.splitext(os.path.basename(f))[0], f)
    _FONTS = dict(sorted(out.items(), key=lambda kv: kv[0].lower()))
    return _FONTS


def _render(text, font_path, px):
    """The text as a 0/1 image, letters about `px` pixels tall, with a margin."""
    from PIL import Image, ImageDraw, ImageFont
    font = ImageFont.truetype(font_path, px)
    lines = text.split("\n")
    probe = ImageDraw.Draw(Image.new("L", (1, 1)))
    boxes = [probe.textbbox((0, 0), ln or " ", font=font) for ln in lines]
    lh = int(px * 1.25)
    W = max(b[2] - min(0, b[0]) for b in boxes) + px
    H = lh * len(lines) + px
    im = Image.new("L", (int(W), int(H)), 0)
    dr = ImageDraw.Draw(im)
    for i, ln in enumerate(lines):
        dr.text((px // 2, px // 2 + i * lh), ln, fill=255, font=font)
    return (np.asarray(im) > 127).astype(np.uint8)


def _rdp(pts, eps):
    """Ramer-Douglas-Peucker: the fewest points within eps of the line."""
    pts = np.asarray(pts, np.float64)
    if len(pts) < 3:
        return pts
    a, b = pts[0], pts[-1]
    d = b - a
    n = math.hypot(d[0], d[1])
    if n < 1e-12:
        dist = np.linalg.norm(pts - a, axis=1)
    else:
        dist = np.abs(d[0] * (a[1] - pts[:, 1]) - d[1] * (a[0] - pts[:, 0])) / n
    i = int(np.argmax(dist))
    if dist[i] > eps:
        left = _rdp(pts[:i + 1], eps)
        return np.vstack([left[:-1], _rdp(pts[i:], eps)])
    return np.vstack([a, b])


def _smooth(pts, closed, k=2):
    """A moving average k points either side: pixel steps into curves."""
    pts = np.asarray(pts, np.float64)
    if len(pts) < 2 * k + 2:
        return pts
    if closed:
        ext = np.vstack([pts[-k:], pts, pts[:k]])
    else:
        ext = np.vstack([np.repeat(pts[:1], k, 0), pts, np.repeat(pts[-1:], k, 0)])
    kern = np.ones(2 * k + 1) / (2 * k + 1)
    out = np.stack([np.convolve(ext[:, j], kern, "valid") for j in range(2)], 1)
    if not closed:
        out[0], out[-1] = pts[0], pts[-1]                   # an open stroke keeps its ends where they are
    return out


def _contours(img):
    """Marching squares on a 0/1 image: the closed outlines between 0 and 1, each a list of (x, y) at
    the pixel edges' midpoints - outer edges and holes alike."""
    h, w = img.shape
    pad = np.zeros((h + 2, w + 2), np.uint8)
    pad[1:-1, 1:-1] = img
    # each cell's corners: tl, tr, br, bl -> a case 0..15
    tl, tr, br, bl = pad[:-1, :-1], pad[:-1, 1:], pad[1:, 1:], pad[1:, :-1]
    case = (tl << 3) | (tr << 2) | (br << 1) | bl
    # the edges a case joins: 0 top, 1 right, 2 bottom, 3 left (the saddles split as "inside joined")
    SEG = {1: [(3, 2)], 2: [(2, 1)], 3: [(3, 1)], 4: [(1, 0)], 5: [(3, 0), (1, 2)], 6: [(2, 0)], 7: [(3, 0)],
           8: [(0, 3)], 9: [(0, 2)], 10: [(0, 1), (2, 3)], 11: [(0, 1)], 12: [(1, 3)], 13: [(1, 2)], 14: [(2, 3)]}
    MID = {0: (0.5, 0.0), 1: (1.0, 0.5), 2: (0.5, 1.0), 3: (0.0, 0.5)}
    nxt = {}
    ys, xs = np.nonzero((case > 0) & (case < 15))
    for y, x in zip(ys.tolist(), xs.tolist()):
        for a, b in SEG[int(case[y, x])]:
            pa = (x + MID[a][0], y + MID[a][1])
            pb = (x + MID[b][0], y + MID[b][1])
            nxt[pa] = pb
    out = []
    while nxt:
        start, cur = next(iter(nxt.items()))
        ring = [start]
        del nxt[start]
        while cur != start and cur in nxt:
            ring.append(cur)
            cur = nxt.pop(cur)
        if len(ring) >= 4:
            out.append(np.asarray(ring, np.float64) - 1.0)    # the pad's offset taken back
    return out


def _thin(img):
    """Zhang-Suen thinning: the letters worn down to lines one pixel wide, their shape kept."""
    im = np.pad(img.astype(np.uint8), 1)
    while True:
        changed = False
        for step in (0, 1):
            P2, P3, P4 = im[:-2, 1:-1], im[:-2, 2:], im[1:-1, 2:]
            P5, P6, P7 = im[2:, 2:], im[2:, 1:-1], im[2:, :-2]
            P8, P9 = im[1:-1, :-2], im[:-2, :-2]
            nb = [P2, P3, P4, P5, P6, P7, P8, P9]
            B = sum(n.astype(int) for n in nb)
            seq = nb + [P2]
            A = sum(((seq[i] == 0) & (seq[i + 1] == 1)).astype(int) for i in range(8))
            if step == 0:
                c = (P2 * P4 * P6 == 0) & (P4 * P6 * P8 == 0)
            else:
                c = (P2 * P4 * P8 == 0) & (P2 * P6 * P8 == 0)
            m = (im[1:-1, 1:-1] == 1) & (B >= 2) & (B <= 6) & (A == 1) & c
            if m.any():
                im[1:-1, 1:-1][m] = 0
                changed = True
        if not changed:
            return im[1:-1, 1:-1]


def _trace_skeleton(sk, min_len):
    """A one-pixel skeleton followed into strokes: from each end and branch point along to the next,
    every pixel used once; loops with no end (an O) as closed strokes. Spurs shorter than min_len
    pixels - the thinning's whiskers at a letter's corners - are dropped."""
    ys, xs = np.nonzero(sk)
    on = set(zip(xs.tolist(), ys.tolist()))
    N4 = [(0, -1), (1, 0), (0, 1), (-1, 0)]
    ND = [(-1, -1), (1, -1), (1, 1), (-1, 1)]

    def nbrs(p):
        # the straight neighbours, and a diagonal one only where no straight neighbour already joins
        # the two: on a staircase a pixel touches both, and counting both made nearly every pixel of
        # a curve a "branch" - the skeleton broke into hundreds of strokes too short for an LED
        x, y = p
        out = [(x + dx, y + dy) for dx, dy in N4 if (x + dx, y + dy) in on]
        for dx, dy in ND:
            q = (x + dx, y + dy)
            if q in on and (x + dx, y) not in on and (x, y + dy) not in on:
                out.append(q)
        return out

    deg = {p: len(nbrs(p)) for p in on}
    nodes = {p for p, d in deg.items() if d != 2}
    strokes_dots = [(np.asarray([p, p], np.float64), False) for p, d in deg.items() if d == 0]
    used = set()                                           # edges walked: (a, b) both ways
    strokes = []

    def walk(a, b):
        path = [a, b]
        used.add((a, b)); used.add((b, a))
        prev, cur = a, b
        while cur not in nodes:
            nx = [q for q in nbrs(cur) if q != prev and (cur, q) not in used]
            if not nx:
                break
            # the straightest way on
            d0 = (cur[0] - prev[0], cur[1] - prev[1])
            q = max(nx, key=lambda q: d0[0] * (q[0] - cur[0]) + d0[1] * (q[1] - cur[1]))
            used.add((cur, q)); used.add((q, cur))
            prev, cur = cur, q
            path.append(cur)
        return path

    for a in sorted(nodes):
        for b in nbrs(a):
            if (a, b) not in used:
                path = walk(a, b)
                is_spur = (deg[path[0]] == 1) != (deg[path[-1]] == 1) and len(path) < min_len
                if not is_spur:
                    strokes.append((np.asarray(path, np.float64), False))
    # what is left is loops with no node on them
    for p in sorted(on):
        for b in nbrs(p):
            if (p, b) not in used:
                path = walk(p, b)
                if len(path) > 3:
                    closed = path[-1] == path[0] or path[-1] in nbrs(path[0])
                    pts = np.asarray(path[:-1] if path[-1] == path[0] else path, np.float64)
                    strokes.append((pts, closed))
                else:                                       # a tiny ring: a dot
                    c = np.asarray(path, np.float64).mean(0)
                    strokes.append((np.asarray([c, c]), False))
    return strokes + strokes_dots


def _blobs(img):
    """The image's separate pieces (8-connected), each as (ys, xs) arrays."""
    h, w = img.shape
    seen = np.zeros_like(img, bool)
    out = []
    for y0, x0 in zip(*np.nonzero(img)):
        if seen[y0, x0]:
            continue
        stack, ys, xs = [(y0, x0)], [], []
        seen[y0, x0] = True
        while stack:
            y, x = stack.pop()
            ys.append(y); xs.append(x)
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    v, u = y + dy, x + dx
                    if 0 <= v < h and 0 <= u < w and img[v, u] and not seen[v, u]:
                        seen[v, u] = True
                        stack.append((v, u))
        out.append((np.asarray(ys), np.asarray(xs)))
    return out


def text_strokes(text, font_path, height_mm=100.0, style="center"):
    """The text as strokes in millimetres (y down): its capital letters `height_mm` tall, in the
    style STYLES names. Each letter's strokes in reading order."""
    px = 150                                               # the letters this many pixels tall: plenty to trace, and quick
    img = _render(text, font_path, px)
    from PIL import ImageFont
    cap = ImageFont.truetype(font_path, px).getbbox("H")
    cap_px = max(1, cap[3] - cap[1])
    k = height_mm / cap_px
    out = []
    if style == "outline":
        for ring in _contours(img):
            pts = _rdp(_smooth(ring, True, 2), 0.6)
            if len(pts) > 3 and np.linalg.norm(pts[-1] - pts[0]) < 1e-9:
                pts = pts[:-1]
            if len(pts) >= 3:
                out.append(svg_import.Stroke(pts * k, True, "outline"))
    else:
        sk = _thin(img)
        stroke_w = max(2.0, float(img.sum()) / max(1, sk.sum()))   # the letters' stroke width, about
        for pts, closed in _trace_skeleton(sk, min_len=stroke_w * 1.2):
            pts = _rdp(_smooth(pts, closed, 3), 0.8)
            if len(pts) >= 2:
                out.append(svg_import.Stroke(pts * k, closed and len(pts) >= 3, "stroke"))
        # thinning can wear a small round blob - an i's dot, a full stop - away to nothing: any blob of
        # the letters that left no skeleton is a dot at its middle
        for blob in _blobs(img):
            ys, xs = blob
            if not sk[ys, xs].any():
                c = np.asarray([[xs.mean(), ys.mean()]] * 2)
                out.append(svg_import.Stroke(c * k, False, "dot"))
    # reading order: by line, then left to right by where each stroke starts
    lh = px * 1.25 * k
    out.sort(key=lambda s: (int(s.points[:, 1].min() // lh), float(s.points[:, 0].min())))
    return out
