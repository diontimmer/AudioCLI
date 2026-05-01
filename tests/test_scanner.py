"""Tests for the target scanner."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from audiocli.errors import AudioCLIError
from audiocli.scanner import scan_targets


def _touch(p: Path) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"")


def test_single_file_target_kept_regardless_of_extension(tmp_path):
    p = tmp_path / "weirdname.dat"
    _touch(p)
    out = scan_targets([p])
    assert out == [p]


def test_directory_recursive_collects_audio(tmp_path):
    _touch(tmp_path / "a.wav")
    _touch(tmp_path / "sub" / "b.flac")
    _touch(tmp_path / "sub" / "deeper" / "c.mp3")
    _touch(tmp_path / "sub" / "ignore.txt")

    out = scan_targets([tmp_path], recursive=True)
    names = sorted(p.name for p in out)
    assert names == ["a.wav", "b.flac", "c.mp3"]


def test_directory_non_recursive_only_top_level(tmp_path):
    _touch(tmp_path / "a.wav")
    _touch(tmp_path / "sub" / "b.wav")
    out = scan_targets([tmp_path], recursive=False)
    assert [p.name for p in out] == ["a.wav"]


def test_extension_filter(tmp_path):
    _touch(tmp_path / "a.wav")
    _touch(tmp_path / "b.flac")
    _touch(tmp_path / "c.mp3")
    out = scan_targets([tmp_path], extensions={".wav", ".mp3"})
    assert sorted(p.name for p in out) == ["a.wav", "c.mp3"]


def test_extension_normalization_handles_missing_dot_and_case(tmp_path):
    _touch(tmp_path / "a.WAV")
    _touch(tmp_path / "b.flac")
    out = scan_targets([tmp_path], extensions={"wav"})
    assert [p.name for p in out] == ["a.WAV"]


def test_hidden_files_excluded_by_default(tmp_path):
    _touch(tmp_path / "a.wav")
    _touch(tmp_path / ".hidden.wav")
    _touch(tmp_path / ".hiddendir" / "c.wav")
    out = scan_targets([tmp_path])
    assert [p.name for p in out] == ["a.wav"]


def test_hidden_files_included_when_requested(tmp_path):
    _touch(tmp_path / "a.wav")
    _touch(tmp_path / ".hidden.wav")
    out = scan_targets([tmp_path], include_hidden=True)
    assert sorted(p.name for p in out) == [".hidden.wav", "a.wav"]


@pytest.mark.skipif(sys.platform == "win32", reason="symlink semantics differ on Windows")
def test_symlinked_directory_skipped_by_default(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    _touch(real / "a.wav")
    link = tmp_path / "link"
    os.symlink(real, link, target_is_directory=True)

    # Scanning the parent: the linked subdir is skipped.
    out = scan_targets([tmp_path])
    # `real/a.wav` is reachable directly; `link/a.wav` is skipped.
    assert all("link" not in p.parts for p in out)
    assert any(p.name == "a.wav" for p in out)


@pytest.mark.skipif(sys.platform == "win32", reason="symlink semantics differ on Windows")
def test_symlinked_directory_followed_when_requested(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    _touch(real / "a.wav")
    link = tmp_path / "link"
    os.symlink(real, link, target_is_directory=True)

    out = scan_targets(
        [link],
        follow_symlinks=True,
    )
    assert any(p.name == "a.wav" for p in out)


def test_missing_path_raises_clean_error(tmp_path):
    with pytest.raises(AudioCLIError) as exc:
        scan_targets([tmp_path / "does_not_exist"])
    assert "not found" in str(exc.value)


def test_no_targets_raises():
    with pytest.raises(AudioCLIError):
        scan_targets([])


def test_results_are_deduplicated(tmp_path):
    a = tmp_path / "a.wav"
    _touch(a)
    out = scan_targets([a, a, tmp_path])
    # Same file via three routes → one entry in the result.
    assert len(out) == 1
    assert out[0].resolve() == a.resolve()


def test_results_are_sorted(tmp_path):
    _touch(tmp_path / "z.wav")
    _touch(tmp_path / "a.wav")
    _touch(tmp_path / "m.wav")
    out = scan_targets([tmp_path])
    assert [p.name for p in out] == ["a.wav", "m.wav", "z.wav"]
