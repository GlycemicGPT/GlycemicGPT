package com.glycemicgpt.mobile.plugin.nightscout

import com.glycemicgpt.mobile.data.local.dao.PumpDao
import com.glycemicgpt.mobile.data.remote.GlycemicGptApi
import com.glycemicgpt.mobile.data.remote.dto.NightscoutConnectionDto
import com.glycemicgpt.mobile.data.remote.dto.NightscoutConnectionListDto
import com.glycemicgpt.mobile.data.remote.dto.NightscoutDataDto
import com.glycemicgpt.mobile.data.remote.dto.NightscoutGlucoseReadingDto
import com.glycemicgpt.mobile.data.remote.dto.NightscoutPumpEventDto
import io.mockk.coEvery
import io.mockk.coVerify
import io.mockk.mockk
import kotlinx.coroutines.test.runTest
import okhttp3.ResponseBody.Companion.toResponseBody
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import retrofit2.Response
import java.time.Instant

class NightscoutSyncEngineTest {

    private val api: GlycemicGptApi = mockk()
    private val dao: PumpDao = mockk(relaxed = true)
    private val backing = FakePluginSettingsStore()
    private val store = NightscoutSyncStore(backing)
    private val engine = NightscoutSyncEngine(api, dao, store)

    private val connId = "conn-1"

    @Test
    fun `disabled returns Disabled and makes no api calls`() = runTest {
        store.enabled = false
        val outcome = engine.syncOnce(nowMs = 1000L)
        assertEquals(SyncOutcome.Disabled, outcome)
        coVerify(exactly = 0) { api.listNightscoutConnections() }
    }

    @Test
    fun `no active connection returns NoConnection`() = runTest {
        store.enabled = true
        coEvery { api.listNightscoutConnections() } returns
            Response.success(NightscoutConnectionListDto(listOf(connection(connId, active = false))))

        val outcome = engine.syncOnce(nowMs = 1000L)

        assertEquals(SyncOutcome.NoConnection, outcome)
        assertEquals(NightscoutSyncStatus.NO_CONNECTION, store.state.value.status)
        coVerify(exactly = 0) { api.getNightscoutData(any(), any(), any()) }
    }

    @Test
    fun `a selected-but-inactive connection is not silently swapped for another`() = runTest {
        store.enabled = true
        backing.putString(NightscoutSyncStore.KEY_SELECTED_CONNECTION, "conn-gone")
        coEvery { api.listNightscoutConnections() } returns Response.success(
            NightscoutConnectionListDto(listOf(connection("conn-1"))),
        )

        assertEquals(SyncOutcome.NoConnection, engine.syncOnce(nowMs = 1L))
        coVerify(exactly = 0) { api.getNightscoutData(any(), any(), any()) }
    }

    @Test
    fun `single short page writes rows, advances cursor, and records completion`() = runTest {
        store.enabled = true
        coEvery { api.listNightscoutConnections() } returns
            Response.success(NightscoutConnectionListDto(listOf(connection(connId))))
        coEvery { api.getNightscoutData(connId, null, 500) } returns Response.success(
            data(
                limit = 500,
                glucose = listOf(glucose(120, T0), glucose(130, T1)),
                events = listOf(event("bolus", T1, 2.0f), event("basal", T0, 0.7f)),
            ),
        )

        val outcome = engine.syncOnce(nowMs = 9999L)

        assertTrue(outcome is SyncOutcome.Success)
        outcome as SyncOutcome.Success
        assertEquals(1, outcome.pages)
        assertEquals(2, outcome.cgm)
        assertEquals(1, outcome.bolus)
        assertEquals(1, outcome.basal)
        coVerify(exactly = 1) { dao.insertCgmBatch(any()) }
        coVerify(exactly = 1) { dao.insertBoluses(any()) }
        coVerify(exactly = 1) { dao.insertBasalBatch(any()) }
        // A short page is the end of data: it must not re-fetch the inclusive boundary forever.
        coVerify(exactly = 1) { api.getNightscoutData(connId, any(), any()) }
        assertEquals(Instant.parse(T1).toEpochMilli(), store.getCursor(connId))
        assertEquals(NightscoutSyncStatus.OK, store.state.value.status)
        assertEquals(9999L, store.state.value.lastSuccessAtMs)
    }

