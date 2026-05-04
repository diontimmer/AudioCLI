"""Guarded destructive remove-silent capability-node tests."""

from __future__ import annotations

import tempfile
from pathlib import Path
from threading import Event

import numpy as np
import pytest

from audiocli.buffer import AudioBuffer
from audiocli.capabilities import list_capabilities, validate_capability_params
from audiocli.chains import CapabilityChain
from audiocli.errors import AudioCLIError
from audiocli.gui_service import (
    DestructiveConfirmation,
    execute_file_chain,
    preview_remove_silent,
)
from audiocli.io import save


def _write_silent(path: Path, *, sr: int = 22050, peak: float = 0.0) -> Path:
    data = np.full((1, sr), peak, dtype=np.float32)
    save(path, AudioBuffer(data=data, sr=sr, subtype="PCM_16"))
    return path


def _write_tone(path: Path, *, sr: int = 22050, peak: float = 0.3) -> Path:
    t = np.arange(sr, dtype=np.float32) / sr
    data = (np.sin(2 * np.pi * 440 * t) * peak).astype(np.float32)[None, :]
    save(path, AudioBuffer(data=data, sr=sr, subtype="PCM_16"))
    return path


def _remove_silent_chain(**params: object) -> CapabilityChain:
    chain = CapabilityChain(name="Remove silent")
    chain.add_node("builtin.destructive.remove_silent", params, node_id="rm-silent")
    return chain


def _gain_then_remove_silent_chain(**params: object) -> CapabilityChain:
    chain = CapabilityChain(name="Gain then remove silent")
    chain.add_node("builtin.filter.gain", {"db": -100.0}, node_id="gain")
    chain.add_node("builtin.destructive.remove_silent", params, node_id="rm-silent")
    return chain


def _dry_run_temp_dirs_for(source: Path) -> set[Path]:
    return set(Path(tempfile.gettempdir()).glob(f"audiocli-dry-run-{source.stem}-*"))


def test_remove_silent_capability_is_discoverable_destructive_filter():
    capabilities = {cap.id: cap for cap in list_capabilities()}
    cap = capabilities["builtin.destructive.remove_silent"]

    assert cap.type == "destructive_filter"
    assert cap.operation_name == "remove_silent"
    assert cap.safety.destructive is True
    assert cap.safety.requires_confirmation is True
    assert cap.metadata["dry_run_supported"] is True
    params = {param.name: param for param in cap.parameters}
    assert params["threshold_db"].default == -60.0
    assert params["metric"].choices == ["rms", "peak"]


def test_remove_silent_dry_run_summarizes_affected_files_without_deleting(tmp_path):
    silent = _write_silent(tmp_path / "silent.wav")
    loud = _write_tone(tmp_path / "tone.wav")

    preview = preview_remove_silent(_remove_silent_chain(), [tmp_path])

    assert preview.removed_candidates == [silent]
    assert preview.kept == [loud]
    assert preview.removed_count == 1
    assert preview.kept_count == 1
    assert preview.failed_count == 0
    assert silent.exists()
    assert loud.exists()
    view = preview.to_view_model()
    assert view["removed_candidates"] == [str(silent)]
    assert {result["status"] for result in view["results"]} == {"removed", "kept"}


def test_remove_silent_execution_refuses_without_confirmation(tmp_path):
    silent = _write_silent(tmp_path / "silent.wav")

    with pytest.raises(AudioCLIError, match="remove-silent.*confirmation"):
        execute_file_chain(_remove_silent_chain(), [tmp_path])

    assert silent.exists()


def test_remove_silent_confirmed_execution_deletes_only_silent_candidates(tmp_path):
    silent = _write_silent(tmp_path / "silent.wav")
    loud = _write_tone(tmp_path / "tone.wav")
    chain = _remove_silent_chain()
    preview = preview_remove_silent(chain, [tmp_path])

    run = execute_file_chain(
        chain,
        [tmp_path],
        destructive_confirmation=DestructiveConfirmation(
            confirmed=True,
            affected_paths=preview.affected_paths,
        ),
    )

    assert run.failed_count == 0
    assert run.removed_count == 1
    assert run.kept_count == 1
    assert run.ok_count == 2
    assert not silent.exists()
    assert loud.exists()
    statuses = {result.source_path.name: result.status for result in run.report.results}
    assert statuses == {"silent.wav": "removed", "tone.wav": "kept"}
    assert run.report.to_view_model()["removed_count"] == 1


