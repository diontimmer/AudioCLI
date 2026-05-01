Status: needs-triage
Type: AFK

# Parallel pipeline with error isolation

## Parent

`.scratch/v2-rewrite/PRD.md`

## What to build

Replace the single-file runner from #1 with the real pipeline: a `ThreadPoolExecutor` that processes all files at once, surfaces worker exceptions, and aggregates per-file results into a `JobReport`. One bad file in a 1000-file batch must be reported and skipped — never crash the job.

- `audiocli/pipeline.py`: `run_per_file(files, op, params, *, output, workers, cancel_token=None) -> JobReport`. Single `ThreadPoolExecutor`, all files submitted up front, results consumed via `as_completed` so worker exceptions surface (no `executor.map` lazy-iterator trap).
- `Result(path: Path, ok: bool, error: str | None)` dataclass — one per file.
- `JobReport(results: list[Result], duration_s: float)` with `ok_count`, `failed_count`, `failures` properties.
- Per-file exceptions caught in the worker, wrapped as `Result(ok=False, error=...)`, never re-raised. Top-level errors (bad CLI args, op resolution failure) still bubble out.
- `JobContext` dataclass replacing the old `one_shot_args` global mutable state. Constructed per CLI invocation, threaded through to the pipeline explicitly.
- `--workers N` flag on every op, default `min(8, os.cpu_count())`.
- Exit-code contract wired into `audiocli/cli.py`: 0 = all ok, non-zero (= number of failures, capped at 255) = any failure.
- `audiocli/scanner.py`: target scanner — `--target <paths>` accepts files or directories, `--recursive/--no-recursive`, extension filter, hidden-file handling, symlink handling, missing-path → clean error.

## Acceptance criteria

- [ ] `tests/test_pipeline.py::test_bulletproof`: 50 files where 3 are deliberately corrupt (truncated, wrong magic bytes, permission-denied) → `JobReport.ok_count == 47`, `failed_count == 3`, exit code != 0, total wall time < 30s
- [ ] `tests/test_pipeline.py::test_parallelism`: wall time on 8 files with `workers=4` is < 0.6× wall time with `workers=1`
- [ ] `tests/test_pipeline.py::test_no_silent_drops`: a worker that raises an arbitrary exception is reflected as `Result(ok=False, error=...)` and not lost in an unconsumed iterator
- [ ] `tests/test_scanner.py`: recursive vs non-recursive; extension filtering; hidden files; symlinks; missing path → `AudioCLIError` with a clean message
- [ ] `audiocli gain --target ./folder-with-1-corrupt-file --db 6` exits non-zero, processes the good files, prints a clear failure summary
- [ ] No `print()` calls inside `audiocli/pipeline.py` (CLI layer is responsible for output)

## Blocked by

- #01 — Tracer bullet: end-to-end spine with `gain` op
