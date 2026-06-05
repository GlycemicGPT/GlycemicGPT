---
title: Medtronic Live-Validation Runbook
description: Scripted, pump-gated validation procedure for the read-only Medtronic 700-series BLE driver.
---

# Medtronic Live-Validation Runbook

The read-only Medtronic MiniMed 700-series BLE driver (680G / 770G / 780G) is fully built and
ships behind the default-on `MEDTRONIC_DRIVER_ENABLED` flag, but its live path has never been
exercised against a real pump: the emulator cannot advertise as a BLE peripheral, so pairing,
the SAKE handshake, decryption, and the per-field reads have only ever run against captured
vectors and mocks.

This document is the **single, ordered script** for the one live session that closes that gap. A
real 700-series pump tester is scarce and the window may be short, so this runbook exists so the
session captures everything in one pass and nothing is improvised. A developer and a tester run it
top to bottom; every step says exactly what to do, what to look at, and how to record the verdict.

> **Read-only.** Every step below is observe-and-compare. The driver never writes to the pump — no
> bolus, no basal change, no suspend/resume, no calibration. This runbook never instructs a write or
> control action; if a step ever seems to ask you to send something to the pump, stop — that is a
> bug, not a step.

> **Scope.** This is the on-device Bluetooth path only (phone pairs directly to the pump). It is
> unrelated to CareLink cloud sync. See
> [Connecting your Medtronic pump over Bluetooth](../daily-use/connecting-medtronic-pump.md) for the
> end-user flow this runbook validates.

## Done-bar (what this session must produce)

The session passes — and the driver graduates from "BETA-ready, flag-on" to "BETA validated" — when:

1. The golden path works end to end on a real pump: pair → handshake → every field appears and
   **matches the pump's own display** → reconnect after a disconnect → unpair (§2).
2. Each field is verified on whatever models the tester(s) have, with coverage and gaps recorded in
   the per-model matrix (§5).
3. Every accumulated open item (the resolution matrix, §3) is marked **resolved** or **carried**,
   each with the evidence observed.
4. The Sentry gate runs with real glucose/insulin data flowing and shows no unresolved real issues
   and **no PHI** in `glycemicgpt-mobile` (§4).

If a tester never materializes, the driver stays BETA-flagged with this session open — an accepted
state, not a failure. If a field is observed wrong (IoB is the usual suspect — see §3), that is a
**successful** session: the bug was caught before users trusted the value.

## Before the session — prep checklist (no pump)

- [ ] A Sentry-enabled debug build is reproducible on demand (the exact command is in §4). Do **not**
      build it until the pump is in hand — keep ordinary iteration Sentry-off to conserve quota.
- [ ] `op whoami` reports `SERVICE_ACCOUNT` (so `op run` is unattended — see §4). If not, the
      desktop-approval fallback still works but needs a human at the laptop.
