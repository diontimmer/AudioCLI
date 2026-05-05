# AudioCLI GUI packaging risk register

Status: living notes for the macOS-first packaging spike.

## Risks

### Bundle size

Risk: PySide6/Qt frameworks, numpy, and pedalboard native wheels can make the app
large.

Mitigation:
- Measure compressed and uncompressed artifact sizes for each candidate.
- Do not enforce a size threshold until maintainer picks one.

### PySide6 / Qt framework inclusion

Risk: packagers can miss Qt plugins, platform plugins, image plugins, or runtime
libraries, causing launch failures only after bundling.

Mitigation:
- Packaged entrypoint smoke must run.
- Native GUI launch smoke must construct/show the main window.
- Keep PySide6 imports lazy so static smoke can isolate dependency issues.

### numpy native wheel inclusion

Risk: compiled numpy libraries may be omitted or architecture-mismatched.

Mitigation:
- Record Python and machine architecture in smoke output.
- Run normal processing smoke with a simple Gain chain.

### pedalboard native wheel inclusion

Risk: pedalboard includes native code and plugin-hosting behavior. Bundling may
miss libraries or fail on architecture mismatches.

Mitigation:
- Import pedalboard as part of full source/native test suite.
- Keep plugin bundle scanning separate from plugin loading.
- Use `AUDIOCLI_TEST_VST_PATH` for explicit live plugin smoke only.

### VST3/AU plugin discovery

Risk: recursive filesystem scans are slow, noisy, and unsafe. Broken plugins can
crash when loaded.

Mitigation:
- Scan only fixed macOS directories:
  - `/Library/Audio/Plug-Ins/VST3`
  - `~/Library/Audio/Plug-Ins/VST3`
  - `/Library/Audio/Plug-Ins/Components`
  - `~/Library/Audio/Plug-Ins/Components`
- Enumerate bundle paths only; never load discovered plugins during default smoke.
- Skip hidden entries, symlinks, and nested bundles.

### Code signing and notarization

Risk: unsigned apps can trigger Gatekeeper/quarantine warnings. Native plugin
hosting may need hardened-runtime entitlement decisions later.

Mitigation:
- Signing/notarization is deferred for this spike.
- Record all warnings and commands needed to launch unsigned artifacts.
- Treat signing and notarization as follow-up release tasks after packager choice.

### macOS architecture mismatch

Risk: arm64 vs x86_64 Python, Qt, pedalboard, and plugin bundles can mismatch.

Mitigation:
- Record `platform.machine()` and Python architecture in every smoke result.
- Test on target architecture before recommending a release path.

### Plugin crash isolation

Risk: third-party plugin code runs in-process through pedalboard and can crash or
hang the packaged app.

Mitigation:
- GUI metadata marks VST/AU nodes as external native-code risk.
- Default plugin discovery never loads plugin code.
- Future release task: separate plugin host process if stability becomes required.

### Cross-platform follow-up

Risk: macOS findings do not automatically transfer to Windows/Linux.

Mitigation:
- Keep this spike macOS-first.
- Add native Windows/Linux package spikes later with platform-specific smoke docs.

## Decision gates

Before installer polish:

1. Native macOS packaged artifact starts.
2. Capability discovery works inside artifact.
3. PySide6, numpy, pedalboard, and AudioCLI module inclusion are documented.
4. Bundle sizes are measured.
5. Plugin scan behavior matches fixed-directory policy.
6. Maintainer approves packager direction.
