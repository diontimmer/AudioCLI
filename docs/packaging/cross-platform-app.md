# AudioCLI Cross-Platform App Packaging

Status: baseline smoke contract in place; packager choice still open.

AudioCLI's GUI target is one PySide6 desktop app for macOS, Windows, and Linux.
Core runtime code should stay platform-neutral; platform-specific behavior
belongs in small boundary modules, smoke scripts, and release packaging config.

## Baseline Contract

Every packaged app candidate must pass:

```shell
python scripts/gui_packaging_smoke.py --static --json
```

For native GUI candidates, also run:

```shell
python scripts/gui_packaging_smoke.py --construct-window
```

For a built executable, run:

```shell
python scripts/gui_packaging_smoke.py --entrypoint /path/to/audiocli-gui
```

Static smoke must not import PySide6 or load plugin native code. It checks that
the app can import lightweight metadata, exposes the VST/AU capability, and
resolves default plugin scan directories for the current platform.

## Platform Defaults

Default plugin directory discovery is conservative and shallow:

- macOS: VST3 and AU bundles under `/Library/Audio/Plug-Ins` and the user's
  `~/Library/Audio/Plug-Ins`.
- Windows: VST3 bundles under `%COMMONPROGRAMFILES%/VST3` and a user-level
  `%LOCALAPPDATA%/Programs/Common/VST3` fallback.
- Linux: VST3 bundles under `/usr/lib/vst3`, `/usr/local/lib/vst3`, and
  `~/.vst3`.

Discovery lists bundle paths only. Native plugin loading still happens only when
the user explicitly opens or runs a VST node.

## VST/AU Editor

The GUI opens a plugin's native editor through a helper process so the main
workspace event loop stays responsive. The helper sends JSONL status and
parameter snapshots back to the GUI. Reported parameters are mirrored into the
selected VST node as AudioCLI `key=value` entries and shown in a paged, read-only
parameter panel.

Default packaging smoke must keep discovery and editor hosting separate:
discovery is safe metadata enumeration, while native editor launch remains an
explicit test path with a known plugin.

## Packager Evaluation

Evaluate packagers against the same smoke contract on all three operating
systems. Record, per candidate:

- OS, CPU architecture, and Python version.
- Packager and version.
- Uncompressed app size and compressed installer/archive size.
- Whether PySide6 Qt platform plugins are bundled correctly.
- Whether `pedalboard`, `numpy`, and AudioCLI's analysis dependencies load.
- Whether the helper process can launch with the bundled Python.
- Whether the VST editor helper can report mirrored parameters when a live test
  plugin is provided.
- Whether compact/code-font GUI surfaces render legibly in the packaged app.
- Signing/notarization or installer blockers.

Start with the lowest-friction PySide6-compatible packager, but keep packager
work out of core GUI modules unless a boundary fix is proven necessary.
