# GlycemicGPT Implementation Progress

> Last Updated: 2026-02-28

## Summary

| Epic | Title | Stories | Status |
|------|-------|---------|--------|
| 1 | Foundation & Safety Compliance | 5/5 | Complete |
| 2 | User Authentication & Account Management | 4/4 | Complete |
| 3 | Data Source Connection | 7/7 | Complete |
| 4 | Real-Time Glucose Dashboard | 6/6 | **Complete** |
| 5 | AI-Powered Analysis & Recommendations | 8/8 | **Complete** |
| 6 | Intelligent Alerting & Escalation | 7/7 | **Complete** |
| 7 | Telegram Bot Integration | 6/6 | **Complete** |
| 8 | Caregiver Access & Support | 6/6 | **Complete** |
| 9 | Settings & Data Management | 5/5 | **Complete** |
| 10 | Settings Infrastructure Fixes | 3/3 | **Complete** |
| 11 | AI Configuration & Chat Interface | 3/3 | **Complete** |
| 12 | Integration & Communication Config | 4/4 | **Complete** |
| 13 | E2E Testing & Real Data Verification | 3/3 | **Complete** |
| 14 | Expanded AI Provider Support | 4/4 | **Complete** |
| 15 | Frontend Auth UI & Route Protection | 8/8 | **Complete** |
| 16 | Android Mobile App with BLE Pump Connectivity | 13/13 | **Complete** |
| 17 | BLE Data Pipeline Debugging & Fixes | 4/4 | **Complete** |
| 18 | App Bug Fixes | 6/6 | **Complete** |
| 19 | BLE Reliability & History | 2/2 | **Complete** |
| 20 | Mobile App Redesign & Foundation | 8/8 | **Complete** |
| 21 | BLE History Log Backfill (CGM + Bolus + Basal) | 2/2 | **Complete** |
| 22 | Web Dashboard Chart & Pump Status Enhancements | 2/2 | **Complete** |
| 23 | Legal & Regulatory Compliance | 1/2 | **In Progress** |
| 24 | Modular Plugin Architecture | 6/6 | **Complete** |
| 25 | Background Service Resilience | 0/1 | Planned |
| 26 | Runtime Plugin Loading | 0/7 | Planned |
| 27 | External Platform Integrations (Backend) | 0/5 | Planned |
| 28 | Security Hardening & Penetration Testing | 17/17 | **Complete** |

**MVP Stories:** 54/54 complete (100%)
**Post-MVP Fix Stories:** 13/13 complete (100%)
**Epic 14 (AI Provider Expansion):** 4/4 complete
**Epic 15 (Frontend Auth UI):** 8/8 complete
**Epic 16 (Mobile App + BLE):** 13/13 complete
**Epic 17 (BLE Data Fixes):** 4/4 complete
**Epic 18 (App Bug Fixes):** 6/6 complete
**Epic 19 (BLE Reliability & History):** 2/2 complete
**Epic 20 (Mobile Redesign):** 8/8 complete
**Epic 21 (BLE History Log Backfill):** 2/2 complete
**Epic 22 (Dashboard Chart & Pump Status):** 2/2 complete
**Epic 23 (Legal & Regulatory):** 1/2 complete
**Epic 24 (Plugin Architecture):** 6/6 complete
**Epic 27 (Platform Integrations):** 0/5 planned
**Epic 28 (Security Hardening):** 17/17 complete
**Overall Progress:** 141/159 stories complete

### Standalone Bug Fixes

