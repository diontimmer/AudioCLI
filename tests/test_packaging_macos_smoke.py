"""Static tests for macOS-first GUI packaging smoke helpers."""

from __future__ import annotations

import sys

from audiocli.gui import app as gui_app
from audiocli.plugin_discovery import macos_default_plugin_scan_directory_specs
from scripts import gui_packaging_smoke, macos_gui_smoke


def _loaded_pyside_modules() -> set[str]:
    return {name for name in sys.modules if name.startswith("PySide6")}


def test_macos_smoke_static_path_reports_core_requirements_without_pyside6() -> None:
    before = _loaded_pyside_modules()

    result = macos_gui_smoke.run_static_smoke()

    assert result["has_vst_capability"] is True
    assert result["live_plugin_status"] == "skipped_missing_env"
    assert result["default_plugin_scan_specs"] == macos_default_plugin_scan_directory_specs()
    assert _loaded_pyside_modules() == before


def test_cross_platform_smoke_static_path_reports_current_platform_without_pyside6() -> None:
    before = _loaded_pyside_modules()

    result = gui_packaging_smoke.run_static_smoke()

    assert result["has_vst_capability"] is True
    assert result["live_plugin_status"] == "skipped_missing_env"
    assert all(
        spec["platform"] in {"darwin", "linux", "win32"}
        for spec in result["default_plugin_scan_specs"]
    )
    assert _loaded_pyside_modules() == before


def test_packaged_static_smoke_entrypoint_does_not_import_pyside6(capsys) -> None:
    before = _loaded_pyside_modules()

    exit_code = gui_app.main(["audiocli-gui", "--packaged-static-smoke"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "AudioCLI GUI packaged static smoke" in captured.out
    assert "builtin.external_plugin.vst" not in captured.err
    assert _loaded_pyside_modules() == before


def test_macos_smoke_refuses_window_construction_off_macos() -> None:
    if sys.platform == "darwin":
        return

    try:
        macos_gui_smoke.main(["--construct-window"])
    except SystemExit as exc:
        assert exc.code == 2
    else:  # pragma: no cover - defensive
        raise AssertionError("expected SystemExit for non-Darwin window construction")
