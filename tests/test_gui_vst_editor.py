"""GUI tests for the VST/AU editor popout integration."""

from __future__ import annotations

import os

import pytest

from audiocli.capabilities import get_capability
from audiocli.gui.app import create_main_window
from audiocli.gui.service import InMemoryWorkspaceService

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

QtCore = pytest.importorskip("PySide6.QtCore")
QtGui = pytest.importorskip("PySide6.QtGui")
QtWidgets = pytest.importorskip("PySide6.QtWidgets")


class _FakeVstHostController(QtCore.QObject):
    loaded = QtCore.Signal(dict)
    parameters = QtCore.Signal(list)
    closed = QtCore.Signal(dict)
    error = QtCore.Signal(str)
    status = QtCore.Signal(str)
    exited = QtCore.Signal(dict)

    def __init__(self) -> None:
        super().__init__()
        self.opened: list[dict[str, object]] = []
        self.stopped = False

    def open_editor(self, *, plugin_path: str, params: list[str]) -> None:
        self.opened.append({"plugin_path": plugin_path, "params": list(params)})

    def stop(self) -> None:
        self.stopped = True


class _FakeDiscoveredPlugin:
    def __init__(self, *, name: str, path: str, plugin_format: str = "VST3") -> None:
        self._view = {
            "name": name,
            "path": path,
            "format": plugin_format,
            "scope": "user",
            "scan_directory": "",
            "platform": "darwin",
        }

    def to_view_model(self) -> dict[str, str]:
        return dict(self._view)


@pytest.fixture
def qapp():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    yield app


def _latest_child(parent, widget_type, object_name):
    children = parent.findChildren(widget_type, object_name)
    assert children
    return children[-1]


def test_vst_node_shows_editor_and_mirrors_parameters(qapp, tmp_path) -> None:
    plugin_path = tmp_path / "effect.vst3"
    plugin_path.write_text("", encoding="utf-8")
    service = InMemoryWorkspaceService([get_capability("builtin.external_plugin.vst")])
    node = service.add_node("builtin.external_plugin.vst")
    service.update_selected_param("plugin_path", str(plugin_path))
    controller = _FakeVstHostController()

    window = create_main_window(
        test_safe=True,
        service=service,
        vst_host_controller_factory=lambda: controller,
    )
    qapp.processEvents()

    open_button = window.findChild(QtWidgets.QPushButton, "open_vst_editor_button")
    assert open_button is not None
    open_button.click()
    qapp.processEvents()

    assert controller.opened == [{"plugin_path": str(plugin_path), "params": []}]

    controller.parameters.emit(
        [
            {"key": "gain", "display_name": "Gain", "value": 2.5, "type": "float"},
            {"key": "mode", "display_name": "Mode", "value": "Hard", "type": "str"},
        ]
    )
    qapp.processEvents()

    assert service.chain.get_node(node.id).params["params"] == ["gain=2.5", "mode=Hard"]
    assert window.findChild(QtWidgets.QScrollArea, "vst_parameter_scroll_area") is not None
    gain_widget = window.findChild(QtWidgets.QDoubleSpinBox, "vst_param_widget_gain")
    assert gain_widget is not None
    assert gain_widget.value() == 2.5

    window.close()
    assert controller.stopped is True


def test_vst_empty_state_uses_code_font(qapp) -> None:
    qapp.setProperty("_audiocli_workspace_theme_applied", True)
    qapp.setFont(QtGui.QFont("Arial"))
    service = InMemoryWorkspaceService([get_capability("builtin.external_plugin.vst")])
    service.add_node("builtin.external_plugin.vst")

    window = create_main_window(test_safe=True, service=service)
    qapp.processEvents()

    hint = window.findChild(QtWidgets.QLabel, "vst_parameter_empty_hint")
    assert hint is not None
    assert hint.font().fixedPitch() is True
    window.close()


def test_capability_browser_items_use_code_font(qapp) -> None:
    qapp.setProperty("_audiocli_workspace_theme_applied", True)
    qapp.setFont(QtGui.QFont("Arial"))
    service = InMemoryWorkspaceService([get_capability("builtin.external_plugin.vst")])

    window = create_main_window(test_safe=True, service=service)
    qapp.processEvents()

    browser = window.findChild(QtWidgets.QTreeWidget, "capability_browser")
    assert browser is not None
    group = browser.topLevelItem(0)
    child = group.child(0)
    assert group.font(0).fixedPitch() is True
    assert child.font(0).fixedPitch() is True
    window.close()


def test_vst_node_detected_plugin_picker_updates_plugin_path(qapp, tmp_path, monkeypatch) -> None:
    plugin_path = tmp_path / "detected.vst3"
    plugin_path.mkdir()
    monkeypatch.setattr(
        "audiocli.plugin_discovery.discover_default_plugins",
        lambda: [_FakeDiscoveredPlugin(name="Detected Effect", path=str(plugin_path))],
    )
    service = InMemoryWorkspaceService([get_capability("builtin.external_plugin.vst")])
    service.add_node("builtin.external_plugin.vst")

    window = create_main_window(test_safe=True, service=service)
    qapp.processEvents()

    picker = window.findChild(QtWidgets.QComboBox, "vst_detected_plugin_combo")
    assert picker is not None
    assert picker.count() == 2
    assert picker.itemText(1) == "Detected Effect  (VST3 / user)"

    picker.setCurrentIndex(1)
    qapp.processEvents()

    selected = service.selected_node()
    assert selected is not None
    assert selected.params["plugin_path"] == str(plugin_path)
    path_line = _latest_child(window, QtWidgets.QLineEdit, "param_widget_plugin_path_line")
    assert path_line.text() == str(plugin_path)
    window.close()


