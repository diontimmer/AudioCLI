Status: needs-triage
Type: HITL

# Repo migration + docs + full CI matrix

## Parent

`.scratch/v2-rewrite/PRD.md`

## What to build

The final v2.0 housekeeping pass: delete v1, write the public-facing docs, expand CI to the full matrix, tag and release.

This slice is **HITL** because the README and CHANGELOG are the artifacts new users encounter first — they should be reviewed and edited by a human before publish, not auto-merged.

- **Delete**: `setup.py`, the old top-level `AudioCLI/` package (capital A), generated `docs/*.html`, `test_song.wav` at repo root (already copied to `tests/data/` in #1).
- **Modify**: `.github/workflows/docs.yml` to point at the new package path or remove if the docs site is deferred (PRD says lower priority).
- **Write**: new `README.md` covering install, every first-party op with one-line description and example invocation, the `--json` event protocol, the plugin author quickstart (`@op` + `pip install audiocli`), the library quickstart (`from audiocli import run_per_file`).
- **Write**: `CHANGELOG.md` documenting the breaking 2.0.0 release. Explicitly call out v1 → v2 migrations: package rename `AudioCLI` → `audiocli`, command flattening (`process resample` → `resample`, `target set` → `set targets`), removed `--pt` save flag, removed ML/torch ops, `phaseflip` → `polarity`, deleted commands.
- **Expand CI**: matrix `{ubuntu-latest, macos-latest, windows-latest} × {3.10, 3.11, 3.12}` running `ruff check`, `ruff format --check`, `pytest --cov`. No torch cell. Linux-only matrix from #1 is replaced.
- **Bump version** to `2.0.0` in `pyproject.toml`. Tag the commit. Decide PyPI publish step in CI now or in a follow-up.

## Acceptance criteria

- [ ] `AudioCLI/` (capital A) directory is gone; `setup.py` is gone; `docs/*.html` is gone; root `test_song.wav` is gone
- [ ] `README.md` opens with a one-paragraph elevator pitch matching the PRD's repositioning ("scriptable, batch-capable, cross-platform audio power-tool that runs DAW-quality effects from the command line")
- [ ] `README.md` lists every first-party op with one-line description and one-line example
- [ ] `README.md` includes a "Plugin authors" section showing the minimum viable plugin (`@op` decorator, `pyproject.toml` entry-point, `pip install`)
- [ ] `README.md` includes a "Use as a library" section showing `from audiocli import run_per_file`
- [ ] `CHANGELOG.md` exists with a 2.0.0 section listing breaking changes
- [ ] CI green on `{ubuntu, macos, windows} × {3.10, 3.11, 3.12}` for the full test suite (excluding test cells that legitimately skip on a platform, e.g., AU on non-mac)
- [ ] `pip install audiocli` on a fresh Windows VM succeeds without any system dependencies (pedalboard wheels handle everything)
- [ ] Version is `2.0.0` in `pyproject.toml`; commit is tagged `v2.0.0`

## Blocked by

- #02–#14 (all prior implementation slices)
