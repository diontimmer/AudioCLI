# Plugins & hooks

AudioCLI has two extension paths:

- **Plugins** — pip-installable packages that register new ops via Python entry-points. The op appears as a first-class CLI subcommand and shows up in the GUI's Tools pane.
- **Hooks** — one-off Python files you run with `audiocli hook`, no packaging required.

Use a hook for experiments. Promote to a plugin once you want the op to be a permanent part of someone's installation.

## Hooks

```python title="my_transform.py"
from audiocli import AudioBuffer

def transform(buf: AudioBuffer, custom_key: str = "") -> AudioBuffer:
    return AudioBuffer(data=buf.data * 0.5, sr=buf.sr, subtype=buf.subtype)
```

```shell
audiocli hook ./my_transform.py --target ./stems --custom-key value
```

The hook file must export a function named `transform` matching the filter shape: `(buf: AudioBuffer, **params) -> AudioBuffer`. Any extra `--key value` flags on the CLI get forwarded as keyword arguments.

You can also run hooks from a chain in the GUI via the **External Script → Python Hook Script** capability.

## Plugins

A plugin is a regular pip-installable package that registers ops via the `audiocli.ops` entry-point group.

### Minimum viable plugin

```python title="my_plugin/ops.py"
from audiocli import op, AudioBuffer

@op(name="reverse", help="Reverse the audio along the time axis.")
def reverse(buf: AudioBuffer) -> AudioBuffer:
    return AudioBuffer(data=buf.data[:, ::-1], sr=buf.sr, subtype=buf.subtype)
```

```toml title="my_plugin/pyproject.toml"
[project]
name = "audiocli-plugin-reverse"
version = "0.1.0"
dependencies = ["audiocli>=2"]

[project.entry-points."audiocli.ops"]
reverse = "my_plugin.ops:reverse"
```

```shell
pip install audiocli-plugin-reverse
audiocli reverse --target ./stems   # appears as a first-class command
```

That's the whole contract. No subclassing, no registration boilerplate. The `@op` decorator captures metadata; the entry-point makes the op discoverable at startup.

### Declaring parameters

Type-annotate the function — AudioCLI builds the CLI/GUI parameter UI from the signature.

```python
from typing import Annotated
from audiocli import op, AudioBuffer

@op(name="vinyl", help="Apply lo-fi vinyl coloration.")
def vinyl(
    buf: AudioBuffer,
    dust_level: Annotated[float, "How much surface noise to add"] = 0.1,
    wow_hz: Annotated[float, "Wow modulation rate in Hz"] = 0.5,
    flutter_amount: Annotated[float, "Flutter depth, 0-1"] = 0.3,
) -> AudioBuffer:
    ...
```

Each annotated parameter becomes a `--dust-level`, `--wow-hz`, `--flutter-amount` CLI flag (kebab-cased) and a labeled GUI field. The annotation string becomes the help text and tooltip. Defaults make the param optional; un-defaulted params become required flags.

Supported parameter types: `int`, `float`, `str`, `bool`, `pathlib.Path`, and `typing.Literal[...]` for enums.

### Op shape

The base contract is a pure filter:

```python
def my_op(buf: AudioBuffer, **params) -> AudioBuffer:
    ...
```

In AudioCLI 2.0, **only filter-shape ops can be plugins.** First-party special-case ops — `info` (analysis), `chunk` (multi-output), `remove-silent` (side-effect), `vst` (external host) — bypass the plugin contract because their shapes can't fit cleanly into `(buf) -> buf`. The plugin contract may broaden in 2.1+; until then, multi-output and analysis plugins aren't supported.

### Name collisions

If your plugin's op name collides with a first-party op, **the first-party op wins** and the collision is logged at startup. Pick distinctive names — prefixing with your project name (`acme-reverse`) is fine.

### Validation errors

A malformed op signature raises `PluginError` at registration time, not at run time. This means a broken plugin won't silently disappear — `audiocli --help` will surface the error so you can fix it. Common causes:

- The decorated function doesn't accept `AudioBuffer` as its first positional argument.
- A non-default parameter has no type annotation.
- The annotated type isn't supported (e.g. a custom class instead of `int`/`float`/`str`/`bool`/`Path`/`Literal`).

### Distribution

Standard PyPI publish flow. Users install with `pip install audiocli-plugin-<name>` and your op shows up in the next `audiocli` invocation. The CLI/GUI rediscover entry-points on every start — no cache, no config, no `audiocli register` step.

## Where to file plugin issues

If a plugin behaves correctly under a direct Python import but fails through `audiocli`, the bug is probably in AudioCLI's plugin loader or capability projection. File against [diontimmer/AudioCLI](https://github.com/diontimmer/AudioCLI/issues). For everything else, file against the plugin's own repo.
