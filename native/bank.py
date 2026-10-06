"""The device's effect bank: which compiled cube_fx effects get one of its
effect slots, and in what order - read, changed and written from the
studio, so a new effect reaches the cube's own list in one step.

The firmware (usermods/cube_fx/cube_fx_bank.{h,cpp}) keeps the choice in
its config as the CubeFXBank usermod's block:

    {"um": {"CubeFXBank": {"enabled": true, "six_faces": false,
                           "s00": 41234, "s01": 9876, ..., "s35": 0}}}

each slot the 16-bit hash of an effect's display name (cfxBankHash: the
name up to its '@', 0 an empty slot) - so a slot survives the effects
being renumbered, and a slot naming an effect the build lacks reads as
empty. The choice applies on the NEXT boot: effects register with WLED
once, in setup().

A write must carry the WHOLE block. WLED hands a posted "um" block to the
usermod's readFromConfig(), and a key missing there takes its default -
a block with only the slots in it would reset six_faces, and one without
the slots empties them all (which the firmware reads as "not configured":
every effect registers, slot order lost). So write() reads the block
first and changes only what it was asked to.

    hs = read(host)                              # {"enabled", "six_faces", "slots": [hash...]} or None
    names = slot_names(hs["slots"], candidates)  # each slot's effect name, None for one it cannot name
    write(host, ["Ace 3-D Paintball", ...])      # the block with these slots, then a reboot

Switching the device's effect live (MIDI's setlist, next and previous) is
Switcher: one POST to /json/state on a worker thread, the newest request
only, the device's effect index looked up by name in its /json/effects.
"""
import json
import queue
import threading
import time
import urllib.request

SLOTS = 36                       # CFX_BANK_SLOTS: the firmware's default; a device's block says its own


def fx_hash(name):
    """cfxBankHash(): the name up to its '@', FNV-ish folded to 16 bits, never 0 (0 is an empty slot)."""
    h = 0x1F35
    for ch in str(name).split("@", 1)[0].encode("utf-8"):
        h ^= ch
        h = (h * 31 + 7) & 0xFFFF
    return h or 1


def slot_key(i):
    return f"s{i:02d}"


def _url(host):
    host = str(host).strip().rstrip("/")
    return host if host.startswith("http") else "http://" + host


