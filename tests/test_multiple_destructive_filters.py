"""Combined destructive file-filter preview and execution tests."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from audiocli.buffer import AudioBuffer
from audiocli.chains import CapabilityChain
from audiocli.errors import AudioCLIError
from audiocli.gui.service import WorkspaceExecutionService
from audiocli.gui_service import DestructiveConfirmation, execute_file_chain
from audiocli.io import save


def _write_audio(path: Path, *, peak: float) -> Path:
    sample_rate = 22050
    if peak:
        time = np.arange(sample_rate, dtype=np.float32) / sample_rate
        data = (np.sin(2 * np.pi * 440 * time) * peak).astype(np.float32)[None, :]
    else:
        data = np.zeros((1, sample_rate), dtype=np.float32)
    save(path, AudioBuffer(data=data, sr=sample_rate, subtype="PCM_16"))
    return path


def _combined_cleanup_chain() -> CapabilityChain:
    chain = CapabilityChain(name="Combined cleanup")
    chain.add_node(
        "builtin.file_filter.name_regex",
        {
            "pattern": "_(?:Current|SC|Master)(?=$|[_. -])",
            "case_sensitive": False,
            "action": "delete",
        },
        node_id="delete-tagged",
    )
    chain.add_node(
        "builtin.file_filter.remove_silent",
        {
            "threshold_db": -60.0,
            "metric": "rms",
            "action": "delete",
        },
        node_id="delete-silent",
    )
    chain.add_node(
        "builtin.file_filter.name_regex",
        {
            "pattern": "_(?:MIDS|SUB x MIDS)(?=$|[_. -])",
            "case_sensitive": False,
            "action": "move",
            "destination_dir": "{source}/GROUPS",
        },
        node_id="move-groups",
    )
    return chain


def test_workspace_previews_and_executes_multiple_destructive_filters_once(
    tmp_path: Path,
) -> None:
    tagged = _write_audio(tmp_path / "kick_Current.wav", peak=0.3)
    silent = _write_audio(tmp_path / "empty.wav", peak=0.0)
    mids = _write_audio(tmp_path / "bass_MIDS.wav", peak=0.3)
    sub_mids = _write_audio(tmp_path / "bass_SUB x MIDS.wav", peak=0.3)
    keep = _write_audio(tmp_path / "lead.wav", peak=0.3)
    groups = tmp_path / "GROUPS"

    execution = WorkspaceExecutionService()
    chain = _combined_cleanup_chain()
    request = execution.make_request(chain, targets=[tmp_path], recursive=False)
    impact = execution.preview_destructive_impact(request)

    assert impact["destructive_filter"] == "multiple"
    assert impact["destructive_filters"] == [
        "name_regex",
        "remove_silent",
        "name_regex",
    ]
    assert impact["affected_paths"] == [
        str(tagged),
        str(silent),
        str(mids),
        str(sub_mids),
    ]
    assert [entry["node_id"] for entry in impact["preview"]["filters"]] == [
        "delete-tagged",
        "delete-silent",
        "move-groups",
    ]
    assert all(path.exists() for path in (tagged, silent, mids, sub_mids, keep))
    assert not groups.exists()

    confirmed = execution.make_request(
        chain,
        targets=[tmp_path],
        recursive=False,
        destructive_confirmation={"confirmed": True},
    )
    prepared = execution.prepare_request(confirmed)
    assert prepared.destructive_confirmation is not None
    assert prepared.destructive_confirmation["affected_paths"] == impact["affected_paths"]

    result = execution.run_sync(prepared)

    assert result["report"]["failed_count"] == 0
    assert result["report"]["removed_count"] == 2
    assert result["report"]["moved_count"] == 2
    assert result["report"]["kept_count"] == 1
    assert not tagged.exists()
    assert not silent.exists()
    assert not mids.exists()
    assert not sub_mids.exists()
    assert (groups / mids.name).exists()
    assert (groups / sub_mids.name).exists()
    assert keep.exists()


def test_combined_confirmation_must_match_union_before_mutation(tmp_path: Path) -> None:
    tagged = _write_audio(tmp_path / "kick_Current.wav", peak=0.3)
    silent = _write_audio(tmp_path / "empty.wav", peak=0.0)

    with pytest.raises(
        AudioCLIError,
        match="combined dry-run candidates.*missing candidates",
    ):
        execute_file_chain(
            _combined_cleanup_chain(),
            [tmp_path],
            recursive=False,
            destructive_confirmation=DestructiveConfirmation(
                confirmed=True,
                affected_paths=[tagged],
            ),
        )

    assert tagged.exists()
    assert silent.exists()
