"""Output path policy for per-file audio operations."""

from __future__ import annotations

import errno
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from audiocli.io import extension_for_format, format_for_extension


def resolve_output_preview(src: Path, output: Path | None, op_name: str) -> Path:
    """Pick the destination path for one source file without mutating disk.

    This mirrors :func:`resolve_output`'s path policy, including the
    ``FileExistsError`` raised when a suffixless output path already exists as
    a non-directory file.  The only difference is that a new suffixless output
    directory is not created during preview.
    """
    if output is None:
        return src.with_name(f"{src.stem}_{op_name}{src.suffix}")
    if output.exists():
        if output.is_dir():
            return output / src.name
        if not output.suffix:
            raise FileExistsError(errno.EEXIST, "File exists", str(output))
    if not output.suffix:
        return output / src.name
    return output


def resolve_output(src: Path, output: Path | None, op_name: str) -> Path:
    """Pick the destination path for one source file.

    ``None`` writes alongside the source as ``<stem>_<op>.<ext>``.
    An existing directory, or a suffixless path, writes ``<dir>/<source-name>``.
    A path with a suffix is treated as the exact destination file.
    """
    if output is not None and not output.suffix:
        dst = output / src.name
        try:
            output.mkdir(parents=True, exist_ok=True)
        except FileExistsError as e:
            if output.is_dir():
                return dst
            raise FileExistsError(errno.EEXIST, "File exists", str(output)) from e
        if not output.is_dir():
            raise FileExistsError(errno.EEXIST, "File exists", str(output))
        return dst
    return resolve_output_preview(src, output, op_name)


def rewrite_output_extension(dst: Path, fmt: str | None) -> Path:
    """Rewrite ``dst`` to the canonical extension for ``fmt`` when known."""
    if fmt is None:
        return dst
    return dst.with_suffix(extension_for_format(fmt))


def predict_output_format(
    src: Path,
    op_name: str,
    params: Mapping[str, Any] | None = None,
) -> str | None:
    """Predict the output ``AudioBuffer.format`` without loading or running DSP.

    The pipeline rewrites the final path whenever an op returns a buffer with a
    non-``None`` ``format``. Preview can only mirror that for built-in ops whose
    output format is determinable from source metadata or params without
    invoking the op. Unknown/plugin ops intentionally return ``None`` so preview
    keeps the raw destination path.
    """

    op = op_name.lower()
    values = params or {}
    if op == "convert":
        requested = values.get("format")
        if requested is None:
            return None
        return str(requested).lower().lstrip(".")
    if op == "bitdepth":
        return format_for_extension(src.suffix)
    return None


def predict_output_extension(
    src: Path,
    op_name: str,
    params: Mapping[str, Any] | None = None,
) -> str | None:
    """Predict the canonical rewritten output extension for a preview path."""
    fmt = predict_output_format(src, op_name, params)
    if fmt is None:
        return None
    return extension_for_format(fmt)


__all__ = [
    "predict_output_extension",
    "predict_output_format",
    "resolve_output",
    "resolve_output_preview",
    "rewrite_output_extension",
]
