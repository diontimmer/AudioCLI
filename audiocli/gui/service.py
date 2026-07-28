"""Workspace service used by the optional PySide6 shell.

The GUI talks to this module instead of mutating widgets directly.  Chain
editing stays GUI-neutral and real execution is represented as a stream of
service events that Qt can bridge safely from a worker thread.
"""

from __future__ import annotations

import copy
import threading
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from audiocli.capabilities import CapabilityNode, list_capabilities
from audiocli.chains import CapabilityChain, ChainNode
from audiocli.errors import AudioCLIError
from audiocli.gui.chain_session import ChainSession
from audiocli.gui.import_export import (
    ExportResult,
    ImportResult,
    export_chain_to_acli,
    export_native_chain,
    import_acli_chain,
    import_native_chain,
)
from audiocli.gui.library import SavedChainEntry, SavedChainLibraryService
from audiocli.gui.settings import GuiSettings, load_gui_settings, save_gui_settings
from audiocli.gui_service import (
    ChainOutputPolicy,
    execute_file_chain,
    prepare_file_chain_execution,
    preview_destructive_filters,
)


@dataclass
class WorkspaceJobState:
    """Mutable target/output/job state for the GUI workspace."""

    targets: list[str] = field(default_factory=list)
    output_path: str = ""
    output_mode: str = "final_only"
    worker_count: int = 0
    recursive: bool = True
    running: bool = False
    cancel_requested: bool = False
    status: str = "idle"
    progress: float = 0.0
    done: int = 0
    total: int = 0
    current_node: str = ""
    current_file: str = ""
    results: list[dict[str, Any]] = field(default_factory=list)
    errors: list[dict[str, Any]] = field(default_factory=list)
    events: list[dict[str, Any]] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)
    logs: list[str] = field(default_factory=list)

    def to_view_model(self) -> dict[str, Any]:
        return {
            "targets": list(self.targets),
            "output_path": self.output_path,
            "output_mode": self.output_mode,
            "worker_count": self.worker_count,
            "recursive": self.recursive,
            "running": self.running,
            "cancel_requested": self.cancel_requested,
            "status": self.status,
            "progress": self.progress,
            "done": self.done,
            "total": self.total,
            "current_node": self.current_node,
            "current_file": self.current_file,
            "results": list(self.results),
            "errors": list(self.errors),
            "events": list(self.events),
            "summary": dict(self.summary),
            "logs": list(self.logs),
        }


@dataclass(frozen=True)
class WorkspaceExecutionRequest:
    """Immutable execution snapshot handed to a worker thread."""

    chain: CapabilityChain
    targets: tuple[str, ...]
    output_path: str = ""
    output_mode: str = "final_only"
    worker_count: int = 0
    recursive: bool = True
    destructive_confirmation: Mapping[str, Any] | None = None

    @property
    def output_policy(self) -> ChainOutputPolicy:
        return ChainOutputPolicy(
            mode=self.output_mode,
            output=Path(self.output_path) if self.output_path else None,
        )

    def to_view_model(self) -> dict[str, Any]:
        return {
            "chain_id": self.chain.id,
            "chain_name": self.chain.name,
            "targets": list(self.targets),
            "output_path": self.output_path,
            "output_mode": self.output_mode,
            "worker_count": self.worker_count,
            "recursive": self.recursive,
            "destructive_confirmation": dict(self.destructive_confirmation or {}),
        }


EventObserver = Callable[[dict[str, Any]], None]


