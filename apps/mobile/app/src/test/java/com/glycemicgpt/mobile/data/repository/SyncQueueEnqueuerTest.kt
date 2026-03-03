package com.glycemicgpt.mobile.data.repository

import com.glycemicgpt.mobile.data.local.dao.SyncDao
import com.glycemicgpt.mobile.data.local.entity.SyncQueueEntity
import com.glycemicgpt.mobile.data.remote.InstantAdapter
import com.glycemicgpt.mobile.domain.model.BasalReading
import com.glycemicgpt.mobile.domain.model.BolusEvent
import com.glycemicgpt.mobile.domain.model.PumpActivityMode
import com.glycemicgpt.mobile.domain.model.IoBReading
import com.squareup.moshi.Moshi
import io.mockk.coEvery
import io.mockk.coVerify
import io.mockk.mockk
import io.mockk.slot
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.Instant

class SyncQueueEnqueuerTest {

    private val syncDao = mockk<SyncDao>(relaxed = true)
    private val moshi = Moshi.Builder().add(InstantAdapter()).build()
    private val enqueuer = SyncQueueEnqueuer(syncDao, moshi)

    @Test
    fun `enqueueIoB creates entity with bg_reading type`() = runTest {
        val slot = slot<SyncQueueEntity>()
        coEvery { syncDao.enqueue(capture(slot)) } returns Unit

        val now = Instant.now()
        enqueuer.enqueueIoB(IoBReading(iob = 2.5f, timestamp = now))

        assertEquals("bg_reading", slot.captured.eventType)
        assertEquals(now.toEpochMilli(), slot.captured.eventTimestampMs)
        assertTrue(slot.captured.payload.contains("2.5"))
        assertEquals(SyncQueueEntity.STATUS_PENDING, slot.captured.status)
    }

    @Test
    fun `enqueueBasal creates entity with basal type`() = runTest {
        val slot = slot<SyncQueueEntity>()
        coEvery { syncDao.enqueue(capture(slot)) } returns Unit

        enqueuer.enqueueBasal(
            BasalReading(
                rate = 1.2f,
                isAutomated = true,
                activityMode = PumpActivityMode.EXERCISE,
                timestamp = Instant.now(),
            ),
        )

        assertEquals("basal", slot.captured.eventType)
        assertTrue(slot.captured.payload.contains("exercise"))
    }

    @Test
    fun `enqueueBoluses enqueues one entity per event`() = runTest {
        val events = listOf(
            BolusEvent(units = 3.0f, isAutomated = false, isCorrection = false, timestamp = Instant.now()),
            BolusEvent(units = 1.5f, isAutomated = true, isCorrection = true, timestamp = Instant.now()),
        )

        enqueuer.enqueueBoluses(events)

        coVerify(exactly = 2) { syncDao.enqueue(any()) }
    }
}
