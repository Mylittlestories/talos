"""
Stockfish installer.

Downloads a matching Stockfish build for this machine into `engines/`, so the
program has a strong UCI engine available without shipping a large binary.
Nothing happens unless the user asks for it (menu: Engines ▸ Install Stockfish).
"""

from __future__ import annotations

import os
import platform
import stat
import sys
import tarfile
import tempfile
import urllib.request
import zipfile
from typing import Callable, List, Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QMessageBox, QProgressDialog

RELEASE = "https://github.com/official-stockfish/Stockfish/releases/download"

# candidate asset names per (system, machine) - first one that downloads wins
CANDIDATES = {
    ("Linux", "x86_64"): [
        ("sf_18", "stockfish-ubuntu-x86-64.tar"),
        ("sf_17", "stockfish-ubuntu-x86-64-avx2.tar"),
        ("sf_16.1", "stockfish-ubuntu-x86-64-avx2.tar"),
    ],
    ("Linux", "aarch64"): [
        ("sf_18", "stockfish-ubuntu-armv8.tar"),
        ("sf_17", "stockfish-ubuntu-armv8.tar"),
    ],
    ("Darwin", "x86_64"): [("sf_18", "stockfish-macos-x86-64.tar")],
    ("Darwin", "arm64"): [("sf_18", "stockfish-macos-arm64.tar")],
    ("Windows", "AMD64"): [
        ("sf_18", "stockfish-windows-x86-64-avx2.zip"),
        ("sf_17", "stockfish-windows-x86-64-avx2.zip"),
    ],
    ("Windows", "x86"): [("sf_17", "stockfish-windows-x86-32-sse41-popcnt.zip")],
}


def engines_dir() -> str:
    here = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    path = os.path.join(here, "engines")
    os.makedirs(path, exist_ok=True)
    return path


def _candidates() -> List[str]:
    system = platform.system()
    machine = platform.machine()
    pairs = CANDIDATES.get((system, machine))
    if not pairs:
        pairs = CANDIDATES.get((system, "x86_64"), CANDIDATES[("Linux", "x86_64")])
    return [f"{RELEASE}/{tag}/{name}" for tag, name in pairs]


def _download(url: str, dest: str, progress: Optional[Callable[[int, int], None]] = None) -> str:
    with urllib.request.urlopen(url, timeout=60) as response:
        total = int(response.headers.get("Content-Length") or 0)
        got = 0
        with open(dest, "wb") as fh:
            while True:
                chunk = response.read(64 * 1024)
                if not chunk:
                    break
                fh.write(chunk)
                got += len(chunk)
                if progress:
                    progress(got, total)
    return dest


def _extract(archive: str, dest_dir: str) -> Optional[str]:
    if archive.endswith(".zip"):
        with zipfile.ZipFile(archive) as zf:
            members = [n for n in zf.namelist() if n.lower().endswith((".exe", "stockfish"))]
            zf.extractall(dest_dir)
    else:
        with tarfile.open(archive) as tf:
            members = [m for m in tf.getnames()
                       if m.lower().endswith("stockfish") or "/stockfish" in m.lower()]
            try:
                tf.extractall(dest_dir)
            except Exception:
                tf.extractall(dest_dir, filter="data") if sys.version_info >= (3, 12) else None
    # find the binary
    for root, dirs, files in os.walk(dest_dir):
        for name in files:
            lower = name.lower()
            if lower.startswith("stockfish") and (lower.endswith(".exe") or
                                                  "stockfish" == lower.split(".")[0]):
                path = os.path.join(root, name)
                try:
                    os.chmod(path, os.stat(path).st_mode | stat.S_IEXEC | stat.S_IXGRP |
                             stat.S_IXOTH)
                except Exception:
                    pass
                return path
    return None


def install_stockfish(parent=None) -> Optional[str]:
    """Download and register Stockfish.  Returns the path or None."""
    existing = _find_existing()
    if existing:
        QMessageBox.information(parent, "Stockfish",
                                f"Stockfish is already installed:\n{existing}")
        return existing
    urls = _candidates()
    dialog = QProgressDialog("Downloading Stockfish…", "Cancel", 0, 100, parent)
    dialog.setWindowModality(Qt.WindowModality.WindowModal)
    dialog.setAutoClose(False)
    dialog.setValue(0)
    dialog.show()

    def progress(got: int, total: int) -> None:
        if total:
            dialog.setValue(int(got / total * 100))
        QApplication.processEvents()

    last_error = None
    for url in urls:
        try:
            tmp_dir = tempfile.mkdtemp(prefix="sf_dl_")
            archive = os.path.join(tmp_dir, url.rsplit("/", 1)[-1])
            dialog.setLabelText(f"Downloading {url.rsplit('/', 1)[-1]}…")
            _download(url, archive, progress)
            dialog.setLabelText("Extracting…")
            path = _extract(archive, engines_dir())
            if path:
                dialog.setValue(100)
                dialog.close()
                QMessageBox.information(parent, "Stockfish",
                                        f"Stockfish installed:\n{path}\n\n"
                                        "It is now selectable in the new game dialog.")
                return path
        except Exception as exc:
            last_error = exc
        dialog.setValue(0)
    dialog.close()
    QMessageBox.warning(
        parent, "Stockfish",
        "The download failed.\n\n"
        f"{last_error}\n\n"
        "You can still install Stockfish by hand and add it in "
        "Engines ▸ Manage engines.  The built-in engine works without it.")
    return None


def _find_existing() -> Optional[str]:
    directory = engines_dir()
    for root, dirs, files in os.walk(directory):
        for name in files:
            lower = name.lower()
            if "stockfish" in lower and (lower.endswith(".exe") or "." not in name):
                return os.path.join(root, name)
    return None
