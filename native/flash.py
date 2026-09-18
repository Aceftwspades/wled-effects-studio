"""Build the firmware with the project's effects in it, and send it to the device.

The export already makes a usermod folder. This stages it into the WLED
tree's `usermods/`, writes an environment into `platformio_override.ini`
that extends the one chosen - its usermods plus ours - runs PlatformIO on
it, and posts the binary to the device's `/update`, as the web UI's update
page does. Everything runs on a worker; the lines it prints go to a queue
the dialog drains.

    job = Job(project, base_env="esp32dev_customfx", host="192.168.1.50", build=True, upload=True)
    job.start()
    while not job.done: line = job.q.get_nowait() ...
"""
import configparser
import os
import queue
import shutil
import subprocess
import sys
import threading
import time
import urllib.request

from native.project import ROOT

USERMOD = "usermod_studio"
MARK_BEGIN = ";; --- WLED Effects Studio: generated environment (rewritten on every flash) ---"
MARK_END = ";; --- end WLED Effects Studio ---"


def pio_exe():
    """PlatformIO's command line, on the path or in its own virtualenv."""
    p = shutil.which("pio") or shutil.which("platformio")
    if p:
        return p
    home = os.path.expanduser("~/.platformio/penv")
    for c in (os.path.join(home, "Scripts", "pio.exe"), os.path.join(home, "bin", "pio")):
        if os.path.exists(c):
            return c
    return None


def _ini(path):
    cp = configparser.ConfigParser(interpolation=None, strict=False)
    cp.optionxform = str
    if os.path.exists(path):
        cp.read(path, encoding="utf-8")
    return cp


def read_envs():
    """([env names], default) from platformio.ini and the override; the
    studio's own generated envs are left out of the list."""
    base = _ini(os.path.join(ROOT, "platformio.ini"))
    over = _ini(os.path.join(ROOT, "platformio_override.ini"))
    names = []
    for cp in (over, base):                       # the user's own first
        for sec in cp.sections():
            if sec.startswith("env:") and not sec.startswith("env:studio_") and sec[4:] not in names:
                names.append(sec[4:])
    default = None
    for cp in (over, base):
        if cp.has_option("platformio", "default_envs"):
            default = cp.get("platformio", "default_envs").split(",")[0].strip().split("\n")[0]
            break
    if default and default.startswith("studio_"):
        default = default[7:]
    return names, default if default in names else (names[0] if names else None)


def usermods_of(env):
    """The custom_usermods an env ends up with, following `extends`."""
    base = _ini(os.path.join(ROOT, "platformio.ini"))
    over = _ini(os.path.join(ROOT, "platformio_override.ini"))
    seen = set()
    while env and env not in seen:
        seen.add(env)
        sec = "env:" + env
        for cp in (over, base):
            if cp.has_section(sec):
                if cp.has_option(sec, "custom_usermods"):
                    return [u.strip() for u in cp.get(sec, "custom_usermods").replace(",", "\n").split("\n") if u.strip()]
                nxt = cp.get(sec, "extends", fallback=None)
                env = nxt.strip()[4:] if nxt and nxt.strip().startswith("env:") else None
                break
        else:
            env = None
    return []


def size_tool():
    """A toolchain's `size`, for the objects' text + data - any xtensa or
    riscv one reads any ELF object."""
    import glob
    home = os.path.expanduser("~/.platformio/packages")
    for pat in ("toolchain-xtensa-esp32s3/bin/*-size*", "toolchain-xtensa-esp32/bin/*-size*", "toolchain-*/bin/*-size*"):
        for p in glob.glob(os.path.join(home, pat)):
            if p.endswith((".exe", "size")):
                return p
    return None


def effect_sizes(env):
    """{effect file: flash bytes} for the studio effects of a built env, from
    their object files: text + data is what the linker places in flash."""
    import glob
    tool = size_tool()
    objs = glob.glob(os.path.join(ROOT, ".pio", "build", env, "lib*", USERMOD, "*.cpp.o"))
    if not tool or not objs:
        return {}
    try:
        flags = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
        out = subprocess.run([tool] + objs, capture_output=True, text=True, timeout=60, **flags).stdout
    except Exception:
        return {}
    # Objects of effects staged for an earlier build stay in the build
    # directory; only what is staged now was linked.
    staged = set(os.listdir(os.path.join(ROOT, "usermods", USERMOD))) if os.path.isdir(os.path.join(ROOT, "usermods", USERMOD)) else set()
    sizes = {}
    for line in out.splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 6 and parts[0].isdigit():
            stem = os.path.basename(parts[-1])
            if stem.endswith(".cpp.o") and stem != "cube_fx_bank.cpp.o" and stem[:-2] in staged:
                sizes[stem[:-2]] = int(parts[0]) + int(parts[1])
    return sizes


