Status: needs-triage
Type: AFK

# Structured events + `--json` mode + `rich` progress

## Parent

`.scratch/v2-rewrite/PRD.md`

## What to build

The pipeline runner emits structured events; the CLI subscribes to them and renders either a `rich` progress bar (default) or newline-delimited JSON (`--json`). Same event protocol later used by the eventual desktop app whether it imports the library or shells out.

- `audiocli/events.py`: event dataclasses — `ProgressEvent(done, total, current)`, `ErrorEvent(file, reason)`, `DoneEvent(ok, failed, duration_s)`. Each has a `to_json()` returning the documented shape.
- `run_per_file` accepts an `on_event: Callable[[Event], None] | None` callback. The runner does **not** import `rich` or know about progress bars — it only emits events.
- `audiocli/cli.py`: default mode wires `on_event` to a `rich.progress.Progress` instance with a single bar showing files-completed / files-total / current-file / ETA. Errors render to stderr.
- `--json` flag on every op: events are serialized as JSON, one per line, to stdout. `rich` is suppressed in this mode.
- Document the JSON event shapes in a docstring on `audiocli/events.py` (this is the public protocol the GUI will consume).

## Acceptance criteria

- [ ] `tests/test_events.py::test_serialization`: each event type round-trips through `json.dumps` / `json.loads` to the documented shape
- [ ] `tests/test_cli_json.py`: `audiocli gain --target <folder> --db 6 --json` emits parseable newline-delimited JSON; every line is a valid event; final line is `{"type": "done", ...}`
- [ ] `tests/test_cli_progress.py`: default (non-`--json`) invocation produces a `rich` progress bar (smoke: stderr/stdout contains expected progress markers)
- [ ] `audiocli/pipeline.py` does not import `rich`
- [ ] Progress bar updates monotonically; never shows `done > total`; `current` reflects the file actively being processed

## Blocked by

- #02 — Parallel pipeline with error isolation
