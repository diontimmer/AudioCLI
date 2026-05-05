"""GUI-neutral capability discovery and parameter validation.

This module is the first service-layer seam for the future PySide6 GUI.  It
projects the existing first-party filter operation registry into stable
"capability node" descriptions that a UI can render without importing or
invoking the Typer CLI adapter.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from audiocli.io import SUPPORTED_FORMATS
from audiocli.plugin_discovery import macos_default_plugin_scan_directory_specs
from audiocli.registry import OpInfo, ParamInfo, list_ops


@dataclass(frozen=True)
class IOShape:
    """Declared input or output contract for a capability node."""

    kind: str
    media_type: str
    cardinality: str
    description: str = ""

    def to_view_model(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "media_type": self.media_type,
            "cardinality": self.cardinality,
            "description": self.description,
        }


@dataclass(frozen=True)
class SafetySemantics:
    """Safety flags shown by UI before a node is added or executed."""

    classification: str
    destructive: bool = False
    requires_confirmation: bool = False
    writes_files: bool = False
    external: bool = False
    notes: list[str] = field(default_factory=list)

    def to_view_model(self) -> dict[str, Any]:
        return {
            "classification": self.classification,
            "destructive": self.destructive,
            "requires_confirmation": self.requires_confirmation,
            "writes_files": self.writes_files,
            "external": self.external,
            "notes": list(self.notes),
        }


@dataclass(frozen=True)
class CapabilityParameter:
    """UI-facing metadata for one capability parameter."""

    name: str
    type: str
    display_name: str
    description: str = ""
    required: bool = False
    default: Any = None
    control_hint: str = "text"
    choices: list[Any] = field(default_factory=list)
    normalizer: str = ""
    min_value: float | int | None = None
    min_exclusive: bool = False
    repeatable: bool = False

    def to_view_model(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "type": self.type,
            "display_name": self.display_name,
            "description": self.description,
            "required": self.required,
            "default": _json_safe(self.default),
            "control_hint": self.control_hint,
            "choices": _json_safe(self.choices),
            "min_value": _json_safe(self.min_value),
            "min_exclusive": self.min_exclusive,
            "repeatable": self.repeatable,
        }


@dataclass(frozen=True)
class ValidationError:
    """Structured pre-execution validation error for a node parameter."""

    parameter: str
    code: str
    message: str
    expected_type: str = ""
    received: str = ""

    def to_view_model(self) -> dict[str, Any]:
        return {
            "parameter": self.parameter,
            "code": self.code,
            "message": self.message,
            "expected_type": self.expected_type,
            "received": self.received,
        }


@dataclass(frozen=True)
class ValidationResult:
    """Validation outcome and JSON-safe coerced values."""

    valid: bool
    errors: list[ValidationError] = field(default_factory=list)
    values: dict[str, Any] = field(default_factory=dict)

    def to_view_model(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "errors": [e.to_view_model() for e in self.errors],
            "values": _json_safe(self.values),
        }


@dataclass(frozen=True)
class CapabilityNode:
    """A runnable GUI capability projected from a service-layer source."""

    id: str
    type: str
    display_name: str
    description: str
    input_shape: IOShape
    output_shape: IOShape
    safety: SafetySemantics
    parameters: list[CapabilityParameter] = field(default_factory=list)
    defaults: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    validation_state: ValidationResult = field(default_factory=lambda: ValidationResult(valid=True))
    operation_name: str = ""

    def validate_params(self, params: dict[str, Any] | None) -> ValidationResult:
        """Validate and coerce user-supplied parameters before execution."""

        if self.metadata.get("validator") == "vst_external_plugin":
            return _validate_vst_external_plugin_params(params or {})
        if self.metadata.get("validator") == "external_script_hook":
            return _validate_external_script_hook_params(params or {})
        if self.metadata.get("validator") == "acli_script":
            return _validate_acli_script_params(params or {})
        return validate_parameters(self.parameters, params or {})

    def to_view_model(self) -> dict[str, Any]:
        """Return a JSON-serializable representation for GUI rendering."""

        return {
            "id": self.id,
            "type": self.type,
            "display_name": self.display_name,
            "description": self.description,
            "input_shape": self.input_shape.to_view_model(),
            "output_shape": self.output_shape.to_view_model(),
            "safety": self.safety.to_view_model(),
            "parameters": [p.to_view_model() for p in self.parameters],
            "defaults": _json_safe(self.defaults),
            "metadata": _json_safe(self.metadata),
            "validation_state": self.validation_state.to_view_model(),
            "operation_name": self.operation_name,
        }


_AUDIO_IN = IOShape(
    kind="audio_buffer",
    media_type="audio/*",
    cardinality="single",
    description="One decoded AudioBuffer from an input audio file.",
)
_AUDIO_OUT = IOShape(
    kind="audio_buffer",
    media_type="audio/*",
    cardinality="single",
    description="One transformed AudioBuffer for the downstream node or output policy.",
)
_DESTRUCTIVE_FILTER_OUT = IOShape(
    kind="audio_buffer",
    media_type="audio/*",
    cardinality="single",
    description=(
        "The original AudioBuffer/file reference is passed downstream when kept; "
        "silent files are removed from the file set and do not continue."
    ),
)
_AUDIO_MANY_OUT = IOShape(
    kind="audio_buffer",
    media_type="audio/*",
    cardinality="many",
    description=(
        "Many AudioBuffers produced from one input file; downstream audio filters "
        "are mapped over each produced file."
    ),
)
_ANALYSIS_AUDIO_OUT = IOShape(
    kind="audio_buffer",
    media_type="audio/*",
    cardinality="single",
    description=(
        "The original AudioBuffer/file reference is passed through unchanged when "
        "pass_through is true; structured analysis metadata is emitted separately."
    ),
)
_METADATA_OUT = IOShape(
    kind="metadata",
    media_type="application/json",
    cardinality="single",
    description="Structured analysis metadata, not an audio buffer.",
)
_FILTER_SAFETY = SafetySemantics(
    classification="pure_transform",
    destructive=False,
    requires_confirmation=False,
    writes_files=False,
    external=False,
    notes=[
        "Built-in filters transform an AudioBuffer in memory; file writes are controlled by execution/output policy."
    ],
)
_MACRO_SAFETY = SafetySemantics(
    classification="saved_chain_macro",
    destructive=False,
    requires_confirmation=False,
    writes_files=False,
    external=False,
    notes=[
        "Saved-chain macros expand to another AudioCLI chain during future chain execution; recursion is rejected during validation."
    ],
)
_ANALYSIS_SAFETY = SafetySemantics(
    classification="analysis",
    destructive=False,
    requires_confirmation=False,
    writes_files=False,
    external=False,
    notes=[
        "Analysis nodes inspect decoded audio and emit structured metadata; they do not transform audio or write files.",
        "Set pass_through=false to stop audio from flowing to downstream audio nodes.",
    ],
)
_MULTI_OUTPUT_SAFETY = SafetySemantics(
    classification="multi_output_transform",
    destructive=False,
    requires_confirmation=False,
    writes_files=True,
    external=False,
    notes=[
        "Chunking intentionally expands one audio file into many files.",
        "Downstream audio filters are applied once per produced chunk file.",
    ],
)
_DESTRUCTIVE_FILTER_SAFETY = SafetySemantics(
    classification="destructive_filter",
    destructive=True,
    requires_confirmation=True,
    writes_files=True,
    external=False,
    notes=[
        "This node deletes files classified as silent and filters them out of downstream chain execution.",
        "Use dry-run preview to inspect affected files, then pass an explicit destructive confirmation before execution.",
    ],
)
_EXTERNAL_PLUGIN_SAFETY = SafetySemantics(
    classification="external_plugin",
    destructive=False,
    requires_confirmation=False,
    writes_files=False,
    external=True,
    notes=[
        "Loads third-party native plugin code into the AudioCLI process; buggy plugins may crash, hang, or corrupt processing.",
        "VST3 plugins are commonly cross-platform when a compatible build is installed; AU plugins are macOS-only.",
        "File writes are controlled by execution/output policy, but plugin DSP and parameter handling are outside AudioCLI's control.",
    ],
)
_EXTERNAL_SCRIPT_SAFETY = SafetySemantics(
    classification="external_script",
    destructive=False,
    requires_confirmation=True,
    writes_files=False,
    external=True,
    notes=[
        "Loads and executes user Python code in-process; review the script before running.",
        "File writes are controlled by execution/output policy unless the user script performs its own side effects.",
        "Hook functions reuse AudioCLI's existing hook loading and return-type validation.",
    ],
)
_ACLI_SCRIPT_SAFETY = SafetySemantics(
    classification="external_cli_script",
    destructive=False,
    requires_confirmation=True,
    writes_files=True,
    external=True,
    notes=[
        ".acli scripts execute saved AudioCLI commands through the CLI adapter.",
        "Strict mode aborts on the first failing line; non-strict mode records failures and continues.",
        "The CLI adapter is imported lazily only when a script node executes.",
    ],
)

_KNOWN_PARAMETER_CHOICES: dict[tuple[str, str], tuple[Any, ...]] = {
    ("bitdepth", "bits"): (8, 16, 24, 32),
    ("convert", "bitdepth"): (8, 16, 24, 32),
    ("convert", "format"): SUPPORTED_FORMATS,
    ("fade", "shape"): ("linear", "exp", "cosine"),
}
_KNOWN_PARAMETER_NORMALIZERS: dict[tuple[str, str], str] = {
    ("convert", "format"): "format",
}
_CAPABILITY_ALIASES: dict[str, str] = {
    "builtin.filtering.remove_silent": "builtin.destructive.remove_silent",
    "builtin.filter.vst": "builtin.external_plugin.vst",
    "builtin.plugin.vst": "builtin.external_plugin.vst",
}


def list_capabilities(
    *,
    include_plugins: bool = False,
    chain_dir: str | Path | None = None,
) -> list[CapabilityNode]:
    """List GUI capability nodes without importing or invoking the CLI adapter.

    By default this returns first-party built-in filter operations only, giving
    the GUI a stable startup path that is not affected by third-party plugin
    discovery.  Callers may opt into plugin-backed registry entries later via
    ``include_plugins=True``.  Passing ``chain_dir`` also appends macro
    capabilities projected from native saved-chain files in that directory.
    """

    capabilities = [
        _analysis_info_capability(),
        _multi_output_chunk_capability(),
        _remove_silent_capability(),
        _vst_external_plugin_capability(),
        _external_script_hook_capability(),
        _acli_script_capability(),
    ]
    capabilities.extend(
        _op_info_to_capability(info)
        for info in list_ops(include_plugins=include_plugins)
        if info.name != "vst"
    )
    if chain_dir is not None:
        capabilities.extend(list_macro_capabilities(chain_dir))
    return capabilities


def get_capability(
    capability_id: str,
    *,
    include_plugins: bool = False,
    chain_dir: str | Path | None = None,
) -> CapabilityNode:
    """Return one capability by stable ID or operation name."""

    capability_id = _CAPABILITY_ALIASES.get(capability_id, capability_id)
    for capability in list_capabilities(include_plugins=include_plugins, chain_dir=chain_dir):
        if capability.id == capability_id or capability.operation_name == capability_id:
            return capability
    raise KeyError(capability_id)


def validate_capability_params(
    capability_id: str,
    params: dict[str, Any] | None,
    *,
    include_plugins: bool = False,
    chain_dir: str | Path | None = None,
) -> ValidationResult:
    """Validate parameters for a capability before any execution is attempted."""

    return get_capability(
        capability_id,
        include_plugins=include_plugins,
        chain_dir=chain_dir,
    ).validate_params(params)


def validate_parameters(
    parameters: list[CapabilityParameter],
    params: dict[str, Any],
) -> ValidationResult:
    """Validate and coerce raw parameters against capability parameter metadata."""

    errors: list[ValidationError] = []
    values: dict[str, Any] = {}
    by_name = {p.name: p for p in parameters}

    for raw_name in params:
        if raw_name not in by_name:
            errors.append(
                ValidationError(
                    parameter=raw_name,
                    code="unknown_parameter",
                    message=f"Unknown parameter '{raw_name}'.",
                    received=_received(params[raw_name]),
                )
            )

    for parameter in parameters:
        if parameter.name not in params:
            if parameter.required:
                errors.append(
                    ValidationError(
                        parameter=parameter.name,
                        code="missing_required",
                        message=f"Parameter '{parameter.name}' is required.",
                        expected_type=parameter.type,
                    )
                )
            else:
                values[parameter.name] = _json_safe(parameter.default)
            continue

        raw_value = params[parameter.name]
        if _is_missing(raw_value):
            if parameter.required:
                errors.append(
                    ValidationError(
                        parameter=parameter.name,
                        code="missing_required",
                        message=f"Parameter '{parameter.name}' is required.",
                        expected_type=parameter.type,
                        received=_received(raw_value),
                    )
                )
            else:
                values[parameter.name] = _json_safe(parameter.default)
            continue

        ok, coerced, error_message = _coerce(raw_value, parameter.type)
        if not ok:
            errors.append(
                ValidationError(
                    parameter=parameter.name,
                    code="invalid_type",
                    message=(
                        error_message or f"Parameter '{parameter.name}' expects {parameter.type}."
                    ),
                    expected_type=parameter.type,
                    received=_received(raw_value),
                )
            )
            continue

        coerced = _normalize_value(coerced, parameter.normalizer)
        if parameter.min_value is not None and isinstance(coerced, int | float):
            below_minimum = (
                coerced <= parameter.min_value
                if parameter.min_exclusive
                else coerced < parameter.min_value
            )
            if below_minimum:
                errors.append(
                    ValidationError(
                        parameter=parameter.name,
                        code="below_minimum",
                        message=(
                            f"Parameter '{parameter.name}' must be "
                            f"{'>' if parameter.min_exclusive else '>='} "
                            f"{parameter.min_value}."
                        ),
                        expected_type=parameter.type,
                        received=_received(raw_value),
                    )
                )
                continue
        if parameter.choices and coerced not in parameter.choices:
            expected = _format_choices(parameter.choices)
            errors.append(
                ValidationError(
                    parameter=parameter.name,
                    code="invalid_choice",
                    message=f"Parameter '{parameter.name}' must be one of: {expected}.",
                    expected_type=parameter.type,
                    received=_received(raw_value),
                )
            )
            continue

        values[parameter.name] = _json_safe(coerced)

    return ValidationResult(valid=not errors, errors=errors, values=values)


def _validate_vst_external_plugin_params(params: dict[str, Any]) -> ValidationResult:
    """Validate VST/AU capability params before the plugin host is invoked."""

    errors: list[ValidationError] = []
    values: dict[str, Any] = {}

    for raw_name in params:
        if raw_name not in {"plugin_path", "params"}:
            errors.append(
                ValidationError(
                    parameter=raw_name,
                    code="unknown_parameter",
                    message=f"Unknown parameter '{raw_name}'.",
                    received=_received(params[raw_name]),
                )
            )

    raw_path = params.get("plugin_path")
    if _is_missing(raw_path):
        errors.append(
            ValidationError(
                parameter="plugin_path",
                code="missing_required",
                message="Parameter 'plugin_path' is required.",
                expected_type="Path",
                received=_received(raw_path) if "plugin_path" in params else "",
            )
        )
    elif not isinstance(raw_path, str | Path):
        errors.append(
            ValidationError(
                parameter="plugin_path",
                code="invalid_type",
                message=f"Expected path string, got {type(raw_path).__name__}.",
                expected_type="Path",
                received=_received(raw_path),
            )
        )
    else:
        plugin_path = Path(raw_path).expanduser()
        if not plugin_path.exists():
            errors.append(
                ValidationError(
                    parameter="plugin_path",
                    code="path_not_found",
                    message=f"Plugin path does not exist: {plugin_path}.",
                    expected_type="existing Path",
                    received=_received(raw_path),
                )
            )
        else:
            values["plugin_path"] = str(plugin_path)

    raw_entries = params.get("params", [])
    if _is_missing(raw_entries):
        values["params"] = []
    else:
        ok, serialized, entry_errors = _coerce_vst_param_entries(raw_entries)
        errors.extend(entry_errors)
        if ok:
            values["params"] = serialized

    return ValidationResult(valid=not errors, errors=errors, values=values)


def _validate_external_script_hook_params(params: dict[str, Any]) -> ValidationResult:
    """Validate a user Python hook capability without executing the hook function."""

    errors: list[ValidationError] = []
    values: dict[str, Any] = {}
    allowed = {"script_path", "function_name", "kwargs"}

    for raw_name in params:
        if raw_name not in allowed:
            errors.append(
                ValidationError(
                    parameter=raw_name,
                    code="unknown_parameter",
                    message=f"Unknown parameter '{raw_name}'.",
                    received=_received(params[raw_name]),
                )
            )

    script_path = _validate_existing_script_path(
        params.get("script_path"),
        parameter="script_path",
        suffix=".py",
        label="Hook script",
        errors=errors,
    )
    if script_path is not None:
        values["script_path"] = str(script_path)

    raw_func = params.get("function_name", "")
    if _is_missing(raw_func):
        values["function_name"] = ""
    elif isinstance(raw_func, str):
        values["function_name"] = raw_func.strip()
    else:
        errors.append(
            ValidationError(
                parameter="function_name",
                code="invalid_type",
                message="Parameter 'function_name' expects a string.",
                expected_type="str",
                received=_received(raw_func),
            )
        )

    ok, kwargs, kwargs_errors = _coerce_key_value_config(
        params.get("kwargs", {}),
        parameter="kwargs",
    )
    errors.extend(kwargs_errors)
    if ok:
        values["kwargs"] = kwargs

    return ValidationResult(valid=not errors, errors=errors, values=values)


def _validate_acli_script_params(params: dict[str, Any]) -> ValidationResult:
    """Validate a .acli script capability before execution."""

    errors: list[ValidationError] = []
    values: dict[str, Any] = {}
    allowed = {"script_path", "strict"}

    for raw_name in params:
        if raw_name not in allowed:
            errors.append(
                ValidationError(
                    parameter=raw_name,
                    code="unknown_parameter",
                    message=f"Unknown parameter '{raw_name}'.",
                    received=_received(params[raw_name]),
                )
            )

    script_path = _validate_existing_script_path(
        params.get("script_path"),
        parameter="script_path",
        suffix=".acli",
        label="AudioCLI script",
        errors=errors,
    )
    if script_path is not None:
        values["script_path"] = str(script_path)

    ok, strict, error_message = _coerce_bool(params.get("strict", False))
    if not ok:
        errors.append(
            ValidationError(
                parameter="strict",
                code="invalid_type",
                message=error_message or "Parameter 'strict' expects bool.",
                expected_type="bool",
                received=_received(params.get("strict")),
            )
        )
    else:
        values["strict"] = strict

    return ValidationResult(valid=not errors, errors=errors, values=values)


def _validate_existing_script_path(
    raw_path: Any,
    *,
    parameter: str,
    suffix: str,
    label: str,
    errors: list[ValidationError],
) -> Path | None:
    if _is_missing(raw_path):
        errors.append(
            ValidationError(
                parameter=parameter,
                code="missing_required",
                message=f"Parameter '{parameter}' is required.",
                expected_type="Path",
                received=_received(raw_path) if raw_path is not None else "",
            )
        )
        return None
    if not isinstance(raw_path, str | Path):
        errors.append(
            ValidationError(
                parameter=parameter,
                code="invalid_type",
                message=f"Expected path string, got {type(raw_path).__name__}.",
                expected_type="Path",
                received=_received(raw_path),
            )
        )
        return None
    script_path = Path(raw_path).expanduser()
    if not script_path.exists():
        errors.append(
            ValidationError(
                parameter=parameter,
                code="path_not_found",
                message=f"{label} path does not exist: {script_path}.",
                expected_type="existing Path",
                received=_received(raw_path),
            )
        )
        return None
    if not script_path.is_file():
        errors.append(
            ValidationError(
                parameter=parameter,
                code="not_a_file",
                message=f"{label} path is not a file: {script_path}.",
                expected_type="file Path",
                received=_received(raw_path),
            )
        )
        return None
    if script_path.suffix.lower() != suffix:
        errors.append(
            ValidationError(
                parameter=parameter,
                code="invalid_extension",
                message=f"{label} path must end with {suffix}.",
                expected_type=f"*{suffix}",
                received=_received(raw_path),
            )
        )
        return None
    return script_path


def _coerce_key_value_config(
    raw_entries: Any,
    *,
    parameter: str,
) -> tuple[bool, dict[str, Any], list[ValidationError]]:
    """Coerce UI key/value config into a kwargs mapping for hook nodes."""

    if _is_missing(raw_entries):
        return True, {}, []
    if isinstance(raw_entries, Mapping):
        return True, {str(key): _json_safe(value) for key, value in raw_entries.items()}, []
    if isinstance(raw_entries, str):
        raw_entries = [raw_entries]
    if not isinstance(raw_entries, list | tuple):
        return (
            False,
            {},
            [
                ValidationError(
                    parameter=parameter,
                    code="invalid_type",
                    message=(
                        f"Parameter '{parameter}' expects a mapping or repeatable key=value entries."
                    ),
                    expected_type="key_value",
                    received=_received(raw_entries),
                )
            ],
        )

    errors: list[ValidationError] = []
    kwargs: dict[str, Any] = {}
    cli_tokens: list[str] = []
    for index, entry in enumerate(raw_entries):
        parameter_name = f"{parameter}[{index}]"
        if isinstance(entry, Mapping):
            if "key" not in entry:
                errors.append(
                    ValidationError(
                        parameter=parameter_name,
                        code="malformed_parameter_entry",
                        message="Key/value entry object must contain a 'key' field.",
                        expected_type="key/value entry",
                        received=_received(entry),
                    )
                )
                continue
            key = str(entry.get("key") or "").strip().replace("-", "_")
            if not key:
                errors.append(
                    ValidationError(
                        parameter=parameter_name,
                        code="malformed_parameter_entry",
                        message="Key/value entry key must not be empty.",
                        expected_type="non-empty key",
                        received=_received(entry),
                    )
                )
                continue
            kwargs[key] = _json_safe(entry.get("value"))
            continue
        if isinstance(entry, str):
            token = entry.strip()
            if not token:
                continue
            if token.startswith("--"):
                cli_tokens.append(token)
            elif "=" in token:
                cli_tokens.append(f"--{token}")
            elif cli_tokens and cli_tokens[-1].startswith("--") and "=" not in cli_tokens[-1]:
                cli_tokens.append(token)
            else:
                cli_tokens.append(f"--{token}")
            continue
        errors.append(
            ValidationError(
                parameter=parameter_name,
                code="invalid_type",
                message="Key/value entry must be a key=value string or {key, value} object.",
                expected_type="key/value entry",
                received=_received(entry),
            )
        )

    if cli_tokens:
        try:
            from audiocli.hook import parse_extra_kwargs  # noqa: PLC0415

            kwargs.update(parse_extra_kwargs(cli_tokens))
        except Exception as e:
            errors.append(
                ValidationError(
                    parameter=parameter,
                    code="malformed_parameter_entry",
                    message=str(e),
                    expected_type="key=value",
                    received=_received(raw_entries),
                )
            )
    return not errors, _json_safe(kwargs), errors


def _coerce_vst_param_entries(raw_entries: Any) -> tuple[bool, list[str], list[ValidationError]]:
    """Serialize VST UI key/value parameter entries to AudioCLI's key=value list."""

    errors: list[ValidationError] = []
    serialized: list[str] = []

    if isinstance(raw_entries, Mapping):
        entries: list[Any] = [{"key": key, "value": value} for key, value in raw_entries.items()]
    elif isinstance(raw_entries, str):
        entries = [raw_entries]
    elif isinstance(raw_entries, list | tuple):
        entries = list(raw_entries)
    else:
        return (
            False,
            [],
            [
                ValidationError(
                    parameter="params",
                    code="invalid_type",
                    message=(
                        "Parameter 'params' expects a repeatable list of key=value strings "
                        "or {key, value} objects."
                    ),
                    expected_type="key_value_list",
                    received=_received(raw_entries),
                )
            ],
        )

    for index, entry in enumerate(entries):
        parameter_name = f"params[{index}]"
        if isinstance(entry, Mapping):
            if "key" not in entry:
                errors.append(
                    ValidationError(
                        parameter=parameter_name,
                        code="malformed_parameter_entry",
                        message="VST parameter entry object must contain a 'key' field.",
                        expected_type="key/value entry",
                        received=_received(entry),
                    )
                )
                continue
            key = str(entry.get("key") or "").strip()
            value = "" if entry.get("value") is None else str(entry.get("value"))
        elif isinstance(entry, str):
            if "=" not in entry:
                errors.append(
                    ValidationError(
                        parameter=parameter_name,
                        code="malformed_parameter_entry",
                        message=f"VST parameter entry must be in key=value form, got {entry!r}.",
                        expected_type="key=value",
                        received=_received(entry),
                    )
                )
                continue
            key, _, value = entry.partition("=")
            key = key.strip()
        else:
            errors.append(
                ValidationError(
                    parameter=parameter_name,
                    code="invalid_type",
                    message="VST parameter entry must be a key=value string or {key, value} object.",
                    expected_type="key/value entry",
                    received=_received(entry),
                )
            )
            continue

        if not key:
            errors.append(
                ValidationError(
                    parameter=parameter_name,
                    code="malformed_parameter_entry",
                    message="VST parameter entry key must not be empty.",
                    expected_type="non-empty key=value",
                    received=_received(entry),
                )
            )
            continue
        serialized.append(f"{key}={value}")

    return not errors, serialized, errors


