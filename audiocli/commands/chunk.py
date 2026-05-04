"""Typer binding for the multi-output ``chunk`` command."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from audiocli.chunking import chunk_buffer
from audiocli.commands.common import resolve_files
from audiocli.errors import AudioCLIError
from audiocli.io import load, save
from audiocli.workers import parallel_map


def register_chunk_command(app: typer.Typer) -> None:
    @app.command(
        "chunk",
        help="Split each input into fixed-length chunks of <seconds> each.",
    )
    def chunk_cmd(
        target: Annotated[
            list[Path],
            typer.Option(
                "--target",
                help="Input audio file(s) or directory. Repeat to pass multiple.",
                exists=True,
                readable=True,
            ),
        ],
        seconds: Annotated[
            float,
            typer.Option(
                "--seconds",
                help="Length of each chunk in seconds.",
            ),
        ],
        output: Annotated[
            Path | None,
            typer.Option("--output", help="Output directory (default: alongside source)."),
        ] = None,
        pad: Annotated[
            bool,
            typer.Option(
                "--pad/--no-pad",
                help="Zero-pad the final chunk so every chunk is exactly <seconds>.",
            ),
        ] = True,
        clean: Annotated[
            bool,
            typer.Option(
                "--clean/--no-clean",
                help="Delete each source file after it is successfully chunked.",
            ),
        ] = False,
        recursive: Annotated[
            bool,
            typer.Option(
                "--recursive/--no-recursive",
                help="Recurse into directories when scanning targets.",
            ),
        ] = True,
        workers: Annotated[
            int,
            typer.Option(
                "--workers",
                help="Worker thread count. 0 -> min(8, cpu_count()).",
                min=0,
            ),
        ] = 0,
    ) -> None:
        if seconds <= 0.0:
            typer.echo(f"error: --seconds must be > 0, got {seconds}", err=True)
            raise typer.Exit(code=1)

        files = resolve_files(target, recursive=recursive)
        total_written = 0
        ok_files = 0
        failed: list[tuple[Path, str]] = []

        def _do_one(p: Path) -> tuple[Path, list[Path], str | None]:
            try:
                buf = load(p)
                pieces = chunk_buffer(buf, seconds=seconds, pad=pad)
                if not pieces:
                    return p, [], "empty buffer (0 samples)"
                if output is not None:
                    dest_dir = output
                    dest_dir.mkdir(parents=True, exist_ok=True)
                else:
                    dest_dir = p.parent
                written: list[Path] = []
                width = max(1, len(str(len(pieces))))
                for i, piece in enumerate(pieces, start=1):
                    name = f"{p.stem}_{i:0{width}d}{p.suffix}"
                    dst = dest_dir / name
                    save(
                        dst,
                        piece,
                        subtype=piece.subtype,
                        format=piece.format,
                        quality=piece.quality,
                    )
                    written.append(dst)
                if clean:
                    try:
                        p.unlink()
                    except OSError as e:
                        return p, written, f"unlink failed: {e}"
                return p, written, None
            except AudioCLIError as e:
                return p, [], str(e)
            except Exception as e:  # pragma: no cover - defensive
                return p, [], f"{type(e).__name__}: {e}"

        for src, written, err in parallel_map(files, _do_one, workers=workers):
            if err is not None:
                failed.append((src, err))
                typer.echo(f"FAIL {src}: {err}", err=True)
                continue
            ok_files += 1
            total_written += len(written)
            for dst in written:
                typer.echo(str(dst))

        typer.echo(
            f"done: {ok_files} ok, {len(failed)} failed, {total_written} chunks written",
            err=True,
        )
        if failed:
            raise typer.Exit(code=min(len(failed), 255))


__all__ = ["register_chunk_command"]
