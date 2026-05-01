"""Tests for the ``lowpass`` op."""

from __future__ import annotations

import numpy as np

from audiocli.buffer import AudioBuffer
from audiocli.io import load, save
from audiocli.ops.lowpass import lowpass

SR = 44100


def _sine(freq: float, seconds: float = 1.0, amp: float = 0.5) -> AudioBuffer:
    t = np.arange(int(SR * seconds)) / SR
    data = (np.sin(2 * np.pi * freq * t) * amp).astype(np.float32)[None, :]
    return AudioBuffer(data=data, sr=SR, subtype="FLOAT")


def _rms(buf: AudioBuffer) -> float:
    return float(np.sqrt(np.mean(buf.data**2)))


def test_lowpass_round_trip(tmp_path):
    src = _sine(1000.0)
    out = lowpass(src, hz=2000.0)
    assert out.sr == src.sr
    assert out.data.shape == src.data.shape
    p = tmp_path / "out.wav"
    save(p, out)
    re = load(p)
    assert re.sr == src.sr


def test_lowpass_attenuates_high_passes_low():
    cutoff = 1000.0
    low = _sine(100.0)
    high = _sine(10000.0)
    low_out = lowpass(low, hz=cutoff)
    high_out = lowpass(high, hz=cutoff)
    assert _rms(high_out) < _rms(high) * 0.5
    assert _rms(low_out) > _rms(low) * 0.8


def test_lowpass_negative_silent_input_stays_silent():
    """Silent input through any low-pass cutoff must remain silent."""
    silent = AudioBuffer(data=np.zeros((1, SR), dtype=np.float32), sr=SR, subtype="FLOAT")
    out = lowpass(silent, hz=1000.0)
    assert float(np.max(np.abs(out.data))) == 0.0
