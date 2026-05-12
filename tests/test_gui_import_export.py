from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
from typer.testing import CliRunner

from audiocli._shell import quote_arg
from audiocli.buffer import AudioBuffer
from audiocli.capabilities import get_capability, list_capabilities
from audiocli.chains import CapabilityChain
from audiocli.cli import app
from audiocli.gui.import_export import (
    ExportError,
    export_chain_to_acli,
    export_native_chain,
    import_acli_chain,
    import_native_chain,
)
from audiocli.gui.service import InMemoryWorkspaceService
from audiocli.gui.settings import GuiSettings
from audiocli.io import save


def _catalog():
    return {capability.id: capability for capability in list_capabilities()}


def _make_src(tmp_path: Path, name: str = "src.wav") -> Path:
    sr = 22050
    t = np.linspace(0, 1, sr, dtype=np.float32)
    buf = AudioBuffer(
        data=(np.sin(2 * np.pi * 440 * t) * 0.2).astype(np.float32)[None, :],
        sr=sr,
        subtype="PCM_16",
    )
    path = tmp_path / name
    save(path, buf)
    return path


def test_native_chain_import_export_round_trips_supported_metadata(tmp_path):
    catalog = _catalog()
    chain = CapabilityChain(
        id="chain-native-1",
        name="Native Round Trip",
        description="description survives",
        notes="chain notes survive",
        output_policy={"mode": "keep_intermediates", "suffix": "gui"},
        capability_catalog=catalog,
    )
    chain.add_node(
        "builtin.filter.gain",
        {"db": 2.5},
        node_id="gain-node",
        enabled=True,
        notes="node notes survive",
        output_policy={"output": "intermediate"},
    )
    chain.add_node(
        "builtin.filter.mono",
        {},
        node_id="mono-node",
        enabled=False,
        notes="disabled node survives",
    )

    export_result = export_native_chain(chain, tmp_path / "roundtrip.aclichain")
    import_result = import_native_chain(export_result.path, catalog)
    loaded = import_result.chain

    assert export_result.kind == "native"
    assert import_result.mode == "native"
    assert loaded.id == "chain-native-1"
    assert loaded.name == "Native Round Trip"
    assert loaded.description == "description survives"
    assert loaded.notes == "chain notes survive"
    assert loaded.output_policy == {"mode": "keep_intermediates", "suffix": "gui"}
    assert [node.id for node in loaded.nodes] == ["gain-node", "mono-node"]
    assert loaded.nodes[0].params == {"db": 2.5}
    assert loaded.nodes[0].enabled is True
    assert loaded.nodes[0].notes == "node notes survive"
    assert loaded.nodes[0].output_policy == {"output": "intermediate"}
    assert loaded.nodes[1].enabled is False
    assert loaded.nodes[1].notes == "disabled node survives"

    raw = json.loads(export_result.path.read_text())
    assert raw["kind"] == "audiocli.saved_chain"
    assert raw["nodes"][1]["enabled"] is False


def test_simple_gui_chain_exports_to_acli_with_executable_context(tmp_path):
    src = _make_src(tmp_path)
    out = tmp_path / "processed.wav"
    chain = CapabilityChain(name="Simple", capability_catalog=_catalog())
    chain.add_node("builtin.filter.gain", {"db": 3.5}, node_id="gain-1")

    result = export_chain_to_acli(
        chain,
        tmp_path / "simple.acli",
        targets=[src],
        output=out,
        recursive=False,
        workers=1,
    )

    # The export code shell-quotes every path so .acli scripts round-trip
    # cleanly through shells; on Windows that wraps the backslash-laden
    # tmp path in single quotes, on POSIX paths without metacharacters pass
    # through unchanged.
    expected = (
        f"gain --target {quote_arg(str(src))} --db 3.5 "
        f"--output {quote_arg(str(out))} --workers 1 --no-recursive"
    )
    assert result.kind == "acli"
    assert result.lines == [expected]
    assert result.path.read_text() == expected + "\n"

    run_result = CliRunner().invoke(app, ["run-script", str(result.path)])
    assert run_result.exit_code == 0, run_result.output
    assert out.exists()


def test_acli_export_without_targets_rejects_before_writing(tmp_path):
    chain = CapabilityChain(name="Missing targets", capability_catalog=_catalog())
    chain.add_node("builtin.filter.gain", {"db": 3.5}, node_id="gain-1")
    destination = tmp_path / "missing-target.acli"
    destination.write_text("existing script\n")

    with pytest.raises(ExportError) as exc_info:
        export_chain_to_acli(chain, destination, output=tmp_path / "processed.wav")

    assert "Target metadata cannot be represented" in str(exc_info.value)
    assert [issue.code for issue in exc_info.value.issues] == ["missing_target_context"]
    assert destination.read_text() == "existing script\n"


