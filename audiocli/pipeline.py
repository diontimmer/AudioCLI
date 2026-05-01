"""Per-file pipeline runner.

A single ``ThreadPoolExecutor`` processes every target file in parallel.
Results are consumed via :func:`concurrent.futures.as_completed` so worker
exceptions surface as ``Result(ok=False, error=...)`` rather than being lost
in an unconsumed iterator.

The signature of :func:`run_per_file` is the one future slices widen — issue
#03 will hand it an ``on_event`` callback for structured progress events;
issue #14 will hand it a ``cancel_token``. Both are accepted today as
optional keyword arguments so callers can be written against the final shape
already.

Library code only — no ``print``, no ``sys.exit``. The CLI is responsible
for rendering the returned :class:`JobReport`.
"""

from __future__ import annotations

import contextlib
import os
import time
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from threading import Event
from typing import Any

from audiocli.errors import AudioCLIError, OpError
from audiocli.io import load, save
from audiocli.registry import Op


@dataclass
class Result:
    """Outcome for a single file."""

    path: Path
    ok: bool
    error: str | None = None


@dataclass
class JobReport:
    """Aggregated outcome of a :func:`run_per_file` invocation."""

    results: list[Result] = field(default_factory=list)
    duration_s: float = 0.0

    @property
    def ok_count(self) -> int:
        return sum(1 for r in self.results if r.ok)

    @property
    def failed_count(self) -> int:
        return sum(1 for r in self.results if not r.ok)

    @property
    def failures(self) -> list[Result]:
        return [r for r in self.results if not r.ok]

    @property
    def exit_code(self) -> int:
        """0 when every file succeeded; otherwise the failure count, capped
        at 255 so it fits in a POSIX exit status."""
        return min(self.failed_count, 255)


@dataclass
class JobContext:
    """Per-invocation runtime configuration.

    Replaces the v1 ``one_shot_args`` global. Constructed by the CLI layer
    (or any library caller) and threaded through to the pipeline explicitly.
    """

    op: Op
    params: dict[str, Any] = field(default_factory=dict)
    output: Path | None = None
    workers: int = 0  # 0 → resolved by `default_workers()`

    def resolved_workers(self) -> int:
        return self.workers if self.workers > 0 else default_workers()


# Type alias for the structured-event callback that issue #03 fills in.
EventCallback = Callable[[dict[str, Any]], None]


def default_workers() -> int:
    """Default worker count: ``min(8, os.cpu_count() or 1)``."""
    return min(8, os.cpu_count() or 1)


