#!/usr/bin/env bash
# End-to-end build / sign / notarize / staple pipeline for AudioCLI on macOS.
#
# Usage:
#   ./packaging/build_macos.sh
#
# Environment overrides:
#   AUDIOCLI_SIGN_ID        — Developer ID Application identity string.
#   AUDIOCLI_NOTARY_PROFILE — keychain profile name for `xcrun notarytool`.
#                             Create once with:
#                               xcrun notarytool store-credentials AC_NOTARY \
#                                 --apple-id <appleid> --team-id YW8PJUTA2T \
#                                 --password <app-specific-password>

set -euo pipefail

cd "$(dirname "$0")/.."

SIGN_ID="${AUDIOCLI_SIGN_ID:-Developer ID Application: Dion Timmer (YW8PJUTA2T)}"
NOTARY_PROFILE="${AUDIOCLI_NOTARY_PROFILE:-AC_NOTARY}"
APP_NAME="AudioCLI"
APP_BUNDLE="dist/${APP_NAME}.app"
ENTITLEMENTS="packaging/entitlements.plist"
ZIP_PATH="dist/${APP_NAME}.zip"

log() { printf '\033[1;35m==>\033[0m %s\n' "$*"; }

log "Generating .icns / .ico from packaging/icon.svg"
python packaging/build_icons.py

log "Cleaning previous build"
rm -rf build dist

log "Running PyInstaller"
pyinstaller packaging/audiocli-gui.spec --noconfirm --clean

if [ ! -d "$APP_BUNDLE" ]; then
    echo "ERROR: expected $APP_BUNDLE not found" >&2
    exit 1
fi

# ---- Sign every nested binary first, then the bundle itself --------------
# Qt framework binaries (e.g. QtGui.framework/Versions/A/QtGui) have no file
# extension, so a name-based glob misses them. We grep `file` output instead
# so anything Mach-O gets signed regardless of where it lives or what it's
# called.
log "Signing every Mach-O binary in the bundle"
find "$APP_BUNDLE" -type f -print0 | while IFS= read -r -d '' f; do
    if file -b "$f" 2>/dev/null | grep -q "Mach-O"; then
        codesign --force --options=runtime --timestamp --sign "$SIGN_ID" "$f"
    fi
done

# Frameworks are bundles — they need their own signature on top of the
# binary signatures we just applied. -depth ensures nested frameworks are
# signed before any framework that contains them.
log "Signing every .framework bundle"
find "$APP_BUNDLE" -depth -type d -name "*.framework" -print0 |
    xargs -0 -n 1 codesign --force --options=runtime --timestamp --sign "$SIGN_ID"

log "Signing nested CLI executable (with entitlements)"
codesign --force --options=runtime --timestamp \
    --entitlements "$ENTITLEMENTS" \
    --sign "$SIGN_ID" \
    "$APP_BUNDLE/Contents/MacOS/acli"

log "Signing main app bundle (with entitlements)"
codesign --force --options=runtime --timestamp \
    --entitlements "$ENTITLEMENTS" \
    --sign "$SIGN_ID" \
    "$APP_BUNDLE"

log "Verifying signature"
codesign --verify --deep --strict --verbose=2 "$APP_BUNDLE"
spctl --assess --verbose --type execute "$APP_BUNDLE" || true

log "Smoke-testing frozen binary"
"$APP_BUNDLE/Contents/MacOS/AudioCLI" --packaged-static-smoke

# ---- Notarize -------------------------------------------------------------
log "Building notarization archive"
rm -f "$ZIP_PATH"
ditto -c -k --keepParent "$APP_BUNDLE" "$ZIP_PATH"

log "Submitting to Apple notary service (will block until ticket issues)"
xcrun notarytool submit "$ZIP_PATH" \
    --keychain-profile "$NOTARY_PROFILE" \
    --wait

log "Stapling notarization ticket to bundle"
xcrun stapler staple "$APP_BUNDLE"
xcrun stapler validate "$APP_BUNDLE"

log "Re-creating final distribution archive (stapled)"
rm -f "$ZIP_PATH"
ditto -c -k --keepParent "$APP_BUNDLE" "$ZIP_PATH"

log "Done. Distributable artifact: $ZIP_PATH"
