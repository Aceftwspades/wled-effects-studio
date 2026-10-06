"""The device's effect bank and live effect switching, offline against the
fake WLED (tests/fake_wled.py): the slot hash as the firmware computes it,
the block read, written whole (six_faces kept) and applied by a reboot,
and the Switcher setting the device's effect by name - with the device's
own defaults, a one-off transition, and a refusal for an effect it lacks.
Run with  python tests/test_bank.py  (or pytest).
"""
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

from fake_wled import FakeWled, ROSTER                    # noqa: E402
from native import bank                                   # noqa: E402

DEV = None


def setup_module(_=None):
    global DEV
    DEV = FakeWled(port=8774, ddp_port=4052).start()
    time.sleep(0.2)


def teardown_module(_=None):
    if DEV:
        DEV.stop()


def test_the_hash_is_the_firmwares():
    # computed by cube_fx_bank.h's cfxBankHash, compiled (2026-10-06)
    assert bank.fx_hash("Ace 3-D Paintball@Drip speed") == 15438                 # up to the '@'
    assert bank.fx_hash("Ace 3-D Murmuration") == 64450
    assert bank.fx_hash("Ace 3-D Jelly Bounce") == 22638
    assert bank.fx_hash("Studio Script") == 43597
    assert bank.slot_key(0) == "s00" and bank.slot_key(35) == "s35"


def test_slots_named_and_blocks_whole():
    names = ["Ace 3-D Paintball", "Ace 3-D Murmuration"]
    hs = [bank.fx_hash(names[1]), 0, 12345, bank.fx_hash(names[0])]
    assert bank.slot_names(hs, names) == ["Ace 3-D Murmuration", None, "?", "Ace 3-D Paintball"]
    b = bank.block_for(["Ace 3-D Paintball", None, "Ace 3-D Murmuration"], {"enabled": False, "six_faces": True, "slots": [0] * 36})
    assert b["enabled"] is True and b["six_faces"] is True                       # six_faces kept, the bank on
    assert b["s00"] == bank.fx_hash("Ace 3-D Paintball") and b["s01"] == 0 and b["s02"] == bank.fx_hash("Ace 3-D Murmuration")
    assert all(f"s{i:02d}" in b for i in range(36)) and b["s35"] == 0             # every slot: a missing one would read 0
    assert bank.parse_block({"enabled": True, "s00": 7, "s01": 8})["slots"] == [7, 8]
    assert bank.parse_block(None) is None


def test_write_reboot_and_the_list():
    st = bank.read(DEV.host)
    assert st and st["enabled"] and len(st["slots"]) == 36 and not any(st["slots"])     # none chosen: all registered
    assert "placed" in bank.status(DEV.host)[0]
    DEV.cfg["um"]["CubeFXBank"]["six_faces"] = True                               # the cube has a bottom: must survive
    order = ["Ace 3-D Jelly Bounce", "Studio Script", "Ace 3-D Paintball"]
    ok, msg = bank.write(DEV.host, order)
    assert ok and "rebooting" in msg, msg
    assert DEV.reboots >= 1 and DEV.cfg["um"]["CubeFXBank"]["six_faces"] is True
    st = bank.read(DEV.host)
    assert bank.slot_names(st["slots"][:4], ROSTER) == order + [None]
    ace = [n for n in DEV.effects if n in ROSTER]
    assert ace == order                                                           # in slot order, the rest left out
    ok, msg = bank.write(DEV.host, [None, None])
    assert not ok and "keep at least one" in msg                                  # all empty would mean "every effect"


def test_the_six_face_push_keeps_the_slots():
    """The studio's six-face push (flash.push_settings / push_segments) once sent the bank block with
    six_faces alone - which the firmware reads as every slot empty."""
    from native import flash
    before = list(bank.read(DEV.host)["slots"])
    assert any(before)
    ok, msg = flash.push_segments(DEV.host, [{"effect": "Solid", "fx": {}, "pal": 0, "bounds": [0, 0, 48, 48]}],
                                  [0, 0, 0], (48, 48), lambda p: "Default", six=False)
    assert ok and "five faces" in msg, msg
    st = bank.read(DEV.host)
    assert st["slots"] == before and st["six_faces"] is False


def test_the_device_switched_by_name():
    sw = bank.Switcher()
    sw.send(DEV.host, "Ace 3-D Paintball", tt=15, bs=3)
    t0 = time.time()
    while not sw._out and time.time() - t0 < 5:
        time.sleep(0.05)
    msgs = sw.messages()
    assert msgs and msgs[0][0], msgs
    seg = DEV.state["seg"][0]
    assert DEV.effects[seg["fx"]] == "Ace 3-D Paintball" and seg.get("fxdef") is True
    sw.send(DEV.host, "Ace 3-D Murmuration")                                     # not in the slots chosen above
    t0 = time.time()
    while not sw._out and time.time() - t0 < 5:
        time.sleep(0.05)
    ok, msg = sw.messages()[0]
    assert not ok and "give it a slot" in msg, msg
    assert DEV.effects[DEV.state["seg"][0]["fx"]] == "Ace 3-D Paintball"           # left as it was


if __name__ == "__main__":
    import inspect
    setup_module()
    bad = 0
    try:
        for name, fn in list(globals().items()):
            if name.startswith("test_") and inspect.isfunction(fn):
                try:
                    fn(); print("ok  ", name)
                except Exception as ex:
                    bad += 1; print("FAIL", name, str(ex)[:3000])
    finally:
        teardown_module()
    sys.exit(1 if bad else 0)
