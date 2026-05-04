"""Tests for the ``remove-silent`` special-case command."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from typer.testing import CliRunner

from audiocli.buffer import AudioBuffer
from audiocli.cli import app
from audiocli.io import save
from audiocli.silence import is_silent


def _write_silent(path: Path, *, sr: int = 22050, peak: float = 1e-6) -> None:
    n = sr  # one second
    data = (np.full(n, peak, dtype=np.float32))[None, :]
    save(path, AudioBuffer(data=data, sr=sr, subtype="PCM_16"))


def _write_loud(path: Path, *, sr: int = 22050, peak: float = 0.3) -> None:
    n = sr
    t = np.linspace(0, 1, n, dtype=np.float32)
    data = (np.sin(2 * np.pi * 440 * t) * peak).astype(np.float32)[None, :]
    save(path, AudioBuffer(data=data, sr=sr, subtype="PCM_16"))


def test_is_silent_threshold():
    sr = 22050
    silent = AudioBuffer(data=np.zeros((1, sr), dtype=np.float32), sr=sr, subtype="PCM_16")
    loud = AudioBuffer(
        data=(np.full(sr, 0.3, dtype=np.float32))[None, :],
        sr=sr,
        subtype="PCM_16",
    )
    assert is_silent(silent, threshold_db=-60.0, metric="rms") is True
    assert is_silent(loud, threshold_db=-60.0, metric="rms") is False
    assert is_silent(loud, threshold_db=-60.0, metric="peak") is False


def test_cli_remove_silent_round_trip(tmp_path):
    silent_paths = [tmp_path / f"silent_{i}.wav" for i in range(3)]
    loud_paths = [tmp_path / f"loud_{i}.wav" for i in range(2)]
    for p in silent_paths:
        _write_silent(p)
    for p in loud_paths:
        _write_loud(p)

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "remove-silent",
            "--target",
            str(tmp_path),
            "--threshold-db",
            "-60",
            "--metric",
            "rms",
        ],
    )
    assert result.exit_code == 0, result.output

    # Silent files must be gone; loud files must remain.
    for p in silent_paths:
        assert not p.exists(), f"{p} should have been deleted"
    for p in loud_paths:
        assert p.exists(), f"{p} should NOT have been deleted"

    # Stderr summary mentions 3 removed, 2 kept.
    assert "3" in result.stderr
    assert "2 kept" in result.stderr


def test_cli_remove_silent_dry_run(tmp_path):
    silent_path = tmp_path / "silent.wav"
    _write_silent(silent_path)

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "remove-silent",
            "--target",
            str(tmp_path),
            "--threshold-db",
            "-60",
            "--dry-run",
        ],
    )
    assert result.exit_code == 0, result.output
    # The file must still exist when --dry-run is set.
    assert silent_path.exists()
    assert "would remove" in result.stdout


def test_cli_remove_silent_invalid_metric(tmp_path):
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "remove-silent",
            "--target",
            str(tmp_path),
            "--metric",
            "bogus",
        ],
    )
    assert result.exit_code != 0
