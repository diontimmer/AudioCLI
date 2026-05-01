"""Tests for the plugin entry-point system.

We synthesize plugin packages by writing a Python module to a tmp dir,
adding it to ``sys.path``, and monkeypatching
``audiocli.plugins.entry_points`` to return :class:`importlib.metadata.EntryPoint`
objects pointing at those modules. This exercises every code path of
``load_plugins`` (import, validate, register, conflict-resolve) without
shelling out to ``pip install``, which would be too slow for a unit test
and would pollute the global site-packages.
"""

from __future__ import annotations

import sys
import textwrap
from importlib.metadata import EntryPoint
from pathlib import Path

import pytest
import typer
from typer.testing import CliRunner

# Importing `audiocli.cli` triggers `_register_commands()` which loads every
# first-party op into `_REGISTRY`. Tests below depend on that snapshot, so we
# import it eagerly at module-load time rather than lazily inside each test.
import audiocli.cli  # noqa: F401
import audiocli.plugins as plugins_mod
from audiocli.errors import PluginError
from audiocli.registry import _REGISTRY


@pytest.fixture
def plugin_workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Provide a tmp dir on ``sys.path`` and a registry snapshot/restore."""
    monkeypatch.syspath_prepend(str(tmp_path))
    # Snapshot the registry so plugin-test pollution can't leak across tests.
    snapshot = dict(_REGISTRY)
    yield tmp_path
    _REGISTRY.clear()
    _REGISTRY.update(snapshot)
    # Drop any modules we created so pytest re-discovers a fresh module on
    # subsequent tests if a name is reused.
    for name in list(sys.modules):
        if name.startswith("_audiocli_test_plugin_"):
            del sys.modules[name]


def _write_plugin(workspace: Path, module_name: str, body: str) -> None:
    (workspace / f"{module_name}.py").write_text(textwrap.dedent(body))


def _ep(name: str, value: str) -> EntryPoint:
    return EntryPoint(name=name, value=value, group=plugins_mod.ENTRY_POINT_GROUP)


def _patch_entry_points(monkeypatch: pytest.MonkeyPatch, eps: list[EntryPoint]) -> None:
    """Replace ``audiocli.plugins.entry_points`` with a fake returning ``eps``."""

    class _FakeEntryPoints:
        def select(self, group: str | None = None) -> list[EntryPoint]:
            if group is None:
                return list(eps)
            return [e for e in eps if e.group == group]

    monkeypatch.setattr(plugins_mod, "entry_points", lambda: _FakeEntryPoints())


def test_discovery_invokes_plugin_op(
    plugin_workspace: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A discovered plugin op is registered and invokable as an `audiocli` subcommand."""
    _write_plugin(
        plugin_workspace,
        "_audiocli_test_plugin_silence",
        """
        from audiocli import op, AudioBuffer

        @op(name="silence", help="Zero the buffer (test plugin).")
        def silence(buf: AudioBuffer) -> AudioBuffer:
            import numpy as np
            return AudioBuffer(
                data=np.zeros_like(buf.data),
                sr=buf.sr,
                subtype=buf.subtype,
            )
        """,
    )
    _patch_entry_points(
        monkeypatch,
        [_ep("silence", "_audiocli_test_plugin_silence:silence")],
    )

    registered, conflicts = plugins_mod.load_plugins()

    assert conflicts == []
    assert [op.name for op in registered] == ["silence"]
    assert "silence" in _REGISTRY

    # Build a fresh Typer app exposing only the plugin op so we can assert
    # end-to-end CLI behaviour without re-importing `audiocli.cli`.
    from audiocli.cli import _make_command

    app = typer.Typer(no_args_is_help=True)

    @app.callback()
    def _root() -> None:
        """Force subcommand mode."""

    app.command(name="silence")(_make_command(_REGISTRY["silence"]))

    # Write a 1-sample WAV the op can run on.
    import numpy as np

    from audiocli.buffer import AudioBuffer
    from audiocli.io import load, save

    src = tmp_path / "src.wav"
    save(src, AudioBuffer(data=np.ones((1, 64), dtype=np.float32) * 0.5, sr=16000))

    out = tmp_path / "out.wav"
    runner = CliRunner()
    result = runner.invoke(app, ["silence", "--target", str(src), "--output", str(out)])
    assert result.exit_code == 0, result.output
    assert out.exists()
    assert float(np.max(np.abs(load(out).data))) == 0.0


