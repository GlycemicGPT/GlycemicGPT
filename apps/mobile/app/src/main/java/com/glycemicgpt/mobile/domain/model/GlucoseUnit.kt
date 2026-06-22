package com.glycemicgpt.mobile.domain.model

/**
 * User-facing glucose display unit.
 *
 * Storage, transport, every threshold comparison, alert detection, and the
 * platform-wide 20-500 safety invariant all stay canonical mg/dL. This enum only
 * selects how a glucose number is *shown* (and spoken) to the user.
 *
 * [wireValue] mirrors the backend `GlucoseUnit` enum's JSON serialization
 * (`"mgdl"` / `"mmol"`); [name] (`MGDL` / `MMOL`) is what we persist in
 * SharedPreferences, matching the existing string-stored-enum pattern.
 */
enum class GlucoseUnit(val wireValue: String) {
    MGDL("mgdl"),
    MMOL("mmol"),
    ;

    companion object {
        /** Parse a backend JSON value (`"mgdl"`/`"mmol"`); unknown/null falls back to [MGDL]. */
        fun fromWire(value: String?): GlucoseUnit =
            entries.firstOrNull { it.wireValue.equals(value, ignoreCase = true) } ?: MGDL

        /**
         * Parse a persisted enum name (SharedPreferences); unknown/null/corrupt falls back to
         * [MGDL]. Mirrors the `themeMode` try/catch-valueOf storage pattern and never throws.
         */
        fun fromName(value: String?): GlucoseUnit =
            try {
                valueOf(value ?: MGDL.name)
            } catch (_: IllegalArgumentException) {
                MGDL
            }
    }
}
