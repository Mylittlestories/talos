#!/usr/bin/env bash
# Prepare the sandbox / dev machine to run Lucas Chess NX.
# On a normal Linux desktop only the pip line is needed.
set -e
python3 -m pip install --quiet --upgrade pip
python3 -m pip install --quiet python-chess numpy PyQt6 PyOpenGL PyQt6-WebEngine
# headless/dev containers may miss these Qt runtime libraries
if command -v apt-get >/dev/null 2>&1 && [ "$(id -u)" = "0" ]; then
  apt-get install -y --no-install-recommends \
    libxkbcommon0 libxkbcommon-x11-0 libdbus-1-3 libxcb-cursor0 libxcb-icccm4 \
    libxcb-image0 libxcb-keysyms1 libxcb-randr0 libxcb-render-util0 \
    libxcb-shape0 libxcb-xinerama0 libxcb-xkb1 libgl1 libglib2.0-0 libpulse0 >/dev/null || true
fi
python3 -c "import chess, PyQt6, OpenGL; print('environment ready')"
