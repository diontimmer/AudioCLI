"""Tests for the ``delay`` op."""

from __future__ import annotations

import numpy as np
import pytest

from audiocli.buffer import AudioBuffer
from audiocli.io import load, save
from audiocli.ops.delay import delay

SR = 44100


def _click(seconds: float = 1.5) -> AudioBuffer:
    n = int(SR * seconds)
    data = np.zeros((1, n), dtype=np.float32)
    data[0, :64] = 0.9
    return AudioBuffer(data=data, sr=SR, subtype="FLOAT")


def test_delay_round_trip(tmp_path):
    src = _click()
    out = delay(src, time_s=0.25, feedback=0.0, mix=0.5)
    assert out.sr == src.sr
    assert out.data.shape == src.data.shape
    p = tmp_path / "out.wav"
    save(p, out)
    re = load(p)
    assert re.sr == src.sr


def test_delay_produces_repeat_at_configured_time():
    src = _click()
    delay_time = 0.25
    out = delay(src, time_s=delay_time, feedback=0.0, mix=1.0)
    # Find the loudest peak after the original click region.
    after_click = out.data[0, 1024:]
    peak_idx = int(np.argmax(np.abs(after_click))) + 1024
    peak_t = peak_idx / SR
    # Should be near the configured delay (allow ±10ms slack).
    assert abs(peak_t - delay_time) < 0.01


def test_delay_negative_feedback_oob_raises():
    src = _click()
    with pytest.raises(ValueError):
        delay(src, time_s=0.25, feedback=2.0, mix=0.5)
