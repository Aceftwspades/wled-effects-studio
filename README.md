# WLED Effects Studio

Node graphs and C++ compiled into [WLED](https://github.com/Aircoookie/WLED)
effects, previewed on a simulated cube, sphere, matrix, strip or any shape
you build, with synthetic or live audio - then sent to the device as a
script, as its settings, or flashed into the firmware.

- **[GUIDE.md](GUIDE.md)** - how to use it, from the first run to a show on the device
- **[TUTORIAL.md](TUTORIAL.md)** - a first effect, node by node
- **[NODES.md](NODES.md)** - every node
- **[STUDIO.md](STUDIO.md)** - the design, the history and the roadmap

## Get it

**Windows**: the newest release's zip (`WLED_Effects_Studio.zip`) from the
[releases](https://github.com/Aceftwspades/wled-effects-studio/releases).
Unzip anywhere, run `WLED Effects Studio.exe`. It is portable - projects,
builds and captures live in its folder - and complete: the engine comes
prebuilt and a compiler is inside, so building your own effects works with
nothing installed. `Desktop shortcut.cmd` puts it on the desktop; the app
checks for newer releases once a day and updates itself.

**From the source** (Windows, Linux, macOS):

```bash
pip install -r requirements.txt
python -m native.doctor            # what this machine has, what it lacks
python build.py --native-only      # the engine, once (a C++ compiler: clang or gcc)
python -m native.app               # or run_studio.cmd / run_studio.sh
```

`python package.py` makes the release folder; `--toolchain` bundles a
MinGW-w64 into it; `--zip` zips it.

## WLED, and this fork

The studio runs WLED's own code: the stock effects, the palettes and the
colour maths the simulator draws are compiled from WLED's sources
(`wled00/FX.cpp`, `palettes.cpp`, `colors.cpp`...), extracted into `gen/`
by `build.py`, and the firmware files the engine links against are copied
into `runtime/`. Both are vendored here from a pinned commit of the WLED
fork **[Aceftwspades/WLED](https://github.com/Aceftwspades/WLED)** (branch
`playground`), where the firmware side lives: the `cube_fx` usermod - the
effect bank, the Studio Script VM, the Ace 3-D effects - and the
PlatformIO environments the studio flashes. `WLED_SOURCE.json` names the
commit; `WLED_ROOT=<checkout> python build.py --runtime` refreshes both
folders from a checkout.

Flashing firmware needs that checkout beside the studio (`../WLED`) or
named by `WLED_ROOT`, and PlatformIO. Everything else - the simulator,
building effects, every send to a device - needs neither.

Upstream WLED is the work of Christian Schwinne and the WLED contributors:
[github.com/Aircoookie/WLED](https://github.com/Aircoookie/WLED).

## Licence

EUPL v1.2 or later, the same as WLED - see [LICENSE](LICENSE). The studio
compiles and ships WLED's code, and stays under WLED's terms. The Windows
release bundles a MinGW-w64 GCC from [winlibs](https://winlibs.com) (GPL v3
with the runtime library exception; `toolchain/mingw64/NOTICE.txt`).
