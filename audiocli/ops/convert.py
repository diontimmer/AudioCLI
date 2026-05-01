"""``convert`` — change the output container format.

This is a filter-shape op: it does not touch ``buf.data``; it only marks
the buffer with the desired output format (and optionally a bit depth /
quality hint) so the next ``save`` writes the new format. Format-specific
behaviour lives in ``audiocli.io``; this op stays format-agnostic.
"""

from __future__ import annotations

from typing import Annotated

import typer

from audiocli.buffer import AudioBuffer
from audiocli.errors import OpError
from audiocli.io import SUPPORTED_FORMATS
from audiocli.registry import op

_BITDEPTH_TO_SUBTYPE: dict[int, str] = {
    8: "PCM_8",
    16: "PCM_16",
    24: "PCM_24",
    32: "FLOAT",
}


@op(
    name="convert",
    help="Change the output format (wav, flac, mp3, ogg).",
)
def convert(
    buf: AudioBuffer,
    format: Annotated[
        str,
        typer.Option(
            "--format",
            "-f",
            help="Target format: wav, flac, mp3, or ogg.",
        ),
    ],
    bitdepth: Annotated[
        int | None,
        typer.Option(
            "--bitdepth",
            help="Target bit depth (8/16/24/32). Ignored for lossy formats.",
        ),
    ] = None,
    quality: Annotated[
        str | None,
        typer.Option(
            "--quality",
            help="Encoder quality for lossy formats (e.g. 192 for kbps, V0 for MP3 VBR).",
        ),
    ] = None,
) -> AudioBuffer:
    """Mark the buffer for output in a different format on next save."""
    fmt = format.lower().lstrip(".")
    if fmt not in SUPPORTED_FORMATS:
        raise OpError(
            f"unsupported format {format!r}; expected one of {', '.join(SUPPORTED_FORMATS)}"
        )

    new_subtype = buf.subtype
    if bitdepth is not None:
        if bitdepth not in _BITDEPTH_TO_SUBTYPE:
            raise OpError(f"unsupported bitdepth {bitdepth}; expected 8, 16, 24 or 32")
        new_subtype = _BITDEPTH_TO_SUBTYPE[bitdepth]

    new_quality: int | str | None = buf.quality
    if quality is not None:
        new_quality = _parse_quality(quality)

    return AudioBuffer(
        data=buf.data,
        sr=buf.sr,
        subtype=new_subtype,
        format=fmt,
        quality=new_quality,
    )


def _parse_quality(value: str) -> int | str:
    """Coerce a CLI ``--quality`` string to ``int`` when numeric."""
    s = value.strip()
    try:
        return int(s)
    except ValueError:
        return s
