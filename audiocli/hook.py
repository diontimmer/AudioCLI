"""User-supplied Python script loader for the ``hook`` escape hatch.

The ``hook`` command lets power users drop a Python file with a single
function ``(buf: AudioBuffer, **kwargs) -> AudioBuffer`` into the filesystem
and run it across a target set without packaging a plugin. This module
isolates the importlib dance and the function-discovery rules so the CLI
layer stays a thin Typer wrapper.

Library code only — no ``print``, no ``sys.exit``. Bad inputs raise
``AudioCLIError`` subclasses so the CLI can render a clean message.
"""

from __future__ import annotations

import importlib.util
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from audiocli.errors import AudioCLIError, OpError
from audiocli.registry import Op

# Function names ``hook`` will look for, in order, when ``--func`` is not given.
# ``transform`` and ``process`` cover the names users intuitively reach for;
# ``main`` is the fallback for one-off scripts that double as ``__main__``.
DEFAULT_FUNC_NAMES: tuple[str, ...] = ("transform", "process", "main")


def load_hook_function(script: Path, func_name: str | None = None) -> Callable[..., Any]:
    """Import ``script`` and return the named (or default) function.

    Args:
        script: path to a ``.py`` file the user wants to run as a one-off op.
        func_name: explicit function name. ``None`` falls back to the names
            in :data:`DEFAULT_FUNC_NAMES`, in order.

    Raises:
        AudioCLIError: if the script does not exist or fails to import.
        OpError: if no suitable function was found inside the loaded module.
    """
    script = Path(script)
    if not script.exists():
        raise AudioCLIError(f"hook script not found: {script}")
    if not script.is_file():
        raise AudioCLIError(f"hook script is not a file: {script}")

    module_name = f"_audiocli_hook_{abs(hash(str(script.resolve())))}"
    spec = importlib.util.spec_from_file_location(module_name, script)
    if spec is None or spec.loader is None:
        raise AudioCLIError(f"could not build import spec for hook script: {script}")

    module = importlib.util.module_from_spec(spec)
    # Register before exec so the script can reference its own module name
    # (e.g. for ``__main__``-style guard checks) without breaking.
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception as e:
        # Drop the half-loaded module so a re-run gets a clean import.
        sys.modules.pop(module_name, None)
        raise OpError(f"hook script {script} failed to import: {e}") from e

    if func_name is not None:
        candidate = getattr(module, func_name, None)
        if candidate is None:
            raise OpError(
                f"hook script {script} has no function named '{func_name}'",
            )
        if not callable(candidate):
            raise OpError(
                f"hook script {script}: '{func_name}' is not callable",
            )
        return candidate

    for name in DEFAULT_FUNC_NAMES:
        candidate = getattr(module, name, None)
        if callable(candidate):
            return candidate

    raise OpError(
        f"hook script {script} defines none of "
        f"{', '.join(DEFAULT_FUNC_NAMES)}; pass --func to name one explicitly",
    )


def make_hook_op(func: Callable[..., Any], script: Path) -> Op:
    """Wrap a user function as a one-off :class:`Op` for the pipeline.

    The returned op is *not* added to the global registry — it lives only
    for the duration of the current ``run_per_file`` invocation. The wrapper
    validates the return type so a buggy user function fails with a clean
    :class:`OpError` instead of a tangled traceback inside the saver.
    """
    from audiocli.buffer import AudioBuffer  # noqa: PLC0415

    op_name = f"hook:{Path(script).stem}"

    def _wrapped(buf: AudioBuffer, **kwargs: Any) -> AudioBuffer:
        try:
            out = func(buf, **kwargs)
        except TypeError as e:
            # Most likely the user function has a bad signature
            # (e.g. takes a list, takes *args only, declines our kwargs).
            raise OpError(
                f"hook script {script}: function signature rejected the buffer / kwargs: {e}",
            ) from e
        if not isinstance(out, AudioBuffer):
            raise OpError(
                f"hook script {script}: function must return an AudioBuffer, "
                f"got {type(out).__name__}",
            )
        return out

    _wrapped.__name__ = op_name
    return Op(name=op_name, help=f"User hook from {script}", func=_wrapped)


def parse_extra_kwargs(extras: list[str]) -> dict[str, Any]:
    """Parse leftover ``--key=value`` / ``--key value`` tokens into a dict.

    Typer's ``allow_extra_args`` hands us a flat list of unknown tokens.
    We accept both ``--key=value`` and ``--key value`` forms, and coerce
    values to ``int`` / ``float`` / ``bool`` when they parse cleanly so
    users can write ``--gain-db=6`` without quoting numbers. Hyphens in
    keys map to underscores so ``--gain-db`` becomes ``gain_db``.
    """
    out: dict[str, Any] = {}
    i = 0
    while i < len(extras):
        tok = extras[i]
        if not tok.startswith("--"):
            raise AudioCLIError(
                f"unexpected positional argument to hook: {tok!r} (use --key=value to pass kwargs)",
            )
        body = tok[2:]
        if "=" in body:
            key, raw = body.split("=", 1)
            i += 1
        else:
            key = body
            if i + 1 >= len(extras) or extras[i + 1].startswith("--"):
                # Bare ``--flag`` → boolean True.
                out[key.replace("-", "_")] = True
                i += 1
                continue
            raw = extras[i + 1]
            i += 2
        out[key.replace("-", "_")] = _coerce(raw)
    return out


def _coerce(raw: str) -> Any:
    """Best-effort coerce a CLI token to bool / int / float / str."""
    low = raw.lower()
    if low in {"true", "yes", "on"}:
        return True
    if low in {"false", "no", "off"}:
        return False
    try:
        if "." not in raw and "e" not in low:
            return int(raw)
    except ValueError:
        pass
    try:
        return float(raw)
    except ValueError:
        return raw