def test_remove_silent_confirmation_paths_must_match_dry_run_candidates(tmp_path):
    silent = _write_silent(tmp_path / "silent.wav")
    loud = _write_tone(tmp_path / "tone.wav")

    with pytest.raises(AudioCLIError, match="affected_paths.*dry-run candidates"):
        execute_file_chain(
            _remove_silent_chain(),
            [tmp_path],
            destructive_confirmation=DestructiveConfirmation(confirmed=True, affected_paths=[]),
        )

    with pytest.raises(AudioCLIError, match="affected_paths.*dry-run candidates"):
        execute_file_chain(
            _remove_silent_chain(),
            [tmp_path],
            destructive_confirmation=DestructiveConfirmation(confirmed=True, affected_paths=[loud]),
        )

    assert silent.exists()
    assert loud.exists()


def test_remove_silent_after_gain_dry_run_uses_current_file_set_and_binds_confirmation(
    tmp_path,
):
    source = _write_tone(tmp_path / "tone.wav")
    post_gain_candidate = tmp_path / "tone_gain.wav"
    chain = _gain_then_remove_silent_chain()
    before_dry_run_dirs = _dry_run_temp_dirs_for(source)

    preview = preview_remove_silent(chain, [source])

    assert preview.removed_candidates == [post_gain_candidate]
    assert preview.kept == []
    assert source.exists()
    assert not post_gain_candidate.exists()
    assert _dry_run_temp_dirs_for(source) == before_dry_run_dirs

    with pytest.raises(AudioCLIError, match="affected_paths.*dry-run candidates"):
        execute_file_chain(
            chain,
            [source],
            destructive_confirmation=DestructiveConfirmation(confirmed=True, affected_paths=[]),
        )

    assert source.exists()
    assert not post_gain_candidate.exists()

    run = execute_file_chain(
        chain,
        [source],
        destructive_confirmation=DestructiveConfirmation(
            confirmed=True,
            affected_paths=preview.affected_paths,
        ),
    )

    assert run.failed_count == 0
    assert run.removed_count == 1
    assert source.exists()
    assert not post_gain_candidate.exists()


def test_remove_silent_invalid_metric_rejected_before_execution(tmp_path):
    silent = _write_silent(tmp_path / "silent.wav")

    validation = validate_capability_params(
        "builtin.destructive.remove_silent", {"metric": "bogus"}
    )
    assert validation.valid is False
    assert validation.errors[0].code == "invalid_choice"

    with pytest.raises(AudioCLIError, match="invalid_choice"):
        execute_file_chain(_remove_silent_chain(metric="bogus"), [tmp_path])

    assert silent.exists()


def test_remove_silent_cancellation_reports_cancelled_without_deleting(tmp_path):
    silent = _write_silent(tmp_path / "silent.wav")
    cancel = Event()
    cancel.set()

    run = execute_file_chain(
        _remove_silent_chain(),
        [tmp_path],
        destructive_confirmation=DestructiveConfirmation(confirmed=True, affected_paths=[silent]),
        cancel_token=cancel,
    )

    assert run.cancelled_count == 1
    assert run.removed_count == 0
    assert run.report.results[0].status == "cancelled"
    assert silent.exists()


def test_remove_silent_dry_run_cancellation_marks_pending_files_cancelled(tmp_path):
    silent = _write_silent(tmp_path / "silent.wav")
    cancel = Event()
    cancel.set()

    preview = preview_remove_silent(_remove_silent_chain(), [tmp_path], cancel_token=cancel)

    assert preview.cancelled_count == 1
    assert preview.removed_count == 0
    assert preview.results[0].status == "cancelled"
    assert silent.exists()
