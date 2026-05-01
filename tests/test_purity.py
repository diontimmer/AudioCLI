"""Library purity — no print() / sys.exit() in code outside ``cli.py``.

The library is the canonical surface; the CLI is the only place that's
allowed to render output or terminate the process. A future desktop GUI
embeds the library directly and must never have stray writes to stdout
nor unexpected ``SystemExit`` from a pipeline call.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "audiocli"

# Files allowed to contain the otherwise-forbidden patterns.
_ALLOWED = {
    "cli.py",
}


def _library_files() -> list[Path]:
    return [
        p for p in ROOT.rglob("*.py") if p.name not in _ALLOWED and "__pycache__" not in p.parts
    ]


def test_no_print_calls_in_library():
    """Greps every library file (excluding ``cli.py``) for ``print(``."""
    pattern = re.compile(r"(?<![\w.])print\s*\(")
    offenders: list[str] = []
    for f in _library_files():
        text = f.read_text()
        for lineno, line in enumerate(text.splitlines(), start=1):
            stripped = line.lstrip()
            if stripped.startswith("#"):
                continue
            if pattern.search(line):
                offenders.append(f"{f.relative_to(ROOT.parent)}:{lineno}: {line.strip()}")
    assert not offenders, "stray print() calls in library code:\n" + "\n".join(offenders)


def test_no_sys_exit_calls_in_library():
    """Greps every library file (excluding ``cli.py``) for ``sys.exit(``."""
    pattern = re.compile(r"sys\.exit\s*\(")
    offenders: list[str] = []
    for f in _library_files():
        text = f.read_text()
        for lineno, line in enumerate(text.splitlines(), start=1):
            stripped = line.lstrip()
            if stripped.startswith("#"):
                continue
            if pattern.search(line):
                offenders.append(f"{f.relative_to(ROOT.parent)}:{lineno}: {line.strip()}")
    assert not offenders, "stray sys.exit() calls in library code:\n" + "\n".join(offenders)
