"""LED outputs: the wiring split into the device's busses, and the power
it draws.

WLED drives LEDs in busses - each a pin, a start index, a length, an LED
type, a colour order, reversed or not - listed in its config as
`hw.led.ins`; the studio's shape gives the wiring order and the count,
this gives the outputs. Three ways to split: one output for the lot, one
per part of a shape (a part is a run of the wiring on the strip layout),
or by count (every N LEDs a new output, for a controller with several
ports). Sent to the device over /json/cfg, which re-initialises its
outputs.

Power: each LED draws up to `ma_per_led` at full white (WLED's default
55 mA), a frame's draw is the sum over its pixels of that scaled by the
brightness of each channel, and WLED's auto brightness limiter (ABL)
dims the whole frame to fit `max_ma` - the same maths the device uses
(BusManager::estimateCurrentAndLimitBri).

    outs = split(count, parts=[(name, n), ...], by="parts")     # [{pin, start, len, ...}]
    cfg = wled_cfg(outs, ma_per_led, max_ma)                     # the /json/cfg body
    ma, scale = power(rgb, phys, ma_per_led, max_ma, bri)        # a frame's current and the ABL's dimming
"""
import numpy as np

# (WLED type id, name, channels): what the type combo offers
TYPES = [(22, "WS2812 / WS2815 RGB", 3), (30, "SK6812 RGBW", 4), (24, "WS2811 400 kHz", 3), (31, "TM1814 RGBW", 4),
         (32, "WS2805 RGB+CCT", 5), (25, "TM1829", 3), (26, "UCS8903", 3), (23, "GS8608", 3),
         (51, "APA102 (data + clock)", 3), (50, "WS2801 (data + clock)", 3)]
ORDERS = [(0, "GRB"), (1, "RGB"), (2, "BRG"), (3, "RBG"), (4, "BGR"), (5, "GBR")]
DEFAULT_PINS = [16, 17, 18, 19, 21, 22, 23, 25, 26, 27]        # an ESP32's usual free outputs, first come first served
MAX_BUSSES = 10
LED_MA_DEFAULT = 55
MAX_MA_DEFAULT = 850


def new_output(pin, start, n, k=0):
    return {"pin": int(pin), "start": int(start), "len": int(n), "type": 22, "order": 0, "rev": False, "skip": 0,
            "name": f"output {k + 1}"}


def split(count, parts=None, by="one", per=300, pins=None):
    """The outputs for `count` LEDs: by "one", "parts" ([(name, n)]) or "count" (per)."""
    pins = list(pins or DEFAULT_PINS)
    outs = []
    if by == "parts" and parts:
        start = 0
        for k, (name, n) in enumerate(parts):
            if n <= 0:
                continue
            if len(outs) >= MAX_BUSSES:
                outs[-1]["len"] += n; continue                 # past ten busses: the rest joins the last
            o = new_output(pins[len(outs) % len(pins)], start, n, len(outs)); o["name"] = name
            outs.append(o); start += n
    elif by == "count":
        per = max(1, int(per))
        start = 0
        while start < count:
            n = min(per, count - start)
            if len(outs) >= MAX_BUSSES:
                outs[-1]["len"] += count - start; break
            outs.append(new_output(pins[len(outs) % len(pins)], start, n, len(outs))); start += n
    else:
        outs.append(new_output(pins[0], 0, max(1, count), 0))
    return outs


def wled_cfg(outs, ma_per_led=LED_MA_DEFAULT, max_ma=MAX_MA_DEFAULT):
    """The /json/cfg body that sets the device's outputs (hw.led.ins) and its power limit."""
    ins = []
    total = 0
    for o in outs:
        d = {"start": int(o["start"]), "len": int(o["len"]), "pin": [int(o["pin"])] + ([int(o["clock"])] if o.get("clock") is not None else []),
             "order": int(o.get("order", 0)), "rev": bool(o.get("rev")), "skip": int(o.get("skip", 0)), "type": int(o.get("type", 22)),
             "ref": False, "rgbwm": 0, "freq": 0, "ledma": int(ma_per_led), "maxpwr": 0}
        ins.append(d); total = max(total, d["start"] + d["len"])
    for d in ins:                                              # each output's share of the limit, as WLED computes it without one
        d["maxpwr"] = int(max_ma * d["len"] / max(1, total))
    return {"hw": {"led": {"total": total, "maxpwr": int(max_ma), "ledma": int(ma_per_led), "ins": ins}}}


def from_wled_cfg(cfg):
    """The device's outputs as the studio keeps them, from its /json/cfg."""
    led = ((cfg or {}).get("hw") or {}).get("led") or {}
    outs = []
    for k, e in enumerate(led.get("ins") or []):
        pins = e.get("pin") or [0]
        o = new_output(pins[0], e.get("start", 0), e.get("len", 1), k)
        o.update({"type": int(e.get("type", 22)) & 0x7F, "order": int(e.get("order", 0)) & 0x0F, "rev": bool(e.get("rev")), "skip": int(e.get("skip", 0))})
        if len(pins) > 1:
            o["clock"] = pins[1]
        outs.append(o)
    return outs, int(led.get("ledma", LED_MA_DEFAULT) or LED_MA_DEFAULT), int(led.get("maxpwr", MAX_MA_DEFAULT) or 0)


MA_FOR_ESP = 120                                               # what the ESP32 itself draws, as WLED subtracts it


def power(rgb, phys, ma_per_led=LED_MA_DEFAULT, max_ma=MAX_MA_DEFAULT, bri=255):
    """A frame's current in mA at brightness `bri`, and the factor WLED's
    auto brightness limiter would scale the brightness by to fit `max_ma`
    (1.0 when it fits; max_ma 0 is no limit) - the device's own maths
    (BusDigital::estimateCurrent, BusManager::applyABL): the colour sum
    over the LEDs times the LED's full-white current over 3 x 255, plus a
    milliamp a LED standing by, against the limit less the ESP's 120 mA."""
    flat = np.asarray(rgb, np.uint8).reshape(-1, 3).astype(np.float64)
    idx = np.asarray(phys, int)
    idx = idx[(idx >= 0) & (idx < len(flat))]
    n = len(idx)
    ma = float(flat[idx].sum() * (bri / 255.0) * float(ma_per_led) / 765.0) + n
    if max_ma <= 0:
        return ma, 1.0
    budget = max(1, int(max_ma) - MA_FOR_ESP)
    if budget <= n or ma <= budget:
        return ma, (1.0 if ma <= budget else 1.0 / 255)
    return ma, budget / ma
