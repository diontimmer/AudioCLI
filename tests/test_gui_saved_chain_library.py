"""Saved-chain GUI library service tests."""

from __future__ import annotations

import json

import pytest

from audiocli.capabilities import CapabilityNode, CapabilityParameter, IOShape, SafetySemantics
from audiocli.chains import CapabilityChain, ChainFormatError, load_chain, save_chain
from audiocli.gui.library import SavedChainLibraryService
from audiocli.gui.service import InMemoryWorkspaceService
from audiocli.gui.settings import GuiSettings


def _fake_capability(capability_id: str = "fake.gain") -> CapabilityNode:
    shape = IOShape("audio_buffer", "audio/*", "single")
    return CapabilityNode(
        id=capability_id,
        type="filter",
        display_name="Gain",
        description="Fake gain capability.",
        input_shape=shape,
        output_shape=shape,
        safety=SafetySemantics("pure_transform"),
        operation_name="gain",
        defaults={"db": 0.0},
        parameters=[
            CapabilityParameter(
                name="db",
                type="float",
                display_name="Gain",
                required=True,
                default=0.0,
                control_hint="number",
            )
        ],
    )


def _valid_chain() -> CapabilityChain:
    chain = CapabilityChain(
        id="chain-valid", name="Master", description="Mastering", notes="Use gently"
    )
    chain.add_node("fake.gain", {"db": -1.5}, node_id="gain")
    return chain


def test_saved_chain_library_lists_valid_invalid_and_outdated_entries(tmp_path) -> None:
    valid_path = save_chain(_valid_chain(), tmp_path / "valid.aclichain")
    invalid_path = tmp_path / "invalid.aclichain"
    invalid_chain = CapabilityChain(id="chain-invalid", name="Invalid")
    invalid_chain.add_node("missing.capability", {}, node_id="missing")
    save_chain(invalid_chain, invalid_path)
    outdated_path = tmp_path / "future.aclichain"
    outdated_path.write_text(
        json.dumps(
            {
                "schema_version": 999,
                "kind": "audiocli.saved_chain",
                "id": "future",
                "name": "Future",
                "nodes": [],
            }
        ),
        encoding="utf-8",
    )
    malformed_path = tmp_path / "malformed.aclichain"
    malformed_path.write_text("{bad json", encoding="utf-8")

    service = SavedChainLibraryService(
        tmp_path,
        capability_catalog={"fake.gain": _fake_capability()},
    )
    entries = {entry.path: entry for entry in service.list_entries()}

    assert entries[str(valid_path)].valid is True
    assert entries[str(valid_path)].name == "Master"
    assert entries[str(valid_path)].description == "Mastering"
    assert entries[str(valid_path)].notes == "Use gently"
    assert entries[str(invalid_path)].valid is False
    assert entries[str(invalid_path)].error_code == "validation_error"
    assert "Unknown capability" in entries[str(invalid_path)].error
    assert entries[str(outdated_path)].valid is False
    assert entries[str(outdated_path)].error_code == "unsupported_schema_version"
    assert "Unsupported saved chain schema_version" in entries[str(outdated_path)].error
    assert entries[str(malformed_path)].valid is False
    assert entries[str(malformed_path)].error_code == "invalid_json"


def test_saved_chain_library_rename_and_notes_preserve_file_path(tmp_path) -> None:
    path = save_chain(_valid_chain(), tmp_path / "chain.aclichain")
    service = SavedChainLibraryService(
        tmp_path,
        capability_catalog={"fake.gain": _fake_capability()},
    )

    renamed = service.rename_saved_chain(path, "Renamed Master")
    updated = service.update_saved_chain_notes(
        path, description="New description", notes="New notes"
    )
    loaded = load_chain(path, capability_catalog={"fake.gain": _fake_capability()})

    assert renamed.path == str(path)
    assert updated.path == str(path)
    assert loaded.name == "Renamed Master"
    assert loaded.description == "New description"
    assert loaded.notes == "New notes"


def test_saved_chain_library_refuses_to_load_invalid_chain(tmp_path) -> None:
    path = tmp_path / "invalid.aclichain"
    chain = CapabilityChain(id="chain-invalid", name="Invalid")
    chain.add_node("missing.capability", {}, node_id="missing")
    save_chain(chain, path)
    service = SavedChainLibraryService(
        tmp_path, capability_catalog={"fake.gain": _fake_capability()}
    )

    with pytest.raises(ChainFormatError) as exc_info:
        service.load_saved_chain(path)

    assert exc_info.value.code == "validation_error"
    assert "cannot be loaded" in str(exc_info.value)


