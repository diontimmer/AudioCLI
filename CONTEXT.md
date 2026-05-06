# AudioCLI Context

AudioCLI is a batch audio processing tool with a CLI and a desktop workspace GUI.
The v2 architecture favors clean internal module shape over preserving old private
import paths.

## Domain Terms

- **Capability**: A GUI-neutral description of one action AudioCLI can perform. A
  capability declares shape, safety, parameters, validation, metadata, and the
  operation name used by execution.
- **Chain**: An ordered set of capability nodes that process one or more audio
  files.
- **Chain node**: One configured capability inside a chain. A node stores the
  capability id, node id, and JSON-safe params that execution can consume.
- **Workspace**: The desktop GUI state around the current chain, selected node,
  settings, saved-chain library, import/export flows, and current run state.
- **Saved chain**: A reusable chain persisted to disk and exposed through the GUI
  library and import/export flows.
- **File-chain execution**: Running a chain over a file set, including per-file
  execution, output path policy, event reporting, cancellation, and result
  summaries.
- **Destructive confirmation**: The pre-run guard for file-filter capabilities
  that can remove, move, rename, or overwrite files.
- **External script hook**: A user-provided Python hook loaded from disk and run
  as a configured chain node.
- **VST/AU plugin node**: The external-plugin capability that loads a VST3 or AU
  effect with Pedalboard, using `plugin_path` plus repeatable `key=value`
  parameter strings.
- **Plugin discovery**: Cross-platform scanning of conventional plugin folders so
  the GUI can offer existing VST3/AU plugin paths without loading native code.
- **VST editor host**: The helper process launched by the GUI to load a selected
  VST/AU plugin and show Pedalboard's native editor outside the main Qt process.
- **Mirrored parameters**: Parameter snapshots emitted by the VST editor host and
  stored back into the selected node as AudioCLI's existing repeatable
  `key=value` strings.

## Architecture Notes

- `audiocli.cli` is the Typer composition root.
- `audiocli.pipeline` owns per-file execution and cancellation.
- `audiocli.output` renders pipeline events and reports for the CLI.
- `audiocli.registry` and `audiocli.plugins` own the public plugin surface.
- `audiocli.capabilities` projects operation metadata into GUI-ready capability
  descriptions.
- GUI modules should keep native plugin loading out of discovery, validation, and
  smoke paths. Native VST/AU code loads only when the user opens the editor or
  executes the VST/AU plugin node.
