"""Power for a physical build: where a shape's strips need power fed in,
how far the voltage sags between feeds, the supply it wants and the wire
for each feed.

    st = settings(shape_params, outputs_options)        # volts, mA an LED, rail resistance, brightness planned for
    p = plan(geometry, st)                              # runs, feeds, drops, the supply, as plain numbers
    p.lines(units_params)                               # the same in words

**Why a strip needs feeding along its length.** An LED strip carries its
power on two thin copper rails. Their resistance (about 0.1 ohm a metre
for the pair on a common 10 mm 5 V strip) and the current the LEDs draw
make the voltage fall along the strip: fed from one end, the drop at the
far end is R I L^2 / 2 for R ohms a metre, I amps a metre and L metres -
growing with the SQUARE of the length. Past a tenth of the supply voltage
lost, colours shift (blue fades first; a white goes yellow-pink) and the
far LEDs can brown out. Feeding power in again along the way ("injection")
keeps every LED near the supply's voltage.

**How it is worked out.** The whole wiring is one ladder: every LED a
node drawing its current, the rails between neighbours a resistor of R
times the distance, each feed a node held at the supply voltage. A lead
wire between two runs of strip (a step longer than 1.6 spacings: from one
letter of a sign to the next, from one part to another) carries the power
on with the data, as a pair of 22 AWG wires does - about 0.1 ohm a metre.
That is a tridiagonal system, solved exactly (Thomas' algorithm, linear in
the LEDs). Feeds go in at the first LED and then every so many - the
spacing starting from the closed form for a stretch fed at both ends
(s = sqrt(8 V / (R I))) and tightened until the worst LED is within the
allowed drop. The runs of strip are reported on their own (what to cut),
with the feeds that land on each.

**What it is planned for.** Full white at the brightness set (100 % by
default: the worst case a strip has to survive). The supply is sized for
that with a fifth more for margin, and - when the Outputs frame has a
supply set for the brightness limiter - what the limiter lets through is
said beside it. 12 V and 24 V strips draw less current an LED and lose a
smaller share of their voltage, so they go many times further between
feeds; their defaults say so.

The resistances are typical figures, not measurements of your strip: a
thick (2 oz, 12 mm) strip does better, a thin cheap one worse. Change the
figure if the strip's sheet gives it.
"""
import math

import numpy as np

# volts -> (mA an LED at full white, ohms a metre for both rails, the drop allowed)
DEFAULTS = {5: (55.0, 0.10, 0.5), 12: (15.0, 0.08, 1.0), 24: (10.0, 0.06, 2.0)}
GAP = 1.6                                   # spacings: a longer step from one LED to the next is a lead, not strip
LEAD_OHM_M = 0.1                            # a lead's pair of 22 AWG wires, ohms a metre for both
# the wire a feed wants: (amps it carries, AWG, mm2) - chassis-wiring figures with room to spare
WIRE = ((2.0, 24, 0.2), (3.5, 22, 0.35), (5.0, 20, 0.5), (7.5, 18, 0.75), (10.0, 16, 1.5), (15.0, 14, 2.5),
        (20.0, 12, 4.0), (30.0, 10, 6.0))
SUPPLIES = (1, 2, 3, 4, 5, 6, 8, 10, 12.5, 15, 20, 25, 30, 40, 50, 60, 80, 100)     # amps sold


def settings(sp, outputs_opts=None):
    """The planning settings: the shape's "power" options over the defaults for its voltage."""
    o = dict((sp or {}).get("power") or {})
    v = int(o.get("volts", 5)) if int(o.get("volts", 5)) in DEFAULTS else 5
    ma0, r0, d0 = DEFAULTS[v]
    out = outputs_opts or {}
    return {"volts": v, "ma": float(o.get("ma", ma0)), "ohm_m": float(o.get("ohm_m", r0)),
            "drop": float(o.get("drop", d0)), "bri": min(1.0, max(0.01, float(o.get("bri", 1.0)))),
            "supply_ma": int(out.get("max_ma", 0) or 0)}


def _thomas(a, b, c, d):
    """Solve the tridiagonal system a[i] x[i-1] + b[i] x[i] + c[i] x[i+1] = d[i]."""
    n = len(d)
    cp, dp = np.zeros(n), np.zeros(n)
    cp[0], dp[0] = c[0] / b[0], d[0] / b[0]
    for i in range(1, n):
        m = b[i] - a[i] * cp[i - 1]
        cp[i] = c[i] / m if i < n - 1 else 0.0
        dp[i] = (d[i] - a[i] * dp[i - 1]) / m
    x = np.zeros(n)
    x[-1] = dp[-1]
    for i in range(n - 2, -1, -1):
        x[i] = dp[i] - cp[i] * x[i + 1]
    return x


def drops(n, r, amps, feeds):
    """Each LED's voltage drop below the supply along a chain of n LEDs: `r` the ohms between
    neighbours (one figure, or one for each of the n-1 steps), `amps` drawn by each LED, the LEDs
    in `feeds` held at the supply."""
    if n == 1:
        return np.zeros(1)
    g = 1.0 / np.maximum(np.broadcast_to(np.asarray(r, np.float64), (n - 1,)), 1e-9)   # conductances
    fed = np.zeros(n, bool)
    fed[list(feeds)] = True
    a, b, c, d = np.zeros(n), np.zeros(n), np.zeros(n), np.zeros(n)
    for i in range(n):
        if fed[i]:
            b[i], d[i] = 1.0, 0.0                       # a feed: no drop
            continue
        # Kirchhoff at the LED, in drops d = V0 - V: what flows in from each side is what it draws
        gl = g[i - 1] if i > 0 else 0.0
        gr = g[i] if i < n - 1 else 0.0
        a[i], b[i], c[i], d[i] = -gl, gl + gr, -gr, amps
    return _thomas(a, b, c, d)


