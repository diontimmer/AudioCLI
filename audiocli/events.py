"""Structured event protocol for the pipeline runner.

The pipeline emits a small set of dict-shaped events via the ``on_event``
callback. The CLI subscribes to those events and renders them either as a
``rich.progress`` bar (default) or as newline-delimited JSON (``--json``).

The event protocol is also the wire format used by the eventual desktop
GUI when it shells out instead of importing the library, so the shape is
deliberately stable and JSON-serialisable.

Public event shapes
-------------------

``start`` — emitted once before any file is processed::

    {"type": "start", "total": int, "workers": int}

``progress`` — emitted whenever the running tally changes (currently after
every file completion). Mirrors the canonical PRD shape::

    {"type": "progress", "done": int, "total": int, "current": str | None}

``file_done`` — emitted once per file with its individual outcome::

    {"type": "file_done", "path": str, "ok": bool, "error": str | None}

``error`` — emitted for every failed file in addition to ``file_done``,
so subscribers that only care about errors don't have to filter. CLI-level
fatal errors that are not tied to a file use ``null`` for ``file``::

    {"type": "error", "file": str | None, "reason": str}

``done`` — emitted exactly once at the end of the run::

    {"type": "done", "ok": int, "failed": int, "duration_s": float}

Notes
-----

- All events are plain dicts (no dataclass instances cross the callback
  boundary) so subscribers can ``json.dumps`` them without help.
- The dataclasses below exist so library callers (or the CLI) can
  construct events with type-checked fields and call ``to_json()`` to
  obtain the dict. They are *not* required to use the dataclasses;
  passing equivalent dicts to ``on_event`` is equally valid.
- Event order within a single run: ``start`` -> (``file_done`` ->
  optional ``error`` -> ``progress``)* -> ``done``.
"""

from __future__ import annotations

import contextlib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class StartEvent:
    """Emitted once at the top of a run."""

    total: int
    workers: int

    def to_json(self) -> dict[str, Any]:
        return {"type": "start", "total": self.total, "workers": self.workers}


@dataclass(frozen=True)
class ProgressEvent:
    """Emitted after each file completion, tracking the running tally."""

    done: int
    total: int
    current: str | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "type": "progress",
            "done": self.done,
            "total": self.total,
            "current": self.current,
        }


@dataclass(frozen=True)
class FileDoneEvent:
    """Emitted once per file with its individual outcome."""

    path: str
    ok: bool
    error: str | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "type": "file_done",
            "path": self.path,
            "ok": self.ok,
            "error": self.error,
        }


@dataclass(frozen=True)
class ErrorEvent:
    """Emitted alongside ``file_done`` whenever a file failed."""

    file: str | None
    reason: str

    def to_json(self) -> dict[str, Any]:
        return {"type": "error", "file": self.file, "reason": self.reason}


@dataclass(frozen=True)
class DoneEvent:
    """Emitted exactly once at the end of a run."""

    ok: int
    failed: int
    duration_s: float

    def to_json(self) -> dict[str, Any]:
        return {
            "type": "done",
            "ok": self.ok,
            "failed": self.failed,
            "duration_s": self.duration_s,
        }


EventCallback = Callable[[dict[str, Any]], None]


@dataclass
class EventSink:
    """Best-effort dispatcher for the structured event protocol."""

    callback: EventCallback | None = None

    def emit(self, event: dict[str, Any]) -> None:
        if self.callback is None:
            return
        with contextlib.suppress(Exception):
            self.callback(event)

    def start(self, *, total: int, workers: int) -> None:
        self.emit(StartEvent(total=total, workers=workers).to_json())

    def completed_file(
        self,
        *,
        path: str | Path,
        ok: bool,
        error: str | None,
        done: int,
        total: int,
    ) -> None:
        path_text = str(path)
        self.file_done(path=path_text, ok=ok, error=error)
        if not ok:
            self.error(file=path_text, reason=error or "unknown error")
        self.progress(done=done, total=total, current=path_text)

    def file_done(self, *, path: str | Path, ok: bool, error: str | None = None) -> None:
        self.emit(FileDoneEvent(path=str(path), ok=ok, error=error).to_json())

    def error(self, *, file: str | Path | None, reason: str) -> None:
        self.emit(ErrorEvent(file=str(file) if file is not None else None, reason=reason).to_json())

    def progress(self, *, done: int, total: int, current: str | Path | None = None) -> None:
        self.emit(
            ProgressEvent(
                done=done,
                total=total,
                current=str(current) if current is not None else None,
            ).to_json()
        )

    def done(self, *, ok: int, failed: int, duration_s: float) -> None:
        self.emit(DoneEvent(ok=ok, failed=failed, duration_s=duration_s).to_json())


__all__ = [
    "DoneEvent",
    "ErrorEvent",
    "EventCallback",
    "EventSink",
    "FileDoneEvent",
    "ProgressEvent",
    "StartEvent",
]
