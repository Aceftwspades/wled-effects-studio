"""A fake WLED device for the tests: an HTTP server that answers what the
studio asks a device, and a DDP listener that counts frames.

    python tests/fake_wled.py [port]          # standalone, for a hand test
    from fake_wled import FakeWled; d = FakeWled(); d.start(); ... d.stop()

What it models of WLED 16, faithfully where the studio was bitten:
  /json/info, /json/effects, /json/palettes, /json/nodes
  /json/state   GET the state; POST applies on / bri / seg fields, "ps"
                (a preset applied), "pl" -1, "pdel", "rmcpal", and "psave":
                the preset is written from a "loop" a beat LATER - a second
                psave arriving before that replaces the one pending, and the
                write is the CURRENT STATE unless "o" is set, when it is the
                object itself (a playlist only lands that way) - as the real
                firmware does (presets.cpp)
  /presets.json the presets written so far (and fs.pmt in /json/info moves)
  /upload       any file into the fake's filesystem (studio.bin, ledmap.json,
                geometry.bin, paletteN.json); GET /<name> serves it back
  /json/cfg     GET the config (hw.led.ins, timers.ins, um.AudioReactive, hw.if.i2c-pin); POST merges timers,
                the LED block, the audio usermod's block (a type or pin change counts a reboot as needed)
                (cleared, then the list) and the LED outputs
  DDP           a UDP socket on 4048 counting packets and frames

Everything is in memory; .state, .presets, .files, .cfg, .ddp_frames are
there for a test to look at.
"""
import json
import socket
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

EFFECTS = ["Solid", "Blink", "Breathe", "Wipe", "Wipe Random", "Random Colors", "Sweep", "Dynamic", "Colorloop", "Rainbow",
           "Scan", "Scan Dual", "Fade", "Theater", "Theater Rainbow", "Running", "Saw", "Twinkle", "Dissolve", "Dissolve Rnd",
           "Sparkle", "Sparkle Dark", "Sparkle+", "Strobe", "Strobe Rainbow", "Strobe Mega", "Blink Rainbow", "Android", "Chase",
           "Chase Random", "Chase Rainbow", "Chase Flash", "Chase Flash Rnd", "Rainbow Runner", "Colorful", "Traffic Light",
           "Sweep Random", "Chase 2", "Aurora", "Stream", "Scanner", "Lighthouse", "Fireworks", "Rain", "Tetrix", "Fire Flicker",
           "Gradient", "Loading", "Rolling Balls", "Fairy", "Two Dots", "Fairytwinkle", "Running Dual", "RSVD", "Chase 3",
           "Tri Wipe", "Tri Fade", "Lightning", "ICU", "Multi Comet", "Scanner Dual", "Stream 2", "Oscillate", "Pride 2015",
           "Juggle", "Palette", "Fire 2012", "Colorwaves", "Bpm", "Fill Noise", "Noise 1", "Noise 2", "Noise 3", "Noise 4",
           "Colortwinkles", "Lake", "Meteor", "Meteor Smooth", "Railway", "Ripple", "Twinklefox", "Twinklecat", "Halloween Eyes",
           "Solid Pattern", "Solid Pattern Tri", "Spots", "Spots Fade", "Glitter", "Candle", "Fireworks Starburst",
           "Fireworks 1D", "Bouncing Balls", "Sinelon", "Sinelon Dual", "Sinelon Rainbow", "Popcorn", "Drip", "Plasma",
           "Percent", "Ripple Rainbow", "Heartbeat", "Pacifica", "Candle Multi", "Solid Glitter", "Sunrise", "Phased",
           "Twinkleup", "Noise Pal", "Sine", "Phased Noise", "Flow", "Chunchun", "Dancing Shadows", "Washing Machine",
           "Blends", "TV Simulator", "Dynamic Smooth", "Ace 3-D Lichtenberg", "Ace 3-D Cube Axes", "Studio Script"]
