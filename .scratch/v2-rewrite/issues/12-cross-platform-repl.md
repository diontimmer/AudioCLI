Status: needs-triage
Type: AFK

# Cross-platform REPL

## Parent

`.scratch/v2-rewrite/PRD.md`

## What to build

Replace v1's Unix-only `readline`-based REPL with a cross-platform shell built on `click-repl` + `prompt_toolkit`. Same Typer app powers one-shot mode and the REPL — commands are identical in both.

- `audiocli/shell.py`: `audiocli shell` enters a REPL backed by `click-repl`. Tab completion of commands, options, and recent file paths via `prompt_toolkit`'s completion machinery.
- Add `click-repl` and `prompt_toolkit` to `pyproject.toml` deps; remove `readline`, `icli`, `termcolor` (already gone in #1, but verify).
- ` ; ` chaining: a single REPL line `mono ; resample --sr 22050 ; gain --db -3` runs three commands sequentially against the current target. The chain operator parses outside any quoted strings.
- Persistent command history: history file at `<platformdirs user_state_dir>/audiocli/history`. Loaded on shell start, written on exit and after each command. Survives REPL restarts.
- `exit` / `quit` / EOF (Ctrl-D on Unix, Ctrl-Z+Enter on Windows) all terminate the shell cleanly.
- Cross-platform: works identically on Linux, macOS, Windows (no `readline`-style platform quirks).

## Acceptance criteria

- [ ] `tests/test_shell.py::test_basic`: subprocess `audiocli shell` fed `gain --target tests/data/test_song.wav --db 6 --output /tmp/out\nexit\n` produces the expected output file and exits 0
- [ ] `tests/test_shell.py::test_chain`: `set targets ./tmp ; resample --sr 22050 ; mono\nexit\n` runs all three commands in order
- [ ] `tests/test_shell.py::test_history`: after a session that ran 3 commands, the history file exists at the expected path and contains exactly those commands
- [ ] `tests/test_shell.py::test_history_persists`: a second shell session reads back the previous session's history
- [ ] CI on Windows runner: shell smoke test passes (no `readline`-style import failures)
- [ ] One-shot and REPL produce identical output for the same command (parametrized test)

## Blocked by

- #01 — Tracer bullet: end-to-end spine with `gain` op
