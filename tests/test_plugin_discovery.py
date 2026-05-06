"""GUI-neutral VST/AU plugin discovery defaults."""

from __future__ import annotations

import sys

from audiocli.capabilities import get_capability
from audiocli.plugin_discovery import (
    default_plugin_scan_directories,
    default_plugin_scan_directory_specs,
    discover_default_plugins,
)


def test_default_plugin_scan_directories_are_macos_only_and_rootable(tmp_path, monkeypatch):
    system_root = tmp_path / "system"
    home = tmp_path / "home"

    monkeypatch.setattr(sys, "platform", "darwin")
    dirs = default_plugin_scan_directories(system_root=system_root, home=home)

    assert [(d.format, d.scope, d.path) for d in dirs] == [
        ("VST3", "system", system_root / "Library/Audio/Plug-Ins/VST3"),
        ("VST3", "user", home / "Library/Audio/Plug-Ins/VST3"),
        ("AU", "system", system_root / "Library/Audio/Plug-Ins/Components"),
        ("AU", "user", home / "Library/Audio/Plug-Ins/Components"),
    ]

    monkeypatch.setattr(sys, "platform", "linux")
    dirs = default_plugin_scan_directories(system_root=system_root, home=home)
    assert [(d.format, d.scope, d.path) for d in dirs] == [
        ("VST3", "system", system_root / "usr/lib/vst3"),
        ("VST3", "system", system_root / "usr/local/lib/vst3"),
        ("VST3", "user", home / ".vst3"),
    ]


def test_default_plugin_scan_directories_are_cross_platform(tmp_path):
    home = tmp_path / "home"
    system_root = tmp_path / "system"

    linux_dirs = default_plugin_scan_directories(
        platform="linux",
        system_root=system_root,
        home=home,
    )
    assert [(d.platform, d.format, d.scope, d.path) for d in linux_dirs] == [
        ("linux", "VST3", "system", system_root / "usr/lib/vst3"),
        ("linux", "VST3", "system", system_root / "usr/local/lib/vst3"),
        ("linux", "VST3", "user", home / ".vst3"),
    ]

    windows_dirs = default_plugin_scan_directories(
        platform="win32",
        home=home,
        environ={
            "COMMONPROGRAMFILES": str(tmp_path / "Common Files"),
            "LOCALAPPDATA": str(tmp_path / "LocalAppData"),
        },
    )
    assert [(d.platform, d.format, d.scope, d.path) for d in windows_dirs] == [
        ("win32", "VST3", "system", tmp_path / "Common Files/VST3"),
        ("win32", "VST3", "user", tmp_path / "LocalAppData/Programs/Common/VST3"),
    ]


def test_discover_default_plugins_scans_macos_fixed_dirs_without_loading_plugins(
    tmp_path,
    monkeypatch,
):
    system_root = tmp_path / "system"
    home = tmp_path / "home"
    system_vst3 = system_root / "Library/Audio/Plug-Ins/VST3"
    user_vst3 = home / "Library/Audio/Plug-Ins/VST3"
    system_au = system_root / "Library/Audio/Plug-Ins/Components"
    user_au = home / "Library/Audio/Plug-Ins/Components"
    for scan_dir in (system_vst3, user_vst3, system_au, user_au):
        scan_dir.mkdir(parents=True)

    (system_vst3 / "Alpha.vst3").mkdir()
    (user_vst3 / "Beta.VST3").mkdir()
    (system_au / "Gamma.component").mkdir()
    (user_au / "Ignored.txt").write_text("not a plugin")
    (user_au / "Nested.component" / "TooDeep.component").mkdir(parents=True)

    sys.modules.pop("pedalboard", None)
    monkeypatch.setattr(sys, "platform", "darwin")

    plugins = discover_default_plugins(system_root=system_root, home=home)

    assert "pedalboard" not in sys.modules
    assert [(p.name, p.format, p.scope, p.path) for p in plugins] == [
        ("Alpha", "VST3", "system", system_vst3 / "Alpha.vst3"),
        ("Beta", "VST3", "user", user_vst3 / "Beta.VST3"),
        ("Gamma", "AU", "system", system_au / "Gamma.component"),
        ("Nested", "AU", "user", user_au / "Nested.component"),
    ]


def test_vst_capability_metadata_exposes_macos_default_scan_directories():
    cap = get_capability("builtin.external_plugin.vst")

    scan_dirs = cap.metadata["default_scan_directories"]

    assert scan_dirs == default_plugin_scan_directory_specs()
    assert default_plugin_scan_directory_specs(platform="darwin") == [
        {
            "path": "/Library/Audio/Plug-Ins/VST3",
            "format": "VST3",
            "scope": "system",
            "platform": "darwin",
        },
        {
            "path": "~/Library/Audio/Plug-Ins/VST3",
            "format": "VST3",
            "scope": "user",
            "platform": "darwin",
        },
        {
            "path": "/Library/Audio/Plug-Ins/Components",
            "format": "AU",
            "scope": "system",
            "platform": "darwin",
        },
        {
            "path": "~/Library/Audio/Plug-Ins/Components",
            "format": "AU",
            "scope": "user",
            "platform": "darwin",
        },
    ]
