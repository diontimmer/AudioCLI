"""Audio file I/O — thin wrappers around ``pedalboard.io.AudioFile``.

All format-specific behaviour (which bit depths each container supports,
how lossy quality is expressed, what extension maps to what format) lives
in this module. Op code stays format-agnostic.

Heavy imports (``pedalboard``, ``numpy``) are deferred into the function
bodies so importing this module is cheap. ``audiocli --help`` only loads
``typer`` and the registry.
"""

from __future__ import annotations

from pathlib import Path

from audiocli.buffer import AudioBuffer
from audiocli.errors import LoadError, SaveError

# Public list of supported formats (lower-case, no leading dot).
SUPPORTED_FORMATS: tuple[str, ...] = ("wav", "flac", "mp3", "ogg")

# Map a file extension (without the leading dot, lower-case) to a canonical
# format name. Aliases like ``.oga`` for Ogg-Vorbis live here so callers can
# pass user-supplied paths through ``format_for_extension`` without first
# normalising them.
_EXTENSION_TO_FORMAT: dict[str, str] = {
    "wav": "wav",
    "wave": "wav",
    "flac": "flac",
    "mp3": "mp3",
    "ogg": "ogg",
    "oga": "ogg",
}

# Canonical extension to write for each format.
_FORMAT_TO_EXTENSION: dict[str, str] = {
    "wav": ".wav",
    "flac": ".flac",
    "mp3": ".mp3",
    "ogg": ".ogg",
}

# Mapping between AudioCLI subtype names (PCM_8/16/24/32, FLOAT) and the
# pedalboard ``file_dtype`` strings the underlying decoder reports.
_PEDALBOARD_TO_SUBTYPE: dict[str, str] = {
    "int8": "PCM_8",
    "int16": "PCM_16",
    "int24": "PCM_24",
    "int32": "PCM_32",
    "float32": "FLOAT",
    "float64": "FLOAT",
}

# Per-format whitelist of subtypes pedalboard can write. When a buffer asks
# for a subtype the format does not support, the saver picks the closest
# legal match (largest available bit depth ≤ the request).
_FORMAT_SUBTYPES: dict[str, tuple[str, ...]] = {
    "wav": ("PCM_8", "PCM_16", "PCM_24", "FLOAT"),
    "flac": ("PCM_16", "PCM_24"),
    # MP3 and OGG are lossy; ``subtype`` is informational only — pedalboard
    # always decodes them as float32 and the encoder picks its own internal
    # representation. We still track ``"FLOAT"`` so reload comparisons work.
    "mp3": ("FLOAT",),
    "ogg": ("FLOAT",),
}

# Default subtype per format when the buffer carries no subtype hint.
_DEFAULT_SUBTYPE: dict[str, str] = {
    "wav": "PCM_16",
    "flac": "PCM_16",
    "mp3": "FLOAT",
    "ogg": "FLOAT",
}

# bit-depth integer pedalboard expects for each subtype.
_SUBTYPE_TO_BIT_DEPTH: dict[str, int] = {
    "PCM_8": 8,
    "PCM_16": 16,
    "PCM_24": 24,
    "PCM_32": 32,
    "FLOAT": 32,
}


def format_for_extension(ext: str) -> str | None:
    """Return the canonical format name for a file extension.

    ``ext`` may include the leading dot or not, and is matched
    case-insensitively. Returns ``None`` for unknown extensions.
    """
    e = ext.lower().lstrip(".")
    return _EXTENSION_TO_FORMAT.get(e)


def extension_for_format(fmt: str) -> str:
    """Return the canonical file extension (with leading dot) for a format."""
    f = fmt.lower()
    if f not in _FORMAT_TO_EXTENSION:
        raise SaveError(f"unsupported format: {fmt!r} (supported: {', '.join(SUPPORTED_FORMATS)})")
    return _FORMAT_TO_EXTENSION[f]


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
    fmt = format_for_extension(p.suffix)
    return AudioBuffer(data=data, sr=sr, subtype=subtype, format=fmt)


def save(
    path: str | Path,
    buf: AudioBuffer,
    *,
    subtype: str | None = None,
    format: str | None = None,
    quality: int | str | None = None,
) -> None:
    """Write `buf` to `path`.

    The format is resolved in this order:
        1. the explicit ``format=`` argument
        2. ``buf.format``
        3. the suffix of ``path``

    The ``subtype`` is resolved in this order:
        1. the explicit ``subtype=`` argument
        2. ``buf.subtype``
        3. the format's default

    If the requested subtype is not legal for the chosen format, the saver
    falls back to the closest available bit depth. ``quality`` is forwarded
    to pedalboard for lossy formats (MP3, OGG); it is ignored for lossless.

    Raises:
        SaveError: when the path is unwritable or the format/subtype combo
            cannot be resolved.
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)

    fmt = (format or buf.format or format_for_extension(p.suffix) or "").lower()
    if fmt not in _FORMAT_TO_EXTENSION:
        raise SaveError(
            f"unsupported output format for {p}: "
            f"got {fmt!r}, expected one of {', '.join(SUPPORTED_FORMATS)}"
        )

    chosen_subtype = (subtype or buf.subtype or _DEFAULT_SUBTYPE[fmt]).upper()
    chosen_subtype = _coerce_subtype(fmt, chosen_subtype)
    bit_depth = _SUBTYPE_TO_BIT_DEPTH[chosen_subtype]
    chosen_quality = quality if quality is not None else buf.quality

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

    channels = int(data.shape[0])
    kwargs: dict[str, object] = {
        "samplerate": int(buf.sr),
        "num_channels": channels,
        "bit_depth": bit_depth,
    }
    if chosen_quality is not None and fmt in {"mp3", "ogg"}:
        kwargs["quality"] = chosen_quality

    try:
        with AudioFile(str(p), "w", **kwargs) as f:
            f.write(data)
    except SaveError:
        raise
    except Exception as e:
        raise SaveError(f"failed to save {p}: {e}") from e


def _coerce_subtype(fmt: str, subtype: str) -> str:
    """Pick the closest legal subtype for ``fmt``.

    Rules:
        * If ``subtype`` is already legal, return it unchanged.
        * For lossy formats (MP3/OGG), always return ``FLOAT``.
        * For PCM/FLAC, walk down the bit-depth ladder to the largest
          supported bit depth ≤ the request.
    """
    legal = _FORMAT_SUBTYPES[fmt]
    if subtype in legal:
        return subtype

    if fmt in {"mp3", "ogg"}:
        return "FLOAT"

    requested_bits = _SUBTYPE_TO_BIT_DEPTH.get(subtype, 16)
    candidates = sorted(
        legal,
        key=lambda s: _SUBTYPE_TO_BIT_DEPTH[s],
        reverse=True,
    )
    for cand in candidates:
        if _SUBTYPE_TO_BIT_DEPTH[cand] <= requested_bits:
            return cand
    return _DEFAULT_SUBTYPE[fmt]