def list_macro_capabilities(chain_dir: str | Path) -> list[CapabilityNode]:
    """Project native saved-chain files in ``chain_dir`` as macro capabilities."""

    directory = Path(chain_dir)
    if not directory.is_dir():
        return []

    capabilities: list[CapabilityNode] = []
    for path in sorted(directory.iterdir()):
        if not path.is_file() or not _is_native_chain_file(path):
            continue
        metadata = _read_chain_metadata(path)
        if metadata is None:
            continue
        capabilities.append(_chain_metadata_to_macro_capability(path, metadata))
    return capabilities


def _analysis_info_capability() -> CapabilityNode:
    parameters = [
        CapabilityParameter(
            name="pass_through",
            type="bool",
            display_name="Pass Through Audio",
            description=(
                "When true, keep the current audio file/buffer available to downstream nodes. "
                "When false, this node outputs metadata only and cannot feed audio filters."
            ),
            required=False,
            default=True,
            control_hint="checkbox",
        )
    ]
    defaults = {"pass_through": True}
    validation_state = validate_parameters(parameters, defaults)
    return CapabilityNode(
        id="builtin.analysis.info",
        type="analysis",
        display_name="File Info / Level Analysis",
        description="Analyze sample rate, channels, duration, peak/RMS dBFS, and LUFS without transforming audio.",
        input_shape=_AUDIO_IN,
        output_shape=_ANALYSIS_AUDIO_OUT,
        safety=_ANALYSIS_SAFETY,
        parameters=parameters,
        defaults=defaults,
        metadata={
            "analysis_kind": "file_info_levels",
            "metadata_output": True,
            "pass_through_default": True,
            "pass_through_parameter": "pass_through",
            "metadata_shape": _METADATA_OUT.to_view_model(),
            "result_schema": {
                "path": "str",
                "sr": "int",
                "channels": "int",
                "duration_s": "float",
                "peak_dbfs": "float",
                "rms_dbfs": "float",
                "lufs": "float|null",
            },
        },
        validation_state=validation_state,
        operation_name="info",
    )