def test_saved_chain_library_rejects_paths_outside_library_dir(tmp_path) -> None:
    library_dir = tmp_path / "library"
    outside_dir = tmp_path / "outside"
    library_dir.mkdir()
    outside_dir.mkdir()
    inside_path = save_chain(_valid_chain(), library_dir / "inside.aclichain")
    outside_path = save_chain(_valid_chain(), outside_dir / "outside.aclichain")
    service = SavedChainLibraryService(
        library_dir,
        capability_catalog={"fake.gain": _fake_capability()},
    )

    assert service.load_saved_chain("inside.aclichain").id == "chain-valid"

    calls = [
        lambda: service.entry_for_path(outside_path),
        lambda: service.load_saved_chain(outside_path),
        lambda: service.load_saved_chain("../outside/outside.aclichain"),
        lambda: service.rename_saved_chain(outside_path, "Escaped"),
        lambda: service.update_saved_chain_notes(outside_path, notes="Escaped"),
    ]
    for call in calls:
        with pytest.raises(ChainFormatError) as exc_info:
            call()
        assert exc_info.value.code == "path_error"
        assert "outside library directory" in str(exc_info.value)

    assert (
        load_chain(inside_path, capability_catalog={"fake.gain": _fake_capability()}).name
        == "Master"
    )
    assert (
        load_chain(outside_path, capability_catalog={"fake.gain": _fake_capability()}).name
        == "Master"
    )


def test_saved_chain_library_rejects_symlink_escape(tmp_path) -> None:
    library_dir = tmp_path / "library"
    outside_dir = tmp_path / "outside"
    library_dir.mkdir()
    outside_dir.mkdir()
    outside_path = save_chain(_valid_chain(), outside_dir / "outside.aclichain")
    symlink_path = library_dir / "linked.aclichain"
    symlink_path.symlink_to(outside_path)
    service = SavedChainLibraryService(
        library_dir,
        capability_catalog={"fake.gain": _fake_capability()},
    )

    entries = service.list_entries()
    linked_entry = next(entry for entry in entries if entry.path == str(symlink_path))
    assert linked_entry.valid is False
    assert linked_entry.name == "linked"
    assert linked_entry.error_code == "path_error"
    assert "outside library directory" in linked_entry.error

    view_model = service.to_view_model()
    linked_view = next(
        entry for entry in view_model["entries"] if entry["path"] == str(symlink_path)
    )
    assert linked_view["valid"] is False
    assert linked_view["name"] == "linked"
    assert linked_view["error_code"] == "path_error"
    assert "outside library directory" in linked_view["error"]
    assert view_model["error_count"] == 1

    workspace = InMemoryWorkspaceService(
        [_fake_capability()], settings=GuiSettings(chain_library_dir=str(library_dir))
    )
    workspace_view = workspace.to_view_model()
    workspace_linked_view = next(
        entry
        for entry in workspace_view["saved_chain_library"]["entries"]
        if entry["path"] == str(symlink_path)
    )
    assert workspace_linked_view["valid"] is False
    assert workspace_linked_view["error_code"] == "path_error"

    calls = [
        lambda: service.load_saved_chain(symlink_path),
        lambda: service.rename_saved_chain(symlink_path, "Escaped"),
        lambda: service.update_saved_chain_notes(symlink_path, notes="Escaped"),
    ]
    for call in calls:
        with pytest.raises(ChainFormatError) as exc_info:
            call()

        assert exc_info.value.code == "path_error"
        assert "outside library directory" in str(exc_info.value)


def test_workspace_service_persists_recent_settings_and_exposes_library_view_model(
    tmp_path,
) -> None:
    settings_path = tmp_path / "settings.json"
    chain_dir = tmp_path / "chains"
    chain_path = save_chain(_valid_chain(), chain_dir / "master.aclichain")
    settings = GuiSettings(chain_library_dir=str(chain_dir))
    service = InMemoryWorkspaceService(
        [_fake_capability()],
        settings=settings,
        settings_path=settings_path,
    )

    service.set_targets(["input-a.wav", "input-b.wav"])
    service.set_output_path(tmp_path / "out")
    service.set_output_mode("destructive")
    service.set_worker_count(3)
    service.set_recursive(False)
    saved_path = service.save_settings()
    reloaded = InMemoryWorkspaceService([_fake_capability()], settings_path=saved_path)

    assert reloaded.settings.recent_targets == ["input-a.wav", "input-b.wav"]
    assert reloaded.settings.recent_output_folders == [str(tmp_path / "out")]
    assert reloaded.job.output_mode == "destructive"
    assert reloaded.job.worker_count == 3
    assert reloaded.job.recursive is False
    view_model = reloaded.to_view_model()
    assert view_model["settings"]["chain_library_dir"] == str(chain_dir)
    assert view_model["saved_chain_library"]["entries"][0]["path"] == str(chain_path)
    assert view_model["saved_chain_library"]["entries"][0]["valid"] is True


def test_workspace_service_loads_and_edits_saved_chains_through_boundary(tmp_path) -> None:
    path = save_chain(_valid_chain(), tmp_path / "chain.aclichain")
    service = InMemoryWorkspaceService(
        [_fake_capability()],
        settings=GuiSettings(chain_library_dir=str(tmp_path)),
    )

    loaded = service.load_saved_chain(path)
    renamed = service.rename_saved_chain(path, "Boundary Rename")
    updated = service.update_saved_chain_notes(
        path, description="Boundary description", notes="Boundary notes"
    )

    assert loaded.id == "chain-valid"
    assert service.chain.name == "Master"
    assert service.selected_node_id == "gain"
    assert renamed.name == "Boundary Rename"
    assert updated.description == "Boundary description"
    assert updated.notes == "Boundary notes"
