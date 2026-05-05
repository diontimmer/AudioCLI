"""``convolve`` — convolution with an impulse response via ``pedalboard.Convolution``."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from audiocli.buffer import AudioBuffer
from audiocli.errors import AudioCLIError
from audiocli.registry import op


@op(name="convolve", help="Convolve audio with an impulse response file (pedalboard.Convolution).")
def convolve(
    buf: AudioBuffer,
    impulse_response: Annotated[
        Path,
        typer.Option("--impulse-response", "--ir", help="Path to an impulse response audio file."),
    ],
    mix: Annotated[
        float,
        typer.Option("--mix", help="Wet/dry convolution mix from 0.0 to 1.0."),
    ] = 1.0,
) -> AudioBuffer:
    """Convolve ``buf`` with an impulse response file."""
    ir_path = Path(impulse_response).expanduser()
    if not ir_path.exists():
        raise AudioCLIError(f"convolve: impulse response not found: {ir_path}")

    import numpy as np  # noqa: PLC0415
    from pedalboard import Convolution  # noqa: PLC0415

    plugin = Convolution(str(ir_path), mix=mix)
    out = plugin(buf.data, sample_rate=buf.sr)
    return AudioBuffer(data=np.asarray(out, dtype=np.float32), sr=buf.sr, subtype=buf.subtype)
