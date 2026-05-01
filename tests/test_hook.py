"""Tests for the ``hook`` command — Python escape hatch."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from typer.testing import CliRunner

from audiocli.buffer import AudioBuffer
from audiocli.cli import app
from audiocli.errors import AudioCLIError, OpError
from audiocli.hook import (
    load_hook_function,
    make_hook_op,
    parse_extra_kwargs,
)
from audiocli.io import load, save

DATA = Path(__file__).parent / "data" / "test_song.wav"


def _make_src(tmp_path: Path) -> Path:
    sr = 44100
    src = AudioBuffer(
        data=(np.sin(np.linspace(0, 4 * np.pi, sr)) * 0.25).astype(np.float32)[None, :],
        sr=sr,
        subtype="PCM_24",
    )
    src_path = tmp_path / "src.wav"
    save(src_path, src)
    return src_path


def _write_script(tmp_path: Path, body: str, name: str = "hook_script.py") -> Path:
    script = tmp_path / name
    script.write_text(body)
    return script


# --- unit tests on the loader & helpers ---------------------------------


def test_load_hook_function_default_names(tmp_path):
    script = _write_script(
        tmp_path,
        "def transform(buf):\n    return buf\n",
    )
    fn = load_hook_function(script)
    assert fn.__name__ == "transform"


def test_load_hook_function_falls_back_to_process(tmp_path):
    script = _write_script(
        tmp_path,
        "def process(buf):\n    return buf\n",
    )
    fn = load_hook_function(script)
    assert fn.__name__ == "process"


def test_load_hook_function_explicit_name(tmp_path):
    script = _write_script(
        tmp_path,
        "def my_thing(buf):\n    return buf\n",
    )
    fn = load_hook_function(script, "my_thing")
    assert fn.__name__ == "my_thing"


def test_load_hook_function_missing_named_func(tmp_path):
    script = _write_script(tmp_path, "def transform(buf):\n    return buf\n")
    with pytest.raises(OpError, match="no function named 'nope'"):
        load_hook_function(script, "nope")


def test_load_hook_function_missing_script(tmp_path):
    with pytest.raises(AudioCLIError, match="not found"):
        load_hook_function(tmp_path / "nope.py")


def test_load_hook_function_no_default_funcs(tmp_path):
    script = _write_script(tmp_path, "x = 1\n")
    with pytest.raises(OpError, match="defines none of"):
        load_hook_function(script)


def test_load_hook_function_import_error(tmp_path):
    script = _write_script(tmp_path, "raise RuntimeError('boom')\n")
    with pytest.raises(OpError, match="failed to import"):
        load_hook_function(script)


def test_parse_extra_kwargs_equals_form():
    out = parse_extra_kwargs(["--gain-db=6", "--name=foo", "--enabled=true"])
    assert out == {"gain_db": 6, "name": "foo", "enabled": True}


def test_parse_extra_kwargs_space_form():
    out = parse_extra_kwargs(["--gain-db", "6.5", "--mode", "peak"])
    assert out == {"gain_db": 6.5, "mode": "peak"}


def test_parse_extra_kwargs_bare_flag_is_true():
    out = parse_extra_kwargs(["--dry-run", "--db=3"])
    assert out == {"dry_run": True, "db": 3}


def test_parse_extra_kwargs_rejects_positional():
    with pytest.raises(AudioCLIError):
        parse_extra_kwargs(["positional"])


def test_make_hook_op_validates_return_type(tmp_path):
    script = _write_script(tmp_path, "def transform(buf):\n    return 42\n")
    fn = load_hook_function(script)
    op_obj = make_hook_op(fn, script)
    buf = AudioBuffer(data=np.zeros((1, 16), dtype=np.float32), sr=44100)
    with pytest.raises(OpError, match="must return an AudioBuffer"):
        op_obj.func(buf)


def test_make_hook_op_bad_signature(tmp_path):
    # Function takes no args at all → calling with buf must raise OpError.
    script = _write_script(tmp_path, "def transform():\n    return None\n")
    fn = load_hook_function(script)
    op_obj = make_hook_op(fn, script)
    buf = AudioBuffer(data=np.zeros((1, 16), dtype=np.float32), sr=44100)
    with pytest.raises(OpError, match="signature rejected"):
        op_obj.func(buf)


# --- end-to-end CLI tests ----------------------------------------------


def test_single_buffer(tmp_path):
    """Hook is invoked once per file with a single AudioBuffer."""
    src_path = _make_src(tmp_path)
    script = _write_script(
        tmp_path,
        "def transform(buf):\n    return buf\n",
    )
    out = tmp_path / "out.wav"
    runner = CliRunner()
    result = runner.invoke(
        app,
        ["hook", str(script), "--target", str(src_path), "--output", str(out)],
    )
    assert result.exit_code == 0, result.output
    assert out.exists()
    re = load(out)
    src = load(src_path)
    assert re.data.shape == src.data.shape


def test_kwargs(tmp_path):
    """Extra ``--gain-db=6`` is forwarded as ``transform(buf, gain_db=6)``."""
    src_path = _make_src(tmp_path)
    script = _write_script(
        tmp_path,
        """
import numpy as np
from audiocli.buffer import AudioBuffer

def transform(buf, gain_db=0):
    factor = float(10.0 ** (gain_db / 20.0))
    return AudioBuffer(
        data=(buf.data * factor).astype(np.float32, copy=False),
        sr=buf.sr,
        subtype=buf.subtype,
    )
""",
    )
    out = tmp_path / "gained.wav"
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "hook",
            str(script),
            "--target",
            str(src_path),
            "--output",
            str(out),
            "--gain-db=6",
        ],
    )
    assert result.exit_code == 0, result.output
    src_peak = float(np.max(np.abs(load(src_path).data)))
    out_peak = float(np.max(np.abs(load(out).data)))
    assert out_peak == pytest.approx(src_peak * 2.0, rel=0.02)


def test_named_func(tmp_path):
    """``--func transform`` finds ``def transform`` even when ``process`` is absent."""
    src_path = _make_src(tmp_path)
    script = _write_script(
        tmp_path,
        "def my_op(buf):\n    return buf\n",
    )
    out = tmp_path / "out.wav"
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "hook",
            str(script),
            "--target",
            str(src_path),
            "--output",
            str(out),
            "--func",
            "my_op",
        ],
    )
    assert result.exit_code == 0, result.output
    assert out.exists()


def test_bad_signature(tmp_path):
    """A script with the wrong return type fails per-file with a clean message."""
    src_path = _make_src(tmp_path)
    script = _write_script(
        tmp_path,
        "def transform(buf):\n    return [buf]\n",
    )
    runner = CliRunner()
    result = runner.invoke(
        app,
        ["hook", str(script), "--target", str(src_path)],
    )
    assert result.exit_code != 0
    assert "must return an AudioBuffer" in result.output or str(script) in result.output


def test_missing_script(tmp_path):
    """A nonexistent script path is rejected with a clean error."""
    src_path = _make_src(tmp_path)
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "hook",
            str(tmp_path / "nope.py"),
            "--target",
            str(src_path),
        ],
    )
    assert result.exit_code != 0


def test_missing_func_flag(tmp_path):
    """``--func`` naming a missing function fails with an OpError-derived message."""
    src_path = _make_src(tmp_path)
    script = _write_script(tmp_path, "def transform(buf):\n    return buf\n")
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "hook",
            str(script),
            "--target",
            str(src_path),
            "--func",
            "does_not_exist",
        ],
    )
    assert result.exit_code != 0
    assert "does_not_exist" in result.output
