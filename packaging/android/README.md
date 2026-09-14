# TALOS Android APK

This directory is the native Android shell for the same browser edition in
`web/`. It uses Capacitor only as the WebView container: the chess engine,
training payload, Anarchess, Anarchess SOLO and Anarcheckers are copied from
this repository by `tools/build_web.py`; no remote web site is wrapped.

## What is built

* **Application ID:** `org.taloschess.studio`
* **Minimum Android version:** Android 6.0 / API 23
* **Target SDK:** API 35
* **Network:** internet access is needed the first time the embedded Pyodide
  runtime is obtained from its pinned jsDelivr URL. Internet is the only
  user-facing device permission; AndroidX adds an app-private receiver
  permission. The app never requests contacts, storage, location, microphone,
  camera, or advertising permissions.
* **Debug APK:** an installable test/sideload artifact.
* **Release APK:** a signed artifact only when the release owner supplies a
  private keystore. The key is intentionally not in this repository.

## Build a debug APK

Install Node 20+, Python 3.9+, JDK 21 (required by the current Capacitor
Android library), and Android SDK platform/build tools for API 35. Then:

```bash
npm ci
python -m pip install -r requirements.txt
npm run android:debug
```

The result is `release/talos-android-<version>-debug.apk`. For a connected
phone with USB debugging enabled:

```bash
adb install -r release/talos-android-2.2.0-debug.apk
```

Android treats debug certificates as test builds; distribute a signed release
APK to users instead.

## Sign a release APK

Create and retain a keystore under the release owner's control, then provide
these four values locally or as protected GitHub Actions secrets:

* `ANDROID_KEYSTORE_BASE64` — base64 encoding of the `.jks` file
* `ANDROID_KEYSTORE_PASSWORD`
* `ANDROID_KEY_ALIAS`
* `ANDROID_KEY_PASSWORD`

Run:

```bash
export ANDROID_KEYSTORE_BASE64="$(base64 -w0 talos-release.jks)"
export ANDROID_KEYSTORE_PASSWORD='…'
export ANDROID_KEY_ALIAS='…'
export ANDROID_KEY_PASSWORD='…'
bash packaging/android/configure-signing.sh
npm run android:release
```

This writes the ignored `android/talos-release.jks` and
`android/signing.properties`, then creates
`release/talos-android-<version>-release.apk`. Never commit either signing
file. The tag-release workflow always produces a debug APK and additionally
publishes the signed APK when all four repository secrets are present.

## Maintain the shell

`npx cap sync android` refreshes only generated Capacitor files and copied web
assets. Keep product changes in the tracked Android resources/Gradle files;
run `npm run android:debug` after upgrades to prove both the web copy and the
native project still build.
