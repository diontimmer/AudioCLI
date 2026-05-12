"""Tests for the persistent-settings module."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from audiocli.errors import ConfigError
from audiocli.settings import (
    SCHEMA_VERSION,
    Settings,
    load_settings,
    save_settings,
    settings_path,
)


def test_roundtrip(tmp_path: Path) -> None:
    """save() then load() returns an equal Settings."""
    p = tmp_path / "settings.json"
    s = Settings(
        targets=[Path("/tmp/a.wav"), Path("/tmp/b.wav")],
        output=Path("/tmp/out"),
        workers=4,
        recursive=True,
        overwrite=True,
    )
    save_settings(s, p)
    loaded = load_settings(p)
    assert loaded == s


def test_missing_file_returns_defaults(tmp_path: Path) -> None:
    """load() with no file present returns defaults, no exception."""
    p = tmp_path / "does-not-exist.json"
    assert not p.exists()
    s = load_settings(p)
    assert s == Settings()


def test_defaults_have_sane_workers() -> None:
    """Default workers is min(8, cpu_count()) — i.e. at least 1."""
    s = Settings()
    assert s.workers >= 1
    assert s.workers <= 8


def test_malformed_json_raises_configerror(tmp_path: Path) -> None:
    """A broken JSON file raises ConfigError with the file path in message."""
    p = tmp_path / "settings.json"
    p.write_text("{not valid json", encoding="utf-8")
    with pytest.raises(ConfigError) as ei:
        load_settings(p)
    assert str(p) in str(ei.value)


def test_top_level_not_object_raises(tmp_path: Path) -> None:
    """A JSON file whose top-level value isn't an object raises ConfigError."""
    p = tmp_path / "settings.json"
    p.write_text("[1, 2, 3]", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_settings(p)


def test_unknown_schema_too_new_raises(tmp_path: Path) -> None:
    """schema=999 (newer than supported) raises ConfigError telling user how to recover."""
    p = tmp_path / "settings.json"
    p.write_text(json.dumps({"schema": 999, "workers": 4}), encoding="utf-8")
    with pytest.raises(ConfigError) as ei:
        load_settings(p)
    msg = str(ei.value)
    assert "999" in msg
    assert "delete" in msg.lower() or "upgrade" in msg.lower()


def test_unknown_schema_too_old_raises(tmp_path: Path) -> None:
    """schema=0 (older than current) raises ConfigError."""
    p = tmp_path / "settings.json"
    p.write_text(json.dumps({"schema": 0}), encoding="utf-8")
    with pytest.raises(ConfigError):
        load_settings(p)


def test_schema_field_wrong_type_raises(tmp_path: Path) -> None:
    p = tmp_path / "settings.json"
    p.write_text(json.dumps({"schema": "one"}), encoding="utf-8")
    with pytest.raises(ConfigError):
        load_settings(p)


def test_missing_schema_treated_as_current(tmp_path: Path) -> None:
    """A hand-edited file with no schema field defaults to the current schema."""
    p = tmp_path / "settings.json"
    p.write_text(json.dumps({"workers": 3, "recursive": True}), encoding="utf-8")
    s = load_settings(p)
    assert s.workers == 3
    assert s.recursive is True


def test_partial_file_uses_defaults_for_missing_fields(tmp_path: Path) -> None:
    """An old file missing newer fields should still load."""
    p = tmp_path / "settings.json"
    p.write_text(json.dumps({"schema": SCHEMA_VERSION, "workers": 2}), encoding="utf-8")
    s = load_settings(p)
    assert s.workers == 2
    assert s.recursive is False  # default
    assert s.overwrite is False
    assert s.targets == []


def test_save_writes_schema_field(tmp_path: Path) -> None:
    p = tmp_path / "settings.json"
    save_settings(Settings(workers=2), p)
    raw = json.loads(p.read_text())
    assert raw["schema"] == SCHEMA_VERSION
    assert raw["workers"] == 2


def test_save_creates_parent_dir(tmp_path: Path) -> None:
    p = tmp_path / "deep" / "nested" / "settings.json"
    save_settings(Settings(), p)
    assert p.exists()


def test_paths_per_platform_linux(monkeypatch: pytest.MonkeyPatch) -> None:
    """On Linux, settings_path resolves under XDG_CONFIG_HOME."""
    import platformdirs

    monkeypatch.delenv("AUDIOCLI_SETTINGS_FILE", raising=False)
    monkeypatch.setattr(
        platformdirs, "user_config_dir", lambda app: f"/home/u/.config/{app}", raising=True
    )
    p = settings_path()
    # Use as_posix() so the assertion is portable: on Windows, Path()
    # rewrites forward slashes to backslashes, which would make a
    # str() comparison platform-specific.
    assert p.as_posix() == "/home/u/.config/audiocli/settings.json"


def test_paths_per_platform_macos(monkeypatch: pytest.MonkeyPatch) -> None:
    import platformdirs

    monkeypatch.delenv("AUDIOCLI_SETTINGS_FILE", raising=False)
    monkeypatch.setattr(
        platformdirs,
        "user_config_dir",
        lambda app: f"/Users/u/Library/Application Support/{app}",
        raising=True,
    )
    p = settings_path()
    assert p.as_posix() == "/Users/u/Library/Application Support/audiocli/settings.json"


def test_paths_per_platform_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    import platformdirs

    monkeypatch.delenv("AUDIOCLI_SETTINGS_FILE", raising=False)
    monkeypatch.setattr(
        platformdirs,
        "user_config_dir",
        lambda app: f"C:\\Users\\u\\AppData\\Roaming\\{app}",
        raising=True,
    )
    p = settings_path()
    # PurePath normalization on Linux preserves backslashes as part of name;
    # check the trailing component instead of full string.
    assert p.name == "settings.json"
    assert "audiocli" in str(p)


def test_env_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """AUDIOCLI_SETTINGS_FILE env var overrides platformdirs resolution."""
    target = tmp_path / "override.json"
    monkeypatch.setenv("AUDIOCLI_SETTINGS_FILE", str(target))
    assert settings_path() == target


def test_settings_replace_returns_new_instance() -> None:
    s1 = Settings(workers=2)
    s2 = s1.replace(workers=4)
    assert s1.workers == 2
    assert s2.workers == 4
    assert s1 is not s2
