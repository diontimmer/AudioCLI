# macOS build pipeline

End-to-end build / sign / notarize / staple flow for the macOS `.app` bundle.

## One-time setup

You need:

1. **Apple Developer ID Application** certificate installed in your login keychain.
2. **Stored notarytool credentials** under a profile name (this repo defaults to `AC_NOTARY`).
3. **librsvg** for icon generation: `brew install librsvg`.
4. **PyInstaller** in your build env: `pip install pyinstaller pillow`.

Stash notarytool credentials once:

```shell
xcrun notarytool store-credentials AC_NOTARY \
  --apple-id your.apple.id@example.com \
  --team-id YOUR_TEAM_ID \
  --password <app-specific-password-from-appleid.apple.com>
```

The app-specific password is generated at [appleid.apple.com](https://appleid.apple.com/) → Sign-In and Security → App-Specific Passwords. It's a one-time setup; the password lives in your keychain afterward.

## Build

```shell
./packaging/build_macos.sh
```

The script:

1. Regenerates `.icns` / `.ico` / `.png` from `packaging/icon.svg`.
2. Clears `build/` and `dist/`, then runs PyInstaller against the `audiocli-gui.spec`.
3. Walks every file inside `dist/AudioCLI.app`, identifies Mach-O binaries via `file`, and signs each with the Developer ID + hardened runtime + secure timestamp.
4. Signs every `.framework` directory as a bundle (depth-first).
5. Signs the nested `acli` CLI executable with entitlements.
6. Signs the main `.app` bundle with entitlements.
7. Runs the `--packaged-static-smoke` check against the frozen GUI binary — verifies the capability registry can discover all ops without booting Qt.
8. Builds a zip via `ditto`, submits to Apple's notary service, waits for the ticket.
9. Staples the ticket to the `.app`.
10. Re-zips the stapled bundle for distribution.

Final artifact: `dist/AudioCLI.zip`.

## Overrides

Two environment variables override the defaults:

```shell
AUDIOCLI_SIGN_ID="Developer ID Application: Name Here (TEAM_ID)" \
AUDIOCLI_NOTARY_PROFILE=YOUR_PROFILE \
./packaging/build_macos.sh
```

## Why every Mach-O is signed individually

Apple's notary service rejects any bundle that contains unsigned binaries with a hardened runtime requirement. A naive `find -name "*.dylib"` misses Qt framework binaries — files like `QtGui.framework/Versions/A/QtGui` have no file extension. The build script uses `file` to identify Mach-O binaries by content, not by name, so nothing gets skipped.

After binaries are signed, frameworks are re-signed as bundles. This refreshes each framework's `_CodeSignature/` directory so the bundle-level signature matches the now-signed binary inside.

## Entitlements

`packaging/entitlements.plist` declares:

| Entitlement | Why |
|---|---|
| `com.apple.security.cs.allow-unsigned-executable-memory` | Qt and pedalboard JIT machine code at runtime. |
| `com.apple.security.cs.disable-library-validation` | pedalboard `dlopen`s user-provided VST3/AU plugins signed by third parties (Native Instruments, FabFilter, etc.) — without this, every plugin load fails. |
| `com.apple.security.cs.allow-dyld-environment-variables` | Some Qt platform plugins consult `DYLD_*` env vars. |
| `com.apple.security.device.audio-input` | Reserved for future live-monitoring features. |

Entitlements are applied to the two entry-point executables (the main `.app` and the nested `acli`). Dylibs and frameworks are signed without entitlements — they inherit the process entitlements at runtime.

## Distribution check

After the script finishes:

```shell
# Confirm the bundle is correctly signed AND notarized
spctl --assess --verbose --type execute dist/AudioCLI.app
# Expected: dist/AudioCLI.app: accepted   source=Notarized Developer ID
```

If `spctl` still says `Unnotarized Developer ID`, the staple step didn't complete. Check `xcrun notarytool log <submission-id> --keychain-profile AC_NOTARY` for Apple's rejection reasons.

## Common notary rejections

| Rejection | Cause | Fix |
|---|---|---|
| "binary is not signed with a valid Developer ID certificate" | A Mach-O file was skipped during signing. | Verify the signing loop walks the path that file lives in. Most often it's a binary with no extension. |
| "signature does not include a secure timestamp" | Same cause as above — usually a missed file. | Same fix. |
| "binary uses an SDK older than the 10.9 SDK" | A bundled native dep was built against an ancient SDK. | Update the offending dep or rebuild with newer headers. |

## Cross-platform notes

Windows and Linux builds run from the same `audiocli-gui.spec` via plain `pyinstaller packaging/audiocli-gui.spec --noconfirm --clean`. There's no signing pipeline for those yet — see [cross-platform app notes](cross-platform-app.md).
