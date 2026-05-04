"""The `@op` decorator and the in-process op registry.

Plugin authors and first-party op modules use the same decorator. Registration
is a pure metadata operation: it inspects the function's signature, stores an
`Op` record, and returns the function unchanged. No heavy imports happen here.

This module also exposes the library-facing introspection surface used by
:func:`audiocli.list_ops`: :class:`OpInfo` and :class:`ParamInfo` describe
every registered op in enough detail for a desktop frontend (or any other
external caller) to render a dynamic UI per op without importing the op's
module.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal, get_args, get_origin

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


@dataclass(frozen=True)
class ParamInfo:
    """Public metadata for one op parameter.

    Designed for round-tripping through JSON and for driving dynamic UI in
    a desktop frontend. ``type`` is reported as a stable string name (e.g.
    ``"float"``, ``"int"``, ``"bool"``, ``"str"``, ``"Path"``) so callers
    don't need to import Python type objects to compare against it.
    """

    name: str
    type: str
    default: Any = None
    help: str = ""
    required: bool = False
    choices: list[Any] = field(default_factory=list)


@dataclass(frozen=True)
class OpInfo:
    """Public metadata for one registered op.

    ``kind`` is always ``"filter"`` for v2.0 ops registered via ``@op``;
    the field exists so future special-case ops (analysis, multi-output,
    side-effect) can broaden the public surface without breaking the shape.
    """

    name: str
    help: str
    kind: str = "filter"
    params: list[ParamInfo] = field(default_factory=list)


_TYPE_NAMES: dict[type, str] = {
    int: "int",
    float: "float",
    bool: "bool",
    str: "str",
    bytes: "bytes",
}


def _type_name(annotation: Any) -> str:
    """Render a parameter annotation as a stable string for ``ParamInfo.type``."""
    if annotation is inspect.Parameter.empty:
        return "any"

    # Unwrap Annotated[T, ...] → T.
    origin = get_origin(annotation)
    if origin is not None:
        args = get_args(annotation)
        # typing.Annotated reports the underlying type as its first arg.
        if args and getattr(annotation, "__metadata__", None) is not None:
            return _type_name(args[0])
        if origin is Literal:
            if not args:
                return "literal"
            literal_types = {type(arg) for arg in args}
            if len(literal_types) == 1:
                return _type_name(next(iter(literal_types)))
            return "literal"
        # X | Y unions and Optional[X]: pick the first non-None member.
        if args:
            non_none = [a for a in args if a is not type(None)]
            if len(non_none) == 1:
                return _type_name(non_none[0])
            return " | ".join(_type_name(a) for a in args)
        return getattr(origin, "__name__", str(origin))

    if isinstance(annotation, type):
        return _TYPE_NAMES.get(annotation, annotation.__name__)
    return str(annotation)


def _param_help(annotation: Any) -> str:
    """Pull the ``help=`` text out of a typer.Option / typer.Argument metadata."""
    if get_origin(annotation) is None:
        return ""
    metadata = getattr(annotation, "__metadata__", ())
    for meta in metadata:
        # typer.Option / typer.Argument → ParameterInfo with a `help` attr.
        help_text = getattr(meta, "help", None)
        if help_text:
            return str(help_text)
    return ""


def _literal_choices(annotation: Any) -> list[Any]:
    """Return literal choices declared by an annotation, if any."""

    origin = get_origin(annotation)
    args = get_args(annotation)
    if origin is None:
        return []
    if args and getattr(annotation, "__metadata__", None) is not None:
        return _literal_choices(args[0])
    if origin is Literal:
        return list(args)

    choices: list[Any] = []
    for arg in args:
        if arg is type(None):
            continue
        choices.extend(_literal_choices(arg))
    return choices


def _op_to_info(op_obj: Op) -> OpInfo:
    """Project an :class:`Op` registry record onto its public :class:`OpInfo`."""
    params: list[ParamInfo] = []
    for p in op_obj.param_signature.parameters.values():
        if p.kind in (
            inspect.Parameter.VAR_POSITIONAL,
            inspect.Parameter.VAR_KEYWORD,
        ):
            # Variadic params are excluded from the public surface — there's
            # no sensible UI for them and the plugin contract forbids *args.
            continue
        default = None if p.default is inspect.Parameter.empty else p.default
        required = p.default is inspect.Parameter.empty
        params.append(
            ParamInfo(
                name=p.name,
                type=_type_name(p.annotation),
                default=default,
                help=_param_help(p.annotation),
                required=required,
                choices=_literal_choices(p.annotation),
            )
        )
    return OpInfo(name=op_obj.name, help=op_obj.help, kind="filter", params=params)


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
    """Look up an op by name; raises ``KeyError`` if unknown.

    Triggers a one-time, idempotent import of every first-party op module
    so library callers don't have to pre-import :mod:`audiocli.ops`. The
    CLI runs its own loader, which short-circuits this on subsequent
    calls within the same process.
    """
    if name not in _REGISTRY:
        _ensure_ops_loaded(include_plugins=True)
    return _REGISTRY[name]


def list_ops(*, include_plugins: bool = True) -> list[OpInfo]:
    """Enumerate every registered op with public metadata.

    Triggers a one-time, idempotent import of every module under
    :mod:`audiocli.ops` so the registry is fully populated even if the
    caller hasn't touched the CLI. When ``include_plugins`` is true (the
    default) third-party entry-point plugins are also discovered.

    Returns:
        A list of :class:`OpInfo` records sorted by op name. The shape is
        deliberately JSON-serialisable so a future GUI can render dynamic
        UI per op without re-importing op modules.
    """
    _ensure_ops_loaded(include_plugins=include_plugins)
    return [_op_to_info(op_obj) for _, op_obj in sorted(_REGISTRY.items())]


_OPS_LOADED = False
_PLUGINS_LOADED = False


def _ensure_ops_loaded(*, include_plugins: bool) -> None:
    """Idempotently import first-party op modules (and optionally plugins).

    Called by :func:`list_ops` so library callers don't have to know about
    the registration side-effect of importing each op module. The CLI does
    its own loading via :mod:`audiocli.cli`; the flags below stop us from
    re-importing modules a second time when both paths run in the same
    process.
    """
    global _OPS_LOADED, _PLUGINS_LOADED  # noqa: PLW0603

    if not _OPS_LOADED:
        import importlib  # noqa: PLC0415
        import pkgutil  # noqa: PLC0415

        from audiocli import ops as _ops_pkg  # noqa: PLC0415

        for m in pkgutil.iter_modules(_ops_pkg.__path__):
            if m.name.startswith("_"):
                continue
            importlib.import_module(f"audiocli.ops.{m.name}")
        _OPS_LOADED = True

    if include_plugins and not _PLUGINS_LOADED:
        from audiocli.plugins import load_plugins  # noqa: PLC0415

        # Plugin import errors are surfaced to the caller; the CLI catches
        # PluginError separately for its own UX. Library callers get the
        # raw exception so they can decide how to render it.
        load_plugins()
        _PLUGINS_LOADED = True
