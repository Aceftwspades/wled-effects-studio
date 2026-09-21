"""The device's audio input: WLED's audioreactive usermod set up from the
studio - a microphone or a line-in module, its pins, its levels - as the
usermod's own config (`um.AudioReactive` in /json/cfg), and as the build
flags a fresh flash boots with.

    state(project)          -> the project's audio-input settings (made when missing)
    apply_preset(st, key)   -> the module's type, its board-fixed pins, its levels
    wled_cfg(st)            -> the body for POST /json/cfg
    from_wled_cfg(cfg, st)  -> the settings read out of the device's config
    flags(st)               -> ["-D SR_DMTYPE=4", "-D I2S_SDPIN=..", ...] for the flash env
    level_of(info)          -> (level 0..255 or None, what the device says of its source)
    needs_reboot(a, b)      -> the device must restart for the change (a type or a pin)
    describe(st)            -> one line

The types are audioreactive's dmType: 1 generic I2S mic, 2 ES7243, 3
SPH0645, 4 generic I2S with a master clock (a line-in ADC: PCM1808,
WM8782), 5 PDM mic, 6 ES8388 (a codec board's line input), 254 network
sound only, 255 off. The fork's audioreactive folds the two channels of a
line-in (types 4 and 6) to mono and removes the DC offset.
"""

TYPES = {1: "generic I2S microphone", 2: "ES7243 microphone", 3: "SPH0645 microphone", 4: "I2S line-in with master clock",
         5: "PDM microphone", 6: "ES8388 codec (line-in)", 254: "network sound only", 255: "off"}
LINE_IN = (4, 6)
AGC = ["off", "normal", "vivid", "lazy"]

# key, label, what it sets, and a note for the tip. Pins are [SD, WS, SCK, MCLK]; None keeps what is set
# (a breakout goes on whatever pins are free); a board with the chip soldered on has them fixed.
PRESETS = [
    ("inmp441", "INMP441 / ICS-43434 microphone (I2S)",
     {"type": 1, "pins": None, "i2c": None, "gain": 60, "squelch": 10, "agc": 0},
     "the usual digital mic: SD, WS and SCK; no master clock (MCLK -1). Gain 60, squelch 10, AGC off."),
    ("sph0645", "SPH0645 microphone (I2S)",
     {"type": 3, "pins": None, "i2c": None, "gain": 60, "squelch": 10, "agc": 0},
     "Adafruit's I2S mic: the same three wires, its own sample format."),
    ("pdm", "PDM microphone (SPM1423, MP34DT01)",
     {"type": 5, "pins": None, "i2c": None, "gain": 60, "squelch": 10, "agc": 0},
     "two wires: the clock on WS, the data on SD; SCK and MCLK -1. Not on the ESP32-S2 or C3."),
    ("es7243", "ES7243 microphone module",
     {"type": 2, "pins": None, "i2c": None, "gain": 60, "squelch": 10, "agc": 0},
     "an ADC module with a mic on it: the three I2S wires plus MCLK, set up over I2C (WLED's I2C pins)."),
    ("pcm1808", "PCM1808 / WM8782 line-in (I2S ADC + MCLK)",
     {"type": 4, "pins": None, "i2c": None, "gain": 40, "squelch": 4, "agc": 0},
     "a line-in breakout: BCK to SCK, LRCK to WS, DOUT to SD, and it needs the master clock (MCLK, any free GPIO on an S3). "
     "Both channels are mixed to mono and the DC offset removed by the fork's firmware. A line signal is steady: gain 40, "
     "squelch 4, no AGC."),
    ("es8388_audiokit", "ES8388 board line-in - AI-Thinker AudioKit",
     {"type": 6, "pins": [35, 25, 27, 0], "i2c": [33, 32], "gain": 40, "squelch": 4, "agc": 0},
     "the AudioKit v2.2: I2S SD 35, WS 25, SCK 27, MCLK 0; I2C SDA 33, SCL 32 (fixed on the board). Its line-in jack; the mics "
     "on the board hear as well, faintly. Both channels mixed, the offset removed."),
    ("es8388_lyrat", "ES8388 board line-in - Espressif LyraT",
     {"type": 6, "pins": [35, 25, 5, 0], "i2c": [18, 23], "gain": 40, "squelch": 4, "agc": 0},
     "the LyraT v4.3: I2S SD 35, WS 25, SCK 5, MCLK 0; I2C SDA 18, SCL 23 (fixed on the board). Its line-in jack."),
    ("es8388", "ES8388 board line-in - other pins",
     {"type": 6, "pins": None, "i2c": None, "gain": 40, "squelch": 4, "agc": 0},
     "any ES8388 board: the four I2S wires and the two I2C wires, typed in."),
    ("network", "network sound only",
     {"type": 254, "pins": None, "i2c": None, "gain": None, "squelch": None, "agc": None},
     "no input of its own: the audio comes from another WLED over UDP sound sync."),
    ("off", "off",
     {"type": 255, "pins": None, "i2c": None, "gain": None, "squelch": None, "agc": None},
     "the usermod stays but listens to nothing; the audio nodes see silence."),
]
PRESET = {k: (label, spec, note) for k, label, spec, note in PRESETS}
DEFAULT = {"preset": "inmp441", "type": 1, "pins": [-1, -1, -1, -1], "i2c": [-1, -1], "gain": 60, "squelch": 10, "agc": 0, "enabled": True}


