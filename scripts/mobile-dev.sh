#!/usr/bin/env bash
#
# Mobile development helper script for GlycemicGPT.
#
# Usage:
#   ./scripts/mobile-dev.sh <command> [subcommand]
#
# Commands:
#   devices              List all connected ADB devices
#   build                Build debug APKs (phone + wear-device)
#   emulator start       Launch the test_pixel emulator (non-headless)
#   emulator stop        Kill the running emulator
#   emulator install     Install phone debug APK on emulator
#   phone install        Install phone debug APK on physical phone
#   phone logcat         Show filtered BLE + app logs from phone
#   phone ble-raw        Show only BLE_RAW hex data logs from phone

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
MOBILE_DIR="$PROJECT_ROOT/apps/mobile"
PHONE_APK="$MOBILE_DIR/app/build/outputs/apk/debug/app-debug.apk"
AVD_NAME="test_device"

# Resolve ADB binary -- prefer ANDROID_HOME, fall back to PATH
if [ -n "${ANDROID_HOME:-}" ] && [ -x "$ANDROID_HOME/platform-tools/adb" ]; then
    ADB="$ANDROID_HOME/platform-tools/adb"
elif command -v adb &>/dev/null; then
    ADB="adb"
else
    echo "Error: adb not found. Run this inside nix-shell or set ANDROID_HOME."
    exit 1
fi

# Resolve emulator binary
if [ -n "${ANDROID_HOME:-}" ] && [ -x "$ANDROID_HOME/emulator/emulator" ]; then
    EMULATOR="$ANDROID_HOME/emulator/emulator"
elif command -v emulator &>/dev/null; then
    EMULATOR="emulator"
else
    EMULATOR=""
fi

get_emulator_serial() {
    "$ADB" devices | grep -E '^emulator-' | head -1 | awk '{print $1}'
}

get_phone_serial() {
    # Physical devices have non-emulator serial numbers (not starting with "emulator-")
    "$ADB" devices | grep -v '^List' | grep -v '^$' | grep -v '^emulator-' | head -1 | awk '{print $1}'
}

case "${1:-help}" in
    devices)
        "$ADB" devices -l
        ;;

    build)
        cd "$MOBILE_DIR"
        ./gradlew assembleDebug
        echo ""
        echo "Debug APKs built:"
        [ -f "$PHONE_APK" ] && echo "  Phone: $PHONE_APK"
        [ -f "$MOBILE_DIR/wear-device/build/outputs/apk/debug/wear-device-debug.apk" ] && \
            echo "  Wear Device:    $MOBILE_DIR/wear-device/build/outputs/apk/debug/wear-device-debug.apk"
        ;;

    emulator)
        case "${2:-help}" in
            start)
                if [ -z "$EMULATOR" ]; then
                    echo "Error: emulator binary not found. Run inside nix-shell."
                    exit 1
                fi
                echo "Starting emulator: $AVD_NAME (non-headless)"
                "$EMULATOR" -avd "$AVD_NAME" -no-audio -gpu auto &
                disown
                echo "Emulator starting in background. Wait for boot to complete."
                echo "Use '$0 devices' to check when it's ready."
                ;;
            stop)
                SERIAL=$(get_emulator_serial)
                if [ -n "$SERIAL" ]; then
                    "$ADB" -s "$SERIAL" emu kill
                    echo "Emulator $SERIAL stopped."
                else
                    echo "No running emulator found."
                fi
                ;;
            install)
                if [ ! -f "$PHONE_APK" ]; then
                    echo "Error: Debug APK not found at $PHONE_APK"
                    echo "Run '$0 build' first."
                    exit 1
                fi
                SERIAL=$(get_emulator_serial)
                if [ -z "$SERIAL" ]; then
                    echo "Error: No running emulator found."
                    echo "Run '$0 emulator start' first."
                    exit 1
                fi
                echo "Installing on emulator ($SERIAL)..."
                "$ADB" -s "$SERIAL" install -r "$PHONE_APK"
                ;;
            *)
                echo "Usage: $0 emulator {start|stop|install}"
                ;;
        esac
        ;;

    phone)
        case "${2:-help}" in
            install)
                if [ ! -f "$PHONE_APK" ]; then
                    echo "Error: Debug APK not found at $PHONE_APK"
                    echo "Run '$0 build' first."
                    exit 1
                fi
                SERIAL=$(get_phone_serial)
                if [ -z "$SERIAL" ]; then
                    echo "Error: No physical phone found."
                    echo "Connect your phone via USB and enable USB debugging."
                    exit 1
                fi
                echo "Installing on phone ($SERIAL)..."
                "$ADB" -s "$SERIAL" install -r "$PHONE_APK"
                ;;
            logcat)
                SERIAL=$(get_phone_serial)
                if [ -z "$SERIAL" ]; then
                    echo "Error: No physical phone found."
                    exit 1
                fi
                echo "Streaming logs from phone ($SERIAL)..."
                echo "Press Ctrl+C to stop."
                "$ADB" -s "$SERIAL" logcat -v time \
                    BleConnectionManager:D \
                    TandemBleDriver:D \
                    PumpPollingOrchestrator:D \
                    JpakeAuthenticator:D \
                    TandemAuthenticator:D \
                    *:S
                ;;
            ble-raw)
                SERIAL=$(get_phone_serial)
                if [ -z "$SERIAL" ]; then
                    echo "Error: No physical phone found."
                    exit 1
                fi
                echo "Streaming BLE_RAW hex data from phone ($SERIAL)..."
                echo "Press Ctrl+C to stop."
                "$ADB" -s "$SERIAL" logcat -v time '*:D' | grep "BLE_RAW"
                ;;
            *)
                echo "Usage: $0 phone {install|logcat|ble-raw}"
                ;;
        esac
        ;;

    help|*)
        echo "GlycemicGPT Mobile Development Helper"
        echo ""
        echo "Usage: $0 <command> [subcommand]"
        echo ""
        echo "Commands:"
        echo "  devices              List all connected ADB devices"
        echo "  build                Build debug APKs (phone + wear-device)"
        echo "  emulator start       Launch the $AVD_NAME emulator"
        echo "  emulator stop        Kill the running emulator"
        echo "  emulator install     Install debug APK on emulator"
        echo "  phone install        Install debug APK on physical phone"
        echo "  phone logcat         Stream filtered BLE + app logs"
        echo "  phone ble-raw        Stream only BLE_RAW hex data logs"
        echo ""
        echo "Prerequisites:"
        echo "  Run inside nix-shell (cd apps/mobile && nix-shell)"
        echo "  Or ensure ANDROID_HOME is set and adb is in PATH"
        ;;
esac
