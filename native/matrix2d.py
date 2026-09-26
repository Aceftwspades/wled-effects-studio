"""A device's 2-D setup as the studio's matrix: its panels' size, where each
one's first LED is, rows or columns, serpentine - WLED's LED Preferences >
2D Configuration, kept in cfg.json as hw.led.matrix - and the gaps file
(/2d-gaps.json) when it has one.

The walk is WLED's own (WS2812FX::setUpMatrix, wled00/FX_2Dfcn.cpp): each
panel in turn, its lines one after another - rows, or columns when
vertical - from the start corner, every other line back when serpentine;
the table it makes says, for each position on the matrix, which LED is
there (-1: none). A gap of -1 is a missing pixel (not counted), 0 an
unused one (counted, not shown).

    panels = matrix2d.panels_of(cfg)            # [{"w","h","x","y","b","r","v","s"}], or None
    w, h, table = matrix2d.layout(panels, gaps) # table[y * w + x] = the LED there, or -1
    params, words = matrix2d.geometry_params(panels, gaps, source)
    info = matrix2d.read(host)                  # all of it from a device, over HTTP (read only)
"""
import json
import urllib.error
import urllib.request


def panels_of(cfg):
    """The panels from a /json/cfg, or None when the device has no 2-D setup."""
    m = (((cfg or {}).get("hw") or {}).get("led") or {}).get("matrix")
    if not isinstance(m, dict):
        return None
    out = []
    for p in (m.get("panels") or [])[:max(1, int(m.get("mpc", 1) or 1))]:
        out.append({"w": int(p.get("w", 8)), "h": int(p.get("h", 8)), "x": int(p.get("x", 0)), "y": int(p.get("y", 0)),
                    "b": bool(p.get("b")), "r": bool(p.get("r")), "v": bool(p.get("v")), "s": bool(p.get("s"))})
    return out or None


def layout(panels, gaps=None):
    """(width, height, table): table[y * width + x] = the LED at that
    position, or -1 - WLED's setUpMatrix, gaps and all."""
    W = max(p["x"] + p["w"] for p in panels)
    H = max(p["y"] + p["h"] for p in panels)
    if W <= 1 or H <= 1 or W > 255 or H > 255:
        raise ValueError(f"a {W} x {H} matrix is one WLED will not set up (each side 2 to 255)")
    size = W * H
    if gaps is not None and len(gaps) < size:
        gaps = None                                     # WLED ignores a gaps file shorter than the matrix
    table = [-1] * size
    pix = 0
    for p in panels:
        inner = p["h"] if p["v"] else p["w"]            # WLED's h: LEDs a line
        lines = p["w"] if p["v"] else p["h"]            # WLED's v: lines
        for j in range(lines):
            for i in range(inner):
                y = lines - j - 1 if (p["r"] if p["v"] else p["b"]) else j
                x = inner - i - 1 if (p["b"] if p["v"] else p["r"]) else i
                if p["s"] and j % 2:
                    x = inner - x - 1
                index = (p["y"] + (x if p["v"] else y)) * W + p["x"] + (y if p["v"] else x)
                g = None if gaps is None else int(gaps[index])
                if g is None or g > 0:
                    table[index] = pix
                if g is None or g >= 0:
                    pix += 1
    return W, H, table


def describe(panels):
    """The setup in words: "16 x 16, rows from the top left, serpentine"."""
    def one(p):
        corner = ("bottom" if p["b"] else "top") + " " + ("right" if p["r"] else "left")
        return f"{p['w']} x {p['h']}, {'columns' if p['v'] else 'rows'} from the {corner}" + (", serpentine" if p["s"] else "")
    if len(panels) == 1:
        return one(panels[0])
    W = max(p["x"] + p["w"] for p in panels)
    H = max(p["y"] + p["h"] for p in panels)
    same = all((p["w"], p["h"], p["b"], p["r"], p["v"], p["s"]) == (panels[0]["w"], panels[0]["h"], panels[0]["b"],
                                                                   panels[0]["r"], panels[0]["v"], panels[0]["s"]) for p in panels)
    return f"{len(panels)} panels making {W} x {H}" + (f", each {one(panels[0])}" if same else "")


def geometry_params(panels, gaps=None, source="the device"):
    """The matrix geometry's params for the setup, and its words. One panel
    in the corner with no gaps is the matrix's own four switches (left to
    change); anything else is the table WLED makes, as a ledmap is."""
    words = describe(panels)
    if len(panels) == 1 and panels[0]["x"] == 0 and panels[0]["y"] == 0 and gaps is None:
        p = panels[0]
        return {"w": p["w"], "h": p["h"], "serpentine": p["s"], "vertical": p["v"],
                "start_right": p["r"], "start_bottom": p["b"]}, words
    W, H, table = layout(panels, gaps)
    return {"w": W, "h": H, "map": table, "source": source}, words + (" (with its gaps file)" if gaps is not None else "")


def _get(host, path, timeout):
    """A path's JSON from the device, or None when it has no such file (404)."""
    try:
        with urllib.request.urlopen(f"http://{host}{path}", timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise


def read(host, timeout=6.0):
    """The device's 2-D setup (GET only - nothing on it changes): {"panels",
    "gaps", "ledmap" (whether it has one, which WLED lays over the setup),
    "total" (the LEDs its outputs drive)}; panels None: no 2-D setup."""
    cfg = _get(host, "/json/cfg", timeout) or {}
    panels = panels_of(cfg)
    gaps = None
    if panels:
        g = _get(host, "/2d-gaps.json", timeout)
        gaps = [int(v) for v in g] if isinstance(g, list) else None
    lm = _get(host, "/ledmap.json", timeout)
    total = int((((cfg.get("hw") or {}).get("led") or {}).get("total")) or 0)
    return {"panels": panels, "gaps": gaps, "ledmap": isinstance(lm, dict) and bool(lm.get("map")), "total": total}
