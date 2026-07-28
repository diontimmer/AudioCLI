# AudioCLI

A scriptable, batch-capable, cross-platform audio power-tool that runs DAW-quality effects from the command line. Built on Spotify's [`pedalboard`](https://github.com/spotify/pedalboard) — pre-built wheels for Linux, macOS, and Windows mean no system `ffmpeg`/`sox` to wrangle.

## Install

```shell
pip install audiocli-tools
```

> **Note on the name:** the PyPI distribution is `audiocli-tools`. The bare
> `audiocli` on PyPI is an unrelated audio-measurement project — `pip install
> audiocli` will get you the wrong tool. Once installed, everything in your
> shell and your code stays `audiocli` / `audiocli-gui` / `from audiocli import ...`.

Python ≥ 3.10. No `torch`, no `librosa`, no `scipy`. `audiocli --help` returns in under 150 ms.

The optional desktop GUI is being developed as a cross-platform PySide6 app:

```shell
pip install "audiocli-tools[gui]"
audiocli-gui
```

The GUI uses the same capability metadata as the CLI/library, with a compact workspace for browsing tools, building chains, and running batches.

## One-shot mode

Every command takes one or more `--target` paths (files or directories), an optional `--output`, and `--workers N` for parallelism. Directory targets recurse by default; pass `--no-recursive` to flatten.

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

## Interactive REPL

```shell
audiocli shell
```

Chain commands with ` ; `. `set targets <paths>`, `set output <dir>`, `set workers N` configure session state and persist to disk so they survive restarts. `show` prints the current session.

```text
audiocli> set targets ./stems ; set output ./out ; resample 22050 ; mono -o
```

## First-party ops

| Command | Description | Example |
|---|---|---|
| `gain` | Apply gain in decibels | `audiocli gain --target … --db 6` |
| `normalize` | Peak (dBFS) or LUFS normalization | `audiocli normalize --target … --peak-db -1` |
| `polarity` | Invert sample polarity | `audiocli polarity --target …` |
| `mono` | Mix down to 1 channel | `audiocli mono --target …` |
| `stereo` | Duplicate mono → 2-channel stereo | `audiocli stereo --target …` |
| `resample` | Change sample rate (libsamplerate) | `audiocli resample --target … --sr 22050` |
| `pitch` | Pitch-shift in semitones | `audiocli pitch --target … --semitones -2` |
| `trim` | Strip leading/trailing silence | `audiocli trim --target … --threshold-db -60` |
| `fade` | Fade in/out (linear, exp, cosine) | `audiocli fade --target … --fade-in-s 0.5 --shape cosine` |
| `convert` | Change output format (wav/flac/mp3/ogg) | `audiocli convert --target … --format flac` |
| `bitdepth` | Set output bit depth (8/16/24/32) | `audiocli bitdepth --target … --bits 24` |
| `compress` | Dynamic range compression | `audiocli compress --target … --ratio 4 --threshold-db -20` |
| `limit` | Peak limiting | `audiocli limit --target … --threshold-db -1` |
| `highpass` | High-pass filter | `audiocli highpass --target … --hz 80` |
| `lowpass` | Low-pass filter | `audiocli lowpass --target … --hz 8000` |
| `reverb` | Algorithmic reverb | `audiocli reverb --target … --room-size 0.6 --wet 0.3` |
| `delay` | Feedback delay | `audiocli delay --target … --time-s 0.4 --feedback 0.4` |
| `chorus` | Modulated chorus | `audiocli chorus --target … --rate-hz 1.0 --depth 0.25` |
| `phaser` | All-pass phaser | `audiocli phaser --target … --rate-hz 1.0` |
| `distortion` | Soft-clip distortion | `audiocli distortion --target … --drive-db 25` |
| `bitcrush` | Bit-depth reduction | `audiocli bitcrush --target … --bit-depth 8` |
| `vst` | Host any VST3 / AU plugin | `audiocli vst --target … --plugin-path ./MyComp.vst3 --param Threshold=-12` |
| `info` | Print sr, channels, duration, peak, RMS, LUFS | `audiocli info --target …` |
| `remove-silent` | Delete files below an RMS threshold | `audiocli remove-silent --target … --threshold-db -55` |
| `chunk` | Split files into N-second pieces | `audiocli chunk --target … --seconds 5.0` |
| `hook` | Run a one-off Python transform | `audiocli hook ./my_transform.py --target …` |
| `run-script` | Run a `.acli` batch file | `audiocli run-script ./pipeline.acli` |
| `shell` | Start the interactive REPL | `audiocli shell` |

Run `audiocli <command> --help` for the full flag set on any op.

## `--json` event mode

Every op accepts `--json`. When set, the CLI emits one JSON object per line on stdout — newline-delimited so any other process can parse it.

```shell
audiocli normalize --target ./stems --peak-db -1 --json
```

