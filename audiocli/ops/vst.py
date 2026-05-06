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
from audiocli.vst_params import (
    apply_param_overrides as _apply_param_overrides,
)
from audiocli.vst_params import (
    coerce_value as _coerce_value,
)
from audiocli.vst_params import (
    parse_param_strings as _parse_param_strings,
)

__all__ = ["_apply_param_overrides", "_coerce_value", "_parse_param_strings", "vst"]


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
