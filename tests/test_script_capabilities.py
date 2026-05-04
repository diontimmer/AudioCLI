"""Issue 11 coverage for hook and script capability execution paths."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from audiocli.capabilities import get_capability
from audiocli.chains import CapabilityChain
from audiocli.errors import AudioCLIError
from audiocli.gui_service import (
    execute_file_chain,
    execute_one_node_filter_chain,
    import_acli_script,
)
from audiocli.io import load
from audiocli.run_script import LineResult, ScriptReport

DATA = Path(__file__).parent / "data" / "test_song.wav"


def _copy_song(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(DATA, path)
    return path


def _write_hook(path: Path, body: str) -> Path:
    path.write_text(body)
    return path


def _identity_hook(path: Path) -> Path:
    return _write_hook(
        path,
        "def transform(buf, gain=0, label=''):\n"
        "    if gain != 2 or label != 'x':\n"
        "        raise ValueError(f'unexpected kwargs: {gain!r} {label!r}')\n"
        "    return buf\n",
    )


def test_external_script_hook_capability_discovery_and_cli_token_kwargs_validation(tmp_path):
    hook_path = _identity_hook(tmp_path / "hook.py")
    capability = get_capability("builtin.external_script.hook")

    validation = capability.validate_params(
        {
            "script_path": hook_path,
            "function_name": "transform",
            "kwargs": ["--gain=2", "--label", "x"],
        }
    )

    assert capability.operation_name == "hook"
    assert capability.metadata["loader"] == "audiocli.hook.load_hook_function"
    assert validation.valid
    assert validation.values["script_path"] == str(hook_path)
    assert validation.values["function_name"] == "transform"
    assert validation.values["kwargs"] == {"gain": 2, "label": "x"}


def test_hook_execution_via_capability_chain_uses_validated_kwargs(tmp_path):
    src = _copy_song(tmp_path / "src" / "song.wav")
    out_dir = tmp_path / "out"
    hook_path = _identity_hook(tmp_path / "hook.py")
    chain = CapabilityChain(name="hook chain")
    chain.add_node(
        "builtin.external_script.hook",
        {
            "script_path": hook_path,
            "function_name": "transform",
            "kwargs": ["--gain=2", "--label", "x"],
        },
        node_id="hook",
    )

    run = execute_file_chain(chain, [src], output_policy={"output": out_dir})

    produced = out_dir / "song.wav"
    assert run.failed_count == 0
    assert run.report.results[0].path == produced
    assert produced.exists()
    assert load(produced).sr == load(src).sr


def test_one_node_hook_missing_function_returns_structured_failures_for_each_target(tmp_path):
    src_dir = tmp_path / "src"
    first = _copy_song(src_dir / "first.wav")
    second = _copy_song(src_dir / "second.wav")
    hook_path = _write_hook(tmp_path / "hook.py", "def transform(buf):\n    return buf\n")
    chain = CapabilityChain(name="bad hook")
    chain.add_node(
        "builtin.external_script.hook",
        {"script_path": hook_path, "function_name": "missing"},
        node_id="hook",
    )

    run = execute_one_node_filter_chain(chain, [src_dir], workers=1)

    assert run.ok_count == 0
    assert run.failed_count == 2
    assert {result.path for result in run.report.results} == {first, second}
    assert all(
        "no function named 'missing'" in (result.error or "") for result in run.report.results
    )


def test_external_script_hook_missing_script_is_rejected_by_capability_validation(tmp_path):
    src = _copy_song(tmp_path / "song.wav")
    chain = CapabilityChain(name="missing hook script")
    chain.add_node(
        "builtin.external_script.hook",
        {"script_path": tmp_path / "missing.py"},
        node_id="hook",
    )

    with pytest.raises(AudioCLIError, match="path_not_found"):
        execute_file_chain(chain, [src])


def test_builtin_acli_script_capability_executes_once_at_job_scope(tmp_path, monkeypatch):
    first = _copy_song(tmp_path / "src" / "first.wav")
    second = _copy_song(tmp_path / "src" / "second.wav")
    script_path = tmp_path / "job.acli"
    script_path.write_text("gain --db 0\n")
    calls: list[Path] = []

    def fake_execute_script(step):
        calls.append(Path(step.params["script_path"]))
        return ScriptReport([LineResult(lineno=1, command="gain --db 0", ok=True)])

    monkeypatch.setattr("audiocli.gui_service._execute_acli_script_step", fake_execute_script)
    chain = CapabilityChain(name="script once")
    chain.add_node("builtin.script.acli", {"script_path": script_path}, node_id="script")

    run = execute_file_chain(chain, [tmp_path / "src"])

    assert calls == [script_path]
    assert run.ok_count == 2
    assert {result.path for result in run.report.results} == {first, second}
    assert all(not result.script_results for result in run.report.results)
    assert len(run.report.script_results) == 1
    assert run.report.script_results[0].scope == "job"
    assert run.to_view_model()["report"]["script_results"][0]["scope"] == "job"


def test_builtin_acli_script_capability_reports_job_failure_without_rerunning_per_target(
    tmp_path, monkeypatch
):
    src_dir = tmp_path / "src"
    first = _copy_song(src_dir / "first.wav")
    second = _copy_song(src_dir / "second.wav")
    script_path = tmp_path / "job.acli"
    script_path.write_text("bogus-command\n")
    calls = 0

    def fake_execute_script(step):
        nonlocal calls
        calls += 1
        return ScriptReport(
            [LineResult(lineno=1, command="bogus-command", ok=False, error="bad command")]
        )

    monkeypatch.setattr("audiocli.gui_service._execute_acli_script_step", fake_execute_script)
    chain = CapabilityChain(name="script fails")
    chain.add_node("builtin.script.acli", {"script_path": script_path}, node_id="script")

    run = execute_file_chain(chain, [src_dir])

    assert calls == 1
    assert run.failed_count == 2
    assert {failure.source_path for failure in run.report.failures} == {first, second}
    assert all(failure.failed_step_index == 1 for failure in run.report.failures)
    assert len(run.report.script_results) == 1
    assert not run.report.script_results[0].ok
    assert "script failed" in (run.report.script_results[0].error or "")


def test_builtin_acli_script_capability_executes_real_acli_script(tmp_path):
    src = _copy_song(tmp_path / "src" / "song.wav")
    script_path = tmp_path / "job.acli"
    script_path.write_text(f"info --target {src}\n")
    chain = CapabilityChain(name="real script")
    chain.add_node("builtin.script.acli", {"script_path": script_path}, node_id="script")

    run = execute_file_chain(chain, [src])

    assert run.failed_count == 0
    assert len(run.report.script_results) == 1
    assert run.report.script_results[0].ok
    assert run.report.script_results[0].report["ok_count"] == 1


def test_import_acli_script_safely_converts_simple_filters_and_wraps_unsupported(tmp_path):
    native_script = tmp_path / "native.acli"
    native_script.write_text("gain --db 0\n")
    wrapped_script = tmp_path / "wrapped.acli"
    wrapped_script.write_text("info --target somewhere.wav\n")

    native = import_acli_script(native_script, chain_id="native", chain_name="Native")
    wrapped = import_acli_script(wrapped_script, strict=True, chain_id="wrapped")

    assert native.id == "native"
    assert native.name == "Native"
    assert len(native.nodes) == 1
    assert native.nodes[0].capability_id == "builtin.filter.gain"
    assert native.to_execution_plan(validate=True).steps[0].params == {"db": 0.0}
    assert len(wrapped.nodes) == 1
    assert wrapped.nodes[0].capability_id == "builtin.script.acli"
    assert wrapped.nodes[0].params == {"script_path": str(wrapped_script), "strict": True}


def test_convert_acli_script_to_chain_alias_wraps_parse_errors(tmp_path):
    from audiocli.gui_service import convert_acli_script_to_chain

    script_path = tmp_path / "bad.acli"
    script_path.write_text("gain --db 'unterminated\n")

    chain = convert_acli_script_to_chain(script_path)

    assert len(chain.nodes) == 1
    assert chain.nodes[0].capability_id == "builtin.script.acli"
