"""``ladder`` — Moog-style ladder filter via ``pedalboard.LadderFilter``."""

from __future__ import annotations

from typing import Annotated, Literal

import typer

from audiocli.buffer import AudioBuffer
from audiocli.errors import AudioCLIError
from audiocli.registry import op

LADDER_MODE = Literal["LPF12", "LPF24", "HPF12", "HPF24", "BPF12", "BPF24"]


@op(name="ladder", help="Moog-style multimode ladder filter (pedalboard.LadderFilter).")
def ladder(
    buf: AudioBuffer,
    mode: Annotated[
        LADDER_MODE,
        typer.Option("--mode", help="Filter mode: LPF12, LPF24, HPF12, HPF24, BPF12, or BPF24."),
    ] = "LPF12",
    cutoff_hz: Annotated[
        float, typer.Option("--cutoff-hz", help="Cutoff frequency in Hz.")
    ] = 200.0,
    resonance: Annotated[float, typer.Option("--resonance", help="Filter resonance amount.")] = 0.0,
    drive: Annotated[float, typer.Option("--drive", help="Input drive amount.")] = 1.0,
) -> AudioBuffer:
    """Apply Moog-style ladder filtering."""
    import numpy as np  # noqa: PLC0415
    from pedalboard import LadderFilter  # noqa: PLC0415

    try:
        mode_enum = getattr(LadderFilter, mode)
    except AttributeError as exc:
        raise AudioCLIError(f"ladder: unknown mode {mode!r}") from exc
    plugin = LadderFilter(mode=mode_enum, cutoff_hz=cutoff_hz, resonance=resonance, drive=drive)
    out = plugin(buf.data, sample_rate=buf.sr)
    return AudioBuffer(data=np.asarray(out, dtype=np.float32), sr=buf.sr, subtype=buf.subtype)
