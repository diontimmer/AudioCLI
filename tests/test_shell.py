"""Tests for the cross-platform REPL (`audiocli shell`).

The REPL is exercised via subprocess so that we cover the same code path a
real user hits — stdin tokenisation, history persistence, and the Typer
app's command dispatch all run together.

Tests are skipped if `click_repl` isn't importable (it ships in pyproject's
runtime deps; a developer running tests in a partially-installed venv
shouldn't be blocked by it).
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("click_repl")
pytest.importorskip("prompt_toolkit")

from audiocli.buffer import AudioBuffer  # noqa: E402
from audiocli.io import load, save  # noqa: E402
from audiocli.repl import _split_chain  # noqa: E402

DATA = Path(__file__).parent / "data" / "test_song.wav"


def _audiocli_cmd() -> list[str]:
    """Return the command vector that invokes the CLI as a subprocess.

    Prefers the installed ``audiocli`` script; falls back to
    ``python -m audiocli.cli`` so tests work in a checked-out tree
    without ``pip install -e .``.
    """
    exe = shutil.which("audiocli")
    if exe:
        return [exe]
    return [sys.executable, "-m", "audiocli.cli"]


def _run_shell(stdin: str, history: Path, cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [*_audiocli_cmd(), "shell", "--history", str(history)],
        input=stdin,
        capture_output=True,
        text=True,
        timeout=30,
        cwd=cwd,
    )


def _make_test_wav(path: Path, peak: float = 0.25) -> None:
    sr = 44100
    src = AudioBuffer(
        data=(np.sin(np.linspace(0, 4 * np.pi, sr)) * peak).astype(np.float32)[None, :],
        sr=sr,
        subtype="PCM_24",
    )
    save(path, src)


# ---------------------------------------------------------------------------
# unit-ish: chain splitter
# ---------------------------------------------------------------------------


def test_split_chain_basic():
    assert _split_chain("gain --db 6") == ["gain --db 6"]


def test_split_chain_multi():
    out = _split_chain("gain --db 6 ; gain --db -3")
    assert out == ["gain --db 6", "gain --db -3"]


def test_split_chain_quoted_semicolon_survives():
    # A `;` inside a quoted string must not split.
    out = _split_chain('gain --db 6 --target "a;b.wav"')
    assert out == ["gain --db 6 --target 'a;b.wav'"]


def test_split_chain_empty():
    assert _split_chain("") == []
    assert _split_chain("   ") == []


# ---------------------------------------------------------------------------
# subprocess REPL behaviour
# ---------------------------------------------------------------------------


def test_shell_runs_single_command(tmp_path):
    src = tmp_path / "src.wav"
    out = tmp_path / "out.wav"
    _make_test_wav(src)

    history = tmp_path / "history"
    cmd = f"gain --target {src} --output {out} --db 6\nexit\n"
    result = _run_shell(cmd, history)
    assert result.returncode == 0, result.stderr
    assert out.exists()
    re = load(out)
    assert re.sr == 44100


def test_shell_chain_runs_each_segment(tmp_path):
    src = tmp_path / "src.wav"
    a = tmp_path / "a.wav"
    b = tmp_path / "b.wav"
    _make_test_wav(src)

    history = tmp_path / "history"
    line = (
        f"gain --target {src} --output {a} --db 0 ; gain --target {src} --output {b} --db 0\nexit\n"
    )
    result = _run_shell(line, history)
    assert result.returncode == 0, result.stderr
    assert a.exists(), result.stdout + result.stderr
    assert b.exists(), result.stdout + result.stderr


def test_shell_history_written(tmp_path):
    src = tmp_path / "src.wav"
    out = tmp_path / "out.wav"
    _make_test_wav(src)

    history = tmp_path / "history"
    cmd = f"gain --target {src} --output {out} --db 0\nexit\n"
    result = _run_shell(cmd, history)
    assert result.returncode == 0, result.stderr
    assert history.exists()
    contents = history.read_text()
    # prompt_toolkit's FileHistory uses a `+` prefix for stored entries.
    assert "gain --target" in contents
    assert str(src) in contents


def test_shell_history_persists_across_sessions(tmp_path):
    src = tmp_path / "src.wav"
    _make_test_wav(src)
    history = tmp_path / "history"

    first = _run_shell(
        f"gain --target {src} --output {tmp_path / 'a.wav'} --db 0\nexit\n",
        history,
    )
    assert first.returncode == 0, first.stderr
    first_contents = history.read_text()
    assert "gain --target" in first_contents

    second = _run_shell(
        f"gain --target {src} --output {tmp_path / 'b.wav'} --db 0\nexit\n",
        history,
    )
    assert second.returncode == 0, second.stderr
    second_contents = history.read_text()
    # First session's entry is still there, and the file has grown.
    assert first_contents in second_contents
    assert len(second_contents) >= len(first_contents)


def test_shell_eof_quits_cleanly(tmp_path):
    """Closing stdin (EOF) should exit the REPL with status 0."""
    history = tmp_path / "history"
    # Empty stdin — REPL sees EOF immediately.
    result = _run_shell("", history)
    assert result.returncode == 0, result.stderr


def test_shell_exit_quits_cleanly(tmp_path):
    history = tmp_path / "history"
    result = _run_shell("exit\n", history)
    assert result.returncode == 0, result.stderr


def test_shell_quit_quits_cleanly(tmp_path):
    history = tmp_path / "history"
    result = _run_shell("quit\n", history)
    assert result.returncode == 0, result.stderr


def test_shell_bad_command_does_not_kill_repl(tmp_path):
    """A bad command should print an error but leave the REPL running."""
    src = tmp_path / "src.wav"
    out = tmp_path / "out.wav"
    _make_test_wav(src)
    history = tmp_path / "history"

    cmd = f"no-such-command-here\ngain --target {src} --output {out} --db 0\nexit\n"
    result = _run_shell(cmd, history)
    assert result.returncode == 0, result.stderr
    assert out.exists(), result.stdout + result.stderr
