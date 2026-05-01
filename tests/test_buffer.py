"""Round-trip tests for `AudioBuffer` + `audiocli.io`."""

from __future__ import annotations

import numpy as np
import pytest

from audiocli.buffer import AudioBuffer
from audiocli.io import load, save


@pytest.mark.parametrize("subtype", ["PCM_16", "PCM_24", "FLOAT"])
@pytest.mark.parametrize("channels", [1, 2])
def test_wav_round_trip_preserves_shape_sr_subtype(tmp_path, subtype, channels):
    sr = 44100
    n = sr  # one second
    rng = np.random.default_rng(0)
    data = rng.standard_normal((channels, n)).astype(np.float32) * 0.1
    buf = AudioBuffer(data=data, sr=sr, subtype=subtype)

    p = tmp_path / f"{subtype}_{channels}.wav"
    save(p, buf)

    re = load(p)
    assert re.sr == sr
    assert re.data.shape == (channels, n)
    assert re.data.dtype == np.float32
    assert re.subtype == subtype


def test_save_creates_parent_dir(tmp_path):
    sr = 44100
    buf = AudioBuffer(data=np.zeros((1, 100), dtype=np.float32), sr=sr, subtype="PCM_16")
    p = tmp_path / "nested" / "deeper" / "out.wav"
    save(p, buf)
    assert p.exists()


def test_save_subtype_override(tmp_path):
    sr = 44100
    buf = AudioBuffer(
        data=np.zeros((1, 100), dtype=np.float32),
        sr=sr,
        subtype="PCM_16",
    )
    p = tmp_path / "out.wav"
    save(p, buf, subtype="PCM_24")
    assert load(p).subtype == "PCM_24"
