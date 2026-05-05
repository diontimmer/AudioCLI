"""``clip`` — hard clipping via ``pedalboard.Clipping``."""

from __future__ import annotations

from typing import Annotated

import typer

from audiocli.buffer import AudioBuffer
from audiocli.registry import op


@op(name="clip", help="Hard clipping distortion (pedalboard.Clipping).")
def clip(
    buf: AudioBuffer,
    threshold_db: Annotated[
        float,
        typer.Option("--threshold-db", help="Clipping threshold in decibels."),
    ] = -6.0,
) -> AudioBuffer:
    """Clip samples above the configured threshold."""
    import numpy as np  # noqa: PLC0415
    from pedalboard import Clipping  # noqa: PLC0415

    plugin = Clipping(threshold_db=threshold_db)
    out = plugin(buf.data, sample_rate=buf.sr)
    return AudioBuffer(data=np.asarray(out, dtype=np.float32), sr=buf.sr, subtype=buf.subtype)
