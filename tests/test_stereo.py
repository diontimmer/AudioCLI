"""Tests for the `stereo` op — round-trip, correctness, negative."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from typer.testing import CliRunner

from audiocli.buffer import AudioBuffer
from audiocli.cli import app
from audiocli.errors import OpError
from audiocli.io import load, save
from audiocli.ops.stereo import stereo

DATA = Path(__file__).parent / "data" / "test_song.wav"


def _mono_buf(sr: int = 44100, n: int = 4410) -> AudioBuffer:
    sig = (np.sin(np.linspace(0, 4 * np.pi, n)) * 0.3).astype(np.float32)
    return AudioBuffer(data=sig[None, :], sr=sr, subtype="PCM_24")


def test_stereo_round_trip(tmp_path):
    src = _mono_buf()
    out = stereo(src)
    p = tmp_path / "out.wav"
    save(p, out)
    re = load(p)
    assert re.sr == src.sr
    assert re.data.shape[0] == 2


def test_mono_input_to_two_identical_channels():
    src = _mono_buf()
    out = stereo(src)
    assert out.data.shape[0] == 2
    assert out.sr == src.sr
    np.testing.assert_array_equal(out.data[0], out.data[1])
    np.testing.assert_array_equal(out.data[0], src.data[0])


def test_stereo_input_passes_through():
    sr = 44100
    src = AudioBuffer(
        data=np.array([[0.1, 0.2], [-0.3, -0.4]], dtype=np.float32),
        sr=sr,
        subtype="PCM_16",
    )
    out = stereo(src)
    assert out.data.shape == (2, 2)
    assert out.sr == sr
    np.testing.assert_array_equal(out.data, src.data)


def test_more_than_two_channels_raises():
    sr = 44100
    src = AudioBuffer(
        data=np.zeros((4, 100), dtype=np.float32),
        sr=sr,
        subtype="FLOAT",
    )
    with pytest.raises(OpError):
        stereo(src)


def test_cli_stereo_runs_end_to_end(tmp_path):
    src = _mono_buf()
    src_path = tmp_path / "src.wav"
    save(src_path, src)

    out = tmp_path / "stereo.wav"
    runner = CliRunner()
    result = runner.invoke(app, ["stereo", "--target", str(src_path), "--output", str(out)])
    assert result.exit_code == 0, result.output
    re = load(out)
    assert re.data.shape[0] == 2
    assert re.sr == src.sr


def test_cli_stereo_missing_target_fails():
    runner = CliRunner()
    result = runner.invoke(app, ["stereo", "--target", "no/such/file.wav"])
    assert result.exit_code != 0


def test_stereo_takes_no_extra_kwargs():
    src = _mono_buf()
    with pytest.raises(TypeError):
        stereo(src, foo=1)  # type: ignore[call-arg]
