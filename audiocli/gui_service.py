"""GUI-neutral service helpers for running simple capability chains.

This module is intentionally below the Typer adapter layer.  It reuses the
same scanner, destination policy, registry lookup, and per-file pipeline that
the CLI uses, but returns dataclasses/view models that a desktop GUI or other
library caller can consume directly.
"""

from __future__ import annotations

import re
import shlex
import shutil
import tempfile
import time
import uuid
from collections.abc import Iterable, Mapping
from contextlib import suppress
from pathlib import Path
from threading import Event
from typing import Any

from audiocli.analysis import compute_info
from audiocli.capabilities import CapabilityNode, get_capability, list_capabilities
from audiocli.chains import (
    CapabilityChain,
    ChainExecutionPlan,
    ChainExecutionStep,
    ChainValidationResult,
)
from audiocli.chunking import chunk_buffer
from audiocli.destinations import (
    predict_output_extension,
    predict_output_format,
    resolve_output_preview,
    rewrite_output_extension,
)
from audiocli.errors import AudioCLIError
from audiocli.events import EventCallback
from audiocli.file_chains.models import (
    CHAIN_FILE_STATUSES,
    CHAIN_OUTPUT_MODES,
    CHAIN_SUCCESS_STATUSES,
    FILE_FILTER_CONFIRMATION_ACTIONS,
    INTERMEDIATES_DIRNAME,
    ChainAnalysisResult,
    ChainEvent,
    ChainExecutionPreparation,
    ChainExecutionReport,
    ChainExecutionResult,
    ChainExecutionRun,
    ChainFileResult,
    ChainOutputPolicy,
    ChainOutputPreview,
    ChainRunReport,
    ChainScriptResult,
    ChainStepArtifact,
    ChainStepFileSet,
    DestructiveConfirmation,
    FileChainExecutionPreparation,
    FileChainExecutionRun,
    NameRegexFileAssessment,
    NameRegexFilterPreview,
    OneNodeFilterChainPreparation,
    OneNodeFilterChainRun,
    RemoveSilentFileAssessment,
    RemoveSilentPreview,
)
from audiocli.io import load, save
from audiocli.pipeline import JobReport, Result, run_per_file
from audiocli.registry import get_op
from audiocli.scanner import scan_targets
from audiocli.silence import is_silent


def build_one_node_filter_chain(
    capability: CapabilityNode | str,
    params: Mapping[str, Any] | None = None,
    *,
    chain_id: str | None = None,
    chain_name: str = "Untitled Chain",
    node_id: str | None = None,
    include_plugins: bool = False,
    capability_catalog: Mapping[str, CapabilityNode] | None = None,
) -> CapabilityChain:
    """Create a chain containing one enabled capability node.

    ``capability`` may be a discovered :class:`CapabilityNode` from
    :func:`audiocli.capabilities.list_capabilities` or its stable id/name.
    Execution-time validation still goes through :class:`CapabilityChain` so
    the caller gets the same parameter coercion and structured errors as the
    editor model.
    """

    capability_id = capability.id if isinstance(capability, CapabilityNode) else str(capability)
    kwargs: dict[str, Any] = {
        "name": chain_name,
        "include_plugins": include_plugins,
        "capability_catalog": capability_catalog,
    }
    if chain_id is not None:
        kwargs["id"] = chain_id
    chain = CapabilityChain(**kwargs)
    chain.add_node(capability_id, params or {}, node_id=node_id)
    return chain


def prepare_one_node_filter_chain(
    chain: CapabilityChain,
    targets: Iterable[str | Path],
    *,
    output: str | Path | None = None,
    recursive: bool = True,
    extensions: Iterable[str] | None = None,
    include_hidden: bool = False,
    follow_symlinks: bool = False,
) -> OneNodeFilterChainPreparation:
    """Validate a one-node chain, scan targets, and preview output paths.

    This mirrors the CLI's target scanning and destination semantics while
    avoiding any audio load/DSP/save work.  Unlike
    :func:`audiocli.destinations.resolve_output`, the shared preview resolver
    is non-mutating: a suffixless, not-yet-existing output path is treated as
    an output directory but is not created until execution. Existing
    suffixless non-directory files still raise the same conflict execution
    would hit.
    """

    validation, step = _validated_single_step(chain)
    target_list = [Path(t) for t in targets]
    scanned = scan_targets(
        target_list,
        recursive=recursive,
        extensions=extensions,
        include_hidden=include_hidden,
        follow_symlinks=follow_symlinks,
    )
    if not scanned:
        raise AudioCLIError("no audio files matched the targets")

    scan_roots = _scan_roots_from_targets(target_list)
    output_path = Path(output) if output is not None else None
    previews = preview_output_paths(scanned, step, output=output_path, scan_roots=scan_roots)
    return OneNodeFilterChainPreparation(
        chain_id=chain.id,
        chain_name=chain.name,
        step=step,
        targets=scanned,
        output_preview=previews,
        validation=validation,
        scan_roots=scan_roots,
    )


def execute_one_node_filter_chain(
    chain: CapabilityChain,
    targets: Iterable[str | Path],
    *,
    output: str | Path | None = None,
    workers: int | None = None,
    recursive: bool = True,
    extensions: Iterable[str] | None = None,
    include_hidden: bool = False,
    follow_symlinks: bool = False,
    on_event: EventCallback | None = None,
    cancel_token: Event | None = None,
) -> OneNodeFilterChainRun:
    """Run a validated one-node filter chain through AudioCLI's pipeline.

    Per-file load/op/save failures are reported in the returned
    :class:`JobReport` and do not stop unrelated files, matching CLI batch
    behaviour.  Pre-execution problems such as invalid chain shape, unknown
    capability, missing targets, or an empty scan raise :class:`AudioCLIError`.
    """

    preparation = prepare_one_node_filter_chain(
        chain,
        targets,
        output=output,
        recursive=recursive,
        extensions=extensions,
        include_hidden=include_hidden,
        follow_symlinks=follow_symlinks,
    )
    try:
        op = (
            _load_hook_op(preparation.step)
            if _is_hook_step(preparation.step)
            else get_op(preparation.step.operation_name)
        )
    except Exception as e:
        report = _structured_one_node_setup_failure(preparation.targets, e, on_event=on_event)
        return OneNodeFilterChainRun(preparation=preparation, report=report)

    params = (
        _hook_step_kwargs(preparation.step)
        if _is_hook_step(preparation.step)
        else preparation.step.params
    )
    report = run_per_file(
        preparation.targets,
        op,
        params,
        output=output,
        workers=workers,
        on_event=on_event,
        cancel_token=cancel_token,
    )
    return OneNodeFilterChainRun(preparation=preparation, report=report)


def prepare_file_chain_execution(
    chain: CapabilityChain,
    targets: Iterable[str | Path],
    *,
    output_policy: Mapping[str, Any] | ChainOutputPolicy | None = None,
    output: str | Path | None = None,
    mode: str | None = None,
    destructive_confirmation: DestructiveConfirmation | Mapping[str, Any] | None = None,
    recursive: bool = True,
    extensions: Iterable[str] | None = None,
    include_hidden: bool = False,
    follow_symlinks: bool = False,
) -> FileChainExecutionPreparation:
    """Validate, scan, and preview a multi-step file-based chain execution.

    ``output_policy`` accepts the issue-05 dict shape
    ``{"mode": "final_only"|"keep_intermediates"|"destructive", "output": path}``.
    ``final_only`` is the default.  ``destructive`` refuses to proceed unless
    an explicit confirmation object/dict with ``confirmed=True`` is supplied.
    """

    policy = _normalize_output_policy(output_policy, output=output, mode=mode)
    if policy.mode == "destructive" and not _confirmation_is_confirmed(destructive_confirmation):
        raise AudioCLIError("destructive chain execution requires explicit confirmation")

    validation, plan = _validated_execution_plan(chain)
    target_list = [Path(t) for t in targets]
    scanned = scan_targets(
        target_list,
        recursive=recursive,
        extensions=extensions,
        include_hidden=include_hidden,
        follow_symlinks=follow_symlinks,
    )
    if not scanned:
        raise AudioCLIError("no audio files matched the targets")

    if policy.mode == "destructive":
        _verify_destructive_affected_paths(scanned, destructive_confirmation)

    scan_roots = _scan_roots_from_targets(target_list)
    previews = preview_chain_output_paths(
        scanned,
        plan,
        output_policy=policy,
        destructive_confirmation=destructive_confirmation,
        scan_roots=scan_roots,
    )
    return FileChainExecutionPreparation(
        chain_id=chain.id,
        chain_name=chain.name,
        plan=plan,
        targets=scanned,
        scan_roots=scan_roots,
        output_policy=policy,
        output_preview=previews,
        validation=validation,
    )


