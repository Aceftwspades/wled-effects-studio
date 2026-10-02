"""Live output: the sim's frames to the device as it draws them, and the
wiring test.

WLED takes pixels in real time over DDP (UDP 4048): a 10-byte header -
flags (version 1, push on the last packet of a frame), a sequence number,
the data type (RGB, 8 bits a channel), the destination (the display),
the byte offset and the length, all big-endian - then the bytes, at most
1440 a packet (480 LEDs). The device shows them in place of its effect
for as long as they keep coming (its realtime timeout, 2.5 s by default)
and goes back to its effect after. Which order the pixels go in is the
device's: WLED puts realtime pixels on its segment's LOGICAL places and
maps them to the wiring with its own table (ledmap, or 2-D setup) while
its Sync settings say "Respect LED maps" - on by default - so the frame
goes as the effect draws it; only with that off does it take them in
wiring order, and the geometry's `phys` lays them out (device_wiring
.stream_order says which). Sent in wiring order to a device that maps
them, a cube came out scrambled: its map applied twice.

    out = DdpOut("192.168.1.17"); out.send(rgb_bytes); out.close()

The wiring test is a frame generator: a chase along the wiring order, one
LED by index, or one part of a shape, written into the engine's pixel
buffer (so the sim's views show it) and streamed like any other frame.
"""
import collections
import socket
import struct
import time
import uuid

import numpy as np

DDP_PORT = 4048
DDP_MAX = 1440                      # bytes of pixel data a packet carries
FLAG_VER1, FLAG_PUSH = 0x40, 0x01
TYPE_RGB8 = 0x0B                    # RGB, 8 bits a channel
ID_DISPLAY = 1
E131_PORT, ARTNET_PORT = 5568, 6454
UNIVERSE_BYTES = 510                # 170 RGB pixels a universe: WLED's "Multiple RGB", xLights' and Falcon's default


class _UdpOut:
    """What every sender shares: a non-blocking UDP socket to the device's IP (a host written
    with its web port, "192.168.1.17:8080" or the tests' fake, takes the protocol's own port),
    the counts, and the last second's frames and bytes for the stream's health line."""
    NAME = "?"

    def __init__(self, host, port):
        self.host, self.port = host, port
        self.ip = host.rsplit(":", 1)[0] if host.count(":") == 1 else host
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setblocking(False)
        self.frames = 0
        self.bytes = 0
        self.errors = 0
        self.last_error = ""
        self._sent = collections.deque()             # (time, bytes) of each frame in the last second

    def _put(self, pkt):
        try:
            self.sock.sendto(pkt, (self.ip, self.port))
            self.bytes += len(pkt)
            return True
        except OSError as e:
            self.errors += 1; self.last_error = str(e)
            return False

    def _frame_done(self, nbytes):
        self.frames += 1
        now = time.perf_counter()
        self._sent.append((now, nbytes))
        while self._sent and now - self._sent[0][0] > 1.0:
            self._sent.popleft()

    def rate(self):
        """(frames a second, kbit a second) over the last second."""
        now = time.perf_counter()
        while self._sent and now - self._sent[0][0] > 1.0:
            self._sent.popleft()
        return float(len(self._sent)), sum(b for _, b in self._sent) * 8.0 / 1000.0

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass


class DdpOut(_UdpOut):
    NAME = "DDP"

    def __init__(self, host, port=DDP_PORT):
        super().__init__(host, port)
        self.seq = 1

    def send(self, data):
        """One frame: `data` is the RGB bytes in physical order."""
        data = bytes(data)
        n = len(data)
        off, sent = 0, 0
        while off < n or n == 0:
            chunk = data[off:off + DDP_MAX]
            last = off + len(chunk) >= n
            head = struct.pack("!BBBBIH", FLAG_VER1 | (FLAG_PUSH if last else 0), self.seq, TYPE_RGB8, ID_DISPLAY, off, len(chunk))
            if not self._put(head + chunk):
                break
            sent += len(head) + len(chunk)
            off += len(chunk)
            if n == 0:
                break
        self.seq = self.seq % 15 + 1
        self._frame_done(sent)