def _get(host, path, timeout):
    with urllib.request.urlopen(_url(host) + path, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def _post(host, path, body, timeout):
    req = urllib.request.Request(_url(host) + path, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def parse_block(block):
    """The bank block of a device's config as {"enabled", "six_faces", "slots"}: the slots in order, as
    many as the block has (s00, s01, ...), each a hash or 0."""
    if not isinstance(block, dict):
        return None
    n = 0
    while slot_key(n) in block:
        n += 1
    slots = []
    for i in range(n or SLOTS):
        try:
            slots.append(int(block.get(slot_key(i), 0)) & 0xFFFF)
        except (TypeError, ValueError):
            slots.append(0)
    return {"enabled": bool(block.get("enabled", True)), "six_faces": bool(block.get("six_faces", False)), "slots": slots}


def read(host, timeout=4.0):
    """The device's bank, or None when its firmware has no bank (no CubeFXBank block). Raises when the
    device does not answer."""
    cfg = _get(host, "/json/cfg", timeout)
    return parse_block((cfg.get("um") or {}).get("CubeFXBank"))


def status(host, timeout=4.0):
    """What the device says of its bank in /json/info: ("12 of 40 placed - reboot to apply changes",
    "free slots line"), either "" when it does not say."""
    i = _get(host, "/json/info", timeout)
    u = i.get("u") or {}
    a = u.get("Cube FX slots") or []
    b = u.get("Cube FX slots free") or []
    return ("".join(str(x) for x in a).strip(), "".join(str(x) for x in b).strip())


def slot_names(slots, candidates):
    """Each slot's effect name from the candidates (the effects the firmware compiles): None for an empty
    slot, "?" for a hash none of them has (an effect of another build)."""
    by = {}
    for n in candidates:
        by.setdefault(fx_hash(n), n)
    return [None if not h else by.get(h, "?") for h in slots]


def block_for(names, current, n=None):
    """The whole bank block for these slot names in order (None or "" an empty slot), the rest of it
    (enabled, six_faces) kept from `current` (parse_block's), enabled turned on."""
    cur = current or {"enabled": True, "six_faces": False, "slots": []}
    n = n or max(len(cur.get("slots") or []), SLOTS)
    names = list(names)[:n]
    out = {"enabled": True, "six_faces": bool(cur.get("six_faces", False))}
    for i in range(n):
        nm = names[i] if i < len(names) else None
        out[slot_key(i)] = fx_hash(nm) if nm else 0
    return out


def write(host, names, reboot=True, timeout=6.0):
    """The slots onto the device - its whole bank block, read first so nothing else in it changes - and,
    with `reboot`, the reboot that applies them. (ok, message)."""
    try:
        cur = read(host, timeout)
    except Exception as e:
        return False, f"the device did not answer: {e}"
    if cur is None:
        return False, "the device's firmware has no effect bank (no CubeFXBank settings): flash a cube_fx build first"
    if len([x for x in names if x]) == 0:
        return False, "no effect in any slot: the device would register every effect again - keep at least one"
    block = block_for(names, cur)
    try:
        _post(host, "/json/cfg", {"um": {"CubeFXBank": block}}, timeout)
    except Exception as e:
        return False, f"the slots were refused: {e}"
    used = sum(1 for i in range(len(cur["slots"]) or SLOTS) if block.get(slot_key(i)))
    if not reboot:
        return True, f"{used} slots written; they apply when the device reboots"
    try:
        _post(host, "/json/state", {"rb": True}, timeout)
    except Exception:
        pass                                              # it may drop the connection as it goes down
    return True, f"{used} slots written; the device is rebooting to apply them"


def set_six(host, six, timeout=5.0):
    """The bank's six_faces setting changed and nothing else: the block read, the one key set, the whole
    block written back (no reboot - the shape table follows it at once). A device without a bank gets the
    key alone, which is all it could ever read."""
    cur = read(host, timeout)
    if cur is None:
        block = {"six_faces": bool(six)}
    else:
        block = {"enabled": cur["enabled"], "six_faces": bool(six)}
        for i, h in enumerate(cur["slots"]):
            block[slot_key(i)] = h
    _post(host, "/json/cfg", {"um": {"CubeFXBank": block}}, timeout)


# --- the device's effect, switched live ----------------------------------------------------
class Switcher:
    """The device's effect set by name from the main thread without waiting on the network: send()
    queues the request (the newest replaces one not yet sent), a worker POSTs it, and messages() hands
    back what happened. The device's effect list is fetched once per host and again when a name is
    not in it (a reflash, new slots), at most every few seconds."""
    REFETCH_S = 5.0

    def __init__(self):
        self._q = queue.Queue(maxsize=1)
        self._out = []
        self._lock = threading.Lock()
        self._names = {}                                  # host -> (time fetched, [names])
        self._t = None

    def send(self, host, name, tt=0, bs=None):
        req = (host, name, int(tt), bs)
        try:
            self._q.get_nowait()                          # an older request not sent yet: dropped for this one
        except queue.Empty:
            pass
        try:
            self._q.put_nowait(req)
        except queue.Full:
            pass
        if self._t is None or not self._t.is_alive():
            self._t = threading.Thread(target=self._run, daemon=True)
            self._t.start()

    def messages(self):
        with self._lock:
            out, self._out = self._out, []
        return out

    def _say(self, ok, msg):
        with self._lock:
            self._out.append((ok, msg))

    def effect_names(self, host, fresh=False):
        got = self._names.get(host)
        if got is None or (fresh and time.time() - got[0] > self.REFETCH_S):
            names = [str(n).split("@", 1)[0] for n in _get(host, "/json/effects", 4.0)]
            got = self._names[host] = (time.time(), names)
        return got[1]

    def _run(self):
        while True:
            try:
                host, name, tt, bs = self._q.get(timeout=2.0)
            except queue.Empty:
                return
            try:
                names = self.effect_names(host)
                if name not in names:
                    names = self.effect_names(host, fresh=True)
                if name not in names:
                    self._say(False, f"{name} is not on {host}: give it a slot (Window > Effect slots...)")
                    continue
                body = {"seg": {"fx": names.index(name), "fxdef": True}}   # the device's own defaults for it
                if tt > 0:
                    body["tt"] = tt                       # a one-off transition, in tenths of a second
                    if bs is not None:
                        body["bs"] = int(bs)
                _post(host, "/json/state", body, 4.0)
                self._say(True, f"{host} runs {name}")
            except Exception as e:
                self._say(False, f"{host} did not take {name}: {e}")
