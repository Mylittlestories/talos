#!/usr/bin/env bash
# Build an installable TALOS Android APK from the Capacitor shell.
#
#   npm ci
#   python tools/build_web.py
#   npm run android:debug
#
# A signed public build additionally needs android/signing.properties; use
# configure-signing.sh locally or let the release workflow create it from
# protected repository secrets.
set -euo pipefail

MODE="${1:-debug}"
case "$MODE" in
    debug|release) ;;
    *) echo "usage: $0 [debug|release]" >&2; exit 2 ;;
esac

ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)"
cd "$ROOT"

if [ ! -f package-lock.json ]; then
    echo "Missing package-lock.json; run npm install first." >&2
    exit 1
fi
if [ ! -d node_modules/@capacitor ]; then
    echo "Missing Capacitor dependencies; run npm ci first." >&2
    exit 1
fi
if [ ! -d android ] || [ ! -x android/gradlew ]; then
    echo "The committed Android shell is missing." >&2
    exit 1
fi

# The Android asset directory must be regenerated from the actual shared
# browser core, never from an old copied payload.
python tools/build_web.py
npx cap sync android

VERSION_INFO="$(python - <<'PY'
from lc import APP_VERSION
parts = APP_VERSION.split('.')
try:
    major, minor, patch = (int(parts[i]) if i < len(parts) else 0 for i in range(3))
except ValueError:
    major, minor, patch = 0, 0, 1
# Android versionCode is monotonic for conventional major.minor.patch releases.
print(APP_VERSION)
print(major * 10000 + minor * 100 + patch)
PY
)"
export TALOS_VERSION="$(printf '%s\n' "$VERSION_INFO" | sed -n '1p')"
export TALOS_VERSION_CODE="$(printf '%s\n' "$VERSION_INFO" | sed -n '2p')"

if [ "$MODE" = "release" ] && [ ! -s android/signing.properties ]; then
    echo "A release APK requires android/signing.properties and its keystore." >&2
    echo "See packaging/android/README.md for the protected-signing workflow." >&2
    exit 1
fi

if [ "$MODE" = "debug" ]; then
    TASK="assembleDebug"
else
    TASK="assembleRelease"
fi
(
    cd android
    ./gradlew --no-daemon "$TASK"
)

OUTPUT="android/app/build/outputs/apk/$MODE/app-$MODE.apk"
if [ ! -s "$OUTPUT" ]; then
    echo "Gradle completed but did not create $OUTPUT" >&2
    exit 1
fi

mkdir -p release
DEST="release/talos-android-${TALOS_VERSION}-${MODE}.apk"
cp "$OUTPUT" "$DEST"
bash packaging/android/verify-apk.sh "$DEST"
printf 'Built %s (%s, versionCode %s)\n' "$DEST" "$TALOS_VERSION" "$TALOS_VERSION_CODE"
