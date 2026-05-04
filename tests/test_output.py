from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from audiocli.output import make_batch_output, render_fatal_error, render_job_report
from audiocli.pipeline import JobReport, Result


@dataclass
class RecordingEcho:
    stdout: list[str] = field(default_factory=list)
    stderr: list[str] = field(default_factory=list)

    def __call__(self, message: str, *, err: bool = False) -> None:
        if err:
            self.stderr.append(message)
        else:
            self.stdout.append(message)


def test_json_batch_output_writes_newline_delimited_events() -> None:
    echo = RecordingEcho()
    output = make_batch_output(True, echo=echo)

    output.on_event({"type": "start", "total": 1, "workers": 1})

    assert [json.loads(line) for line in echo.stdout] == [
        {"type": "start", "total": 1, "workers": 1}
    ]
    assert echo.stderr == []


def test_json_fatal_error_stays_parseable() -> None:
    echo = RecordingEcho()

    render_fatal_error(True, "no audio files matched the targets", echo=echo)

    assert [json.loads(line) for line in echo.stdout] == [
        {
            "type": "error",
            "file": None,
            "reason": "no audio files matched the targets",
        },
        {"type": "done", "ok": 0, "failed": 0, "duration_s": 0.0},
    ]
    assert echo.stderr == []


def test_default_fatal_error_is_human_readable() -> None:
    echo = RecordingEcho()

    render_fatal_error(False, "boom", echo=echo)

    assert echo.stdout == []
    assert echo.stderr == ["error: boom"]


def test_render_job_report_can_include_failures() -> None:
    echo = RecordingEcho()
    report = JobReport(
        results=[
            Result(path=Path("ok.wav"), ok=True),
            Result(path=Path("bad.wav"), ok=False, error="bad magic"),
        ],
        duration_s=1.234,
    )

    render_job_report(report, echo=echo, include_failures=True)

    assert echo.stdout == ["ok.wav"]
    assert echo.stderr == [
        "FAIL bad.wav: bad magic",
        "done: 1 ok, 1 failed in 1.23s",
    ]


def test_progress_report_leaves_failures_to_event_renderer() -> None:
    echo = RecordingEcho()
    output = make_batch_output(False, echo=echo)
    report = JobReport(
        results=[
            Result(path=Path("ok.wav"), ok=True),
            Result(path=Path("bad.wav"), ok=False, error="bad magic"),
        ],
        duration_s=1.0,
    )

    output.render_report(report)

    assert echo.stdout == ["ok.wav"]
    assert echo.stderr == ["done: 1 ok, 1 failed in 1.00s"]
