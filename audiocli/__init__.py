"""AudioCLI v2 — pedalboard-powered batch audio power-tool.

Public surface for plugin authors and library users:

    from audiocli import op, AudioBuffer

Plugin contract (v2.0): an op is a *filter*, i.e. a function with the shape

    @op(name="my-op", help="...")
    def my_op(buf: AudioBuffer, **params) -> AudioBuffer:
        ...

The first parameter must be the input ``AudioBuffer``; the return type must
be ``AudioBuffer`` (single-buffer output). Multi-output ops, analysis ops,
and side-effect ops are first-party-only special cases in v2.0; the plugin
contract may loosen in v2.1+ without breaking existing plugins.

Third-party packages register ops via Python entry-points::

    [project.entry-points."audiocli.ops"]
    my-op = "my_package.module:my_op"
"""

from audiocli.buffer import AudioBuffer
from audiocli.errors import (
    AudioCLIError,
    ConfigError,
    LoadError,
    OpError,
    PluginError,
    SaveError,
)
from audiocli.registry import Op, op

__all__ = [
    "AudioBuffer",
    "AudioCLIError",
    "ConfigError",
    "LoadError",
    "Op",
    "OpError",
    "PluginError",
    "SaveError",
    "op",
]
__version__ = "2.0.0a0"
