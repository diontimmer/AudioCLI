"""Versioned persistence for GUI-only AudioCLI preferences."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from platformdirs import user_config_path, user_data_path

GUI_SETTINGS_SCHEMA_VERSION = 1
GUI_SETTINGS_FILENAME = "gui-settings.json"
RECENT_LIST_LIMIT = 10
VALID_OUTPUT_MODES = frozenset({"final_only", "keep_intermediates", "destructive"})


class GuiSettingsError(ValueError):
    """Raised when persisted GUI settings cannot be safely loaded."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class GuiSettings:
    """GUI-specific preferences that are intentionally separate from CLI config."""

    schema_version: int = GUI_SETTINGS_SCHEMA_VERSION
    recent_targets: list[str] = field(default_factory=list)
    recent_output_folders: list[str] = field(default_factory=list)
    worker_count: int = 0
    recursive: bool = True
    last_output_mode: str = "final_only"
    chain_library_dir: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "schema_version", int(self.schema_version))
        object.__setattr__(
            self,
            "recent_targets",
            _normalize_recent_list(self.recent_targets),
        )
        object.__setattr__(
            self,
            "recent_output_folders",
            _normalize_recent_list(self.recent_output_folders),
        )
        object.__setattr__(self, "worker_count", max(0, int(self.worker_count)))
        object.__setattr__(self, "recursive", bool(self.recursive))
        mode = str(self.last_output_mode or "final_only")
        if mode not in VALID_OUTPUT_MODES:
            mode = "final_only"
        object.__setattr__(self, "last_output_mode", mode)
        chain_library_dir = str(self.chain_library_dir or default_chain_library_dir())
        object.__setattr__(self, "chain_library_dir", chain_library_dir)

    def with_recent_targets(self, targets: Sequence[str | Path]) -> GuiSettings:
        return replace(
            self,
            recent_targets=_merge_recent_values(
                [str(path) for path in targets], self.recent_targets
            ),
        )

    def with_recent_output_folder(self, output_path: str | Path | None) -> GuiSettings:
        folder = _output_folder_value(output_path)
        if not folder:
            return self
        return replace(
            self,
            recent_output_folders=_merge_recent_values([folder], self.recent_output_folders),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "recent_targets": list(self.recent_targets),
            "recent_output_folders": list(self.recent_output_folders),
            "worker_count": self.worker_count,
            "recursive": self.recursive,
            "last_output_mode": self.last_output_mode,
            "chain_library_dir": self.chain_library_dir,
        }

    def to_view_model(self) -> dict[str, Any]:
        return self.to_dict()

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> GuiSettings:
        _validate_settings_mapping(data)
        return cls(
            schema_version=int(data["schema_version"]),
            recent_targets=_require_string_list(data, "recent_targets"),
            recent_output_folders=_require_string_list(data, "recent_output_folders"),
            worker_count=_require_non_negative_int(data, "worker_count"),
            recursive=_require_bool(data, "recursive"),
            last_output_mode=_require_output_mode(data, "last_output_mode"),
            chain_library_dir=_require_string(data, "chain_library_dir"),
        )


Settings = GuiSettings


def default_settings_path() -> Path:
    """Return the platform-specific default GUI settings file path."""

    return user_config_path("AudioCLI", appauthor=False) / GUI_SETTINGS_FILENAME


def default_chain_library_dir() -> Path:
    """Return the platform-specific default saved-chain library directory."""

    return user_data_path("AudioCLI", appauthor=False) / "chain-library"


def default_gui_settings() -> GuiSettings:
    return GuiSettings(chain_library_dir=str(default_chain_library_dir()))


