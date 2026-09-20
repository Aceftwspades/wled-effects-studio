"""One folder that runs:  python package.py  [--toolchain <folder>] [--zip]

    1. the engine built here (python build.py --native-only), so a first run
       needs no compiler: viewing, the examples, the script preview and the
       device sends work at once
    2. runtime/: the firmware files the engine compiles from, copied out of
       the checkout, so building an effect needs no WLED tree
    3. PyInstaller (studio.spec): the app, its packages, the resources
    4. the engine copied in beside the exe (build/), an app icon drawn from
       the studio's own cube icon
    5. --toolchain: a folder with a compiler copied in as toolchain/, so
       effects build anywhere; the studio finds it there before it looks
       for one installed. A full MinGW-w64 (winlibs' zip, unpacked) is cut
       down first to what a build uses (trim_toolchain; --trim <src> <dst>
       does that alone): 940 MB to about 120
    6. the engine's objects, named by relative paths and stamped by
       contents, so a first build in the copy compiles only the new effect
    7. --zip: the folder zipped, for a release (about 85 MB with the
       compiler)

The result is dist/WLED Effects Studio/: portable - projects, builds and
captures land beside the exe when the folder can be written to, else in
%LOCALAPPDATA%. The flash (firmware build + OTA) still needs a WLED
checkout and PlatformIO: set WLED_ROOT to the checkout.
"""
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
APP = "WLED Effects Studio"
DIST = os.path.join(HERE, "dist", APP)


def run(cmd, **kw):
    print("  >", " ".join(cmd) if isinstance(cmd, list) else cmd)
    r = subprocess.run(cmd, cwd=HERE, **kw)
    if r.returncode != 0:
        sys.exit(f"package: failed: {cmd}")


def icon_file():
    """An .ico from the toolbar's cube icon, in the accent colour on the panel colour."""
    sys.path.insert(0, HERE)
    from native.icons import Icon, ICONS
    from PIL import Image
    import numpy as np
    out = os.path.join(HERE, "build", "app.ico")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    frames = []
    for px in (256, 128, 64, 48, 32, 16):
        ic = Icon(px); ICONS["cube"](ic)
        a = np.array(ic.data(), np.float32).reshape(px, px, 4)[:, :, 3]
        img = np.zeros((px, px, 4), np.uint8)
        img[:, :, 0], img[:, :, 1], img[:, :, 2] = 24, 27, 33          # the panel's dark
        img[:, :, 3] = 255
        # a rounded square behind, the icon in the accent
        yy, xx = np.mgrid[0:px, 0:px]
        r = px * 0.22
        inside = ((np.clip(np.abs(xx - px / 2 + 0.5) - (px / 2 - r), 0, None)) ** 2 + (np.clip(np.abs(yy - px / 2 + 0.5) - (px / 2 - r), 0, None)) ** 2) <= r * r
        img[~inside, 3] = 0
        col = np.array([90, 169, 230], np.float32)
        for c in range(3):
            img[:, :, c] = np.where(inside, img[:, :, c] * (1 - a) + col[c] * a, 0).astype(np.uint8)
        frames.append(Image.fromarray(img, "RGBA"))
    frames[0].save(out, format="ICO", sizes=[(f.width, f.height) for f in frames], append_images=frames[1:])
    return out


