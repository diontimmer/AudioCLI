Status: needs-triage
Type: AFK

# Multi-format I/O + `convert` + `bitdepth`

## Parent

`.scratch/v2-rewrite/PRD.md`

## What to build

Extend `audiocli/io.py` from WAV-only (#1) to the full pedalboard format set, preserve subtype information through round-trips, and expose two ops that exercise it.

- `audiocli/io.py`: `load`/`save` handle WAV, FLAC, MP3, OGG via `pedalboard.io.AudioFile`. `subtype` field on `AudioBuffer` is populated on load (`PCM_16`, `PCM_24`, `PCM_32`, `FLOAT`, format-specific values for compressed formats) and respected on save.
- `audiocli/ops/convert.py`: `convert(buf, *, format: str, bitdepth: int | None = None) -> AudioBuffer` — sets the output format and optionally the bitdepth for formats that support it. Output filename extension changes to match.
- `audiocli/ops/bitdepth.py`: `bitdepth(buf, *, bits: int) -> AudioBuffer` — sets the output subtype for the next save (8/16/24/32). On reload, the subtype is the requested one.
- Save path: when an op returns a buffer with a different `subtype` than the input, the save respects it. When `convert` changes the format, the file extension on disk changes accordingly.

## Acceptance criteria

- [ ] `tests/test_io.py::test_wav_roundtrip`: 16-bit, 24-bit, 32-bit float WAV; mono and stereo; subtype preserved on reload
- [ ] `tests/test_io.py::test_flac_roundtrip`: lossless round-trip — sample-exact within FLAC's bitdepth
- [ ] `tests/test_io.py::test_mp3_roundtrip`: lossy — assert sr/channels/duration preserved, peak within reasonable tolerance
- [ ] `tests/test_io.py::test_ogg_roundtrip`: same shape as MP3 test
- [ ] `tests/test_io.py::test_corrupt_load`: corrupt file raises `LoadError`
- [ ] `tests/test_convert.py`: `convert --format flac` on a WAV produces a `.flac` file, reloadable, sr/channels match
- [ ] `tests/test_bitdepth.py`: `bitdepth 16` on a 24-bit WAV produces a file whose reloaded subtype is `PCM_16`
- [ ] No format-specific branching in op code — all of it lives in `audiocli/io.py`

## Blocked by

- #01 — Tracer bullet: end-to-end spine with `gain` op
