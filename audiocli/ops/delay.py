"""``delay`` — feedback delay via ``pedalboard.Delay``."""

from __future__ import annotations

from typing import Annotated

import typer

from audiocli.buffer import AudioBuffer
from audiocli.registry import op


@op(name="delay", help="Feedback delay (pedalboard.Delay).")
def delay(
    buf: AudioBuffer,
    time_s: Annotated[
        float,
        typer.Option("--time-s", help="Delay time in seconds."),
    ] = 0.5,
    feedback: Annotated[
        float,
        typer.Option("--feedback", help="Feedback amount in [0, 1]."),
    ] = 0.3,
    mix: Annotated[
        float,
        typer.Option("--mix", help="Wet/dry mix in [0, 1]."),
    ] = 0.5,
) -> AudioBuffer:
    """Add a delayed echo with the given time/feedback/mix."""
    import numpy as np  # noqa: PLC0415
    from pedalboard import Delay  # noqa: PLC0415

    plugin = Delay(delay_seconds=time_s, feedback=feedback, mix=mix)
    out = plugin(buf.data, sample_rate=buf.sr)
    return AudioBuffer(data=np.asarray(out, dtype=np.float32), sr=buf.sr, subtype=buf.subtype)
