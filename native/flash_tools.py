"""The flash's companions: a board on USB, the device's settings kept before
a flash, the firmware it ran before, how far a build has got, and
PlatformIO itself when it is missing.

    ports = serial_ports()                       # [{port, description, hwid, esp}] - esp: a likely ESP32 board
    path = backup(host, project)                 # the device's settings files into the project, before a flash
    restore(host, path, log)                     # put them back, and reboot
    keep_firmware(project, key, bin, what)       # a copy of what was flashed, the last few per device
    kept(project, key)                           # [(path, info)] newest first: "flash the previous one again"
    est = BuildEstimate(project, env)            # a build's progress from the last one's count of units
    install_platformio(log)                      # PlatformIO's own installer, run with this computer's Python

**USB** is what a board with no WLED on it needs: OTA asks a running WLED
to take the image, and a new, wiped or broken board has none. PlatformIO's
`run -t upload` writes the whole flash over the serial port - the
bootloader, the partition table and the application - so a blank chip
boots; `-t erase` first clears everything, settings included. The serial
chips on ESP32 boards are recognised by their USB ids (Silicon Labs
CP210x, WCH CH340/CH9102, FTDI, and Espressif's own USB on the S2, S3, C3
and later), so the right port is offered first.

**Settings**: WLED keeps its configuration (cfg.json), presets, the
ledmap and the studio's shape table (geometry.bin) on its file system,
which an OTA leaves alone - but a partition table that changes, or a
board that does not come back, loses them. A copy goes into the project's
`backups/<device>/<time>/` before each flash (the newest ten kept), and
Restore uploads them and reboots the device.

**Previous firmware**: each image flashed successfully is kept in the
project's `firmware/<device>/` (the newest three), so a flash that turns
out badly is one click from undone.
"""
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request

from native import procs

# USB vendor ids of the serial chips on ESP32 boards (and Espressif's own USB)
ESP_VIDS = {"10C4": "Silicon Labs CP210x", "1A86": "WCH CH340 / CH9102", "0403": "FTDI", "303A": "Espressif USB"}
# wsec.json is never copied: it holds the Wi-Fi passwords and the OTA PIN, and a project folder gets zipped and handed on
SETTINGS_FILES = ("/cfg.json", "/presets.json", "/ledmap.json", "/geometry.bin")
KEEP_BACKUPS = 10
KEEP_FIRMWARE = 3
WLED_AP = ("WLED-AP", "wled1234")        # what a fresh WLED starts when it knows no Wi-Fi (its defaults)


# --- USB -------------------------------------------------------------------------------------
def serial_ports(pio=None):
    """The serial ports PlatformIO sees: [{port, description, hwid, esp}], likely ESP32 boards first."""
    from native import flash
    pio = pio or flash.pio_exe()
    if not pio:
        return []
    try:
        out = procs.run([pio, "device", "list", "--serial", "--json-output"], capture_output=True, text=True,
                        timeout=30, env=dict(os.environ, **flash.PIO_ENV)).stdout
        rows = json.loads(out or "[]")
    except Exception:
        return []
    return sort_ports(rows)


def sort_ports(rows):
    out = []
    for r in rows or []:
        hw = str(r.get("hwid", "")).upper()
        vid = next((v for v in ESP_VIDS if f"VID:PID={v}" in hw or f"VID_{v}" in hw), None)
        out.append({"port": r.get("port", ""), "description": r.get("description", "") or "", "hwid": r.get("hwid", ""),
                    "esp": ESP_VIDS.get(vid) if vid else None})
    out.sort(key=lambda p: (p["esp"] is None, p["port"]))
    return out


USB_ADVICE = (("Failed to connect", "the board did not answer: hold its BOOT button while the upload starts (some boards "
               "need it), use a data cable rather than a charging one, and close anything else using the port (a serial "
               "monitor, the Arduino IDE)"),
              ("could not open port", "the port is busy or gone: close a serial monitor or another program holding it, "
               "replug the board, Refresh the ports"),
              ("Access is denied", "the port is held by another program: close it (a serial monitor), or replug the board"),
              ("Permission denied", "no permission for the port: on Linux add yourself to the dialout group "
               "(sudo usermod -aG dialout $USER) and log in again"),
              ("This chip is", "the board is another chip than the environment builds for: choose the environment for "
               "the board's chip"),
              ("Wrong boot mode", "the board is not in download mode: hold BOOT, press RESET, let go of BOOT, and start again"),
              ("No serial data received", "the board sent nothing: hold its BOOT button while the upload starts, or try "
               "another cable or port"))


def usb_advice(line):
    """Plain words for an esptool failure on a line of its output, or None."""
    for key, words in USB_ADVICE:
        if key.lower() in line.lower():
            return words
    return None


