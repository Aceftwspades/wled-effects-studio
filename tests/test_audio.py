"""The studio's audio analysis without the app: the pitch classes (audio._chroma, the twin of the
fork's cfxChromaCapture) on chords and bass notes at the rates a source runs at, the PCM slot
over the device's span, and the synth's stand-in chords. Run with  python tests/test_audio.py
(or pytest).
"""
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from native import audio as A                   # noqa: E402

NAMES = "C C# D D# E F F# G G# A A# B".split()


def _tones(rate, notes, seconds=0.4, harmonics=5, cents=0.0):
    """Notes (Hz, amplitude) with falling harmonics, as an instrument's, float32 at rate."""
    t = np.arange(int(seconds * rate)) / rate
    x = np.zeros_like(t)
    for f, a in notes:
        f *= 2 ** (cents / 1200.0)
        for h in range(1, harmonics + 1):
            if f * h < rate / 2:
                x += a * np.sin(2 * np.pi * f * h * t) / h
    return (0.2 * x / max(1e-9, np.abs(x).max())).astype(np.float32)


def top(pc, k=3):
    return [NAMES[i] for i in np.argsort(-pc)[:k]]


def test_a_chord_reads_as_its_notes_at_every_rate():
    """A C major triad voiced low (C3 E3 G3) and a C7 higher up read as their notes, the rest
    small, at the rates a source runs at - the device's 11025 among them."""
    for rate in (11025, 44100, 48000):
        pc, level = A._chroma(_tones(rate, [(130.81, 1.0), (164.81, 0.8), (196.0, 0.7)]), rate)
        assert sorted(top(pc)) == ["C", "E", "G"], (rate, top(pc, 5))
        assert pc.max() == 1.0 and level > 0.0
        assert all(pc[i] < 0.35 for i in range(12) if NAMES[i] not in ("C", "E", "G", "B", "D")), (rate, pc.round(2))
        pc, _ = A._chroma(_tones(rate, [(261.63, 1.0), (329.63, 0.8), (392.0, 0.7), (466.16, 0.6)]), rate)
        assert sorted(top(pc, 4)) == ["A#", "C", "E", "G"], (rate, top(pc, 5))


def test_a_bass_note_reads_as_its_class():
    """A bass note below the bank's C3 (A2, E2) still reads as its class, through its harmonics;
    a note 20 cents sharp still reads as itself."""
    rate = 48000
    for f, name in ((110.0, "A"), (82.41, "E")):
        pc, _ = A._chroma(_tones(rate, [(f, 1.0)]), rate)
        assert top(pc, 1) == [name], (name, top(pc, 4))
    pc, _ = A._chroma(_tones(rate, [(261.63, 1.0), (329.63, 0.8), (392.0, 0.7)], cents=20), rate)
    assert sorted(top(pc)) == ["C", "E", "G"], top(pc, 5)


def test_silence_is_no_note():
    for rate in (11025, 48000):
        pc, level = A._chroma(np.zeros(int(0.3 * rate), np.float32), rate)
        assert pc.max() == 0.0 and level == 0.0


def test_the_pcm_spans_the_devices_batch():
    """The PCM slot holds the device's last batch: 512 samples at 22050 Hz, 23.2 ms - taken as
    that span of a 48 kHz source (it took 512 of its samples, 10.7 ms). A 1 kHz sine crosses
    zero ~46 times in it; its peak is scaled to 127."""
    class Src:
        rate = 48000
        _buf = np.zeros(2048, np.float32)
    s = Src()
    t = np.arange(20000) / s.rate
    s._hist = (0.5 * np.sin(2 * np.pi * 1000.0 * t)).astype(np.float32)
    s._buf = s._hist[-2048:]
    p = A._pcm(s)
    assert p.shape == (256,)
    crossings = int(np.sum(np.signbit(p[:-1]) != np.signbit(p[1:])))
    assert 44 <= crossings <= 48, crossings
    assert 120 <= np.abs(p).max() <= 127


def test_the_synth_plays_a_chord_a_bar():
    """The synth's stand-in: I - vi - IV - V in C, a chord a bar of its beats, on its own clock."""
    from native.synth import Synth

    class Eng:
        def __init__(self):
            self.fft = np.zeros(16, np.uint8)
            self.sim_ms = 0

        def audio(self, v, p):
            pass

        def audio_peak(self):
            pass
    syn, eng = Synth(bpm=120), Eng()
    got = []
    for bar in range(4):
        eng.sim_ms = bar * 2000 + 500                      # 120 bpm: a bar is 2 s
        syn.push(eng)
        pc, _ = syn.chroma()
        got.append(tuple(sorted(top(pc))))
    assert got == [("C", "E", "G"), ("A", "C", "E"), ("A", "C", "F"), ("B", "D", "G")], got
    syn.muted = True
    assert syn.chroma()[0].max() == 0.0


if __name__ == "__main__":                        # without pytest: every test_ function, in order
    import inspect
    bad = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and inspect.isfunction(fn):
            try:
                fn(); print("ok  ", name)
            except Exception as e:
                bad += 1; print("FAIL", name, repr(e))
    sys.exit(1 if bad else 0)