def execute_file_chain(
    chain: CapabilityChain,
    targets: Iterable[str | Path],
    *,
    output_policy: Mapping[str, Any] | ChainOutputPolicy | None = None,
    output: str | Path | None = None,
    mode: str | None = None,
    destructive_confirmation: DestructiveConfirmation | Mapping[str, Any] | None = None,
    recursive: bool = True,
    extensions: Iterable[str] | None = None,
    include_hidden: bool = False,
    follow_symlinks: bool = False,
    on_event: EventCallback | None = None,
    cancel_token: Event | None = None,
) -> FileChainExecutionRun:
    """Execute an ordered chain over real files using file intermediates.

    Each source file is isolated: load/op/save failures for one file or step
    are returned as failed results and do not stop unrelated files.  Successful
    ``final_only`` temp intermediates are cleaned; failed ``final_only`` runs
    leave their per-file temp directory and report its path for diagnosis.
    """

    preparation = prepare_file_chain_execution(
        chain,
        targets,
        output_policy=output_policy,
        output=output,
        mode=mode,
        destructive_confirmation=destructive_confirmation,
        recursive=recursive,
        extensions=extensions,
        include_hidden=include_hidden,
        follow_symlinks=follow_symlinks,
    )
    if _has_destructive_filter_step(preparation.plan.steps):
        if not _confirmation_is_confirmed(destructive_confirmation):
            raise AudioCLIError(
                "name-regex/remove-silent destructive filtering requires explicit confirmation; "
                "run a destructive dry-run preview first and confirm affected paths"
            )
        if any(
            _file_filter_requires_confirmation(step) and _is_remove_silent_step(step)
            for step in preparation.plan.steps
        ):
            remove_preview = _preview_remove_silent_for_confirmation(preparation)
            _verify_remove_silent_affected_paths(
                remove_preview.affected_paths,
                destructive_confirmation,
            )
        if any(
            _file_filter_requires_confirmation(step) and _is_name_regex_filter_step(step)
            for step in preparation.plan.steps
        ):
            name_preview = _preview_name_regex_for_confirmation(preparation)
            _verify_name_regex_affected_paths(
                name_preview.affected_paths,
                destructive_confirmation,
            )

    report = ChainRunReport()
    start = time.perf_counter()
    total = len(preparation.targets)
    run_id = f"run-{uuid.uuid4().hex}"
    node_count = len(preparation.plan.steps)
    _emit_chain_event(
        on_event,
        ChainEvent(
            "chain_start",
            chain_id=preparation.chain_id,
            chain_name=preparation.chain_name,
            run_id=run_id,
            status="running",
            total_files=total,
            total=total,
            node_count=node_count,
            workers=1,
        ),
    )

    job_script_failure: ChainScriptResult | None = None
    job_script_results = _execute_job_script_steps(
        preparation.plan.steps,
        chain_id=preparation.chain_id,
        chain_name=preparation.chain_name,
        run_id=run_id,
        node_count=node_count,
        on_event=on_event,
        cancel_token=cancel_token,
    )
    report.script_results.extend(job_script_results)
    for script_result in job_script_results:
        if not script_result.ok:
            job_script_failure = script_result
            break

    for index, source in enumerate(preparation.targets, start=1):
        if _cancel_requested(cancel_token):
            result = ChainFileResult(
                source_path=source,
                path=source,
                ok=False,
                error="cancelled",
                status="cancelled",
            )
            _emit_chain_event(
                on_event,
                ChainEvent(
                    "cancellation",
                    chain_id=preparation.chain_id,
                    chain_name=preparation.chain_name,
                    run_id=run_id,
                    status="cancelled",
                    scope="file",
                    file_index=index,
                    total_files=total,
                    source_path=str(source),
                    path=str(source),
                    reason="cancelled before file start",
                ),
            )
        elif job_script_failure is not None:
            result = ChainFileResult(
                source_path=source,
                path=source,
                ok=False,
                error=job_script_failure.error,
                status="failed",
                failed_step_index=job_script_failure.step_index,
                failed_step=job_script_failure.step,
            )
        else:
            result = _execute_chain_for_file(
                source,
                preparation.plan,
                preparation.output_policy,
                chain_id=preparation.chain_id,
                chain_name=preparation.chain_name,
                run_id=run_id,
                file_index=index,
                total_files=total,
                on_event=on_event,
                cancel_token=cancel_token,
                skip_job_script_steps=True,
                scan_roots=preparation.scan_roots,
            )
        report.results.append(result)
        _emit_file_completion_events(
            on_event,
            result,
            preparation=preparation,
            run_id=run_id,
            file_index=index,
            done=len(report.results),
            total=total,
            report=report,
        )

    report.duration_s = time.perf_counter() - start
    _emit_chain_event(
        on_event,
        ChainEvent(
            "chain_done",
            chain_id=preparation.chain_id,
            chain_name=preparation.chain_name,
            run_id=run_id,
            status=report.status,
            total_files=total,
            total=total,
            done=len(report.results),
            ok_count=report.ok_count,
            kept_count=report.kept_count,
            removed_count=report.removed_count,
            filtered_count=report.filtered_count,
            copied_count=report.copied_count,
            moved_count=report.moved_count,
            renamed_count=report.renamed_count,
            failed_count=report.failed_count,
            cancelled_count=report.cancelled_count,
            duration_s=report.duration_s,
        ),
    )
    return FileChainExecutionRun(preparation=preparation, report=report)


def preview_remove_silent(
    chain: CapabilityChain,
    targets: Iterable[str | Path],
    *,
    recursive: bool = True,
    extensions: Iterable[str] | None = None,
    include_hidden: bool = False,
    follow_symlinks: bool = False,
    cancel_token: Event | None = None,
) -> RemoveSilentPreview:
    """Dry-run a guarded remove-silent node without deleting anything.

    The returned summary is suitable for an explicit
    :class:`DestructiveConfirmation`: pass ``preview.affected_paths`` as the
    confirmation's affected paths before calling :func:`execute_file_chain`.
    """

    preparation = prepare_file_chain_execution(
        chain,
        targets,
        recursive=recursive,
        extensions=extensions,
        include_hidden=include_hidden,
        follow_symlinks=follow_symlinks,
    )
    return _preview_remove_silent_at_chain_node(
        preparation,
        cancel_token=cancel_token,
    )


def dry_run_remove_silent_chain(*args: Any, **kwargs: Any) -> RemoveSilentPreview:
    """Alias for :func:`preview_remove_silent`."""

    return preview_remove_silent(*args, **kwargs)


def preview_name_regex_filter(
    chain: CapabilityChain,
    targets: Iterable[str | Path],
    *,
    recursive: bool = True,
    extensions: Iterable[str] | None = None,
    include_hidden: bool = False,
    follow_symlinks: bool = False,
    cancel_token: Event | None = None,
) -> NameRegexFilterPreview:
    """Dry-run a guarded filename-regex destructive filter without deleting anything."""

    preparation = prepare_file_chain_execution(
        chain,
        targets,
        recursive=recursive,
        extensions=extensions,
        include_hidden=include_hidden,
        follow_symlinks=follow_symlinks,
    )
    return _preview_name_regex_at_chain_node(preparation, cancel_token=cancel_token)


def dry_run_name_regex_filter_chain(*args: Any, **kwargs: Any) -> NameRegexFilterPreview:
    """Alias for :func:`preview_name_regex_filter`."""

    return preview_name_regex_filter(*args, **kwargs)


def preview_chain_output_paths(
    targets: Iterable[str | Path],
    plan: ChainExecutionPlan,
    *,
    output_policy: Mapping[str, Any] | ChainOutputPolicy | None = None,
    output: str | Path | None = None,
    mode: str | None = None,
    destructive_confirmation: DestructiveConfirmation | Mapping[str, Any] | None = None,
    scan_roots: Iterable[Path] = (),
) -> list[ChainOutputPreview]:
    """Preview final destinations for a file-based chain without running DSP."""

    policy = _normalize_output_policy(output_policy, output=output, mode=mode)
    if policy.mode == "destructive" and not _confirmation_is_confirmed(destructive_confirmation):
        raise AudioCLIError("destructive chain execution requires explicit confirmation")
    target_paths = [Path(target) for target in targets]
    _reject_multi_target_exact_output(policy, target_paths)
    _reject_unsupported_multi_output_policy(policy, plan.steps)
    if policy.mode == "destructive":
        _verify_destructive_affected_paths(target_paths, destructive_confirmation)
    if not plan.steps:
        raise AudioCLIError("chain execution requires at least one enabled node")
    final_step = _final_materializing_step(plan.steps)
    if final_step is None:
        if policy.mode == "destructive":
            return [
                ChainOutputPreview(source_path=target, output_path=target)
                for target in target_paths
            ]
        return [
            ChainOutputPreview(source_path=target, output_path=target) for target in target_paths
        ]
    if policy.mode == "destructive":
        _reject_destructive_format_changing_final_step(target_paths, final_step)
        return [
            ChainOutputPreview(source_path=target, output_path=target) for target in target_paths
        ]
    roots = tuple(scan_roots)
    return [
        ChainOutputPreview(
            source_path=target,
            output_path=_preview_output_path(
                target, policy.output, final_step, scan_roots=roots
            ),
        )
        for target in target_paths
    ]


def prepare_chain_execution(*args: Any, **kwargs: Any) -> FileChainExecutionPreparation:
    """Alias for :func:`prepare_file_chain_execution`."""

    return prepare_file_chain_execution(*args, **kwargs)


def execute_chain(*args: Any, **kwargs: Any) -> FileChainExecutionRun:
    """Alias for :func:`execute_file_chain`."""

    return execute_file_chain(*args, **kwargs)


def preview_output_paths(
    targets: Iterable[str | Path],
    step: ChainExecutionStep,
    *,
    output: str | Path | None = None,
    scan_roots: Iterable[Path] = (),
) -> list[ChainOutputPreview]:
    """Preview destination paths for one execution step without running audio DSP."""

    raw_output = str(output) if output is not None else None
    roots = tuple(scan_roots)
    previews: list[ChainOutputPreview] = []
    for target in targets:
        src = Path(target)
        if raw_output is not None:
            expanded = expand_path_placeholders(raw_output, src, scan_roots=roots)
            out = Path(expanded)
        else:
            out = None
        previews.append(
            ChainOutputPreview(
                source_path=src,
                output_path=_preview_output_path(src, out, step, scan_roots=roots),
            )
        )
    return previews


def import_acli_script(
    path: str | Path,
    *,
    strict: bool = False,
    chain_id: str | None = None,
    chain_name: str | None = None,
) -> CapabilityChain:
    """Import a .acli script as a native chain when safely recognizable.

    Simple lines that name built-in filter capabilities with only operation
    parameters (for example ``gain --db 3``) are converted to native nodes.
    Any unsupported command, I/O option, parse error, or invalid parameter set
    returns a single wrapper ``builtin.script.acli`` node instead so existing
    script behavior is preserved.
    """

    script_path = Path(path)
    name = chain_name or f"Script: {script_path.stem}"
    chain_kwargs: dict[str, Any] = {"name": name}
    if chain_id is not None:
        chain_kwargs["id"] = chain_id

    try:
        from audiocli.run_script import parse_script  # noqa: PLC0415

        lines = parse_script(script_path)
    except Exception:
        return _wrapped_acli_script_chain(script_path, strict=strict, **chain_kwargs)

    if not lines:
        return _wrapped_acli_script_chain(script_path, strict=strict, **chain_kwargs)

    chain = CapabilityChain(**chain_kwargs)
    for lineno, line in lines:
        converted = _convert_acli_line_to_native_node(line)
        if converted is None:
            return _wrapped_acli_script_chain(script_path, strict=strict, **chain_kwargs)
        capability_id, params = converted
        chain.add_node(
            capability_id, params, node_id=f"line-{lineno}-{_safe_node_id_part(capability_id)}"
        )

    return chain


def convert_acli_script_to_chain(*args: Any, **kwargs: Any) -> CapabilityChain:
    """Alias for :func:`import_acli_script`."""

    return import_acli_script(*args, **kwargs)


def _wrapped_acli_script_chain(
    script_path: Path,
    *,
    strict: bool,
    name: str,
    id: str | None = None,
) -> CapabilityChain:
    kwargs: dict[str, Any] = {"name": name}
    if id is not None:
        kwargs["id"] = id
    chain = CapabilityChain(**kwargs)
    chain.add_node(
        "builtin.script.acli",
        {"script_path": str(script_path), "strict": strict},
        node_id="script-1",
    )
    return chain


def _convert_acli_line_to_native_node(line: str) -> tuple[str, dict[str, Any]] | None:
    try:
        tokens = shlex.split(line)
    except ValueError:
        return None
    if not tokens:
        return None

    command = tokens[0]
    if command in {"hook", "run-script", "info", "remove-silent", "chunk", "shell"}:
        return None
    try:
        capability = get_capability(command)
    except KeyError:
        capability = _capability_by_operation_name(command)
    if capability is None or capability.type != "built_in_filter":
        return None

    params = _parse_simple_cli_options(tokens[1:], capability=capability)
    if params is None:
        return None
    validation = capability.validate_params(params)
    if not validation.valid:
        return None
    return capability.id, validation.values


def _capability_by_operation_name(command: str) -> CapabilityNode | None:
    for capability in list_capabilities():
        if capability.operation_name == command:
            return capability
    return None


