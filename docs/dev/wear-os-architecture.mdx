---
title: Wear OS Architecture
description: Single phone-app-plus-watch-services architecture for Wear OS integration.
---

# Wear OS Architecture

> Committed: 2026-03-09 | Status: Active | Supersedes: Epic 32 original plan

## Design Decision

GlycemicGPT uses a **single phone app + watch-side services** architecture for Wear OS integration. There is NO separate "wear companion" phone app. All watch management is built into the main GlycemicGPT mobile app.

This follows the same pattern used by xDrip, AAPS, Dexcom G7, and other health apps. A separate phone companion app was considered and rejected because:

- Adds unnecessary complexity (inter-app IPC on the same phone)
- Confusing UX (users must install and manage two phone apps)
- The main app already has WearDataSender and DataLayer communication
- Two separate distribution artifacts to maintain
- No technical benefit -- the main app can do everything a companion app would

## Architecture Overview

```
PHONE (Single App)                             WATCH (Wear OS 6+)
+--------------------------------------+      +----------------------------------+
| GlycemicGPT Mobile App (:app)       |      | WFF Watch Face (:watchface)      |
|                                      |      | - Resource-only APK (no code)    |
|  Core Features:                      | Push | - Pushed via Watch Face Push API |
|  - BLE pump/CGM connection           |----->| - Rendered by system WFF engine  |
|  - Backend API sync                  |      | - Complication slots for live    |
|  - AI chat, alerts, briefs           |      |   data from wear-device services |
|                                      |      +----------------------------------+
|  Watch Management (Settings > Watch):|      |                                  |
|  - Watch face gallery & push         | Data | Watch-Side Services              |
|  - Feature toggles (IoB, graph,     | Layer|   (:wear-device)                 |
|    alerts, seconds, theme)           |----->| - WearableListenerService        |
|  - Watch face preview                |      |   (receives BG/IoB/alerts/hist)  |
|  - Connection status                 |      | - Complication providers          |
|                                      |      |   (BG, IoB)                      |
|  Data Streaming:                     | Msgs | - WatchFacePushManager           |
|  - WearDataSender (BG, IoB, alerts,  |<-----|   (installs/activates faces)     |
|    CGM history, thresholds)          |      | - MessageClient relay            |
|  - Receives AI queries from watch    |      |   (AI queries, alert dismiss)    |
|  - Receives alert dismissals         |      | - WatchDataRepository            |
|  - Relays to backend API             |      |   (StateFlow for all data)       |
+--------------------------------------+      +----------------------------------+
```

## Gradle Modules

| Module | Location | Runs On | Purpose |
|--------|----------|---------|---------|
| `:app` | `apps/mobile/app/` | Phone | Main app -- everything including watch management UI, WearDataSender, ChannelClient for face push |
| `:wear-device` | `apps/mobile/wear-device/` | Watch | Minimal watch-side services: DataLayer listener, complication providers, WatchFacePushManager |
| `:watchface` | `apps/mobile/watchface/` | Watch | WFF resource-only APK (`hasCode="false"`). Bundled in `:app` assets, pushed to watch via Watch Face Push API |
| `:pump-driver-api` | `plugins/pump-driver-api/` | Phone | Plugin SDK interfaces |
| `:tandem-pump-driver` | `plugins/shipped/tandem/` | Phone | Tandem BLE plugin |

### CRITICAL: applicationId Must Match

The `:wear-device` module MUST use the same `applicationId` as `:app` (`com.glycemicgpt.mobile`). The Wearable Data Layer (DataClient, MessageClient) routes messages by applicationId -- if the phone app uses `com.glycemicgpt.mobile` and the watch app uses a different applicationId, messages are silently dropped. The `namespace` (R class package) can differ (`com.glycemicgpt.weardevice`).

This was discovered during Story 32.8 E2E testing when MessageClient messages from the watch were never delivered to the phone. Phone logcat showed `WearableService: Failed to deliver message to AppKey[...]` due to applicationId mismatch.

### Key: No separate wear companion phone app

The old `apps/mobile/wear/` module (which was a watch-side app with tiny watch UIs like HomeActivity, ChatActivity) is **removed**. Its watch-side services are migrated to `:wear-device`. Its phone-side functionality is absorbed into `:app`.

