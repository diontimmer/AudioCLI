"""Typer command registrars."""

from audiocli.commands.chunk import register_chunk_command
from audiocli.commands.info import register_info_command
from audiocli.commands.remove_silent import register_remove_silent_command

__all__ = [
    "register_chunk_command",
    "register_info_command",
    "register_remove_silent_command",
]