def _multi_output_chunk_capability() -> CapabilityNode:
    parameters = [
        CapabilityParameter(
            name="seconds",
            type="float",
            display_name="Seconds",
            description="Length of each produced chunk in seconds. Must be greater than zero.",
            required=True,
            default=None,
            control_hint="number",
            min_value=0.0,
            min_exclusive=True,
        ),
        CapabilityParameter(
            name="pad",
            type="bool",
            display_name="Pad Final Chunk",
            description="Zero-pad the final chunk so every chunk is exactly seconds long.",
            required=False,
            default=True,
            control_hint="toggle",
        ),
    ]
    defaults = {"pad": True}
    validation_state = validate_parameters(parameters, {"seconds": 1.0, "pad": True})
    return CapabilityNode(
        id="builtin.multi_output.chunk",
        type="multi_output",
        display_name="Chunk",
        description="Split one audio file into many fixed-length chunk files.",
        input_shape=_AUDIO_IN,
        output_shape=_AUDIO_MANY_OUT,
        safety=_MULTI_OUTPUT_SAFETY,
        parameters=parameters,
        defaults=defaults,
        metadata={
            "multi_output": True,
            "expands_file_set": True,
            "downstream_behavior": "map_audio_filters_over_each_chunk_file",
            "output_name_pattern": "{source_stem}_{index}{source_suffix}",
        },
        validation_state=validation_state,
        operation_name="chunk",
    )


