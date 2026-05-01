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
from audiocli.events import (
    DoneEvent,
    ErrorEvent,
    FileDoneEvent,
    ProgressEvent,
    StartEvent,
)
from audiocli.io import extension_for_format, load, save
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
            Best-effort — exceptions raised by the callback are swallowed
            so a buggy subscriber cannot kill the batch. The full event
            protocol (``start`` / ``progress`` / ``file_done`` / ``error``
            / ``done``) is documented in :mod:`audiocli.events`.
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
    total = len(paths)

    _emit(on_event, StartEvent(total=total, workers=n_workers).to_json())

    def _cancelled() -> bool:
        return cancel_token is not None and cancel_token.is_set()

    # `ThreadPoolExecutor` as a context manager guarantees we wait on every
    # in-flight task before returning, so a worker exception cannot escape
    # silently in an unconsumed iterator (the bug the v1 batcher had).
    with ThreadPoolExecutor(max_workers=n_workers) as pool:
        future_to_path: dict[Any, Path] = {}
        skipped: list[Path] = []
        for p in paths:
            if _cancelled():
                # Caller cancelled before we could submit — record the
                # remainder as failures so the report is faithful.
                skipped.append(p)
                continue
            fut = pool.submit(_run_one_safe, p, op, params, output_path, cancel_token)
            future_to_path[fut] = p

        # Drain completed futures; check the token between each one so a
        # mid-job cancellation skips remaining un-started work quickly.
        # In-flight files are allowed to finish (no thread kills), as
        # required by the issue spec.
        for fut in as_completed(future_to_path):
            if _cancelled():
                # Try to cancel still-pending futures (only un-started
                # work can be cancelled by the executor); anything that
                # was already running will complete and arrive here on a
                # later iteration.
                for pending, pending_path in list(future_to_path.items()):
                    if pending is fut or pending.done():
                        continue
                    if pending.cancel():
                        skipped.append(pending_path)
                        future_to_path.pop(pending, None)

            path = future_to_path[fut]
            try:
                result = fut.result()
            except Exception as e:  # pragma: no cover — _run_one_safe traps everything
                result = Result(path=path, ok=False, error=f"unexpected: {e}")
            report.results.append(result)
            _emit(
                on_event,
                FileDoneEvent(
                    path=str(result.path),
                    ok=result.ok,
                    error=result.error,
                ).to_json(),
            )
            if not result.ok:
                _emit(
                    on_event,
                    ErrorEvent(
                        file=str(result.path),
                        reason=result.error or "unknown error",
                    ).to_json(),
                )
            _emit(
                on_event,
                ProgressEvent(
                    done=len(report.results),
                    total=total,
                    current=str(result.path),
                ).to_json(),
            )

        # Append cancellation results last so the report's progress
        # reflects when the cancel happened relative to completed files.
        for p in skipped:
            cancelled_result = Result(path=p, ok=False, error="cancelled")
            report.results.append(cancelled_result)
            _emit(
                on_event,
                FileDoneEvent(
                    path=str(p),
                    ok=False,
                    error="cancelled",
                ).to_json(),
            )

    report.duration_s = time.perf_counter() - start
    _emit(
        on_event,
        DoneEvent(
            ok=report.ok_count,
            failed=report.failed_count,
            duration_s=report.duration_s,
        ).to_json(),
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

    If the op returns a buffer with a ``format`` field set (e.g. ``convert``),
    the destination's extension is rewritten to match — so a ``.wav`` source
    converted to FLAC lands as ``.flac`` on disk.
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
    cancel_token: Event | None = None,
) -> Result:
    """Worker: run one file, trap every exception, return a ``Result``.

    Never raises — ``run_per_file`` relies on this so the ``as_completed``
    loop never has to translate worker exceptions into failures itself.

    If ``cancel_token`` is flipped before this worker starts its load, the
    file is short-circuited as ``Result(ok=False, error="cancelled")`` so
    a long batch can stop quickly without leaking thread time. Once the
    op is running the worker is committed — we don't kill threads
    mid-flight; the in-flight file is allowed to finish naturally.
    """
    if cancel_token is not None and cancel_token.is_set():
        return Result(path=src, ok=False, error="cancelled")
    try:
        buf = load(src)
        if cancel_token is not None and cancel_token.is_set():
            # Cancelled between load and op — bail before the (potentially
            # expensive) DSP step rather than waste the work.
            return Result(path=src, ok=False, error="cancelled")
        try:
            out_buf = op.func(buf, **params)
        except Exception as e:
            raise OpError(f"op '{op.name}' failed on {src}: {e}") from e
        dst = _resolve_output(src, output, op.name)
        if out_buf.format is not None:
            dst = dst.with_suffix(extension_for_format(out_buf.format))
        save(
            dst,
            out_buf,
            subtype=out_buf.subtype,
            format=out_buf.format,
            quality=out_buf.quality,
        )
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
