package com.glycemicgpt.weardevice.util

/**
 * Watch-side mirror of the phone's `GlucoseUnit`
 * (`app/.../domain/model/GlucoseUnit.kt`). The two live in separate Gradle
 * modules and cannot share code, so the wire token and parsing are duplicated
 * here deliberately.
 *
 * Display-only: storage, transport, every threshold comparison, and the
 * platform-wide 20-500 mg/dL safety invariant all stay canonical mg/dL. This
 * enum only selects how a glucose number is shown (and spoken) to the user.
 *
 * [wireValue] is the token carried on `WearDataContract.KEY_GLUCOSE_UNIT`
 * (`"mgdl"` / `"mmol"`), matching the phone enum and the backend serialization.
 */
enum class GlucoseUnit(val wireValue: String) {
    MGDL("mgdl"),
    MMOL("mmol"),
    ;

    companion object {
        /** Parse the wire token (`"mgdl"`/`"mmol"`); unknown/null falls back to [MGDL]. */
        fun fromWire(value: String?): GlucoseUnit =
            entries.firstOrNull { it.wireValue.equals(value, ignoreCase = true) } ?: MGDL
    }
}