def test_conflict_first_party_wins(
    plugin_workspace: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A plugin op named after a first-party op loses; conflict is reported."""
    # Make sure the first-party `gain` op is in the registry before we run.
    import audiocli.ops.gain as first_party_gain  # noqa: F401

    first_party_func = _REGISTRY["gain"].func

    _write_plugin(
        plugin_workspace,
        "_audiocli_test_plugin_gain_conflict",
        """
        from audiocli import op, AudioBuffer

        @op(name="gain", help="Imposter gain (should be shadowed).")
        def imposter(buf: AudioBuffer) -> AudioBuffer:
            return buf
        """,
    )
    _patch_entry_points(
        monkeypatch,
        [_ep("gain", "_audiocli_test_plugin_gain_conflict:imposter")],
    )

    registered, conflicts = plugins_mod.load_plugins()

    assert registered == []
    assert len(conflicts) == 1
    assert conflicts[0].name == "gain"
    assert "_audiocli_test_plugin_gain_conflict" in conflicts[0].plugin_target

    # First-party op survived in the registry — no silent override.
    assert _REGISTRY["gain"].func is first_party_func


def test_malformed_signature_missing_buf(
    plugin_workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A plugin without a `buf` parameter raises PluginError naming the package."""
    _write_plugin(
        plugin_workspace,
        "_audiocli_test_plugin_no_buf",
        """
        from audiocli import AudioBuffer

        def broken(x: int) -> AudioBuffer:
            raise NotImplementedError
        """,
    )
    _patch_entry_points(
        monkeypatch,
        [_ep("broken", "_audiocli_test_plugin_no_buf:broken")],
    )

    with pytest.raises(PluginError) as excinfo:
        plugins_mod.load_plugins()

    msg = str(excinfo.value)
    assert "buf" in msg
    assert "_audiocli_test_plugin_no_buf" in msg or "broken" in msg


def test_non_filter_signature_rejected(
    plugin_workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A plugin returning ``list[AudioBuffer]`` is rejected at startup (filter-only in v2.0)."""
    _write_plugin(
        plugin_workspace,
        "_audiocli_test_plugin_multi",
        """
        from audiocli import AudioBuffer

        def split(buf: AudioBuffer) -> list[AudioBuffer]:
            return [buf, buf]
        """,
    )
    _patch_entry_points(
        monkeypatch,
        [_ep("split", "_audiocli_test_plugin_multi:split")],
    )

    with pytest.raises(PluginError) as excinfo:
        plugins_mod.load_plugins()

    assert "AudioBuffer" in str(excinfo.value)


def test_optional_dep_failure_raises_at_startup(
    plugin_workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A plugin importing a missing dep fails at startup, not at op-invocation."""
    _write_plugin(
        plugin_workspace,
        "_audiocli_test_plugin_missing_dep",
        """
        import this_module_does_not_exist_anywhere  # noqa: F401

        from audiocli import op, AudioBuffer

        @op(name="brokenimport", help="never runs")
        def brokenimport(buf: AudioBuffer) -> AudioBuffer:
            return buf
        """,
    )
    _patch_entry_points(
        monkeypatch,
        [_ep("brokenimport", "_audiocli_test_plugin_missing_dep:brokenimport")],
    )

    with pytest.raises(PluginError) as excinfo:
        plugins_mod.load_plugins()

    msg = str(excinfo.value)
    assert "_audiocli_test_plugin_missing_dep" in msg
    assert "this_module_does_not_exist_anywhere" in msg


def test_public_api_imports() -> None:
    """`from audiocli import op, AudioBuffer` works without any other imports."""
    from audiocli import AudioBuffer, PluginError, op

    assert op is not None
    assert AudioBuffer is not None
    assert issubclass(PluginError, Exception)
