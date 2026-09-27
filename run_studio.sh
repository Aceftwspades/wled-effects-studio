#!/bin/sh
# WLED Effects Studio - the launcher for Linux and macOS (run_studio.pyw / run_studio.cmd are Windows').
# Runs from its own folder, with the checkout's virtual environment (.venv) when there is one - the
# README's install from source makes it - else python3; builds the engine once if it is missing (clang
# or gcc from the path). From a terminal the reason stays on screen when it does not start; from the
# app launcher (install_linux.sh; no terminal) the output goes to launch.log in the studio's private
# scratch folder and a failure is said in a notification or a dialog - a dev tool that dies silently
# is worse than one that never started.
cd "$(dirname "$0")" || exit 1
PY=python3
[ -x .venv/bin/python ] && PY=.venv/bin/python
LOG=
QUIET=
if [ ! -t 1 ]; then
  QUIET=1
  # the scratch folder native/scratch.py uses: the user's run directory, else one in the temp folder
  # named for the user - made for them alone (umask 077), and not written into when it is a link,
  # someone else's, or open to others (a file there could be a link planted to one of the user's)
  if [ -n "$XDG_RUNTIME_DIR" ] && [ -d "$XDG_RUNTIME_DIR" ]; then
    DIR="$XDG_RUNTIME_DIR/cubefx"
  else
    DIR="${TMPDIR:-/tmp}"; DIR="${DIR%/}/cubefx-$(id -u)"
  fi
  (umask 077 && mkdir -p "$DIR") 2>/dev/null
  if [ -d "$DIR" ] && [ ! -L "$DIR" ] && [ -O "$DIR" ]; then
    case "$(ls -ld "$DIR")" in
      drwx------*) LOG="$DIR/launch.log" ;;
    esac
  fi
  if [ -n "$LOG" ]; then
    rm -f "$LOG"                                    # a fresh file each start, never through a link
    (umask 077 && : >"$LOG") && exec >"$LOG" 2>&1
  else
    exec >/dev/null 2>&1
  fi
fi
fail() {
  echo; echo "$1"
  if [ -n "$QUIET" ]; then
    msg="$1"
    [ -n "$LOG" ] && msg="$1 - the whole of it: $LOG"
    if command -v notify-send >/dev/null 2>&1; then notify-send -u critical "WLED Effects Studio" "$msg"
    elif command -v zenity >/dev/null 2>&1; then zenity --error --title="WLED Effects Studio" --text="$msg"
    elif command -v kdialog >/dev/null 2>&1; then kdialog --title "WLED Effects Studio" --error "$msg"
    fi
  fi
  exit 1
}
if [ ! -f build/latest ] && [ ! -f cubefx.so ] && [ ! -f cubefx.dylib ]; then
  echo "no engine built yet - building it once, this takes a minute..."
  "$PY" build.py --native-only || fail "the engine did not build: $PY -m native.doctor says what is missing"
fi
"$PY" -m native.app || fail "the studio did not start: $PY -m native.doctor says what is missing"
