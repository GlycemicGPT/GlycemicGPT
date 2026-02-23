package com.glycemicgpt.mobile.domain.pump

/**
 * User-configured safety limits for data validation.
 *
 * These values come from the user's backend settings (glucose range,
 * insulin configuration) and are used by parsers to reject implausible
 * readings. The defaults match common clinical ranges but should always
 * be overridden with the user's actual configured values.
 *
 * An `init` block enforces absolute floor/ceiling values that no
 * configuration can bypass -- these represent the physical limits of
 * current CGM sensors and insulin pump hardware.
 */
data class SafetyLimits(
    /** Minimum valid CGM glucose reading in mg/dL. */
    val minGlucoseMgDl: Int = DEFAULT_MIN_GLUCOSE,
    /** Maximum valid CGM glucose reading in mg/dL. */
    val maxGlucoseMgDl: Int = DEFAULT_MAX_GLUCOSE,
    /** Maximum valid basal rate in milliunits/hr. */
    val maxBasalRateMilliunits: Int = DEFAULT_MAX_BASAL_MILLIUNITS,
    /** Maximum valid single bolus dose in milliunits. */
    val maxBolusDoseMilliunits: Int = DEFAULT_MAX_BOLUS_MILLIUNITS,
) {
    init {
        require(minGlucoseMgDl >= ABSOLUTE_MIN_GLUCOSE) {
            "minGlucoseMgDl ($minGlucoseMgDl) cannot be below absolute floor ($ABSOLUTE_MIN_GLUCOSE)"
        }
        require(maxGlucoseMgDl <= ABSOLUTE_MAX_GLUCOSE) {
            "maxGlucoseMgDl ($maxGlucoseMgDl) cannot exceed absolute ceiling ($ABSOLUTE_MAX_GLUCOSE)"
        }
        require(minGlucoseMgDl < maxGlucoseMgDl) {
            "minGlucoseMgDl ($minGlucoseMgDl) must be less than maxGlucoseMgDl ($maxGlucoseMgDl)"
        }
        require(maxBasalRateMilliunits in 1..ABSOLUTE_MAX_BASAL_MILLIUNITS) {
            "maxBasalRateMilliunits ($maxBasalRateMilliunits) must be in 1..$ABSOLUTE_MAX_BASAL_MILLIUNITS"
        }
        require(maxBolusDoseMilliunits in 1..ABSOLUTE_MAX_BOLUS_MILLIUNITS) {
            "maxBolusDoseMilliunits ($maxBolusDoseMilliunits) must be in 1..$ABSOLUTE_MAX_BOLUS_MILLIUNITS"
        }
    }

    companion object {
        const val DEFAULT_MIN_GLUCOSE = 20
        const val DEFAULT_MAX_GLUCOSE = 500
        const val DEFAULT_MAX_BASAL_MILLIUNITS = 15_000 // 15 u/hr (Tandem hardware max)
        const val DEFAULT_MAX_BOLUS_MILLIUNITS = 25_000 // 25 u single dose

        // Absolute clinical bounds -- no backend configuration may widen these.
        // CGM sensors are unreliable below ~20 mg/dL and above ~500 mg/dL.
        const val ABSOLUTE_MIN_GLUCOSE = DEFAULT_MIN_GLUCOSE   // 20 mg/dL
        const val ABSOLUTE_MAX_GLUCOSE = DEFAULT_MAX_GLUCOSE   // 500 mg/dL
        const val ABSOLUTE_MAX_BASAL_MILLIUNITS = DEFAULT_MAX_BASAL_MILLIUNITS
        const val ABSOLUTE_MAX_BOLUS_MILLIUNITS = DEFAULT_MAX_BOLUS_MILLIUNITS

        /**
         * Safe factory that clamps values to absolute bounds instead of throwing.
         *
         * Use this when constructing from untrusted input (e.g., backend config)
         * where a crash would be worse than clamped values. The constructor's
         * [require] checks are intentionally strict for programmatic callers;
         * this factory is lenient for external data.
         */
        fun safeOf(
            minGlucoseMgDl: Int = DEFAULT_MIN_GLUCOSE,
            maxGlucoseMgDl: Int = DEFAULT_MAX_GLUCOSE,
            maxBasalRateMilliunits: Int = DEFAULT_MAX_BASAL_MILLIUNITS,
            maxBolusDoseMilliunits: Int = DEFAULT_MAX_BOLUS_MILLIUNITS,
        ): SafetyLimits {
            val clampedMin = minGlucoseMgDl.coerceIn(ABSOLUTE_MIN_GLUCOSE, ABSOLUTE_MAX_GLUCOSE - 1)
            val clampedMax = maxGlucoseMgDl.coerceIn(clampedMin + 1, ABSOLUTE_MAX_GLUCOSE)
            val clampedBasal = maxBasalRateMilliunits.coerceIn(1, ABSOLUTE_MAX_BASAL_MILLIUNITS)
            val clampedBolus = maxBolusDoseMilliunits.coerceIn(1, ABSOLUTE_MAX_BOLUS_MILLIUNITS)
            return SafetyLimits(clampedMin, clampedMax, clampedBasal, clampedBolus)
        }
    }
}
