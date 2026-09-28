"""MIDI learn: a controller's knobs onto the panel's sliders - and through
the sim, the device: the DDP stream carries what the sliders make.

python-rtmidi is optional (pip install python-rtmidi); without it the
window says so and nothing else changes. A mapping is a control - a CC
number on a channel, a note for a button, the pitch bend - and a target:
an effect slider (sx, ix, c1..c3), a check (o1..o3), the palette or the
effect by index, or a typed value on a node's pin with a range. The
mappings live in the project's options under "midi":

    {"port": "nanoKONTROL2 0", "maps": [{"ctl": ["cc", 0, 7], "target": {"kind": "fx", "key": "sx"}}, ...]}

    m = MidiIn(); m.open(m.ports()[0])         # messages arrive on rtmidi's thread
    for ctl, value in m.drain(): ...           # taken on the main thread, once a frame

Learn: the app asks for the next control moved; the first message binds
that control to the target asked for (midi_ui.py does the asking).

A MIDI clock on the port - a drum machine's, a DAW's: 24 ticks a beat,
with start, continue and stop - is followed apart from the controls: its
tempo from the ticks' spacing and a beat at every 24th tick from the
start, which midi_ui gives the synth (its beat fired by the clock, not its
own period), when the project's "clock" setting is on.
"""
import threading
import time
from collections import deque

CLOCK_PPQN = 24                  # MIDI clock ticks a beat (a quarter note)
CLOCK_GONE_S = 0.5               # no tick for this long: the clock has stopped, stop message or not

try:
    import rtmidi
except Exception:                       # not installed, or no MIDI API on this OS
    rtmidi = None

FX_KEYS = ("sx", "ix", "c1", "c2", "c3")
CHECK_KEYS = ("o1", "o2", "o3")


def available():
    return rtmidi is not None


def ports():
    """The MIDI inputs on this machine, by name; [] without python-rtmidi."""
    if rtmidi is None:
        return []
    try:
        return list(rtmidi.MidiIn().get_ports())
    except Exception:
        return []


def parse(msg):
    """A raw message to (control, value 0..127), or None for what is not
    a control: a control change is ("cc", channel, number); a note is
    ("note", channel, number), on at its velocity and off at 0; the pitch
    bend is ("bend", channel, 0) with its coarse byte."""
    if not msg:
        return None
    st, ch = msg[0] & 0xF0, msg[0] & 0x0F
    if st == 0xB0 and len(msg) >= 3:
        return ("cc", ch, int(msg[1])), int(msg[2])
    if st == 0x90 and len(msg) >= 3:
        return ("note", ch, int(msg[1])), int(msg[2])
    if st == 0x80 and len(msg) >= 3:
        return ("note", ch, int(msg[1])), 0
    if st == 0xE0 and len(msg) >= 3:
        return ("bend", ch, 0), int(msg[2])
    return None


def ctl_label(ctl):
    kind, ch, n = ctl
    return {"cc": f"CC {n}", "note": f"note {n}", "bend": "pitch bend"}.get(kind, kind) + f" ch {int(ch) + 1}"


def state(project):
    """The project's MIDI settings, made if missing."""
    st = project.options.setdefault("midi", {})
    st.setdefault("port", ""); st.setdefault("maps", []); st.setdefault("clock", True)
    return st