def run_per_file(
    targets: Iterable[str | Path],
    op: Op,
    params: dict[str, Any] | None = None,
    *,
    output: str | Path | None = None,
    workers: int | None = None,
    on_event: EventCallback | None = None,
    cancel_token: Event | None = None,
) -> JobReport:
    """Apply ``op`` to every path in ``targets`` in parallel.

    Args:
        targets: iterable of input paths.
        op: registered op (from the registry).
        params: keyword arguments to pass to the op function.
        output: ``None`` → write next to source as ``<stem>_<op>.<ext>``;
            existing or new directory → ``<dir>/<source-name>``;
            file path with a suffix → that exact path (only meaningful when
            there is exactly one target).
        workers: thread count. ``None`` → :func:`default_workers`.
        on_event: optional callback invoked with structured event dicts.
            Filled in fully by issue #03; today only ``"start"``,
            ``"file_done"`` and ``"done"`` are emitted, all best-effort.
        cancel_token: optional :class:`threading.Event` flipped by the
            caller to stop the job. In-flight files complete; no new files
            are submitted. Filled in fully by issue #14.

    Returns:
        :class:`JobReport` describing every file's outcome. Per-file
        exceptions are wrapped as failed ``Result``s and never re-raised.
        Top-level errors (e.g. empty target list) raise ``AudioCLIError``.
    """
    paths = [Path(p) for p in targets]
    if not paths:
        raise AudioCLIError("no targets to process")

    params = dict(params or {})
    output_path = Path(output) if output is not None else None
    n_workers = workers if (workers is not None and workers > 0) else default_workers()

    report = JobReport()
    start = time.perf_counter()

    _emit(on_event, {"type": "start", "total": len(paths), "workers": n_workers})

    # `ThreadPoolExecutor` as a context manager guarantees we wait on every
    # in-flight task before returning, so a worker exception cannot escape
    # silently in an unconsumed iterator (the bug the v1 batcher had).
    with ThreadPoolExecutor(max_workers=n_workers) as pool:
        future_to_path = {}
        for p in paths:
            if cancel_token is not None and cancel_token.is_set():
                # Caller cancelled before we could submit — record the
                # remainder as failures so the report is faithful.
                report.results.append(Result(path=p, ok=False, error="cancelled"))
                continue
            fut = pool.submit(_run_one_safe, p, op, params, output_path)
            future_to_path[fut] = p

        for fut in as_completed(future_to_path):
            path = future_to_path[fut]
            try:
                result = fut.result()
            except Exception as e:  # pragma: no cover — _run_one_safe traps everything
                result = Result(path=path, ok=False, error=f"unexpected: {e}")
            report.results.append(result)
            _emit(
                on_event,
                {
                    "type": "file_done",
                    "path": str(result.path),
                    "ok": result.ok,
                    "error": result.error,
                },
            )

    report.duration_s = time.perf_counter() - start
    _emit(
        on_event,
        {
            "type": "done",
            "ok": report.ok_count,
            "failed": report.failed_count,
            "duration_s": report.duration_s,
        },
    )
    return report


def run_one(
    path: str | Path,
    op: Op,
    params: dict[str, Any] | None = None,
    output: str | Path | None = None,
) -> Path:
    """Apply ``op`` to a single file and return the written path.

    Thin wrapper around :func:`run_per_file` so library callers that only
    want one file don't have to build a list. Re-raises the underlying
    error (``LoadError`` / ``SaveError`` / ``OpError``) when the single
    file fails — keeping the v1 contract intact.
    """
    report = run_per_file([path], op, params, output=output, workers=1)
    result = report.results[0]
    if not result.ok:
        raise OpError(result.error or f"op '{op.name}' failed on {path}")
    return _resolve_output(Path(path), Path(output) if output is not None else None, op.name)


def _run_one_safe(
    src: Path,
    op: Op,
    params: dict[str, Any],
    output: Path | None,
) -> Result:
    """Worker: run one file, trap every exception, return a ``Result``.

    Never raises — ``run_per_file`` relies on this so the ``as_completed``
    loop never has to translate worker exceptions into failures itself.
    """
    try:
        buf = load(src)
        try:
            out_buf = op.func(buf, **params)
        except Exception as e:
            raise OpError(f"op '{op.name}' failed on {src}: {e}") from e
        dst = _resolve_output(src, output, op.name)
        save(dst, out_buf, subtype=out_buf.subtype)
        return Result(path=dst, ok=True, error=None)
    except AudioCLIError as e:
        return Result(path=src, ok=False, error=str(e))
    except Exception as e:
        return Result(path=src, ok=False, error=f"{type(e).__name__}: {e}")


def _resolve_output(src: Path, output: Path | None, op_name: str) -> Path:
    """Pick the destination path for a single source file.

    Mirrors the v1 ``run_one`` semantics so existing callers keep working.
    """
    if output is None:
        return src.with_name(f"{src.stem}_{op_name}{src.suffix}")
    if output.exists() and output.is_dir():
        return output / src.name
    if not output.suffix:
        output.mkdir(parents=True, exist_ok=True)
        return output / src.name
    return output


def _emit(on_event: EventCallback | None, event: dict[str, Any]) -> None:
    """Best-effort event dispatch — never lets a buggy callback kill the job."""
    if on_event is None:
        return
    # Library code: swallow callback errors silently. The CLI/GUI is
    # responsible for its own rendering errors; we won't sink the batch.
    with contextlib.suppress(Exception):
        on_event(event)
