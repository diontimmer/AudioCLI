"""Application entry point for the optional PySide6 GUI."""

from __future__ import annotations

import os
import sys
from collections.abc import Sequence


def _missing_pyside_error() -> RuntimeError:
    return RuntimeError(
        "The AudioCLI GUI requires the optional PySide6 dependency. "
        "Install it with `pip install 'audiocli[gui]'`."
    )


def create_main_window(*, test_safe: bool = False, service=None):  # noqa: ANN001, ANN201
    """Create the main workspace window, importing PySide6 lazily."""

    try:
        from audiocli.gui.main_window import MainWindow, ensure_qapplication
    except ModuleNotFoundError as exc:
        if exc.name and exc.name.startswith("PySide6"):
            raise _missing_pyside_error() from exc
        raise

    if test_safe:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    ensure_qapplication([])
    return MainWindow(service=service, test_safe=test_safe)


def main(argv: Sequence[str] | None = None) -> int:
    """Run the AudioCLI desktop shell."""

    args = list(sys.argv if argv is None else argv)
    try:
        from audiocli.gui.main_window import MainWindow, ensure_qapplication
    except ModuleNotFoundError as exc:
        if exc.name and exc.name.startswith("PySide6"):
            raise SystemExit(str(_missing_pyside_error())) from exc
        raise

    app = ensure_qapplication(args)
    window = MainWindow()
    window.show()
    return int(app.exec())


if __name__ == "__main__":
    raise SystemExit(main())
