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

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.dirname(HERE)
PROJECTS = os.path.join(HERE, "projects")

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

    def load(self):
        if not os.path.exists(self.file):
            self.save()
            return
        try:
            d = json.load(open(self.file, encoding="utf-8"))
        except Exception:
            return
        try:
            self.geometry = Geometry.from_json(d.get("geometry", {}))
        except Exception:
            self.geometry = Geometry("cube", B=16)
        self.selected = d.get("selected", "")
        self.options = d.get("options", {})
        self.imported = [f for f in d.get("imported", []) if isinstance(f, str)]

    def save(self):
        d = {"geometry": self.geometry.to_json(), "selected": self.selected,
             "options": self.options, "imported": self.imported,
             "saved": time.strftime("%Y-%m-%d %H:%M:%S")}
        with open(self.file, "w", encoding="utf-8") as f:
            json.dump(d, f, indent=1)

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
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)

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
        if new != fname:
            os.remove(self.effect_path(fname))
            if fname in self.imported:
                self.imported = [new if f == fname else f for f in self.imported]
                self.save()
        self.write_effect(new, src)
        return new

    def effect_title(self, fname):
        """The name the effect registers, from its metadata string."""
        try:
            m = re.search(r'PROGMEM\s*=\s*"([^@"]+)', self.read_effect(fname))
            return m.group(1) if m else fname
        except Exception:
            return fname

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
            src = os.path.join(ROOT, "usermods", "cube_fx", h)
            if os.path.exists(src):
                shutil.copyfile(src, os.path.join(um, h))
        # the firmware behind a feature the effects need, when asked for
        from native.flash import DEPENDENCIES
        dep_files = []
        for k in deps:
            for rel in DEPENDENCIES.get(k, {}).get("files", []):
                src = os.path.join(ROOT, rel)
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

    def send_ledmap(self, host):
        """Upload ledmap.json to a device over WLED's /upload form, as the
        web UI does. Returns a message for the status line."""
        host = (host or "").strip().rstrip("/")
        if not host:
            return "type the device's address first"
        if not host.startswith("http"):
            host = "http://" + host
        import urllib.request
        body = json.dumps(self.geometry.ledmap()).encode()
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
    try:
        return json.load(open(STUDIO_FILE, encoding="utf-8"))
    except Exception:
        return {}


def _studio_save(d):
    os.makedirs(PROJECTS, exist_ok=True)
    with open(STUDIO_FILE, "w", encoding="utf-8") as f:
        json.dump(d, f, indent=1)


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
    return dict(_studio().get("ui", {}))


def save_prefs(prefs):
    d = _studio(); d["ui"] = dict(prefs); _studio_save(d)


def project_path(name_or_path):
    """A project folder from what was typed: an existing directory as it
    is, else a name under projects/."""
    if os.path.isdir(name_or_path) or os.path.isabs(name_or_path):
        return os.path.abspath(name_or_path)
    return os.path.join(PROJECTS, _ident(name_or_path) or "default")


def default_project():
    """The project the app opens with: the last one used, else default."""
    last = last_project()
    if last and os.path.isdir(last):
        return Project(last)
    return Project(os.path.join(PROJECTS, "default"))
