"""Issue 13 workspace real execution service and bridge tests."""

from __future__ import annotations

import os
import shutil
import threading
from pathlib import Path
from typing import Any

import pytest

from audiocli.capabilities import get_capability
from audiocli.gui.service import InMemoryWorkspaceService, WorkspaceExecutionService
from audiocli.io import load

DATA = Path(__file__).parent / "data" / "test_song.wav"


def _copy_song(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(DATA, path)
    return path


def test_workspace_execution_state_applies_fake_service_events() -> None:
    execution = WorkspaceExecutionService()

    execution.apply_event(
        {
            "type": "chain_start",
            "status": "running",
            "total": 2,
            "total_files": 2,
        }
    )
    execution.apply_event(
        {
            "type": "node_start",
            "status": "running",
            "operation_name": "gain",
            "node_id": "gain-node",
            "source_path": "input.wav",
        }
    )
    execution.apply_event(
        {
            "type": "file_done",
            "status": "ok",
            "source_path": "input.wav",
            "path": "out/input.wav",
            "output_path": "out/input.wav",
            "ok": True,
            "done": 1,
            "total": 2,
        }
    )
    execution.apply_event(
        {
            "type": "error",
            "status": "failed",
            "operation_name": "gain",
            "node_id": "gain-node",
            "source_path": "bad.wav",
            "error": "boom",
        }
    )
    execution.apply_event(
        {
            "type": "chain_done",
            "status": "failed",
            "done": 2,
            "total": 2,
            "ok_count": 1,
            "failed_count": 1,
            "cancelled_count": 0,
        }
    )

    job = execution.job
    assert job.running is False
    assert job.status == "failed"
    assert job.progress == 1.0
    assert job.done == 2
    assert job.total == 2
    assert job.current_node == "gain (gain-node)"
    assert job.current_file == "bad.wav"
    assert job.results == [
        {
            "source_path": "input.wav",
            "path": "out/input.wav",
            "output_path": "out/input.wav",
            "status": "ok",
            "ok": True,
            "error": None,
        }
    ]
    assert job.errors[-1]["error"] == "boom"
    assert job.summary["failed_count"] == 1
    assert [event["type"] for event in job.events] == [
        "chain_start",
        "node_start",
        "file_done",
        "error",
        "chain_done",
    ]


def test_workspace_execution_service_runs_real_gain_chain(tmp_path) -> None:
    src = _copy_song(tmp_path / "src" / "song.wav")
    out_dir = tmp_path / "out"
    service = InMemoryWorkspaceService()
    service.add_node("builtin.filter.gain")
    service.update_selected_param("db", 0)
    service.set_targets([src])
    service.set_output_path(out_dir)

    report = service.run_current_chain_sync()

    produced = out_dir / "song.wav"
    assert service.job.status == "ok"
    assert service.job.progress == 1.0
    assert service.job.summary["ok_count"] == 1
    assert service.job.summary["failed_count"] == 0
    assert report["report"]["ok_count"] == 1
    assert produced.exists()
    assert load(produced).sr == load(src).sr
    assert any(event["type"] == "node_start" for event in service.job.events)
    assert any(result["output_path"] == str(produced) for result in service.job.results)


def test_workspace_execution_cancel_token_marks_pending_files_cancelled(tmp_path) -> None:
    first = _copy_song(tmp_path / "first.wav")
    second = _copy_song(tmp_path / "second.wav")
    service = InMemoryWorkspaceService()
    service.add_node("builtin.filter.gain")
    service.update_selected_param("db", 0)
    service.set_targets([first, second])
    service.set_output_path(tmp_path / "out")
    request = service.make_execution_request()
    cancel = threading.Event()

    service.request_cancel_execution(cancel)
    report = service.execution.run_sync(request, cancel_token=cancel)

    assert cancel.is_set()
    assert service.job.cancel_requested is True
    assert service.job.status == "cancelled"
    assert report["report"]["cancelled_count"] == 2
    assert all(result["status"] == "cancelled" for result in service.job.results)
    assert not (tmp_path / "out" / "first.wav").exists()


def test_workspace_validation_errors_block_worker_start() -> None:
    service = InMemoryWorkspaceService([get_capability("builtin.filter.gain")])
    service.add_node("builtin.filter.gain")
    service.update_selected_param("db", 0)
    request = service.make_execution_request()

    errors = service.start_execution(request)

    assert errors[0]["code"] == "no_targets"
    assert service.job.running is False
    assert service.job.status == "validation_error"
    assert service.job.results == errors


def test_workspace_destructive_directory_confirmation_expands_to_files(tmp_path) -> None:
    src_dir = tmp_path / "src"
    src = _copy_song(src_dir / "song.wav")
    service = InMemoryWorkspaceService([get_capability("builtin.filter.gain")])
    service.add_node("builtin.filter.gain")
    service.update_selected_param("db", 0)
    service.set_targets([src_dir])
    service.set_output_mode("destructive")

    raw_request = service.make_execution_request(
        destructive_confirmation={"confirmed": True, "affected_paths": [str(src_dir)]}
    )
    raw_errors = service.start_execution(raw_request)
    assert raw_errors[0]["code"] == "destructive_preflight_failed"
    assert "confirmation does not cover" in raw_errors[0]["message"]
    assert service.job.running is False

    prepared = service.prepare_execution_request(raw_request)
    affected_paths = list(prepared.destructive_confirmation["affected_paths"])

    assert str(src) in affected_paths
    assert str(src_dir) not in affected_paths
    assert prepared.destructive_confirmation["affected_file_count"] == 1
    assert prepared.destructive_confirmation["affected_directory_count"] == 1
    assert service.start_execution(prepared) == []
    assert service.job.running is True

    runner = InMemoryWorkspaceService([get_capability("builtin.filter.gain")])
    runner.add_node("builtin.filter.gain")
    runner.update_selected_param("db", 0)
    runner.set_targets([src_dir])
    runner.set_output_mode("destructive")
    report = runner.run_current_chain_sync(
        destructive_confirmation={"confirmed": True, "affected_paths": [str(src_dir)]}
    )

    assert report["report"]["status"] == "ok"
    assert runner.job.errors == []


def test_workspace_destructive_mode_rejects_without_confirmation(tmp_path) -> None:
    src = _copy_song(tmp_path / "song.wav")
    service = InMemoryWorkspaceService([get_capability("builtin.filter.gain")])
    service.add_node("builtin.filter.gain")
    service.update_selected_param("db", 0)
    service.set_targets([src])
    service.set_output_mode("destructive")
    request = service.make_execution_request()

    errors = service.start_execution(request)

    assert errors[0]["code"] == "destructive_confirmation_required"
    assert service.job.running is False


def test_workspace_name_regex_filter_confirmation_uses_preview_candidates(tmp_path) -> None:
    junk = _copy_song(tmp_path / "junk_take.wav")
    keep = _copy_song(tmp_path / "keeper.wav")
    service = InMemoryWorkspaceService()
    service.add_node("builtin.file_filter.name_regex")
    service.update_selected_param("pattern", "junk")
    service.update_selected_param("action", "delete")
    service.set_targets([tmp_path])
    request = service.make_execution_request()

    impact = service.preview_destructive_impact(request)
    errors = service.start_execution(request)
    prepared = service.prepare_execution_request(
        service.make_execution_request(destructive_confirmation={"confirmed": True})
    )

    assert impact["destructive_filter"] == "name_regex"
    assert impact["affected_paths"] == [str(junk)]
    assert impact["affected_file_count"] == 1
    assert errors[0]["code"] == "destructive_confirmation_required"
    assert prepared.destructive_confirmation["affected_paths"] == [str(junk)]
    assert prepared.destructive_confirmation["affected_file_count"] == 1

    report = service.execution.run_sync(prepared)

    assert report["report"]["removed_count"] == 1
    assert report["report"]["kept_count"] == 1
    assert not junk.exists()
    assert keep.exists()


def test_qt_workspace_worker_emits_fake_events_when_pyside6_available() -> None:
    from audiocli.chains import CapabilityChain

    QtCore = pytest.importorskip("PySide6.QtCore")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    QtWidgets = pytest.importorskip("PySide6.QtWidgets")
    _app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    assert _app is not None
    from audiocli.gui.qt_bridge import WorkspaceChainWorker
    from audiocli.gui.service import WorkspaceExecutionRequest

    chain = CapabilityChain(name="Fake bridge")
    request = WorkspaceExecutionRequest(chain=chain, targets=("input.wav",))

    def fake_executor(_request, on_event, cancel_token) -> dict[str, Any]:  # noqa: ANN001
        on_event({"type": "chain_start", "status": "running", "total": 1})
        if not cancel_token.is_set():
            on_event(
                {
                    "type": "file_done",
                    "status": "ok",
                    "source_path": "input.wav",
                    "done": 1,
                    "total": 1,
                }
            )
        return {"report": {"status": "ok", "ok_count": 1, "results": []}}

    worker = WorkspaceChainWorker(request, executor=fake_executor)
    events: list[dict[str, Any]] = []
    finished: list[dict[str, Any]] = []
    states: list[dict[str, Any]] = []
    worker.event_received.connect(events.append, QtCore.Qt.ConnectionType.DirectConnection)
    worker.finished.connect(finished.append, QtCore.Qt.ConnectionType.DirectConnection)
    worker.state_changed.connect(states.append, QtCore.Qt.ConnectionType.DirectConnection)

    worker.run()

    assert [event["type"] for event in events] == ["chain_start", "file_done"]
    assert finished[0]["report"]["ok_count"] == 1
    assert states[0]["running"] is True
    assert states[-1]["running"] is False
