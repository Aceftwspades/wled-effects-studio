"""The Sequence's audio (native/showaudio.py) without the speakers: a clip's fades - a crossfade where two overlap
on a track by themselves, as set by hand otherwise; the mix - each clip at its time, from its trimmed start in its
file, by its gain, a crossfade keeping its loudness, a muted track silent; a file decoded to stereo at the mixer's
rate with its wave's picture; the analyser's source hearing the mix where the show is.
Run with  python tests/test_showaudio.py  (or pytest).
"""
import os
import sys
import tempfile
import wave

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np                                             # noqa: E402

from native import showaudio as A                              # noqa: E402

R = A.RATE


def _snd(seconds, value=0.5):
    """A Sound of a constant level (both channels), as int16."""
    return A.Sound(np.full((int(seconds * R), 2), int(value * 32767), np.int16), "test")


def test_overlaps_crossfade_by_themselves():
    tr = {"clips": [{"at": 0.0, "len": 10.0}, {"at": 8.0, "len": 10.0}, {"at": 30.0, "len": 5.0}]}
    f = A.fades(tr)
    assert f[0] == (0.0, 2.0) and f[1] == (2.0, 0.0) and f[2] == (0.0, 0.0)


def test_a_fade_set_by_hand_is_kept_and_kept_inside_the_clip():
    tr = {"clips": [{"at": 0.0, "len": 10.0, "fade_out": 0.5}, {"at": 8.0, "len": 10.0, "fade_in": 4.0}]}
    f = A.fades(tr)
    assert f[0] == (0.0, 0.5) and f[1] == (4.0, 0.0)
    f = A.fades({"clips": [{"at": 0.0, "len": 4.0, "fade_in": 3.0, "fade_out": 3.0}]})
    assert abs(sum(f[0]) - 4.0) < 1e-9 and abs(f[0][0] - 2.0) < 1e-9          # they meet in the middle


def test_a_clip_plays_at_its_time_from_its_trimmed_start():
    s = A.Sound(np.repeat((np.arange(5 * R) % 30000).astype(np.int16)[:, None], 2, 1), "ramp")
    res = [(s, 2.0, 1.0, 2.0, 1.0, 0.0, 0.0)]                     # at 2 s, 1 s into the file, 2 s long
    out = A.render(res, 0.0, 5 * R)
    assert np.all(out[:2 * R - 1] == 0) and np.all(out[4 * R + 1:] == 0)    # silent before and after it
    k = 3 * R                                                     # 1 s into the clip: 2 s into the file
    assert abs(out[k, 0] * 32768 - (2 * R) % 30000) < 2
    part = A.render(res, 2.5, 100)                                # a block from the middle: the same samples
    assert np.allclose(part, out[int(2.5 * R):int(2.5 * R) + 100])


def test_gain_fades_and_a_crossfade_keep_the_loudness():
    a, b = _snd(10), _snd(10)
    f = A.fades({"clips": [{"at": 0.0, "len": 6.0}, {"at": 4.0, "len": 6.0}]})
    res = [(a, 0.0, 0.0, 6.0, 1.0) + f[0], (b, 4.0, 0.0, 6.0, 1.0) + f[1]]
    out = A.render(res, 0.0, 10 * R)[:, 0]
    level = int(0.5 * 32767) / 32768                             # the clip's samples, as whole int16s
    power = out[int(4 * R):int(6 * R)] ** 2                      # equal power: the two together as loud as one
    # sin^2 + cos^2: the sum of the two clips' powers is constant; the summed amplitude rises at most by sqrt 2
    assert out[int(1 * R)] == np.float32(level) and abs(out[int(5 * R)] - level * 2 ** 0.5) < 1e-3
    assert power.max() <= (level * 2 ** 0.5) ** 2 + 1e-4
    half = A.render([(a, 0.0, 0.0, 6.0, 0.5, 0.0, 0.0)], 1.0, 10)
    assert np.allclose(half, level * 0.5)


def test_a_muted_track_and_a_missing_file_are_left_out():
    S = {"tracks": [{"mute": True, "clips": [{"file": "x.wav", "at": 0, "len": 1}]},
                    {"clips": [{"file": "not_there.wav", "at": 0, "len": 1}]}]}
    assert A.resolve(S, tempfile.gettempdir()) == []
    assert A.length(S) == 1.0


def _wav(path, seconds, rate, ch, freq=440.0):
    t = np.arange(int(seconds * rate)) / rate
    a = (np.sin(2 * np.pi * freq * t) * 16000).astype(np.int16)
    a = np.repeat(a[:, None], ch, 1)
    with wave.open(path, "wb") as w:
        w.setnchannels(ch); w.setsampwidth(2); w.setframerate(rate); w.writeframes(a.tobytes())


def test_a_file_decoded_at_the_mixer_s_rate_with_its_wave():
    d = tempfile.mkdtemp()
    p = os.path.join(d, "tone.wav")
    _wav(p, 2.0, 22050, 1)
    s = A.sound(p, wait=True)
    assert s is not None, A.error(p)
    assert s.data.shape[1] == 2 and abs(s.seconds - 2.0) < 0.01
    # a mono file is spread over both channels 3 dB down each (ffmpeg's pan law, as loud to the ear): 0.488 or 0.345
    assert len(s.peaks) == len(s.data) // A.PEAK and 0.3 < s.peaks.max() <= 0.5
    assert A.sound(p) is s                                        # cached
    assert A.sound(os.path.join(d, "none.wav")) is None and A.error(os.path.join(d, "none.wav"))


def test_the_effects_hear_the_mix_where_the_show_is():
    s = _snd(4, 0.25)
    res = [(s, 1.0, 0.0, 2.0, 1.0, 0.0, 0.0)]
    t = [0.5]
    src = A.ShowAudio(lambda: res, lambda: t[0])

    class Eng:
        fft = np.zeros(16, np.uint8)

        def audio(self, level, beat):
            self.level = level
    e = Eng()
    src.push(e)
    assert np.allclose(src._buf, 0)                              # before the clip: silence
    t[0] = 2.0
    src.push(e)
    assert np.allclose(src._buf, 0.25 * 32767 / 32768, atol=1e-4)   # in it: the clip
    assert len(src._hist) > src.chunk


if __name__ == "__main__":
    import inspect
    bad = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and inspect.isfunction(fn):
            try:
                fn(); print("ok  ", name)
            except Exception as e:
                bad += 1; print("FAIL", name, repr(e))
    sys.exit(1 if bad else 0)
