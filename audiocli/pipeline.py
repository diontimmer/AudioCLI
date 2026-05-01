"""Single-file pipeline runner.

This is the v1 of the pipeline that ships with the tracer slice. Issue #02
extends it with parallelism, per-file `Result` records and a `JobReport`.
The function signature here is the one #02 will widen, not a throwaway.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from audiocli.errors import OpError
from audiocli.io import load, save
from audiocli.registry import Op


def run_one(
    path: str | Path,
    op: Op,
    params: dict[str, Any],
    output: str | Path | None = None,
) -> Path:
    """Load `path`, apply `op(buf, **params)`, write the result.

    `output` semantics:
      - ``None`` → write next to the source as ``<stem>_<op>.<ext>``.
      - existing directory → ``<dir>/<source-name>``.
      - non-existing path with no suffix → treated as a directory; created.
      - non-existing path with a suffix → treated as a file path.

    Returns the path written. Re-raises `LoadError`/`SaveError` from I/O,
    wraps any op-thrown exception as `OpError`.
    """
    src = Path(path)
    buf = load(src)

    try:
        out_buf = op.func(buf, **params)
    except Exception as e:
        raise OpError(f"op '{op.name}' failed on {src}: {e}") from e

    dst = _resolve_output(src, Path(output) if output is not None else None, op.name)
    save(dst, out_buf, subtype=out_buf.subtype)
    return dst


def _resolve_output(src: Path, output: Path | None, op_name: str) -> Path:
    if output is None:
        return src.with_name(f"{src.stem}_{op_name}{src.suffix}")
    if output.exists() and output.is_dir():
        return output / src.name
    if not output.suffix:
        output.mkdir(parents=True, exist_ok=True)
        return output / src.name
    return output
