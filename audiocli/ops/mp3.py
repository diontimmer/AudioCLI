"""``mp3`` — MP3 codec artifact simulation via ``pedalboard.MP3Compressor``."""

from __future__ import annotations

from typing import Annotated

import typer

from audiocli.buffer import AudioBuffer
from audiocli.registry import op


@op(name="mp3", help="MP3 compression artifact simulation (pedalboard.MP3Compressor).")
def mp3(
    buf: AudioBuffer,
    vbr_quality: Annotated[
        float,
        typer.Option("--vbr-quality", help="VBR quality from 0.0 (best) to 10.0 (worst)."),
    ] = 2.0,
) -> AudioBuffer:
    """Apply real-time MP3 codec artifacts."""
    import numpy as np  # noqa: PLC0415
    from pedalboard import MP3Compressor  # noqa: PLC0415

    plugin = MP3Compressor(vbr_quality=vbr_quality)
    out = plugin(buf.data, sample_rate=buf.sr)
    return AudioBuffer(data=np.asarray(out, dtype=np.float32), sr=buf.sr, subtype=buf.subtype)
