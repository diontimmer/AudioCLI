"""``limit`` — peak limiting via ``pedalboard.Limiter``."""

from __future__ import annotations

from typing import Annotated

import typer

from audiocli.buffer import AudioBuffer
from audiocli.registry import op


@op(name="limit", help="Peak limiting (pedalboard.Limiter).")
def limit(
    buf: AudioBuffer,
    threshold_db: Annotated[
        float,
        typer.Option("--threshold-db", help="Ceiling above which the signal is clamped, in dB."),
    ] = -1.0,
    release_ms: Annotated[
        float,
        typer.Option("--release-ms", help="Release time in milliseconds."),
    ] = 100.0,
) -> AudioBuffer:
    """Brick-wall limit the signal at ``threshold_db``."""
    import numpy as np  # noqa: PLC0415
    from pedalboard import Limiter  # noqa: PLC0415

    plugin = Limiter(threshold_db=threshold_db, release_ms=release_ms)
    out = plugin(buf.data, sample_rate=buf.sr)
    return AudioBuffer(data=np.asarray(out, dtype=np.float32), sr=buf.sr, subtype=buf.subtype)
