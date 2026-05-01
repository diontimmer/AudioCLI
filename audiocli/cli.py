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

    cli_params = [target_param, output_param, workers_param, recursive_param] + [
        p.replace(kind=inspect.Parameter.KEYWORD_ONLY) for p in op_params
    ]

    def cmd(**kwargs: Any) -> None:
        targets: list[Path] = kwargs.pop("target")
        output = kwargs.pop("output", None)
        workers = kwargs.pop("workers", 0)
        recursive = kwargs.pop("recursive", True)

        from audiocli.errors import AudioCLIError  # noqa: PLC0415
        from audiocli.pipeline import run_per_file  # noqa: PLC0415
        from audiocli.scanner import scan_targets  # noqa: PLC0415

        try:
            files = scan_targets(targets, recursive=recursive)
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
                kwargs,
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


_register_commands()


def main() -> None:  # pragma: no cover
    app()


if __name__ == "__main__":  # pragma: no cover
    sys.exit(app())
