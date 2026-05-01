Status: needs-triage
Type: AFK

# First-party special-case ops: `info`, `remove-silent`, `chunk`

## Parent

`.scratch/v2-rewrite/PRD.md`

## What to build

Three ops that don't fit the public `(buf) -> buf` filter contract. Per PRD, they are first-party-only special cases in v2.0; the plugin contract may broaden in v2.1+.

- `audiocli/ops/info.py`: **analysis op**. `info(buf) -> dict` — prints sr, channels, duration, peak (dBFS), RMS (dBFS), integrated LUFS. CLI binding renders a readable table by default; `--json` emits one JSON object per file.
- `audiocli/ops/remove_silent.py`: **side-effect op**. `remove_silent(path, *, threshold_db: float = -60.0, metric: Literal["rms", "peak"] = "rms")` — deletes the file if its RMS or peak (per `metric`) is below the threshold. Reports the deletion in the `JobReport`.
- `audiocli/ops/chunk.py`: **multi-output op**. `chunk(buf, *, seconds: float, pad: bool = True, clean: bool = False) -> list[AudioBuffer]` — splits a buffer into `seconds`-long pieces. `pad` zero-pads the final chunk to `seconds`. `clean` deletes the source file after successful chunking. CLI saves each chunk with `_1`, `_2`, ... suffixes.

These ops require small extensions to the pipeline runner / save path:
- `info` results need to be emitted (table or JSON) rather than producing output files.
- `remove_silent` needs the runner to skip the save step and report deletions.
- `chunk` needs the runner to handle a list-of-buffers return and save each with a numeric suffix.

Keep these extensions narrow — a `OpKind` enum (`FILTER`, `ANALYSIS`, `SIDE_EFFECT`, `MULTI_OUTPUT`) on the `Op` dataclass, and a small switch in the runner's save step. Plugin authors continue to use `FILTER` only.

## Acceptance criteria

- [ ] `tests/test_info.py`: on `test_song.wav` returns sr/channels/duration matching ground truth; LUFS within ±0.5 of an external reference value
- [ ] `tests/test_remove_silent.py`: a folder with 3 silent files (RMS < threshold) and 2 normal files → silent files deleted, normal files untouched, `JobReport` reflects 3 deletions
- [ ] `tests/test_chunk.py::test_correctness`: `chunk --seconds 1.0` on a 3.5s file with `--pad` → 4 files, each exactly `sr` samples; without `--pad` → 4 files, last is shorter
- [ ] `tests/test_chunk.py::test_clean`: `--clean` deletes the source file after successful chunking; failure during chunking does **not** delete
- [ ] CLI: `audiocli info --target file.wav` prints a readable table; `audiocli info --target file.wav --json` emits one JSON line per file
- [ ] `OpKind` enum is internal — not exposed to plugin authors in v2.0

## Blocked by

- #02 — Parallel pipeline with error isolation
