"""Typer binding for the ``info`` analysis command."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from audiocli.analysis import FileInfo, compute_info
from audiocli.commands.common import resolve_files
from audiocli.errors import AudioCLIError
from audiocli.io import load
from audiocli.workers import parallel_map


def _format_info_row(info: FileInfo) -> str:
    lufs_str = f"{info.lufs:+.2f} LUFS" if info.lufs is not None else "  n/a LUFS"
    return (
        f"{info.path}: "
        f"{info.sr} Hz, {info.channels} ch, "
        f"{info.duration_s:.3f}s, "
        f"peak {info.peak_dbfs:+.2f} dBFS, "
        f"rms {info.rms_dbfs:+.2f} dBFS, "
        f"{lufs_str}"
    )


def register_info_command(app: typer.Typer) -> None:
    @app.command("info", help="Print sample-rate, channels, duration, peak, RMS, and LUFS.")
    def info_cmd(
        target: Annotated[
            list[Path],
            typer.Option(
                "--target",
                help="Input audio file(s) or directory. Repeat to pass multiple.",
                exists=True,
                readable=True,
            ),
        ],
        recursive: Annotated[
            bool,
            typer.Option(
                "--recursive/--no-recursive",
                help="Recurse into directories when scanning targets.",
            ),
        ] = True,
        as_json: Annotated[
            bool,
            typer.Option("--json", help="Emit one JSON object per file instead of a table."),
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
        files = resolve_files(target, recursive=recursive)

        def _one(p: Path) -> tuple[Path, FileInfo | str]:
            try:
                buf = load(p)
                return p, compute_info(buf, path=p)
            except AudioCLIError as e:
                return p, str(e)
            except Exception as e:  # pragma: no cover - defensive
                return p, f"{type(e).__name__}: {e}"

        failed = 0
        for path, payload in parallel_map(files, _one, workers=workers, ordered=True):
            if isinstance(payload, FileInfo):
                if as_json:
                    typer.echo(json.dumps(payload.to_dict()))
                else:
                    typer.echo(_format_info_row(payload))
            else:
                failed += 1
                if as_json:
                    typer.echo(json.dumps({"path": str(path), "error": payload}))
                else:
                    typer.echo(f"FAIL {path}: {payload}", err=True)

        if failed > 0:
            raise typer.Exit(code=min(failed, 255))


__all__ = ["register_info_command"]
