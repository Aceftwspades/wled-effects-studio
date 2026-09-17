"""
Live audio, three ways, one analyser.

  LiveAudio   Windows: WASAPI loopback of the default OUTPUT, via
              pyaudiowpatch - whatever you are listening to is what the LEDs
              see, no picker, no prompt. This is the reason the simulator
              moved off the browser, where the only route to the speakers is
              a screen-share dialog.
  LiveInput   anywhere: an INPUT device through sounddevice - a microphone,
              a line-in, or a loopback that the OS exposes as an input: a
              PulseAudio / PipeWire "Monitor of ..." on Linux, BlackHole or
              Loopback on macOS, "Stereo Mix" on Windows machines that have it.
  open_live() picks: loopback where it exists, else the default input, or a
              named device.

Audio is turned into sixteen band levels and discarded; nothing is written to
disk or sent anywhere. Both present the same push(engine) call as
synth.Synth, so the three are interchangeable everywhere.
"""
import sys

import numpy as np
import time
import os

try:
    import pyaudiowpatch as pyaudio
except ImportError:                                    # pragma: no cover
    pyaudio = None
try:
    import sounddevice as sd
except ImportError:                                    # pragma: no cover
    sd = None


class LiveAudio:
    # Sixteen log-spaced bands, 50 Hz to 10 kHz. This APPROXIMATES the shape of
    # WLED's own sixteen bands rather than reproducing their exact edges - close
    # enough to judge an effect by, and not claimed to be more.
    LO, HI, BANDS = 50.0, 10000.0, 16

    # 2048 samples at 48 kHz is 23 Hz per bin and 43 ms of latency. 1024 halves
    # the latency and costs twice the bin width, which at the bottom of the
    # range is the difference between the lowest bands resolving and collapsing
    # onto each other - the bass bands are the ones driving beat detection, so
    # resolution wins.
    def __init__(self, gain=3.0, chunk=2048):
        if pyaudio is None:
            raise RuntimeError("pyaudiowpatch is not installed:  pip install pyaudiowpatch")
        self.gain = gain
        self.chunk = chunk
        self.p = pyaudio.PyAudio()
        dev = self._loopback_device()
        self.rate = int(dev["defaultSampleRate"])
        self.channels = int(dev["maxInputChannels"])
        self.name = dev["name"]
        self._buf = np.zeros(chunk, np.float32)
        self._win = np.hanning(chunk).astype(np.float32)
        self._edges = self._band_edges()
        self._prev_low = 0.0
        self._floor = 0.0
        self._primed = False
        self._agc = 1.0
        self.level = 0.0
        self.stream = self.p.open(
            format=pyaudio.paFloat32, channels=self.channels, rate=self.rate,
            input=True, input_device_index=dev["index"],
            frames_per_buffer=chunk, stream_callback=self._cb)

    def _loopback_device(self):
        """The loopback endpoint that belongs to the current default output."""
        api = self.p.get_host_api_info_by_type(pyaudio.paWASAPI)
        out = self.p.get_device_info_by_index(api["defaultOutputDevice"])
        if out.get("isLoopbackDevice"):
            return out
        for lb in self.p.get_loopback_device_info_generator():
            if out["name"] in lb["name"]:
                return lb
        raise RuntimeError(
            f"no loopback endpoint for default output {out['name']!r}. "
            "Windows exposes one per output device; if this persists, check that "
            "the device is not exclusive-mode locked by another application.")

    def _band_edges(self):
        return _band_edges(self.chunk, self.rate, self.LO, self.HI, self.BANDS)

    def _cb(self, data, frames, time_info, status):
        a = np.frombuffer(data, np.float32)
        if self.channels > 1:
            a = a.reshape(-1, self.channels).mean(axis=1)     # downmix
        if a.size >= self.chunk:
            self._buf = a[-self.chunk:].copy()
        return (None, pyaudio.paContinue)

    def push(self, eng):
        return _push(self, eng)

    def pcm(self):
        return _pcm(self)

    def close(self):
        try:
            self.stream.stop_stream(); self.stream.close()
        finally:
            self.p.terminate()