## Watch Face Push Flow (Wear OS 6+)

The Watch Face Push API (`androidx.wear.watchface:watchface-push`) enables the phone app to programmatically install and activate WFF watch faces on the watch.

### Initial Setup
1. User installs GlycemicGPT on phone (sideload from GitHub Releases)
2. Watch-side `:wear-device` APK installs on watch (ADB sideload or helper app)
3. User opens Settings > Watch in the phone app
4. App detects connected watch, shows watch face gallery
5. User taps "Set Watch Face" -- app pushes WFF APK via ChannelClient
6. `:wear-device` on watch receives APK, calls `WatchFacePushManager.addWatchFace()`
7. Phone app sends `setWatchFaceAsActive()` -- face appears immediately

### Data Streaming (Real-Time)
1. Main app receives BG/IoB/alerts from pump plugin via BLE
2. `WearDataSender` pushes data items to watch via `DataClient`
3. `:wear-device` `GlycemicDataListenerService` receives data
4. Updates `WatchDataRepository` StateFlows
5. Triggers complication provider updates
6. WFF watch face reads complication data and renders live glucose info

### Watch-to-Phone Communication (Story 32.8)

Two message paths use `MessageClient` (transient, bidirectional):

**AI Chat Flow:**
1. User opens `ChatActivity` on watch (launched via explicit intent from complication tap target)
2. Selects a quick query ("How am I doing?", "Breakfast advice", "Why is my BG high?")
3. `WearMessageSender` discovers phone node via `CapabilityClient` (capability: `glycemicgpt_chat_relay`), falls back to `NodeClient`
4. Sends message on `/glycemicgpt/chat/request` path via `MessageClient`
5. Phone-side `WearChatRelayService` receives message, delegates to `ChatRepository` which calls the backend AI endpoint
6. Backend response sent back on `/glycemicgpt/chat/response` (or `/glycemicgpt/chat/error`) via `MessageClient`
7. Watch-side `GlycemicDataListenerService.onMessageReceived()` updates `WatchDataRepository.chatState`
8. `ChatActivity` renders response with safety disclaimer ("Not medical advice. Consult your doctor.")

**Alert Dismiss Flow:**
1. User taps "Dismiss" on `AlertsActivity` on watch
2. `WearMessageSender` sends empty message on `/glycemicgpt/alert/dismiss` path
3. Phone-side `WearChatRelayService` receives dismiss, acknowledges latest unacknowledged alert in Room DB
4. Phone resets alert DataItem to `type="none"` via `WearDataSender.clearAlert()`
5. Watch-side `GlycemicDataListenerService` receives the `none` type and sets `WatchDataRepository.alert` to null

**Known limitation:** Alert dismiss sends an empty payload -- the phone acknowledges the latest unacknowledged alert by timestamp. If multiple alerts arrive in quick succession, the wrong alert could be dismissed. A future improvement should include the alert ID in the dismiss payload for exact matching.

**Timeouts and error handling:**
- All `Wearable.*Client` `await()` calls wrapped in `withTimeout(10_000L)`
- Chat response timeout: 30s on watch side (shows "Request timed out" error)
- Blank/null message validation on both sides
- `ChatState` sealed class: `Idle | Loading | Success(response, disclaimer) | Error(message)`

## Watch Face Customization

The phone app's Settings > Watch section provides full customization:

### Feature Toggles (synced to watch via DataLayer)
- Show/hide IoB display
- Show/hide glucose graph (sparkline)
- Show/hide alert indicator
- Show/hide seconds in time display
- Graph time range (1h, 3h, 6h)

