"""PySide6 bridge for running workspace chain execution in a worker thread.

This module intentionally imports PySide6 and must only be imported from the
optional GUI path.  The worker emits plain dictionaries; widgets are updated by
slots in the main thread.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, Signal, Slot

from audiocli.gui.service import WorkspaceExecutionRequest
from audiocli.gui_service import execute_file_chain

Executor = Callable[
    [WorkspaceExecutionRequest, Callable[[dict[str, Any]], None], threading.Event],
    dict[str, Any],
]


class WorkspaceChainWorker(QObject):
    """QObject worker that executes one real file-backed chain request."""

    event_received = Signal(dict)
    finished = Signal(dict)
    failed = Signal(str)
    state_changed = Signal(dict)

    def __init__(
        self,
        request: WorkspaceExecutionRequest,
        *,
        executor: Executor | None = None,
    ) -> None:
        super().__init__()
        self.request = request
        self._cancel_token = threading.Event()
        self._executor = executor or _default_executor

    @property
    def cancel_token(self) -> threading.Event:
        return self._cancel_token

    @Slot()
    def run(self) -> None:
        self.state_changed.emit({"running": True, "cancel_requested": False})
        try:
            report = self._executor(self.request, self._emit_event, self._cancel_token)
        except Exception as exc:  # pragma: no cover - exercised through failed signal tests
            self.failed.emit(_format_exception(exc))
        else:
            self.finished.emit(report)
        finally:
            self.state_changed.emit(
                {"running": False, "cancel_requested": self._cancel_token.is_set()}
            )

    @Slot()
    def cancel(self) -> None:
        self._cancel_token.set()
        self.state_changed.emit({"cancel_requested": True})

    def _emit_event(self, event: dict[str, Any]) -> None:
        self.event_received.emit(dict(event))


def _default_executor(
    request: WorkspaceExecutionRequest,
    on_event: Callable[[dict[str, Any]], None],
    cancel_token: threading.Event,
) -> dict[str, Any]:
    run = execute_file_chain(
        request.chain,
        request.targets,
        output_policy=request.output_policy,
        destructive_confirmation=request.destructive_confirmation,
        on_event=on_event,
        cancel_token=cancel_token,
    )
    return run.to_view_model()


def _format_exception(exc: Exception) -> str:
    message = str(exc)
    return message if message else type(exc).__name__