def _parse_simple_cli_options(
    tokens: list[str], *, capability: CapabilityNode
) -> dict[str, Any] | None:
    params: dict[str, Any] = {}
    bool_params = {param.name for param in capability.parameters if param.type == "bool"}
    blocked = {"target", "output", "workers", "recursive", "json"}
    i = 0
    while i < len(tokens):
        token = tokens[i]
        if not token.startswith("--"):
            return None
        body = token[2:]
        if not body:
            return None
        if "=" in body:
            key, raw_value = body.split("=", 1)
            i += 1
        else:
            key = body
            raw_value: Any
            if key.startswith("no-") and key[3:].replace("-", "_") in bool_params:
                key = key[3:]
                raw_value = False
                i += 1
            elif i + 1 < len(tokens) and not tokens[i + 1].startswith("--"):
                raw_value = tokens[i + 1]
                i += 2
            else:
                raw_value = True
                i += 1
        normalized_key = key.replace("-", "_")
        if normalized_key in blocked:
            return None
        params[normalized_key] = raw_value
    return params


def _safe_node_id_part(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in {"-", "_"} else "-" for ch in value)[-48:]


def _validated_single_step(
    chain: CapabilityChain,
) -> tuple[ChainValidationResult, ChainExecutionStep]:
    validation = chain.validate()
    if not validation.valid:
        codes = ", ".join(error.code for error in validation.errors)
        raise AudioCLIError(f"invalid chain: {codes}")

    plan = chain.to_execution_plan(validate=True)
    if len(plan.steps) != 1:
        raise AudioCLIError(
            f"one-node filter execution requires exactly one enabled node; got {len(plan.steps)}"
        )
    step = plan.steps[0]
    if not step.operation_name:
        raise AudioCLIError(f"chain node {step.node_id!r} has no operation to execute")
    return validation, step


def _preview_output_path(
    src: Path,
    output: Path | None,
    step: ChainExecutionStep,
    *,
    scan_roots: Iterable[Path] = (),
) -> Path:
    if output is not None and "{" in str(output):
        expanded = expand_path_placeholders(str(output), src, scan_roots=scan_roots)
        output = Path(expanded)
    dst = _resolve_output_preview(src, output, step.operation_name)
    predicted_format = predict_output_format(src, step.operation_name, step.params)
    return rewrite_output_extension(dst, predicted_format)


def _is_analysis_step(step: ChainExecutionStep) -> bool:
    return step.capability_id == "builtin.analysis.info" or step.capability_id.startswith(
        "builtin.analysis."
    )


def _is_hook_step(step: ChainExecutionStep) -> bool:
    return step.capability_id == "builtin.external_script.hook"


def _is_acli_script_step(step: ChainExecutionStep) -> bool:
    return step.capability_id == "builtin.script.acli"


def _is_pass_through_step(step: ChainExecutionStep) -> bool:
    return (
        _is_analysis_step(step) or _is_destructive_filter_step(step) or _is_acli_script_step(step)
    )


def _is_chunk_step(step: ChainExecutionStep) -> bool:
    return step.capability_id == "builtin.multi_output.chunk" or step.operation_name == "chunk"


def _is_remove_silent_step(step: ChainExecutionStep) -> bool:
    return (
        step.capability_id
        in {"builtin.file_filter.remove_silent", "builtin.destructive.remove_silent"}
        or step.operation_name == "remove_silent"
    )


def _is_name_regex_filter_step(step: ChainExecutionStep) -> bool:
    return (
        step.capability_id in {"builtin.file_filter.name_regex", "builtin.destructive.name_regex"}
        or step.operation_name == "name_regex_filter"
    )


def _is_destructive_filter_step(step: ChainExecutionStep) -> bool:
    return _is_remove_silent_step(step) or _is_name_regex_filter_step(step)


def _file_filter_action(step: ChainExecutionStep) -> str:
    return str(step.params.get("action") or "skip").strip().lower()


def _file_filter_requires_confirmation(step: ChainExecutionStep) -> bool:
    return (
        _is_destructive_filter_step(step)
        and _file_filter_action(step) in FILE_FILTER_CONFIRMATION_ACTIONS
    )


def _has_remove_silent_step(steps: Iterable[ChainExecutionStep]) -> bool:
    return any(_is_remove_silent_step(step) for step in steps)


def _has_name_regex_filter_step(steps: Iterable[ChainExecutionStep]) -> bool:
    return any(_is_name_regex_filter_step(step) for step in steps)


def _has_destructive_filter_step(steps: Iterable[ChainExecutionStep]) -> bool:
    return any(_file_filter_requires_confirmation(step) for step in steps)


def _has_multi_output_step(steps: Iterable[ChainExecutionStep]) -> bool:
    return any(_is_chunk_step(step) for step in steps)


def _final_materializing_step(steps: Iterable[ChainExecutionStep]) -> ChainExecutionStep | None:
    final_step: ChainExecutionStep | None = None
    for step in steps:
        if not _is_pass_through_step(step):
            final_step = step
    return final_step


def _is_final_materializing_step(
    steps: list[ChainExecutionStep], step_index: int, step: ChainExecutionStep
) -> bool:
    if _is_pass_through_step(step):
        return False
    return all(_is_pass_through_step(later) for later in steps[step_index:])


def _resolve_output_preview(src: Path, output: Path | None, op_name: str) -> Path:
    """Non-mutating preview equivalent of :func:`resolve_output` returns."""
    return resolve_output_preview(src, output, op_name)


def _validated_execution_plan(
    chain: CapabilityChain,
) -> tuple[ChainValidationResult, ChainExecutionPlan]:
    validation = chain.validate()
    if not validation.valid:
        codes = ", ".join(error.code for error in validation.errors)
        raise AudioCLIError(f"invalid chain: {codes}")

    try:
        plan = chain.to_execution_plan(validate=True)
    except ValueError as e:
        raise AudioCLIError(str(e)) from e
    if not plan.steps:
        raise AudioCLIError("chain execution requires at least one enabled node")
    for step in plan.steps:
        if not step.operation_name:
            raise AudioCLIError(f"chain node {step.node_id!r} has no operation to execute")
    return validation, plan


def _normalize_output_policy(
    output_policy: Mapping[str, Any] | ChainOutputPolicy | None,
    *,
    output: str | Path | None = None,
    mode: str | None = None,
) -> ChainOutputPolicy:
    if isinstance(output_policy, ChainOutputPolicy):
        policy_mode = output_policy.mode
        policy_output = output_policy.output
    else:
        data = dict(output_policy or {})
        policy_mode = str(data.get("mode") or "final_only")
        policy_output = data.get("output")

    if mode is not None:
        policy_mode = str(mode)
    if output is not None:
        policy_output = output

    policy_mode = policy_mode.lower()
    if policy_mode not in CHAIN_OUTPUT_MODES:
        raise AudioCLIError(
            f"unsupported chain output mode {policy_mode!r}; expected one of "
            f"{', '.join(sorted(CHAIN_OUTPUT_MODES))}"
        )
    return ChainOutputPolicy(
        mode=policy_mode,
        output=Path(policy_output) if policy_output is not None else None,
    )


def _reject_multi_target_exact_output(policy: ChainOutputPolicy, targets: list[Path]) -> None:
    if policy.mode == "destructive" or policy.output is None or len(targets) <= 1:
        return
    if policy.output.suffix and not policy.output.is_dir():
        raise AudioCLIError(
            "exact output file cannot be used with multiple targets; "
            "choose an output directory or run one target at a time"
        )


def _reject_unsupported_multi_output_policy(
    policy: ChainOutputPolicy, steps: Iterable[ChainExecutionStep]
) -> None:
    if not _has_multi_output_step(steps):
        return
    if policy.mode == "destructive":
        raise AudioCLIError("destructive chain execution does not support multi-output chunk nodes")
    if policy.output is not None and policy.output.suffix and not policy.output.is_dir():
        raise AudioCLIError(
            "exact output file cannot be used with multi-output chunk nodes; "
            "choose an output directory"
        )


def _reject_destructive_format_changing_final_step(
    targets: Iterable[Path],
    final_step: ChainExecutionStep,
) -> None:
    """Reject destructive chains whose final save would rewrite the source suffix."""
    for target in targets:
        predicted_extension = predict_output_extension(
            target,
            final_step.operation_name,
            final_step.params,
        )
        if predicted_extension is None:
            continue
        if predicted_extension.lower() != target.suffix.lower():
            raise AudioCLIError(
                "destructive chain execution cannot use a format-changing final step; "
                f"final step {final_step.operation_name!r} would write {target.with_suffix(predicted_extension)} "
                f"instead of overwriting {target}"
            )


def _confirmation_is_confirmed(
    confirmation: DestructiveConfirmation | Mapping[str, Any] | None,
) -> bool:
    if confirmation is None:
        return False
    if isinstance(confirmation, DestructiveConfirmation):
        return bool(confirmation.confirmed)
    return bool(confirmation.get("confirmed", False))


def _confirmation_affected_paths(
    confirmation: DestructiveConfirmation | Mapping[str, Any] | None,
) -> list[Path]:
    if confirmation is None:
        return []
    if isinstance(confirmation, DestructiveConfirmation):
        return [Path(path).resolve() for path in confirmation.affected_paths]
    return [Path(path).resolve() for path in (confirmation.get("affected_paths") or [])]


def _verify_destructive_affected_paths(
    targets: Iterable[Path],
    confirmation: DestructiveConfirmation | Mapping[str, Any] | None,
) -> None:
    affected = set(_confirmation_affected_paths(confirmation))
    if not affected:
        return
    missing = [path for path in targets if path.resolve() not in affected]
    if missing:
        raise AudioCLIError(
            "destructive confirmation does not cover all affected paths: "
            + ", ".join(str(path) for path in missing)
        )


def _single_remove_silent_step(steps: Iterable[ChainExecutionStep]) -> ChainExecutionStep:
    return _single_remove_silent_step_with_index(steps)[0]


def _single_remove_silent_step_with_index(
    steps: Iterable[ChainExecutionStep],
) -> tuple[ChainExecutionStep, int]:
    remove_steps = [
        (index, step) for index, step in enumerate(steps, start=1) if _is_remove_silent_step(step)
    ]
    if not remove_steps:
        raise AudioCLIError("chain does not contain a remove-silent destructive filtering node")
    if len(remove_steps) > 1:
        raise AudioCLIError("dry-run preview supports exactly one remove-silent node per chain")
    index, step = remove_steps[0]
    return step, index


def _single_name_regex_filter_step_with_index(
    steps: Iterable[ChainExecutionStep],
) -> tuple[ChainExecutionStep, int]:
    filter_steps = [
        (index, step)
        for index, step in enumerate(steps, start=1)
        if _is_name_regex_filter_step(step)
    ]
    if not filter_steps:
        raise AudioCLIError("chain does not contain a name-regex destructive filtering node")
    if len(filter_steps) > 1:
        raise AudioCLIError("dry-run preview supports exactly one name-regex node per chain")
    index, step = filter_steps[0]
    return step, index


def _preview_remove_silent_for_confirmation(
    preparation: FileChainExecutionPreparation,
) -> RemoveSilentPreview:
    return _preview_remove_silent_at_chain_node(preparation)


