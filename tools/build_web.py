#!/usr/bin/env python3
"""
Build the browser edition's Python payload.

The desktop app is PyQt6, and Qt cannot run in a browser. But *the parts that
matter are pure Python*: the engine, the Anarchchess rules, the Anarchess
rules and its bot. This tool copies exactly those files, plus a small bridge,
into web/python/ and exports the training data as JSON, so Pyodide can import
the real code — not a rewrite of it.

    python tools/build_web.py

Writes:

    web/python/lc/...            the engine and both games, unmodified
    web/python/bridge.py         a thin JSON API over them
    web/python/files.json        what the worker has to fetch
    web/data/sets.json           the training sets
    web/data/puzzles.json        the puzzles, grouped by set
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB = os.path.join(ROOT, "web")
PYDIR = os.path.join(WEB, "python")
DATA = os.path.join(WEB, "data")
ASSETS = os.path.join(ROOT, "assets")
SRC = os.path.join(WEB, "python_src")

#: repo file -> path inside the Pyodide filesystem
def read_version() -> str:
    """The version in lc/__init__.py, read without importing the package."""
    import re
    path = os.path.join(ROOT, "lc", "__init__.py")
    with open(path, encoding="utf-8") as fh:
        found = re.search(r'^APP_VERSION\s*=\s*"([^"]+)"', fh.read(), re.M)
    if not found:
        raise SystemExit(f"no APP_VERSION in {path}")
    return found.group(1)


MODULES = {
    "lc/core/engine.py": "lc/core/engine.py",
    "lc/variants/anarchchess.py": "lc/variants/anarchchess.py",
    "lc/anarchess/rules.py": "lc/anarchess/rules.py",
    "lc/anarchess/ai.py": "lc/anarchess/ai.py",
}

#: packages that need an (empty) __init__.py in the browser
PACKAGES = ("lc", "lc/core", "lc/variants", "lc/anarchess")

MAX_PER_SET = 250          # keeps puzzles.json a few megabytes, not fifty


def build_python() -> int:
    if os.path.isdir(PYDIR):
        shutil.rmtree(PYDIR)
    for package in PACKAGES:
        os.makedirs(os.path.join(PYDIR, package), exist_ok=True)
        with open(os.path.join(PYDIR, package, "__init__.py"), "w") as fh:
            fh.write("")

    copied = 0
    for source, target in MODULES.items():
        src = os.path.join(ROOT, source)
        if not os.path.exists(src):
            print(f"  missing {source}", file=sys.stderr)
            return 1
        shutil.copyfile(src, os.path.join(PYDIR, target))
        copied += 1

    bridge = os.path.join(SRC, "bridge.py")
    if not os.path.exists(bridge):
        print(f"  missing {bridge}", file=sys.stderr)
        return 1
    shutil.copyfile(bridge, os.path.join(PYDIR, "bridge.py"))
    # stamp the version in: lc/__init__.py is deliberately not in the bundle,
    # so the bridge cannot read it at run time
    target = os.path.join(PYDIR, "bridge.py")
    with open(target, encoding="utf-8") as fh:
        text = fh.read()
    text = text.replace("__APP_VERSION__", read_version())
    with open(target, "w", encoding="utf-8") as fh:
        fh.write(text)

    print(f"python: {copied} modules + bridge -> web/python")
    return 0


def vendor_chess() -> int:
    """Copy python-chess into the payload.

    It is pure Python, so vendoring it means the browser edition needs no
    network at all beyond the Pyodide runtime itself - no micropip, no PyPI.
    """
    try:
        import chess
    except ImportError:
        print("  python-chess is not installed", file=sys.stderr)
        return 1
    source = os.path.dirname(os.path.abspath(chess.__file__))
    target = os.path.join(PYDIR, "chess")
    if os.path.isdir(target):
        shutil.rmtree(target)

    kept = 0
    for entry in sorted(os.listdir(source)):
        if entry == "__pycache__":
            continue
        src = os.path.join(source, entry)
        dst = os.path.join(target, entry)
        if os.path.isdir(src):
            shutil.copytree(src, dst,
                            ignore=shutil.ignore_patterns("__pycache__"))
        else:
            os.makedirs(target, exist_ok=True)
            shutil.copyfile(src, dst)
        kept += 1
    print(f"vendored python-chess {chess.__version__} ({kept} entries)")
    return 0


def build_icons() -> int:
    """Copy the generated app icons into the web edition."""
    icons = os.path.join(WEB, "icons")
    os.makedirs(icons, exist_ok=True)
    wanted = ["talos.svg", "favicon.ico", "apple-touch-icon.png",
              "talos-192.png", "talos-512.png", "talos-maskable-512.png"]
    missing = []
    for name in wanted:
        src = os.path.join(ASSETS, name)
        if not os.path.exists(src):
            missing.append(name)
            continue
        shutil.copy2(src, os.path.join(icons, name))
    if missing:
        print("  missing icons (run tools/make_icon.py): " + ", ".join(missing),
              file=sys.stderr)
        return 0
    print("icons:  %d -> web/icons" % len(wanted))
    return 0


def write_file_index() -> int:
    """List every file in web/python so the worker can fetch and mount them."""
    names = []
    for base, _dirs, files in os.walk(PYDIR):
        for name in files:
            if name.endswith(".pyc"):
                continue
            rel = os.path.relpath(os.path.join(base, name), PYDIR)
            names.append(rel.replace(os.sep, "/"))
    names.sort()
    with open(os.path.join(PYDIR, "files.json"), "w") as fh:
        json.dump(names, fh)
    print(f"index:  {len(names)} files")
    return 0


def build_data() -> int:
    os.makedirs(DATA, exist_ok=True)
    db_path = os.path.join(ROOT, "data", "lucas.db")
    if not os.path.exists(db_path):
        print("  no data/lucas.db - the web edition ships without puzzles",
              file=sys.stderr)
        return 0

    db = sqlite3.connect(db_path)
    sets = []
    for row in db.execute("SELECT id, kind, name FROM sets ORDER BY kind, name"):
        sets.append({"id": row[0], "kind": row[1], "name": row[2]})

    puzzles = {}
    total = 0
    for entry in sets:
        rows = db.execute(
            "SELECT id, fen, solution, solution_san, label, difficulty"
            " FROM puzzles WHERE set_id=? AND solution<>''"
            " ORDER BY ord LIMIT ?", (entry["id"], MAX_PER_SET)).fetchall()
        items = []
        for pid, fen, solution, san, label, difficulty in rows:
            moves = [m for m in (solution or "").split() if m]
            if not moves:
                continue
            items.append({
                "i": pid,
                "f": fen,
                "m": moves,
                "s": san or "",
                "d": int(difficulty or 0),
            })
        if items:
            puzzles[str(entry["id"])] = items
            total += len(items)
    db.close()

    with open(os.path.join(DATA, "sets.json"), "w") as fh:
        json.dump({"sets": sets}, fh, separators=(",", ":"))
    with open(os.path.join(DATA, "puzzles.json"), "w") as fh:
        json.dump({"puzzles": puzzles}, fh, separators=(",", ":"))

    sizes = [os.path.getsize(os.path.join(DATA, name))
             for name in ("sets.json", "puzzles.json")]
    print(f"data:   {len(sets)} sets, {total} puzzles -> "
          f"{sizes[0] / 1024:.0f} KB + {sizes[1] / 1024 / 1024:.1f} MB")
    return 0


def main() -> int:
    if not os.path.isdir(WEB):
        print("no web/ directory", file=sys.stderr)
        return 1
    print("building the browser edition")
    return (build_python() or vendor_chess()
            or write_file_index() or build_icons() or build_data())


if __name__ == "__main__":
    raise SystemExit(main())
