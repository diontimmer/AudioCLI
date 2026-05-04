"""First-party special-case command registrar.

``info``, ``remove-silent``, and ``chunk`` do not fit the standard
``(buf) -> buf`` filter contract used by registered ops. They stay as direct
Typer commands, while their reusable domain logic lives in focused modules:
``analysis``, ``silence``, and ``chunking``.
"""

from __future__ import annotations

import typer

from audiocli.commands import (
    register_chunk_command,
    register_info_command,
    register_remove_silent_command,
)


def register_special_commands(app: typer.Typer) -> None:
    register_info_command(app)
    register_remove_silent_command(app)
    register_chunk_command(app)


__all__ = ["register_special_commands"]
