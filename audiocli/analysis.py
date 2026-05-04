"""Audio analysis helpers for the ``info`` command."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from audiocli.buffer import AudioBuffer
from audiocli.errors import AudioCLIError
from audiocli.levels import to_dbfs


@dataclass
class FileInfo:
    """Computed facts for one audio file."""

    path: Path
    sr: int
    channels: int
    duration_s: float
    peak_dbfs: float
    rms_dbfs: float
    lufs: float | None

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


def compute_info(buf: AudioBuffer, *, path: Path | None = None) -> FileInfo:
    """Compute sample-rate, duration, peak, RMS, and LUFS for ``buf``.

    LUFS is best-effort: pyloudnorm refuses signals below its measurement
    threshold, which we report as ``None`` instead of failing the file.
    """
    import numpy as np  # noqa: PLC0415

    data = buf.data
    if data.ndim != 2:
        raise AudioCLIError(f"info: buffer must be 2-D (channels, samples); got shape {data.shape}")

    channels = int(data.shape[0])
    n_samples = int(data.shape[1])
    duration = n_samples / float(buf.sr) if buf.sr > 0 else 0.0

    peak_lin = float(np.max(np.abs(data))) if n_samples > 0 else 0.0
    rms_lin = float(np.sqrt(np.mean(data.astype(np.float64) ** 2))) if n_samples > 0 else 0.0

    lufs: float | None = None
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
        peak_dbfs=to_dbfs(peak_lin),
        rms_dbfs=to_dbfs(rms_lin),
        lufs=lufs,
    )


__all__ = ["FileInfo", "compute_info"]
