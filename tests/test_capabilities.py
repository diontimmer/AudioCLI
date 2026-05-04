"""GUI capability-node service foundation."""

from __future__ import annotations

import json
import sys

import pytest

from audiocli.capabilities import (
    CapabilityNode,
    ValidationResult,
    list_capabilities,
    list_macro_capabilities,
    validate_capability_params,
)
from audiocli.chains import CapabilityChain, save_chain


def _capability_by_op_name() -> dict[str, CapabilityNode]:
    return {cap.operation_name: cap for cap in list_capabilities()}


def test_discovery_returns_real_builtin_filter_without_cli_adapter_import():
    sys.modules.pop("audiocli.cli", None)

    capabilities = list_capabilities()

    assert "audiocli.cli" not in sys.modules
    assert capabilities
    by_name = {cap.operation_name: cap for cap in capabilities}
    assert "highpass" in by_name
    assert by_name["highpass"].id == "builtin.filter.highpass"
    assert by_name["highpass"].type == "built_in_filter"


def test_builtin_filter_capability_exposes_ui_metadata_shape():
    highpass = _capability_by_op_name()["highpass"]

    assert highpass.display_name == "Highpass"
    assert highpass.description == "High-pass filter (pedalboard.HighpassFilter)."
    assert highpass.input_shape.kind == "audio_buffer"
    assert highpass.input_shape.cardinality == "single"
    assert highpass.output_shape.kind == "audio_buffer"
    assert highpass.output_shape.cardinality == "single"
    assert highpass.safety.classification == "pure_transform"
    assert highpass.safety.destructive is False
    assert highpass.safety.requires_confirmation is False
    assert highpass.defaults == {"hz": 100.0}
    assert highpass.validation_state.valid is True
    assert highpass.validation_state.errors == []

    params = {p.name: p for p in highpass.parameters}
    assert params["hz"].type == "float"
    assert params["hz"].display_name == "Hz"
    assert "Cutoff frequency" in params["hz"].description
    assert params["hz"].required is False
    assert params["hz"].default == 100.0
    assert params["hz"].control_hint == "number"
    assert params["hz"].choices == []


def test_builtin_constrained_parameters_expose_choices_in_view_model():
    capabilities = _capability_by_op_name()

    fade_shape = {p.name: p for p in capabilities["fade"].parameters}["shape"]
    assert fade_shape.type == "str"
    assert fade_shape.control_hint == "select"
    assert fade_shape.choices == ["linear", "exp", "cosine"]
    assert fade_shape.to_view_model()["choices"] == ["linear", "exp", "cosine"]

    convert_params = {p.name: p for p in capabilities["convert"].parameters}
    assert convert_params["format"].choices == ["wav", "flac", "mp3", "ogg"]
    assert convert_params["format"].control_hint == "select"
    assert convert_params["bitdepth"].choices == [8, 16, 24, 32]


def test_constrained_builtin_values_fail_validation_before_execution():
    cases = [
        ("builtin.filter.fade", {"shape": "triangle"}, "shape"),
        ("builtin.filter.convert", {"format": "xyz"}, "format"),
        ("builtin.filter.convert", {"format": "wav", "bitdepth": 12}, "bitdepth"),
    ]

    for capability_id, params, parameter in cases:
        result = validate_capability_params(capability_id, params)

        assert result.valid is False
        assert parameter not in result.values
        assert len(result.errors) == 1
        error = result.errors[0]
        assert error.parameter == parameter
        assert error.code == "invalid_choice"
        assert "must be one of" in error.message
        json.dumps(result.to_view_model(), allow_nan=False)


def test_convert_format_validation_matches_runtime_normalization():
    result = validate_capability_params("builtin.filter.convert", {"format": ".WAV"})

    assert result.valid is True
    assert result.errors == []
    assert result.values["format"] == "wav"


