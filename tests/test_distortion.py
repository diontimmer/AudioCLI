"""Tests for the ``distortion`` op."""

from __future__ import annotations

import numpy as np

from audiocli.buffer import AudioBuffer
from audiocli.io import load, save
from audiocli.ops.distortion import distortion

SR = 44100


def _sine(freq: float = 440.0, seconds: float = 0.5, amp: float = 0.3) -> AudioBuffer:
    t = np.arange(int(SR * seconds)) / SR
    data = (np.sin(2 * np.pi * freq * t) * amp).astype(np.float32)[None, :]
    return AudioBuffer(data=data, sr=SR, subtype="FLOAT")


def _rms(buf: AudioBuffer) -> float:
    return float(np.sqrt(np.mean(buf.data**2)))


def test_distortion_round_trip(tmp_path):
    src = _sine()
    out = distortion(src, drive_db=10.0)
    assert out.sr == src.sr
    assert out.data.shape == src.data.shape
    p = tmp_path / "out.wav"
    save(p, out)
    re = load(p)
    assert re.sr == src.sr


def test_distortion_increases_rms():
    src = _sine(amp=0.3)
    out = distortion(src, drive_db=30.0)
    # Hard drive raises perceived loudness via clipping.
    assert _rms(out) > _rms(src)


def test_distortion_negative_silent_input_stays_silent():
    """Silent input must remain silent — distortion has no internal source."""
    silent = AudioBuffer(data=np.zeros((1, SR), dtype=np.float32), sr=SR, subtype="FLOAT")
    out = distortion(silent, drive_db=30.0)
    assert float(np.max(np.abs(out.data))) == 0.0
