"""Tests for the ``vst`` op.

Real VST3/AU plugins typically aren't available in CI. The bulk of these
tests therefore exercise the parsing / coercion / error paths against a
hand-rolled fake plugin and a mocked ``pedalboard.load_plugin``. The
``test_load`` happy-path test is auto-skipped when no plugin path is
configured via the ``AUDIOCLI_TEST_VST_PATH`` env var.
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest
from typer.testing import CliRunner

from audiocli.buffer import AudioBuffer
from audiocli.cli import app
from audiocli.errors import OpError
from audiocli.io import save
from audiocli.ops.vst import (
    _apply_param_overrides,
    _coerce_value,
    _parse_param_strings,
    vst,
)

# ---------------------------------------------------------------------------
# Fake plugin used to stand in for a real VST3 in unit tests.
# ---------------------------------------------------------------------------


class _FakeParamMeta:
    def __init__(self, declared_type, valid_values=None):
        self.type = declared_type
        if valid_values is not None:
            self.valid_values = valid_values


class _FakePlugin:
    """A minimal stand-in mirroring pedalboard's loaded-plugin surface."""

    def __init__(self, gain: float = 1.0):
        self._gain = gain
        self._threshold = -10.0
        self._enabled = True
        self._mode = "Soft"
        self.parameters = {
            "gain": _FakeParamMeta(float),
            "threshold": _FakeParamMeta(float),
            "enabled": _FakeParamMeta(bool),
            "mode": _FakeParamMeta(str, valid_values=["Soft", "Hard", "Off"]),
        }

    # Allow setattr-by-key like pedalboard plugin objects.
    @property
    def gain(self) -> float:
        return self._gain

    @gain.setter
    def gain(self, v: float) -> None:
        self._gain = float(v)

    @property
    def threshold(self) -> float:
        return self._threshold

    @threshold.setter
    def threshold(self, v: float) -> None:
        self._threshold = float(v)

    @property
    def enabled(self) -> bool:
        return self._enabled

    @enabled.setter
    def enabled(self, v: bool) -> None:
        self._enabled = bool(v)

    @property
    def mode(self) -> str:
        return self._mode

    @mode.setter
    def mode(self, v: str) -> None:
        self._mode = str(v)

    def process(self, data, sample_rate, reset=False):  # noqa: ARG002
        return (data * self._gain).astype(np.float32, copy=False)


def _make_buf(sr: int = 44100, dur_s: float = 0.25) -> AudioBuffer:
    n = int(sr * dur_s)
    sig = (np.sin(np.linspace(0, 4 * np.pi, n)) * 0.25).astype(np.float32)[None, :]
    return AudioBuffer(data=sig, sr=sr, subtype="PCM_24")


# ---------------------------------------------------------------------------
# _parse_param_strings
# ---------------------------------------------------------------------------


def test_parse_param_strings_happy():
    assert _parse_param_strings(["gain=2.0", "mode=Soft"]) == {"gain": "2.0", "mode": "Soft"}


def test_parse_param_strings_preserves_value_with_equals():
    # Values containing '=' (e.g. an enum literal) should survive the partition.
    assert _parse_param_strings(["expr=a=b"]) == {"expr": "a=b"}


def test_parse_param_strings_missing_equals():
    with pytest.raises(OpError, match="missing '='"):
        _parse_param_strings(["gain"])


def test_parse_param_strings_empty_key():
    with pytest.raises(OpError, match="empty key"):
        _parse_param_strings(["=5"])


# ---------------------------------------------------------------------------
# _coerce_value / _apply_param_overrides
# ---------------------------------------------------------------------------


def test_coerce_float():
    assert _coerce_value("gain", "2.5", _FakeParamMeta(float)) == pytest.approx(2.5)


def test_coerce_int():
    assert _coerce_value("n", "3", _FakeParamMeta(int)) == 3


def test_coerce_bool_truthy():
    for raw in ("true", "1", "yes", "on", "TRUE"):
        assert _coerce_value("enabled", raw, _FakeParamMeta(bool)) is True


def test_coerce_bool_falsy():
    for raw in ("false", "0", "no", "off"):
        assert _coerce_value("enabled", raw, _FakeParamMeta(bool)) is False


def test_coerce_bool_bad_value():
    with pytest.raises(OpError, match="expects a bool"):
        _coerce_value("enabled", "maybe", _FakeParamMeta(bool))


def test_coerce_enum_choice():
    meta = _FakeParamMeta(str, valid_values=["Soft", "Hard"])
    assert _coerce_value("mode", "soft", meta) == "Soft"


def test_coerce_enum_unknown():
    meta = _FakeParamMeta(str, valid_values=["Soft", "Hard"])
    with pytest.raises(OpError, match="expected one of"):
        _coerce_value("mode", "Mushy", meta)


def test_apply_overrides_unknown_param_lists_valid_keys():
    plugin = _FakePlugin()
    with pytest.raises(OpError) as excinfo:
        _apply_param_overrides(plugin, {"NoSuch": "1"})
    msg = str(excinfo.value)
    assert "NoSuch" in msg
    assert "gain" in msg and "threshold" in msg


def test_apply_overrides_bad_value_names_param_and_type():
    plugin = _FakePlugin()
    with pytest.raises(OpError) as excinfo:
        _apply_param_overrides(plugin, {"gain": "not-a-float"})
    msg = str(excinfo.value)
    assert "gain" in msg
    assert "float" in msg


