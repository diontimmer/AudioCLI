"""Issue 06 chain-level events and cancellation semantics."""

from __future__ import annotations

import json
import shutil
import threading
from pathlib import Path

from audiocli.chains import CapabilityChain
from audiocli.gui_service import ChainEvent, execute_file_chain
from audiocli.io import load

DATA = Path(__file__).parent / "data" / "test_song.wav"


def _copy_song(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(DATA, path)
    return path


def _write_garbage(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"NOTAWAV" + b"\x00" * 64)
    return path


def _two_step_chain() -> CapabilityChain:
    chain = CapabilityChain(id="chain-issue06", name="Issue 06 chain")
    chain.add_node("builtin.filter.highpass", {"hz": 120}, node_id="hp")
    chain.add_node("builtin.filter.gain", {"db": -3}, node_id="gain")
    return chain


def test_chain_events_order_identifiers_and_json_serialization(tmp_path):
    src = _copy_song(tmp_path / "song.wav")
    out_dir = tmp_path / "out"
    events: list[dict] = []

    run = execute_file_chain(
        _two_step_chain(),
        [src],
        output_policy={"output": out_dir},
        on_event=events.append,
    )

    assert run.ok_count == 1
    assert [event["type"] for event in events] == [
        "chain_start",
        "node_start",
        "node_done",
        "node_start",
        "node_done",
        "file_done",
        "file_progress",
        "chain_done",
    ]
    for event in events:
        json.dumps(event)
        assert event["chain_id"] == "chain-issue06"
        assert event["run_id"].startswith("run-")
        assert event["event"] == event["type"]

    first_node = events[1]
    assert first_node["node_id"] == "hp"
    assert first_node["node_index"] == 1
    assert first_node["node_count"] == 2
    assert first_node["capability_id"] == "builtin.filter.highpass"
    assert first_node["source_path"] == str(src)
    assert first_node["file_index"] == 1
    assert first_node["total_files"] == 1
    assert events[-2]["status"] == "ok"
    assert events[-1]["ok_count"] == 1
    assert events[-1]["failed_count"] == 0
    assert events[-1]["cancelled_count"] == 0


def test_chain_event_dataclass_serializes_false_and_omits_none():
    event = ChainEvent(
        "node_done",
        chain_id="chain",
        run_id="run",
        status="failed",
        ok=False,
        failed_count=0,
    ).to_json()

    assert event["type"] == "node_done"
    assert event["event"] == "node_done"
    assert event["ok"] is False
    assert event["failed_count"] == 0
    assert "error" not in event
    json.dumps(event)


def test_callback_errors_do_not_crash_executor(tmp_path):
    src = _copy_song(tmp_path / "song.wav")

    def broken_observer(_event: dict) -> None:
        raise RuntimeError("observer broke")

    run = execute_file_chain(
        _two_step_chain(),
        [src],
        output_policy={"output": tmp_path / "out"},
        on_event=broken_observer,
    )

    assert run.ok_count == 1
    assert run.failed_count == 0


def test_cancellation_before_start_marks_files_cancelled_not_failed(tmp_path):
    files = [_copy_song(tmp_path / f"in_{index}.wav") for index in range(2)]
    cancel = threading.Event()
    cancel.set()
    events: list[dict] = []

    run = execute_file_chain(
        _two_step_chain(),
        files,
        output_policy={"output": tmp_path / "out"},
        cancel_token=cancel,
        on_event=events.append,
    )

    assert run.ok_count == 0
    assert run.failed_count == 0
    assert run.cancelled_count == len(files)
    assert run.exit_code == len(files)
    assert all(result.status == "cancelled" for result in run.report.results)
    assert [event["type"] for event in events].count("node_start") == 0
    assert [event["status"] for event in events if event["type"] == "file_done"] == [
        "cancelled",
        "cancelled",
    ]
    assert [event["type"] for event in events].count("cancellation") == len(files)
    assert events[-1]["type"] == "chain_done"
    assert events[-1]["status"] == "cancelled"
    assert events[-1]["failed_count"] == 0
    assert events[-1]["cancelled_count"] == len(files)


def test_cancellation_mid_run_allows_current_node_to_finish_and_skips_pending(tmp_path):
    first = _copy_song(tmp_path / "first.wav")
    second = _copy_song(tmp_path / "second.wav")
    cancel = threading.Event()
    events: list[dict] = []

    def cancel_after_first_node_starts(event: dict) -> None:
        events.append(event)
        if event["type"] == "node_start" and event["source_path"] == str(first):
            cancel.set()

    run = execute_file_chain(
        _two_step_chain(),
        [first, second],
        output_policy={"output": tmp_path / "out"},
        cancel_token=cancel,
        on_event=cancel_after_first_node_starts,
    )

    assert run.ok_count == 0
    assert run.failed_count == 0
    assert run.cancelled_count == 2
    first_result, second_result = run.report.results
    assert first_result.status == "cancelled"
    assert first_result.cancelled_step_index == 2
    assert second_result.status == "cancelled"
    assert second_result.cancelled_step_index is None
    assert any(
        event["type"] == "node_done"
        and event["source_path"] == str(first)
        and event["node_index"] == 1
        and event["status"] == "ok"
        for event in events
    )
    assert not any(
        event["type"] == "node_start"
        and event.get("source_path") == str(first)
        and event.get("node_index") == 2
        for event in events
    )
    assert not any(
        event.get("source_path") == str(second) and event["type"] == "node_start"
        for event in events
    )
    assert [event["done"] for event in events if event["type"] == "file_progress"] == [1, 2]
    assert events[-1]["type"] == "chain_done"
    assert events[-1]["cancelled_count"] == 2


def test_failure_and_final_report_counts_are_consistent(tmp_path):
    good = _copy_song(tmp_path / "src" / "good.wav")
    bad = _write_garbage(tmp_path / "src" / "bad.wav")
    events: list[dict] = []

    run = execute_file_chain(
        _two_step_chain(),
        [good, bad],
        output_policy={"output": tmp_path / "out"},
        on_event=events.append,
    )

    assert run.ok_count == 1
    assert run.failed_count == 1
    assert run.cancelled_count == 0
    assert run.report.status == "failed"
    assert run.report.failures[0].source_path == bad
    view = run.to_view_model()["report"]
    assert view["ok_count"] == 1
    assert view["failed_count"] == 1
    assert view["cancelled_count"] == 0
    assert {result["status"] for result in view["results"]} == {"ok", "failed"}
    error_events = [event for event in events if event["type"] == "error"]
    assert len(error_events) == 1
    assert error_events[0]["source_path"] == str(bad)
    assert events[-1]["ok_count"] == run.ok_count
    assert events[-1]["failed_count"] == run.failed_count
    assert events[-1]["cancelled_count"] == run.cancelled_count
    assert load(tmp_path / "out" / "good.wav").sr == load(good).sr
