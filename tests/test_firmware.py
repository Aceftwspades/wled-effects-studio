"""Firmware that is not the studio's own build, and the cube effects chosen
one by one - without a device or the network: a binary's chip read from its
image header (and one for another chip refused), WLED's release files
matched to a chip, the release list and a download through a file URL, the
built-in effects' catalogue, a trimmed cube_fx staged in a tree made for
the test, and a .bin flashed to the fake WLED (its /update), recorded - and
one for the wrong chip never sent. Run with  python tests/test_firmware.py
"""
import json
import os
import pathlib
import shutil
import struct
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))

from native import firmware, flash                      # noqa: E402


def image(chip_id=None, esp8266=False, size=4096):
    """A firmware image's first bytes as an ESP chip's bootloader reads them."""
    h = bytearray(24)
    h[0], h[1] = 0xE9, 3
    if esp8266:
        struct.pack_into("<I", h, 4, 0x40100400)
    else:
        struct.pack_into("<I", h, 4, 0x40080400)
        struct.pack_into("<H", h, 12, chip_id)
    return bytes(h) + b"\x00" * (size - 24)


def test_a_binary_says_its_chip():
    d = tempfile.mkdtemp()
    try:
        files = {"s3.bin": image(9), "esp32.bin": image(0), "c3.bin": image(5), "e8266.bin": image(esp8266=True),
                 "e8266.bin.gz": b"\x1f\x8b\x08rest", "junk.bin": b"not firmware" * 4}
        for n, b in files.items():
            open(os.path.join(d, n), "wb").write(b)
        got = {n: firmware.bin_chip(os.path.join(d, n)) for n in files}
        assert got == {"s3.bin": "esp32-s3", "esp32.bin": "esp32", "c3.bin": "esp32-c3", "e8266.bin": "esp8266",
                       "e8266.bin.gz": "esp8266", "junk.bin": None}, got
        assert firmware.check(os.path.join(d, "s3.bin"), "ESP32-S3")[0]
        ok, words = firmware.check(os.path.join(d, "esp32.bin"), "esp32-s3")
        assert not ok and "would not boot" in words
        assert not firmware.check(os.path.join(d, "junk.bin"), "esp32")[0]
        assert firmware.check(os.path.join(d, "esp32.bin"), None)[0]          # no device: taken as it says
    finally:
        shutil.rmtree(d, ignore_errors=True)


RELEASES = [
    {"tag_name": "nightly", "name": "nightly", "prerelease": True, "draft": False, "published_at": "2026-10-01T00:00:00Z",
     "assets": [{"name": "WLED_nightly_ESP32.bin", "browser_download_url": "", "size": 10}]},
    {"tag_name": "v16.0.1", "name": "Kriek", "prerelease": False, "draft": False, "published_at": "2026-09-20T00:00:00Z",
     "assets": [{"name": n, "browser_download_url": "", "size": 1000} for n in (
         "WLED_16.0.1_ESP32-S3_HD-WF2.bin", "WLED_16.0.1_ESP32-S3_8MB_opi.bin", "WLED_16.0.1_ESP32-S3_4M_qspi.bin",
         "WLED_16.0.1_ESP32_Ethernet.bin", "WLED_16.0.1_ESP32.bin", "WLED_16.0.1_ESP8266.bin", "WLED_16.0.1_ESP02.bin.gz",
         "WLED_16.0.1_ESP32-C3.bin", "release_notes.md")]},
    {"tag_name": "v0.1", "name": "draft", "prerelease": False, "draft": True, "published_at": "", "assets": []},
]


def test_releases_matched_to_a_chip():
    d = tempfile.mkdtemp()
    was_cache, was_url = firmware.CACHE, os.environ.get("STUDIO_WLED_RELEASES_URL")
    try:
        firmware.CACHE = os.path.join(d, "firmware")
        src = os.path.join(d, "releases.json")
        json.dump(RELEASES, open(src, "w"))
        os.environ["STUDIO_WLED_RELEASES_URL"] = pathlib.Path(src).as_uri()
        rels = firmware.releases(force=True)
        assert [r["tag"] for r in rels] == ["nightly", "v16.0.1"] and rels[0]["pre"] and not rels[1]["pre"]
        assert all(a["name"].endswith((".bin", ".bin.gz")) for r in rels for a in r["assets"])     # the notes left out
        rel = rels[1]
        names = lambda arch: [a["name"][12:] for a in firmware.assets_for(rel, arch)]
        assert names("esp32") == ["ESP32.bin", "ESP32_Ethernet.bin"]
        assert names("ESP32-S3")[:2] == ["ESP32-S3_4M_qspi.bin", "ESP32-S3_8MB_opi.bin"] and names("esp32-s3")[-1] == "ESP32-S3_HD-WF2.bin"
        assert names("esp8266") == ["ESP8266.bin", "ESP02.bin.gz"] and names("esp32-c3") == ["ESP32-C3.bin"]
        assert len(firmware.assets_for(rel, None)) == 8                       # no device: every file
        os.environ["STUDIO_WLED_RELEASES_URL"] = pathlib.Path(os.path.join(d, "gone.json")).as_uri()
        assert [r["tag"] for r in firmware.releases(force=True)] == ["nightly", "v16.0.1"]   # offline: the copy kept
        # a download through a file URL, kept, and not fetched twice
        bin_ = os.path.join(d, "WLED_16.0.1_ESP32.bin")
        open(bin_, "wb").write(image(0))
        asset = {"name": "WLED_16.0.1_ESP32.bin", "url": pathlib.Path(bin_).as_uri(), "size": 4096}
        seen = []
        p = firmware.download("v16.0.1", asset, lambda done, total: seen.append(done))
        assert os.path.exists(p) and firmware.bin_chip(p) == "esp32" and seen and seen[-1] == 4096
        os.remove(bin_)
        assert firmware.download("v16.0.1", asset) == p                        # from the cache
    finally:
        firmware.CACHE = was_cache
        if was_url is None:
            os.environ.pop("STUDIO_WLED_RELEASES_URL", None)
        else:
            os.environ["STUDIO_WLED_RELEASES_URL"] = was_url
        shutil.rmtree(d, ignore_errors=True)


