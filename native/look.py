"""How the 3-D view is lit: the promo film's look (wled-studio-promo's
cine.py) as options of the live view - each LED a glowing dot, the colour
it throws into the room behind the shape, a filmic curve and an exposure,
a vignette, film grain - and, in the pictures the view makes (a screenshot,
a GIF, a video), bloom.

The live view draws on the GPU with no shaders (gpucube.py: textured
quads), so each part is put where it can go: the glow into the cube's
texture, the curve into the colours as they are uploaded, the spill as a
soft pool drawn under the LEDs, the vignette and the grain as layers drawn
over them. A picture is made in numpy (render.py), where the same parts
and a real bloom are affordable.

A look is a dict of strengths; prefs["look"] keeps the preset's name and
any value moved from it:

    lk = look.current(prefs)              # {"glow": 0.7, "spill": 0.5, ...}
    tex = look.led_texture(net, 4, lk)    # the cube's texture, glowing
    img = look.finish(img, lk, seed)      # a picture: spill, bloom, curve, vignette, grain
"""
import numpy as np

# the strengths, 0 for off; exposure a factor
KEYS = ("glow", "diffuse", "reflect", "spill", "bloom", "vignette", "grain", "exposure", "filmic")
DEFAULTS = {"glow": 0.0, "diffuse": 0.0, "reflect": 0.0, "spill": 0.0, "bloom": 0.0, "vignette": 0.0, "grain": 0.0, "exposure": 1.0, "filmic": 0.0}
PRESETS = {
    "studio":    dict(DEFAULTS),                                                  # the view as it always was
    "glow":      dict(DEFAULTS, glow=0.6, bloom=0.3),
    "cinematic": dict(DEFAULTS, glow=0.7, reflect=0.35, spill=0.5, bloom=0.5, vignette=0.45, grain=0.25, exposure=1.1, filmic=1.0),
    "diffused":  dict(DEFAULTS, diffuse=0.45, reflect=0.3, spill=0.45, bloom=0.3, vignette=0.3, filmic=1.0),
    "night":     dict(DEFAULTS, glow=1.0, reflect=0.5, spill=0.8, bloom=0.6, vignette=0.6, grain=0.15, exposure=1.15, filmic=1.0),
}
PRESET_WORDS = {"studio": "Studio", "glow": "Glow", "cinematic": "Cinematic", "diffused": "Diffused", "night": "Night"}
RANGES = {"glow": (0.0, 1.0), "diffuse": (0.0, 1.0), "reflect": (0.0, 1.0), "spill": (0.0, 1.0), "bloom": (0.0, 1.0), "vignette": (0.0, 1.0), "grain": (0.0, 1.0),
          "exposure": (0.5, 2.0), "filmic": (0.0, 1.0)}
WORDS = {"glow": ("glow", "each LED a bright dot with a soft halo, as a lit LED looks to a camera"),
         "diffuse": ("diffuser", "the LEDs as behind frosted acrylic: their light spread to their neighbours (a cube's within each face), the further the diffuser the more"),
         "reflect": ("reflection", "the floor a mirror: the shape reflected in it, fading with depth"),
         "spill": ("spill", "the LEDs' colour thrown into the room behind them"),
         "bloom": ("bloom", "light past white spreading round it - in screenshots, GIFs and videos (the live view has the glow)"),
         "vignette": ("vignette", "the corners darkened, as a lens does"),
         "grain": ("grain", "film grain, moving"),
         "exposure": ("exposure", "brighter or darker, before the curve"),
         "filmic": ("filmic", "a film's curve: highlights roll off instead of clipping, darks lift a little")}


def current(prefs):
    """The look in force: its preset's values with the ones moved over them."""
    st = prefs.get("look") or {}
    base = dict(PRESETS.get(st.get("preset", "studio"), PRESETS["studio"]))
    for k in KEYS:
        if k in st:
            try:
                base[k] = float(st[k])
            except (TypeError, ValueError):
                pass
    return base


