"""Tests for the ``chorus`` op."""

from __future__ import annotations

import numpy as np

from audiocli.buffer import AudioBuffer
from audiocli.io import load, save
from audiocli.ops.chorus import chorus

SR = 44100


def _sine(freq: float = 440.0, seconds: float = 1.0, amp: float = 0.5) -> AudioBuffer:
    t = np.arange(int(SR * seconds)) / SR
    data = (np.sin(2 * np.pi * freq * t) * amp).astype(np.float32)[None, :]
    return AudioBuffer(data=data, sr=SR, subtype="FLOAT")


def test_chorus_round_trip(tmp_path):
    src = _sine()
    out = chorus(src)
    assert out.sr == src.sr
    assert out.data.shape == src.data.shape
    p = tmp_path / "out.wav"
    save(p, out)
    re = load(p)
    assert re.sr == src.sr


def test_chorus_alters_signal():
    src = _sine()
    out = chorus(src, rate_hz=2.0, depth=0.5, centre_delay_ms=10.0, feedback=0.0, mix=1.0)
    diff = float(np.mean(np.abs(out.data - src.data)))
    assert diff > 0.001


def test_chorus_negative_silent_input_stays_silent():
    """Silent input must remain silent — chorus has no internal noise source."""
    silent = AudioBuffer(data=np.zeros((1, SR), dtype=np.float32), sr=SR, subtype="FLOAT")
    out = chorus(silent)
    assert float(np.max(np.abs(out.data))) == 0.0
