"""``distortion`` — soft-clip distortion via ``pedalboard.Distortion``."""

from __future__ import annotations

from typing import Annotated

import typer

from audiocli.buffer import AudioBuffer
from audiocli.registry import op


@op(name="distortion", help="Soft-clip distortion (pedalboard.Distortion).")
def distortion(
    buf: AudioBuffer,
    drive_db: Annotated[
        float,
        typer.Option("--drive-db", help="Pre-clip drive in dB."),
    ] = 25.0,
) -> AudioBuffer:
    """Apply ``tanh``-style saturation with the given drive."""
    import numpy as np  # noqa: PLC0415
    from pedalboard import Distortion  # noqa: PLC0415

    plugin = Distortion(drive_db=drive_db)
    out = plugin(buf.data, sample_rate=buf.sr)
    return AudioBuffer(data=np.asarray(out, dtype=np.float32), sr=buf.sr, subtype=buf.subtype)
