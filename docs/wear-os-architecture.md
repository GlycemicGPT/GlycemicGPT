# Wear OS Architecture

> Committed: 2026-03-09 | Status: Active | Supersedes: Epic 32 original plan

## Design Decision

GlycemicGPT uses a **single phone app + watch-side services** architecture for Wear OS integration. There is NO separate "wear companion" phone app. All watch management is built into the main GlycemicGPT mobile app.

This follows the same pattern used by xDrip, AAPS, Dexcom G7, and other health apps. A separate phone companion app was considered and rejected because:

- Adds unnecessary complexity (inter-app IPC on the same phone)
- Confusing UX (users must install and manage two phone apps)
- The main app already has WearDataSender and DataLayer communication
- Two Play Store listings to maintain
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
|                                      |      |   (BG, IoB, Trend, Graph, Alert) |
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

### Key: No separate wear companion phone app

The old `apps/mobile/wear/` module (which was a watch-side app with tiny watch UIs like HomeActivity, ChatActivity) is **removed**. Its watch-side services are migrated to `:wear-device`. Its phone-side functionality is absorbed into `:app`.

## Watch Face Push Flow (Wear OS 6+)

The Watch Face Push API (`androidx.wear.watchface:watchface-push`) enables the phone app to programmatically install and activate WFF watch faces on the watch.

### Initial Setup
1. User installs GlycemicGPT on phone (Play Store or sideload)
2. Watch-side `:wear-device` APK installs on watch (Play Store auto-install for production, ADB for dev)
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

### Watch-to-Phone Communication
1. User taps AI chat or dismisses alert on watch face
2. Watch-side `MessageClient` sends message to phone
3. Phone-side `WearChatRelayService` (in `:app`) receives message
4. Routes to appropriate handler (AI backend, alert service, etc.)
5. Response flows back via DataLayer

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
| `BgColorComplicationDataSource` | SMALL_IMAGE | Color-coded BG bitmap with trend arrow, delta, freshness |
| `GraphComplicationDataSource` | SMALL_IMAGE | Sparkline glucose graph bitmap |
| `IoBComplicationDataSource` | SHORT_TEXT | Insulin on board value |
| `BgComplicationDataSource` | SHORT_TEXT | Plain BG text value |
| `TrendComplicationDataSource` | SHORT_TEXT | Trend arrow symbol |
| `AlertComplicationDataSource` | SHORT_TEXT | Alert status/message |

### Services
| Service | Purpose |
|---------|---------|
| `GlycemicDataListenerService` | Receives DataLayer events from phone, updates WatchDataRepository, triggers complication refreshes |

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
adb -s <phone> install app/build/outputs/apk/debug/app-debug.apk

# Install watch-side services (via ADB to watch)
adb -s <watch> install wear-device/build/outputs/apk/debug/wear-device-debug.apk

# Watch face is pushed programmatically by the app (not sideloaded)
# OR for testing: adb -s <watch> install watchface/build/outputs/apk/debug/watchface-debug.apk
```

### Production (Play Store)
- Phone APK and watch APK share the same Play Store listing
- Play Store auto-installs `:wear-device` on paired watches
- Watch face is pushed by the app itself via Watch Face Push API
- No manual sideloading required by end users

## API Level Requirements

| Component | minSdk | targetSdk | Notes |
|-----------|--------|-----------|-------|
| `:app` (phone) | 26 | 35 | Standard Android phone app |
| `:wear-device` (watch) | 33 | 34 | Wear OS 4+ for services/complications; Watch Face Push API (Story 32.2) bumps minSdk to 36 |
| `:watchface` (WFF) | 33 | 34 | WFF v1 for broadest compatibility |

## Migration from Old Architecture

The old `apps/mobile/wear/` module is removed. Migration:

| Old (wear/) | New Location |
|-------------|-------------|
| `GlycemicDataListenerService` | `:wear-device` |
| `WatchDataRepository` | `:wear-device` |
| `GlucoseDisplayUtils` | `:wear-device` |
| Complication providers (6) | `:wear-device` |
| `HomeActivity` (watch UI) | Removed -- phone Settings > Watch replaces this |
| `ChatActivity` (watch STT) | Removed -- AI interactions go through watch face tap targets |
| `IoBDetailActivity` | Removed -- IoB detail is a complication tap action |
| `AlertsActivity` | `:wear-device` (simplified, launched from watch face tap) |
| `GlycemicTileService` | `:wear-device` (optional, tile alongside watch face) |
| `GlycemicWearApp` (Hilt app) | `:wear-device` |

Phone-side components stay in `:app`:
- `WearDataSender` (already in `:app`)
- `WearChatRelayService` (already in `:app`)
- `WearDataContract` (already in `:app`)
- Settings > Watch UI (enhanced from current stub)
