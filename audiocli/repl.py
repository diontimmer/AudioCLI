"""Cross-platform REPL adapter for AudioCLI.

The REPL re-uses the exact same Typer app as one-shot mode. Typer wraps a
Click ``Group``; ``click-repl`` drives that group interactively. Commands
are therefore identical in both modes — there is no second parser to keep
in sync.

Three niceties on top of vanilla ``click-repl``:

* **`` ; `` chaining**: a single line ``mono ; resample --sr 22050`` runs
  each segment as its own command, in order. The split happens outside
  quoted strings so paths like ``"a;b.wav"`` survive.
* **Persistent history**: command history lives at the ``platformdirs``
  user-data dir (``~/.local/share/audiocli/history`` on Linux, the
  Application Support dir on macOS, ``%LOCALAPPDATA%`` on Windows).
* **Persistent session settings**: ``set targets <paths>``,
  ``set output <dir>``, ``set workers N``, ``set recursive on|off``,
  and ``set overwrite on|off`` mutate the in-memory :class:`Settings`
  and write to disk immediately so a crash doesn't lose state. ``show``
  prints the current settings.

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

from audiocli.errors import ConfigError
from audiocli.settings import Settings, load_settings, save_settings


def _default_history_path() -> Path:
    """Return the platformdirs user-data history path.

    Honours ``AUDIOCLI_HISTORY_FILE`` for tests / scripted overrides;
    otherwise resolves via ``platformdirs.user_data_dir``. Lazy
    ``platformdirs`` import keeps ``audiocli --help`` fast.
    """
    import os  # noqa: PLC0415

    override = os.environ.get("AUDIOCLI_HISTORY_FILE")
    if override:
        return Path(override)
    import platformdirs  # noqa: PLC0415

    return Path(platformdirs.user_data_dir("audiocli")) / "history"


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


def _parse_bool(s: str) -> bool:
    s = s.strip().lower()
    if s in {"on", "true", "yes", "1"}:
        return True
    if s in {"off", "false", "no", "0"}:
        return False
    raise ValueError(f"expected on/off, got {s!r}")


def _format_settings(s: Settings) -> str:
    targets = ", ".join(str(p) for p in s.targets) if s.targets else "(none)"
    output = str(s.output) if s.output is not None else "(none)"
    return (
        f"targets:    {targets}\n"
        f"output:     {output}\n"
        f"workers:    {s.workers}\n"
        f"recursive:  {'on' if s.recursive else 'off'}\n"
        f"overwrite:  {'on' if s.overwrite else 'off'}"
    )


def _handle_set(
    args: list[str], settings: Settings, settings_path: Path | None
) -> tuple[Settings, bool]:
    """Apply a ``set <key> <value>`` command.

    Returns the (possibly new) ``Settings`` and a flag indicating whether
    anything actually changed (so the caller can decide to persist).
    Raises :class:`ConfigError` for unknown keys or bad values; the REPL
    loop catches and renders these.
    """
    if not args:
        raise ConfigError("set: missing key. Try: set targets|output|workers|recursive|overwrite")
    key, *rest = args
    key = key.lower()

    if key == "targets":
        if not rest:
            raise ConfigError("set targets: at least one path required")
        new = settings.replace(targets=[Path(p) for p in rest])
    elif key == "output":
        if len(rest) != 1:
            raise ConfigError("set output: exactly one path required")
        new = settings.replace(output=Path(rest[0]))
    elif key == "workers":
        if len(rest) != 1:
            raise ConfigError("set workers: exactly one integer required")
        try:
            n = int(rest[0])
        except ValueError as e:
            raise ConfigError(f"set workers: not an integer: {rest[0]!r}") from e
        if n < 0:
            raise ConfigError("set workers: must be >= 0")
        new = settings.replace(workers=n)
    elif key == "recursive":
        if len(rest) != 1:
            raise ConfigError("set recursive: expected on|off")
        try:
            new = settings.replace(recursive=_parse_bool(rest[0]))
        except ValueError as e:
            raise ConfigError(f"set recursive: {e}") from e
    elif key == "overwrite":
        if len(rest) != 1:
            raise ConfigError("set overwrite: expected on|off")
        try:
            new = settings.replace(overwrite=_parse_bool(rest[0]))
        except ValueError as e:
            raise ConfigError(f"set overwrite: {e}") from e
    else:
        raise ConfigError(
            f"set: unknown key {key!r} (try: targets, output, workers, recursive, overwrite)"
        )

    changed = new != settings
    if changed:
        save_settings(new, settings_path)
    return new, changed


def run_shell(
    app: typer.Typer,
    history_path: Path | None = None,
    settings_path: Path | None = None,
) -> None:
    """Enter the interactive REPL for ``app``.

    All ``click-repl`` / ``prompt_toolkit`` imports are deferred to here so
    importing :mod:`audiocli.cli` (and therefore ``audiocli --help``) stays
    fast.
    """
    # Lazy imports — keep --help snappy.
    from click_repl import ExitReplException  # noqa: PLC0415
    from prompt_toolkit.history import FileHistory  # noqa: PLC0415

    history_path = _ensure_history(history_path or _default_history_path())

    try:
        settings = load_settings(settings_path)
    except ConfigError as e:
        typer.echo(f"error: {e}", err=True)
        # Fall back to defaults so the user can keep working; they can
        # delete the file when they want to.
        settings = Settings()

    cli = typer.main.get_command(app)

    prompt_kwargs = {
        "history": FileHistory(str(history_path)),
        "message": "audiocli> ",
    }

    isatty = sys.stdin.isatty()
    history_obj = prompt_kwargs["history"]

    if isatty:
        from prompt_toolkit import PromptSession  # noqa: PLC0415

        session: PromptSession[str] = PromptSession(**prompt_kwargs)

        def read_line() -> str:
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

    INTERNAL_EXIT = {"exit", "quit", ":exit", ":quit", ":q"}

    ctx = click.Context(cli, info_name=cli.name, parent=None)

    def _apply_settings_defaults(args: list[str]) -> list[str]:
        """Inject persisted settings into ``args`` as defaults.

        Explicit flags on the command line always win — we only add a
        flag if it isn't already present. ``--target`` accepts repeats,
        so we add one ``--target`` per persisted path.
        """
        if not args:
            return args
        # First token is the subcommand name; settings only make sense
        # for op subcommands, but injecting harmless defaults into
        # ``shell`` itself is also fine since Typer ignores unknown? — no,
        # it errors. Restrict injection to known op commands by checking
        # the click group.
        subcmd = args[0]
        if cli.get_command(ctx, subcmd) is None:
            return args
        # Don't inject into the shell command (recursion) or set/show
        # which are handled before this function runs.
        if subcmd in {"shell"}:
            return args

        joined = " ".join(args[1:])
        out = list(args)
        if settings.targets and "--target" not in args:
            for t in settings.targets:
                out.extend(["--target", str(t)])
        if settings.output is not None and "--output" not in args:
            out.extend(["--output", str(settings.output)])
        if settings.workers and "--workers" not in args:
            out.extend(["--workers", str(settings.workers)])
        if "--recursive" not in joined and "--no-recursive" not in joined:
            out.append("--recursive" if settings.recursive else "--no-recursive")
        return out

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

            if not args:
                continue

            # Built-in REPL commands (handled inside the loop, never
            # dispatched to Typer).
            if args[0] == "set":
                try:
                    settings, _changed = _handle_set(args[1:], settings, settings_path)
                except ConfigError as e:
                    typer.echo(f"error: {e}", err=True)
                continue
            if args[0] in {"show", "settings"}:
                typer.echo(_format_settings(settings))
                continue

            args = _apply_settings_defaults(args)

            try:
                with cli.make_context(cli.name, args, parent=ctx) as sub_ctx:
                    cli.invoke(sub_ctx)
            except click.exceptions.Exit:
                continue
            except click.ClickException as e:
                e.show()
            except ExitReplException:
                return
            except SystemExit:
                continue

    history_path.touch(exist_ok=True)


def shell_command(app: typer.Typer) -> None:
    """Register the ``shell`` Typer command on ``app``."""

    @app.command("shell", help="Start the interactive REPL.")
    def _shell(
        history: Annotated[
            Path | None,
            typer.Option(
                "--history",
                help=(
                    "Override the history file path (defaults to the platformdirs user-data dir)."
                ),
            ),
        ] = None,
        settings_file: Annotated[
            Path | None,
            typer.Option(
                "--settings",
                help=(
                    "Override the settings file path "
                    "(defaults to the platformdirs user-config dir)."
                ),
            ),
        ] = None,
    ) -> None:
        run_shell(app, history_path=history, settings_path=settings_file)
