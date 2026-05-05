"""``lowshelf`` — low-shelf EQ via ``pedalboard.LowShelfFilter``."""

from __future__ import annotations

from typing import Annotated

import typer

from audiocli.buffer import AudioBuffer
from audiocli.registry import op


@op(name="lowshelf", help="Low-shelf EQ filter (pedalboard.LowShelfFilter).")
def lowshelf(
    buf: AudioBuffer,
    hz: Annotated[float, typer.Option("--hz", help="Shelf cutoff frequency in Hz.")] = 440.0,
    gain_db: Annotated[float, typer.Option("--gain-db", help="Shelf gain in decibels.")] = 0.0,
    q: Annotated[float, typer.Option("--q", help="Filter Q factor.")] = 0.70710678,
) -> AudioBuffer:
    """Boost or cut frequencies below ``hz``."""
    import numpy as np  # noqa: PLC0415
    from pedalboard import LowShelfFilter  # noqa: PLC0415

    plugin = LowShelfFilter(cutoff_frequency_hz=hz, gain_db=gain_db, q=q)
    out = plugin(buf.data, sample_rate=buf.sr)
    return AudioBuffer(data=np.asarray(out, dtype=np.float32), sr=buf.sr, subtype=buf.subtype)
