"""CLI output adapters for batch pipeline events.

The pipeline emits structured events and returns a ``JobReport``. This
module owns the CLI presentation policy for those two surfaces so
``audiocli.cli`` can stay focused on command composition.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, Protocol

import typer

from audiocli.events import DoneEvent, ErrorEvent

if TYPE_CHECKING:
    from audiocli.pipeline import JobReport


EventPayload = dict[str, Any]


class Echo(Protocol):
    def __call__(self, message: str, *, err: bool = False) -> None: ...


def _echo(message: str, *, err: bool = False) -> None:
    typer.echo(message, err=err)


class BatchOutput(Protocol):
    """Adapter interface used by the CLI batch command flow."""

    def on_event(self, event: EventPayload) -> None: ...

    def render_report(self, report: JobReport) -> None: ...

    def render_fatal_error(self, message: str) -> None: ...

    def close(self) -> None: ...


class JsonBatchOutput:
    """Render every event as newline-delimited JSON on stdout."""

    def __init__(self, *, echo: Echo = _echo) -> None:
        self._echo = echo

    def on_event(self, event: EventPayload) -> None:
        self._echo(json.dumps(event))

    def render_report(self, report: JobReport) -> None:
        return None

    def render_fatal_error(self, message: str) -> None:
        self.on_event(ErrorEvent(file=None, reason=message).to_json())
        self.on_event(DoneEvent(ok=0, failed=0, duration_s=0.0).to_json())

    def close(self) -> None:
        return None


class ProgressBatchOutput:
    """Render pipeline events through a Rich progress bar on stderr."""

    def __init__(self, *, echo: Echo = _echo) -> None:
        self._echo = echo
        self._progress: Any | None = None
        self._task_id: int | None = None

    def on_event(self, event: EventPayload) -> None:
        kind = event.get("type")
        if kind == "start":
            progress = self._ensure_progress()
            self._task_id = progress.add_task(
                "processing",
                total=event.get("total", 0),
                current="",
            )
        elif kind == "progress" and self._progress is not None and self._task_id is not None:
            current = event.get("current") or ""
            display = current.rsplit("/", 1)[-1] if current else ""
            self._progress.update(
                self._task_id,
                completed=event.get("done", 0),
                current=display,
            )
        elif kind == "error":
            reason = event.get("reason", "")
            file = event.get("file", "")
            self._echo(f"FAIL {file}: {reason}", err=True)

    def render_report(self, report: JobReport) -> None:
        render_job_report(report, echo=self._echo, include_failures=False)

    def render_fatal_error(self, message: str) -> None:
        self._echo(f"error: {message}", err=True)

    def close(self) -> None:
        if self._progress is None:
            return
        self._progress.stop()

    def _ensure_progress(self) -> Any:
        if self._progress is not None:
            return self._progress

        # rich.progress is intentionally imported here, not at module top, so
        # `audiocli --help` stays under its startup budget.
        from rich.progress import (  # noqa: PLC0415
            BarColumn,
            MofNCompleteColumn,
            Progress,
            TextColumn,
            TimeRemainingColumn,
        )

        self._progress = Progress(
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            MofNCompleteColumn(),
            TextColumn("*"),
            TimeRemainingColumn(),
            TextColumn("[dim]{task.fields[current]}"),
            transient=False,
        )
        self._progress.start()
        return self._progress


def make_batch_output(json_mode: bool, *, echo: Echo = _echo) -> BatchOutput:
    if json_mode:
        return JsonBatchOutput(echo=echo)
    return ProgressBatchOutput(echo=echo)


def render_fatal_error(json_mode: bool, message: str, *, echo: Echo = _echo) -> None:
    """Render a top-level error before a batch adapter has been created."""
    make_batch_output(json_mode, echo=echo).render_fatal_error(message)


def render_job_report(
    report: JobReport,
    *,
    echo: Echo = _echo,
    include_failures: bool = True,
) -> None:
    """Render final paths and summary for a completed batch report."""
    for result in report.results:
        if result.ok:
            echo(str(result.path))
        elif include_failures:
            echo(f"FAIL {result.path}: {result.error}", err=True)

    echo(
        f"done: {report.ok_count} ok, {report.failed_count} failed in {report.duration_s:.2f}s",
        err=True,
    )


__all__ = [
    "BatchOutput",
    "JsonBatchOutput",
    "ProgressBatchOutput",
    "make_batch_output",
    "render_fatal_error",
    "render_job_report",
]
