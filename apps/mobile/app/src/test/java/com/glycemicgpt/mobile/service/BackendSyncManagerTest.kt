package com.glycemicgpt.mobile.service

import com.glycemicgpt.mobile.data.local.AppSettingsStore
import com.glycemicgpt.mobile.data.local.AuthTokenStore
import com.glycemicgpt.mobile.data.local.dao.RawHistoryLogDao
import com.glycemicgpt.mobile.data.local.dao.SyncDao
import com.glycemicgpt.mobile.data.local.entity.SyncQueueEntity
import com.glycemicgpt.mobile.data.remote.GlycemicGptApi
import com.glycemicgpt.mobile.data.remote.InstantAdapter
import com.glycemicgpt.mobile.data.remote.dto.PumpPushResponse
import com.squareup.moshi.Moshi
import io.mockk.coEvery
import io.mockk.coVerify
import io.mockk.every
import io.mockk.mockk
import kotlinx.coroutines.test.runTest
import okhttp3.ResponseBody.Companion.toResponseBody
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test
import retrofit2.Response

class BackendSyncManagerTest {

    private val syncDao = mockk<SyncDao>(relaxed = true)
    private val rawHistoryLogDao = mockk<RawHistoryLogDao>(relaxed = true)
    private val api = mockk<GlycemicGptApi>()
    private val authTokenStore = mockk<AuthTokenStore>()
    private val appSettingsStore = mockk<AppSettingsStore> {
        every { backendSyncEnabled } returns true
        every { dataRetentionDays } returns 7
    }
    private val moshi = Moshi.Builder().add(InstantAdapter()).build()

    private val manager = BackendSyncManager(syncDao, rawHistoryLogDao, api, authTokenStore, appSettingsStore, moshi)

    private fun sampleEntity(id: Long = 1L): SyncQueueEntity =
        SyncQueueEntity(
            id = id,
            eventType = "basal",
            eventTimestampMs = System.currentTimeMillis(),
            payload = """{"event_type":"basal","event_timestamp":"2025-01-01T00:00:00Z","units":0.5,"is_automated":true}""",
        )

    @Test
    fun `processQueue sends batch to API and deletes on success`() = runTest {
        every { authTokenStore.hasActiveSession() } returns true
        coEvery { syncDao.getPendingBatch(any(), any(), any()) } returns listOf(sampleEntity())
        coEvery { api.pushPumpEvents(any()) } returns Response.success(
            PumpPushResponse(accepted = 1, duplicates = 0),
        )

        manager.processQueue()

        coVerify { syncDao.deleteSent(listOf(1L)) }
        assertNull(manager.syncStatus.value.lastError)
    }

    @Test
    fun `processQueue skips when not logged in`() = runTest {
        every { authTokenStore.hasActiveSession() } returns false

        manager.processQueue()

        coVerify(exactly = 0) { syncDao.getPendingBatch(any(), any(), any()) }
    }

    @Test
    fun `processQueue skips when backend sync disabled`() = runTest {
        every { appSettingsStore.backendSyncEnabled } returns false

        manager.processQueue()

        coVerify(exactly = 0) { authTokenStore.hasActiveSession() }
        coVerify(exactly = 0) { syncDao.getPendingBatch(any(), any(), any()) }
    }

    @Test
    fun `processQueue marks failed on network error`() = runTest {
        every { authTokenStore.hasActiveSession() } returns true
        coEvery { syncDao.getPendingBatch(any(), any(), any()) } returns listOf(sampleEntity())
        coEvery { api.pushPumpEvents(any()) } throws java.io.IOException("No connection")

        manager.processQueue()

        coVerify { syncDao.markFailed(listOf(1L), "No connection", any()) }
        assertEquals("No connection", manager.syncStatus.value.lastError)
    }

    @Test
    fun `processQueue marks failed on HTTP error`() = runTest {
        every { authTokenStore.hasActiveSession() } returns true
        coEvery { syncDao.getPendingBatch(any(), any(), any()) } returns listOf(sampleEntity())
        coEvery { api.pushPumpEvents(any()) } returns Response.error(
            500,
            "Internal Server Error".toResponseBody(),
        )

        manager.processQueue()

        coVerify { syncDao.markFailed(listOf(1L), "HTTP 500", any()) }
    }

    @Test
    fun `processQueue marks unparseable items as failed separately`() = runTest {
        every { authTokenStore.hasActiveSession() } returns true
        val badEntity = SyncQueueEntity(
            id = 2L,
            eventType = "basal",
            eventTimestampMs = System.currentTimeMillis(),
            payload = "not valid json",
        )
        coEvery { syncDao.getPendingBatch(any(), any(), any()) } returns listOf(
            sampleEntity(1L),
            badEntity,
        )
        coEvery { api.pushPumpEvents(any()) } returns Response.success(
            PumpPushResponse(accepted = 1, duplicates = 0),
        )

        manager.processQueue()

        // Bad entity marked failed with parse error
        coVerify { syncDao.markFailed(listOf(2L), "JSON parse error", any()) }
        // Good entity deleted after successful push
        coVerify { syncDao.deleteSent(listOf(1L)) }
    }
}
