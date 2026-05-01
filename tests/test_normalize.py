"""Tests for the `normalize` op — round-trip, peak, LUFS, and negative cases."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from typer.testing import CliRunner

from audiocli.buffer import AudioBuffer
from audiocli.cli import app
from audiocli.errors import OpError
from audiocli.io import load, save
from audiocli.ops.normalize import normalize

DATA = Path(__file__).parent / "data" / "test_song.wav"


def test_normalize_round_trip(tmp_path):
    buf = load(DATA)
    out = normalize(buf, peak_db=-1.0)
    p = tmp_path / "out.wav"
    save(p, out)
    re = load(p)
    assert re.sr == buf.sr
    assert re.data.shape == buf.data.shape
    assert re.subtype == buf.subtype


def test_peak():
    buf = load(DATA)
    out = normalize(buf, peak_db=-1.0)
    target = 10.0 ** (-1.0 / 20.0)
    assert float(np.max(np.abs(out.data))) == pytest.approx(target, abs=1e-3)


def test_peak_zero_dbfs():
    buf = load(DATA)
    out = normalize(buf, peak_db=0.0)
    assert float(np.max(np.abs(out.data))) == pytest.approx(1.0, abs=1e-3)


def test_peak_silence_passes_through():
    sr = 44100
    src = AudioBuffer(data=np.zeros((1, sr), dtype=np.float32), sr=sr, subtype="PCM_16")
    out = normalize(src, peak_db=-3.0)
    assert float(np.max(np.abs(out.data))) == 0.0


def test_lufs():
    import pyloudnorm as pyln

    buf = load(DATA)
    out = normalize(buf, lufs=-14.0)
    samples_first = np.ascontiguousarray(out.data.T)
    meter_input = samples_first[:, 0] if samples_first.shape[1] == 1 else samples_first
    measured = float(pyln.Meter(int(out.sr)).integrated_loudness(meter_input))
    assert measured == pytest.approx(-14.0, abs=0.5)


def test_either_or_both_raises():
    buf = load(DATA)
    with pytest.raises(OpError):
        normalize(buf, peak_db=-1.0, lufs=-14.0)


def test_either_or_neither_raises():
    buf = load(DATA)
    with pytest.raises(OpError):
        normalize(buf)


def test_cli_normalize_peak(tmp_path):
    sr = 44100
    src = AudioBuffer(
        data=(np.sin(np.linspace(0, 4 * np.pi, sr)) * 0.25).astype(np.float32)[None, :],
        sr=sr,
        subtype="PCM_24",
    )
    src_path = tmp_path / "src.wav"
    save(src_path, src)

    out = tmp_path / "norm.wav"
    runner = CliRunner()
    result = runner.invoke(
        app,
        ["normalize", "--target", str(src_path), "--output", str(out), "--peak-db", "-1"],
    )
    assert result.exit_code == 0, result.output
    target = 10.0 ** (-1.0 / 20.0)
    out_peak = float(np.max(np.abs(load(out).data)))
    assert out_peak == pytest.approx(target, abs=1e-3)


def test_cli_normalize_missing_args_fails(tmp_path):
    runner = CliRunner()
    result = runner.invoke(
        app, ["normalize", "--target", str(DATA), "--output", str(tmp_path / "x.wav")]
    )
    assert result.exit_code != 0