# --- the analyser, shared -------------------------------------------------------
def _band_edges(chunk, rate, LO, HI, BANDS):
    """Log-spaced, and forced strictly increasing.

    A log spacing packs the low bands close together, and down there the bins
    are wider than the bands are: at 48 kHz with a 1024 chunk the first two
    edges both landed on bin 1, so bands 0 and 1 read identical values and the
    bottom of the spectrum was a duplicate rather than a reading. Nudging each
    edge past the last costs a little accuracy in band centres and buys every
    band its own data.
    """
    n = chunk // 2 + 1
    e, prev = [], -1
    for i in range(BANDS + 1):
        f = LO * (HI / LO) ** (i / BANDS)
        b = int(round(f / (rate / 2.0) * n))
        b = max(b, prev + 1)
        e.append(min(n - 1, b))
        prev = e[-1]
    return e


def _pcm(self):
    """The newest 512 samples of the buffer folded 2:1 to 256, scaled by
    the batch peak with a floor so silence stays flat - what the device's
    PCM slot holds."""
    buf = self._buf
    if buf is None or len(buf) < 512:
        return np.zeros(256, np.float32)
    batch = buf[-512:]
    peak = float(np.abs(batch).max())
    scale = 127.0 / max(peak, 0.0625)
    return np.clip(batch[::2] * scale, -127, 127)


def _push(self, eng):
    """Fill the engine's FFT bins from the most recent audio, and detect onsets.

    Automatic gain, because a fixed multiplier cannot serve real music. This was
    a flat x40, and at that ordinary programme material clipped 18% of all band
    samples flat against 255. A clipped band is a CONSTANT, so anything watching
    for onsets sees nothing at all in exactly the bands carrying the music.
    Dropping it to x10 fixed the passage it was measured on and then clipped 16%
    on the next one, four minutes later - the dynamic range between a quiet
    verse and a chorus is far wider than any one number can straddle. So: track
    the loudest band with a fast attack and a slow release, and normalise
    against it. The loudest band lands near 200, leaving real headroom for a
    transient, and quiet passages come up instead of disappearing. gain stays
    as a trim on top.

    Onset by spectral flux on the low bands - the transient shape fx_lowBeat is
    looking for. The floor attacks fast and decays slowly, so sustained bass
    stops triggering while a kick over it still does.
    """
    spec = np.abs(np.fft.rfft(self._buf * self._win))
    raw = np.empty(self.BANDS, np.float32)
    for i in range(self.BANDS):
        a, b = self._edges[i], max(self._edges[i] + 1, self._edges[i + 1])
        raw[i] = spec[a:b].mean()
    peak = float(raw.max())
    if peak > self._agc:
        self._agc = peak
    else:
        self._agc += (peak - self._agc) * 0.010
    ref = max(self._agc, 0.35)
    scaled = np.clip(raw * (200.0 / ref) * self.gain, 0.0, 255.0)
    arr = eng.fft
    for i in range(self.BANDS):
        arr[i] = int(scaled[i])
    self.level = float(scaled.mean())
    low = (int(arr[0]) + int(arr[1]) + int(arr[2])) / 3.0
    if not self._primed:
        self._primed = True
        self._prev_low = low
        eng.audio(min(255.0, self.level * 1.6), 0)
        return 0
    flux = max(0.0, low - self._prev_low)
    self._prev_low = low
    self._floor = max(flux, self._floor * 0.92)
    hit = 1 if (flux > 8 and flux >= self._floor * 0.85 and low > 40) else 0
    eng.audio(min(255.0, self.level * 1.6), hit)
    return hit


