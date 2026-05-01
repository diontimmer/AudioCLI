Status: needs-triage
Type: AFK

# Levels & channels: `normalize`, `polarity`, `mono`, `stereo`

## Parent

`.scratch/v2-rewrite/PRD.md`

## What to build

Four filter ops that handle level and channel-shape tasks, all using the public `@op` contract from #1.

- `audiocli/ops/normalize.py`: `normalize(buf, *, peak_db: float | None = None, lufs: float | None = None) -> AudioBuffer`. Exactly one of `peak_db` / `lufs` is required. LUFS path uses `pyloudnorm`. Peak path scales so `max(abs(samples)) == 10**(peak_db/20)`.
- `audiocli/ops/polarity.py`: `polarity(buf) -> AudioBuffer` — bitwise-negates samples. Renamed from v1's `phaseflip`.
- `audiocli/ops/mono.py`: `mono(buf) -> AudioBuffer` — mixes down to 1 channel via mean.
- `audiocli/ops/stereo.py`: `stereo(buf) -> AudioBuffer` — duplicates a mono channel; passes stereo through.
- Add `pyloudnorm` to `pyproject.toml` deps.

## Acceptance criteria

- [ ] `tests/test_normalize.py::test_peak`: `normalize --peak-db -1` → `max(abs(samples))` within ±0.001 of `10**(-1/20)`
- [ ] `tests/test_normalize.py::test_lufs`: `normalize --lufs -14` on `test_song.wav` → measured integrated LUFS within ±0.5 of -14
- [ ] `tests/test_normalize.py::test_either_or`: passing both `--peak-db` and `--lufs`, or neither, raises a clean `OpError`
- [ ] `tests/test_polarity.py`: `polarity` produces exactly `-1 * input_samples`
- [ ] `tests/test_mono.py`: stereo input → 1 channel; mono input passes through; sr unchanged
- [ ] `tests/test_stereo.py`: mono input → 2 channels (duplicated); stereo input passes through; sr unchanged
- [ ] All four ops have round-trip + correctness + negative tests as described in the PRD

## Blocked by

- #01 — Tracer bullet: end-to-end spine with `gain` op
