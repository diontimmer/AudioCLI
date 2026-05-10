"""PyInstaller entry point for the AudioCLI GUI."""

from __future__ import annotations

import sys

from audiocli.gui.app import main


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
