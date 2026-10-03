# WLED Effects Studio

Node graphs and C++ compiled into [WLED](https://github.com/Aircoookie/WLED)
effects, previewed on a simulated cube, sphere, matrix, strip or any shape
you build, with synthetic or live audio - then sent to the device as a
script, as its settings, or flashed into the firmware.

- **[GUIDE.md](GUIDE.md)** - how to use it, from the first run to a show on the device
- **[TUTORIAL.md](TUTORIAL.md)** - a first effect, node by node
- **[NODES.md](NODES.md)** - every node
- **[STUDIO.md](STUDIO.md)** - the design, the history and the roadmap

## Try it in the browser

**[aceftwspades.github.io/wled-effects-studio](https://aceftwspades.github.io/wled-effects-studio/)**
is the lightweight Cube FX Simulator: WLED's stock effects on a simulated
cube, matrix, cylinder, sphere or torus (up to 192x192 pixels), with
palettes, parameters and synthetic audio. It is only the preview.
The node-graph composer, the C++ editor, the other geometries, usermod export
and sending to a device are in the desktop app below.

## Get it

**Windows**: the newest release's zip (`WLED_Effects_Studio.zip`) from the
[releases](https://github.com/Aceftwspades/wled-effects-studio/releases).
Unzip anywhere, run `WLED Effects Studio.exe`. It is portable - projects,
builds and captures live in its folder - and complete: the engine comes
prebuilt and a compiler is inside, so building your own effects works with
nothing installed. `Desktop shortcut.cmd` puts it on the desktop; the app
checks for newer releases once a day and updates itself.

**Linux**: the release's tarball - `WLED_Effects_Studio_linux.tar.gz` on a
PC, `WLED_Effects_Studio_aarch64.tar.gz` on a 64-bit ARM (a Raspberry Pi 4
or 5 with a 64-bit OS; releases after 1.4.0) - built on Ubuntu. Unpack it anywhere (`tar -xzf`),
run `./WLED Effects Studio`; `./install_linux.sh` puts it in the app
launcher. The engine comes prebuilt; building your own effects takes the
system's gcc or clang (`build-essential`, `base-devel`, `gcc-c++`), live
audio its PortAudio. The app says when a newer release is out and downloads
its tarball for you to unpack over the folder.

**macOS** (Apple silicon; releases after 1.4.0): the release's
`WLED_Effects_Studio_macos_arm64.tar.gz`. Unpack it anywhere, run
`./WLED Effects Studio` (or double-click it). The build is not signed by a
developer Apple knows, so the first time the Finder asks - right-click it,
Open - or run `xattr -dr com.apple.quarantine .` in the folder once.
Building your own effects takes Apple's compiler (`xcode-select --install`).
An Intel Mac runs it from the source, below.

**From the source**, on Windows:

```bash
pip install -r requirements.txt
python -m native.doctor            # what this machine has, what it lacks
python build.py --native-only      # the engine, once (a C++ compiler: clang or gcc)
python -m native.app               # or run_studio.pyw (no console window) / run_studio.cmd
```

On Linux and macOS, in a virtual environment - current distributions refuse
a `pip install` into the system's Python (PEP 668: "externally-managed-environment"),
and many have `python3` but no `python`:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m native.doctor     # what this machine has, what it lacks
.venv/bin/python build.py --native-only
.venv/bin/python -m native.app        # or ./run_studio.sh - it takes .venv by itself
./install_linux.sh                    # Linux: the studio in the app launcher, with its icon
```

Linux wants a few system packages too: PortAudio for live audio (the
sounddevice package does not bring it there), and a C++ compiler with the
ALSA (and JACK) headers for python-rtmidi, which pip builds from source
where there is no wheel for your Python (3.14, for one):

```bash
# Debian / Ubuntu
sudo apt install python3-venv clang libportaudio2 libasound2-dev libjack-jackd2-dev
# Arch
sudo pacman -S clang portaudio alsa-lib
# Fedora
sudo dnf install clang portaudio alsa-lib-devel jack-audio-connection-kit-devel
```

To hear what the computer plays on Linux, choose a PipeWire / PulseAudio
"Monitor of ..." input under the panel's LIVE, where the system lists one.

`python package.py` makes the release folder; `--toolchain` bundles a
MinGW-w64 into it; `--zip` zips it (on Linux: the tarball).

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
