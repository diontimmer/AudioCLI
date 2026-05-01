"""``normalize`` — peak or LUFS loudness normalization."""

from __future__ import annotations

from typing import Annotated

import typer

from audiocli.buffer import AudioBuffer
from audiocli.errors import OpError
from audiocli.registry import op


@op(
    name="normalize",
    help="Normalize to a peak (dBFS) or integrated LUFS target. Pass exactly one of --peak-db or --lufs.",
)
def normalize(
    buf: AudioBuffer,
    peak_db: Annotated[
        float | None,
        typer.Option(
            "--peak-db",
            help="Target peak level in dBFS (e.g. -1.0). Mutually exclusive with --lufs.",
        ),
    ] = None,
    lufs: Annotated[
        float | None,
        typer.Option(
            "--lufs",
            help="Target integrated loudness in LUFS (e.g. -14.0). Mutually exclusive with --peak-db.",
        ),
    ] = None,
) -> AudioBuffer:
    """Scale ``buf`` so its peak or integrated LUFS hits the requested target."""
    import numpy as np  # noqa: PLC0415

    if (peak_db is None) == (lufs is None):
        raise OpError("normalize requires exactly one of --peak-db or --lufs")

    data = buf.data
    if peak_db is not None:
        current_peak = float(np.max(np.abs(data)))
        if current_peak == 0.0:
            return AudioBuffer(
                data=data.astype(np.float32, copy=False), sr=buf.sr, subtype=buf.subtype
            )
        target = float(10.0 ** (peak_db / 20.0))
        factor = target / current_peak
        scaled = (data * factor).astype(np.float32, copy=False)
        return AudioBuffer(data=scaled, sr=buf.sr, subtype=buf.subtype)

    # LUFS path.
    try:
        import pyloudnorm as pyln  # noqa: PLC0415
    except ImportError as e:
        raise OpError(f"pyloudnorm is required for LUFS normalization: {e}") from e

    # pyloudnorm expects shape (samples,) for mono or (samples, channels) for multi-channel.
    samples_first = np.ascontiguousarray(data.T)
    meter_input = samples_first[:, 0] if samples_first.shape[1] == 1 else samples_first

    meter = pyln.Meter(int(buf.sr))
    try:
        loudness = float(meter.integrated_loudness(meter_input))
    except Exception as e:
        raise OpError(f"failed to measure LUFS: {e}") from e

    if not np.isfinite(loudness):
        raise OpError("input is too quiet to measure integrated loudness")

    normed_samples_first = pyln.normalize.loudness(meter_input, loudness, float(lufs))
    if normed_samples_first.ndim == 1:
        normed = normed_samples_first[np.newaxis, :]
    else:
        normed = normed_samples_first.T
    return AudioBuffer(data=normed.astype(np.float32, copy=False), sr=buf.sr, subtype=buf.subtype)
