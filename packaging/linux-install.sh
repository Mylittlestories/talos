#!/usr/bin/env bash
# Install or remove a built TALOS Linux bundle in the current user's home.
#
# From a release archive (after extracting it):
#   ./install.sh
# From a source checkout:
#   bash packaging/linux-install.sh dist/talos
# Optional: PREFIX=/somewhere ./install.sh, or ./install.sh --uninstall
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
PREFIX="${PREFIX:-$HOME/.local}"
INSTALL="$PREFIX/lib/talos"
BIN="$PREFIX/bin/talos"
DESKTOP_TARGET="$PREFIX/share/applications/talos.desktop"
ICON_TARGET="$PREFIX/share/icons/hicolor/512x512/apps/talos.png"
META_TARGET="$PREFIX/share/metainfo/org.taloschess.studio.metainfo.xml"

if [ "${1:-}" = "--uninstall" ]; then
    rm -rf "$INSTALL"
    rm -f "$BIN" "$DESKTOP_TARGET" "$ICON_TARGET" "$META_TARGET"
    if command -v update-desktop-database >/dev/null 2>&1; then
        update-desktop-database "$PREFIX/share/applications" || true
    fi
    if command -v gtk-update-icon-cache >/dev/null 2>&1; then
        gtk-update-icon-cache -f -t "$PREFIX/share/icons/hicolor" || true
    fi
    echo "TALOS was removed from $PREFIX."
    exit 0
fi

# A release has install.sh next to talos/; a source checkout retains the old
# convenient default. An explicit first argument always wins.
SRC="${1:-$SCRIPT_DIR/talos}"
if [ ! -x "$SRC/talos" ] && [ -x "$SCRIPT_DIR/../dist/talos/talos" ]; then
    SRC="$SCRIPT_DIR/../dist/talos"
fi
if [ ! -x "$SRC/talos" ]; then
    echo "usage: $0 [path/to/talos] | --uninstall" >&2
    echo "Expected a PyInstaller bundle containing an executable named talos." >&2
    exit 1
fi

find_resource() {
    for candidate in "$@"; do
        if [ -f "$candidate" ]; then
            printf '%s\n' "$candidate"
            return 0
        fi
    done
    return 1
}

# These candidates deliberately support both the self-contained release layout
# and developer invocation from packaging/ in a git checkout.
DESKTOP_SOURCE="$(find_resource \
    "$SCRIPT_DIR/talos.desktop" \
    "$(dirname "$SCRIPT_DIR")/packaging/talos.desktop" \
    "$(dirname "$SRC")/talos.desktop")" || {
    echo "Missing talos.desktop beside the installer." >&2; exit 1;
}
ICON_SOURCE="$(find_resource \
    "$SCRIPT_DIR/talos.png" \
    "$(dirname "$SCRIPT_DIR")/assets/talos-512.png" \
    "$(dirname "$SRC")/talos.png")" || {
    echo "Missing TALOS icon beside the installer." >&2; exit 1;
}
META_SOURCE="$(find_resource \
    "$SCRIPT_DIR/talos.metainfo.xml" \
    "$(dirname "$SCRIPT_DIR")/packaging/talos.metainfo.xml" \
    "$(dirname "$SRC")/talos.metainfo.xml")" || {
    echo "Missing TALOS AppStream metadata beside the installer." >&2; exit 1;
}

mkdir -p "$INSTALL" "$PREFIX/bin" "$PREFIX/share/applications" \
         "$PREFIX/share/icons/hicolor/512x512/apps" "$PREFIX/share/metainfo"

# Copy the complete one-folder application so _internal/ remains next to talos.
rm -rf "$INSTALL"
mkdir -p "$INSTALL"
cp -a "$SRC"/. "$INSTALL"/
ln -sfn "$INSTALL/talos" "$BIN"
install -m 0644 "$ICON_SOURCE" "$ICON_TARGET"
install -m 0644 "$META_SOURCE" "$META_TARGET"

# Do not assume ~/.local/bin (or a caller's custom PREFIX/bin) is already in
# the graphical session's PATH. A concrete launcher path makes the .desktop
# entry work immediately and lets `%F` deliver clicked PGNs to run.py.
# Quote Exec/TryExec as specified by freedesktop.org: paths containing a space
# are valid for a custom PREFIX too. Escape characters that are meaningful to
# either sed's replacement or a desktop-entry quoted string.
escaped_bin="$(printf '%s' "$BIN" | sed 's/[\\&|\"]/\\&/g')"
escaped_icon="$(printf '%s' "$ICON_TARGET" | sed 's/[\\&|]/\\&/g')"
sed -e "s|^Exec=talos\\(.*\\)$|Exec=\"$escaped_bin\"\\1|" \
    -e "s|^TryExec=talos$|TryExec=\"$escaped_bin\"|" \
    -e "s|^Icon=talos$|Icon=$escaped_icon|" \
    "$DESKTOP_SOURCE" > "$DESKTOP_TARGET"
chmod 0644 "$DESKTOP_TARGET"

if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "$PREFIX/share/applications" || true
fi
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
    gtk-update-icon-cache -f -t "$PREFIX/share/icons/hicolor" || true
fi

echo "TALOS installed in $INSTALL"
echo "Run it with: $BIN"
echo "If the desktop launcher is not visible yet, log out and back in or run:"
echo "  update-desktop-database $PREFIX/share/applications"