def active(lk):
    """Anything to do at all (the studio look costs nothing)."""
    return any(abs(lk.get(k, DEFAULTS[k]) - DEFAULTS[k]) > 1e-6 for k in KEYS)


# --- the curve ----------------------------------------------------------------------------------
_TONE = {}


def _hable(x):
    """John Hable's filmic curve (Uncharted 2): a toe, a straight middle, a shoulder."""
    A, B, C, D, E, F = 0.15, 0.50, 0.10, 0.20, 0.02, 0.30
    return (x * (A * x + C * B) + D * E) / (x * (A * x + B) + D * F) - E / F


def _tone_lut(exposure, filmic):
    """uint8 -> uint8: exposure, then a blend toward a filmic curve
    (Hable-like: highlights roll off, a lift in the darks), sRGB in and out."""
    key = (round(exposure, 3), round(filmic, 3))
    lut = _TONE.get(key)
    if lut is None:
        x = np.arange(256, dtype=np.float32) / 255.0
        lin = (x ** 2.2) * exposure
        straight = np.clip(lin, 0, 1) ** (1 / 2.2)
        film = np.clip(_hable(lin * 4.0) / _hable(4.6), 0, 1) ** (1 / 2.2)   # white held just under white
        out = straight + (film - straight) * filmic
        lut = _TONE[key] = np.clip(out * 255 + 0.5, 0, 255).astype(np.uint8)
    return lut


def tone(img, lk):
    """A picture's (or the LEDs') colours through the exposure and the curve."""
    if abs(lk.get("exposure", 1.0) - 1.0) < 1e-6 and lk.get("filmic", 0.0) <= 0.0:
        return img
    return np.take(_tone_lut(float(lk.get("exposure", 1.0)), float(lk.get("filmic", 0.0))), img)


# --- the glow, in the cube's texture -------------------------------------------------------------
_CELLS = {}


def _cell(k, glow):
    """A k x k block's weights: a bright disc in the middle of the LED's
    pitch, soft at its rim, the rest of the block dark - the stronger the
    glow, the more of it the disc fills its light."""
    key = (k, round(glow, 3))
    c = _CELLS.get(key)
    if c is None:
        u = (np.arange(k) + 0.5) / k - 0.5
        r = np.sqrt(u[:, None] ** 2 + u[None, :] ** 2) * 2.0           # 0 at the middle, 1 at the block's side
        disc = np.clip((0.95 - r) / 0.35, 0, 1)
        c = _CELLS[key] = (0.35 + 0.65 * disc) * (1.0 + 0.4 * glow)
    return c


def _blur(a, passes=2):
    """A soft blur of a small (h, w, 3) float image: box passes of 3, which
    approach a gaussian - the halo, an LED's light reaching its neighbours."""
    out = a
    for _ in range(passes):
        p = np.pad(out, ((1, 1), (1, 1), (0, 0)), mode="edge")
        out = (p[:-2, 1:-1] + p[1:-1, 1:-1] + p[2:, 1:-1]) / 3.0
        p = np.pad(out, ((1, 1), (1, 1), (0, 0)), mode="edge")
        out = (p[1:-1, :-2] + p[1:-1, 1:-1] + p[1:-1, 2:]) / 3.0
    return out


def diffuse(net, B, lk):
    """The net as seen through a diffuser: each B x B face blurred on its
    own (light does not cross a cube's edge through acrylic), the further
    the diffuser the wider - box passes, each a third of an LED's reach."""
    d = float(lk.get("diffuse", 0.0))
    if d <= 0 or not B:
        return net
    passes = int(round(1 + d * max(1.5, B / 8.0)))
    out = net.copy()
    h, w = net.shape[:2]
    for by in range(0, h - B + 1, B):
        for bx in range(0, w - B + 1, B):
            blk = net[by:by + B, bx:bx + B]
            if blk.max() == 0:
                continue                                  # a corner of the net: no LEDs
            out[by:by + B, bx:bx + B] = np.clip(_blur(blk.astype(np.float32), passes), 0, 255).astype(np.uint8)
    return out


