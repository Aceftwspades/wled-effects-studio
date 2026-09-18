"""WLED devices on the network: finding them, asking them what they are,
and keeping the list.

Three ways to find one, none needing a package that is not in the
standard library:

- **mDNS**: WLED advertises `_wled._tcp.local`. One multicast query to
  224.0.0.251:5353 and two seconds of listening; the answers carry the
  name, and the A records the address (a hand-written DNS reader: the
  four record types this needs are simple). On Windows the system's own
  resolver holds port 5353 and keeps the multicast answers to itself, so
  this finds nothing there - the sweep does the work; on Linux and macOS
  it is the quick way.
- **A known device's list**: every WLED keeps the nodes it has heard on
  the network (`/json/nodes`), so one known address finds the rest.
- **A sweep of the subnet**: `/json/info` asked of every address on the
  active interface's /24, sixty at a time, with a short timeout. Slower
  (a few seconds) but it finds a device whose mDNS the router eats.

A device is a dict: host, name, arch, ver, vid, release, fx (how many
effects), script (whether the Studio Script effect is there), seen (when
it last answered), and reachable. The list lives in the app's
preferences (a network is not a project's); the ACTIVE device - the one
every "send" and the flash go to - is the project's `device` option, as
it always was.
"""
import json
import queue
import socket
import struct
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

MDNS_ADDR, MDNS_PORT = "224.0.0.251", 5353
SERVICE = "_wled._tcp.local"


# --- one device -------------------------------------------------------------------------
def clean_host(host):
    host = (host or "").strip().rstrip("/")
    if host.startswith("http://"):
        host = host[7:]
    if host.startswith("https://"):
        host = host[8:]
    return host


