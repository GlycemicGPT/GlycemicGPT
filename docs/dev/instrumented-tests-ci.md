---
title: Instrumented Android Tests in CI
description: How the emulator-backed androidTest job runs in CI, and how to run instrumented tests locally.
---

# Instrumented Android Tests in CI

The Android workflow (`.github/workflows/android.yml`) runs three fast checks on every
mobile-relevant change — `testDebugUnitTest`, `lintDebug`, and `assembleDebug`. Those
compile and unit-test the app, but they do **not** execute the instrumented
`androidTest` suite (Compose/espresso UI tests and the Room migration test). A test that
only compiles provides false confidence: it can rot into a non-running state without
anyone noticing.

The **Instrumented Tests (emulator)** job closes that gap. It boots an Android emulator
and runs `:app:connectedDebugAndroidTest` — actually executing the UI and migration
tests against a real Android runtime.

## What runs

`:app:connectedDebugAndroidTest` builds the debug app + its androidTest APK, installs
both on the emulator, and runs every test under
`apps/mobile/app/src/androidTest/`. This is repo-wide infrastructure: any instrumented
test added to `:app` is executed automatically, no workflow change required.

## How the CI job is configured

- **Emulator:** a single pinned API level (`API_LEVEL` in the job, currently **35**, the
  app's `targetSdk`), `google_apis` system image, `x86_64`. KVM hardware acceleration is
  enabled on the runner via a udev rule so the x86_64 emulator boots fast.
- **Action:** [`reactivecircus/android-emulator-runner`](https://github.com/ReactiveCircus/android-emulator-runner)
  (SHA-pinned), which manages emulator creation, boot, and readiness.
- **Caching:** the AVD and its boot snapshot are cached (`actions/cache`, keyed on the API
  level) so subsequent runs skip the image download and cold boot; Gradle is cached via
  `gradle/actions/setup-gradle`. Animations are disabled on the emulator for stable UI
  assertions.
- **Triggering:** the job reuses the same `detect-changes` path filter as the rest of the
  Android workflow, so it runs only on mobile-relevant PRs — the paths the filter matches
  today are `apps/mobile/**`, `plugins/pump-driver-api/**`, `plugins/shipped/**`, and
  `.github/workflows/android.yml` — never on backend-only changes. (The filter lives in
  `android.yml`; that is the source of truth if the matched paths change.)
- **Timeout:** the job is bounded (45 min) so a wedged emulator can't run indefinitely.
- **Report:** the HTML/XML test report is uploaded as the `instrumented-test-report`
  artifact (even on failure) so a red run is debuggable from the PR.

## Rollout posture (non-required while it beds in)

The job reports its **own** status and is intentionally **not** folded into the required
**Android Gate** aggregate check. Emulator-backed jobs are inherently more prone to
infrastructure flakiness (boot timeouts, image-download hiccups) than pure-JVM steps, so
during the bed-in period a transient emulator failure should not block an otherwise-green
PR.

**Flaky-retry posture:** the job does not auto-retry tests — a red result reflects a real
test failure or a genuine infrastructure problem, and we keep that signal honest. If a run
fails for an obviously transient reason (emulator boot timeout, network blip during image
download), **re-run the single job** rather than disabling the test. Once the job has
proven stable over a stretch of mobile PRs, promote it to a **required** status check in
branch protection.

A real, reproducible test failure here is a bug to fix or surface — not to suppress or
retry away.

## Running instrumented tests locally

You need an Android emulator (or a connected device) running before the tests start;
`connectedDebugAndroidTest` connects to an already-running device, it does not boot one.

```bash
# 1. Start the emulator (non-headless, so you can watch). Uses the provisioned AVD.
./scripts/mobile-dev.sh emulator start

# 2. (Recommended) disable animations for stable Compose/espresso assertions:
adb shell settings put global window_animation_scale 0
adb shell settings put global transition_animation_scale 0
adb shell settings put global animator_duration_scale 0

# 3. Run the full instrumented suite (from apps/mobile):
cd apps/mobile
./gradlew :app:connectedDebugAndroidTest
```

Run a single test class while iterating:

```bash
cd apps/mobile
./gradlew :app:connectedDebugAndroidTest \
  -Pandroid.testInstrumentationRunnerArguments.class=com.glycemicgpt.mobile.presentation.meal.MealFullFlowE2ETest
```

The local Android toolchain (SDK, emulator, system images) is provisioned by
`apps/mobile/shell.nix`. After a run, the HTML report is at
`apps/mobile/app/build/reports/androidTests/connected/debug/index.html`.