PALETTES = ["Default", "* Random Cycle", "* Color 1", "* Colors 1&2", "* Color Gradient", "* Colors Only", "Party", "Cloud",
            "Lava", "Ocean", "Forest", "Rainbow", "Rainbow Bands", "Sunset", "Rivendell", "Breeze", "Red & Blue", "Yellowout",
            "Analogous", "Splash", "Pastel", "Sunset 2", "Beach", "Vintage", "Departure", "Landscape", "Beech", "Sherbet", "Hult",
            "Hult 64", "Drywet", "Jul", "Grintage", "Rewhi", "Tertiary", "Fire", "Icefire", "Cyane", "Light Pink", "Autumn",
            "Magenta", "Magred", "Yelmag", "Yelblu", "Orange & Teal", "Tiamat", "April Night", "Orangery", "C9", "Sakura",
            "Aurora", "Atlantica", "C9 2", "C9 New", "Temperature", "Aurora 2", "Retro Clown", "Candy", "Toxy Reaf", "Fairy Reaf",
            "Semi Blue", "Pink Candy", "Red Reaf", "Aqua Flash", "Yelblu Hot", "Lite Light", "Red Flash", "Blink Red", "Red Shift",
            "Red Tide", "Candy2"]


def _seg(i=0, start=0, stop=48, sy=0, sty=48):
    return {"id": i, "start": start, "stop": stop, "startY": sy, "stopY": sty, "grp": 1, "spc": 0, "of": 0, "on": True, "frz": False,
            "bri": 255, "cct": 127, "set": 0, "n": "", "col": [[255, 160, 0], [0, 0, 0], [0, 0, 0]], "fx": 0, "sx": 128, "ix": 128,
            "pal": 0, "c1": 128, "c2": 128, "c3": 16, "sel": True, "rev": False, "mi": False, "rY": False, "mY": False, "tp": False,
            "o1": False, "o2": False, "o3": False, "si": 0, "m12": 0, "bm": 0}


