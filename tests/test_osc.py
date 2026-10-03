"""OSC in without a phone: messages and bundles parsed, the numbers in
them as controls with a position 0..1, what is not OSC refused (and
counted), a real datagram through a port on this machine's loopback, and
an OSC control learnt and mapped as a MIDI knob is. Run with
python tests/test_osc.py  or through pytest.
"""
import os
import socket
import struct
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from native import osc, midi                           # noqa: E402


def test_messages_and_bundles_parse():
    m = osc.message("/1/fader1", 0.25)
    assert len(m) % 4 == 0 and osc.parse(m) == [("/1/fader1", [0.25])]
    # every kind of argument: the numbers kept, a string and a blob stepped over
    s = b"/mix\0\0\0\0" + b",ifsbTFhd\0\0\0" + struct.pack(">i", 7) + struct.pack(">f", 0.5) + b"hi\0\0" \
        + struct.pack(">i", 3) + b"abc\0" + struct.pack(">q", 2) + struct.pack(">d", 0.75)
    assert osc.parse(s) == [("/mix", [7, 0.5, None, None, True, False, 2, 0.75])]
    b = osc.bundle(osc.message("/a", 1), osc.bundle(osc.message("/b", 0.5, 0.25)))
    assert osc.parse(b) == [("/a", [1]), ("/b", [0.5, 0.25])]
    assert osc.parse(b"/bare\0\0\0") == [("/bare", [])]                  # an old sender's message with no tags
    for junk in (b"", b"hello", b"/x\0\0,f\0\0\0\0", b"/x\0\0,q\0\0", b"#bundle\0" + b"\0" * 8 + struct.pack(">i", 99)):
        try:
            osc.parse(junk)
            assert junk == b"", junk                                         # b"" is not even a message
        except (ValueError, struct.error):
            pass
    deep = osc.message("/d", 1.0)
    for _ in range(osc.MAX_DEPTH + 2):
        deep = osc.bundle(deep)
    try:
        osc.parse(deep); assert False, "nested past MAX_DEPTH"
    except ValueError:
        pass


def test_numbers_become_positions():
    assert osc.fraction(0.4) == 0.4 and osc.fraction(1.7) == 1.0 and osc.fraction(-2.0) == 0.0
    assert osc.fraction(float("nan")) is None and osc.fraction(None) is None
    assert osc.fraction(1) == 1.0 and osc.fraction(0) == 0.0 and abs(osc.fraction(127) - 1.0) < 1e-9
    assert abs(osc.fraction(64) - 64 / 127) < 1e-9 and osc.fraction(True) == 1.0 and osc.fraction(False) == 0.0
    evs = osc.controls([("/xy", [0.2, 0.9]), ("/name", [None, 0.5])])
    assert evs == [(("osc", "/xy", 0), 0.2), (("osc", "/xy", 1), 0.9), (("osc", "/name", 1), 0.5)]


def test_a_port_on_the_loopback():
    o = osc.OscIn()
    port = o.open(0, "127.0.0.1")
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.sendto(b"not osc", ("127.0.0.1", port))
        s.sendto(osc.bundle(osc.message("/1/fader2", 0.5), osc.message("/1/toggle1", True)), ("127.0.0.1", port))
        s.close()
        got, end = [], time.time() + 3.0
        while len(got) < 2 and time.time() < end:
            got += o.drain()
            time.sleep(0.02)
        assert got == [(("osc", "/1/fader2", 0), 0.5), (("osc", "/1/toggle1", 0), 1.0)], got
        assert o.bad == 1 and o.last[0] == ("osc", "/1/toggle1", 0)
    finally:
        o.close()
    assert o.port is None
    taken = osc.OscIn()
    port = taken.open(0, "127.0.0.1")
    try:
        try:
            osc.OscIn().open(port, "127.0.0.1"); assert False, "two on one port"
        except OSError:
            pass
    finally:
        taken.close()


def test_an_osc_control_maps_as_a_knob_does():
    st = {"maps": []}
    midi.bind(st, ("osc", "/1/fader1", 0), {"kind": "fx", "key": "sx"})
    assert st["maps"] == [{"ctl": ["osc", "/1/fader1", 0], "target": {"kind": "fx", "key": "sx"}}]
    assert midi.ctl_label(("osc", "/1/fader1", 0)) == "OSC /1/fader1" and midi.ctl_label(("osc", "/xy", 1)) == "OSC /xy #2"
    # a position 0..1 (full 1.0) as each target wants it - finer than MIDI's 128 steps
    assert midi.value_for({"kind": "fx", "key": "sx"}, 0.5, full=1.0) == 128
    assert midi.value_for({"kind": "fx", "key": "c3"}, 1.0, full=1.0) == 31
    assert midi.value_for({"kind": "check", "key": "o1"}, 0.6, full=1.0) is True
    v = midi.value_for({"kind": "pin", "lo": 0.0, "hi": 10.0}, 0.123, full=1.0)
    assert abs(v - 1.23) < 1e-9
    assert midi.value_for({"kind": "fx", "key": "sx"}, 127) == 255                 # MIDI's scale stays the default


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
