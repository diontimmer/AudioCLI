"""``resample`` — change a buffer's sample rate via libsamplerate (pedalboard)."""

from __future__ import annotations

from typing import Annotated

import typer

from audiocli.buffer import AudioBuffer
from audiocli.errors import AudioCLIError
from audiocli.registry import op


@op(name="resample", help="Resample audio to a target sample rate (libsamplerate).")
def resample(
    buf: AudioBuffer,
    sr: Annotated[int, typer.Option("--sr", help="Target sample rate in Hz.")],
) -> AudioBuffer:
    """Resample ``buf`` to ``sr`` Hz using pedalboard's ``StreamResampler``."""
    if sr <= 0:
        raise AudioCLIError(f"resample: target sample rate must be positive (got {sr})")

    if int(sr) == int(buf.sr):
        return AudioBuffer(data=buf.data, sr=buf.sr, subtype=buf.subtype)

    import numpy as np  # noqa: PLC0415
    from pedalboard.io import StreamResampler  # noqa: PLC0415

    data = buf.data
    if data.dtype != np.float32:
        data = data.astype(np.float32, copy=False)

    channels = int(data.shape[0])
    resampler = StreamResampler(
        source_sample_rate=float(buf.sr),
        target_sample_rate=float(sr),
        num_channels=channels,
    )

    chunks: list[np.ndarray] = []
    first = resampler.process(data)
    if first.size:
        chunks.append(first)
    flushed = resampler.process()
    if flushed.size:
        chunks.append(flushed)

    out = np.concatenate(chunks, axis=1) if chunks else np.zeros((channels, 0), dtype=np.float32)

    if out.dtype != np.float32:
        out = out.astype(np.float32, copy=False)

    return AudioBuffer(data=out, sr=int(sr), subtype=buf.subtype)
