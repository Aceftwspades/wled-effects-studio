#!/bin/sh
# Puts the WLED Effects Studio in the app launcher on Linux: a desktop entry for this checkout,
# made from linux/wled-effects-studio.desktop (@STUDIO@: this folder) in ~/.local/share/applications,
# starting run_studio.sh with no terminal - its icon the cube (linux/wled-effects-studio.png; python
# package.py --linux-icon draws it again from native/icons.py). ./install_linux.sh --uninstall takes it out.
cd "$(dirname "$0")" || exit 1
HERE="$(pwd)"
APPS="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
ENTRY="$APPS/wled-effects-studio.desktop"
if [ "$1" = "--uninstall" ]; then
  rm -f "$ENTRY" && echo "removed $ENTRY"
  command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$APPS" >/dev/null 2>&1
  exit 0
fi
chmod +x run_studio.sh
mkdir -p "$APPS" || exit 1
# this folder into the template: sed's special characters in a path (& | \) escaped first
ESC=$(printf '%s' "$HERE" | sed 's/[&|\\]/\\&/g')
sed "s|@STUDIO@|$ESC|g" linux/wled-effects-studio.desktop > "$ENTRY" || exit 1
chmod 644 "$ENTRY"
command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$APPS" >/dev/null 2>&1
command -v desktop-file-validate >/dev/null 2>&1 && desktop-file-validate "$ENTRY"
echo "WLED Effects Studio is in the app launcher: $ENTRY"
