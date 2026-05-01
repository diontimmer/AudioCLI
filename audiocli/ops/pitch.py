"""``pitch`` — pitch-shift a buffer by a fractional number of semitones."""

from __future__ import annotations

from typing import Annotated

import typer

from audiocli.buffer import AudioBuffer
from audiocli.registry import op


@op(name="pitch", help="Pitch-shift audio by a number of semitones (PitchShift, thread-safe).")
def pitch(
    buf: AudioBuffer,
    semitones: Annotated[
        float,
        typer.Option("--semitones", help="Pitch shift in semitones (12 = octave up)."),
    ],
) -> AudioBuffer:
    """Shift the pitch of ``buf`` by ``semitones`` using ``pedalboard.PitchShift``."""
    if semitones == 0.0:
        return AudioBuffer(data=buf.data, sr=buf.sr, subtype=buf.subtype)

    import numpy as np  # noqa: PLC0415
    from pedalboard import Pedalboard, PitchShift  # noqa: PLC0415

    board = Pedalboard([PitchShift(semitones=float(semitones))])
    out = board.process(buf.data, sample_rate=float(buf.sr), reset=True)
    if out.dtype != np.float32:
        out = out.astype(np.float32, copy=False)

    return AudioBuffer(data=out, sr=buf.sr, subtype=buf.subtype)
