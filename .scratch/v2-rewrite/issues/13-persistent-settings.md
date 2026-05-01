Status: needs-triage
Type: AFK

# Persistent settings

## Parent

`.scratch/v2-rewrite/PRD.md`

## What to build

Per-user settings stored at the platform-appropriate config location, so REPL session state (target folder, output dir, worker count, recursive flag) survives restarts.

- `audiocli/settings.py`: `Settings` dataclass with fields `targets: list[Path]`, `output: Path | None`, `workers: int`, `recursive: bool`, `overwrite: bool`. JSON file with top-level `"schema": 1` field for future migrations.
- Storage location via `platformdirs.user_config_dir("audiocli")`:
  - Linux: `~/.config/audiocli/settings.json`
  - macOS: `~/Library/Application Support/audiocli/settings.json`
  - Windows: `%APPDATA%\audiocli\settings.json`
- `load() -> Settings` and `save(settings)` round-trip. Missing file → returns defaults (`workers = min(8, os.cpu_count())`, `recursive = False`, `overwrite = False`, others empty/None).
- REPL commands: `set targets <path> [<path> ...]`, `set output <dir>`, `set workers N`, `set recursive on|off`. Each writes to disk immediately so a crash doesn't lose state.
- `audiocli/errors.py`: `ConfigError` for malformed JSON / unknown schema versions.
- Settings inform the CLI flag defaults: `--target` defaults to `settings.targets`, etc. Explicit flags override settings.

## Acceptance criteria

- [ ] `tests/test_settings.py::test_roundtrip`: save → load → equal
- [ ] `tests/test_settings.py::test_missing_file`: load with no file present → returns defaults, no exception
- [ ] `tests/test_settings.py::test_malformed_json`: load with broken JSON → `ConfigError` with file path in message
- [ ] `tests/test_settings.py::test_unknown_schema`: load a file with `"schema": 999` → `ConfigError` instructing the user to migrate / delete
- [ ] `tests/test_settings.py::test_paths_per_platform`: mock `platformdirs` to return Linux/macOS/Windows paths; resolution is correct on each
- [ ] `tests/test_shell.py::test_set_persists`: REPL session 1 runs `set workers 4`; REPL session 2 reports `workers = 4` without re-setting
- [ ] Explicit `--workers 2` on a CLI invocation overrides the persisted `workers = 4` for that invocation only

## Blocked by

- #12 — Cross-platform REPL