def led_texture(net, k, lk, unlit=None, B=None):
    """The net at k times its size, each lit LED a glowing dot - a disc
    and a halo reaching the neighbours - over a faint board, so the shape
    of the faces still reads where the LEDs are off. Through a diffuser
    (B: a face's side) the light is spread and the dots fade into it. With
    neither: the net as squares (and `unlit`'s dim dots, as render.dotted
    draws them)."""
    from native.render import dotted
    g = float(lk.get("glow", 0.0))
    d = float(lk.get("diffuse", 0.0)) if B else 0.0
    if d > 0:
        net = diffuse(net, B, lk)
    if g <= 0.0:
        if d > 0:                                         # the diffuser: smooth, no dots to see - and no steps
            from PIL import Image
            h, w = net.shape[:2]
            return np.asarray(Image.fromarray(net).resize((w * k, h * k), Image.BILINEAR))
        return dotted(net, k, unlit) if unlit is not None else net.repeat(k, 0).repeat(k, 1)
    f = net.astype(np.float32)
    cell = _cell(k, g) * (1.0 - d) + d                    # a diffuser washes the dots out
    h, w = net.shape[:2]
    disc = f.repeat(k, 0).repeat(k, 1) * np.tile(cell, (h, w))[..., None]
    halo = _blur(f).repeat(k, 0).repeat(k, 1) * (1.1 * g)
    board = np.array(unlit if unlit is not None else (9, 10, 12), np.float32) * (0.5 if unlit is not None else 1.0)
    out = np.maximum(disc + halo, board)
    return np.clip(out, 0, 255).astype(np.uint8)


# --- any shape: an LED a sprite, a diffuser by distance ------------------------------------------
SPRITE_K = 8                 # a point LED's sprite cell, texels a side


def sprite_grow(lk):
    """How much bigger than its bare square an LED's sprite is drawn: room for its halo, or its diffused light."""
    return 1.0 + 0.9 * float(lk.get("glow", 0.0)) + 1.0 * float(lk.get("diffuse", 0.0))


def sprite_mask(lk, k=SPRITE_K):
    """A point LED's light in its sprite (k x k, 0..1): a bright disc the
    size of the bare square in the middle, a halo out to the sprite's edge;
    through a diffuser the disc softens into the halo. The alpha a sprite
    is drawn with, and its colour's weight."""
    g, d = float(lk.get("glow", 0.0)), float(lk.get("diffuse", 0.0))
    grow = sprite_grow(lk)
    u = (np.arange(k) + 0.5) / k * 2 - 1
    r = np.sqrt(u[:, None] ** 2 + u[None, :] ** 2) * grow          # 1 at the bare square's edge
    disc = np.clip((1.15 - r) / 0.3, 0, 1)
    halo = np.exp(-(r * r) / max(0.2, 0.9 * grow)) * (0.45 * g + 0.6 * d)
    core = disc * (1.0 - 0.6 * d)
    return np.clip(np.maximum(core, halo) * np.clip((grow + 0.4 - r) / 0.4, 0, 1), 0, 1).astype(np.float32)


_NEIGH = {}


def neighbours(pos, k=12):
    """Each LED's nearest k others (itself first) and their distances, and
    the shape's LED spacing (the median nearest distance) - for the
    diffuser on any shape. Made once for a set of positions."""
    pos = np.asarray(pos, np.float32).reshape(-1, 3)
    key = (pos.shape, hash(pos.tobytes()))
    hit = _NEIGH.get(key)
    if hit is not None:
        return hit
    n = len(pos)
    P = np.where(np.isfinite(pos), pos, 1e9)                       # a NaN row: far from everything
    k = max(1, min(k, n))
    idx = np.zeros((n, k), np.int64)
    dist = np.zeros((n, k), np.float32)
    for a in range(0, n, 256):
        d2 = ((P[a:a + 256, None, :] - P[None, :, :]) ** 2).sum(axis=2)
        part = np.argpartition(d2, k - 1, axis=1)[:, :k]
        dd = np.take_along_axis(d2, part, axis=1)
        o = np.argsort(dd, axis=1)
        idx[a:a + 256] = np.take_along_axis(part, o, axis=1)
        dist[a:a + 256] = np.sqrt(np.take_along_axis(dd, o, axis=1))
    near = dist[:, 1] if k > 1 else np.ones(n, np.float32)
    spacing = float(np.median(near[np.isfinite(near) & (near < 1e8)])) if n > 1 else 1.0
    if len(_NEIGH) > 8:
        _NEIGH.clear()
    hit = _NEIGH[key] = (idx, dist, max(spacing, 1e-6))
    return hit


