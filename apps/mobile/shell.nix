{ pkgs ? import <nixpkgs> {
    config = {
      allowUnfree = true;
      android_sdk.accept_license = true;
    };
  }
}:

let
  androidComposition = pkgs.androidenv.composeAndroidPackages {
    # Build tools matching build.gradle.kts compileSdk / targetSdk
    # AGP 8.7.3 requires build-tools 34 in addition to 35
    # Platform 36 needed for wear-device (watchface-push requires Wear OS 6 / API 36)
    platformVersions = [ "34" "35" "36" ];
    buildToolsVersions = [ "34.0.0" "35.0.0" "36.0.0" ];

    # Emulator + system images for local UI testing
    # google_apis: phone emulator, android-wear: Wear OS emulator
    includeEmulator = true;
    includeSystemImages = true;
    systemImageTypes = [ "google_apis" "android-wear" ];
    abiVersions = [ "x86_64" ];

    # Extras
    includeNDK = false;
    includeSources = false;
    includeExtras = [];
  };

  androidSdk = androidComposition.androidsdk;
in
pkgs.mkShell {
  buildInputs = [
    androidSdk
    pkgs.jdk17
    pkgs.gradle
  ];

  ANDROID_HOME = "${androidSdk}/libexec/android-sdk";
  ANDROID_SDK_ROOT = "${androidSdk}/libexec/android-sdk";
  JAVA_HOME = "${pkgs.jdk17.home}";

  # Gradle needs writable directories
  GRADLE_USER_HOME = toString ./.gradle-home;

  shellHook = ''
    echo ""
    echo "Android development shell ready"
    echo "  ANDROID_HOME=$ANDROID_HOME"
    echo "  JAVA_HOME=$JAVA_HOME"
    echo "  SDK platforms: 34, 35, 36"
    echo "  Build tools: 34.0.0, 35.0.0, 36.0.0"
    echo "  System images: google_apis (phone), android-wear (Wear OS)"
    echo ""
    echo "Available commands:"
    echo "  ./gradlew assembleDebug          - Build phone + wear-device debug APKs"
    echo "  ./gradlew testDebugUnitTest      - Run all unit tests"
    echo "  ./gradlew lintDebug              - Run lint checks"
    echo "  emulator -list-avds              - List AVDs"
    echo ""
  '';
}
