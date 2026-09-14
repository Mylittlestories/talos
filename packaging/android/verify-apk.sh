#!/usr/bin/env bash
# Inspect a built APK without requiring an emulator. This is intentionally
# stricter than `unzip -t`: it proves the app identity, SDK policy, user-facing
# permissions, signature and the copied TALOS payload survived Gradle packaging.
set -euo pipefail

APK="${1:?usage: verify-apk.sh path/to/talos.apk}"
if [ ! -s "$APK" ]; then
    echo "APK is missing or empty: $APK" >&2
    exit 1
fi

SDK="${ANDROID_SDK_ROOT:-${ANDROID_HOME:-}}"
if [ -z "$SDK" ]; then
    echo "Set ANDROID_SDK_ROOT (or ANDROID_HOME) to verify Android metadata." >&2
    exit 1
fi
AAPT="$(find "$SDK/build-tools" -type f -name aapt -perm -u+x 2>/dev/null | sort -V | tail -n 1)"
APKSIGNER="$(find "$SDK/build-tools" -type f -name apksigner -perm -u+x 2>/dev/null | sort -V | tail -n 1)"
if [ -z "$AAPT" ] || [ -z "$APKSIGNER" ]; then
    echo "Could not find aapt and apksigner under $SDK/build-tools." >&2
    exit 1
fi

unzip -t "$APK" >/dev/null
BADGING="$($AAPT dump badging "$APK")"
VERSION="$(python -c 'from lc import APP_VERSION; print(APP_VERSION)')"
CODE="$(python - <<'PY'
from lc import APP_VERSION
parts = APP_VERSION.split('.')
try:
    major, minor, patch = (int(parts[i]) if i < len(parts) else 0 for i in range(3))
except ValueError:
    major, minor, patch = 0, 0, 1
print(major * 10000 + minor * 100 + patch)
PY
)"

printf '%s\n' "$BADGING" | grep -q "package: name='org.taloschess.studio' versionCode='$CODE' versionName='$VERSION'"
printf '%s\n' "$BADGING" | grep -qx "sdkVersion:'23'"
printf '%s\n' "$BADGING" | grep -qx "targetSdkVersion:'35'"
printf '%s\n' "$BADGING" | grep -qx "uses-permission: name='android.permission.INTERNET'"
# AndroidX 1.12 creates this app-private receiver permission automatically. It
# is signature-scoped to TALOS and is not a user-granted device permission.
UNEXPECTED="$(printf '%s\n' "$BADGING" | grep '^uses-permission:' | \
    grep -Ev "^uses-permission: name='(android.permission.INTERNET|org.taloschess.studio.DYNAMIC_RECEIVER_NOT_EXPORTED_PERMISSION)'$" || true)"
if [ -n "$UNEXPECTED" ]; then
    echo "Unexpected Android permissions:" >&2
    printf '%s\n' "$UNEXPECTED" >&2
    exit 1
fi
# A successful verifier exit alone is not enough: it can accept an APK signed
# only with a newer scheme. TALOS supports API 23, so require both the broadly
# compatible v1 signature and the tamper-resistant v2 signature explicitly.
SIGNATURE_REPORT="$("$APKSIGNER" verify --verbose --min-sdk-version 23 "$APK")"
for scheme in v1 v2; do
    if ! printf '%s\n' "$SIGNATURE_REPORT" | \
            grep -Eq "^Verified using ${scheme} scheme .*: true$"; then
        echo "APK is not validly signed with the required ${scheme} scheme." >&2
        printf '%s\n' "$SIGNATURE_REPORT" >&2
        exit 1
    fi
done
ZIP_LIST="$(unzip -Z1 "$APK")"
for asset in assets/public/index.html assets/public/js/worker.js \
             assets/public/python/files.json assets/public/data/sets.json; do
    grep -Fxq -- "$asset" <<< "$ZIP_LIST" || {
        echo "APK is missing required payload asset: $asset" >&2
        exit 1
    }
done

printf 'Verified %s: TALOS %s (versionCode %s), API 23–35, local payload present.\n' \
       "$APK" "$VERSION" "$CODE"
