---
hide:
  - navigation
---

# AudioCLI

**A scriptable, batch-capable, cross-platform audio power-tool that runs DAW-quality effects from the command line.** Built on Spotify's [`pedalboard`](https://github.com/spotify/pedalboard) — pre-built wheels for Linux, macOS, and Windows mean no system `ffmpeg`/`sox` to wrangle.

[![PyPI](https://img.shields.io/pypi/v/audiocli.svg)](https://pypi.org/project/audiocli/)
[![Python](https://img.shields.io/pypi/pyversions/audiocli.svg)](https://pypi.org/project/audiocli/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](https://github.com/diontimmer/AudioCLI/blob/main/LICENSE)

## Three ways to drive it

<div class="grid cards" markdown>

-   :material-console:{ .lg .middle } **Command line**

    ---

    One-shot ops, parallel batches, JSON event streams. `audiocli gain --target ./stems --db 6`.

    [:octicons-arrow-right-24: CLI guide](cli.md)

-   :material-application:{ .lg .middle } **Desktop workspace**

    ---

    PySide6 GUI for browsing tools, building chains, hosting VST/AU plugins. Same metadata as the CLI.

    [:octicons-arrow-right-24: Desktop GUI](gui.md)

-   :material-language-python:{ .lg .middle } **Python library**

    ---

    `from audiocli import run_per_file`. GUI-friendly with progress events, cancellation, and typed op metadata.

    [:octicons-arrow-right-24: Library API](library.md)

</div>

## Install

```shell
pip install audio-cli
```

!!! note "PyPI distribution name"

    The package is published as **`audio-cli`** (hyphenated). The unhyphenated
    `audiocli` on PyPI is an unrelated audio-measurement project, not this one.

Python ≥ 3.10. No `torch`, no `librosa`, no `scipy`. `audiocli --help` returns in under 150 ms.

The optional desktop GUI:

```shell
pip install "audio-cli[gui]"
audiocli-gui
```

## Quickstart

```shell
# Apply 6 dB of gain to every WAV in a folder, write to a new dir
audiocli gain --target ./stems --db 6 --output ./stems-louder

# Normalize a folder of stems to -1 dBFS peak in parallel
audiocli normalize --target ./stems --peak-db -1 --workers 8

# Convert WAVs to FLAC in place (writing alongside the source)
audiocli convert --target ./stems --format flac

# LUFS normalization for streaming targets
audiocli normalize --target ./mixes --lufs -14

# A 1000-file batch where 50 files are corrupt — 950 succeed, 50 are
# reported, exit code is non-zero, the job never hangs
audiocli compress --target ./big-folder --ratio 4 --threshold-db -20 --workers 16
```

## What's included

- **34+ first-party ops** — gain, EQ, compression, reverb, delay, chorus, phaser, distortion, bitcrush, sample-rate conversion, format conversion, LUFS normalization, silence trim, fade, chunking, and more. See the [ops reference](ops-reference.md).
- **VST3 / AU plugin hosting** via pedalboard, in both CLI and GUI. The GUI can open a plugin's native editor in a helper process and mirror parameters back into the chain.
- **Interactive REPL** with chain commands, persistent session state, and `.acli` scripts.
- **Python hook scripts** for one-off transforms without packaging a plugin.
- **Plugin entry-points** — third-party `pip install`-able op packages register through `audiocli.ops`.
- **Library API** with cancellation tokens, structured events, and frozen op metadata for dynamic UI generation.

## Project status

AudioCLI 2.0 is the in-flight rewrite. The CLI is feature-complete; the desktop GUI is the active polish frontier. CI runs the suite on `{ubuntu, macos, windows} × {3.10, 3.11, 3.12}`.

For build and distribution, see [packaging](packaging/index.md) — the macOS pipeline ships a signed and notarized `.app` bundle with the CLI embedded.

## License

[MIT](https://github.com/diontimmer/AudioCLI/blob/main/LICENSE).
