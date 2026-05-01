"""First-party special-case commands.

These three commands do **not** fit the standard ``(buf) -> buf`` filter
contract that ``@op``-registered ops follow:

* ``info`` is **analysis** — emits stats to stdout, never writes audio.
* ``remove-silent`` is **side-effect** — deletes the *input* file when its
  level falls below a threshold; no output file at all.
* ``chunk`` is **multi-output** — splits one input into N output files.

Per the v2.0 PRD they are first-party-only special cases; the public plugin
contract may broaden in v2.1+ if real plugins demand it. Keeping them as
direct Typer commands (rather than entries in the registry) means plugin
authors aren't tempted to mimic the shape before it stabilises.

Heavy imports (numpy, pyloudnorm) live inside function bodies so
``audiocli --help`` stays under its 120 ms budget.
"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any, Literal

import typer

from audiocli.buffer import AudioBuffer
from audiocli.errors import AudioCLIError
from audiocli.io import load, save
from audiocli.pipeline import default_workers
from audiocli.scanner import scan_targets

# Floor for dB conversions so ``-inf`` never appears in printed output.
_DB_FLOOR = -200.0


@dataclass
class FileInfo:
    """Result of :func:`compute_info` for one file."""

    path: Path
    sr: int
    channels: int
    duration_s: float
    peak_dbfs: float
    rms_dbfs: float
    lufs: float | None  # ``None`` when the signal is too quiet to measure.

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": str(self.path),
            "sr": self.sr,
            "channels": self.channels,
            "duration_s": self.duration_s,
            "peak_dbfs": self.peak_dbfs,
            "rms_dbfs": self.rms_dbfs,
            "lufs": self.lufs,
        }


def _to_db(linear: float) -> float:
    """Convert a linear amplitude to dBFS, clamped to :data:`_DB_FLOOR`."""
    import math  # noqa: PLC0415

    if linear <= 0.0:
        return _DB_FLOOR
    return max(_DB_FLOOR, 20.0 * math.log10(linear))


def compute_info(buf: AudioBuffer, *, path: Path | None = None) -> FileInfo:
    """Compute sample-rate / channels / duration / peak / RMS / LUFS for ``buf``.

    LUFS is best-effort: pyloudnorm refuses signals below its measurement
    threshold (~-70 LUFS) and that's not an error from our point of view —
    we report ``None`` instead.
    """
    import numpy as np  # noqa: PLC0415

    data = buf.data
    if data.ndim != 2:
        raise AudioCLIError(f"info: buffer must be 2-D (channels, samples); got shape {data.shape}")

    channels = int(data.shape[0])
    n_samples = int(data.shape[1])
    duration = n_samples / float(buf.sr) if buf.sr > 0 else 0.0

    peak_lin = float(np.max(np.abs(data))) if n_samples > 0 else 0.0
    # RMS across the entire buffer, mixed across channels.
    rms_lin = float(np.sqrt(np.mean(data.astype(np.float64) ** 2))) if n_samples > 0 else 0.0

    lufs: float | None = None
    # Need at least ~0.4 s for the LUFS gating block to even run.
    if n_samples / float(max(buf.sr, 1)) >= 0.4:
        try:
            import pyloudnorm as pyln  # noqa: PLC0415

            samples_first = np.ascontiguousarray(data.T)
            meter_input = samples_first[:, 0] if samples_first.shape[1] == 1 else samples_first
            meter = pyln.Meter(int(buf.sr))
            measured = float(meter.integrated_loudness(meter_input))
            lufs = measured if np.isfinite(measured) else None
        except Exception:
            lufs = None

    return FileInfo(
        path=Path(path) if path is not None else Path(""),
        sr=int(buf.sr),
        channels=channels,
        duration_s=duration,
        peak_dbfs=_to_db(peak_lin),
        rms_dbfs=_to_db(rms_lin),
        lufs=lufs,
    )


def is_silent(buf: AudioBuffer, *, threshold_db: float, metric: Literal["rms", "peak"]) -> bool:
    """Return ``True`` when ``buf``'s level is below ``threshold_db``.

    ``metric="rms"`` measures the RMS across the whole buffer; ``"peak"``
    measures the absolute peak. The threshold is in dBFS.
    """
    import numpy as np  # noqa: PLC0415

    if metric not in {"rms", "peak"}:
        raise AudioCLIError(f"unknown metric: {metric!r} (expected 'rms' or 'peak')")

    data = buf.data
    n_samples = int(data.shape[1]) if data.ndim == 2 else int(data.size)
    if n_samples == 0:
        return True

    if metric == "peak":
        level_lin = float(np.max(np.abs(data)))
    else:
        level_lin = float(np.sqrt(np.mean(data.astype(np.float64) ** 2)))
    return _to_db(level_lin) < threshold_db


def chunk_buffer(
    buf: AudioBuffer,
    *,
    seconds: float,
    pad: bool = True,
) -> list[AudioBuffer]:
    """Split ``buf`` into fixed-length chunks of ``seconds`` each.

    The last chunk is zero-padded to ``seconds`` when ``pad`` is true;
    otherwise it is shorter than the others. Returns an empty list when
    the buffer itself is empty.
    """
    import numpy as np  # noqa: PLC0415

    if seconds <= 0.0:
        raise AudioCLIError(f"chunk: --seconds must be > 0, got {seconds}")

    data = buf.data
    if data.ndim != 2:
        raise AudioCLIError(
            f"chunk: buffer must be 2-D (channels, samples); got shape {data.shape}"
        )

    chunk_samples = int(round(seconds * float(buf.sr)))
    if chunk_samples <= 0:
        raise AudioCLIError(f"chunk: --seconds {seconds} resolves to 0 samples at sr={buf.sr}")

    n_samples = int(data.shape[1])
    if n_samples == 0:
        return []

    out: list[AudioBuffer] = []
    for start in range(0, n_samples, chunk_samples):
        end = start + chunk_samples
        piece = data[:, start:end]
        if piece.shape[1] < chunk_samples and pad:
            short = chunk_samples - piece.shape[1]
            piece = np.concatenate(
                [piece, np.zeros((piece.shape[0], short), dtype=piece.dtype)],
                axis=1,
            )
        if not piece.flags["C_CONTIGUOUS"]:
            piece = np.ascontiguousarray(piece)
        out.append(
            AudioBuffer(
                data=piece.astype(np.float32, copy=False),
                sr=buf.sr,
                subtype=buf.subtype,
                format=buf.format,
                quality=buf.quality,
            )
        )
    return out


# --------------------------------------------------------------------------- #
# Typer command bindings
# --------------------------------------------------------------------------- #


def _resolve_files(
    targets: list[Path],
    *,
    recursive: bool,
) -> list[Path]:
    """Run the scanner and surface clean errors instead of tracebacks."""
    try:
        files = scan_targets(targets, recursive=recursive)
    except AudioCLIError as e:
        typer.echo(f"error: {e}", err=True)
        raise typer.Exit(code=1) from e
    if not files:
        typer.echo("error: no audio files matched the targets", err=True)
        raise typer.Exit(code=1)
    return files


def _format_info_row(info: FileInfo) -> str:
    """Render one :class:`FileInfo` as a human-readable line."""
    lufs_str = f"{info.lufs:+.2f} LUFS" if info.lufs is not None else "  n/a LUFS"
    return (
        f"{info.path}: "
        f"{info.sr} Hz, {info.channels} ch, "
        f"{info.duration_s:.3f}s, "
        f"peak {info.peak_dbfs:+.2f} dBFS, "
        f"rms {info.rms_dbfs:+.2f} dBFS, "
        f"{lufs_str}"
    )


def register_special_commands(app: typer.Typer) -> None:
    """Register ``info``, ``remove-silent``, and ``chunk`` on ``app``.

    The bindings live here (rather than in :mod:`audiocli.cli`) so that
    the CLI module stays focused on the standard registry-driven dispatch
    path. See module docstring for why these three are first-party only.
    """

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
                help="Worker thread count. 0 → min(8, cpu_count()).",
                min=0,
            ),
        ] = 0,
    ) -> None:
        files = _resolve_files(target, recursive=recursive)
        n_workers = workers if workers > 0 else default_workers()

        results: list[tuple[Path, FileInfo | str]] = []
        # Preserve scan order in output regardless of completion order.
        order = {p: i for i, p in enumerate(files)}
        bag: list[tuple[int, Path, FileInfo | str]] = []

        def _one(p: Path) -> tuple[Path, FileInfo | str]:
            try:
                buf = load(p)
                return p, compute_info(buf, path=p)
            except AudioCLIError as e:
                return p, str(e)
            except Exception as e:  # pragma: no cover — defensive
                return p, f"{type(e).__name__}: {e}"

        with ThreadPoolExecutor(max_workers=n_workers) as pool:
            futs = [pool.submit(_one, p) for p in files]
            for fut in as_completed(futs):
                p, payload = fut.result()
                bag.append((order[p], p, payload))

        bag.sort(key=lambda t: t[0])
        results = [(p, payload) for _, p, payload in bag]

        failed = 0
        for path, payload in results:
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
                help="Worker thread count. 0 → min(8, cpu_count()).",
                min=0,
            ),
        ] = 0,
    ) -> None:
        if metric not in {"rms", "peak"}:
            typer.echo(f"error: --metric must be 'rms' or 'peak', got {metric!r}", err=True)
            raise typer.Exit(code=1)

        files = _resolve_files(target, recursive=recursive)
        n_workers = workers if workers > 0 else default_workers()

        deleted: list[Path] = []
        kept: list[Path] = []
        failed: list[tuple[Path, str]] = []

        def _check(p: Path) -> tuple[Path, bool, str | None]:
            try:
                buf = load(p)
                silent = is_silent(buf, threshold_db=threshold_db, metric=metric)  # type: ignore[arg-type]
                return p, silent, None
            except AudioCLIError as e:
                return p, False, str(e)
            except Exception as e:  # pragma: no cover — defensive
                return p, False, f"{type(e).__name__}: {e}"

        with ThreadPoolExecutor(max_workers=n_workers) as pool:
            futs = [pool.submit(_check, p) for p in files]
            for fut in as_completed(futs):
                p, silent, err = fut.result()
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
                help="Worker thread count. 0 → min(8, cpu_count()).",
                min=0,
            ),
        ] = 0,
    ) -> None:
        if seconds <= 0.0:
            typer.echo(f"error: --seconds must be > 0, got {seconds}", err=True)
            raise typer.Exit(code=1)

        files = _resolve_files(target, recursive=recursive)
        n_workers = workers if workers > 0 else default_workers()

        total_written = 0
        ok_files = 0
        failed: list[tuple[Path, str]] = []

        def _do_one(p: Path) -> tuple[Path, list[Path], str | None]:
            try:
                buf = load(p)
                pieces = chunk_buffer(buf, seconds=seconds, pad=pad)
                if not pieces:
                    return p, [], "empty buffer (0 samples)"
                # Resolve destination directory.
                if output is not None:
                    dest_dir = output
                    dest_dir.mkdir(parents=True, exist_ok=True)
                else:
                    dest_dir = p.parent
                written: list[Path] = []
                # Width controls suffix zero-padding so files sort lexically.
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
                    # Only delete the source after every chunk wrote successfully.
                    try:
                        p.unlink()
                    except OSError as e:
                        return p, written, f"unlink failed: {e}"
                return p, written, None
            except AudioCLIError as e:
                return p, [], str(e)
            except Exception as e:  # pragma: no cover — defensive
                return p, [], f"{type(e).__name__}: {e}"

        with ThreadPoolExecutor(max_workers=n_workers) as pool:
            futs = [pool.submit(_do_one, p) for p in files]
            for fut in as_completed(futs):
                src, written, err = fut.result()
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
