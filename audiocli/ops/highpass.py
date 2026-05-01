"""``highpass`` — high-pass filter via ``pedalboard.HighpassFilter``."""

from __future__ import annotations

from typing import Annotated

import typer

from audiocli.buffer import AudioBuffer
from audiocli.registry import op


@op(name="highpass", help="High-pass filter (pedalboard.HighpassFilter).")
def highpass(
    buf: AudioBuffer,
    hz: Annotated[
        float,
        typer.Option("--hz", help="Cutoff frequency in Hz; energy below it is attenuated."),
    ] = 100.0,
) -> AudioBuffer:
    """Attenuate frequencies below ``hz``."""
    import numpy as np  # noqa: PLC0415
    from pedalboard import HighpassFilter  # noqa: PLC0415

    plugin = HighpassFilter(cutoff_frequency_hz=hz)
    out = plugin(buf.data, sample_rate=buf.sr)
    return AudioBuffer(data=np.asarray(out, dtype=np.float32), sr=buf.sr, subtype=buf.subtype)