def diffuse_points(pos, rgb, lk):
    """The LEDs' colours through a diffuser on any shape: each one's light
    shared with its neighbours within a reach the diffuser's distance sets
    (a few LED spacings at the most), as frosted acrylic over them would."""
    d = float(lk.get("diffuse", 0.0))
    rgb = np.asarray(rgb)
    if d <= 0 or len(rgb) < 2:
        return rgb
    idx, dist, spacing = neighbours(pos)
    reach = spacing * (0.5 + 2.2 * d)
    w = np.exp(-(dist / reach) ** 2)
    w[dist > 1e8] = 0.0
    f = rgb.astype(np.float32)[idx]                                  # (n, k, 3)
    out = (f * w[..., None]).sum(axis=1) / np.maximum(w.sum(axis=1), 1e-6)[:, None]
    return np.clip(out, 0, 255).astype(np.uint8)


# --- the room and the lens, as layers of the live view (RGBA, 0..1) --------------------------------
_VIG = {}


def mean_light(rgb):
    """The LEDs' light, as the room would see it: the mean of the lit ones
    (0..1 each), and how much of the shape is lit."""
    a = np.asarray(rgb).reshape(-1, 3)
    lit = a.max(axis=1) >= 10
    if not lit.any():
        return np.zeros(3, np.float32), 0.0
    return a[lit].astype(np.float32).mean(axis=0) / 255.0, float(lit.mean())


def spill_rgba(mean, frac, lk, n=48):
    """The pool of light behind the shape: the LEDs' mean colour, strongest
    behind the middle and fading out, its alpha by how much is lit and the
    spill's strength - stretched to the view, where its smallness is a blur."""
    s = float(lk.get("spill", 0.0))
    u = (np.arange(n) + 0.5) / n * 2 - 1
    r2 = u[:, None] ** 2 + (u[None, :] * 1.15 + 0.12) ** 2           # a little low: the floor catches more
    fall = np.exp(-r2 / 0.6)
    col = np.clip(mean / max(1e-3, mean.max()) if mean.max() > 0 else mean, 0, 1)
    out = np.zeros((n, n, 4), np.float32)
    out[..., :3] = col
    out[..., 3] = fall * min(1.0, s * (0.35 + 0.9 * frac))
    return out


def vignette_rgba(lk, n=64):
    """The lens's darker corners: black, its alpha growing from the middle out."""
    v = float(lk.get("vignette", 0.0))
    key = (n, round(v, 3))
    out = _VIG.get(key)
    if out is None:
        u = (np.arange(n) + 0.5) / n * 2 - 1
        r = np.sqrt(u[:, None] ** 2 + u[None, :] ** 2) / np.sqrt(2)
        out = np.zeros((n, n, 4), np.float32)
        out[..., 3] = np.clip((r - 0.35) / 0.65, 0, 1) ** 1.6 * 0.85 * v
        _VIG[key] = out
    return out


def grain_rgba(lk, n, rng):
    """A frame's grain: grey specks, light and dark, their alpha the grain's
    strength - n square, drawn over the view at about two pixels a speck."""
    g = float(lk.get("grain", 0.0))
    noise = rng.standard_normal((n, n)).astype(np.float32)
    out = np.zeros((n, n, 4), np.float32)
    out[..., :3] = (noise > 0)[..., None].astype(np.float32)
    out[..., 3] = np.clip(np.abs(noise) * 0.11 * g, 0, 1)
    return out


