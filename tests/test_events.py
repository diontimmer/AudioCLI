"""Tests for the structured event protocol.

The event dataclasses are the type-checked construction path; the dicts
they emit via ``to_json()`` are the public protocol. Both have to round
trip cleanly through ``json.dumps`` / ``json.loads`` because the
``--json`` CLI mode and the eventual desktop GUI both depend on it.
"""

from __future__ import annotations

import json

from audiocli.events import (
    DoneEvent,
    ErrorEvent,
    EventSink,
    FileDoneEvent,
    ProgressEvent,
    StartEvent,
)


def _roundtrip(payload: dict) -> dict:
    return json.loads(json.dumps(payload))


def test_start_event_serialization():
    e = StartEvent(total=10, workers=4)
    assert e.to_json() == {"type": "start", "total": 10, "workers": 4}
    assert _roundtrip(e.to_json()) == e.to_json()


def test_progress_event_serialization():
    e = ProgressEvent(done=3, total=10, current="/tmp/a.wav")
    assert e.to_json() == {
        "type": "progress",
        "done": 3,
        "total": 10,
        "current": "/tmp/a.wav",
    }
    assert _roundtrip(e.to_json()) == e.to_json()


def test_progress_event_current_optional():
    e = ProgressEvent(done=0, total=10)
    assert e.to_json()["current"] is None
    assert _roundtrip(e.to_json())["current"] is None


def test_file_done_event_serialization():
    ok = FileDoneEvent(path="/tmp/a.wav", ok=True, error=None)
    assert ok.to_json() == {
        "type": "file_done",
        "path": "/tmp/a.wav",
        "ok": True,
        "error": None,
    }
    bad = FileDoneEvent(path="/tmp/b.wav", ok=False, error="boom")
    assert bad.to_json()["ok"] is False
    assert bad.to_json()["error"] == "boom"
    assert _roundtrip(bad.to_json()) == bad.to_json()


def test_error_event_serialization():
    e = ErrorEvent(file="/tmp/x.wav", reason="LoadError: bad magic")
    assert e.to_json() == {
        "type": "error",
        "file": "/tmp/x.wav",
        "reason": "LoadError: bad magic",
    }
    assert _roundtrip(e.to_json()) == e.to_json()


def test_done_event_serialization():
    e = DoneEvent(ok=7, failed=3, duration_s=1.234)
    assert e.to_json() == {
        "type": "done",
        "ok": 7,
        "failed": 3,
        "duration_s": 1.234,
    }
    assert _roundtrip(e.to_json()) == e.to_json()


def test_all_event_types_have_type_field():
    for ev in (
        StartEvent(total=1, workers=1),
        ProgressEvent(done=0, total=1),
        FileDoneEvent(path="/x", ok=True),
        ErrorEvent(file="/x", reason="r"),
        DoneEvent(ok=1, failed=0, duration_s=0.0),
    ):
        assert "type" in ev.to_json()
        # Every dict must be JSON-serialisable.
        json.dumps(ev.to_json())


def test_event_sink_completed_file_emits_protocol_sequence():
    seen: list[dict] = []
    sink = EventSink(seen.append)

    sink.completed_file(
        path="/tmp/bad.wav",
        ok=False,
        error="bad magic",
        done=1,
        total=2,
    )

    assert [event["type"] for event in seen] == ["file_done", "error", "progress"]
    assert seen[0] == {
        "type": "file_done",
        "path": "/tmp/bad.wav",
        "ok": False,
        "error": "bad magic",
    }
    assert seen[1] == {
        "type": "error",
        "file": "/tmp/bad.wav",
        "reason": "bad magic",
    }
    assert seen[2] == {
        "type": "progress",
        "done": 1,
        "total": 2,
        "current": "/tmp/bad.wav",
    }


def test_event_sink_callback_errors_do_not_escape():
    def explode(_event: dict) -> None:
        raise RuntimeError("subscriber blew up")

    sink = EventSink(explode)
    sink.start(total=1, workers=1)
