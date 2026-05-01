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
    expose the params as CLI options and prepend ``--target`` / ``--output``
    so users always have the same I/O shape regardless of which op they run.
    """
    op_params = list(op_obj.param_signature.parameters.values())

    target_param = inspect.Parameter(
        "target",
        kind=inspect.Parameter.KEYWORD_ONLY,
        annotation=Annotated[
            Path,
            typer.Option(
                "--target",
                help="Input audio file (directory inputs land in #02).",
                exists=True,
                dir_okay=False,
                file_okay=True,
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

    cli_params = [target_param, output_param] + [
        p.replace(kind=inspect.Parameter.KEYWORD_ONLY) for p in op_params
    ]

    def cmd(**kwargs: Any) -> None:
        target = kwargs.pop("target")
        output = kwargs.pop("output", None)
        from audiocli.errors import AudioCLIError  # noqa: PLC0415
        from audiocli.pipeline import run_one  # noqa: PLC0415

        try:
            dst = run_one(target, op_obj, kwargs, output)
        except AudioCLIError as e:
            typer.echo(f"error: {e}", err=True)
            raise typer.Exit(code=1) from e
        typer.echo(str(dst))

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


def _register_commands() -> None:
    _load_ops()
    for op_obj in all_ops().values():
        cmd = _make_command(op_obj)
        app.command(name=op_obj.name, help=op_obj.help)(cmd)


_register_commands()


def main() -> None:  # pragma: no cover
    app()


if __name__ == "__main__":  # pragma: no cover
    sys.exit(app())
