"""Tests for the `bitdepth` op."""

from __future__ import annotations

import numpy as np
import pytest
from typer.testing import CliRunner

from audiocli.buffer import AudioBuffer
from audiocli.cli import app
from audiocli.errors import OpError
from audiocli.io import load, save
from audiocli.ops.bitdepth import bitdepth


def test_bitdepth_sets_subtype():
    buf = AudioBuffer(data=np.zeros((1, 100), dtype=np.float32), sr=44100, subtype="PCM_24")
    out = bitdepth(buf, bits=16)
    assert out.subtype == "PCM_16"
    # Filter-shape: untouched data.
    assert out.data is buf.data


@pytest.mark.parametrize(
    ("bits", "subtype"),
    [(8, "PCM_8"), (16, "PCM_16"), (24, "PCM_24"), (32, "FLOAT")],
)
def test_bitdepth_all_supported(bits, subtype):
    buf = AudioBuffer(data=np.zeros((1, 100), dtype=np.float32), sr=44100)
    out = bitdepth(buf, bits=bits)
    assert out.subtype == subtype


def test_bitdepth_rejects_invalid():
    buf = AudioBuffer(data=np.zeros((1, 100), dtype=np.float32), sr=44100)
    with pytest.raises(OpError):
        bitdepth(buf, bits=12)


def test_cli_bitdepth_24_to_16(tmp_path):
    """Save a 24-bit WAV, run `bitdepth 16`, reload, assert PCM_16."""
    sr = 44100
    buf = AudioBuffer(
        data=(np.sin(np.linspace(0, 4 * np.pi, sr)) * 0.3).astype(np.float32)[None, :],
        sr=sr,
        subtype="PCM_24",
    )
    src = tmp_path / "src.wav"
    save(src, buf)
    assert load(src).subtype == "PCM_24"

    out = tmp_path / "out.wav"
    runner = CliRunner()
    result = runner.invoke(
        app,
        ["bitdepth", "--target", str(src), "--output", str(out), "--bits", "16"],
    )
    assert result.exit_code == 0, result.output
    re = load(out)
    assert re.subtype == "PCM_16"
    assert re.sr == sr


def test_cli_bitdepth_16_to_24(tmp_path):
    sr = 44100
    buf = AudioBuffer(
        data=(np.sin(np.linspace(0, 4 * np.pi, sr)) * 0.3).astype(np.float32)[None, :],
        sr=sr,
        subtype="PCM_16",
    )
    src = tmp_path / "src.wav"
    save(src, buf)
    assert load(src).subtype == "PCM_16"

    out = tmp_path / "out.wav"
    runner = CliRunner()
    result = runner.invoke(
        app,
        ["bitdepth", "--target", str(src), "--output", str(out), "--bits", "24"],
    )
    assert result.exit_code == 0, result.output
    assert load(out).subtype == "PCM_24"
