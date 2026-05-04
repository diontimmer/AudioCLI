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
from audiocli.capabilities import (
    CapabilityNode,
    CapabilityParameter,
    IOShape,
    SafetySemantics,
    ValidationError,
    ValidationResult,
    get_capability,
    list_capabilities,
    validate_capability_params,
)
from audiocli.chains import (
    CapabilityChain,
    ChainExecutionPlan,
    ChainExecutionStep,
    ChainModel,
    ChainNode,
    ChainValidationError,
    ChainValidationResult,
)
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
from audiocli.gui_service import (
    ChainEvent,
    ChainExecutionPreparation,
    ChainExecutionReport,
    ChainExecutionResult,
    ChainExecutionRun,
    ChainFileResult,
    ChainOutputPolicy,
    ChainOutputPreview,
    ChainRunReport,
    ChainStepArtifact,
    DestructiveConfirmation,
    FileChainExecutionPreparation,
    FileChainExecutionRun,
    OneNodeFilterChainPreparation,
    OneNodeFilterChainRun,
    build_one_node_filter_chain,
    execute_chain,
    execute_file_chain,
    execute_one_node_filter_chain,
    prepare_chain_execution,
    prepare_file_chain_execution,
    prepare_one_node_filter_chain,
    preview_chain_output_paths,
    preview_output_paths,
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
    "CapabilityNode",
    "CapabilityParameter",
    "CapabilityChain",
    "ChainEvent",
    "ChainFileResult",
    "ChainOutputPolicy",
    "ChainOutputPreview",
    "ChainRunReport",
    "ChainStepArtifact",
    "ChainExecutionPlan",
    "ChainExecutionPreparation",
    "ChainExecutionReport",
    "ChainExecutionResult",
    "ChainExecutionRun",
    "ChainExecutionStep",
    "ChainModel",
    "ChainNode",
    "ChainValidationError",
    "ChainValidationResult",
    "ConfigError",
    "DestructiveConfirmation",
    "DoneEvent",
    "ErrorEvent",
    "FileChainExecutionPreparation",
    "FileChainExecutionRun",
    "FileDoneEvent",
    "IOShape",
    "JobReport",
    "LoadError",
    "OneNodeFilterChainPreparation",
    "OneNodeFilterChainRun",
    "Op",
    "OpError",
    "OpInfo",
    "ParamInfo",
    "PluginError",
    "ProgressEvent",
    "Result",
    "SafetySemantics",
    "SaveError",
    "StartEvent",
    "ValidationError",
    "ValidationResult",
    "all_ops",
    "build_one_node_filter_chain",
    "default_workers",
    "execute_chain",
    "execute_file_chain",
    "execute_one_node_filter_chain",
    "get_capability",
    "get_op",
    "list_capabilities",
    "list_ops",
    "op",
    "prepare_chain_execution",
    "prepare_file_chain_execution",
    "prepare_one_node_filter_chain",
    "preview_chain_output_paths",
    "preview_output_paths",
    "run_one",
    "run_per_file",
    "validate_capability_params",
]
__version__ = "2.0.0"
