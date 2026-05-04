"""PySide6 smoke tests for the main workspace shell.

These tests are skipped when the optional ``gui`` dependency is not installed.
"""

from __future__ import annotations

import os

import pytest

from audiocli.capabilities import CapabilityNode, CapabilityParameter, IOShape, SafetySemantics
from audiocli.gui.app import create_main_window
from audiocli.gui.service import InMemoryWorkspaceService

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

QtWidgets = pytest.importorskip("PySide6.QtWidgets")


def _form_capability() -> CapabilityNode:
    shape = IOShape("audio_buffer", "audio/*", "single")
    return CapabilityNode(
        id="fake.form",
        type="filter",
        display_name="Form Renderer",
        description="Exercises generated GUI controls.",
        input_shape=shape,
        output_shape=shape,
        safety=SafetySemantics("pure_transform"),
        operation_name="form_renderer",
        defaults={
            "name": "demo",
            "amount": 1.5,
            "enabled": True,
            "mode": "fast",
            "path": "",
        },
        parameters=[
            CapabilityParameter("name", "str", "Name", default="demo", control_hint="text"),
            CapabilityParameter("amount", "float", "Amount", default=1.5, control_hint="number"),
            CapabilityParameter("enabled", "bool", "Enabled", default=True, control_hint="toggle"),
            CapabilityParameter(
                "mode",
                "str",
                "Mode",
                default="fast",
                control_hint="select",
                choices=["fast", "safe"],
            ),
            CapabilityParameter("path", "path", "Path", default="", control_hint="path"),
        ],
    )


@pytest.fixture
def qapp():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    yield app


def test_main_window_construction_fake_service_and_form_rendering(qapp) -> None:
    service = InMemoryWorkspaceService([_form_capability()])
    service.add_node("fake.form")

    window = create_main_window(test_safe=True, service=service)
    qapp.processEvents()

    assert window.centralWidget().objectName() == "main_workspace_splitter"
    assert window.findChildren(QtWidgets.QTabWidget) == []

    browser = window.findChild(QtWidgets.QTreeWidget, "capability_browser")
    chain = window.findChild(QtWidgets.QListWidget, "chain_editor")
    assert browser is not None
    assert chain is not None
    assert browser.topLevelItemCount() == 1
    assert chain.count() == 1

    assert window.findChild(QtWidgets.QLineEdit, "param_widget_name") is not None
    assert window.findChild(QtWidgets.QDoubleSpinBox, "param_widget_amount") is not None
    assert window.findChild(QtWidgets.QCheckBox, "param_widget_enabled") is not None
    assert window.findChild(QtWidgets.QComboBox, "param_widget_mode") is not None
    assert window.findChild(QtWidgets.QWidget, "param_widget_path") is not None

    amount = window.findChild(QtWidgets.QDoubleSpinBox, "param_widget_amount")
    amount.setValue(4.0)
    qapp.processEvents()
    assert service.selected_node() is not None
    assert service.selected_node().params["amount"] == 4.0

    window.close()
