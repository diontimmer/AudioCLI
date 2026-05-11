"""PyInstaller entry point for the AudioCLI command-line interface."""

from __future__ import annotations

from audiocli.cli import app

if __name__ == "__main__":
    app()