def test_multi_node_acli_export_rejects_unrepresentable_intermediates(tmp_path):
    src = _make_src(tmp_path)
    chain = CapabilityChain(name="Multi", capability_catalog=_catalog())
    chain.add_node("builtin.filter.gain", {"db": 3.5}, node_id="gain-1")
    chain.add_node("builtin.filter.mono", {}, node_id="mono-1")

    with pytest.raises(ExportError) as exc_info:
        export_chain_to_acli(chain, tmp_path / "multi.acli", targets=[src])

    assert "Multi-node managed chains" in str(exc_info.value)
    assert not (tmp_path / "multi.acli").exists()


def test_acli_import_wraps_unsupported_script_as_script_node(tmp_path):
    script = tmp_path / "unsafe.acli"
    script.write_text("shell echo hello\n")

    result = import_acli_chain(script)

    assert result.mode == "wrapped"
    assert "builtin.script.acli wrapper" in result.explanation
    assert len(result.chain.nodes) == 1
    assert result.chain.nodes[0].capability_id == "builtin.script.acli"
    assert result.chain.nodes[0].params["script_path"] == str(script)


def test_acli_import_converts_recognized_filter_commands(tmp_path):
    script = tmp_path / "filters.acli"
    script.write_text("# comment\ngain --db 2\nmono\n")

    result = import_acli_chain(script)

    assert result.mode == "converted"
    assert [node.capability_id for node in result.chain.nodes] == [
        "builtin.filter.gain",
        "builtin.filter.mono",
    ]
    assert result.chain.nodes[0].params == {"db": 2.0}


def test_unsupported_acli_export_explains_node_and_metadata(tmp_path):
    chain = CapabilityChain(
        name="Unsupported",
        description="cannot go to script metadata",
        capability_catalog=_catalog(),
    )
    chain.add_node(
        "builtin.analysis.info",
        get_capability("builtin.analysis.info").defaults,
        node_id="info-node",
    )

    with pytest.raises(ExportError) as exc_info:
        export_chain_to_acli(chain, tmp_path / "unsupported.acli", targets=[tmp_path / "input.wav"])

    message = str(exc_info.value)
    assert "description metadata" in message
    assert "info-node" in message
    assert "builtin.analysis.info" in message
    assert not (tmp_path / "unsupported.acli").exists()


def test_native_export_atomic_write_failure_preserves_existing_destination(tmp_path, monkeypatch):
    chain = CapabilityChain(name="Native", capability_catalog=_catalog())
    chain.add_node("builtin.filter.gain", {"db": 1.0}, node_id="gain-atomic")
    destination = tmp_path / "atomic.aclichain"
    destination.write_text("original native contents\n")

    def fail_replace(src, dst):
        raise OSError("simulated replace failure")

    monkeypatch.setattr("audiocli.chains.os.replace", fail_replace)

    with pytest.raises(OSError, match="simulated replace failure"):
        export_native_chain(chain, destination)

    assert destination.read_text() == "original native contents\n"


def test_acli_export_atomic_write_failure_preserves_existing_destination(tmp_path, monkeypatch):
    src = _make_src(tmp_path)
    chain = CapabilityChain(name="Script", capability_catalog=_catalog())
    chain.add_node("builtin.filter.gain", {"db": 1.0}, node_id="gain-atomic")
    destination = tmp_path / "atomic.acli"
    destination.write_text("original script contents\n")

    def fail_replace(src, dst):
        raise OSError("simulated replace failure")

    monkeypatch.setattr("audiocli.chains.os.replace", fail_replace)

    with pytest.raises(OSError, match="simulated replace failure"):
        export_chain_to_acli(chain, destination, targets=[src], output=tmp_path / "out.wav")

    assert destination.read_text() == "original script contents\n"


def test_workspace_service_exposes_import_export_methods(tmp_path):
    service = InMemoryWorkspaceService(settings=GuiSettings())
    service.chain.add_node("builtin.filter.gain", {"db": 1.0}, node_id="gain-service")

    native_result = service.export_current_chain_native(tmp_path / "service.aclichain")
    service.chain = CapabilityChain(name="Cleared", capability_catalog=service.capability_catalog)
    imported_native = service.import_native_chain(native_result.path)
    assert imported_native.chain.nodes[0].id == "gain-service"

    src = _make_src(tmp_path)
    out = tmp_path / "service-out.wav"
    service.set_targets([src])
    service.set_output_path(out)
    service.set_recursive(False)
    acli_result = service.export_current_chain_acli(tmp_path / "service.acli")
    expected = (
        f"gain --target {quote_arg(str(src))} --db 1.0 "
        f"--output {quote_arg(str(out))} --no-recursive"
    )
    assert acli_result.path.read_text() == expected + "\n"

    imported_script = service.import_acli_script_file(acli_result.path)
    assert imported_script.mode == "wrapped"
    assert service.chain.nodes[0].capability_id == "builtin.script.acli"
    assert any("Exported chain" in line for line in service.job.logs)
