"""MIDI learn without a controller: the messages parsed, a mapping bound
and unbound, a control's value as each target wants it, and the port
list (empty or not) with or without python-rtmidi. Run with
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
    assert st == {"port": "", "maps": []} and P.options["midi"] is st
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
