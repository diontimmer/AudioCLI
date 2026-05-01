Status: needs-triage

# AudioCLI v2.0 — Pedalboard-Powered Audio Power-Tool

## Problem Statement

AudioCLI today is a fragile, ML-flavored batch processor. Audio engineers — the people who would actually benefit from a fast, reliable batch CLI — can't easily install or use it:

- The dependency stack (`torch`, `torchaudio`, `aeiou`) is enormous, slow to install, and unnecessary for the audio-engineering tasks the tool is shaped around.
- `readline` is in `install_requires`, which breaks Windows installs outright.
- Several headline commands are silently broken: GPU device transfer is a no-op (`audio.to(device)` discarded), `process mono` iterates a tqdm counter, `process bitdepth` calls `len()` on a string, `process chunk` confuses samples with seconds, `process hook` passes a list to a single-file loader, `download http`'s signature binds the URL to `session`, `process file` is unreachable.
- The "batching" architecture is theatre: chunks of N files each spawn an N-worker pool that processes exactly N tasks via `executor.map` (lazy, never consumed) — batches serialize against each other, in-batch parallelism is a flat pool in disguise, and worker exceptions vanish into the unconsumed iterator.
- `--help` takes ~5 seconds because torch/torchaudio/aeiou are imported eagerly.
- The op set itself is ML-flavored (random-pool, noise injection, .pt save) and missing the staples an audio engineer expects (normalize, trim silence, fade, gain, format conversion, loudness analysis, EQ, compression, reverb).
- There is no plugin system, so extending the tool requires forking it.
- There is no library API, so a future desktop GUI cannot reuse the engine without shelling out.

## Solution

Rewrite AudioCLI as an **audio-engineer-focused batch power-tool built on Spotify's `pedalboard`**, with a public plugin system and a library-first architecture suitable for an eventual cross-platform desktop GUI.

The product is repositioned from "ML data-prep tool" to "scriptable, batch-capable, cross-platform audio power-tool that runs DAW-quality effects from the command line." Pedalboard provides the engine (effects, I/O, VST hosting). Numpy + a small core handle the file-level ops pedalboard doesn't cover. Every op — first-party or plugin — is a pure function over an `AudioBuffer`, making the engine trivially driveable from a Python desktop app down the road.

Concretely:

- Drop `torch`, `torchaudio`, `aeiou`, `librosa`, `scipy`, `tqdm`, `termcolor`, `readline`, `icli`, `einops`, `pdoc`.
- Add `pedalboard` (engine), `numpy` (buffers), `typer` (CLI), `click-repl` + `prompt_toolkit` (cross-platform REPL replacing `readline`), `rich` (progress + styled output), `pyloudnorm` (LUFS), `platformdirs` (XDG paths).
- Public plugin system via Python entry-points (`audiocli.ops` group); first-party ops use the same `@op` decorator they expose to plugin authors.
- Library-first architecture: every op is a pure function `(buf: AudioBuffer, **params) -> AudioBuffer`; the CLI is a thin Typer shell over the library.
- Real pipeline: a single `ThreadPoolExecutor`, `as_completed` iteration so worker exceptions surface, per-file `Result` aggregation, end-of-job summary, structured progress/error events.
- Cross-platform install: pedalboard ships pre-built wheels for Linux/macOS/Windows; no system ffmpeg/sox required; CI matrix proves it.
- Bulletproof bar: a job over 1000 files where 50 are deliberately broken must finish, report 950 successes + 50 failures with reasons, exit non-zero, and never hang or silently drop work.

## User Stories

### Audio engineer / sound designer