# --- features: what the firmware carries -----------------------------------------------
# Not every setup has a motion sensor, a knob and a screen; the picker in the
# flash dialog leaves out what a device lacks. Each is a build flag the
# firmware defaults ON (a build outside the studio is unchanged); the studio
# passes =0 for what is unticked. `nodes`: the node types that lean on it,
# from the library's `needs` (nodedefs.py), for the picker's description.
FEATURES = [
    ("imu", "IMU - MPU6050 motion sensor", "ace_imu_mpu6050.cpp", "CFX_WITH_IMU",
     "the Gravity node's sensor output, and motion in Gyro Sand, Gyro Rain, Liquid, Cube Fire, Sauron, Cube Wire, "
     "Mario Block and Audio Atlas. Without it those settle to 'top face up' and Gravity follows its tilt inputs."),
    ("ui", "Rotary encoder + OLED menu", "ace_ui_encoder / menu / screen.cpp, the U8g2 library", "CFX_WITH_UI",
     "the on-device menu (effects, palettes, presets, system). Nothing in the studio needs it; Breakout is played "
     "from the knob when it is there."),
    ("param_memory", "Per-effect slider memory", "cube_fx_param_memory.cpp", "CFX_WITH_PARAM_MEMORY",
     "the device remembers each effect's sliders across switches."),
]
AUDIO = [
    ("pcm", "audioreactive with the PCM waveform (the studio's patch)",
     "the FFT bands, volume and beat, and the raw waveform: Warp and Scope draw the real signal."),
    ("stock", "audioreactive as WLED ships it",
     "the FFT bands, volume and beat; Warp and Scope rebuild a waveform from the bins (-D CFX_PCM=0)."),
    ("none", "no audio usermod",
     "the smallest firmware: audio nodes and effects read WLED's simulated sound (audioreactive left out of the env)."),
]
DEFAULTS = {"imu": True, "ui": True, "param_memory": True, "audio": "pcm"}       # a project from before: as it built
NEW_DEFAULTS = {"imu": False, "ui": False, "param_memory": True, "audio": "pcm"}  # a new project: no hardware assumed


# What a feature is made of, for handing a graph or an effect to someone
# else: the firmware files that are ours (bundled on export, installed on
# import) and what the receiving tree must have anyway. `standard` marks
# what every WLED tree carries, which is never bundled. A node's `needs`
# names the feature; an effect's C++ betrays it by the helper it calls.
DEPENDENCIES = {
    "imu": {"label": "the IMU driver (MPU6050)", "files": ["usermods/cube_fx/ace_imu_mpu6050.cpp", "usermods/cube_fx/cube_fx_imu.h"],
            "marker": "cfx_imu(", "standard": False,
            "note": "registers itself as a usermod; needs the sensor on I2C and CFX_WITH_IMU=1 (the default)"},
    "audio": {"label": "the audioreactive usermod", "files": [], "marker": "cfx_getAudioData(", "standard": True,
              "note": "WLED's own audioreactive, in custom_usermods (the studio's PCM waveform patch is optional)"},
}


def requirements_of_graph(graph, lib, resolve=None):
    """The features a graph's nodes lean on, sub-graphs included: a set of
    keys from the library's `needs`."""
    out, seen = set(), set()
    def walk(g):
        for n in g.nodes.values():
            d = lib.get(n["type"])
            if d and d.get("needs"):
                out.add(d["needs"])
            if n["type"].startswith("sub:") and resolve and n["type"] not in seen:
                seen.add(n["type"])
                sub = resolve(n["type"][4:])
                if sub is not None:
                    walk(sub)
    walk(graph)
    return out


