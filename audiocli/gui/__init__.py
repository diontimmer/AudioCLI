"""Optional PySide6 GUI package for AudioCLI.

Importing :mod:`audiocli.gui` is intentionally lightweight: PySide6 is only
imported by concrete GUI construction functions/modules such as
:mod:`audiocli.gui.app` at runtime.
"""

from __future__ import annotations

__all__ = ["__version__"]

__version__ = "0.1.0"