class E131Out(_UdpOut):
    """sACN (ANSI E1.31-2018): a data packet a universe, 510 bytes of RGB (170 pixels) in each, from
    `universe` up, to the device's IP on 5568 - what WLED takes with E1.31 on in its Sync settings
    (DMX mode Multiple RGB), and what Falcon, ESPixelStick or FPP controllers take. Each universe
    keeps its own sequence number."""
    NAME = "E1.31 (sACN)"
    ROOT_ID = b"ASC-E1.17\x00\x00\x00"

    def __init__(self, host, universe=1, port=E131_PORT, source="WLED Effects Studio", priority=100):
        super().__init__(host, port)
        self.universe = max(1, min(63999, int(universe)))
        self.cid = uuid.uuid4().bytes                  # this sender, for the receiver to tell sources apart
        self.source = source.encode("utf-8")[:63].ljust(64, b"\x00")
        self.priority = max(0, min(200, int(priority)))
        self.seqs = {}

    def packet(self, universe, data, seq):
        """One E1.31 data packet: the root layer, the framing layer, the DMP layer (start code 0)."""
        n = len(data)
        total = 126 + n
        root = struct.pack("!HH12sHI16s", 0x0010, 0x0000, self.ROOT_ID, 0x7000 | (total - 16), 0x00000004, self.cid)
        framing = struct.pack("!HI64sBHBBH", 0x7000 | (total - 38), 0x00000002, self.source, self.priority, 0,
                              seq & 255, 0, universe)
        dmp = struct.pack("!HBBHHHB", 0x7000 | (total - 115), 0x02, 0xA1, 0x0000, 0x0001, n + 1, 0x00)
        return root + framing + dmp + bytes(data)

    def send(self, data):
        data = bytes(data)
        sent = 0
        for k, off in enumerate(range(0, max(1, len(data)), UNIVERSE_BYTES)):
            u = self.universe + k
            seq = self.seqs.get(u, 0)
            self.seqs[u] = (seq + 1) & 255
            pkt = self.packet(u, data[off:off + UNIVERSE_BYTES], seq)
            if not self._put(pkt):
                break
            sent += len(pkt)
        self._frame_done(sent)


class ArtNetOut(_UdpOut):
    """Art-Net (Art-Net 4): an ArtDMX packet a universe, 510 bytes of RGB (170 pixels) in each, from
    the port-address `universe` up (net, sub-net and universe in its 15 bits), to the device's IP on
    6454 - WLED with Art-Net on in its Sync settings, and the lighting world's nodes. The sequence
    runs 1..255 (0 would switch the receiver's reordering off)."""
    NAME = "Art-Net"

    def __init__(self, host, universe=0, port=ARTNET_PORT):
        super().__init__(host, port)
        self.universe = max(0, min(32767, int(universe)))
        self.seq = 1

    def packet(self, universe, data, seq):
        """One ArtDMX packet: the ID, OpDmx (0x5000, low byte first), protocol 14, the sequence, the
        port-address (SubUni, Net) and the length (big-endian, even)."""
        data = bytes(data)
        if len(data) % 2:
            data += b"\x00"
        return (b"Art-Net\x00" + struct.pack("<H", 0x5000) + struct.pack("!H", 14)
                + struct.pack("!BBBB", seq & 255, 0, universe & 0xFF, (universe >> 8) & 0x7F)
                + struct.pack("!H", len(data)) + data)

    def send(self, data):
        data = bytes(data)
        sent = 0
        for k, off in enumerate(range(0, max(1, len(data)), UNIVERSE_BYTES)):
            pkt = self.packet(self.universe + k, data[off:off + UNIVERSE_BYTES], self.seq)
            if not self._put(pkt):
                break
            sent += len(pkt)
        self.seq = self.seq % 255 + 1
        self._frame_done(sent)


# the protocols the stream can speak: (key, name, the universe it starts at by default - None: none)
PROTOCOLS = (("ddp", "DDP", None), ("e131", "E1.31 (sACN)", 1), ("artnet", "Art-Net", 0))


def make_out(protocol, host, universe=None):
    """A sender for `protocol` ("ddp", "e131", "artnet") to host."""
    if protocol == "e131":
        return E131Out(host, 1 if universe is None else universe)
    if protocol == "artnet":
        return ArtNetOut(host, 0 if universe is None else universe)
    return DdpOut(host)


def stream_bytes(rgb, geom, order="logical"):
    """The engine's picture as the device takes it: "logical" - every
    logical pixel, as the effect draws it (the device's table maps them) -
    or "wiring" - LED by LED, each at its number on the device (a device
    map's own numbering where the geometry has one)."""
    flat = np.asarray(rgb, np.uint8).reshape(-1, 3)
    if order == "logical":
        return flat.tobytes()
    phys = np.asarray(geom.phys, int)
    ids = getattr(geom, "phys_ids", None)
    ids = np.arange(len(phys)) if ids is None else np.asarray(ids, int)
    ok = (phys >= 0) & (phys < len(flat)) & (ids >= 0)
    out = np.zeros((int(ids[ok].max()) + 1 if ok.any() else 0, 3), np.uint8)
    out[ids[ok]] = flat[phys[ok]]
    return out.tobytes()


def frame_bytes(rgb, phys):
    """The engine's (rows, cols, 3) picture as RGB bytes in wiring order."""
    flat = np.asarray(rgb, np.uint8).reshape(-1, 3)
    idx = np.asarray(phys, int)
    idx = idx[(idx >= 0) & (idx < len(flat))]
    return flat[idx].tobytes()


