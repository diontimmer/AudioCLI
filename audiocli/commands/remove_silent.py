"""Typer binding for the destructive ``remove-silent`` command."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal, cast

import typer

from audiocli.commands.common import resolve_files
from audiocli.errors import AudioCLIError
from audiocli.io import load
from audiocli.silence import is_silent
from audiocli.workers import parallel_map


def register_remove_silent_command(app: typer.Typer) -> None:
    @app.command(
        "remove-silent",
        help="Delete input files whose level is below --threshold-db.",
    )
    def remove_silent_cmd(
        target: Annotated[
            list[Path],
            typer.Option(
                "--target",
                help="Input audio file(s) or directory. Repeat to pass multiple.",
                exists=True,
                readable=True,
            ),
        ],
        threshold_db: Annotated[
            float,
            typer.Option(
                "--threshold-db",
                help="Silence threshold in dBFS (e.g. -60).",
            ),
        ] = -60.0,
        metric: Annotated[
            str,
            typer.Option(
                "--metric",
                help="Level metric to compare against the threshold: 'rms' or 'peak'.",
            ),
        ] = "rms",
        recursive: Annotated[
            bool,
            typer.Option(
                "--recursive/--no-recursive",
                help="Recurse into directories when scanning targets.",
            ),
        ] = True,
        dry_run: Annotated[
            bool,
            typer.Option(
                "--dry-run/--no-dry-run",
                help="Report which files would be deleted without removing them.",
            ),
        ] = False,
        workers: Annotated[
            int,
            typer.Option(
                "--workers",
                help="Worker thread count. 0 -> min(8, cpu_count()).",
                min=0,
            ),
        ] = 0,
    ) -> None:
        if metric not in {"rms", "peak"}:
            typer.echo(f"error: --metric must be 'rms' or 'peak', got {metric!r}", err=True)
            raise typer.Exit(code=1)
        metric_name = cast(Literal["rms", "peak"], metric)

        files = resolve_files(target, recursive=recursive)
        deleted: list[Path] = []
        kept: list[Path] = []
        failed: list[tuple[Path, str]] = []

        def _check(p: Path) -> tuple[Path, bool, str | None]:
            try:
                buf = load(p)
                silent = is_silent(buf, threshold_db=threshold_db, metric=metric_name)
                return p, silent, None
            except AudioCLIError as e:
                return p, False, str(e)
            except Exception as e:  # pragma: no cover - defensive
                return p, False, f"{type(e).__name__}: {e}"

        for p, silent, err in parallel_map(files, _check, workers=workers):
            if err is not None:
                failed.append((p, err))
                typer.echo(f"FAIL {p}: {err}", err=True)
                continue
            if silent:
                if dry_run:
                    deleted.append(p)
                    typer.echo(f"would remove: {p}")
                else:
                    try:
                        p.unlink()
                        deleted.append(p)
                        typer.echo(f"removed: {p}")
                    except OSError as e:
                        failed.append((p, f"unlink failed: {e}"))
                        typer.echo(f"FAIL {p}: unlink failed: {e}", err=True)
            else:
                kept.append(p)

        verb = "would remove" if dry_run else "removed"
        typer.echo(
            f"done: {len(deleted)} {verb}, {len(kept)} kept, {len(failed)} failed",
            err=True,
        )
        if failed:
            raise typer.Exit(code=min(len(failed), 255))


__all__ = ["register_remove_silent_command"]