def _get(host, path, timeout):
    with urllib.request.urlopen(f"http://{host}{path}", timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def probe(host, timeout=3.0, effects=True):
    """What a device is, from /json/info (and whether it has the Studio
    Script effect, from /json/effects); None if it does not answer."""
    host = clean_host(host)
    try:
        i = _get(host, "/json/info", timeout)
    except Exception:
        return None
    d = {"host": host, "name": i.get("name") or host, "arch": i.get("arch", ""), "ver": i.get("ver", ""),
         "vid": i.get("vid", ""), "release": i.get("release", ""), "fx": i.get("fxcount", 0),
         "mac": i.get("mac", ""), "uptime": i.get("uptime", 0), "fps": (i.get("leds") or {}).get("fps"),
         "seen": time.strftime("%Y-%m-%d %H:%M"), "reachable": True}
    st = (i.get("u") or {}).get("Studio Script")
    d["script_state"] = st[0] if isinstance(st, list) and st else ""
    if effects:
        try:
            names = _get(host, "/json/effects", timeout)
            d["script"] = any("Studio Script" in str(n) for n in names)
        except Exception:
            d["script"] = None
    return d


def state(host, timeout=3.0):
    """What the device runs now: (effect name, fps, the Script effect's
    budget line) - None if it does not answer."""
    host = clean_host(host)
    try:
        s = _get(host, "/json/state", timeout)
        i = _get(host, "/json/info", timeout)
        names = _get(host, "/json/effects", timeout)
    except Exception:
        return None
    seg = next((g for g in s.get("seg", []) if g.get("id") == s.get("mainseg", 0)), (s.get("seg") or [{}])[0])
    fx = seg.get("fx", 0)
    name = names[fx] if 0 <= fx < len(names) else f"effect {fx}"
    st = (i.get("u") or {}).get("Studio Script")
    return {"effect": str(name).split("@")[0], "fps": (i.get("leds") or {}).get("fps"), "on": s.get("on"),
            "bri": s.get("bri"), "script_state": st[0] if isinstance(st, list) and st else "",
            "pal": seg.get("pal"), "sx": seg.get("sx"), "ix": seg.get("ix")}


def env_for(device, envs):
    """The build environment that fits a device, from its arch and release:
    the first of `envs` for its chip, a project's own *_customfx env
    preferred over WLED's stock ones. None when nothing fits."""
    arch = (device.get("arch") or "").lower().replace("-", "").replace("_", "")
    rel = (device.get("release") or "").lower()
    if "s3" in arch:
        want = ["s3"]
    elif "s2" in arch:
        want = ["s2"]
    elif "c3" in arch:
        want = ["c3"]
    elif "8266" in arch:
        want = ["8266", "nodemcu", "esp01"]
    elif "esp32" in arch:
        want = ["esp32dev", "esp32_"]
    else:
        return None
    fits = [e for e in envs if any(w in e.lower() for w in want) and not (("s3" in e.lower() or "s2" in e.lower() or "c3" in e.lower()) and want == ["esp32dev", "esp32_"])]
    if not fits:
        return None
    # a flash-size hint in the release name ("16MB") narrows it further
    for mb in ("16mb", "8mb", "4mb"):
        if mb in rel:
            narrowed = [e for e in fits if mb in e.lower()]
            if narrowed:
                fits = narrowed + [e for e in fits if e not in narrowed]
            break
    custom = [e for e in fits if e.lower().endswith("customfx") and not e.startswith("studio_")]
    return (custom or [e for e in fits if not e.startswith("studio_")] or fits)[0]


# --- finding them -----------------------------------------------------------------------
def _dns_name(data, pos):
    """A DNS name at `pos` (with compression pointers): (name, next pos)."""
    parts, jumped, end = [], False, pos
    guard = 0
    while guard < 64:
        guard += 1
        n = data[pos]
        if n == 0:
            pos += 1
            break
        if n & 0xC0 == 0xC0:
            ptr = struct.unpack("!H", data[pos:pos + 2])[0] & 0x3FFF
            if not jumped:
                end = pos + 2
            jumped = True
            pos = ptr
            continue
        parts.append(data[pos + 1:pos + 1 + n].decode("utf-8", "replace"))
        pos += 1 + n
    if not jumped:
        end = pos
    return ".".join(parts), end


def _dns_records(data):
    """Every answer / additional record of a DNS packet: (name, type, rdata offset, rdata)."""
    out = []
    try:
        qd, an, ns, ar = struct.unpack("!HHHH", data[4:12])
        pos = 12
        for _ in range(qd):
            _, pos = _dns_name(data, pos); pos += 4
        for _ in range(an + ns + ar):
            name, pos = _dns_name(data, pos)
            typ, _cls, _ttl, rdlen = struct.unpack("!HHIH", data[pos:pos + 10])
            pos += 10
            out.append((name, typ, pos, data[pos:pos + rdlen]))
            pos += rdlen
    except Exception:
        pass
    return out


def mdns_scan(seconds=2.5, log=lambda m: None):
    """Hosts answering for _wled._tcp.local: [(ip, instance name)]."""
    q = bytearray(struct.pack("!HHHHHH", 0, 0, 1, 0, 0, 0))
    for part in SERVICE.split("."):
        q += bytes([len(part)]) + part.encode()
    q += struct.pack("!HH", 12, 1)                         # PTR, IN
    found = {}
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.settimeout(0.3)
        s.bind(("", 0))
        s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
        s.sendto(bytes(q), (MDNS_ADDR, MDNS_PORT))
    except Exception as e:
        log(f"mDNS query failed: {e}")
        return []
    t0 = time.time()
    while time.time() - t0 < seconds:
        try:
            data, addr = s.recvfrom(9000)
        except socket.timeout:
            continue
        except Exception:
            break
        recs = _dns_records(data)
        names = [_dns_name(r[3], 0)[0] for r in recs if r[1] == 12 and r[0].lower() == SERVICE]
        if not names:
            continue
        a = {r[0].lower(): socket.inet_ntoa(r[3]) for r in recs if r[1] == 1 and len(r[3]) == 4}
        for inst in names:
            target = None
            for r in recs:
                if r[1] == 33 and r[0].lower() == inst.lower() and len(r[3]) >= 6:   # SRV: target after 6 bytes
                    target, _ = _dns_name(data, r[2] + 6)
            ip = a.get((target or "").lower()) or addr[0]
            found[ip] = inst.split("._")[0]
    s.close()
    return sorted(found.items())


def nodes_of(host, timeout=3.0):
    """The nodes a WLED device has heard: [(ip, name)]."""
    try:
        d = _get(clean_host(host), "/json/nodes", timeout)
    except Exception:
        return []
    out = []
    for n in d.get("nodes", []):
        ip = n.get("ip")
        if ip:
            out.append((ip, n.get("name", ip)))
    return out


def local_prefix():
    """The /24 of the interface that routes out: '192.168.1.'"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip.rsplit(".", 1)[0] + "."
    except Exception:
        return None


def sweep(prefix=None, timeout=0.8, log=lambda m: None, stop=lambda: False):
    """Every address of the /24, asked /json/info: [(ip, name)]."""
    prefix = prefix or local_prefix()
    if not prefix:
        log("no network interface found")
        return []
    hosts = [f"{prefix}{i}" for i in range(1, 255)]
    out = []

    def one(h):
        if stop():
            return None
        try:
            i = _get(h, "/json/info", timeout)
            return (h, i.get("name") or h) if "ver" in i else None
        except Exception:
            return None
    with ThreadPoolExecutor(max_workers=60) as ex:
        for r in ex.map(one, hosts):
            if r:
                out.append(r)
    return out


class Scan:
    """A scan on a worker: the log lines and the devices found arrive on
    the queue as ("log", text) / ("device", dict) / ("done", n)."""
    def __init__(self, mode, known_hosts=(), prefix=None):
        self.mode, self.known, self.prefix = mode, list(known_hosts), prefix
        self.q = queue.Queue()
        self.done = False
        self._stop = False

    def start(self):
        threading.Thread(target=self._run, daemon=True).start()

    def cancel(self):
        self._stop = True

    def log(self, m):
        self.q.put(("log", m))

    def _run(self):
        try:
            hosts = {}
            if self.mode in ("mdns", "all"):
                self.log("asking the network for _wled._tcp ...")
                for ip, name in mdns_scan(log=self.log):
                    hosts[ip] = name
                self.log(f"mDNS: {len(hosts)} answered")
            if self.mode in ("nodes", "all") and not self._stop:
                for h in self.known:
                    got = nodes_of(h)
                    if got:
                        self.log(f"{h} knows {len(got)} node(s)")
                    for ip, name in got:
                        hosts.setdefault(ip, name)
            if self.mode in ("sweep", "all") and not self._stop:
                self.log(f"sweeping {self.prefix or local_prefix() or '?'}0/24 ...")
                for ip, name in sweep(self.prefix, log=self.log, stop=lambda: self._stop):
                    hosts.setdefault(ip, name)
            n = 0
            for ip in sorted(hosts, key=lambda s: [int(p) if p.isdigit() else p for p in s.split(".")]):
                if self._stop:
                    break
                d = probe(ip)
                if d:
                    n += 1
                    self.q.put(("device", d))
                    self.log(f"{d['name']} at {ip}: WLED {d['ver']}, {d['arch']}, {d['fx']} effects"
                             + (", Studio Script" if d.get("script") else ""))
                else:
                    self.log(f"{ip} ({hosts[ip]}) did not answer /json/info")
            self.q.put(("done", n))
        except Exception as e:
            self.log(f"scan failed: {e}")
            self.q.put(("done", 0))
        finally:
            self.done = True


class Probe:
    """One device asked on a worker: ("device", dict|None) then ("state", dict|None)."""
    def __init__(self, host):
        self.host = host
        self.q = queue.Queue()
        self.done = False

    def start(self):
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        try:
            self.q.put(("device", probe(self.host)))
            self.q.put(("state", state(self.host)))
        finally:
            self.done = True
