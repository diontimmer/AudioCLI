"""``polarity`` — invert sample polarity (a.k.a. phase flip)."""

from __future__ import annotations

from audiocli.buffer import AudioBuffer
from audiocli.registry import op


@op(name="polarity", help="Invert sample polarity (multiply by -1).")
def polarity(buf: AudioBuffer) -> AudioBuffer:
    """Return a buffer whose samples are bitwise-negated (``-1 * x``)."""
    import numpy as np  # noqa: PLC0415

    flipped = np.negative(buf.data).astype(np.float32, copy=False)
    return AudioBuffer(data=flipped, sr=buf.sr, subtype=buf.subtype)
