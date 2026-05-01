"""The `AudioBuffer` value type — the unit every op consumes and produces.

Numpy is referenced only as a type annotation here; the import is deferred
to keep `audiocli --help` fast.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import numpy as np


@dataclass
class AudioBuffer:
    """A chunk of audio in float32, channels-first layout.

    Attributes:
        data: ndarray of shape ``(channels, samples)`` and dtype ``float32`` —
            the same shape pedalboard expects for its plugin chains.
        sr: sample rate in Hz.
        subtype: original file subtype (e.g. ``"PCM_16"``, ``"PCM_24"``,
            ``"FLOAT"``) so that round-trips can preserve bit depth. ``None``
            means "use the saver's default".
        format: optional output format override (``"wav"``, ``"flac"``,
            ``"mp3"``, ``"ogg"``). ``None`` means "infer from output path".
            Set by ops like ``convert`` to request a format change on save.
        quality: optional encoder quality hint passed to lossy formats
            (kbps int for MP3/OGG, or a string like ``"V0"`` for MP3 VBR).
            Ignored for lossless formats.
    """

    data: np.ndarray
    sr: int
    subtype: str | None = None
    format: str | None = None
    quality: int | str | None = None