def trim_toolchain(src, dst, log=print):
    """A MinGW-w64 (winlibs' 940 MB unpacked) cut down to what building an
    effect uses, found by asking g++ itself: -print-prog-name for the
    programs it runs, -MM for the headers the engine's sources pull in,
    -Wl,--trace for the archives a DLL link takes, objdump -p for the DLLs
    those programs import. The whole C++ library and gcc's own headers are
    kept, so an effect may include what the engine does not; the Windows
    SDK's thousands of API headers, the debugger, cmake, fortran and the
    docs go. About 90 MB."""
    import re
    sys.path.insert(0, HERE)
    import build as B
    gxx = os.path.join(src, "bin", "g++.exe")
    if not os.path.exists(gxx):
        sys.exit(f"package: no bin/g++.exe under {src}")
    src = os.path.abspath(src)
    keep = set()

    def under(p):
        p = os.path.abspath(p.replace("/", os.sep))
        return p if p.lower().startswith(src.lower() + os.sep) else None

    def add(p):
        q = under(p)
        if q and os.path.isfile(q):
            keep.add(q)

    # the programs, and the DLLs they import (found beside them or in bin/)
    for prog in ("cc1plus", "as", "collect2", "ld", "lto-wrapper"):        # no cc1: g++ compiles .c as C++ too
        r = subprocess.run([gxx, f"-print-prog-name={prog}"], capture_output=True, text=True)
        p = (r.stdout or "").strip()
        if p and os.path.isabs(p):
            add(p)
    add(gxx); add(os.path.join(src, "bin", "gcc.exe"))
    add(os.path.join(src, "bin", "ld.exe")); add(os.path.join(src, "bin", "ld.bfd.exe")); add(os.path.join(src, "bin", "as.exe"))
    for prog in ("cc1plus",):                                                 # the LTO plugin lives beside cc1plus; the link insists on it
        r = subprocess.run([gxx, f"-print-prog-name={prog}"], capture_output=True, text=True)
        d = os.path.dirname((r.stdout or "").strip())
        add(os.path.join(d, "liblto_plugin.dll"))
    objdump = os.path.join(src, "bin", "objdump.exe")
    todo = [p for p in keep if p.lower().endswith((".exe", ".dll"))]
    seen = set()
    while todo:
        p = todo.pop()
        if p in seen or not os.path.exists(objdump):
            continue
        seen.add(p)
        r = subprocess.run([objdump, "-p", p], capture_output=True, text=True)
        for m in re.finditer(r"DLL Name:\s*(\S+)", r.stdout or ""):
            name = m.group(1)
            for d in (os.path.dirname(p), os.path.join(src, "bin")):
                q = os.path.join(d, name)
                if os.path.exists(q) and q not in seen:
                    keep.add(q); todo.append(q); break
    # the headers the engine's sources use, and the whole C++ library
    inc = B.include_dirs()
    flags = [f for f in __import__("native.toolchain", fromlist=["x"]).COMMON_FLAGS if f != "-Wno-vla-cxx-extension"]
    for s_ in B.engine_sources(log=lambda *a: None):
        cmd = [gxx] + flags + ["-MM", "-MF", "-"] + [x for d in inc for x in ("-I", d)] + [s_]
        r = subprocess.run(cmd, capture_output=True, text=True, cwd=HERE)
        for tok in (r.stdout or "").replace("\\\n", " ").split():
            add(tok)
    for d in (os.path.join(src, "include", "c++"), os.path.join(src, "lib", "gcc")):
        for root, _, files in os.walk(d):
            if os.sep + "plugin" + os.sep in root + os.sep or root.endswith(os.sep + "plugin"):
                continue
            for f in files:
                if f.endswith((".h", ".hpp", ".tcc", ".def", ".o", ".a")) or "." not in f:
                    keep.add(os.path.join(root, f))
    # the C runtime's headers (not the Windows API's thousands): the standard
    # names, mingw's own, and sec_api/ - what a microcontroller effect could ask for
    C_STD = {"assert", "complex", "ctype", "errno", "fenv", "float", "inttypes", "iso646", "limits", "locale", "math", "setjmp",
             "signal", "stdalign", "stdarg", "stdatomic", "stdbool", "stddef", "stdint", "stdio", "stdlib", "stdnoreturn", "string",
             "tgmath", "threads", "time", "uchar", "wchar", "wctype", "io", "process", "direct", "malloc", "memory", "conio", "share",
             "fcntl", "unistd", "dirent", "sys/types", "sys/stat", "sys/time", "sys/timeb", "sys/utime", "pthread", "pthread_time",
             "pthread_signal", "pthread_unistd", "pthread_compat", "sched", "semaphore", "vadefs", "sdkddkver", "crtdefs", "crtdbg",
             "swprintf.inl", "eh", "new", "dos", "search", "strings", "intrin", "x86intrin", "mm_malloc", "getopt", "utime"}
    incdir = os.path.join(src, "x86_64-w64-mingw32", "include")
    for root, _, files in os.walk(incdir):
        rel = os.path.relpath(root, incdir).replace(os.sep, "/")
        for f in files:
            stem = (f if rel == "." else rel + "/" + f)
            base = stem[:-2] if stem.endswith(".h") else stem
            if base in C_STD or stem.startswith(("_mingw", "corecrt", "sec_api/", "psdk_inc/intrin", "intrin-impl")) or rel.startswith(("sec_api", "sys")):
                keep.add(os.path.join(root, f))
    # the archives a DLL link takes
    probe = os.path.join(HERE, "build", "_trim_probe.cpp"); open(probe, "w").write("#include <vector>\n#include <cmath>\nextern \"C\" __declspec(dllexport) int f(){std::vector<int> v(3); return (int)std::sqrt(9.0)+v.size();}\n")
    obj = probe[:-4] + ".o"
    subprocess.run([gxx] + flags + ["-c", probe, "-o", obj], capture_output=True, text=True)
    r = subprocess.run([gxx, "-shared", "-static", "-static-libgcc", "-static-libstdc++", "-Wl,--trace", obj, "-o", probe[:-4] + ".dll"], capture_output=True, text=True)
    for line in (r.stdout or "").splitlines() + (r.stderr or "").splitlines():
        add(line.strip().split("(")[0])
    for name in ("libstdc++.a", "libgcc.a", "libgcc_eh.a", "libmingw32.a", "libmingwex.a", "libmsvcrt.a", "libucrt.a", "libucrtbase.a",
                 "libkernel32.a", "libuser32.a", "libadvapi32.a", "libshell32.a", "libpthread.a", "libwinpthread.a", "libgdi32.a", "libws2_32.a",
                 "dllcrt2.o", "crtbegin.o", "crtend.o", "crt2.o", "libm.a", "libssp.a", "libssp_nonshared.a"):
        r = subprocess.run([gxx, f"-print-file-name={name}"], capture_output=True, text=True)
        add((r.stdout or "").strip())
    # the copy
    if os.path.isdir(dst):
        shutil.rmtree(dst)
    n = 0
    for p in sorted(keep):
        q = os.path.join(dst, os.path.relpath(p, src))
        os.makedirs(os.path.dirname(q), exist_ok=True)
        shutil.copyfile(p, q); n += 1
    for f in ("version_info.txt",):
        if os.path.exists(os.path.join(src, f)):
            shutil.copyfile(os.path.join(src, f), os.path.join(dst, f))
    open(os.path.join(dst, "NOTICE.txt"), "w", encoding="utf-8").write(
        "This folder is a cut-down MinGW-w64 GCC from winlibs (https://winlibs.com, Brecht Sanders), kept here so the\n"
        "WLED Effects Studio can compile effects on a machine with no compiler installed. GCC is licensed under the\n"
        "GNU GPL v3 with the GCC Runtime Library Exception; MinGW-w64 under its own permissive licenses. The sources:\n"
        "https://github.com/brechtsanders/winlibs_mingw and https://gcc.gnu.org. version_info.txt names the build.\n")
    size = sum(os.path.getsize(os.path.join(d, f)) for d, _, fs in os.walk(dst) for f in fs)
    log(f"  toolchain: {n} files, {size / 1e6:.0f} MB, from {src}")
    return dst


