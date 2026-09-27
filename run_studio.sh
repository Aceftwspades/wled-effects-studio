#!/bin/sh
# WLED Effects Studio - the launcher for Linux and macOS (run_studio.pyw / run_studio.cmd are Windows').
# Runs from its own folder, with the checkout's virtual environment (.venv) when there is one - the
# README's install from source makes it - else python3; builds the engine once if it is missing (clang
# or gcc from the path). From a terminal the reason stays on screen when it does not start; from the
# app launcher (install_linux.sh; no terminal) the output goes to $TMPDIR/cubefx/launch.log and a
# failure is said in a notification or a dialog - a dev tool that dies silently is worse than one that
# never started.
cd "$(dirname "$0")" || exit 1
PY=python3
[ -x .venv/bin/python ] && PY=.venv/bin/python
LOG=
if [ ! -t 1 ]; then
  LOG="${TMPDIR:-/tmp}/cubefx/launch.log"
  mkdir -p "$(dirname "$LOG")" && exec >"$LOG" 2>&1
fi
fail() {
  echo; echo "$1"
  if [ -n "$LOG" ]; then
    msg="$1 - the whole of it: $LOG"
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
