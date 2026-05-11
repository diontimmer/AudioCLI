# Desktop GUI

`audiocli-gui` is the cross-platform desktop workspace for AudioCLI — a PySide6 app that drives the same pipeline and capability model as the CLI. It runs on macOS, Windows, and Linux.

```shell
pip install "audiocli[gui]"
audiocli-gui
```

## Workspace layout

The workspace is split into three vertical panes:

- **Tools** — the capability browser. Every first-party op and any installed plugin op appears here, grouped by category (Analysis, Multi Output, File Filter, External Plugin, External Script, Script, Built-In Filter).
- **Chain** — the ordered list of nodes that will run. Each node references a capability and carries its own configured params.
- **Parameters** — the params panel for whichever node is selected. The form layout is generated from each capability's metadata, so adding a new op gives you a parameter UI for free.

The top toolbar holds Open / Save / Import Chain / Import Script / Export Script / Refresh, and a saved-chain library dropdown under Open.

## Building a chain

1. Pick targets and an output dir from the file menu (or via the toolbar).
2. Double-click a capability in the **Tools** pane (or hit "Add to chain") to append a node.
3. Configure params in the right pane. Required fields are highlighted; validation runs as you type.
4. Hit the green play button at the bottom of the **Chain** pane to run.

## Saved chains

The toolbar's Open menu lists every saved chain in your library. Save the current chain via the disk icon. Saved chains are JSON files stored at the platformdirs user-data location, and the Import Chain / Export Script buttons round-trip between the native format and `.acli` scripts.

The library refreshes on every Open click, but you can hit Refresh in the toolbar to force a rescan if you edited a chain file directly.

## VST/AU plugins

Add an **External Plugin → VST / AU Plugin** node to host a third-party effect:

- The node accepts a `plugin_path` (absolute path to a `.vst3` bundle or `.component`).
- The GUI discovers installed plugins from conservative platform defaults — without loading native code — and offers them in a path picker:

| Platform | Scanned directories |
|---|---|
| macOS | `/Library/Audio/Plug-Ins/VST3`, `~/Library/Audio/Plug-Ins/VST3`, `/Library/Audio/Plug-Ins/Components`, `~/Library/Audio/Plug-Ins/Components` |
| Windows | `%CommonProgramFiles%\VST3`, `%LocalAppData%\Programs\Common\VST3` |
| Linux | `/usr/lib/vst3`, `/usr/local/lib/vst3`, `~/.vst3` |

- "Open Editor" launches the plugin's native editor in a **helper process**, keeping native code out of the main Qt event loop. Adjust params in the editor and they get mirrored back into the node as repeatable `key=value` entries.
- A paged, read-only parameter view in the GUI shows the current snapshot.

## File-filter nodes and destructive confirmation

Some capabilities can remove, move, rename, or overwrite files — `remove-silent`, `Name Regex Filter`, and similar **File Filter** ops. Before any chain run that contains a destructive node, the GUI shows a confirmation dialog summarizing exactly which files will be touched. You opt in explicitly per run.

## Settings

GUI settings persist alongside the CLI's at the platformdirs user-config location:

- macOS: `~/Library/Application Support/AudioCLI/`
- Windows: `%APPDATA%\AudioCLI\`
- Linux: `$XDG_CONFIG_HOME/AudioCLI/`

The library of saved chains lives in the same root.

## Theming

The GUI ships with a built-in dark theme designed for dense desktop use. The toolbar uses flat, transparent buttons that match native conventions on each platform; on hover they show a subtle white overlay highlight.

## Cancellation and progress

Long chain runs surface live progress in the run dialog. Every step emits structured events (same protocol as the CLI's `--json` mode) and a cancel button flips a [`threading.Event`](https://docs.python.org/3/library/threading.html#threading.Event) that the pipeline checks between files. In-flight files complete naturally; pending submissions skip.

## Headless / scripted use

The GUI uses the same library API as the CLI. If you want to drive AudioCLI from your own Python code without ever opening a window, see the [library guide](library.md).
