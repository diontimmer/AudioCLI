"""GUI-neutral import/export helpers for native chains and .acli scripts."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from audiocli._shell import quote_arg
from audiocli.capabilities import CapabilityNode, get_capability
from audiocli.chains import (
    CapabilityChain,
    ChainNode,
    ChainValidationResult,
    _atomic_write_text,
    load_chain,
    save_chain,
)
from audiocli.gui_service import import_acli_script


@dataclass(frozen=True)
class ImportExportIssue:
    """One exact import/export limitation or diagnostic."""

    code: str
    message: str
    node_id: str = ""
    capability_id: str = ""
    metadata_key: str = ""
    parameter: str = ""

    def to_view_model(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "node_id": self.node_id,
            "capability_id": self.capability_id,
            "metadata_key": self.metadata_key,
            "parameter": self.parameter,
        }


@dataclass(frozen=True)
class ImportResult:
    """Result returned by native/.acli imports."""

    path: Path
    kind: str
    mode: str
    chain: CapabilityChain
    explanation: str
    metadata: dict[str, Any] = field(default_factory=dict)
    issues: list[ImportExportIssue] = field(default_factory=list)
    validation: ChainValidationResult | None = None

    def to_view_model(self) -> dict[str, Any]:
        return {
            "path": str(self.path),
            "kind": self.kind,
            "mode": self.mode,
            "chain": self.chain.to_dict(),
            "explanation": self.explanation,
            "metadata": dict(self.metadata),
            "issues": [issue.to_view_model() for issue in self.issues],
            "validation": self.validation.to_view_model() if self.validation is not None else None,
        }


@dataclass(frozen=True)
class ExportResult:
    """Result returned by native/.acli exports."""

    path: Path
    kind: str
    mode: str
    explanation: str
    metadata: dict[str, Any] = field(default_factory=dict)
    lines: list[str] = field(default_factory=list)
    issues: list[ImportExportIssue] = field(default_factory=list)

    def to_view_model(self) -> dict[str, Any]:
        return {
            "path": str(self.path),
            "kind": self.kind,
            "mode": self.mode,
            "explanation": self.explanation,
            "metadata": dict(self.metadata),
            "lines": list(self.lines),
            "issues": [issue.to_view_model() for issue in self.issues],
        }


class ExportError(ValueError):
    """Raised when a chain cannot be represented as .acli commands."""

    def __init__(self, issues: list[ImportExportIssue]) -> None:
        self.issues = issues
        message = "Cannot export chain to .acli: " + "; ".join(issue.message for issue in issues)
        super().__init__(message)

    def to_view_model(self) -> dict[str, Any]:
        return {
            "message": str(self),
            "issues": [issue.to_view_model() for issue in self.issues],
        }


def export_native_chain(chain: CapabilityChain, path: str | Path) -> ExportResult:
    """Write a native saved-chain file losslessly."""

    destination = save_chain(chain, path)
    metadata = _chain_metadata(chain)
    return ExportResult(
        path=destination,
        kind="native",
        mode="native",
        explanation=(
            f"Exported native AudioCLI chain '{chain.name}' with {len(chain.nodes)} node(s) "
            f"to {destination}."
        ),
        metadata=metadata,
    )


def import_native_chain(
    path: str | Path,
    capability_catalog: Mapping[str, CapabilityNode] | None = None,
) -> ImportResult:
    """Load and validate a native saved-chain file."""

    source = Path(path)
    chain = load_chain(source, capability_catalog=capability_catalog)
    validation = chain.validate()
    if validation.valid:
        explanation = (
            f"Imported native AudioCLI chain '{chain.name}' with {len(chain.nodes)} node(s); "
            "all enabled nodes validate against the current capability catalog."
        )
        issues: list[ImportExportIssue] = []
    else:
        issues = [
            ImportExportIssue(
                code=error.code,
                message=error.message,
                node_id=error.node_id,
                capability_id=error.capability_id,
                parameter=error.parameter,
            )
            for error in validation.errors
        ]
        explanation = (
            f"Imported native AudioCLI chain '{chain.name}' with {len(chain.nodes)} node(s), "
            f"but validation reported {len(issues)} issue(s)."
        )
    return ImportResult(
        path=source,
        kind="native",
        mode="native",
        chain=chain,
        explanation=explanation,
        metadata=_chain_metadata(chain),
        issues=issues,
        validation=validation,
    )


def import_acli_chain(path: str | Path, *, strict: bool = False) -> ImportResult:
    """Import a .acli script as converted native nodes or one script wrapper node."""

    source = Path(path)
    chain = import_acli_script(source, strict=strict)
    wrapped = _is_wrapped_acli_script(chain)
    mode = "wrapped" if wrapped else "converted"
    if wrapped:
        explanation = (
            "Imported .acli as a single builtin.script.acli wrapper node because the script "
            "contains commands, options, parse errors, or I/O behavior that cannot be safely "
            "converted to native GUI nodes. The wrapper preserves script execution behavior."
        )
    else:
        explanation = (
            f"Converted .acli script to {len(chain.nodes)} native built-in filter node(s). "
            "Only simple filter command lines with operation parameters were converted."
        )
    return ImportResult(
        path=source,
        kind="acli",
        mode=mode,
        chain=chain,
        explanation=explanation,
        metadata=_chain_metadata(chain),
    )


def export_chain_to_acli(
    chain: CapabilityChain,
    path: str | Path,
    *,
    targets: Sequence[str | Path] | None = None,
    output: str | Path | None = None,
    recursive: bool = True,
    workers: int | None = None,
) -> ExportResult:
    """Export a simple native GUI chain to a .acli script.

    Only one enabled built-in filter node with scalar CLI-representable parameters can
    be represented, and export requires the execution context needed to make the
    resulting line runnable (at least one target, plus optional output/workers and the
    recursive flag). Unsupported nodes, unsupported metadata, missing context, and
    multi-node chains are reported exactly in :class:`ExportError.issues` and no file
    is written.
    """

    issues: list[ImportExportIssue] = []
    target_values = _normalize_targets(targets)
    output_value = _normalize_optional_path(output)
    issues.extend(_unsupported_chain_metadata(chain))
    issues.extend(_unsupported_execution_context_issues(target_values))
    issues.extend(_unsupported_chain_topology_issues(chain))

    validation = chain.validate()
    if not validation.valid:
        issues.extend(
            ImportExportIssue(
                code=f"validation_{error.code}",
                message=(
                    f"Node '{error.node_id}' ({error.capability_id}) cannot be exported: "
                    f"{error.message}"
                )
                if error.node_id
                else f"Chain cannot be exported: {error.message}",
                node_id=error.node_id,
                capability_id=error.capability_id,
                parameter=error.parameter,
            )
            for error in validation.errors
        )

    lines: list[str] = []
    node_results = validation.node_results
    for node in chain.nodes:
        capability = _resolve_capability(chain, node.capability_id)
        node_issues = _unsupported_node_issues(node, capability)
        issues.extend(node_issues)
        if node_issues or capability is None or not node.enabled:
            continue
        params = node_results.get(node.id, capability.validate_params(node.params)).values
        try:
            lines.append(
                _node_to_acli_line(
                    node,
                    capability,
                    params,
                    targets=target_values,
                    output=output_value,
                    recursive=recursive,
                    workers=workers,
                )
            )
        except ExportError as exc:
            issues.extend(exc.issues)

    if issues:
        raise ExportError(issues)

    destination = Path(path)
    _atomic_write_text(destination, "\n".join(lines) + ("\n" if lines else ""))
    return ExportResult(
        path=destination,
        kind="acli",
        mode="script",
        explanation=(
            f"Exported chain '{chain.name}' as {len(lines)} .acli command line(s) to {destination}."
        ),
        metadata=_chain_metadata(chain)
        | {
            "line_count": len(lines),
            "targets": [str(target) for target in target_values],
            "output": str(output_value) if output_value is not None else "",
            "recursive": bool(recursive),
            "workers": int(workers or 0),
        },
        lines=lines,
    )


def _is_wrapped_acli_script(chain: CapabilityChain) -> bool:
    return len(chain.nodes) == 1 and chain.nodes[0].capability_id == "builtin.script.acli"


def _chain_metadata(chain: CapabilityChain) -> dict[str, Any]:
    return {
        "chain_id": chain.id,
        "chain_name": chain.name,
        "description": chain.description,
        "notes": chain.notes,
        "node_count": len(chain.nodes),
        "enabled_node_count": sum(1 for node in chain.nodes if node.enabled),
        "output_policy": dict(chain.output_policy),
    }


def _unsupported_chain_metadata(chain: CapabilityChain) -> list[ImportExportIssue]:
    issues: list[ImportExportIssue] = []
    if chain.description:
        issues.append(
            ImportExportIssue(
                code="unsupported_chain_metadata",
                metadata_key="description",
                message="Chain description metadata cannot be represented in .acli commands.",
            )
        )
    if chain.notes:
        issues.append(
            ImportExportIssue(
                code="unsupported_chain_metadata",
                metadata_key="notes",
                message="Chain notes metadata cannot be represented in .acli commands.",
            )
        )
    if chain.output_policy:
        issues.append(
            ImportExportIssue(
                code="unsupported_chain_metadata",
                metadata_key="output_policy",
                message=f"Chain output_policy metadata cannot be represented in .acli: {chain.output_policy!r}.",
            )
        )
    return issues


def _normalize_targets(targets: Sequence[str | Path] | None) -> list[Path]:
    if targets is None:
        return []
    return [Path(target) for target in targets if str(target)]


def _normalize_optional_path(path: str | Path | None) -> Path | None:
    if path is None or str(path) == "":
        return None
    return Path(path)


def _unsupported_execution_context_issues(targets: Sequence[Path]) -> list[ImportExportIssue]:
    if targets:
        return []
    return [
        ImportExportIssue(
            code="missing_target_context",
            message=(
                "Target metadata cannot be represented by the chain alone; select at least "
                "one target before exporting an executable .acli script."
            ),
        )
    ]


def _unsupported_chain_topology_issues(chain: CapabilityChain) -> list[ImportExportIssue]:
    if len(chain.nodes) == 1:
        return []
    if not chain.nodes:
        message = "A .acli export requires exactly one executable built-in filter node."
    else:
        message = (
            "Multi-node managed chains cannot be represented as a simple executable .acli "
            "script without an explicit intermediate temporary-path plan. Export a native "
            "saved chain instead."
        )
    return [
        ImportExportIssue(
            code="unsupported_chain_topology",
            message=message,
        )
    ]


def _unsupported_node_issues(
    node: ChainNode, capability: CapabilityNode | None
) -> list[ImportExportIssue]:
    issues: list[ImportExportIssue] = []
    if not node.enabled:
        issues.append(
            ImportExportIssue(
                code="unsupported_disabled_node",
                node_id=node.id,
                capability_id=node.capability_id,
                message=(
                    f"Node '{node.id}' ({node.capability_id}) is disabled; .acli has no disabled-node metadata."
                ),
            )
        )
    if node.notes:
        issues.append(
            ImportExportIssue(
                code="unsupported_node_metadata",
                node_id=node.id,
                capability_id=node.capability_id,
                metadata_key="notes",
                message=f"Node '{node.id}' notes metadata cannot be represented in .acli commands.",
            )
        )
    if node.output_policy:
        issues.append(
            ImportExportIssue(
                code="unsupported_node_metadata",
                node_id=node.id,
                capability_id=node.capability_id,
                metadata_key="output_policy",
                message=(
                    f"Node '{node.id}' output_policy metadata cannot be represented in .acli: "
                    f"{node.output_policy!r}."
                ),
            )
        )
    if capability is None:
        issues.append(
            ImportExportIssue(
                code="unknown_capability",
                node_id=node.id,
                capability_id=node.capability_id,
                message=f"Node '{node.id}' references unknown capability '{node.capability_id}'.",
            )
        )
        return issues
    if capability.type != "built_in_filter":
        issues.append(
            ImportExportIssue(
                code="unsupported_capability_type",
                node_id=node.id,
                capability_id=node.capability_id,
                message=(
                    f"Node '{node.id}' ({node.capability_id}) has type '{capability.type}', "
                    "not .acli-exportable built_in_filter."
                ),
            )
        )
    if not capability.operation_name:
        issues.append(
            ImportExportIssue(
                code="missing_operation_name",
                node_id=node.id,
                capability_id=node.capability_id,
                message=(
                    f"Node '{node.id}' ({node.capability_id}) has no CLI operation_name to write."
                ),
            )
        )
    return issues


def _node_to_acli_line(
    node: ChainNode,
    capability: CapabilityNode,
    params: Mapping[str, Any],
    *,
    targets: Sequence[Path],
    output: Path | None,
    recursive: bool,
    workers: int | None,
) -> str:
    parts = [quote_arg(capability.operation_name)]
    for target in targets:
        parts.extend(["--target", quote_arg(str(target))])
    known_order = [parameter.name for parameter in capability.parameters]
    ordered_names = [name for name in known_order if name in params]
    ordered_names.extend(sorted(name for name in params if name not in set(known_order)))
    for name in ordered_names:
        value = params[name]
        if value is None:
            continue
        option = "--" + name.replace("_", "-")
        if isinstance(value, bool):
            parts.append(option if value else "--no-" + name.replace("_", "-"))
            continue
        if not _is_acli_scalar(value):
            raise ExportError(
                [
                    ImportExportIssue(
                        code="unsupported_parameter_value",
                        node_id=node.id,
                        capability_id=node.capability_id,
                        parameter=name,
                        message=(
                            f"Node '{node.id}' ({node.capability_id}) parameter '{name}' has "
                            f"unsupported .acli value {type(value).__name__}: {value!r}."
                        ),
                    )
                ]
            )
        parts.extend([option, quote_arg(str(value))])
    if output is not None:
        parts.extend(["--output", quote_arg(str(output))])
    if workers is not None and workers > 0:
        parts.extend(["--workers", str(int(workers))])
    parts.append("--recursive" if recursive else "--no-recursive")
    return " ".join(parts)


def _is_acli_scalar(value: Any) -> bool:
    if isinstance(value, bool):
        return True
    if isinstance(value, int):
        return True
    if isinstance(value, float):
        return math.isfinite(value)
    return isinstance(value, str | Path)


def _resolve_capability(chain: CapabilityChain, capability_id: str) -> CapabilityNode | None:
    if chain.capability_catalog is not None:
        capability = chain.capability_catalog.get(capability_id)
        if capability is not None:
            return capability
        for candidate in chain.capability_catalog.values():
            if candidate.operation_name == capability_id:
                return candidate
        return None
    try:
        return get_capability(capability_id, include_plugins=chain.include_plugins)
    except KeyError:
        return None


__all__ = [
    "ExportError",
    "ExportResult",
    "ImportExportIssue",
    "ImportResult",
    "export_chain_to_acli",
    "export_native_chain",
    "import_acli_chain",
    "import_native_chain",
]
