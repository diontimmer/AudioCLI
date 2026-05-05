"""GUI-neutral VST3/AU plugin discovery helpers.

Discovery here is intentionally conservative: it only enumerates bundle names in
known fixed directories and never imports pedalboard or loads native plugin code.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_MACOS_PLUGIN_SCAN_DIRECTORY_SPECS: tuple[tuple[str, str, str], ...] = (
    ("VST3", "system", "/Library/Audio/Plug-Ins/VST3"),
    ("VST3", "user", "~/Library/Audio/Plug-Ins/VST3"),
    ("AU", "system", "/Library/Audio/Plug-Ins/Components"),
    ("AU", "user", "~/Library/Audio/Plug-Ins/Components"),
)
_PLUGIN_SUFFIX_BY_FORMAT = {
    "VST3": ".vst3",
    "AU": ".component",
}


@dataclass(frozen=True)
class PluginScanDirectory:
    """One platform default directory that can contain native audio plugins."""

    path: Path
    format: str
    scope: str
    platform: str = "darwin"

    def to_view_model(self) -> dict[str, Any]:
        return {
            "path": str(self.path),
            "format": self.format,
            "scope": self.scope,
            "platform": self.platform,
        }


@dataclass(frozen=True)
class DiscoveredPlugin:
    """A plugin bundle discovered by filename only; no native code is loaded."""

    name: str
    path: Path
    format: str
    scope: str
    scan_directory: Path
    platform: str = "darwin"

    def to_view_model(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "path": str(self.path),
            "format": self.format,
            "scope": self.scope,
            "scan_directory": str(self.scan_directory),
            "platform": self.platform,
        }


def macos_default_plugin_scan_directory_specs() -> list[dict[str, str]]:
    """Return stable macOS plugin search-directory specs without host expansion."""

    return [
        {"path": path, "format": plugin_format, "scope": scope, "platform": "darwin"}
        for plugin_format, scope, path in _MACOS_PLUGIN_SCAN_DIRECTORY_SPECS
    ]


def default_plugin_scan_directories(
    *,
    platform: str | None = None,
    system_root: str | Path = "/",
    home: str | Path | None = None,
    existing_only: bool = False,
) -> list[PluginScanDirectory]:
    """Return default plugin scan directories for the current platform.

    Only macOS has fixed VST3/AU directories here. ``system_root`` and ``home``
    make the paths testable without touching real machine locations.
    """

    platform_name = platform or sys.platform
    if platform_name != "darwin":
        return []

    system_root_path = Path(system_root)
    home_path = Path(home).expanduser() if home is not None else Path.home()
    directories: list[PluginScanDirectory] = []

    for plugin_format, scope, raw_path in _MACOS_PLUGIN_SCAN_DIRECTORY_SPECS:
        path = _resolve_scan_directory(
            raw_path, scope=scope, system_root=system_root_path, home=home_path
        )
        if existing_only and not path.is_dir():
            continue
        directories.append(
            PluginScanDirectory(
                path=path,
                format=plugin_format,
                scope=scope,
                platform=platform_name,
            )
        )
    return directories


def discover_default_plugins(
    *,
    platform: str | None = None,
    system_root: str | Path = "/",
    home: str | Path | None = None,
) -> list[DiscoveredPlugin]:
    """Discover plugin bundles in platform default directories without loading them."""

    scan_directories = default_plugin_scan_directories(
        platform=platform,
        system_root=system_root,
        home=home,
        existing_only=True,
    )
    return discover_plugins(scan_directories)


def discover_plugins(scan_directories: list[PluginScanDirectory]) -> list[DiscoveredPlugin]:
    """Discover direct child plugin bundles in the supplied scan directories.

    This is name/path discovery only. It does not recurse, follow symlinks, or
    call ``pedalboard.load_plugin``.
    """

    discovered: list[DiscoveredPlugin] = []
    for scan_directory in scan_directories:
        suffix = _PLUGIN_SUFFIX_BY_FORMAT.get(scan_directory.format)
        if suffix is None or not scan_directory.path.is_dir():
            continue
        for child in sorted(scan_directory.path.iterdir(), key=lambda p: p.name.lower()):
            if child.name.startswith(".") or child.is_symlink():
                continue
            if child.suffix.lower() != suffix or not child.is_dir():
                continue
            discovered.append(
                DiscoveredPlugin(
                    name=_plugin_name_from_path(child),
                    path=child,
                    format=scan_directory.format,
                    scope=scan_directory.scope,
                    scan_directory=scan_directory.path,
                    platform=scan_directory.platform,
                )
            )
    return discovered


def _resolve_scan_directory(
    raw_path: str,
    *,
    scope: str,
    system_root: Path,
    home: Path,
) -> Path:
    if scope == "user":
        return home / raw_path.removeprefix("~/")
    return system_root / raw_path.removeprefix("/")


def _plugin_name_from_path(path: Path) -> str:
    suffix = path.suffix
    if suffix:
        return path.name[: -len(suffix)]
    return path.name


__all__ = [
    "DiscoveredPlugin",
    "PluginScanDirectory",
    "default_plugin_scan_directories",
    "discover_default_plugins",
    "discover_plugins",
    "macos_default_plugin_scan_directory_specs",
]
