"""
Minimal PNG writer, stdlib only.

Pillow would do this in a line, but a snapshot of a 48x48 grid is not worth a
dependency - and keeping the native tool installable with nothing but numpy
matters if anyone else ever builds it.
"""
import struct
import zlib


def _chunk(tag, data):
    return (struct.pack(">I", len(data)) + tag + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))


def write_rgb(path, rgb, scale=1):
    """rgb: (h, w, 3) uint8. scale repeats pixels, so the grid stays hard-edged."""
    if scale > 1:
        rgb = rgb.repeat(scale, axis=0).repeat(scale, axis=1)
    h, w, _ = rgb.shape
    raw = bytearray()
    for y in range(h):
        raw.append(0)                      # filter type 0 for every scanline
        raw += rgb[y].tobytes()
    png = (b"\x89PNG\r\n\x1a\n"
           + _chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
           + _chunk(b"IDAT", zlib.compress(bytes(raw), 6))
           + _chunk(b"IEND", b""))
    with open(path, "wb") as f:
        f.write(png)
    return path
