"""Typer entry point.

The CLI auto-registers every op found under ``audiocli.ops`` at import time.
To keep ``audiocli --help`` snappy, op modules and the registry use lazy
imports — numpy and pedalboard are only loaded when an op actually runs.
"""

from __future__ import annotations

import importlib
import inspect
import pkgutil
import sys
from pathlib import Path
from typing import Annotated, Any

import typer

from audiocli.registry import Op, all_ops

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="AudioCLI v2 — pedalboard-powered batch audio power-tool.",
)


@app.callback()
def _root() -> None:
    """Forces Typer into subcommand mode even when only one op is registered."""


def _emit_fatal_error(json_mode: bool, message: str) -> None:
    """Surface a top-level error before/around the pipeline run.

    In ``--json`` mode we still produce parseable output: a single
    ``error`` event plus a terminating ``done`` event with no successes
    so subscribers can drive their state machines uniformly. In default
    mode we fall back to the human-readable ``error: ...`` line.
    """
    if json_mode:
        import json as _json  # noqa: PLC0415

        typer.echo(_json.dumps({"type": "error", "file": None, "reason": message}))
        typer.echo(_json.dumps({"type": "done", "ok": 0, "failed": 0, "duration_s": 0.0}))
    else:
        typer.echo(f"error: {message}", err=True)


def _make_event_subscriber(json_mode: bool):
    """Build the ``on_event`` callback and a ``finalize()`` cleanup pair.

    - ``json_mode=True`` → callback prints one JSON object per line on
      stdout. ``finalize`` is a noop.
    - Otherwise → callback drives a ``rich.progress.Progress`` bar on
      stderr (so stdout stays usable for piping) and ``finalize``
      stops it. ``rich`` is imported lazily so ``audiocli --help``
      doesn't pay for it.
    """
    if json_mode:
        import json as _json  # noqa: PLC0415

        def on_event(event: dict) -> None:
            typer.echo(_json.dumps(event))

        def finalize() -> None:
            return None

        return on_event, finalize

    # rich.progress is intentionally imported here, not at module top, so
    # `audiocli --help` stays under its 120ms wall-clock budget.
    from rich.progress import (  # noqa: PLC0415
        BarColumn,
        MofNCompleteColumn,
        Progress,
        TextColumn,
        TimeRemainingColumn,
    )

    progress = Progress(
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TextColumn("•"),
        TimeRemainingColumn(),
        TextColumn("[dim]{task.fields[current]}"),
        transient=False,
    )
    task_id: list[int | None] = [None]
    progress.start()

    def on_event(event: dict) -> None:
        kind = event.get("type")
        if kind == "start":
            task_id[0] = progress.add_task(
                "processing",
                total=event.get("total", 0),
                current="",
            )
        elif kind == "progress" and task_id[0] is not None:
            current = event.get("current") or ""
            # Show just the basename to keep the bar readable.
            display = current.rsplit("/", 1)[-1] if current else ""
            progress.update(
                task_id[0],
                completed=event.get("done", 0),
                current=display,
            )
        elif kind == "error":
            # Errors render to stderr alongside the progress bar so they
            # don't get scrolled off the top.
            reason = event.get("reason", "")
            file = event.get("file", "")
            typer.echo(f"FAIL {file}: {reason}", err=True)

    def finalize() -> None:
        progress.stop()

    return on_event, finalize


