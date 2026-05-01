"""Cross-platform REPL adapter for AudioCLI.

The REPL re-uses the exact same Typer app as one-shot mode. Typer wraps a
Click ``Group``; ``click-repl`` drives that group interactively. Commands
are therefore identical in both modes — there is no second parser to keep
in sync.

Two niceties on top of vanilla ``click-repl``:

* **`` ; `` chaining**: a single line ``mono ; resample --sr 22050`` runs
  each segment as its own command, in order. The split happens outside
  quoted strings so paths like ``"a;b.wav"`` survive.
* **Persistent history**: command history lives at ``~/.audiocli/history``
  and is loaded on shell start, so users can re-run recent commands across
  sessions. (``platformdirs`` integration lands with the settings work in
  issue #13.)

All heavy imports — ``click_repl`` and ``prompt_toolkit`` — happen inside
``run_shell`` so they never load at ``audiocli --help`` time.
"""

from __future__ import annotations

import shlex
import sys
from pathlib import Path
from typing import Annotated

import click
import typer

DEFAULT_HISTORY_PATH = Path.home() / ".audiocli" / "history"


def _split_chain(line: str) -> list[str]:
    """Split a REPL line on `` ; `` outside quoted strings.

    Uses ``shlex`` in POSIX mode with ``;`` as a recognised separator so
    we get quote-aware tokenisation for free, then re-joins each segment
    back into a string ``click-repl`` can dispatch.
    """
    lex = shlex.shlex(line, posix=True)
    lex.whitespace_split = True
    lex.commenters = ""
    segments: list[list[str]] = [[]]
    try:
        for tok in lex:
            if tok == ";":
                segments.append([])
            else:
                segments[-1].append(tok)
    except ValueError:
        # Unbalanced quotes — fall back to running the raw line as one
        # command and let click-repl surface the parse error.
        return [line.strip()] if line.strip() else []
    out: list[str] = []
    for seg in segments:
        if not seg:
            continue
        out.append(" ".join(shlex.quote(t) for t in seg))
    return out


def _ensure_history(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.touch()
    return path


def run_shell(app: typer.Typer, history_path: Path | None = None) -> None:
    """Enter the interactive REPL for ``app``.

    All ``click-repl`` / ``prompt_toolkit`` imports are deferred to here so
    importing :mod:`audiocli.cli` (and therefore ``audiocli --help``) stays
    fast.
    """
    # Lazy imports — keep --help snappy.
    from click_repl import ExitReplException  # noqa: PLC0415
    from prompt_toolkit.history import FileHistory  # noqa: PLC0415

    history_path = _ensure_history(history_path or DEFAULT_HISTORY_PATH)

    cli = typer.main.get_command(app)

    # We hand click-repl pre-tokenised segments by wrapping its prompt
    # source: read one physical line, split on `` ; ``, then feed each
    # segment back as its own command. We do this by patching stdin
    # readline behaviour for non-tty mode and by patching the
    # PromptSession in tty mode via prompt_toolkit's ``message`` hook.
    prompt_kwargs = {
        "history": FileHistory(str(history_path)),
        "message": "audiocli> ",
    }

    # click-repl's ``repl`` does not natively know about `;`-chaining, so
    # we drive it ourselves: a small loop reads input, splits, and invokes
    # the underlying group for each segment. This keeps behaviour
    # identical between TTY and piped-stdin modes.
    isatty = sys.stdin.isatty()

    history_obj = prompt_kwargs["history"]

    if isatty:
        from prompt_toolkit import PromptSession  # noqa: PLC0415

        session: PromptSession[str] = PromptSession(**prompt_kwargs)

        def read_line() -> str:
            # PromptSession routes input through the FileHistory itself,
            # so we don't need to manually append.
            return session.prompt()
    else:

        def read_line() -> str:
            line = sys.stdin.readline()
            if not line:
                raise EOFError
            stripped = line.rstrip("\n")
            if stripped.strip():
                history_obj.append_string(stripped)
            return stripped

    # Internal commands users expect.
    INTERNAL_EXIT = {"exit", "quit", ":exit", ":quit", ":q"}

    ctx = click.Context(cli, info_name=cli.name, parent=None)

    while True:
        try:
            line = read_line()
        except (EOFError, KeyboardInterrupt):
            break

        line = line.strip()
        if not line:
            continue
        if line in INTERNAL_EXIT:
            break

        for segment in _split_chain(line):
            if not segment:
                continue
            try:
                args = shlex.split(segment)
            except ValueError as e:
                typer.echo(f"parse error: {e}", err=True)
                continue
            try:
                with cli.make_context(cli.name, args, parent=ctx) as sub_ctx:
                    cli.invoke(sub_ctx)
            except click.exceptions.Exit:
                # A subcommand called sys.exit / typer.Exit — keep the
                # REPL alive regardless of the exit code.
                continue
            except click.ClickException as e:
                e.show()
            except ExitReplException:
                return
            except SystemExit:
                continue

    # Touch the history file on exit so callers can rely on its presence
    # even if no commands were run (prompt_toolkit only writes on input).
    history_path.touch(exist_ok=True)


def shell_command(app: typer.Typer) -> None:
    """Register the ``shell`` Typer command on ``app``."""

    @app.command("shell", help="Start the interactive REPL.")
    def _shell(
        history: Annotated[
            Path | None,
            typer.Option(
                "--history",
                help="Override the history file path (defaults to ~/.audiocli/history).",
            ),
        ] = None,
    ) -> None:
        run_shell(app, history_path=history)