def requirements_of_code(text):
    """The features a C++ effect calls on, by the helpers it uses."""
    return {k for k, d in DEPENDENCIES.items() if d["marker"] and d["marker"] in text}


def dependency_files(keys):
    """{path relative to the WLED tree: text} for the bundled files of these features."""
    out = {}
    for k in keys:
        for rel in DEPENDENCIES.get(k, {}).get("files", []):
            p = os.path.join(ROOT, rel)
            if os.path.exists(p):
                out[rel] = open(p, encoding="utf-8", errors="replace").read()
    return out


def install_dependency_files(files):
    """Bundled firmware files into this tree, where the tree lacks them.
    Returns the paths written."""
    written = []
    for rel, text in (files or {}).items():
        rel = rel.replace("\\", "/")
        if not rel.startswith("usermods/") or ".." in rel:
            continue                                    # only usermod sources, only under usermods/
        p = os.path.join(ROOT, *rel.split("/"))
        if os.path.exists(p):
            continue
        os.makedirs(os.path.dirname(p), exist_ok=True)
        open(p, "w", encoding="utf-8", newline="\n").write(text)
        written.append(rel)
    return written


def missing_features(project, keys):
    """Of these required features, the ones this project's picker leaves out."""
    f = features_of(project)
    out = set()
    for k in keys:
        if k == "audio" and f.get("audio") == "none":
            out.add(k)
        elif k != "audio" and f.get(k) is False:
            out.add(k)
    return out


def features_of(project):
    f = dict(DEFAULTS)
    opts = project.options.get("features") or {}
    f.update({k: v for k, v in opts.items() if k in f})
    if f["audio"] not in {a[0] for a in AUDIO}:
        f["audio"] = "pcm"
    # the usermods the manager lists: {folder name: on}, over the env's own
    f["usermods"] = {str(k): bool(v) for k, v in (opts.get("usermods") or {}).items()}
    return f


# --- usermods: WLED's own, managed per project ---------------------------------------
# Every folder under usermods/ is one; the environment names the ones it
# builds (custom_usermods). The manager (Settings > Usermods) lets a project
# add any from the tree, import one from a folder or a zip, turn one off
# that the env would build, and drop one from its list. The staged env's
# custom_usermods is the base env's list with the project's changes on it.
UM_DIR = os.path.join(ROOT, "usermods")
CORE = ("cube_fx", "audioreactive")            # the two the studio itself leans on


def usermod_dirs():
    """The usermod folders in this tree, by name."""
    if not os.path.isdir(UM_DIR):
        return []
    out = []
    for n in sorted(os.listdir(UM_DIR), key=str.lower):
        p = os.path.join(UM_DIR, n)
        if os.path.isdir(p) and (os.path.exists(os.path.join(p, "library.json"))
                                 or any(f.endswith((".cpp", ".h")) for f in os.listdir(p))):
            out.append(n)
    return out


def usermod_info(name):
    """A line about a usermod: library.json's description, else the
    README's first line of prose, else nothing."""
    import json
    p = os.path.join(UM_DIR, name)
    try:
        d = json.load(open(os.path.join(p, "library.json"), encoding="utf-8"))
        if d.get("description"):
            return str(d["description"]).strip()
    except Exception:
        pass
    for rd in ("README.md", "readme.md", "README.txt"):
        try:
            for line in open(os.path.join(p, rd), encoding="utf-8", errors="replace"):
                t = line.strip()
                if t and not t.startswith(("#", "!", "[", "|", "-", "<", "```")):
                    return t[:160]
        except OSError:
            continue
    return ""


def usermod_rows(project, base_env):
    """What the manager shows: [(name, on, source)] - the env's own first,
    then the project's additions; source is "env" or "project"."""
    f = features_of(project)
    base = usermods_of(base_env) if base_env else []
    rows = []
    for n in base:
        rows.append((n, f["usermods"].get(n, True), "env"))
    for n, on in f["usermods"].items():
        if n not in base:
            rows.append((n, on, "project"))
    return rows


def staged_usermods(project, base_env):
    """The custom_usermods the studio's env gets."""
    f = features_of(project)
    mods = [m for m in usermods_of(base_env)]
    for n, on in f["usermods"].items():
        if on and n not in mods:
            mods.append(n)
        elif not on and n in mods:
            mods.remove(n)
    if f["audio"] == "none":
        mods = [m for m in mods if m != "audioreactive"]
    return mods