def _preview_name_regex_for_confirmation(
    preparation: FileChainExecutionPreparation,
) -> NameRegexFilterPreview:
    return _preview_name_regex_at_chain_node(preparation)


def _preview_remove_silent_at_chain_node(
    preparation: FileChainExecutionPreparation,
    *,
    cancel_token: Event | None = None,
) -> RemoveSilentPreview:
    step, remove_step_index = _single_remove_silent_step_with_index(preparation.plan.steps)
    threshold_db, metric = _remove_silent_params(step)
    target_paths = [Path(target) for target in preparation.targets]
    preview = RemoveSilentPreview(
        chain_id=preparation.chain_id,
        chain_name=preparation.chain_name,
        step=step,
        targets=target_paths,
    )
    start = time.perf_counter()
    for source in target_paths:
        if _cancel_requested(cancel_token):
            preview.results.append(
                RemoveSilentFileAssessment(
                    path=source,
                    status="cancelled",
                    threshold_db=threshold_db,
                    metric=metric,
                    error="cancelled",
                )
            )
            continue

        temp_dir: Path | None = None
        try:
            temp_dir = Path(tempfile.mkdtemp(prefix=f"audiocli-dry-run-{source.stem}-"))
            current_paths = _simulate_file_set_before_remove_silent(
                source,
                preparation.plan,
                preparation.output_policy,
                remove_step_index,
                temp_dir,
                cancel_token=cancel_token,
                scan_roots=preparation.scan_roots,
            )
            for physical_path, preview_path in current_paths:
                if _cancel_requested(cancel_token):
                    preview.results.append(
                        RemoveSilentFileAssessment(
                            path=preview_path,
                            status="cancelled",
                            threshold_db=threshold_db,
                            metric=metric,
                            error="cancelled",
                        )
                    )
                    continue
                silent = is_silent(load(physical_path), threshold_db=threshold_db, metric=metric)
                preview.results.append(
                    RemoveSilentFileAssessment(
                        path=preview_path,
                        status="removed" if silent else "kept",
                        threshold_db=threshold_db,
                        metric=metric,
                        silent=silent,
                    )
                )
        except Exception as e:
            preview.results.append(
                RemoveSilentFileAssessment(
                    path=source,
                    status="failed",
                    threshold_db=threshold_db,
                    metric=metric,
                    error=str(e) if isinstance(e, AudioCLIError) else f"{type(e).__name__}: {e}",
                )
            )
        finally:
            if temp_dir is not None:
                shutil.rmtree(temp_dir, ignore_errors=True)
    preview.duration_s = time.perf_counter() - start
    return preview


def _preview_name_regex_at_chain_node(
    preparation: FileChainExecutionPreparation,
    *,
    cancel_token: Event | None = None,
) -> NameRegexFilterPreview:
    step, filter_step_index = _single_name_regex_filter_step_with_index(preparation.plan.steps)
    pattern, case_sensitive, matcher = _name_regex_params(step)
    target_paths = [Path(target) for target in preparation.targets]
    preview = NameRegexFilterPreview(
        chain_id=preparation.chain_id,
        chain_name=preparation.chain_name,
        step=step,
        targets=target_paths,
    )
    start = time.perf_counter()
    for source in target_paths:
        if _cancel_requested(cancel_token):
            preview.results.append(
                NameRegexFileAssessment(
                    path=source,
                    status="cancelled",
                    pattern=pattern,
                    case_sensitive=case_sensitive,
                    error="cancelled",
                )
            )
            continue

        temp_dir: Path | None = None
        try:
            temp_dir = Path(tempfile.mkdtemp(prefix=f"audiocli-dry-run-{source.stem}-"))
            current_paths = _simulate_file_set_before_remove_silent(
                source,
                preparation.plan,
                preparation.output_policy,
                filter_step_index,
                temp_dir,
                cancel_token=cancel_token,
                scan_roots=preparation.scan_roots,
            )
            for _physical_path, preview_path in current_paths:
                if _cancel_requested(cancel_token):
                    preview.results.append(
                        NameRegexFileAssessment(
                            path=preview_path,
                            status="cancelled",
                            pattern=pattern,
                            case_sensitive=case_sensitive,
                            error="cancelled",
                        )
                    )
                    continue
                matched = bool(matcher.search(preview_path.name))
                preview.results.append(
                    NameRegexFileAssessment(
                        path=preview_path,
                        status="removed" if matched else "kept",
                        pattern=pattern,
                        case_sensitive=case_sensitive,
                        matched=matched,
                    )
                )
        except Exception as e:
            preview.results.append(
                NameRegexFileAssessment(
                    path=source,
                    status="failed",
                    pattern=pattern,
                    case_sensitive=case_sensitive,
                    error=str(e) if isinstance(e, AudioCLIError) else f"{type(e).__name__}: {e}",
                )
            )
        finally:
            if temp_dir is not None:
                shutil.rmtree(temp_dir, ignore_errors=True)
    preview.duration_s = time.perf_counter() - start
    return preview


def _simulate_file_set_before_remove_silent(
    source: Path,
    plan: ChainExecutionPlan,
    policy: ChainOutputPolicy,
    remove_step_index: int,
    temp_dir: Path,
    *,
    cancel_token: Event | None = None,
    scan_roots: Iterable[Path] = (),
) -> list[tuple[Path, Path]]:
    """Run enabled steps before remove-silent against managed dry-run files.

    The first path in each tuple is the physical file to inspect. The second is
    the stable path a real execution would present to remove-silent and bind in
    destructive confirmation.
    """

    dry_policy = ChainOutputPolicy(mode="final_only")
    current_paths: list[tuple[Path, Path]] = [(source, source)]
    collection_expanded = False

    for step_index, step in enumerate(plan.steps[: remove_step_index - 1], start=1):
        if _cancel_requested(cancel_token):
            return current_paths

        input_paths = list(current_paths)
        if _is_analysis_step(step):
            for physical_path, _preview_path in input_paths:
                compute_info(load(physical_path), path=physical_path)
            current_paths = input_paths
            continue

        if _is_acli_script_step(step):
            report = _execute_acli_script_step(step)
            if report.failed_count:
                raise AudioCLIError(f"script failed with {report.failed_count} failing line(s)")
            current_paths = input_paths
            continue

        is_final = _is_final_materializing_step(plan.steps, step_index, step)
        if _is_chunk_step(step):
            current_paths = _simulate_chunk_step_before_remove_silent(
                source,
                input_paths,
                step,
                step_index,
                is_final,
                policy,
                dry_policy,
                temp_dir,
                scan_roots=scan_roots,
            )
            collection_expanded = True
            continue

        if _is_destructive_filter_step(step):
            raise AudioCLIError(
                "dry-run preview supports exactly one destructive filter node per chain"
            )

        output_paths: list[tuple[Path, Path]] = []
        op = _load_hook_op(step) if _is_hook_step(step) else get_op(step.operation_name)
        op_params = _hook_step_kwargs(step) if _is_hook_step(step) else step.params
        expanded_inputs = collection_expanded or len(input_paths) > 1
        for physical_path, preview_path in input_paths:
            physical_dst = _mapped_step_destination(
                source,
                physical_path,
                step,
                step_index,
                False,
                dry_policy,
                temp_dir,
                collection_expanded=expanded_inputs,
                scan_roots=scan_roots,
            )
            preview_dst = (
                _mapped_step_destination(
                    source,
                    preview_path,
                    step,
                    step_index,
                    True,
                    policy,
                    None,
                    collection_expanded=expanded_inputs,
                    scan_roots=scan_roots,
                )
                if is_final
                else physical_dst
            )
            out_buf = op.func(load(physical_path), **op_params)
            physical_dst = rewrite_output_extension(physical_dst, out_buf.format)
            preview_dst = rewrite_output_extension(preview_dst, out_buf.format)
            save(
                physical_dst,
                out_buf,
                subtype=out_buf.subtype,
                format=out_buf.format,
                quality=out_buf.quality,
            )
            output_paths.append((physical_dst, preview_dst))
        current_paths = output_paths

    return current_paths


def _simulate_chunk_step_before_remove_silent(
    source: Path,
    input_paths: list[tuple[Path, Path]],
    step: ChainExecutionStep,
    step_index: int,
    is_final: bool,
    policy: ChainOutputPolicy,
    dry_policy: ChainOutputPolicy,
    temp_dir: Path,
    *,
    scan_roots: Iterable[Path] = (),
) -> list[tuple[Path, Path]]:
    physical_dest_dir = _chunk_destination_dir(
        source,
        step,
        step_index,
        False,
        dry_policy,
        temp_dir,
        scan_roots=scan_roots,
    )
    preview_dest_dir = (
        _chunk_destination_dir(
            source, step, step_index, True, policy, None, scan_roots=scan_roots
        )
        if is_final
        else physical_dest_dir
    )
    output_paths: list[tuple[Path, Path]] = []
    for physical_path, preview_path in input_paths:
        pieces = chunk_buffer(
            load(physical_path),
            seconds=float(step.params["seconds"]),
            pad=bool(step.params.get("pad", True)),
        )
        if not pieces:
            raise AudioCLIError("chunk produced no files for empty buffer")
        width = max(1, len(str(len(pieces))))
        for piece_index, piece in enumerate(pieces, start=1):
            physical_dst = (
                physical_dest_dir
                / f"{physical_path.stem}_{piece_index:0{width}d}{physical_path.suffix}"
            )
            preview_dst = (
                preview_dest_dir
                / f"{preview_path.stem}_{piece_index:0{width}d}{preview_path.suffix}"
                if is_final
                else physical_dst
            )
            save(
                physical_dst,
                piece,
                subtype=piece.subtype,
                format=piece.format,
                quality=piece.quality,
            )
            output_paths.append((physical_dst, preview_dst))
    return output_paths


def _verify_remove_silent_affected_paths(
    candidates: Iterable[Path],
    confirmation: DestructiveConfirmation | Mapping[str, Any] | None,
) -> None:
    affected = set(_confirmation_affected_paths(confirmation))
    candidate_set = {Path(path).resolve() for path in candidates}
    missing = sorted(candidate_set - affected, key=str)
    extra = sorted(affected - candidate_set, key=str)
    if missing or extra:
        parts: list[str] = []
        if missing:
            parts.append("missing candidates: " + ", ".join(str(path) for path in missing))
        if extra:
            parts.append("unexpected paths: " + ", ".join(str(path) for path in extra))
        raise AudioCLIError(
            "remove-silent confirmation affected_paths do not match dry-run candidates ("
            + "; ".join(parts)
            + ")"
        )


def _verify_name_regex_affected_paths(
    candidates: Iterable[Path],
    confirmation: DestructiveConfirmation | Mapping[str, Any] | None,
) -> None:
    affected = set(_confirmation_affected_paths(confirmation))
    candidate_set = {Path(path).resolve() for path in candidates}
    missing = sorted(candidate_set - affected, key=str)
    extra = sorted(affected - candidate_set, key=str)
    if missing or extra:
        parts: list[str] = []
        if missing:
            parts.append("missing candidates: " + ", ".join(str(path) for path in missing))
        if extra:
            parts.append("unexpected paths: " + ", ".join(str(path) for path in extra))
        raise AudioCLIError(
            "name-regex confirmation affected_paths do not match dry-run candidates ("
            + "; ".join(parts)
            + ")"
        )