class WorkspaceExecutionService:
    """GUI-neutral state reducer and synchronous runner for workspace jobs.

    Qt code uses :meth:`start_execution`, :meth:`apply_event`,
    :meth:`finish_execution`, and :meth:`fail_execution` on the main thread while
    a worker emits raw service events.  Tests and non-Qt callers can use
    :meth:`run_sync` directly.
    """

    def __init__(self, job_state: WorkspaceJobState | None = None) -> None:
        self.job = job_state or WorkspaceJobState()

    def make_request(
        self,
        chain: CapabilityChain,
        *,
        capability_catalog: Mapping[str, CapabilityNode] | None = None,
        targets: Sequence[str | Path] | None = None,
        output_path: str | Path | None = None,
        output_mode: str | None = None,
        worker_count: int | None = None,
        recursive: bool | None = None,
        destructive_confirmation: Mapping[str, Any] | None = None,
    ) -> WorkspaceExecutionRequest:
        target_values = [str(path) for path in (self.job.targets if targets is None else targets)]
        output_value = self.job.output_path if output_path is None else str(output_path)
        mode_value = self.job.output_mode if output_mode is None else str(output_mode)
        worker_value = self.job.worker_count if worker_count is None else max(0, int(worker_count))
        recursive_value = self.job.recursive if recursive is None else bool(recursive)
        return WorkspaceExecutionRequest(
            chain=_snapshot_chain(chain, capability_catalog=capability_catalog),
            targets=tuple(target_values),
            output_path=output_value,
            output_mode=mode_value,
            worker_count=worker_value,
            recursive=recursive_value,
            destructive_confirmation=destructive_confirmation,
        )

    def prepare_request(self, request: WorkspaceExecutionRequest) -> WorkspaceExecutionRequest:
        """Return a request whose destructive confirmation covers scanned files.

        The GUI accepts directories, while the execution guard verifies concrete
        files after scanner expansion.  This lightweight preflight reuses the
        normal chain preparation path, then rewrites ``affected_paths`` from raw
        user targets to the scanned file list before a worker is started.
        """

        if not _request_needs_destructive_confirmation(request) or not _confirmation_is_confirmed(
            request.destructive_confirmation
        ):
            return request

        impact = self.preview_destructive_impact(request)
        affected_paths = list(impact.get("affected_paths") or [])
        confirmation = _confirmation_to_dict(request.destructive_confirmation)
        confirmation.update(
            {
                "confirmed": True,
                "affected_paths": affected_paths,
                "affected_file_count": len(affected_paths),
                "affected_directory_count": _target_directory_count(request.targets),
            }
        )
        return replace(request, destructive_confirmation=confirmation)

    def preview_destructive_impact(self, request: WorkspaceExecutionRequest) -> dict[str, Any]:
        """Return scanned destructive impact details for confirmation UI."""

        filter_impact = _preview_destructive_filter_impact(request)
        if filter_impact is not None:
            return filter_impact
        if request.output_mode != "destructive":
            return {
                "affected_paths": [],
                "affected_file_count": 0,
                "affected_directory_count": 0,
            }
        preparation = self._prepare_destructive_preflight(request, require_coverage=False)
        affected_paths = [str(path) for path in preparation.targets]
        return {
            "affected_paths": affected_paths,
            "affected_file_count": len(affected_paths),
            "affected_directory_count": _target_directory_count(request.targets),
        }

    def validate_request(self, request: WorkspaceExecutionRequest) -> list[dict[str, Any]]:
        errors: list[dict[str, Any]] = []
        validation = request.chain.validate()
        if not validation.valid:
            errors.extend(
                {
                    "status": "validation_error",
                    "code": error.code,
                    "message": error.message,
                    "node_id": error.node_id,
                    "capability_id": error.capability_id,
                    "parameter": error.parameter,
                }
                for error in validation.errors
            )
        if not request.targets:
            errors.append(
                {
                    "status": "validation_error",
                    "code": "no_targets",
                    "message": "Select at least one target file or directory before running.",
                    "node_id": "",
                }
            )
        if request.output_mode not in {"final_only", "keep_intermediates", "destructive"}:
            errors.append(
                {
                    "status": "validation_error",
                    "code": "invalid_output_mode",
                    "message": f"Unsupported output mode: {request.output_mode!r}.",
                    "node_id": "",
                }
            )
        if _request_needs_destructive_confirmation(request) and not _confirmation_is_confirmed(
            request.destructive_confirmation
        ):
            errors.append(
                {
                    "status": "validation_error",
                    "code": "destructive_confirmation_required",
                    "message": "Destructive mode requires explicit confirmation before execution.",
                    "node_id": "",
                }
            )
        elif request.output_mode == "destructive" and not errors:
            try:
                self._prepare_destructive_preflight(request, require_coverage=True)
            except AudioCLIError as exc:
                errors.append(
                    {
                        "status": "validation_error",
                        "code": "destructive_preflight_failed",
                        "message": str(exc),
                        "node_id": "",
                    }
                )
        return errors

    def _prepare_destructive_preflight(
        self,
        request: WorkspaceExecutionRequest,
        *,
        require_coverage: bool,
    ):
        confirmation = (
            request.destructive_confirmation
            if require_coverage
            else _scanner_confirmation(request.destructive_confirmation)
        )
        return prepare_file_chain_execution(
            request.chain,
            request.targets,
            output_policy=request.output_policy,
            destructive_confirmation=confirmation,
            recursive=request.recursive,
        )

    def start_execution(self, request: WorkspaceExecutionRequest) -> list[dict[str, Any]]:
        """Reset state for a run if pre-flight validation passes.

        Returns validation errors.  When non-empty, no worker should be started.
        """

        self.job.targets = list(request.targets)
        self.job.output_path = request.output_path
        self.job.output_mode = request.output_mode
        self.job.worker_count = request.worker_count
        self.job.recursive = request.recursive
        errors = self.validate_request(request)
        self._reset_runtime_state()
        if errors:
            self.job.status = "validation_error"
            self.job.running = False
            self.job.results = errors
            self.job.errors = list(errors)
            self.job.summary = {"status": "validation_error", "error_count": len(errors)}
            self.job.logs.append("Run blocked by validation errors.")
            return errors

        self.job.running = True
        self.job.status = "running"
        self.job.logs.append(f"Run started for {len(request.targets)} target(s).")
        return []

    def request_cancel(self, cancel_token: threading.Event | None = None) -> None:
        """Mark cancellation requested and set the underlying token if provided."""

        self.job.cancel_requested = True
        if self.job.status == "running":
            self.job.status = "cancelling"
        if cancel_token is not None:
            cancel_token.set()
        self.job.logs.append("Cancellation requested; in-flight work will finish safely.")

    def apply_event(self, event: Mapping[str, Any]) -> dict[str, Any]:
        """Apply one service event to the job state and return its dict copy."""

        payload = dict(event)
        event_type = str(payload.get("type") or payload.get("event") or "event")
        payload.setdefault("type", event_type)
        payload.setdefault("event", event_type)
        self.job.events.append(payload)

        status = payload.get("status")
        if isinstance(status, str) and status:
            self.job.status = status
        if event_type == "chain_start":
            self.job.running = True
            self.job.status = "running"
            self.job.total = _int_value(payload.get("total") or payload.get("total_files"))
            self.job.done = _int_value(payload.get("done"))
            self.job.progress = _progress(self.job.done, self.job.total)
        elif event_type in {"node_start", "node_done", "error", "cancellation"}:
            self.job.current_node = _node_label(payload)
            self.job.current_file = str(
                payload.get("source_path") or payload.get("path") or self.job.current_file
            )
            if event_type == "cancellation":
                self.job.cancel_requested = True
            if event_type == "error":
                self.job.errors.append(payload)
        elif event_type in {"file_done", "file_progress"}:
            self.job.current_file = str(
                payload.get("source_path") or payload.get("current") or self.job.current_file
            )
            self.job.done = _int_value(payload.get("done"), self.job.done)
            self.job.total = _int_value(
                payload.get("total") or payload.get("total_files"), self.job.total
            )
            self.job.progress = _progress(self.job.done, self.job.total)
            if event_type == "file_done":
                self.job.results.append(_file_result_from_event(payload))
                if payload.get("status") == "failed":
                    self.job.errors.append(payload)
        elif event_type == "chain_done":
            self.job.running = False
            self.job.done = _int_value(payload.get("done"), self.job.done)
            self.job.total = _int_value(
                payload.get("total") or payload.get("total_files"), self.job.total
            )
            self.job.progress = _progress(self.job.done, self.job.total)
            self.job.summary = _summary_from_event(payload)

        self.job.logs.append(_event_log_line(payload))
        return payload

    def finish_execution(self, report: Mapping[str, Any]) -> dict[str, Any]:
        """Apply a final ``FileChainExecutionRun.to_view_model()`` report."""

        report_dict = dict(report)
        report_payload = dict(report_dict.get("report") or report_dict)
        self.job.running = False
        self.job.status = str(report_payload.get("status") or self.job.status or "done")
        self.job.summary = report_payload
        if "results" in report_payload:
            self.job.results = [dict(result) for result in report_payload.get("results") or []]
        self.job.done = len(self.job.results) or self.job.done
        self.job.total = max(self.job.total, self.job.done)
        self.job.progress = _progress(self.job.done, self.job.total)
        self.job.logs.append(
            "Run finished: "
            f"status={self.job.status}, ok={report_payload.get('ok_count', 0)}, "
            f"failed={report_payload.get('failed_count', 0)}, "
            f"cancelled={report_payload.get('cancelled_count', 0)}."
        )
        return report_dict

    def fail_execution(self, message: str) -> dict[str, Any]:
        """Mark execution failed before a final service report was produced."""

        error = {"status": "failed", "message": message, "error": message}
        self.job.running = False
        self.job.status = "failed"
        self.job.errors.append(error)
        self.job.results.append(error)
        self.job.summary = {"status": "failed", "error": message, "failed_count": 1}
        self.job.logs.append(f"Run failed: {message}")
        return error

    def run_sync(
        self,
        request: WorkspaceExecutionRequest,
        *,
        cancel_token: threading.Event | None = None,
        on_event: EventObserver | None = None,
    ) -> dict[str, Any]:
        """Run a request synchronously, applying all events to this service state."""

        request = self.prepare_request(request)
        errors = self.start_execution(request)
        if errors:
            return {"report": dict(self.job.summary), "results": list(self.job.results)}
        token = cancel_token or threading.Event()

        def handle_event(event: dict[str, Any]) -> None:
            applied = self.apply_event(event)
            if on_event is not None:
                on_event(applied)

        try:
            run = execute_file_chain(
                request.chain,
                request.targets,
                output_policy=request.output_policy,
                destructive_confirmation=request.destructive_confirmation,
                recursive=request.recursive,
                on_event=handle_event,
                cancel_token=token,
            )
        except Exception as exc:
            message = str(exc) if isinstance(exc, AudioCLIError) else f"{type(exc).__name__}: {exc}"
            return self.fail_execution(message)
        return self.finish_execution(run.to_view_model())

    def _reset_runtime_state(self) -> None:
        self.job.running = False
        self.job.cancel_requested = False
        self.job.status = "idle"
        self.job.progress = 0.0
        self.job.done = 0
        self.job.total = 0
        self.job.current_node = ""
        self.job.current_file = ""
        self.job.results = []
        self.job.errors = []
        self.job.events = []
        self.job.summary = {}