def writing_progress(line):
    """esptool's "Writing at 0x0004c000... (37 %)" as 0.37, else None."""
    import re
    m = re.search(r"Writing at 0x[0-9a-fA-F]+\.*\s*\((\d+)\s*%\)", line)
    return int(m.group(1)) / 100.0 if m else None


# --- device keys -------------------------------------------------------------------------------
def device_key(host, info=None):
    """A folder name for a device: its MAC when it said it, else its address."""
    mac = (info or {}).get("mac") or ""
    key = mac or str(host or "device")
    return "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in key)


# --- settings ----------------------------------------------------------------------------------
def _url(host):
    host = str(host).strip().rstrip("/")
    return host if host.startswith("http") else "http://" + host


def _get(host, path, timeout=6.0):
    with urllib.request.urlopen(_url(host) + path, timeout=timeout) as r:
        return r.read()


def device_files(host):
    """The names on the device's file system (WLED's /edit?list=/), or None when it will not say."""
    try:
        rows = json.loads(_get(host, "/edit?list=/").decode("utf-8", "replace"))
        return ["/" + str(r.get("name", "")).lstrip("/") for r in rows if r.get("type", "file") == "file"]
    except Exception:
        return None


def backup(host, project, info=None):
    """The device's settings files into project/backups/<device>/<time>/: (folder, [names saved]). Raises when the
    device does not answer at all."""
    names = device_files(host)
    want = list(SETTINGS_FILES)
    if names:
        want += [n for n in names if n.endswith(".json") and n not in want and "wsec" not in n]   # palettes, other settings
    key = device_key(host, info)
    folder = os.path.join(project.path, "backups", key, time.strftime("%Y%m%d-%H%M%S"))
    saved = []
    for n in want:
        try:
            data = _get(host, n)
        except urllib.error.HTTPError:
            continue                                                            # not there: nothing to keep
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, n.lstrip("/")), "wb") as f:
            f.write(data)
        saved.append(n)
    if not saved:
        raise OSError("the device gave none of its settings files")
    with open(os.path.join(folder, "device.json"), "w", encoding="utf-8") as f:
        json.dump({"host": host, "info": info or {}, "when": time.strftime("%Y-%m-%d %H:%M"), "files": saved}, f, indent=1)
    _prune(os.path.dirname(folder), KEEP_BACKUPS)
    return folder, saved


def backups(project, key):
    """[(folder, its device.json)] newest first."""
    root = os.path.join(project.path, "backups", key)
    out = []
    for d in sorted(os.listdir(root), reverse=True) if os.path.isdir(root) else []:
        try:
            meta = json.load(open(os.path.join(root, d, "device.json"), encoding="utf-8"))
        except Exception:
            meta = {"when": d, "files": []}
        out.append((os.path.join(root, d), meta))
    return out


