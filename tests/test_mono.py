"""Tests for the `mono` op — round-trip, correctness, negative."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from typer.testing import CliRunner

from audiocli.buffer import AudioBuffer
from audiocli.cli import app
from audiocli.io import load, save
from audiocli.ops.mono import mono

DATA = Path(__file__).parent / "data" / "test_song.wav"


def _stereo_buf(sr: int = 44100, n: int = 4410) -> AudioBuffer:
    left = np.sin(np.linspace(0, 4 * np.pi, n)).astype(np.float32) * 0.4
    right = np.sin(np.linspace(0, 6 * np.pi, n)).astype(np.float32) * 0.2
    return AudioBuffer(data=np.stack([left, right]), sr=sr, subtype="PCM_24")


def test_mono_round_trip(tmp_path):
    src = _stereo_buf()
    out = mono(src)
    p = tmp_path / "out.wav"
    save(p, out)
    re = load(p)
    assert re.sr == src.sr
    assert re.data.shape[0] == 1
    assert re.data.shape[1] == src.data.shape[1]


def test_stereo_input_to_one_channel():
    src = _stereo_buf()
    out = mono(src)
    assert out.data.shape[0] == 1
    assert out.sr == src.sr
    expected = np.mean(src.data, axis=0, keepdims=True)
    np.testing.assert_allclose(out.data, expected, atol=1e-6)


def test_mono_input_passes_through():
    sr = 44100
    src = AudioBuffer(
        data=np.array([[0.1, -0.2, 0.3]], dtype=np.float32),
        sr=sr,
        subtype="PCM_16",
    )
    out = mono(src)
    assert out.data.shape == (1, 3)
    assert out.sr == sr
    np.testing.assert_array_equal(out.data, src.data)


def test_multi_channel_input_averages():
    sr = 44100
    src = AudioBuffer(
        data=np.array(
            [
                [1.0, 1.0, 1.0],
                [0.0, 0.0, 0.0],
                [-1.0, -1.0, -1.0],
                [0.5, 0.5, 0.5],
            ],
            dtype=np.float32,
        ),
        sr=sr,
        subtype="FLOAT",
    )
    out = mono(src)
    assert out.data.shape == (1, 3)
    np.testing.assert_allclose(out.data, np.array([[0.125, 0.125, 0.125]], dtype=np.float32))


def test_cli_mono_runs_end_to_end(tmp_path):
    src = _stereo_buf()
    src_path = tmp_path / "src.wav"
    save(src_path, src)

    out = tmp_path / "mono.wav"
    runner = CliRunner()
    result = runner.invoke(app, ["mono", "--target", str(src_path), "--output", str(out)])
    assert result.exit_code == 0, result.output
    re = load(out)
    assert re.data.shape[0] == 1
    assert re.sr == src.sr


def test_cli_mono_missing_target_fails():
    runner = CliRunner()
    result = runner.invoke(app, ["mono", "--target", "no/such/file.wav"])
    assert result.exit_code != 0


def test_mono_takes_no_extra_kwargs():
    src = _stereo_buf()
    with pytest.raises(TypeError):
        mono(src, foo=1)  # type: ignore[call-arg]
