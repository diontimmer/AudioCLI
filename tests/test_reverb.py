"""Tests for the ``reverb`` op."""

from __future__ import annotations

import numpy as np
import pytest

from audiocli.buffer import AudioBuffer
from audiocli.io import load, save
from audiocli.ops.reverb import reverb

SR = 44100


def _impulse(seconds: float = 2.0) -> AudioBuffer:
    n = int(SR * seconds)
    data = np.zeros((1, n), dtype=np.float32)
    # short percussive burst at the start.
    burst_len = int(0.005 * SR)
    data[0, :burst_len] = 0.8
    return AudioBuffer(data=data, sr=SR, subtype="FLOAT")


def test_reverb_round_trip(tmp_path):
    src = _impulse()
    out = reverb(src, room_size=0.5, wet=0.5, dry=0.5)
    assert out.sr == src.sr
    assert out.data.shape == src.data.shape
    p = tmp_path / "out.wav"
    save(p, out)
    re = load(p)
    assert re.sr == src.sr


def test_reverb_adds_tail_energy():
    src = _impulse()
    out = reverb(src, room_size=0.9, wet=0.9, dry=0.5)
    # Energy after the initial burst should be substantially higher with reverb.
    burst_len = int(0.005 * SR)
    src_tail_rms = float(np.sqrt(np.mean(src.data[:, burst_len:] ** 2)))
    out_tail_rms = float(np.sqrt(np.mean(out.data[:, burst_len:] ** 2)))
    assert out_tail_rms > src_tail_rms


def test_reverb_negative_invalid_room_size_raises():
    src = _impulse()
    with pytest.raises(ValueError):
        reverb(src, room_size=5.0, wet=0.5, dry=0.5)
