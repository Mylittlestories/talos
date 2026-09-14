"""Paths for read-only application resources and writable player data.

A source checkout can safely use its local :mod:`data` directory.  A frozen
PyInstaller app cannot: on Windows it is normally installed below ``Program
Files`` and on macOS inside an application bundle, neither of which is a place
for a SQLite journal or a player's settings.  This module keeps the shipped
Lucas Chess database immutable and provisions one writable per-user copy on
first launch.

``TALOS_DATA_DIR`` is intentionally supported for portable/managed installs
and automated tests.  It is the complete data directory, not merely a parent.
"""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import sys
import tempfile
from typing import Union

from . import APP_NAME

PathLike = Union[str, os.PathLike[str]]


def resource_root() -> Path:
    """Return the root containing bundled, read-only application resources."""
    if getattr(sys, "frozen", False):
        # PyInstaller's one-folder mode exposes its collected files here.
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent.parent


def resource_path(*parts: PathLike) -> Path:
    """Path to a file shipped with TALOS (for example ``data/lucas.db``)."""
    return resource_root().joinpath(*(str(part) for part in parts))


def _platform_data_dir() -> Path:
    """A conventional writable location for this operating system."""
    override = os.environ.get("TALOS_DATA_DIR")
    if override:
        return Path(override).expanduser()
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_NAME
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
        return Path(base) / APP_NAME if base else Path.home() / "AppData" / "Local" / APP_NAME
    base = os.environ.get("XDG_DATA_HOME")
    return (Path(base).expanduser() if base else Path.home() / ".local" / "share") / APP_NAME.lower()


def _copy_seed(source: Path, destination: Path) -> None:
    """Copy an initial database without ever overwriting player progress."""
    if destination.exists() or not source.is_file():
        return

    # A fixed ``lucas.db.new`` name lets two first launches write the same file
    # while one process has already published it.  Give every copy its own
    # sibling temporary, then atomically add the finished file as a hard link.
    # ``link`` fails when another process got there first; unlike ``replace``
    # it can never replace a database that has since acquired player progress.
    fd, temporary_name = tempfile.mkstemp(
        prefix="." + destination.name + ".", suffix=".new", dir=destination.parent
    )
    os.close(fd)
    temporary = Path(temporary_name)
    try:
        shutil.copy2(source, temporary)
        try:
            os.link(temporary, destination)
        except FileExistsError:
            return
        except OSError:
            # Hard links are unavailable on a few removable/network file
            # systems. Retain the old best-effort path there, but the unique
            # temporary still prevents two writers from sharing a live file.
            if not destination.exists():
                os.replace(temporary, destination)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def data_dir() -> Path:
    """Return the writable directory for settings and the player database.

    In a normal source tree this remains ``data/`` for developer convenience.
    Frozen, portable and explicitly overridden runs receive a per-user directory
    seeded from the bundled ``data/lucas.db`` exactly once.
    """
    override = os.environ.get("TALOS_DATA_DIR")
    frozen = bool(getattr(sys, "frozen", False))
    if not frozen and not override:
        return resource_path("data")

    target = _platform_data_dir()
    target.mkdir(parents=True, exist_ok=True)
    _copy_seed(resource_path("data", "lucas.db"), target / "lucas.db")
    return target


def database_path() -> Path:
    """The per-user SQLite database path, provisioned if a seed is available."""
    return data_dir() / "lucas.db"


def settings_path() -> Path:
    """The per-user settings JSON path."""
    return data_dir() / "settings.json"