def state(project):
    st = project.options.setdefault("audioin", dict(DEFAULT))
    for k, v in DEFAULT.items():
        st.setdefault(k, list(v) if isinstance(v, list) else v)
    return st


def preset_for(type_, pins=None, i2c=None):
    """The preset key a type (and board pins) matches, for what a device reports."""
    for key, label, spec, _ in PRESETS:
        if spec["type"] == type_ and (spec["pins"] is None or list(spec["pins"]) == list(pins or [])):
            return key
    return next((k for k, _, spec, _ in PRESETS if spec["type"] == type_), "inmp441")


def apply_preset(st, key):
    """The module's type and levels into the state; its pins when the board fixes them."""
    label, spec, _ = PRESET[key]
    st["preset"] = key
    st["type"] = spec["type"]
    if spec["pins"] is not None:
        st["pins"] = list(spec["pins"])
    if spec["i2c"] is not None:
        st["i2c"] = list(spec["i2c"])
    for k in ("gain", "squelch", "agc"):
        if spec[k] is not None:
            st[k] = spec[k]
    st["enabled"] = spec["type"] != 255
    return st


def needs_i2c(st):
    return int(st.get("type", 1)) in (2, 6)


def uses_mclk(st):
    return int(st.get("type", 1)) in (2, 4, 6)


def wled_cfg(st):
    """The body for POST /json/cfg: the usermod's block, and the I2C pins when the module is set up over I2C."""
    pins = [int(p) for p in (list(st.get("pins") or [-1] * 4) + [-1] * 4)[:4]]
    t = int(st.get("type", 1))
    body = {"um": {"AudioReactive": {"enabled": bool(st.get("enabled", True)) and t != 255,
                                     "digitalmic": {"type": t, "pin": pins},
                                     "config": {"squelch": int(st.get("squelch", 10)), "gain": int(st.get("gain", 60)),
                                                "AGC": int(st.get("agc", 0))}}}}
    i2c = list(st.get("i2c") or [-1, -1])
    if needs_i2c(st) and i2c[0] >= 0 and i2c[1] >= 0:
        body["hw"] = {"if": {"i2c-pin": [int(i2c[0]), int(i2c[1])]}}
    return body


