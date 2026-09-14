# Packaging TALOS

A version tag runs `.github/workflows/release.yml` and creates a **draft**
release. The pipeline builds real distributable artifacts rather than merely
zipping a source checkout:

| Platform | Release asset | Validation / install path |
|---|---|---|
| Windows x64 | `talos-<version>-windows-x86_64-setup.exe` and `…-portable.zip` | PyInstaller + Inno Setup; per-user installer, optional PGN Open With entry that loads the selected game |
| Linux x86_64 | `talos-<version>-linux-x86_64.tar.gz` | extract, run `./install.sh`; archive contains its working desktop launcher, icon and AppStream metadata |
| macOS | `talos-<version>-macos-universal.zip` | PyInstaller `.app` bundle, currently unsigned |
| Browser | `talos-browser-<version>.zip` | static Pyodide payload for self-hosting |
| Android | `talos-android-<version>-debug.apk`; optionally `…-release.apk` | Capacitor/Gradle native shell; signed output appears only with maintainer secrets |

The app keeps bundled resources separate from mutable player data. In a frozen
build its seed database and artwork remain inside the bundle, while settings,
saved games and learning progress live in the platform user's data directory
(or `TALOS_DATA_DIR` for a managed/portable test install).

## Windows

```bat
py -m pip install -r requirements.txt pyinstaller
pyinstaller packaging\talos.spec --noconfirm --distpath dist
iscc /DMyAppVersion=2.2.0 packaging\windows-installer.iss
```

This produces `dist\installer\TALOS-Setup-2.2.0-x64.exe`. The installer is
per-user (`%LOCALAPPDATA%\Programs\TALOS`), so it does not need an elevation
prompt. It can create a desktop icon and register TALOS as an **Open with**
handler for `.pgn`; it does not silently replace another app's default
association. For a portable build, archive the contents of `dist\talos`.

The release job explicitly installs Inno Setup and fails if the expected setup
EXE is not produced; the `.iss` file is no longer an orphaned optional recipe.

## Linux

```bash
python -m pip install -r requirements.txt pyinstaller
pyinstaller packaging/talos.spec --noconfirm --distpath dist
bash packaging/linux-install.sh dist/talos
```

The installer copies the complete one-folder application to
`~/.local/lib/talos`, creates `~/.local/bin/talos`, and installs a desktop
entry, 512px icon and AppStream metadata under `~/.local/share`. Remove it
with:

```bash
bash packaging/linux-install.sh --uninstall
```

For a release archive, extract it and run `./install.sh` without arguments. It
locates `talos/`, `talos.desktop`, `talos.png` and `talos.metainfo.xml` beside
itself, so it does not depend on absent repository-relative `packaging/` or
`assets/` paths.

Qt needs runtime libraries such as `libxkbcommon0` and `libxcb-cursor0`; the
CI job installs and tests against those dependencies. On a minimal Debian or
Ubuntu desktop, run `bash tools/setup_env.sh` first.

## macOS

The same spec produces `dist/TALOS.app` on macOS. It is currently unsigned;
users need to right-click **Open** on first launch. Release signing/notarising
requires an Apple developer identity and is intentionally not fabricated by
CI.

## Android APK

The tracked `android/` project is a Capacitor shell around the local `web/`
payload. Build a debug APK with Node 20+, JDK 21 and Android SDK API 35:

```bash
npm ci
python -m pip install chess   # only python-chess is needed to build the web payload
npm run android:debug
```

See [`android/README.md`](android/README.md) for installation, signing and
first-boot runtime details. A public signed APK needs the repository owner's
keystore. The tag workflow always produces a real debug APK, and produces a
release APK only when `ANDROID_KEYSTORE_BASE64`,
`ANDROID_KEYSTORE_PASSWORD`, `ANDROID_KEY_ALIAS` and `ANDROID_KEY_PASSWORD`
are supplied as protected secrets.

## What ships inside the desktop bundle

| Path | Why |
|---|---|
| `data/lucas.db` | imported Lucas Chess training content (about 24 MB), copied to writable player data on first launch |
| `assets/` | icon set used by the window, taskbar and installer |
| `LICENSE`, `README.md`, `CHANGELOG.md` | offline documentation and licence |
| `engines/` | a README-only folder where users can add UCI engines |

One-folder desktop builds are deliberate: startup is fast, resource lookup is
reliable, and the user can see what the binary contains without putting their
personal database inside an installation directory.
