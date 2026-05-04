"""Fixed-length audio chunking helpers."""

from __future__ import annotations

from audiocli.buffer import AudioBuffer
from audiocli.errors import AudioCLIError


def chunk_buffer(
    buf: AudioBuffer,
    *,
    seconds: float,
    pad: bool = True,
) -> list[AudioBuffer]:
    """Split ``buf`` into fixed-length chunks of ``seconds`` each."""
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


__all__ = ["chunk_buffer"]
