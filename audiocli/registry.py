"""The `@op` decorator and the in-process op registry.

Plugin authors and first-party op modules use the same decorator. Registration
is a pure metadata operation: it inspects the function's signature, stores an
`Op` record, and returns the function unchanged. No heavy imports happen here.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable
from dataclasses import dataclass

_REGISTRY: dict[str, Op] = {}


@dataclass
class Op:
    """Registry entry describing a single op."""

    name: str
    help: str
    func: Callable[..., object]

    @property
    def signature(self) -> inspect.Signature:
        # `eval_str=True` resolves string annotations produced by
        # `from __future__ import annotations`, which op modules will commonly
        # use. Without it, `Annotated[float, typer.Option(...)]` arrives at
        # the CLI builder as the literal string and Typer can't unwrap it.
        return inspect.signature(self.func, eval_str=True)

    @property
    def param_signature(self) -> inspect.Signature:
        """Signature with the leading buffer parameter removed."""
        sig = self.signature
        params = list(sig.parameters.values())
        return sig.replace(parameters=params[1:])


def op(
    *,
    name: str | None = None,
    help: str | None = None,
) -> Callable[[Callable[..., object]], Callable[..., object]]:
    """Register a function as an op.

    Usage::

        @op(name="gain", help="Apply gain in decibels.")
        def gain(buf: AudioBuffer, db: float) -> AudioBuffer:
            ...

    The first parameter must be the input ``AudioBuffer``; everything after
    becomes a CLI option, derived from type hints and defaults.
    """

    def decorator(func: Callable[..., object]) -> Callable[..., object]:
        op_name = name or func.__name__
        op_help = help
        if op_help is None and func.__doc__:
            op_help = func.__doc__.strip().splitlines()[0]
        op_help = op_help or op_name

        op_obj = Op(name=op_name, help=op_help, func=func)
        func.__op__ = op_obj  # type: ignore[attr-defined]
        _REGISTRY[op_name] = op_obj
        return func

    return decorator


def all_ops() -> dict[str, Op]:
    """Return a snapshot of the current op registry."""
    return dict(_REGISTRY)


def get_op(name: str) -> Op:
    """Look up an op by name; raises ``KeyError`` if unknown."""
    return _REGISTRY[name]