def test_apply_overrides_case_insensitive_key():
    plugin = _FakePlugin()
    _apply_param_overrides(plugin, {"GAIN": "3.0"})
    assert plugin.gain == pytest.approx(3.0)


# ---------------------------------------------------------------------------
# vst() — function-level happy path with a mocked plugin loader
# ---------------------------------------------------------------------------


def _fake_plugin_path(tmp_path: Path) -> Path:
    p = tmp_path / "FakePlug.vst3"
    p.write_bytes(b"\x00")  # presence is all the op checks; loader is mocked
    return p


def test_vst_calls_loader_and_processes(tmp_path):
    plugin_path = _fake_plugin_path(tmp_path)
    fake = _FakePlugin(gain=1.0)
    buf = _make_buf()

    with patch("pedalboard.load_plugin", return_value=fake):
        out = vst(buf, plugin_path=plugin_path, params=[])

    assert out.sr == buf.sr
    assert out.data.shape == buf.data.shape
    np.testing.assert_allclose(out.data, buf.data)


def test_vst_param_override_changes_output(tmp_path):
    plugin_path = _fake_plugin_path(tmp_path)
    buf = _make_buf()

    with patch("pedalboard.load_plugin", return_value=_FakePlugin()):
        default = vst(buf, plugin_path=plugin_path, params=[])
    with patch("pedalboard.load_plugin", return_value=_FakePlugin()):
        boosted = vst(buf, plugin_path=plugin_path, params=["gain=4.0"])

    assert float(np.max(np.abs(boosted.data))) > float(np.max(np.abs(default.data))) * 2


def test_vst_unknown_param_raises_op_error(tmp_path):
    plugin_path = _fake_plugin_path(tmp_path)
    with (
        patch("pedalboard.load_plugin", return_value=_FakePlugin()),
        pytest.raises(OpError, match="unknown parameter"),
    ):
        vst(_make_buf(), plugin_path=plugin_path, params=["bogus=1"])


def test_vst_bad_value_raises_op_error(tmp_path):
    plugin_path = _fake_plugin_path(tmp_path)
    with (
        patch("pedalboard.load_plugin", return_value=_FakePlugin()),
        pytest.raises(OpError, match="float"),
    ):
        vst(_make_buf(), plugin_path=plugin_path, params=["gain=oops"])


def test_vst_missing_plugin_raises_op_error(tmp_path):
    missing = tmp_path / "NotThere.vst3"
    with pytest.raises(OpError, match="not found"):
        vst(_make_buf(), plugin_path=missing, params=[])


def test_vst_plugin_load_failure_raises_op_error(tmp_path):
    plugin_path = _fake_plugin_path(tmp_path)
    with (
        patch("pedalboard.load_plugin", side_effect=RuntimeError("bad bundle")),
        pytest.raises(OpError, match="failed to load plugin"),
    ):
        vst(_make_buf(), plugin_path=plugin_path, params=[])


# ---------------------------------------------------------------------------
# CLI integration — parse path with a mocked plugin loader
# ---------------------------------------------------------------------------


def test_cli_vst_parses_repeatable_param(tmp_path):
    src = _make_buf()
    src_path = tmp_path / "src.wav"
    save(src_path, src)

    plugin_path = _fake_plugin_path(tmp_path)
    out_path = tmp_path / "out.wav"

    with patch("pedalboard.load_plugin", return_value=_FakePlugin(gain=1.0)):
        result = CliRunner().invoke(
            app,
            [
                "vst",
                "--target",
                str(src_path),
                "--output",
                str(out_path),
                "--plugin-path",
                str(plugin_path),
                "--param",
                "gain=2.0",
                "--param",
                "enabled=true",
            ],
        )

    assert result.exit_code == 0, result.output
    assert out_path.exists()


def test_cli_vst_unknown_param_exits_nonzero(tmp_path):
    src = _make_buf()
    src_path = tmp_path / "src.wav"
    save(src_path, src)
    plugin_path = _fake_plugin_path(tmp_path)

    with patch("pedalboard.load_plugin", return_value=_FakePlugin()):
        result = CliRunner().invoke(
            app,
            [
                "vst",
                "--target",
                str(src_path),
                "--plugin-path",
                str(plugin_path),
                "--param",
                "Nope=1",
            ],
        )

    assert result.exit_code != 0


def test_cli_vst_missing_plugin_path_exits_nonzero(tmp_path):
    src = _make_buf()
    src_path = tmp_path / "src.wav"
    save(src_path, src)

    result = CliRunner().invoke(
        app,
        [
            "vst",
            "--target",
            str(src_path),
            "--plugin-path",
            str(tmp_path / "no.vst3"),
        ],
    )

    # Typer's `exists=True` rejects the path before our op runs.
    assert result.exit_code != 0


# ---------------------------------------------------------------------------
# Optional happy-path against a real plugin, only when one is configured.
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not os.environ.get("AUDIOCLI_TEST_VST_PATH"),
    reason="set AUDIOCLI_TEST_VST_PATH to a real VST3/AU bundle to exercise live hosting",
)
def test_load_real_plugin_modifies_buffer():
    plugin_path = Path(os.environ["AUDIOCLI_TEST_VST_PATH"])
    buf = _make_buf()
    out = vst(buf, plugin_path=plugin_path, params=[])
    # A non-bypassed plugin should produce something other than identity.
    assert out.data.shape[0] == buf.data.shape[0]
    assert not np.allclose(out.data, buf.data)
