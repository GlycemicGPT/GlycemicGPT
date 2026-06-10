package com.glycemicgpt.mobile.plugin.nightscout

import com.glycemicgpt.mobile.data.local.dao.PumpDao
import com.glycemicgpt.mobile.data.remote.GlycemicGptApi
import com.glycemicgpt.mobile.data.remote.dto.NightscoutConnectionDto
import retrofit2.Response
import timber.log.Timber
import java.io.IOException
import java.time.Instant
import javax.inject.Inject
import javax.inject.Singleton

/** The outcome of one sync pass. The worker maps these onto a WorkManager Result. */
sealed interface SyncOutcome {
    /** The plugin is disabled -- nothing to do. */
    data object Disabled : SyncOutcome

    /** No active Nightscout connection is available on this account. */
    data object NoConnection : SyncOutcome

    /** A successful pull; counts are row counts written (post-mapping, pre-dedupe). */
    data class Success(val pages: Int, val cgm: Int, val bolus: Int, val basal: Int) : SyncOutcome

    /** Auth/not-found (401/403/404): give up this run without retrying. */
    data object AuthError : SyncOutcome

    /** A transient error (network, 5xx): the run should be retried with backoff. */
    data object Transient : SyncOutcome
}

/**
 * The pure sync logic for the Nightscout-source plugin (Story 43.8), extracted from
 * the WorkManager worker so it is unit-testable without an Android/WorkManager harness.
 *
 * It pulls the user's Nightscout-sourced data from the backend's unified read endpoint
 * (`GET /api/integrations/nightscout/{id}/data?since=...`) and writes it into the same
 * Room tables the BLE plugins use (AC2/AC4). The `since` cursor is **inclusive**, so the
 * idempotent DAO inserts (unique `timestampMs` / `(units, timestampMs)` indexes) absorb the
 * boundary-row duplicates the backend warns about -- there is no separate ns_id dedupe pass.
 *
 * Logging is counts + connection id only -- never glucose/insulin values (PHI).
 */
@Singleton
class NightscoutSyncEngine @Inject constructor(
    private val api: GlycemicGptApi,
    private val pumpDao: PumpDao,
    private val store: NightscoutSyncStore,
) {

    suspend fun syncOnce(nowMs: Long = System.currentTimeMillis()): SyncOutcome {
        if (!store.enabled) return SyncOutcome.Disabled
        return try {
            val connections = api.listNightscoutConnections().bodyOrThrow().connections
            val connection = resolveConnection(connections) ?: return SyncOutcome.NoConnection
            runSync(connection, nowMs)
        } catch (e: SyncAuthError) {
            Timber.w("Nightscout sync gave up (http %d)", e.code)
            SyncOutcome.AuthError
        } catch (e: SyncTransientError) {
            Timber.w("Nightscout sync transient error: %s", e.message)
            SyncOutcome.Transient
        } catch (e: IOException) {
            Timber.w(e, "Nightscout sync network error")
            SyncOutcome.Transient
        }
    }

    /**
     * Pick the connection to sync: the user-selected one if it is still present and active,
     * otherwise the first active connection.
     */
    private fun resolveConnection(connections: List<NightscoutConnectionDto>): NightscoutConnectionDto? {
        val active = connections.filter { it.isActive }
        val selectedId = store.selectedConnectionId
        return active.firstOrNull { selectedId.isNotEmpty() && it.id == selectedId }
            ?: active.firstOrNull()
    }

    private suspend fun runSync(connection: NightscoutConnectionDto, nowMs: Long): SyncOutcome {
        var cursorMs = store.lastSyncCursorMs
        var pages = 0
        var cgmTotal = 0
        var bolusTotal = 0
        var basalTotal = 0

        while (true) {
            val sinceIso = if (cursorMs > 0) Instant.ofEpochMilli(cursorMs).toString() else null
            val data = api.getNightscoutData(connection.id, sinceIso, PAGE_LIMIT).bodyOrThrow()
            pages++

            if (data.glucoseReadings.isEmpty() && data.pumpEvents.isEmpty()) break

            val cgm = NightscoutDataMapper.toCgmEntities(data)
            val bolus = NightscoutDataMapper.toBolusEntities(data)
            val basal = NightscoutDataMapper.toBasalEntities(data)
            if (cgm.isNotEmpty()) pumpDao.insertCgmBatch(cgm)
            if (bolus.isNotEmpty()) pumpDao.insertBoluses(bolus)
            if (basal.isNotEmpty()) pumpDao.insertBasalBatch(basal)
            cgmTotal += cgm.size
            bolusTotal += bolus.size
            basalTotal += basal.size

            val effLimit = data.effectiveLimitPerArray.coerceAtLeast(1)
            val glucoseFull = data.glucoseReadings.size >= effLimit
            val eventsFull = data.pumpEvents.size >= effLimit
            val glucoseMax = data.glucoseReadings.maxOfOrNull { it.readingTimestamp.toEpochMilli() }
            val eventsMax = data.pumpEvents.maxOfOrNull { it.eventTimestamp.toEpochMilli() }
            val overallMax = maxOf(cursorMs, glucoseMax ?: cursorMs, eventsMax ?: cursorMs)

            if (!glucoseFull && !eventsFull) {
                // Both streams fully drained: advance past everything we pulled and stop.
                cursorMs = overallMax
                break
            }
            // At least one stream is truncated; advance only as far as the lagging full stream so
            // its un-fetched tail is never skipped. The other stream's re-fetched boundary rows are
            // harmless (idempotent inserts). A cursor that can't move forward (all rows share the
            // boundary timestamp) stops the loop.
            val next = listOfNotNull(
                glucoseMax.takeIf { glucoseFull },
                eventsMax.takeIf { eventsFull },
            ).minOrNull() ?: overallMax
            if (next <= cursorMs) break
            cursorMs = next
        }

        store.lastSyncCursorMs = cursorMs
        store.recordSyncCompleted(nowMs)
        Timber.i(
            "Nightscout sync ok: pages=%d cgm=%d bolus=%d basal=%d",
            pages, cgmTotal, bolusTotal, basalTotal,
        )
        return SyncOutcome.Success(pages, cgmTotal, bolusTotal, basalTotal)
    }

    private fun <T> Response<T>.bodyOrThrow(): T {
        if (isSuccessful) {
            return body() ?: throw SyncTransientError("empty body")
        }
        when (code()) {
            401, 403, 404 -> throw SyncAuthError(code())
            else -> throw SyncTransientError("http ${code()}")
        }
    }

    private class SyncAuthError(val code: Int) : Exception("http $code")
    private class SyncTransientError(message: String) : Exception(message)

    private companion object {
        /** Per-array page size; matches the backend's default `limit`. */
        const val PAGE_LIMIT = 500
    }
}
