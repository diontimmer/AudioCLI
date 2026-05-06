"""GUI-neutral capability and validation view models."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


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
            "default": json_safe(self.default),
            "control_hint": self.control_hint,
            "choices": json_safe(self.choices),
            "min_value": json_safe(self.min_value),
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
            "values": json_safe(self.values),
        }


def json_safe(value: Any) -> Any:
    """Return a JSON-safe representation used by capability view models."""

    if isinstance(value, Path):
        return str(value)
    if isinstance(value, tuple):
        return [json_safe(v) for v in value]
    if isinstance(value, list):
        return [json_safe(v) for v in value]
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, float):
        return value if math.isfinite(value) else str(value)
    if value is None or isinstance(value, str | int | bool):
        return value
    return repr(value)
