"""Plugin discovery via Python entry-points.

Third-party packages register ops by declaring entries in the
``audiocli.ops`` entry-point group::

    [project.entry-points."audiocli.ops"]
    my-op = "my_package.module:my_op"

At startup, AudioCLI iterates ``importlib.metadata.entry_points(group=...)``,
loads each target, and validates that it is a function decorated with
``@op`` whose signature matches the v2.0 plugin contract — a *filter*:

    (buf: AudioBuffer, **params) -> AudioBuffer

Conflicts with first-party ops are resolved in favour of the first-party op
and reported via the ``conflicts`` list returned from :func:`load_plugins`.
Malformed signatures and import failures raise :class:`PluginError` at
startup so problems surface immediately, not on first invocation.
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass
from importlib.metadata import EntryPoint, entry_points

from audiocli.buffer import AudioBuffer
from audiocli.errors import PluginError
from audiocli.registry import Op, all_ops

ENTRY_POINT_GROUP = "audiocli.ops"


@dataclass
class PluginConflict:
    """A plugin op whose name collided with a first-party op.

    The first-party op wins; the plugin op is dropped. The CLI logs one
    line per conflict to stderr at startup.
    """

    name: str
    plugin_dist: str
    plugin_target: str


def _entry_point_dist_name(ep: EntryPoint) -> str:
    """Best-effort distribution name for an entry-point, for error messages."""
    dist = getattr(ep, "dist", None)
    if dist is not None:
        meta_name = getattr(dist, "name", None) or getattr(dist, "metadata", {}).get("Name")
        if meta_name:
            return str(meta_name)
    return ep.value.split(":", 1)[0]


def _validate_filter_signature(func: object, ep: EntryPoint) -> None:
    """Enforce the v2.0 filter contract on a plugin function.

    Raises :class:`PluginError` with a message that names the package, the
    entry-point, and the specific signature problem.
    """
    dist_name = _entry_point_dist_name(ep)
    location = f"plugin {dist_name!r} entry-point {ep.name!r} ({ep.value})"

    if not callable(func):
        raise PluginError(f"{location} is not callable")

    try:
        sig = inspect.signature(func, eval_str=True)
    except (TypeError, ValueError) as e:
        raise PluginError(f"{location}: cannot inspect signature ({e})") from e

    params = list(sig.parameters.values())
    if not params:
        raise PluginError(f"{location}: missing required first parameter 'buf: AudioBuffer'")

    first = params[0]
    if first.kind in (
        inspect.Parameter.VAR_POSITIONAL,
        inspect.Parameter.VAR_KEYWORD,
        inspect.Parameter.KEYWORD_ONLY,
    ):
        raise PluginError(
            f"{location}: first parameter must be a positional 'buf: AudioBuffer', "
            f"got {first.kind.description} {first.name!r}"
        )

    if first.name != "buf":
        raise PluginError(f"{location}: first parameter must be named 'buf' (got {first.name!r})")

    if first.annotation is not inspect.Parameter.empty and first.annotation is not AudioBuffer:
        raise PluginError(
            f"{location}: parameter 'buf' must be annotated as AudioBuffer "
            f"(got {first.annotation!r})"
        )

    # `*args` is incompatible with the keyword-driven CLI binding.
    for p in params[1:]:
        if p.kind is inspect.Parameter.VAR_POSITIONAL:
            raise PluginError(f"{location}: variadic *{p.name} is not allowed in plugin ops")

    if sig.return_annotation is inspect.Signature.empty:
        raise PluginError(f"{location}: missing return type annotation; must be -> AudioBuffer")

    if sig.return_annotation is not AudioBuffer:
        raise PluginError(
            f"{location}: return type must be AudioBuffer "
            f"(got {sig.return_annotation!r}); multi-output ops are first-party-only in v2.0"
        )


def _iter_entry_points() -> list[EntryPoint]:
    """Return the entry-points registered under our group, across Python versions."""
    eps = entry_points()
    # Python 3.10+: EntryPoints object with `.select(group=...)`.
    select = getattr(eps, "select", None)
    if select is not None:
        return list(select(group=ENTRY_POINT_GROUP))
    # Older fallback (dict-like API).
    return list(eps.get(ENTRY_POINT_GROUP, []))  # type: ignore[union-attr]


def load_plugins() -> tuple[list[Op], list[PluginConflict]]:
    """Discover and register every plugin op.

    Returns a tuple of ``(registered_ops, conflicts)``:

    * ``registered_ops`` — :class:`Op` records for plugins that won
      registration (i.e. didn't collide with a first-party op).
    * ``conflicts`` — :class:`PluginConflict` records for plugin ops that
      were dropped because a first-party op already owns the name.

    Raises :class:`PluginError` if any entry-point fails to import or has a
    signature that doesn't match the v2.0 filter contract.
    """
    # Snapshot first-party ops *before* any plugin import runs. Importing a
    # plugin module triggers any module-level `@op(...)` decorations, which
    # would otherwise overwrite first-party entries in `_REGISTRY` silently.
    first_party_snapshot = dict(all_ops())
    registered: list[Op] = []
    conflicts: list[PluginConflict] = []

    from audiocli.registry import _REGISTRY  # noqa: PLC0415

    for ep in _iter_entry_points():
        dist_name = _entry_point_dist_name(ep)
        try:
            target = ep.load()
        except Exception as e:  # ImportError, AttributeError, ModuleNotFoundError, ...
            raise PluginError(
                f"plugin {dist_name!r} entry-point {ep.name!r} ({ep.value}) "
                f"failed to import: {e.__class__.__name__}: {e}"
            ) from e

        _validate_filter_signature(target, ep)

        # If the function wasn't decorated with @op, decorate it now using the
        # entry-point name so plugin authors can write a plain function.
        op_obj: Op | None = getattr(target, "__op__", None)
        if op_obj is None:
            from audiocli.registry import op as op_decorator  # noqa: PLC0415

            op_decorator(name=ep.name)(target)
            op_obj = target.__op__  # type: ignore[attr-defined]

        if op_obj.name in first_party_snapshot:
            conflicts.append(
                PluginConflict(
                    name=op_obj.name,
                    plugin_dist=dist_name,
                    plugin_target=ep.value,
                )
            )
            # Restore first-party ownership in case the plugin's @op decorator
            # already overwrote the registry entry at import time.
            _REGISTRY[op_obj.name] = first_party_snapshot[op_obj.name]
            continue

        registered.append(op_obj)

    return registered, conflicts
