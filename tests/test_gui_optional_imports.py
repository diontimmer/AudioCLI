"""Tests for the optional GUI import boundary."""

from __future__ import annotations

import importlib
import sys


def test_gui_package_and_app_import_do_not_import_pyside6() -> None:
    before = {name for name in sys.modules if name.startswith("PySide6")}

    import audiocli  # noqa: F401

    gui_pkg = importlib.import_module("audiocli.gui")
    gui_app = importlib.import_module("audiocli.gui.app")

    after = {name for name in sys.modules if name.startswith("PySide6")}
    assert gui_pkg.__name__ == "audiocli.gui"
    assert gui_app.__name__ == "audiocli.gui.app"
    assert after == before
