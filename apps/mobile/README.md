# GlycemicGPT Android App

Android mobile app with BLE connectivity to Tandem insulin pumps for real-time data monitoring.

## What This App Does

- Connects to your Tandem pump via Bluetooth Low Energy (BLE)
- Reads real-time IoB, basal rate, BG, battery, and reservoir data
- Syncs pump data to your self-hosted GlycemicGPT backend
- Uploads to Tandem cloud at faster intervals (5-15 min vs 60 min)
- Voice AI chat via text-to-speech
- Wear OS watch face companion

## What This App Does NOT Do

- **No insulin delivery** -- read-only pump access
- **No pump setting changes** -- read-only pump access
- **No AI-controlled pump actions** -- AI provides suggestions only

## Prerequisites

- Android Studio Ladybug (2024.2.1) or newer
- JDK 17
- Android SDK with API 35
- Android device with BLE support (minSdk 30 / Android 11+)

## Building

```bash
# Debug build
cd apps/mobile
./gradlew assembleDebug

# Run unit tests
./gradlew testDebugUnitTest

# Lint check
./gradlew lintDebug
```

The debug APK is output to `app/build/outputs/apk/debug/`.

## Installing on Device

1. Enable Developer Options on your Android device
2. Enable "Install from unknown sources" for your file manager
3. Transfer the APK to your device
4. Open the APK to install

Or via ADB:
```bash
adb install app/build/outputs/apk/debug/app-debug.apk
```

## Project Structure

```
apps/mobile/
  app/src/main/java/com/glycemicgpt/mobile/
    ble/              # BLE protocol implementation (our own, no pumpX2 dependency)
      connection/     # BLE connection manager and TandemBleDriver
      messages/       # BLE message definitions (read-only status requests)
      protocol/       # Protocol constants, framing, checksums
    data/             # Data layer (Room DB, repositories)
      local/          # Room entities and DAOs
      repository/     # Repository implementations
    domain/           # Domain layer (models, interfaces)
      model/          # Data models (IoBReading, BasalReading, etc.)
      pump/           # PumpDriver interface
      usecase/        # Use cases
    presentation/     # UI layer (Compose screens)
      home/           # Home screen with pump status
      chat/           # AI chat with TTS
      settings/       # App settings
      pairing/        # Pump pairing flow
      theme/          # Material 3 dark theme
      navigation/     # Navigation graph
    service/          # Android services
```

## BLE Protocol

The Bluetooth Low Energy protocol implementation is our own Kotlin code, informed
by the reverse-engineering research in [jwoglom/pumpX2](https://github.com/jwoglom/pumpX2)
(MIT licensed). We do not depend on pumpX2 at runtime.

See [THIRD_PARTY_LICENSES.md](THIRD_PARTY_LICENSES.md) for attribution.

## CI/CD

GitHub Actions automatically builds and tests on every PR that modifies `apps/mobile/`.
Debug APKs are uploaded as build artifacts. See `.github/workflows/android.yml`.