    @Test
    fun `a full events stream alongside a short glucose stream advances safely and terminates`() = runTest {
        // Regression for the asymmetric-truncation path: the backend pages each array independently,
        // so a short glucose array is fully drained even when events are still truncated. The cursor
        // must follow the lagging full stream (events) without skipping or looping.
        store.enabled = true
        coEvery { api.listNightscoutConnections() } returns
            Response.success(NightscoutConnectionListDto(listOf(connection(connId))))
        coEvery { api.getNightscoutData(connId, null, 500) } returns Response.success(
            data(
                limit = 2,
                glucose = listOf(glucose(120, T0)),
                events = listOf(event("bolus", T0, 1.0f), event("bolus", T1, 2.0f)),
            ),
        )
        coEvery { api.getNightscoutData(connId, Instant.parse(T1).toString(), 500) } returns
            Response.success(data(limit = 2, events = listOf(event("bolus", T2, 3.0f))))

        val outcome = engine.syncOnce(nowMs = 1L)

        assertTrue(outcome is SyncOutcome.Success)
        assertEquals(2, (outcome as SyncOutcome.Success).pages)
        assertEquals(Instant.parse(T2).toEpochMilli(), store.getCursor(connId))
    }

    @Test
    fun `a saturated boundary page is a retryable stall, not a false success`() = runTest {
        // A full page whose only row sits exactly on the cursor cannot advance an inclusive cursor.
        store.enabled = true
        val boundary = Instant.parse(T1).toEpochMilli()
        store.setCursor(connId, boundary)
        coEvery { api.listNightscoutConnections() } returns
            Response.success(NightscoutConnectionListDto(listOf(connection(connId))))
        coEvery { api.getNightscoutData(connId, Instant.parse(T1).toString(), 500) } returns
            Response.success(data(limit = 1, glucose = listOf(glucose(120, T1))))

        val outcome = engine.syncOnce(nowMs = 1L)

        assertEquals(SyncOutcome.Transient, outcome)
        assertEquals(NightscoutSyncStatus.ERROR, store.state.value.status)
        // Cursor is preserved (progress not lost), and no clean success was recorded.
        assertEquals(boundary, store.getCursor(connId))
        assertEquals(null, store.state.value.lastSuccessAtMs)
    }

    @Test
    fun `cursors are tracked per connection`() = runTest {
        // A cursor for one connection must not leak into a different connection's backfill.
        store.enabled = true
        store.setCursor("conn-1", Instant.parse(T2).toEpochMilli())
        backing.putString(NightscoutSyncStore.KEY_SELECTED_CONNECTION, "conn-2")
        coEvery { api.listNightscoutConnections() } returns Response.success(
            NightscoutConnectionListDto(listOf(connection("conn-1"), connection("conn-2"))),
        )
        coEvery { api.getNightscoutData("conn-2", null, 500) } returns
            Response.success(data(limit = 500))

        engine.syncOnce(nowMs = 1L)

        // conn-2 starts a fresh backfill (since=null), unaffected by conn-1's cursor.
        coVerify(exactly = 1) { api.getNightscoutData("conn-2", null, 500) }
    }