```json
{"type": "start", "total": 12, "workers": 8}
{"type": "file_done", "path": "./stems/a.wav", "ok": true, "error": null}
{"type": "progress", "done": 1, "total": 12, "current": "./stems/a.wav"}
…
{"type": "done", "ok": 12, "failed": 0, "duration_s": 3.42}
```

Exit code is 0 on full success, otherwise the failure count (capped at 255). Pipe straight into your CI script or progress UI.

## Desktop GUI

`audiocli-gui` is the v2 desktop direction for macOS, Windows, and Linux. It is a thin workspace over the same pipeline and capability model: tool metadata drives the browser and parameter panel, saved chains can round-trip through native chain files or `.acli` scripts, and long runs use the library event/cancellation path.

For VST/AU work, the GUI discovers installed plugin bundles from conservative platform defaults without loading native code. Selecting a `VST / AU Plugin` node shows detected plugins, accepts an explicit plugin path, and can open the plugin's native editor in a helper process. Parameters reported by the editor are mirrored back into the node as repeatable `key=value` entries, with a paged, read-only parameter view in the GUI.

The current GUI polish favors dense desktop use: compact controls, icon buttons where practical, and code-font lists/empty states for scan- and capability-heavy surfaces.

## Use as a library

```python
from audiocli import run_per_file, list_ops, get_op

# Enumerate registered ops with full param metadata
for op in list_ops():
    print(op.name, [p.name for p in op.params])

# Drive a batch from Python with a progress callback
gain = get_op("gain")
report = run_per_file(
    ["song1.wav", "song2.wav"],
    gain,
    {"db": 6.0},
    output="./out",
    workers=4,
    on_event=lambda evt: print(evt),
)
print(report.ok_count, "ok,", report.failed_count, "failed")
```

The library API is intentionally GUI-friendly:

- `cancel_token: threading.Event` — flip from any thread to abort a long batch. In-flight files complete; pending submissions skip.
- `on_event` — same protocol as the `--json` CLI mode, so a desktop app can render progress without shelling out.
- `list_ops()` returns frozen dataclasses (`OpInfo` / `ParamInfo`) describing every op's parameters — type, default, help, required — for dynamic UI generation.
- No `print()` or `sys.exit()` in any library module. Errors are raised from the public hierarchy: `AudioCLIError` → `LoadError`, `SaveError`, `OpError`, `PluginError`, `ConfigError`.

## Plugin authors

A plugin is a regular pip-installable package that registers ops via Python entry-points. The minimum viable plugin:

```python
# my_plugin/ops.py
from audiocli import op, AudioBuffer


@op(name="reverse", help="Reverse the audio along the time axis.")
def reverse(buf: AudioBuffer) -> AudioBuffer:
    return AudioBuffer(data=buf.data[:, ::-1], sr=buf.sr, subtype=buf.subtype)
```

```toml
# my_plugin/pyproject.toml
[project]
name = "audiocli-plugin-reverse"
version = "0.1.0"
dependencies = ["audiocli>=2"]

[project.entry-points."audiocli.ops"]
reverse = "my_plugin.ops:reverse"
```

```shell
pip install audiocli-plugin-reverse
audiocli reverse --target ./stems   # appears as a first-class command
```

The plugin contract is **filter-shape only** in v2.0: `(buf: AudioBuffer, **params) -> AudioBuffer`. First-party special-case ops (`info`, `chunk`, `remove-silent`, `vst`) bypass the contract because their shape is multi-output / analysis / side-effect; the plugin contract may broaden in v2.1+.

If a plugin's name collides with a first-party op, the first-party op wins and the conflict is logged at startup. Malformed plugin signatures raise `PluginError` at registration time, not at run time.

## Power-user escape hatches

Don't want to publish a package for a one-off experiment? Drop a Python file and:

```shell
audiocli hook ./my_transform.py --target ./stems --custom-key value
```

```python
# my_transform.py
from audiocli import AudioBuffer


def transform(buf: AudioBuffer, custom_key: str = "") -> AudioBuffer:
    return AudioBuffer(data=buf.data * 0.5, sr=buf.sr, subtype=buf.subtype)
```

Save a sequence of commands as a `.acli` script and re-run it:

```text
# pipeline.acli
gain --target ./stems --db -6 --output ./out
trim --target ./out --threshold-db -55
fade --target ./out --fade-out-s 0.5
```

```shell
audiocli run-script ./pipeline.acli
```

## Settings

Persisted at the platformdirs user-config location (XDG on Linux, `~/Library/Application Support/AudioCLI` on macOS, `%APPDATA%\AudioCLI` on Windows). JSON with a `"schema": 1` field for forward-compatibility. Stores: targets, output dir, workers, recursive flag, last-used overwrite preference. Override with `AUDIOCLI_SETTINGS_FILE` for testing.

## Development

```shell
git clone https://github.com/diontimmer/AudioCLI
cd AudioCLI
pip install -e ".[dev]"
ruff check .
ruff format --check .
pytest --cov=audiocli
```

CI runs the suite on `{ubuntu, macos, windows} × {3.10, 3.11, 3.12}`.

## License

MIT.
