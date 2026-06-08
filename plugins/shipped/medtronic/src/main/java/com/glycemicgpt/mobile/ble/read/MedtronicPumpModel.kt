/*
 * Per-model capability tiering for the Medtronic MiniMed 700-series read-only driver.
 *
 * GlycemicGPT code (GPL-3.0). The capability bits are read from the IDD Features characteristic as
 * mapped by OpenMinimed PythonPumpConnector `idd/features/pump_features.py` (PumpFeatureFlags),
 * https://github.com/OpenMinimed, GPL-3.0, used with the author's permission. Copyright (C)
 * OpenMinimed contributors: palmarci (Pal Marci), drfubar, Morten Fyhn Amundsen, Stenium; original
 * medtronic-bt-decrypt PoC by @planiitis. GlycemicGPT is itself GPL-3.0.
 */
package com.glycemicgpt.mobile.ble.read

/**
 * The MiniMed 700-series model this driver supports, inferred from the IDD Features capability bits.
 *
 * **Why capability flags and not the model-number string:** the marketing model name (680G/770G/780G)
 * is not on the wire -- the Device Information model characteristic carries an MMT part number
 * (e.g. "MMT-1885") that OpenMinimed never mapped to a marketing name, so substring-matching it is
 * unreliable. The reverse-engineering findings instead prescribe driving per-model behavior off the
 * features flag (the same fix applied to E2E-CRC: read the flag, never hardcode 780G). So this enum
 * is a coarse **capability tier** derived from the closed-loop feature bits, used to decide whether
 * SmartGuard / auto-basal data is expected -- not a precise hardware identifier.
 *
 * The single data-shape consequence that matters for C2 is [supportsSmartGuard]: 770G/780G run a
 * hybrid closed loop (auto-basal, auto-mode therapy state, AP-controller basal context, and on the
 * 780G auto-correction micro-boluses), while the 680G does not. The individual records remain
 * flag-driven and parse safely regardless; this tier only governs interpretation/labeling and the
 * "is this expected for this model?" sanity logging.
 *
 * `TODO(48.A2)`: confirm the exact feature-bit-to-model boundary against a real 680G/770G/780G; the
 * inference here is the best that can be done offline.
 */
enum class MedtronicPumpModel {
    /** No hybrid closed loop: manual/PLGM/suspend-before-low only. No SmartGuard auto-basal. */
    MINIMED_680G,

    /** Hybrid closed loop (SmartGuard auto-basal + auto-mode), without auto-correction boluses. */
    MINIMED_770G,

    /** Hybrid closed loop with auto-correction (SmartGuard + Meal Detection / auto-correction boluses). */
    MINIMED_780G,

    /** Features unavailable or unrecognized; treat conservatively (parse defensively, no assumptions). */
    UNKNOWN,
    ;

    /** True for the closed-loop models (770G/780G) that produce SmartGuard / auto-basal data. */
    val supportsSmartGuard: Boolean
        get() = this == MINIMED_770G || this == MINIMED_780G

    /** True only for the 780G tier, which adds SmartGuard auto-correction (Meal Detection) boluses. */
    val supportsAutoCorrectionBolus: Boolean
        get() = this == MINIMED_780G

    companion object {
        // IDD Features bits (pump_features.py PumpFeatureFlags). Hybrid Closed Loop ("SmartGuard")
        // distinguishes 770G/780G from 680G; Smart Settings (Meal Detection / auto-correction) is the
        // 780G addition on top.
        private const val HCL_FEATURE_SUPPORTED = 1L shl 28
        private const val SMART_SETTINGS_SUPPORTED = 1L shl 29

        /**
         * Infer the capability tier from the IDD Features flag word. With no closed loop -> 680G; with
         * closed loop but no smart settings -> 770G; with both -> 780G. [featureFlags] of 0 (features
         * unread/unavailable) maps to [UNKNOWN].
         */
        fun fromFeatureFlags(featureFlags: Long): MedtronicPumpModel =
            when {
                featureFlags == 0L -> UNKNOWN
                featureFlags and HCL_FEATURE_SUPPORTED == 0L -> MINIMED_680G
                featureFlags and SMART_SETTINGS_SUPPORTED != 0L -> MINIMED_780G
                else -> MINIMED_770G
            }
    }
}
