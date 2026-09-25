"""Real sizes for a shape: its LED density and the unit it is shown in.

A shape's own unit is the LED pitch (shapes.py): a strip of pitch 1 has
its LEDs one unit apart. What a pitch is on the bench is the strip's
density - 60 LEDs a metre is a pitch of 16.7 mm - so a shape keeps one
(`density`, LEDs a metre, 60 unless set) and a unit to show lengths in
(`unit`: mm, cm or in). Only what is shown changes: the positions stay in
pitches, and the device's table is fitted to its box as before.

    units.mm(params)                 # millimetres a unit
    units.show(3.0, params)          # "5 cm" - a length in the shape's units, in words
    units.to_unit(3.0, params)       # 5.0 - the number, in the chosen unit
    units.from_unit(5.0, params)     # 3.0 - back into the shape's units
    units.grid(params, extent)       # a round grid step near a fraction of the extent
"""
import math

UNITS = {"mm": 1.0, "cm": 10.0, "in": 25.4}
DENSITIES = (30, 60, 96, 144)           # the strips sold: LEDs a metre
DEFAULT_DENSITY = 60.0
DEFAULT_UNIT = "cm"


def density(params):
    """LEDs a metre at pitch 1 (the shape's `density`, 60 when unset)."""
    try:
        d = float((params or {}).get("density", DEFAULT_DENSITY) or DEFAULT_DENSITY)
    except (TypeError, ValueError):
        d = DEFAULT_DENSITY
    return min(2000.0, max(1.0, d))


def unit(params):
    u = (params or {}).get("unit", DEFAULT_UNIT)
    return u if u in UNITS else DEFAULT_UNIT


def mm(params):
    """Millimetres in one of the shape's units (one LED pitch)."""
    return 1000.0 / density(params)


def to_unit(v, params):
    """A length in the shape's units as a number in the chosen unit."""
    return float(v) * mm(params) / UNITS[unit(params)]


def from_unit(v, params):
    """A number in the chosen unit back into the shape's units."""
    return float(v) * UNITS[unit(params)] / mm(params)


def digits(value):
    """Decimals worth showing for a number this size in cm or inches."""
    a = abs(value)
    return 0 if a >= 100 else 1 if a >= 10 else 2 if a >= 0.1 or a == 0 else 3


def number(v, params):
    """A length in the shape's units as the chosen unit's number, rounded to
    what is worth showing, no unit: "12.5"."""
    x = to_unit(v, params)
    s = f"{x:.{digits(x)}f}"
    return s.rstrip("0").rstrip(".") if "." in s else s


def show(v, params, exact=False):
    """A length in words: "12.5 cm", "1.2 m" (a metre or more, from cm or
    mm), "18 in" (inches stay inches). `exact`: the unit asked for, never
    promoted to metres."""
    u = unit(params)
    x = to_unit(v, params)
    if u == "cm" and abs(x) >= 100 and not exact:
        m = x / 100.0
        return f"{m:.{2 if abs(m) < 10 else 1}f}".rstrip("0").rstrip(".") + " m"
    if u == "mm" and abs(x) >= 1000 and not exact:
        m = x / 1000.0
        return f"{m:.{2 if abs(m) < 10 else 1}f}".rstrip("0").rstrip(".") + " m"
    s = f"{x:.{digits(x)}f}"
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return f"{s} {u}"


# round steps for a grid or a snap, in each unit (a ruler's divisions)
_STEPS = {"mm": [1, 2, 5, 10, 20, 50, 100, 200, 500, 1000, 2000, 5000, 10000],
          "cm": [0.1, 0.2, 0.5, 1, 2, 5, 10, 20, 50, 100, 200, 500, 1000],
          "in": [0.125, 0.25, 0.5, 1, 2, 3, 6, 12, 24, 36, 48, 120, 240, 480]}


def round_step(target, params):
    """The ruler division nearest `target` (in the shape's units), in the
    shape's units - so a grid or a snap falls on round distances."""
    u = unit(params)
    t = to_unit(target, params)
    if t <= 0 or not math.isfinite(t):
        return from_unit(_STEPS[u][0], params)
    best = min(_STEPS[u], key=lambda s: abs(math.log(s / t)))
    return from_unit(best, params)


def grid(params, extent, frac=0.45):
    """A round step near `frac` of the extent (the shape's units): the
    floor's lines, a drag's snap."""
    return round_step(extent * frac, params)


def density_label(params):
    d = density(params)
    return f"{d:g} a metre ({show(1.0, dict(params or {}, unit='mm'), exact=True)} apart)"
