"""Round-trip and error-path tests for `audiocli.io`."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from audiocli.buffer import AudioBuffer
from audiocli.errors import LoadError, SaveError
from audiocli.io import (
    SUPPORTED_FORMATS,
    extension_for_format,
    format_for_extension,
    load,
    save,
)

DATA = Path(__file__).parent / "data" / "test_song.wav"


def _signal(channels: int, n: int, freq: float = 440.0, sr: int = 44100) -> np.ndarray:
    t = np.arange(n) / sr
    mono = (np.sin(2 * np.pi * freq * t) * 0.5).astype(np.float32)
    return np.tile(mono[None, :], (channels, 1))


@pytest.mark.parametrize("subtype", ["PCM_16", "PCM_24", "FLOAT"])
@pytest.mark.parametrize("channels", [1, 2])
def test_wav_roundtrip(tmp_path, subtype, channels):
    sr = 44100
    n = sr  # one second
    buf = AudioBuffer(data=_signal(channels, n, sr=sr), sr=sr, subtype=subtype)

    p = tmp_path / f"{subtype}_{channels}.wav"
    save(p, buf)

    re = load(p)
    assert re.sr == sr
    assert re.data.shape == (channels, n)
    assert re.data.dtype == np.float32
    assert re.subtype == subtype
    assert re.format == "wav"


@pytest.mark.parametrize("subtype", ["PCM_16", "PCM_24"])
@pytest.mark.parametrize("channels", [1, 2])
def test_flac_roundtrip(tmp_path, subtype, channels):
    sr = 44100
    n = sr
    src = _signal(channels, n, sr=sr) * 0.5
    buf = AudioBuffer(data=src.astype(np.float32), sr=sr, subtype=subtype)
    p = tmp_path / f"out_{subtype}_{channels}.flac"
    save(p, buf)
    re = load(p)
    assert re.sr == sr
    assert re.data.shape == (channels, n)
    assert re.subtype == subtype
    assert re.format == "flac"
    # Lossless: peak preserved within the quantisation step of the bit depth.
    tol = 1.0 / (2 ** (16 if subtype == "PCM_16" else 24)) * 4
    assert np.max(np.abs(re.data - src)) <= tol


@pytest.mark.parametrize("channels", [1, 2])
def test_mp3_roundtrip(tmp_path, channels):
    sr = 44100
    n = sr
    src = _signal(channels, n, sr=sr) * 0.4
    buf = AudioBuffer(data=src.astype(np.float32), sr=sr)
    p = tmp_path / f"out_{channels}.mp3"
    save(p, buf, quality=192)
    re = load(p)
    assert re.sr == sr
    assert re.data.shape[0] == channels
    # MP3 typically pads with a couple of frames of silence; allow ~0.1s.
    assert abs(re.data.shape[1] - n) <= int(sr * 0.1)
    assert re.format == "mp3"
    assert re.subtype == "FLOAT"
    # Lossy: peak should still be in the same neighbourhood as the source.
    src_peak = float(np.max(np.abs(src)))
    re_peak = float(np.max(np.abs(re.data)))
    assert re_peak == pytest.approx(src_peak, abs=0.1)


@pytest.mark.parametrize("channels", [1, 2])
def test_ogg_roundtrip(tmp_path, channels):
    sr = 44100
    n = sr
    src = _signal(channels, n, sr=sr) * 0.4
    buf = AudioBuffer(data=src.astype(np.float32), sr=sr)
    p = tmp_path / f"out_{channels}.ogg"
    save(p, buf, quality=192)
    re = load(p)
    assert re.sr == sr
    assert re.data.shape[0] == channels
    assert abs(re.data.shape[1] - n) <= int(sr * 0.1)
    assert re.format == "ogg"
    src_peak = float(np.max(np.abs(src)))
    re_peak = float(np.max(np.abs(re.data)))
    assert re_peak == pytest.approx(src_peak, abs=0.1)


def test_corrupt_load(tmp_path):
    bad = tmp_path / "bad.wav"
    bad.write_bytes(b"not a real audio file at all, definitely corrupt")
    with pytest.raises(LoadError):
        load(bad)


def test_load_missing_file(tmp_path):
    with pytest.raises(LoadError):
        load(tmp_path / "nope.wav")


def test_save_unsupported_format(tmp_path):
    buf = AudioBuffer(data=np.zeros((1, 100), dtype=np.float32), sr=44100)
    with pytest.raises(SaveError):
        save(tmp_path / "out.xyz", buf)


def test_format_for_extension():
    assert format_for_extension(".WAV") == "wav"
    assert format_for_extension("wav") == "wav"
    assert format_for_extension(".flac") == "flac"
    assert format_for_extension(".oga") == "ogg"
    assert format_for_extension(".unknown") is None


def test_extension_for_format():
    assert extension_for_format("flac") == ".flac"
    with pytest.raises(SaveError):
        extension_for_format("xyz")


def test_supported_formats_complete():
    assert set(SUPPORTED_FORMATS) == {"wav", "flac", "mp3", "ogg"}


def test_save_format_override_changes_encoding(tmp_path):
    """Passing format= should override the path suffix."""
    sr = 44100
    buf = AudioBuffer(data=_signal(1, sr, sr=sr) * 0.3, sr=sr, subtype="PCM_16")
    # Path suffix says .ogg, but the explicit format= argument is what
    # actually drives encoding — verify by writing to an .ogg suffix path
    # while the buffer's format hint says wav.
    buf.format = "wav"
    p_ogg = tmp_path / "out_via_override.ogg"
    save(p_ogg, buf, format="ogg")
    re = load(p_ogg)
    assert re.format == "ogg"


def test_load_test_song_populates_subtype_and_format():
    buf = load(DATA)
    assert buf.subtype in {"PCM_16", "PCM_24", "FLOAT"}
    assert buf.format == "wav"


def test_save_falls_back_to_legal_subtype(tmp_path):
    """FLAC does not support 8-bit; saver should pick a supported depth."""
    sr = 22050
    buf = AudioBuffer(data=_signal(1, sr, sr=sr) * 0.3, sr=sr, subtype="PCM_8")
    p = tmp_path / "out.flac"
    save(p, buf)
    re = load(p)
    # Must downgrade gracefully, not crash. The result is one of FLAC's legal
    # subtypes — we don't pin which one, just that it round-trips.
    assert re.subtype in {"PCM_16", "PCM_24"}