def _make_command(op_obj: Op):
    """Wrap an op as a Typer-compatible command function.

    The op's signature looks like ``(buf, *params) -> AudioBuffer``. We
    expose the params as CLI options and prepend the standard I/O flags so
    every op shares the same ``--target`` / ``--output`` / ``--workers`` /
    ``--recursive`` shape regardless of which op the user invoked.
    """
    op_params = list(op_obj.param_signature.parameters.values())

    target_param = inspect.Parameter(
        "target",
        kind=inspect.Parameter.KEYWORD_ONLY,
        annotation=Annotated[
            list[Path],
            typer.Option(
                "--target",
                help="Input audio file(s) or directory. Repeat to pass multiple.",
                exists=True,
                readable=True,
            ),
        ],
    )
    output_param = inspect.Parameter(
        "output",
        kind=inspect.Parameter.KEYWORD_ONLY,
        default=None,
        annotation=Annotated[
            Path | None,
            typer.Option("--output", help="Output file or directory."),
        ],
    )
    workers_param = inspect.Parameter(
        "workers",
        kind=inspect.Parameter.KEYWORD_ONLY,
        default=0,
        annotation=Annotated[
            int,
            typer.Option(
                "--workers",
                help="Worker thread count. 0 → min(8, cpu_count()).",
                min=0,
            ),
        ],
    )
    recursive_param = inspect.Parameter(
        "recursive",
        kind=inspect.Parameter.KEYWORD_ONLY,
        default=True,
        annotation=Annotated[
            bool,
            typer.Option(
                "--recursive/--no-recursive",
                help="Recurse into directories when scanning targets.",
            ),
        ],
    )
    json_param = inspect.Parameter(
        "json_mode",
        kind=inspect.Parameter.KEYWORD_ONLY,
        default=False,
        annotation=Annotated[
            bool,
            typer.Option(
                "--json",
                help=(
                    "Emit one JSON event per line on stdout instead of a "
                    "progress bar. Suitable for piping into another process."
                ),
            ),
        ],
    )

    cli_params = [
        target_param,
        output_param,
        workers_param,
        recursive_param,
        json_param,
    ] + [p.replace(kind=inspect.Parameter.KEYWORD_ONLY) for p in op_params]

    def cmd(**kwargs: Any) -> None:
        targets: list[Path] = kwargs.pop("target")
        output = kwargs.pop("output", None)
        workers = kwargs.pop("workers", 0)
        recursive = kwargs.pop("recursive", True)
        json_mode = kwargs.pop("json_mode", False)

        from audiocli.errors import AudioCLIError  # noqa: PLC0415
        from audiocli.pipeline import run_per_file  # noqa: PLC0415
        from audiocli.scanner import scan_targets  # noqa: PLC0415

        try:
            files = scan_targets(targets, recursive=recursive)
        except AudioCLIError as e:
            _emit_fatal_error(json_mode, str(e))
            raise typer.Exit(code=1) from e

        if not files:
            _emit_fatal_error(json_mode, "no audio files matched the targets")
            raise typer.Exit(code=1)

        on_event, finalize = _make_event_subscriber(json_mode)
        try:
            try:
                report = run_per_file(
                    files,
                    op_obj,
                    kwargs,
                    output=output,
                    workers=workers if workers > 0 else None,
                    on_event=on_event,
                )
            except AudioCLIError as e:
                _emit_fatal_error(json_mode, str(e))
                raise typer.Exit(code=1) from e
        finally:
            finalize()

        if not json_mode:
            # Successes go to stdout (one path per line) so users can pipe
            # them to other tools. Failures already rendered via the
            # progress-bar `error` event handler above.
            for r in report.results:
                if r.ok:
                    typer.echo(str(r.path))

            typer.echo(
                f"done: {report.ok_count} ok, {report.failed_count} failed "
                f"in {report.duration_s:.2f}s",
                err=True,
            )

        if report.failed_count > 0:
            raise typer.Exit(code=report.exit_code)

    cmd.__signature__ = inspect.Signature(parameters=cli_params)  # type: ignore[attr-defined]
    cmd.__name__ = op_obj.name
    cmd.__doc__ = op_obj.help
    return cmd


def _load_ops() -> None:
    """Import every module under ``audiocli.ops`` to trigger registration."""
    from audiocli import ops  # noqa: PLC0415

    for m in pkgutil.iter_modules(ops.__path__):
        if m.name.startswith("_"):
            continue
        importlib.import_module(f"audiocli.ops.{m.name}")


def _load_plugins() -> None:
    """Discover third-party plugin ops via the ``audiocli.ops`` entry-point group.

    First-party ops are loaded first; on a name conflict, the first-party op
    wins and the conflict is logged once to stderr. Malformed plugin
    signatures or import failures raise :class:`PluginError`, which we
    surface as a clean non-zero CLI exit so the user sees the offending
    plugin name instead of a traceback.
    """
    from audiocli.errors import PluginError  # noqa: PLC0415
    from audiocli.plugins import load_plugins  # noqa: PLC0415

    try:
        _, conflicts = load_plugins()
    except PluginError as e:
        typer.echo(f"error: {e}", err=True)
        raise typer.Exit(code=1) from e

    for c in conflicts:
        typer.echo(
            f"warning: plugin {c.plugin_dist!r} op {c.name!r} "
            f"({c.plugin_target}) shadowed by first-party op; plugin op ignored.",
            err=True,
        )


def _register_commands() -> None:
    _load_ops()
    _load_plugins()
    for op_obj in all_ops().values():
        cmd = _make_command(op_obj)
        app.command(name=op_obj.name, help=op_obj.help)(cmd)


def _register_shell() -> None:
    """Register the ``shell`` REPL command on the Typer app.

    ``audiocli.repl`` itself only imports light stdlib + click + typer at
    module load. The heavy ``click_repl`` / ``prompt_toolkit`` imports
    live inside ``run_shell`` and only fire when the user actually enters
    the REPL, so ``audiocli --help`` stays under its 100ms budget.
    """
    from audiocli.repl import shell_command  # noqa: PLC0415

    shell_command(app)


def _register_special() -> None:
    """Register the first-party special-case commands on the Typer app.

    ``info``, ``remove-silent``, and ``chunk`` don't fit the standard
    ``(buf) -> buf`` filter contract that registered ops use, so they are
    registered as direct Typer commands. The implementation lives in
    :mod:`audiocli.special`; numpy / pyloudnorm imports there are deferred
    so ``audiocli --help`` stays under its 120 ms budget.
    """
    from audiocli.special import register_special_commands  # noqa: PLC0415

    register_special_commands(app)


