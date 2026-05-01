Status: needs-triage
Type: AFK

# VST/AU hosting (`vst` command)

## Parent

`.scratch/v2-rewrite/PRD.md`

## What to build

A `vst` command that hosts any VST3 (or AU on macOS) plugin via `pedalboard.load_plugin` and applies it to each file in the batch, with parameter overrides on the command line.

- `audiocli/ops/vst.py`: `vst(buf, *, plugin_path: Path, params: list[str] = ()) -> AudioBuffer`. Loads the plugin once at registration / first use; `params` is a list of `key=value` strings parsed into the plugin's parameter dict. Type coercion matches the plugin's parameter types (float / bool / int / enum) — coerce based on the plugin's reported parameter metadata.
- CLI invocation: `audiocli vst --target ./folder --plugin-path /path/to/plugin.vst3 --param "Threshold=-12" --param "Ratio=4"`. `--param` is repeatable.
- Per-file isolation: a plugin that crashes on file N must be reported as a `Result(ok=False, ...)`, not bring down the job. Re-instantiate the plugin per file if pedalboard's hosting model requires it for safety.
- Clear errors for: missing plugin file, unloadable plugin, unknown parameter name, value that fails type coercion.

## Acceptance criteria

- [ ] `tests/test_vst.py::test_load`: hosting a known free VST3 (or a stub plugin shipped with pedalboard) succeeds and produces a non-trivially-modified buffer
- [ ] `tests/test_vst.py::test_param_override`: setting a parameter via `--param` produces a different output than the default
- [ ] `tests/test_vst.py::test_unknown_param`: unknown parameter name → `OpError` with a message naming the bad key, lists valid keys
- [ ] `tests/test_vst.py::test_bad_value`: non-coercible value → `OpError` naming the parameter and expected type
- [ ] `tests/test_vst.py::test_missing_plugin`: missing path → `OpError` with a clear filesystem error
- [ ] If no test plugin is available on a CI runner, the test is skipped (not failed) — document the skip condition

## Blocked by

- #01 — Tracer bullet: end-to-end spine with `gain` op