class InMemoryWorkspaceService:
    """Service/view-model boundary for the desktop workspace shell.

    The service owns a mutable :class:`~audiocli.chains.CapabilityChain` and a
    service-provided capability catalog.  Execution state is reduced through
    :class:`WorkspaceExecutionService`, allowing tests to exercise real service
    runs without importing PySide6.
    """

    def __init__(
        self,
        capabilities: Iterable[CapabilityNode] | None = None,
        *,
        chain_name: str = "AudioCLI Workspace Chain",
        settings: GuiSettings | None = None,
        settings_path: str | Path | None = None,
    ) -> None:
        capability_list = list(list_capabilities() if capabilities is None else capabilities)
        self._capabilities: list[CapabilityNode] = capability_list
        self._catalog: dict[str, CapabilityNode] = {node.id: node for node in capability_list}
        self.settings_path = Path(settings_path) if settings_path is not None else None
        self.settings = settings if settings is not None else load_gui_settings(self.settings_path)
        self.chain_session = ChainSession(self._catalog, chain_name=chain_name)
        self.job = WorkspaceJobState(
            output_mode=self.settings.last_output_mode,
            worker_count=self.settings.worker_count,
            recursive=self.settings.recursive,
        )
        self.execution = WorkspaceExecutionService(self.job)

    @property
    def chain(self) -> CapabilityChain:
        return self.chain_session.chain

    @chain.setter
    def chain(self, chain: CapabilityChain) -> None:
        self.replace_chain(chain)

    @property
    def selected_node_id(self) -> str | None:
        return self.chain_session.selected_node_id

    @selected_node_id.setter
    def selected_node_id(self, node_id: str | None) -> None:
        self.chain_session.selected_node_id = node_id

    @property
    def capability_catalog(self) -> Mapping[str, CapabilityNode]:
        return self._catalog

    def capabilities(self) -> list[CapabilityNode]:
        """Return the service-provided capability nodes in browser order."""

        return list(self._capabilities)

    def get_capability(self, capability_id: str) -> CapabilityNode:
        return self.chain_session.get_capability(capability_id)

    def replace_chain(
        self, chain: CapabilityChain, *, select_first: bool = True
    ) -> CapabilityChain:
        return self.chain_session.replace_chain(chain, select_first=select_first)

    def selected_node(self) -> ChainNode | None:
        return self.chain_session.selected_node()

    def selected_capability(self) -> CapabilityNode | None:
        return self.chain_session.selected_capability()

    def select_node(self, node_id: str | None) -> ChainNode | None:
        return self.chain_session.select_node(node_id)

    def add_node(self, capability_id: str, *, index: int | None = None) -> ChainNode:
        capability = self.get_capability(capability_id)
        node = self.chain_session.add_node(capability.id, index=index)
        self.job.logs.append(f"Added {capability.display_name} to the chain.")
        return node

    def move_node(self, node_id: str, index: int) -> ChainNode:
        node = self.chain_session.move_node(node_id, index)
        self.job.logs.append(f"Moved node {node.id} to position {index + 1}.")
        return node

    def move_selected(self, delta: int) -> ChainNode | None:
        selected = self.selected_node()
        current_index = self.chain.nodes.index(selected) if selected is not None else None
        node = self.chain_session.move_selected(delta)
        if node is not None and current_index is not None:
            new_index = self.chain.nodes.index(node)
            if new_index != current_index:
                self.job.logs.append(f"Moved node {node.id} to position {new_index + 1}.")
        return node

    def remove_node(self, node_id: str) -> ChainNode:
        node = self.chain_session.remove_node(node_id)
        self.job.logs.append(f"Removed node {node.id}.")
        return node

    def remove_selected(self) -> ChainNode | None:
        node = self.selected_node()
        if node is None:
            return None
        return self.remove_node(node.id)

    def update_node_params(self, node_id: str, params: Mapping[str, Any]) -> ChainNode:
        return self.chain_session.update_node_params(node_id, params)

    def update_selected_param(self, name: str, value: Any) -> ChainNode | None:
        return self.chain_session.update_selected_param(name, value)

    def set_targets(self, targets: Sequence[str | Path]) -> None:
        self.job.targets = [str(path) for path in targets]
        self.settings = self.settings.with_recent_targets(self.job.targets)

    def set_output_path(self, output_path: str | Path | None) -> None:
        self.job.output_path = "" if output_path is None else str(output_path)
        self.settings = self.settings.with_recent_output_folder(self.job.output_path)

    def set_output_mode(self, output_mode: str) -> None:
        self.job.output_mode = output_mode
        self.settings = replace(self.settings, last_output_mode=output_mode)

    def set_worker_count(self, worker_count: int) -> None:
        self.job.worker_count = max(0, int(worker_count))
        self.settings = replace(self.settings, worker_count=self.job.worker_count)

    def set_recursive(self, recursive: bool) -> None:
        self.job.recursive = bool(recursive)
        self.settings = replace(self.settings, recursive=self.job.recursive)

    def set_chain_library_dir(self, chain_library_dir: str | Path) -> None:
        self.settings = replace(self.settings, chain_library_dir=str(chain_library_dir))

    def save_settings(self) -> Path:
        return save_gui_settings(self.settings, self.settings_path)

    def chain_library_service(self) -> SavedChainLibraryService:
        return SavedChainLibraryService(
            self.settings.chain_library_dir,
            capability_catalog=self._catalog,
        )

    def list_saved_chains(self) -> list[SavedChainEntry]:
        return self.chain_library_service().list_entries()

    def saved_chain_library_view_model(self) -> dict[str, Any]:
        return self.chain_library_service().to_view_model()

    def load_saved_chain(self, path: str | Path) -> CapabilityChain:
        chain = self.chain_library_service().load_saved_chain(path)
        self.replace_chain(chain)
        self.job.logs.append(f"Loaded saved chain '{chain.name}' from {path}.")
        return chain

    def rename_saved_chain(self, path: str | Path, new_name: str) -> SavedChainEntry:
        entry = self.chain_library_service().rename_saved_chain(path, new_name)
        self.job.logs.append(f"Renamed saved chain at {path} to '{entry.name}'.")
        return entry

    def update_saved_chain_notes(
        self,
        path: str | Path,
        *,
        description: str | None = None,
        notes: str | None = None,
    ) -> SavedChainEntry:
        entry = self.chain_library_service().update_saved_chain_notes(
            path,
            description=description,
            notes=notes,
        )
        self.job.logs.append(f"Updated saved-chain notes for {path}.")
        return entry

    def import_native_chain(self, path: str | Path) -> ImportResult:
        result = import_native_chain(path, capability_catalog=self._catalog)
        self.replace_chain(result.chain)
        self.job.logs.append(result.explanation)
        return result

    def export_current_chain_native(self, path: str | Path) -> ExportResult:
        result = export_native_chain(self.chain, path)
        self.job.logs.append(result.explanation)
        return result

    def import_acli_script_file(self, path: str | Path, *, strict: bool = False) -> ImportResult:
        result = import_acli_chain(path, strict=strict)
        self.replace_chain(result.chain)
        self.job.logs.append(result.explanation)
        return result

    def export_current_chain_acli(self, path: str | Path) -> ExportResult:
        result = export_chain_to_acli(
            self.chain,
            path,
            targets=self.job.targets,
            output=self.job.output_path or None,
            recursive=self.job.recursive,
            workers=self.job.worker_count,
        )
        self.job.logs.append(result.explanation)
        return result

    def make_execution_request(
        self,
        *,
        destructive_confirmation: Mapping[str, Any] | None = None,
    ) -> WorkspaceExecutionRequest:
        return self.execution.make_request(
            self.chain,
            capability_catalog=self._catalog,
            destructive_confirmation=destructive_confirmation,
        )

    def prepare_execution_request(
        self, request: WorkspaceExecutionRequest
    ) -> WorkspaceExecutionRequest:
        return self.execution.prepare_request(request)

    def preview_destructive_impact(self, request: WorkspaceExecutionRequest) -> dict[str, Any]:
        return self.execution.preview_destructive_impact(request)

    def start_execution(self, request: WorkspaceExecutionRequest) -> list[dict[str, Any]]:
        self.settings = self.settings.with_recent_targets(
            request.targets
        ).with_recent_output_folder(request.output_path)
        self.settings = replace(
            self.settings,
            last_output_mode=request.output_mode,
            worker_count=request.worker_count,
            recursive=request.recursive,
        )
        return self.execution.start_execution(request)

    def apply_execution_event(self, event: Mapping[str, Any]) -> dict[str, Any]:
        return self.execution.apply_event(event)

    def finish_execution(self, report: Mapping[str, Any]) -> dict[str, Any]:
        return self.execution.finish_execution(report)

    def fail_execution(self, message: str) -> dict[str, Any]:
        return self.execution.fail_execution(message)

    def request_cancel_execution(self, cancel_token: threading.Event | None = None) -> None:
        self.execution.request_cancel(cancel_token)

    def run_current_chain_sync(
        self,
        *,
        cancel_token: threading.Event | None = None,
        on_event: EventObserver | None = None,
        destructive_confirmation: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        request = self.make_execution_request(destructive_confirmation=destructive_confirmation)
        self.settings = self.settings.with_recent_targets(
            request.targets
        ).with_recent_output_folder(request.output_path)
        self.settings = replace(
            self.settings,
            last_output_mode=request.output_mode,
            worker_count=request.worker_count,
            recursive=request.recursive,
        )
        return self.execution.run_sync(request, cancel_token=cancel_token, on_event=on_event)

    def run_fake_job(self) -> list[dict[str, Any]]:
        """Compatibility shim for issue-12 tests; prefer real execution now."""

        validation = self.chain.validate()
        self.job.running = False
        if not validation.valid:
            self.job.results = [
                {
                    "status": "validation_error",
                    "code": error.code,
                    "message": error.message,
                    "node_id": error.node_id,
                }
                for error in validation.errors
            ]
            self.job.logs.append("Fake run blocked by chain validation errors.")
            return self.job.results

        targets = self.job.targets or ["<no target selected>"]
        steps = self.chain.to_execution_plan(validate=True).steps
        self.job.results = [
            {
                "status": "ok",
                "target": target,
                "output": self.job.output_path or "<preview>",
                "steps": [step.operation_name for step in steps],
            }
            for target in targets
        ]
        self.job.logs.append(f"Fake run completed for {len(targets)} target(s).")
        return self.job.results

    def cancel_fake_job(self) -> None:
        self.request_cancel_execution()
        self.job.running = False
        self.job.logs.append("Fake run cancelled.")

    def to_view_model(self) -> dict[str, Any]:
        return {
            "capabilities": [capability.to_view_model() for capability in self._capabilities],
            "chain": self.chain.to_view_model(),
            "selected_node_id": self.selected_node_id,
            "selected_node": self._selected_node_view_model(),
            "job": self.job.to_view_model(),
            "settings": self.settings.to_view_model(),
            "saved_chain_library": self.saved_chain_library_view_model(),
        }

    def _selected_node_view_model(self) -> dict[str, Any] | None:
        return self.chain_session.selected_node_view_model()


def _snapshot_chain(
    chain: CapabilityChain,
    *,
    capability_catalog: Mapping[str, CapabilityNode] | None = None,
) -> CapabilityChain:
    snapshot = CapabilityChain.from_dict(
        copy.deepcopy(chain.to_dict()),
        include_plugins=chain.include_plugins,
        capability_catalog=capability_catalog
        if capability_catalog is not None
        else chain.capability_catalog,
    )
    snapshot.source_path = chain.source_path
    snapshot.chain_dir = chain.chain_dir
    return snapshot


def _destructive_filter_kinds(request: WorkspaceExecutionRequest) -> list[str]:
    try:
        steps = request.chain.to_execution_plan(validate=True).steps
    except Exception:
        return []
    kinds: list[str] = []
    for step in steps:
        if str(step.params.get("action") or "skip").strip().lower() not in {
            "delete",
            "move",
            "rename",
        }:
            continue
        if (
            step.capability_id
            in {"builtin.file_filter.remove_silent", "builtin.destructive.remove_silent"}
            or step.operation_name == "remove_silent"
        ):
            kinds.append("remove_silent")
        elif (
            step.capability_id
            in {"builtin.file_filter.name_regex", "builtin.destructive.name_regex"}
            or step.operation_name == "name_regex_filter"
        ):
            kinds.append("name_regex")
    return kinds


def _request_needs_destructive_confirmation(request: WorkspaceExecutionRequest) -> bool:
    return request.output_mode == "destructive" or bool(_destructive_filter_kinds(request))


def _preview_destructive_filter_impact(
    request: WorkspaceExecutionRequest,
) -> dict[str, Any] | None:
    kinds = _destructive_filter_kinds(request)
    if not kinds:
        return None
    preview = preview_destructive_filters(
        request.chain,
        request.targets,
        recursive=request.recursive,
    )
    affected_paths = [str(path) for path in preview.affected_paths]
    filter_kind = kinds[0] if len(kinds) == 1 else "multiple"
    return {
        "affected_paths": affected_paths,
        "affected_file_count": len(affected_paths),
        "affected_directory_count": _target_directory_count(request.targets),
        "destructive_filter": filter_kind,
        "destructive_filters": kinds,
        "preview": preview.to_view_model(),
    }


def _confirmation_is_confirmed(confirmation: Mapping[str, Any] | None) -> bool:
    return bool(confirmation and confirmation.get("confirmed"))


def _confirmation_to_dict(confirmation: Mapping[str, Any] | None) -> dict[str, Any]:
    return dict(confirmation or {})


def _scanner_confirmation(confirmation: Mapping[str, Any] | None) -> dict[str, Any]:
    prepared = _confirmation_to_dict(confirmation)
    prepared["confirmed"] = True
    prepared["affected_paths"] = []
    return prepared


def _target_directory_count(targets: Sequence[str]) -> int:
    return sum(1 for target in targets if Path(target).is_dir())


def _int_value(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _progress(done: int, total: int) -> float:
    if total <= 0:
        return 0.0
    return max(0.0, min(1.0, done / total))


def _node_label(event: Mapping[str, Any]) -> str:
    operation = event.get("operation_name")
    node_id = event.get("node_id")
    if operation and node_id:
        return f"{operation} ({node_id})"
    return str(operation or node_id or "")


def _file_result_from_event(event: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "source_path": event.get("source_path"),
        "path": event.get("path"),
        "output_path": event.get("output_path"),
        "status": event.get("status"),
        "ok": event.get("ok"),
        "error": event.get("error"),
    }


def _summary_from_event(event: Mapping[str, Any]) -> dict[str, Any]:
    keys = (
        "status",
        "done",
        "total",
        "total_files",
        "ok_count",
        "kept_count",
        "removed_count",
        "failed_count",
        "cancelled_count",
        "duration_s",
    )
    return {key: event[key] for key in keys if key in event}


def _event_log_line(event: Mapping[str, Any]) -> str:
    event_type = str(event.get("type") or event.get("event") or "event")
    status = event.get("status")
    node = event.get("operation_name") or event.get("node_id")
    source = event.get("source_path") or event.get("current") or event.get("path")
    parts = [event_type]
    if status:
        parts.append(str(status))
    if node:
        parts.append(str(node))
    if source:
        parts.append(str(source))
    if event.get("error"):
        parts.append(str(event["error"]))
    return " | ".join(parts)


WorkspaceService = InMemoryWorkspaceService
