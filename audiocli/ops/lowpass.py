"""``lowpass`` — low-pass filter via ``pedalboard.LowpassFilter``."""

from __future__ import annotations

from typing import Annotated

import typer

from audiocli.buffer import AudioBuffer
from audiocli.registry import op


@op(name="lowpass", help="Low-pass filter (pedalboard.LowpassFilter).")
def lowpass(
    buf: AudioBuffer,
    hz: Annotated[
        float,
        typer.Option("--hz", help="Cutoff frequency in Hz; energy above it is attenuated."),
    ] = 5000.0,
) -> AudioBuffer:
    """Attenuate frequencies above ``hz``."""
    import numpy as np  # noqa: PLC0415
    from pedalboard import LowpassFilter  # noqa: PLC0415

    plugin = LowpassFilter(cutoff_frequency_hz=hz)
    out = plugin(buf.data, sample_rate=buf.sr)
    return AudioBuffer(data=np.asarray(out, dtype=np.float32), sr=buf.sr, subtype=buf.subtype)