- [ ] The capture path is armed and gitignored (see [§2.0](#20-arm-the-capture-first) and
      [Capturing the session](#capturing-the-session-offline-regression-fixture)). Verify with
      `git check-ignore`.
- [ ] You have the tester's pump model(s) written down (680G / 770G / 780G) — each model is a column
      in the per-model matrix (§5).
- [ ] The tester knows to **remove the pump from the official Medtronic app first** — a MiniMed pump
      pairs with only one phone at a time (the single-peer constraint; the app shows the same
      reminder). Without this, pairing stalls on `BOUND_ELSEWHERE`.

---

## 1. AC → observation script overview

Each acceptance criterion for the live session maps to a concrete, ordered block below. Run them in
order; later blocks depend on a live session being up.

| Goal | Where | What it proves |
|---|---|---|
| Golden path E2E (pair → read → reconnect → unpair) | §2 | The full live path the offline build could never run |
| Per-model mapping verification | §5 (filled live), driven by §2 reads | CGM/IoB/basal/bolus/reservoir/battery/alarms map correctly per model |
| Close the open-item set | §3 | Each upstream "not tested / confirm live" item is resolved or carried with evidence |
| Live Sentry gate | §4 | BLE/SAKE/reader error paths produce no unresolved real issues; no PHI under live data |
| BETA graduation sign-off | §6 | The verified matrix + resolved items recorded; driver graduates or stays flagged |

---

## 2. Golden-path observation script (ordered)

Run this with the pump tester present. Every read step is **observe app value → read the same value
off the pump's own screen → record match / mismatch**. The pump is the authority; if they disagree,
the app is wrong.

App identifiers below are the dashboard `testTag`s, so a value can be pulled reliably (e.g. via
mobile-mcp `mobile_list_elements_on_screen`) rather than eyeballed.

### 2.0 Arm the capture first

Before pairing, enable the over-the-air BLE capture so the whole session — handshake included — is
recorded to a gitignored file (see
[Capturing the session](#capturing-the-session-offline-regression-fixture) for how and why). The
capture is the **Android Bluetooth HCI snoop log**, which records the actual wire frames regardless
of what the app logs; the driver itself deliberately logs no raw bytes (it is PHI-hardened), so app
logcat is **not** a usable capture. A one-shot live session becomes a durable offline regression
fixture only if the snoop log is enabled **before** the handshake.

- [ ] HCI snoop logging enabled on the phone (Developer Options → "Enable Bluetooth HCI snoop log"),
      then Bluetooth toggled off/on so it starts fresh. (Pull the log into the gitignored
      `captures/` dir **after** the session, §2.5 — it is written continuously by the OS while you
      run.)

### 2.1 Pair (advertise-and-wait)

This is the advertise-and-wait flow: the phone makes itself discoverable as **"Mobile 000001"** and
the pump connects to it. (Unlike Tandem, the phone does **not** scan.)

1. [ ] In the app, open pump settings → choose **Medtronic** as the pump. Confirm Medtronic is
       selectable (flag is on) and selecting it evicts any previously-active pump (single-instance).
2. [ ] Open **Pump Pairing**. Confirm the **"Before you start"** note about removing the pump from
       the manufacturer's app is shown (this is the single-peer reminder).
3. [ ] Tap **Start Pairing**. Confirm the phone shows **"Waiting for your pump"** and the
       `advertising_status` element reflects advertising. (Foreground-service note: the service must
       start only once a session forms, not on the tap — a regression where it started on the tap
       was caught during development as a `ForegroundServiceDidNotStartInTime` crash. Watch for any
       crash on this tap.)
4. [ ] On the **pump**, open the Bluetooth pairing / add-device menu (commonly **Add / Pair new
       device** — the exact label varies by model and firmware) and select **"Mobile 000001."**
5. [ ] Confirm the app transitions **waiting → connecting → authenticating → connected** and
       `connection_status` reads connected. (The handshake runs during the *authenticating* phase, so
       expect a brief intermediate state, not an instant jump to connected.) Record the wall-clock
       time from "Start Pairing" to "connected" (informs the single-peer wait-window item in §3).

If pairing stalls or fails, note which fault appeared — it maps to a known cause and feeds §3. One
fault behaves differently in the UI: `BOUND_ELSEWHERE` is **not terminal** — the screen stays in the
"Waiting for your pump" state with its message shown inline and a **Cancel** button (it keeps
advertising in case the pump becomes free). The other four are terminal: the screen shows a fault
card with **Try Again**.

| Pairing screen message | Fault | UI | Meaning |
|---|---|---|---|
| "No pump has connected yet." | `BOUND_ELSEWHERE` | stays Waiting, **Cancel** | Pump likely still paired to another phone/app — remove it there first |
| "This phone can't act as a Bluetooth accessory." | `PERIPHERAL_UNSUPPORTED` | fault card, **Try Again** | This phone can't advertise as a BLE peripheral — try a different phone |
| "Couldn't start Bluetooth advertising." | `ADVERTISE_FAILED` | fault card, **Try Again** | OS rejected the advertiser — close other BLE apps |
| "The secure handshake timed out." | `HANDSHAKE_TIMEOUT` | fault card, **Try Again** | Pump connected but SAKE didn't finish in time — retry, keep the pump close |
| "the pump rejected the secure handshake." | `AUTH_FAILED` | fault card, **Try Again** | SAKE ran but auth was rejected |

### 2.2 SAKE handshake

The handshake runs automatically inside "connecting." There is nothing to tap. Confirm:

6. [ ] Reached **connected** without a `HANDSHAKE_TIMEOUT` / `AUTH_FAILED` fault. (This is the first
       time the 6-stage SAKE handshake has ever completed against a real pump rather than a captured
       780G trace — record that it completed for this model.)

### 2.3 Read each field and compare to the pump display

Reads are **poll-driven** (the GATT-client transport is request/response, not push), so values land
at the fast tier's ~15s cadence — give each field a poll cycle or two to populate. Record each as
match / mismatch / not-available, and copy the verdict into the per-model matrix (§5).

For each field: read the app value at the listed `testTag`, then read the same value on the pump.

7. [ ] **Sensor glucose (CGM)** — app `glucose_hero_value` + `cgm_stats_card`; trend at
       `glucose_hero_trend`. First confirm the pump itself has an **active sensor session showing a
       glucose value** (otherwise "no CGM" is legitimate, not a bug). Then compare mg/dL and trend
       arrow to the pump's sensor screen. CGM is the make-or-break read — a correct mg/dL here proves
       the full decrypt→parse path end to end.
       - ⚠️ **Decision rule for §5:** if the **pump shows a glucose value but the app shows none**
         after 2+ poll cycles, record **WRONG** (not N/A or GAP). A per-model E2E-CRC mismatch makes
         the CGM parse *throw* (the read fails and shows nothing) rather than show a wrong number, and
         that failure logs only at WARN — so the Sentry gate won't flag it either. Absent-when-the-
         pump-has-a-value is the expected signature of a per-model CRC bug; capture it and carry it
         (§3 item 7). Only record **N/A** when the pump genuinely has no active sensor.
8. [ ] **Insulin on board (IoB)** — app `hero_iob` + `insulin_summary_card`. Compare to the pump's
       active-insulin display. ⚠️ **Highest-risk field** — upstream marks IoB parsing "not tested."
       Verify the number carefully and record the exact app-vs-pump pair (see the IoB row in §3).
9. [ ] **Basal rate** — app `hero_basal`. Compare to the pump's active basal rate. On a SmartGuard /
       auto-basal pump the rate moves automatically; note whether the app's rate tracks the pump.
10. [ ] **Bolus history** — app `recent_boluses_card` / `bolus_history_list`. Compare the most recent
        bolus (units + time) to the pump's bolus history. Confirm no duplicate rows on repeated
        polls (the cursor should advance, not rescan).
11. [ ] **Reservoir** — app `hero_reservoir`. Compare units remaining to the pump's reservoir display.
12. [ ] **Battery** — app `hero_battery`. Compare to the pump's battery indicator.
13. [ ] **Alarms / annunciations** — if the pump raises an alarm during the session (or has a recent
        one in history), confirm it appears in the app's history. Record any alarm types seen.

### 2.4 Reconnect after disconnect

14. [ ] Take the pump out of range (or otherwise drop the link) and confirm the app shows
        disconnected. Bring it back into range.
15. [ ] Confirm the app **auto-reconnects without re-pairing** (the already-paired `0xFE81`
        reconnect advertisement). Record the reconnect time and whether data resumes.

### 2.5 Unpair

16. [ ] In the app's pump settings card, tap **Unpair** (`unpair_button`; the confirmation dialog is
        titled "Unpair Pump") and confirm. Confirm the app returns to an unpaired/not-connected state
        and stops advertising.
17. [ ] Confirm the pump no longer lists "Mobile 000001" as connected (or that re-pairing is required
        to reconnect) — i.e. the unpair actually removed the bond, not just dropped the link.

18. [ ] **Pull the HCI snoop log** into the gitignored `captures/` dir (command in
        [Capturing the session](#capturing-the-session-offline-regression-fixture)). Confirm the file
        is non-empty and still gitignored — it contains real wire data (PHI); never commit it.

---

## 3. Open-item resolution matrix (`TODO(48.A2)` set)

These are the items accumulated across the offline build that only a real pump can settle. They are
tagged `TODO(48.A2)` in the source. For each: what to observe live, what we expect vs. what is
genuinely uncertain, and how to record the verdict. Mark each **RESOLVED** (with the observation) or
**CARRIED** (with why it couldn't be settled and what's still needed).

| # | Item | What to observe live | Expected vs. uncertain | Record |
|---|---|---|---|---|
| 1 | **SAKE characteristic UUID base** (SIG `0xFE82` vs vendor-base) | That the handshake completes (§2.2) with the UUIDs the driver actually advertises/exposes. | Expected: the driver's current UUIDs work (the module uses the SIG-style base). Uncertain: whether a vendor-base characteristic is required on real hardware. | RESOLVED if handshake completes as shipped; CARRIED with the failing UUID if it doesn't. |
| 2 | **Per-install "Mobile …" name** | That the pump accepts and lists **"Mobile 000001"** in its Bluetooth pair/add-device menu (§2.1.4; exact menu label varies by model). | Expected: the fixed `Mobile 000001` name is accepted (matches the `Mobile .{0,7}` pattern). Uncertain: whether a per-install/unique suffix is needed to avoid collisions. | RESOLVED if the pump pairs to `Mobile 000001`; note if a unique name is needed. |
| 3 | **Single-peer wait-window** | The time from "Start Pairing" to "connected" (§2.1.5) and whether `BOUND_ELSEWHERE` fired before the pump was removed from the other app. | Expected: pairing succeeds within the advertise window once the pump is free; `BOUND_ELSEWHERE` only when still bound elsewhere. Uncertain: the real wait-window length and reconnect advertising interval. | RESOLVED with the measured pairing + reconnect times; CARRIED if the window proved too short. |
| 4 | **DIS-field validation** | Device Information service fields (model / serial / hardware / firmware) shown in the app's pump card vs. the pump's own device-info screen. | Expected: model/serial/firmware read and match. Uncertain: exact field set and formatting per model. | RESOLVED with the matched fields; note any missing/garbled field. |
| 5 | **IoB trust** ⚠️ highest risk | App `hero_iob` vs. the pump's active-insulin display, across multiple readings over the session (§2.3.8). | Upstream marks IoB "not tested." Genuinely uncertain — this is where it's finally trusted or corrected. | RESOLVED only if the app IoB matches the pump across several readings; otherwise CARRIED, IoB stays PROVISIONAL, record the exact app-vs-pump values so the parse can be corrected offline from the capture. |
| 6 | **History on-wire framing at MTU 23** | That history/RACP reads return complete, parseable records over the 23-byte PDU link (bolus history populates correctly, §2.3.10). | Expected: ≤20-byte fragmentation reassembles correctly. Uncertain: real fragmentation edge cases at MTU 23 on a long history. | RESOLVED if bolus/event history reads cleanly; CARRIED with the capture if records are truncated/dropped. |
| 7 | **Per-model E2E-CRC for 680G/770G** | CGM reads succeed (§2.3.7) on a 680G and/or 770G — not just 780G — driven by the CGM Feature flag, not a 780G hardcode. Apply the §2.3.7 decision rule: pump-shows-glucose-but-app-shows-none = a CRC mismatch (WRONG), not N/A. | Expected: the features-flag-driven path works on 680G/770G. Uncertain: whether non-780G models set the E2E-CRC bit as assumed. | RESOLVED per model that reads CGM correctly; CARRIED (WRONG) for a model where the pump has glucose but the app shows none; coverage GAP for any model not available to the tester (a gap is not a failure). |
| 8 | **SmartGuard / auto-basal micro-bolus attribution** | On a 770G/780G in SmartGuard, whether auto-basal micro-boluses appear and how they're attributed vs. user boluses (§2.3.9/10). | Expected: macro events map. Uncertain — known open nuance shared with Medtronic Connect: micro-bolus attribution may be incomplete. | RESOLVED if micro-boluses attribute correctly; otherwise CARRIED as the documented known limitation (already disclosed in the user doc). |

> **Where the evidence lives.** Record one-line verdicts in this table during the session, and drop
> the detailed app-vs-pump readings into the per-model matrix (§5). The raw capture (gitignored) is
> the backing evidence for anything CARRIED — it lets the parse be corrected offline without the
> pump.

---

## 4. Sentry-with-pump procedure (live error-path gate)

Run the mobile Sentry gate **with the real pump** so the driver's BLE / SAKE / GATT / reader error
paths actually execute — the emulator could never trigger them. The `op run` step is unattended now
that a 1Password **service account** is active (`op whoami` → `SERVICE_ACCOUNT`); no desktop approval
is needed.

> **Quota.** Keep Sentry **off** for all ordinary iteration. Only build the Sentry-enabled APK for
> this one live gate, and rebuild Sentry-off afterward.

### Steps

1. [ ] Confirm the service account is active:
       ```sh
       op whoami    # expect: User Type: SERVICE_ACCOUNT
       ```
2. [ ] Build the **Sentry-enabled** debug APK (DSN injected from 1Password at build time, never
       plaintext):
       ```sh
       SENTRY_DSN="op://develop/Sentry DSN - Mobile/password" \
       SENTRY_ENVIRONMENT="development" \
       op run -- ./gradlew :app:assembleDebug
       ```
       After installing and launching the app, confirm the **device logcat** (not the gradle build
       output) shows `Sentry initialized (environment=development)` — that line is emitted at app
       startup when the DSN is present.
3. [ ] Install on the physical phone and run the **full §2 golden path** with the pump, so real
       glucose/IoB/basal values flow through the driver.
4. [ ] **Exercise the error paths on purpose** so the gate has something to observe (these are the
       paths the emulator can't reach). Note which produce a Sentry **event** vs. only a **breadcrumb**
       — the driver routes Timber WARN to breadcrumbs and Timber ERROR to events:
       - [ ] **SAKE handshake/auth failure** — interrupt the handshake (move the pump away mid-pair).
             These log at **ERROR → Sentry event** (`HANDSHAKE_TIMEOUT`, `AUTH_FAILED`).
       - [ ] **Advertiser failure** — if reproducible (e.g. another app holding the advertiser), forces
             an `ADVERTISE_FAILED` at **ERROR → Sentry event**. This is the most reliable way to
             confirm an event actually reaches `glycemicgpt-mobile`.
       - [ ] **Still-bound-elsewhere** — start pairing with the pump still on the official app. Logs at
             **WARN → breadcrumb only** (`BOUND_ELSEWHERE`); expect no event.
       - [ ] **Disconnect mid-session / poll timeout** — drop the link or move to the edge of range
             during a read. The reader failure logs at **WARN → breadcrumb only**; expect no event.
5. [ ] In the **Sentry MCP**, query the `glycemicgpt-mobile` project for new/unresolved issues in the
       run window. An **empty event list for the WARN-only exercises is expected** — those live in
       breadcrumbs, not as issues. The ERROR exercises (SAKE/advertiser) should produce issues.
6. [ ] **Triage every surfaced issue:**
       - **Expected** (a deliberately-triggered ERROR-level connection failure — SAKE auth/timeout or
         advertiser failure — surfaced as a `Timber.e` event from the paths you just exercised).
         Confirm the message body carries **no PHI** (no glucose/IoB/serial values — the driver logs
         op + exception class / GATT status only) and resolve it as validation noise with a comment.
       - **Unexpected** (anything not explained by the paths you exercised): treat as a real bug.
         Fix it, then **re-run the whole dev loop from automated checks back to this gate** — do not
         shortcut to a PR.
7. [ ] **Re-confirm no PHI under live data.** This is the PHI-in-logs leak failure mode, now with
       real glucose and IoB values flowing. Inspect the structured fields (tags / user / extra) of
       every issue **and the breadcrumbs** (the WARN reader-failure lines land there, and that is the
       path closest to live readings) — the Sentry MCP masks message bodies on output, so check the
       structured fields explicitly. None may contain a glucose value, an IoB value, a pump serial, or
       any reading.
8. [ ] **Resolve the synthetic/validation issues** you created, with a root-cause comment. Resolve
       any real issues you actually fixed.
9. [ ] **Rebuild Sentry-off** (plain `./gradlew :app:assembleDebug`, DSN empty → "Sentry disabled")
       and reinstall, so the tester's phone isn't left reporting and we don't burn quota.

The gate **passes** only when the live run surfaces no unresolved real issues attributable to the
driver and no PHI under real data.

---

## 5. Per-model verification matrix (template — fill live)

Fill one cell per field × model with the verdict from §2.3, comparing each app value to the pump's
own display. Only fill columns for models the tester actually has; leave the rest as a recorded
coverage **gap** (a gap is not a failure — the driver stays flagged for unverified models).

Legend: **OK** = app matches pump · **WRONG** = app disagrees with pump (record both values) ·
**N/A** = field not present on this model · **GAP** = model not available to test.

| Field | 680G | 770G | 780G | Notes (app value vs. pump value; anomalies) |
|---|---|---|---|---|
| CGM (sensor glucose mg/dL + trend) |  |  |  |  |
| IoB ⚠️ (insulin on board) |  |  |  | Highest-risk; record exact app-vs-pump pairs |
| Basal rate (active) |  |  |  | SmartGuard moves this automatically |
| Bolus history |  |  |  | Check most-recent bolus + no duplicate rows |
| Reservoir (units) |  |  |  |  |
| Battery (%) |  |  |  |  |
| Alarms / annunciations |  |  |  | Record any types seen |

**Per-model open items (carry the §3 verdicts here):**

- E2E-CRC features-flag path verified on: ☐ 680G ☐ 770G ☐ 780G (gaps = not tested)
- SmartGuard / auto-basal micro-bolus attribution: ☐ resolved ☐ carried as known limitation
- IoB trusted (matched pump across multiple readings): ☐ 680G ☐ 770G ☐ 780G

> **Home of the filled matrix.** The completed results belong in the local-only findings doc
> `medtronic-ble-reverse-engineering.md` (kept out of the committed tree, alongside the per-model
> E2E-CRC and IoB notes it already carries) — not next to this runbook. This empty template lives
> here in the committed dev docs so the *procedure* is reviewable; after the run, copy the filled-in
> results into that findings doc and into the session sign-off (§6). Model-mapping verdicts
> (OK/WRONG/N/A) are **not** PHI; do not paste raw glucose/IoB time series into any committed file.

---

## 6. Sign-off

After the session, record:

- [ ] The filled per-model matrix (§5) and its coverage gaps.
- [ ] Each §3 item marked RESOLVED or CARRIED, with the evidence.
- [ ] The Sentry gate result (§4): clean / issues fixed; PHI re-confirmed absent.
- [ ] Any per-model caveats.
- [ ] **Verdict:** driver graduates to validated BETA, **or** stays flag-default pending a specific
      unresolved finding (name it). A wrong-IoB or wrong-CRC finding that keeps the driver flagged is
      a successful outcome — the point of the session is to catch exactly that before users rely on it.

---

## Capturing the session (offline regression fixture)

A live session is scarce; capturing it turns a one-shot run into a durable offline fixture so the
protocol can be re-verified — and any CARRIED parse corrected — **without** the pump.

> **PHI.** A live capture contains real glucose, insulin, and device-identifier data. It is PHI and
> **must never be committed.** The capture paths below are gitignored; verify before and after.

### Why the HCI snoop log (not app logcat)

The Tandem driver logs raw frames under a `BLE_RAW` tag, but the **Medtronic driver does not** — it
is PHI-hardened and logs only operation names + byte counts, never wire bytes. So
`./scripts/mobile-dev.sh phone ble-raw` (which greps logcat for `BLE_RAW`) produces an **empty**
capture for a Medtronic session and must not be used here. The over-the-air frames are instead
captured at the OS level via the **Bluetooth HCI snoop log**, which records every BLE PDU regardless
of app logging — including the SAKE handshake and the encrypted session traffic.

### Where captures go (gitignored)

Pull the snoop log into `tools/medtronic-ble-spike/captures/`. That directory is gitignored, so
anything written there stays local. Verify:

```sh
# Should print the ignoring rule (i.e. the file is ignored), not nothing:
git check-ignore -v tools/medtronic-ble-spike/captures/session.btsnoop
```

### Capturing during the live session

1. **Before** pairing (§2.0): on the phone, enable Developer Options → **Enable Bluetooth HCI snoop
   log**, then toggle Bluetooth off and on so logging starts fresh. The OS now writes every BLE frame
   to the snoop log for the whole session.
2. Run the full §2 golden path with the pump.
3. **After** unpair (§2.5): pull the snoop log into the gitignored capture dir. The exact on-device
   path is OEM-dependent; the portable way is via a bug report:

   ```sh
   mkdir -p tools/medtronic-ble-spike/captures
   # Either pull the snoop log directly if your device exposes it:
   adb pull /sdcard/btsnoop_hci.log tools/medtronic-ble-spike/captures/session.btsnoop 2>/dev/null \
     # …or extract it from a bug report (works on any device):
     || (adb bugreport tools/medtronic-ble-spike/captures/bugreport.zip \
         && echo "Snoop log is inside bugreport.zip under FS/data/misc/bluetooth/logs/ (extract it there).")
   ```
4. Confirm the pulled file is **non-empty** and still gitignored (`git status` shows nothing new
   under `captures/`). An empty file means snoop logging wasn't enabled before the handshake — the
   capture is lost and cannot be recreated without the pump.

The resulting `.btsnoop`/bugreport is the wire-level record of the handshake + reads. Disable HCI
snoop logging afterward (it logs all Bluetooth traffic system-wide).

### Re-verifying offline afterward

The spike harness (`tools/medtronic-ble-spike/`) replays SAKE + SeqCrypt against captured vectors
with `./gradlew test` / `./gradlew run`. A live capture extends that: the recorded frames can be fed
back through the parsers offline to confirm (or correct) any field that was CARRIED in §3 — most
importantly IoB — without needing the pump again. Keep the capture local; reference it in the
sign-off, never commit it.
