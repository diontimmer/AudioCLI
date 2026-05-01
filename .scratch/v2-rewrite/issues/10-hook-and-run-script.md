Status: needs-triage
Type: AFK

# Power-user hooks: `hook` + `run-script`

## Parent

`.scratch/v2-rewrite/PRD.md`

## What to build

Two escape hatches for power users who don't want to package a plugin.

- `audiocli/ops/hook.py`: `audiocli hook --script path/to/script.py [--func name]`. Loads the script with `importlib`, finds the named function (default `process`), and invokes it per file with a single `AudioBuffer` (the v1 list-passing was a bug — fixed here per PRD). The function must have signature `(buf: AudioBuffer, **kwargs) -> AudioBuffer`. Extra `--key=value` flags are passed through as kwargs.
- `audiocli/run_script.py` + `audiocli/ops/run_script.py` binding: `audiocli run-script path/to/job.acli`. Reads the file, executes one CLI command per line. `#`-prefixed lines and blank lines are ignored. Each line is parsed and dispatched through the same Typer app the user would invoke directly. A failure on line N is reported but does not abort subsequent lines unless the user passes `--strict`.
- Both ops use `OpKind.SIDE_EFFECT` or a dedicated kind — they don't fit the pure filter shape and are first-party-only (per PRD, plugin contract is filter-only in v2.0).

## Acceptance criteria

- [ ] `tests/test_hook.py::test_single_buffer`: a hook script with `def process(buf): return buf` is invoked once per input file (not once per batch)
- [ ] `tests/test_hook.py::test_kwargs`: `--gain-db=6` is forwarded as `process(buf, gain_db=6)`
- [ ] `tests/test_hook.py::test_named_func`: `--func transform` finds `def transform(buf)` instead of `process`
- [ ] `tests/test_hook.py::test_bad_signature`: a script that returns the wrong type or has a bad signature → `OpError` naming the script and the issue
- [ ] `tests/test_run_script.py::test_basic`: a 3-line `.acli` file runs all 3 commands; output reflects all 3
- [ ] `tests/test_run_script.py::test_failure_isolation`: a failing line in the middle does not stop the rest (default mode); `--strict` aborts on first failure
- [ ] `tests/test_run_script.py::test_comments_and_blanks`: `#`-lines and blank lines are skipped silently

## Blocked by

- #02 — Parallel pipeline with error isolation