def _remove_silent_capability() -> CapabilityNode:
    parameters = [
        CapabilityParameter(
            name="threshold_db",
            type="float",
            display_name="Threshold Db",
            description="Files with level below this dBFS threshold are considered silent.",
            required=False,
            default=-60.0,
            control_hint="number",
        ),
        CapabilityParameter(
            name="metric",
            type="str",
            display_name="Metric",
            description="Level metric used for silence detection.",
            required=False,
            default="rms",
            control_hint="select",
            choices=["rms", "peak"],
        ),
    ]
    defaults = {"threshold_db": -60.0, "metric": "rms"}
    validation_state = validate_parameters(parameters, defaults)
    return CapabilityNode(
        id="builtin.destructive.remove_silent",
        type="destructive_filter",
        display_name="Remove Silent",
        description=(
            "Delete audio files whose RMS or peak level is below a threshold and "
            "filter them out of downstream execution."
        ),
        input_shape=_AUDIO_IN,
        output_shape=_DESTRUCTIVE_FILTER_OUT,
        safety=_DESTRUCTIVE_FILTER_SAFETY,
        parameters=parameters,
        defaults=defaults,
        metadata={
            "dry_run_supported": True,
            "destructive_filter": True,
            "filters_file_set": True,
            "affected_paths_parameter": "affected_paths",
            "result_statuses": ["kept", "removed", "failed", "cancelled"],
            "affected_summary_schema": {
                "removed_candidates": "list[str]",
                "kept": "list[str]",
                "failed": "list[dict[path,error]]",
                "cancelled": "list[str]",
            },
        },
        validation_state=validation_state,
        operation_name="remove_silent",
    )