    @Test
    fun `pages until a short page using an inclusive since cursor`() = runTest {
        store.enabled = true
        coEvery { api.listNightscoutConnections() } returns
            Response.success(NightscoutConnectionListDto(listOf(connection(connId))))
        // First page fills the (tiny) glucose limit -> more to fetch; second page is short -> stop.
        coEvery { api.getNightscoutData(connId, null, 500) } returns Response.success(
            data(limit = 2, glucose = listOf(glucose(100, T0), glucose(110, T1))),
        )
        // Second page is fetched with the inclusive cursor set to the first page's max timestamp.
        coEvery { api.getNightscoutData(connId, Instant.parse(T1).toString(), 500) } returns
            Response.success(data(limit = 2, glucose = listOf(glucose(120, T2))))

        val outcome = engine.syncOnce(nowMs = 1L)

        assertTrue(outcome is SyncOutcome.Success)
        assertEquals(2, (outcome as SyncOutcome.Success).pages)
        coVerify(exactly = 1) { api.getNightscoutData(connId, null, 500) }
        coVerify(exactly = 1) { api.getNightscoutData(connId, Instant.parse(T1).toString(), 500) }
        assertEquals(Instant.parse(T2).toEpochMilli(), store.getCursor(connId))
    }

    @Test
    fun `resolves the user-selected connection over the first active one`() = runTest {
        store.enabled = true
        backing.putString(NightscoutSyncStore.KEY_SELECTED_CONNECTION, "conn-2")
        coEvery { api.listNightscoutConnections() } returns Response.success(
            NightscoutConnectionListDto(
                listOf(connection("conn-1"), connection("conn-2")),
            ),
        )
        coEvery { api.getNightscoutData("conn-2", null, 500) } returns
            Response.success(data(limit = 500))

        val outcome = engine.syncOnce(nowMs = 1L)

        assertTrue(outcome is SyncOutcome.Success)
        coVerify(exactly = 1) { api.getNightscoutData("conn-2", null, 500) }
        coVerify(exactly = 0) { api.getNightscoutData("conn-1", any(), any()) }
    }

    @Test
    fun `401 from the data endpoint returns AuthError without retrying`() = runTest {
        store.enabled = true
        coEvery { api.listNightscoutConnections() } returns
            Response.success(NightscoutConnectionListDto(listOf(connection(connId))))
        coEvery { api.getNightscoutData(connId, null, 500) } returns
            Response.error(401, "unauthorized".toResponseBody(null))

        assertEquals(SyncOutcome.AuthError, engine.syncOnce(nowMs = 1L))
        assertEquals(NightscoutSyncStatus.AUTH_ERROR, store.state.value.status)
    }

    @Test
    fun `5xx returns Transient so the worker retries`() = runTest {
        store.enabled = true
        coEvery { api.listNightscoutConnections() } returns
            Response.error(503, "down".toResponseBody(null))

        assertEquals(SyncOutcome.Transient, engine.syncOnce(nowMs = 1L))
        assertEquals(NightscoutSyncStatus.ERROR, store.state.value.status)
    }

    // -- Fixtures -------------------------------------------------------------

    private fun connection(id: String, active: Boolean = true) =
        NightscoutConnectionDto(id = id, name = "NS $id", isActive = active)

    private fun data(
        limit: Int,
        glucose: List<NightscoutGlucoseReadingDto> = emptyList(),
        events: List<NightscoutPumpEventDto> = emptyList(),
    ) = NightscoutDataDto(
        connectionId = connId,
        fetchedAt = Instant.parse(T0),
        effectiveLimitPerArray = limit,
        glucoseReadings = glucose,
        pumpEvents = events,
    )

    private fun glucose(value: Int, ts: String) = NightscoutGlucoseReadingDto(
        nsId = "g-$ts",
        readingTimestamp = Instant.parse(ts),
        value = value,
        trend = "Flat",
        trendRate = 0f,
        source = "nightscout:$connId",
    )

    private fun event(type: String, ts: String, units: Float?) = NightscoutPumpEventDto(
        nsId = "e-$type-$ts",
        eventTimestamp = Instant.parse(ts),
        eventType = type,
        units = units,
        durationMinutes = null,
        isAutomated = false,
        source = "nightscout:$connId",
    )

    private companion object {
        const val T0 = "2026-03-01T12:00:00Z"
        const val T1 = "2026-03-01T12:05:00Z"
        const val T2 = "2026-03-01T12:10:00Z"
    }
}
