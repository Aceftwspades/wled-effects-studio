"""
The incremental engine build: one object per translation unit, cached, linked
into a VERSIONED shared library the running app can swap in.

Why this exists. The original build handed clang every source at once - fifty
translation units, ten seconds - and wrote one cubefx.dll, which the app held
open, so building while the app ran failed at the link and quietly left the old
code in place. Fine for a measurement harness; useless for an editor, where the
loop is "change a line, see it" and has to close in about a second.

Two changes make the editor loop possible:

  1. Objects are cached. A translation unit is recompiled only when it, or a
     header it can see, is newer than its object. Editing one effect is one
     compile plus one link.

  2. Output is versioned. Each link writes build/cubefx_<n>.dll and points
     build/latest at it. The app loads whatever latest names, and a fresh link
     never fights the file the app has open. Stale versions are removed once
     nothing holds them.

Cross-platform by construction: on Windows it is emsdk's clang against MSVC's
headers and import libraries (vcvarsall's environment captured once and reused,
not re-run per file); elsewhere it is whatever clang++ or g++ is on PATH with
-fPIC. The flags that matter to the firmware sources are the same everywhere.
"""
import glob
import hashlib
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

from native import paths
HERE = paths.RES                        # studio/, or the bundle: shim/, gen/
ROOT = paths.TREE                       # the WLED checkout, or None
BUILD = paths.BUILD                     # writable: the versioned libraries
OBJ = os.path.join(BUILD, "obj")
IS_WIN = sys.platform.startswith("win")
IS_MAC = sys.platform == "darwin"

# Flags every translation unit gets. The comments on WHY live in build.py's
# history; briefly: legacy 2-D effects instead of the particle system, a roster
# big enough for every stock effect, MSVC's M_PI gate, and CFX_SIM to skip the
# settings-page code that reaches into FX_fcn.cpp.
COMMON_FLAGS = ["-std=gnu++17", "-O2",
                "-D_USE_MATH_DEFINES", "-DWLED_PS_DONT_REPLACE_2D_FX",
                "-DCFX_BANK_MAX_FX=256", "-DCFX_SIM",
                "-Wno-vla-cxx-extension", "-Wno-unknown-attributes",
                "-Wno-deprecated-declarations", "-Wno-unused-value"]


class ToolchainError(RuntimeError):
    pass


# --- finding a compiler -------------------------------------------------------
def _find_vcvarsall():
    pf = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
    vswhere = os.path.join(pf, "Microsoft Visual Studio", "Installer", "vswhere.exe")
    if os.path.exists(vswhere):
        r = subprocess.run([vswhere, "-latest", "-products", "*",
                            "-requires", "Microsoft.VisualStudio.Component.VC.Tools.x86.x64",
                            "-property", "installationPath"],
                           capture_output=True, text=True)
        for root in (r.stdout or "").strip().splitlines():
            p = os.path.join(root, "VC", "Auxiliary", "Build", "vcvarsall.bat")
            if os.path.exists(p):
                return p
    for p in glob.glob(os.path.join(pf, "Microsoft Visual Studio", "*", "*",
                                    "VC", "Auxiliary", "Build", "vcvarsall.bat")):
        return p
    return None


def _msvc_env():
    """vcvarsall's environment, captured ONCE into build/msvc_env.json.

    Sourcing the bat costs about a second, which is nothing for one build and
    everything for fifty parallel compiles. The capture is keyed on the bat's
    path and mtime, so a Visual Studio update invalidates it.
    """
    vc = _find_vcvarsall()
    if not vc:
        raise ToolchainError("no MSVC Build Tools found - install the C++ workload "
                             "(clang needs its headers and import libraries)")
    os.makedirs(BUILD, exist_ok=True)
    cache = os.path.join(BUILD, "msvc_env.json")
    key = f"{vc}|{os.path.getmtime(vc)}"
    if os.path.exists(cache):
        try:
            d = json.load(open(cache, encoding="utf-8"))
            if d.get("key") == key:
                return d["env"]
        except Exception:
            pass
    r = subprocess.run(f'"{vc}" x64 >nul && set', shell=True, capture_output=True, text=True)
    if r.returncode != 0:
        raise ToolchainError("vcvarsall failed:\n" + (r.stdout or "") + (r.stderr or ""))
    env = {}
    for line in (r.stdout or "").splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            env[k] = v
    json.dump({"key": key, "env": env}, open(cache, "w", encoding="utf-8"))
    return env