def _file_filter_event_metadata(
    action_results: Mapping[str, list[Path]],
    **extra: Any,
) -> dict[str, Any]:
    payload: dict[str, Any] = {**extra}
    for status in ("kept", "filtered", "removed", "copied", "moved", "renamed"):
        paths = action_results.get(status, [])
        payload[f"{status}_paths"] = [str(path) for path in paths]
        payload[f"{status}_count"] = len(paths)
    return payload


def _apply_file_filter_action(
    path: Path,
    step: ChainExecutionStep,
    matched: bool,
    *,
    scan_roots: Iterable[Path] = (),
) -> tuple[Path | None, str, Path | None]:
    if not matched:
        return path, "kept", None

    action = _file_filter_action(step)
    if action == "skip":
        return None, "filtered", None
    if action == "delete":
        path.unlink()
        return None, "removed", None
    if action == "copy":
        destination = _copy_or_move_destination(path, step, scan_roots=scan_roots)
        shutil.copy2(path, destination)
        return path, "copied", destination
    if action == "move":
        destination = _copy_or_move_destination(path, step, scan_roots=scan_roots)
        shutil.move(str(path), str(destination))
        return destination, "moved", destination
    if action == "rename":
        destination = _rename_destination(path, step, scan_roots=scan_roots)
        path.rename(destination)
        return destination, "renamed", destination
    raise AudioCLIError(f"unsupported file filter action: {action!r}")


def _scan_roots_from_targets(targets: Iterable[str | Path]) -> tuple[Path, ...]:
    """Extract directory targets as scan roots for relative-path expansion.

    File targets contribute their parent so ``{relative}`` still works when a
    user passes individual files. The result is order-preserving and de-duped.
    """
    seen: set[Path] = set()
    roots: list[Path] = []
    for raw in targets:
        path = Path(raw)
        if path.is_dir():
            root = path
        elif path.is_file():
            root = path.parent
        else:
            continue
        try:
            resolved = root.resolve()
        except OSError:
            resolved = root
        if resolved in seen:
            continue
        seen.add(resolved)
        roots.append(resolved)
    return tuple(roots)


def _resolve_scan_root(source: Path, scan_roots: Iterable[Path]) -> Path | None:
    """Return the deepest scan root that contains ``source`` (or ``None``)."""
    try:
        src_resolved = source.resolve()
    except OSError:
        src_resolved = source
    best: Path | None = None
    best_depth = -1
    for root in scan_roots:
        try:
            root_resolved = root.resolve()
        except OSError:
            root_resolved = root
        try:
            src_resolved.relative_to(root_resolved)
        except ValueError:
            continue
        depth = len(root_resolved.parts)
        if depth > best_depth:
            best = root_resolved
            best_depth = depth
    return best


def expand_path_placeholders(
    raw_path: str,
    source: Path,
    *,
    scan_roots: Iterable[Path] = (),
) -> str:
    """Expand placeholder variables in a path string.

    Supported placeholders:
        {source}        — parent directory of the source file
        {parent}        — same as {source}
        {stem}          — filename without extension
        {name}          — full filename including extension
        {suffix}        — file extension (e.g. ".wav")
        {relative}      — source path relative to its scan root (with filename)
        {relative_dir}  — directory portion of the relative path

    When no scan root contains ``source`` (or none provided), ``{relative}``
    falls back to the bare filename and ``{relative_dir}`` to an empty string.
    """
    relative_name = source.name
    relative_dir = ""
    roots = tuple(scan_roots)
    if roots:
        root = _resolve_scan_root(source, roots)
        if root is not None:
            try:
                rel = source.resolve().relative_to(root)
                relative_name = str(rel)
                parent = rel.parent
                if str(parent) != ".":
                    relative_dir = str(parent)
            except (ValueError, OSError):
                pass
    return raw_path.format(
        source=str(source.parent),
        parent=str(source.parent),
        stem=source.stem,
        name=source.name,
        suffix=source.suffix,
        relative=relative_name,
        relative_dir=relative_dir,
    )


def _copy_or_move_destination(
    path: Path,
    step: ChainExecutionStep,
    *,
    scan_roots: Iterable[Path] = (),
) -> Path:
    raw_dir = str(step.params.get("destination_dir") or "").strip()
    if not raw_dir:
        raise AudioCLIError(f"destination_dir is required for action {_file_filter_action(step)!r}")
    try:
        expanded = expand_path_placeholders(raw_dir, path, scan_roots=scan_roots)
    except (KeyError, ValueError, IndexError) as exc:
        raise AudioCLIError(f"invalid placeholder in destination_dir: {exc}") from exc
    destination_dir = Path(expanded).expanduser()
    destination_dir.mkdir(parents=True, exist_ok=True)
    destination = destination_dir / path.name
    _reject_existing_action_destination(destination)
    return destination


def _rename_destination(
    path: Path,
    step: ChainExecutionStep,
    *,
    scan_roots: Iterable[Path] = (),
) -> Path:
    template = str(step.params.get("rename_template") or "").strip()
    if not template:
        raise AudioCLIError("rename_template is required for rename action")
    relative_name = path.name
    relative_dir = ""
    roots = tuple(scan_roots)
    if roots:
        root = _resolve_scan_root(path, roots)
        if root is not None:
            try:
                rel = path.resolve().relative_to(root)
                relative_name = str(rel)
                parent = rel.parent
                if str(parent) != ".":
                    relative_dir = str(parent)
            except (ValueError, OSError):
                pass
    try:
        name = template.format(
            stem=path.stem,
            suffix=path.suffix,
            name=path.name,
            parent=str(path.parent),
            source=str(path.parent),
            relative=relative_name,
            relative_dir=relative_dir,
        )
    except Exception as exc:
        raise AudioCLIError(f"invalid rename template: {exc}") from exc
    if not name or Path(name).name != name:
        raise AudioCLIError("rename_template must produce a simple file name")
    destination = path.with_name(name)
    _reject_existing_action_destination(destination)
    return destination


def _reject_existing_action_destination(destination: Path) -> None:
    if destination.exists():
        raise AudioCLIError(f"file filter action destination already exists: {destination}")


def _remove_silent_params(step: ChainExecutionStep) -> tuple[float, str]:
    threshold_db = float(step.params.get("threshold_db", -60.0))
    metric = str(step.params.get("metric", "rms"))
    if metric not in {"rms", "peak"}:
        raise AudioCLIError(f"unknown metric: {metric!r} (expected 'rms' or 'peak')")
    return threshold_db, metric


def _name_regex_params(step: ChainExecutionStep) -> tuple[str, bool, re.Pattern[str]]:
    pattern = str(step.params.get("pattern") or "")
    if not pattern:
        raise AudioCLIError("name-regex filter requires a pattern")
    case_sensitive = bool(step.params.get("case_sensitive", False))
    flags = 0 if case_sensitive else re.IGNORECASE
    try:
        return pattern, case_sensitive, re.compile(pattern, flags)
    except re.error as exc:
        raise AudioCLIError(f"invalid name-regex pattern: {exc}") from exc


def _cancel_requested(cancel_token: Event | None) -> bool:
    return cancel_token is not None and cancel_token.is_set()


def _emit_chain_event(callback: EventCallback | None, event: ChainEvent) -> None:
    if callback is None:
        return
    _emit_event(callback, event.to_json())


def _chain_step_event(
    event_type: str,
    *,
    chain_id: str,
    chain_name: str,
    run_id: str,
    source: Path,
    path: Path,
    file_index: int,
    total_files: int,
    step: ChainExecutionStep,
    step_index: int,
    node_count: int,
    status: str,
    output_path: Path | None = None,
    ok: bool | None = None,
    metadata: dict[str, Any] | None = None,
    error: str | None = None,
    reason: str | None = None,
    scope: str | None = None,
) -> ChainEvent:
    return ChainEvent(
        event_type,
        chain_id=chain_id,
        chain_name=chain_name,
        run_id=run_id,
        status=status,
        scope=scope,
        node_id=step.node_id,
        node_index=step_index,
        node_count=node_count,
        capability_id=step.capability_id,
        operation_name=step.operation_name,
        file_index=file_index,
        total_files=total_files,
        source_path=str(source),
        path=str(path),
        output_path=str(output_path) if output_path is not None else None,
        ok=ok,
        metadata=metadata,
        error=error,
        reason=reason,
    )


def _emit_chain_error(
    callback: EventCallback | None,
    *,
    chain_id: str,
    chain_name: str,
    run_id: str,
    source: Path,
    path: Path,
    file_index: int,
    total_files: int,
    step: ChainExecutionStep,
    step_index: int,
    node_count: int,
    error: str,
) -> None:
    _emit_chain_event(
        callback,
        _chain_step_event(
            "error",
            chain_id=chain_id,
            chain_name=chain_name,
            run_id=run_id,
            source=source,
            path=path,
            file_index=file_index,
            total_files=total_files,
            step=step,
            step_index=step_index,
            node_count=node_count,
            status="failed",
            ok=False,
            error=error,
            reason=error,
            scope="node",
        ),
    )


def _emit_file_completion_events(
    callback: EventCallback | None,
    result: ChainFileResult,
    *,
    preparation: FileChainExecutionPreparation,
    run_id: str,
    file_index: int,
    done: int,
    total: int,
    report: ChainRunReport,
) -> None:
    common = {
        "chain_id": preparation.chain_id,
        "chain_name": preparation.chain_name,
        "run_id": run_id,
        "file_index": file_index,
        "total_files": total,
        "source_path": str(result.source_path),
        "path": str(result.path),
        "output_path": str(result.output_path) if result.output_path is not None else None,
        "status": result.status,
        "ok": result.ok,
        "error": result.error,
        "done": done,
        "total": total,
        "ok_count": report.ok_count,
        "kept_count": report.kept_count,
        "removed_count": report.removed_count,
        "filtered_count": report.filtered_count,
        "copied_count": report.copied_count,
        "moved_count": report.moved_count,
        "renamed_count": report.renamed_count,
        "failed_count": report.failed_count,
        "cancelled_count": report.cancelled_count,
    }
    _emit_chain_event(callback, ChainEvent("file_done", **common))
    _emit_chain_event(
        callback, ChainEvent("file_progress", current=str(result.source_path), **common)
    )


