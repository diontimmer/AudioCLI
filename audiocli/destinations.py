"""Output path policy for per-file audio operations."""

from __future__ import annotations

from pathlib import Path


def resolve_output(src: Path, output: Path | None, op_name: str) -> Path:
    """Pick the destination path for one source file.

    ``None`` writes alongside the source as ``<stem>_<op>.<ext>``.
    An existing directory, or a suffixless path, writes ``<dir>/<source-name>``.
    A path with a suffix is treated as the exact destination file.
    """
    if output is None:
        return src.with_name(f"{src.stem}_{op_name}{src.suffix}")
    if output.exists() and output.is_dir():
        return output / src.name
    if not output.suffix:
        output.mkdir(parents=True, exist_ok=True)
        return output / src.name
    return output


__all__ = ["resolve_output"]
