"""
A project: a geometry, the effects being written for it, and where the
results go.

    <dir>/
      project.json        geometry, the last-selected effect, options
      effects/*.cpp       effects authored here - compiled into the engine
      recipes/*.json      layer recipes (phase 2) - generated to effects/
      export/             what you take to the device: ledmap.json and a
                          usermod folder with the effects in it

An effect file here is an ordinary cube_fx-style translation unit: it includes
wled.h and cube_fx_common.h, defines one mode_*() function, and registers it
with a CfxBankReg. That is deliberately the SAME shape as the effects in
usermods/cube_fx/, so a file that works in the studio drops into a build with
no changes, and so the template can be honest about what a WLED effect is
rather than hiding it behind a friendlier one the device would not accept.
"""
import json
import os
import re
import shutil
import time

from native.geometry import Geometry

from native import paths
HERE = paths.RES                         # what ships: examples/, the docs
ROOT = paths.TREE                        # the WLED checkout, or None (native/paths.py)
PROJECTS = paths.PROJECTS

TEMPLATE = r'''#include "wled.h"
#include "cube_fx_common.h"
#include "cube_fx_bank.h"

// ===========================================================================
// {title}
// ===========================================================================
// Written in the WLED Effects Studio. This file is an ordinary WLED effect:
// drop it into usermods/cube_fx/ (or any usermod folder that includes
// cube_fx_common.h and cube_fx_bank.h) and it compiles into the firmware
// unchanged.
//
// What an effect has to work with:
//   SEGMENT.speed, .intensity, .custom1, .custom2   0..255   the sliders
//   SEGMENT.custom3                                   0..31    (five bits)
//   SEGMENT.check1, .check2, .check3                  bool     the checkboxes
//   SEGMENT.color_from_palette(idx, false, true, 0)   a palette colour
//   SEGCOLOR(0..2)                                    the segment's colours
//   strip.now                                         the clock, in ms
//   SEGENV.call / .aux0 / .aux1 / .step               per-effect scratch
//   SEGENV.allocateData(n) / SEGENV.data              persistent state
// 2-D:  SEG_W, SEG_H, SEGMENT.setPixelColorXY(x, y, c)
// 1-D:  SEGLEN, SEGMENT.setPixelColor(i, c)
// Audio: cfx_getAudioData(), cfx_bands(), fx_lowBeat() - see cube_fx_common.h
// ===========================================================================

static FX_RET mode_{ident}() {{
  // A 1-D effect runs on anything: on a matrix WLED expands it according to
  // the segment's 1-D-to-2-D setting. Ask is2D() to draw a matrix instead.
  const uint32_t t = strip.now;
  const uint8_t  sp = SEGMENT.speed;

  if (SEGMENT.is2D()) {{
    const int W = SEG_W, H = SEG_H;
    for (int y = 0; y < H; y++)
      for (int x = 0; x < W; x++) {{
        const uint8_t idx = (uint8_t)((x * 255) / (W > 1 ? W - 1 : 1) + (t * sp) / 2048);
        const uint8_t bri = (uint8_t)(SEGMENT.intensity);
        SEGMENT.setPixelColorXY(x, y, mq_scale(SEGMENT.color_from_palette(idx, false, true, 0), bri));
      }}
  }} else {{
    for (int i = 0; i < SEGLEN; i++) {{
      const uint8_t idx = (uint8_t)((i * 255) / (SEGLEN > 1 ? SEGLEN - 1 : 1) + (t * sp) / 2048);
      SEGMENT.setPixelColor(i, mq_scale(SEGMENT.color_from_palette(idx, false, true, 0), SEGMENT.intensity));
    }}
  }}
  FX_DONE;
}}

// Name@slider labels;colour labels;palette;flags;defaults
//   flags: 1 = 1-D, 2 = 2-D, 12 = both, f = frequency/audio, v = volume
static const char _data_FX_MODE_{upper}[] PROGMEM =
  "{title}@Speed,Brightness,,,,,,;;!;12;sx=120,ix=200,pal=11";

static CfxBankReg {ident}_reg(&mode_{ident}, _data_FX_MODE_{upper});
'''


def _ident(name):
    from native.graph import _ident as ident            # the same rule as a graph's effect name
    return ident(name)