def _vst_external_plugin_capability() -> CapabilityNode:
    parameters = [
        CapabilityParameter(
            name="plugin_path",
            type="Path",
            display_name="Plugin Path",
            description="Path to a VST3 (.vst3) plugin or, on macOS, an AU plugin bundle.",
            required=True,
            default=None,
            control_hint="path",
        ),
        CapabilityParameter(
            name="params",
            type="key_value_list",
            display_name="Plugin Parameters",
            description=(
                "Repeatable plugin parameter overrides. Each entry is serialized as key=value "
                "and passed to AudioCLI's existing VST host."
            ),
            required=False,
            default=[],
            control_hint="key_value_list",
            repeatable=True,
        ),
    ]
    return CapabilityNode(
        id="builtin.external_plugin.vst",
        type="external_plugin",
        display_name="VST / AU Plugin",
        description=(
            "Host a VST3 or AU plugin as an external processing node using a plugin path "
            "and manual key=value parameter overrides."
        ),
        input_shape=_AUDIO_IN,
        output_shape=_AUDIO_OUT,
        safety=_EXTERNAL_PLUGIN_SAFETY,
        parameters=parameters,
        defaults={"params": []},
        metadata={
            "validator": "vst_external_plugin",
            "external_plugin": True,
            "risk": "external-plugin",
            "risk_level": "third_party_native_code",
            "plugin_host": "pedalboard.load_plugin",
            "operation_name": "vst",
            "plugin_formats": ["VST3", "AU"],
            "default_scan_directories": macos_default_plugin_scan_directory_specs(),
            "parameter_serialization": "repeatable key=value strings",
            "platform_notes": [
                "VST3 plugins require a compatible plugin build for this operating system and CPU architecture.",
                "AU plugin bundles are supported by pedalboard on macOS only.",
                "Third-party native plugins can crash or hang the host process; warn users before execution.",
            ],
            "ui_warnings": [
                "External plugin code runs in-process and may be unstable.",
                "Plugin availability and behavior are platform-specific.",
            ],
        },
        validation_state=_validate_vst_external_plugin_params({}),
        operation_name="vst",
    )