# --- a picture (screenshot, GIF, video) ----------------------------------------------------------
def _resize(a, w, h):
    from PIL import Image
    return np.asarray(Image.fromarray(np.clip(a * 255, 0, 255).astype(np.uint8)).resize((w, h), Image.BILINEAR),
                      np.float32) / 255.0


_LAYERS = {}


def _layer(key, w, h, make):
    """A layer at a picture's size, made once (the spill's fall-off, the vignette)."""
    k = (key, w, h)
    if k not in _LAYERS:
        if len(_LAYERS) > 16:
            _LAYERS.clear()
        _LAYERS[k] = make().astype(np.float32)
    return _LAYERS[k]


def _spread(a, w, h):
    """A layer as the live view draws it: stretched a quarter past each side
    of the view (gpucube.Layers), the middle w x h of it."""
    from PIL import Image
    W, H = int(w * 1.5), int(h * 1.5)
    big = np.asarray(Image.fromarray(np.clip(a * 255, 0, 255).astype(np.uint8)).resize((W, H), Image.BILINEAR), np.float32) / 255.0
    x0, y0 = (W - w) // 2, (H - h) // 2
    return big[y0:y0 + h, x0:x0 + w]


def finish(img, lk, seed=None, light=None):
    """A picture of the view (uint8 h x w x 3) with the look: the spill
    under the shape (`light`: mean_light of its LEDs), bloom, the curve,
    the vignette and the grain. The studio look returns it as it was."""
    if not active(lk):
        return img
    from PIL import Image, ImageFilter
    h, w = img.shape[:2]
    spill = float(lk.get("spill", 0)) if light is not None else 0.0
    b = float(lk.get("bloom", 0.0))
    if spill > 0 or b > 0:                                     # light added: in float, once
        f = img.astype(np.float32)
        if spill > 0:
            mean, frac = light
            fall = _layer("fall", w, h, lambda: _spread(spill_rgba(np.ones(3, np.float32), 1.0, dict(lk, spill=1.0))[..., 3], w, h))
            col = (np.clip(mean / max(1e-3, float(mean.max())), 0, 1) if mean.max() > 0 else mean).astype(np.float32)
            a = fall * (255.0 * min(1.0, spill * (0.35 + 0.9 * frac)))
            a = a * (1.0 - img.max(axis=2) * (1.0 / 255.0))            # under the shape: only where it is dark
            f += a[..., None] * col
        if b > 0:
            small_img = Image.fromarray(img[::2, ::2])
            bright = Image.eval(small_img, lambda v: max(0, v - 190) * 3)    # only what is near white blooms
            r = max(1, min(w, h) // 180)
            sm = bright.filter(ImageFilter.GaussianBlur(r))
            wide = bright.resize((max(1, w // 8), max(1, h // 8)), Image.BILINEAR).filter(ImageFilter.GaussianBlur(r)).resize(sm.size, Image.BILINEAR)
            glow = Image.blend(sm, wide, 0.6).resize((w, h), Image.BILINEAR)
            f += np.asarray(glow, np.float32) * (0.8 * b)
        img = np.clip(f, 0, 255).astype(np.uint8)
    img = tone(img, lk)
    v, g = float(lk.get("vignette", 0)), float(lk.get("grain", 0))
    if v > 0 or g > 0:                                          # light taken away, specks: in float, once
        f = img.astype(np.float32)
        if v > 0:
            va = _layer(("vig", round(v, 3)), w, h, lambda: 1.0 - _resize(np.repeat(vignette_rgba(lk)[..., 3:], 3, 2), w, h)[..., 0])
            f *= va[..., None]
        if g > 0:
            bank = _layer("grain", w, h, lambda: np.random.default_rng(7).standard_normal((8, h, w), dtype=np.float32))
            f += (bank[(seed or 0) % 8] * (7.5 * g))[..., None]                 # eight frames of grain, taken in turn
        img = np.clip(f, 0, 255).astype(np.uint8)
    return img
