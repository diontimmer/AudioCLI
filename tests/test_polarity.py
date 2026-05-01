"""Tests for the `polarity` op — round-trip, correctness, negative."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from typer.testing import CliRunner

from audiocli.buffer import AudioBuffer
from audiocli.cli import app
from audiocli.io import load, save
from audiocli.ops.polarity import polarity

DATA = Path(__file__).parent / "data" / "test_song.wav"


def test_polarity_round_trip(tmp_path):
    buf = load(DATA)
    out = polarity(buf)
    p = tmp_path / "out.wav"
    save(p, out)
    re = load(p)
    assert re.sr == buf.sr
    assert re.data.shape == buf.data.shape
    assert re.subtype == buf.subtype


def test_polarity_negates_samples():
    buf = load(DATA)
    out = polarity(buf)
    np.testing.assert_array_equal(out.data, -buf.data)


def test_polarity_double_flip_is_identity():
    buf = load(DATA)
    out = polarity(polarity(buf))
    np.testing.assert_array_equal(out.data, buf.data)


def test_polarity_synth():
    sr = 44100
    src = AudioBuffer(
        data=np.array([[0.5, -0.25, 0.0, 1.0]], dtype=np.float32),
        sr=sr,
        subtype="FLOAT",
    )
    out = polarity(src)
    np.testing.assert_array_equal(out.data, np.array([[-0.5, 0.25, 0.0, -1.0]], dtype=np.float32))


def test_cli_polarity_runs_end_to_end(tmp_path):
    sr = 44100
    src = AudioBuffer(
        data=(np.sin(np.linspace(0, 4 * np.pi, sr)) * 0.25).astype(np.float32)[None, :],
        sr=sr,
        subtype="PCM_24",
    )
    src_path = tmp_path / "src.wav"
    save(src_path, src)

    out = tmp_path / "flipped.wav"
    runner = CliRunner()
    result = runner.invoke(app, ["polarity", "--target", str(src_path), "--output", str(out)])
    assert result.exit_code == 0, result.output
    out_data = load(out).data
    src_data = load(src_path).data
    np.testing.assert_allclose(out_data, -src_data, atol=1e-4)


def test_cli_polarity_missing_target_fails():
    runner = CliRunner()
    result = runner.invoke(app, ["polarity", "--target", "no/such/file.wav"])
    assert result.exit_code != 0


def test_polarity_no_extra_options_takes_no_kwargs():
    # Negative correctness: polarity has no parameters beyond the buffer.
    buf = load(DATA)
    with pytest.raises(TypeError):
        polarity(buf, foo=1)  # type: ignore[call-arg]
