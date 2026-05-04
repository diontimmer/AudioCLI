## Agent skills

### Issue tracker

Issues for this repo live as local markdown files under `.scratch/<feature>/`. See `docs/agents/issue-tracker.md`.

### Triage labels

Default triage label vocabulary (`needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`). See `docs/agents/triage-labels.md`.

### Domain docs

Single-context repo — one `CONTEXT.md` and `docs/adr/` at the repo root. See `docs/agents/domain.md`.

## Architecture context

This is the first v2 version. Prefer clean internal module shape over preserving old private import paths or compatibility shims unless a public README/API contract says otherwise.

- `audiocli.cli` is the Typer composition root: dynamic op registration, shell/hook/run-script wiring, and command setup.
- `audiocli.pipeline` owns per-file execution and cancellation. It delegates event protocol details to `audiocli.events`, output paths to `audiocli.destinations`, and worker-count policy to `audiocli.workers`.
- `audiocli.output` renders pipeline events and reports for the CLI (`--json` newline-delimited events or Rich progress).
- First-party commands that do not fit the plugin filter contract live under `audiocli.commands`. Their reusable domain logic lives in `audiocli.analysis`, `audiocli.silence`, and `audiocli.chunking`.
- `audiocli.registry` and `audiocli.plugins` own the public plugin surface. Plugin ops stay filter-shaped: `(AudioBuffer, **params) -> AudioBuffer`.

## Verification

Before committing broad changes, run:

```shell
ruff check .
ruff format --check .
pytest -q
```
