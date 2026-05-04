from __future__ import annotations

from pathlib import Path

from audiocli.destinations import resolve_output


def test_resolve_output_default_names_file_after_op() -> None:
    assert resolve_output(Path("/tmp/song.wav"), None, "gain") == Path("/tmp/song_gain.wav")


def test_resolve_output_existing_directory_keeps_source_name(tmp_path) -> None:
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    assert resolve_output(Path("song.wav"), out_dir, "gain") == out_dir / "song.wav"


def test_resolve_output_suffixless_path_creates_directory(tmp_path) -> None:
    out_dir = tmp_path / "new-out"

    assert resolve_output(Path("song.wav"), out_dir, "gain") == out_dir / "song.wav"
    assert out_dir.is_dir()


def test_resolve_output_suffix_path_is_exact_file(tmp_path) -> None:
    out_file = tmp_path / "custom.flac"

    assert resolve_output(Path("song.wav"), out_file, "gain") == out_file
