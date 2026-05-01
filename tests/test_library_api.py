"""Library-facing public surface — issue #14.

A future desktop GUI (PySide6/Qt) will consume the same library the CLI
uses. These tests pin the public import surface so it doesn't drift, and
exercise the secondary integration path (an external ``on_event``
callback collecting structured events) end-to-end.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

import audiocli
from audiocli import (
    AudioBuffer,
    AudioCLIError,
    ConfigError,
    DoneEvent,
    ErrorEvent,
    FileDoneEvent,
    JobReport,
    LoadError,
    Op,
    OpError,
    OpInfo,
    ParamInfo,
    PluginError,
    ProgressEvent,
    Result,
    SaveError,
    StartEvent,
    get_op,
    list_ops,
    op,
    run_one,
    run_per_file,
)
from audiocli.io import save


def _write_synth(path: Path) -> None:
    sr = 22050
    t = np.linspace(0, 1, sr, dtype=np.float32)
    data = (np.sin(2 * np.pi * 440 * t) * 0.1).astype(np.float32)[None, :]
    save(path, AudioBuffer(data=data, sr=sr, subtype="PCM_16"))


def test_imports_all_public_symbols():
    """Every documented public symbol is importable from the package root."""
    expected = {
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
        "get_op",
        "list_ops",
        "op",
        "run_one",
        "run_per_file",
    }
    # Each name resolves to a non-None object.
    for name in expected:
        assert getattr(audiocli, name, None) is not None, name
    # And they're advertised in __all__ so star-imports work.
    assert expected.issubset(set(audiocli.__all__))


def test_imports_are_the_objects_we_documented():
    """Quick sanity that re-exports refer to the canonical implementations."""
    from audiocli import errors as _errors
    from audiocli import events as _events
    from audiocli import pipeline as _pipeline
    from audiocli import registry as _registry

    assert AudioCLIError is _errors.AudioCLIError
    assert PluginError is _errors.PluginError
    assert ConfigError is _errors.ConfigError
    assert LoadError is _errors.LoadError
    assert SaveError is _errors.SaveError
    assert OpError is _errors.OpError
    assert StartEvent is _events.StartEvent
    assert ProgressEvent is _events.ProgressEvent
    assert FileDoneEvent is _events.FileDoneEvent
    assert ErrorEvent is _events.ErrorEvent
    assert DoneEvent is _events.DoneEvent
    assert run_per_file is _pipeline.run_per_file
    assert run_one is _pipeline.run_one
    assert JobReport is _pipeline.JobReport
    assert Result is _pipeline.Result
    assert Op is _registry.Op
    assert OpInfo is _registry.OpInfo
    assert ParamInfo is _registry.ParamInfo
    assert op is _registry.op
    assert list_ops is _registry.list_ops
    assert get_op is _registry.get_op


def test_integration_smoke_run_per_file_with_event_callback(tmp_path):
    """3-file batch via ``run_per_file`` with a custom ``on_event`` collector."""
    files = []
    for i in range(3):
        p = tmp_path / f"in_{i}.wav"
        _write_synth(p)
        files.append(p)

    events: list[dict] = []
    out_dir = tmp_path / "out"
    report = run_per_file(
        files,
        get_op("gain"),
        {"db": 0.0},
        output=out_dir,
        on_event=events.append,
    )

    assert report.ok_count == 3
    assert report.failed_count == 0
    types = [e["type"] for e in events]
    assert types[0] == "start"
    assert types[-1] == "done"
    # One file_done per input.
    assert types.count("file_done") == 3