def _execute_chain_for_file_legacy(
    source: Path,
    plan: ChainExecutionPlan,
    policy: ChainOutputPolicy,
    *,
    chain_id: str,
    chain_name: str,
    run_id: str,
    file_index: int,
    total_files: int,
    on_event: EventCallback | None = None,
    cancel_token: Event | None = None,
) -> ChainFileResult:
    artifacts: list[ChainStepArtifact] = []
    analysis_results: list[ChainAnalysisResult] = []
    temp_dir: Path | None = None
    current_path = source
    final_path: Path | None = None
    node_count = len(plan.steps)

    try:
        if policy.mode in {"final_only", "destructive"}:
            temp_dir = Path(tempfile.mkdtemp(prefix=f"audiocli-chain-{source.stem}-"))

        for step_index, step in enumerate(plan.steps, start=1):
            if _cancel_requested(cancel_token):
                if policy.mode in {"final_only", "destructive"} and temp_dir is not None:
                    shutil.rmtree(temp_dir, ignore_errors=True)
                    temp_dir = None
                _emit_chain_event(
                    on_event,
                    _chain_step_event(
                        "cancellation",
                        chain_id=chain_id,
                        chain_name=chain_name,
                        run_id=run_id,
                        source=source,
                        path=current_path,
                        file_index=file_index,
                        total_files=total_files,
                        step=step,
                        step_index=step_index,
                        node_count=node_count,
                        status="cancelled",
                        reason="cancelled before node start",
                        scope="file",
                    ),
                )
                return ChainFileResult(
                    source_path=source,
                    path=source,
                    ok=False,
                    error="cancelled",
                    status="cancelled",
                    cancelled_step_index=step_index,
                    cancelled_step=step,
                    intermediates=artifacts,
                    analysis_results=analysis_results,
                    preserved_context_dir=None,
                )

            is_final = _is_final_materializing_step(plan.steps, step_index, step)
            dst: Path | None = None
            if not _is_analysis_step(step):
                dst = _step_destination(
                    source, current_path, step, step_index, is_final, policy, temp_dir
                )
            _emit_chain_event(
                on_event,
                _chain_step_event(
                    "node_start",
                    chain_id=chain_id,
                    chain_name=chain_name,
                    run_id=run_id,
                    source=source,
                    path=current_path,
                    file_index=file_index,
                    total_files=total_files,
                    step=step,
                    step_index=step_index,
                    node_count=node_count,
                    status="running",
                ),
            )
            if _is_analysis_step(step):
                try:
                    metadata = compute_info(load(current_path), path=current_path).to_dict()
                except Exception as e:
                    error = _format_step_error(source, step, step_index, e)
                    analysis_results.append(
                        ChainAnalysisResult(
                            step_index=step_index,
                            step=step,
                            path=current_path,
                            metadata={},
                            ok=False,
                            error=error,
                        )
                    )
                    _emit_chain_error(
                        on_event,
                        chain_id=chain_id,
                        chain_name=chain_name,
                        run_id=run_id,
                        source=source,
                        path=current_path,
                        file_index=file_index,
                        total_files=total_files,
                        step=step,
                        step_index=step_index,
                        node_count=node_count,
                        error=error,
                    )
                    _emit_chain_event(
                        on_event,
                        _chain_step_event(
                            "node_done",
                            chain_id=chain_id,
                            chain_name=chain_name,
                            run_id=run_id,
                            source=source,
                            path=current_path,
                            file_index=file_index,
                            total_files=total_files,
                            step=step,
                            step_index=step_index,
                            node_count=node_count,
                            status="failed",
                            ok=False,
                            error=error,
                        ),
                    )
                    return ChainFileResult(
                        source_path=source,
                        path=source,
                        ok=False,
                        error=error,
                        status="failed",
                        failed_step_index=step_index,
                        failed_step=step,
                        intermediates=artifacts,
                        analysis_results=analysis_results,
                        preserved_context_dir=_preserved_context_dir(policy, temp_dir, source),
                    )

                analysis_result = ChainAnalysisResult(
                    step_index=step_index,
                    step=step,
                    path=current_path,
                    metadata=metadata,
                    ok=True,
                )
                analysis_results.append(analysis_result)
                if final_path is None and all(
                    _is_analysis_step(later) for later in plan.steps[step_index:]
                ):
                    final_path = current_path
                _emit_chain_event(
                    on_event,
                    _chain_step_event(
                        "node_done",
                        chain_id=chain_id,
                        chain_name=chain_name,
                        run_id=run_id,
                        source=source,
                        path=current_path,
                        file_index=file_index,
                        total_files=total_files,
                        step=step,
                        step_index=step_index,
                        node_count=node_count,
                        status="ok",
                        ok=True,
                        metadata=metadata,
                    ),
                )
                continue

            if dst is None:
                raise AudioCLIError("chain execution missing destination for audio step")
            try:
                buf = load(current_path)
                out_buf = get_op(step.operation_name).func(buf, **step.params)
            except Exception as e:
                error = _format_step_error(source, step, step_index, e)
                _emit_chain_error(
                    on_event,
                    chain_id=chain_id,
                    chain_name=chain_name,
                    run_id=run_id,
                    source=source,
                    path=source,
                    file_index=file_index,
                    total_files=total_files,
                    step=step,
                    step_index=step_index,
                    node_count=node_count,
                    error=error,
                )
                _emit_chain_event(
                    on_event,
                    _chain_step_event(
                        "node_done",
                        chain_id=chain_id,
                        chain_name=chain_name,
                        run_id=run_id,
                        source=source,
                        path=source,
                        file_index=file_index,
                        total_files=total_files,
                        step=step,
                        step_index=step_index,
                        node_count=node_count,
                        status="failed",
                        ok=False,
                        error=error,
                    ),
                )
                return ChainFileResult(
                    source_path=source,
                    path=source,
                    ok=False,
                    error=error,
                    status="failed",
                    failed_step_index=step_index,
                    failed_step=step,
                    intermediates=artifacts,
                    analysis_results=analysis_results,
                    preserved_context_dir=_preserved_context_dir(policy, temp_dir, source),
                )

            dst = rewrite_output_extension(dst, out_buf.format)
            try:
                save(
                    dst,
                    out_buf,
                    subtype=out_buf.subtype,
                    format=out_buf.format,
                    quality=out_buf.quality,
                )
            except Exception as e:
                error = _format_step_error(source, step, step_index, e)
                _emit_chain_error(
                    on_event,
                    chain_id=chain_id,
                    chain_name=chain_name,
                    run_id=run_id,
                    source=source,
                    path=source,
                    file_index=file_index,
                    total_files=total_files,
                    step=step,
                    step_index=step_index,
                    node_count=node_count,
                    error=error,
                )
                _emit_chain_event(
                    on_event,
                    _chain_step_event(
                        "node_done",
                        chain_id=chain_id,
                        chain_name=chain_name,
                        run_id=run_id,
                        source=source,
                        path=source,
                        output_path=dst if is_final else None,
                        file_index=file_index,
                        total_files=total_files,
                        step=step,
                        step_index=step_index,
                        node_count=node_count,
                        status="failed",
                        ok=False,
                        error=error,
                    ),
                )
                return ChainFileResult(
                    source_path=source,
                    path=source,
                    ok=False,
                    error=error,
                    status="failed",
                    output_path=dst if is_final else None,
                    failed_step_index=step_index,
                    failed_step=step,
                    intermediates=artifacts,
                    analysis_results=analysis_results,
                    preserved_context_dir=_preserved_context_dir(policy, temp_dir, source),
                )

            artifact = ChainStepArtifact(
                step_index=step_index,
                step=step,
                path=dst,
                intermediate=not is_final,
            )
            if is_final:
                final_path = dst
                current_path = dst
            else:
                artifacts.append(artifact)
                current_path = dst
            _emit_chain_event(
                on_event,
                _chain_step_event(
                    "node_done",
                    chain_id=chain_id,
                    chain_name=chain_name,
                    run_id=run_id,
                    source=source,
                    path=dst,
                    output_path=dst if is_final else None,
                    file_index=file_index,
                    total_files=total_files,
                    step=step,
                    step_index=step_index,
                    node_count=node_count,
                    status="ok",
                    ok=True,
                ),
            )

        if final_path is None:
            raise AudioCLIError("chain execution produced no final output")
        if policy.mode in {"final_only", "destructive"} and temp_dir is not None:
            shutil.rmtree(temp_dir, ignore_errors=True)
            temp_dir = None
        return ChainFileResult(
            source_path=source,
            path=final_path,
            ok=True,
            status="ok",
            output_path=final_path,
            intermediates=artifacts,
            analysis_results=analysis_results,
            preserved_context_dir=None,
        )
    except Exception as e:
        error = f"{type(e).__name__}: {e}"
        _emit_chain_event(
            on_event,
            ChainEvent(
                "error",
                chain_id=chain_id,
                chain_name=chain_name,
                run_id=run_id,
                status="failed",
                scope="file",
                file_index=file_index,
                total_files=total_files,
                source_path=str(source),
                path=str(source),
                error=error,
                reason=error,
            ),
        )
        return ChainFileResult(
            source_path=source,
            path=source,
            ok=False,
            error=error,
            status="failed",
            intermediates=artifacts,
            analysis_results=analysis_results,
            preserved_context_dir=_preserved_context_dir(policy, temp_dir, source),
        )
    finally:
        if policy.mode == "destructive" and temp_dir is not None:
            shutil.rmtree(temp_dir, ignore_errors=True)


