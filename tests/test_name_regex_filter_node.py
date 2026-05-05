"""Filename-regex file-filter capability tests."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from audiocli.buffer import AudioBuffer
from audiocli.capabilities import get_capability, list_capabilities, validate_capability_params
from audiocli.chains import CapabilityChain
from audiocli.errors import AudioCLIError
from audiocli.gui_service import (
    DestructiveConfirmation,
    execute_file_chain,
    preview_name_regex_filter,
)
from audiocli.io import save


def _write_tone(path: Path, *, sr: int = 22050, peak: float = 0.3) -> Path:
    t = np.arange(sr, dtype=np.float32) / sr
    data = (np.sin(2 * np.pi * 440 * t) * peak).astype(np.float32)[None, :]
    save(path, AudioBuffer(data=data, sr=sr, subtype="PCM_16"))
    return path


def _name_regex_chain(**params: object) -> CapabilityChain:
    chain = CapabilityChain(name="Name regex filter")
    chain.add_node("builtin.file_filter.name_regex", params, node_id="name-regex")
    return chain


def test_name_regex_capability_is_discoverable_file_filter_with_action_dropdown() -> None:
    capabilities = {cap.id: cap for cap in list_capabilities()}
    cap = capabilities["builtin.file_filter.name_regex"]

    assert cap.type == "file_filter"
    assert cap.operation_name == "name_regex_filter"
    assert cap.safety.destructive is False
    assert cap.safety.requires_confirmation is False
    assert cap.metadata["dry_run_supported"] is True
    params = {param.name: param for param in cap.parameters}
    assert params["pattern"].required is True
    assert params["action"].choices == ["skip", "delete", "copy", "move", "rename"]
    assert params["action"].default == "skip"
    assert params["destination_dir"].control_hint == "path"
    assert params["rename_template"].default == "{stem}{suffix}"
    assert get_capability("builtin.destructive.name_regex").id == "builtin.file_filter.name_regex"


def test_name_regex_validation_rejects_invalid_regex() -> None:
    validation = validate_capability_params(
        "builtin.file_filter.name_regex",
        {"pattern": "[", "case_sensitive": False},
    )

    assert validation.valid is False
    assert validation.errors[0].code == "invalid_regex"
    assert validation.errors[0].parameter == "pattern"


def test_name_regex_validation_requires_destination_for_copy_and_move() -> None:
    copy_validation = validate_capability_params(
        "builtin.file_filter.name_regex", {"pattern": "junk", "action": "copy"}
    )
    move_validation = validate_capability_params(
        "builtin.file_filter.name_regex", {"pattern": "junk", "action": "move"}
    )

    assert copy_validation.valid is False
    assert copy_validation.errors[0].code == "missing_required_for_action"
    assert move_validation.valid is False
    assert move_validation.errors[0].code == "missing_required_for_action"


def test_name_regex_preview_matches_filename_without_mutating(tmp_path: Path) -> None:
    junk = _write_tone(tmp_path / "JUNK_take.wav")
    keep = _write_tone(tmp_path / "keeper.wav")
    chain = _name_regex_chain(pattern="junk")

    preview = preview_name_regex_filter(chain, [tmp_path])

    assert preview.removed_candidates == [junk]
    assert preview.kept == [keep]
    assert preview.removed_count == 1
    assert preview.kept_count == 1
    assert junk.exists()
    assert keep.exists()


def test_name_regex_default_skip_filters_match_without_confirmation_or_deleting(
    tmp_path: Path,
) -> None:
    junk = _write_tone(tmp_path / "junk_take.wav")
    keep = _write_tone(tmp_path / "keeper.wav")

    run = execute_file_chain(_name_regex_chain(pattern="junk"), [tmp_path])

    assert run.failed_count == 0
    assert run.filtered_count == 1
    assert run.kept_count == 1
    assert junk.exists()
    assert keep.exists()
    statuses = {result.source_path.name: result.status for result in run.report.results}
    assert statuses == {"junk_take.wav": "filtered", "keeper.wav": "kept"}


def test_name_regex_delete_action_requires_confirmation(tmp_path: Path) -> None:
    junk = _write_tone(tmp_path / "junk_take.wav")

    with pytest.raises(AudioCLIError, match="name-regex.*confirmation"):
        execute_file_chain(_name_regex_chain(pattern="junk", action="delete"), [tmp_path])

    assert junk.exists()


def test_name_regex_delete_action_deletes_matching_names_only(tmp_path: Path) -> None:
    junk = _write_tone(tmp_path / "junk_take.wav")
    keep = _write_tone(tmp_path / "keeper.wav")
    chain = _name_regex_chain(pattern="junk", action="delete")
    preview = preview_name_regex_filter(chain, [tmp_path])

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
    assert not junk.exists()
    assert keep.exists()
    statuses = {result.source_path.name: result.status for result in run.report.results}
    assert statuses == {"junk_take.wav": "removed", "keeper.wav": "kept"}


def test_name_regex_copy_action_copies_match_and_keeps_original_downstream(
    tmp_path: Path,
) -> None:
    junk = _write_tone(tmp_path / "junk_take.wav")
    keep = _write_tone(tmp_path / "keeper.wav")
    copies = tmp_path / "matches"

    run = execute_file_chain(
        _name_regex_chain(pattern="junk", action="copy", destination_dir=str(copies)),
        [tmp_path],
    )

    assert run.failed_count == 0
    assert run.copied_count == 1
    assert run.kept_count == 1
    assert (copies / "junk_take.wav").exists()
    assert junk.exists()
    assert keep.exists()


def test_name_regex_move_action_requires_confirmation_and_moves_match(
    tmp_path: Path,
) -> None:
    junk = _write_tone(tmp_path / "junk_take.wav")
    keep = _write_tone(tmp_path / "keeper.wav")
    moved = tmp_path / "moved"
    chain = _name_regex_chain(pattern="junk", action="move", destination_dir=str(moved))
    preview = preview_name_regex_filter(chain, [tmp_path])

    with pytest.raises(AudioCLIError, match="name-regex.*confirmation"):
        execute_file_chain(chain, [tmp_path])

    run = execute_file_chain(
        chain,
        [tmp_path],
        destructive_confirmation=DestructiveConfirmation(
            confirmed=True,
            affected_paths=preview.affected_paths,
        ),
    )

    assert run.failed_count == 0
    assert run.moved_count == 1
    assert not junk.exists()
    assert (moved / "junk_take.wav").exists()
    assert keep.exists()


def test_name_regex_rename_action_uses_template_and_requires_confirmation(
    tmp_path: Path,
) -> None:
    junk = _write_tone(tmp_path / "junk_take.wav")
    renamed = tmp_path / "matched_junk_take.wav"
    chain = _name_regex_chain(
        pattern="junk",
        action="rename",
        rename_template="matched_{stem}{suffix}",
    )
    preview = preview_name_regex_filter(chain, [tmp_path])

    run = execute_file_chain(
        chain,
        [tmp_path],
        destructive_confirmation=DestructiveConfirmation(
            confirmed=True,
            affected_paths=preview.affected_paths,
        ),
    )

    assert run.failed_count == 0
    assert run.renamed_count == 1
    assert not junk.exists()
    assert renamed.exists()


def test_name_regex_confirmation_paths_must_match_preview_candidates(tmp_path: Path) -> None:
    junk = _write_tone(tmp_path / "junk_take.wav")
    keep = _write_tone(tmp_path / "keeper.wav")

    with pytest.raises(AudioCLIError, match="name-regex.*affected_paths.*dry-run candidates"):
        execute_file_chain(
            _name_regex_chain(pattern="junk", action="delete"),
            [tmp_path],
            destructive_confirmation=DestructiveConfirmation(confirmed=True, affected_paths=[keep]),
        )

    assert junk.exists()
    assert keep.exists()
