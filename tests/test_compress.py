"""Tests for the ``compress`` op."""

from __future__ import annotations

import numpy as np
import pytest
from typer.testing import CliRunner

from audiocli.buffer import AudioBuffer
from audiocli.cli import app
from audiocli.io import load, save
from audiocli.ops.compress import compress

SR = 44100


def _loud_sine(seconds: float = 1.0, amp: float = 0.9, freq: float = 440.0) -> AudioBuffer:
    t = np.arange(int(SR * seconds)) / SR
    data = (np.sin(2 * np.pi * freq * t) * amp).astype(np.float32)[None, :]
    return AudioBuffer(data=data, sr=SR, subtype="FLOAT")


def test_compress_round_trip(tmp_path):
    src = _loud_sine()
    out = compress(src, threshold_db=-20.0, ratio=4.0, attack_ms=1.0, release_ms=100.0)
    assert out.sr == src.sr
    assert out.data.shape == src.data.shape
    assert out.data.dtype == np.float32
    p = tmp_path / "out.wav"
    save(p, out)
    re = load(p)
    assert re.sr == src.sr


def test_compress_reduces_peak_when_input_exceeds_threshold():
    src = _loud_sine(amp=0.9)
    out = compress(src, threshold_db=-30.0, ratio=10.0, attack_ms=0.5, release_ms=50.0)
    src_peak = float(np.max(np.abs(src.data)))
    out_peak = float(np.max(np.abs(out.data)))
    assert out_peak < src_peak


def test_compress_negative_invalid_ratio_raises():
    src = _loud_sine()
    with pytest.raises(ValueError):
        compress(src, threshold_db=-20.0, ratio=-1.0, attack_ms=1.0, release_ms=100.0)


def test_cli_compress_runs_end_to_end(tmp_path):
    src = _loud_sine(amp=0.5)
    src_path = tmp_path / "src.wav"
    save(src_path, src)
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "compress",
            "--target",
            str(src_path),
            "--output",
            str(tmp_path / "out.wav"),
            "--threshold-db",
            "-30",
            "--ratio",
            "8",
        ],
    )
    assert result.exit_code == 0, result.output
