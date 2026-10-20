"""Shaders in (native/glsl.py): Shadertoy shaders translated into code effects,
compiled into an engine of their own and run - each draws a picture that
moves - and what it cannot take refused with the line and the reason. Needs a
compiler (as the studio's builds do). Run with  python tests/test_glsl.py  (or pytest).
"""
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from native import glsl                                   # noqa: E402

DEFAULT = """
void mainImage( out vec4 fragColor, in vec2 fragCoord )
{
    // Normalized pixel coordinates (from 0 to 1)
    vec2 uv = fragCoord/iResolution.xy;
    vec3 col = 0.5 + 0.5*cos(iTime+uv.xyx+vec3(0,2,4));
    fragColor = vec4(col,1.0);
}
"""

ROTATE = """
#define PI 3.14159265
precision highp float;
const float SCALE = 4.0;
mat2 rot(float a) { float c = cos(a), s = sin(a); return mat2(c, -s, s, c); }
void palette(in float t, out vec3 c) { c = 0.5 + 0.5 * cos(2.0 * PI * (t + vec3(0.0, 0.33, 0.67))); }
float sdCircle(vec2 p, float r) { return length(p) - r; }
void mainImage(out vec4 fragColor, in vec2 fragCoord) {
    vec2 p = (2.0 * fragCoord - iResolution.xy) / iResolution.y;
    p *= rot(iTime * 0.5);
    p.xy = fract(p.xy * SCALE) - 0.5;
    vec3 col;
    palette(length(p) + iTime * 0.1, col);
    col *= 0.3 + smoothstep(0.08, 0.0, abs(sdCircle(p, 0.3)));
    col.rg += vec2(0.05);
    fragColor = vec4(col, 1.);
}
"""

BALLS = """
struct Ball { vec2 pos; float r; };
float field(vec2 p) {
  float s = 0.;
  for (int i = 0; i < 4; i++) {
    float fi = float(i);
    vec2 c = 0.3 * vec2(sin(iTime + fi * 1.7), cos(iTime * 1.3 + fi));
    s += 0.02 / dot(p - c, p - c);
  }
  return s;
}
void mainImage(out vec4 o, vec2 u) {
  vec2 p = (u - 0.5 * iResolution.xy) / iResolution.y;
  float f = clamp(field(p), 0.0, 1.0);
  o = vec4(vec3(f, f * 0.5, f * 0.2), 1.);
}
"""


def test_what_it_refuses():
    for src, want in (("void main() { gl_FragColor = vec4(1.0); }", "no mainImage"),
                      ("void mainImage(out vec4 o, vec2 u) {\n  o = texture(iChannel0, u);\n}", "line 2: a texture"),
                      ("void mainImage(out vec4 o, vec2 u) { ivec2 q = ivec2(u); o = vec4(1.0); }", "ivec2"),
                      ("uniform float uSpeed;\nvoid mainImage(out vec4 o, vec2 u) { o = vec4(uSpeed); }", "uniform it cannot give")):
        try:
            glsl.translate(src, "x")
            raise AssertionError(f"read: {src[:30]}")
        except glsl.ShaderError as e:
            assert want in str(e), (want, str(e))


def test_what_it_writes():
    cpp = glsl.translate(ROTATE, "Rotating tiles")
    assert "gl_cos(" in cpp and "p.xy() = gl_fract(p.xy() * SCALE) - 0.5f;" in cpp, cpp[-1500:]
    assert "void palette(float t, vec3 &c)" in cpp                       # in by value, out by reference
    assert "#define PI_ 3.14159265f" in cpp and "PI_ *" in cpp           # Arduino's PI left alone
    assert "precision" not in cpp.split("// --- the shader")[1]
    assert '"Rotating tiles@Speed,Brightness' in cpp and "mode_rotating_tiles" in cpp


def test_they_build_and_move():
    """The three compiled into an engine, each run on a 32 x 16 matrix: a picture (not black), and a
    different one a second later."""
    import build as B
    from native import scratch
    from native.toolchain import build_engine
    from native.engine import Engine
    from native.geometry import Geometry
    srcs, titles = [], []
    for title, src in (("GLSL Default", DEFAULT), ("GLSL Rotate", ROTATE), ("GLSL Balls", BALLS)):
        path = scratch.path("test_glsl_" + title.split()[1].lower() + ".cpp")
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(glsl.translate(src, title))
        srcs.append(path); titles.append(title)
    rep = build_engine(B.engine_sources(srcs, log=lambda *a: None), B.include_dirs(), log=lambda *a: None,
                       point_latest=False)
    assert rep.ok, "\n".join(f"{os.path.basename(f)}:{ln}: {m}" for f, ln, m in rep.error_lines()[:12])
    eng = Engine(rep.library)
    try:
        eng.set_geometry(Geometry("matrix", w=32, h=16))
        for title in titles:
            k = eng.find(title)
            assert k is not None, title
            eng.select(k, {"sx": 128, "ix": 255})
            eng.frame(20)
            a = eng.rgb().copy()
            for _ in range(50):
                eng.frame(20)
            b = eng.rgb()
            assert a.max() > 40, (title, int(a.max()))
            assert np.abs(a.astype(int) - b.astype(int)).mean() > 1.0, title
    finally:
        from native.engine import _unload
        _unload(eng)


if __name__ == "__main__":
    import inspect
    bad = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and inspect.isfunction(fn):
            try:
                fn(); print("ok  ", name)
            except Exception as e:
                bad += 1; print("FAIL", name, str(e)[:3000])
    sys.exit(1 if bad else 0)