def import_usermod(path):
    """A usermod folder, or a zip of one, copied into this tree's
    usermods/. Returns the folder name, or raises with the reason."""
    import shutil, zipfile, tempfile
    path = os.path.abspath(path)
    if not os.path.exists(path):
        raise ValueError(f"no such path: {path}")
    src = path
    tmp = None
    if os.path.isfile(path) and path.lower().endswith(".zip"):
        tmp = tempfile.mkdtemp(prefix="studio_um_")
        with zipfile.ZipFile(path) as z:
            for m in z.namelist():
                if m.startswith("/") or ".." in m:
                    raise ValueError("the zip reaches outside its folder")
            z.extractall(tmp)
        kids = [k for k in os.listdir(tmp) if not k.startswith("__MACOSX")]
        src = os.path.join(tmp, kids[0]) if len(kids) == 1 and os.path.isdir(os.path.join(tmp, kids[0])) else tmp
    if not os.path.isdir(src):
        raise ValueError("a usermod is a folder (or a zip of one)")
    files = os.listdir(src)
    if not (any(f.endswith((".cpp", ".h")) for f in files) or "library.json" in files):
        raise ValueError("no .cpp, .h or library.json inside - not a usermod")
    name = os.path.basename(path)[:-4] if path.lower().endswith(".zip") else os.path.basename(src)
    name = "".join(c if (c.isalnum() or c in "_-+") else "_" for c in name) or "usermod"
    dst = os.path.join(UM_DIR, name)
    if os.path.abspath(src) == os.path.abspath(dst):
        return name
    if os.path.exists(dst):
        raise ValueError(f"usermods/{name} exists already - remove it first, or add the existing one")
    shutil.copytree(src, dst)
    if tmp:
        shutil.rmtree(tmp, ignore_errors=True)
    return name


def feature_flags(project):
    """The -D flags the picker adds to the studio's env."""
    f = features_of(project)
    flags = [f"-D {flag}=0" for key, _, _, flag, _ in FEATURES if not f.get(key)]
    if f["audio"] == "stock":
        flags.append("-D CFX_PCM=0")
    g = project.geometry
    if g.kind == "cube" and g.params.get("six"):
        flags.append("-D CFX_SIX_FACES=1")
    return flags


def stage(project, base_env, log, only=None):
    """Export (the effects chosen, or the list), copy the usermod into the
    tree, write the env. Returns the env name to build."""
    from native.script import write_helpers
    write_helpers()                              # the Script effect's copy of the gc_* helpers
    out = project.export(only)
    src = os.path.join(out, USERMOD)
    dst = os.path.join(ROOT, "usermods", USERMOD)
    if os.path.isdir(dst):
        shutil.rmtree(dst)
    shutil.copytree(src, dst)
    mods = staged_usermods(project, base_env)
    base = usermods_of(base_env)
    added = [m for m in mods if m not in base]
    dropped = [m for m in base if m not in mods]
    if added or dropped:
        log("usermods: " + ", ".join(["+" + m for m in added] + ["-" + m for m in dropped]))
    if "cube_fx" in mods:
        # The effects register through cube_fx's bank; a second copy of the
        # bank's usermod would be the same class twice.
        for f in ("cube_fx_bank.cpp",):
            p = os.path.join(dst, f)
            if os.path.exists(p):
                os.remove(p)
        log(f"staged {USERMOD} beside cube_fx (its bank is shared; the effects take bank slots)")
    else:
        log(f"staged {USERMOD} with its own bank")
    env = "studio_" + base_env
    lines = [MARK_BEGIN, f"[env:{env}]", f"extends = env:{base_env}", "custom_usermods ="]
    lines += [f"  {m}" for m in mods if m != USERMOD] + [f"  {USERMOD}"]
    flags = feature_flags(project)
    if flags:
        # the features left out, and a lit bottom face: the firmware's defaults, before its settings say otherwise
        lines += [f"build_flags = ${{env:{base_env}.build_flags}} " + " ".join(flags)]
        log("build flags: " + " ".join(flags))
    lines += [MARK_END, ""]
    path = os.path.join(ROOT, "platformio_override.ini")
    text = open(path, encoding="utf-8").read() if os.path.exists(path) else "[platformio]\n"
    if MARK_BEGIN in text and MARK_END in text:
        a, b = text.index(MARK_BEGIN), text.index(MARK_END) + len(MARK_END)
        text = text[:a] + "\n".join(lines).rstrip("\n") + text[b:]
    else:
        text = text.rstrip("\n") + "\n\n" + "\n".join(lines)
    open(path, "w", encoding="utf-8", newline="\n").write(text)
    log(f"environment [env:{env}] written to platformio_override.ini")
    # A new env fetches its libraries afresh from the registry. The base
    # env has them already: start from its copy, so the first build needs
    # no network and takes no longer than the base's would.
    src_deps = os.path.join(ROOT, ".pio", "libdeps", base_env)
    dst_deps = os.path.join(ROOT, ".pio", "libdeps", env)
    if os.path.isdir(src_deps) and not os.path.isdir(dst_deps):
        shutil.copytree(src_deps, dst_deps)
        log(f"libraries seeded from {base_env}")
    return env


