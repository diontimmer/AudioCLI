"""``bitcrush`` — bit-depth reduction via ``pedalboard.Bitcrush``."""

from __future__ import annotations

from typing import Annotated

import typer

from audiocli.buffer import AudioBuffer
from audiocli.registry import op


@op(name="bitcrush", help="Bit-depth reduction (pedalboard.Bitcrush).")
def bitcrush(
    buf: AudioBuffer,
    bit_depth: Annotated[
        float,
        typer.Option("--bit-depth", help="Effective bit depth (lower = harsher quantization)."),
    ] = 8.0,
) -> AudioBuffer:
    """Quantize the signal to ``bit_depth`` bits."""
    import numpy as np  # noqa: PLC0415
    from pedalboard import Bitcrush  # noqa: PLC0415

    plugin = Bitcrush(bit_depth=bit_depth)
    out = plugin(buf.data, sample_rate=buf.sr)
    return AudioBuffer(data=np.asarray(out, dtype=np.float32), sr=buf.sr, subtype=buf.subtype)
