"""
The API reference beside the code pane: what an effect has to work with,
one line each, with a snippet: a click puts it at the cursor of the
in-app editor (and on the clipboard, for an external one).

Grouped as the effect author thinks of them. Everything here is a stock
WLED name or a cube_fx_common.h helper - nothing the shim invents.
"""

API = [
    ("controls", [
        ("SEGMENT.speed", "SEGMENT.speed", "slider 1, 0..255"),
        ("SEGMENT.intensity", "SEGMENT.intensity", "slider 2, 0..255"),
        ("SEGMENT.custom1 / custom2", "SEGMENT.custom1", "sliders 3 and 4, 0..255"),
        ("SEGMENT.custom3", "SEGMENT.custom3", "slider 5, five bits: 0..31"),
        ("SEGMENT.check1 / 2 / 3", "SEGMENT.check1", "the three checkboxes"),
        ("SEGCOLOR(n)", "SEGCOLOR(0)", "the segment's colours, 0..2, as 0xRRGGBB"),
        ("SEGMENT.palette", "SEGMENT.palette", "the palette id"),
    ]),
    ("time", [
        ("strip.now", "strip.now", "the clock in ms, uint32_t"),
        ("fx_dt(store)", "const uint16_t dt = fx_dt(SEGENV.step);", "ms since last frame, clamped; store in .step"),
        ("SEGENV.call", "SEGENV.call", "frames since the effect started"),
        ("beatsin8(bpm, lo, hi)", "beatsin8(30, 0, 255)", "a sine at bpm, between lo and hi"),
        ("beatsin16(bpm, lo, hi)", "beatsin16(30, 0, 65535)", "16-bit beatsin"),
        ("beat8(bpm)", "beat8(30)", "a sawtooth 0..255 at bpm"),
    ]),
    ("pixels", [
        ("SEG_W / SEG_H", "const int W = SEG_W, H = SEG_H;", "the 2-D size (virtual)"),
        ("SEGLEN", "SEGLEN", "the 1-D length"),
        ("SEGMENT.is2D()", "if (SEGMENT.is2D()) {", "true on a matrix segment"),
        ("setPixelColorXY(x, y, c)", "SEGMENT.setPixelColorXY(x, y, c);", "2-D write"),
        ("setPixelColor(i, c)", "SEGMENT.setPixelColor(i, c);", "1-D write"),
        ("getPixelColorXY(x, y)", "SEGMENT.getPixelColorXY(x, y)", "last frame's colour (feedback)"),
        ("SEGMENT.fill(c)", "SEGMENT.fill(BLACK);", "every pixel one colour"),
        ("SEGMENT.fadeToBlackBy(n)", "SEGMENT.fadeToBlackBy(32);", "fade the buffer, trails"),
        ("SEGMENT.blur(n)", "SEGMENT.blur(64);", "blur the buffer (2-D)"),
    ]),
    ("colour", [
        ("color_from_palette(i, ...)", "SEGMENT.color_from_palette(idx, false, true, 0)", "palette colour at index 0..255"),
        ("ColorFromPalette(pal, i, bri)", "ColorFromPalette(SEGPALETTE, idx, 255, LINEARBLEND)", "FastLED palette lookup"),
        ("CHSV / hsv2rgb", "CRGB c = CHSV(hue, 255, 255);", "hue 0..255, saturation, value"),
        ("RGBW32(r, g, b, w)", "RGBW32(r, g, b, 0)", "pack a colour"),
        ("R(c) G(c) B(c)", "R(c)", "unpack a channel"),
        ("mq_scale(c, s)", "mq_scale(c, 128)", "scale a colour by 0..255 (cube_fx_common.h)"),
        ("cfxPaletteSourceColor(pos, bri)", "cfxPaletteSourceColor(idx, 255)", "the palette-source setting's colour; declare weak, see a generated graph effect"),
        ("color_blend(a, b, f)", "color_blend(a, b, 128)", "mix two colours, f 0..255"),
        ("color_add(a, b)", "color_add(a, b)", "saturating add"),
        ("gamma32(c)", "gamma32(c)", "gamma-correct"),
    ]),
    ("noise and maths", [
        ("inoise8(x, y, z)", "inoise8(x * 16, y * 16, t / 4)", "Perlin noise 0..255"),
        ("inoise16(x, y, z)", "inoise16(x, y, z)", "16-bit noise"),
        ("sin8 / cos8(a)", "sin8(a)", "0..255 sine of a 0..255 angle"),
        ("sin16 / cos16(a)", "sin16(a)", "16-bit sine of a 0..65535 angle"),
        ("scale8(v, s)", "scale8(v, s)", "v * s / 256"),
        ("qadd8 / qsub8", "qadd8(a, b)", "saturating byte add / subtract"),
        ("random8() / random16(n)", "random8()", "a random byte / 0..n-1"),
        ("hw_random16()", "hw_random16()", "hardware random"),
        ("map(v, a, b, c, d)", "map(v, 0, 255, 0, W)", "Arduino map"),
        ("constrain(v, lo, hi)", "constrain(v, 0, 255)", ""),
        ("cfx_sinf16(rad) / cfx_cosf16", "cfx_sinf16(a)", "float sine by table (cube_fx_common.h)"),
        ("cfx_atan2f(y, x)", "cfx_atan2f(y, x)", "fast atan2"),
    ]),
    ("state", [
        ("SEGENV.aux0 / aux1", "SEGENV.aux0", "two uint16_t scratch values per effect"),
        ("SEGENV.step", "SEGENV.step", "uint32_t scratch"),
        ("allocateData(n)", "if (!SEGENV.allocateData(N)) return mode_static();", "persistent bytes: SEGENV.data"),
        ("SEGENV.data", "uint8_t *d = SEGENV.data;", "the allocated bytes"),
    ]),
    ("audio", [
        ("cfx_getAudioData()", "um_data_t *um = cfx_getAudioData();", "the audioreactive usermod's data, or a silent stand-in"),
        ("volumeSmth", "float vol = *(float*)um->u_data[0];", "smoothed volume"),
        ("fftResult[16]", "uint8_t *fft = (uint8_t*)um->u_data[2];", "the 16 FFT bins, 0..255"),
        ("cfx_bands(fft, bass, mid, treb)", "int bass, mid, treb; cfx_bands(fft, bass, mid, treb);", "three bands from the bins"),
        ("fx_lowBeat(um)", "uint8_t kick = fx_lowBeat(um);", "a kick detector, 0..255"),
        ("cfx_tempo(um)", "CfxTempoState &tempo = cfx_tempo(um);", "beat tracking: .bpm, .phase"),
        ("cfx_drop(um, tempo)", "CfxDropState &drop = cfx_drop(um, tempo);", "drop / build detection"),
    ]),
    ("cube", [
        ("cfx_isCube(cols, rows)", "const bool cube = cfx_isCube(cols, rows);", "is this segment a cube net"),
        ("CFX_NET_PREP / ROW / SKIP", "CFX_NET_PREP();\nfor (int y = 0; y < rows; y++) {\n  CFX_NET_ROW(y);\n  for (int x = 0; x < cols; x++) {\n    CFX_NET_SKIP(x);", "skip the net's unlit tiles; needs cols, B, cube"),
        ("cfx_pos(x, y, cols, rows, B, cube, ...)", "float px, py, pz; cfx_pos(x, y, cols, rows, B, cube, px, py, pz);", "a pixel's 3-D position on the cube"),
        ("cfx_face(x, y, z, face, a, b)", "int face, a, b; cfx_face(x, y, z, face, a, b);", "which face and where on it"),
        ("CfxTumble", "CfxTumble tum; cfx_tumbleInit(tum); cfx_tumbleStep(tum, step);", "a slow random rotation"),
        ("cfx_tumbleMatrix(t, M)", "float M[3][3]; cfx_tumbleMatrix(tum, M);", "its rotation matrix"),
    ]),
    ("metadata", [
        ("the metadata string", '"Name@Speed,Intensity,Custom 1,Custom 2,Custom 3,Check 1,Check 2,Check 3;;!;12;sx=128,ix=128,pal=11"',
         "name @ slider labels ; colours ; palette ; flags (1=1D 2=2D 12=both) ; defaults"),
        ("register", "static CfxBankReg my_reg(&mode_my_effect, _data_FX_MODE_MY_EFFECT);", "the bank picks it up"),
    ]),
]
