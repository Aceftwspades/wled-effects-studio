"""Live output: the sim's frames to the device as it draws them, and the
wiring test.

WLED takes pixels in real time over DDP (UDP 4048): a 10-byte header -
flags (version 1, push on the last packet of a frame), a sequence number,
the data type (RGB, 8 bits a channel), the destination (the display),
the byte offset and the length, all big-endian - then the bytes, at most
1440 a packet (480 LEDs). The device shows them in place of its effect
for as long as they keep coming (its realtime timeout, 2.5 s by default)
and goes back to its effect after. Pixels are addressed in PHYSICAL
order - the wiring - so the frame is sent as the geometry's `phys` lays
it out, which is what the device's own ledmap would do for an effect.

    out = DdpOut("192.168.1.17"); out.send(rgb_bytes); out.close()

The wiring test is a frame generator: a chase along the wiring order, one
LED by index, or one part of a shape, written into the engine's pixel
buffer (so the sim's views show it) and streamed like any other frame.
"""
import socket
import struct

import numpy as np

DDP_PORT = 4048
DDP_MAX = 1440                      # bytes of pixel data a packet carries
FLAG_VER1, FLAG_PUSH = 0x40, 0x01
TYPE_RGB8 = 0x0B                    # RGB, 8 bits a channel
ID_DISPLAY = 1


class DdpOut:
    def __init__(self, host, port=DDP_PORT):
        self.host, self.port = host, port
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setblocking(False)
        self.seq = 1
        self.frames = 0
        self.bytes = 0
        self.errors = 0
        self.last_error = ""

    def send(self, data):
        """One frame: `data` is the RGB bytes in physical order."""
        data = bytes(data)
        n = len(data)
        off = 0
        while off < n or n == 0:
            chunk = data[off:off + DDP_MAX]
            last = off + len(chunk) >= n
            head = struct.pack("!BBBBIH", FLAG_VER1 | (FLAG_PUSH if last else 0), self.seq, TYPE_RGB8, ID_DISPLAY, off, len(chunk))
            try:
                self.sock.sendto(head + chunk, (self.host, self.port))
                self.bytes += len(head) + len(chunk)
            except OSError as e:
                self.errors += 1; self.last_error = str(e)
                break
            off += len(chunk)
            if n == 0:
                break
        self.seq = self.seq % 15 + 1
        self.frames += 1

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass


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
