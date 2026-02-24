package com.glycemicgpt.mobile.domain.plugin

/**
 * Capabilities a plugin can declare. The platform uses these to enforce
 * mutual-exclusion rules and route data to the correct consumers.
 */
enum class PluginCapability {
    /** Provides CGM/glucose readings (CGMs, pumps with CGM stream). Max 1 active. */
    GLUCOSE_SOURCE,

    /** Provides IoB, basal rate, bolus history (read-only). Max 1 active. */
    INSULIN_SOURCE,

    /** Provides battery, reservoir, hardware info (read-only). Max 1 active. */
    PUMP_STATUS,

    /** Insulin delivery (future, build-from-source only). Max 1 active. */
    PUMP_CONTROL,

    /** Provides fingerstick blood glucose readings. Multiple allowed. */
    BGM_SOURCE,

    /** Accepts calibration from BGM readings. Max 1 active. */
    CALIBRATION_TARGET,

    /** Syncs data to external services (Nightscout, Tidepool). Multiple allowed. */
    DATA_SYNC,
    ;

    companion object {
        /** Capabilities that allow only one active plugin at a time. */
        val SINGLE_INSTANCE: Set<PluginCapability> = setOf(
            GLUCOSE_SOURCE,
            INSULIN_SOURCE,
            PUMP_STATUS,
            PUMP_CONTROL,
            CALIBRATION_TARGET,
        )

        /** Capabilities that allow multiple active plugins simultaneously. */
        val MULTI_INSTANCE: Set<PluginCapability> = setOf(
            BGM_SOURCE,
            DATA_SYNC,
        )

        init {
            val covered = SINGLE_INSTANCE + MULTI_INSTANCE
            check(covered == entries.toSet()) {
                "PluginCapability exhaustiveness: missing from SINGLE_INSTANCE or MULTI_INSTANCE: " +
                    (entries.toSet() - covered)
            }
        }
    }
}
