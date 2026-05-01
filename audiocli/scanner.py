"""Target scanner — resolve user-supplied paths to a concrete file list.

Accepts a mix of files and directories. Directories are walked (optionally
recursively), filtered by extension, with hidden-file and symlink controls.

Library code: never prints, never ``sys.exit``s. Bad inputs raise
``AudioCLIError`` so the CLI layer can render a clean message.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from audiocli.errors import AudioCLIError

# Default audio extensions AudioCLI considers "scannable" when walking a
# directory. Single-file targets bypass this filter — the user named the
# file explicitly, so honour their intent.
DEFAULT_EXTENSIONS: tuple[str, ...] = (
    ".wav",
    ".flac",
    ".mp3",
    ".ogg",
    ".aac",
    ".m4a",
    ".aiff",
    ".aif",
)


def scan_targets(
    targets: Iterable[str | Path],
    *,
    recursive: bool = True,
    extensions: Iterable[str] | None = None,
    include_hidden: bool = False,
    follow_symlinks: bool = False,
) -> list[Path]:
    """Resolve ``targets`` to a sorted, de-duplicated list of audio files.

    Args:
        targets: paths to files and/or directories.
        recursive: walk directories recursively when ``True``.
        extensions: extensions to keep (case-insensitive, leading dot
            optional). ``None`` uses :data:`DEFAULT_EXTENSIONS`.
        include_hidden: include dot-files / dot-directories when walking.
        follow_symlinks: follow symlinked directories during the walk.

    Raises:
        AudioCLIError: if any target path does not exist, or if no targets
            were provided at all.
    """
    target_list = [Path(t) for t in targets]
    if not target_list:
        raise AudioCLIError("no targets provided")

    exts = _normalize_extensions(extensions)
    seen: set[Path] = set()
    out: list[Path] = []

    for t in target_list:
        if not t.exists():
            raise AudioCLIError(f"target not found: {t}")
        if t.is_file():
            # Single-file targets are always included regardless of extension.
            resolved = t.resolve()
            if resolved not in seen:
                seen.add(resolved)
                out.append(t)
            continue
        if t.is_dir():
            for f in _walk_dir(
                t,
                recursive=recursive,
                exts=exts,
                include_hidden=include_hidden,
                follow_symlinks=follow_symlinks,
            ):
                resolved = f.resolve()
                if resolved in seen:
                    continue
                seen.add(resolved)
                out.append(f)
            continue
        raise AudioCLIError(f"target is neither a file nor a directory: {t}")

    out.sort()
    return out


def _normalize_extensions(exts: Iterable[str] | None) -> set[str]:
    src = DEFAULT_EXTENSIONS if exts is None else exts
    out: set[str] = set()
    for e in src:
        if not e:
            continue
        e = e.lower()
        if not e.startswith("."):
            e = "." + e
        out.add(e)
    return out


def _walk_dir(
    root: Path,
    *,
    recursive: bool,
    exts: set[str],
    include_hidden: bool,
    follow_symlinks: bool,
) -> Iterable[Path]:
    """Yield audio files under ``root`` honouring the scanner's flags."""
    if recursive:
        # Manual walk so we can prune hidden subdirectories before descending.
        stack: list[Path] = [root]
        while stack:
            current = stack.pop()
            try:
                entries = list(current.iterdir())
            except PermissionError:
                continue
            for entry in entries:
                if not include_hidden and entry.name.startswith("."):
                    continue
                # A symlinked file is fine; only skip symlinked dirs.
                if entry.is_symlink() and not follow_symlinks and entry.is_dir():
                    continue
                if entry.is_dir():
                    stack.append(entry)
                    continue
                if entry.is_file() and entry.suffix.lower() in exts:
                    yield entry
        return

    try:
        entries = list(root.iterdir())
    except PermissionError:
        return
    for entry in entries:
        if not include_hidden and entry.name.startswith("."):
            continue
        if entry.is_symlink() and not follow_symlinks and entry.is_dir():
            continue
        if entry.is_file() and entry.suffix.lower() in exts:
            yield entry