def runs(pos, spacing):
    """The wiring split into runs of strip: [(first LED, end, metres of strip)] - a step longer than
    GAP spacings starts a new run (it is a lead wire). `spacing` in the positions' units."""
    n = len(pos)
    if n == 0:
        return []
    step = np.linalg.norm(np.diff(pos, axis=0), axis=1) if n > 1 else np.zeros(0)
    cut = np.nonzero(step > GAP * spacing)[0]
    starts = [0] + (cut + 1).tolist()
    ends = (cut + 1).tolist() + [n]
    return [(a, b, float(step[a:b - 1].sum()) if b - a > 1 else 0.0) for a, b in zip(starts, ends)]


class Plan:
    def __init__(self):
        self.runs = []                  # [{first, end, leds, metres, feeds (LED numbers), drop (V), amps}]
        self.amps = 0.0                 # all of it at the brightness planned for
        self.volts = 5
        self.supply = None              # (amps, watts) suggested
        self.limiter_amps = None        # what the brightness limiter allows, when the Outputs frame sets a supply
        self.settings = {}
        self.feed_list = []             # every feed, by LED number

    def feeds(self):
        return len(self.feed_list)

    def worst(self):
        return max((r["drop"] for r in self.runs), default=0.0)

    def lines(self, sp):
        """The plan in words, for the Shape frame and the build sheet."""
        from native import units
        st = self.settings
        out = [f"{self.volts} V strip, {st['ma']:g} mA an LED at full white, planned at {st['bri'] * 100:.0f} %: "
               f"{self.amps:.1f} A in all ({self.amps * self.volts:.0f} W)"]
        if self.supply:
            out.append(f"a {self.volts} V supply of {self.supply[0]:g} A ({self.supply[1]:.0f} W) or more - the draw and a fifth to spare")
        if self.limiter_amps is not None:
            out.append(f"with the brightness limiter at the Outputs frame's {st['supply_ma'] / 1000:g} A, the strip draws at most "
                       f"{self.limiter_amps:.1f} A - full white is dimmed to fit")
        out.append(f"{self.feeds()} feed(s) on {len(self.runs)} run(s) of strip; the worst LED {self.worst():.2f} V down "
                   f"({self.worst() / self.volts * 100:.0f} % of {self.volts} V; {st['drop']:g} V allowed)"
                   + (" - feeding it at the first LED is enough" if self.feeds() == 1 else ""))
        return out


def wire_for(amps):
    """(AWG, mm2) for a feed carrying `amps`."""
    for a, awg, mm2 in WIRE:
        if amps <= a:
            return awg, mm2
    return WIRE[-1][1], WIRE[-1][2]


def supply_for(amps):
    """The smallest common supply rating at or above amps with a fifth to spare."""
    need = amps * 1.2
    return next((s for s in SUPPLIES if s >= need), math.ceil(need))


def plan(pos, spacing_units, mm_per_unit, st):
    """The plan for LEDs at `pos` (wiring order, shape units): the feeds along the whole chain, and
    the runs of strip with the feeds and the worst drop on each."""
    P = Plan()
    P.settings, P.volts = st, st["volts"]
    pos = np.asarray(pos, np.float64)
    n = len(pos)
    amps = st["ma"] / 1000.0 * st["bri"]                # each LED
    if n == 0:
        return P
    step_u = np.linalg.norm(np.diff(pos, axis=0), axis=1) if n > 1 else np.zeros(0)
    step_m = step_u * mm_per_unit / 1000.0
    lead = step_u > GAP * spacing_units
    r = np.where(lead, LEAD_OHM_M, st["ohm_m"]) * step_m   # both rails (or both wires), between neighbours
    feeds = [0]
    d = drops(n, r, amps, feeds)
    if d.max() > st["drop"] and n > 1:
        strip_m = step_m[~lead]
        avg = float(strip_m.mean()) if len(strip_m) else float(step_m.mean())
        I_m = amps / max(avg, 1e-9)                        # amps a metre of strip
        s_m = math.sqrt(8.0 * st["drop"] / (st["ohm_m"] * I_m))
        k = max(1, int(s_m / max(avg, 1e-9)))
        while True:
            feeds = list(range(0, n, k))
            d = drops(n, r, amps, feeds)
            if d.max() <= st["drop"] or k == 1:
                break
            k = max(1, int(k * 0.9))
    fs = np.asarray(feeds)
    for a, b, length_u in runs(pos, spacing_units):
        P.runs.append({"first": a, "end": b, "leds": b - a, "metres": length_u * mm_per_unit / 1000.0,
                       "feeds": [int(f) for f in fs[(fs >= a) & (fs < b)]], "drop": float(d[a:b].max()), "amps": (b - a) * amps})
    P.amps = n * amps
    P.feed_list = [int(f) for f in feeds]
    if P.amps > 0:
        s = supply_for(P.amps)
        P.supply = (s, s * P.volts)
    if st.get("supply_ma"):
        P.limiter_amps = min(P.amps, max(0.0, (st["supply_ma"] - 120) / 1000.0))
    return P


def for_geometry(g, outputs_opts=None):
    """The plan for a shape geometry (None for any other): its LEDs in wiring order, a spacing a unit."""
    if g is None or g.kind != "shape":
        return None
    from native import shapes, units
    pos, _, _ = shapes.resolve(g.params.get("parts") or [])
    if len(pos) == 0:
        return None
    return plan(pos, 1.0, units.mm(g.params), settings(g.params, outputs_opts))
