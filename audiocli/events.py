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
so subscribers that only care about errors don't have to filter::

    {"type": "error", "file": str, "reason": str}

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
- Event order within a single run: ``start`` → (``progress`` |
  ``file_done`` | ``error``)* → ``done``. ``progress`` and ``file_done``
  share the same trigger (a file completing) so they always come in that
  order; ``error`` only fires when the file failed.
"""

from __future__ import annotations

from dataclasses import dataclass
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

    file: str
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


__all__ = [
    "DoneEvent",
    "ErrorEvent",
    "FileDoneEvent",
    "ProgressEvent",
    "StartEvent",
]
