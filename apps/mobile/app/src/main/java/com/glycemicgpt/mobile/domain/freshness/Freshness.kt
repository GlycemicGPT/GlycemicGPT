package com.glycemicgpt.mobile.domain.freshness

/**
 * How trustworthy a timestamped data point is, given its age.
 *
 * One classifier shared across every dashboard source so staleness is judged the same
 * way everywhere instead of each surface re-deriving it. The three tiers map to a display policy:
 *
 * - [FRESH] — recent; render normally, "just now" / "Xm ago" is advisory only.
 * - [STALE] — older than the source's expected cadence; show a "last updated Xm ago" badge so the
 *   user knows it is cached, but the value is still shown.
 * - [TOO_STALE] — old enough that the value must NOT be presented as a current reading. For glucose
 *   this is a safety-grade de-emphasis (grey + "stale") rather than a confident live number
 *   ([FreshnessThresholds.tooStaleAfterMs]).
 *
 * The local freshness-gated alerting layer reuses this exact policy — do not fork a second
 * staleness definition.
 */
enum class Freshness { FRESH, STALE, TOO_STALE }

/**
 * Per-source staleness bounds, in milliseconds, mirroring the `STALE_THRESHOLD_MS` idiom used by the
 * cached-settings stores (`SafetyLimitsStore`, `GlucoseRangeStore`, ...).
 *
 * @property staleAfterMs age at which [FRESH] flips to [STALE] (the "last updated Xm ago" advisory).
 * @property tooStaleAfterMs age at which [STALE] flips to [TOO_STALE] (the value is no longer shown
 *   as a live reading; for glucose this is the de-emphasis threshold — a safety call).
 *
 * Boundaries are half-open: `age < staleAfterMs` is FRESH, `staleAfterMs <= age < tooStaleAfterMs`
 * is STALE, and `age >= tooStaleAfterMs` is TOO_STALE. So a point exactly at [staleAfterMs] is STALE
 * and one exactly at [tooStaleAfterMs] is TOO_STALE.
 */
data class FreshnessThresholds(
    val staleAfterMs: Long,
    val tooStaleAfterMs: Long,
) {
    init {
        require(staleAfterMs in 1 until tooStaleAfterMs) {
            "staleAfterMs ($staleAfterMs) must be positive and < tooStaleAfterMs ($tooStaleAfterMs)"
        }
    }

    /** Classify a point of the given [ageMs] (now - timestamp). Negative ages (clock skew, a
     *  future timestamp) are treated as [Freshness.FRESH]. */
    fun classify(ageMs: Long): Freshness = when {
        ageMs < staleAfterMs -> Freshness.FRESH
        ageMs < tooStaleAfterMs -> Freshness.STALE
        else -> Freshness.TOO_STALE
    }
}

/** Human "how long ago" for an age in ms. Pure (no Android/Compose) so it is unit-testable and can
 *  be reused by the watch/complication surfaces. Negative ages read as "just now". */
fun relativeAgeLabel(ageMs: Long): String {
    val seconds = ageMs / 1000
    return when {
        seconds < 60 -> "just now"
        seconds < 3600 -> "${seconds / 60}m ago"
        seconds < 86_400 -> "${seconds / 3600}h ago"
        else -> "${seconds / 86_400}d ago"
    }
}

/**
 * The documented staleness policy per data source. These thresholds are a **display safety
 * decision**: they decide when a cached number stops being presented as
 * current. They are deliberately conservative and are surfaced for PM/clinical sign-off at review.
 */
object FreshnessPolicy {
    private const val MINUTE_MS = 60_000L

    /**
     * CGM glucose. Sensors (Dexcom G6/G7, Libre) publish a new value roughly every 5 minutes, so a
     * single missed reading (~6 min) is [Freshness.STALE] — worth a badge but still plausibly
     * current. By ~15 min (three missed readings) the trend and value can no longer be trusted as a
     * live glucose, so it is [Freshness.TOO_STALE] and de-emphasised. The freshness-gated alerting layer reuses
     * TOO_STALE as the "don't fire a glucose alert off this" floor.
     */
    val CGM = FreshnessThresholds(staleAfterMs = 6 * MINUTE_MS, tooStaleAfterMs = 15 * MINUTE_MS)

    /**
     * Pump-state values shown as secondary metrics — IOB, basal, battery, reservoir. These are
     * polled far less aggressively than glucose (battery/reservoir every ~5 min) and are not a
     * safety-critical live vital, so the policy is looser: a ~15-minute gap (several missed polls)
     * means the pump link has dropped ([Freshness.STALE]); an hour old is clearly not current
     * ([Freshness.TOO_STALE]).
     */
    val PUMP = FreshnessThresholds(staleAfterMs = 15 * MINUTE_MS, tooStaleAfterMs = 60 * MINUTE_MS)

    /**
     * Debug-only compressed thresholds so the FRESH → STALE → TOO_STALE transitions can be observed
     * in seconds on an emulator instead of waiting out the real 15-min
     * CGM bound. Never used in release paths — the compressed policy is only substituted when the
     * debug "Fast staleness" fault-injection toggle is on. Seeds the reusable debug harness.
     */
    val CGM_DEBUG_FAST = FreshnessThresholds(staleAfterMs = 20_000L, tooStaleAfterMs = 45_000L)
}
