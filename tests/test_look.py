"""The 3-D view's look (native/look.py) without the window: a preset with
values moved over it, the curve (black stays black, white near white, in
order), the glowing texture (its size, the studio look's squares exactly,
a lit LED brighter at its middle than its rim, light reaching an unlit
neighbour), the layers' shapes and strengths, and a picture finished - the
studio look untouched. Run with  python tests/test_look.py  or pytest.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import numpy as np                                      # noqa: E402
from native import look                                 # noqa: E402


def test_a_preset_with_values_moved_over_it():
    assert look.current({}) == look.PRESETS["studio"] and not look.active(look.current({}))
    lk = look.current({"look": {"preset": "cinematic", "grain": 0.9, "spill": "junk"}})
    assert lk["grain"] == 0.9 and lk["spill"] == look.PRESETS["cinematic"]["spill"] and look.active(lk)
    assert look.current({"look": {"preset": "nonesuch"}}) == look.PRESETS["studio"]
    assert set(look.PRESETS) == set(look.PRESET_WORDS) and all(set(p) == set(look.KEYS) for p in look.PRESETS.values())


def test_the_curve():
    img = np.arange(256, dtype=np.uint8).reshape(16, 16, 1).repeat(3, 2)
    assert look.tone(img, look.PRESETS["studio"]) is img                  # nothing to do: the same array
    for name in ("cinematic", "night"):
        out = look.tone(img, look.PRESETS[name])[..., 0].ravel().astype(int)
        assert out[0] == 0 and out[-1] >= 240 and all(np.diff(out) >= 0), (name, out[[0, 64, 128, 255]])
    lifted = look.tone(img, dict(look.DEFAULTS, filmic=1.0))[..., 0].ravel()
    assert lifted[64] > 64                                                # the film's toe lifts the darks a little


def test_the_glowing_texture():
    net = np.zeros((48, 48, 3), np.uint8)
    net[20, 20] = (255, 120, 0)
    flat = look.led_texture(net, 4, look.PRESETS["studio"])
    assert np.array_equal(flat, net.repeat(4, 0).repeat(4, 1))           # the studio look: squares, as ever
    tex = look.led_texture(net, 4, look.PRESETS["glow"])
    assert tex.shape == (192, 192, 3) and tex.dtype == np.uint8
    block = tex[80:84, 80:84].astype(int).sum(axis=2)
    assert block[1:3, 1:3].min() > block[0, 0]                           # brighter in the middle than at the rim
    assert tex[84:88, 80:84].astype(int).sum() > tex[150:154, 150:154].astype(int).sum()   # its light on a neighbour
    assert tex[150, 150].max() > 0                                        # the faint board where all is off


def test_the_layers():
    lk = look.PRESETS["night"]
    mean, frac = look.mean_light(np.array([[255, 0, 0], [0, 0, 255], [0, 0, 0], [0, 0, 0]], np.uint8))
    assert np.allclose(mean, (0.5, 0, 0.5)) and frac == 0.5
    sp = look.spill_rgba(mean, frac, lk)
    assert sp.shape == (48, 48, 4) and sp[24, 24, 3] > sp[0, 0, 3] >= 0
    v = look.vignette_rgba(lk)
    assert v[32, 32, 3] == 0 and v[0, 0, 3] > 0.4
    g = look.grain_rgba(lk, 64, np.random.default_rng(1))
    assert g.shape == (64, 64, 4) and 0 < g[..., 3].mean() < 0.2
    assert look.vignette_rgba(dict(lk, vignette=0.0))[0, 0, 3] == 0


def test_a_picture_finished():
    img = np.zeros((200, 200, 3), np.uint8)
    img[80:120, 80:120] = (255, 255, 200)
    assert look.finish(img, look.PRESETS["studio"]) is img
    light = look.mean_light(img)
    for name in ("glow", "cinematic", "night"):
        out = look.finish(img, look.PRESETS[name], 3, light)
        assert out.shape == img.shape and out.dtype == np.uint8
    out = look.finish(img, look.PRESETS["night"], 3, light)
    assert out[70, 100].sum() > 30                                        # the bloom and spill round the bright square
    assert out[2, 2].sum() < out[70, 100].sum()                           # the vignette's corner darker



def test_the_diffuser():
    net = np.zeros((48, 48, 3), np.uint8)
    net[24, 24] = (255, 255, 255)                                         # one LED on the top face (block 1, 1)
    net[16, 16] = (0, 0, 0)
    lk = dict(look.DEFAULTS, diffuse=0.8)
    d = look.diffuse(net, 16, lk)
    assert d[24, 24].max() < 255 and d[25, 24].max() > 0                  # its light spread to its neighbours
    assert d[24, 15].max() == 0                                           # but not across the face's edge
    assert look.diffuse(net, 16, look.DEFAULTS) is net                    # no diffuser: the net itself
    tex = look.led_texture(net, 4, lk, B=16)
    assert tex.shape == (192, 192, 3) and tex[96:100, 96:100].std() < 40  # smooth: no dot to see


def test_the_reflection():
    from native import render
    net = np.full((48, 48, 3), 200, np.uint8)
    plain = render.render(net, 16, 200, 0.7, 0.35, 5.0)
    mirror = render.render(net, 16, 200, 0.7, 0.35, 5.0, reflect=0.8)
    below = slice(170, 200)
    assert mirror[below].astype(int).sum() > plain[below].astype(int).sum()   # the cube's light in the floor
    assert np.array_equal(mirror[:60], plain[:60])                            # above, as it was
    up = render.render(net, 16, 200, 0.7, -0.4, 5.0, reflect=0.8)             # from below the floor: none
    assert np.array_equal(up, render.render(net, 16, 200, 0.7, -0.4, 5.0))
    assert render.reflection_weight(np.array([0.0, 1.0, 2.0, 3.0])).tolist() == [1.0, 0.25, 0.0, 0.0]


def test_any_shape_has_the_look():
    """Parity: a ring of LEDs gets the diffuser by distance, glowing sprites and a reflection, as the cube does."""
    from native import render
    t = np.linspace(0, 2 * np.pi, 60, endpoint=False)
    pos = np.stack([np.cos(t) * 10, np.sin(t) * 10, np.zeros_like(t)], 1).astype(np.float32)
    rgb = np.zeros((60, 3), np.uint8)
    rgb[0] = (255, 200, 100)
    d = look.diffuse_points(pos, rgb, dict(look.DEFAULTS, diffuse=0.8))
    assert d[0].max() < 255 and d[1].max() > 0 and d[59].max() > 0 and d[30].max() == 0   # to its neighbours only
    assert look.diffuse_points(pos, rgb, look.DEFAULTS) is rgb
    idx, dist, spacing = look.neighbours(pos)
    assert idx[5, 0] == 5 and set(idx[5, 1:3].tolist()) == {4, 6} and abs(spacing - 2 * 10 * np.sin(np.pi / 60)) < 1e-3
    lit = np.full((60, 3), 200, np.uint8)
    plain = render.render_points(pos, lit, 200, 0.7, 0.35, 5.0)
    glow = render.render_points(pos, lit, 200, 0.7, 0.35, 5.0, lk=look.PRESETS["glow"])
    assert (glow.max(axis=2) > 20).sum() > (plain.max(axis=2) > 20).sum()          # each LED's light reaches further
    flat = render.render_points(pos, lit, 200, 0.7, 0.35, 5.0, lk=dict(look.DEFAULTS, reflect=0.0))
    tall = np.concatenate([pos, pos + (0, 0, 8)]).astype(np.float32)
    lit2 = np.full((120, 3), 200, np.uint8)
    a = render.render_points(tall, lit2, 200, 0.7, 0.35, 5.0, floor=False)
    b = render.render_points(tall, lit2, 200, 0.7, 0.35, 5.0, floor=False, lk=dict(look.DEFAULTS, reflect=0.9))
    assert b.astype(int).sum() > a.astype(int).sum() and np.array_equal(flat, plain)  # the reflection adds light
    m = look.sprite_mask(look.PRESETS["glow"])
    assert m.shape == (look.SPRITE_K, look.SPRITE_K) and m[4, 4] == m.max() and m[0, 0] < m[4, 4]

if __name__ == "__main__":
    import inspect
    bad = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and inspect.isfunction(fn):
            try:
                fn(); print("ok  ", name)
            except Exception as ex:
                bad += 1; print("FAIL", name, repr(ex)[:3000])
    sys.exit(1 if bad else 0)
