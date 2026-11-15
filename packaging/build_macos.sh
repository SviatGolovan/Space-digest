#!/usr/bin/env bash
# Сборка Space Digest для macOS → dist/SpaceDigest-<версия>-mac-<arm64|x86_64>.dmg
# Нужно один раз: Python 3.12 с python.org.
# Запуск: bash packaging/build_macos.sh   (флаг --no-venv — собирать в текущем окружении, для CI)
set -euo pipefail
cd "$(dirname "$0")/.."

if [[ "${1:-}" != "--no-venv" ]]; then
  PY=${PYTHON:-python3.12}
  command -v "$PY" >/dev/null || PY=python3
  [[ -d .venv-build ]] || "$PY" -m venv .venv-build
  source .venv-build/bin/activate
  python -m pip install --upgrade pip
  pip install -r requirements-build.txt
fi

pyinstaller packaging/SpaceDigest.spec --noconfirm --clean

VERSION=$(python -c "from spacedigest import VERSION; print(VERSION)")
ARCH=$(uname -m)
APP="dist/Space Digest.app"
DMG="dist/SpaceDigest-${VERSION}-mac-${ARCH}.dmg"

# Подпись: по умолчанию ad-hoc (работает на своём Mac; на чужих — «Открыть всё равно»).
# Если задан APPLE_SIGN_IDENTITY ("Developer ID Application: …"), подписываем по-настоящему.
if [[ -n "${APPLE_SIGN_IDENTITY:-}" ]]; then
  codesign --force --deep --options runtime --timestamp -s "$APPLE_SIGN_IDENTITY" "$APP"
else
  codesign --force --deep -s - "$APP"
fi

STAGE=$(mktemp -d)
cp -R "$APP" "$STAGE/"
ln -s /Applications "$STAGE/Applications"
rm -f "$DMG"
hdiutil create -volname "Space Digest" -srcfolder "$STAGE" -ov -format UDZO "$DMG"
rm -rf "$STAGE"

# Нотаризация (если есть учётка Apple Developer): APPLE_ID, APPLE_TEAM_ID, APPLE_APP_PASSWORD
if [[ -n "${APPLE_SIGN_IDENTITY:-}" && -n "${APPLE_ID:-}" ]]; then
  codesign -s "$APPLE_SIGN_IDENTITY" --timestamp "$DMG"
  xcrun notarytool submit "$DMG" --apple-id "$APPLE_ID" --team-id "$APPLE_TEAM_ID" \
        --password "$APPLE_APP_PASSWORD" --wait
  xcrun stapler staple "$DMG"
fi
echo "Готово: $DMG"
