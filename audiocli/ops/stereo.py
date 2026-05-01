"""``stereo`` — duplicate a mono channel into a stereo pair."""

from __future__ import annotations

from audiocli.buffer import AudioBuffer
from audiocli.errors import OpError
from audiocli.registry import op


@op(name="stereo", help="Duplicate a mono channel into a 2-channel stereo buffer.")
def stereo(buf: AudioBuffer) -> AudioBuffer:
    """Mono input becomes 2 identical channels; stereo passes through; >2 channels errors."""
    import numpy as np  # noqa: PLC0415

    data = buf.data
    if data.ndim != 2:
        data = np.atleast_2d(data)
    channels = data.shape[0]
    if channels == 2:
        return AudioBuffer(data=data.astype(np.float32, copy=False), sr=buf.sr, subtype=buf.subtype)
    if channels == 1:
        duped = np.repeat(data, 2, axis=0).astype(np.float32, copy=False)
        return AudioBuffer(data=duped, sr=buf.sr, subtype=buf.subtype)
    raise OpError(f"stereo expects mono or stereo input; got {channels} channels")
