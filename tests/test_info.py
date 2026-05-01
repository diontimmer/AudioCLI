"""Tests for the ``info`` special-case command."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
from typer.testing import CliRunner

from audiocli.buffer import AudioBuffer
from audiocli.cli import app
from audiocli.io import load, save
from audiocli.special import compute_info

DATA = Path(__file__).parent / "data" / "test_song.wav"


def test_compute_info_matches_numpy_groundtruth():
    buf = load(DATA)
    info = compute_info(buf, path=DATA)

    # Sample rate and channels are read straight from the file.
    assert info.sr == buf.sr
    assert info.channels == int(buf.data.shape[0])

    # Duration is samples / sr — independent compute.
    expected_duration = float(buf.data.shape[1]) / float(buf.sr)
    assert info.duration_s == pytest.approx(expected_duration, rel=1e-9, abs=1e-9)

    # Peak / RMS computed independently.
    expected_peak = float(np.max(np.abs(buf.data)))
    expected_rms = float(np.sqrt(np.mean(buf.data.astype(np.float64) ** 2)))
    expected_peak_db = 20.0 * np.log10(expected_peak) if expected_peak > 0 else -200.0
    expected_rms_db = 20.0 * np.log10(expected_rms) if expected_rms > 0 else -200.0
    assert info.peak_dbfs == pytest.approx(expected_peak_db, abs=1e-6)
    assert info.rms_dbfs == pytest.approx(expected_rms_db, abs=1e-6)

    # LUFS should be a finite float for a real song.
    assert info.lufs is not None
    assert -70.0 < info.lufs < 0.0


def test_compute_info_silent_lufs_is_none():
    sr = 44100
    silent = AudioBuffer(data=np.zeros((1, sr), dtype=np.float32), sr=sr, subtype="PCM_16")
    info = compute_info(silent, path=Path("silent.wav"))
    # Silent file -> LUFS unmeasurable, peak/rms hit the floor.
    assert info.lufs is None
    assert info.peak_dbfs == -200.0
    assert info.rms_dbfs == -200.0


def test_cli_info_human_table():
    runner = CliRunner()
    result = runner.invoke(app, ["info", "--target", str(DATA)])
    assert result.exit_code == 0, result.output
    assert str(DATA) in result.stdout
    assert "Hz" in result.stdout
    assert "peak" in result.stdout
    assert "rms" in result.stdout
    assert "LUFS" in result.stdout


def test_cli_info_json(tmp_path):
    runner = CliRunner()
    result = runner.invoke(app, ["info", "--target", str(DATA), "--json"])
    assert result.exit_code == 0, result.output
    line = result.stdout.strip().splitlines()[0]
    obj = json.loads(line)
    assert obj["path"] == str(DATA)
    assert obj["sr"] > 0
    assert obj["channels"] >= 1
    assert obj["duration_s"] > 0
    assert obj["peak_dbfs"] < 0
    assert obj["rms_dbfs"] < 0
    assert obj["lufs"] is None or isinstance(obj["lufs"], float)


def test_cli_info_directory(tmp_path):
    sr = 22050
    for i in range(2):
        data = (np.sin(np.linspace(0, 2 * np.pi * 440, sr)) * 0.2).astype(np.float32)[None, :]
        save(tmp_path / f"a{i}.wav", AudioBuffer(data=data, sr=sr, subtype="PCM_16"))
    runner = CliRunner()
    result = runner.invoke(app, ["info", "--target", str(tmp_path), "--json"])
    assert result.exit_code == 0, result.output
    lines = [line for line in result.stdout.strip().splitlines() if line]
    assert len(lines) == 2
    for line in lines:
        json.loads(line)  # Each line must be parseable JSON.