| Fix | Description | Status | PR |
|-----|-------------|--------|-----|
| Session Persistence | Preserve mobile session on transient 5xx/network errors (was clearing all tokens on any failure) | Done | [#276](https://github.com/jlengelbrecht/GlycemicGPT/pull/276) |
| Notification Permission | Request POST_NOTIFICATIONS runtime permission on Android 13+, add Settings notification section | Done | [#276](https://github.com/jlengelbrecht/GlycemicGPT/pull/276) |
| Boot AlertStream | Restart AlertStreamService after device reboot when user is logged in | Done | [#276](https://github.com/jlengelbrecht/GlycemicGPT/pull/276) |
| Alert Notification Spam | Stable notification IDs, local dedup, severity-aware sound, "Got It" acknowledge button | Done | [#277](https://github.com/jlengelbrecht/GlycemicGPT/pull/277) |
| Custom Alert Sounds | Per-category sound customization (low/high/AI), versioned notification channels, DND bypass, volume boost for lows, ringtone picker in Settings | Done | [#278](https://github.com/jlengelbrecht/GlycemicGPT/pull/278) |

---

## Epic 1: Foundation & Safety Compliance

**Status:** Complete
**Retrospective:** [epic-1-retrospective.md](implementation-artifacts/epic-1-retrospective.md)

| Story | Title | Status | PR |
|-------|-------|--------|-----|
| 1.1 | Project Scaffolding & Docker Setup | Done | Initial commit |
| 1.2 | Database Migrations & Health Endpoint | Done | Initial commit |
| 1.3 | First-Run Safety Disclaimer | Done | Initial commit |
| 1.4 | Kubernetes Deployment Manifests | Done | Initial commit |
| 1.5 | Structured Logging & Backup Configuration | Done | Initial commit |

---

## Epic 2: User Authentication & Account Management

**Status:** Complete
**Retrospective:** [epic-2-retrospective.md](implementation-artifacts/epic-2-retrospective.md)

| Story | Title | Status | PR |
|-------|-------|--------|-----|
| 2.1 | User Registration | Done | Initial commit |
| 2.2 | User Login & Session Management | Done | Initial commit |
| 2.3 | User Logout | Done | Initial commit |
| 2.4 | Role-Based Access Control | Done | Initial commit |

---

## Epic 3: Data Source Connection

**Status:** Complete
**Retrospective:** Pending

| Story | Title | Status | PR |
|-------|-------|--------|-----|
| 3.1 | Dexcom Credential Configuration | Done | Initial commit |
| 3.2 | Dexcom CGM Data Ingestion | Done | Initial commit |
| 3.3 | Tandem Credential Configuration | Done | Initial commit |
| 3.4 | Tandem Pump Data Ingestion | Done | Initial commit |
| 3.5 | Control-IQ Activity Parsing | Done | Initial commit |
| 3.6 | Data Freshness Display | Done | Initial commit |
| 3.7 | IoB Projection Engine | Done | [#1](https://github.com/jlengelbrecht/GlycemicGPT/pull/1) |

---

## Epic 4: Real-Time Glucose Dashboard

**Status:** Complete
**Retrospective:** Pending

| Story | Title | Status | PR |
|-------|-------|--------|-----|
| 4.1 | Dashboard Layout & Navigation | Done | [#3](https://github.com/jlengelbrecht/GlycemicGPT/pull/3) |
| 4.2 | GlucoseHero Component | Done | [#20](https://github.com/jlengelbrecht/GlycemicGPT/pull/20) |
| 4.3 | TrendArrow Component | Done | [#22](https://github.com/jlengelbrecht/GlycemicGPT/pull/22) |
| 4.4 | TimeInRangeBar Component | Done | [#24](https://github.com/jlengelbrecht/GlycemicGPT/pull/24) |
| 4.5 | Real-Time Updates via SSE | Done | [#26](https://github.com/jlengelbrecht/GlycemicGPT/pull/26) |
| 4.6 | Dashboard Accessibility | Done | Pending |

---

## Epic 5: AI-Powered Analysis & Recommendations

**Status:** Complete

| Story | Title | Status | PR |
|-------|-------|--------|----|
| 5.1 | AI Provider Configuration | Done | [#30](https://github.com/jlengelbrecht/GlycemicGPT/pull/30) |
| 5.2 | BYOAI Abstraction Layer | Done | [#32](https://github.com/jlengelbrecht/GlycemicGPT/pull/32) |
| 5.3 | Daily Brief Generation | Done | [#34](https://github.com/jlengelbrecht/GlycemicGPT/pull/34) |
| 5.4 | Pattern Recognition & Carb Ratio Suggestions | Done | [#36](https://github.com/jlengelbrecht/GlycemicGPT/pull/36) |
| 5.5 | Correction Factor Suggestions | Done | [#38](https://github.com/jlengelbrecht/GlycemicGPT/pull/38) |
| 5.6 | Pre-Validation Safety Layer | Done | [#40](https://github.com/jlengelbrecht/GlycemicGPT/pull/40) |
| 5.7 | AIInsightCard Component | Done | [#44](https://github.com/jlengelbrecht/GlycemicGPT/pull/44) |
| 5.8 | AI Reasoning Display & Audit Logging | Done | [#46](https://github.com/jlengelbrecht/GlycemicGPT/pull/46) |

---

## Epic 6: Intelligent Alerting & Escalation

**Status:** Complete

| Story | Title | Status | PR |
|-------|-------|--------|----|
| 6.1 | Alert Threshold Configuration | Done | [#48](https://github.com/jlengelbrecht/GlycemicGPT/pull/48) |
| 6.2 | Predictive Alert Engine | Done | [#50](https://github.com/jlengelbrecht/GlycemicGPT/pull/50) |
| 6.3 | Tiered Alert Delivery | Done | [#52](https://github.com/jlengelbrecht/GlycemicGPT/pull/52) |
| 6.4 | AlertCard Component with Acknowledgment | Done | [#54](https://github.com/jlengelbrecht/GlycemicGPT/pull/54) |
| 6.5 | Emergency Contact Configuration | Done | [#56](https://github.com/jlengelbrecht/GlycemicGPT/pull/56) |
| 6.6 | Escalation Timing Configuration | Done | [#58](https://github.com/jlengelbrecht/GlycemicGPT/pull/58) |
| 6.7 | Automatic Escalation to Caregivers | Done | [#60](https://github.com/jlengelbrecht/GlycemicGPT/pull/60) |

---

## Epic 7: Telegram Bot Integration

**Status:** Complete

| Story | Title | Status | PR |
|-------|-------|--------|----|
| 7.1 | Telegram Bot Setup & Configuration | Done | [#62](https://github.com/jlengelbrecht/GlycemicGPT/pull/62) |
| 7.2 | Alert Delivery via Telegram | Done | [#64](https://github.com/jlengelbrecht/GlycemicGPT/pull/64) |
| 7.3 | Daily Brief via Telegram | Done | [#66](https://github.com/jlengelbrecht/GlycemicGPT/pull/66) |
| 7.4 | Telegram Command Handlers | Done | [#68](https://github.com/jlengelbrecht/GlycemicGPT/pull/68) |
| 7.5 | AI Chat via Telegram | Done | [#75](https://github.com/jlengelbrecht/GlycemicGPT/pull/75) |
| 7.6 | Caregiver Telegram Access | Done | [#77](https://github.com/jlengelbrecht/GlycemicGPT/pull/77) |

---

## Epic 8: Caregiver Access & Support

**Status:** Complete

| Story | Title | Status | PR |
|-------|-------|--------|----|
| 8.1 | Caregiver Account Creation & Linking | Done | #78 |
| 8.2 | Caregiver Data Access Configuration | Done | #80 |
| 8.3 | Caregiver Dashboard View | Done | #82 |
| 8.4 | Caregiver AI Queries | Done | #84 |
| 8.5 | Multi-Patient Dashboard | Done | #86 |
| 8.6 | Caregiver Read-Only Enforcement | Done | #88 |

---

## Epic 9: Settings & Data Management

**Status:** Complete (5/5)

| Story | Title | Status | PR |
|-------|-------|--------|----|
| 9.1 | Target Glucose Range Configuration | Done | #90 |
| 9.2 | Daily Brief Delivery Configuration | Done | #92 |
| 9.3 | Data Retention Settings | Done | #94 |
| 9.4 | Data Purge Capability | Done | #96 |
| 9.5 | Settings Export | Done | PR pending |

---

## Release History

| Version | Date | Notable Features |
|---------|------|------------------|
| 0.1.88 | 2026-02-14 | BLE auth protocol fixes, CRC byte order fix |
| 0.1.87 | 2026-02-14 | BLE runtime permission requests |
| 0.1.86 | 2026-02-13 | Cleartext request prevention for unconfigured server URL |
| 0.1.85 | 2026-02-13 | Security hardening: token refresh, rate limiting, TLS (Story 16.12) |
| 0.1.84 | 2026-02-13 | Caregiver & emergency contact push notifications (Story 16.11) |
| 0.1.83 | 2026-02-12 | Wear OS watch face, alerts, AI voice chat (Story 16.9) |
| 0.1.82 | 2026-02-12 | GitHub self-update mechanism (Story 16.13) |
| 0.1.81 | 2026-02-12 | App settings & configuration (Story 16.8) |
| 0.1.80 | 2026-02-11 | Removed CLAUDE.md and _bmad-output from repo |
| 0.1.79 | 2026-02-11 | Home screen dashboard with CGM, freshness, pull-to-refresh (Story 16.7) |
| 0.1.78 | 2026-02-11 | Tandem cloud upload pipeline (Story 16.6) |
| 0.1.77 | 2026-02-10 | R8 keep rule fix, ExperimentalCoroutinesApi OptIn |
| 0.1.76 | 2026-02-10 | Backend sync -- real-time pump data to API (Story 16.5) |
| 0.1.9 | 2026-02-08 | Real-time SSE updates (Story 4.5) |
| 0.1.8 | 2026-02-08 | TimeInRangeBar component (Story 4.4) |
| 0.1.7 | 2026-02-08 | TrendArrow component (Story 4.3) |
| 0.1.6 | 2026-02-07 | GlucoseHero component (Story 4.2) |
| 0.1.1 | 2026-02-07 | Foundation, Auth, Data Sources, Dashboard Layout |

---

## Current Sprint Focus

**Epic 17: BLE Data Pipeline Debugging & Fixes** - COMPLETE

After completing Epic 16 and achieving first successful JPAKE pump connection, real-world testing revealed BLE data parsing issues. This epic focuses on fixing those:

1. Story 17.1: BLE Debug Instrumentation (add hex logging, in-app debug viewer)
2. Story 17.2: Mobile Dev Environment Setup (scripts, docs for iterative testing)
3. Story 17.3: Fix Status Response Parsers (blocked on 17.1 -- needs real hex data)
4. Story 17.4: Fix Connection Stability (GATT disconnect handling, request staggering)

**Also in-flight:** Branch `fix/ble-auth-protocol` has BLE auth protocol fixes and EC-JPAKE implementation for firmware v7.7+ pumps (not yet merged to main).

**Previous:** Epic 16 completed 13/13 stories. Full details: [epic-16-mobile-app-ble.md](planning-artifacts/epic-16-mobile-app-ble.md)

---

## Previous Sprint History

**Epic 16: Android Mobile App with BLE Pump Connectivity** - COMPLETE

All 13 stories completed:
- [x] Story 16.1: Android Project Scaffolding & Build Configuration
- [x] Story 16.2: BLE Connection Manager & Pump Pairing
- [x] Story 16.3: PumpDriver Interface & Tandem BLE Implementation
- [x] Story 16.4: Real-Time Data Polling & Local Storage
- [x] Story 16.5: Backend Sync -- Push Real-Time Data to GlycemicGPT API
- [x] Story 16.6: Tandem Cloud Upload at Faster Intervals
- [x] Story 16.7: App Home Screen & Pump Status Dashboard
- [x] Story 16.8: App Settings & Configuration
- [x] Story 16.9: Wear OS Watch Face, Alerts & AI Voice Chat
- [x] Story 16.10: TTS/STT Voice AI Chat
- [x] Story 16.11: Caregiver & Emergency Contact Push Notifications
- [x] Story 16.12: Security Hardening & Backend Exposure
- [x] Story 16.13: GitHub Self-Update (xDrip+-style)

**Epic 6: Intelligent Alerting & Escalation** - COMPLETE

All 7 stories completed:
- [x] Story 6.1: Alert Threshold Configuration
- [x] Story 6.2: Predictive Alert Engine
- [x] Story 6.3: Tiered Alert Delivery
- [x] Story 6.4: AlertCard Component with Acknowledgment
- [x] Story 6.5: Emergency Contact Configuration
- [x] Story 6.6: Escalation Timing Configuration
- [x] Story 6.7: Automatic Escalation to Caregivers

**Epic 7: Telegram Bot Integration** - COMPLETE

All 6 stories completed:
- [x] Story 7.1: Telegram Bot Setup & Configuration
- [x] Story 7.2: Alert Delivery via Telegram
- [x] Story 7.3: Daily Brief via Telegram
- [x] Story 7.4: Telegram Command Handlers
- [x] Story 7.5: AI Chat via Telegram
- [x] Story 7.6: Caregiver Telegram Access

**Epic 8: Caregiver Access & Support** - COMPLETE

All 6 stories completed:
- [x] Story 8.1: Caregiver Account Creation & Linking
- [x] Story 8.2: Caregiver Data Access Configuration
- [x] Story 8.3: Caregiver Dashboard View
- [x] Story 8.4: Caregiver AI Queries
- [x] Story 8.5: Multi-Patient Dashboard
- [x] Story 8.6: Caregiver Read-Only Enforcement

**Epic 9: Settings & Data Management** - COMPLETE

All 5 stories completed:
- [x] Story 9.1: Target Glucose Range Configuration
- [x] Story 9.2: Daily Brief Delivery Configuration
- [x] Story 9.3: Data Retention Settings
- [x] Story 9.4: Data Purge Capability
- [x] Story 9.5: Settings Export

---

## Post-MVP Fix Epics (from manual testing feedback)

**Epic 10: Settings Infrastructure Fixes** - COMPLETE

- [x] Story 10.1: Fix Save Changes Button Across All Settings Pages
- [x] Story 10.2: Create Settings > Profile Page - [PR #105](https://github.com/jlengelbrecht/GlycemicGPT/pull/105)
- [x] Story 10.3: Create Settings > Alerts Page - [PR #107](https://github.com/jlengelbrecht/GlycemicGPT/pull/107)

**Epic 11: AI Configuration & Chat Interface** - COMPLETE

- [x] Story 11.1: Create AI Provider Configuration Page - [PR #117](https://github.com/jlengelbrecht/GlycemicGPT/pull/117)
- [x] Story 11.2: Create Web-Based AI Chat Interface - [PR #119](https://github.com/jlengelbrecht/GlycemicGPT/pull/119)
- [x] Story 11.3: Wire Daily Briefs Web Delivery - [PR #121](https://github.com/jlengelbrecht/GlycemicGPT/pull/121)

**Epic 12: Integration & Communication Configuration** - COMPLETE

- [x] Story 12.1: Create Settings > Integrations Page - [PR #109](https://github.com/jlengelbrecht/GlycemicGPT/pull/109)
- [x] Story 12.2: Redesign Communications Settings Hub - [PR #113](https://github.com/jlengelbrecht/GlycemicGPT/pull/113)
- [x] Story 12.3: Add Telegram Bot Token Configuration - [PR #115](https://github.com/jlengelbrecht/GlycemicGPT/pull/115)
- [x] Story 12.4: Graceful Offline/Disconnected State for All Settings - [PR #111](https://github.com/jlengelbrecht/GlycemicGPT/pull/111)

**Epic 13: End-to-End Testing & Real Data Verification** - COMPLETE

- [x] Story 13.1: Local Dev Server Testing Checklist - [PR #123](https://github.com/jlengelbrecht/GlycemicGPT/pull/123)
- [x] Story 13.2: Docker Container Integration Testing - [PR #124](https://github.com/jlengelbrecht/GlycemicGPT/pull/124)
- [x] Story 13.3: Real Data Pipeline Verification - [PR #125](https://github.com/jlengelbrecht/GlycemicGPT/pull/125)

---

## Epic 14: Expanded AI Provider Support

**Goal:** Expand AI provider system from 2 to 5 types: Claude Subscription, ChatGPT Subscription, Claude API, OpenAI API, Self-Hosted/BYOAI.

**Epic Details:** [epic-14-expanded-ai-providers.md](planning-artifacts/epic-14-expanded-ai-providers.md)

- [x] Story 14.1: Database Migration for Expanded Provider Types - [PR #128](https://github.com/jlengelbrecht/GlycemicGPT/pull/128)
- [x] Story 14.2: Backend Support for 5 Provider Types - [PR #128](https://github.com/jlengelbrecht/GlycemicGPT/pull/128)
- [x] Story 14.3: Frontend AI Provider Page Redesign - [PR #128](https://github.com/jlengelbrecht/GlycemicGPT/pull/128)
- [x] Story 14.4: Tests for Expanded Provider System - [PR #128](https://github.com/jlengelbrecht/GlycemicGPT/pull/128)

---

## Epic 15: Frontend Authentication UI & Route Protection

**Goal:** Build login/register pages, add Next.js middleware for route protection, fix logout, add global 401 handling, and enforce post-login disclaimer. Discovered during Docker deployment testing - the backend auth system (Epic 2) is complete but the frontend has no auth pages or route protection.

**Epic Details:** [epic-15-frontend-auth-ui.md](planning-artifacts/epic-15-frontend-auth-ui.md)

- [x] Story 15.1: Login Page - [PR #147](https://github.com/jlengelbrecht/GlycemicGPT/pull/147)
- [x] Story 15.2: Registration Page - [PR #149](https://github.com/jlengelbrecht/GlycemicGPT/pull/149)
- [x] Story 15.3: Next.js Auth Middleware & Route Protection - [PR #151](https://github.com/jlengelbrecht/GlycemicGPT/pull/151)
- [x] Story 15.4: Logout, Auth State & Global 401 Handling - [PR #153](https://github.com/jlengelbrecht/GlycemicGPT/pull/153)
- [x] Story 15.5: Post-Login Disclaimer Enforcement - [PR #157](https://github.com/jlengelbrecht/GlycemicGPT/pull/157)
- [x] Story 15.6: Landing Page & Auth Navigation Polish (implemented in prior stories)
- [x] Story 15.7: Enhance AI Chat with Comprehensive Pump Data Context - [PR #161](https://github.com/jlengelbrecht/GlycemicGPT/pull/161)
- [x] Story 15.8: Sync Pump Settings & Therapy Data from Tandem APIs - [PR #163](https://github.com/jlengelbrecht/GlycemicGPT/pull/163)

---

## Epic 16: Android Mobile App with BLE Pump Connectivity

**Goal:** Build an Android app that connects to the Tandem t:slim X2 pump via BLE for real-time data (IoB, basal, BG), uploads to Tandem cloud at 5-15 min intervals, syncs to GlycemicGPT backend in real-time, and includes a Wear OS watch face, TTS voice AI chat, and native caregiver push notifications. READ-ONLY pump access only -- no insulin delivery or pump control.

**Epic Details:** [epic-16-mobile-app-ble.md](planning-artifacts/epic-16-mobile-app-ble.md)

- [x] Story 16.1: Android Project Scaffolding & Build Configuration (PR #168)
- [x] Story 16.2: BLE Connection Manager & Pump Pairing (PR #169)
- [x] Story 16.3: PumpDriver Interface & Tandem BLE Implementation (PR #173)
- [x] Story 16.4: Real-Time Data Polling & Local Storage (PR #175)
- [x] Story 16.5: Backend Sync -- Push Real-Time Data to GlycemicGPT API (PR #177)
- [x] Story 16.6: Tandem Cloud Upload at Faster Intervals (PR #179)
- [x] Story 16.7: App Home Screen & Pump Status Dashboard
- [x] Story 16.8: App Settings & Configuration - [PR #185](https://github.com/jlengelbrecht/GlycemicGPT/pull/185)
- [x] Story 16.9: Wear OS Watch Face, Alerts & AI Voice Chat - [PR #189](https://github.com/jlengelbrecht/GlycemicGPT/pull/189)
- [x] Story 16.10: TTS/STT Voice AI Chat - [PR #191](https://github.com/jlengelbrecht/GlycemicGPT/pull/191)
- [x] Story 16.11: Caregiver & Emergency Contact Push Notifications - [PR #192](https://github.com/jlengelbrecht/GlycemicGPT/pull/192)
- [x] Story 16.12: Security Hardening & Backend Exposure - [PR #194](https://github.com/jlengelbrecht/GlycemicGPT/pull/194)
- [x] Story 16.13: GitHub Self-Update (xDrip+-style) - [PR #187](https://github.com/jlengelbrecht/GlycemicGPT/pull/187)

---

## Epic 17: BLE Data Pipeline Debugging & Fixes

**Goal:** Fix the BLE data parsing bugs discovered after first successful JPAKE pump connection. IoB, basal rate, reservoir, battery, and CGM values are either wrong or missing. Connection cycles between Connecting/Reconnecting. Root cause: StatusResponseParser byte layouts were written from pumpX2 source study without validation against actual pump BLE responses. This epic adds debug instrumentation to see real hex data, sets up a proper mobile dev environment for iterative testing, fixes the parsers, and stabilizes the connection.

**Plan Details:** [Plan file](../../.claude/plans/elegant-floating-hennessy.md)

- [x] Story 17.1: BLE Debug Instrumentation (PR #204)
  - Added BLE_RAW hex logging to TandemBleDriver and BleConnectionManager
  - Created BleDebugStore (circular buffer, 100 entries, no-op in release)
  - Created BleDebugScreen + ViewModel (in-app raw data viewer)
  - Added navigation to debug screen (debug builds only via BuildConfig.DEBUG)
  - Added opcodeName() mapping for all Tandem protocol opcodes
  - Hex scrubbed from Timber.e paths for release safety
- [x] Story 17.2: Mobile Dev Environment Setup (PR #204)
  - Created `scripts/mobile-dev.sh` (emulator start/stop/install, phone install/logcat/ble-raw)
  - Configured mobile-mcp MCP server for Android emulator + physical phone
  - Added testTag modifiers to HomeScreen, SettingsScreen, PairingScreen
  - Updated CLAUDE.md with two-phase mobile dev workflow
  - Validated mobile-mcp with emulator and Galaxy S25 Ultra (wireless ADB)
- [x] Story 17.3: Fix Status Response Parsers (PR #206)
  - Fixed 5 wrong opcode pairs in TandemProtocol.kt (Basal, Insulin, Battery, CGM, HomeScreenMirror)
  - Rewrote all StatusResponseParser methods with correct byte layouts from pumpX2
  - Added Battery V1/V2 fallback (V2 for fw v7.7+, V1 for older)
  - Split CGM into EGV (glucose) + HomeScreenMirror (trend arrows) with graceful degradation
  - Accept LOW/HIGH CGM status codes for clinically important out-of-range readings
  - Rewrote tests with pumpX2-verified hex test vectors (228 tests passing)
  - Adversarial review: 11 findings, all addressed
- [x] Story 17.4: Fix Connection Stability (PR #204, extended in PR #206)
  - Added 500ms post-auth settle delay in BleConnectionManager with race-condition guard
  - Added 2s initial poll delay + 200ms request stagger in PumpPollingOrchestrator
  - Removed duplicate refreshData() LaunchedEffect race in HomeScreen
  - Made HomeViewModel.refreshData() sequential with stagger delays
  - Added "Loading pump data..." indicator for connected-but-no-data state
  - Skip JPAKE on reconnect for bonded pumps (fixes status 19 rejection loop)
  - Set autoReconnect=true in connect() (was missing after unpair+pair flow)
  - Bond-loss detection: rapid disconnect counter + insufficient auth -> AUTH_FAILED
  - Reduced fast poll interval 30s -> 15s (pump idle timeout is ~30s)
  - Full adversarial review: all HIGH/MEDIUM findings addressed

---

## Epic 18: App Bug Fixes

**Goal:** Fix user-reported bugs across the mobile and web apps: non-functional AI Chat tab, stale pump data requiring manual pull-to-refresh, broken Tandem Cloud Sync settings, background BLE persistence, and web session redirect loop.

- [x] Story 18.1: Implement AI Chat Screen (PR #214)
  - **Bug:** Tapping "AI Chat" in bottom navigation shows a blank placeholder screen (just centered text "AI Chat") with no actual chat interface
  - **Root cause:** `AiChatScreen.kt` delegates to `PlaceholderScreen(title = "AI Chat")` -- never implemented beyond placeholder
  - **Acceptance criteria:**
    - AI Chat tab opens a functional chat interface with text input, send button, and message history
    - Messages are sent to the backend AI sidecar (`/api/ai/chat`) and responses displayed
    - Pump context (current glucose, IoB, basal, recent boluses) is included in chat context
    - Chat works when backend is reachable; shows offline state when it isn't
    - Matches the web app's AI Chat functionality
  - **Key files:** `AiChatScreen.kt`, `NavHost.kt:79`, `PlaceholderScreen.kt`, `GlycemicGptApi.kt`
- [x] Story 18.2: Fix Auto-Refresh for Reservoir, Battery, and CGM Cards (PR #220)
  - **Bug:** Reservoir, Battery, and Last BG cards only update when user manually pulls down to refresh on the home screen. They should auto-update on their polling intervals without user intervention
  - **Current behavior:** IoB and Basal update automatically ("just now"), but Reservoir/Battery show "12m ago" and Last BG shows stale until pull-to-refresh
  - **Investigation needed:**
    - Slow loop polls battery + reservoir every 15 min (`INTERVAL_SLOW_MS = 900_000L`) -- verify this loop is actually running and its results flow to the UI
    - CGM is in the fast loop (15s) but "Last BG" may not be updating -- check if `parseCgmEgvResponse` results are reaching the HomeViewModel's StateFlow
    - Check if Room DAO queries / Flow collectors are properly wired for reservoir, battery, CGM
    - The slow loop has a 120s initial delay (`SLOW_LOOP_INITIAL_DELAY_MS`) -- verify this isn't preventing updates
  - **Acceptance criteria:**
    - Reservoir and Battery update automatically every 15 minutes (slow poll) without manual refresh
    - Last BG updates automatically every 15 seconds (fast poll) without manual refresh
    - Timestamps on all cards reflect when data was actually polled, not stale values
    - Pull-to-refresh still works as a manual override
  - **Key files:** `PumpPollingOrchestrator.kt:158-172` (slow loop), `HomeViewModel.kt`, `HomeScreen.kt:73-77` (pull-to-refresh), `PumpDataRepository.kt`
- [x] Story 18.3: Move Tandem Cloud Upload Settings from Mobile to Web -- PR #222
  - **Bug:** Tandem Cloud Sync in Settings shows "No uploads yet" and "No pump hardware info available. Pair your pump first." even though the pump IS connected and paired
  - **Design decision:** Tandem Cloud Sync should be handled via the Docker stack (backend), NOT from the mobile app directly. The mobile app's role is to sync raw BLE data to the backend via the existing `/api/integrations/pump/push` endpoint; the backend handles the cloud upload to Tandem
  - **Investigation needed:**
    - Backend endpoints: `GET /api/integrations/tandem/cloud-upload/status`, `PUT .../settings`, `POST .../trigger` -- check if these are implemented or returning errors
    - The "no pump hardware info" error likely comes from the backend not finding PumpGlobals data -- check if PumpGlobals (opcode 87) is being polled and synced to backend
    - Cloud sync may be trying to use pump hardware info that the mobile app pushes, but PumpGlobals parsing may not be working correctly
  - **Acceptance criteria:**
    - When pump is paired and connected, the cloud sync status screen shows pump info (not the "pair your pump" error)
    - Settings correctly toggle cloud sync on/off via the backend
    - Upload interval setting is persisted and respected
    - "Upload Now" button triggers a backend upload and shows success/failure
    - If cloud sync is handled entirely by the Docker stack, update the UI to reflect that (e.g., show backend sync status instead of direct upload controls)
  - **Key files:** `SettingsScreen.kt:821-978` (UI), `TandemCloudSyncViewModel.kt` (state), `GlycemicGptApi.kt:43-52` (API endpoints), backend `apps/api/src/` (cloud upload service)
- [x] Story 18.4: Background BLE Persistence and Sync Reliability -- PR #219
  - **Bug:** When the phone screen turns off or the phone goes to sleep, the app stops communicating with the pump and stops syncing data to the backend. User woke up to 1000+ pending sync queue items and a disconnected pump despite leaving the app connected overnight.
  - **Root cause analysis:**
    - `PumpConnectionService` is a foreground service with `START_STICKY` but does NOT hold a `PARTIAL_WAKE_LOCK` -- CPU suspends, coroutine polling loops freeze
    - App does not request `REQUEST_IGNORE_BATTERY_OPTIMIZATIONS` -- Android Doze mode throttles BLE and network operations
    - `WAKE_LOCK` permission is only declared in the Wear module manifest, not the phone app manifest
    - `BackendSyncManager.syncLoop()` runs on a coroutine `delay(3000)` which is unreliable during Doze -- sync stalls, queue grows unbounded
    - `BleConnectionManager` reconnect uses coroutine `delay()` for exponential backoff which gets stretched/skipped in Doze
    - `AlertStreamService` uses `readTimeout(0)` (infinite) on SSE stream -- hangs silently when Doze throttles network
    - No automatic cleanup of failed `SyncQueueEntity` items after max retries -- they accumulate forever
  - **Required fixes:**
    1. **Add WAKE_LOCK permission** to phone app `AndroidManifest.xml`
    2. **Acquire PARTIAL_WAKE_LOCK** in `PumpConnectionService.onStartCommand()` -- release in `onDestroy()`
    3. **Request battery optimization exemption** -- prompt user via `ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS` on first pump pair (or in Settings)
    4. **Add AlarmManager fallback** for polling -- `setExactAndAllowWhileIdle()` can fire during Doze maintenance windows to ensure BLE keep-alive
    5. **Add finite timeout on SSE stream** in `AlertStreamService` to detect Doze throttling and reconnect
    6. **Add sync queue cleanup** -- purge items older than 24h or past max retries in `BackendSyncManager`
    7. **Add wake lock around BLE reconnect** -- hold lock during reconnect attempt to prevent CPU suspension mid-handshake
  - **Acceptance criteria:**
    - Pump BLE connection persists when screen off, app backgrounded, and phone sleeping overnight
    - Polling loops (fast/medium/slow) continue running during screen-off with no more than 1 missed cycle
    - Backend sync queue stays bounded (no 1000+ item accumulation)
    - User is prompted to disable battery optimization for the app (one-time, on first pump pair)
    - Battery impact is reasonable (foreground notification already shown, wake lock is partial CPU only)
    - Reconnect works reliably if pump temporarily goes out of BLE range and returns
  - **Key files:** `PumpConnectionService.kt:32-142`, `AndroidManifest.xml:5-28`, `BleConnectionManager.kt:252-258,406-423` (reconnect), `BackendSyncManager.kt:70-100` (sync loop), `AlertStreamService.kt:68` (SSE timeout), `PumpPollingOrchestrator.kt:70-119` (polling loops)
  - **Reference:** Other diabetes apps (xDrip+, AAPS, Loop) all use wake locks + battery exemption for reliable background BLE
- [x] Story 18.5: Fix Web App Auth (Cross-Origin Cookies + Redirect Loop) -- PR #211
  - **Bug 1 -- Login doesn't work:** Signing in returns 200 OK but the session cookie is set for `localhost` domain while the web app is accessed at `10.20.66.40:3000`. The browser never sends the cookie to the web server, so middleware always sees "no session" and redirects back to `/login`.
  - **Bug 2 -- Redirect loop on stale cookie:** When a user has an expired/stale session cookie, the web app enters an infinite redirect loop between `/login` and `/dashboard`, causing the page to hang.
  - **Root cause (shared):** The Dockerfile does NOT consume the `NEXT_PUBLIC_API_URL` build arg. `docker-compose.override.yml` passes `args: NEXT_PUBLIC_API_URL: http://10.20.66.40:8000` but the Dockerfile has no `ARG NEXT_PUBLIC_API_URL` in the builder stage. So `npm run build` bakes in the fallback `http://localhost:8000` from `api.ts:9`. All client-side API calls go to `localhost:8000`, causing cross-origin cookie domain mismatch.
  - **Login flow (broken):**
    1. Browser at `10.20.66.40:3000/login` → JS sends `POST http://localhost:8000/api/auth/login` → 200 OK
    2. API sets `Set-Cookie: glycemicgpt_session=...` for `localhost` domain
    3. Browser navigates to `10.20.66.40:3000/dashboard` -- cookie for `localhost` is NOT sent
    4. Middleware sees no cookie → redirects to `/login`
    5. User is stuck despite valid credentials
  - **Redirect loop flow (stale cookie):**
    1. Stale cookie exists → middleware allows `/dashboard` → API returns 401
    2. `apiFetch` 401 handler redirects to `/login?expired=true`
    3. Middleware sees stale cookie → redirects back to `/dashboard` → loop
  - **Required fixes:**
    1. **Fix Dockerfile build arg:** Add `ARG NEXT_PUBLIC_API_URL=http://localhost:8000` and `ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL` in the builder stage before `RUN npm run build`. This ensures the override URL gets baked into the client bundle.
    2. **Clear cookie on 401:** In `apiFetch()` 401 handler (`api.ts:36-41`), delete `glycemicgpt_session` cookie before redirecting to `/login`. Breaks the stale cookie loop.
    3. **Middleware guard for `?expired=true`:** Skip the redirect-to-dashboard logic when `?expired=true` is present, so the login page renders even if a stale cookie exists.
    4. **Long-term (optional):** Proxy API calls through Next.js rewrites so all cookies are on the same domain regardless of deployment topology.
  - **Acceptance criteria:**
    - Login works when accessing the web app from any URL (localhost, LAN IP, domain)
    - Session cookie is set for the correct domain
    - User with expired session is cleanly redirected to `/login` with no loop
    - Expired session banner displays correctly
    - No page hangs, no infinite navigation
    - `docker compose up --build` with override produces a working login flow at `10.20.66.40:3000`
  - **Key files:** `Dockerfile:25-32` (missing ARG), `docker-compose.override.yml:10-14`, `docker-compose.yml:86-87`, `api.ts:9,36-41`, `middleware.ts:14-35`, `login/page.tsx:62-82`
- [x] Story 18.6: Fix Time in Range Bar Showing Mock Data (Web) -- PR #213
  - **Bug:** TIR bar displayed hardcoded mock data (78%/5%/17%) instead of real glucose data
  - **Solution:**
    - Added `GET /api/integrations/glucose/time-in-range` endpoint with SQL CASE/SUM aggregation
    - Uses user's configured target glucose range thresholds (not hardcoded 70/180)
    - Created `useTimeInRangeStats` hook with period selection and stale-response prevention
    - Added interactive period selector (24h, 3d, 7d, 14d, 30d) matching glucose trend chart pattern
    - Summary card label dynamically reflects selected period
    - Rate-limited at 30 req/min, rounding guarantees sum = 100%
    - No-data state returns zeros (not misleading 100% in-range)
  - **Key files:** `integrations.py:740-805`, `use-time-in-range-stats.ts`, `time-in-range-bar.tsx`, `dashboard/page.tsx`, `api.ts`

---

## Epic 19: BLE Reliability & History

**Goal:** Implement BLE history log download from the Tandem pump and fix critical reconnection stability bugs that caused overnight data loss.

- [x] Story 19.1: BLE History Log Download -- PR #226
  - **Feature:** Query the pump's history log sequence range via opcode 58 (HistoryLogStatus)
  - **Implementation:**
    - `StatusResponseParser.parseHistoryLogStatusResponse()` reads 12-byte response (numEntries + firstSeq + lastSeq, little-endian uint32)
    - `TandemBleDriver.getHistoryLogs()` queries range and returns it for diagnostics (actual record streaming via opcode 60/FFF8 requires further reverse-engineering)
    - Added `HistoryLogRange` and `HistoryLogRecord` domain models
    - Added FFF8 (HISTORY_LOG_UUID) routing in `BleConnectionManager` with hex logging
    - Comprehensive unit tests including real pump data validation
  - **Key files:** `StatusResponseParser.kt`, `TandemBleDriver.kt`, `BleConnectionManager.kt`, `PumpModels.kt`, `StatusResponseParserTest.kt`
- [x] Story 19.2: BLE Reconnection Stability Fix -- PR #228
  - **Bug:** App stopped syncing pump data when phone screen turned off. User woke up to 1010+ pending sync tasks and hours of missing data.
  - **Root causes (3 interacting bugs):**
    1. Bond-loss false positive: Status 19 (PEER_USER) during reconnection misclassified as bond rejection after 3 attempts, permanently disabling autoReconnect. Fix: `hadSuccessfulSession` flag + `consecutiveReconnectFailures` cap (10 attempts)
    2. Broken exponential backoff: `connect()` reset `reconnectAttempt=0` on every call. Fix: `resetCounters` parameter, false from `scheduleReconnect()`
    3. No wake lock during reconnection: PARTIAL_WAKE_LOCK only held during CONNECTED. Fix: 2-minute reconnect wake lock for RECONNECTING/CONNECTING/AUTHENTICATING states
  - **Additional fixes from adversarial review:** `@Volatile` thread safety, reconnectJob race prevention, zeroResponseConnectionCount guard, stale RECONNECTING state cleanup
  - **Phone-verified:** Screen-off test confirmed INSUFFICIENT_ENCRYPTION disconnect recovered in 6 seconds with proper backoff and wake lock
  - **Key files:** `BleConnectionManager.kt`, `PumpConnectionService.kt`

---

## Epic 20: Mobile App Redesign & Foundation

**Goal:** Redesign the mobile app foundation with improved auth reliability, navigation architecture, glucose charting, and pump data architecture for maintainability and user experience.

- [x] Story 20.0: Repository Attribution Cleanup & Prevention Guardrails -- PR #231
  - **Feature:** Remove all AI co-author attribution from git history and prevent recurrence
  - **Implementation:**
    - Rewrote git history with `git-filter-repo` to strip 226 Co-Authored-By trailers from all commits
    - Force-pushed all 29 branches with clean history
    - Created `scripts/hooks/commit-msg` hook that auto-strips prohibited Co-Authored-By lines
    - Added `check-attribution` CI job to fail PRs containing AI attribution
    - Three lines of defense: CLAUDE.md instruction, local hook, CI enforcement
  - **Key files:** `scripts/hooks/commit-msg`, `.github/workflows/ci.yml`
- [x] Story 20.1: Auth Token Persistence & Refresh Reliability -- PR #229
  - **Feature:** Observable auth state management with proactive token refresh
  - **Implementation:**
    - `AuthState` sealed class: Authenticated, Refreshing, Expired, Unauthenticated
    - `AuthManager` with mutex-protected refresh, proactive scheduling (5 min before expiry), startup validation
    - `RefreshClientProvider` with dedicated OkHttpClient (no auth interceptors, prevents recursion)
    - JWT `exp` claim extraction from refresh tokens via regex (avoids android.util.Base64/JSONObject stubs)
    - `SessionExpiredBanner` in NavHost with tap-to-Settings navigation
    - Auth lifecycle integration in SettingsViewModel (login/logout) and GlycemicGptApp (startup)
    - Updated TokenRefreshInterceptor: uses RefreshClientProvider, coordinates with AuthManager, proper response cleanup
  - **Tests:** 14 AuthManager tests, 4 AuthTokenStore JWT tests, updated interceptor + ViewModel tests
  - **Adversarial review:** 14 findings (4 HIGH, 6 MEDIUM, 4 LOW) -- all addressed
  - **Key files:** `AuthManager.kt`, `AuthState.kt`, `RefreshClientProvider.kt`, `AuthTokenStore.kt`, `TokenRefreshInterceptor.kt`, `NavHost.kt`, `SettingsViewModel.kt`, `GlycemicGptApp.kt`
- [x] Story 20.4: Dashboard Redesign -- Glucose Trend Chart -- PR #236
  - **Feature:** Replace standalone status cards with integrated glucose chart and hero display
  - **Implementation:**
    - `GlucoseHero` composable: large color-coded BG value, trend arrow, IoB + Basal as secondary metrics, accessibility semantics
    - `GlucoseTrendChart` composable: custom Canvas-based chart with color-coded glucose dots, target range band (70-180 mg/dL green), IoB area overlay on secondary right Y-axis, 3H/6H/12H/24H period selector chips
    - Basal rate stepped area overlay in bottom 25% of chart, color-coded by Control-IQ mode (Auto=teal, Profile=grey, Sleep=purple, Exercise=orange)
    - Bolus diamond markers at top of chart, color-coded by type (auto-correction=pink, meal=green), with stagger for close events
    - Chart legend dynamically shows only data types present in current view
    - Compact `PumpStatusRow` replaces standalone Battery/Reservoir cards with inline icons
    - Dynamic battery icon selection based on actual percentage level
    - Room DAO reactive queries: `observeCgmHistory`, `observeIoBHistory`, `observeBasalHistory`, `observeBolusHistory` (all with LIMIT)
    - HomeViewModel: `flatMapLatest` on period selection for reactive chart data (4 history flows)
    - `SyncStatusBanner` clock side-effect fixed with `remember`/`LaunchedEffect` pattern
  - **Adversarial review:** 11 findings in first pass, 11 in second pass -- all addressed
  - **Phase 2 testing:** Verified on physical phone with real Tandem pump data across all period views
  - **Key files:** `GlucoseHero.kt`, `GlucoseTrendChart.kt`, `HomeScreen.kt`, `HomeViewModel.kt`, `PumpDao.kt`, `PumpDataRepository.kt`
- [x] Story 20.5: Dashboard Layout -- Time in Range Bar -- PR #237
  - **Feature:** Stacked TIR bar with period selector, quality labels, and pump status relocation
  - **Implementation:**
    - `TimeInRangeBar` composable: Canvas-based stacked horizontal bar (Low=red, In Range=green, High=yellow), FilterChip period selector (24H/3D/7D), quality assessment labels (Excellent/Good/Needs Improvement), legend with formatted percentages, accessibility semantics
    - Room aggregate query: `observeTimeInRangeCounts()` using CASE WHEN for efficient TIR computation
    - `PumpDataRepository.observeTimeInRange()` with `TimeInRangeCounts.toTimeInRange()` mapper
    - `HomeViewModel`: `selectedTirPeriod` + `timeInRange` StateFlows with `flatMapLatest`
    - Moved Battery + Reservoir from standalone `PumpStatusRow` into `GlucoseHero` card alongside IoB and Basal on single evenly-spaced row
    - Replaced verbose connection/sync banners with compact icon-only `ConnectionSyncRow`
    - Improved GlucoseHero a11y: contentDescription includes all secondary metrics
    - `TirPeriod` enum, `TimeInRangeData` domain model, `formatTirPercent()` edge case handling
  - **Tests:** TimeInRangeBarTest (percentage math, quality labels, format edge cases using real production functions), PumpDataRepositoryTest (TIR mapping), HomeViewModelTest (TIR state/period selection)
  - **Adversarial review:** 11 findings -- 3 fixed (test duplication, a11y gap, enum placement), 2 deferred to dynamic ranges story
  - **Phase 2 testing:** Verified on physical phone with real pump data across all three TIR periods
  - **Key files:** `TimeInRangeBar.kt`, `GlucoseHero.kt`, `HomeScreen.kt`, `HomeViewModel.kt`, `PumpDao.kt`, `PumpDataRepository.kt`
- [x] Story 20.8: Dynamic Glucose Ranges from Backend Settings -- PR #239
  - **Feature:** Make all four glucose thresholds (urgent_low, low, high, urgent_high) configurable from backend
  - **Implementation:**
    - Alembic migration adds urgent_low/urgent_high columns with server defaults (55.0/250.0)
    - Pydantic schema with cross-field ordering validation, service-layer merge validation for partial updates
    - Web: `useGlucoseRange` hook, dynamic thresholds in GlucoseHero/GlucoseTrendChart/dashboard, settings page with all 4 inputs + preview
    - Mobile: `GlucoseRangeStore` with atomic SharedPreferences batch writes, auto-fetch on login/stale
    - `GlucoseThresholds` converted from object to data class with defaults, passed through HomeViewModel/HomeScreen
    - PumpPollingOrchestrator: dynamic alert detection + watch CGM data uses store values
    - Aligned glucoseColor/detectAlertForCgm boundary operators for consistent alert/color behavior
    - Fixed Docker web build: added NEXT_PUBLIC_API_URL as build arg (was only runtime env)
    - Reactive glucose range sync: `glucoseThresholds` converted to MutableStateFlow, refreshes on pull-to-refresh (concurrent with BLE reads) and init when stale (15 min)
    - Bounds validation (20-500 mg/dL) on API response thresholds
    - Atomic refresh guard via compareAndSet, HTTP error logging
  - **Tests:** 40 backend tests, 11 mobile HomeViewModelTest cases (including API sync success/failure/staleness), lint clean, build succeeds
  - **Adversarial review:** Round 1: 11 findings -- 2 fixed. Round 2: 10 findings -- 6 fixed (missing tests, concurrent refresh, bounds validation, atomic guard, HTTP logging, constant visibility)
  - **Key files:** `GlucoseRangeStore.kt`, `GlucoseHero.kt`, `GlucoseTrendChart.kt`, `PumpPollingOrchestrator.kt`, `SettingsViewModel.kt`, `HomeViewModel.kt`, `use-glucose-range.ts`, `glucose-range/page.tsx`
- [x] Story 20.2: Branching Strategy & Dev/Prod Release Channels -- PR #254
  - **Feature:** Develop/main branching strategy with separate dev and stable release channels
  - **Implementation:**
    - All CI workflows (ci, android, docker-integration, container-build, container-cleanup, auto-label) trigger on both `main` and `develop`
    - Docker images tagged `dev` from develop pushes, `latest`/semver from main
    - New `dev-pre-release.yml` workflow: builds debug APKs on develop push, publishes rolling `dev-latest` pre-release
    - `AppUpdateChecker` channel-aware: release builds check `/releases/latest`, debug builds check `/releases/tags/dev-latest`
    - `BuildConfig.UPDATE_CHANNEL` ("dev"/"stable") and `DEV_BUILD_NUMBER` (CI run number via `-PdevBuildNumber` Gradle property) for correct version comparison
    - Renovate retargeted to `develop` via `baseBranches` config
    - Attribution check uses dynamic `BASE_REF` instead of hardcoded `origin/main`
    - Promotion PR template and branching strategy documentation
    - Branch rulesets: main (ID 12552358, squash+rebase+merge, homebot-0 bypass actor), develop (ID 13014168, squash only)
    - Cleaned up 50 stale remote branches, force-updated develop to match main
  - **Tests:** 7 new AppUpdateCheckerTest cases (parseDevRunNumber: valid, large, stable, non-matching, empty, ordering, loose-match rejection)
  - **Adversarial review:** 11 findings -- 2 HIGH (broken getCurrentApkName replaced with BuildConfig.DEV_BUILD_NUMBER, missing integration tests noted), 4 MEDIUM (regex tightened, atomicity improved, docs fixed, deprecated API removed), 5 LOW (version validation, APK check, docs note, regex precompiled)
  - **Key files:** `ci.yml`, `container-build.yml`, `dev-pre-release.yml`, `container-cleanup.yml`, `renovate.json5`, `build.gradle.kts`, `AppUpdateChecker.kt`, `docs/branching-strategy.md`
- [x] Story 20.3: Onboarding & Welcome Flow -- PR #267
  - **Feature:** Guided first-run onboarding experience gating app access until server setup and login complete
  - **Implementation:**
    - `AuthRepository` singleton: extracted login/testConnection/logout from SettingsViewModel into shared auth logic
    - `OnboardingScreen`: 5-page HorizontalPager (Welcome, Features, Safety Disclaimer, Server Setup, Login) with page indicators, Skip/Back/Next controls
    - `OnboardingViewModel`: manages pager state, connection testing, login flow, and onboarding completion persistence
    - `AppSettingsStore.onboardingComplete`: SharedPreferences flag gates first-run vs returning user
    - Conditional `startDestination` in NavHost: fresh install -> Onboarding, subsequent launch -> Home
    - Post-logout navigation: `SharedFlow<Unit>` event from SettingsViewModel navigates to Onboarding page 3 with URL pre-filled
    - Password cleared from ViewModel state after login attempt (both success and failure paths)
    - SettingsViewModel auth state observation: `drop(1).distinctUntilChanged()` prevents duplicate loadState() calls
    - SettingsScreen: simplified AccountSection when logged in (read-only server info, email badge, Sign Out)
  - **Tests:** AuthRepositoryTest (login, logout, testConnection, URL validation), OnboardingViewModelTest (initial state, URL pre-fill, getStartPage, connection test, login, error clearing), updated SettingsViewModelTest for AuthRepository delegation
  - **Adversarial review:** 12 findings -- 5 fixed (HIGH: password in plaintext state, MEDIUM: loadState duplication, MEDIUM: scope coupling docs, LOW: saveBaseUrl side effect, LOW: back navigation on pages 3-4)
  - **Key files:** `AuthRepository.kt`, `OnboardingScreen.kt`, `OnboardingViewModel.kt`, `NavHost.kt`, `SettingsViewModel.kt`, `SettingsScreen.kt`, `AppSettingsStore.kt`
- [x] Story 20.1b: BLE Reconnection Stability -- PR #244
  - **Feature:** Tiered BLE reconnection with indefinite slow phase for medical device reliability
  - **Implementation:**
    - Two-phase reconnection: FAST (exponential backoff 1s-32s, ~5 min) then SLOW (every 2 min indefinitely + passive autoConnect=true GATT)
    - `ReconnectPhase` enum with synchronized phase transitions via `autoConnectLock`
    - Passive `autoConnect=true` GATT: Android BLE kernel stack handles reconnection when pump returns to range (no CPU wake needed)
    - BluetoothAdapter state receiver: triggers reconnect on BT toggle ON (RECEIVER_EXPORTED for system broadcast)
    - Accelerated polling on reconnection: bolus backfill in 5s (vs 60s), battery/reservoir in 3s (vs 30s)
    - Removed hard AUTH_FAILED after 10 reconnect failures; bond-loss detection (insufficient auth/encryption, rapid disconnects, zero-response) unchanged
    - `cancelAutoConnectGatt()` added to all AUTH_FAILED paths to prevent stale passive connections
    - `consecutiveReconnectFailures` capped at 100 to prevent unbounded growth
    - Fixed INSUFFICIENT_ENCRYPTION before CONNECTED: when hadSuccessfulSession=true, treats as transient (count failures up to 3) instead of immediate AUTH_FAILED + bond removal
  - **Phone testing:** Paired pump, walked away, came back. App reconnected 4+ times through INSUFFICIENT_ENCRYPTION cycles without AUTH_FAILED. Previous code would have shown "Pairing failed" after first pre-CONNECTED encryption failure.
  - **Tests:** 3 new PumpPollingOrchestratorTest cases + ReconnectSchedulerTest (7 tests)
  - **Adversarial review:** 3 rounds total. All HIGH/MEDIUM fixed, stale comments updated.
  - **Key files:** `BleConnectionManager.kt`, `PumpConnectionService.kt`, `PumpPollingOrchestrator.kt`

---

## Epic 21: BLE History Log Backfill (CGM + Bolus + Basal)

**Goal:** Fill data gaps that occur when BLE disconnects by downloading history log records from the Tandem pump on reconnection and extracting CGM, bolus, and basal delivery data.

- [x] Story 21.1: CGM Chart Gap Backfill -- PR #245 (closed), PR #246 (closed), PR #247
  - **Feature:** Extract CGM readings from BLE history logs to backfill chart gaps during disconnection periods
  - **Implementation:**
    - BleConnectionManager: Added FFF8 history log stream handling (PacketAssembler + CompletableDeferred), requestHistoryLogStream(), thread-safe cleanup via cancelHistoryLogDeferred() on connect/disconnect, @Volatile on historyLogIdleJob
    - TandemBleDriver: Replaced getHistoryLogs() stub with batched opcode 60 fetch loop using requestHistoryLogStream() for FFF8 data collection, progressive scanning with nextHistoryIndex across poll cycles, time-capped at 15s
    - StatusResponseParser: 26-byte FFF8 stream records (eventTypeId(2)+pumpTimeSec(4)+seqNum(4)+data(16)), event type 16 (BG meter) and type 399 (Dexcom G7 CGM, glucose at data[6:8]) with status byte validation, extractCgmFromHistoryLogs() with dual format support
    - PumpDao/PumpDataRepository: Added insertCgmBatch(IGNORE) and saveCgmBatch() for dedup-safe batch insert
    - PumpPollingOrchestrator: Wired CGM extraction into pollHistoryLogs() after raw record save
    - Room schema migration v6->v7: dedup existing rows + unique index on cgm_readings.timestampMs
  - **Key discovery:** Event type 16 is fingerstick BG meter only, NOT CGM. Dexcom G7 CGM data is event type 399 (LidCgmDataG7) with ~5-min intervals (299s avg)
  - **Phone testing:** "Backfilled 18 CGM readings from history logs" confirmed across multiple progressive scan cycles
  - **Tests:** CgmHistoryParserTest (25+ tests), HistoryLogCargoTest (6 tests), PumpPollingOrchestratorTest updated

- [x] Story 21.2: Bolus & Basal Backfill from History Logs -- PR #247
  - **Feature:** Extract bolus delivery (event 280) and basal delivery (event 279) from raw FFF8 history log records
  - **Key discovery:** Raw BLE byte layout differs from tconnectsync cloud format! tconnectsync uses big-endian cloud upload format with different field order. Raw BLE layout verified by decoding actual pump records:
    - Event 280 (bolus): bolusId(0-1), deliveryStatus(2), bolusType(3), bolusSource(4), remoteId(5), requestedNow(6-7), correction(8-9), requestedLater(10-11), reserved(12-13), deliveredTotal(14-15)
    - Event 279 (basal): sourceRaw(0-1), unknown(2-3), profileBasalRate(4-5), commandedRate(6-7), algorithmRate(8-9), padding(10-15)
  - **Implementation:**
    - StatusResponseParser: parseBolusDeliveryPayload() (status filtering, correction/automation detection, sanity limits), parseBasalDeliveryPayload() (source classification, rate limits), extractBolusesFromHistoryLogs(), extractBasalFromHistoryLogs()
    - Room migration v7->v8: unique index on basal_readings.timestampMs for dedup
    - PumpDao: insertBasalBatch(IGNORE), PumpDataRepository: saveBasalBatch()
    - PumpPollingOrchestrator: Wired bolus + basal extraction, enqueue backfilled boluses to sync queue
  - **Phone testing:** "Backfilled 17 basal readings" (rates: 1.5 u/hr profile, 1.65 algorithm-adjusted), "Backfilled 1 bolus events". Decoded raw event 280 bytes confirmed bolus amounts (1.134u, 1.913u, 2.295u, 4.081u auto-corrections)
  - **Tests:** BolusBasalHistoryParserTest (27 tests: payload parsing, boundary values, offset verification, extraction, automation detection, empty input)
  - **Adversarial review:** 10 findings (2 MEDIUM, 8 LOW). Fixed: stale KDoc, isAutomated logic (user corrections not automated), sync enqueue for backfilled boluses, boundary tests, offset verification test, empty input tests

---

## Epic 22: Web Dashboard Chart & Pump Status Enhancements

**Goal:** Add bolus/basal overlays to the web glucose chart, sync pump hardware status (battery, reservoir) to backend, and fix chart gaps from BLE disconnections.

- [x] Story 22.1: Web Dashboard Bolus Markers & Basal Area Overlay -- PR #250
  - **Feature:** Add bolus dose markers and basal rate area fill to the web glucose trend chart; replace CoB with pump status in hero card; add 14D/30D to mobile TiR
  - **Implementation:**
    - Backend: Added BATTERY and RESERVOIR to PumpEventType enum + Alembic migration 036
    - Backend: New GET /api/integrations/pump/status endpoint with DISTINCT ON single-query optimization
    - Backend: PumpStatusResponse schema (basal rate, battery %, reservoir units)
    - Backend: Removed always-null CoB from SSE glucose stream
    - Mobile: PumpEventMapper.fromBattery()/fromReservoir() + SyncQueueEnqueuer methods
    - Mobile: Wired battery/reservoir polling into backend sync pipeline
    - Mobile: Added 14D and 30D to TirPeriod enum (matches web's 5 periods)
    - Web: usePumpStatus hook with generation counter for race condition prevention
    - Web: GlucoseHero replaced CoB with 4-metric row: IoB | Basal | Battery | Reservoir
    - Web: Dashboard page wired to pump status hook
  - **Tests:** 1202 backend, 119 frontend (glucose-hero, use-pump-status, use-glucose-stream), mobile lint + build clean
  - **Adversarial review:** 10 findings (3 MEDIUM, 7 LOW). Fixed: DISTINCT ON query optimization, inline import cleanup, migration docstring, hook error logging, removed residual cob types
  - **Phone testing:** Confirmed battery (60%) and reservoir (250u) synced from phone to backend to web dashboard in real-time
  - **Key files:** `pump_data.py`, `integrations.py`, `tandem_sync.py`, `pump.py`, `glucose-hero.tsx`, `use-pump-status.ts`, `PumpEventMapper.kt`, `TimeInRangeBar.kt`
- [x] Story 22.2: Basal Chart Gap Fill During BLE Disconnections -- PR #250
  - **Feature:** BLE history log backfill for basal delivery events fills chart gaps automatically
  - **Implementation:** Resolved by Epic 21 basal backfill (event 279 extraction from FFF8 history logs). When BLE reconnects, the slow polling loop downloads history records covering the disconnection period and extracts basal delivery events, filling the chart gap with real pump data rather than interpolated values.
  - **Adversarial review:** 13 findings (2 HIGH, 5 MEDIUM, 5 LOW). HIGH #1 (missing basal sync enqueue) fixed in chart overlay commit. Remaining findings addressed: extracted AUTOMATED_BASAL_SOURCES to companion val, removed dead MAX_BOLUS_MILLIUNITS check, added 3 new tests (TempRate source, 18-byte record skip).
  - **Phone verification:** Confirmed 17 basal readings backfilled per history log cycle on physical device

---

## Epic 23: Legal & Regulatory Compliance

**Status:** In Progress (1/2 stories complete)
**Goal:** Ensure GlycemicGPT has proper legal coverage before implementing pump control features (bolus delivery). Investigate FDA regulations, open-source medical device precedent, and required safety architecture.

- [x] Story 23.1: Legal Research Spike -- FDA & Medical Device Regulations
  - **Type:** Research spike (no code)
  - **Goal:** Determine legal requirements and risk mitigation strategy for implementing insulin bolus delivery via BLE
  - **Scope:**
    - Research FDA guidance on mobile medical apps vs. clinical decision support software
    - Review FDA enforcement history with DIY diabetes projects (Loop, OpenAPS, AndroidAPS, xDrip+)
    - Investigate whether distributing pre-built APKs with pump control is legally distinct from build-from-source
    - Research DMCA 1201(f) interoperability exception as it applies to our Tandem reverse engineering
    - Evaluate whether the HMAC key in source code poses specific legal exposure
    - Review EU MDR implications if the app is used internationally
    - Consult with a software/IP attorney (recommended: someone familiar with DMCA interoperability + FDA SaMD guidance)
  - **Deliverables:**
    - Written summary of legal findings in `_bmad-output/planning-artifacts/legal-regulatory-assessment.md`
    - Go/no-go recommendation for bolus delivery feature
    - List of required safety measures if go
    - Recommended changes to disclaimer/license if needed

- [ ] Story 23.2: Implement Safety Architecture for Pump Control Features
  - **Type:** Implementation (blocked by 23.1 go decision)
  - **Goal:** Build the safety guardrails required before any pump control feature ships
  - **Scope (preliminary -- finalized after 23.1):**
    - Hard safety limits: max single bolus cap, max daily insulin cap, configurable by user
    - CGM confirmation gate: require recent (< 15 min) CGM reading before allowing correction bolus
    - Rate limiting / lockout: minimum time between bolus commands
    - AI suggestion vs. execution separation: AI suggests as text, user explicitly confirms, app executes with all safety checks
    - Build-from-source gate: pump control features excluded from pre-built GitHub Release APKs (require source build with explicit flag)
    - Enhanced disclaimer / consent flow: user must acknowledge risks before enabling pump control
    - Audit logging: every bolus command logged with timestamp, source (AI suggestion vs manual), CGM context, user confirmation timestamp
    - 6-stage safety pipeline (from CONTRIBUTING.md vision): Intent Capture -> Clinical Validation -> Dose Calculation -> Safety Boundary Check -> User Confirmation -> Execution + Monitoring
  - **Blocked by:** Story 23.1 (legal go/no-go decision)

---

## Epic 24: Modular Plugin Architecture

**Goal:** Transform the mobile app into a modular plugin architecture where pump control features are build-from-source only (user = manufacturer), while the base APK remains a monitoring platform.

- [x] Story 24.1: Interface Extraction & Decoupling (Phase 1)
  - **PR:** #279 (merged)
  - **Scope:** Extract 3 domain interfaces (PumpConnectionManager, PumpScanner, HistoryLogParser), update 5 consumers to use interfaces instead of concrete BLE types, add DI bindings, add contract tests
  - **Result:** Zero concrete BLE imports outside `ble/` and `di/PumpModule.kt`

- [x] Story 24.2: Gradle Module Split (Phase 2)
  - **PR:** #281 (merged)
  - **Scope:** Split into 3 Gradle modules: `:pump-driver-api` (interfaces + domain models), `:tandem-pump-driver` (BLE implementation), `:app` (base)
  - **Result:** Build-time module boundary enforcement. Cross-module Hilt via PumpCredentialProvider and DebugLogger interfaces. SafetyLimits tightened to clinical bounds (glucose 20-500, basal 15u/hr, bolus 25u). BouncyCastle ProGuard narrowed to 4 classes.

- [x] Story 24.3: Safety Architecture (Phase 3)
  - **Scope:** Backend-synced safety limits: per-user `safety_limits` table, API endpoints (GET/PATCH/defaults), mobile SafetyLimitsStore with SharedPreferences caching, backend sync via AuthRepository, web settings page with platform framing
  - **Key design:** Mobile NEVER allows local override -- only backend sync via `updateAll()` with `SafetyLimits.safeOf()` clamping. Defense-in-depth: frontend bounds -> API schema -> service validation -> DB CHECK constraints -> mobile client clamping. PumpDriver.getBolusHistory() threads synced limits for consistent bolus filtering across real-time and history paths.
  - **PR:** #282 (merged 2026-02-23)

- [x] Story 24.4: General-Purpose Plugin Platform (Phase 4)
  - **PR:** #288
  - **Scope:** Capability-based plugin model (GLUCOSE_SOURCE, INSULIN_SOURCE, PUMP_STATUS, BGM_SOURCE, CALIBRATION_TARGET, DATA_SYNC) with mutual-exclusion enforcement. Plugin/DevicePlugin interfaces, PluginFactory + Hilt multibindings, PluginRegistry with thread-safe lifecycle management, cross-plugin event bus (SharedFlow-backed), declarative UI (SettingDescriptor + DashboardCardDescriptor + CardElement), platform UI renderers, adapter layer (PumpDriverAdapter, PumpConnectionAdapter, PumpScannerAdapter, HistoryLogParserAdapter) for backward compat, Tandem plugin wrapper (TandemDevicePlugin + 3 capability classes + TandemPluginFactory). 63 new/modified files, 337 tests passing.
  - **Key design:** Compile-time discovery via Hilt @IntoSet multibindings now; infrastructure supports runtime loading later. Platform owns core UI (GlucoseHero, TrendChart, TIR); plugins contribute additional cards. Safety limits enforced by platform, not plugins. PUMP_CONTROL capability deferred pending legal review.

- [x] Story 24.5: Documentation & Legal Updates (Phase 5)
  - **Scope:** Plugin architecture docs, medical disclaimer, README/CONTRIBUTING updates, .coderabbit.yaml updates
  - **Deliverables:** `docs/plugin-architecture.md` (full plugin dev guide), `MEDICAL-DISCLAIMER.md` (consolidated safety disclaimer), updated README.md, CONTRIBUTING.md, CLAUDE.md, `.coderabbit.yaml`, `legal-regulatory-assessment.md`

- [x] Story 24.6: Backend Isolation (Phase 6) -- PR #291
  - **Scope:** Functional treatment safety validator -- every bolus request must pass 6 checks before reaching the pump
  - **Implementation:**
    - `enums.py`: StrEnum with auto() for SafetyCheckType, BolusSource, ValidationStatus; documented safety invariants for ai_suggested and automated sources
    - `models.py`: Frozen Pydantic models (BolusRequest, SafetyCheckResult, BolusValidationResult) with model_validator enforcing consistency (no approved-with-zero-dose, no approved-with-rejections)
    - `constants.py`: Clinical constants (CGM freshness 15 min, rate limit 15 min, daily max 100U, hypo floor 70 mg/dL)
    - `validator.py`: TreatmentSafetyValidator with 6 functional checks (max single bolus, max daily total, CGM freshness, rate limit, glucose range, user confirmation), server-side timestamps, no short-circuit
    - `bolus_validation_log.py`: SQLAlchemy audit log model for every validation (approved and rejected)
    - `treatment_validation.py`: Service layer with per-user advisory lock (pg_advisory_xact_lock) preventing TOCTOU race conditions
    - `treatment.py` router: POST /api/treatment/validate-bolus with auth + role protection
    - Migration 038: max_daily_bolus_milliunits column + bolus_validation_logs table with CHECK constraints
    - SafetyLimits model/schema updated with max_daily_bolus_milliunits field
  - **Tests:** 54 tests -- 31 model/enum tests + 23 validator tests (pure checks + DB-backed checks + integration)
  - **Security hardening:** Advisory lock ordering (safety limits fetched before lock), frozen models prevent mutation, server-side time for all safety calculations, DB CHECK constraints as defense-in-depth

---

## Epic 25: Background Service Resilience

- [ ] Story 25.1: Survive OS Process Kill Without Data Gaps
  - **Scope:** Ensure `PumpConnectionService` restarts automatically after OS kills the app process (not just device reboot). Current gap: `BootCompletedReceiver` only handles reboot; process death from memory pressure or force-close leaves BLE dead until user manually reopens the app. Fix options: `START_STICKY` return from `onStartCommand()`, periodic `WorkManager` health check, or both. Should be done AFTER plugin consumer migration (PumpConnectionService still uses deprecated PumpConnectionManager -- migrate to plugin system first, then add resilience).
  - **Depends on:** Epic 24 completion (plugin architecture migration)
  - **Priority:** High (diabetes monitoring app should not silently stop monitoring)

---

## Epic 26: Runtime Plugin Loading

**Goal:** Transform the plugin system from compile-time-only discovery (Hilt @IntoSet) to support both built-in AND user-sideloaded plugins via DexClassLoader. Users build plugins in their own Android Studio project against the published plugin SDK, then load via "Add Custom Plugin" in the app.

- [x] Story 26.1: Research Spike -- DexClassLoader and Android Dynamic Loading
- [x] Story 26.2: Plugin SDK Packaging (maven-publish + reference project)
- [x] Story 26.3: Sandboxed PluginContext (restricted API surface for runtime plugins)
- [x] Story 26.4: Runtime Plugin Loader (DexClassLoader, manifest, file manager)
- [x] Story 26.5: Plugin Management UI (settings section with add/remove/toggle)
- [x] Story 26.6: PluginRegistry Integration (dual discovery: Hilt + runtime)
- [x] Story 26.7: Integration Testing and Documentation

**PR:** #297 (all 7 stories in single PR)

---

## Epic 27: External Platform Integrations (Backend)

**Goal:** Allow users of existing diabetes platforms (Nightscout, Tidepool, LibreView) to connect their accounts as data sources in GlycemicGPT. Data flows through the backend only -- no mobile app changes beyond displaying the data that already comes through the existing pipeline. Users who already have a working Nightscout/Loop/AndroidAPS/Tidepool setup can adopt GlycemicGPT without abandoning their existing infrastructure, gaining our AI analysis, alerting, mobile app, and Wear OS interface on top of what they already use.

**Architecture:** Each integration is a backend service that periodically polls the external platform's API, normalizes data into our existing schema (glucose readings, bolus events, basal rates, etc.), and stores it via the same pipeline that mobile BLE data uses. The web frontend adds configuration UI to the existing Integrations settings page. No pump/CGM setup required -- the integration IS the data source.

**Priority:** Planned (not targeted for current development cycle -- core standalone users first)

### Story 27.1: Nightscout Integration
- **Scope:** Connect to a user's Nightscout instance as a data source. This single integration covers the largest user base: Nightscout users, Loop users, AndroidAPS users, and xDrip+ users (all sync to Nightscout).
- **Backend:**
  - Nightscout API client: REST API polling for SGV entries (CGM readings), treatments (bolus, carbs, temp basal), profile (basal schedule, ISF, ICR)
  - Configurable poll interval (default 5 min, matching CGM cadence)
  - Data normalization: Nightscout SGV entries -> our glucose_readings schema, Nightscout treatments -> our pump_events schema
  - API token storage (encrypted, per-user) -- Nightscout uses `API_SECRET` or JWT tokens
  - Backfill on initial connect: pull last 24h-7d of historical data
  - Connection health monitoring: track last successful sync, error counts, staleness alerts
- **Web Frontend:**
  - Integrations settings page: "Nightscout" card with URL input, API token input, test connection button
  - Status display: last sync time, record counts, connection health badge
  - Enable/disable toggle
- **Validation:** Verify data appears on dashboard charts, AI briefs reference the data, alerts fire on thresholds

### Story 27.2: Tidepool Integration
- **Scope:** Connect to a user's Tidepool account as a data source. Covers Tidepool Loop users and users whose clinics use Tidepool for data review.
- **Backend:**
  - Tidepool API client: OAuth2 authentication, data fetch for CGM, pump, BGM records
  - Data normalization: Tidepool's unified data model -> our schema
  - Handle Tidepool's data types: cbg (CGM), smbg (fingerstick), bolus, basal, wizard (bolus calculator), deviceEvent
  - Encrypted credential storage (OAuth tokens, per-user)
  - Poll interval: 15 min (Tidepool data is less real-time than Nightscout)
  - Backfill on initial connect
- **Web Frontend:**
  - Integrations settings page: "Tidepool" card with OAuth connect flow, status display
  - Disconnect button with confirmation
- **Validation:** Verify data appears on charts, correct unit handling (Tidepool uses mmol/L internally)

### Story 27.3: LibreView Integration
- **Scope:** Connect to Abbott's LibreView cloud platform as a data source. Covers FreeStyle Libre 2/3 users who use the official LibreLink app (not xDrip+).
- **Backend:**
  - LibreView API client: authenticate with LibreView credentials, fetch glucose data
  - Handle LibreView's data format: historical readings (every 15 min), real-time readings (every 1 min for Libre 3), scan results
  - Data normalization: LibreView glucose entries -> our schema with proper source attribution
  - Encrypted credential storage
  - Poll interval: 5 min (Libre 3 has 1-min data, Libre 2 has 15-min scans)
  - Note: LibreView API is semi-private/reverse-engineered -- may need community maintenance
- **Web Frontend:**
  - Integrations settings page: "LibreView" card with email/password input, region selector (EU/US endpoints differ), test connection
  - Status display with sensor info (sensor type, days remaining)
- **Validation:** Verify glucose data flows, correct handling of Libre's scan vs stream readings

### Story 27.4: Integration Data Pipeline & Source Attribution
- **Scope:** Backend infrastructure to support multiple data sources per user with proper attribution and deduplication.
- **Backend:**
  - Source attribution: extend `source` field on all data tables to identify origin (e.g., `nightscout`, `tidepool`, `libreview`, `mobile_ble`)
  - Deduplication across sources: if a user has both BLE and Nightscout sending the same CGM data, deduplicate by timestamp + value
  - Data source priority: user configures which source is "primary" when overlaps exist
  - Integration health dashboard: API endpoints for per-integration sync status, error logs, data freshness
  - Rate limiting: respect external API rate limits, implement exponential backoff
  - Graceful degradation: if an integration's API is down, continue serving cached data and alert the user
- **Web Frontend:**
  - Data Sources overview page showing all active sources (BLE pump, integrations) with health status
  - Per-source data freshness indicators on the dashboard
- **Validation:** Verify deduplication works when same data arrives from multiple sources, verify source labels appear correctly in data exports

### Story 27.5: Integration-Only Onboarding Flow
- **Scope:** Streamlined onboarding for users who ONLY use integrations (no pump/CGM setup in our app).
- **Backend:**
  - Skip pump/CGM setup requirement when an integration is configured as primary data source
  - Allow account creation -> integration setup -> dashboard (no BLE pairing step)
  - Detect and handle "integration-only" users in AI analysis (no pump status data, no IoB from BLE)
- **Web Frontend:**
  - Onboarding wizard: option to "Connect existing platform" vs "Set up pump directly"
  - Integration-first flow: select platform -> authenticate -> verify data flowing -> dashboard
- **Mobile:**
  - Home screen adapts when no BLE pump is configured: hide pump status card, show integration source card instead
  - Settings: show integration status instead of BLE connection status
- **Validation:** End-to-end test of a user who signs up, connects Nightscout, and immediately sees data on dashboard/mobile/watch without ever touching BLE setup

---

## Epic 28: Security Hardening & Penetration Testing

**Status:** In Progress (16/17 stories)

| Story | Title | Status | PR |
|-------|-------|--------|-----|
| 28.1 | JWT Secret Startup Validation & Separate Encryption Key | Done | [#310](https://github.com/jlengelbrecht/GlycemicGPT/pull/310) |
| 28.2 | Web Security Headers (CSP, HSTS, X-Frame-Options) | Done | [#310](https://github.com/jlengelbrecht/GlycemicGPT/pull/310) |
| 28.3 | JWT Token Revocation via Redis Blacklist | Done | [#310](https://github.com/jlengelbrecht/GlycemicGPT/pull/310) |
| 28.4 | CORS Tightening & CSRF Protection | Done | [#310](https://github.com/jlengelbrecht/GlycemicGPT/pull/310) |
| 28.5 | Key Derivation Hardening (PBKDF2) | Done | [#310](https://github.com/jlengelbrecht/GlycemicGPT/pull/310) |
| 28.6 | Encrypted Room Database (SQLCipher) | Done | [#310](https://github.com/jlengelbrecht/GlycemicGPT/pull/310) |
| 28.7 | Device Binding & API Security Foundation | Done | [#322](https://github.com/jlengelbrecht/GlycemicGPT/pull/322) |
| 28.8 | Mobile Storage Hardening (EncryptedSharedPreferences) | Done | [#310](https://github.com/jlengelbrecht/GlycemicGPT/pull/310) |
| 28.9 | SSRF Prevention for AI Provider base_url | Done | [#310](https://github.com/jlengelbrecht/GlycemicGPT/pull/310) |
| 28.10 | Information Disclosure Fixes | Done | [#310](https://github.com/jlengelbrecht/GlycemicGPT/pull/310) |
| 28.11 | Automated DAST & Auth Flow Penetration Testing | Done | [#314](https://github.com/jlengelbrecht/GlycemicGPT/pull/314) |
| 28.12 | Code Quality & Best Practices Audit | Done | [#321](https://github.com/jlengelbrecht/GlycemicGPT/pull/321) |
| 28.13 | Security Scan Gate | Done | [#316](https://github.com/jlengelbrecht/GlycemicGPT/pull/316) |
| 28.14 | Android Gate | Done | [#316](https://github.com/jlengelbrecht/GlycemicGPT/pull/316) |
| 28.15 | Dependency Vulnerability Scanning | Done | [#316](https://github.com/jlengelbrecht/GlycemicGPT/pull/316) |
| 28.16 | Security Testing Documentation | Done | [#316](https://github.com/jlengelbrecht/GlycemicGPT/pull/316) |
| 28.17 | Branch Protection Rules Update | Done | Applied via gh api after #316 merged |
