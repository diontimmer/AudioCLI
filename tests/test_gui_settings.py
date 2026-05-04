"""GUI settings persistence tests."""

from __future__ import annotations

import json

import pytest

from audiocli.gui.settings import (
    GUI_SETTINGS_SCHEMA_VERSION,
    RECENT_LIST_LIMIT,
    GuiSettings,
    GuiSettingsError,
    default_gui_settings,
    load_gui_settings,
    save_gui_settings,
)


def test_gui_settings_defaults_include_required_preferences() -> None:
    settings = default_gui_settings()

    assert settings.schema_version == GUI_SETTINGS_SCHEMA_VERSION
    assert settings.recent_targets == []
    assert settings.recent_output_folders == []
    assert settings.worker_count == 0
    assert settings.recursive is True
    assert settings.last_output_mode == "final_only"
    assert settings.chain_library_dir


def test_gui_settings_save_load_round_trip(tmp_path) -> None:
    path = tmp_path / "gui-settings.json"
    settings = GuiSettings(
        recent_targets=["input.wav", "album"],
        recent_output_folders=["out"],
        worker_count=4,
        recursive=False,
        last_output_mode="keep_intermediates",
        chain_library_dir=str(tmp_path / "chains"),
    )

    saved = save_gui_settings(settings, path)
    loaded = load_gui_settings(saved)

    assert loaded == settings
    assert json.loads(path.read_text())["schema_version"] == GUI_SETTINGS_SCHEMA_VERSION


def test_gui_settings_missing_file_uses_defaults(tmp_path) -> None:
    settings = load_gui_settings(tmp_path / "missing.json")

    assert settings == default_gui_settings()


@pytest.mark.parametrize(
    ("payload", "code", "message"),
    [
        (
            {"schema_version": GUI_SETTINGS_SCHEMA_VERSION + 1},
            "unsupported_schema_version",
            "newer",
        ),
        ({"schema_version": "1"}, "schema_error", "integer"),
        ({"recent_targets": []}, "missing_schema_version", "schema_version"),
        (
            {"schema_version": 1, "worker_count": -1},
            "schema_error",
            "worker_count",
        ),
        (
            {"schema_version": 1, "last_output_mode": "bad"},
            "schema_error",
            "last_output_mode",
        ),
    ],
)
def test_gui_settings_schema_errors_are_clear(tmp_path, payload, code, message) -> None:
    path = tmp_path / "settings.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(GuiSettingsError) as exc_info:
        load_gui_settings(path)

    assert exc_info.value.code == code
    assert message in str(exc_info.value)


def test_gui_settings_malformed_json_is_clear(tmp_path) -> None:
    path = tmp_path / "bad.json"
    path.write_text("{not json", encoding="utf-8")

    with pytest.raises(GuiSettingsError) as exc_info:
        load_gui_settings(path)

    assert exc_info.value.code == "invalid_json"
    assert "Invalid GUI settings JSON" in str(exc_info.value)


def test_gui_settings_recent_lists_dedupe_move_to_front_and_limit() -> None:
    settings = GuiSettings(
        recent_targets=[f"old-{index}.wav" for index in range(RECENT_LIST_LIMIT + 3)],
        chain_library_dir="chains",
    )

    updated = settings.with_recent_targets(["new.wav", "old-2.wav", "new.wav"])

    assert updated.recent_targets[0:2] == ["new.wav", "old-2.wav"]
    assert len(updated.recent_targets) == RECENT_LIST_LIMIT
    assert updated.recent_targets.count("new.wav") == 1
