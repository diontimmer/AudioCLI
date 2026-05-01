Status: needs-triage
Type: AFK

# Library API: cancellation + op enumeration

## Parent

`.scratch/v2-rewrite/PRD.md`

## What to build

The library-facing surface a future desktop GUI (PySide6/Qt) will consume directly. The CLI is already a thin Typer shell over this library; this slice formalizes the contract and adds the two GUI-required pieces (cancellation, op enumeration).

- `audiocli/__init__.py` re-exports the public API: `op`, `AudioBuffer`, `run_per_file`, `JobReport`, `Result`, `ProgressEvent`, `ErrorEvent`, `DoneEvent`, `list_ops`, `OpInfo`, `AudioCLIError` and subclasses.
- `run_per_file(files, op, params, *, output, workers, on_event=None, cancel_token=None) -> JobReport`: signature finalized from #2 / #3. `cancel_token` is a `threading.Event`; runner checks it before submitting each new file and inside long-running iteration loops, but lets in-flight files finish (graceful, not violent).
- `list_ops() -> list[OpInfo]`: enumerate all registered ops (first-party + plugin) at runtime. `OpInfo` exposes `name`, `help`, `kind`, and `params: list[ParamInfo]` where each `ParamInfo` has `name`, `type`, `default`, `help`. Enough metadata for a GUI to render dynamic UI for each op.
- Library invariants enforced by tests: no `print()` calls anywhere under `audiocli/` except `audiocli/cli.py`; no `sys.exit()` calls anywhere under `audiocli/` except `audiocli/cli.py`. A test greps the codebase to assert this.
- Document the JSON event protocol in `audiocli/events.py` as the secondary integration path for non-Python frontends. Same shapes as `--json` mode, already shipped in #3.

## Acceptance criteria

- [ ] `tests/test_library_api.py::test_imports`: every documented public symbol is importable from `audiocli`
- [ ] `tests/test_cancellation.py::test_token`: a cancel_token flipped mid-job → in-flight files complete; no new files start; returns `JobReport` reflecting partial completion (`ok + failed < total`)
- [ ] `tests/test_cancellation.py::test_no_hang`: cancellation does not leave threads or executors hanging — pytest's thread-leak detector finds no leaks
- [ ] `tests/test_list_ops.py::test_enumeration`: `list_ops()` returns one `OpInfo` per registered op (first-party + any plugins); names match the CLI subcommand names
- [ ] `tests/test_list_ops.py::test_param_info`: an op with `Annotated[float, typer.Option(help="cutoff")]` produces a `ParamInfo` with that help text and the float type
- [ ] `tests/test_purity.py::test_no_print`: greps `audiocli/` (excluding `cli.py`) for `print(` / `sys.exit(` — finds zero matches
- [ ] An integration smoke test imports `audiocli` and runs a 3-file batch via `run_per_file` with a custom `on_event` callback collecting events into a list

## Blocked by

- #03 — Structured events + `--json` mode + `rich` progress
- #11 — Plugin entry-point system
