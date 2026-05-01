Status: needs-triage
Type: AFK

# Plugin entry-point system

## Parent

`.scratch/v2-rewrite/PRD.md`

## What to build

A public plugin system via Python entry-points, so third-party packages can register ops without forking AudioCLI.

- `audiocli/plugins.py`: discovers entry-points in the `audiocli.ops` group via `importlib.metadata.entry_points(group="audiocli.ops")`. Each entry-point points at a function decorated with `@op`. Discovery happens once at startup before Typer subcommand registration.
- Public surface: `from audiocli import op, AudioBuffer` works (re-export from `audiocli/__init__.py`). Plugin authors only need `@op` and `AudioBuffer`.
- Conflict resolution: if a plugin and a first-party op share a name, the first-party op wins. The conflict is logged at startup (stderr, one line per conflict).
- Registration-time validation: a plugin function with a malformed signature (no `buf` param, non-`AudioBuffer` return type hint, `*args`/`**kwargs` in the wrong positions) raises `PluginError` at startup naming the package, entry-point, and the specific signature problem. CLI exits non-zero with a clean message.
- `audiocli/errors.py`: add `PluginError` to the public hierarchy (already declared as a placeholder in #1).
- Plugin contract is **filter-shape only** in v2.0: `(buf: AudioBuffer, **params) -> AudioBuffer`. Multi-output / analysis / side-effect ops remain first-party-only. Document this in `audiocli/__init__.py` docstring.

## Acceptance criteria

- [ ] `tests/test_plugins.py::test_discovery`: a synthetic plugin package installed via a test fixture (entry-point declared in its `pyproject.toml`) is discovered and its op is invokable as `audiocli <plugin-op-name> ...`
- [ ] `tests/test_plugins.py::test_conflict`: a plugin op with a name matching a first-party op → first-party wins, conflict logged to stderr, no crash
- [ ] `tests/test_plugins.py::test_malformed_signature`: a plugin with no `buf` parameter → `PluginError` at startup; error message names the package and the missing parameter
- [ ] `tests/test_plugins.py::test_non_filter_signature`: a plugin returning `list[AudioBuffer]` (multi-output) → `PluginError` (filter-only in v2.0)
- [ ] `tests/test_plugins.py::test_optional_deps`: a plugin that `import`s a missing dependency → `PluginError` at startup, NOT at op-invocation time, with the failing import in the message
- [ ] `from audiocli import op, AudioBuffer` works without any other imports

## Blocked by

- #01 — Tracer bullet: end-to-end spine with `gain` op
