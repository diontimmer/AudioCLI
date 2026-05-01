"""Tests for the `fade` op — round-trip, correctness, shapes, negative."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from typer.testing import CliRunner

from audiocli.buffer import AudioBuffer
from audiocli.cli import app
from audiocli.errors import AudioCLIError
from audiocli.io import load, save
from audiocli.ops.fade import fade

DATA = Path(__file__).parent / "data" / "test_song.wav"


def _const(sr: int, duration_s: float = 1.0, level: float = 0.5) -> AudioBuffer:
    n = int(sr * duration_s)
    data = np.full((1, n), level, dtype=np.float32)
    return AudioBuffer(data=data, sr=sr, subtype="FLOAT")


def test_fade_round_trip(tmp_path):
    buf = load(DATA)
    out = fade(buf)  # no fades — passthrough
    p = tmp_path / "out.wav"
    save(p, out)
    re = load(p)
    assert re.data.shape == buf.data.shape


def test_fade_linear_first_sample_zero_and_full_at_duration():
    sr = 44100
    src = _const(sr, duration_s=0.5, level=0.5)
    out = fade(src, fade_in_s=0.1, fade_out_s=0.0, shape="linear")
    assert out.data[0, 0] == pytest.approx(0.0, abs=1e-6)
    fade_n = int(0.1 * sr)
    # The sample at the end of the fade-in should be at the input level.
    assert out.data[0, fade_n - 1] == pytest.approx(0.5, abs=1e-3)


def test_fade_shapes_monotonic_increase():
    sr = 44100
    src = _const(sr, duration_s=0.5, level=1.0)
    fade_n = int(0.1 * sr)
    for shape in ("linear", "exp", "cosine"):
        out = fade(src, fade_in_s=0.1, shape=shape)
        env = out.data[0, :fade_n]
        diffs = np.diff(env)
        # Allow tiny floating-point dips, but envelope must be non-decreasing.
        assert float(np.min(diffs)) >= -1e-7, f"{shape} not monotonic"
        assert env[0] == pytest.approx(0.0, abs=1e-6)
        assert env[-1] == pytest.approx(1.0, abs=1e-3)


def test_fade_out_ends_at_zero():
    sr = 44100
    src = _const(sr, duration_s=0.5, level=0.5)
    out = fade(src, fade_out_s=0.1, shape="linear")
    assert out.data[0, -1] == pytest.approx(0.0, abs=1e-6)


def test_fade_negative_duration_raises():
    src = _const(44100, duration_s=0.1)
    with pytest.raises(AudioCLIError):
        fade(src, fade_in_s=-0.1)


def test_fade_unknown_shape_raises():
    src = _const(44100, duration_s=0.1)
    with pytest.raises(AudioCLIError):
        fade(src, fade_in_s=0.05, shape="bogus")  # type: ignore[arg-type]


def test_cli_fade_runs_end_to_end(tmp_path):
    sr = 44100
    src = _const(sr, duration_s=0.5, level=0.5)
    src_path = tmp_path / "src.wav"
    save(src_path, src)
    out = tmp_path / "out.wav"

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "fade",
            "--target",
            str(src_path),
            "--output",
            str(out),
            "--in",
            "0.1",
            "--shape",
            "linear",
        ],
    )
    assert result.exit_code == 0, result.output
    assert out.exists()
