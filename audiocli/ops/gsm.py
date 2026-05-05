"""``gsm`` — GSM full-rate codec degradation via ``pedalboard.GSMFullRateCompressor``."""

from __future__ import annotations

from typing import Annotated, Literal

import typer

from audiocli.buffer import AudioBuffer
from audiocli.errors import AudioCLIError
from audiocli.registry import op

GSM_QUALITY = Literal[
    "ZeroOrderHold",
    "Linear",
    "CatmullRom",
    "Lagrange",
    "WindowedSinc",
    "WindowedSinc8",
    "WindowedSinc16",
    "WindowedSinc32",
    "WindowedSinc64",
    "WindowedSinc128",
    "WindowedSinc256",
]


@op(name="gsm", help="GSM full-rate phone codec degradation (pedalboard.GSMFullRateCompressor).")
def gsm(
    buf: AudioBuffer,
    quality: Annotated[
        GSM_QUALITY,
        typer.Option("--quality", help="Resampling quality used by the GSM codec stage."),
    ] = "WindowedSinc8",
) -> AudioBuffer:
    """Apply 2G GSM full-rate codec artifacts."""
    import numpy as np  # noqa: PLC0415
    from pedalboard import GSMFullRateCompressor, Resample  # noqa: PLC0415

    try:
        quality_enum = getattr(Resample.Quality, quality)
    except AttributeError as exc:
        raise AudioCLIError(f"gsm: unknown quality {quality!r}") from exc
    plugin = GSMFullRateCompressor(quality=quality_enum)
    out = plugin(buf.data, sample_rate=buf.sr)
    return AudioBuffer(data=np.asarray(out, dtype=np.float32), sr=buf.sr, subtype=buf.subtype)