def write_atomic(path, text):
    """A text file written whole or not at all: into <path>.tmp, flushed to
    the disk, then moved over the file - a crash or a power cut mid-write
    leaves the old file, never half of the new one (issue #5). On Windows a
    virus scanner or a sync tool can hold the file for a moment: the move is
    tried a few times, then the file is written in place rather than not.
    The temporary file is this write's own: two saves at once (a flash's
    worker and the panel) shared one <path>.tmp and could interleave."""
    import tempfile
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(os.path.abspath(path)), prefix=os.path.basename(path) + ".", suffix=".tmp")
    os.close(fd)
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    for k in range(6):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            time.sleep(0.05 * (k + 1))
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    try:
        os.remove(tmp)
    except OSError:
        pass


import threading
_SAVE_LOCK = threading.RLock()


class Project:
    def __init__(self, path):
        self.path = os.path.abspath(path)
        self.geometry = Geometry("cube", B=16)
        self.selected = ""              # name of the last-used effect
        self.options = {}
        # Effect files that are part of the project's effects list. Every
        # other file in effects/ is a draft: it is built - and appears in the
        # roster - only while it is the one being edited, and it is not
        # exported. "import" moves a draft onto the list.
        self.imported = []
        os.makedirs(os.path.join(self.path, "effects"), exist_ok=True)
        os.makedirs(os.path.join(self.path, "recipes"), exist_ok=True)
        os.makedirs(os.path.join(self.path, "export"), exist_ok=True)
        # a new project starts with the example graphs, so the node editor has
        # something to open and take apart; an existing graphs/ is left alone
        gdir = os.path.join(self.path, "graphs")
        if not os.path.isdir(gdir):
            os.makedirs(gdir, exist_ok=True)
            ex = os.path.join(HERE, "examples", "graphs")
            if os.path.isdir(ex):
                for f in os.listdir(ex):
                    if f.endswith(".json"):
                        shutil.copyfile(os.path.join(ex, f), os.path.join(gdir, f))
            assets = os.path.join(HERE, "examples", "assets")
            if os.path.isdir(assets):
                adir = os.path.join(self.path, "assets"); os.makedirs(adir, exist_ok=True)
                for f in os.listdir(assets):
                    if not os.path.exists(os.path.join(adir, f)):
                        shutil.copyfile(os.path.join(assets, f), os.path.join(adir, f))
        self.load()

    # --- persistence ----------------------------------------------------------------
    @property
    def file(self):
        return os.path.join(self.path, "project.json")

    # the options with an undo of their own: the sequence's steps, the schedule, the
    # palettes, the segments - every save() that changes one keeps what it was
    UNDO_KEYS = ("sequence", "schedule", "palettes", "segments")
    UNDO_MAX = 40

    def load(self):
        self.load_error = None          # what went wrong reading project.json, for the app to say (issue #5)
        self.save_blocked = False       # True: the file could not even be copied, so nothing is saved over it
        if not os.path.exists(self.file):
            self.save()
            return
        try:
            with open(self.file, encoding="utf-8") as f:
                d = json.load(f)
            if not isinstance(d, dict):
                raise ValueError("it is not a JSON object")
        except Exception as e:
            self._set_aside(e)
            return
        try:
            self.geometry = Geometry.from_json(d.get("geometry", {}))
        except Exception as e:
            # it was reset to the cube without a word, and the next save wrote the cube over it: a copy is kept
            self.geometry = Geometry("cube", B=16)
            bad = self._keep_copy()
            self.load_error = (f"the project's geometry could not be read ({type(e).__name__}: {e}), and it starts as "
                               f"the 16-pixel cube. " + (f"The file as it was is kept as {os.path.basename(bad)} in "
                               f"{self.path}." if bad else "It could not be copied, so nothing is saved over it."))
        self.selected = d.get("selected", "") if isinstance(d.get("selected", ""), str) else ""
        opts = d.get("options", {})
        self.options = opts if isinstance(opts, dict) else {}
        imp = d.get("imported")                           # null or not a list (a hand edit) raised at the start
        self.imported = [f for f in imp if isinstance(f, str)] if isinstance(imp, list) else []
        self._journal_reset()

    def _set_aside(self, err):
        """project.json that does not read - a hand edit's stray comma, a
        merge, a write cut short: the project starts from the defaults, and
        the next save would write them over every setting it held. So the
        file is copied to project.json.bad-<time> first and load_error says
        where; when it cannot even be copied, nothing is saved over it."""
        why = f"{type(err).__name__}: {err}" if not isinstance(err, ValueError) else str(err)
        bad = self._keep_copy()
        if bad is None:
            self.load_error = (f"{self.file} could not be read ({why}), nor copied. The studio will not save "
                               "over it: close the studio, see to the file, and start it again.")
            return
        self.load_error = (f"project.json could not be read ({why}). It was kept as {os.path.basename(bad)} in "
                           f"{self.path}, and the project starts from the defaults: put the settings back by fixing "
                           "that file and copying it over project.json, or from File > History.")

    def _keep_copy(self):
        """project.json copied to project.json.bad-<time>, before anything is saved over it: the copy's path, or
        None when it could not be made (then nothing is saved over it: save_blocked)."""
        bad = f"{self.file}.bad-{time.strftime('%Y%m%d-%H%M%S')}"
        k = 2
        while os.path.exists(bad):
            bad = f"{self.file}.bad-{time.strftime('%Y%m%d-%H%M%S')}-{k}"; k += 1
        try:
            shutil.copy2(self.file, bad)
            return bad
        except OSError:
            self.save_blocked = True
            return None

    def _journal_reset(self):
        self._undo = {k: [] for k in self.UNDO_KEYS}
        self._redo = {k: [] for k in self.UNDO_KEYS}
        self._last = {k: json.dumps(self.options.get(k), sort_keys=True) for k in self.UNDO_KEYS}
        # when each entry was made, by one count across the keys: which of two stacks changed last
        self._undo_t = {k: [] for k in self.UNDO_KEYS}
        self._redo_t = {k: [] for k in self.UNDO_KEYS}
        self._tick = 0
        self._restoring = False

    def _journal(self):
        """What changed since the last save, into its undo stack."""
        if not hasattr(self, "_last"):
            self._journal_reset(); return
        for k in self.UNDO_KEYS:
            cur = json.dumps(self.options.get(k), sort_keys=True)
            if cur != self._last[k]:
                if not self._restoring:
                    self._undo[k].append(self._last[k]); del self._undo[k][:-self.UNDO_MAX]
                    self._redo[k].clear()
                    self._tick += 1
                    self._undo_t[k].append(self._tick); del self._undo_t[k][:-self.UNDO_MAX]
                    self._redo_t[k].clear()
                self._last[k] = cur

    def can_undo(self, key):
        return bool(getattr(self, "_undo", {}).get(key))

    def can_redo(self, key):
        return bool(getattr(self, "_redo", {}).get(key))

    def undo(self, key):
        """The option back to what it was before its last change; the
        caller then shows it (the frame's refresh, the engine's segments).
        True when there was something to undo."""
        return self._step(key, self._undo, self._redo, self._undo_t, self._redo_t)

    def redo(self, key):
        return self._step(key, self._redo, self._undo, self._redo_t, self._undo_t)

    def latest(self, keys, redo=False):
        """Of `keys`, the one whose next undo (or redo) is the latest change - so one Ctrl+Z over two
        journals (the sequence and its schedule) takes back what was done last. None when neither has one."""
        if not hasattr(self, "_last"):
            self._journal_reset()
        stamps = self._redo_t if redo else self._undo_t
        have = [k for k in keys if (self.can_redo(k) if redo else self.can_undo(k))]
        return max(have, key=lambda k: stamps[k][-1] if stamps.get(k) else 0) if have else None

    def _step(self, key, take, give, take_t=None, give_t=None):
        if not hasattr(self, "_last"):
            self._journal_reset()
        if not take.get(key):
            return False
        give[key].append(self._last[key])
        if take_t is not None:
            give_t[key].append(take_t[key].pop() if take_t[key] else 0)
        val = json.loads(take[key].pop())
        if val is None:
            self.options.pop(key, None)
        else:
            self.options[key] = val
        self._restoring = True
        try:
            self.save()
        finally:
            self._restoring = False
        return True

    # a copy of the settings kept in the history (File > History) at most this often: they
    # are saved at every change, so a copy at every save would push the older ones out within minutes
    HISTORY_EVERY = 300.0

    def save(self):
        if getattr(self, "save_blocked", False):
            return                      # the file on disk could not be read or copied: left as it is
        # a flash's worker saves its record while the panel saves its edits: one at a time (the journal and the
        # file interleaved), and a setting changed on the main thread mid-way through serialising tried again -
        # "dictionary changed size during iteration" failed the save, and a flash that worked was called failed
        with _SAVE_LOCK:
            self._journal()
            d = {"geometry": self.geometry.to_json(), "selected": self.selected,
                 "options": self.options, "imported": self.imported,
                 "saved": time.strftime("%Y-%m-%d %H:%M:%S")}
            for attempt in range(8):
                try:
                    text = json.dumps(d, indent=1)
                    break
                except RuntimeError:
                    if attempt == 7:
                        raise
                    time.sleep(0.01)
            self._keep_history()
            write_atomic(self.file, text)

    def _keep_history(self):
        """What project.json held before this save, into history/project/ -
        the first save of a session, then at most every HISTORY_EVERY
        seconds, and only a file that reads (a broken one is kept aside by
        load, not here)."""
        now = time.time()
        if now - getattr(self, "_kept_at", 0.0) < self.HISTORY_EVERY:
            return
        try:
            old = open(self.file, encoding="utf-8").read()
            json.loads(old)
        except (OSError, ValueError):
            return
        from native import history
        try:
            history.keep(self, "project", "project", ".json", old)
            self._kept_at = now
        except OSError:
            pass

    # --- effects ------------------------------------------------------------------
    @property
    def effects_dir(self):
        return os.path.join(self.path, "effects")

    def effect_files(self):
        return sorted(f for f in os.listdir(self.effects_dir) if f.endswith(".cpp"))

    def effect_path(self, fname):
        return os.path.join(self.effects_dir, fname)

    def new_effect(self, title):
        """Write a fresh effect from the template; returns its file name."""
        ident = _ident(title)
        fname = ident + ".cpp"
        n = 2
        while os.path.exists(self.effect_path(fname)):
            fname = f"{ident}_{n}.cpp"; n += 1
            ident = f"{ident}_{n - 1}" if n > 2 else ident
        src = TEMPLATE.format(title=title.replace('"', "'"), ident=_ident(fname[:-4]),
                              upper=_ident(fname[:-4]).upper())
        with open(self.effect_path(fname), "w", encoding="utf-8", newline="\n") as f:
            f.write(src)
        return fname

    def read_effect(self, fname):
        return open(self.effect_path(fname), encoding="utf-8").read()

    def write_effect(self, fname, text):
        path = self.effect_path(fname)
        if os.path.exists(path):
            from native import history
            try:
                old = open(path, encoding="utf-8").read()
            except OSError:
                old = ""
            if old != text:
                history.keep(self, "effects", os.path.splitext(fname)[0], ".cpp", old)
        write_atomic(path, text)                         # whole or not at all, as project.json is
        self.__dict__.get("_titles", {}).pop(fname, None)

    # --- the effects list -----------------------------------------------------------
    def is_imported(self, fname):
        return fname in self.imported

    def set_imported(self, fname, on):
        if on and fname not in self.imported:
            self.imported.append(fname)
        if not on:
            self.imported = [f for f in self.imported if f != fname]
        self.save()

    def build_files(self, current=None):
        """The effect files a build compiles: the list, plus the one being
        edited so it can be previewed before it is imported."""
        have = set(self.effect_files())
        out = [f for f in self.imported if f in have]
        if current and current in have and current not in out:
            out.append(current)
        return out

    def rename_effect(self, fname, title):
        """Give an effect a new title and a file name to match. The metadata
        title is what the roster shows; the identifiers derived from the old
        file name are renamed too, so two effects never define the same
        function. Returns the new file name."""
        title = (title or "").strip()
        if not title or fname not in self.effect_files():
            return fname
        old = _ident(fname[:-4])
        ident = _ident(title)
        new = ident + ".cpp"
        n = 2
        while new != fname and os.path.exists(self.effect_path(new)):
            new = f"{ident}_{n}.cpp"; n += 1
        ident = new[:-4]
        src = self.read_effect(fname)
        old_title = self.effect_title(fname)
        src = re.sub(r'(PROGMEM\s*=\s*")[^@"]*', lambda m: m.group(1) + title.replace('"', "'"), src, count=1)
        src = src.replace(f"// {old_title}\n", f"// {title}\n", 1)      # the banner
        if old != ident:
            # inside identifiers too: mode_<old>, _data_FX_MODE_<OLD>
            edge = lambda w: r"(?<![A-Za-z0-9])" + re.escape(w) + r"(?![A-Za-z0-9])"
            src = re.sub(edge(old), ident, src)
            src = re.sub(edge(old.upper()), ident.upper(), src)
        self.write_effect(new, src)                      # the new file first: the old one goes once it is there
        if new != fname:
            # (a name that differs only in case is the same file on Windows and macOS: kept, not removed)
            if os.path.normcase(self.effect_path(new)) != os.path.normcase(self.effect_path(fname)) and \
                    not os.path.samefile(self.effect_path(new), self.effect_path(fname)):
                os.remove(self.effect_path(fname))
                self.__dict__.get("_titles", {}).pop(fname, None)
            if fname in self.imported:
                self.imported = [new if f == fname else f for f in self.imported]
                self.save()
        return new

    TITLE_RECHECK_S = 0.5                                # a file changed outside the studio: its new title this soon

    def effect_title(self, fname):
        """The name the effect registers, from its metadata string - kept until the file changes: the live
        glyphs asked every frame, and each time the file was read again. Its time is looked at again only
        after TITLE_RECHECK_S (a stat is 0.1 ms on Windows, every frame); the studio's own writes forget it."""
        cache = self.__dict__.setdefault("_titles", {})
        hit = cache.get(fname)
        now = time.monotonic()
        if hit and now - hit[2] < self.TITLE_RECHECK_S:
            return hit[1]
        try:
            mt = os.path.getmtime(self.effect_path(fname))
        except OSError:
            mt = None
        if hit and hit[0] == mt and mt is not None:
            cache[fname] = (mt, hit[1], now)
            return hit[1]
        try:
            m = re.search(r'PROGMEM\s*=\s*"([^@"]+)', self.read_effect(fname))
            title = m.group(1) if m else fname
        except Exception:
            title = fname
        cache[fname] = (mt, title, now)
        return title

    # --- export ---------------------------------------------------------------------
    def export(self, files=None, deps=(), requires=()):
        """ledmap.json for the geometry and a usermod folder with the effects
        (the list, or the `files` given); `deps` names the features whose
        firmware files go in the folder too, `requires` what the README
        says the effects need. Returns the export directory."""
        out = os.path.join(self.path, "export")
        with open(os.path.join(out, "ledmap.json"), "w", encoding="utf-8") as f:
            json.dump(self.geometry.ledmap(), f)
        um = os.path.join(out, "usermod_studio")
        if os.path.isdir(um):
            shutil.rmtree(um)                     # nothing from a previous, larger selection
        os.makedirs(um, exist_ok=True)
        files = [f for f in (files if files is not None else self.build_files()) if f in self.effect_files()]
        for fname in files:
            shutil.copyfile(self.effect_path(fname), os.path.join(um, fname))
        # what the effects include and register through, so the folder
        # builds on its own as a usermod: the two headers, the bank's
        # implementation, and a library.json PlatformIO can pick up
        for h in ("cube_fx_common.h", "cube_fx_bank.h", "cube_fx_bank.cpp", "cube_fx_imu.h"):
            src = os.path.join(paths.firmware_dir(), h)
            if os.path.exists(src):
                shutil.copyfile(src, os.path.join(um, h))
        # the firmware behind a feature the effects need, when asked for
        from native.flash import DEPENDENCIES
        dep_files = []
        for k in deps:
            for rel in DEPENDENCIES.get(k, {}).get("files", []):
                src = os.path.join(ROOT, rel) if ROOT else ""
                if os.path.exists(src):
                    shutil.copyfile(src, os.path.join(um, os.path.basename(rel)))
                    dep_files.append(os.path.basename(rel))
        with open(os.path.join(um, "library.json"), "w", encoding="utf-8") as f:
            json.dump({"name": "usermod_studio", "version": "1.0.0",
                       "description": "Effects written in the WLED Effects Studio",
                       "build": {"libArchive": False}}, f, indent=2)
        titles = [self.effect_title(f) for f in files]
        g = self.geometry
        with open(os.path.join(um, "README.md"), "w", encoding="utf-8") as f:
            f.write("# Studio export\n\n"
                    f"Effects written in the WLED Effects Studio for: {g.describe()}.\n\n"
                    "## Effects\n\n" + "".join(f"- {t}\n" for t in titles) + "\n"
                    + ("## Needs\n\n" + "".join(f"- {DEPENDENCIES[k]['label']}: {DEPENDENCIES[k]['note']}\n" for k in requires if k in DEPENDENCIES)
                       + (f"\nIncluded here: {', '.join(dep_files)}.\n" if dep_files else
                          "\nNot included here: build against a tree that has them, or export again with them.\n" if any(not DEPENDENCIES[k]["standard"] for k in requires if k in DEPENDENCIES) else "")
                       + "\n" if requires else "")
                    + "## Building\n\n"
                    "1. Copy this folder into `usermods/` of a WLED source tree (0.15 / 16.x).\n"
                    "2. Add it to the build: in `platformio_override.ini`, under your environment,\n"
                    "   `custom_usermods = usermod_studio` (append to the list if there is one).\n"
                    "   The effects register through `cube_fx_bank.h`, which is included here.\n"
                    "3. Build and upload the firmware.\n"
                    "4. Upload `ledmap.json` to the device: LED Preferences, or\n"
                    "   `curl -F \"data=@ledmap.json;filename=/ledmap.json\" http://<device>/upload`\n"
                    "   then enable it under LED Preferences.\n\n"
                    f"The segment should be {g.w} x {g.h}" + (" (a 2-D matrix)" if g.is2d else " (1-D)") + ".\n")
        # one file to hand over
        zip_path = os.path.join(out, "studio_export.zip")
        import zipfile
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
            z.write(os.path.join(out, "ledmap.json"), "ledmap.json")
            for fn in os.listdir(um):
                z.write(os.path.join(um, fn), f"usermod_studio/{fn}")
        return out

    def send_ledmap(self, host, ledmap=None):
        """Upload ledmap.json to a device over WLED's /upload form, as the
        web UI does. Returns a message for the status line. `ledmap`: the
        one to send, made on the main thread when this runs on a worker
        (the geometry can change under it); else this project's."""
        host = (host or "").strip().rstrip("/")
        if not host:
            return "type the device's address first"
        if not host.startswith("http"):
            host = "http://" + host
        import urllib.request
        body = json.dumps(self.geometry.ledmap() if ledmap is None else ledmap).encode()
        boundary = "----studio" + str(int(time.time()))
        data = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"data\"; filename=\"/ledmap.json\"\r\n"
                "Content-Type: application/json\r\n\r\n").encode() + body + f"\r\n--{boundary}--\r\n".encode()
        req = urllib.request.Request(host + "/upload", data=data,
                                     headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                r.read()
            return f"ledmap.json ({len(body)} bytes) sent to {host} - enable it under LED Preferences"
        except Exception as e:
            return f"upload failed: {e}"


STUDIO_FILE = os.path.join(PROJECTS, "studio.json")     # what is not any one project's: the last one opened


# what a project zip leaves out: the history's copies, the export's build products
# backups (a device's settings) and firmware (the images flashed, megabytes each) stay with the project, not in its zip
ZIP_SKIP = ("history", "export", "__pycache__", "backups", "firmware")


def zip_project(project, path=None):
    """The whole project - project.json, effects, graphs, sub-graphs, user
    nodes, assets, recipes - as one zip (in captures/ by default, named
    after the project and the day). Returns the zip's path."""
    import zipfile
    name = os.path.basename(project.path.rstrip("/\\")) or "project"
    if path is None:
        os.makedirs(paths.CAPTURES, exist_ok=True)
        path = os.path.join(paths.CAPTURES, f"{name}_{time.strftime('%Y%m%d')}.zip")
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for d, dirs, files in os.walk(project.path):
            dirs[:] = [x for x in dirs if x not in ZIP_SKIP]
            for f in files:
                full = os.path.join(d, f)
                z.write(full, os.path.join(name, os.path.relpath(full, project.path)))
    return path


def unzip_project(path, name=None):
    """A project zip into projects/<name> (the zip's own top folder, or the
    file's stem; a name already taken gets a number). Returns the project
    folder, or raises with why not."""
    import zipfile
    with zipfile.ZipFile(path) as z:
        names = [n for n in z.namelist() if not n.endswith("/")]
        tops = {n.split("/")[0] for n in names if "/" in n}
        top = tops.pop() if len(tops) == 1 and all("/" in n for n in names) else None
        inside = [n[len(top) + 1:] if top else n for n in names]
        if "project.json" not in inside and not any(n.startswith("effects/") or n.startswith("graphs/") for n in inside):
            raise ValueError("not a project zip: no project.json, effects/ or graphs/ in it")
        base = _ident(name or top or os.path.splitext(os.path.basename(path))[0]) or "project"
        dest, k = os.path.join(PROJECTS, base), 2
        while os.path.exists(dest):
            dest = os.path.join(PROJECTS, f"{base}_{k}"); k += 1
        os.makedirs(dest)
        for n, rel in zip(names, inside):
            out = _inside(dest, rel)
            if out is None:
                continue                                          # nothing outside the folder
            os.makedirs(os.path.dirname(out), exist_ok=True)
            with z.open(n) as src, open(out, "wb") as f:
                shutil.copyfileobj(src, f)
    return dest


def _inside(dest, rel):
    """Where a zip entry's path lands under dest - or None when it would
    land anywhere else. The name is not trusted to say: a drive letter
    ("D:/x.txt") makes os.path.join drop dest on Windows, a backslash is a
    separator there too, and a colon also names an NTFS stream
    ("a.cpp:hidden") - so any part with a colon is refused, and the path is
    resolved and compared with the folder (issue #8)."""
    parts = [p for p in rel.replace("\\", "/").split("/") if p not in ("", ".")]
    if not parts or rel.startswith(("/", "\\")) or any(p == ".." or ":" in p for p in parts):
        return None
    out = os.path.realpath(os.path.join(dest, *parts))
    root = os.path.realpath(dest)
    try:
        if os.path.commonpath([out, root]) != root or out == root:
            return None
    except ValueError:                                            # another drive altogether
        return None
    return out


def list_projects():
    """Project folder names under projects/, the ones with a project.json
    or an effects folder."""
    os.makedirs(PROJECTS, exist_ok=True)
    out = []
    for d in sorted(os.listdir(PROJECTS)):
        p = os.path.join(PROJECTS, d)
        if os.path.isdir(p) and (os.path.exists(os.path.join(p, "project.json")) or os.path.isdir(os.path.join(p, "effects"))):
            out.append(d)
    return out


def _studio():
    """studio.json: the prefs, the last project and the recent ones. One that does not read is put aside as
    studio.json.bad-<time> (as a project.json is) - it read as {}, and the next save wrote that over it."""
    try:
        with open(STUDIO_FILE, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except FileNotFoundError:
        return {}
    except Exception:
        try:
            os.replace(STUDIO_FILE, f"{STUDIO_FILE}.bad-{time.strftime('%Y%m%d-%H%M%S')}")
        except OSError:
            pass
        return {}


def _studio_save(d):
    """Whole or not at all: made into text first (a value json cannot write - a numpy number - raised once
    the file was already emptied), then written by write_atomic."""
    os.makedirs(PROJECTS, exist_ok=True)
    text = json.dumps(d, indent=1, default=lambda o: o.item() if hasattr(o, "item") else str(o))
    write_atomic(STUDIO_FILE, text)


def last_project():
    return _studio().get("last")


def remember_project(path):
    d = _studio(); d["last"] = path
    recent = [p for p in d.get("recent", []) if p != path]
    d["recent"] = [path] + recent[:9]
    _studio_save(d)


def recent_projects():
    """The last ten projects opened, newest first, the ones still there."""
    return [p for p in _studio().get("recent", []) if os.path.isdir(p)]


def load_prefs():
    """UI preferences that belong to the app, not a project: pane splits,
    the side panel's width, the node editor's zoom."""
    ui = _studio().get("ui", {})
    return dict(ui) if isinstance(ui, dict) else {}           # another shape: the defaults, not a raise at the start


def pref_num(prefs, key, default):
    """A number from the prefs, the default when it is not one (a hand edit, another version): float() of a
    string or a list raised where it was read - in the start, a draw."""
    try:
        v = float(prefs.get(key, default))
        return v if v == v and abs(v) != float("inf") else float(default)
    except (TypeError, ValueError, OverflowError):
        return float(default)


def save_prefs(prefs):
    d = _studio(); d["ui"] = dict(prefs); _studio_save(d)


def project_path(name_or_path):
    """A project folder from what was typed: a path (absolute, or with a
    folder in it) as it is, else a name under projects/. A bare name that
    happened to be a folder where the studio was started ("docs", "tests",
    "native") was taken as that folder, and the project's folders and
    files were written into it."""
    s = str(name_or_path)
    if os.path.isabs(s) or ((os.sep in s or "/" in s) and os.path.isdir(s)):
        return os.path.abspath(s)
    return os.path.join(PROJECTS, _ident(name_or_path) or "default")


def default_project():
    """The project the app opens with: the last one used, else default."""
    last = last_project()
    if last and os.path.isdir(last):
        return Project(last)
    return Project(os.path.join(PROJECTS, "default"))