def from_wled_cfg(cfg, st=None):
    """The settings out of a device's /json/cfg: the type, the pins, the levels, the I2C pins."""
    st = dict(st or DEFAULT)
    ar = (cfg.get("um") or {}).get("AudioReactive") or {}
    dm = ar.get("digitalmic") or {}
    if "type" in dm:
        st["type"] = int(dm["type"])
    pins = dm.get("pin")
    if isinstance(pins, list) and len(pins) >= 4:
        st["pins"] = [int(p) for p in pins[:4]]
    c = ar.get("config") or {}
    for k, key in (("gain", "gain"), ("squelch", "squelch"), ("agc", "AGC")):
        if key in c:
            st[k] = int(c[key])
    if "enabled" in ar:
        st["enabled"] = bool(ar["enabled"])
    i2c = ((cfg.get("hw") or {}).get("if") or {}).get("i2c-pin")
    if isinstance(i2c, list) and len(i2c) >= 2:
        st["i2c"] = [int(i2c[0]), int(i2c[1])]
    st["preset"] = preset_for(st["type"], st.get("pins"), st.get("i2c"))
    return st


def flags(st):
    """The -D flags for the flash env: what a fresh flash boots with (the
    device's own config, once saved, wins over these)."""
    t = int(st.get("type", 1))
    pins = [int(p) for p in (list(st.get("pins") or [-1] * 4) + [-1] * 4)[:4]]
    if t < 254 and pins[0] < 0 and pins[1] < 0:
        return []                                         # no pins set yet: the firmware's own defaults, not a deaf build
    out = [f"-D SR_DMTYPE={t if t < 254 else -1}", f"-D I2S_SDPIN={pins[0]}", f"-D I2S_WSPIN={pins[1]}",
           f"-D I2S_CKPIN={pins[2]}", f"-D MCLK_PIN={pins[3]}", "-D AUDIOPIN=-1"]
    if st.get("gain") is not None and t < 254:
        out += [f"-D SR_GAIN={int(st['gain'])}", f"-D SR_SQUELCH={int(st['squelch'])}", f"-D SR_AGC={int(st['agc'])}"]
    i2c = list(st.get("i2c") or [-1, -1])
    if needs_i2c(st) and i2c[0] >= 0 and i2c[1] >= 0:
        out += [f"-D I2CSDAPIN={int(i2c[0])}", f"-D I2CSCLPIN={int(i2c[1])}"]
    return out


def level_of(info):
    """(level 0..255 or None, the source line) from /json/info's usermod
    block: the fork's "Input level" row, else the stock "Audio Source"
    row's five-second peak."""
    u = (info or {}).get("u") or {}
    ar = u.get("AudioReactive") or {}
    src = ar.get("Audio Source") or []
    src_text = " ".join(str(x) for x in src).replace("  ", " ").strip() if isinstance(src, list) else str(src)
    lvl = ar.get("Input level")
    if isinstance(lvl, list) and lvl:
        try:
            return float(lvl[0]), src_text
        except (TypeError, ValueError):
            pass
    if isinstance(src, list):
        for x in src:
            s = str(x)
            if "peak" in s and "%" in s:
                try:
                    return float(s.split("peak")[1].strip().rstrip("%")) * 2.55, src_text
                except ValueError:
                    pass
    return None, src_text


def needs_reboot(a, b):
    """audioreactive re-reads its config live, but a new type or new pins take effect on the next boot."""
    if int(a.get("type", 1)) != int(b.get("type", 1)):
        return True
    pa = [int(p) for p in (list(a.get("pins") or []) + [-1] * 4)[:4]]
    pb = [int(p) for p in (list(b.get("pins") or []) + [-1] * 4)[:4]]
    return pa != pb or (needs_i2c(b) and list(a.get("i2c") or [-1, -1]) != list(b.get("i2c") or [-1, -1]))


def describe(st):
    t = int(st.get("type", 1))
    name = TYPES.get(t, f"type {t}")
    if t >= 254:
        return name
    pins = list(st.get("pins") or [-1] * 4)
    s = f"{name}: SD {pins[0]}, WS {pins[1]}, SCK {pins[2]}" + (f", MCLK {pins[3]}" if uses_mclk(st) else "")
    if needs_i2c(st):
        i2c = list(st.get("i2c") or [-1, -1]); s += f"; I2C {i2c[0]}/{i2c[1]}"
    return s + f"; gain {st.get('gain', 60)}, squelch {st.get('squelch', 10)}, AGC {AGC[int(st.get('agc', 0)) % 4]}"
