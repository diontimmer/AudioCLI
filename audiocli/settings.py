"""Persistent user settings for AudioCLI.

Settings live as a JSON file at the platform-appropriate user-config
location (``platformdirs.user_config_dir("audiocli")``):

* Linux: ``~/.config/audiocli/settings.json``
* macOS: ``~/Library/Application Support/audiocli/settings.json``
* Windows: ``%APPDATA%\\audiocli\\settings.json``

The file carries a top-level ``"schema"`` integer so future format
changes can migrate cleanly. ``load_settings()`` returns sensible
defaults when the file is absent (first run), and raises
:class:`audiocli.errors.ConfigError` on malformed JSON or unknown
schema versions so the CLI can render a clean error.

``platformdirs`` is imported lazily inside the path-resolver so
``audiocli --help`` does not pay for it.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any

from audiocli.errors import ConfigError

#: The current on-disk schema version. Bump when the JSON shape changes
#: in a non-additive way; keep `_migrate` in sync.
SCHEMA_VERSION = 1

#: App name passed to ``platformdirs`` so the config dir matches the
#: package name across platforms.
_APP_NAME = "audiocli"


def _default_workers() -> int:
    return min(8, os.cpu_count() or 1)


@dataclass
class Settings:
    """In-memory representation of persisted user settings.

    Field defaults match the CLI defaults so a freshly-installed user
    sees the same behaviour as someone with an empty settings file.
    """

    targets: list[Path] = field(default_factory=list)
    output: Path | None = None
    workers: int = field(default_factory=_default_workers)
    recursive: bool = False
    overwrite: bool = False

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["targets"] = [str(p) for p in self.targets]
        d["output"] = str(self.output) if self.output is not None else None
        return {"schema": SCHEMA_VERSION, **d}

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> Settings:
        targets = [Path(p) for p in raw.get("targets", []) or []]
        output_raw = raw.get("output")
        output = Path(output_raw) if output_raw else None
        # Use defaults for any field absent from disk so old files can
        # gain new fields without manual migration.
        defaults = cls()
        return cls(
            targets=targets,
            output=output,
            workers=int(raw.get("workers", defaults.workers)),
            recursive=bool(raw.get("recursive", defaults.recursive)),
            overwrite=bool(raw.get("overwrite", defaults.overwrite)),
        )

    def replace(self, **changes: Any) -> Settings:
        """Return a copy with the given fields overridden."""
        return replace(self, **changes)


def settings_path() -> Path:
    """Resolve the platform-appropriate settings file path.

    Honours ``AUDIOCLI_SETTINGS_FILE`` for tests / scripted overrides;
    otherwise resolves via ``platformdirs.user_config_dir``. Lazy
    ``platformdirs`` import so importing this module (and hence
    ``audiocli.cli``) stays cheap.
    """
    override = os.environ.get("AUDIOCLI_SETTINGS_FILE")
    if override:
        return Path(override)
    import platformdirs  # noqa: PLC0415

    return Path(platformdirs.user_config_dir(_APP_NAME)) / "settings.json"


def _migrate(raw: dict[str, Any], path: Path) -> dict[str, Any]:
    """Migrate ``raw`` (a parsed JSON dict) to :data:`SCHEMA_VERSION`.

    Currently a no-op stub: the only known schema is ``1``. Future
    migrations should branch on ``raw.get("schema")`` and rewrite the
    dict to the latest shape, returning the migrated dict.
    """
    schema = raw.get("schema")
    if schema is None:
        # Treat a missing schema field as schema=1 so users hand-editing
        # the file aren't punished. Anything truly broken will fall out
        # of the per-field parsing below.
        return {**raw, "schema": SCHEMA_VERSION}
    if not isinstance(schema, int):
        raise ConfigError(f"settings file {path}: 'schema' must be an integer, got {schema!r}")
    if schema > SCHEMA_VERSION:
        raise ConfigError(
            f"settings file {path}: schema version {schema} is newer than this "
            f"AudioCLI supports (max {SCHEMA_VERSION}). Upgrade audiocli or "
            f"delete the file to reset to defaults."
        )
    if schema < SCHEMA_VERSION:
        # No older schemas exist yet. When one does, dispatch here.
        raise ConfigError(
            f"settings file {path}: schema version {schema} is no longer supported. "
            f"Delete the file to reset to defaults."
        )
    return raw


def load_settings(path: Path | None = None) -> Settings:
    """Load settings from disk, returning defaults if the file is absent.

    Raises :class:`ConfigError` with the file path embedded if the file
    exists but is malformed or carries an unknown schema version.
    """
    p = path or settings_path()
    if not p.exists():
        return Settings()
    try:
        text = p.read_text(encoding="utf-8")
    except OSError as e:
        raise ConfigError(f"settings file {p}: cannot read ({e})") from e
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as e:
        raise ConfigError(f"settings file {p}: malformed JSON ({e.msg} at line {e.lineno})") from e
    if not isinstance(raw, dict):
        raise ConfigError(f"settings file {p}: top-level value must be a JSON object")
    raw = _migrate(raw, p)
    return Settings.from_dict(raw)


def save_settings(settings: Settings, path: Path | None = None) -> Path:
    """Write ``settings`` to disk atomically(-ish) and return the path.

    Creates the parent directory if needed and replaces the file via a
    sibling ``.tmp`` rename so a crash mid-write doesn't truncate the
    real file.
    """
    p = path or settings_path()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(p.suffix + ".tmp")
        tmp.write_text(json.dumps(settings.to_dict(), indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, p)
    except OSError as e:
        raise ConfigError(f"settings file {p}: cannot write ({e})") from e
    return p