def _external_script_hook_capability() -> CapabilityNode:
    parameters = [
        CapabilityParameter(
            name="script_path",
            type="Path",
            display_name="Python Hook Script",
            description="Path to a .py file containing an AudioBuffer hook function.",
            required=True,
            default=None,
            control_hint="path",
        ),
        CapabilityParameter(
            name="function_name",
            type="str",
            display_name="Function Name",
            description=(
                "Optional explicit function name. Empty uses AudioCLI's hook default search "
                "order: transform, process, then main."
            ),
            required=False,
            default="",
            control_hint="text",
        ),
        CapabilityParameter(
            name="kwargs",
            type="key_value",
            display_name="Hook Kwargs",
            description=(
                "Optional hook keyword arguments as a mapping or repeatable key=value entries. "
                "Values are parsed with the same bool/int/float/string behavior as the hook CLI."
            ),
            required=False,
            default={},
            control_hint="key_value_list",
            repeatable=True,
        ),
    ]
    return CapabilityNode(
        id="builtin.external_script.hook",
        type="external_script",
        display_name="Python Hook Script",
        description=(
            "Run a user Python hook as an external script transform while reusing AudioCLI's "
            "existing hook loading, kwargs parsing, and return-type checks."
        ),
        input_shape=_AUDIO_IN,
        output_shape=_AUDIO_OUT,
        safety=_EXTERNAL_SCRIPT_SAFETY,
        parameters=parameters,
        defaults={"function_name": "", "kwargs": {}},
        metadata={
            "validator": "external_script_hook",
            "external_script": True,
            "script_kind": "python_hook",
            "path_parameter": "script_path",
            "function_parameter": "function_name",
            "kwargs_parameter": "kwargs",
            "loader": "audiocli.hook.load_hook_function",
            "wrapper": "audiocli.hook.make_hook_op",
        },
        validation_state=_validate_external_script_hook_params({}),
        operation_name="hook",
    )


