"""``chorus`` — modulated short-delay chorus via ``pedalboard.Chorus``."""

from __future__ import annotations

from typing import Annotated

import typer

from audiocli.buffer import AudioBuffer
from audiocli.registry import op


@op(name="chorus", help="Modulated chorus (pedalboard.Chorus).")
def chorus(
    buf: AudioBuffer,
    rate_hz: Annotated[
        float,
        typer.Option("--rate-hz", help="LFO rate in Hz."),
    ] = 1.0,
    depth: Annotated[
        float,
        typer.Option("--depth", help="Modulation depth in [0, 1]."),
    ] = 0.25,
    centre_delay_ms: Annotated[
        float,
        typer.Option("--centre-delay-ms", help="Centre delay in milliseconds."),
    ] = 7.0,
    feedback: Annotated[
        float,
        typer.Option("--feedback", help="Feedback amount in [0, 1]."),
    ] = 0.0,
    mix: Annotated[
        float,
        typer.Option("--mix", help="Wet/dry mix in [0, 1]."),
    ] = 0.5,
) -> AudioBuffer:
    """Add chorus modulation with the given rate/depth/delay/feedback/mix."""
    import numpy as np  # noqa: PLC0415
    from pedalboard import Chorus  # noqa: PLC0415

    plugin = Chorus(
        rate_hz=rate_hz,
        depth=depth,
        centre_delay_ms=centre_delay_ms,
        feedback=feedback,
        mix=mix,
    )
    out = plugin(buf.data, sample_rate=buf.sr)
    return AudioBuffer(data=np.asarray(out, dtype=np.float32), sr=buf.sr, subtype=buf.subtype)