1. As an audio engineer, I want to install AudioCLI with `pip install audiocli` on Windows, macOS, and Linux without any system dependencies, so that I can use it on whichever machine I'm at.
2. As an audio engineer, I want `audiocli --help` to respond in under 100ms, so that exploring the tool feels instant.
3. As an audio engineer, I want to normalize a folder of stems to -1 dBFS peak with one command, so that I can prep deliverables in batch.
4. As an audio engineer, I want to LUFS-normalize a folder to -14 LUFS, so that I can match streaming-platform loudness targets in batch.
5. As an audio engineer, I want to trim leading and trailing silence from a folder of recordings with a configurable threshold, so that I can clean up takes without opening each in a DAW.
6. As an audio engineer, I want to apply a fade-in and fade-out (linear / exponential / equal-power) across a folder, so that I can prep loops or stems consistently.
7. As an audio engineer, I want to apply per-file gain in dB, so that I can rescale a folder uniformly.
8. As an audio engineer, I want to convert a folder of WAVs to FLAC or MP3 with a chosen bitdepth/quality, so that I can produce delivery formats in batch.
9. As an audio engineer, I want to resample a folder to a target sample rate at high quality, so that I can prep assets for a target system.
10. As an audio engineer, I want to convert files between mono and stereo, so that I can match downstream channel requirements.
11. As an audio engineer, I want to invert polarity on a folder, so that I can fix mis-wired stems.
12. As an audio engineer, I want to chunk long files into fixed-length pieces with optional silence padding, so that I can prep training samples or loop libraries.
13. As an audio engineer, I want to change bit depth (8/16/24/32) on save, so that I can match a target spec.
14. As an audio engineer, I want to pitch-shift by semitones, so that I can transpose a batch of stems.
15. As an audio engineer, I want to apply pedalboard effects (compression, limiting, EQ filters, reverb, delay, chorus, phaser, distortion, bitcrush) per-file in batch, so that I can run preset chains over many files.
16. As an audio engineer, I want to host any VST3 or AU plugin from the CLI with parameter overrides, so that I can drive my favourite plugins in batch without opening a DAW.
17. As an audio engineer, I want to print metadata about a file (sample rate, channels, duration, peak, RMS, LUFS), so that I can audit assets quickly.
18. As an audio engineer, I want to delete files below a silence threshold from a folder, so that I can clean up empty takes.
19. As an audio engineer, I want a confirmation that destructive operations (overwrite, delete) actually happened, with a summary, so that I can trust the tool didn't silently fail.
20. As an audio engineer, I want one bad file in a 1000-file batch to be reported and skipped — not crash the whole job — so that I never lose a long-running run to a single corrupt asset.
21. As an audio engineer, I want a non-zero exit code if any file failed, so that I can pipe the tool into shell scripts and CI.
22. As an audio engineer, I want a progress bar that shows files-completed / files-total / current-file / ETA, so that I know how much longer to wait.
23. As an audio engineer, I want to chain commands with ` ; ` in the REPL so that I can run multi-step pipelines interactively.
24. As an audio engineer, I want to persist my target/output folders and worker count between sessions, so that I don't have to re-set them every time.
25. As an audio engineer, I want my command history saved across REPL sessions, so that I can re-run recent commands quickly.
26. As an audio engineer, I want to overwrite source files with `-o` or write to an output directory, so that I have control over where results land.
27. As an audio engineer, I want to save a sequence of commands as an `.acli` script and re-run it, so that I can templatize my workflows.

### Scripting / automation user

28. As a script author, I want to invoke any command in one shot (`audiocli normalize --target ./songs --lufs -14`), so that I can call the tool from shell scripts and Makefiles.
29. As a script author, I want a `--json` event mode that emits one JSON object per line on stdout, so that I can parse progress and errors in another program.
30. As a script author, I want a documented exit-code contract (0 = all ok, non-zero = failures), so that I can fail CI builds reliably.
31. As a script author, I want every command to support `--workers N` to control parallelism, so that I can tune throughput for the hardware.
32. As a script author, I want lazy imports so that command discovery (`--help`, `--version`) is fast even when heavy effects libraries exist, so that scripting feels responsive.
33. As a script author, I want a stable CLI surface with no breaking changes within v2.x, so that I can build durable automation.

### Plugin author

34. As a plugin author, I want to write a new op as a single decorated Python function with type hints, so that I don't have to learn a plugin framework.
35. As a plugin author, I want to publish my plugin as a normal pip package, so that users can install it with `pip install audiocli-plugin-myop`.
36. As a plugin author, I want my plugin's parameters to become CLI arguments automatically based on type hints and defaults, so that I don't have to write argparse code.
37. As a plugin author, I want my plugin to declare its own dependencies (numba, torch, librosa, whatever) without polluting AudioCLI's core deps, so that the core stays light.
38. As a plugin author, I want to read the same `AudioBuffer` and return the same `AudioBuffer` shape that first-party ops use, so that the plugin contract isn't second-class.
39. As a plugin author, I want a discoverable Python API (`from audiocli import op, AudioBuffer`), so that I can find what to import without reading internals.
40. As a plugin author, I want my plugin's docstring to become the command help text, so that documentation is co-located with the function.
41. As a plugin author, I want clear errors when my plugin's signature is malformed at registration time, so that I find out at install time, not at run time.

