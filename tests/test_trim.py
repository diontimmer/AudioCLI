"""Tests for the `trim` op — round-trip, correctness, head/tail-only, negative."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from typer.testing import CliRunner

from audiocli.buffer import AudioBuffer
from audiocli.cli import app
from audiocli.io import load, save
from audiocli.ops.trim import trim

DATA = Path(__file__).parent / "data" / "test_song.wav"


def _padded_tone(
    sr: int,
    *,
    head_silence_s: float,
    tail_silence_s: float,
    tone_duration_s: float = 0.5,
    freq: float = 440.0,
    amp: float = 0.5,
) -> AudioBuffer:
    head_n = int(round(head_silence_s * sr))
    tail_n = int(round(tail_silence_s * sr))
    n = int(round(tone_duration_s * sr))
    t = np.arange(n, dtype=np.float32) / sr
    tone = (np.sin(2 * np.pi * freq * t) * amp).astype(np.float32)
    silence_head = np.zeros(head_n, dtype=np.float32)
    silence_tail = np.zeros(tail_n, dtype=np.float32)
    sig = np.concatenate([silence_head, tone, silence_tail])
    return AudioBuffer(data=sig[None, :], sr=sr, subtype="FLOAT")


def test_trim_round_trip(tmp_path):
    buf = load(DATA)
    out = trim(buf, head=False, tail=False)
    p = tmp_path / "out.wav"
    save(p, out)
    re = load(p)
    assert re.data.shape == buf.data.shape


def test_trim_strips_leading_silence_within_5ms():
    sr = 44100
    buf = _padded_tone(sr, head_silence_s=0.5, tail_silence_s=0.0)
    out = trim(buf, head=True, tail=False, threshold_db=-60.0)
    expected_n = int(0.5 * sr)
    removed = buf.data.shape[1] - out.data.shape[1]
    # Within 5 ms tolerance.
    assert abs(removed - expected_n) <= int(0.005 * sr)


def test_trim_head_only_keeps_tail():
    sr = 44100
    buf = _padded_tone(sr, head_silence_s=0.3, tail_silence_s=0.4)
    out = trim(buf, head=True, tail=False, threshold_db=-60.0)
    # Tail silence should be preserved (within window granularity).
    expected_min = int(0.4 * sr)
    # Tone (0.5s) + tail (0.4s) = 0.9s.
    assert out.data.shape[1] >= int(0.85 * sr)
    # And the tail end should still be silent.
    assert float(np.max(np.abs(out.data[:, -expected_min // 2 :]))) < 1e-3


def test_trim_tail_only_keeps_head():
    sr = 44100
    buf = _padded_tone(sr, head_silence_s=0.3, tail_silence_s=0.4)
    out = trim(buf, head=False, tail=True, threshold_db=-60.0)
    # Head silence should be preserved.
    head_n = int(0.3 * sr)
    assert float(np.max(np.abs(out.data[:, : head_n // 2]))) < 1e-3
    # Tail silence should be removed.
    removed = buf.data.shape[1] - out.data.shape[1]
    assert abs(removed - int(0.4 * sr)) <= int(0.02 * sr)


def test_trim_all_silence_returns_empty():
    sr = 44100
    silence = AudioBuffer(data=np.zeros((1, sr), dtype=np.float32), sr=sr, subtype="FLOAT")
    out = trim(silence, threshold_db=-60.0)
    assert out.data.shape[1] == 0


def test_cli_trim_runs_end_to_end(tmp_path):
    sr = 44100
    buf = _padded_tone(sr, head_silence_s=0.3, tail_silence_s=0.3)
    src_path = tmp_path / "src.wav"
    save(src_path, buf)
    out = tmp_path / "out.wav"

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "trim",
            "--target",
            str(src_path),
            "--output",
            str(out),
            "--threshold-db",
            "-60",
        ],
    )
    assert result.exit_code == 0, result.output
    assert out.exists()
    re = load(out)
    assert re.data.shape[1] < buf.data.shape[1]
