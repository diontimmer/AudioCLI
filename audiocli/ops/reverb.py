"""``reverb`` — algorithmic reverb via ``pedalboard.Reverb``."""

from __future__ import annotations

from typing import Annotated

import typer

from audiocli.buffer import AudioBuffer
from audiocli.registry import op


@op(name="reverb", help="Algorithmic reverb (pedalboard.Reverb).")
def reverb(
    buf: AudioBuffer,
    room_size: Annotated[
        float,
        typer.Option("--room-size", help="Virtual room size in [0, 1]."),
    ] = 0.5,
    wet: Annotated[
        float,
        typer.Option("--wet", help="Wet (reverberated) level in [0, 1]."),
    ] = 0.33,
    dry: Annotated[
        float,
        typer.Option("--dry", help="Dry (direct) level in [0, 1]."),
    ] = 0.4,
) -> AudioBuffer:
    """Add reverberation tail with the given room/wet/dry mix."""
    import numpy as np  # noqa: PLC0415
    from pedalboard import Reverb  # noqa: PLC0415

    plugin = Reverb(room_size=room_size, wet_level=wet, dry_level=dry)
    out = plugin(buf.data, sample_rate=buf.sr)
    return AudioBuffer(data=np.asarray(out, dtype=np.float32), sr=buf.sr, subtype=buf.subtype)