### Power user / quick experiments

42. As a power user, I want to drop a Python file into the filesystem and run it via `audiocli hook script.py` for a one-off transform, so that I don't need to publish a package for a throwaway experiment.
43. As a power user, I want the `hook` command to receive a single `AudioBuffer` per call (not a list), so that I can write the simplest possible custom function.

### Eventual desktop-app developer (forward-looking)

44. As the future desktop-app developer, I want to import AudioCLI as a Python library and call `run_per_file(files, op, on_progress=..., on_error=...)` with my own callbacks, so that I can wire progress to UI widgets.
45. As the future desktop-app developer, I want a cancellation token I can flip from the UI to abort a long-running batch, so that the user can stop a job mid-way.
46. As the future desktop-app developer, I want the engine to have no `print` calls or `sys.exit` inside the library layer, so that the GUI can render output as it sees fit.
47. As the future desktop-app developer, I want to enumerate registered ops at runtime (name, params, types, help), so that I can build dynamic UI for each op.
48. As the future desktop-app developer, I want the same `--json` event protocol used by the CLI to be available for free if I shell out instead of importing, so that I have two integration paths.

### CI / maintainer

49. As the maintainer, I want CI to run on Linux, macOS, and Windows across Python 3.10 / 3.11 / 3.12, so that cross-platform regressions are caught at PR time.
50. As the maintainer, I want a single ruff invocation to lint and format the codebase, so that style is one tool.
51. As the maintainer, I want every op to have a round-trip test, a correctness test, and a negative test, so that fixes don't regress.
52. As the maintainer, I want a pipeline-level test that proves error isolation (50 files, 3 corrupt, 47 succeed), so that the bulletproof claim is enforced.

## Implementation Decisions

### Engine and dependencies

- **Pedalboard becomes the load-bearing engine.** It provides effects (`Compressor`, `Limiter`, `HighpassFilter`, `LowpassFilter`, `Reverb`, `Delay`, `Chorus`, `Phaser`, `Distortion`, `Bitcrush`, `PitchShift`, `Resample`), file I/O via `pedalboard.io.AudioFile` for WAV/FLAC/MP3/OGG/AAC, and VST3/AU hosting. All cross-platform via pre-built wheels.
- **No torch, no torchaudio, no librosa, no scipy, no aeiou.** The four `aeiou` ops (`Mono`, `Stereo`, `PhaseFlipper`, `RandPool`) are either reimplemented as ~5-line numpy functions (mono/stereo/polarity) or dropped (`RandPool` was data augmentation).
- **No `--pt` save flag.** Torch is gone from the default install path entirely.
- **Python ≥ 3.10**, `pyproject.toml` (drop `setup.py`).
- **CLI**: `typer`. **REPL**: `click-repl` + `prompt_toolkit` (cross-platform; replaces Unix-only `readline`). **Progress / styled output**: `rich` (replaces `tqdm` + `termcolor`). **LUFS**: `pyloudnorm`. **Settings paths**: `platformdirs`. **Lint/format**: `ruff`. **Tests**: `pytest` + `pytest-cov`.

### Architecture: library-first

- The library is the source of truth. Every op is a pure function `op(buf: AudioBuffer, **params) -> AudioBuffer` with no prints, no `sys.exit`, no global state.
- The CLI is a thin Typer shell that binds structured progress/error events to `rich.progress` and stderr.
- A `--json` output mode emits one JSON event per line on stdout (`{"type": "progress", "done": N, "total": M, "current": "..."}`, `{"type": "error", "file": "...", "reason": "..."}`, `{"type": "done", "ok": N, "failed": M}`). Same event protocol used by the eventual desktop app whether it imports or shells out.
- `JobContext` dataclass replaces the existing `one_shot_args` global mutable state. Constructed per-invocation, passed explicitly through to the pipeline.

### AudioBuffer