def bundled_compiler():
    """A compiler shipped beside the app (HOME/toolchain/: a MinGW-w64 g++
    or a clang++, any layout - the first found under it), which needs no
    MSVC environment. None when there is none."""
    root = os.path.join(paths.HOME, "toolchain")
    if not os.path.isdir(root):
        return None
    for name in (("g++.exe", "clang++.exe") if IS_WIN else ("g++", "clang++")):
        for p in glob.glob(os.path.join(root, "**", "bin", name), recursive=True):
            return p
    return None


def find_compiler():
    """(compiler path, environment dict) for this machine, or raise."""
    bundled = bundled_compiler()
    if bundled:
        env = dict(os.environ)
        env["PATH"] = os.path.dirname(bundled) + os.pathsep + env.get("PATH", "")
        return bundled, env
    if IS_WIN:
        clang = os.environ.get("SIM_CLANG") or os.path.join(
            os.path.expanduser("~"), "emsdk", "upstream", "bin", "clang++.exe")
        if not os.path.exists(clang):
            for cand in ("clang++.exe", "clang++"):
                r = subprocess.run(["where", cand], capture_output=True, text=True)
                if r.returncode == 0 and r.stdout.strip():
                    clang = r.stdout.strip().splitlines()[0]
                    break
        if not os.path.exists(clang):
            raise ToolchainError("no clang++ found - install emsdk (its clang is used) "
                                 "or set SIM_CLANG to a clang++.exe")
        env = dict(os.environ)
        env.update(_msvc_env())
        return clang, env
    for cand in (os.environ.get("SIM_CLANG"), "clang++", "g++"):
        if not cand:
            continue
        r = subprocess.run(["which", cand], capture_output=True, text=True)
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip().splitlines()[0], dict(os.environ)
    raise ToolchainError("no C++ compiler on PATH - install clang or gcc")


# --- the cache --------------------------------------------------------------------
def _header_stamp(include_dirs):
    """Newest mtime among every header a TU could see. Coarse on purpose: a
    header change rebuilds everything, which is right, and it is cheap to
    compute against a few hundred files."""
    newest = 0.0
    for d in include_dirs:
        for pat in ("*.h", "*.hpp", "**/*.h"):
            for f in glob.glob(os.path.join(d, pat), recursive=True):
                try:
                    newest = max(newest, os.path.getmtime(f))
                except OSError:
                    pass
    return newest


def _obj_path(src):
    h = hashlib.sha1(os.path.abspath(src).encode("utf-8")).hexdigest()[:8]
    base = os.path.splitext(os.path.basename(src))[0]
    return os.path.join(OBJ, f"{base}_{h}.o")


def _needs_compile(src, obj, hstamp):
    if not os.path.exists(obj):
        return True
    om = os.path.getmtime(obj)
    return om < os.path.getmtime(src) or om < hstamp


# --- compiling and linking ----------------------------------------------------------
def _is_gcc(compiler):
    return os.path.basename(compiler).lower().startswith(("g++", "gcc"))


def compile_tu(compiler, env, src, obj, include_dirs, extra_flags=()):
    """One translation unit to one object. Returns (ok, output text)."""
    os.makedirs(os.path.dirname(obj), exist_ok=True)
    flags = [f for f in COMMON_FLAGS if not (_is_gcc(compiler) and f == "-Wno-vla-cxx-extension")]
    cmd = [compiler] + flags + list(extra_flags) + ["-c"]
    if not IS_WIN:
        cmd.append("-fPIC")
    for d in include_dirs:
        cmd += ["-I", d]
    cmd += [src, "-o", obj]
    r = subprocess.run(cmd, capture_output=True, text=True, env=env, cwd=HERE)
    txt = (r.stdout or "") + (r.stderr or "")
    if r.returncode != 0 and os.path.exists(obj):
        try:
            os.remove(obj)
        except OSError:
            pass
    return r.returncode == 0, txt


def link_shared(compiler, env, objs, out):
    cmd = [compiler, "-shared"]
    if IS_MAC:
        cmd += ["-undefined", "dynamic_lookup"]
    if IS_WIN and _is_gcc(compiler):
        cmd += ["-static", "-static-libgcc", "-static-libstdc++"]      # a DLL that needs no MinGW runtime beside it
    cmd += objs + ["-o", out]
    r = subprocess.run(cmd, capture_output=True, text=True, env=env, cwd=HERE)
    txt = (r.stdout or "") + (r.stderr or "")
    return r.returncode == 0, txt