class FakeWled:
    LOOP_DELAY = 0.3                 # a psave is written this much later, from the "loop"

    def __init__(self, port=8770, w=48, h=48, ddp_port=4048):
        self.port, self.w, self.h, self.ddp_port = port, w, h, ddp_port
        self.state = {"on": False, "bri": 128, "transition": 7, "ps": -1, "pl": -1, "mainseg": 0, "seg": [_seg(0, 0, w, 0, h)]}
        self.presets = {"0": {}}
        self.files = {}                                  # name -> bytes
        self.cfg = {"hw": {"led": {"total": w * h, "maxpwr": 0, "ledma": 55, "ins": [{"start": 0, "len": w * h, "pin": [16], "order": 0, "rev": False, "type": 22}],
                                   "matrix": {"mpc": 1, "panels": [{"b": False, "r": False, "v": False, "s": True, "x": 0, "y": 0, "h": h, "w": w}]}}},
                    "timers": {"ins": []},
                    "um": {"AudioReactive": {"enabled": True, "addPalettes": False, "digitalmic": {"type": 1, "pin": [13, 15, 14, -1]},
                                             "config": {"squelch": 10, "gain": 60, "AGC": 0}, "sync": {"port": 11988, "mode": 0}}}}
        self.cfg["hw"]["if"] = {"i2c-pin": [-1, -1]}
        self.audio_level = 0.0                           # what /json/info reports as the input level (a test sets it)
        self.reboots = 0                                 # /json/state {"rb": true} counted
        self.reboot_needed = False                       # a new audio type or new pins were written
        self.pmt = int(time.time()) - 100                # presets file modified time: whole seconds by the device's clock
        self.t0 = time.time()
        self.pending = None                              # (id, object, is_api_call)
        self.ddp_packets = self.ddp_frames = 0
        self.ddp_last = b""                              # the last whole frame streamed (its packets put together at their offsets)
        self.live_until = 0.0
        self.log = []
        self._lock = threading.Lock()
        self._srv = None

    # --- the "loop": a pending preset written a beat later ---------------------------
    def _loop(self):
        while self._srv is not None:
            time.sleep(0.05)
            with self._lock:
                p = self.pending
                if p and time.time() >= p[3]:
                    self.pending = None
                    pid, obj, api, _ = p
                    if api and "playlist" in obj:
                        body = {"playlist": obj["playlist"], "on": True, "n": obj.get("n", f"Preset {pid}")}
                    elif api:
                        body = {k: v for k, v in obj.items() if k not in ("psave", "o", "v", "time", "error")}
                        body.setdefault("n", f"Preset {pid}")
                    else:
                        body = {k: json.loads(json.dumps(v)) for k, v in self.state.items() if k in ("mainseg", "seg")}
                        if obj.get("ib"):
                            body["on"] = self.state["on"]; body["bri"] = self.state["bri"]
                        body["n"] = obj.get("n", f"Preset {pid}")
                    self.presets[str(pid)] = body
                    self.pmt = int(time.time())
                    self.log.append(f"wrote preset {pid}")

    # --- the state, as /json/state changes it --------------------------------------------
    def apply(self, d):
        st = self.state
        for k in ("on", "bri", "transition", "mainseg"):
            if k in d:
                st[k] = d[k]
        if "pl" in d:
            st["pl"] = int(d["pl"])
        if "ps" in d and str(d["ps"]).lstrip("-").isdigit():
            n = int(d["ps"])
            if str(n) in self.presets and n > 0:
                pre = self.presets[str(n)]
                if "playlist" in pre:
                    st["pl"] = n; st["ps"] = int(pre["playlist"]["ps"][0]) if pre["playlist"].get("ps") else n
                else:
                    st["ps"] = n
                    for k in ("on", "bri", "seg", "mainseg"):
                        if k in pre:
                            st[k] = json.loads(json.dumps(pre[k]))
        for sg in d.get("seg") or []:
            i = int(sg.get("id", 0))
            while len(st["seg"]) <= i:
                st["seg"].append(_seg(len(st["seg"])))
            st["seg"][i].update({k: v for k, v in sg.items() if k != "id"})
        if "pdel" in d:
            self.presets.pop(str(int(d["pdel"])), None); self.pmt = int(time.time())
        if "rmcpal" in d:
            self.files.pop(f"/palette{int(d['rmcpal'])}.json", None)
        if d.get("rb"):
            self.reboots += 1; self.reboot_needed = False
        if "psave" in d:
            pid = int(d["psave"])
            if 0 < pid < 251:
                api = "o" in d and d["o"]
                self.pending = (pid, d, api, time.time() + self.LOOP_DELAY)     # replaces one still pending, as WLED's does

    def info(self):
        fx = self.state["seg"][self.state["mainseg"]]["fx"]
        ar = self.cfg["um"]["AudioReactive"]
        t = ar["digitalmic"]["type"]
        u = {"Studio Script": ["running" if EFFECTS[fx] == "Studio Script" else "idle"],
             "AudioReactive": {"Audio Source": ["I2S digital" if t < 254 else "network only",
                                                f" - peak {int(self.audio_level / 2.55):3d}%" if self.audio_level > 1 else " - quiet"],
                               "Input level": [round(self.audio_level), "/255"],
                               "Sound Processing": ["running" if ar["enabled"] else "suspended"]}}
        return {"ver": "16.0.1", "vid": 2605010, "name": "Fake WLED", "arch": "ESP32-S3", "fxcount": len(EFFECTS),
                "palcount": len(PALETTES), "cpalcount": sum(1 for f in self.files if f.startswith("/palette")),
                "mac": "aabbccddeeff", "uptime": int(time.time() - self.t0), "freeheap": 150000,
                "leds": {"count": self.w * self.h, "pwr": 0, "fps": 40, "maxpwr": 0, "matrix": {"w": self.w, "h": self.h}, "lc": 1},
                "live": time.time() < self.live_until, "lm": "DDP" if time.time() < self.live_until else "",
                "fs": {"u": 100, "t": 1000, "pmt": self.pmt}, "u": u}

    # --- the servers ---------------------------------------------------------------------
    def start(self):
        fake = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, code, body, ctype="application/json"):
                data = body if isinstance(body, bytes) else json.dumps(body).encode()
                self.send_response(code); self.send_header("Content-Type", ctype); self.send_header("Content-Length", str(len(data)))
                self.end_headers(); self.wfile.write(data)

            def do_GET(self):
                p = self.path.split("?")[0]
                with fake._lock:
                    if p == "/json/info": return self._send(200, fake.info())
                    if p == "/json/effects": return self._send(200, EFFECTS)
                    if p == "/json/palettes": return self._send(200, PALETTES)
                    if p == "/json/nodes": return self._send(200, {"nodes": []})
                    if p == "/json/state": return self._send(200, fake.state)
                    if p == "/json/si": return self._send(200, {"state": fake.state, "info": fake.info()})
                    if p == "/json/cfg": return self._send(200, fake.cfg)
                    if p == "/presets.json": return self._send(200, fake.presets)
                    if p in fake.files: return self._send(200, fake.files[p], "application/octet-stream")
                self._send(404, {"error": 404})

            def do_POST(self):
                p = self.path.split("?")[0]
                n = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(n) if n else b""
                if p == "/upload":
                    # multipart: the one file, by its filename
                    name = "/unknown"
                    head, sep, rest = raw.partition(b"\r\n\r\n")
                    if b'filename="' in head:
                        name = head.split(b'filename="')[1].split(b'"')[0].decode()
                    body = rest.rsplit(b"\r\n--", 1)[0]
                    with fake._lock:
                        fake.files[name] = body; fake.log.append(f"upload {name} {len(body)} bytes")
                    return self._send(200, b"OK", "text/plain")
                try:
                    d = json.loads(raw.decode("utf-8") or "{}")
                except Exception:
                    return self._send(400, {"error": 9})
                with fake._lock:
                    if p == "/json/state":
                        fake.apply(d); return self._send(200, {"success": True})
                    if p == "/json/cfg":
                        if "timers" in d and "ins" in d["timers"]:
                            fake.cfg["timers"]["ins"] = list(d["timers"]["ins"])
                        if "hw" in d and "led" in d["hw"]:
                            fake.cfg["hw"]["led"].update(d["hw"]["led"])
                        if "hw" in d and "if" in d["hw"] and "i2c-pin" in d["hw"]["if"]:
                            fake.cfg["hw"]["if"]["i2c-pin"] = list(d["hw"]["if"]["i2c-pin"])
                        ar = (d.get("um") or {}).get("AudioReactive")
                        if ar:
                            cur = fake.cfg["um"]["AudioReactive"]
                            dm = ar.get("digitalmic") or {}
                            if ("type" in dm and dm["type"] != cur["digitalmic"]["type"]) or ("pin" in dm and list(dm["pin"]) != cur["digitalmic"]["pin"]):
                                fake.reboot_needed = True
                            for k, v in ar.items():
                                if isinstance(v, dict) and isinstance(cur.get(k), dict):
                                    cur[k].update(v)
                                else:
                                    cur[k] = v
                        fake.log.append("cfg written")
                        return self._send(200, {"success": True})
                    if p == "/json":
                        fake.apply(d); return self._send(200, {"success": True})
                self._send(404, {"error": 404})

        self._srv = ThreadingHTTPServer(("127.0.0.1", self.port), H)
        threading.Thread(target=self._srv.serve_forever, daemon=True).start()
        threading.Thread(target=self._loop, daemon=True).start()
        threading.Thread(target=self._ddp, daemon=True).start()
        return self

    def _ddp(self):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.bind(("127.0.0.1", self.ddp_port)); s.settimeout(0.5)
        except OSError:
            return
        frame = bytearray()
        while self._srv is not None:
            try:
                d, _ = s.recvfrom(4096)
            except socket.timeout:
                continue
            with self._lock:
                self.ddp_packets += 1
                if len(d) >= 10:
                    off, n = int.from_bytes(d[4:8], "big"), int.from_bytes(d[8:10], "big")
                    if len(frame) < off + n:
                        frame.extend(bytes(off + n - len(frame)))
                    frame[off:off + n] = d[10:10 + n]
                if len(d) >= 10 and d[0] & 0x01:
                    self.ddp_frames += 1
                    self.ddp_last = bytes(frame)
                    frame = bytearray()
                self.live_until = time.time() + 2.5
        s.close()

    def stop(self):
        srv, self._srv = self._srv, None
        if srv:
            srv.shutdown(); srv.server_close()

    @property
    def host(self):
        return f"127.0.0.1:{self.port}"


if __name__ == "__main__":
    d = FakeWled(int(sys.argv[1]) if len(sys.argv) > 1 else 8770).start()
    print(f"fake WLED on http://{d.host}  (DDP on {d.ddp_port}); Ctrl-C to stop")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        d.stop()
