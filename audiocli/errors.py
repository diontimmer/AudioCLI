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


class PluginError(AudioCLIError):
    """Raised when a third-party plugin fails to register.

    Surfaced at startup (during entry-point discovery), not at op-invocation
    time, so plugin authors find signature or import errors as soon as the
    user runs ``audiocli``.
    """


class ConfigError(AudioCLIError):
    """Raised when persisted settings cannot be parsed or migrated.

    Covers malformed JSON, missing required fields, and unknown ``schema``
    versions. The CLI surfaces this with the offending file path so users
    know which file to delete or fix.
    """