class _Project:
    """What stage_builtins and builtin_missing read of a project."""
    def __init__(self, options):
        self.options = options


def test_the_built_in_effects_one_by_one():
    d = tempfile.mkdtemp()
    was = flash.ROOT
    try:
        flash.ROOT = d
        um = os.path.join(d, "usermods", "cube_fx")
        os.makedirs(um)
        src = {"cube_fx.cpp": "// the usermod", "cube_fx_common.h": "", "cube_fx_bank.cpp": "",
               "cube_fx_00_geometry.cpp": "void cfx_geomPoll() {}",
               "cube_fx_01_rings.cpp": 'static const char _data_FX_MODE_RINGS[] PROGMEM = "Ace 3-D Rings@Speed;;!;3";\nx = cfx_getAudioData();',
               "cube_fx_02_sand.cpp": 'static const char _data_FX_MODE_SAND[] PROGMEM =\n  "Gyro Sand@!";\ncfx_imu(); cfx_pos(a);',
               "cube_fx_98_script.cpp": 'static const char _data_FX_MODE_STUDIO_SCRIPT[] PROGMEM = "Studio Script@x";',
               "library.json": json.dumps({"name": "cube_fx", "version": "1.0.0"})}
        for n, t in src.items():
            open(os.path.join(um, n), "w").write(t)
        cat = flash.builtin_catalog()
        assert [(e["file"], e["name"]) for e in cat] == [("cube_fx_01_rings.cpp", "Ace 3-D Rings"),
                                                       ("cube_fx_02_sand.cpp", "Gyro Sand"),
                                                       ("cube_fx_98_script.cpp", "Studio Script")]
        assert cat[0]["needs"] == {"audio"} and cat[1]["needs"] == {"imu", "geometry"} and not cat[2]["needs"]
        p = _Project({})
        assert flash.builtin_chosen(p) == [e["file"] for e in cat] and flash.stage_builtins(p, print) is None   # all: the tree's own
        p = _Project({"builtin_ship": ["cube_fx_02_sand.cpp"], "features": {"imu": False}})
        assert flash.builtin_missing(p) == [("Gyro Sand", ["the IMU"])]
        lines = []
        assert flash.stage_builtins(p, lines.append) == flash.BUILTIN_STAGED
        got = sorted(os.listdir(os.path.join(d, "usermods", flash.BUILTIN_STAGED)))
        assert got == ["cube_fx.cpp", "cube_fx_00_geometry.cpp", "cube_fx_02_sand.cpp", "cube_fx_bank.cpp", "cube_fx_common.h",
                       "library.json"], got                           # the unchosen effects out, every helper in
        meta = json.load(open(os.path.join(d, "usermods", flash.BUILTIN_STAGED, "library.json")))
        assert meta["name"] == flash.BUILTIN_STAGED and "1 of 3" in lines[0]
        p.options["builtin_ship"] = []
        flash.stage_builtins(p, print)
        assert not any(f.startswith("cube_fx_0") and f != "cube_fx_00_geometry.cpp"
                       for f in os.listdir(os.path.join(d, "usermods", flash.BUILTIN_STAGED)))
    finally:
        flash.ROOT = was
        shutil.rmtree(d, ignore_errors=True)


def test_a_bin_flashed_to_the_fake_device():
    from fake_wled import FakeWled
    dev = FakeWled(port=8772, ddp_port=4052).start()            # its arch: ESP32-S3
    d = tempfile.mkdtemp()
    try:
        import time
        dev.t0 = time.time() - 100                              # up a while: its uptime starting over is the reboot
        good, bad = os.path.join(d, "s3.bin"), os.path.join(d, "esp32.bin")
        open(good, "wb").write(image(9))
        open(bad, "wb").write(image(0))
        p = _Project({})
        p.save = lambda: None
        job = flash.Job(p, "", dev.host, build=False, upload=True, source="file", bin_path=bad)
        job._run()
        assert not job.ok and "not sent" in job.result and getattr(dev, "firmware", None) is None, job.result
        job = flash.Job(p, "", dev.host, build=False, upload=True, source="file", bin_path=good)
        job._run()
        assert job.ok, job.result
        assert dev.firmware == image(9)
        rec = p.options["flash_history"][-1]
        assert rec["source"] == "file" and rec["firmware"] == "s3.bin" and rec["size"] == 4096
    finally:
        dev.stop()
        shutil.rmtree(d, ignore_errors=True)


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
