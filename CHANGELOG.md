# Changelog

All notable changes to AudioCLI are documented in this file. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project adheres to [Semantic Versioning](https://semver.org/).

## [2.0.0] — 2026-04-30

A complete, breaking rewrite. AudioCLI is repositioned from "ML data-prep tool" to "scriptable, batch-capable, cross-platform audio power-tool that runs DAW-quality effects from the command line." The engine is now Spotify's `pedalboard`; the v1 ML-flavored stack is gone.

### Migration from v1

- **Package rename:** `AudioCLI` (capital A) → `audiocli` (lowercase). Update imports: `from AudioCLI.modules.core.process import ...` → `from audiocli import run_per_file, AudioBuffer, op, ...`.
- **Command flattening:** the `process` / `target` / `download` grouping is gone. Every command is now top-level.
  - `process resample 44100` → `audiocli resample --target … --sr 44100`
  - `process mono -o` → `audiocli mono --target … -o` (per-op flag)
  - `target set <path>` → in REPL: `set targets <path>`; in one-shot: `--target <path>`
  - `target output <path>` → in REPL: `set output <path>`; in one-shot: `--output <path>`
  - `process file script.acli` → `audiocli run-script script.acli`
  - `process hook script.py` → `audiocli hook script.py --target …`
- **`phaseflip` renamed to `polarity`.**
- **v1 `.acli` scripts will not run on v2** — the command grammar changed. Update each line to the new shape.
- **`pip install audiocli` now works on Windows** (v1's `readline` install requirement broke Windows entirely).

### Removed

- **Torch and torchaudio entirely.** The default install no longer pulls torch. The `--pt` save flag is gone. ML-flavored ops (`RandPool`, the noise-injection primitives) are removed; the new plugin system is the path forward for users who want them.
- **`librosa`, `scipy`, `aeiou`, `tqdm`, `termcolor`, `readline`, `icli`, `einops`, `pdoc`** are no longer dependencies.
- **`download http`** recursive scrape — punted to a possible future `audiocli-plugin-http-scrape` plugin.
- **`process file`** unreachable command path — its loader-confusion bug is fixed by the new `run-script` command.
- **`one_shot_args` global state** — replaced by explicit per-call `run_per_file(...)` parameters.

### Added — engine

- **`pedalboard` is the engine.** All effects (`Compressor`, `Limiter`, `HighpassFilter`, `LowpassFilter`, `Reverb`, `Delay`, `Chorus`, `Phaser`, `Distortion`, `Bitcrush`, `PitchShift`, libsamplerate `Resample`), file I/O (WAV/FLAC/MP3/OGG/AAC via `pedalboard.io.AudioFile`), and VST3/AU hosting come from pedalboard's pre-built wheels. No system `ffmpeg`/`sox` required on any platform.
- **`AudioBuffer`** value type: `(channels, samples) float32` ndarray + `sr` + `subtype` + optional `format` / `quality` overrides. Same shape pedalboard expects, so passing buffers in/out of pedalboard chains is a noop.

### Added — pipeline

- **Real parallelism.** Single `ThreadPoolExecutor`, all files submitted at once, results consumed via `as_completed` so worker exceptions surface as `Result(ok=False, error=…)` instead of vanishing into an unconsumed iterator (the v1 batcher's bug).
- **Per-file `Result` + end-of-job `JobReport`** with `ok_count`, `failed_count`, `failures`, `duration_s`, `exit_code` (capped at 255).
- **Cancellation.** `run_per_file` accepts a `cancel_token: threading.Event`; flipping it from any thread skips pending submissions, lets in-flight files finish, and returns a partial `JobReport`.
- **Bulletproof:** a job over 1000 files where 50 are deliberately broken finishes, reports 950 successes + 50 failures with reasons, exits non-zero, and never hangs.
- **Modular execution seams.** Event dispatch, output path resolution, worker-count policy, and CLI rendering live in focused modules so the pipeline remains library-only execution code.

### Added — CLI

- Flat command namespace. Every op lives at the top level (`audiocli normalize`, not `audiocli process normalize`).
- Consistent flags across every op: `--target` (repeatable), `--output`, `--workers N`, `--recursive/--no-recursive`, `-o`, `--json`.
- Lazy imports: `audiocli --help` returns in ~120 ms. `numpy` / `pedalboard` / `pyloudnorm` / `platformdirs` / `click_repl` / `prompt_toolkit` / `rich` only load when an op actually runs.
- **Cross-platform REPL** via `click-repl` + `prompt_toolkit` (replaces v1's Unix-only `readline`-based shell). Same Typer app powers REPL and one-shot; commands are identical. ` ; ` chaining preserved. History persists across sessions.
- **`--json` event mode**: every op emits newline-delimited `{"type": "start" | "progress" | "file_done" | "error" | "done", ...}` events on stdout. Same protocol the eventual desktop app uses to subscribe via `on_event=`.
- **Persistent settings** at the `platformdirs` user-config location (XDG on Linux, `~/Library/Application Support/AudioCLI` on macOS, `%APPDATA%\AudioCLI` on Windows), JSON with a `"schema": 1` field for future migrations.
- **First-party command modules.** Special-case commands (`info`, `remove-silent`, `chunk`) are direct Typer commands, with reusable analysis, silence detection, and chunking logic split into focused library modules.

### Added — first-party ops

| Group | Ops |
|---|---|
| Levels & channels | `gain`, `normalize` (peak / LUFS), `polarity`, `mono`, `stereo` |
| Time-domain | `resample`, `pitch`, `trim`, `fade` (linear / exp / cosine) |
| Format | `convert` (wav/flac/mp3/ogg), `bitdepth` (8/16/24/32) |
| Effects (pedalboard) | `compress`, `limit`, `highpass`, `lowpass`, `reverb`, `delay`, `chorus`, `phaser`, `distortion`, `bitcrush` |
| VST/AU | `vst --plugin-path … --param key=value` |
| Special-case (analysis / side-effect / multi-output) | `info`, `remove-silent`, `chunk` |
| Power-user | `hook`, `run-script`, `shell` |

### Added — plugin system

- Public `@op` decorator (`from audiocli import op, AudioBuffer`). First-party ops use the same decorator plugin authors do.
- Discovery via Python entry-points: `[project.entry-points."audiocli.ops"] my-op = "my_pkg:my_func"`. AudioCLI loads them via `importlib.metadata.entry_points(group="audiocli.ops")` at startup.
- Conflict resolution: first-party wins on name collision; the conflict is logged at startup. Malformed plugin signatures raise `PluginError` at registration time.
- Plugin contract is **filter-shape only** in v2.0 (`(buf: AudioBuffer, **params) -> AudioBuffer`). The contract may broaden in v2.1+.

### Added — library API

- Public surface: `from audiocli import run_per_file, run_one, list_ops, get_op, AudioBuffer, op, Op, OpInfo, ParamInfo, AudioCLIError, LoadError, SaveError, OpError, PluginError, ConfigError`.
- `list_ops()` returns frozen dataclasses describing every registered op (name, help, kind, params with type/default/help/required) — designed to drive dynamic UI in a future desktop frontend.
- No `print()` / `sys.exit()` in any library module. The CLI layer renders; the library raises.

### Added — error model

Public exception hierarchy:

```text
AudioCLIError
├── LoadError
├── SaveError
├── OpError
├── PluginError
└── ConfigError
```

### Tooling

- Ruff lints + formats. `ruff check . && ruff format --check .` is the full lint pass.
- 313 tests covering every op (round-trip + correctness + negative), the pipeline (50-files-with-3-corrupt isolation, cancellation mid-batch, no-thread-leak), the CLI (every command's `--help`, `--json` JSON parseability, exit codes), the REPL (`;`-chaining, history, `set` persistence), the plugin loader (entry-point discovery, conflict resolution, malformed signature → `PluginError`), and the library API (`list_ops()` shape, `run_per_file` callable surface).
- CI matrix: `{ubuntu, macos, windows}-latest × {3.10, 3.11, 3.12}` running `ruff check`, `ruff format --check`, `pytest --cov`.

[2.0.0]: https://github.com/diontimmer/AudioCLI/releases/tag/v2.0.0