def firmware_bin(env):
    return os.path.join(ROOT, ".pio", "build", env, "firmware.bin")


def upload(host, path, log, timeout=180):
    """POST the binary to /update. The device checks the subnet, its PIN
    and its OTA lock, and reboots on success."""
    host = (host or "").strip().rstrip("/")
    if not host:
        return False, "no device address"
    if not host.startswith("http"):
        host = "http://" + host
    data = open(path, "rb").read()
    boundary = "----studio" + str(int(time.time()))
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"update\"; filename=\"firmware.bin\"\r\n"
            "Content-Type: application/octet-stream\r\n\r\n").encode() + data + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(host + "/update", data=body,
                                 headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    log(f"sending {len(data) // 1024} KB to {host}/update ...")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            page = r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        page = e.read().decode("utf-8", "replace")
        return False, f"the device answered {e.code}: " + _message(page)
    except Exception as e:
        return False, f"upload failed: {e}"
    return True, _message(page) or "sent - the device is rebooting"


def send_script(host, prog, log=lambda m: None):
    """The bytecode to the device as /studio.bin over /upload; the Studio
    Script effect there picks it up within two seconds."""
    host = (host or "").strip().rstrip("/")
    if not host:
        return False, "no device address"
    if not host.startswith("http"):
        host = "http://" + host
    boundary = "----studio" + str(int(time.time()))
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"data\"; filename=\"/studio.bin\"\r\n"
            "Content-Type: application/octet-stream\r\n\r\n").encode() + bytes(prog) + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(host + "/upload", data=body,
                                 headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            r.read()
    except Exception as e:
        return False, f"upload failed: {e}"
    return True, f"{len(prog)} bytes of script sent to {host} as /studio.bin"


def device_info(host, timeout=4):
    """The device's /json/info as a dict, or None."""
    host = (host or "").strip().rstrip("/")
    if not host.startswith("http"):
        host = "http://" + host
    try:
        with urllib.request.urlopen(host + "/json/info", timeout=timeout) as r:
            import json
            return json.loads(r.read().decode("utf-8", "replace"))
    except Exception:
        return None


def verify_reboot(host, before, log, timeout=90):
    """After an OTA: wait for the device to come back and say what it runs
    now - its version and build id - and whether the build changed."""
    t0 = time.time()
    time.sleep(6)
    while time.time() - t0 < timeout:
        info = device_info(host)
        if info:
            ver, vid = info.get("ver", "?"), info.get("vid", "?")
            was = (before or {}).get("vid")
            if was is not None and vid == was:
                return False, f"the device is back on the SAME build ({ver}, {vid}) - the update did not take"
            return True, f"the device is back: WLED {ver}, build {vid}" + (f" (was {was})" if was is not None else "")
        time.sleep(3)
    return False, "the device did not answer within a minute and a half after the update - check it"


def _message(page):
    """The text of WLED's message page, without its markup."""
    import re
    t = re.sub(r"<script.*?</script>", "", page, flags=re.S)
    t = re.sub(r"<[^>]+>", " ", t)
    return " ".join(t.split())[:200]


def _get_json(host, path, timeout=5):
    import json
    with urllib.request.urlopen(host + path, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def push_settings(host, effect, params, palette, colours, seg_id=0, blend=None, opacity=None, six=None):
    """The current effect and its settings to the device's first segment
    over /json/state: the effect and palette found by NAME in the device's
    own lists (its ids are its own), the sliders, the checkboxes, the three
    colours; and, for a cube, whether it has six faces (the CubeFXBank
    usermod's setting, over /json/cfg). Returns (ok, message)."""
    import json
    host = (host or "").strip().rstrip("/")
    if not host:
        return False, "no device address"
    if not host.startswith("http"):
        host = "http://" + host
    try:
        names = _get_json(host, "/json/effects")
        pals = _get_json(host, "/json/palettes")
    except Exception as e:
        return False, f"could not read the device's lists: {e}"
    want = effect.split("@")[0].strip().lower()
    clean = [str(n).split("@")[0].strip().lower() for n in names]
    fx = next((i for i, n in enumerate(clean) if n == want), None)
    if fx is None:
        # a firmware from before a rename: the name with a family prefix ("Ace 3-D Studio Script")
        fx = next((i for i, n in enumerate(clean) if n.endswith(" " + want) or want.endswith(" " + n)), None)
    if fx is None:
        return False, f"the device has no effect called {effect!r} - flash the firmware with it first"
    seg = {"id": int(seg_id), "fx": fx, "sx": int(params.get("sx", 128)), "ix": int(params.get("ix", 128)),
           "c1": int(params.get("c1", 128)), "c2": int(params.get("c2", 128)), "c3": int(params.get("c3", 16)),
           "o1": bool(params.get("o1")), "o2": bool(params.get("o2")), "o3": bool(params.get("o3")),
           "col": [[(c >> 16) & 255, (c >> 8) & 255, c & 255] for c in colours]}
    if blend is not None:
        seg["bm"] = int(blend)                       # the segment's blend mode, as index.js sends it
    if opacity is not None:
        seg["bri"] = int(opacity)
    pal = next((i for i, n in enumerate(pals) if str(n).strip().lower() == (palette or "").strip().lower()), None)
    if pal is not None:
        seg["pal"] = pal
    body = json.dumps({"on": True, "seg": [seg]}).encode()
    req = urllib.request.Request(host + "/json/state", data=body, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            r.read()
    except Exception as e:
        return False, f"the device refused the state: {e}"
    note = "" if pal is not None else f" (palette {palette!r} not on the device; left as is)"
    if six is not None:
        body = json.dumps({"um": {"CubeFXBank": {"six_faces": bool(six)}}}).encode()
        req = urllib.request.Request(host + "/json/cfg", data=body, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                r.read()
            note += f"; {'six' if six else 'five'} faces"
        except Exception as e:
            note += f" (the six-face setting was not taken: {e})"
    return True, f"{effect} with its settings sent to {host} as effect {fx}" + note


def advice(stats, env):
    """What to do about a firmware that does not fit, from what was measured:
    the effects' own sizes, and the rest - WLED, its usermods and the
    library code the studio's effects pull in - which no selection changes."""
    part, firm, sizes = stats["partition"], stats["firmware"], stats["sizes"]
    total = sum(sizes.values())
    base = firm - total
    over = firm - part
    if base > part:
        return (f"the firmware is {over // 1024} KB over this environment's app partition ({part // 1024} KB), and "
                f"{(base - part) // 1024} KB of that is not the effects: WLED with {env}'s usermods and the studio's "
                f"runtime comes to {base // 1024} KB on its own. No selection fits. Drop a usermod from {env}, or build "
                "for an environment with a bigger app partition (esp32dev_16M, an S3 with 16 MB).")
    avg = total / len(sizes) if sizes else 4096.0
    n = max(1, int(-(-over // avg)))
    return (f"the firmware is {over // 1024} KB over this environment's app partition ({part // 1024} KB): untick "
            f"{n} of the {len(sizes)} effects above (their measured sizes are beside them; the biggest first "
            "gets there soonest), or build for an environment with a bigger partition.")


class Job:
    def __init__(self, project, base_env, host, build=True, upload=True, only=None):
        self.project, self.base_env, self.host = project, base_env, host
        self.build, self.upload = build, upload
        self.only = only
        self.stats = None            # after a build: partition, firmware size, each effect's size
        self.q = queue.Queue()
        self.done = False
        self.ok = False
        self.result = ""
        self.proc = None
        self._cancel = False

    def log(self, line):
        self.q.put(line)

    def start(self):
        threading.Thread(target=self._run, daemon=True).start()

    def cancel(self):
        self._cancel = True
        if self.proc and self.proc.poll() is None:
            try:
                self.proc.terminate()
            except Exception:
                pass

    @staticmethod
    def _diagnose(line):
        """The two ways a build of many effects fails, in plain words."""
        import re
        m = re.search(r"program size \((\d+) bytes\) is greater than maximum allowed \((\d+) bytes\)", line)
        if m:
            over = int(m.group(1)) - int(m.group(2))
            return (f"the firmware is {over // 1024} KB over this environment's app partition "
                    f"({int(m.group(2)) // 1024} KB): untick about {max(1, -(-over // 4096))} effect(s) "
                    "above (~4 KB each - the sizes beside them are measured now), or build for an "
                    "environment with a bigger partition (esp32dev_16M, an S3 with 16 MB).")
        m = re.search(r"region `(\w+)' overflowed by (\d+) bytes", line)
        if m:
            return (f"the firmware needs {int(m.group(2)) // 1024} KB more RAM than the chip has ({m.group(1)}): "
                    "an effect keeps too much static state - fewer effects on the list, or fewer big "
                    "state nodes (Reaction diffusion, Shells) in them.")
        return None

    def _run(self):
        try:
            env = stage(self.project, self.base_env, self.log, self.only)
            if self.build:
                pio = pio_exe()
                if not pio:
                    self.result = "PlatformIO not found: install it (pip install platformio) or put pio on the path"
                    return
                self.log(f"{os.path.basename(pio)} run -e {env}   (in {ROOT})")
                t0 = time.time()
                flags = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
                self.proc = subprocess.Popen([pio, "run", "-e", env], cwd=ROOT, stdout=subprocess.PIPE,
                                             stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
                                             bufsize=1, **flags)
                why = None
                import re
                part = firm = None
                for line in self.proc.stdout:
                    line = line.rstrip()
                    if line:
                        self.log(line)
                        why = why or self._diagnose(line)
                        m = re.search(r"Flash: \[.*?\]\s+[\d.]+% \(used (\d+) bytes from (\d+) bytes\)", line)
                        if m:
                            firm, part = int(m.group(1)), int(m.group(2))
                        m = re.search(r"program size \((\d+) bytes\) is greater than maximum allowed \((\d+) bytes\)", line)
                        if m:
                            firm, part = int(m.group(1)), int(m.group(2))
                    if self._cancel:
                        break
                rc = self.proc.wait()
                sizes = effect_sizes(env)
                if part and firm:
                    known = dict((self.project.options.get("flash_stats") or {}).get(self.base_env, {}).get("sizes") or {})
                    known.update(sizes)
                    self.stats = {"partition": part, "firmware": firm, "sizes": sizes, "known": known}
                    self.log(f"measured: firmware {firm // 1024} KB of {part // 1024} KB; "
                             f"{len(sizes)} effect(s) {sum(sizes.values()) // 1024} KB together")
                    if firm > part:
                        why = advice(self.stats, self.base_env)
                if self._cancel:
                    self.result = "cancelled"; return
                if rc != 0:
                    self.result = why or f"build failed ({rc}) - the last lines above say why"; return
                self.log(f"built in {time.time() - t0:.0f} s")
            bin_ = firmware_bin(env)
            if not os.path.exists(bin_):
                self.result = f"no firmware at {bin_} - build first"; return
            self.log(f"firmware: {bin_} ({os.path.getsize(bin_) // 1024} KB)")
            if self.upload:
                before = device_info(self.host)
                if before:
                    self.log(f"device before: WLED {before.get('ver', '?')}, build {before.get('vid', '?')}, {before.get('name', '')}")
                ok, msg = upload(self.host, bin_, self.log)
                self.log(msg)
                if ok:
                    self.log("waiting for the device to reboot...")
                    ok, msg = verify_reboot(self.host, before, self.log)
                self.result = msg
                self.ok = ok
            else:
                self.result = "built; not sent"
                self.ok = True
        except Exception as e:
            self.result = f"failed: {e}"
        finally:
            self.done = True