def _upload(host, name, data, timeout=15.0):
    boundary = "----studiorestore" + str(int(time.time() * 1000))
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"data\"; filename=\"{name}\"\r\n"
            "Content-Type: application/octet-stream\r\n\r\n").encode() + data + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(_url(host) + "/upload", data=body,
                                 headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        r.read()


def restore(host, folder, log=lambda m: None, reboot=True):
    """A backup's files back onto the device (WLED reads them as it boots), then a reboot. (ok, message)."""
    files = [f for f in sorted(os.listdir(folder)) if f != "device.json"]
    if not files:
        return False, "the backup holds no files"
    done = []
    for f in files:
        try:
            _upload(host, "/" + f, open(os.path.join(folder, f), "rb").read())
            done.append(f)
            log(f"restored {f}")
        except Exception as e:
            return False, f"{f} was not taken ({e}); {len(done)} restored before it"
    if reboot:
        try:
            req = urllib.request.Request(_url(host) + "/json/state", data=b'{"rb": true}',
                                         headers={"Content-Type": "application/json"})
            urllib.request.urlopen(req, timeout=5).read()
        except Exception:
            pass                                                          # it may drop the connection as it goes down
    return True, f"{len(done)} file(s) restored ({', '.join(done)}); the device is rebooting to read them"


def _prune(root, keep):
    try:
        ds = sorted(os.listdir(root), reverse=True)
    except OSError:
        return
    for d in ds[keep:]:
        shutil.rmtree(os.path.join(root, d), ignore_errors=True)


# --- previous firmware ----------------------------------------------------------------------------
def keep_firmware(project, key, bin_path, what):
    """A copy of the image just flashed, in project/firmware/<device>/; the newest few kept. Its path."""
    root = os.path.join(project.path, "firmware", key)
    os.makedirs(root, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    dest = os.path.join(root, f"{stamp}.bin")
    shutil.copyfile(bin_path, dest)
    with open(dest + ".json", "w", encoding="utf-8") as f:
        json.dump({"what": what, "when": time.strftime("%Y-%m-%d %H:%M"), "size": os.path.getsize(dest)}, f)
    bins = sorted((f for f in os.listdir(root) if f.endswith(".bin")), reverse=True)
    for old in bins[KEEP_FIRMWARE:]:
        for p in (os.path.join(root, old), os.path.join(root, old + ".json")):
            try:
                os.remove(p)
            except OSError:
                pass
    return dest


def kept(project, key):
    """[(path, info)] of the images kept for a device, newest first."""
    root = os.path.join(project.path, "firmware", key)
    out = []
    for f in sorted((f for f in os.listdir(root) if f.endswith(".bin")), reverse=True) if os.path.isdir(root) else []:
        try:
            info = json.load(open(os.path.join(root, f + ".json"), encoding="utf-8"))
        except Exception:
            info = {"what": f, "when": f[:15]}
        out.append((os.path.join(root, f), info))
    return out


# --- a build's progress -----------------------------------------------------------------------------
class BuildEstimate:
    """How far a build has got: the units it compiles counted against the last build of the same environment
    (kept in the project), the time left from the pace so far. A first build of an environment has no count
    to go by: its phase is said, without a share."""

    def __init__(self, project, env):
        self.project, self.env = project, env
        st = (project.options.get("build_units") or {}).get(env) or {}
        self.expected = int(st.get("units", 0)) or None
        self.units = 0
        self.t0 = time.time()
        self.first = None                                        # when the first unit compiled

    def line(self, text):
        """A line of the build's output: True when it counted a unit."""
        if text.startswith("Compiling "):
            self.units += 1
            if self.first is None:
                self.first = time.time()
            return True
        return False

    def share(self):
        if not self.expected or not self.units:
            return None
        return min(0.99, self.units / self.expected)

    def remaining(self):
        """Seconds left, from the pace so far, or None."""
        s = self.share()
        if s is None or s < 0.05 or self.first is None:
            return None
        spent = time.time() - self.first
        return spent * (1 - s) / s

    def finish(self, ok):
        """A build that went through records its count for the next one (an incremental build compiles few and
        teaches nothing: only a count at least half the last is kept)."""
        if not ok or self.units == 0:
            return
        if self.expected and self.units < self.expected // 2:
            return
        st = dict(self.project.options.get("build_units") or {})
        st[self.env] = {"units": self.units, "seconds": round(time.time() - self.t0)}
        self.project.options["build_units"] = st
        self.project.save()


# --- PlatformIO itself ----------------------------------------------------------------------------
INSTALLER_URL = "https://raw.githubusercontent.com/platformio/platformio-core-installer/master/get-platformio.py"


def system_python():
    """A Python on this computer to run PlatformIO's installer with - not the studio's own when it is packaged
    (a frozen app runs no scripts)."""
    if not getattr(sys, "frozen", False):
        return sys.executable
    for name in (("py", "-3"), ("python3",), ("python",)):
        p = shutil.which(name[0])
        if not p or "WindowsApps" in p:                          # the Store's stub opens the Store, it runs nothing
            continue
        try:
            r = procs.run([p, *name[1:], "-c", "import sys; print(sys.version_info[:2] >= (3, 7))"], capture_output=True,
                          text=True, timeout=20)
            if r.stdout.strip() == "True":
                return [p, *name[1:]]
        except Exception:
            continue
    return None


def install_platformio(log, download=None, run=None):
    """PlatformIO installed by its own installer (into ~/.platformio, as its docs give it): (ok, message). `download`
    and `run` stand in for the network and the process in the tests."""
    py = system_python()
    if not py:
        return False, ("PlatformIO's installer needs Python 3, and none was found on this computer: install it from "
                       "python.org (tick \"Add python.exe to PATH\"), then Install PlatformIO again")
    py = [py] if isinstance(py, str) else list(py)
    import tempfile
    script = os.path.join(tempfile.gettempdir(), "get-platformio.py")
    try:
        log("downloading PlatformIO's installer ...")
        data = (download or (lambda u: urllib.request.urlopen(u, timeout=60).read()))(INSTALLER_URL)
        with open(script, "wb") as f:
            f.write(data)
    except Exception as e:
        return False, f"the installer could not be downloaded: {e}"
    log("running it (a few minutes: it sets up PlatformIO in its own folder) ...")
    try:
        if run:
            rc = run(py + [script], log)
        else:
            p = procs.popen(py + [script], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                            encoding="utf-8", errors="replace", bufsize=1)
            for line in p.stdout:
                if line.strip():
                    log(line.rstrip())
            rc = p.wait()
    except Exception as e:
        return False, f"the installer did not run: {e}"
    if rc != 0:
        return False, f"the installer stopped ({rc}) - the lines above say why"
    from native import flash
    pio = flash.pio_exe()
    return (True, f"PlatformIO installed: {pio}") if pio else (False, "the installer finished but pio was not found where it puts it")
