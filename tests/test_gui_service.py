"""GUI-neutral one-node chain execution service tests."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

from audiocli.capabilities import get_capability, list_capabilities
from audiocli.errors import AudioCLIError
from audiocli.gui_service import (
    build_one_node_filter_chain,
    execute_one_node_filter_chain,
    prepare_one_node_filter_chain,
)
from audiocli.io import load

DATA = Path(__file__).parent / "data" / "test_song.wav"


def _copy_song(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(DATA, path)
    return path


def _write_garbage(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"NOTAWAV" + b"\x00" * 64)
    return path


def test_build_prepare_previews_scanned_targets_without_importing_cli_or_creating_output_dir(
    tmp_path,
):
    sys.modules.pop("audiocli.cli", None)
    src_dir = tmp_path / "src"
    song = _copy_song(src_dir / "song.wav")
    (src_dir / "notes.txt").write_text("not audio")
    out_dir = tmp_path / "new-output-dir"

    discovered_gain = next(cap for cap in list_capabilities() if cap.operation_name == "gain")
    chain = build_one_node_filter_chain(
        discovered_gain,
        {"db": "0"},
        chain_id="chain-gain",
        chain_name="Gain Chain",
        node_id="gain-node",
    )

    preparation = prepare_one_node_filter_chain(chain, [src_dir], output=out_dir)

    assert preparation.chain_id == "chain-gain"
    assert preparation.chain_name == "Gain Chain"
    assert preparation.step.operation_name == "gain"
    assert preparation.step.params == {"db": 0.0}
    assert preparation.targets == [song]
    assert preparation.output_preview[0].source_path == song
    assert preparation.output_preview[0].output_path == out_dir / "song.wav"
    assert preparation.to_view_model()["target_count"] == 1
    assert not out_dir.exists(), "preview must not create destination directories"
    assert "audiocli.cli" not in sys.modules


def test_prepare_convert_preview_matches_pipeline_format_extension_rewrite(tmp_path):
    src = _copy_song(tmp_path / "song.wav")
    out_dir = tmp_path / "converted"
    convert_capability = get_capability("builtin.filter.convert")
    chain = build_one_node_filter_chain(convert_capability, {"format": "FLAC"})

    preparation = prepare_one_node_filter_chain(chain, [src], output=out_dir)

    assert preparation.step.params["format"] == "flac"
    assert preparation.output_preview[0].output_path == out_dir / "song.flac"
    assert not out_dir.exists()


def test_bitdepth_preview_and_execution_rewrite_exact_output_to_source_format(tmp_path):
    requested = tmp_path / "custom.flac"
    expected = tmp_path / "custom.wav"
    chain = build_one_node_filter_chain("builtin.filter.bitdepth", {"bits": 16})

    preparation = prepare_one_node_filter_chain(chain, [DATA], output=requested)

    assert preparation.output_preview[0].source_path == DATA
    assert preparation.output_preview[0].output_path == expected
    assert not requested.exists()
    assert not expected.exists()

    run = execute_one_node_filter_chain(chain, [DATA], output=requested, workers=1)

    assert run.failed_count == 0
    assert run.preparation.output_preview[0].output_path == expected
    assert run.report.results[0].path == expected
    assert expected.exists()
    assert not requested.exists()
    assert load(expected).format == "wav"


def test_prepare_preview_rejects_existing_suffixless_output_file(tmp_path):
    src = _copy_song(tmp_path / "song.wav")
    out_file = tmp_path / "output"
    out_file.write_text("already a file")
    chain = build_one_node_filter_chain("builtin.filter.gain", {"db": 0})

    with pytest.raises(FileExistsError) as error:
        prepare_one_node_filter_chain(chain, [src], output=out_file)

    assert error.value.filename == str(out_file)
    assert out_file.is_file()


def test_execute_one_node_filter_chain_produces_real_output_and_report(tmp_path):
    src = _copy_song(tmp_path / "song.wav")
    out_dir = tmp_path / "out"
    chain = build_one_node_filter_chain("builtin.filter.gain", {"db": 0})

    run = execute_one_node_filter_chain(chain, [src], output=out_dir, workers=1)

    produced = out_dir / "song.wav"
    assert run.ok_count == 1
    assert run.failed_count == 0
    assert run.exit_code == 0
    assert run.preparation.targets == [src]
    assert run.preparation.output_preview[0].output_path == produced
    assert run.report.results[0].path == produced
    assert produced.exists()
    assert load(produced).sr == load(src).sr
    assert run.to_view_model()["report"]["ok_count"] == 1


def test_execute_reports_bad_file_without_stopping_unrelated_good_file(tmp_path):
    src_dir = tmp_path / "src"
    good = _copy_song(src_dir / "good.wav")
    bad = _write_garbage(src_dir / "bad.wav")
    out_dir = tmp_path / "out"
    chain = build_one_node_filter_chain("builtin.filter.gain", {"db": 0})

    run = execute_one_node_filter_chain(chain, [src_dir], output=out_dir, workers=2)

    assert run.ok_count == 1
    assert run.failed_count == 1
    assert run.exit_code == 1
    assert (out_dir / "good.wav").exists()
    assert not (out_dir / "bad.wav").exists()
    failures = run.report.failures
    assert len(failures) == 1
    assert failures[0].path == bad
    assert failures[0].error
    assert {preview.source_path for preview in run.preparation.output_preview} == {good, bad}


def test_execute_rejects_invalid_or_multi_node_chain_before_pipeline(tmp_path):
    src = _copy_song(tmp_path / "song.wav")
    invalid = build_one_node_filter_chain("builtin.filter.gain", {})

    with pytest.raises(AudioCLIError, match="invalid chain: missing_required"):
        execute_one_node_filter_chain(invalid, [src], workers=1)

    multi = build_one_node_filter_chain("builtin.filter.gain", {"db": 0})
    multi.add_node("builtin.filter.highpass", {"hz": 120}, node_id="hp")

    with pytest.raises(AudioCLIError, match="exactly one enabled node"):
        execute_one_node_filter_chain(multi, [src], workers=1)
