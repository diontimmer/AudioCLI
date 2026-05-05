"""``highshelf`` — high-shelf EQ via ``pedalboard.HighShelfFilter``."""

from __future__ import annotations

from typing import Annotated

import typer

from audiocli.buffer import AudioBuffer
from audiocli.registry import op


@op(name="highshelf", help="High-shelf EQ filter (pedalboard.HighShelfFilter).")
def highshelf(
    buf: AudioBuffer,
    hz: Annotated[float, typer.Option("--hz", help="Shelf cutoff frequency in Hz.")] = 440.0,
    gain_db: Annotated[float, typer.Option("--gain-db", help="Shelf gain in decibels.")] = 0.0,
    q: Annotated[float, typer.Option("--q", help="Filter Q factor.")] = 0.70710678,
) -> AudioBuffer:
    """Boost or cut frequencies above ``hz``."""
    import numpy as np  # noqa: PLC0415
    from pedalboard import HighShelfFilter  # noqa: PLC0415

    plugin = HighShelfFilter(cutoff_frequency_hz=hz, gain_db=gain_db, q=q)
    out = plugin(buf.data, sample_rate=buf.sr)
    return AudioBuffer(data=np.asarray(out, dtype=np.float32), sr=buf.sr, subtype=buf.subtype)
