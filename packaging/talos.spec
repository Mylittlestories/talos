# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for TALOS.

    pyinstaller packaging/talos.spec --noconfirm --distpath dist

The result is dist/talos/ — the executable, plus a _internal/ folder holding
the Python runtime, the Qt libraries, the Lucas database and the icon set.
(PyInstaller 6 moved the payload out of the top level; everything below is
unaffected because the app resolves its data through sys._MEIPASS.)
Zip it for Windows, tar it for Linux.

One-folder mode is deliberate: start-up is instant, and the database and the
engines folder stay visible so users can replace or delete them.
"""

import os
import sys

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))  # noqa: F821
sys.path.insert(0, ROOT)

from lc import APP_NAME, APP_VERSION  # noqa: E402

datas = [
    (os.path.join(ROOT, "data", "lucas.db"), "data"),
    (os.path.join(ROOT, "assets"), "assets"),
    (os.path.join(ROOT, "LICENSE"), "."),
    (os.path.join(ROOT, "README.md"), "."),
    (os.path.join(ROOT, "CHANGELOG.md"), "."),
]
if os.path.exists(os.path.join(ROOT, "engines", "README.md")):
    datas.append((os.path.join(ROOT, "engines", "README.md"), "engines"))

# Each platform wants its own icon format, and PyInstaller refuses to convert:
# a .ico on macOS is a hard error, and on Linux it is simply ignored.
if sys.platform == "darwin":
    icon = os.path.join(ROOT, "assets", "talos.icns")
elif sys.platform == "win32":
    icon = os.path.join(ROOT, "assets", "favicon.ico")
else:
    icon = None                          # Linux takes it from talos.desktop
if icon is not None and not os.path.exists(icon):
    icon = None                          # never let a missing icon break a build

block_cipher = None

a = Analysis(  # noqa: F821
    [os.path.join(ROOT, "run.py")],
    pathex=[ROOT],
    binaries=[],
    datas=datas,
    hiddenimports=[
        "chess",
        "chess.variant",
        "chess.gaviota",
        "chess.polyglot",
        "chess.syzygy",
        "sqlite3",
        "numpy",
    ],
    hookspath=[os.path.join(ROOT, "packaging", "hooks")],
    runtime_hooks=[],
    excludes=[
        # none of these are used; they are worth tens of megabytes
        "PyQt6-WebEngine",
        "PyQt6.QtWebEngineCore",
        "PyQt6.QtWebEngineWidgets",
        "PyQt6.QtQuick",
        "PyQt6.QtQml",
        "PyQt6.Qt3DCore",
        "PyQt6.QtMultimedia",
        "PyQt6.QtBluetooth",
        "PyQt6.QtNfc",
        "PyQt6.QtPositioning",
        "PyQt6.QtSerialPort",
        "PyQt6.QtSensors",
        "PyQt6.QtTest",
        "PyQt6.QtDesigner",
        "PySide6",
        "tkinter",
        "matplotlib",
        "scipy",
        "pandas",
        "IPython",
        "notebook",
        "PIL.ImageQt",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)  # noqa: F821

exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="talos",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,                      # a GUI app: no console window
    disable_windowed_traceback=False,
    icon=icon,
    version=None,
)

coll = COLLECT(  # noqa: F821
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="talos",
)

# BUNDLE only exists on macOS; building an .app anywhere else is an error.
if sys.platform == "darwin":
    app = BUNDLE(  # noqa: F821
        coll,
        name=f"{APP_NAME}.app",
        icon=icon,
        bundle_identifier="org.taloschess.studio",
        version=APP_VERSION,
    )
