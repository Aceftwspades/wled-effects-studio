"""The flash's companions (flash_tools.py) and the flash job's new halves: USB
ports recognised, esptool's progress and failures read, the device's settings
kept and restored (never its Wi-Fi secrets), the image kept for undoing, a
build's progress, PlatformIO's installer, and a USB flash and an OTA flash end
to end - against the fake device, and a stand-in for PlatformIO. Run with
python tests/test_flash_tools.py  (or pytest).
"""
import json
import os
import shutil
import struct
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

from fake_wled import FakeWled                    # noqa: E402
from native import flash, flash_tools as FT        # noqa: E402


class _Project:
    def __init__(self, path):
        self.path, self.options = path, {}

    def save(self):
        pass


def _image(chip_id=9, size=4096):
    h = bytearray(24)
    h[0], h[1] = 0xE9, 3
    struct.pack_into("<I", h, 4, 0x40080400)
    struct.pack_into("<H", h, 12, chip_id)
    return bytes(h) + b"\x00" * (size - 24)


def test_ports_progress_and_advice():
    rows = [{"port": "COM9", "description": "Bluetooth link", "hwid": "BTHENUM\\..."},
            {"port": "COM4", "description": "Silicon Labs CP210x USB to UART Bridge", "hwid": "USB VID:PID=10C4:EA60 SER=0001"},
            {"port": "COM6", "description": "USB JTAG/serial debug unit", "hwid": "USB VID:PID=303A:1001"}]
    ports = FT.sort_ports(rows)
    assert [p["port"] for p in ports] == ["COM4", "COM6", "COM9"]           # the ESP boards first
    assert ports[0]["esp"].startswith("Silicon Labs") and ports[1]["esp"] == "Espressif USB" and ports[2]["esp"] is None
    assert FT.writing_progress("Writing at 0x0004c000... (37 %)") == 0.37
    assert FT.writing_progress("Wrote 1595776 bytes") is None
    assert "BOOT" in FT.usb_advice("A fatal error occurred: Failed to connect to ESP32-S3: No serial data received.")
    assert "environment" in FT.usb_advice("A fatal error occurred: This chip is ESP32 not ESP32-S3. Wrong --chip argument?")
    assert FT.usb_advice("Hash of data verified.") is None


def test_settings_kept_and_restored():
    dev = FakeWled(port=8776, ddp_port=4056).start()
    d = tempfile.mkdtemp()
    try:
        dev.files["/ledmap.json"] = b'{"map":[0,1,2]}'
        p = _Project(d)
        folder, files = FT.backup(dev.host, p, {"mac": "aabbccddeeff"})
        assert os.path.basename(os.path.dirname(folder)) == "aabbccddeeff"
        assert {"/cfg.json", "/presets.json", "/ledmap.json"} <= set(files)
        assert not any("wsec" in f for f in files) and not os.path.exists(os.path.join(folder, "wsec.json"))   # no secrets
        meta = json.load(open(os.path.join(folder, "device.json")))
        assert meta["host"] == dev.host and meta["files"] == files
        assert FT.backups(p, "aabbccddeeff")[0][0] == folder
        # the settings changed on the device, then put back
        was = json.loads(json.dumps(dev.cfg))
        dev.cfg["hw"]["led"]["total"] = 7
        reboots = dev.reboots
        ok, msg = FT.restore(dev.host, folder)
        assert ok and dev.cfg == was and dev.reboots == reboots + 1, msg
        # the newest ten kept
        root = os.path.dirname(folder)
        for k in range(12):
            os.makedirs(os.path.join(root, f"2000010{k:02d}-000000"))
        FT._prune(root, FT.KEEP_BACKUPS)
        assert len(os.listdir(root)) == FT.KEEP_BACKUPS and os.path.isdir(folder)
    finally:
        dev.stop()
        shutil.rmtree(d, ignore_errors=True)


def test_previous_images_kept():
    d = tempfile.mkdtemp()
    try:
        p = _Project(d)
        src = os.path.join(d, "fw.bin")
        for k in range(5):
            open(src, "wb").write(_image(size=2048 + k))
            FT.keep_firmware(p, "dev1", src, f"build {k}")
            time.sleep(1.05)                                              # one a second: the names are stamps
        k = FT.kept(p, "dev1")
        assert len(k) == FT.KEEP_FIRMWARE and k[0][1]["what"] == "build 4" and k[-1][1]["what"] == "build 2"
        assert os.path.getsize(k[0][0]) == 2052
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_build_progress():
    p = _Project(tempfile.mkdtemp())
    e = FT.BuildEstimate(p, "envA")
    assert e.expected is None and e.share() is None                       # a first build: no share to tell
    for _ in range(40):
        e.line("Compiling .pio/build/x/a.cpp.o")
    e.line("Linking .pio/build/x/firmware.elf")
    e.finish(True)
    assert p.options["build_units"]["envA"]["units"] == 40
    e2 = FT.BuildEstimate(p, "envA")
    e2.first = time.time() - 10
    for _ in range(10):
        e2.line("Compiling y")
    assert abs(e2.share() - 0.25) < 1e-9 and 25 < e2.remaining() < 35       # a quarter in 10 s: about 30 s left
    e2.finish(True)                                                        # an incremental build teaches nothing
    assert p.options["build_units"]["envA"]["units"] == 40


