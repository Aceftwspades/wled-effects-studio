#!/bin/sh
# WLED Effects Studio - the launcher for Linux and macOS (run_studio.cmd is Windows').
# Runs from its own folder, builds the engine once if it is missing (clang or gcc
# from the path), and keeps the reason on screen when it does not start.
cd "$(dirname "$0")" || exit 1
if [ ! -f build/latest ] && [ ! -f cubefx.so ] && [ ! -f cubefx.dylib ]; then
  echo "no engine built yet - building it once, this takes a minute..."
  python3 build.py --native-only || { echo; echo "the engine did not build: python3 -m native.doctor says what is missing"; exit 1; }
fi
python3 -m native.app || { echo; echo "the studio did not start: python3 -m native.doctor says what is missing"; exit 1; }
