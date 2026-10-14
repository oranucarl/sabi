#!/usr/bin/env bash
# Build SAbi.app (arm64, ad-hoc signed) and a drag-to-install DMG in dist/.
#
#   scripts/build_app.sh           # bundles the cached Whisper "small" model if present
#   SKIP_DMG=1 scripts/build_app.sh
set -euo pipefail

cd "$(dirname "$0")/.."
PY=.venv/bin/python

if ! "$PY" -c "import PyInstaller" 2>/dev/null; then
  echo "PyInstaller is missing. Install it with: uv pip install --python $PY pyinstaller" >&2
  exit 1
fi

mkdir -p build
"$PY" packaging/make_icon.py build/SAbi.icns

# Find the Whisper model faster-whisper downloaded (run SAbi once from source first).
model=$(ls -d "$HOME"/.cache/huggingface/hub/models--Systran--faster-whisper-small/snapshots/*/ 2>/dev/null | head -1 || true)
if [[ -n "$model" ]]; then
  export SABI_WHISPER_DIR="${model%/}"
  echo "Bundling speech model from $SABI_WHISPER_DIR"
else
  echo "Speech model not cached; the app will download it on first use."
fi

"$PY" -m PyInstaller --noconfirm --clean --distpath dist --workpath build/pyinstaller packaging/sabi.spec

# Sign with a stable local identity when one exists, so macOS keeps SAbi's permissions across
# rebuilds (an ad-hoc signature changes every build and resets them). Create one once with
# scripts/make_signing_identity.sh. Public release needs a Developer ID and notarization instead.
identity="${SABI_SIGN_IDENTITY:-SAbi Local Signing}"
if security find-identity -p codesigning 2>/dev/null | grep -q "\"$identity\""; then
  echo "Signing with \"$identity\""
  codesign --force --deep --sign "$identity" dist/SAbi.app
else
  echo "No \"$identity\" certificate; using an ad-hoc signature (permissions reset on each rebuild)."
  codesign --force --deep --sign - dist/SAbi.app
fi
codesign --verify --deep --strict dist/SAbi.app
echo "Built dist/SAbi.app ($(du -sh dist/SAbi.app | cut -f1))"

if [[ -z "${SKIP_DMG:-}" ]]; then
  staging=build/dmg
  rw=build/SAbi-rw.dmg
  rm -rf "$staging" "$rw" dist/SAbi.dmg
  mkdir -p "$staging"
  cp -R dist/SAbi.app "$staging/"
  ln -s /Applications "$staging/Applications"
  hdiutil create -volname "SAbi" -srcfolder "$staging" -ov -format UDRW "$rw" >/dev/null

  # Give the mounted "SAbi" volume the app icon, then compress.
  mount=$(hdiutil attach "$rw" -nobrowse -noautoopen | awk -F'\t' '/\/Volumes\// {print $NF}')
  "$PY" packaging/set_icon.py build/SAbi.icns "$mount"
  hdiutil detach "$mount" >/dev/null
  hdiutil convert "$rw" -format UDZO -o dist/SAbi.dmg >/dev/null
  rm -f "$rw"

  # And the .dmg file itself, as shown in Finder. (Stored in file metadata, so some downloads drop it.)
  "$PY" packaging/set_icon.py build/SAbi.icns dist/SAbi.dmg
  echo "Built dist/SAbi.dmg ($(du -sh dist/SAbi.dmg | cut -f1))"
fi