### Theme Configuration
- Color themes (Dark, Clinical Blue, High Contrast)
- BG color coding thresholds (synced from user's glucose range settings)

### Complication Configuration
- Which data sources are active
- Complication slot assignments

### Watch Face Gallery (Future)
- Multiple WFF face designs to choose from
- Preview before pushing to watch

## Watch-Side Services Detail (`:wear-device`)

### Complication Providers
| Provider | Type | Data |
|----------|------|------|
| `BgComplicationDataSource` | SHORT_TEXT, LONG_TEXT | Plain BG text value |
| `IoBComplicationDataSource` | SHORT_TEXT, LONG_TEXT | Insulin on board value |

### Services
| Service | Purpose |
|---------|---------|
| `GlycemicDataListenerService` | Receives DataLayer events (DataClient) and messages (MessageClient) from phone. Updates WatchDataRepository, triggers complication refreshes. Handles chat response/error messages. |

### Activities (Story 32.8)
| Activity | Purpose |
|----------|---------|
| `ChatActivity` | Quick-query AI chat UI. Shows 3 preset questions, sends via `WearMessageSender`, displays response with safety disclaimer. 30s timeout. |
| `AlertsActivity` | Displays active glucose alert with BG value (validated 20-500 range) and dismiss button. Sends dismiss to phone via `WearMessageSender`. |

### Messaging
| Component | Purpose |
|-----------|---------|
| `WearMessageSender` | Discovers phone node via CapabilityClient/NodeClient, sends messages with 10s timeout on all await() calls. Used by ChatActivity and AlertsActivity. |

### WatchFacePushManager Integration
- Receives WFF APK bytes from phone via ChannelClient
- Calls `addWatchFace()` / `updateWatchFace()` to install
- Handles `setWatchFaceAsActive()` to auto-activate
- Manages face lifecycle (install, update, remove)

## Development vs Production

### Development (Sideloading)

```bash
# Build all modules
./gradlew :app:assembleDebug :wear-device:assembleDebug :watchface:assembleDebug

# Install phone app
adb -s <phone> install apps/mobile/app/build/outputs/apk/debug/app-debug.apk

# Install watch-side services (via ADB to watch)
adb -s <watch> install apps/mobile/wear-device/build/outputs/apk/debug/wear-device-debug.apk

# Watch face is pushed programmatically by the app (not sideloaded)
# OR for testing: adb -s <watch> install apps/mobile/watchface/build/outputs/apk/debug/watchface-debug.apk
```

### Production (GitHub Releases)

GlycemicGPT is distributed via GitHub Releases (not Play Store -- open source diabetes software, not FDA approved).

- Phone APK and watch APK are published as GitHub Release assets
- Users sideload the phone APK or install via F-Droid (future)
- Watch APK must be installed separately on the watch via ADB or a helper app (Epic 32 future story)
- Watch face is pushed programmatically by the phone app via Watch Face Push API

## API Level Requirements

| Component | minSdk | targetSdk | Notes |
|-----------|--------|-----------|-------|
| `:app` (phone) | 26 | 35 | Standard Android phone app |
| `:wear-device` (watch) | 35 | 35 | Wear OS 5+. Watch Face Push API requires Wear OS 6 (API 36) at runtime; guarded by `Build.VERSION.SDK_INT` check. `watchface-push` AAR's minSdk 36 is overridden via `tools:overrideLibrary`. On API 35 devices: core services (data listener, complications) work normally; watch face push is unavailable and `WatchFaceInstaller.isSupported()` returns false. Users on Wear OS 5 must install watch faces manually via ADB. All `WatchFacePushManager` references are isolated in `@RequiresApi(36)` methods to prevent class-loading failures on older API levels. |
| `:watchface` (WFF) | 33 | 34 | WFF v1 for broadest compatibility |

## Migration from Old Architecture

The old `apps/mobile/wear/` module was replaced by `:wear-device` in Stories 32.1--32.9. Story 32.1 created the new module and migrated core services. Story 32.9 removed the old module. Migration map:

| Old (wear/) | New Location |
|-------------|-------------|
| `GlycemicDataListenerService` | `:wear-device` |
| `WatchDataRepository` | `:wear-device` |
| `GlucoseDisplayUtils` | `:wear-device` |
| Complication providers (BG, IoB) | `:wear-device` |
| `HomeActivity` (watch UI) | Removed -- phone Settings > Watch replaces this |
| `ChatActivity` (watch STT) | Replaced -- new `ChatActivity` in `:wear-device` (Story 32.8) with quick-query buttons + AI response display via MessageClient relay |
| `IoBDetailActivity` | Removed -- IoB detail is a complication tap action |
| `GlycemicWearApp` (Hilt app) | `:wear-device` |

Phone-side components stay in `:app`:
- `WearDataSender` (already in `:app`)
- `WearChatRelayService` (already in `:app`)
- `WearDataContract` (already in `:app`)
- Settings > Watch UI (enhanced from current stub)