# --- the wiring test -------------------------------------------------------------------
MODES = ("off", "chase", "index", "part", "parts in turn", "output", "red", "green", "blue", "white", "alternate", "twinkle")


class WiringTest:
    """A pattern over the LEDs in wiring order, advanced by time.

        t = WiringTest(n_leds, owner=None)   # owner: part index per LED (a shape), or None
        colours = t.frame(dt)                # (n_leds, 3) uint8, in WIRING order
    """
    def __init__(self, n, owner=None, names=None, outputs=None):
        self.n = max(1, int(n))
        self.owner = None if owner is None else np.asarray(owner, int)
        self.names = names or []
        self.outputs = outputs or []     # [(start, count)] of the device's LED outputs, for the "output" mode
        self.mode = "chase"
        self.speed = 20.0            # LEDs a second (chase), or parts a second / 2 (parts in turn)
        self.trail = 6               # LEDs lit behind the head
        self.index = 0               # the LED (index mode) or the part (part mode)
        self.colour = (255, 255, 255)
        self.mask = None             # (n,) bool: the LEDs lit in the "mask" mode (mapping by camera's binary codes)
        self.pos = 0.0
        self.t = 0.0

    def describe(self):
        if self.mode == "chase":
            k = int(self.pos) % self.n
        elif self.mode == "index":
            k = self.index % self.n
        elif self.mode == "part":
            p = self.index % max(1, self._parts())
            return f"part {p + 1}" + (f": {self.names[p]}" if p < len(self.names) else "") + f", {int((self.owner == p).sum()) if self.owner is not None else self.n} LEDs"
        elif self.mode == "parts in turn":
            p = int(self.t * self.speed / 20.0) % max(1, self._parts())
            return f"part {p + 1}" + (f": {self.names[p]}" if p < len(self.names) else "")
        elif self.mode == "output":
            if not self.outputs:
                return "no outputs: split the wiring in the LED outputs frame"
            o = self.index % len(self.outputs)
            return f"output {o + 1} of {len(self.outputs)}: LEDs {self.outputs[o][0]}..{self.outputs[o][0] + self.outputs[o][1] - 1}"
        elif self.mode in ("red", "green", "blue", "white"):
            return f"all {self.mode}: every LED the one colour - a colour-order check"
        elif self.mode == "mask":
            return f"{int(np.count_nonzero(self.mask)) if self.mask is not None else 0} LEDs lit by code"
        elif self.mode == "alternate":
            return "every other LED, swapping"
        elif self.mode == "twinkle":
            return "random LEDs, briefly"
        else:
            return ""
        s = f"LED {k} of {self.n}"
        if self.owner is not None and k < len(self.owner):
            p = int(self.owner[k])
            s += f" (part {p + 1}" + (f": {self.names[p]}" if p < len(self.names) else "") + f", #{int((self.owner[:k] == p).sum())})"
        return s

    def _parts(self):
        return int(self.owner.max()) + 1 if self.owner is not None and len(self.owner) else 1

    def frame(self, dt):
        self.t += dt
        out = np.zeros((self.n, 3), np.uint8)
        c = np.asarray(self.colour, np.uint8)
        if self.mode == "chase":
            self.pos = (self.pos + dt * self.speed) % self.n
            head = int(self.pos)
            for k in range(self.trail + 1):
                i = (head - k) % self.n
                f = 1.0 if k == 0 else max(0.0, 1.0 - k / (self.trail + 1)) * 0.5
                out[i] = np.maximum(out[i], (c * f).astype(np.uint8))
        elif self.mode == "index":
            out[self.index % self.n] = c
        elif self.mode == "mask" and self.mask is not None:
            m = np.asarray(self.mask, bool)[:self.n]
            out[:len(m)][m] = c
        elif self.mode == "part" and self.owner is not None:
            out[self.owner == (self.index % self._parts())] = c
        elif self.mode == "parts in turn" and self.owner is not None:
            p = int(self.t * self.speed / 20.0) % self._parts()
            out[self.owner == p] = c
        elif self.mode in ("part", "parts in turn"):
            out[:] = c
        elif self.mode == "output" and self.outputs:
            start, count = self.outputs[self.index % len(self.outputs)]
            out[max(0, start):max(0, start) + max(0, count)] = c
        elif self.mode in ("red", "green", "blue", "white"):
            out[:] = {"red": (255, 0, 0), "green": (0, 255, 0), "blue": (0, 0, 255), "white": (255, 255, 255)}[self.mode]
        elif self.mode == "alternate":
            phase = int(self.t * self.speed / 20.0) % 2
            out[phase::2] = c
        elif self.mode == "twinkle":
            rng = np.random.default_rng(int(self.t * self.speed / 4.0))
            k = max(1, self.n // 12)
            out[rng.choice(self.n, size=min(k, self.n), replace=False)] = c
        return out