- Dataclass with `data: np.ndarray` (shape `(channels, samples)`, `float32`), `sr: int`, `subtype: str | None` (e.g., `"PCM_16"`, `"PCM_24"`, `"FLOAT"`).
- Same shape pedalboard expects, so passing buffers in/out of pedalboard chains is a noop.
- `load(path) -> AudioBuffer` and `save(path, buf, *, subtype=None)` live in the audio I/O module and wrap `pedalboard.io.AudioFile` for all formats.

### Pipeline runner

- Single `ThreadPoolExecutor` (no fake batches). All files submitted at once, results consumed via `as_completed` so worker exceptions surface.
- Per-file results collected as `Result(path, ok, error)` — one bad file does not kill the job.
- End-of-job `JobReport` aggregates `ok` count, `failed` count, list of failures with reasons, total duration. Returned to the caller.
- Single `rich.progress` bar driven by completion events from the runner — the CLI subscribes to events; the runner doesn't know about progress bars.
- `--workers N` flag, default `min(8, os.cpu_count())`. Per-op override available for ops with thread-unsafety (none in the v2.0 set; flag exists for future ops).
- `cancel_token` parameter (a `threading.Event` or equivalent) so callers (notably the future GUI) can abort.

### Op registration and the plugin system

- A single `@op(name=..., help=...)` decorator. Wraps a function, derives a Typer command from its signature (type hints + defaults + `Annotated[T, "help"]` for per-param help), and stores an `Op` dataclass on the function for the registry.
- First-party ops in `audiocli/ops/<name>.py` use the **same** decorator. No special path.
- Plugin discovery via Python entry-points: `[project.entry-points."audiocli.ops"] name = "package:func"`. AudioCLI loads them at startup via `importlib.metadata.entry_points(group="audiocli.ops")` and registers them as Typer subcommands alongside first-party ops.
- Plugin contract is **filter-shape only** in v2.0: `(buf: AudioBuffer, **params) -> AudioBuffer`. Multi-output ops, analysis ops, and side-effect ops are first-party-only special cases. The contract can loosen in v2.1+ without breaking existing plugins.
- Conflict resolution: if a plugin and a first-party op share a name, first-party wins; the conflict is logged at startup.
- The `hook` command remains as the one-off escape hatch for power users who don't want to package a plugin. It expects a single-buffer signature (the existing list-based contract was a bug).

### Op surface for v2.0

**File-level ops (first-party special cases — not via the plugin contract):**
- `chunk <seconds> [--pad/--no-pad] [--clean]` — multi-output: produces N files with `_1`, `_2`, ... suffixes.
- `info <path>` — analysis: prints sr, channels, duration, peak, RMS, LUFS.
- `remove-silent --threshold-db <db>` — side-effect: deletes files whose RMS or peak (configurable) is below the threshold.
- `run-script <path.acli>` — line-by-line execution of saved command sequences.
- `hook <script.py> [--func name]` — Python escape hatch.
- `vst <plugin-path> [--param key=value ...]` — host a VST3/AU via pedalboard's plugin host.

**Filter ops (use the public `@op` contract):**
- `resample <sr>`
- `mono`, `stereo`
- `polarity` (renamed from `phaseflip`)
- `bitdepth <8|16|24|32>`
- `pitch <semitones>`
- `normalize [--peak <db>] [--lufs <lufs>]`
- `trim [--head] [--tail] [--threshold-db <db>]`
- `gain <db>`
- `fade [--in <s>] [--out <s>] [--shape linear|exp|cosine]`
- `convert --format <wav|flac|mp3|ogg> [--bitdepth N]`
- `compress --ratio --threshold-db --attack-ms --release-ms`
- `limit --threshold-db [--release-ms]`
- `highpass <hz>`, `lowpass <hz>`
- `reverb [--room] [--wet] [--dry]`
- `delay [--time-s] [--feedback] [--mix]`
- `chorus`, `phaser`, `distortion`, `bitcrush` — same pattern.

### CLI shape

- Flat command namespace (`audiocli normalize`, not `audiocli process normalize`). The old `process` / `target` / `download` grouping is dropped — it added a level of overhead with no organizational payoff.
- One-shot mode and REPL share the exact same Typer app. The REPL re-invokes it via `click-repl`, so commands are identical in both modes.
- Per-command flags consistent across all ops: `--target <paths>`, `--output <dir>`, `--workers N`, `-o` (overwrite), `--json` (event mode), `--recursive/--no-recursive`.
- REPL retains ` ; ` chaining. `set targets <paths>`, `set output <dir>`, `set workers N` configure session state; settings persist to disk so they survive restarts.

