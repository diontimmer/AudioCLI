"""Tests for the GUI VST/AU editor helper process."""

from __future__ import annotations

import io
import json
import sys
from types import SimpleNamespace

from audiocli.gui.vst_host import (
    apply_initial_params,
    run_host,
    serialize_parameter_snapshot,
)


class _FakeParamMeta:
    def __init__(self, declared_type, *, valid_values=None, label="") -> None:
        self.type = declared_type
        self.label = label
        if valid_values is not None:
            self.valid_values = valid_values


class _FakeEditorPlugin:
    def __init__(self) -> None:
        self.gain = 1.0
        self.enabled = True
        self.mode = "Soft"
        self.parameters = {
            "gain": _FakeParamMeta(float, label="dB"),
            "enabled": _FakeParamMeta(bool),
            "mode": _FakeParamMeta(str, valid_values=["Soft", "Hard"]),
        }

    def show_editor(self, _close_event) -> None:
        self.gain = 2.5


def test_apply_initial_params_and_serialize_snapshot() -> None:
    plugin = _FakeEditorPlugin()

    apply_initial_params(plugin, ["gain=2.0", "enabled=false", "mode=Hard"])
    snapshot = serialize_parameter_snapshot(plugin)

    assert plugin.gain == 2.0
    assert plugin.enabled is False
    assert plugin.mode == "Hard"
    assert {
        "key": "mode",
        "display_name": "mode",
        "value": "Hard",
        "raw_value": "Hard",
        "type": "str",
        "label": "",
        "choices": ["Soft", "Hard"],
    } in snapshot


def test_run_host_emits_final_close_snapshot(tmp_path, monkeypatch) -> None:
    plugin_path = tmp_path / "effect.vst3"
    plugin_path.write_text("", encoding="utf-8")
    plugin = _FakeEditorPlugin()
    monkeypatch.setitem(
        sys.modules,
        "pedalboard",
        SimpleNamespace(load_plugin=lambda _path: plugin),
    )
    stdin = io.StringIO(
        json.dumps({"type": "open", "plugin_path": str(plugin_path), "params": ["gain=1.5"]}) + "\n"
    )
    stdout = io.StringIO()

    exit_code = run_host(stdin, stdout)

    assert exit_code == 0
    events = [json.loads(line) for line in stdout.getvalue().splitlines()]
    assert [event["type"] for event in events] == [
        "loaded",
        "parameters",
        "parameters",
        "closed",
    ]
    assert events[-2]["parameters"][0]["key"] == "gain"
    assert events[-2]["parameters"][0]["value"] == 2.5
