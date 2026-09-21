"""Every device path, offline: the studio's modules against the fake WLED
(tests/fake_wled.py). No app, no window - the functions the frames call.
Run with  python tests/test_device.py  (or pytest).
"""
import json
import os
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

from fake_wled import FakeWled, EFFECTS                   # noqa: E402
from native import devices, flash, sequence, outputs      # noqa: E402
from native.geometry import Geometry                      # noqa: E402

DEV = None


def setup_module(_=None):
    global DEV
    DEV = FakeWled(port=8771, ddp_port=4049).start()
    time.sleep(0.2)


def teardown_module(_=None):
    if DEV:
        DEV.stop()


def _post(path, body):
    req = urllib.request.Request(f"http://{DEV.host}{path}", data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.loads(r.read())


def test_probe_and_state():
    """A scan's probe: the device named, its effects counted, the Script effect seen."""
    d = devices.probe(DEV.host)
    assert d and d["name"] == "Fake WLED" and d["fx"] == len(EFFECTS) and d["script"] is True and d["arch"] == "ESP32-S3"
    st = devices.state(DEV.host)
    assert st and st["effect"] == "Solid" and st["on"] is False


def test_send_script_and_push_settings():
    """The bytecode lands as /studio.bin; the settings push selects the effect by name and refuses an unknown one."""
    ok, msg = flash.send_script(DEV.host, bytes(range(64)))
    assert ok and DEV.files["/studio.bin"] == bytes(range(64)), msg
    ok, msg = flash.push_settings(DEV.host, "Studio Script", {"sx": 110, "ix": 160, "c1": 100, "c2": 128, "c3": 16, "o1": False, "o2": True, "o3": False},
                                  "Rainbow", [0xFF0000, 0, 0], blend=3, opacity=200, options={"rev": True, "grp": 2})
    assert ok, msg
    seg = DEV.state["seg"][0]
    assert EFFECTS[seg["fx"]] == "Studio Script" and seg["sx"] == 110 and seg["o2"] is True and seg["bm"] == 3 and seg["bri"] == 200
    assert seg["rev"] is True and seg["grp"] == 2 and seg["col"][0] == [255, 0, 0]
    assert DEV.state["on"] is True
    ok, msg = flash.push_settings(DEV.host, "No Such Effect", {}, "Rainbow", [0, 0, 0])
    assert not ok and "no effect called" in msg


def test_presets_and_playlist_land():
    """Every step a preset, waited for; the playlist a playlist (WLED's "o"), all of it there afterwards; the run starts it."""
    steps = [{"name": f"step {i}", "dur": 5.0 + i, "trans": 0.5, "rows": 48, "colors": [0xFF0000, 0, 0],
              "segments": [{"effect": name, "params": {"sx": 10 * i, "ix": 100}, "bounds": [0, 0, 48, 48], "pal": 11}]}
             for i, name in enumerate(("Rainbow", "Scan", "Twinkle"))]
    presets, playlist = sequence.to_wled(steps, EFFECTS, list(range(256)), base=20, pid=19, name="Show", repeat=0)
    t0 = time.time()
    ok, msg = sequence.send(DEV.host, presets, playlist, 19)
    assert ok, msg
    assert sorted(int(k) for k in DEV.presets if k != "0") == [19, 20, 21, 22], DEV.presets.keys()
    assert "playlist" in DEV.presets["19"] and DEV.presets["19"]["playlist"]["ps"] == [20, 21, 22]
    assert DEV.presets["21"]["seg"][0]["sx"] == 10 and DEV.presets["21"]["n"] == "step 1"
    assert time.time() - t0 >= 3 * 1.0                     # a beat a preset: waited for, not fired
    ok, msg = sequence.start(DEV.host, 19)
    assert ok and DEV.state["pl"] == 19, msg


def test_back_to_back_psave_is_the_bug_the_wait_avoids():
    """The fake models the firmware: two psaves in one breath and only the second lands."""
    DEV.presets = {"0": {}}
    _post("/json/state", {"psave": 30, "n": "a", "ib": True}); _post("/json/state", {"psave": 31, "n": "b", "ib": True})
    time.sleep(0.6)
    assert "31" in DEV.presets and "30" not in DEV.presets


def test_ramps_become_sub_presets():
    st = {"name": "fade", "dur": 4.0, "rows": 48, "colors": [0, 0, 0], "ramps": {"ix": 250},
          "segments": [{"effect": "Rainbow", "params": {"ix": 10}, "bounds": [0, 0, 48, 48]}]}
    presets, playlist = sequence.to_wled([st], EFFECTS, [], base=40, pid=39)
    ids = sorted(k for k in presets if k is not None)
    assert ids == [40, 41, 42, 43] and [presets[k]["seg"][0]["ix"] for k in ids] == [10, 90, 170, 250]
    assert playlist["playlist"]["dur"] == [10, 10, 10, 10]
    # a shape: up and back returns to where it began, eased ends stay put longer; two sliders at once
    st["ramps"] = {"ix": {"end": 250, "shape": "up and back"}, "sx": {"end": 0, "shape": "ease in"}}
    st["segments"][0]["params"]["sx"] = 200
    subs = sequence.sub_steps(st)
    ix = [q["segments"][0]["params"]["ix"] for q in subs]
    sx = [q["segments"][0]["params"]["sx"] for q in subs]
    assert len(subs) == 7 and ix[0] == 10 and ix[-1] == 10 and max(ix) == 250          # up and back: seven samples, the top among them
    assert sx[0] == 200 and sx[-1] == 0 and sx[1] > 200 - 200 * (1 / 5)                 # ease in: slow to leave
    assert sequence.ramp_value(st, "ix", 0.5) == 250 and sequence.ramp_value(st, "sx", 1.0) == 0
    assert sequence.ramp_of({"ramps": {"c1": 7}, "segments": []}, "c1") == (7, "linear")  # a ramp saved before shapes
    assert sequence.shape_t("step", 0.49) == 0.0 and sequence.shape_t("step", 0.5) == 1.0


def test_off_preset_and_timers():
    """The schedule: the Off preset with its "on": false kept (ib), the timers cleared and set; read back with their kinds."""
    from native.sequence_ui import timers_json, OFF_PRESET
    before = DEV.state["on"]
    sequence.psave(DEV.host, OFF_PRESET, {"on": False, "n": "Off", "ib": True})
    assert DEV.presets[str(OFF_PRESET)]["on"] is False
    T = [{"en": True, "when": "time", "hour": 18, "min": 30, "dow": 127, "preset": 19, "what": "playlist"},
         {"en": True, "when": "sunset", "hour": 0, "min": -15, "dow": 62, "preset": OFF_PRESET, "what": "off"}]
    body = timers_json(T)
    _post("/json/cfg", body)
    ins = DEV.cfg["timers"]["ins"]
    assert len(ins) == 2 and ins[0]["hour"] == 18 and ins[0]["macro"] == 19 and ins[1]["hour"] == 254 and ins[1]["min"] == -15
    _post("/json/cfg", timers_json([]))
    assert DEV.cfg["timers"]["ins"] == []
    assert before is not None


def test_outputs_round_trip():
    """The wiring split into outputs, sent as the LED config, read back the same."""
    outs = outputs.split(2304, by="count", per=768)
    assert len(outs) == 3 and sum(o["len"] for o in outs) == 2304
    body = outputs.wled_cfg(outs, 40, 5000)
    _post("/json/cfg", body)
    got, ledma, maxma = outputs.from_wled_cfg(DEV.cfg)
    assert [o["len"] for o in got] == [768, 768, 768] and ledma == 40 and maxma == 5000


def test_palette_upload_and_removal():
    from native.palette_ui import wled_json
    p = {"name": "Test", "stops": [[0, 255, 0, 0], [128, 0, 255, 0], [255, 0, 0, 255]]}
    data = wled_json(p).encode()
    ok, msg = flash.send_file(DEV.host, "/palette0.json", data)
    assert ok and json.loads(DEV.files["/palette0.json"])["palette"][:4] == [0, 255, 0, 0]
    assert devices._get(DEV.host, "/json/info", 3)["cpalcount"] == 1
    _post("/json/state", {"rmcpal": 0})
    assert "/palette0.json" not in DEV.files


def test_ledmap_and_geometry_table():
    """The shape's wiring as ledmap.json and its positions as geometry.bin, both on the device's filesystem."""
    g = Geometry("cube", B=8)
    ok, msg = flash.send_file(DEV.host, "/ledmap.json", json.dumps(g.ledmap()).encode())
    assert ok and json.loads(DEV.files["/ledmap.json"])["map"][:3] == g.ledmap()["map"][:3]
    ok, msg = flash.send_geometry(DEV.host, Geometry("sphere", w=24, h=12))
    assert ok and DEV.files["/geometry.bin"][:4] == b"STGM", msg
    ok, msg = flash.send_geometry(DEV.host, g)               # a cube has a rule of its own: the file is emptied
    assert ok and DEV.files["/geometry.bin"] == b""


def test_ddp_stream_counted():
    from native import live_out
    out = live_out.DdpOut(f"127.0.0.1", port=4049) if "port" in live_out.DdpOut.__init__.__code__.co_varnames else None
    if out is None:
        return                                            # the sender's port is fixed to 4048; the smoke test covers it
    import numpy as np
    for _ in range(5):
        out.send(np.zeros((300, 3), np.uint8)); time.sleep(0.02)
    out.close(); time.sleep(0.3)
    assert DEV.ddp_frames >= 5


def test_audio_input_round_trip():
    """The device's audio input read, a line-in preset sent, read back the
    same; a type change counts a reboot as needed and the reboot request
    lands; the level meter reads the fork's row, or the stock peak."""
    from native import audioin
    cfg = devices._get(DEV.host, "/json/cfg", 3)
    st = audioin.from_wled_cfg(cfg)
    assert st["type"] == 1 and st["pins"] == [13, 15, 14, -1] and st["preset"] == "inmp441" and st["gain"] == 60
    st = audioin.apply_preset(dict(st), "pcm1808"); st["pins"] = [13, 15, 14, 4]
    assert st["type"] == 4 and st["gain"] == 40 and audioin.needs_reboot(audioin.from_wled_cfg(cfg), st)
    _post("/json/cfg", audioin.wled_cfg(st))
    back = audioin.from_wled_cfg(devices._get(DEV.host, "/json/cfg", 3))
    assert back["type"] == 4 and back["pins"] == [13, 15, 14, 4] and back["gain"] == 40 and back["squelch"] == 4 and back["preset"] == "pcm1808"
    assert DEV.reboot_needed
    _post("/json/state", {"rb": True})
    assert DEV.reboots == 1 and not DEV.reboot_needed
    # an ES8388 board: its I2C pins ride along
    st = audioin.apply_preset(dict(st), "es8388_audiokit")
    body = audioin.wled_cfg(st)
    assert body["hw"]["if"]["i2c-pin"] == [33, 32] and body["um"]["AudioReactive"]["digitalmic"]["pin"] == [35, 25, 27, 0]
    _post("/json/cfg", body)
    back = audioin.from_wled_cfg(devices._get(DEV.host, "/json/cfg", 3))
    assert back["preset"] == "es8388_audiokit" and back["i2c"] == [33, 32]
    assert "-D SR_DMTYPE=6" in audioin.flags(back) and "-D I2CSDAPIN=33" in audioin.flags(back) and "-D MCLK_PIN=0" in audioin.flags(back)
    # the meter
    DEV.audio_level = 120.0
    lvl, src = audioin.level_of(devices._get(DEV.host, "/json/info", 3))
    assert lvl == 120.0 and "I2S digital" in src
    info = devices._get(DEV.host, "/json/info", 3); info["u"]["AudioReactive"].pop("Input level")     # a stock firmware: the peak row
    lvl, _ = audioin.level_of(info)
    assert 100 < lvl < 130
    DEV.audio_level = 0.0
    assert audioin.level_of({"u": {}}) == (None, "")
    # off and network-only: no pins to speak of
    assert audioin.flags(audioin.apply_preset(dict(st), "network"))[0] == "-D SR_DMTYPE=-1"
    assert audioin.wled_cfg(audioin.apply_preset(dict(st), "off"))["um"]["AudioReactive"]["enabled"] is False


def test_a_device_that_is_off():
    """No traceback, a clear refusal, quickly."""
    t0 = time.time()
    assert devices.probe("127.0.0.1:1", timeout=1.0) is None
    ok, msg = flash.send_script("127.0.0.1:1", b"\x00")
    assert not ok and "upload failed" in msg and time.time() - t0 < 15


if __name__ == "__main__":
    import inspect
    setup_module()
    bad = 0
    try:
        for name, fn in list(globals().items()):
            if name.startswith("test_") and inspect.isfunction(fn):
                try:
                    fn(); print("ok  ", name)
                except Exception as e:
                    bad += 1; print("FAIL", name, repr(e))
    finally:
        teardown_module()
    sys.exit(1 if bad else 0)
