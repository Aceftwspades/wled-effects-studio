"""
Minimal animated GIF writer, stdlib + numpy.

Same reasoning as png.py: Pillow would do this in a line, and the native tool is
worth keeping installable with nothing but numpy. GIF because it plays inline
everywhere without a codec, loops on its own, and a still cannot show motion -
which is most of what these effects are.

Three things make the output small enough to be worth having:

  * ONE palette for the whole clip, built by median cut over sampled frames.
    Per-frame palettes would track colour better and cost 768 bytes a frame,
    and worse, they make the clip flicker as the quantisation shifts under a
    slowly moving field.

  * A 15-bit RGB lookup table for the mapping. Nearest-colour over 256 entries
    for every pixel of every frame is millions of distance calculations; doing
    it once for 32768 cells and then indexing is the difference between a
    minute and a second.

  * Frame differencing. Each frame is emitted as only the rectangle that
    changed, left in place over the last one. On a mostly-still effect that is
    almost nothing; on a full-surface flow it saves little, and that is fine.
"""
import struct
import numpy as np


def _median_cut(px, n=256):
    """px: (N,3) uint8 sample. Returns (n,3) uint8 palette.

    Split the box with the largest spread along its longest axis, repeatedly,
    which keeps detail where the colours actually are. An LED palette sweeping
    hue at full saturation puts almost nothing near the grey axis, so a uniform
    RGB cube would spend most of its entries on colours that never appear.
    """
    boxes = [px]
    while len(boxes) < n:
        # widest box first, by its longest side
        i = max(range(len(boxes)),
                key=lambda k: (boxes[k].max(0) - boxes[k].min(0)).max()
                if len(boxes[k]) > 1 else -1)
        b = boxes[i]
        if len(b) <= 1:
            break
        ax = int((b.max(0) - b.min(0)).argmax())
        b = b[b[:, ax].argsort()]
        mid = len(b) // 2
        if mid == 0:
            break
        boxes[i:i + 1] = [b[:mid], b[mid:]]
    pal = np.array([b.mean(0) for b in boxes], np.float32)
    if len(pal) < n:                       # pad, so the table is always 256
        pal = np.vstack([pal, np.zeros((n - len(pal), 3), np.float32)])
    return np.clip(pal + 0.5, 0, 255).astype(np.uint8)


def _lut(pal):
    """15-bit RGB -> palette index, computed once."""
    g = np.arange(32, dtype=np.float32) * (255.0 / 31.0)
    grid = np.stack(np.meshgrid(g, g, g, indexing="ij"), -1).reshape(-1, 3)
    out = np.empty(len(grid), np.uint8)
    p = pal.astype(np.float32)
    for i in range(0, len(grid), 4096):     # chunked, to bound memory
        d = ((grid[i:i + 4096, None, :] - p[None, :, :]) ** 2).sum(-1)
        out[i:i + 4096] = d.argmin(1).astype(np.uint8)
    return out


def _lzw(data, min_code_size=8):
    clear, end = 1 << min_code_size, (1 << min_code_size) + 1
    out = bytearray()
    cur = nbits = 0
    code_size = min_code_size + 1
    dic = {}
    nxt_code = end + 1

    def emit(code):
        nonlocal cur, nbits
        cur |= code << nbits
        nbits += code_size
        while nbits >= 8:
            out.append(cur & 0xFF)
            cur >>= 8
            nbits -= 8

    def reset():
        nonlocal dic, code_size, nxt_code
        dic = {bytes([i]): i for i in range(clear)}
        code_size = min_code_size + 1
        nxt_code = end + 1

    reset()
    emit(clear)
    prefix = b""
    for ch in data:
        nx = prefix + bytes((ch,))
        if nx in dic:
            prefix = nx
            continue
        emit(dic[prefix])
        dic[nx] = nxt_code
        nxt_code += 1
        if nxt_code == 4096:
            emit(clear)
            reset()
        elif nxt_code == (1 << code_size) + 1 and code_size < 12:
            # PLUS ONE, and it is load-bearing. The decoder's table runs exactly
            # one entry behind the encoder's: the encoder adds an entry for
            # every code it emits, while the decoder cannot add one until it has
            # seen the code AFTER the one that created it. So a decoder reading
            # code number k has k-1 entries where the encoder had k.
            #
            # Widening on the naive nxt_code == (1 << code_size) therefore
            # switches to wider codes one code sooner than the decoder expects,
            # and everything after the first transition is read at the wrong
            # width. It survives an 8x8 test image, which never gets past 256
            # entries, and falls apart at 40x40 - which is how this was found.
            code_size += 1
        prefix = bytes((ch,))
    if prefix:
        emit(dic[prefix])
    emit(end)
    if nbits:
        out.append(cur & 0xFF)
    return bytes(out)


def _blocks(b):
    o = bytearray()
    for i in range(0, len(b), 255):
        c = b[i:i + 255]
        o.append(len(c))
        o += c
    o.append(0)
    return bytes(o)


def write(path, frames, fps=15, loop=0):
    """frames: list of (h, w, 3) uint8, all the same shape."""
    h, w, _ = frames[0].shape
    delay = max(2, int(round(100.0 / fps)))        # GIF ticks are 1/100 s

    step = max(1, len(frames) // 24)               # sample for the palette
    sample = np.concatenate([f.reshape(-1, 3)[::7] for f in frames[::step]])
    pal = _median_cut(sample, 256)
    lut = _lut(pal)

    def to_idx(f):
        q = (f.astype(np.uint16) >> 3)
        return lut[(q[..., 0] << 10) | (q[..., 1] << 5) | q[..., 2]]

    out = bytearray(b"GIF89a")
    out += struct.pack("<HH", w, h) + bytes((0xF7, 0, 0))
    out += pal.tobytes()
    out += b"\x21\xFF\x0BNETSCAPE2.0\x03\x01" + struct.pack("<H", loop) + b"\x00"

    prev = None
    for f in frames:
        idx = to_idx(f)
        x0, y0, sub = 0, 0, idx
        if prev is not None:
            d = np.nonzero(idx != prev)
            if len(d[0]) == 0:                      # identical frame
                x0 = y0 = 0
                sub = idx[:1, :1]
            else:
                y0, y1 = int(d[0].min()), int(d[0].max()) + 1
                x0, x1 = int(d[1].min()), int(d[1].max()) + 1
                sub = idx[y0:y1, x0:x1]
        prev = idx
        sh, sw = sub.shape
        out += b"\x21\xF9\x04\x04" + struct.pack("<H", delay) + b"\x00\x00"
        out += b"\x2C" + struct.pack("<HHHH", x0, y0, sw, sh) + b"\x00"
        out += bytes((8,)) + _blocks(_lzw(sub.tobytes(), 8))
    out += b"\x3B"

    with open(path, "wb") as fh:
        fh.write(bytes(out))
    return len(out)
