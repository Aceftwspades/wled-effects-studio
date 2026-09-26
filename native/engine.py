"""
Native front end to the compiled effects.

The DLL exports exactly the C surface the browser build exports - it is the same
sim_main.cpp, compiled by clang instead of Emscripten. That surface was written
for JavaScript's ccall and turns out to be precisely what ctypes wants too:
plain C linkage, no structs by value, buffers handed back as pointers.

Nothing here interprets an effect. The effect list, the parameter labels and the
defaults all come out of the metadata string the effect itself registered, so
this cannot drift from what the firmware would do.
"""
import ctypes as C
import os
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))


def default_library():
    """The library to load: the newest versioned build, else the legacy
    cubefx.dll beside build.py. See native/toolchain.py."""
    from native.toolchain import latest_library
    from native import paths
    return latest_library() or os.path.join(paths.RES, "cubefx.dll")


def ensure_library(project=None, log=print):
    """The library to load, built first when there is none (a build/ that
    was cleared, a checkout not built yet): the project's imported effects
    with the toolchain, as the editor's build would. Raises RuntimeError
    with what went wrong, and what to do, when it cannot."""
    lib = default_library()
    if os.path.exists(lib):
        return lib
    log("no engine built yet - building one (a minute the first time)...")
    try:
        import build as B
        from native.toolchain import build_engine
        srcs = B.engine_sources([project.effect_path(f) for f in project.build_files()] if project else [], log=log)
        rep = build_engine(srcs, B.include_dirs(), log=log)
    except Exception as e:
        raise RuntimeError(f"the engine could not be built: {e} - python -m native.doctor says what is missing")
    if not rep.ok:
        lines = [l for l in rep.link_output.splitlines() if l.strip()][-6:]
        for src, txt in rep.errors.items():
            lines += [l for l in txt.splitlines() if "error" in l][:3]
        raise RuntimeError("the engine could not be built:\n  " + "\n  ".join(lines) + "\n  python -m native.doctor says what is missing")
    return rep.library


def _unload(lib):
    """Drop a ctypes library so its file can be replaced. Best effort; a
    library that refuses to unload is simply left until the process exits."""
    try:
        if os.name == "nt":
            import ctypes.wintypes
            k32 = C.windll.kernel32
            k32.FreeLibrary.argtypes = [ctypes.wintypes.HMODULE]
            k32.FreeLibrary(lib._handle)
        else:
            C.CDLL(None).dlclose(lib._handle)
    except Exception:
        pass


def parse_meta(s):
    """Split a WLED effect metadata string into name, slider labels, defaults.

    Mirrors parseMeta() in index.html. Format:
        Name@lab1,lab2,...;colours;palette;flags;def1=v1,def2=v2
    """
    at = s.find("@")
    name = s if at < 0 else s[:at]
    rest = "" if at < 0 else s[at + 1:]
    seg = rest.split(";")
    labels = (seg[0] if seg else "").split(",")
    defs = {}
    if len(seg) > 4:
        for kv in seg[4].split(","):
            if "=" in kv:
                k, v = kv.split("=", 1)
                try:
                    defs[k.strip()] = int(v)
                except ValueError:
                    pass
    # flags: "1" runs on a strip, "2" on a matrix (both: "12"; none: a strip, WLED's default); "v"/"f" audio
    flags = seg[3] if len(seg) > 3 and "=" not in seg[3] else ""
    return {"name": name, "labels": labels, "defs": defs, "flags": flags}


def matrix_only(meta):
    """An effect written for a matrix alone: on a single row of LEDs WLED runs it as a solid colour."""
    f = meta.get("flags", "")
    return "2" in f and "1" not in f


