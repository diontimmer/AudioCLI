"""AudioCLI v2 — pedalboard-powered batch audio power-tool.

Public surface for plugin authors and library users:

    from audiocli import op, AudioBuffer
"""

from audiocli.buffer import AudioBuffer
from audiocli.errors import AudioCLIError, LoadError, OpError, SaveError
from audiocli.registry import Op, op

__all__ = [
    "AudioBuffer",
    "AudioCLIError",
    "LoadError",
    "Op",
    "OpError",
    "SaveError",
    "op",
]
__version__ = "2.0.0a0"
