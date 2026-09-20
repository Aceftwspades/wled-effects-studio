"""One folder that runs:  python package.py  [--toolchain <folder>] [--zip]

    1. the engine built here (python build.py --native-only), so a first run
       needs no compiler: viewing, the examples, the script preview and the
       device sends work at once
    2. runtime/: the firmware files the engine compiles from, copied out of
       the checkout, so building an effect needs no WLED tree
    3. PyInstaller (studio.spec): the app, its packages, the resources
    4. the engine copied in beside the exe (build/), an app icon drawn from
       the studio's own cube icon
    5. --toolchain: a folder with a compiler (a MinGW-w64 with bin/g++.exe,
       or a clang) copied in as toolchain/, so effects build anywhere; the
       studio finds it there before it looks for one installed
    6. --zip: the folder zipped, for a release

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


def main():
    args = sys.argv[1:]
    toolchain = args[args.index("--toolchain") + 1] if "--toolchain" in args else None
    print("package: the engine")
    run([sys.executable, "build.py", "--native-only"])
    print("package: runtime/")
    run([sys.executable, "build.py", "--runtime"])
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
    if toolchain:
        print(f"package: the toolchain from {toolchain}")
        shutil.copytree(toolchain, os.path.join(DIST, "toolchain"), dirs_exist_ok=True)
    open(os.path.join(DIST, "README.txt"), "w", encoding="utf-8").write(
        f"{APP}\n\nRun '{APP}.exe'. Projects, builds and captures are kept in this folder (or in %LOCALAPPDATA%\\{APP} "
        "when it cannot be written to).\n\nBuilding an effect needs a C++ compiler: one in toolchain\\ beside the exe (a MinGW-w64 "
        "with bin\\g++.exe), or emsdk's clang with the MSVC Build Tools. Without one, the effects already built, the examples, "
        "the script preview and every send to a device still work.\n\nFlashing firmware needs a WLED checkout and PlatformIO: "
        "set WLED_ROOT to the checkout.\n\nThe guide is _internal\\GUIDE.md; Help > Studio guide opens it.\n")
    size = sum(os.path.getsize(os.path.join(d, f)) for d, _, fs in os.walk(DIST) for f in fs)
    print(f"package: {DIST}  ({size / 1e6:.0f} MB)")
    if "--zip" in args:
        z = shutil.make_archive(os.path.join(HERE, "dist", APP.replace(" ", "_")), "zip", os.path.join(HERE, "dist"), APP)
        print(f"package: {z}  ({os.path.getsize(z) / 1e6:.0f} MB)")


if __name__ == "__main__":
    main()
