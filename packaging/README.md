# Packaging TALOS

Everything here is driven by GitHub Actions on a tag push
(`.github/workflows/release.yml`), but every step also runs by hand.

## Windows

```bat
pip install pyinstaller
pyinstaller packaging\talos.spec --noconfirm --distpath dist
```

Then either zip `dist\talos`, or build a real installer with
[Inno Setup](https://jrsoftware.org/isinfo.php):

```bat
iscc packaging\windows-installer.iss     :: writes dist\installer\TALOS-Setup.exe
```

## Linux

```bash
pip install pyinstaller
pyinstaller packaging/talos.spec --noconfirm --distpath dist
tar -czf talos-linux-x86_64.tar.gz -C dist talos
```

Users install it with the bundled script, which drops the app in
`~/.local/lib/talos`, a launcher in `~/.local/bin`, a `.desktop` entry, the
icon and the AppStream metadata:

```bash
bash packaging/linux-install.sh dist/talos
```

Qt needs its runtime libraries (`libxkbcommon0`, `libxcb-cursor0`, …). They
are present on any desktop distribution; on a minimal container run
`bash tools/setup_env.sh` first.

## macOS

The same spec produces `dist/TALOS.app` (the `BUNDLE` step is macOS-only).
It is unsigned — users need to right-click ▸ Open the first time.

## What goes in the bundle

| Path | Why |
|---|---|
| `data/lucas.db` | the imported Lucas Chess training content (24 MB) |
| `assets/` | icons, used by the window and the notifications |
| `LICENSE`, `README.md`, `CHANGELOG.md` | shipped next to the app |
| `engines/` | an empty folder with a README — users drop UCI engines there |

The bundle is one-folder on purpose: start-up is instant and the database
stays visible, so a user can delete it if they only want to play.
