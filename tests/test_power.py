"""Power planning (power_plan.py): the voltage drop along a strip solved
exactly, feeds placed so no LED sags past the drop allowed, runs split at
lead wires, and the supply and wire for them. Run with
python tests/test_power.py  (or pytest).
"""
import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from native import power_plan as PP, shapes        # noqa: E402
from native.geometry import Geometry               # noqa: E402

MM60 = 1000.0 / 60.0                               # a unit is one spacing of a 60-a-metre strip


def _line(n, start=0.0):
    return np.stack([np.arange(n) + start, np.zeros(n), np.zeros(n)], 1).astype(float)


def test_the_drop_is_the_closed_form():
    # fed at one end, the far LED is R I L^2 / 2 down (5 m of 60/m strip, 0.1 ohm/m, 55 mA an LED)
    n, L = 301, 5.0
    d = PP.drops(n, 0.1 * L / (n - 1), 0.055, [0])
    want = 0.1 * (0.055 * 60) * L * L / 2
    assert abs(d.max() - want) / want < 0.02 and d[0] == 0 and np.all(np.diff(d) >= 0)
    # fed at both ends, the middle is R I L^2 / 8 down
    d2 = PP.drops(n, 0.1 * L / (n - 1), 0.055, [0, n - 1])
    assert abs(d2.max() - want / 4) / (want / 4) < 0.02 and abs(int(np.argmax(d2)) - n // 2) <= 1


def test_feeds_keep_every_led_within_the_drop():
    st = PP.settings({})
    assert (st["volts"], st["ma"], st["ohm_m"], st["drop"], st["bri"]) == (5, 55.0, 0.10, 0.5, 1.0)
    p = PP.plan(_line(300), 1.0, MM60, st)
    r = p.runs[0]
    assert r["leds"] == 300 and abs(r["metres"] - 299 / 60) < 1e-6
    assert len(r["feeds"]) >= 2 and r["feeds"][0] == 0 and r["drop"] <= 0.5 + 1e-9
    # one feed fewer would not do
    fewer = PP.drops(300, 0.1 / 60, 0.055, r["feeds"][:-1])
    assert fewer.max() > 0.5
    assert abs(p.amps - 300 * 0.055) < 1e-9 and p.supply == (20, 100)
    # a short run: fed at its start is enough
    short = PP.plan(_line(30), 1.0, MM60, st)
    assert short.runs[0]["feeds"] == [0] and "is enough" in short.lines({})[-1]
    # many short runs joined by leads (a sign's letters): one chain, not a feed for every letter
    letters = np.concatenate([_line(15, start=k * 20.0) for k in range(6)])
    assert PP.plan(letters, 1.0, MM60, st).feeds() == 1


def test_twelve_volts_go_further_and_dimmer_plans_less():
    long = _line(600)                                                    # 10 m
    five = PP.plan(long, 1.0, MM60, PP.settings({}))
    twelve = PP.plan(long, 1.0, MM60, PP.settings({"power": {"volts": 12}}))
    assert len(twelve.runs[0]["feeds"]) < len(five.runs[0]["feeds"])
    half = PP.plan(long, 1.0, MM60, PP.settings({"power": {"bri": 0.5}}))
    assert len(half.runs[0]["feeds"]) < len(five.runs[0]["feeds"]) and abs(half.amps - five.amps / 2) < 1e-9


def test_a_lead_starts_a_new_run():
    pos = np.concatenate([_line(20), _line(20, start=40.0)])            # a 21-spacing gap: a lead wire
    p = PP.plan(pos, 1.0, MM60, PP.settings({}))
    assert [(r["first"], r["end"]) for r in p.runs] == [(0, 20), (20, 40)]
    assert [r["feeds"] for r in p.runs] == [[0], []] and p.feeds() == 1     # the lead carries the power on
    assert p.runs[1]["drop"] > p.runs[0]["drop"] > 0                         # further from the feed, further down
    g = Geometry("shape", parts=[shapes.new_part("strip", n=40), shapes.new_part("ring", n=24)],
                 power={"volts": 5})
    pl = PP.for_geometry(g)
    assert pl is not None and sum(r["leds"] for r in pl.runs) == 64


def test_supply_wire_and_limiter():
    assert PP.supply_for(16.5) == 20 and PP.supply_for(0.5) == 1 and PP.supply_for(100) == math.ceil(120)
    assert PP.wire_for(3.0) == (22, 0.35) and PP.wire_for(9.0) == (16, 1.5) and PP.wire_for(99) == (10, 6.0)
    p = PP.plan(_line(300), 1.0, MM60, PP.settings({}, {"max_ma": 5000}))
    assert abs(p.limiter_amps - 4.88) < 1e-9 and any("limiter" in s for s in p.lines({}))


if __name__ == "__main__":
    import inspect
    bad = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and inspect.isfunction(fn):
            try:
                fn(); print("ok  ", name)
            except Exception as ex:
                bad += 1; print("FAIL", name, repr(ex)[:3000])
    sys.exit(1 if bad else 0)
