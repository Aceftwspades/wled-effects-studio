# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for the WLED Effects Studio: one folder, the app and
# everything it reads - the shim, the generated firmware extracts, the
# runtime copy of the firmware, the examples, the docs. What the app writes
# (projects, build, captures) lands beside the exe; native/paths.py knows
# where. Run through package.py, which builds the engine first and copies
# it in.
import os

HERE = os.path.abspath(".")


def folder(name, dest=None):
    return (os.path.join(HERE, name), dest or name)


datas = [folder("shim"), folder("gen"), folder("runtime"),
         folder(os.path.join("examples", "graphs")), folder(os.path.join("examples", "assets")),
         folder("docs"),
         (os.path.join(HERE, "sim_main.cpp"), "."),
         (os.path.join(HERE, "GUIDE.md"), "."), (os.path.join(HERE, "NODES.md"), "."),
         (os.path.join(HERE, "STUDIO.md"), "."), (os.path.join(HERE, "TUTORIAL.md"), ".")]
datas = [(s, d) for s, d in datas if os.path.exists(s)]

# every module of native/: the app imports many of them by name at run time
hidden = ["native." + f[:-3] for f in os.listdir(os.path.join(HERE, "native")) if f.endswith(".py") and f != "__init__.py"]
hidden += ["sounddevice", "pyaudiowpatch", "PIL.Image", "PIL.ImageDraw", "numpy"]

a = Analysis([os.path.join(HERE, "studio.py")],
             pathex=[HERE],
             binaries=[],
             datas=datas,
             hiddenimports=hidden,
             hookspath=[],
             runtime_hooks=[],
             excludes=["tkinter", "matplotlib", "scipy", "pytest", "PyInstaller"],
             noarchive=False)
pyz = PYZ(a.pure)

import sys
icon = os.path.join(HERE, "build", "app.ico")                      # an .ico: Windows; macOS wants .icns, Linux has none
common = dict(exclude_binaries=True, debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
              icon=icon if os.path.exists(icon) and sys.platform.startswith("win") else None)
exe = EXE(pyz, a.scripts, [], name="WLED Effects Studio", console=False, **common)
# the same app with a console: what went wrong stays on screen (the launcher's reason for keeping one)
dbg = EXE(pyz, a.scripts, [], name="WLED Effects Studio (console)", console=True, **common)
coll = COLLECT(exe, dbg, a.binaries, a.datas,
               strip=False,
               upx=False,
               name="WLED Effects Studio")
