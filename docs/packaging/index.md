# Packaging

AudioCLI ships in three forms:

- **PyPI package** (`pip install audio-cli`) — the canonical distribution for developers and CI. Note the hyphen — `audiocli` on PyPI is an unrelated project.
- **Desktop bundles** — signed, notarized `.app` (macOS), `.exe` (Windows), and onedir (Linux) builds that include the GUI and CLI together.
- **Custom integrations** — embedded in other tools via the [library API](../library.md).

This section covers the desktop bundle build.

## Layout

The packaging assets live in [`packaging/`](https://github.com/diontimmer/AudioCLI/tree/main/packaging) at the repo root:

| File | Role |
|---|---|
| `audiocli-gui.spec` | PyInstaller spec — produces one bundle containing both the GUI exe and the `acli` CLI exe, sharing all native libs (pedalboard, soundfile, numpy, PySide6). |
| `launcher.py` | GUI entry point (`audiocli.gui.app:main`). |
| `cli_launcher.py` | CLI entry point (`audiocli.cli:app`). |
| `entitlements.plist` | Hardened-runtime entitlements for macOS — disables library validation so pedalboard can dlopen third-party VST/AU plugins. |
| `icon.svg` | Source icon (Dracula palette). |
| `icon.icns`, `icon.ico`, `icon.png` | Generated platform icons. |
| `build_icons.py` | SVG → `.icns` / `.ico` / `.png` generator. Prefers `rsvg-convert`, falls back to `cairosvg`. |
| `build_macos.sh` | End-to-end macOS pipeline: icons → PyInstaller → sign every Mach-O → sign frameworks → smoke test → notarize → staple → re-zip. |

## Why a single bundle for GUI + CLI

The CLI's `acli` binary lives inside the same `.app` as the GUI, sharing one copy of every native library (~half the disk footprint of two independent bundles). Users symlink it into their PATH after install:

```shell
sudo ln -s /Applications/AudioCLI.app/Contents/MacOS/acli /usr/local/bin/audiocli
```

The CLI is named `acli` inside the bundle on purpose — APFS is case-insensitive by default, so `AudioCLI` and `audiocli` would collide. The shell symlink can be whatever name you want.

## Pages

- [macOS build pipeline](macos-build.md) — the day-to-day `./packaging/build_macos.sh` flow.
- [Cross-platform app notes](cross-platform-app.md) — Windows / Linux specifics.
- [macOS smoke harness](macos-smoke.md) — the `--packaged-static-smoke` flag and the cross-platform smoke runner that validates frozen bundles in CI.
- [Risk register](packaging-risk-register.md) — known gotchas and mitigations.
