"""
The synthetic audio generator, ported line for line from index.html.

This exists so native measurements can be held against the browser ones. If the
two front ends fed the effects different audio, every number either produced
would be incomparable and the parity check that lets us retire the browser build
would be meaningless.

Real audio lives in audio.py. This is the repeatable stand-in.
"""
import math
import numpy as np


class Synth:
    # The gate envelope decays over the same 200 ms the kick does, so a gated
    # band rises and falls with the transient fx_lowBeat is looking at rather
    # than on a second clock of its own.
    GATE_MS = 200.0

    def __init__(self, vol=90, bass=45, mid=50, treb=35, bpm=120, auto_beat=True):
        self.vol, self.bass, self.mid, self.treb = vol, bass, mid, treb
        self.bpm, self.auto_beat = bpm, auto_beat
        self.muted = False
        self.last_beat = -1e9
        self._last_fft = None
        self._ph = np.zeros(16, np.float32)
        self.kick_req = False
        # Gating a band means it is SILENT between beats and jumps to its slider
        # level on one. Without it only the bass ever carried a transient - the
        # kick is added to the low bins alone - so every effect reading mid or
        # treble was being shown a steady tone and could not be judged on how it
        # answers a hit.
        self.gate_bass = False
        self.gate_mid = False
        self.gate_treb = False

    def pcm(self):
        """A waveform to match the bands: sixteen sines, one to sixteen
        cycles across the window, at the bins' levels, drifting - the same
        stand-in the firmware rebuilds when it has no PCM, made here so the
        sim's Warp and Scope move as the device's do; the beat puts a kick
        on it."""
        arr = self._last_fft
        if arr is None:
            return np.zeros(256, np.float32)
        t = np.arange(256, dtype=np.float32) * (2 * np.pi / 256.0)
        w = np.zeros(256, np.float32)
        tot = 0.0
        for b in range(16):
            amp = (float(arr[b]) / 255.0) / (1.0 + 0.25 * b)
            tot += amp
            if amp < 0.004:
                continue
            w += amp * np.sin(t * (b + 1) + self._ph[b])
        w *= 1.0 / (0.35 + tot)
        return np.clip(w * 127.0, -127, 127)

    def push(self, eng):
        """Fill the engine's FFT bins and volume for the current simulated time."""
        arr = eng.fft
        if self.muted:
            arr[:] = 0
            eng.audio(0.0, 0)
            return 0

        # Beat timing runs on the SIMULATED clock, so stepping frame by frame
        # cannot drift relative to the beat.
        period = 60000.0 / max(1, self.bpm)
        # The engine's clock restarts when an effect is (re)selected or the
        # engine reloads; a beat timestamp from before that would hold the
        # next beat back until the new clock caught up with the old one -
        # minutes of silence after every rebuild. Re-arm instead.
        if eng.sim_ms < self.last_beat:
            self.last_beat = eng.sim_ms - period
        fire = self.kick_req
        if self.auto_beat and (eng.sim_ms - self.last_beat) >= period:
            fire = True
        if fire:
            self.last_beat = eng.sim_ms
            self.kick_req = False

        # A kick that decays over ~200 ms, so the low band genuinely rises above
        # its floor and falls back - a transient, not a louder held note. A
        # constant bass can never pass fx_lowBeat's rise test, because the floor
        # simply climbs to meet it.
        kick = max(0.0, 165.0 * (1.0 - (eng.sim_ms - self.last_beat) / 200.0))

        # One envelope, shared by every gated band, falling from 1 to 0 over the
        # same window the kick uses.
        env = max(0.0, 1.0 - (eng.sim_ms - self.last_beat) / self.GATE_MS)
        gb = env if self.gate_bass else 1.0
        gm = env if self.gate_mid else 1.0
        gt = env if self.gate_treb else 1.0

        T = eng.sim_ms / 1000.0
        for i in range(16):
            # The gate is interpolated across the bins exactly as the level is,
            # so a gated band fades into an ungated neighbour instead of leaving
            # a step in the middle of the spectrum.
            if i < 3:
                base, gain = self.bass, gb
            elif i < 9:
                f = (i - 3) / 6.0
                base = self.bass + (self.mid - self.bass) * f
                gain = gb + (gm - gb) * f
            else:
                f = (i - 9) / 7.0
                base = self.mid + (self.treb - self.mid) * f
                gain = gm + (gt - gm) * f
            wob = 0.55 * base * (
                0.5 * math.sin(T * (0.7 + i * 0.13) + i * 1.7)
                + 0.3 * math.sin(T * (1.9 + i * 0.07) + i * 0.9)
                + 0.2 * math.sin(T * (3.3 - i * 0.05) + i * 2.6))
            # The kick is NOT gated: it is the transient itself, and it is what
            # lets fx_lowBeat see a beat at all.
            v = (base + wob) * gain + (kick if i < 3 else 0.0)
            arr[i] = int(max(0, min(255, int(v))))

        # peak is set for exactly the firing frame: leaving it high latches
        # prevPeak inside fx_lowBeat and suppresses every later beat.
        peak = 1 if fire else 0
        eng.audio(min(255.0, self.vol + kick * 0.4), peak)
        # what pcm() draws from: these bins, phases turning as the firmware's do
        self._last_fft = np.array([int(arr[i]) for i in range(16)], np.float32)
        self._ph += np.array([(9 + 6 * b) * (2 * np.pi / 65536.0) * 33.0 for b in range(16)], np.float32)
        return peak
