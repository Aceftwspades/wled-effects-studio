"""MIDI learn without a controller: the messages parsed, a mapping bound
and unbound, a control's value as each target wants it, and the port
list (empty or not) with or without python-rtmidi. A MIDI clock
followed: its tempo, its beats, none while stopped, and the synth's own
beat quiet while it plays. Live effect switching: a Program Change
parsed, the setlist picked from by number or by place, next and
previous stepping and wrapping, a note-off never switching. Run with
python tests/test_midi.py  or through pytest.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from native import midi                                # noqa: E402


def test_messages_parse_to_controls():
    assert midi.parse([0xB0, 7, 100]) == (("cc", 0, 7), 100)
    assert midi.parse([0xB5, 1, 0]) == (("cc", 5, 1), 0)
    assert midi.parse([0x90, 60, 90]) == (("note", 0, 60), 90)
    assert midi.parse([0x80, 60, 40]) == (("note", 0, 60), 0)             # off: 0 whatever the velocity
    assert midi.parse([0xE1, 0, 64]) == (("bend", 1, 0), 64)
    assert midi.parse([0xC2, 5]) == (("pc", 2, 0), 5)                     # Program Change: the number is the value
    assert midi.ctl_label(("pc", 2, 0)) == "program change ch 3"
    assert midi.parse([0xF8]) is None and midi.parse([]) is None          # a clock tick, nothing
    assert midi.ctl_label(("cc", 0, 7)) == "CC 7 ch 1" and midi.ctl_label(("note", 9, 36)) == "note 36 ch 10"


def test_a_port_queues_for_the_main_thread():
    m = midi.MidiIn()
    m.inject([0xB0, 7, 10]); m.inject([0xB0, 7, 20]); m.inject([0xF8]); m.inject([0x90, 1, 127])
    evs = m.drain()
    assert evs == [(("cc", 0, 7), 10), (("cc", 0, 7), 20), (("note", 0, 1), 127)]
    assert m.last[0] == ("note", 0, 1) and m.last[1] == 127
    assert m.drain() == []
    assert isinstance(midi.ports(), list)                                # with or without rtmidi
    if not midi.available():
        try:
            m.open("anything"); assert False, "opened a port without rtmidi"
        except RuntimeError as e:
            assert "python-rtmidi" in str(e)
    m.close()


def test_maps_bind_once_and_unbind():
    class P:
        options = {}
    st = midi.state(P)
    assert st == {"port": "", "maps": [], "clock": True, "setlist": [], "pc": True, "xfade": 0.0, "xstyle": "fade",
                  "osc": {"on": False, "port": 9000}}         and P.options["midi"] is st                                      # a port's clock followed; OSC off (osc.py)
    P.options["midi"]["osc"] = "on"                                      # a hand-edited project: made right again
    assert midi.state(P)["osc"] == {"on": False, "port": 9000}
    midi.bind(st, ("cc", 0, 7), {"kind": "fx", "key": "sx"})
    midi.bind(st, ("cc", 0, 7), {"kind": "fx", "key": "sx"})             # the same pair once
    midi.bind(st, ("cc", 0, 7), {"kind": "fx", "key": "ix"})             # one knob, two targets
    assert [m["target"]["key"] for m in st["maps"]] == ["sx", "ix"]
    assert st["maps"][0]["ctl"] == ["cc", 0, 7]                          # a list: JSON-safe
    midi.unbind(st, 0); midi.unbind(st, 5)
    assert [m["target"]["key"] for m in st["maps"]] == ["ix"]


def test_values_as_the_targets_want_them():
    assert midi.value_for({"kind": "fx", "key": "sx"}, 127) == 255
    assert midi.value_for({"kind": "fx", "key": "sx"}, 0) == 0
    assert midi.value_for({"kind": "fx", "key": "c3"}, 127) == 31          # custom3 is five bits
    assert midi.value_for({"kind": "check", "key": "o1"}, 63) is False
    assert midi.value_for({"kind": "check", "key": "o1"}, 64) is True
    assert abs(midi.value_for({"kind": "pin", "lo": 2.0, "hi": 12.0}, 127) - 12.0) < 1e-9
    assert abs(midi.value_for({"kind": "pin", "lo": -1.0, "hi": 1.0}, 0) + 1.0) < 1e-9
    assert midi.value_for({"kind": "pin", "bool": True}, 100) is True
    assert abs(midi.value_for({"kind": "palette"}, 127) - 1.0) < 1e-9
    assert midi.value_for({"kind": "effect"}, 200) == 1.0                  # clamped


def test_the_setlist_and_stepping():
    names = ["A", "B", "C", "D", "E"]
    sl = ["D", "gone", "B", "E"]                                        # one no longer in the build: skipped
    pc = ("pc", 0, 0)
    assert midi.setlist_pick(names, sl, pc, 0) == "D"                   # program 1 (sent as 0) the first
    assert midi.setlist_pick(names, sl, pc, 2) == "E"
    assert midi.setlist_pick(names, sl, pc, 3) is None                  # beyond the list: nothing
    assert midi.setlist_pick(names, sl, ("cc", 0, 1), 127) == "E"       # a knob: by place along it
    assert midi.setlist_pick(names, sl, ("cc", 0, 1), 0) == "D"
    assert midi.setlist_pick(names, [], pc, 0) is None
    assert midi.step_effect(names, sl, "B", 1) == "E" and midi.step_effect(names, sl, "E", 1) == "D"   # wraps
    assert midi.step_effect(names, sl, "D", -1) == "E"
    assert midi.step_effect(names, sl, "A", 1) == "D" and midi.step_effect(names, sl, "A", -1) == "E"  # off the list
    assert midi.step_effect(names, [], "E", 1) == "A"                   # no setlist: the whole list


def test_switches_fire_on_the_press_only():
    nxt, eff, fx = {"kind": "next"}, {"kind": "effect"}, {"kind": "fx", "key": "sx"}
    note, cc = ("note", 0, 36), ("cc", 0, 20)
    assert midi.fires(nxt, note, 100, None) and not midi.fires(nxt, note, 0, 100)      # press, not release
    assert not midi.fires(eff, note, 0, 90)                             # a pad released never jumps to the first
    assert midi.fires(eff, note, 90, 0)
    assert midi.fires(nxt, cc, 127, 0) and not midi.fires(nxt, cc, 127, 120)           # a knob crossing the middle, once
    assert not midi.fires(nxt, cc, 30, 0)
    assert midi.fires(nxt, ("osc", "/next", 0), 1.0, 0.0, full=1.0)     # an OSC button: 0..1
    assert midi.fires(fx, note, 0, 90)                                  # a slider still takes every value


def test_a_clock_is_followed():
    m = midi.MidiIn()
    t, dt = 100.0, 60.0 / (125.0 * midi.CLOCK_PPQN)           # 125 bpm
    m.inject([0xFA], now=t)                                    # start: the next tick is beat one
    for k in range(48):
        m.inject([0xF8], now=t + k * dt)
    n, bpm, playing = m.take_clock(now=t + 47 * dt)
    assert n == 2 and playing and abs(bpm - 125.0) < 0.5, (n, bpm, playing)
    assert m.drain() == []                                     # ticks are not controls: Learn never binds one
    m.inject([0xFC], now=t + 48 * dt)                          # stop: the ticks go on, the beats do not
    for k in range(48, 96):
        m.inject([0xF8], now=t + k * dt)
    n, bpm, playing = m.take_clock(now=t + 95 * dt)
    assert n == 0 and not playing and abs(bpm - 125.0) < 0.5, (n, bpm, playing)
    m.inject([0xFB], now=t + 96 * dt)                          # continue: on the beat where it stopped
    m.inject([0xF8], now=t + 96 * dt)
    assert m.take_clock(now=t + 96 * dt)[:1] == (1,)
    n, bpm, playing = m.take_clock(now=t + 96 * dt + 0.6)      # half a second without a tick: gone
    assert n == 0 and bpm is None and not playing
    # a clock that never says start: its beats counted from the first tick heard
    f = midi.MidiIn()
    for k in range(25):
        f.inject([0xF8], now=200.0 + k * dt)
    assert f.take_clock(now=200.0 + 24 * dt)[0] == 2


def test_the_synth_beat_follows_the_clock():
    import numpy as np
    from native.synth import Synth

    class Eng:
        sim_ms = 0
        fft = np.zeros(16, np.uint8)

        def audio(self, v, peak):
            pass

        def audio_peak(self):
            pass
    e, s = Eng(), Synth(bpm=120)
    fired = []
    for k in range(200):                                       # 5 s at 25 ms: its own beat, 120 bpm
        e.sim_ms = k * 25
        fired.append(s.push(e))
    assert sum(fired) >= 9
    s.external, fired = True, []                               # the clock's: quiet but for its beats
    for k in range(200, 400):
        e.sim_ms = k * 25
        if k == 300:
            s.kick_req = True
        fired.append(s.push(e))
    assert sum(fired) == 1 and fired[100] == 1


if __name__ == "__main__":
    import inspect
    bad = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and inspect.isfunction(fn):
            try:
                fn(); print("ok  ", name)
            except Exception as ex:
                bad += 1; print("FAIL", name, str(ex)[:3000])
    sys.exit(1 if bad else 0)
