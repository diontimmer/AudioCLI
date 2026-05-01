"""Op enumeration — issue #14.

A future GUI needs to render a dynamic UI per registered op. The library
exposes :func:`audiocli.list_ops` for that purpose; these tests pin the
shape and the parameter-metadata round-trip.
"""

from __future__ import annotations

from typing import Annotated

import typer

from audiocli import OpInfo, ParamInfo, list_ops
from audiocli.buffer import AudioBuffer
from audiocli.registry import op as op_decorator


@op_decorator(name="_test_param_op", help="Test-only op for parameter introspection.")
def _param_op(
    buf: AudioBuffer,
    cutoff: Annotated[float, typer.Option("--cutoff", help="Cutoff frequency in Hz.")] = 100.0,
    enabled: Annotated[bool, typer.Option("--enabled/--disabled", help="Toggle.")] = True,
    label: Annotated[str, typer.Option("--label", help="A label.")] = "default",
) -> AudioBuffer:
    return buf


def test_enumeration_returns_every_registered_op():
    """``list_ops()`` returns one OpInfo per registered op, sorted by name."""
    infos = list_ops()
    assert len(infos) >= 20  # 22 first-party ops at the time of writing
    assert all(isinstance(o, OpInfo) for o in infos)
    names = [o.name for o in infos]
    assert names == sorted(names)
    # First-party ops we know exist.
    for required in ("gain", "highpass", "lowpass", "trim", "fade", "convert"):
        assert required in names


def test_enumeration_includes_kind_filter_for_op_decorated():
    """Every ``@op`` registration is reported as kind='filter'."""
    infos = list_ops()
    for info in infos:
        assert info.kind == "filter"


def test_param_info_round_trip_for_typer_option_metadata():
    """An ``Annotated[float, typer.Option(help=...)]`` parameter round-trips."""
    infos = {o.name: o for o in list_ops()}
    info = infos["_test_param_op"]
    by_name = {p.name: p for p in info.params}

    cutoff = by_name["cutoff"]
    assert isinstance(cutoff, ParamInfo)
    assert cutoff.type == "float"
    assert cutoff.default == 100.0
    assert cutoff.help == "Cutoff frequency in Hz."
    assert cutoff.required is False

    enabled = by_name["enabled"]
    assert enabled.type == "bool"
    assert enabled.default is True
    assert enabled.help == "Toggle."

    label = by_name["label"]
    assert label.type == "str"
    assert label.default == "default"


def test_first_party_op_param_info_has_help_text():
    """A real first-party op (``highpass``) reports its typer help string."""
    infos = {o.name: o for o in list_ops()}
    hp = infos["highpass"]
    by_name = {p.name: p for p in hp.params}
    assert by_name["hz"].type == "float"
    assert "Cutoff frequency" in by_name["hz"].help


def test_list_ops_is_idempotent():
    """Calling list_ops() repeatedly does not re-import or grow the registry."""
    a = list_ops()
    b = list_ops()
    assert {o.name for o in a} == {o.name for o in b}


def test_op_info_is_json_serialisable():
    """The OpInfo dataclass projects cleanly through ``dataclasses.asdict``."""
    import dataclasses
    import json

    infos = list_ops()
    payload = [dataclasses.asdict(o) for o in infos]
    # Must serialise without TypeError — strings/ints/bools/floats/None only.
    blob = json.dumps(payload)
    assert "gain" in blob
