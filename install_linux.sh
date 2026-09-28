#!/bin/sh
# Puts the WLED Effects Studio in the app launcher on Linux: a desktop entry for this folder, made from
# linux/wled-effects-studio.desktop (@STUDIO@: this folder, @START@: what starts it there) in
# ~/.local/share/applications, with no terminal - its icon the cube (linux/wled-effects-studio.png; python
# package.py --linux-icon draws it again from native/icons.py). A checkout starts through run_studio.sh, the
# release's folder (its Linux tarball) is the app itself. ./install_linux.sh --uninstall takes it out.
cd "$(dirname "$0")" || exit 1
HERE="$(pwd)"
APPS="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
ENTRY="$APPS/wled-effects-studio.desktop"
if [ "$1" = "--uninstall" ]; then
  rm -f "$ENTRY" && echo "removed $ENTRY"
  command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$APPS" >/dev/null 2>&1
  exit 0
fi
if [ -f run_studio.sh ]; then
  chmod +x run_studio.sh
  START="run_studio.sh"
elif [ -x "WLED Effects Studio" ]; then
  START="WLED Effects Studio"
else
  echo "neither run_studio.sh (a checkout) nor the app (the release's folder) is here: $HERE" >&2
  exit 1
fi
mkdir -p "$APPS" || exit 1
# this folder into the template: sed's special characters in a path (& | \) escaped first
ESC=$(printf '%s' "$HERE" | sed 's/[&|\\]/\\&/g')
sed -e "s|@STUDIO@|$ESC|g" -e "s|@START@|$START|g" linux/wled-effects-studio.desktop > "$ENTRY" || exit 1
chmod 644 "$ENTRY"
command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$APPS" >/dev/null 2>&1
command -v desktop-file-validate >/dev/null 2>&1 && desktop-file-validate "$ENTRY"
echo "WLED Effects Studio is in the app launcher: $ENTRY"
