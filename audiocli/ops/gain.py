"""``gain`` — apply a linear gain in decibels."""

from __future__ import annotations

from typing import Annotated

import typer

from audiocli.buffer import AudioBuffer
from audiocli.registry import op


@op(name="gain", help="Apply gain in decibels (positive = louder, negative = quieter).")
def gain(
    buf: AudioBuffer,
    db: Annotated[float, typer.Option("--db", help="Gain in decibels.")],
) -> AudioBuffer:
    """Scale the buffer by ``10**(db/20)``."""
    import numpy as np  # noqa: PLC0415

    factor = float(10.0 ** (db / 20.0))
    scaled = (buf.data * factor).astype(np.float32, copy=False)
    return AudioBuffer(data=scaled, sr=buf.sr, subtype=buf.subtype)
