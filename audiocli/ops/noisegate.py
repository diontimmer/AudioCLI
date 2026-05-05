"""``noisegate`` — noise gate/expander via ``pedalboard.NoiseGate``."""

from __future__ import annotations

from typing import Annotated

import typer

from audiocli.buffer import AudioBuffer
from audiocli.registry import op


@op(name="noisegate", help="Noise gate / expander (pedalboard.NoiseGate).")
def noisegate(
    buf: AudioBuffer,
    threshold_db: Annotated[
        float, typer.Option("--threshold-db", help="Gate threshold in dB.")
    ] = -100.0,
    ratio: Annotated[float, typer.Option("--ratio", help="Gate/expander ratio.")] = 10.0,
    attack_ms: Annotated[
        float, typer.Option("--attack-ms", help="Attack time in milliseconds.")
    ] = 1.0,
    release_ms: Annotated[
        float, typer.Option("--release-ms", help="Release time in milliseconds.")
    ] = 100.0,
) -> AudioBuffer:
    """Gate low-level signal below ``threshold_db``."""
    import numpy as np  # noqa: PLC0415
    from pedalboard import NoiseGate  # noqa: PLC0415

    plugin = NoiseGate(
        threshold_db=threshold_db, ratio=ratio, attack_ms=attack_ms, release_ms=release_ms
    )
    out = plugin(buf.data, sample_rate=buf.sr)
    return AudioBuffer(data=np.asarray(out, dtype=np.float32), sr=buf.sr, subtype=buf.subtype)
