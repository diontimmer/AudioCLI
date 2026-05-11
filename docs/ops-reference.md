# Ops reference

Every first-party op is listed below. Run `audiocli <command> --help` for the complete parameter list of any op.

## Gain & level

| Command | Description | Example |
|---|---|---|
| `gain` | Apply gain in decibels | `audiocli gain --target … --db 6` |
| `normalize` | Peak (dBFS) or LUFS normalization | `audiocli normalize --target … --peak-db -1` |
| `polarity` | Invert sample polarity | `audiocli polarity --target …` |

## Channels & sample rate

| Command | Description | Example |
|---|---|---|
| `mono` | Mix down to 1 channel | `audiocli mono --target …` |
| `stereo` | Duplicate mono → 2-channel stereo | `audiocli stereo --target …` |
| `resample` | Change sample rate (libsamplerate) | `audiocli resample --target … --sr 22050` |
| `pitch` | Pitch-shift in semitones | `audiocli pitch --target … --semitones -2` |

## Time domain

| Command | Description | Example |
|---|---|---|
| `trim` | Strip leading/trailing silence | `audiocli trim --target … --threshold-db -60` |
| `fade` | Fade in/out (linear, exp, cosine) | `audiocli fade --target … --fade-in-s 0.5 --shape cosine` |

## Format conversion

| Command | Description | Example |
|---|---|---|
| `convert` | Change output format (wav/flac/mp3/ogg) | `audiocli convert --target … --format flac` |
| `bitdepth` | Set output bit depth (8/16/24/32) | `audiocli bitdepth --target … --bits 24` |

## Dynamics

| Command | Description | Example |
|---|---|---|
| `compress` | Dynamic range compression | `audiocli compress --target … --ratio 4 --threshold-db -20` |
| `limit` | Peak limiting | `audiocli limit --target … --threshold-db -1` |

## Filters

| Command | Description | Example |
|---|---|---|
| `highpass` | High-pass filter | `audiocli highpass --target … --hz 80` |
| `lowpass` | Low-pass filter | `audiocli lowpass --target … --hz 8000` |
| `highshelf` | High-shelf EQ | `audiocli highshelf --target … --hz 8000 --gain-db 3` |
| `lowshelf` | Low-shelf EQ | `audiocli lowshelf --target … --hz 200 --gain-db 3` |
| `ladder` | Moog-style ladder filter | `audiocli ladder --target … --cutoff-hz 1200` |

## Modulation & space

| Command | Description | Example |
|---|---|---|
| `reverb` | Algorithmic reverb | `audiocli reverb --target … --room-size 0.6 --wet 0.3` |
| `delay` | Feedback delay | `audiocli delay --target … --time-s 0.4 --feedback 0.4` |
| `chorus` | Modulated chorus | `audiocli chorus --target … --rate-hz 1.0 --depth 0.25` |
| `phaser` | All-pass phaser | `audiocli phaser --target … --rate-hz 1.0` |
| `convolve` | Convolution reverb (IR file) | `audiocli convolve --target … --ir ./impulse.wav` |

## Distortion & lo-fi

| Command | Description | Example |
|---|---|---|
| `distortion` | Soft-clip distortion | `audiocli distortion --target … --drive-db 25` |
| `clip` | Hard clipping | `audiocli clip --target … --ceiling -3` |
| `bitcrush` | Bit-depth reduction | `audiocli bitcrush --target … --bit-depth 8` |
| `noisegate` | Noise gate | `audiocli noisegate --target … --threshold-db -50` |
| `gsm` | GSM codec coloration | `audiocli gsm --target …` |
| `mp3` | MP3 encode/decode roundtrip | `audiocli mp3 --target … --bitrate 128` |

## External plugins

| Command | Description | Example |
|---|---|---|
| `vst` | Host any VST3 / AU plugin | `audiocli vst --target … --plugin-path ./MyComp.vst3 --param Threshold=-12` |

## Multi-output / analysis / file actions

These ops have non-standard shapes (multi-output, side-effect, or read-only) and are first-party special cases.

| Command | Description | Example |
|---|---|---|
| `info` | Print sr, channels, duration, peak, RMS, LUFS | `audiocli info --target …` |
| `remove-silent` | Delete files below an RMS threshold | `audiocli remove-silent --target … --threshold-db -55` |
| `chunk` | Split files into N-second pieces | `audiocli chunk --target … --seconds 5.0` |

## Scripting & extension

| Command | Description | Example |
|---|---|---|
| `hook` | Run a one-off Python transform | `audiocli hook ./my_transform.py --target …` |
| `run-script` | Run a `.acli` batch file | `audiocli run-script ./pipeline.acli` |
| `shell` | Start the interactive REPL | `audiocli shell` |

## Common flags

All ops (except `info`, `shell`, `run-script`) accept these:

| Flag | Description |
|---|---|
| `--target PATH` | One or more input files or directories. Repeat for multiple targets. |
| `--output DIR` | Output directory. If omitted, writes alongside each source. |
| `--workers N` | Parallelism. Default is the CPU count. |
| `--recursive` / `--no-recursive` | Recurse into directory targets. Default is recursive. |
| `--overwrite` | Replace existing output files. |
| `--json` | Emit newline-delimited JSON events on stdout. |
| `--quiet` | Suppress the rich progress bar. |
