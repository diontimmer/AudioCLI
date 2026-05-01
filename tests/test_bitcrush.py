"""Tests for the ``bitcrush`` op."""

from __future__ import annotations

import numpy as np
import pytest

from audiocli.buffer import AudioBuffer
from audiocli.io import load, save
from audiocli.ops.bitcrush import bitcrush

SR = 44100


def _sine(freq: float = 440.0, seconds: float = 0.5, amp: float = 0.5) -> AudioBuffer:
    t = np.arange(int(SR * seconds)) / SR
    data = (np.sin(2 * np.pi * freq * t) * amp).astype(np.float32)[None, :]
    return AudioBuffer(data=data, sr=SR, subtype="FLOAT")


def test_bitcrush_round_trip(tmp_path):
    src = _sine()
    out = bitcrush(src, bit_depth=8.0)
    assert out.sr == src.sr
    assert out.data.shape == src.data.shape
    p = tmp_path / "out.wav"
    save(p, out)
    re = load(p)
    assert re.sr == src.sr


def test_bitcrush_quantizes_signal():
    src = _sine()
    out = bitcrush(src, bit_depth=4.0)
    # A 4-bit quantization yields at most ~16 distinct levels — far fewer than the
    # near-continuous float32 sine input.
    src_unique = len(np.unique(np.round(src.data, 6)))
    out_unique = len(np.unique(np.round(out.data, 6)))
    assert out_unique < src_unique
    assert out_unique <= 64


def test_bitcrush_negative_invalid_bit_depth_raises():
    src = _sine()
    with pytest.raises(ValueError):
        bitcrush(src, bit_depth=-1.0)
