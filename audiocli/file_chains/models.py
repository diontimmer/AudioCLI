"""Pure dataclasses and view models for file-chain GUI services."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from audiocli.chains import ChainExecutionPlan, ChainExecutionStep, ChainValidationResult
from audiocli.pipeline import JobReport

CHAIN_OUTPUT_MODES = frozenset({"final_only", "keep_intermediates", "destructive"})
INTERMEDIATES_DIRNAME = ".audiocli-intermediates"
CHAIN_FILE_STATUSES = frozenset(
    {"ok", "kept", "filtered", "removed", "copied", "moved", "renamed", "failed", "cancelled"}
)
CHAIN_SUCCESS_STATUSES = frozenset(
    {"ok", "kept", "filtered", "removed", "copied", "moved", "renamed"}
)
FILE_FILTER_CONFIRMATION_ACTIONS = frozenset({"delete", "move", "rename"})


@dataclass(frozen=True)
class ChainEvent:
    """JSON-safe chain execution event emitted by ``execute_file_chain``.

    ``type`` is the canonical discriminator and ``event`` mirrors it for UI
    adapters that prefer that key. Optional fields are omitted from
    :meth:`to_json`, while falsey JSON values such as ``False`` and ``0`` are
    preserved.
    """

    type: str
    chain_id: str
    run_id: str
    chain_name: str | None = None
    status: str | None = None
    scope: str | None = None
    node_id: str | None = None
    node_index: int | None = None
    node_count: int | None = None
    capability_id: str | None = None
    operation_name: str | None = None
    file_index: int | None = None
    total_files: int | None = None
    source_path: str | None = None
    path: str | None = None
    output_path: str | None = None
    done: int | None = None
    total: int | None = None
    current: str | None = None
    ok: bool | None = None
    ok_count: int | None = None
    kept_count: int | None = None
    removed_count: int | None = None
    filtered_count: int | None = None
    copied_count: int | None = None
    moved_count: int | None = None
    renamed_count: int | None = None
    failed_count: int | None = None
    cancelled_count: int | None = None
    metadata: dict[str, Any] | None = None
    error: str | None = None
    reason: str | None = None
    duration_s: float | None = None
    workers: int | None = None

    def to_json(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"type": self.type, "event": self.type}
        for key, value in self.__dict__.items():
            if key == "type" or value is None:
                continue
            payload[key] = _event_json_safe(value)
        return payload

    def to_dict(self) -> dict[str, Any]:
        return self.to_json()

    def to_view_model(self) -> dict[str, Any]:
        return self.to_json()


@dataclass(frozen=True)
class ChainOutputPreview:
    """Predicted destination for one scanned source file."""

    source_path: Path
    output_path: Path

    def to_view_model(self) -> dict[str, str]:
        return {
            "source_path": str(self.source_path),
            "output_path": str(self.output_path),
        }


@dataclass(frozen=True)
class OneNodeFilterChainPreparation:
    """Validated, scanned, previewed one-node chain ready for execution."""

    chain_id: str
    chain_name: str
    step: ChainExecutionStep
    targets: list[Path] = field(default_factory=list)
    output_preview: list[ChainOutputPreview] = field(default_factory=list)
    validation: ChainValidationResult | None = None
    scan_roots: tuple[Path, ...] = ()

    @property
    def target_count(self) -> int:
        return len(self.targets)

    def to_view_model(self) -> dict[str, Any]:
        return {
            "chain_id": self.chain_id,
            "chain_name": self.chain_name,
            "step": self.step.to_view_model(),
            "target_count": self.target_count,
            "targets": [str(path) for path in self.targets],
            "output_preview": [preview.to_view_model() for preview in self.output_preview],
            "validation_state": self.validation.to_view_model() if self.validation else None,
            "scan_roots": [str(path) for path in self.scan_roots],
        }


@dataclass(frozen=True)
class OneNodeFilterChainRun:
    """Result of executing a prepared one-node filter chain."""

    preparation: OneNodeFilterChainPreparation
    report: JobReport

    @property
    def ok_count(self) -> int:
        return self.report.ok_count

    @property
    def failed_count(self) -> int:
        return self.report.failed_count

    @property
    def exit_code(self) -> int:
        return self.report.exit_code

    def to_view_model(self) -> dict[str, Any]:
        return {
            **self.preparation.to_view_model(),
            "report": {
                "ok_count": self.report.ok_count,
                "failed_count": self.report.failed_count,
                "exit_code": self.report.exit_code,
                "duration_s": self.report.duration_s,
                "results": [
                    {
                        "path": str(result.path),
                        "ok": result.ok,
                        "error": result.error,
                    }
                    for result in self.report.results
                ],
            },
        }


@dataclass(frozen=True)
class DestructiveConfirmation:
    """Explicit opt-in required before destructive/in-place chain execution."""

    confirmed: bool
    affected_paths: list[Path] = field(default_factory=list)

    def to_view_model(self) -> dict[str, Any]:
        return {
            "confirmed": self.confirmed,
            "affected_paths": [str(path) for path in self.affected_paths],
        }


@dataclass(frozen=True)
class RemoveSilentFileAssessment:
    """Dry-run/confirmation assessment for one file touched by remove-silent."""

    path: Path
    status: str
    threshold_db: float
    metric: str
    silent: bool | None = None
    error: str | None = None

    @property
    def would_remove(self) -> bool:
        return self.status == "removed"

    def to_view_model(self) -> dict[str, Any]:
        return {
            "path": str(self.path),
            "status": self.status,
            "would_remove": self.would_remove,
            "silent": self.silent,
            "threshold_db": self.threshold_db,
            "metric": self.metric,
            "error": self.error,
        }


@dataclass
class RemoveSilentPreview:
    """Structured dry-run summary for a guarded remove-silent node."""

    chain_id: str
    chain_name: str
    step: ChainExecutionStep
    targets: list[Path] = field(default_factory=list)
    results: list[RemoveSilentFileAssessment] = field(default_factory=list)
    duration_s: float = 0.0

    @property
    def removed_candidates(self) -> list[Path]:
        return [result.path for result in self.results if result.status == "removed"]

    @property
    def affected_paths(self) -> list[Path]:
        return self.removed_candidates

    @property
    def kept(self) -> list[Path]:
        return [result.path for result in self.results if result.status == "kept"]

    @property
    def failed(self) -> list[RemoveSilentFileAssessment]:
        return [result for result in self.results if result.status == "failed"]

    @property
    def cancelled(self) -> list[Path]:
        return [result.path for result in self.results if result.status == "cancelled"]

    @property
    def removed_count(self) -> int:
        return len(self.removed_candidates)

    @property
    def kept_count(self) -> int:
        return len(self.kept)

    @property
    def failed_count(self) -> int:
        return len(self.failed)

    @property
    def cancelled_count(self) -> int:
        return len(self.cancelled)

    def to_view_model(self) -> dict[str, Any]:
        return {
            "chain_id": self.chain_id,
            "chain_name": self.chain_name,
            "step": self.step.to_view_model(),
            "target_count": len(self.targets),
            "targets": [str(path) for path in self.targets],
            "removed_candidates": [str(path) for path in self.removed_candidates],
            "affected_paths": [str(path) for path in self.affected_paths],
            "kept": [str(path) for path in self.kept],
            "failed": [result.to_view_model() for result in self.failed],
            "cancelled": [str(path) for path in self.cancelled],
            "removed_count": self.removed_count,
            "kept_count": self.kept_count,
            "failed_count": self.failed_count,
            "cancelled_count": self.cancelled_count,
            "duration_s": self.duration_s,
            "results": [result.to_view_model() for result in self.results],
        }


@dataclass(frozen=True)
class NameRegexFileAssessment:
    """Dry-run/confirmation assessment for one filename-regex filter file."""

    path: Path
    status: str
    pattern: str
    case_sensitive: bool = False
    matched: bool | None = None
    error: str | None = None

    @property
    def would_remove(self) -> bool:
        return self.status == "removed"

    def to_view_model(self) -> dict[str, Any]:
        return {
            "path": str(self.path),
            "status": self.status,
            "would_remove": self.would_remove,
            "matched": self.matched,
            "pattern": self.pattern,
            "case_sensitive": self.case_sensitive,
            "error": self.error,
        }


@dataclass
class NameRegexFilterPreview:
    """Structured dry-run summary for a guarded filename-regex filter node."""

    chain_id: str
    chain_name: str
    step: ChainExecutionStep
    targets: list[Path] = field(default_factory=list)
    results: list[NameRegexFileAssessment] = field(default_factory=list)
    duration_s: float = 0.0

    @property
    def removed_candidates(self) -> list[Path]:
        return [result.path for result in self.results if result.status == "removed"]

    @property
    def affected_paths(self) -> list[Path]:
        return self.removed_candidates

    @property
    def kept(self) -> list[Path]:
        return [result.path for result in self.results if result.status == "kept"]

    @property
    def failed(self) -> list[NameRegexFileAssessment]:
        return [result for result in self.results if result.status == "failed"]

    @property
    def cancelled(self) -> list[Path]:
        return [result.path for result in self.results if result.status == "cancelled"]

    @property
    def removed_count(self) -> int:
        return len(self.removed_candidates)

    @property
    def kept_count(self) -> int:
        return len(self.kept)

    @property
    def failed_count(self) -> int:
        return len(self.failed)

    @property
    def cancelled_count(self) -> int:
        return len(self.cancelled)

    def to_view_model(self) -> dict[str, Any]:
        return {
            "chain_id": self.chain_id,
            "chain_name": self.chain_name,
            "step": self.step.to_view_model(),
            "target_count": len(self.targets),
            "targets": [str(path) for path in self.targets],
            "removed_candidates": [str(path) for path in self.removed_candidates],
            "affected_paths": [str(path) for path in self.affected_paths],
            "kept": [str(path) for path in self.kept],
            "failed": [result.to_view_model() for result in self.failed],
            "cancelled": [str(path) for path in self.cancelled],
            "removed_count": self.removed_count,
            "kept_count": self.kept_count,
            "failed_count": self.failed_count,
            "cancelled_count": self.cancelled_count,
            "duration_s": self.duration_s,
            "results": [result.to_view_model() for result in self.results],
        }


@dataclass(frozen=True)
class ChainOutputPolicy:
    """Normalized output policy for file-based chain execution."""

    mode: str = "final_only"
    output: Path | None = None

    def to_view_model(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "output": str(self.output) if self.output is not None else None,
        }


@dataclass(frozen=True)
class ChainAnalysisResult:
    """Structured metadata emitted by one analysis node for one file."""

    step_index: int
    step: ChainExecutionStep
    path: Path
    metadata: dict[str, Any] = field(default_factory=dict)
    ok: bool = True
    error: str | None = None

    def to_view_model(self) -> dict[str, Any]:
        return {
            "step_index": self.step_index,
            "step": self.step.to_view_model(),
            "path": str(self.path),
            "metadata": _event_json_safe(self.metadata),
            "ok": self.ok,
            "error": self.error,
        }


@dataclass(frozen=True)
class ChainScriptResult:
    """Structured report emitted by one external script node for one file/job."""

    step_index: int
    step: ChainExecutionStep
    path: Path | None = None
    report: dict[str, Any] = field(default_factory=dict)
    ok: bool = True
    error: str | None = None
    scope: str = "file"

    def to_view_model(self) -> dict[str, Any]:
        return {
            "step_index": self.step_index,
            "step": self.step.to_view_model(),
            "path": str(self.path) if self.path is not None else None,
            "report": _event_json_safe(self.report),
            "ok": self.ok,
            "error": self.error,
            "scope": self.scope,
        }


@dataclass(frozen=True)
class ChainStepArtifact:
    """One file materialized while executing a chain step."""

    step_index: int
    step: ChainExecutionStep
    path: Path
    intermediate: bool = True

    def to_view_model(self) -> dict[str, Any]:
        return {
            "step_index": self.step_index,
            "step": self.step.to_view_model(),
            "path": str(self.path),
            "intermediate": self.intermediate,
        }


@dataclass(frozen=True)
class ChainStepFileSet:
    """Explicit input/output file set for one executed chain step."""

    step_index: int
    step: ChainExecutionStep
    input_paths: list[Path] = field(default_factory=list)
    output_paths: list[Path] = field(default_factory=list)
    expanded: bool = False
    behavior: str = "single_file"

    def to_view_model(self) -> dict[str, Any]:
        return {
            "step_index": self.step_index,
            "step": self.step.to_view_model(),
            "input_paths": [str(path) for path in self.input_paths],
            "output_paths": [str(path) for path in self.output_paths],
            "expanded": self.expanded,
            "behavior": self.behavior,
        }


@dataclass(frozen=True)
class ChainFileResult:
    """Outcome for one source file in a multi-step file-based chain run."""

    source_path: Path
    path: Path
    ok: bool
    error: str | None = None
    status: str = ""
    output_path: Path | None = None
    output_paths: list[Path] = field(default_factory=list)
    current_files: list[Path] = field(default_factory=list)
    expanded_output_files: list[Path] = field(default_factory=list)
    failed_step_index: int | None = None
    failed_step: ChainExecutionStep | None = None
    cancelled_step_index: int | None = None
    cancelled_step: ChainExecutionStep | None = None
    intermediates: list[ChainStepArtifact] = field(default_factory=list)
    analysis_results: list[ChainAnalysisResult] = field(default_factory=list)
    script_results: list[ChainScriptResult] = field(default_factory=list)
    step_file_sets: list[ChainStepFileSet] = field(default_factory=list)
    preserved_context_dir: Path | None = None

    def __post_init__(self) -> None:
        status = self.status or ("ok" if self.ok else "failed")
        if status not in CHAIN_FILE_STATUSES:
            raise ValueError(
                f"unsupported chain file status {status!r}; expected one of "
                f"{', '.join(sorted(CHAIN_FILE_STATUSES))}"
            )
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "ok", status in CHAIN_SUCCESS_STATUSES)
        if self.output_path is None and self.output_paths:
            object.__setattr__(self, "output_path", self.output_paths[0])
        elif self.output_path is not None and not self.output_paths:
            object.__setattr__(self, "output_paths", [self.output_path])
        if not self.current_files and self.output_paths:
            object.__setattr__(self, "current_files", list(self.output_paths))

    @property
    def cancelled(self) -> bool:
        return self.status == "cancelled"

    @property
    def kept(self) -> bool:
        return self.status == "kept"

    @property
    def removed(self) -> bool:
        return self.status == "removed"

    @property
    def filtered(self) -> bool:
        return self.status == "filtered"

    @property
    def copied(self) -> bool:
        return self.status == "copied"

    @property
    def moved(self) -> bool:
        return self.status == "moved"

    @property
    def renamed(self) -> bool:
        return self.status == "renamed"

    def to_view_model(self) -> dict[str, Any]:
        return {
            "source_path": str(self.source_path),
            "path": str(self.path),
            "ok": self.ok,
            "status": self.status,
            "cancelled": self.cancelled,
            "kept": self.kept,
            "removed": self.removed,
            "filtered": self.filtered,
            "copied": self.copied,
            "moved": self.moved,
            "renamed": self.renamed,
            "error": self.error,
            "output_path": str(self.output_path) if self.output_path is not None else None,
            "output_paths": [str(path) for path in self.output_paths],
            "current_files": [str(path) for path in self.current_files],
            "expanded_output_files": [str(path) for path in self.expanded_output_files],
            "failed_step_index": self.failed_step_index,
            "failed_step": self.failed_step.to_view_model() if self.failed_step else None,
            "cancelled_step_index": self.cancelled_step_index,
            "cancelled_step": self.cancelled_step.to_view_model() if self.cancelled_step else None,
            "intermediates": [artifact.to_view_model() for artifact in self.intermediates],
            "analysis_results": [result.to_view_model() for result in self.analysis_results],
            "script_results": [result.to_view_model() for result in self.script_results],
            "step_file_sets": [file_set.to_view_model() for file_set in self.step_file_sets],
            "preserved_context_dir": (
                str(self.preserved_context_dir) if self.preserved_context_dir is not None else None
            ),
        }


@dataclass
class ChainRunReport:
    """Aggregated outcome of multi-step file-based chain execution."""

    results: list[ChainFileResult] = field(default_factory=list)
    script_results: list[ChainScriptResult] = field(default_factory=list)
    duration_s: float = 0.0

    @property
    def ok_count(self) -> int:
        return sum(1 for result in self.results if result.status in CHAIN_SUCCESS_STATUSES)

    @property
    def kept_count(self) -> int:
        return sum(1 for result in self.results if result.status == "kept")

    @property
    def removed_count(self) -> int:
        return sum(1 for result in self.results if result.status == "removed")

    @property
    def filtered_count(self) -> int:
        return sum(1 for result in self.results if result.status == "filtered")

    @property
    def copied_count(self) -> int:
        return sum(1 for result in self.results if result.status == "copied")

    @property
    def moved_count(self) -> int:
        return sum(1 for result in self.results if result.status == "moved")

    @property
    def renamed_count(self) -> int:
        return sum(1 for result in self.results if result.status == "renamed")

    @property
    def failed_count(self) -> int:
        return sum(1 for result in self.results if result.status == "failed")

    @property
    def cancelled_count(self) -> int:
        return sum(1 for result in self.results if result.status == "cancelled")

    @property
    def failures(self) -> list[ChainFileResult]:
        return [result for result in self.results if result.status == "failed"]

    @property
    def cancelled(self) -> list[ChainFileResult]:
        return [result for result in self.results if result.status == "cancelled"]

    @property
    def status(self) -> str:
        if self.failed_count:
            return "failed"
        if self.cancelled_count:
            return "cancelled"
        return "ok"

    @property
    def exit_code(self) -> int:
        return min(self.failed_count + self.cancelled_count, 255)

    def to_view_model(self) -> dict[str, Any]:
        return {
            "ok_count": self.ok_count,
            "kept_count": self.kept_count,
            "removed_count": self.removed_count,
            "filtered_count": self.filtered_count,
            "copied_count": self.copied_count,
            "moved_count": self.moved_count,
            "renamed_count": self.renamed_count,
            "failed_count": self.failed_count,
            "cancelled_count": self.cancelled_count,
            "status": self.status,
            "exit_code": self.exit_code,
            "duration_s": self.duration_s,
            "script_results": [result.to_view_model() for result in self.script_results],
            "results": [result.to_view_model() for result in self.results],
        }


@dataclass(frozen=True)
class FileChainExecutionPreparation:
    """Validated, scanned, previewed file-based chain ready for execution."""

    chain_id: str
    chain_name: str
    plan: ChainExecutionPlan
    targets: list[Path] = field(default_factory=list)
    output_policy: ChainOutputPolicy = field(default_factory=ChainOutputPolicy)
    output_preview: list[ChainOutputPreview] = field(default_factory=list)
    validation: ChainValidationResult | None = None
    scan_roots: tuple[Path, ...] = ()

    @property
    def target_count(self) -> int:
        return len(self.targets)

    @property
    def steps(self) -> list[ChainExecutionStep]:
        return list(self.plan.steps)

    def to_view_model(self) -> dict[str, Any]:
        return {
            "chain_id": self.chain_id,
            "chain_name": self.chain_name,
            "plan": self.plan.to_view_model(),
            "target_count": self.target_count,
            "targets": [str(path) for path in self.targets],
            "output_policy": self.output_policy.to_view_model(),
            "output_preview": [preview.to_view_model() for preview in self.output_preview],
            "validation_state": self.validation.to_view_model() if self.validation else None,
            "scan_roots": [str(path) for path in self.scan_roots],
        }


@dataclass(frozen=True)
class FileChainExecutionRun:
    """Result of executing a prepared multi-step file-based chain."""

    preparation: FileChainExecutionPreparation
    report: ChainRunReport

    @property
    def ok_count(self) -> int:
        return self.report.ok_count

    @property
    def kept_count(self) -> int:
        return self.report.kept_count

    @property
    def removed_count(self) -> int:
        return self.report.removed_count

    @property
    def filtered_count(self) -> int:
        return self.report.filtered_count

    @property
    def copied_count(self) -> int:
        return self.report.copied_count

    @property
    def moved_count(self) -> int:
        return self.report.moved_count

    @property
    def renamed_count(self) -> int:
        return self.report.renamed_count

    @property
    def failed_count(self) -> int:
        return self.report.failed_count

    @property
    def cancelled_count(self) -> int:
        return self.report.cancelled_count

    @property
    def exit_code(self) -> int:
        return self.report.exit_code

    def to_view_model(self) -> dict[str, Any]:
        return {
            **self.preparation.to_view_model(),
            "report": self.report.to_view_model(),
        }


def _event_json_safe(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): _event_json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_event_json_safe(item) for item in value]
    return value


ChainExecutionReport = ChainRunReport
ChainExecutionResult = ChainFileResult
ChainExecutionPreparation = FileChainExecutionPreparation
ChainExecutionRun = FileChainExecutionRun


__all__ = [
    "CHAIN_FILE_STATUSES",
    "CHAIN_OUTPUT_MODES",
    "CHAIN_SUCCESS_STATUSES",
    "FILE_FILTER_CONFIRMATION_ACTIONS",
    "INTERMEDIATES_DIRNAME",
    "ChainAnalysisResult",
    "ChainEvent",
    "ChainExecutionPreparation",
    "ChainExecutionReport",
    "ChainExecutionResult",
    "ChainExecutionRun",
    "ChainFileResult",
    "ChainOutputPolicy",
    "ChainOutputPreview",
    "ChainRunReport",
    "ChainScriptResult",
    "ChainStepArtifact",
    "ChainStepFileSet",
    "DestructiveConfirmation",
    "FileChainExecutionPreparation",
    "FileChainExecutionRun",
    "NameRegexFileAssessment",
    "NameRegexFilterPreview",
    "OneNodeFilterChainPreparation",
    "OneNodeFilterChainRun",
    "RemoveSilentFileAssessment",
    "RemoveSilentPreview",
]
