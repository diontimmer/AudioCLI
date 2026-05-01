"""``bitdepth`` — set the output subtype for the next save.

Filter-shape op: leaves ``buf.data`` untouched and only flips the
``subtype`` so the saver writes the requested bit depth. The actual
quantisation happens in ``audiocli.io.save`` via pedalboard.
"""

from __future__ import annotations

from typing import Annotated

import typer

from audiocli.buffer import AudioBuffer
from audiocli.errors import OpError
from audiocli.registry import op

_BITDEPTH_TO_SUBTYPE: dict[int, str] = {
    8: "PCM_8",
    16: "PCM_16",
    24: "PCM_24",
    32: "FLOAT",
}


@op(
    name="bitdepth",
    help="Set the output bit depth (8, 16, 24, or 32) for the next save.",
)
def bitdepth(
    buf: AudioBuffer,
    bits: Annotated[
        int,
        typer.Option(
            "--bits",
            help="Target bit depth: 8, 16, 24, or 32 (32 = float).",
        ),
    ],
) -> AudioBuffer:
    """Mark the buffer to be saved at ``bits`` bit depth."""
    if bits not in _BITDEPTH_TO_SUBTYPE:
        raise OpError(f"unsupported bitdepth {bits}; expected 8, 16, 24 or 32")
    return AudioBuffer(
        data=buf.data,
        sr=buf.sr,
        subtype=_BITDEPTH_TO_SUBTYPE[bits],
        format=buf.format,
        quality=buf.quality,
    )