def test_platformio_installer():
    lines = []
    ok, msg = FT.install_platformio(lines.append, download=lambda u: b"print('installing')", run=lambda cmd, log: 3)
    assert not ok and "stopped (3)" in msg
    was = flash.pio_exe
    try:
        flash.pio_exe = lambda: "C:/pio/pio.exe"
        ok, msg = FT.install_platformio(lines.append, download=lambda u: b"#", run=lambda cmd, log: 0)
        assert ok and "PlatformIO installed" in msg
        ok, msg = FT.install_platformio(lines.append, download=lambda u: (_ for _ in ()).throw(OSError("offline")))
        assert not ok and "offline" in msg
    finally:
        flash.pio_exe = was


def _fake_pio(d, script):
    """A stand-in for pio: a script printing what PlatformIO and esptool print."""
    py = os.path.join(d, "fakepio.py")
    open(py, "w").write(script)
    if os.name == "nt":
        exe = os.path.join(d, "pio.cmd")
        open(exe, "w").write(f'@"{sys.executable}" "{py}" %*\n')
    else:
        exe = os.path.join(d, "pio")
        open(exe, "w").write(f'#!/bin/sh\n"{sys.executable}" "{py}" "$@"\n')
        os.chmod(exe, 0o755)
    return exe


def test_a_usb_flash_through_platformio():
    d = tempfile.mkdtemp()
    saved = (flash.pio_exe, flash.stage, flash.manifest, flash.record_flash, flash.firmware_bin)
    try:
        calls = os.path.join(d, "calls.txt")
        ok_pio = _fake_pio(d, f"""import sys
open(r"{calls}", "a").write(" ".join(sys.argv[1:]) + "\\n")
if "erase" in sys.argv:
    print("Erasing flash (this may take a while)..."); print("Chip erase completed successfully")
else:
    for k in (0, 37, 100):
        print(f"Writing at 0x000{{k}}0000... ({{k}} %)")
    print("Hash of data verified.")
""")
        flash.pio_exe = lambda: ok_pio
        flash.stage = lambda project, env, log, only=None: "studio_" + env
        flash.manifest = lambda *a, **k: {}
        flash.record_flash = lambda project, m, b, host, dev=None: {"when": "now", "effects": []}
        flash.firmware_bin = lambda env: os.path.join(d, "firmware.bin")
        p = _Project(d)
        job = flash.Job(p, "esp32s3_customfx", "", build=False, upload=True, transport="usb", port="COM4", erase=True)
        job._run()
        assert job.ok and "COM4" in job.result and "WLED-AP" in job.result and "4.3.2.1" in job.result, job.result
        ran = open(calls).read().splitlines()
        assert ran == ["run -e studio_esp32s3_customfx -t erase --upload-port COM4",
                       "run -e studio_esp32s3_customfx -t upload --upload-port COM4"], ran
        assert abs(job.progress - 0.99) < 1e-9
        # a board that does not answer: said in plain words
        bad_pio = _fake_pio(d, "import sys\nprint('A fatal error occurred: Failed to connect to ESP32-S3: No serial data received.')\nsys.exit(2)\n")
        flash.pio_exe = lambda: bad_pio
        job = flash.Job(p, "esp32s3_customfx", "", build=False, upload=True, transport="usb", port="COM4")
        job._run()
        assert not job.ok and "BOOT" in job.result, job.result
        # a release over USB: refused, it cannot start a blank board
        job = flash.Job(p, "", "", upload=True, source="release", release=("v1", {}), transport="usb", port="COM4")
        job._run()
        assert not job.ok and "bootloader" in job.result
    finally:
        flash.pio_exe, flash.stage, flash.manifest, flash.record_flash, flash.firmware_bin = saved
        shutil.rmtree(d, ignore_errors=True)


def test_an_ota_flash_keeps_the_settings_and_the_image():
    dev = FakeWled(port=8777, ddp_port=4057).start()
    d = tempfile.mkdtemp()
    try:
        dev.t0 = time.time() - 100
        good = os.path.join(d, "s3.bin")
        open(good, "wb").write(_image(9, size=200000))
        p = _Project(d)
        seen = []
        job = flash.Job(p, "", dev.host, build=False, upload=True, source="file", bin_path=good)
        orig = job._sending
        job._sending = lambda sent, total: (seen.append(sent), orig(sent, total))
        job._run()
        assert job.ok, job.result
        assert job.backup and os.path.exists(os.path.join(job.backup[0], "cfg.json"))          # kept before sending
        assert len(seen) > 3 and seen[-1] == max(seen) and job.progress > 0.97                  # sent in pieces, told
        assert job.kept and open(job.kept, "rb").read() == _image(9, size=200000)               # kept for undoing
        key = FT.device_key(dev.host, flash.device_info(dev.host))
        assert FT.kept(p, key)[0][0] == job.kept
        # the kept image sent again is not kept a second time
        job2 = flash.Job(p, "", dev.host, build=False, upload=True, source="file", bin_path=job.kept)
        job2._run()
        assert job2.ok and job2.kept is None and len(FT.kept(p, key)) == 1, job2.result
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
