"""Audio file I/O — thin wrappers around ``pedalboard.io.AudioFile``.

Heavy imports (``pedalboard``, ``numpy``) are deferred into the function
bodies so importing this module is cheap. ``audiocli --help`` only loads
``typer`` and the registry.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from audiocli.buffer import AudioBuffer
from audiocli.errors import LoadError, SaveError

if TYPE_CHECKING:
    pass


# Mapping between AudioCLI subtype names (PCM_16, PCM_24, FLOAT) and
# pedalboard's `file_dtype` strings (int16, int24, float32).
_SUBTYPE_TO_PEDALBOARD: dict[str, tuple[int, str]] = {
    "PCM_8": (8, "int8"),
    "PCM_16": (16, "int16"),
    "PCM_24": (24, "int24"),
    "FLOAT": (32, "float32"),
}

_PEDALBOARD_TO_SUBTYPE: dict[str, str] = {
    "int8": "PCM_8",
    "int16": "PCM_16",
    "int24": "PCM_24",
    "int32": "PCM_32",
    "float32": "FLOAT",
    "float64": "FLOAT",
}


def load(path: str | Path) -> AudioBuffer:
    """Load an audio file into an `AudioBuffer`.

    Raises:
        LoadError: when the file is missing, unreadable, or not a recognised
            audio format.
    """
    p = Path(path)
    if not p.exists():
        raise LoadError(f"file not found: {p}")
    if not p.is_file():
        raise LoadError(f"not a regular file: {p}")

    try:
        from pedalboard.io import AudioFile  # noqa: PLC0415
    except ImportError as e:  # pragma: no cover
        raise LoadError(f"pedalboard is not installed: {e}") from e

    try:
        with AudioFile(str(p)) as f:
            sr = int(f.samplerate)
            data = f.read(f.frames)
            file_dtype = str(getattr(f, "file_dtype", "") or "")
    except LoadError:
        raise
    except Exception as e:
        raise LoadError(f"failed to load {p}: {e}") from e

    import numpy as np  # noqa: PLC0415

    if data.dtype != np.float32:
        data = data.astype(np.float32, copy=False)
    subtype = _PEDALBOARD_TO_SUBTYPE.get(file_dtype, file_dtype.upper() or None)
    return AudioBuffer(data=data, sr=sr, subtype=subtype)


def save(
    path: str | Path,
    buf: AudioBuffer,
    *,
    subtype: str | None = None,
) -> None:
    """Write `buf` to `path`. ``subtype`` overrides ``buf.subtype``.

    Raises:
        SaveError: when the file cannot be opened or the data is malformed.
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)

    try:
        from pedalboard.io import AudioFile  # noqa: PLC0415
    except ImportError as e:  # pragma: no cover
        raise SaveError(f"pedalboard is not installed: {e}") from e

    import numpy as np  # noqa: PLC0415

    data = buf.data
    if data.ndim != 2:
        raise SaveError(f"buffer data must be 2-D (channels, samples); got shape {data.shape}")
    if data.dtype != np.float32:
        data = data.astype(np.float32, copy=False)

    chosen = subtype or buf.subtype
    bit_depth = _bit_depth_for(chosen)
    channels = int(data.shape[0])

    try:
        with AudioFile(
            str(p),
            "w",
            samplerate=int(buf.sr),
            num_channels=channels,
            bit_depth=bit_depth,
        ) as f:
            f.write(data)
    except SaveError:
        raise
    except Exception as e:
        raise SaveError(f"failed to save {p}: {e}") from e


def _bit_depth_for(subtype: str | None) -> int:
    """Resolve a subtype name to the bit-depth pedalboard expects."""
    if subtype is None:
        return 16
    spec = _SUBTYPE_TO_PEDALBOARD.get(subtype.upper())
    if spec is not None:
        return spec[0]
    # Fall back to 16-bit when the subtype is unfamiliar.
    return 16
