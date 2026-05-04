from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from audiocli.destinations import resolve_output, resolve_output_preview


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


def test_resolve_output_parallel_suffixless_directory_is_idempotent(tmp_path) -> None:
    out_dir = tmp_path / "new-out"
    sources = [Path(f"song_{i}.wav") for i in range(16)]

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(lambda src: resolve_output(src, out_dir, "gain"), sources))

    assert results == [out_dir / src.name for src in sources]
    assert out_dir.is_dir()


def test_resolve_output_suffixless_path_tolerates_concurrent_directory_creation(
    tmp_path,
    monkeypatch,
) -> None:
    out_dir = tmp_path / "new-out"
    real_exists = Path.exists
    calls = {"count": 0}

    def racing_exists(path: Path) -> bool:
        if path == out_dir:
            calls["count"] += 1
            if calls["count"] == 1:
                return False
            out_dir.mkdir(parents=True, exist_ok=True)
            return True
        return real_exists(path)

    monkeypatch.setattr(Path, "exists", racing_exists)

    assert resolve_output(Path("song.wav"), out_dir, "gain") == out_dir / "song.wav"
    assert out_dir.is_dir()


def test_resolve_output_suffixless_path_detects_file_after_mkdir_attempt(
    tmp_path,
    monkeypatch,
) -> None:
    out_file = tmp_path / "output"
    real_mkdir = Path.mkdir

    def racing_mkdir(
        path: Path,
        mode: int = 0o777,
        parents: bool = False,
        exist_ok: bool = False,
    ) -> None:
        if path == out_file:
            out_file.write_text("created as a file during resolve")
            return None
        return real_mkdir(path, mode=mode, parents=parents, exist_ok=exist_ok)

    monkeypatch.setattr(Path, "mkdir", racing_mkdir)

    with pytest.raises(FileExistsError) as resolve_error:
        resolve_output(Path("song.wav"), out_file, "gain")

    assert resolve_error.value.filename == str(out_file)
    assert out_file.is_file()


def test_resolve_output_suffix_path_is_exact_file(tmp_path) -> None:
    out_file = tmp_path / "custom.flac"

    assert resolve_output(Path("song.wav"), out_file, "gain") == out_file


def test_resolve_output_preview_suffixless_path_does_not_create_directory(tmp_path) -> None:
    out_dir = tmp_path / "new-out"

    assert resolve_output_preview(Path("song.wav"), out_dir, "gain") == out_dir / "song.wav"
    assert not out_dir.exists()


def test_resolve_output_preview_and_resolve_conflict_on_existing_suffixless_file(
    tmp_path,
) -> None:
    out_file = tmp_path / "output"
    out_file.write_text("already a file")

    with pytest.raises(FileExistsError) as preview_error:
        resolve_output_preview(Path("song.wav"), out_file, "gain")
    with pytest.raises(FileExistsError) as resolve_error:
        resolve_output(Path("song.wav"), out_file, "gain")

    assert preview_error.value.filename == str(out_file)
    assert resolve_error.value.filename == str(out_file)
    assert out_file.is_file()
