"""Tests for the `gain` op — round-trip, correctness, negative."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from typer.testing import CliRunner

from audiocli.cli import app
from audiocli.errors import LoadError
from audiocli.io import load, save
from audiocli.ops.gain import gain

DATA = Path(__file__).parent / "data" / "test_song.wav"


def test_gain_round_trip(tmp_path):
    buf = load(DATA)
    out = gain(buf, db=0.0)
    p = tmp_path / "out.wav"
    save(p, out)
    re = load(p)
    assert re.sr == buf.sr
    assert re.data.shape == buf.data.shape
    assert re.subtype == buf.subtype


def test_gain_six_db_doubles_peak():
    buf = load(DATA)
    src_peak = float(np.max(np.abs(buf.data)))
    out = gain(buf, db=6.0)
    out_peak = float(np.max(np.abs(out.data)))
    # 6 dB is ~1.995× linear gain; allow a small tolerance.
    assert out_peak == pytest.approx(src_peak * 2.0, rel=0.02)


def test_gain_negative_db_halves_peak():
    buf = load(DATA)
    src_peak = float(np.max(np.abs(buf.data)))
    out = gain(buf, db=-6.0)
    out_peak = float(np.max(np.abs(out.data)))
    assert out_peak == pytest.approx(src_peak * 0.5, rel=0.02)


def test_load_corrupt_file_raises_load_error(tmp_path):
    bad = tmp_path / "bad.wav"
    bad.write_bytes(b"this is definitely not a wav file")
    with pytest.raises(LoadError):
        load(bad)


def test_cli_gain_runs_end_to_end(tmp_path):
    # Use a synthetic low-peak input so 6 dB headroom doesn't clip on PCM save.
    from audiocli.buffer import AudioBuffer

    sr = 44100
    src = AudioBuffer(
        data=(np.sin(np.linspace(0, 4 * np.pi, sr)) * 0.25).astype(np.float32)[None, :],
        sr=sr,
        subtype="PCM_24",
    )
    src_path = tmp_path / "src.wav"
    save(src_path, src)

    out = tmp_path / "gained.wav"
    runner = CliRunner()
    result = runner.invoke(
        app, ["gain", "--target", str(src_path), "--output", str(out), "--db", "6"]
    )
    assert result.exit_code == 0, result.output
    assert out.exists()
    src_peak = float(np.max(np.abs(load(src_path).data)))
    out_peak = float(np.max(np.abs(load(out).data)))
    assert out_peak == pytest.approx(src_peak * 2.0, rel=0.02)


def test_cli_gain_missing_target_fails():
    runner = CliRunner()
    result = runner.invoke(app, ["gain", "--target", "no/such/file.wav", "--db", "6"])
    assert result.exit_code != 0
