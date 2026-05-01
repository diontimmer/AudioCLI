"""Tests for the `convert` op."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from typer.testing import CliRunner

from audiocli.buffer import AudioBuffer
from audiocli.cli import app
from audiocli.errors import OpError
from audiocli.io import load, save
from audiocli.ops.convert import convert

DATA = Path(__file__).parent / "data" / "test_song.wav"


def test_convert_marks_buffer_format():
    buf = load(DATA)
    out = convert(buf, format="flac")
    assert out.format == "flac"
    # Filter-shape: data is untouched.
    assert out.data is buf.data
    assert out.sr == buf.sr


def test_convert_with_bitdepth_sets_subtype():
    buf = load(DATA)
    out = convert(buf, format="flac", bitdepth=16)
    assert out.subtype == "PCM_16"
    out2 = convert(buf, format="wav", bitdepth=24)
    assert out2.subtype == "PCM_24"


def test_convert_rejects_unknown_format():
    buf = AudioBuffer(data=np.zeros((1, 100), dtype=np.float32), sr=44100)
    with pytest.raises(OpError):
        convert(buf, format="aiff")


def test_convert_rejects_bad_bitdepth():
    buf = AudioBuffer(data=np.zeros((1, 100), dtype=np.float32), sr=44100)
    with pytest.raises(OpError):
        convert(buf, format="wav", bitdepth=12)


def test_cli_convert_wav_to_flac(tmp_path):
    sr = 44100
    buf = AudioBuffer(
        data=(np.sin(np.linspace(0, 4 * np.pi, sr)) * 0.3).astype(np.float32)[None, :],
        sr=sr,
        subtype="PCM_16",
    )
    src = tmp_path / "src.wav"
    save(src, buf)

    out_dir = tmp_path / "out"
    runner = CliRunner()
    result = runner.invoke(
        app,
        ["convert", "--target", str(src), "--output", str(out_dir), "--format", "flac"],
    )
    assert result.exit_code == 0, result.output

    produced = out_dir / "src.flac"
    assert produced.exists(), f"expected {produced}, got {list(out_dir.iterdir())}"
    re = load(produced)
    assert re.format == "flac"
    assert re.sr == sr
    assert re.data.shape[0] == 1


def test_cli_convert_to_mp3_with_quality(tmp_path):
    sr = 44100
    buf = AudioBuffer(
        data=(np.sin(np.linspace(0, 4 * np.pi, sr)) * 0.3).astype(np.float32)[None, :],
        sr=sr,
        subtype="PCM_16",
    )
    src = tmp_path / "src.wav"
    save(src, buf)

    out_dir = tmp_path / "out"
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "convert",
            "--target",
            str(src),
            "--output",
            str(out_dir),
            "--format",
            "mp3",
            "--quality",
            "192",
        ],
    )
    assert result.exit_code == 0, result.output
    produced = out_dir / "src.mp3"
    assert produced.exists()
    re = load(produced)
    assert re.format == "mp3"
    assert re.sr == sr


def test_cli_convert_default_output_rewrites_extension(tmp_path):
    """With no --output, the file is written next to the source with the new extension."""
    sr = 22050
    buf = AudioBuffer(
        data=(np.sin(np.linspace(0, 4 * np.pi, sr)) * 0.3).astype(np.float32)[None, :],
        sr=sr,
        subtype="PCM_16",
    )
    src = tmp_path / "song.wav"
    save(src, buf)

    runner = CliRunner()
    result = runner.invoke(app, ["convert", "--target", str(src), "--format", "flac"])
    assert result.exit_code == 0, result.output
    expected = tmp_path / "song_convert.flac"
    assert expected.exists()
    assert load(expected).format == "flac"