class Clock:
    """A MIDI clock followed, fed its realtime bytes as they arrive: 0xF8 a
    tick, 0xFA start (the next tick is the first beat), 0xFB continue, 0xFC
    stop. The tempo is the ticks' mean spacing over the last beat; a beat
    is every 24th tick counted from the start - or, for a clock that never
    says start or stop, from the first tick heard. Many clocks tick on
    while stopped (so what follows knows the tempo): no beats then."""

    def __init__(self):
        self.times = deque(maxlen=CLOCK_PPQN + 1)
        self.ticks = 0                   # since the start: the next tick's number
        self.transport = None            # None: never told (a free-running clock); True playing; False stopped
        self.last = -1e9                 # when the newest tick came
        self.beats = 0                   # beats not yet taken by the main thread

    def feed(self, status, now):
        if status == 0xFA:               # start: from the top
            self.transport, self.ticks = True, 0
        elif status == 0xFB:             # continue: where it stopped
            self.transport = True
        elif status == 0xFC:             # stop
            self.transport = False
        elif status == 0xF8:
            if now - self.last > CLOCK_GONE_S:
                self.times.clear()       # a gap: the spacing starts again
                if self.transport is None:
                    self.ticks = 0       # a free-running clock heard anew: its next beat is ours
            self.times.append(now)
            self.last = now
            if self.transport is not False:
                if self.ticks % CLOCK_PPQN == 0:
                    self.beats += 1
                self.ticks += 1

    def ticking(self, now):
        return now - self.last <= CLOCK_GONE_S

    def bpm(self):
        """The tempo from the last beat's ticks, or None before there are a few."""
        if len(self.times) < 4:
            return None
        span = (self.times[-1] - self.times[0]) / (len(self.times) - 1)
        return 60.0 / (span * CLOCK_PPQN) if span > 0 else None

    def take(self, now):
        """(beats since the last call, bpm or None, playing) - the main
        thread's, once a frame. Playing: ticking, and not stopped."""
        n, self.beats = self.beats, 0
        tick = self.ticking(now)
        return n, (self.bpm() if tick else None), tick and self.transport is not False


def bind(st, ctl, target):
    """`ctl` onto `target` in the maps: the same pair once, another
    target on the same control kept (one knob may turn two things)."""
    ctl = list(ctl)
    st["maps"] = [m for m in st["maps"] if not (list(m["ctl"]) == ctl and m["target"] == target)]
    st["maps"].append({"ctl": ctl, "target": target})


def unbind(st, k):
    if 0 <= k < len(st["maps"]):
        st["maps"].pop(k)


def value_for(target, v):
    """A control's 0..127 as the target wants it: a slider's integer, a
    check's on/off, a pin's number in its range (a bool pin on/off)."""
    kind = target.get("kind")
    f = max(0.0, min(1.0, v / 127.0))
    if kind == "fx":
        hi = 31 if target.get("key") == "c3" else 255
        return int(round(f * hi))
    if kind == "check":
        return v >= 64
    if kind == "pin":
        if target.get("bool"):
            return v >= 64
        lo, hi = float(target.get("lo", 0.0)), float(target.get("hi", 1.0))
        return lo + f * (hi - lo)
    return f                                              # palette, effect: a fraction of the list


class MidiIn:
    """One input port; its messages queued for the main thread."""

    def __init__(self):
        self._in = None
        self.port = None
        self._q = deque(maxlen=4096)
        self._lock = threading.Lock()
        self.last = None            # (ctl, value, time): the newest seen, for the window
        self.clock = Clock()        # the port's MIDI clock, if it sends one

    def open(self, name):
        self.close()
        if rtmidi is None:
            raise RuntimeError("python-rtmidi is not installed:  pip install python-rtmidi")
        mi = rtmidi.MidiIn()
        names = mi.get_ports()
        if name not in names:
            raise RuntimeError(f"no MIDI input named {name!r}")
        mi.open_port(names.index(name))
        mi.ignore_types(sysex=True, timing=False, active_sense=True)     # the clock's ticks let through
        mi.set_callback(self._on)
        self._in, self.port = mi, name
        self.clock = Clock()

    def _on(self, event, data=None, now=None):
        msg, _dt = event
        if msg and msg[0] in (0xF8, 0xFA, 0xFB, 0xFC):                    # the clock: kept apart from the controls
            with self._lock:
                self.clock.feed(msg[0], time.perf_counter() if now is None else now)
            return
        p = parse(list(msg))
        if p:
            with self._lock:
                self._q.append(p)

    def inject(self, msg, now=None):
        """A message as if the port sent it: the tests', and a hook's
        (`now` the time it came, for a clock's ticks)."""
        self._on((list(msg), 0.0), now=now)

    def take_clock(self, now=None):
        """(beats since the last call, bpm or None, running) of the port's clock."""
        with self._lock:
            return self.clock.take(time.perf_counter() if now is None else now)

    def drain(self):
        """Everything since the last call, oldest first: [(ctl, value)]."""
        with self._lock:
            out = list(self._q); self._q.clear()
        if out:
            self.last = (out[-1][0], out[-1][1], time.time())
        return out

    def close(self):
        if self._in is not None:
            try:
                self._in.close_port()
            except Exception:
                pass
        self._in, self.port = None, None
