"""Tests for the ``chunk`` special-case command."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from typer.testing import CliRunner

from audiocli.buffer import AudioBuffer
from audiocli.cli import app
from audiocli.errors import AudioCLIError
from audiocli.io import load, save
from audiocli.special import chunk_buffer


def _write_sine(path: Path, *, sr: int = 22050, duration_s: float = 3.5, peak: float = 0.2) -> None:
    n = int(round(sr * duration_s))
    t = np.linspace(0, duration_s, n, endpoint=False, dtype=np.float32)
    data = (np.sin(2 * np.pi * 220 * t) * peak).astype(np.float32)[None, :]
    save(path, AudioBuffer(data=data, sr=sr, subtype="PCM_16"))


def test_chunk_buffer_pad():
    sr = 22050
    n = int(round(sr * 3.5))
    data = np.linspace(-0.1, 0.1, n, dtype=np.float32)[None, :]
    buf = AudioBuffer(data=data, sr=sr, subtype="PCM_16")

    pieces = chunk_buffer(buf, seconds=1.0, pad=True)
    assert len(pieces) == 4
    for piece in pieces:
        assert piece.data.shape[1] == sr  # exact second
        assert piece.sr == sr


def test_chunk_buffer_no_pad():
    sr = 22050
    n = int(round(sr * 3.5))
    data = np.linspace(-0.1, 0.1, n, dtype=np.float32)[None, :]
    buf = AudioBuffer(data=data, sr=sr, subtype="PCM_16")

    pieces = chunk_buffer(buf, seconds=1.0, pad=False)
    assert len(pieces) == 4
    for piece in pieces[:-1]:
        assert piece.data.shape[1] == sr
    assert pieces[-1].data.shape[1] == n - 3 * sr


def test_chunk_buffer_invalid_seconds():
    sr = 22050
    buf = AudioBuffer(data=np.zeros((1, sr), dtype=np.float32), sr=sr, subtype="PCM_16")
    with pytest.raises(AudioCLIError):
        chunk_buffer(buf, seconds=0.0)
    with pytest.raises(AudioCLIError):
        chunk_buffer(buf, seconds=-1.0)


def test_cli_chunk_correctness_pad(tmp_path):
    src = tmp_path / "src.wav"
    sr = 22050
    _write_sine(src, sr=sr, duration_s=3.5)

    out_dir = tmp_path / "chunks"

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "chunk",
            "--target",
            str(src),
            "--seconds",
            "1.0",
            "--output",
            str(out_dir),
            "--pad",
        ],
    )
    assert result.exit_code == 0, result.output

    chunks = sorted(out_dir.glob("src_*.wav"))
    assert len(chunks) == 4
    for c in chunks:
        loaded = load(c)
        assert loaded.data.shape[1] == sr  # padded → exact second
        assert loaded.sr == sr


def test_cli_chunk_no_pad(tmp_path):
    src = tmp_path / "src.wav"
    sr = 22050
    _write_sine(src, sr=sr, duration_s=3.5)

    out_dir = tmp_path / "chunks"

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "chunk",
            "--target",
            str(src),
            "--seconds",
            "1.0",
            "--output",
            str(out_dir),
            "--no-pad",
        ],
    )
    assert result.exit_code == 0, result.output

    chunks = sorted(out_dir.glob("src_*.wav"))
    assert len(chunks) == 4
    full_chunks = [load(c) for c in chunks[:3]]
    last = load(chunks[-1])
    for c in full_chunks:
        assert c.data.shape[1] == sr
    assert last.data.shape[1] < sr
    assert last.data.shape[1] > 0


def test_cli_chunk_clean_deletes_source(tmp_path):
    src = tmp_path / "src.wav"
    _write_sine(src, duration_s=2.0)
    assert src.exists()

    out_dir = tmp_path / "chunks"
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "chunk",
            "--target",
            str(src),
            "--seconds",
            "1.0",
            "--output",
            str(out_dir),
            "--clean",
        ],
    )
    assert result.exit_code == 0, result.output
    assert not src.exists(), "source file should have been removed by --clean"
    assert len(list(out_dir.glob("src_*.wav"))) == 2


def test_cli_chunk_no_clean_keeps_source(tmp_path):
    src = tmp_path / "src.wav"
    _write_sine(src, duration_s=2.0)

    out_dir = tmp_path / "chunks"
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "chunk",
            "--target",
            str(src),
            "--seconds",
            "1.0",
            "--output",
            str(out_dir),
        ],
    )
    assert result.exit_code == 0, result.output
    assert src.exists(), "source must remain when --clean is not passed"


def test_cli_chunk_invalid_seconds(tmp_path):
    src = tmp_path / "src.wav"
    _write_sine(src, duration_s=1.0)

    runner = CliRunner()
    result = runner.invoke(
        app,
        ["chunk", "--target", str(src), "--seconds", "0"],
    )
    assert result.exit_code != 0