def test_vst_node_plugin_picker_refreshes_cached_scan(qapp, tmp_path, monkeypatch) -> None:
    first_path = tmp_path / "first.vst3"
    second_path = tmp_path / "second.vst3"
    first_path.mkdir()
    second_path.mkdir()
    scans = [
        [_FakeDiscoveredPlugin(name="First", path=str(first_path))],
        [_FakeDiscoveredPlugin(name="Second", path=str(second_path))],
    ]

    def fake_scan():
        return scans.pop(0)

    monkeypatch.setattr("audiocli.plugin_discovery.discover_default_plugins", fake_scan)
    service = InMemoryWorkspaceService([get_capability("builtin.external_plugin.vst")])
    service.add_node("builtin.external_plugin.vst")
    window = create_main_window(test_safe=True, service=service)

    picker = window.findChild(QtWidgets.QComboBox, "vst_detected_plugin_combo")
    assert picker is not None
    assert picker.itemText(1) == "First  (VST3 / user)"

    window.findChild(QtWidgets.QPushButton, "refresh_vst_plugins_button").click()
    qapp.processEvents()

    picker = _latest_child(window, QtWidgets.QComboBox, "vst_detected_plugin_combo")
    assert picker.itemText(1) == "Second  (VST3 / user)"
    window.close()


def test_vst_host_errors_surface_in_parameters_panel(qapp, tmp_path) -> None:
    plugin_path = tmp_path / "effect.vst3"
    plugin_path.write_text("", encoding="utf-8")
    service = InMemoryWorkspaceService([get_capability("builtin.external_plugin.vst")])
    service.add_node("builtin.external_plugin.vst")
    service.update_selected_param("plugin_path", str(plugin_path))
    controller = _FakeVstHostController()
    window = create_main_window(
        test_safe=True,
        service=service,
        vst_host_controller_factory=lambda: controller,
    )

    window.findChild(QtWidgets.QPushButton, "open_vst_editor_button").click()
    controller.error.emit("native editor failed")
    qapp.processEvents()

    status = window.findChild(QtWidgets.QLabel, "vst_host_status")
    assert status is not None
    assert status.text() == "native editor failed"
    assert status.property("state") == "failed"
    window.close()


def test_vst_parameter_mirror_is_paged_and_scrollable(qapp, tmp_path) -> None:
    plugin_path = tmp_path / "effect.vst3"
    plugin_path.write_text("", encoding="utf-8")
    service = InMemoryWorkspaceService([get_capability("builtin.external_plugin.vst")])
    service.add_node("builtin.external_plugin.vst")
    service.update_selected_param("plugin_path", str(plugin_path))
    controller = _FakeVstHostController()
    window = create_main_window(
        test_safe=True,
        service=service,
        vst_host_controller_factory=lambda: controller,
    )

    window.findChild(QtWidgets.QPushButton, "open_vst_editor_button").click()
    controller.parameters.emit(
        [
            {
                "key": f"param_{index:02d}",
                "display_name": f"Parameter {index:02d}",
                "value": float(index),
                "type": "float",
            }
            for index in range(30)
        ]
    )
    qapp.processEvents()

    assert window.findChild(QtWidgets.QScrollArea, "vst_parameter_scroll_area") is not None
    assert window.findChild(QtWidgets.QDoubleSpinBox, "vst_param_widget_param_00") is not None
    assert window.findChild(QtWidgets.QDoubleSpinBox, "vst_param_widget_param_23") is not None
    assert window.findChild(QtWidgets.QDoubleSpinBox, "vst_param_widget_param_24") is None
    page_label = _latest_child(window, QtWidgets.QLabel, "vst_parameter_page_label")
    assert page_label.text() == "1-24 of 30"

    _latest_child(window, QtWidgets.QPushButton, "vst_params_next_page_button").click()
    qapp.processEvents()

    assert window.findChild(QtWidgets.QDoubleSpinBox, "vst_param_widget_param_24") is not None
    page_label = _latest_child(window, QtWidgets.QLabel, "vst_parameter_page_label")
    assert page_label.text() == "25-30 of 30"
    window.close()


def test_vst_editor_close_reenables_open_button(qapp, tmp_path) -> None:
    plugin_path = tmp_path / "effect.vst3"
    plugin_path.write_text("", encoding="utf-8")
    service = InMemoryWorkspaceService([get_capability("builtin.external_plugin.vst")])
    service.add_node("builtin.external_plugin.vst")
    service.update_selected_param("plugin_path", str(plugin_path))
    controller = _FakeVstHostController()
    window = create_main_window(
        test_safe=True,
        service=service,
        vst_host_controller_factory=lambda: controller,
    )

    window.findChild(QtWidgets.QPushButton, "open_vst_editor_button").click()
    qapp.processEvents()
    assert (
        _latest_child(window, QtWidgets.QPushButton, "open_vst_editor_button").isEnabled() is False
    )

    controller.closed.emit({"type": "closed"})
    qapp.processEvents()

    open_button = _latest_child(window, QtWidgets.QPushButton, "open_vst_editor_button")
    status = window.findChild(QtWidgets.QLabel, "vst_host_status")
    assert open_button is not None
    assert open_button.isEnabled() is True
    assert status.text() == "Editor closed. Parameters are mirrored."
    assert status.property("state") == "idle"
    window.close()
