"""Silence detection policy for destructive cleanup commands."""

from __future__ import annotations

from typing import Literal

from audiocli.buffer import AudioBuffer
from audiocli.errors import AudioCLIError
from audiocli.levels import to_dbfs


def is_silent(buf: AudioBuffer, *, threshold_db: float, metric: Literal["rms", "peak"]) -> bool:
    """Return ``True`` when ``buf``'s level is below ``threshold_db``."""
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
    return to_dbfs(level_lin) < threshold_db


__all__ = ["is_silent"]
