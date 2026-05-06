"""Generic capability parameter validation."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from audiocli.capability_models import (
    CapabilityParameter,
    ValidationError,
    ValidationResult,
    json_safe,
)


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
                    received=received(params[raw_name]),
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
                values[parameter.name] = json_safe(parameter.default)
            continue

        raw_value = params[parameter.name]
        if is_missing(raw_value):
            if parameter.required:
                errors.append(
                    ValidationError(
                        parameter=parameter.name,
                        code="missing_required",
                        message=f"Parameter '{parameter.name}' is required.",
                        expected_type=parameter.type,
                        received=received(raw_value),
                    )
                )
            else:
                values[parameter.name] = json_safe(parameter.default)
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
                    received=received(raw_value),
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
                        received=received(raw_value),
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
                    received=received(raw_value),
                )
            )
            continue

        values[parameter.name] = json_safe(coerced)

    return ValidationResult(valid=not errors, errors=errors, values=values)


def coerce_bool(value: Any) -> tuple[bool, bool | None, str]:
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


def is_missing(value: Any) -> bool:
    return value is None or (isinstance(value, str) and value == "")


def received(value: Any) -> str:
    return f"{type(value).__name__}: {value!r}"


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
        return coerce_bool(value)
    if type_name == "str":
        return True, str(value), ""
    if type_name == "Path":
        if isinstance(value, Path):
            return True, str(value), ""
        if isinstance(value, str):
            return True, value, ""
        return False, None, f"Expected path string, got {type(value).__name__}."
    return True, json_safe(value), ""


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
