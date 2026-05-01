"""Tests for ``run-script`` — line-by-line ``.acli`` execution."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from typer.testing import CliRunner

from audiocli.buffer import AudioBuffer
from audiocli.cli import app
from audiocli.io import save
from audiocli.run_script import parse_script


def _make_src(tmp_path: Path, name: str = "src.wav") -> Path:
    sr = 44100
    src = AudioBuffer(
        data=(np.sin(np.linspace(0, 4 * np.pi, sr)) * 0.25).astype(np.float32)[None, :],
        sr=sr,
        subtype="PCM_24",
    )
    src_path = tmp_path / name
    save(src_path, src)
    return src_path


def test_parse_script_skips_blanks_and_comments(tmp_path):
    p = tmp_path / "job.acli"
    p.write_text(
        "\n"
        "# this is a comment\n"
        "gain --target a.wav --db 6\n"
        "\n"
        "    # indented comment\n"
        "polarity --target a.wav\n",
    )
    pairs = parse_script(p)
    assert pairs == [
        (3, "gain --target a.wav --db 6"),
        (6, "polarity --target a.wav"),
    ]


def test_basic(tmp_path):
    """A 3-line ``.acli`` runs every command and produces every output."""
    src_path = _make_src(tmp_path)
    out_a = tmp_path / "a.wav"
    out_b = tmp_path / "b.wav"
    out_c = tmp_path / "c.wav"

    script = tmp_path / "job.acli"
    script.write_text(
        f"gain --target {src_path} --output {out_a} --db 6\n"
        f"gain --target {src_path} --output {out_b} --db 3\n"
        f"gain --target {src_path} --output {out_c} --db 0\n",
    )

    runner = CliRunner()
    result = runner.invoke(app, ["run-script", str(script)])
    assert result.exit_code == 0, result.output
    assert out_a.exists()
    assert out_b.exists()
    assert out_c.exists()


def test_failure_isolation(tmp_path):
    """A failing line does not stop subsequent lines in default (non-strict) mode."""
    src_path = _make_src(tmp_path)
    out_a = tmp_path / "a.wav"
    out_c = tmp_path / "c.wav"

    script = tmp_path / "job.acli"
    script.write_text(
        f"gain --target {src_path} --output {out_a} --db 6\n"
        f"gain --target {tmp_path / 'no_such.wav'} --db 3\n"
        f"gain --target {src_path} --output {out_c} --db 0\n",
    )

    runner = CliRunner()
    result = runner.invoke(app, ["run-script", str(script)])
    # default mode runs every line; final exit reflects the failure count.
    assert result.exit_code != 0
    assert out_a.exists(), result.output
    assert out_c.exists(), result.output


def test_strict_aborts_on_first_failure(tmp_path):
    """``--strict`` aborts on the first failing line and skips the rest."""
    src_path = _make_src(tmp_path)
    out_a = tmp_path / "a.wav"
    out_c = tmp_path / "c.wav"

    script = tmp_path / "job.acli"
    script.write_text(
        f"gain --target {src_path} --output {out_a} --db 6\n"
        f"gain --target {tmp_path / 'no_such.wav'} --db 3\n"
        f"gain --target {src_path} --output {out_c} --db 0\n",
    )

    runner = CliRunner()
    result = runner.invoke(app, ["run-script", str(script), "--strict"])
    assert result.exit_code != 0
    assert out_a.exists()
    # third line must NOT have been executed in strict mode.
    assert not out_c.exists(), result.output


def test_comments_and_blanks(tmp_path):
    """Comment and blank lines are silently skipped."""
    src_path = _make_src(tmp_path)
    out_a = tmp_path / "a.wav"

    script = tmp_path / "job.acli"
    script.write_text(
        "# header comment\n"
        "\n"
        f"gain --target {src_path} --output {out_a} --db 6\n"
        "\n"
        "# trailing comment\n",
    )

    runner = CliRunner()
    result = runner.invoke(app, ["run-script", str(script)])
    assert result.exit_code == 0, result.output
    assert out_a.exists()


def test_missing_script_file(tmp_path):
    runner = CliRunner()
    # Use a path Typer's `exists=True` will reject so we get a clean error
    # rather than a traceback.
    result = runner.invoke(app, ["run-script", str(tmp_path / "nope.acli")])
    assert result.exit_code != 0
