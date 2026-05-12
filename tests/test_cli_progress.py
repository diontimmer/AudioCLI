"""Default (non-``--json``) mode renders a ``rich`` progress bar.

Smoke-tests the wiring rather than rich's internals: a CLI run with a
small batch should still succeed, print at least one progress-bar token
to stderr, and call the library-level ``on_event`` callback once per
file when invoked from a Python caller.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from typer.testing import CliRunner

from audiocli.buffer import AudioBuffer
from audiocli.cli import app
from audiocli.io import save
from audiocli.pipeline import run_per_file


def _write_synth(path: Path, *, peak: float = 0.1) -> None:
    sr = 22050
    t = np.linspace(0, 1, sr, dtype=np.float32)
    data = (np.sin(2 * np.pi * 440 * t) * peak).astype(np.float32)[None, :]
    save(path, AudioBuffer(data=data, sr=sr, subtype="PCM_16"))


def _gain_op():
    from audiocli.ops.gain import gain  # noqa: PLC0415

    return gain.__op__  # type: ignore[attr-defined]


def test_progress_callback_fires_for_each_file(tmp_path):
    """Library callers receive a structured event per file plus the
    surrounding ``start`` / ``done`` envelope — no rendering required."""
    files = []
    for i in range(4):
        p = tmp_path / f"in_{i}.wav"
        _write_synth(p)
        files.append(p)

    seen: list[dict] = []
    report = run_per_file(
        files,
        _gain_op(),
        {"db": 0.0},
        output=tmp_path / "out",
        workers=2,
        on_event=seen.append,
    )

    assert report.failed_count == 0
    types = [e["type"] for e in seen]
    assert types[0] == "start"
    assert types[-1] == "done"
    assert types.count("progress") == 4
    assert types.count("file_done") == 4

    # Progress is monotonic and bounded by total.
    progress = [e for e in seen if e["type"] == "progress"]
    dones = [e["done"] for e in progress]
    assert dones == sorted(dones)
    assert max(dones) == 4
    assert all(e["total"] == 4 for e in progress)


def test_progress_callback_callback_errors_do_not_kill_job(tmp_path):
    """A buggy subscriber must not sink the batch — the runner swallows
    callback exceptions on a best-effort basis."""
    p = tmp_path / "in.wav"
    _write_synth(p)

    def explode(_event: dict) -> None:
        raise RuntimeError("subscriber blew up")

    report = run_per_file(
        [p],
        _gain_op(),
        {"db": 0.0},
        output=tmp_path / "out",
        on_event=explode,
    )
    assert report.failed_count == 0
    assert report.ok_count == 1


def test_cli_default_mode_runs_without_json(tmp_path):
    """Smoke test: default mode (no ``--json``) still completes a run
    and emits the human-readable summary on stderr."""
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
        ],
    )
    assert result.exit_code == 0, (result.stdout, result.stderr)
    # Successes still go to stdout, one path per line.
    assert "a.wav" in result.stdout
    assert "b.wav" in result.stdout
    # Final summary on stderr.
    assert "done:" in result.stderr


def test_cli_json_flag_appears_in_help(monkeypatch):
    # CI runners don't allocate a TTY, so without COLUMNS set Rich auto-renders
    # the Typer help into a ~20-column panel and truncates every flag name to
    # `…`. Force a wide enough terminal that flag names render in full.
    monkeypatch.setenv("COLUMNS", "120")
    runner = CliRunner()
    result = runner.invoke(app, ["gain", "--help"])
    assert result.exit_code == 0
    assert "--json" in result.output
