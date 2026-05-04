"""Issue 05 multi-step file-based chain execution output mode tests."""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import pytest

from audiocli.chains import CapabilityChain
from audiocli.errors import AudioCLIError
from audiocli.gui_service import (
    DestructiveConfirmation,
    execute_file_chain,
    prepare_file_chain_execution,
    preview_chain_output_paths,
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


def _two_step_chain() -> CapabilityChain:
    chain = CapabilityChain(name="HP then gain")
    chain.add_node("builtin.filter.highpass", {"hz": 120}, node_id="hp")
    chain.add_node("builtin.filter.gain", {"db": -3}, node_id="gain")
    return chain


def _convert_chain(fmt: str) -> CapabilityChain:
    chain = CapabilityChain(name=f"Convert to {fmt}")
    chain.add_node("builtin.filter.convert", {"format": fmt}, node_id="convert")
    return chain


def _chunk_chain(*, seconds: float = 10.0, pad: bool = True) -> CapabilityChain:
    chain = CapabilityChain(name="Chunk")
    chain.add_node(
        "builtin.multi_output.chunk",
        {"seconds": seconds, "pad": pad},
        node_id="chunk",
    )
    return chain


def _chunk_then_gain_chain(*, seconds: float = 10.0, pad: bool = False) -> CapabilityChain:
    chain = _chunk_chain(seconds=seconds, pad=pad)
    chain.name = "Chunk then gain"
    chain.add_node("builtin.filter.gain", {"db": 0.0}, node_id="gain")
    return chain


def _chain_temp_dirs_for(source: Path) -> set[Path]:
    return set(Path(tempfile.gettempdir()).glob(f"audiocli-chain-{source.stem}-*"))


def test_multi_step_chain_executes_real_files_final_only_and_cleans_temp(tmp_path):
    src = _copy_song(tmp_path / "src" / "song.wav")
    out_dir = tmp_path / "out"

    run = execute_file_chain(_two_step_chain(), [src], output_policy={"output": out_dir})

    produced = out_dir / "song.wav"
    assert run.ok_count == 1
    assert run.failed_count == 0
    assert run.report.results[0].path == produced
    assert produced.exists()
    assert load(produced).sr == load(src).sr
    assert run.report.results[0].intermediates
    assert all(not artifact.path.exists() for artifact in run.report.results[0].intermediates)
    assert not list(out_dir.glob("**/.audiocli-intermediates"))


def test_chunk_chain_final_outputs_are_expanded_padded_file_set(tmp_path):
    src = _copy_song(tmp_path / "song.wav")
    out_dir = tmp_path / "chunks"

    run = execute_file_chain(
        _chunk_chain(seconds=10.0, pad=True), [src], output_policy={"output": out_dir}
    )

    result = run.report.results[0]
    chunks = sorted(out_dir.glob("song_*.wav"))
    assert run.ok_count == 1
    assert run.failed_count == 0
    assert len(chunks) == 4
    assert result.path == chunks[0]
    assert result.output_paths == chunks
    assert result.current_files == chunks
    assert result.expanded_output_files == chunks
    assert result.step_file_sets[0].behavior == "expand_one_to_many"
    assert result.step_file_sets[0].output_paths == chunks
    assert [load(path).data.shape[1] for path in chunks] == [441000] * 4


def test_chunk_chain_no_pad_preserves_short_final_chunk(tmp_path):
    src = _copy_song(tmp_path / "song.wav")
    out_dir = tmp_path / "chunks"

    run = execute_file_chain(
        _chunk_chain(seconds=10.0, pad=False), [src], output_policy={"output": out_dir}
    )

    chunks = sorted(out_dir.glob("song_*.wav"))
    lengths = [load(path).data.shape[1] for path in chunks]
    assert run.ok_count == 1
    assert len(chunks) == 4
    assert lengths[:3] == [441000, 441000, 441000]
    assert 0 < lengths[-1] < 441000


def test_chunk_then_filter_maps_downstream_over_expanded_file_set(tmp_path):
    src = _copy_song(tmp_path / "song.wav")
    out_dir = tmp_path / "out"
    chain = _chunk_then_gain_chain(seconds=10.0, pad=False)

    preparation = prepare_file_chain_execution(chain, [src], output_policy={"output": out_dir})
    run = execute_file_chain(chain, [src], output_policy={"output": out_dir})

    result = run.report.results[0]
    final_files = sorted(out_dir.glob("song_*.wav"))
    assert preparation.validation is not None
    assert preparation.validation.collection_mappings[0].behavior == "map_each_file"
    assert run.ok_count == 1
    assert len(final_files) == 4
    assert result.output_paths == final_files
    assert result.step_file_sets[0].behavior == "expand_one_to_many"
    assert result.step_file_sets[1].behavior == "map_each_file"
    assert result.step_file_sets[1].input_paths == result.step_file_sets[0].output_paths
    assert result.step_file_sets[1].output_paths == final_files
    assert all(path.exists() for path in final_files)
    assert all(not artifact.path.exists() for artifact in result.intermediates)


def test_chunk_chain_reports_bad_source_without_stopping_other_files(tmp_path):
    src_dir = tmp_path / "src"
    good = _copy_song(src_dir / "good.wav")
    bad = _write_garbage(src_dir / "bad.wav")
    out_dir = tmp_path / "chunks"

    run = execute_file_chain(
        _chunk_chain(seconds=10.0, pad=False), [src_dir], output_policy={"output": out_dir}
    )

    assert run.ok_count == 1
    assert run.failed_count == 1
    assert len(sorted(out_dir.glob("good_*.wav"))) == 4
    assert not sorted(out_dir.glob("bad_*.wav"))
    failure = run.report.failures[0]
    assert failure.source_path == bad
    assert failure.failed_step_index == 1
    assert failure.failed_step is not None
    assert failure.failed_step.operation_name == "chunk"
    assert "chunk" in (failure.error or "")
    assert {result.source_path for result in run.report.results} == {good, bad}


def test_chunk_chain_rejects_invalid_seconds_before_execution(tmp_path):
    src = _copy_song(tmp_path / "song.wav")
    out_dir = tmp_path / "chunks"

    with pytest.raises(AudioCLIError, match="below_minimum"):
        execute_file_chain(
            _chunk_chain(seconds=0.0, pad=True), [src], output_policy={"output": out_dir}
        )

    assert not out_dir.exists()


def test_keep_intermediates_preserves_predictable_step_artifacts(tmp_path):
    src = _copy_song(tmp_path / "song.wav")
    out_dir = tmp_path / "out"

    run = execute_file_chain(
        _two_step_chain(),
        [src],
        output_policy={"mode": "keep_intermediates", "output": out_dir},
    )

    produced = out_dir / "song.wav"
    step_one = out_dir / ".audiocli-intermediates" / "step-01-highpass" / "song.wav"
    assert run.failed_count == 0
    assert produced.exists()
    assert step_one.exists()
    assert run.report.results[0].intermediates[0].path == step_one
    assert load(step_one).sr == load(src).sr


def test_destructive_mode_refuses_without_explicit_confirmation(tmp_path):
    src = _copy_song(tmp_path / "song.wav")

    with pytest.raises(AudioCLIError, match="destructive.*confirmation"):
        prepare_file_chain_execution(
            _two_step_chain(),
            [src],
            output_policy={"mode": "destructive"},
        )

    with pytest.raises(AudioCLIError, match="destructive.*confirmation"):
        execute_file_chain(
            _two_step_chain(),
            [src],
            output_policy={"mode": "destructive"},
        )


def test_destructive_mode_executes_in_place_with_confirmation(tmp_path):
    src = _copy_song(tmp_path / "song.wav")
    before = src.stat().st_mtime_ns

    run = execute_file_chain(
        _two_step_chain(),
        [src],
        output_policy={"mode": "destructive"},
        destructive_confirmation=DestructiveConfirmation(confirmed=True, affected_paths=[src]),
    )

    assert run.ok_count == 1
    assert run.report.results[0].path == src
    assert src.exists()
    assert src.stat().st_mtime_ns >= before
    assert load(src).sr == load(DATA).sr


def test_destructive_mode_cleans_managed_temp_intermediates(tmp_path):
    src = _copy_song(tmp_path / "issue05_destructive_leak.wav")
    before_temp_dirs = _chain_temp_dirs_for(src)

    run = execute_file_chain(
        _two_step_chain(),
        [src],
        output_policy={"mode": "destructive"},
        destructive_confirmation=DestructiveConfirmation(confirmed=True, affected_paths=[src]),
    )

    result = run.report.results[0]
    assert run.ok_count == 1
    assert result.path == src
    assert result.preserved_context_dir is None
    assert result.intermediates
    assert all(not artifact.path.exists() for artifact in result.intermediates)
    assert _chain_temp_dirs_for(src) == before_temp_dirs


def test_destructive_mode_rejects_format_changing_final_step_before_mutation(tmp_path):
    src = _copy_song(tmp_path / "song.wav")
    flac_path = tmp_path / "song.flac"
    before_bytes = src.read_bytes()
    chain = _convert_chain("flac")
    confirmation = DestructiveConfirmation(confirmed=True, affected_paths=[src])
    match = "destructive.*format-changing final step"

    with pytest.raises(AudioCLIError, match=match):
        prepare_file_chain_execution(
            chain,
            [src],
            output_policy={"mode": "destructive"},
            destructive_confirmation=confirmation,
        )

    with pytest.raises(AudioCLIError, match=match):
        preview_chain_output_paths(
            [src],
            chain.to_execution_plan(validate=True),
            output_policy={"mode": "destructive"},
            destructive_confirmation=confirmation,
        )

    with pytest.raises(AudioCLIError, match=match):
        execute_file_chain(
            chain,
            [src],
            output_policy={"mode": "destructive"},
            destructive_confirmation=confirmation,
        )

    assert src.exists()
    assert src.read_bytes() == before_bytes
    assert not flac_path.exists()


def test_destructive_mode_allows_convert_to_same_source_extension(tmp_path):
    src = _copy_song(tmp_path / "song.wav")
    chain = _convert_chain("wav")
    confirmation = DestructiveConfirmation(confirmed=True, affected_paths=[src])

    preparation = prepare_file_chain_execution(
        chain,
        [src],
        output_policy={"mode": "destructive"},
        destructive_confirmation=confirmation,
    )
    run = execute_file_chain(
        chain,
        [src],
        output_policy={"mode": "destructive"},
        destructive_confirmation=confirmation,
    )

    assert preparation.output_preview[0].output_path == src
    assert run.ok_count == 1
    assert run.report.results[0].path == src
    assert src.exists()
    assert load(src).format == "wav"
    assert not (tmp_path / "song_convert.wav").exists()


def test_destructive_confirmation_affected_path_validation_still_runs(tmp_path):
    src = _copy_song(tmp_path / "song.wav")
    other = tmp_path / "other.wav"

    with pytest.raises(AudioCLIError, match="confirmation does not cover"):
        prepare_file_chain_execution(
            _convert_chain("flac"),
            [src],
            output_policy={"mode": "destructive"},
            destructive_confirmation=DestructiveConfirmation(
                confirmed=True, affected_paths=[other]
            ),
        )

    assert src.exists()
    assert not (tmp_path / "song.flac").exists()


def test_prepare_and_preview_reject_multi_target_exact_output_file(tmp_path):
    first = _copy_song(tmp_path / "first.wav")
    second = _copy_song(tmp_path / "second.wav")
    exact_output = tmp_path / "combined.wav"
    chain = _two_step_chain()
    plan = chain.to_execution_plan(validate=True)
    match = "exact output file.*multiple targets"

    with pytest.raises(AudioCLIError, match=match):
        prepare_file_chain_execution(chain, [first, second], output_policy={"output": exact_output})

    with pytest.raises(AudioCLIError, match=match):
        preview_chain_output_paths([first, second], plan, output_policy={"output": exact_output})

    assert not exact_output.exists()


def test_execute_rejects_multi_target_exact_output_file_before_execution(tmp_path):
    first = _copy_song(tmp_path / "first.wav")
    second = _copy_song(tmp_path / "second.wav")
    exact_output = tmp_path / "combined.wav"
    before_mtimes = {path: path.stat().st_mtime_ns for path in (first, second)}

    with pytest.raises(AudioCLIError, match="exact output file.*multiple targets"):
        execute_file_chain(
            _two_step_chain(), [first, second], output_policy={"output": exact_output}
        )

    assert not exact_output.exists()
    assert {path: path.stat().st_mtime_ns for path in (first, second)} == before_mtimes


def test_partial_failure_reports_failed_step_and_preserves_context(tmp_path):
    src_dir = tmp_path / "src"
    good = _copy_song(src_dir / "good.wav")
    bad = _write_garbage(src_dir / "bad.wav")
    out_dir = tmp_path / "out"

    run = execute_file_chain(_two_step_chain(), [src_dir], output_policy={"output": out_dir})

    assert run.ok_count == 1
    assert run.failed_count == 1
    assert (out_dir / "good.wav").exists()
    assert not (out_dir / "bad.wav").exists()
    failure = run.report.failures[0]
    assert failure.source_path == bad
    assert failure.failed_step_index == 1
    assert "highpass" in (failure.error or "")
    assert failure.preserved_context_dir is not None
    assert failure.preserved_context_dir.exists()
    assert {preview.source_path for preview in run.preparation.output_preview} == {good, bad}
