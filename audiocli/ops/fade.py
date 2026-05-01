"""``fade`` — apply linear/exp/cosine fade-in and fade-out envelopes."""

from __future__ import annotations

from typing import Annotated, Literal

import typer

from audiocli.buffer import AudioBuffer
from audiocli.errors import AudioCLIError
from audiocli.registry import op


@op(name="fade", help="Fade in/out with linear, exponential, or cosine shape.")
def fade(
    buf: AudioBuffer,
    fade_in_s: Annotated[
        float,
        typer.Option("--in", help="Fade-in duration in seconds."),
    ] = 0.0,
    fade_out_s: Annotated[
        float,
        typer.Option("--out", help="Fade-out duration in seconds."),
    ] = 0.0,
    shape: Annotated[
        Literal["linear", "exp", "cosine"],
        typer.Option("--shape", help="Envelope shape: linear, exp, or cosine."),
    ] = "linear",
) -> AudioBuffer:
    """Apply a fade-in and/or fade-out envelope to ``buf``."""
    if fade_in_s < 0 or fade_out_s < 0:
        raise AudioCLIError(
            f"fade: durations must be non-negative (got in={fade_in_s}, out={fade_out_s})"
        )
    if shape not in ("linear", "exp", "cosine"):
        raise AudioCLIError(f"fade: unknown shape '{shape}' (use linear, exp, or cosine)")

    import numpy as np  # noqa: PLC0415

    data = buf.data
    if data.dtype != np.float32:
        data = data.astype(np.float32, copy=False)

    n_samples = int(data.shape[1])
    if n_samples == 0 or (fade_in_s == 0.0 and fade_out_s == 0.0):
        return AudioBuffer(data=data.copy(), sr=buf.sr, subtype=buf.subtype)

    out = data.copy()

    fade_in_samples = min(int(round(fade_in_s * buf.sr)), n_samples)
    fade_out_samples = min(int(round(fade_out_s * buf.sr)), n_samples)

    if fade_in_samples > 0:
        env = _envelope(fade_in_samples, shape, fade_in=True)
        out[:, :fade_in_samples] *= env

    if fade_out_samples > 0:
        env = _envelope(fade_out_samples, shape, fade_in=False)
        out[:, n_samples - fade_out_samples :] *= env

    return AudioBuffer(data=out, sr=buf.sr, subtype=buf.subtype)


def _envelope(n: int, shape: str, *, fade_in: bool):
    """Return a length-``n`` envelope ramp for the given shape.

    ``fade_in=True`` ramps 0→1; ``fade_in=False`` ramps 1→0. The endpoints are
    inclusive: a fade-in starts at 0 and ends at 1.
    """
    import numpy as np  # noqa: PLC0415

    if n == 1:
        return np.ones(1, dtype=np.float32) if not fade_in else np.zeros(1, dtype=np.float32)

    t = np.linspace(0.0, 1.0, n, dtype=np.float64)
    if shape == "linear":
        env = t
    elif shape == "exp":
        # Exponential curve (perceptually closer to a logarithmic taper).
        # Use the canonical (e^(k*t) - 1) / (e^k - 1) shape with k=5.
        k = 5.0
        env = (np.exp(k * t) - 1.0) / (np.exp(k) - 1.0)
    else:  # cosine
        env = 0.5 - 0.5 * np.cos(np.pi * t)

    if not fade_in:
        env = env[::-1]
    return env.astype(np.float32, copy=False)