class Engine:
    KEYS = ("sx", "ix", "c1", "c2", "c3", "o1", "o2", "o3")

    def __init__(self, dll=None):
        self.seg = 0                 # the current segment
        self._segstate = {}          # k -> its effect, sliders, palette, colours when not current
        self.idx = 0
        self.pal = 1
        self.fx = {}
        self.sim_ms = 0
        self.B = 16
        self.geom = None
        self.map1d2d = 0
        self.lib = None
        self.library = None
        self._colors = (0xFFA000, 0, 0)
        self.load(dll or default_library())

    def load(self, dll):
        """Bind a library. Called once from the constructor and again by
        reload() when the editor has produced a new build."""
        if not os.path.exists(dll):
            raise FileNotFoundError(
                f"{dll} not found - build it with:  python build.py --native-only")
        self.lib = C.CDLL(dll)
        self.library = dll
        L = self.lib
        L.simEffectCount.restype = C.c_int
        L.simEffectName.restype = C.c_char_p;  L.simEffectName.argtypes = [C.c_int]
        L.simEffectMeta.restype = C.c_char_p;  L.simEffectMeta.argtypes = [C.c_int]
        L.simInit.argtypes = [C.c_int, C.c_int]
        if hasattr(L, "simSixFaces"):
            L.simSixFaces.argtypes = [C.c_int]
        L.simParams.argtypes = [C.c_int] * 9
        L.simColors.argtypes = [C.c_uint32] * 3
        L.simFftPtr.restype = C.POINTER(C.c_uint8)
        L.simAudioSet.argtypes = [C.c_float, C.c_int]
        L.simFrame.argtypes = [C.c_int, C.c_int]
        L.simPixels.restype = C.POINTER(C.c_uint32)
        L.simPalCount.restype   = C.c_int
        L.simUmPalCount.restype = C.c_int
        L.simUmPalName.restype  = C.c_char_p; L.simUmPalName.argtypes = [C.c_int]
        L.simPalColor.restype   = C.c_uint32; L.simPalColor.argtypes = [C.c_int, C.c_int]
        L.simSetPalSource.argtypes = [C.c_int]
        L.simGetPalSource.restype  = C.c_int
        L.simSetMap1D2D.argtypes = [C.c_int]
        L.simWidth.restype = C.c_int
        L.simHeight.restype = C.c_int

        self.count = L.simEffectCount()
        self.meta = [parse_meta(L.simEffectMeta(i).decode("utf-8", "replace"))
                     for i in range(self.count)]
        self.names = [m["name"] for m in self.meta]
        if self.geom is not None:
            self.set_geometry(self.geom)
        else:
            self.resize(self.B)

    def reload(self, dll=None):
        """Swap to a newer build, keeping the selected effect (by NAME, since
        indices move when effects are added), its parameters, palette, colours
        and geometry. The effect restarts from nothing, which is what an edit
        to it means anyway."""
        dll = dll or default_library()
        want = self.names[self.idx] if self.names else None
        fx, pal, cols = dict(self.fx), self.pal, self._colors
        segs = self.segments() if self.seg_count() > 1 else None
        old = self.lib
        self.load(dll)
        if old is not None and old is not self.lib:
            _unload(old)
        if want in self.names:
            self.select(self.names.index(want), params=dict(fx, pal=pal))
        self.colors(*cols)
        if segs:
            self.load_segments(segs)

    # --- geometry ------------------------------------------------------------
    def resize(self, B):
        """The cube net at B pixels a face - the shape this started with."""
        from native.geometry import Geometry
        self.set_geometry(Geometry("cube", B=B))

    def set_geometry(self, geom):
        """Any Geometry: the engine hears only its logical (w, h); positions
        stay on the Python side for the renderer and the ledmap."""
        self.geom = geom
        self.cols, self.rows = geom.w, geom.h
        self.B = geom.params.get("B", self.B) if geom.kind == "cube" else self.B
        # a lit bottom face in the net's (2,2) block; the effects size their
        # buffers by it, so it is set before anything is (re)initialised
        self.six = bool(geom.kind == "cube" and geom.params.get("six"))
        if hasattr(self.lib, "simSixFaces"):
            self.lib.simSixFaces(int(self.six))
        self.lib.simInit(self.cols, self.rows)
        # the engine clamps what it cannot hold; a size it did not take would
        # leave the pixel view reading past the buffer
        got = (self.lib.simWidth(), self.lib.simHeight())
        if got != (self.cols, self.rows):
            raise ValueError(f"the engine cannot hold {self.cols} x {self.rows} pixels (max 65536)")
        self.lib.simSetMap1D2D(self.map1d2d)
        self.geometry_table(geom.table())
        self._px = self.lib.simPixels()
        self._fft = self.lib.simFftPtr()
        self.sim_ms = 0
        self.seg = 0
        self._segstate.clear()
        self.select(self.idx)

    def set_map1d2d(self, mode):
        """How a 1-D effect is expanded on a 2-D geometry: 0 strip, 1 bars,
        2 arcs, 3 corner - WLED's own segment setting."""
        self.map1d2d = int(mode)
        self.lib.simSetMap1D2D(self.map1d2d)

    @property
    def is_cube(self):
        return self.geom is not None and self.geom.kind == "cube"

    def find(self, needle):
        n = needle.lower()
        for i, name in enumerate(self.names):
            if n in name.lower():
                return i
        raise KeyError(f"no effect matching {needle!r}")

    # --- driving -------------------------------------------------------------
    # --- segments -------------------------------------------------------------
    # The strip can carry several: each a rectangle with its own effect,
    # sliders, palette and opacity, composited in order. The single-segment
    # calls (select, push, fx, pal) act on the CURRENT one; the others' state
    # is kept here and swapped in by seg_select. Segment 0 is the whole
    # strip until the host says otherwise.
    def seg_count(self):
        try:
            return int(self.lib.simSegCount())
        except AttributeError:
            return 1

    BLEND_MODES = ["Top/Default", "Bottom/None", "Add", "Subtract", "Difference", "Average", "Multiply", "Divide",
                   "Lighten", "Darken", "Screen", "Overlay", "Hard light", "Soft light", "Dodge", "Burn", "Stencil"]

    def seg_get(self, k):
        """(x0, y0, x1, y1, opacity, effect index, blend mode) of segment k."""
        return tuple(int(self.lib.simSegGet(int(k), w)) for w in range(7))

    OPTION_KEYS = ("rev", "mi", "rY", "mY", "tp", "grp", "spc", "of")       # WLED's names, as index.js sends them

    def seg_options(self, k):
        """WLED's segment options of segment k: {rev, mi, rY, mY, tp, grp, spc, of}."""
        vals = [int(self.lib.simSegGet(int(k), 7 + i)) for i in range(8)]
        return {key: (bool(v) if i < 5 else v) for i, (key, v) in enumerate(zip(self.OPTION_KEYS, vals))}

    def seg_set_options(self, k, **opt):
        """Some of the options changed (the rest kept): reverse, mirror (x and y), transpose, grouping, spacing, offset."""
        cur = self.seg_options(k); cur.update(opt)
        try:
            self.lib.simSegOptions(int(k), int(cur["rev"]), int(cur["mi"]), int(cur["rY"]), int(cur["mY"]), int(cur["tp"]),
                                   int(cur["grp"]), int(cur["spc"]), int(cur["of"]))
        except AttributeError:
            pass                                                    # an older library

    def seg_blend(self, k, mode):
        self.lib.simSegBlendMode(int(k), int(mode))

    def seg_config(self, k, x0, y0, x1, y1, opacity=255):
        self.lib.simSegConfig(int(k), int(x0), int(y0), int(x1), int(y1), int(opacity))
        self._segstate.setdefault(k, None)

    def seg_truncate(self, n):
        self.lib.simSegTruncate(int(n))
        for k in list(self._segstate):
            if k >= n:
                self._segstate.pop(k)
        if self.seg >= n:
            self.seg_select(n - 1)

    def seg_select(self, k):
        """Make segment k the one the effect, sliders and colours refer to."""
        k = int(k)
        if k == self.seg:
            return
        self._segstate[self.seg] = {"idx": self.idx, "fx": dict(self.fx), "pal": self.pal, "colors": self._colors}
        self.seg = k
        self.lib.simSegSelect(k)
        st = self._segstate.get(k)
        if st:
            self.idx, self.fx, self.pal = st["idx"], dict(st["fx"]), st["pal"]
            self._colors = st["colors"]
        else:
            self.select(self.idx)                  # a new segment starts on the current effect
            self._segstate[k] = {"idx": self.idx, "fx": dict(self.fx), "pal": self.pal, "colors": self._colors}

    def segments(self):
        """Every segment as the host sees it: bounds, opacity, the effect's
        name, its params and palette - for saving with the project."""
        out = []
        cur = {"idx": self.idx, "fx": dict(self.fx), "pal": self.pal, "colors": self._colors}
        for k in range(self.seg_count()):
            x0, y0, x1, y1, op, fx, bm = self.seg_get(k)
            st = cur if k == self.seg else (self._segstate.get(k) or {"idx": fx, "fx": {}, "pal": self.pal, "colors": self._colors})
            name = self.names[st["idx"]] if 0 <= st["idx"] < len(self.names) else ""
            row = {"bounds": [x0, y0, x1, y1], "opacity": op, "blend": bm, "effect": name, "params": dict(st["fx"]), "pal": st["pal"]}
            opts = self.seg_options(k)
            if any(opts[key] for key in ("rev", "mi", "rY", "mY", "tp", "spc", "of")) or opts["grp"] != 1:
                row["options"] = opts                                # only when something is set: older files stay as they were
            out.append(row)
        return out

    def load_segments(self, segs):
        """The reverse: the strip's segments from a saved list."""
        self.lib.simSegTruncate(1)
        self._segstate.clear()
        self.seg = 0
        self.lib.simSegSelect(0)
        for k, sg in enumerate(segs[:8]):
            b = sg.get("bounds") or [0, 0, self.cols, self.rows]
            self.seg_config(k, b[0], b[1], b[2], b[3], sg.get("opacity", 255))
            self.seg_blend(k, sg.get("blend", 0))
            opts = dict(rev=False, mi=False, rY=False, mY=False, tp=False, grp=1, spc=0, of=0); opts.update(sg.get("options") or {})
            self.seg_set_options(k, **opts)
        for k, sg in enumerate(segs[:8]):
            self.seg_select(k) if k != self.seg else None
            if sg.get("effect") in self.names:
                self.select(self.names.index(sg["effect"]), params=dict(sg.get("params") or {}, pal=sg.get("pal", self.pal)))
            self.lib.simSegEffect(k, self.idx)
        if segs:
            self.seg_select(0)

    def select(self, idx, params=None):
        """Pick an effect and reset it, exactly as WLED does on a mode change."""
        self.idx = idx
        try:
            self.lib.simSegEffect(self.seg, idx)
        except AttributeError:
            pass
        m = self.meta[idx]
        # Defaults come from the effect's own metadata, same as the web UI.
        self.fx = {k: m["defs"].get(k, 16 if k == "c3" else 128) for k in self.KEYS[:5]}
        for k in self.KEYS[5:]:
            self.fx[k] = 1 if m["defs"].get(k) else 0
        if params:
            self.fx.update(params)
        # Palette DOES come from the effect's metadata now, like every other
        # default, because the simulator carries WLED's real palette set and an
        # id means the same thing on both sides. It used to be excluded: with
        # only six hand-copied gradients here, a metadata default of pal=11 was
        # Rainbow on the device and Mono in the simulator, so effects were
        # previewed in greyscale at a reported saturation of zero.
        if params is None or "pal" not in params:
            self.pal = m["defs"].get("pal", self.pal)
        elif "pal" in params:
            self.pal = params["pal"]
        self.push()
        self.lib.simSelect()
        self.sim_ms = 0

    # --- palettes -------------------------------------------------------------
    _PAL_NAMES = None

    @classmethod
    def fixed_palette_names(cls):
        """The firmware's own palette names, lifted by build.py."""
        if cls._PAL_NAMES is None:
            import json
            path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "gen", "palette_names.json")
            with open(path, encoding="utf-8") as f:
                cls._PAL_NAMES = json.load(f)
        return cls._PAL_NAMES

    def palette_list(self):
        """[(name, id)] for everything selectable - fixed, then usermod.

        Usermod palettes are queried from the DLL rather than listed here, so
        whatever a usermod registered shows up without this file knowing about
        it. Their ids count DOWN from 255, as in the firmware.
        """
        out = [(n, i) for i, n in enumerate(self.fixed_palette_names())]
        for i in range(self.lib.simUmPalCount()):
            nm = self.lib.simUmPalName(i)
            out.append((nm.decode() if isinstance(nm, bytes) else str(nm), 255 - i))
        for i, name in enumerate(getattr(self, "custom_names", []) or []):
            out.append((name, 200 - i))                # the studio's custom palettes: ids 200 down, as on the device
        return out

    def custom_palettes(self, pals):
        """The project's custom palettes into the engine: a list of
        {"name", "stops": [[pos, r, g, b], ...]}; ids 200, 199, ... in that
        order. False for an engine built without them."""
        try:
            f = self.lib.simCustomPalette
        except AttributeError:
            return False
        self.lib.simCustomPaletteClear()
        self.custom_names = []
        for i, p in enumerate(pals[:10]):
            stops = sorted([[int(q[0]), int(q[1]), int(q[2]), int(q[3])] for q in (p.get("stops") or [])], key=lambda q: q[0])
            if len(stops) < 2:
                stops = [[0, 0, 0, 0], [255, 255, 255, 255]]
            flat = [max(0, min(255, v)) for q in stops[:18] for v in q]
            buf = (C.c_uint8 * len(flat))(*flat)
            f(int(i), buf, len(stops[:18]))
            self.custom_names.append(str(p.get("name") or f"Custom {i + 1}"))
        return True

    # The audio palettes draw their colours from a SOURCE palette. On the device
    # that is a Usermods setting; here it is a control, because the simulator has
    # no settings page.
    @property
    def pal_source(self):
        return self.lib.simGetPalSource()

    @pal_source.setter
    def pal_source(self, v):
        self.lib.simSetPalSource(int(v))

    def palette_swatch(self, pal, n=16):
        """n colours across a palette, as (r,g,b) - for UI swatches and tests."""
        out = []
        for k in range(n):
            c = self.lib.simPalColor(int(pal), (k * 255) // max(n - 1, 1))
            out.append(((c >> 16) & 255, (c >> 8) & 255, c & 255))
        return out

    def push(self):
        f = self.fx
        self.lib.simParams(f["sx"], f["ix"], f["c1"], f["c2"], f["c3"],
                           f["o1"], f["o2"], f["o3"], self.pal)

    def colors(self, c0, c1=0, c2=0):
        """Segment colours. WLED's DEFAULT_COLOR is 0xFFA000."""
        self._colors = (int(c0) & 0xFFFFFF, int(c1) & 0xFFFFFF, int(c2) & 0xFFFFFF)
        self.lib.simColors(*self._colors)

    def script(self, prog):
        """Load a script (bytes from script.compile_script) into the Studio
        Script effect; True if the engine has it and took it."""
        try:
            f = self.lib.simScript
        except AttributeError:
            return False
        buf = (C.c_uint8 * len(prog)).from_buffer_copy(prog)
        f(buf, len(prog))
        return bool(self.lib.simScriptValid())

    def geometry_table(self, table):
        """The shape's position table into the engine (cfx_pos reads it for
        this segment size); None clears it. Ignored by an engine built
        without it."""
        try:
            f = self.lib.simGeometry
        except AttributeError:
            return False
        if not table:
            f(None, 0); return True
        buf = (C.c_uint8 * len(table)).from_buffer_copy(table)
        f(buf, len(table))
        return bool(self.lib.simGeometryValid())

    def script_effect(self):
        return next((i for i, n in enumerate(self.names) if "Studio Script" in n), None)

    def pcm(self, samples):
        """The waveform slot (u_data[8]) for effects that draw the wave
        itself: 256 int8 samples, as audioreactive's cube_fx block gives
        the device. Ignored by an engine built without it."""
        try:
            f = self.lib.simPcmSet
        except AttributeError:
            return
        a = np.ascontiguousarray(np.clip(samples, -127, 127).astype(np.int8))
        f(a.ctypes.data_as(C.POINTER(C.c_int8)), int(a.size))

    def param_set(self, idx, k, v):
        """A typed value into a running graph effect's parameter table
        (slot k of effect idx): True when it landed, False when the
        effect has no table bound yet (it has not run since its build)
        or the engine predates this."""
        try:
            f = self.lib.simParamSet
        except AttributeError:
            return False
        f.restype = C.c_int
        return bool(f(int(idx), int(k), C.c_float(float(v))))

    def probe(self, i):
        """A live value the generated effect reported (see graph.py's probes);
        0 if this build has no probes."""
        try:
            f = self.lib.simProbeGet
            f.restype = C.c_float
            return float(f(int(i)))
        except AttributeError:
            return 0.0

    def audio(self, vol, peak):
        self.last_audio = (float(vol), int(peak))
        self.lib.simAudioSet(C.c_float(vol), int(peak))

    @property
    def fft(self):
        """Writable 16-byte view of the FFT bins the effects read."""
        return np.ctypeslib.as_array(self._fft, shape=(16,))

    def frame(self, dt=23):
        self.sim_ms += dt
        self.lib.simFrame(self.idx, dt)

    def set_now(self, ms=0):
        """The engine's clock (strip.now) set: two runs from the same
        millisecond, for a comparison. Ignored by an engine without it."""
        self.sim_ms = int(ms)
        try:
            self.lib.simNowSet(C.c_uint32(int(ms)))
        except AttributeError:
            pass

    def pixels(self):
        """(rows, cols) uint32 0x00RRGGBB, a live view of the engine's buffer."""
        n = self.cols * self.rows
        return np.ctypeslib.as_array(self._px, shape=(n,)).reshape(self.rows, self.cols)

    def rgb(self):
        """(rows, cols, 3) uint8."""
        p = self.pixels()
        return np.dstack(((p >> 16) & 255, (p >> 8) & 255, p & 255)).astype(np.uint8)

    # --- masks ---------------------------------------------------------------
    def lit_mask(self, flat=False):
        """True where a pixel exists. On the cube the four gap corners do not;
        every other geometry is fully populated."""
        if flat or self.geom is None or self.geom.kind != "cube":
            return np.ones((self.rows, self.cols), bool)
        B = self.B
        yy, xx = np.mgrid[0:self.rows, 0:self.cols]
        m = ((xx // B) == 1) | ((yy // B) == 1)
        if getattr(self, "six", False):
            m |= ((xx // B) == 2) & ((yy // B) == 2)       # the bottom face
        return m

    def lid_mask(self):
        B = self.B
        m = np.zeros((self.rows, self.cols), bool)
        m[B:2 * B, B:2 * B] = True
        return m


def stats(rgb, mask):
    """The same five measures harness.js reports, computed the same way.

    Kept bit-comparable on purpose: these numbers are how every tuning decision
    in this project has been argued, and they are only worth anything if the
    native and browser builds can be held against each other.
    """
    r = rgb[..., 0].astype(np.int32)
    g = rgb[..., 1].astype(np.int32)
    b = rgb[..., 2].astype(np.int32)
    L = (r * 54 + g * 183 + b * 19) >> 8          # same integer luma as the JS
    Lm = L[mask]
    if Lm.size == 0:
        return dict(mean=0.0, sigma=0.0, dark=0.0, bright=0.0, sat=0)
    mx = np.maximum(np.maximum(r, g), b)[mask]
    mn = np.minimum(np.minimum(r, g), b)[mask]
    sel = Lm > 32
    sat = np.where(mx > 0, (mx - mn) * 255.0 / np.maximum(mx, 1), 0)[sel]
    return dict(
        mean=round(float(Lm.mean()), 1),
        sigma=round(float(Lm.std()), 1),
        dark=round(float((Lm < 16).mean() * 100), 1),
        bright=round(float((Lm > 200).mean() * 100), 1),
        sat=int(round(float(sat.mean()))) if sat.size else 0,
    )
