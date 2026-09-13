#!/usr/bin/env bash
# Install a built TALOS bundle into the current user's home directory.
#   bash packaging/linux-install.sh dist/talos
set -euo pipefail

SRC="${1:-dist/talos}"
PREFIX="${PREFIX:-$HOME/.local}"

if [ ! -x "$SRC/talos" ]; then
    echo "usage: bash packaging/linux-install.sh dist/talos" >&2
    exit 1
fi

INSTALL="$PREFIX/lib/talos"
mkdir -p "$INSTALL" "$PREFIX/bin" "$PREFIX/share/applications" \
         "$PREFIX/share/icons/hicolor/512x512/apps" "$PREFIX/share/metainfo"

cp -r "$SRC"/. "$INSTALL"/
ln -sf "$INSTALL/talos" "$PREFIX/bin/talos"
cp packaging/talos.desktop "$PREFIX/share/applications/"
cp assets/talos-512.png "$PREFIX/share/icons/hicolor/512x512/apps/talos.png"
cp packaging/talos.metainfo.xml "$PREFIX/share/metainfo/org.taloschess.studio.metainfo.xml"

if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "$PREFIX/share/applications" || true
fi
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
    gtk-update-icon-cache -f -t "$PREFIX/share/icons/hicolor" || true
fi

echo "TALOS installed. Run it with: $PREFIX/bin/talos"
