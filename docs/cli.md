# Command-line interface

The CLI is the canonical surface for AudioCLI. Every op is a subcommand, every subcommand accepts the same target/output/parallelism flags, and the whole thing emits machine-readable events on demand.

```shell
audiocli --help
```

## One-shot mode

Every command takes one or more `--target` paths (files or directories), an optional `--output`, and `--workers N` for parallelism. Directory targets recurse by default; pass `--no-recursive` to flatten.

```shell
# Single file
audiocli gain --target ./song.wav --db 6

# Whole folder with parallelism
audiocli normalize --target ./stems --peak-db -1 --workers 8

# Multiple targets
audiocli compress --target ./vox ./drums --ratio 4 --threshold-db -20

# Output to a different directory (preserves relative paths)
audiocli convert --target ./input --format flac --output ./converted

# In-place by default if --output is omitted (writes alongside source)
audiocli bitdepth --target ./stems --bits 24
```

Run `audiocli <command> --help` for the full flag set on any op.

## Output and overwrite

Two destination modes:

- **`--output <dir>`** — writes processed files into `<dir>`, preserving the relative path from each target root. Existing files are skipped unless `--overwrite` is passed.
- **No `--output`** — writes alongside each source file with a default suffix like `_gain.wav`. Suffixing keeps you from clobbering inputs by accident.

You can also use path-token templates for destinations like `{stem}-processed{ext}` — see the per-op `--output` help.

## Interactive REPL

```shell
audiocli shell
```

The shell maintains session state across commands and persists it to disk so it survives restarts.

```text
audiocli> set targets ./stems
audiocli> set output ./out
audiocli> set workers 8
audiocli> show
audiocli> resample 22050 ; mono -o
```

`set` configures session defaults. `show` prints the current session. Chain multiple commands on one line with ` ; `.

## Scripts

Save a sequence of commands as a `.acli` script and re-run it:

```text title="pipeline.acli"
gain --target ./stems --db -6 --output ./out
trim --target ./out --threshold-db -55
fade --target ./out --fade-out-s 0.5
```

```shell
audiocli run-script ./pipeline.acli
```

Lines starting with `#` are comments. Each non-comment line is a full `audiocli` invocation with its own flags.

## Python hook scripts

For one-off transforms without packaging a plugin:

```python title="my_transform.py"
from audiocli import AudioBuffer

def transform(buf: AudioBuffer, custom_key: str = "") -> AudioBuffer:
    return AudioBuffer(data=buf.data * 0.5, sr=buf.sr, subtype=buf.subtype)
```

```shell
audiocli hook ./my_transform.py --target ./stems --custom-key value
```

Any extra `--key value` flags get forwarded to the `transform` function as keyword arguments. See [plugins & hooks](plugins.md) for the longer story.

## JSON event mode

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

Exit code is 0 on full success, otherwise the failure count (capped at 255). Pipe straight into a CI script or progress UI.

## Settings

CLI settings persist at the [platformdirs](https://github.com/platformdirs/platformdirs) user-config location:

- Linux: `$XDG_CONFIG_HOME/AudioCLI/settings.json`
- macOS: `~/Library/Application Support/AudioCLI/settings.json`
- Windows: `%APPDATA%\AudioCLI\settings.json`

The file is JSON with a `"schema": 1` field for forward-compatibility. Stored fields: targets, output dir, workers, recursive flag, last-used overwrite preference.

Override the path with `AUDIOCLI_SETTINGS_FILE=<path>` (useful for tests and isolated environments).

## Exit codes

- `0` — every input processed without error
- `1`-`254` — number of files that failed (per-file errors are reported but don't abort the batch)
- `255` — more than 254 failures, or a fatal error before any file ran