def lib_ext():
    return ".dll" if IS_WIN else (".dylib" if IS_MAC else ".so")


def _next_version():
    os.makedirs(BUILD, exist_ok=True)
    n = 0
    for f in glob.glob(os.path.join(BUILD, "cubefx_*" + lib_ext())):
        try:
            n = max(n, int(os.path.basename(f).split("_")[1].split(".")[0]))
        except ValueError:
            pass
    return n + 1


def latest_library():
    """Path the app should load: build/latest's target if it exists, else the
    legacy cubefx.dll beside build.py."""
    p = os.path.join(BUILD, "latest")
    if os.path.exists(p):
        target = open(p, encoding="utf-8").read().strip()
        if target and not os.path.isabs(target):
            target = os.path.join(BUILD, target)
        if target and os.path.exists(target):
            return target
    legacy = os.path.join(HERE, "cubefx" + lib_ext())
    return legacy if os.path.exists(legacy) else None


def prune_versions(keep=2):
    """Delete old versioned libraries that nothing holds open. A file the app
    still has loaded refuses to be removed on Windows and is simply left for
    the next prune."""
    files = sorted(glob.glob(os.path.join(BUILD, "cubefx_*" + lib_ext())),
                   key=lambda f: int(os.path.basename(f).split("_")[1].split(".")[0]))
    for f in files[:-keep] if keep else files:
        for side in (f, f[:-len(lib_ext())] + ".lib", f[:-len(lib_ext())] + ".exp"):
            try:
                os.remove(side)
            except OSError:
                pass


class BuildReport:
    def __init__(self):
        self.ok = True
        self.compiled = []      # sources actually compiled this run
        self.errors = {}        # src -> compiler output
        self.link_output = ""
        self.library = None

    def error_lines(self):
        """(file, line, message) triples parsed from clang/gcc output."""
        import re
        out = []
        # path:line:col: kind: message - the path may itself contain a drive
        # colon, so it is matched from the right, not split from the left
        pat = re.compile(r"^(.*?):(\d+):(\d+):\s*(error|warning|note):\s*(.*)$")
        for src, txt in self.errors.items():
            for line in txt.splitlines():
                m = pat.match(line.strip())
                if m:
                    out.append((m.group(1), int(m.group(2)), m.group(4) + ": " + m.group(5)))
                elif "error" in line and ":" in line and not line.startswith(" "):
                    out.append((src, 0, line.strip()))
        return out


def build_engine(sources, include_dirs, jobs=None, force=False, log=print):
    """Compile whatever is stale, link a new versioned library, point latest at
    it. Returns a BuildReport; .library is the path to load on success."""
    rep = BuildReport()
    try:
        compiler, env = find_compiler()
    except ToolchainError as e:
        rep.ok = False
        rep.link_output = str(e)
        log(f"  toolchain: {e}")
        return rep

    hstamp = _header_stamp(include_dirs)
    todo = []
    objs = []
    for src in sources:
        obj = _obj_path(src)
        objs.append(obj)
        if force or _needs_compile(src, obj, hstamp):
            todo.append((src, obj))

    if todo:
        log(f"  compiling {len(todo)} of {len(sources)} translation units")
        jobs = jobs or max(2, (os.cpu_count() or 4))
        with ThreadPoolExecutor(max_workers=jobs) as ex:
            futs = {ex.submit(compile_tu, compiler, env, s, o, include_dirs): s for s, o in todo}
            for fut, src in futs.items():
                ok, txt = fut.result()
                rep.compiled.append(src)
                if not ok:
                    rep.ok = False
                    rep.errors[src] = txt
                    log(f"  FAILED: {os.path.basename(src)}")
                    for l in txt.splitlines():
                        if "error" in l:
                            log("    " + l.strip())
        if not rep.ok:
            return rep
    else:
        log("  nothing to compile")

    n = _next_version()
    out = os.path.join(BUILD, f"cubefx_{n}{lib_ext()}")
    ok, txt = link_shared(compiler, env, objs, out)
    rep.link_output = txt
    if not ok:
        rep.ok = False
        log("  link FAILED")
        log("    " + "\n    ".join(txt.splitlines()[-12:]))
        return rep
    with open(os.path.join(BUILD, "latest"), "w", encoding="utf-8") as f:
        f.write(os.path.basename(out))                # a name, not a path: the folder may move (a portable install)
    rep.library = out
    log(f"  {os.path.basename(out)}: {os.path.getsize(out):,} bytes")
    prune_versions(keep=3)
    return rep
