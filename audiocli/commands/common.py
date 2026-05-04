"""Shared helpers for Typer command bindings."""

from __future__ import annotations

from pathlib import Path

import typer

from audiocli.errors import AudioCLIError
from audiocli.scanner import scan_targets


def resolve_files(
    targets: list[Path],
    *,
    recursive: bool,
) -> list[Path]:
    """Run the scanner and surface clean CLI errors instead of tracebacks."""
    try:
        files = scan_targets(targets, recursive=recursive)
    except AudioCLIError as e:
        typer.echo(f"error: {e}", err=True)
        raise typer.Exit(code=1) from e
    if not files:
        typer.echo("error: no audio files matched the targets", err=True)
        raise typer.Exit(code=1)
    return files


__all__ = ["resolve_files"]
