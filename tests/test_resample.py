"""Tests for the `resample` op — round-trip, correctness, quality, negative."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from typer.testing import CliRunner

from audiocli.buffer import AudioBuffer
from audiocli.cli import app
from audiocli.errors import AudioCLIError
from audiocli.io import load, save
from audiocli.ops.resample import resample

DATA = Path(__file__).parent / "data" / "test_song.wav"


def _sine(freq_hz: float, sr: int, duration_s: float = 1.0, channels: int = 1) -> AudioBuffer:
    n = int(sr * duration_s)
    t = np.arange(n, dtype=np.float32) / sr
    wave = np.sin(2 * np.pi * freq_hz * t).astype(np.float32) * 0.5
    data = np.tile(wave, (channels, 1))
    return AudioBuffer(data=data, sr=sr, subtype="FLOAT")


def test_resample_round_trip(tmp_path):
    buf = load(DATA)
    out = resample(buf, sr=buf.sr)  # no-op
    p = tmp_path / "out.wav"
    save(p, out)
    re = load(p)
    assert re.sr == buf.sr
    assert re.data.shape == buf.data.shape


def test_resample_correctness_halves_frame_count():
    src = _sine(440.0, sr=44100, duration_s=1.0)
    out = resample(src, sr=22050)
    assert out.sr == 22050
    expected = src.data.shape[1] * 22050 // 44100
    # Allow ±2 frames for filter delay per the spec.
    assert abs(out.data.shape[1] - expected) <= 2


def test_resample_quality_thd_round_trip():
    sr = 44100
    src = _sine(1000.0, sr=sr, duration_s=1.0)
    down = resample(src, sr=22050)
    back = resample(down, sr=sr)

    # Trim transients from the start/end before measuring.
    n = back.data.shape[1]
    pad = sr // 20  # 50 ms
    seg = back.data[0, pad : n - pad]
    if seg.size > src.data.shape[1] - 2 * pad:
        seg = seg[: src.data.shape[1] - 2 * pad]

    spectrum = np.fft.rfft(seg * np.hanning(len(seg)))
    mag = np.abs(spectrum)
    freqs = np.fft.rfftfreq(len(seg), d=1.0 / sr)

    fundamental_idx = int(np.argmin(np.abs(freqs - 1000.0)))
    # Sum power in a small bin around the fundamental.
    bin_pad = 3
    sig_power = float(np.sum(mag[fundamental_idx - bin_pad : fundamental_idx + bin_pad + 1] ** 2))
    total_power = float(np.sum(mag**2))
    noise_power = max(total_power - sig_power, 0.0)
    thd = float(np.sqrt(noise_power / sig_power)) if sig_power > 0 else float("inf")
    assert thd < 0.01, f"THD too high: {thd:.5f}"


def test_resample_negative_zero_sr_raises():
    src = _sine(440.0, sr=44100, duration_s=0.1)
    with pytest.raises(AudioCLIError):
        resample(src, sr=0)


def test_cli_resample_runs_end_to_end(tmp_path):
    sr = 44100
    src = _sine(440.0, sr=sr, duration_s=0.2)
    src_path = tmp_path / "src.wav"
    save(src_path, src)
    out = tmp_path / "out.wav"

    runner = CliRunner()
    result = runner.invoke(
        app,
        ["resample", "--target", str(src_path), "--output", str(out), "--sr", "22050"],
    )
    assert result.exit_code == 0, result.output
    assert out.exists()
    re = load(out)
    assert re.sr == 22050