def test_chunk_capability_is_discoverable_multi_output_and_validates_seconds():
    capabilities = {cap.id: cap for cap in list_capabilities()}
    chunk = capabilities["builtin.multi_output.chunk"]

    assert chunk.type == "multi_output"
    assert chunk.operation_name == "chunk"
    assert chunk.input_shape.kind == "audio_buffer"
    assert chunk.input_shape.cardinality == "single"
    assert chunk.output_shape.kind == "audio_buffer"
    assert chunk.output_shape.cardinality == "many"
    assert chunk.defaults == {"pad": True}
    assert chunk.metadata["expands_file_set"] is True

    params = {p.name: p for p in chunk.parameters}
    assert params["seconds"].required is True
    assert params["seconds"].type == "float"
    assert params["seconds"].min_value == 0.0
    assert params["seconds"].min_exclusive is True
    assert params["pad"].default is True

    valid = validate_capability_params(
        "builtin.multi_output.chunk", {"seconds": "10", "pad": "false"}
    )
    assert valid.valid is True
    assert valid.values == {"seconds": 10.0, "pad": False}

    for bad_seconds in (0, 0.0, -1):
        invalid = validate_capability_params("builtin.multi_output.chunk", {"seconds": bad_seconds})
        assert invalid.valid is False
        assert invalid.errors[0].parameter == "seconds"
        assert invalid.errors[0].code == "below_minimum"


@pytest.mark.parametrize("value", ["nan", "inf", "-inf"])
def test_non_finite_float_input_reports_json_safe_structured_error(value: str):
    result = validate_capability_params("builtin.filter.highpass", {"hz": value})

    assert result.valid is False
    assert result.values == {}
    assert len(result.errors) == 1
    error = result.errors[0]
    assert error.parameter == "hz"
    assert error.code == "invalid_type"
    assert error.expected_type == "float"
    assert "finite float" in error.message
    json.dumps(result.to_view_model(), allow_nan=False)


def test_validation_result_view_model_is_strict_json_safe_for_valid_values():
    result = validate_capability_params("builtin.filter.highpass", {"hz": "250.5"})

    assert result.valid is True
    blob = json.dumps(result.to_view_model(), allow_nan=False)
    assert "250.5" in blob


def test_invalid_parameter_input_reports_structured_errors_before_execution():
    result = validate_capability_params("builtin.filter.highpass", {"hz": "not-a-number"})

    assert isinstance(result, ValidationResult)
    assert result.valid is False
    assert result.values == {}
    assert len(result.errors) == 1
    error = result.errors[0]
    assert error.parameter == "hz"
    assert error.code == "invalid_type"
    assert error.expected_type == "float"
    assert "not-a-number" in error.received


def test_required_parameter_validation_for_builtin_filter():
    result = validate_capability_params("builtin.filter.gain", {})

    assert result.valid is False
    assert result.errors[0].parameter == "db"
    assert result.errors[0].code == "missing_required"
    assert result.errors[0].expected_type == "float"


def test_valid_input_is_coerced_to_json_safe_values():
    highpass = _capability_by_op_name()["highpass"]

    result = highpass.validate_params({"hz": "250.5"})

    assert result.valid is True
    assert result.errors == []
    assert result.values == {"hz": 250.5}


def test_capability_view_model_is_json_serializable():
    highpass = _capability_by_op_name()["highpass"]
    view_model = highpass.to_view_model()

    blob = json.dumps(view_model)
    assert "builtin.filter.highpass" in blob
    assert view_model["type"] == "built_in_filter"
    assert view_model["input_shape"]["kind"] == "audio_buffer"
    assert view_model["parameters"][0]["default"] == 100.0
    assert view_model["validation_state"]["valid"] is True


def test_saved_chain_macro_discovery_exposes_native_files_as_capabilities(tmp_path):
    chain_path = tmp_path / "My Reusable Chain.aclichain"
    chain = CapabilityChain(
        id="macro-chain",
        name="Reusable Macro",
        description="A saved chain for reuse.",
    )
    chain.add_node("builtin.filter.highpass", {"hz": 100}, node_id="hp")
    save_chain(chain, chain_path)
    (tmp_path / "ignore.txt").write_text("not a chain")

    macros = list_macro_capabilities(tmp_path)
    all_capabilities = list_capabilities(chain_dir=tmp_path)

    assert len(macros) == 1
    macro = macros[0]
    assert macro in all_capabilities
    assert macro.id.startswith("saved.chain.my-reusable-chain.")
    assert macro.type == "saved_chain_macro"
    assert macro.display_name == "Reusable Macro"
    assert macro.description == "A saved chain for reuse."
    assert macro.input_shape.kind == "audio_buffer"
    assert macro.output_shape.kind == "audio_buffer"
    assert macro.defaults["path"] == str(chain_path.resolve())
    assert macro.defaults["chain_id"] == "macro-chain"
    assert macro.validate_params({}).valid is True
    assert macro.validate_params({}).values["path"] == str(chain_path.resolve())
