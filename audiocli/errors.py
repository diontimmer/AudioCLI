"""Public exception hierarchy for AudioCLI."""

from __future__ import annotations


class AudioCLIError(Exception):
    """Base class for all AudioCLI errors."""


class LoadError(AudioCLIError):
    """Raised when an audio file cannot be loaded."""


class SaveError(AudioCLIError):
    """Raised when an audio file cannot be written."""


class OpError(AudioCLIError):
    """Raised when an op fails on a given buffer."""