def _execute_chain_for_file(
    source: Path,
    plan: ChainExecutionPlan,
    policy: ChainOutputPolicy,
    *,
    chain_id: str,
    chain_name: str,
    run_id: str,
    file_index: int,
    total_files: int,
    on_event: EventCallback | None = None,
    cancel_token: Event | None = None,
    skip_job_script_steps: bool = False,
    scan_roots: tuple[Path, ...] = (),
) -> ChainFileResult:
    artifacts: list[ChainStepArtifact] = []
    analysis_results: list[ChainAnalysisResult] = []
    script_results: list[ChainScriptResult] = []
    step_file_sets: list[ChainStepFileSet] = []
    expanded_output_files: list[Path] = []
    temp_dir: Path | None = None
    current_paths = [source]
    collection_expanded = False
    saw_file_filter = False
    file_filter_final_status: str | None = None
    empty_file_filter_status = "filtered"
    node_count = len(plan.steps)

    try:
        if policy.mode in {"final_only", "destructive"}:
            temp_dir = Path(tempfile.mkdtemp(prefix=f"audiocli-chain-{source.stem}-"))

        for step_index, step in enumerate(plan.steps, start=1):
            if skip_job_script_steps and _is_acli_script_step(step):
                continue
            if _cancel_requested(cancel_token):
                if policy.mode in {"final_only", "destructive"} and temp_dir is not None:
                    shutil.rmtree(temp_dir, ignore_errors=True)
                    temp_dir = None
                return ChainFileResult(
                    source_path=source,
                    path=source,
                    ok=False,
                    error="cancelled",
                    status="cancelled",
                    cancelled_step_index=step_index,
                    cancelled_step=step,
                    intermediates=artifacts,
                    analysis_results=analysis_results,
                    script_results=script_results,
                    step_file_sets=step_file_sets,
                    preserved_context_dir=None,
                )

            input_paths = list(current_paths)
            is_final = _is_final_materializing_step(plan.steps, step_index, step)
            _emit_chain_event(
                on_event,
                _chain_step_event(
                    "node_start",
                    chain_id=chain_id,
                    chain_name=chain_name,
                    run_id=run_id,
                    source=source,
                    path=input_paths[0],
                    file_index=file_index,
                    total_files=total_files,
                    step=step,
                    step_index=step_index,
                    node_count=node_count,
                    status="running",
                    metadata={"input_paths": [str(path) for path in input_paths]},
                ),
            )

            try:
                if _is_analysis_step(step):
                    analysis_payloads: list[dict[str, Any]] = []
                    for path in input_paths:
                        try:
                            metadata = compute_info(load(path), path=path).to_dict()
                        except Exception as e:
                            formatted = _format_step_error(source, step, step_index, e)
                            analysis_results.append(
                                ChainAnalysisResult(
                                    step_index=step_index,
                                    step=step,
                                    path=path,
                                    metadata={},
                                    ok=False,
                                    error=formatted,
                                )
                            )
                            raise
                        analysis_payloads.append(metadata)
                        analysis_results.append(
                            ChainAnalysisResult(
                                step_index=step_index,
                                step=step,
                                path=path,
                                metadata=metadata,
                                ok=True,
                            )
                        )
                    output_paths = input_paths
                    behavior = "pass_through_collection" if len(input_paths) > 1 else "pass_through"
                    event_metadata: dict[str, Any] | None = (
                        analysis_payloads[0]
                        if len(analysis_payloads) == 1
                        else {"analysis_results": analysis_payloads}
                    )

                elif _is_acli_script_step(step):
                    report = _execute_acli_script_step(step)
                    report_payload = report.to_view_model()
                    ok = report.failed_count == 0
                    error = (
                        None if ok else f"script failed with {report.failed_count} failing line(s)"
                    )
                    for path in input_paths:
                        script_results.append(
                            ChainScriptResult(
                                step_index=step_index,
                                step=step,
                                path=path,
                                report=report_payload,
                                ok=ok,
                                error=error,
                            )
                        )
                    if not ok:
                        raise AudioCLIError(error or "script failed")
                    output_paths = input_paths
                    behavior = (
                        "script_pass_through_collection"
                        if len(input_paths) > 1
                        else "script_pass_through"
                    )
                    event_metadata = {"script_report": report_payload}

                elif _is_chunk_step(step):
                    output_paths = []
                    dest_dir = _chunk_destination_dir(
                        source, step, step_index, is_final, policy, temp_dir,
                        scan_roots=scan_roots,
                    )
                    for path in input_paths:
                        pieces = chunk_buffer(
                            load(path),
                            seconds=float(step.params["seconds"]),
                            pad=bool(step.params.get("pad", True)),
                        )
                        if not pieces:
                            raise AudioCLIError("chunk produced no files for empty buffer")
                        width = max(1, len(str(len(pieces))))
                        for piece_index, piece in enumerate(pieces, start=1):
                            dst = dest_dir / f"{path.stem}_{piece_index:0{width}d}{path.suffix}"
                            save(
                                dst,
                                piece,
                                subtype=piece.subtype,
                                format=piece.format,
                                quality=piece.quality,
                            )
                            output_paths.append(dst)
                            if not is_final:
                                artifacts.append(
                                    ChainStepArtifact(
                                        step_index=step_index,
                                        step=step,
                                        path=dst,
                                        intermediate=True,
                                    )
                                )
                    collection_expanded = True
                    expanded_output_files = list(output_paths)
                    behavior = "expand_one_to_many"
                    event_metadata = None

                elif _is_remove_silent_step(step):
                    saw_file_filter = True
                    output_paths = []
                    action_results: dict[str, list[Path]] = {
                        "kept": [],
                        "filtered": [],
                        "removed": [],
                        "copied": [],
                        "moved": [],
                        "renamed": [],
                    }
                    threshold_db, metric = _remove_silent_params(step)
                    for path in input_paths:
                        if _cancel_requested(cancel_token):
                            return ChainFileResult(
                                source_path=source,
                                path=source,
                                ok=False,
                                error="cancelled",
                                status="cancelled",
                                cancelled_step_index=step_index,
                                cancelled_step=step,
                                intermediates=artifacts,
                                analysis_results=analysis_results,
                                script_results=script_results,
                                step_file_sets=step_file_sets,
                                current_files=input_paths,
                                expanded_output_files=expanded_output_files,
                                preserved_context_dir=None,
                            )
                        matched = is_silent(load(path), threshold_db=threshold_db, metric=metric)
                        next_path, status, action_path = _apply_file_filter_action(
                            path, step, matched, scan_roots=scan_roots
                        )
                        action_results[status].append(action_path or path)
                        if matched:
                            empty_file_filter_status = status
                            if status in {"copied", "moved", "renamed"}:
                                file_filter_final_status = status
                        if next_path is not None:
                            output_paths.append(next_path)
                    behavior = "file_filter"
                    event_metadata = _file_filter_event_metadata(
                        action_results,
                        action=_file_filter_action(step),
                        threshold_db=threshold_db,
                        metric=metric,
                    )

                elif _is_name_regex_filter_step(step):
                    saw_file_filter = True
                    output_paths = []
                    action_results = {
                        "kept": [],
                        "filtered": [],
                        "removed": [],
                        "copied": [],
                        "moved": [],
                        "renamed": [],
                    }
                    pattern, case_sensitive, matcher = _name_regex_params(step)
                    for path in input_paths:
                        if _cancel_requested(cancel_token):
                            return ChainFileResult(
                                source_path=source,
                                path=source,
                                ok=False,
                                error="cancelled",
                                status="cancelled",
                                cancelled_step_index=step_index,
                                cancelled_step=step,
                                intermediates=artifacts,
                                analysis_results=analysis_results,
                                script_results=script_results,
                                step_file_sets=step_file_sets,
                                current_files=input_paths,
                                expanded_output_files=expanded_output_files,
                                preserved_context_dir=None,
                            )
                        matched = bool(matcher.search(path.name))
                        next_path, status, action_path = _apply_file_filter_action(
                            path, step, matched, scan_roots=scan_roots
                        )
                        action_results[status].append(action_path or path)
                        if matched:
                            empty_file_filter_status = status
                            if status in {"copied", "moved", "renamed"}:
                                file_filter_final_status = status
                        if next_path is not None:
                            output_paths.append(next_path)
                    behavior = "file_filter"
                    event_metadata = _file_filter_event_metadata(
                        action_results,
                        action=_file_filter_action(step),
                        pattern=pattern,
                        case_sensitive=case_sensitive,
                    )

                else:
                    output_paths = []
                    op = _load_hook_op(step) if _is_hook_step(step) else get_op(step.operation_name)
                    op_params = _hook_step_kwargs(step) if _is_hook_step(step) else step.params
                    for path in input_paths:
                        dst = _mapped_step_destination(
                            source,
                            path,
                            step,
                            step_index,
                            is_final,
                            policy,
                            temp_dir,
                            collection_expanded=collection_expanded or len(input_paths) > 1,
                            scan_roots=scan_roots,
                        )
                        out_buf = op.func(load(path), **op_params)
                        dst = rewrite_output_extension(dst, out_buf.format)
                        save(
                            dst,
                            out_buf,
                            subtype=out_buf.subtype,
                            format=out_buf.format,
                            quality=out_buf.quality,
                        )
                        output_paths.append(dst)
                        if not is_final:
                            artifacts.append(
                                ChainStepArtifact(
                                    step_index=step_index,
                                    step=step,
                                    path=dst,
                                    intermediate=True,
                                )
                            )
                    behavior = (
                        "map_each_file"
                        if collection_expanded or len(input_paths) > 1
                        else "single_file"
                    )
                    event_metadata = None

            except Exception as e:
                error = _format_step_error(source, step, step_index, e)
                _emit_chain_error(
                    on_event,
                    chain_id=chain_id,
                    chain_name=chain_name,
                    run_id=run_id,
                    source=source,
                    path=input_paths[0] if input_paths else source,
                    file_index=file_index,
                    total_files=total_files,
                    step=step,
                    step_index=step_index,
                    node_count=node_count,
                    error=error,
                )
                return ChainFileResult(
                    source_path=source,
                    path=source,
                    ok=False,
                    error=error,
                    status="failed",
                    failed_step_index=step_index,
                    failed_step=step,
                    intermediates=artifacts,
                    analysis_results=analysis_results,
                    script_results=script_results,
                    step_file_sets=step_file_sets,
                    current_files=input_paths,
                    expanded_output_files=expanded_output_files,
                    preserved_context_dir=_preserved_context_dir(policy, temp_dir, source),
                )

            step_file_set = ChainStepFileSet(
                step_index=step_index,
                step=step,
                input_paths=input_paths,
                output_paths=output_paths,
                expanded=len(output_paths) != len(input_paths) or len(output_paths) > 1,
                behavior=behavior,
            )
            step_file_sets.append(step_file_set)
            current_paths = list(output_paths)
            if is_final:
                expanded_output_files = list(output_paths)

            node_status = (
                empty_file_filter_status
                if _is_destructive_filter_step(step) and not output_paths
                else "ok"
            )
            _emit_chain_event(
                on_event,
                _chain_step_event(
                    "node_done",
                    chain_id=chain_id,
                    chain_name=chain_name,
                    run_id=run_id,
                    source=source,
                    path=current_paths[0] if current_paths else source,
                    output_path=current_paths[0] if is_final and current_paths else None,
                    file_index=file_index,
                    total_files=total_files,
                    step=step,
                    step_index=step_index,
                    node_count=node_count,
                    status=node_status,
                    ok=True,
                    metadata=event_metadata or step_file_set.to_view_model(),
                ),
            )
            if _is_destructive_filter_step(step) and not current_paths:
                if policy.mode in {"final_only", "destructive"} and temp_dir is not None:
                    shutil.rmtree(temp_dir, ignore_errors=True)
                    temp_dir = None
                return ChainFileResult(
                    source_path=source,
                    path=source,
                    ok=True,
                    status=empty_file_filter_status,
                    intermediates=artifacts,
                    analysis_results=analysis_results,
                    script_results=script_results,
                    step_file_sets=step_file_sets,
                    current_files=[],
                    expanded_output_files=expanded_output_files,
                    preserved_context_dir=None,
                )

        if not current_paths:
            raise AudioCLIError("chain execution produced no final output")
        if policy.mode in {"final_only", "destructive"} and temp_dir is not None:
            shutil.rmtree(temp_dir, ignore_errors=True)
            temp_dir = None
        final_status = "ok"
        if saw_file_filter and _final_materializing_step(plan.steps) is None:
            final_status = file_filter_final_status or "kept"
        return ChainFileResult(
            source_path=source,
            path=current_paths[0],
            ok=True,
            status=final_status,
            output_path=current_paths[0],
            output_paths=list(current_paths),
            current_files=list(current_paths),
            expanded_output_files=expanded_output_files or list(current_paths),
            intermediates=artifacts,
            analysis_results=analysis_results,
            script_results=script_results,
            step_file_sets=step_file_sets,
            preserved_context_dir=None,
        )
    except Exception as e:
        error = f"{type(e).__name__}: {e}"
        _emit_chain_event(
            on_event,
            ChainEvent(
                "error",
                chain_id=chain_id,
                chain_name=chain_name,
                run_id=run_id,
                status="failed",
                scope="file",
                file_index=file_index,
                total_files=total_files,
                source_path=str(source),
                path=str(source),
                error=error,
                reason=error,
            ),
        )
        return ChainFileResult(
            source_path=source,
            path=source,
            ok=False,
            error=error,
            status="failed",
            intermediates=artifacts,
            analysis_results=analysis_results,
            script_results=script_results,
            step_file_sets=step_file_sets,
            current_files=list(current_paths),
            expanded_output_files=expanded_output_files,
            preserved_context_dir=_preserved_context_dir(policy, temp_dir, source),
        )
    finally:
        if policy.mode == "destructive" and temp_dir is not None:
            shutil.rmtree(temp_dir, ignore_errors=True)


