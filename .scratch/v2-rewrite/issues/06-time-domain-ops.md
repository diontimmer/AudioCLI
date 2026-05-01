Status: needs-triage
Type: AFK

# Time-domain ops: `resample`, `pitch`, `trim`, `fade`

## Parent

`.scratch/v2-rewrite/PRD.md`

## What to build

Four filter ops covering sample-rate, pitch, silence trimming, and amplitude shaping over time. All use the public `@op` contract.

- `audiocli/ops/resample.py`: `resample(buf, *, sr: int) -> AudioBuffer` via `pedalboard.Resample` (libsamplerate / "Secret Rabbit Code").
- `audiocli/ops/pitch.py`: `pitch(buf, *, semitones: float) -> AudioBuffer` via `pedalboard.PitchShift`. Thread-safe (per PRD), no `--workers 1` special-case needed.
- `audiocli/ops/trim.py`: `trim(buf, *, head: bool = True, tail: bool = True, threshold_db: float = -60.0) -> AudioBuffer` — strips leading and/or trailing silence below the threshold (RMS over short windows).
- `audiocli/ops/fade.py`: `fade(buf, *, fade_in_s: float = 0.0, fade_out_s: float = 0.0, shape: Literal["linear", "exp", "cosine"] = "linear") -> AudioBuffer`.

## Acceptance criteria

- [ ] `tests/test_resample.py::test_correctness`: `resample --sr 22050` on a 44.1kHz file → frame count is `original_frames * 22050/44100` (within ±2 frames for filter delay)
- [ ] `tests/test_resample.py::test_quality`: a 1kHz sine resampled 44100→22050→44100 has THD < 0.1% (libsamplerate is high-quality)
- [ ] `tests/test_pitch.py`: `pitch --semitones 12` on a known-frequency tone produces a tone at ~2× the input frequency (FFT peak check)
- [ ] `tests/test_trim.py`: input with 0.5s silence prepended → trimmed output starts within 5ms of the original audio; tail-only and head-only modes work independently
- [ ] `tests/test_fade.py::test_linear`: `fade --in 0.1 --shape linear` → first sample == 0, sample at 0.1s == max input level (within ±0.001)
- [ ] `tests/test_fade.py::test_shapes`: linear/exp/cosine all produce monotonically increasing fade-in envelopes
- [ ] All four ops have round-trip + correctness + negative tests

## Blocked by

- #01 — Tracer bullet: end-to-end spine with `gain` op
