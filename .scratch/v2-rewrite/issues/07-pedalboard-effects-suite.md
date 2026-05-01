Status: needs-triage
Type: AFK

# Pedalboard effects suite

## Parent

`.scratch/v2-rewrite/PRD.md`

## What to build

Ten filter ops that wrap pedalboard's effect plugins as first-party ops. Each is a thin pass-through that exposes pedalboard's parameters as Typer options. All use the public `@op` contract.

- `audiocli/ops/compress.py`: `compress(buf, *, ratio: float, threshold_db: float, attack_ms: float, release_ms: float)` → `pedalboard.Compressor`
- `audiocli/ops/limit.py`: `limit(buf, *, threshold_db: float, release_ms: float = 100.0)` → `pedalboard.Limiter`
- `audiocli/ops/highpass.py`: `highpass(buf, *, hz: float)` → `pedalboard.HighpassFilter`
- `audiocli/ops/lowpass.py`: `lowpass(buf, *, hz: float)` → `pedalboard.LowpassFilter`
- `audiocli/ops/reverb.py`: `reverb(buf, *, room_size: float = 0.5, wet: float = 0.33, dry: float = 0.4)` → `pedalboard.Reverb`
- `audiocli/ops/delay.py`: `delay(buf, *, time_s: float = 0.5, feedback: float = 0.3, mix: float = 0.5)` → `pedalboard.Delay`
- `audiocli/ops/chorus.py`, `phaser.py`, `distortion.py`, `bitcrush.py`: same wrapping pattern using their pedalboard counterparts.

Per PRD: each op runs through `pedalboard.Pedalboard([effect]).process(buf.data, buf.sr)`. The `AudioBuffer` shape (channels, samples) matches what pedalboard expects, so no transposition is needed.

## Acceptance criteria

- [ ] Each of the 10 ops has round-trip + correctness + negative tests
- [ ] Correctness tests assert *something* observably changed and matches the parameter direction:
  - `compress`: peak reduced when input exceeds threshold
  - `limit`: output peak ≤ `10**(threshold_db/20)` within ±0.001
  - `highpass 1000`: a 100Hz sine is attenuated, a 10kHz sine is not
  - `lowpass 1000`: inverse of highpass
  - `reverb`: output RMS > input RMS for a short impulse (tail energy)
  - `delay`: detectable repeat at the configured time
  - `chorus`/`phaser`/`distortion`/`bitcrush`: output differs from input in a way consistent with the effect (RMS / spectral / quantization checks)
- [ ] No op contains pedalboard-version-specific branching — fail loudly if a parameter name changes upstream
- [ ] Help text on each Typer subcommand reflects the function's docstring

## Blocked by

- #01 — Tracer bullet: end-to-end spine with `gain` op
