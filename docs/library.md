# Library API

Everything the CLI and GUI do is reachable from Python. No subprocess shelling, no parsing CLI output — `audiocli` is a real library with typed metadata, structured events, and cancellation.

## Quick start

```python
from audiocli import run_per_file, list_ops, get_op

# Enumerate registered ops with full param metadata
for op in list_ops():
    print(op.name, [p.name for p in op.params])

# Drive a batch from Python with a progress callback
gain = get_op("gain")
report = run_per_file(
    ["song1.wav", "song2.wav"],
    gain,
    {"db": 6.0},
    output="./out",
    workers=4,
    on_event=lambda evt: print(evt),
)
print(report.ok_count, "ok,", report.failed_count, "failed")
```

## The op registry

`list_ops()` returns a tuple of frozen `OpInfo` dataclasses:

```python
@dataclass(frozen=True)
class ParamInfo:
    name: str
    type: type  # int, float, str, bool, Path, …
    default: Any
    required: bool
    help: str


@dataclass(frozen=True)
class OpInfo:
    name: str
    help: str
    params: tuple[ParamInfo, ...]
    # …plus tags for shape (filter, multi-output, analysis, side-effect)
```

This is the same metadata that drives the CLI's `--help` output and the GUI's parameter forms. If you're building any UI on top of AudioCLI, hit `list_ops()` instead of hard-coding op lists — third-party plugins show up here automatically.

## Running batches

`run_per_file(targets, op, params, ...)` accepts:

| Argument | Description |
|---|---|
| `targets` | List of file paths or directories. Directories recurse unless `recursive=False`. |
| `op` | `OpInfo` (e.g. from `get_op("gain")`) or the underlying callable. |
| `params` | Dict of `{param_name: value}`. Validated against the op's `ParamInfo` declarations. |
| `output` | Output directory. If `None`, writes alongside each source. |
| `workers` | Parallelism. Default is `os.cpu_count()`. |
| `on_event` | Callback receiving structured event dicts (same shape as the CLI's `--json` events). |
| `cancel_token` | `threading.Event`; flip from any thread to abort. |
| `overwrite` | Whether to replace existing output files. |

Returns a `RunReport` with `ok_count`, `failed_count`, per-file errors, and total duration.

## Cancellation

```python
import threading
from audiocli import run_per_file, get_op

cancel = threading.Event()


def run_in_background():
    run_per_file(
        ["./big-folder"],
        get_op("normalize"),
        {"peak_db": -1.0},
        workers=8,
        cancel_token=cancel,
    )


worker = threading.Thread(target=run_in_background)
worker.start()

# Later, from another thread:
cancel.set()
worker.join()
```

In-flight files complete cleanly. Pending submissions skip. The returned report reflects what actually ran.

## Event protocol

`on_event` receives dicts with a `type` key:

```python
{"type": "start", "total": 12, "workers": 8}
{"type": "progress", "done": 5, "total": 12, "current": "./stems/foo.wav"}
{"type": "file_done", "path": "./stems/foo.wav", "ok": True, "error": None}
{"type": "file_done", "path": "./stems/broken.wav", "ok": False, "error": "Could not decode"}
{"type": "done", "ok": 11, "failed": 1, "duration_s": 4.2}
```

Same shape as the CLI's `--json` output, so any tooling you build for one works for both.

## Error hierarchy

All public errors descend from a single root:

```text
AudioCLIError
├── LoadError           — couldn't read or decode an input file
├── SaveError           — couldn't write an output
├── OpError             — an op raised during processing
├── PluginError         — third-party plugin failed registration or load
└── ConfigError         — bad params, invalid settings, etc.
```

No library module ever calls `print()` or `sys.exit()`. All failures are exceptions you can catch.

## Audio buffers

The op contract uses a tiny `AudioBuffer` dataclass:

```python
@dataclass
class AudioBuffer:
    data: np.ndarray  # shape (channels, samples), float32 or float64
    sr: int  # sample rate in Hz
    subtype: str  # libsndfile subtype, e.g. "PCM_24", "FLOAT"
    # …plus optional format hints
```

Filter ops take a buffer and return a buffer:

```python
from audiocli import AudioBuffer


def reverse(buf: AudioBuffer) -> AudioBuffer:
    return AudioBuffer(data=buf.data[:, ::-1], sr=buf.sr, subtype=buf.subtype)
```

Multi-output / analysis / side-effect ops have their own shapes — see the [plugins guide](plugins.md) for details.

## Module map

| Module | Role |
|---|---|
| `audiocli.cli` | Typer composition root for the `audiocli` binary. |
| `audiocli.pipeline` | Per-file execution, parallelism, cancellation. |
| `audiocli.registry` / `audiocli.plugins` | Public op registry and entry-point plugin loading. |
| `audiocli.capabilities` | GUI-ready capability descriptions projected from op metadata. |
| `audiocli.output` | Pipeline event rendering for the CLI. |
| `audiocli.gui` | Optional PySide6 desktop shell. |

Internal modules are subject to change; the public surface is what's exported from `audiocli/__init__.py`.
