"""Pipeline-level tests for `run_per_file`.

Real filesystem, real WAVs (and real garbage). Tests assert observable
outcomes (counts, exit codes, wall time, error reasons) rather than
inspecting internal state — see PRD § Testing Decisions.
"""

from __future__ import annotations

import time
from pathlib import Path

import numpy as np
import pytest
from typer.testing import CliRunner

from audiocli.buffer import AudioBuffer
from audiocli.cli import app
from audiocli.errors import AudioCLIError
from audiocli.io import save
from audiocli.pipeline import JobReport, Result, run_one, run_per_file
from audiocli.registry import op as op_decorator

DATA = Path(__file__).parent / "data" / "test_song.wav"


def _write_synth(path: Path, *, peak: float = 0.1) -> None:
    """Write a one-second mono sine so tests don't depend on the canonical
    fixture for bulk-file generation."""
    sr = 22050
    t = np.linspace(0, 1, sr, dtype=np.float32)
    data = (np.sin(2 * np.pi * 440 * t) * peak).astype(np.float32)[None, :]
    save(path, AudioBuffer(data=data, sr=sr, subtype="PCM_16"))


def _write_garbage(path: Path) -> None:
    """Wrong magic bytes — pedalboard rejects this on load."""
    path.write_bytes(b"NOTAWAV" + b"\x00" * 64)


# Register a sleepy op once at import time. The pipeline-level parallelism
# test uses it to prove worker concurrency without depending on real DSP
# wall time (which is noisy in CI).
@op_decorator(name="_sleepy_test_op", help="Test-only op: sleeps for `seconds`.")
def _sleepy(buf: AudioBuffer, seconds: float = 0.2) -> AudioBuffer:
    time.sleep(seconds)
    return buf


@op_decorator(name="_raise_test_op", help="Test-only op: always raises.")
def _raise(buf: AudioBuffer, msg: str = "boom") -> AudioBuffer:
    raise RuntimeError(msg)


def _gain_op():
    from audiocli.ops.gain import gain  # noqa: PLC0415

    return gain.__op__  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Acceptance criteria
# ---------------------------------------------------------------------------


def test_bulletproof_50_files_3_corrupt(tmp_path):
    """50 inputs, 3 deliberately bad → 47 ok, 3 failed, exit_code != 0."""
    n_total = 50
    bad_idx = {7, 23, 41}
    files: list[Path] = []
    for i in range(n_total):
        p = tmp_path / "src" / f"song_{i:03d}.wav"
        p.parent.mkdir(parents=True, exist_ok=True)
        if i in bad_idx:
            _write_garbage(p)
        else:
            _write_synth(p)
        files.append(p)

    out_dir = tmp_path / "out"
    start = time.perf_counter()
    report = run_per_file(files, _gain_op(), {"db": 0.0}, output=out_dir, workers=4)
    wall = time.perf_counter() - start

    assert isinstance(report, JobReport)
    assert report.ok_count == n_total - len(bad_idx)
    assert report.failed_count == len(bad_idx)
    assert report.exit_code == len(bad_idx)
    assert wall < 30.0
    # Every failure carries a non-empty reason.
    for r in report.failures:
        assert r.error
        assert r.path in {files[i] for i in bad_idx}


def test_parallelism_speedup(tmp_path):
    """Wall time on 8 files with 4 workers is < 0.6× the single-worker run."""
    files = []
    for i in range(8):
        p = tmp_path / f"in_{i}.wav"
        _write_synth(p)
        files.append(p)

    out_dir = tmp_path / "out"
    sleep_s = 0.25

    t0 = time.perf_counter()
    r1 = run_per_file(files, _sleepy.__op__, {"seconds": sleep_s}, output=out_dir / "w1", workers=1)
    t_serial = time.perf_counter() - t0

    t0 = time.perf_counter()
    r4 = run_per_file(files, _sleepy.__op__, {"seconds": sleep_s}, output=out_dir / "w4", workers=4)
    t_parallel = time.perf_counter() - t0

    assert r1.failed_count == 0
    assert r4.failed_count == 0
    assert t_parallel < 0.6 * t_serial, (
        f"expected parallel speedup: serial={t_serial:.2f}s parallel={t_parallel:.2f}s"
    )


