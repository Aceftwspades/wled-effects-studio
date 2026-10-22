"""The show's sections found in its audio (native/showanalysis.py) and a show planned on them (native/autoshow.py):
a synthetic song - a quiet intro, a verse, a build rising, a loud drop, a quiet outro - cut where it changes, on its
bars, each part named by its loudness; steps laid on the sections, the loud effects on the drop, a cut into it, the
build ramped up and the outro faded out.
Run with  python tests/test_autoshow.py  (or pytest).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np                                             # noqa: E402

from native import autoshow, showanalysis as A                 # noqa: E402

R = A.RATE


def _song():
    rng = np.random.default_rng(1)

    def part(sec, level, tone):
        t = np.arange(int(sec * R)) / R
        return rng.standard_normal(len(t)) * level * 0.3 + np.sin(2 * np.pi * tone * t) * level
    build = part(16, 0.3, 330) * np.linspace(0.5, 1.6, int(16 * R))
    return np.concatenate([part(24, 0.08, 220), part(32, 0.3, 330), build, part(32, 0.9, 110),
                           part(16, 0.06, 220)]).astype(np.float32)


def test_the_sections_where_the_song_changes_on_its_bars():
    secs = A.sections(_song(), R, bar=2.0)
    starts = [s["at"] for s in secs]
    assert starts == [0.0, 24.0, 56.0, 72.0, 104.0], starts
    assert all(abs(s["at"] / 2.0 - round(s["at"] / 2.0)) < 1e-6 for s in secs)          # on the bars
    assert [s["kind"] for s in secs] == ["intro", "verse", "build", "drop", "outro"], [s["kind"] for s in secs]
    assert abs(sum(s["len"] for s in secs) - 120.0) < 0.6


def test_too_little_to_go_on_is_one_section_or_none():
    assert A.sections(np.zeros(R, np.float32), R) == []
    one = A.sections(np.random.default_rng(2).standard_normal(R * 20).astype(np.float32) * 0.2, R)
    assert len(one) <= 2


def test_a_show_planned_on_the_sections():
    secs = A.sections(_song(), R, bar=2.0)
    scores = {f"fx{k}": k / 9.0 for k in range(10)}                                      # fx9 the most energetic
    pl = autoshow.plan(secs, 2.0, scores, seed=3, bars_a_step=4)
    assert abs(sum(p["dur"] for p in pl) - sum(s["len"] for s in secs)) < 1e-6
    by = lambda kind: [p for p in pl if secs[p["section"]]["kind"] == kind]              # noqa: E731
    drop, intro = by("drop"), by("intro")
    assert np.mean([scores[p["effect"]] for p in drop]) > np.mean([scores[p["effect"]] for p in intro]) + 0.4
    assert drop[0]["trans"] == 0.0                                                       # a cut into the drop
    assert all("ix" in p["ramps"] for p in by("build"))                                  # the build rising
    assert by("outro")[-1]["ramps"]["bri"]["end"] == 0                                   # the outro faded out
    for a, b in zip(pl, pl[1:]):
        assert a["effect"] != b["effect"]                                                # no effect twice running
    assert autoshow.plan(secs, 2.0, scores, seed=3) == pl                                # the same take again
    assert autoshow.plan(secs, 2.0, scores, seed=4) != pl                                # another take


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