def load_gui_settings(path: str | Path | None = None) -> GuiSettings:
    """Load GUI settings, returning defaults when no settings file exists."""

    source = Path(path) if path is not None else default_settings_path()
    if not source.exists():
        return default_gui_settings()
    try:
        raw = json.loads(source.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise GuiSettingsError(
            "invalid_json", f"Invalid GUI settings JSON in {source}: {exc.msg}."
        ) from exc
    except OSError as exc:
        raise GuiSettingsError(
            "read_error", f"Could not read GUI settings {source}: {exc}."
        ) from exc
    if not isinstance(raw, Mapping):
        raise GuiSettingsError("schema_error", "GUI settings file must contain a JSON object.")
    return GuiSettings.from_dict(raw)


def save_gui_settings(settings: GuiSettings, path: str | Path | None = None) -> Path:
    """Persist GUI settings as stable, versioned JSON."""

    destination = Path(path) if path is not None else default_settings_path()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(settings.to_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return destination


def add_recent_value(
    existing: Sequence[str], value: str | Path, *, limit: int = RECENT_LIST_LIMIT
) -> list[str]:
    """Return a deduplicated recents list with ``value`` first."""

    return _merge_recent_values([str(value)], existing, limit=limit)


def _validate_settings_mapping(data: Mapping[str, Any]) -> None:
    if "schema_version" not in data:
        raise GuiSettingsError("missing_schema_version", "GUI settings are missing schema_version.")
    schema_version = data["schema_version"]
    if isinstance(schema_version, bool) or not isinstance(schema_version, int):
        raise GuiSettingsError(
            "schema_error", "GUI settings schema_version must be a JSON integer number."
        )
    if schema_version > GUI_SETTINGS_SCHEMA_VERSION:
        raise GuiSettingsError(
            "unsupported_schema_version",
            "GUI settings schema_version "
            f"{schema_version} is newer than this AudioCLI supports ({GUI_SETTINGS_SCHEMA_VERSION}).",
        )
    if schema_version < GUI_SETTINGS_SCHEMA_VERSION:
        raise GuiSettingsError(
            "unsupported_schema_version",
            "GUI settings schema_version "
            f"{schema_version} is no longer supported; expected {GUI_SETTINGS_SCHEMA_VERSION}.",
        )


def _require_string_list(data: Mapping[str, Any], field_name: str) -> list[str]:
    value = data.get(field_name, [])
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise GuiSettingsError(
            "schema_error", f"GUI settings field '{field_name}' must be a list of strings."
        )
    return _normalize_recent_list(value)


def _require_non_negative_int(data: Mapping[str, Any], field_name: str) -> int:
    value = data.get(field_name, 0)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise GuiSettingsError(
            "schema_error", f"GUI settings field '{field_name}' must be a non-negative integer."
        )
    return value


def _require_bool(data: Mapping[str, Any], field_name: str) -> bool:
    value = data.get(field_name, True)
    if not isinstance(value, bool):
        raise GuiSettingsError(
            "schema_error", f"GUI settings field '{field_name}' must be a boolean."
        )
    return value


def _require_output_mode(data: Mapping[str, Any], field_name: str) -> str:
    value = data.get(field_name, "final_only")
    if not isinstance(value, str) or value not in VALID_OUTPUT_MODES:
        raise GuiSettingsError(
            "schema_error",
            f"GUI settings field '{field_name}' must be one of {sorted(VALID_OUTPUT_MODES)}.",
        )
    return value


def _require_string(data: Mapping[str, Any], field_name: str) -> str:
    value = data.get(field_name, "")
    if not isinstance(value, str):
        raise GuiSettingsError(
            "schema_error", f"GUI settings field '{field_name}' must be a string."
        )
    return value


def _normalize_recent_list(values: Sequence[str], *, limit: int = RECENT_LIST_LIMIT) -> list[str]:
    return _merge_recent_values(values, (), limit=limit)


def _merge_recent_values(
    new_values: Sequence[str], existing: Sequence[str], *, limit: int = RECENT_LIST_LIMIT
) -> list[str]:
    seen: set[str] = set()
    merged: list[str] = []
    for raw_value in [*new_values, *existing]:
        value = str(raw_value).strip()
        if not value or value in seen:
            continue
        seen.add(value)
        merged.append(value)
        if len(merged) >= limit:
            break
    return merged


def _output_folder_value(output_path: str | Path | None) -> str:
    if output_path is None:
        return ""
    raw = str(output_path).strip()
    if not raw:
        return ""
    path = Path(raw)
    if path.suffix:
        return str(path.parent if str(path.parent) != "." else Path.cwd())
    return raw


__all__ = [
    "GUI_SETTINGS_FILENAME",
    "GUI_SETTINGS_SCHEMA_VERSION",
    "RECENT_LIST_LIMIT",
    "GuiSettings",
    "GuiSettingsError",
    "Settings",
    "add_recent_value",
    "default_chain_library_dir",
    "default_gui_settings",
    "default_settings_path",
    "load_gui_settings",
    "save_gui_settings",
]