def test_no_silent_drops_on_worker_exception(tmp_path):
    """A worker that raises an arbitrary exception is reflected as a failed
    Result and not lost in an unconsumed iterator."""
    files = []
    for i in range(5):
        p = tmp_path / f"in_{i}.wav"
        _write_synth(p)
        files.append(p)

    report = run_per_file(
        files, _raise.__op__, {"msg": "kaboom"}, output=tmp_path / "out", workers=2
    )
    assert report.ok_count == 0
    assert report.failed_count == 5
    for r in report.failures:
        assert "kaboom" in (r.error or "")


def test_run_per_file_empty_targets_raises():
    with pytest.raises(AudioCLIError):
        run_per_file([], _gain_op(), {"db": 0.0})


def test_run_one_returns_actual_written_path_after_format_rewrite(tmp_path):
    from audiocli.ops.convert import convert  # noqa: PLC0415

    src = tmp_path / "song.wav"
    _write_synth(src)

    result = run_one(src, convert.__op__, {"format": "flac"})

    assert result == tmp_path / "song_convert.flac"
    assert result.exists()


def test_result_dataclass_fields():
    r = Result(path=Path("/x"), ok=False, error="nope")
    assert r.path == Path("/x")
    assert r.ok is False
    assert r.error == "nope"


def test_jobreport_properties():
    rs = [
        Result(path=Path("a"), ok=True),
        Result(path=Path("b"), ok=False, error="bad"),
        Result(path=Path("c"), ok=False, error="also bad"),
    ]
    report = JobReport(results=rs, duration_s=1.5)
    assert report.ok_count == 1
    assert report.failed_count == 2
    assert {r.path for r in report.failures} == {Path("b"), Path("c")}
    assert report.exit_code == 2


def test_jobreport_exit_code_capped_at_255():
    rs = [Result(path=Path(str(i)), ok=False, error="x") for i in range(300)]
    assert JobReport(results=rs).exit_code == 255


# ---------------------------------------------------------------------------
# CLI integration
# ---------------------------------------------------------------------------


def test_cli_exits_non_zero_when_any_file_fails(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    _write_synth(src / "good_a.wav")
    _write_synth(src / "good_b.wav")
    _write_garbage(src / "bad.wav")

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "gain",
            "--target",
            str(src),
            "--output",
            str(tmp_path / "out"),
            "--db",
            "0",
            "--workers",
            "2",
        ],
    )
    assert result.exit_code != 0, result.output
    # Combined stdout/stderr — Typer's runner mixes streams by default.
    combined = result.output + (result.stderr if result.stderr_bytes else "")
    assert "FAIL" in combined or "failed" in combined


def test_cli_succeeds_on_clean_directory(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    _write_synth(src / "a.wav")
    _write_synth(src / "b.wav")

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "gain",
            "--target",
            str(src),
            "--output",
            str(tmp_path / "out"),
            "--db",
            "0",
            "--workers",
            "2",
        ],
    )
    assert result.exit_code == 0, result.output
    assert (tmp_path / "out" / "a.wav").exists()
    assert (tmp_path / "out" / "b.wav").exists()


def test_cli_multiple_target_paths(tmp_path):
    a = tmp_path / "a.wav"
    b = tmp_path / "b.wav"
    _write_synth(a)
    _write_synth(b)

    runner = CliRunner()
    out = tmp_path / "out"
    result = runner.invoke(
        app,
        [
            "gain",
            "--target",
            str(a),
            "--target",
            str(b),
            "--output",
            str(out),
            "--db",
            "0",
        ],
    )
    assert result.exit_code == 0, result.output
    assert (out / "a.wav").exists()
    assert (out / "b.wav").exists()
