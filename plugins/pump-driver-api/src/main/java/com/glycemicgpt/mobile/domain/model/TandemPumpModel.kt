package com.glycemicgpt.mobile.domain.model

/**
 * Known Tandem pump hardware models, identified by BLE advertised name.
 *
 * This enum lives in the SDK because pairing UX (in the app module) needs it
 * to show model-appropriate instructions. The SDK already contains other
 * Tandem-specific domain types (e.g. [ControlIqMode]).
 */
enum class TandemPumpModel(
    /** Human-readable model label. */
    val displayName: String,
    /**
     * Whether the pump has a built-in screen for displaying pairing codes.
     * `null` means unknown -- callers should show generic instructions.
     */
    val hasScreen: Boolean?,
) {
    TSLIM_X2("t:slim X2", hasScreen = true),
    MOBI("Mobi", hasScreen = false),
    UNKNOWN("Unknown Tandem Pump", hasScreen = null);

    companion object {
        /**
         * Detect the pump model from the BLE advertised name.
         *
         * X2 advertises as "tslim X2 ..." and Mobi as "Tandem Mobi ...".
         * Matching is case-insensitive to handle variant capitalisation in
         * BLE advertisements.
         */
        fun fromAdvertisedName(name: String?): TandemPumpModel = when {
            name == null -> UNKNOWN
            name.startsWith("tslim X2", ignoreCase = true) -> TSLIM_X2
            name.startsWith("Tandem Mobi", ignoreCase = true) -> MOBI
            else -> UNKNOWN
        }
    }
}