class LiveInput:
    """Any input device, on any OS, through sounddevice (PortAudio)."""
    LO, HI, BANDS = LiveAudio.LO, LiveAudio.HI, LiveAudio.BANDS

    def __init__(self, gain=3.0, chunk=2048, device=None):
        if sd is None:
            raise RuntimeError("sounddevice is not installed:  pip install sounddevice")
        self.gain = gain
        self.chunk = chunk
        if device is None:
            device = sd.default.device[0]
        info = sd.query_devices(device)
        self.name = info["name"]
        self.rate = int(info.get("default_samplerate") or 48000)
        self.channels = max(1, min(2, int(info.get("max_input_channels") or 1)))
        self._buf = np.zeros(chunk, np.float32)
        self._win = np.hanning(chunk).astype(np.float32)
        self._edges = _band_edges(chunk, self.rate, self.LO, self.HI, self.BANDS)
        self._prev_low = 0.0
        self._floor = 0.0
        self._primed = False
        self._agc = 1.0
        self.level = 0.0
        self.stream = sd.InputStream(device=device, channels=self.channels,
                                     samplerate=self.rate, blocksize=chunk,
                                     dtype="float32", callback=self._cb)
        self.stream.start()

    def _cb(self, indata, frames, time_info, status):
        a = indata.mean(axis=1) if indata.ndim > 1 and indata.shape[1] > 1 else indata.reshape(-1)
        if a.size >= self.chunk:
            self._buf = a[-self.chunk:].copy()

    def push(self, eng):
        return _push(self, eng)

    def pcm(self):
        return _pcm(self)

    def close(self):
        try:
            self.stream.stop(); self.stream.close()
        except Exception:
            pass


class FileAudio:
    """A WAV file through the same analyser as the live sources, at real
    time and looping: the same passage every run, so a beat response can be
    judged twice and compared. 8 / 16 / 24 / 32-bit PCM, any rate."""
    LO, HI, BANDS = LiveAudio.LO, LiveAudio.HI, LiveAudio.BANDS

    def __init__(self, path, gain=3.0, chunk=2048):
        import wave
        with wave.open(path, "rb") as w:
            self.rate = w.getframerate()
            ch, sw, n = w.getnchannels(), w.getsampwidth(), w.getnframes()
            raw = w.readframes(n)
        if sw == 1:
            a = (np.frombuffer(raw, np.uint8).astype(np.float32) - 128.0) / 128.0
        elif sw == 2:
            a = np.frombuffer(raw, np.int16).astype(np.float32) / 32768.0
        elif sw == 3:
            b = np.frombuffer(raw, np.uint8).reshape(-1, 3).astype(np.int32)
            a = ((b[:, 0] | (b[:, 1] << 8) | (b[:, 2] << 16)) ^ 0x800000) - 0x800000
            a = a.astype(np.float32) / 8388608.0
        else:
            a = np.frombuffer(raw, np.int32).astype(np.float32) / 2147483648.0
        if ch > 1:
            a = a.reshape(-1, ch).mean(axis=1)
        self.samples = np.ascontiguousarray(a, dtype=np.float32)
        self.name = os.path.basename(path)
        self.seconds = len(self.samples) / float(self.rate)
        self.gain = gain
        self.chunk = chunk
        self._buf = np.zeros(chunk, np.float32)
        self._win = np.hanning(chunk).astype(np.float32)
        self._edges = _band_edges(chunk, self.rate, self.LO, self.HI, self.BANDS)
        self._prev_low = 0.0
        self._floor = 0.0
        self._primed = False
        self._agc = 1.0
        self.level = 0.0
        self.t0 = time.perf_counter()

    @property
    def position(self):
        return (time.perf_counter() - self.t0) % max(0.01, self.seconds)

    def push(self, eng):
        n = len(self.samples)
        if n < self.chunk:
            return 0
        end = int(self.position * self.rate) % n
        if end >= self.chunk:
            self._buf = self.samples[end - self.chunk:end]
        else:
            self._buf = np.concatenate([self.samples[n - (self.chunk - end):], self.samples[:end]])
        return _push(self, eng)

    def pcm(self):
        return _pcm(self)

    def close(self):
        pass


def list_inputs():
    """[(index, name)] of devices that can capture, for a picker."""
    if sd is None:
        return []
    out = []
    for i, d in enumerate(sd.query_devices()):
        if d.get("max_input_channels", 0) > 0:
            out.append((i, d["name"]))
    return out


def open_live(gain=3.0, device=None):
    """Loopback of what is playing where the OS offers it, else an input.

    Windows with pyaudiowpatch: the default output's loopback. Everything
    else, or a named device: sounddevice. On Linux pick the "Monitor of ..."
    device to hear what is playing; on macOS install BlackHole and route
    through it - the OS has no loopback of its own.
    """
    if device is None and sys.platform.startswith("win") and pyaudio is not None:
        try:
            return LiveAudio(gain=gain)
        except Exception:
            pass                     # fall through to an input device
    return LiveInput(gain=gain, device=device)
