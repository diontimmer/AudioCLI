"""``trim`` — strip leading and/or trailing silence below a dB threshold."""

from __future__ import annotations

from typing import Annotated

import typer

from audiocli.buffer import AudioBuffer
from audiocli.registry import op

# RMS window size for silence detection (~10 ms at 44.1 kHz).
_WINDOW_MS = 10.0


@op(name="trim", help="Trim leading/trailing silence below a dB threshold (RMS-based).")
def trim(
    buf: AudioBuffer,
    head: Annotated[
        bool,
        typer.Option("--head/--no-head", help="Trim leading silence."),
    ] = True,
    tail: Annotated[
        bool,
        typer.Option("--tail/--no-tail", help="Trim trailing silence."),
    ] = True,
    threshold_db: Annotated[
        float,
        typer.Option("--threshold-db", help="Silence threshold in dBFS (e.g. -60)."),
    ] = -60.0,
) -> AudioBuffer:
    """Strip silence below ``threshold_db`` from the start and/or end of ``buf``."""
    import numpy as np  # noqa: PLC0415

    data = buf.data
    if data.dtype != np.float32:
        data = data.astype(np.float32, copy=False)

    n_samples = int(data.shape[1])
    if n_samples == 0 or (not head and not tail):
        return AudioBuffer(data=data, sr=buf.sr, subtype=buf.subtype)

    # Mono-mix for envelope detection (max across channels keeps loud transients).
    mono = np.max(np.abs(data), axis=0)

    win = max(1, int(round(buf.sr * _WINDOW_MS / 1000.0)))
    threshold_lin = float(10.0 ** (threshold_db / 20.0))

    # Compute RMS over non-overlapping windows.
    n_full = n_samples // win
    if n_full == 0:
        # Buffer shorter than a single window — fall back to peak check.
        peak = float(np.max(mono)) if mono.size else 0.0
        if peak < threshold_lin:
            return AudioBuffer(
                data=np.zeros((data.shape[0], 0), dtype=np.float32),
                sr=buf.sr,
                subtype=buf.subtype,
            )
        return AudioBuffer(data=data, sr=buf.sr, subtype=buf.subtype)

    trimmed = mono[: n_full * win].reshape(n_full, win)
    rms = np.sqrt(np.mean(trimmed.astype(np.float64) ** 2, axis=1))
    above = rms >= threshold_lin

    if not np.any(above):
        # Entire signal is silent.
        return AudioBuffer(
            data=np.zeros((data.shape[0], 0), dtype=np.float32),
            sr=buf.sr,
            subtype=buf.subtype,
        )

    first_idx = int(np.argmax(above)) if head else 0
    # argmax on reversed boolean array gives last True from the end.
    last_idx = int(n_full - 1 - np.argmax(above[::-1])) if tail else (n_full - 1)

    start = first_idx * win if head else 0
    if tail:
        end = (last_idx + 1) * win
        # Include the trailing samples after the last full window when not trimming
        # past them — but since the tail window is above threshold, keep its full
        # span. Stop at end (capped by n_samples).
        end = min(end, n_samples)
    else:
        end = n_samples

    out = data[:, start:end]
    if not out.flags["C_CONTIGUOUS"]:
        out = np.ascontiguousarray(out)
    return AudioBuffer(data=out, sr=buf.sr, subtype=buf.subtype)
