#!/usr/bin/env bash
# Materialise release-signing inputs supplied by a local release owner or CI.
# Required environment variables:
#   ANDROID_KEYSTORE_BASE64, ANDROID_KEYSTORE_PASSWORD,
#   ANDROID_KEY_ALIAS, ANDROID_KEY_PASSWORD
set -euo pipefail

ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)"
cd "$ROOT"

for name in ANDROID_KEYSTORE_BASE64 ANDROID_KEYSTORE_PASSWORD ANDROID_KEY_ALIAS ANDROID_KEY_PASSWORD; do
    if [ -z "${!name:-}" ]; then
        echo "Missing required signing variable: $name" >&2
        exit 1
    fi
done

umask 077
KEYSTORE="android/talos-release.jks"
printf '%s' "$ANDROID_KEYSTORE_BASE64" | base64 --decode > "$KEYSTORE"
if [ ! -s "$KEYSTORE" ]; then
    echo "Decoded keystore is empty." >&2
    rm -f "$KEYSTORE"
    exit 1
fi

cat > android/signing.properties <<EOF
storeFile=talos-release.jks
storePassword=${ANDROID_KEYSTORE_PASSWORD}
keyAlias=${ANDROID_KEY_ALIAS}
keyPassword=${ANDROID_KEY_PASSWORD}
EOF

echo "Release signing configuration written to android/ (not tracked by git)."
