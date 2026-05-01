"""Tests for the `pitch` op — round-trip, correctness, negative."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from typer.testing import CliRunner

from audiocli.buffer import AudioBuffer
from audiocli.cli import app
from audiocli.io import load, save
from audiocli.ops.pitch import pitch

DATA = Path(__file__).parent / "data" / "test_song.wav"


def _sine(freq_hz: float, sr: int, duration_s: float = 1.0) -> AudioBuffer:
    n = int(sr * duration_s)
    t = np.arange(n, dtype=np.float32) / sr
    wave = (np.sin(2 * np.pi * freq_hz * t) * 0.5).astype(np.float32)
    return AudioBuffer(data=wave[None, :], sr=sr, subtype="FLOAT")


def _fft_peak_hz(buf: AudioBuffer) -> float:
    sig = buf.data[0]
    # Skip transient at start/end.
    pad = buf.sr // 10
    seg = sig[pad : len(sig) - pad]
    spectrum = np.fft.rfft(seg * np.hanning(len(seg)))
    mag = np.abs(spectrum)
    freqs = np.fft.rfftfreq(len(seg), d=1.0 / buf.sr)
    return float(freqs[int(np.argmax(mag))])


def test_pitch_round_trip(tmp_path):
    buf = load(DATA)
    out = pitch(buf, semitones=0.0)
    p = tmp_path / "out.wav"
    save(p, out)
    re = load(p)
    assert re.sr == buf.sr
    assert re.data.shape == buf.data.shape


def test_pitch_octave_up_doubles_frequency():
    sr = 44100
    src = _sine(440.0, sr=sr, duration_s=1.0)
    shifted = pitch(src, semitones=12.0)
    peak = _fft_peak_hz(shifted)
    # Allow ±5% tolerance — PitchShift introduces some smearing.
    assert peak == 880.0 or abs(peak - 880.0) / 880.0 < 0.05, f"got peak {peak} Hz"


def test_pitch_negative_semitones_down():
    sr = 44100
    src = _sine(880.0, sr=sr, duration_s=1.0)
    shifted = pitch(src, semitones=-12.0)
    peak = _fft_peak_hz(shifted)
    assert abs(peak - 440.0) / 440.0 < 0.05, f"got peak {peak} Hz"


def test_cli_pitch_runs_end_to_end(tmp_path):
    sr = 44100
    src = _sine(440.0, sr=sr, duration_s=0.5)
    src_path = tmp_path / "src.wav"
    save(src_path, src)
    out = tmp_path / "out.wav"

    runner = CliRunner()
    result = runner.invoke(
        app,
        ["pitch", "--target", str(src_path), "--output", str(out), "--semitones", "12"],
    )
    assert result.exit_code == 0, result.output
    assert out.exists()


def test_cli_pitch_missing_target_fails():
    runner = CliRunner()
    result = runner.invoke(app, ["pitch", "--target", "no/such/file.wav", "--semitones", "12"])
    assert result.exit_code != 0