def main():
    args = sys.argv[1:]
    toolchain = args[args.index("--toolchain") + 1] if "--toolchain" in args else None
    if "--trim" in args:                                   # python package.py --trim <mingw64> <out>: the cut-down toolchain alone
        i = args.index("--trim"); trim_toolchain(args[i + 1], args[i + 2]); return
    print("package: the engine" + (" (with the toolchain that ships)" if toolchain else ""))
    if toolchain:
        # the engine and its objects are made by the compiler the release ships, so the
        # app's first build reuses them (an object is stamped with the compiler that made it)
        os.environ["STUDIO_TOOLCHAIN"] = os.path.abspath(toolchain)
    run([sys.executable, "build.py", "--native-only"])
    sys.path.insert(0, HERE)
    from native import paths
    if paths.has_tree():
        print("package: runtime/ from the WLED checkout")
        run([sys.executable, "build.py", "--runtime"])
    else:
        print("package: runtime/ as vendored (no WLED checkout here)")     # a release runner: the pinned copy in the repository
        if not os.path.isdir(paths.RUNTIME):
            sys.exit("package: no runtime/ and no WLED checkout - nothing to build the engine from")
    print("package: the icon")
    icon_file()
    print("package: PyInstaller")
    if os.path.isdir(DIST):
        shutil.rmtree(DIST)
    run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--distpath", os.path.join(HERE, "dist"),
         "--workpath", os.path.join(HERE, "build", "pyinstaller"), "studio.spec"])
    # the prebuilt engine beside the exe, named by build/latest (a name, so the folder can move)
    sys.path.insert(0, HERE)
    from native.toolchain import latest_library
    lib = latest_library()
    if not lib:
        sys.exit("package: no engine to ship")
    os.makedirs(os.path.join(DIST, "build"), exist_ok=True)
    shutil.copyfile(lib, os.path.join(DIST, "build", os.path.basename(lib)))
    open(os.path.join(DIST, "build", "latest"), "w", encoding="utf-8").write(os.path.basename(lib))
    # the engine's objects too (named by relative paths, stamped by contents): a
    # first build then compiles only the effect being added, not the whole engine
    from native.toolchain import OBJ
    if os.path.isdir(OBJ):
        shutil.copytree(OBJ, os.path.join(DIST, "build", "obj"), dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns("*_probe*", "*.log", "*.cpp", "*.dll"))
    if toolchain:
        print(f"package: the toolchain from {toolchain}")
        if os.path.exists(os.path.join(toolchain, "bin", "g++.exe")) and os.path.isdir(os.path.join(toolchain, "share")):
            trim_toolchain(toolchain, os.path.join(DIST, "toolchain", "mingw64"))       # a full MinGW: cut down
        else:
            shutil.copytree(toolchain, os.path.join(DIST, "toolchain"), dirs_exist_ok=True)  # already trimmed, or a clang
    open(os.path.join(DIST, "README.txt"), "w", encoding="utf-8").write(
        f"{APP}\n\nRun '{APP}.exe'. Projects, builds and captures are kept in this folder (or in %LOCALAPPDATA%\\{APP} "
        "when it cannot be written to).\n\nBuilding an effect needs a C++ compiler: the one in toolchain\\ beside the exe when "
        "the release ships with it (a cut-down MinGW-w64 GCC), else a MinGW-w64 put there, or emsdk's clang with the MSVC Build "
        "Tools. Without one, the effects already built, the examples, the script preview and every send to a device still work."
        "\n\nFlashing firmware needs a WLED checkout and PlatformIO: set WLED_ROOT to the checkout.\n\n"
        "The guide is _internal\\GUIDE.md; Help > Studio guide opens it.\n")
    shutil.copyfile(os.path.join(HERE, "Desktop shortcut.cmd"), os.path.join(DIST, "Desktop shortcut.cmd"))   # a .lnk holds a path: made where it lands
    # what this build is: the version, the commit, the day - for the About dialog and a bug report
    import json, time
    from native import version
    try:
        commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, cwd=HERE).stdout.strip()
    except Exception:
        commit = ""
    json.dump({"version": version.__version__, "commit": commit, "built": time.strftime("%Y-%m-%d")},
              open(os.path.join(DIST, "version.json"), "w", encoding="utf-8"), indent=1)
    size = sum(os.path.getsize(os.path.join(d, f)) for d, _, fs in os.walk(DIST) for f in fs)
    print(f"package: {DIST}  ({size / 1e6:.0f} MB)")
    if "--zip" in args:
        z = shutil.make_archive(os.path.join(HERE, "dist", APP.replace(" ", "_")), "zip", os.path.join(HERE, "dist"), APP)
        print(f"package: {z}  ({os.path.getsize(z) / 1e6:.0f} MB)")


if __name__ == "__main__":
    main()
