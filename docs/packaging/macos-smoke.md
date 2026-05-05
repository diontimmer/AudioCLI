# AudioCLI GUI macOS packaging smoke

Status: preparation-only until run on native macOS.

## Scope

This spike is macOS-first. Windows and Linux bundles stay follow-up work. Signing,
notarization, hardened runtime, entitlements, DMG polish, and installer polish are
deferred until after a packager is chosen.

Packager is intentionally undecided. Use this document to collect evidence before
choosing PyInstaller, Briefcase, Nuitka, or another route.

## Bundle size limit

Bundle size limit means the max app artifact size we are willing to ship. Measure
both:

- compressed artifact: `.zip` or `.dmg`
- uncompressed artifact: `.app` directory size

No hard fail threshold exists yet. Record sizes first, choose limit later.

## Fixed plugin scan directories

The packaged GUI smoke scans only these macOS plugin directories by default:

- `/Library/Audio/Plug-Ins/VST3`
- `~/Library/Audio/Plug-Ins/VST3`
- `/Library/Audio/Plug-Ins/Components`
- `~/Library/Audio/Plug-Ins/Components`

The scan is conservative. It lists direct child `.vst3` and `.component` bundles.
It does not recurse, follow symlinks, import `pedalboard`, or load plugin native
code. Live plugin hosting remains opt-in via `AUDIOCLI_TEST_VST_PATH`.

## Source smoke on macOS

```shell
python -m pip install -e '.[dev,gui]'
ruff check .
ruff format --check .
pytest -q
python scripts/macos_gui_smoke.py --static
python scripts/macos_gui_smoke.py --construct-window
```

Optional live plugin smoke:

```shell
AUDIOCLI_TEST_VST_PATH='/Library/Audio/Plug-Ins/VST3/SomePlugin.vst3' \
  python scripts/macos_gui_smoke.py --construct-window
```

## Packaged smoke

After building a candidate app, run static smoke from the packaged entry point if
available:

```shell
/path/to/audiocli-gui --packaged-static-smoke
```

Then run source-side smoke against the packaged executable:

```shell
python scripts/macos_gui_smoke.py --entrypoint /path/to/audiocli-gui
```

Then manually launch the app:

```shell
open /path/to/AudioCLI.app
```

Manual checks:

1. App opens without terminal tracebacks.
2. Capability browser populates.
3. `VST / AU Plugin` capability appears.
4. Fixed plugin directories are visible in logs/smoke output or equivalent UI metadata.
5. Simple Gain chain can process a small audio file.
6. Save/load chain works after app relaunch.

## Candidate evidence template

For each packager tested, record:

- Toolchain and version:
- Python version and architecture:
- macOS version and CPU architecture:
- Build command:
- Build time:
- Uncompressed `.app` size:
- Compressed artifact size:
- Static packaged smoke output:
- GUI launch result:
- Capability discovery result:
- PySide6/Qt inclusion notes:
- numpy inclusion notes:
- pedalboard inclusion notes:
- AudioCLI module inclusion notes:
- Plugin directory scan result:
- Live plugin result, if tested:
- Signing/notarization blockers:
- Recommendation:

## Current recommendation state

No canonical packager chosen yet. Pick after native macOS evidence exists. Start
with the lowest-friction PySide6 baseline if no other constraint dominates, but
record failures instead of forcing packager hacks into core code.
