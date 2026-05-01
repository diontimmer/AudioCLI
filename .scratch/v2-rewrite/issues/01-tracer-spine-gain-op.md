Status: needs-triage
Type: HITL

# Tracer bullet: end-to-end spine with `gain` op

## Parent

`.scratch/v2-rewrite/PRD.md`

## What to build

Establish the architectural spine that every subsequent slice will thicken: a working `audiocli gain --target ./songs --db 6` command that loads a WAV file, scales samples, and saves the result, going through every layer the v2 architecture defines.

This slice is **HITL** because it sets the template (`AudioBuffer` shape, `@op` decorator contract, pipeline runner shape, CLI binding pattern, test conventions) that every later op and feature must match. A reviewer should sign off on the architectural pattern before #2–#15 fan out against it.

Concretely:

- New `pyproject.toml` (drop `setup.py`); declare `audiocli` package; deps: `pedalboard`, `numpy`, `typer`, `rich`; dev deps: `pytest`, `pytest-cov`, `ruff`. No `torch`, `torchaudio`, `librosa`, `scipy`, `aeiou`, `tqdm`, `termcolor`, `readline`, `icli`, `einops`, `pdoc`.
- New `audiocli/` package (lowercase). Old `AudioCLI/` package is **not** deleted in this slice — left in place to avoid blowing away unrelated work; deletion happens in #15.
- `audiocli/buffer.py`: `AudioBuffer` dataclass with `data: np.ndarray (channels, samples), float32`, `sr: int`, `subtype: str | None`.
- `audiocli/io.py`: `load(path) -> AudioBuffer` and `save(path, buf, *, subtype=None)` wrapping `pedalboard.io.AudioFile`. WAV only in this slice; FLAC/MP3/OGG arrive in #4.
- `audiocli/registry.py`: `@op(name=..., help=...)` decorator that derives a Typer command from the wrapped function's signature (type hints + defaults + `Annotated[T, typer.Option(help=...)]`). Stores an `Op` dataclass on the function for later registry lookup.
- `audiocli/ops/gain.py`: first-party op using the public `@op` decorator — `def gain(buf: AudioBuffer, db: float) -> AudioBuffer`. Same decorator path plugin authors will use later.
- `audiocli/pipeline.py`: a **single-file** runner for now (`run_one(path, op, params, output)`). No threadpool, no `Result`, no `JobReport` — those land in #2. The function signature should be the one #2 will extend, not a throwaway.
- `audiocli/cli.py`: Typer app that auto-registers ops from `audiocli/ops/` at import time. Entry point `audiocli = "audiocli.cli:app"` in `pyproject.toml`.
- `audiocli/errors.py`: `AudioCLIError` base + `LoadError`, `SaveError`, `OpError`. (`PluginError`, `ConfigError` arrive in their respective slices.)
- `tests/data/test_song.wav`: copied (not moved — #15 handles the root deletion) from repo root.
- `tests/test_gain.py`: round-trip + correctness (`gain 6` → samples ~2×) + negative (corrupt input → `LoadError`).
- `tests/test_buffer.py`: WAV round-trip 16/24/32-bit, mono and stereo, subtype preserved.
- `.github/workflows/ci.yml`: ubuntu-latest × python 3.10/3.11/3.12 running `ruff check`, `ruff format --check`, `pytest --cov`. Mac/Windows arrive in #15.

## Acceptance criteria

- [ ] `pip install -e .` works on Linux without pulling torch
- [ ] `audiocli --help` returns in under 100ms (lazy imports verified)
- [ ] `audiocli gain --target tests/data/test_song.wav --db 6 --output /tmp/out` produces a file whose peak is ~2× the input peak
- [ ] `AudioBuffer.data` shape is `(channels, samples)`, `float32`, matching pedalboard's expected layout
- [ ] `@op` decorator: a function with `Annotated[float, typer.Option(help="...")]` parameters becomes a Typer subcommand with the help text propagated
- [ ] `tests/test_gain.py` passes (round-trip + correctness + negative)
- [ ] `tests/test_buffer.py` passes (WAV 16/24/32, mono+stereo, subtype preserved)
- [ ] CI green on ubuntu-latest × py3.10/3.11/3.12
- [ ] No `print()` or `sys.exit()` calls anywhere under `audiocli/` except `audiocli/cli.py`
- [ ] Old `AudioCLI/` package is **untouched** (deletion is #15's job)

## Blocked by

None — can start immediately.
