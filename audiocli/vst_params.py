"""Shared VST/AU plugin parameter serialization and coercion."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from typing import Any

from audiocli.errors import OpError


def normalize_param_entries(raw: Any) -> list[str]:
    """Return AudioCLI's repeatable ``key=value`` VST parameter entries."""

    if raw is None:
        return []
    if isinstance(raw, str):
        return [raw]
    if isinstance(raw, Mapping):
        return [f"{key}={'' if value is None else value}" for key, value in raw.items()]
    entries: list[str] = []
    if isinstance(raw, Sequence):
        for item in raw:
            if isinstance(item, str):
                entries.append(item)
            elif isinstance(item, Mapping):
                key = str(item.get("key") or "").strip()
                if key:
                    entries.append(
                        f"{key}={'' if item.get('value') is None else item.get('value')}"
                    )
            elif item is not None:
                entries.append(str(item))
    return entries


def parse_param_strings(raw: list[str], *, label: str = "--param") -> dict[str, str]:
    """Parse ``["key=value", ...]`` into a dict; raise ``OpError`` on bad shape."""

    out: dict[str, str] = {}
    for item in raw:
        if "=" not in item:
            raise OpError(f"vst: {label} expects 'key=value', got {item!r} (missing '=')")
        key, _, value = item.partition("=")
        key = key.strip()
        if not key:
            raise OpError(f"vst: {label} has empty key: {item!r}")
        out[key] = value
    return out


def apply_serialized_params(plugin: Any, raw_params: Any, *, label: str = "--param") -> None:
    """Apply serialized AudioCLI VST params to a loaded plugin object."""

    entries = normalize_param_entries(raw_params)
    overrides = parse_param_strings(entries, label=label)
    apply_param_overrides(plugin, overrides)


def apply_param_overrides(plugin: Any, overrides: Mapping[str, str]) -> None:
    """Coerce each parameter override against Pedalboard metadata and set it."""

    if not overrides:
        return

    plugin_params = getattr(plugin, "parameters", {}) or {}
    valid_keys = sorted(str(key) for key in plugin_params)

    for raw_key, raw_value in overrides.items():
        key = resolve_param_key(str(raw_key), plugin_params)
        if key is None:
            valid_hint = ", ".join(valid_keys) if valid_keys else "(no parameters reported)"
            raise OpError(f"vst: unknown parameter {raw_key!r}; valid keys: {valid_hint}")

        meta = plugin_params[key]
        coerced = coerce_value(key, raw_value, meta)
        try:
            setattr(plugin, key, coerced)
        except Exception as exc:
            raise OpError(f"vst: failed to set parameter {key!r}={raw_value!r}: {exc}") from exc


def resolve_param_key(raw_key: str, plugin_params: Mapping[str, Any]) -> str | None:
    """Match a serialized key against plugin parameters, case-insensitively."""

    if raw_key in plugin_params:
        return raw_key
    lowered = raw_key.lower().replace(" ", "_")
    for key in plugin_params:
        key_text = str(key)
        if key_text.lower() == lowered:
            return key_text
    return None


def coerce_value(key: str, raw: Any, meta: Any) -> Any:
    """Coerce a serialized value to match a Pedalboard parameter's metadata."""

    raw_text = str(raw)
    declared = getattr(meta, "type", None)
    valid_values = getattr(meta, "valid_values", None) or getattr(meta, "valid_strings", None)

    if declared is bool:
        return coerce_bool(key, raw_text)
    if declared is int:
        return coerce_int(key, raw_text)
    if declared is float:
        return coerce_float(key, raw_text)
    if valid_values:
        if raw in valid_values or raw_text in valid_values:
            return raw
        for value in valid_values:
            if isinstance(value, str) and value.lower() == raw_text.lower():
                return value
        raise OpError(f"vst: parameter {key!r} expected one of {list(valid_values)!r}, got {raw!r}")
    return raw_text


def coerce_bool(key: str, raw: str) -> bool:
    low = raw.strip().lower()
    if low in {"1", "true", "yes", "on"}:
        return True
    if low in {"0", "false", "no", "off"}:
        return False
    raise OpError(f"vst: parameter {key!r} expects a bool, got {raw!r}")


def coerce_int(key: str, raw: str) -> int:
    try:
        return int(raw)
    except ValueError as exc:
        raise OpError(f"vst: parameter {key!r} expects an int, got {raw!r}") from exc


def coerce_float(key: str, raw: str) -> float:
    try:
        return float(raw)
    except ValueError as exc:
        raise OpError(f"vst: parameter {key!r} expects a float, got {raw!r}") from exc


def serialize_parameter_snapshot(plugin: Any) -> list[dict[str, Any]]:
    """Serialize Pedalboard-reported plugin parameters to JSON-safe dicts."""

    plugin_params = getattr(plugin, "parameters", {}) or {}
    snapshot: list[dict[str, Any]] = []
    for key, meta in plugin_params.items():
        key_text = str(key)
        value = current_parameter_value(plugin, key_text, meta)
        declared = getattr(meta, "type", None)
        choices = first_attr(meta, ("valid_values", "valid_strings", "choices"))
        entry: dict[str, Any] = {
            "key": key_text,
            "display_name": str(first_attr(meta, ("display_name", "name", "label")) or key_text),
            "value": json_safe(value),
            "raw_value": json_safe(first_attr(meta, ("raw_value", "value")) or value),
            "type": type_name(declared),
            "label": str(first_attr(meta, ("unit", "units", "label")) or ""),
        }
        if choices is not None:
            entry["choices"] = [json_safe(choice) for choice in list(choices)]
        snapshot.append(entry)
    return snapshot


def snapshot_to_param_entries(snapshot: list[dict[str, Any]]) -> list[str]:
    """Serialize a mirrored parameter snapshot as AudioCLI ``key=value`` entries."""

    entries: list[str] = []
    for parameter in snapshot:
        key = str(parameter.get("key") or "").strip()
        if not key:
            continue
        value = parameter.get("value", parameter.get("raw_value", ""))
        entries.append(f"{key}={'' if value is None else value}")
    return entries


def current_parameter_value(plugin: Any, key: str, meta: Any) -> Any:
    try:
        return getattr(plugin, key)
    except Exception:
        pass
    return first_attr(meta, ("raw_value", "value", "default_value", "default"))


def first_attr(obj: Any, names: tuple[str, ...]) -> Any:
    for name in names:
        try:
            value = getattr(obj, name)
        except Exception:
            continue
        if value is not None:
            return value
    return None


def type_name(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, type):
        return value.__name__
    return str(value)


def json_safe(value: Any) -> Any:
    if isinstance(value, float) and not math.isfinite(value):
        return str(value)
    if value is None or isinstance(value, str | int | float | bool):
        return value
    try:
        json.dumps(value, allow_nan=False)
    except (TypeError, ValueError):
        return str(value)
    return value