def _acli_script_capability() -> CapabilityNode:
    parameters = [
        CapabilityParameter(
            name="script_path",
            type="Path",
            display_name="AudioCLI Script",
            description="Path to a .acli script file containing one AudioCLI command per line.",
            required=True,
            default=None,
            control_hint="path",
        ),
        CapabilityParameter(
            name="strict",
            type="bool",
            display_name="Strict Mode",
            description=(
                "When true, abort the script on the first failing line. When false, run all "
                "parseable lines and report every failure."
            ),
            required=False,
            default=False,
            control_hint="toggle",
        ),
    ]
    return CapabilityNode(
        id="builtin.script.acli",
        type="script",
        display_name="AudioCLI .acli Script",
        description=(
            "Execute an existing .acli text automation script as an external script node. "
            "The script is treated as a whole-job side-effect action and passes audio files through."
        ),
        input_shape=_AUDIO_IN,
        output_shape=_AUDIO_OUT,
        safety=_ACLI_SCRIPT_SAFETY,
        parameters=parameters,
        defaults={"strict": False},
        metadata={
            "validator": "acli_script",
            "external_script": True,
            "script_kind": "acli",
            "path_parameter": "script_path",
            "strict_parameter": "strict",
            "runner": "audiocli.run_script.run_script",
            "strict_semantics": "abort_on_first_failure",
            "non_strict_semantics": "record_failures_and_continue",
            "pass_through": True,
            "lazy_cli_import": True,
        },
        validation_state=_validate_acli_script_params({}),
        operation_name="script",
    )


def _op_info_to_capability(info: OpInfo) -> CapabilityNode:
    parameters = [_param_info_to_capability_param(info.name, param) for param in info.params]
    defaults = {p.name: _json_safe(p.default) for p in parameters if not p.required}
    validation_state = validate_parameters(parameters, defaults)
    return CapabilityNode(
        id=f"builtin.filter.{info.name}",
        type="built_in_filter",
        display_name=_display_name(info.name),
        description=info.help,
        input_shape=_AUDIO_IN,
        output_shape=_AUDIO_OUT,
        safety=_FILTER_SAFETY,
        parameters=parameters,
        defaults=defaults,
        validation_state=validation_state,
        operation_name=info.name,
    )


def _chain_metadata_to_macro_capability(path: Path, metadata: dict[str, Any]) -> CapabilityNode:
    resolved = path.resolve()
    chain_id = str(metadata["id"])
    defaults = {
        "path": str(resolved),
        "chain_id": chain_id,
        "schema_version": int(metadata.get("schema_version", 1)),
    }
    parameters = [
        CapabilityParameter(
            name="path",
            type="Path",
            display_name="Chain File",
            description="Native saved-chain file backing this macro node.",
            required=False,
            default=str(resolved),
            control_hint="path",
        ),
        CapabilityParameter(
            name="chain_id",
            type="str",
            display_name="Chain Id",
            description="Saved chain id used for validation and diagnostics.",
            required=False,
            default=chain_id,
            control_hint="text",
        ),
        CapabilityParameter(
            name="schema_version",
            type="int",
            display_name="Schema Version",
            description="Native saved-chain schema version.",
            required=False,
            default=int(metadata.get("schema_version", 1)),
            control_hint="number",
        ),
    ]
    validation_state = validate_parameters(parameters, defaults)
    name = str(metadata.get("name") or _display_name(_chain_file_stem(path)))
    description = str(
        metadata.get("description") or metadata.get("notes") or "Saved AudioCLI chain."
    )
    return CapabilityNode(
        id=_macro_capability_id(path),
        type="saved_chain_macro",
        display_name=name,
        description=description,
        input_shape=_AUDIO_IN,
        output_shape=_AUDIO_OUT,
        safety=_MACRO_SAFETY,
        parameters=parameters,
        defaults=defaults,
        validation_state=validation_state,
        operation_name="",
    )