def _register_hook() -> None:
    """Register the ``hook`` Typer command — Python escape-hatch op runner.

    ``hook`` accepts arbitrary ``--key=value`` flags and forwards them to
    the user's function as kwargs, so we configure Typer's context to
    allow extra args and ignore unknown options. Heavy modules (importlib
    is stdlib but the user's script might pull in numpy/torch) only load
    inside ``_hook`` itself.
    """

    @app.command(
        "hook",
        help=(
            "Run a one-off Python transform from a script file. "
            "The script must define a function (default 'transform'/'process'/'main') "
            "with signature (buf: AudioBuffer, **kwargs) -> AudioBuffer."
        ),
        context_settings={
            "allow_extra_args": True,
            "ignore_unknown_options": True,
        },
    )
    def _hook(
        ctx: typer.Context,
        script: Annotated[
            Path,
            typer.Argument(
                help="Path to a Python file with the user's transform.",
                exists=True,
                readable=True,
            ),
        ],
        target: Annotated[
            list[Path],
            typer.Option(
                "--target",
                help="Input audio file(s) or directory. Repeat to pass multiple.",
                exists=True,
                readable=True,
            ),
        ],
        output: Annotated[
            Path | None,
            typer.Option("--output", help="Output file or directory."),
        ] = None,
        func: Annotated[
            str | None,
            typer.Option(
                "--func",
                help=(
                    "Function name to invoke. Defaults to the first of "
                    "transform/process/main found in the script."
                ),
            ),
        ] = None,
        workers: Annotated[
            int,
            typer.Option(
                "--workers",
                help="Worker thread count. 0 → min(8, cpu_count()).",
                min=0,
            ),
        ] = 0,
        recursive: Annotated[
            bool,
            typer.Option(
                "--recursive/--no-recursive",
                help="Recurse into directories when scanning targets.",
            ),
        ] = True,
    ) -> None:
        from audiocli.errors import AudioCLIError  # noqa: PLC0415
        from audiocli.hook import (  # noqa: PLC0415
            load_hook_function,
            make_hook_op,
            parse_extra_kwargs,
        )
        from audiocli.pipeline import run_per_file  # noqa: PLC0415
        from audiocli.scanner import scan_targets  # noqa: PLC0415

        try:
            user_kwargs = parse_extra_kwargs(list(ctx.args))
            user_func = load_hook_function(script, func)
            op_obj = make_hook_op(user_func, script)
            files = scan_targets(target, recursive=recursive)
        except AudioCLIError as e:
            typer.echo(f"error: {e}", err=True)
            raise typer.Exit(code=1) from e

        if not files:
            typer.echo("error: no audio files matched the targets", err=True)
            raise typer.Exit(code=1)

        try:
            report = run_per_file(
                files,
                op_obj,
                user_kwargs,
                output=output,
                workers=workers if workers > 0 else None,
            )
        except AudioCLIError as e:
            typer.echo(f"error: {e}", err=True)
            raise typer.Exit(code=1) from e

        for r in report.results:
            if r.ok:
                typer.echo(str(r.path))
            else:
                typer.echo(f"FAIL {r.path}: {r.error}", err=True)

        typer.echo(
            f"done: {report.ok_count} ok, {report.failed_count} failed in {report.duration_s:.2f}s",
            err=True,
        )

        if report.failed_count > 0:
            raise typer.Exit(code=report.exit_code)


def _register_run_script() -> None:
    """Register the ``run-script`` Typer command — ``.acli`` batch runner."""

    @app.command(
        "run-script",
        help="Execute a .acli file: one CLI command per line, '#' for comments.",
    )
    def _run_script(
        path: Annotated[
            Path,
            typer.Argument(
                help="Path to a .acli script file.",
                exists=True,
                readable=True,
            ),
        ],
        strict: Annotated[
            bool,
            typer.Option(
                "--strict/--no-strict",
                help="Abort on the first failing line instead of running every line.",
            ),
        ] = False,
    ) -> None:
        from audiocli.errors import AudioCLIError  # noqa: PLC0415
        from audiocli.run_script import run_script as _exec_script  # noqa: PLC0415

        try:
            report = _exec_script(app, path, strict=strict)
        except AudioCLIError as e:
            typer.echo(f"error: {e}", err=True)
            raise typer.Exit(code=1) from e

        for r in report.results:
            if r.ok:
                typer.echo(f"line {r.lineno}: ok  | {r.command}")
            else:
                typer.echo(f"line {r.lineno}: FAIL | {r.command}: {r.error}", err=True)

        typer.echo(
            f"done: {report.ok_count} ok, {report.failed_count} failed",
            err=True,
        )

        if report.failed_count > 0:
            raise typer.Exit(code=report.exit_code)


_register_commands()
_register_shell()
_register_special()
_register_hook()
_register_run_script()


def main() -> None:  # pragma: no cover
    app()


if __name__ == "__main__":  # pragma: no cover
    sys.exit(app())
