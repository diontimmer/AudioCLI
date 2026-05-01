"""``mono`` — mix any multi-channel buffer down to a single channel."""

from __future__ import annotations

from audiocli.buffer import AudioBuffer
from audiocli.registry import op


@op(name="mono", help="Mix down to 1 channel by averaging across channels.")
def mono(buf: AudioBuffer) -> AudioBuffer:
    """Average all channels into one. Mono input passes through unchanged."""
    import numpy as np  # noqa: PLC0415

    data = buf.data
    if data.ndim != 2:
        # Defensive: pipeline guarantees (channels, samples), but be explicit.
        data = np.atleast_2d(data)
    if data.shape[0] == 1:
        return AudioBuffer(data=data.astype(np.float32, copy=False), sr=buf.sr, subtype=buf.subtype)
    mixed = np.mean(data, axis=0, keepdims=True).astype(np.float32, copy=False)
    return AudioBuffer(data=mixed, sr=buf.sr, subtype=buf.subtype)