def _load_hook_op(step: ChainExecutionStep):
    from audiocli.hook import load_hook_function, make_hook_op  # noqa: PLC0415

    script_path = Path(str(step.params.get("script_path") or ""))
    function_name = str(step.params.get("function_name") or "").strip() or None
    func = load_hook_function(script_path, function_name)
    return make_hook_op(func, script_path)


def _structured_one_node_setup_failure(
    targets: Iterable[Path],
    error: Exception,
    *,
    on_event: EventCallback | None = None,
) -> JobReport:
    """Return per-target failures for one-node setup errors discovered after scanning.

    Hook function discovery/import errors are execution-time script failures, not
    chain-shape failures. Reporting one structured failure per scanned target
    keeps one-node hook execution aligned with normal per-file pipeline errors.
    """

    paths = [Path(path) for path in targets]
    report = JobReport()
    start = time.perf_counter()
    message = f"{type(error).__name__}: {error}"
    for index, path in enumerate(paths, start=1):
        result = Result(path=path, ok=False, error=message)
        report.results.append(result)
        if on_event is not None:
            _emit_event(
                on_event,
                {
                    "event": "file_done",
                    "type": "file_done",
                    "path": str(path),
                    "ok": False,
                    "error": message,
                    "done": index,
                    "total": len(paths),
                },
            )
    report.duration_s = time.perf_counter() - start
    return report


def _hook_step_kwargs(step: ChainExecutionStep) -> dict[str, Any]:
    kwargs = step.params.get("kwargs", {})
    return dict(kwargs) if isinstance(kwargs, Mapping) else {}


def _execute_acli_script_step(step: ChainExecutionStep):
    from audiocli.cli import app  # noqa: PLC0415
    from audiocli.run_script import run_script  # noqa: PLC0415

    return run_script(
        app,
        Path(str(step.params.get("script_path") or "")),
        strict=bool(step.params.get("strict", False)),
    )


def _execute_job_script_steps(
    steps: Iterable[ChainExecutionStep],
    *,
    chain_id: str,
    chain_name: str,
    run_id: str,
    node_count: int,
    on_event: EventCallback | None = None,
    cancel_token: Event | None = None,
) -> list[ChainScriptResult]:
    """Run .acli script nodes once for the whole chain job.

    ``builtin.script.acli`` is a pass-through, whole-job side-effect node.  It
    must not execute once per target file; its report is captured at the run
    level via ``ChainRunReport.script_results`` and failures are projected onto
    per-file results by the caller without re-running the script.
    """

    results: list[ChainScriptResult] = []
    for step_index, step in enumerate(steps, start=1):
        if not _is_acli_script_step(step):
            continue
        if _cancel_requested(cancel_token):
            results.append(
                ChainScriptResult(
                    step_index=step_index,
                    step=step,
                    ok=False,
                    error="cancelled",
                    scope="job",
                )
            )
            break

        _emit_chain_event(
            on_event,
            ChainEvent(
                "node_start",
                chain_id=chain_id,
                chain_name=chain_name,
                run_id=run_id,
                status="running",
                scope="job",
                node_id=step.node_id,
                node_index=step_index,
                node_count=node_count,
                capability_id=step.capability_id,
                operation_name=step.operation_name,
                metadata={"whole_job_side_effect": True},
            ),
        )
        try:
            report = _execute_acli_script_step(step)
            report_payload = report.to_view_model()
            ok = report.failed_count == 0
            error = None if ok else f"script failed with {report.failed_count} failing line(s)"
        except Exception as e:
            report_payload = {}
            ok = False
            error = f"{type(e).__name__}: {e}"

        result = ChainScriptResult(
            step_index=step_index,
            step=step,
            report=report_payload,
            ok=ok,
            error=error,
            scope="job",
        )
        results.append(result)
        _emit_chain_event(
            on_event,
            ChainEvent(
                "node_done" if ok else "error",
                chain_id=chain_id,
                chain_name=chain_name,
                run_id=run_id,
                status="ok" if ok else "failed",
                scope="job",
                node_id=step.node_id,
                node_index=step_index,
                node_count=node_count,
                capability_id=step.capability_id,
                operation_name=step.operation_name,
                ok=ok,
                error=error,
                reason=error,
                metadata={
                    "whole_job_side_effect": True,
                    "script_report": report_payload,
                },
            ),
        )
        if not ok:
            break
    return results


def _chunk_destination_dir(
    source: Path,
    step: ChainExecutionStep,
    step_index: int,
    is_final: bool,
    policy: ChainOutputPolicy,
    temp_dir: Path | None,
    *,
    scan_roots: Iterable[Path] = (),
) -> Path:
    if is_final:
        return _final_output_dir(source, policy, scan_roots=scan_roots)
    return _intermediate_step_dir(source, step, step_index, policy, temp_dir)


def _mapped_step_destination(
    source: Path,
    current_path: Path,
    step: ChainExecutionStep,
    step_index: int,
    is_final: bool,
    policy: ChainOutputPolicy,
    temp_dir: Path | None,
    *,
    collection_expanded: bool,
    scan_roots: Iterable[Path] = (),
) -> Path:
    if is_final and collection_expanded:
        return _final_output_dir(source, policy, scan_roots=scan_roots) / current_path.name
    if not is_final and collection_expanded:
        return (
            _intermediate_step_dir(source, step, step_index, policy, temp_dir) / current_path.name
        )
    return _step_destination(
        source, current_path, step, step_index, is_final, policy, temp_dir, scan_roots=scan_roots
    )


def _final_output_dir(
    source: Path,
    policy: ChainOutputPolicy,
    *,
    scan_roots: Iterable[Path] = (),
) -> Path:
    if policy.mode == "destructive":
        raise AudioCLIError("destructive chain execution does not support expanded file sets")
    if policy.output is None:
        return source.parent
    output = policy.output
    if "{" in str(output):
        output = Path(expand_path_placeholders(str(output), source, scan_roots=scan_roots))
    if output.suffix and not output.is_dir():
        raise AudioCLIError(
            "exact output file cannot be used with expanded file sets; choose an output directory"
        )
    return output


def _intermediate_step_dir(
    source: Path,
    step: ChainExecutionStep,
    step_index: int,
    policy: ChainOutputPolicy,
    temp_dir: Path | None,
) -> Path:
    if policy.mode == "keep_intermediates":
        base_dir = _keep_intermediates_base_dir(source, policy.output)
        return base_dir / INTERMEDIATES_DIRNAME / _step_dirname(step_index, step.operation_name)
    if temp_dir is None:
        raise AudioCLIError("managed temp directory missing for chain intermediate")
    return temp_dir / _step_dirname(step_index, step.operation_name)


def _keep_intermediates_base_dir(source: Path, output: Path | None) -> Path:
    if output is not None and not output.suffix:
        return output
    if output is not None and output.suffix:
        return output.parent
    return source.parent


def _step_destination(
    source: Path,
    current_path: Path,
    step: ChainExecutionStep,
    step_index: int,
    is_final: bool,
    policy: ChainOutputPolicy,
    temp_dir: Path | None,
    *,
    scan_roots: Iterable[Path] = (),
) -> Path:
    if is_final:
        if policy.mode == "destructive":
            return source
        return _preview_output_path(source, policy.output, step, scan_roots=scan_roots)

    if policy.mode == "keep_intermediates":
        base_dir = _keep_intermediates_root(source, policy.output, step)
        step_dir = base_dir / _step_dirname(step_index, step.operation_name)
        return step_dir / current_path.name

    if temp_dir is None:
        raise AudioCLIError("managed temp directory missing for chain intermediate")
    step_dir = temp_dir / _step_dirname(step_index, step.operation_name)
    return step_dir / current_path.name


def _keep_intermediates_root(
    source: Path, output: Path | None, final_step: ChainExecutionStep
) -> Path:
    if output is not None and not output.suffix:
        return output / INTERMEDIATES_DIRNAME
    if output is not None and output.suffix:
        return output.parent / INTERMEDIATES_DIRNAME
    return _preview_output_path(source, None, final_step).parent / INTERMEDIATES_DIRNAME


def _step_dirname(step_index: int, op_name: str) -> str:
    safe_op = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "-" for ch in op_name)
    return f"step-{step_index:02d}-{safe_op or 'op'}"


def _preserved_context_dir(
    policy: ChainOutputPolicy, temp_dir: Path | None, source: Path
) -> Path | None:
    if policy.mode == "final_only":
        return temp_dir
    if policy.mode == "keep_intermediates":
        return _keep_intermediates_root(
            source, policy.output, ChainExecutionStep("", 0, "", "", {})
        )
    return None


def _format_step_error(
    source: Path, step: ChainExecutionStep, step_index: int, error: Exception
) -> str:
    detail = str(error) if isinstance(error, AudioCLIError) else f"{type(error).__name__}: {error}"
    return f"step {step_index} ({step.operation_name}) failed for {source}: {detail}"


def _emit_event(callback: EventCallback, payload: dict[str, Any]) -> None:
    with suppress(Exception):
        callback(payload)


__all__ = [
    "CHAIN_FILE_STATUSES",
    "CHAIN_OUTPUT_MODES",
    "CHAIN_SUCCESS_STATUSES",
    "FILE_FILTER_CONFIRMATION_ACTIONS",
    "INTERMEDIATES_DIRNAME",
    "ChainEvent",
    "ChainAnalysisResult",
    "ChainScriptResult",
    "ChainExecutionPreparation",
    "ChainExecutionReport",
    "ChainExecutionResult",
    "ChainExecutionRun",
    "ChainFileResult",
    "ChainOutputPolicy",
    "ChainOutputPreview",
    "ChainRunReport",
    "ChainStepArtifact",
    "ChainStepFileSet",
    "DestructiveConfirmation",
    "FileChainExecutionPreparation",
    "FileChainExecutionRun",
    "OneNodeFilterChainPreparation",
    "OneNodeFilterChainRun",
    "RemoveSilentFileAssessment",
    "RemoveSilentPreview",
    "build_one_node_filter_chain",
    "convert_acli_script_to_chain",
    "dry_run_remove_silent_chain",
    "execute_chain",
    "execute_file_chain",
    "execute_one_node_filter_chain",
    "import_acli_script",
    "prepare_chain_execution",
    "prepare_file_chain_execution",
    "prepare_one_node_filter_chain",
    "preview_chain_output_paths",
    "preview_output_paths",
    "preview_remove_silent",
]
