"""Tests for the ``limit`` op."""

from __future__ import annotations

import numpy as np

from audiocli.buffer import AudioBuffer
from audiocli.io import load, save
from audiocli.ops.limit import limit

SR = 44100


def _hot_sine(seconds: float = 0.5, amp: float = 0.95, freq: float = 440.0) -> AudioBuffer:
    t = np.arange(int(SR * seconds)) / SR
    data = (np.sin(2 * np.pi * freq * t) * amp).astype(np.float32)[None, :]
    return AudioBuffer(data=data, sr=SR, subtype="FLOAT")


def test_limit_round_trip(tmp_path):
    src = _hot_sine()
    out = limit(src, threshold_db=-3.0)
    assert out.sr == src.sr
    assert out.data.shape == src.data.shape
    p = tmp_path / "out.wav"
    save(p, out)
    re = load(p)
    assert re.sr == src.sr


def test_limit_reduces_peak_for_signal_above_threshold():
    """In steady state the limiter must hold a hot signal below its raw peak."""
    src = _hot_sine(seconds=2.0, amp=0.99)
    threshold_db = -3.0
    out = limit(src, threshold_db=threshold_db, release_ms=10.0)
    # Drop the attack transient so we can read the steady-state peak.
    steady = out.data[0, SR // 5 :]
    steady_peak = float(np.max(np.abs(steady)))
    src_peak = float(np.max(np.abs(src.data)))
    assert steady_peak < src_peak


def test_limit_negative_silent_input_stays_silent():
    """Silent input must remain silent — limiting cannot fabricate signal."""
    silent = AudioBuffer(data=np.zeros((1, SR), dtype=np.float32), sr=SR, subtype="FLOAT")
    out = limit(silent, threshold_db=-3.0, release_ms=100.0)
    assert float(np.max(np.abs(out.data))) == 0.0
