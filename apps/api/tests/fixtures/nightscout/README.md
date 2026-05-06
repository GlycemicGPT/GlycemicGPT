# Nightscout Test Fixtures

Synthetic JSON fixtures for the Nightscout translator's input layer
(Story 43.3 PR1). Each fixture represents one realistic
on-the-wire shape from a specific uploader.

## Provenance policy

**Synthetic only.** No fixture contains data copied from a real Nightscout
instance. Every value (glucose, carbs, insulin, timestamps) is hand-authored
to be obviously test data: round-number BGs, round bolus/carb amounts, a
fixed reference date of 2026-05-06.

This matches the project's "no project-owned medical data" rule. AC9 of
Story 43.3 ("Test fixtures from at least 3 real Nightscout instances
representing different upstream uploaders") is satisfied by covering 4+
uploader shapes, not by copying real instance data.

## Source attribution per fixture

Each fixture's shape was verified against the upstream uploader's source
code on GitHub. The references below cite:
- The upstream repo + file path
- The Ben West cross-validation reference doc (where it informed the shape)
- Any verification work (resolved 2026-05-06)

### Tier 1 fixtures (this PR)

#### entries/

| Fixture | Source |
|---|---|
| `xdrip_sgv.json` | xDrip+ Android: `app/src/main/java/com/eveningoutpost/dexdrip/utilitymodels/NightscoutUploader.java#L664-L694` ([NightscoutFoundation/xDrip](https://github.com/NightscoutFoundation/xDrip)). Cross-ref: `bewest mapping/xdrip/nightscout-fields.md`. Notes: `rssi: 100` is hardcoded for non-share-follower paths; `filtered`/`unfiltered` scaled by 1000 (Dexcom G4 raw counts, kept for legacy). |
| `dexcom_bridge_sgv.json` | cgm-remote-monitor's own bridge ("share2" device): `lib/server/swagger.yaml` + `lib/server/entries.js#L100-L125`. Lean shape (no raw fields) -- a useful baseline for parsers that assume `delta`/`filtered`/`unfiltered` are always present. |
| `xdrip_mbg_fingerstick.json` | xDrip+ entries-route fingerstick: `NightscoutUploader.java#L716-L742`. Per synthesis §1.8: same logical event as `xdrip4ios_bg_check_treatment.json`, different collection. |
| `cal_calibration.json` | Canonical calibration record per `bewest mapping/openaps/nightscout-formats.md §Calibration Format`. `scale: 1` is the documented default. Useful for noise/calibration-window analysis. |

#### treatments/

| Fixture | Source |
|---|---|
| `careportal_meal_bolus.json` | cgm-remote-monitor Care Portal: `lib/client/careportal.js#L247-L345` (`gatherData`). Canonical NS shape with `created_at`+`enteredBy`+`carbs`+`insulin`+`notes`. |
| `careportal_temp_basal.json` | Care Portal Temp Basal collapses Start/End to bare `"Temp Basal"` per `lib/client/careportal.js#L319-L321`. Absolute U/h rate + duration in **minutes** (locked per §10.V2 verification). |
| `careportal_profile_switch.json` | Care Portal `Profile Switch` with full tuple. Per synthesis §1.6: profile/originalProfileName/percentage/timeshift/duration encode three semantically distinct cases. |
| `careportal_temporary_target.json` | Care Portal `Temporary Target`. `targetTop`/`targetBottom` always in mg/dL on the wire (Care Portal pre-converts mmol input client-side). |
| `loop_correction_bolus.json` | Loop iOS bolus full shape: [LoopKit/NightscoutKit `Sources/NightscoutKit/Models/Treatments/BolusNightscoutTreatment.swift`](https://github.com/LoopKit/NightscoutKit/blob/main/Sources/NightscoutKit/Models/Treatments/BolusNightscoutTreatment.swift#L57-L65). Includes `programmed`, `unabsorbed: 0` (always), `duration: 0` for normal bolus, `automatic: true` (Loop SMB signal), `bolusType: "Normal"` (Loop derives `"Square"` if duration ≥30 min), `syncIdentifier` (Loop dedup key). No `_id` -- Loop omits on POST. |
| `loop_carb_correction.json` | Loop carbs use [`identifier` field, NOT `syncIdentifier`](https://github.com/LoopKit/NightscoutKit/blob/main/Sources/NightscoutKit/Models/Treatments/CarbCorrectionNightscoutTreatment.swift#L86-L107) -- different field name from boluses/temp basals. `userEnteredAt`, `userLastModifiedAt` are Loop-specific HealthKit metadata fields. `absorptionTime` is in **seconds** (NS expects minutes; server does NOT auto-convert -- translator must detect Loop+CarbCorrection and convert per synthesis §2.6). |
| `aaps_v1_smb_correction_bolus.json` | AAPS V1 NSClient: `plugins/sync/src/main/kotlin/app/aaps/plugins/sync/nsclient/extensions/BolusExtension.kt#L10-L27` ([nightscout/AndroidAPS](https://github.com/nightscout/AndroidAPS)). Verified §10.V1: `eventType: "Correction Bolus"` + `type: "SMB"` + `isSMB: true` (V1 writes both). Plus AAPS-specific `pumpId`/`pumpType`/`pumpSerial` composite dedup triple. |
| `aaps_v3_smb_correction_bolus.json` | AAPS V3 NSClientV3: `plugins/sync/.../nsclientV3/extensions/BolusExtension.kt#L25-L41` + `core/nssdk/.../mapper/TreatmentMapper.kt#L273-L292`. Verified §10.V1: same eventType+type as V1, but writes `isBasalInsulin` instead of `isSMB`. v3 envelope adds `identifier`, `srvCreated`, `srvModified`, `app`, `utcOffset` (minutes per synthesis §2.6). |
| `aaps_meal_bolus_carbs_only.json` | AAPS carb-only Meal Bolus when carbs ≥12g: `CarbsExtension.kt#L75-L88`. Critical: `eventType: "Meal Bolus"` with NO `insulin` field. Translator must route by field presence (synthesis §1.2), not eventType. |
| `aaps_profile_switch_percentage.json` | AAPS profile-percentage adjustment per `bewest mapping/aaps/profile-switch.md`. `percentage: 110` with same `originalProfileName` is semantically distinct from a true Day→Night switch (synthesis §1.6). `profileJson` is a stringified embedded snapshot of the modified profile. |
| `xdrip_empty_eventtype_with_carbs.json` | xDrip+ behavior per `bewest mapping/nightscout-reporter/treatment-classification.md §Empty Event Types`. xDrip+ sometimes emits `eventType: ""` for treatments that still carry valid carbs/insulin. Translator must route by field presence, NOT crash on empty/`<none>`/null. |
| `xdrip4ios_bg_check_treatment.json` | xDrip4iOS treatments-route fingerstick. Per synthesis §1.8: same logical event as `xdrip_mbg_fingerstick.json` but in the treatments collection. `enteredBy: "xDrip4iOS"` (camelCase, distinct from xDrip+ Android's lowercase `"xdrip"`). |

#### devicestatus/

| Fixture | Source |
|---|---|
| `loop_devicestatus.json` | Loop iOS: [LoopKit/NightscoutKit `Models/DeviceStatus.swift`](https://github.com/LoopKit/NightscoutKit/blob/main/Sources/NightscoutKit/Models/DeviceStatus.swift#L31-L62) + `LoopStatus.swift` + `PumpStatus.swift` + `OverrideStatus.swift`. Notable: `pump.iob: null` (always nil for Loop -- only `loop.iob` is populated, synthesis §7.3); snake_case `reservoir_display_override`/`reservoir_level_override` (everything else is camelCase); `predicted.values` keys uppercase `IOB`/`COB` while `loop.iob`/`loop.cob` is lowercase; `automaticDoseRecommendation` carries hybrid temp+bolus cycle data. |
| `aaps_devicestatus.json` | AAPS V1: `plugins/sync/.../nsclient/extensions/DeviceStatusExtension.kt#L555-L569` + `LoopPlugin.buildAndStoreDeviceStatus()`. Notable: `pump.extended` carries driver-specific freeform JSON; `uploaderBattery` is a top-level int (V1 quirk), distinct from the nested `uploader.battery` (V3 supports both); `openaps.suggested`/`enacted` carry the full oref0 `rT` payload verbatim. |
| `oref0_devicestatus_with_predbgs.json` | oref0 `bin/ns-status.js#L130-L175` ([openaps/oref0](https://github.com/openaps/oref0)). Notable: full `predBGs: {IOB,ZT,COB,UAM}` (4 arrays of integer mg/dL); `tick: "-1"` (signed string -- not number, see `mapping/oref0/data-models.md §rT`); `reservoir: null` is valid (don't crash); `device: "openaps://example-rig/medtronic-722"` is a structured URI parsed by `parse_openaps_uri()`; `iob.mills` injected for backwards compat. |

#### profile/

| Fixture | Source |
|---|---|
| `multi_store_profile.json` | Canonical NS profile: `cgm-remote-monitor lib/profile/profileeditor.js#L28-L71` + `#L119-L134`. Contains `defaultProfile` indirection, two stores (`Default` + `Exercise`), multi-zone basal/sens/carbratio/target_low/target_high. **First entry NOT at 00:00** (06:00) to force midnight-wrap parsing per `bewest mapping/nightscout-reporter/profile-handling.md §Midnight Entry Handling`. |

## Cross-validation references (Ben's repo)

`bewest/rag-nightscout-ecosystem-alignment` provides per-uploader mapping
documentation cited above. Used as reference only; not vendored. Verified
3 of 3 contradictions against current upstream source in 2026-05-06
verification pass:

1. AAPS V3 SMB encoding: NEVER bare `"SMB"` (Ben's NSBolus mapping was
   model-level convention, not wire output)
2. Loop override duration: minutes in treatments, seconds in devicestatus
   (Ben missed the encode-time `.minutes` conversion in `OverrideTreatment.swift:62-70`)
3. Trio override path: uploads as `eventType: "Exercise"` (Ben's doc was
   stale, pre-CoreData rewrite mid-2024)

See `_bmad-output/planning-artifacts/nightscout-translator-fixture-survey.md` §10
for full verification details.

### Tier 2 fixtures (this PR — translator routing edge cases)

#### entries/

| Fixture | Source |
|---|---|
| `xdrip_sgv_noisy.json` | xDrip+ Android with `noise: 4` (heavy) and `direction: "NOT COMPUTABLE"` (canonical spaced form). Locks the defensive direction-enum parser and the noise-int coercion path. |

#### treatments/

| Fixture | Source |
|---|---|
| `aaps_effective_profile_switch_as_note.json` | AAPS uploads Effective Profile Switch as `eventType: "Note"` with `originalProfileName` populated (telltale). Routes to the profile-switch translator path despite the Note eventType. Per `mapping/aaps/profile-switch.md`. |
| `aaps_extended_bolus_emulating_tbr.json` | AAPS extended-bolus-emulating-TBR shape: outer `Temp Basal` envelope with nested `extendedEmulated` Combo Bolus. Translator's `is_combo_bolus` detection requires both (a) Temp Basal envelope AND (b) bolus-bearing `extendedEmulated` payload. |
| `aaps_temp_basal_superbolus.json` | AAPS `type: "SUPERBOLUS"` (1 of 5 Temp Basal Type values). Routes as Temp Basal with `aaps_type=SUPERBOLUS` preserved in metadata. |
| `aaps_temp_basal_emulated_suspend.json` | AAPS `type: "EMULATED_PUMP_SUSPEND"` with rate=0, percent=-100, duration=60. Routes as suspend (rate=0 + duration ≥30). |
| `aaps_carbs_with_protein_fat.json` | High-fat meal: `carbs + protein + fat + duration` per `mapping/aaps/nightscout-models.md`. Captures AAPS extended-meal nutrition. |
| `aaps_therapy_event_site_change.json` | NSTherapyEvent path: `eventType: "Site Change"`. Routes to device_event (was on the deliberate-skip list pre-cross-validation; promoted because therapy events anchor occlusion analysis). |
| `aaps_therapy_event_sensor_start.json` | `eventType: "Sensor Start"` with `transmitterId`. Anchors CGM noise/calibration windows. |
| `loop_pump_suspend_as_temp_basal.json` | Loop convention: `Temp Basal` rate=0, `reason: "suspend"`, duration ≥30 min. Per `LoopKit/NightscoutService DoseEntry.swift:46`. |
| `loop_square_bolus.json` | Loop bolus with delivery duration ≥30 min, classified `bolusType: "Square"` (per `BolusNightscoutTreatment.swift:62`, `bolusType: duration >= 30 min ? .Square : .Normal`). Translator preserves `bolus_subtype=square` in metadata. |
| `loop_override_with_remote_address.json` | Loop override triggered via remote command: `enteredBy: "Loop (via remote command)"`, `remoteAddress` populated. Per `OverrideTreatment.swift:43-48`. |
| `careportal_combo_bolus.json` | Care Portal Combo Bolus: `splitNow: 60, splitExt: 40` (sums to 100 per the constraint). |
| `bolus_wizard_with_carbs.json` | AAPS `eventType: "Bolus Wizard"` with insulin AND carbs. The 4th carb encoding (`isCarbBolus = isMealBolus OR (isBolusWizard AND carbs > 0)` per Reporter heuristic). Routes as meal_bolus_pair → split into bolus + carbs rows. Includes `bolusCalculatorResult` JSON for AI analysis context. |
| `trio_exercise_override.json` | Trio override toggle uploads as `eventType: "Exercise"` per `Trio/Sources/APS/Storage/OverrideStorage.swift`. Indefinite would use `duration: 43200`. |
| `trio_temp_target_manual.json` | Trio manual temp-target preset uploads as `eventType: "Temporary Target"` via a separate code path from override toggles -- two distinct features. |

#### devicestatus/

| Fixture | Source |
|---|---|
| `loop_failure_devicestatus.json` | Loop failure cycle: `loop.failureReason` populated, NO `loop.enacted` block. Mutually exclusive at the source per `LoopStatus.swift` `enacted` guard. |
| `loop_hybrid_dose_devicestatus.json` | Loop hybrid dose: `automaticDoseRecommendation` carries both `tempBasalAdjustment` AND `bolusVolume` simultaneously. Tests parser handling of combined cycles. |
| `trio_devicestatus_with_tdd.json` | Trio's `enacted.TDD` plus `insulin: { TDD, bolus, temp_basal, scheduled_basal }` sub-object on suggested/enacted. TDD also injected into the `reason` string per `NightscoutManager.swift`. |

### Tier 3 fixtures (deferred to follow-up PR)

17 regression-lock fixtures from the synthesis doc §4 (V3 RemoteTreatment envelope, Nocturne unknown event types, xDrip4iOS suffix-extension `_id`, AAPS Bolus Wizard `bolusCalculatorResult` deeper variants, isValid soft-delete, pre-v14 legacy treatment, etc.). Not required for translator correctness on the 95% case; useful as defensive locks once we have community beta data flowing.

## Adding a new fixture

1. Create the JSON file in the appropriate subdirectory (`entries/`,
   `treatments/`, `devicestatus/`, `profile/`).
2. Use synthetic data only -- round-number BGs within the medically
   plausible range (40-400 mg/dL for normal readings), fixed test
   date, no patient-derived values. Where a fixture is intentionally
   testing boundary or gap behavior, include explicit boundary values
   (e.g., the gap fixtures use `sgv: 5` and `sgv: 1100` to lock the
   `is_glucose_gap` rule).
3. Add a row to the table above with the upstream source citation
   (URL + file path + line range when possible).
4. Add a parser test in `apps/api/tests/test_nightscout_models.py`
   that loads the fixture and asserts the routing decision (e.g.,
   `semantic_kind`, `is_smb`, `is_glucose_gap`). Tests must:
   - **Mock all external services** (Dexcom Share, Tandem cloud, AI
     providers, real Nightscout instances). Parser tests load JSON
     from the fixture directory and exercise the in-process Pydantic
     models -- no network or filesystem access outside `tests/fixtures/`
     is permitted.
   - **Cover edge cases** including null/empty values, empty/`<none>`
     eventTypes (xDrip+ behavior), and glucose boundary values
     (40-400 mg/dL valid range plus the `sgv < 20` / `sgv > 1000`
     gap thresholds).

## Licensing

These fixtures are part of the GlycemicGPT codebase and inherit its
license. Field shapes were observed in upstream open-source projects
(LoopKit, AndroidAPS, Trio, oref0, xDrip+, cgm-remote-monitor); the
documented shapes themselves are not copyrightable wire-protocol facts.
No upstream code is reproduced here -- only the JSON shapes that those
projects produce on the wire.