### Settings

- Stored at the `platformdirs` user-config location (XDG on Linux, `~/Library/Application Support/AudioCLI` on macOS, `%APPDATA%\AudioCLI` on Windows).
- JSON file with a `"schema": 1` field at the top so future migrations are clean.
- Stores: targets, output dir, workers, recursive flag, last-used overwrite preference. No device/torch fields.

### Error model

- Public exception hierarchy: `AudioCLIError` (base) → `LoadError`, `SaveError`, `OpError`, `PluginError`, `ConfigError`.
- The pipeline catches per-file exceptions, wraps as `Result(path, ok=False, error=...)`, and emits an `ErrorEvent`. Exceptions raised at the top level (e.g., bad CLI args, plugin registration failure) bubble out and exit non-zero with a clean message.
- No silent `try/except: print(e)` anywhere.

### Migration / breaking changes

- Major version bump to **2.0.0**. Breaking change is documented in the changelog.
- The old top-level package `AudioCLI/` (capital A) is deleted. The new package is `audiocli/` (lowercase). Entry-point name `audiocli` stays the same.
- Existing scripts using `process resample` / `target set` / `process hook`, etc. break. README documents the new flat command shape. An `.acli` script written against v1 will not run on v2.

### Files to create / modify / delete

- **New**: `pyproject.toml`, `audiocli/` (full new package), `tests/` (full suite), `.github/workflows/ci.yml`, `CHANGELOG.md`, new `README.md`.
- **Modify**: `.github/workflows/docs.yml` to point at the new package path (if docs site is kept; lower priority).
- **Delete**: `setup.py`, `AudioCLI/` (old package), generated `docs/*.html`, `test_song.wav` at repo root (moved to `tests/data/test_song.wav`).

## Testing Decisions

### What makes a good test in this codebase

Tests assert **observable external behavior**, not implementation details. Concretely:

- Op tests load real audio, run the op, save, reload, and assert measurable properties (channels, sample rate, frame count, peak, RMS, dB-FS). They do not patch internals or assert internal call counts.
- Pipeline tests use a real filesystem and real (sometimes deliberately corrupted) WAV files. They assert the `JobReport` reflects reality — counts, exit code, error reasons.
- CLI tests use `typer.testing.CliRunner` to invoke commands as a user would and assert on stdout/stderr/exit-code.
- REPL tests subprocess `audiocli shell` with stdin strings and assert on stdout and the persisted history file.
- No mocking of pedalboard or filesystem in the happy path. Mocks reserved for entry-point loading (which needs synthetic plugin packages on the path).

### Modules with full unit-test coverage

- **`AudioBuffer` + I/O**: round-trips for WAV (16/24/32-bit, mono and stereo), FLAC, MP3, OGG; subtype preservation; corrupt-file load raises `LoadError`.
- **Pipeline runner**: 50 files where 3 are corrupt → 47 succeed, 3 fail with reasons, exit non-zero, no hangs. Cancellation: token flipped mid-job → in-flight files complete, no new files start, returns partial report. Parallelism: wall time on 8 files with 4 workers is < 0.6× wall time with 1 worker.
- **Target scanner**: recursive vs non-recursive; extension filtering; hidden files; symlinks; missing paths produce a clean error.
- **Op registry**: `@op` decorator round-trip (function in, registry entry out, signature inspected); entry-point loading from a synthetic plugin package; conflict resolution (plugin name collides with first-party); malformed plugin signature raises `PluginError` at registration.
- **Settings**: load/save round-trip; missing file produces sane defaults; schema-version bump triggers migration path; cross-platform path resolution (mock `platformdirs`).
- **Event protocol**: each event type serializes to expected JSON; `--json` mode produces newline-delimited JSON parseable by another process.

### Per-op tests

For every op in v2.0, three tests:

