"""OSC in: a phone's or a tablet's faders (TouchOSC, Open Stage Control, a
DAW's OSC out) onto the same targets MIDI learn drives - midi.py's maps,
midi_ui.py's learn and its window. Off until the project turns it on (the
MIDI window's OSC row); it listens on a UDP port of this machine for OSC
1.0 messages and bundles. Nothing here sends.

A control is ("osc", address, k): the k-th number of the messages sent to
that address (an XY pad's two are k 0 and 1). Its value is a fraction of
its range: a float as sent, held to 0..1 (the faders' own range); an int 0
or 1 as off or on, and any other int as MIDI's 0..127; true and false as 1
and 0. Strings, blobs and the rest are left out.

    o = OscIn(); o.open(9000)                 # datagrams arrive on its thread
    for ctl, frac in o.drain(): ...           # taken on the main thread, once a frame

OSC has no sender check (WLED's own UDP sync has none either): anyone on
the network who can reach the port can move what is mapped - which is why
it is off until asked for, and only ever moves the sim's sliders and pins.
"""
import socket
import struct
import threading
import time
from collections import deque

DEFAULT_PORT = 9000
MAX_DEPTH = 8                    # bundles inside bundles: no deeper (a packet cannot recurse us down)


def _string(data, at):
    """An OSC-string at `at`: its text and where the next field starts (a
    string ends in a 0 and is padded with 0s to a multiple of four)."""
    end = data.index(b"\0", at)
    return data[at:end].decode("utf-8", "replace"), (end + 4) & ~3


def _args(tags, data, at):
    """The arguments the type tags describe, from `at`: [value], numbers
    as numbers, True/False for T/F, None for what is not a number."""
    out = []
    for t in tags:
        if t == "i":
            out.append(struct.unpack_from(">i", data, at)[0]); at += 4
        elif t == "f":
            out.append(struct.unpack_from(">f", data, at)[0]); at += 4
        elif t == "h":
            out.append(struct.unpack_from(">q", data, at)[0]); at += 8
        elif t == "d":
            out.append(struct.unpack_from(">d", data, at)[0]); at += 8
        elif t in "sS":
            _, at = _string(data, at); out.append(None)
        elif t == "b":
            n = struct.unpack_from(">i", data, at)[0]
            if n < 0 or at + 4 + n > len(data):
                raise ValueError("a blob longer than its packet")
            at = (at + 4 + n + 3) & ~3; out.append(None)
        elif t in "tcrm":                                   # a timetag (8 bytes), a char, a colour, a MIDI message (4)
            at += 8 if t == "t" else 4; out.append(None)
        elif t == "T":
            out.append(True)
        elif t == "F":
            out.append(False)
        elif t in "NI[]":                                   # nil, infinitum, an array's brackets: no data
            if t in "NI":
                out.append(None)
        else:
            raise ValueError(f"an unknown type tag {t!r}")
        if at > len(data):
            raise ValueError("arguments past the packet's end")
    return out


def parse(data, depth=0):
    """A packet to [(address, [value])]: one message, or every message of
    a bundle (and of the bundles inside it). Raises ValueError (or
    struct.error) on a packet that is not OSC."""
    if depth > MAX_DEPTH:
        raise ValueError("bundles nested too deep")
    if data.startswith(b"#bundle\0"):
        out, at = [], 16                                    # "#bundle\0" and the timetag (followed at once: no scheduling)
        while at + 4 <= len(data):
            n = struct.unpack_from(">i", data, at)[0]
            at += 4
            if n <= 0 or at + n > len(data):
                raise ValueError("a bundle element longer than its packet")
            out += parse(data[at:at + n], depth + 1)
            at += n
        return out
    if not data.startswith(b"/"):
        raise ValueError("not an OSC message")
    addr, at = _string(data, 0)
    if at >= len(data):
        return [(addr, [])]                                 # no type tags: an old sender's bare address
    tags, at = _string(data, at)
    if not tags.startswith(","):
        raise ValueError("no type tag string")
    return [(addr, _args(tags[1:], data, at))]


def fraction(v):
    """An argument as a control's position 0..1, or None for one that is not a number."""
    if v is None:
        return None
    if isinstance(v, bool):
        return 1.0 if v else 0.0
    if isinstance(v, int):
        return float(v) if v in (0, 1) else max(0.0, min(1.0, v / 127.0))
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if f != f:                                              # NaN: no position at all
        return None
    return max(0.0, min(1.0, f))


def controls(messages):
    """[(ctl, fraction)] of parsed messages: ("osc", address, k) for each number."""
    out = []
    for addr, args in messages:
        for k, v in enumerate(args):
            f = fraction(v)
            if f is not None:
                out.append((("osc", addr, k), f))
    return out


def message(address, *args):
    """An OSC message of floats, ints and bools - the tests' (and a sender's)."""
    def pad(b):
        return b + b"\0" * (4 - len(b) % 4)
    tags, body = ",", b""
    for a in args:
        if isinstance(a, bool):
            tags += "T" if a else "F"
        elif isinstance(a, int):
            tags += "i"; body += struct.pack(">i", a)
        else:
            tags += "f"; body += struct.pack(">f", float(a))
    return pad(address.encode()) + pad(tags.encode()) + body


def bundle(*packets):
    """An OSC bundle of packets, timetag 1 ("at once")."""
    out = b"#bundle\0" + struct.pack(">Q", 1)
    for p in packets:
        out += struct.pack(">i", len(p)) + p
    return out


class OscIn:
    """One UDP port listened on; its messages queued for the main thread."""

    def __init__(self):
        self._sock = None
        self.port = None                 # the port listened on (the one the OS gave, for 0)
        self._q = deque(maxlen=4096)
        self._lock = threading.Lock()
        self.last = None                 # (ctl, fraction, time): the newest seen, for the window
        self.bad = 0                     # packets that were not OSC

    def open(self, port=DEFAULT_PORT, host="0.0.0.0"):
        """Listen on `port` (0: any free one). Raises OSError when it is taken."""
        self.close()
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.bind((host, int(port)))
        except OSError:
            s.close()
            raise
        s.settimeout(0.5)                # the thread looks up every half second: close() ends it
        self._sock, self.port = s, s.getsockname()[1]
        threading.Thread(target=self._run, args=(s,), daemon=True, name="osc-in").start()
        return self.port

    def _run(self, s):
        while self._sock is s:
            try:
                data, _addr = s.recvfrom(65535)
            except socket.timeout:
                continue
            except OSError:
                break                    # closed under us
            self.feed(data)

    def feed(self, data):
        """A datagram as if it came to the port (the thread's, the tests')."""
        try:
            evs = controls(parse(data))
        except (ValueError, struct.error, UnicodeError):
            self.bad += 1
            return
        if evs:
            with self._lock:
                self._q.extend(evs)

    def inject(self, address, *args):
        """A message as if a sender sent it: the tests' and a hook's."""
        self.feed(message(address, *args))

    def drain(self):
        """Everything since the last call, oldest first: [(ctl, fraction)]."""
        with self._lock:
            out = list(self._q); self._q.clear()
        if out:
            self.last = (out[-1][0], out[-1][1], time.time())
        return out

    def close(self):
        s, self._sock, self.port = self._sock, None, None
        if s is not None:
            try:
                s.close()
            except OSError:
                pass
