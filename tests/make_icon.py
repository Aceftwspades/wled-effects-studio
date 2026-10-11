"""The app icon's art, from the studio's own Ace 3-D Voronoi: its net rendered by the engine at four seconds,
folded into an isometric cube of lit LEDs with a glow - docs/brand/icon_cube.png - then the icons package.py
makes from it (docs/brand/app.ico, linux/wled-effects-studio.png).

    python tests/make_icon.py

The net is the studio's 3 x 3 cross of 16 x 16 faces: the centre is the top, the arm below it the front (hanging
from the top's near edge), the arm right of it the right side (folded down from the top's right edge)."""
import os
import subprocess
import sys
import tempfile

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, "docs", "brand", "icon_cube.png")
EFFECT, AT = "Ace 3-D Voronoi", 4000
N = 16


def net():
    """The effect's net at AT ms, one pixel an LED."""
    with tempfile.TemporaryDirectory() as d:
        base = os.path.join(d, "net")
        subprocess.run([sys.executable, "-m", "native.cli", "--snapshot", EFFECT, "--at", str(AT), "--scale", "1",
                        "--out", base], cwd=ROOT, check=True, capture_output=True)
        return Image.open(f"{base}_{AT}.png").convert("RGB").copy()


def faces(img):
    a = np.asarray(img, np.float32)
    top = a[N:2 * N, N:2 * N]
    front = a[2 * N:3 * N, N:2 * N]
    right = a[N:2 * N, 2 * N:3 * N][::-1, :].transpose(1, 0, 2)
    return top, front, right


def cube(img, size, *, edge=0.426, gain=1.25, glow=0.75, body=(17, 19, 24), gap=0.16, shade=(1.0, 0.86, 0.72), ss=3):
    """An RGBA size x size: the cube (an edge `edge` of the size on screen), transparent around it but for its glow."""
    top, front, right = faces(img)
    S = size * ss
    out = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    led = Image.new("RGB", (S, S), (0, 0, 0))
    d, dl = ImageDraw.Draw(out), ImageDraw.Draw(led)
    e = S * edge
    ex = np.array([np.cos(np.pi / 6), np.sin(np.pi / 6)]) * e      # x to the lower right
    ey = np.array([-np.cos(np.pi / 6), np.sin(np.pi / 6)]) * e     # y to the lower left
    ez = np.array([0.0, -1.0]) * e                                  # z up
    o = np.array([S / 2, S / 2]) - (ex + ey + ez) / 2

    def P(x, y, z):
        return tuple(o + ex * x + ey * y + ez * z)

    for poly, k in (([P(0, 0, 1), P(1, 0, 1), P(1, 1, 1), P(0, 1, 1)], shade[0]),
                    ([P(0, 1, 1), P(1, 1, 1), P(1, 1, 0), P(0, 1, 0)], shade[1]),
                    ([P(1, 1, 1), P(1, 0, 1), P(1, 0, 0), P(1, 1, 0)], shade[2])):
        d.polygon(poly, fill=tuple(int(c * k) for c in body) + (255,))

    def cells(face, k, quad):
        for r in range(N):
            for c in range(N):
                col = np.clip(face[r, c] * gain * k, 0, 255)
                if col.max() < 6:
                    continue
                u0, u1, v0, v1 = (c + gap) / N, (c + 1 - gap) / N, (r + gap) / N, (r + 1 - gap) / N
                pts = [quad(u0, v0), quad(u1, v0), quad(u1, v1), quad(u0, v1)]
                fill = tuple(int(v) for v in col)
                d.polygon(pts, fill=fill + (255,))
                dl.polygon(pts, fill=fill)

    cells(top, shade[0], lambda u, v: P(u, v, 1))
    cells(front, shade[1], lambda u, v: P(u, 1, 1 - v))
    cells(right, shade[2], lambda u, v: P(1, 1 - u, 1 - v))
    g = (np.asarray(led.filter(ImageFilter.GaussianBlur(S * 0.012)), np.float32) * 0.55
         + np.asarray(led.filter(ImageFilter.GaussianBlur(S * 0.05)), np.float32) * 0.9) * glow
    base = np.asarray(out, np.float32)
    a = base[:, :, 3:4] / 255
    alpha = np.clip(a + g.max(axis=2, keepdims=True) / 255 * 0.9, 0, 1)
    rgb = np.clip((base[:, :, :3] * a + g) / np.maximum(alpha, 1e-3), 0, 255)
    out = Image.fromarray(np.concatenate([rgb, alpha * 255], axis=2).astype(np.uint8), "RGBA")
    return out.resize((size, size), Image.LANCZOS)


def main():
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    cube(net(), 512).save(OUT, optimize=True)
    print("icon art", OUT)
    sys.path.insert(0, ROOT)
    import package
    print("icon", package.icon_file())
    print("icon", package.linux_icon())


if __name__ == "__main__":
    main()
