"""Issue 07 analysis capability node tests."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from audiocli.buffer import AudioBuffer
from audiocli.capabilities import get_capability, list_capabilities
from audiocli.chains import CapabilityChain
from audiocli.errors import AudioCLIError
from audiocli.gui_service import execute_file_chain, prepare_file_chain_execution
from audiocli.io import load, save


def _write_tone(path: Path, *, sr: int = 44100, seconds: float = 0.6) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    t = np.arange(int(sr * seconds), dtype=np.float32) / sr
    data = (0.25 * np.sin(2 * np.pi * 440.0 * t))[None, :].astype(np.float32)
    save(path, AudioBuffer(data=data, sr=sr, subtype="PCM_16"))
    return path


def _write_silence(path: Path, *, sr: int = 44100, seconds: float = 0.6) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = np.zeros((1, int(sr * seconds)), dtype=np.float32)
    save(path, AudioBuffer(data=data, sr=sr, subtype="PCM_16"))
    return path


def _write_garbage(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"NOTAWAV" + b"\x00" * 64)
    return path


def test_info_analysis_capability_is_discoverable_with_explicit_pass_through_metadata():
    capability = get_capability("builtin.analysis.info")
    discovered = {cap.id: cap for cap in list_capabilities()}

    assert discovered[capability.id] == capability
    assert capability.type == "analysis"
    assert capability.operation_name == "info"
    assert capability.input_shape.kind == "audio_buffer"
    assert capability.output_shape.kind == "audio_buffer"
    assert capability.safety.classification == "analysis"
    assert capability.defaults["pass_through"] is True
    assert capability.metadata["metadata_output"] is True
    assert capability.metadata["metadata_shape"]["kind"] == "metadata"

    params = {param.name: param for param in capability.parameters}
    assert params["pass_through"].type == "bool"
    assert params["pass_through"].default is True
    assert params["pass_through"].control_hint == "checkbox"
    assert capability.validate_params({"pass_through": "false"}).values == {"pass_through": False}
    json.dumps(capability.to_view_model(), allow_nan=False)


def test_info_analysis_execution_returns_structured_metadata_and_events(tmp_path):
    src = _write_tone(tmp_path / "tone.wav")
    events: list[dict] = []
    chain = CapabilityChain(name="Analyze")
    chain.add_node("builtin.analysis.info", node_id="info")

    run = execute_file_chain(chain, [src], on_event=events.append)

    assert run.ok_count == 1
    result = run.report.results[0]
    assert result.path == src
    assert result.output_path == src
    assert len(result.analysis_results) == 1
    analysis = result.analysis_results[0]
    assert analysis.ok is True
    assert analysis.step.capability_id == "builtin.analysis.info"
    assert analysis.path == src
    assert analysis.metadata["path"] == str(src)
    assert analysis.metadata["sr"] == 44100
    assert analysis.metadata["channels"] == 1
    assert analysis.metadata["duration_s"] == pytest.approx(0.6)
    assert isinstance(analysis.metadata["peak_dbfs"], float)
    assert isinstance(analysis.metadata["rms_dbfs"], float)

    view_model = run.to_view_model()
    json.dumps(view_model, allow_nan=False)
    assert view_model["report"]["results"][0]["analysis_results"][0]["metadata"]["sr"] == 44100
    node_done = [event for event in events if event["type"] == "node_done"][-1]
    assert node_done["metadata"]["path"] == str(src)


def test_silent_info_analysis_reports_level_floor_and_lufs_none(tmp_path):
    src = _write_silence(tmp_path / "silent.wav")
    chain = CapabilityChain(name="Analyze silence")
    chain.add_node("builtin.analysis.info", node_id="info")

    run = execute_file_chain(chain, [src])

    metadata = run.report.results[0].analysis_results[0].metadata
    assert metadata["peak_dbfs"] == -200.0
    assert metadata["rms_dbfs"] == -200.0
    assert metadata["lufs"] is None
    json.dumps(metadata, allow_nan=False)


def test_analysis_pass_through_allows_downstream_audio_node(tmp_path):
    src = _write_tone(tmp_path / "tone.wav")
    out_dir = tmp_path / "out"
    chain = CapabilityChain(name="Analyze then gain")
    chain.add_node("builtin.analysis.info", {"pass_through": True}, node_id="info")
    chain.add_node("builtin.filter.gain", {"db": -3}, node_id="gain")

    preparation = prepare_file_chain_execution(chain, [src], output_policy={"output": out_dir})
    run = execute_file_chain(chain, [src], output_policy={"output": out_dir})

    produced = out_dir / "tone.wav"
    assert preparation.validation is not None and preparation.validation.valid is True
    assert run.ok_count == 1
    assert produced.exists()
    assert run.report.results[0].path == produced
    assert load(produced).sr == load(src).sr
    assert run.report.results[0].analysis_results[0].metadata["path"] == str(src)


def test_analysis_pass_through_false_rejects_downstream_audio_node():
    chain = CapabilityChain(name="Metadata stops audio")
    chain.add_node("builtin.analysis.info", {"pass_through": False}, node_id="info")
    chain.add_node("builtin.filter.gain", {"db": 1}, node_id="gain")

    validation = chain.validate()

    assert validation.valid is False
    assert len(validation.errors) == 1
    error = validation.errors[0]
    assert error.code == "incompatible_shapes"
    assert error.source_node_id == "info"
    assert error.node_id == "gain"
    assert "metadata" in error.message
    assert "audio_buffer" in error.message
    with pytest.raises(AudioCLIError, match="invalid chain: incompatible_shapes"):
        prepare_file_chain_execution(chain, [])


def test_analysis_failures_are_reported_per_file_without_stopping_unrelated_files(tmp_path):
    good = _write_tone(tmp_path / "src" / "good.wav")
    bad = _write_garbage(tmp_path / "src" / "bad.wav")
    chain = CapabilityChain(name="Analyze batch")
    chain.add_node("builtin.analysis.info", node_id="info")

    run = execute_file_chain(chain, [tmp_path / "src"])

    by_source = {result.source_path: result for result in run.report.results}
    assert run.ok_count == 1
    assert run.failed_count == 1
    assert by_source[good].ok is True
    assert by_source[good].analysis_results[0].metadata["sr"] == 44100
    assert by_source[bad].ok is False
    assert by_source[bad].failed_step_index == 1
    assert by_source[bad].analysis_results[0].ok is False
    assert "step 1 (info) failed" in (by_source[bad].error or "")