- **Round-trip**: load `tests/data/test_song.wav`, run op, save to tmp, reload, assert basic shape/sr/properties survived.
- **Correctness**: assert the op did what it claims. Examples: `mono` → 1 channel; `resample 22050` → frame count halved; `polarity` → samples bitwise-negated; `chunk 1.0` → produces N files of `sr` samples each; `normalize --peak -1` → max abs sample within ±0.001 of `10**(-1/20)`; `gain 6` → samples scaled by ~2.0; `bitdepth 16` → reload subtype is `PCM_16`; `trim` → leading/trailing silence below threshold removed.
- **Negative**: corrupt input file → reported failure with reason, no crash, other files in batch still complete.

### Integration tests

- **Bulletproof bar**: 1000 generated files where 50 are deliberately broken (truncated, wrong magic bytes, permission-denied) → 950 succeed, 50 fail with reasons, exit non-zero, total wall time bounded.
- **CLI smoke**: `--help` for every command produces non-empty output and exits 0; argument parsing rejects malformed input cleanly; `--json` mode emits parseable events for a small batch.
- **REPL**: subprocess feeding `set targets ./tmp ; resample 22050 ; mono -o\nexit\n` to `audiocli shell` produces expected files on disk and writes history file.
- **Plugin loading**: a synthetic plugin package installed in the test environment via entry-points is discovered and its op is invokable as a CLI subcommand.

### CI matrix

`{ubuntu-latest, macos-latest, windows-latest} × {3.10, 3.11, 3.12}` running `ruff check`, `ruff format --check`, `pytest --cov`. No torch cell.

### Adapter modules (smoke-only)

CLI app and REPL adapter are not deeply unit-tested — they are mostly wiring. They get smoke tests (does `--help` work; do commands dispatch; does the REPL parse `;`-chained input) but no exhaustive coverage.

## Out of Scope

- **ML / torch ops**, including `--pt` save and any data-augmentation primitives (random pool, noise injection). The plugin system is the path forward for users who want them.
- **`chain <yaml>` command** for one-pass effect stacks. Real value but a YAML-format design problem; the REPL's `;` chaining covers most workflows. Punted to v2.1+.
- **Long-running daemon / RPC architecture**. The library + CLI design lets the eventual desktop app import directly or shell out with `--json`; a daemon is overkill for v2.0.
- **A web GUI or desktop GUI itself**. v2.0 ships the engine and CLI; the desktop app is a separate future project that consumes this library.
- **Public `Op` lifecycle hooks** (init/teardown/validate). Premature without real plugins to validate the shape against. v2.0 plugins are stateless decorated functions only.
- **Multi-output and analysis ops as part of the public plugin contract**. `chunk`, `info`, `remove-silent` are first-party-only in v2.0. The plugin contract may broaden in v2.1+ if real plugins demand it.
- **Documentation site**. The existing `docs.yml` workflow can be left alone or updated to mkdocs in a follow-up; not required for v2.0 ship.
- **Backwards compatibility with v1 `.acli` scripts or v1 CLI shape**. This is a breaking 2.0 release.

## Further Notes

- The repo currently has `test_song.wav` at the root (44.1kHz stereo WAV, ~8MB). It moves to `tests/data/test_song.wav` and becomes the canonical fixture.
- The existing `download http` recursive scrape logic is interesting but tangential to "audio power-tool." Keep it on the punt list — port the algorithm later as a plugin (`audiocli-plugin-http-scrape`) if there's demand. Not in v2.0.
- The `extract_arg_help` regex from `src/util.py` is obsoleted by Typer's native `Annotated[T, typer.Argument(help=...)]` support. Drop entirely.
- `chunks()` helper from `src/util.py` becomes `itertools.batched` (3.12) or an inline 3-line yield (3.10/3.11).
- The existing `process file` (`.acli` batch script runner) is preserved as `audiocli run-script`. The format itself is unchanged: one CLI command per line, comments with `#`.
- The eventual GUI's recommended integration path is "PySide6/Qt-for-Python desktop app that imports `audiocli`." The `--json` event mode is the secondary path for non-Python frontends. Both are first-class.
- Pedalboard's `PitchShift` is thread-safe (unlike the old librosa-based plan), so no `--workers 1` special-case is needed for it. The `--workers N` flag is preserved for future ops with thread-safety constraints.
- Pedalboard's `Resample` uses libsamplerate ("Secret Rabbit Code"), which is high-quality and the same engine pro tools use; resample-quality regressions vs the old torchaudio path are not expected.