def _read_chain_metadata(path: Path) -> dict[str, Any] | None:
    try:
        raw = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(raw, dict):
        return None
    schema_version = raw.get("schema_version")
    if isinstance(schema_version, bool) or not isinstance(schema_version, int):
        return None
    if schema_version != 1:
        return None
    if raw.get("kind") != "audiocli.saved_chain":
        return None
    if not isinstance(raw.get("id"), str) or not isinstance(raw.get("nodes"), list):
        return None
    return raw


def _macro_capability_id(path: Path) -> str:
    stem = _sanitize_id_part(_chain_file_stem(path))
    digest = hashlib.sha1(str(path.resolve()).encode("utf-8")).hexdigest()[:8]
    return f"saved.chain.{stem}.{digest}"


def _chain_file_stem(path: Path) -> str:
    name = path.name
    if name.endswith(".audiocli-chain.json"):
        return name[: -len(".audiocli-chain.json")]
    if name.endswith(".aclichain"):
        return name[: -len(".aclichain")]
    return path.stem


def _is_native_chain_file(path: Path) -> bool:
    name = path.name
    return name.endswith((".aclichain", ".audiocli-chain.json"))


def _sanitize_id_part(value: str) -> str:
    sanitized = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower()).strip("-")
    return sanitized or "chain"


def _param_info_to_capability_param(op_name: str, param: ParamInfo) -> CapabilityParameter:
    choices = _parameter_choices(op_name, param)
    return CapabilityParameter(
        name=param.name,
        type=param.type,
        display_name=_display_name(param.name),
        description=param.help,
        required=param.required,
        default=_json_safe(param.default),
        control_hint=_control_hint(param.type, choices),
        choices=choices,
        normalizer=_KNOWN_PARAMETER_NORMALIZERS.get((op_name, param.name), ""),
    )


def _display_name(name: str) -> str:
    return name.replace("_", " ").replace("-", " ").title()


def _parameter_choices(op_name: str, param: ParamInfo) -> list[Any]:
    known = _KNOWN_PARAMETER_CHOICES.get((op_name, param.name), ())
    choices = list(param.choices) or list(known)
    if choices and known:
        choices = [choice for choice in choices if choice in known]
        choices.extend(choice for choice in known if choice not in choices)
    return [_json_safe(choice) for choice in choices]


def _control_hint(type_name: str, choices: list[Any] | None = None) -> str:
    if choices:
        return "select"
    if type_name in {"int", "float"}:
        return "number"
    if type_name == "bool":
        return "toggle"
    if type_name == "Path":
        return "path"
    return "text"


def _normalize_value(value: Any, normalizer: str) -> Any:
    if normalizer == "format" and isinstance(value, str):
        return value.lower().lstrip(".")
    return value


def _format_choices(choices: list[Any]) -> str:
    return ", ".join(str(choice) for choice in choices)


def _coerce(value: Any, type_name: str) -> tuple[bool, Any, str]:
    if type_name == "int":
        return _coerce_int(value)
    if type_name == "float":
        return _coerce_float(value)
    if type_name == "bool":
        return _coerce_bool(value)
    if type_name == "str":
        return True, str(value), ""
    if type_name == "Path":
        if isinstance(value, Path):
            return True, str(value), ""
        if isinstance(value, str):
            return True, value, ""
        return False, None, f"Expected path string, got {type(value).__name__}."
    # Unknown or richer registry types are left to the operation itself for now.
    return True, _json_safe(value), ""


def _coerce_int(value: Any) -> tuple[bool, int | None, str]:
    if isinstance(value, bool):
        return False, None, f"Expected int, got {type(value).__name__}."
    if isinstance(value, int):
        return True, value, ""
    if isinstance(value, float):
        if not math.isfinite(value):
            return False, None, f"Expected finite int, got {value!r}."
        if value.is_integer():
            return True, int(value), ""
    if isinstance(value, str):
        try:
            return True, int(value.strip()), ""
        except ValueError:
            return False, None, f"Expected int, got {value!r}."
    return False, None, f"Expected int, got {type(value).__name__}."


def _coerce_float(value: Any) -> tuple[bool, float | None, str]:
    if isinstance(value, bool):
        return False, None, f"Expected float, got {type(value).__name__}."
    if isinstance(value, int | float):
        coerced = float(value)
        if not math.isfinite(coerced):
            return False, None, f"Expected finite float, got {value!r}."
        return True, coerced, ""
    if isinstance(value, str):
        try:
            coerced = float(value.strip())
        except ValueError:
            return False, None, f"Expected float, got {value!r}."
        if not math.isfinite(coerced):
            return False, None, f"Expected finite float, got {value!r}."
        return True, coerced, ""
    return False, None, f"Expected float, got {type(value).__name__}."


def _coerce_bool(value: Any) -> tuple[bool, bool | None, str]:
    if isinstance(value, bool):
        return True, value, ""
    if isinstance(value, int) and value in {0, 1}:
        return True, bool(value), ""
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True, True, ""
        if normalized in {"0", "false", "no", "off"}:
            return True, False, ""
        return False, None, f"Expected bool, got {value!r}."
    return False, None, f"Expected bool, got {type(value).__name__}."


def _is_missing(value: Any) -> bool:
    return value is None or (isinstance(value, str) and value == "")


def _received(value: Any) -> str:
    return f"{type(value).__name__}: {value!r}"


def _json_safe(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, tuple):
        return [_json_safe(v) for v in value]
    if isinstance(value, list):
        return [_json_safe(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, float):
        return value if math.isfinite(value) else str(value)
    if value is None or isinstance(value, str | int | bool):
        return value
    return repr(value)
