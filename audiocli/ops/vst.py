"""``vst`` — host any VST3 or AU plugin via pedalboard's plugin host.

This is a first-party special-case op. The parameter shape of a real
plugin is dynamic (it depends on the loaded VST3/AU), so we don't expose
each plugin parameter as its own CLI flag. Instead, the CLI takes a
``--plugin-path`` and a repeatable ``--param key=value`` option, and
parameter values are coerced against the plugin's reported metadata.

Heavy imports (``pedalboard``, ``numpy``) stay inside the function body
to keep ``audiocli --help`` fast.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any

import typer

from audiocli.buffer import AudioBuffer
from audiocli.errors import OpError
from audiocli.registry import op


@op(
    name="vst",
    help=(
        "Host a VST3 or AU plugin and apply it to each file. "
        "Use repeatable --param key=value to override plugin parameters."
    ),
)
def vst(
    buf: AudioBuffer,
    plugin_path: Annotated[
        Path,
        typer.Option(
            "--plugin-path",
            help="Path to a VST3 (.vst3) or, on macOS, AU plugin bundle.",
            exists=True,
            readable=True,
        ),
    ],
    params: Annotated[
        list[str],
        typer.Option(
            "--param",
            help='Plugin parameter override, in "key=value" form. Repeatable.',
        ),
    ] = (),
) -> AudioBuffer:
    """Load ``plugin_path``, apply parameter overrides, and process ``buf``.

    Re-instantiates the plugin per call so a buggy plugin can't taint
    state across files.
    """
    import numpy as np  # noqa: PLC0415

    plugin_path = Path(plugin_path).expanduser()
    plugin = _load_plugin(plugin_path)
    overrides = _parse_param_strings(list(params))
    _apply_param_overrides(plugin, overrides)

    try:
        out = plugin.process(buf.data, sample_rate=float(buf.sr), reset=True)
    except Exception as e:
        raise OpError(f"vst: plugin '{plugin_path.name}' failed during processing: {e}") from e

    if out.dtype != np.float32:
        out = out.astype(np.float32, copy=False)
    return AudioBuffer(data=out, sr=buf.sr, subtype=buf.subtype)


def _load_plugin(plugin_path: Path) -> Any:
    """Load a plugin from disk; raise ``OpError`` on any failure."""
    if not plugin_path.exists():
        raise OpError(f"vst: plugin file not found: {plugin_path}")

    try:
        from pedalboard import load_plugin  # noqa: PLC0415
    except ImportError as e:  # pragma: no cover
        raise OpError(f"vst: pedalboard is not installed: {e}") from e

    try:
        return load_plugin(str(plugin_path))
    except Exception as e:
        raise OpError(f"vst: failed to load plugin '{plugin_path}': {e}") from e


def _parse_param_strings(raw: list[str]) -> dict[str, str]:
    """Parse ``["key=value", ...]`` into a dict; raise ``OpError`` on bad shape."""
    out: dict[str, str] = {}
    for item in raw:
        if "=" not in item:
            raise OpError(f"vst: --param expects 'key=value', got {item!r} (missing '=')")
        key, _, value = item.partition("=")
        key = key.strip()
        if not key:
            raise OpError(f"vst: --param has empty key: {item!r}")
        out[key] = value
    return out


def _apply_param_overrides(plugin: Any, overrides: dict[str, str]) -> None:
    """Coerce each ``key=value`` against the plugin's parameter metadata.

    Raises ``OpError`` for unknown names or values that don't fit the
    parameter's declared type.
    """
    if not overrides:
        return

    plugin_params = getattr(plugin, "parameters", {}) or {}
    valid_keys = sorted(plugin_params.keys())

    for raw_key, raw_value in overrides.items():
        key = _resolve_param_key(raw_key, plugin_params)
        if key is None:
            valid_hint = ", ".join(valid_keys) if valid_keys else "(no parameters reported)"
            raise OpError(f"vst: unknown parameter {raw_key!r}; valid keys: {valid_hint}")

        meta = plugin_params[key]
        coerced = _coerce_value(key, raw_value, meta)
        try:
            setattr(plugin, key, coerced)
        except Exception as e:
            raise OpError(f"vst: failed to set parameter {key!r}={raw_value!r}: {e}") from e


def _resolve_param_key(raw_key: str, plugin_params: dict[str, Any]) -> str | None:
    """Match a CLI key against the plugin's identifier dict, case-insensitively."""
    if raw_key in plugin_params:
        return raw_key
    lowered = raw_key.lower().replace(" ", "_")
    for k in plugin_params:
        if k.lower() == lowered:
            return k
    return None


def _coerce_value(key: str, raw: str, meta: Any) -> Any:
    """Coerce ``raw`` to match ``meta``'s declared type.

    Pedalboard's parameter objects expose ``type`` (a Python type like
    ``float`` / ``bool`` / ``int`` / ``str``) and, for choice parameters,
    a ``valid_values`` / ``valid_strings`` listing.
    """
    declared = getattr(meta, "type", None)
    valid_values = getattr(meta, "valid_values", None) or getattr(meta, "valid_strings", None)

    if declared is bool:
        return _coerce_bool(key, raw)
    if declared is int:
        return _coerce_int(key, raw)
    if declared is float:
        return _coerce_float(key, raw)
    if valid_values:
        if raw in valid_values:
            return raw
        # case-insensitive fallback
        for v in valid_values:
            if isinstance(v, str) and v.lower() == raw.lower():
                return v
        raise OpError(f"vst: parameter {key!r} expected one of {list(valid_values)!r}, got {raw!r}")
    # Default: pass through as string. Many pedalboard params accept str.
    return raw


def _coerce_bool(key: str, raw: str) -> bool:
    low = raw.strip().lower()
    if low in {"1", "true", "yes", "on"}:
        return True
    if low in {"0", "false", "no", "off"}:
        return False
    raise OpError(f"vst: parameter {key!r} expects a bool, got {raw!r}")


def _coerce_int(key: str, raw: str) -> int:
    try:
        return int(raw)
    except ValueError as e:
        raise OpError(f"vst: parameter {key!r} expects an int, got {raw!r}") from e


def _coerce_float(key: str, raw: str) -> float:
    try:
        return float(raw)
    except ValueError as e:
        raise OpError(f"vst: parameter {key!r} expects a float, got {raw!r}") from e
