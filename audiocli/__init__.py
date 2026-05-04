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

Library API
-----------

The same surface used by the Typer CLI is the surface a future desktop GUI
(or any other embedder) consumes directly. Heavy modules — numpy,
pedalboard, soundfile — are *not* imported at ``import audiocli`` time;
they only load when an op actually runs. Importing this package keeps
startup well under the 130 ms ``audiocli --help`` budget.

Typical library usage::

    import threading
    from audiocli import AudioBuffer, list_ops, run_per_file
    from audiocli.registry import get_op

    cancel = threading.Event()
    op = get_op("gain")
    events = []
    report = run_per_file(
        ["a.wav", "b.wav"],
        op,
        {"db": -3.0},
        output="out/",
        on_event=events.append,
        cancel_token=cancel,
    )

The structured event protocol (``start`` / ``progress`` / ``file_done`` /
``error`` / ``done``) is documented in :mod:`audiocli.events` and is the
secondary integration path for non-Python frontends that prefer to shell
out and parse newline-delimited JSON.
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
from audiocli.events import (
    DoneEvent,
    ErrorEvent,
    FileDoneEvent,
    ProgressEvent,
    StartEvent,
)
from audiocli.pipeline import (
    JobReport,
    Result,
    run_one,
    run_per_file,
)
from audiocli.registry import (
    Op,
    OpInfo,
    ParamInfo,
    all_ops,
    get_op,
    list_ops,
    op,
)
from audiocli.workers import default_workers

__all__ = [
    "AudioBuffer",
    "AudioCLIError",
    "ConfigError",
    "DoneEvent",
    "ErrorEvent",
    "FileDoneEvent",
    "JobReport",
    "LoadError",
    "Op",
    "OpError",
    "OpInfo",
    "ParamInfo",
    "PluginError",
    "ProgressEvent",
    "Result",
    "SaveError",
    "StartEvent",
    "all_ops",
    "default_workers",
    "get_op",
    "list_ops",
    "op",
    "run_one",
    "run_per_file",
]
__version__ = "2.0.0"
