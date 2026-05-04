"""``--json`` mode emits one event per line on stdout.

Smoke-tested by parsing every line as JSON; the final line must be a
``done`` event so subscribers can detect end-of-stream without counting
inputs.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from typer.testing import CliRunner

from audiocli.buffer import AudioBuffer
from audiocli.cli import app
from audiocli.io import save


def _write_synth(path: Path, *, peak: float = 0.1) -> None:
    sr = 22050
    t = np.linspace(0, 1, sr, dtype=np.float32)
    data = (np.sin(2 * np.pi * 440 * t) * peak).astype(np.float32)[None, :]
    save(path, AudioBuffer(data=data, sr=sr, subtype="PCM_16"))


def _write_garbage(path: Path) -> None:
    path.write_bytes(b"NOTAWAV" + b"\x00" * 64)


def _run_json(args: list[str]) -> tuple[int, list[dict]]:
    """Run the CLI with ``--json`` and parse stdout into event dicts."""
    runner = CliRunner()
    result = runner.invoke(app, args)
    events: list[dict] = []
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        events.append(json.loads(line))  # raises if any line isn't JSON
    return result.exit_code, events


def test_json_mode_emits_newline_delimited_events(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    for i in range(3):
        _write_synth(src / f"in_{i}.wav")

    code, events = _run_json(
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
            "--json",
        ]
    )

    assert code == 0
    types = [e["type"] for e in events]
    assert types[0] == "start"
    assert types[-1] == "done"
    # One file_done per input.
    assert types.count("file_done") == 3
    # And a matching progress event per file_done.
    assert types.count("progress") == 3
    # No errors expected.
    assert "error" not in types


def test_json_start_event_shape(tmp_path):
    _write_synth(tmp_path / "a.wav")
    code, events = _run_json(
        [
            "gain",
            "--target",
            str(tmp_path / "a.wav"),
            "--output",
            str(tmp_path / "out"),
            "--db",
            "0",
            "--json",
        ]
    )
    assert code == 0
    start = events[0]
    assert start["type"] == "start"
    assert start["total"] == 1
    assert isinstance(start["workers"], int)


def test_json_progress_events_monotonic(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    for i in range(5):
        _write_synth(src / f"in_{i}.wav")

    code, events = _run_json(
        [
            "gain",
            "--target",
            str(src),
            "--output",
            str(tmp_path / "out"),
            "--db",
            "0",
            "--json",
        ]
    )
    assert code == 0
    progress = [e for e in events if e["type"] == "progress"]
    dones = [e["done"] for e in progress]
    totals = [e["total"] for e in progress]
    # Monotonic and never exceeds total.
    assert dones == sorted(dones)
    assert all(t == 5 for t in totals)
    assert max(dones) == 5
    assert progress[-1]["current"]  # last progress carries the final filename


def test_json_done_event_shape(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    _write_synth(src / "ok.wav")
    _write_garbage(src / "bad.wav")

    code, events = _run_json(
        [
            "gain",
            "--target",
            str(src),
            "--output",
            str(tmp_path / "out"),
            "--db",
            "0",
            "--json",
        ]
    )
    assert code != 0  # one bad file
    done = events[-1]
    assert done["type"] == "done"
    assert done["ok"] == 1
    assert done["failed"] == 1
    assert done["duration_s"] >= 0.0


def test_json_emits_error_event_per_failure(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    _write_garbage(src / "bad.wav")

    code, events = _run_json(
        [
            "gain",
            "--target",
            str(src),
            "--output",
            str(tmp_path / "out"),
            "--db",
            "0",
            "--json",
        ]
    )
    assert code != 0
    errors = [e for e in events if e["type"] == "error"]
    assert len(errors) == 1
    assert errors[0]["file"].endswith("bad.wav")
    assert errors[0]["reason"]


def test_json_no_human_readable_lines_on_stdout(tmp_path):
    """In JSON mode, every stdout line must be a JSON object — no
    human-readable mixed in."""
    _write_synth(tmp_path / "a.wav")
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "gain",
            "--target",
            str(tmp_path / "a.wav"),
            "--output",
            str(tmp_path / "out"),
            "--db",
            "0",
            "--json",
        ],
    )
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        json.loads(line)  # raises if any line isn't JSON


def test_json_fatal_error_is_newline_delimited(tmp_path):
    src = tmp_path / "empty"
    src.mkdir()
    (src / "notes.txt").write_text("not audio")

    code, events = _run_json(
        [
            "gain",
            "--target",
            str(src),
            "--db",
            "0",
            "--json",
        ]
    )

    assert code != 0
    assert events == [
        {
            "type": "error",
            "file": None,
            "reason": "no audio files matched the targets",
        },
        {"type": "done", "ok": 0, "failed": 0, "duration_s": 0.0},
    ]
