"""``phaser`` — all-pass phase modulation via ``pedalboard.Phaser``."""

from __future__ import annotations

from typing import Annotated

import typer

from audiocli.buffer import AudioBuffer
from audiocli.registry import op


@op(name="phaser", help="All-pass phaser (pedalboard.Phaser).")
def phaser(
    buf: AudioBuffer,
    rate_hz: Annotated[
        float,
        typer.Option("--rate-hz", help="LFO rate in Hz."),
    ] = 1.0,
    depth: Annotated[
        float,
        typer.Option("--depth", help="Modulation depth in [0, 1]."),
    ] = 0.5,
    centre_frequency_hz: Annotated[
        float,
        typer.Option("--centre-frequency-hz", help="Centre frequency of the sweep, in Hz."),
    ] = 1300.0,
    feedback: Annotated[
        float,
        typer.Option("--feedback", help="Feedback amount in [0, 1]."),
    ] = 0.0,
    mix: Annotated[
        float,
        typer.Option("--mix", help="Wet/dry mix in [0, 1]."),
    ] = 0.5,
) -> AudioBuffer:
    """Sweep an all-pass network with the given rate/depth/centre/feedback/mix."""
    import numpy as np  # noqa: PLC0415
    from pedalboard import Phaser  # noqa: PLC0415

    plugin = Phaser(
        rate_hz=rate_hz,
        depth=depth,
        centre_frequency_hz=centre_frequency_hz,
        feedback=feedback,
        mix=mix,
    )
    out = plugin(buf.data, sample_rate=buf.sr)
    return AudioBuffer(data=np.asarray(out, dtype=np.float32), sr=buf.sr, subtype=buf.subtype)
