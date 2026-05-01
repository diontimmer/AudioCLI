"""``.acli`` script runner — executes a saved sequence of CLI commands.

The format is intentionally minimal: one CLI command per line, blank lines
and ``#``-prefixed comments are skipped. Each line is tokenised with
``shlex`` and dispatched through the same Typer/Click app the user would
hit from a shell, so command behaviour is identical between modes.

Library code only — no ``print``, no ``sys.exit``. Returns a
:class:`ScriptReport` describing every line's outcome so callers can pick
the rendering / exit strategy.
"""

from __future__ import annotations

import shlex
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from audiocli.errors import AudioCLIError

if TYPE_CHECKING:
    import typer


@dataclass
class LineResult:
    """Outcome for a single ``.acli`` line."""

    lineno: int
    command: str
    ok: bool
    exit_code: int = 0
    error: str | None = None


@dataclass
class ScriptReport:
    """Aggregated outcome of a :func:`run_script` invocation."""

    results: list[LineResult] = field(default_factory=list)

    @property
    def ok_count(self) -> int:
        return sum(1 for r in self.results if r.ok)

    @property
    def failed_count(self) -> int:
        return sum(1 for r in self.results if not r.ok)

    @property
    def exit_code(self) -> int:
        """0 when every line succeeded; otherwise the failure count, capped at 255."""
        return min(self.failed_count, 255)


def parse_script(path: Path) -> list[tuple[int, str]]:
    """Read ``path`` and return ``(lineno, command)`` pairs to execute.

    Blank lines and ``#``-prefixed comments are dropped. Inline ``#``
    comments are *not* stripped — users can embed ``#`` inside quoted
    arguments without surprises.
    """
    path = Path(path)
    if not path.exists():
        raise AudioCLIError(f"script file not found: {path}")
    if not path.is_file():
        raise AudioCLIError(f"script path is not a file: {path}")

    out: list[tuple[int, str]] = []
    for i, raw in enumerate(path.read_text().splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        out.append((i, line))
    return out


def run_script(
    app: typer.Typer,
    path: Path,
    *,
    strict: bool = False,
) -> ScriptReport:
    """Execute every command in ``path`` against ``app``.

    Args:
        app: the Typer app to dispatch each line through.
        path: ``.acli`` script file.
        strict: when ``True``, the first failing line aborts the run and
            subsequent lines are not executed. Default ``False`` mirrors
            ``run_per_file``'s "best-effort batch" semantics — one bad line
            doesn't sink the rest of the job.

    Returns:
        :class:`ScriptReport` describing every executed line's outcome.
    """
    import click  # noqa: PLC0415
    import typer as _typer  # noqa: PLC0415

    cli = _typer.main.get_command(app)
    report = ScriptReport()

    for lineno, line in parse_script(path):
        try:
            args = shlex.split(line)
        except ValueError as e:
            report.results.append(
                LineResult(lineno=lineno, command=line, ok=False, error=f"parse error: {e}"),
            )
            if strict:
                break
            continue

        try:
            with cli.make_context(cli.name, args, parent=None) as ctx:
                cli.invoke(ctx)
            report.results.append(LineResult(lineno=lineno, command=line, ok=True))
        except click.exceptions.Exit as e:
            code = int(e.exit_code or 0)
            ok = code == 0
            report.results.append(
                LineResult(
                    lineno=lineno,
                    command=line,
                    ok=ok,
                    exit_code=code,
                    error=None if ok else f"command exited with code {code}",
                ),
            )
            if not ok and strict:
                break
        except click.ClickException as e:
            report.results.append(
                LineResult(
                    lineno=lineno,
                    command=line,
                    ok=False,
                    exit_code=e.exit_code,
                    error=e.format_message(),
                ),
            )
            if strict:
                break
        except SystemExit as e:
            code = int(e.code) if isinstance(e.code, int) else 1
            ok = code == 0
            report.results.append(
                LineResult(
                    lineno=lineno,
                    command=line,
                    ok=ok,
                    exit_code=code,
                    error=None if ok else f"command exited with code {code}",
                ),
            )
            if not ok and strict:
                break
        except Exception as e:
            report.results.append(
                LineResult(
                    lineno=lineno,
                    command=line,
                    ok=False,
                    error=f"{type(e).__name__}: {e}",
                ),
            )
            if strict:
                break

    return report
