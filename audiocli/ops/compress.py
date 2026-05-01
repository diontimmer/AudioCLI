"""``compress`` — dynamic range compression via ``pedalboard.Compressor``."""

from __future__ import annotations

from typing import Annotated

import typer

from audiocli.buffer import AudioBuffer
from audiocli.registry import op


@op(name="compress", help="Dynamic range compression (pedalboard.Compressor).")
def compress(
    buf: AudioBuffer,
    threshold_db: Annotated[
        float,
        typer.Option("--threshold-db", help="Threshold above which compression engages, in dB."),
    ] = -20.0,
    ratio: Annotated[
        float,
        typer.Option("--ratio", help="Compression ratio (e.g. 4.0 = 4:1)."),
    ] = 4.0,
    attack_ms: Annotated[
        float,
        typer.Option("--attack-ms", help="Attack time in milliseconds."),
    ] = 1.0,
    release_ms: Annotated[
        float,
        typer.Option("--release-ms", help="Release time in milliseconds."),
    ] = 100.0,
) -> AudioBuffer:
    """Compress dynamics with the given threshold/ratio/attack/release."""
    import numpy as np  # noqa: PLC0415
    from pedalboard import Compressor  # noqa: PLC0415

    plugin = Compressor(
        threshold_db=threshold_db,
        ratio=ratio,
        attack_ms=attack_ms,
        release_ms=release_ms,
    )
    out = plugin(buf.data, sample_rate=buf.sr)
    return AudioBuffer(data=np.asarray(out, dtype=np.float32), sr=buf.sr, subtype=buf.subtype)
