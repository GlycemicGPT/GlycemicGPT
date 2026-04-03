package com.glycemicgpt.mobile.data.repository

import com.glycemicgpt.mobile.data.local.dao.PumpDao
import com.glycemicgpt.mobile.data.local.dao.TimeInRangeCounts
import com.glycemicgpt.mobile.data.local.entity.BasalReadingEntity
import com.glycemicgpt.mobile.data.local.entity.BatteryReadingEntity
import com.glycemicgpt.mobile.data.local.entity.CgmReadingEntity
import com.glycemicgpt.mobile.data.local.entity.IoBReadingEntity
import com.glycemicgpt.mobile.data.local.entity.ReservoirReadingEntity
import com.glycemicgpt.mobile.domain.model.BasalReading
import com.glycemicgpt.mobile.domain.model.BatteryStatus
import com.glycemicgpt.mobile.domain.model.BolusEvent
import com.glycemicgpt.mobile.domain.model.CgmReading
import com.glycemicgpt.mobile.domain.model.CgmTrend
import com.glycemicgpt.mobile.domain.model.PumpActivityMode
import com.glycemicgpt.mobile.domain.model.IoBReading
import com.glycemicgpt.mobile.domain.model.ReservoirReading
import io.mockk.coEvery
import io.mockk.coVerify
import io.mockk.mockk
import io.mockk.slot
import kotlinx.coroutines.flow.flowOf
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Test
import java.time.Instant

class PumpDataRepositoryTest {

    private val pumpDao = mockk<PumpDao>(relaxed = true)
    private val repository = PumpDataRepository(pumpDao)

    // -- IoB ------------------------------------------------------------------

    @Test
    fun `saveIoB converts domain model to entity`() = runTest {
        val slot = slot<IoBReadingEntity>()
        coEvery { pumpDao.insertIoB(capture(slot)) } returns Unit

        val now = Instant.now()
        repository.saveIoB(IoBReading(iob = 2.5f, timestamp = now))

        assertEquals(2.5f, slot.captured.iob, 0.001f)
        assertEquals(now.toEpochMilli(), slot.captured.timestampMs)
    }

    @Test
    fun `observeLatestIoB maps entity to domain`() = runTest {
        val entity = IoBReadingEntity(id = 1, iob = 3.0f, timestampMs = 1000L)
        coEvery { pumpDao.observeLatestIoB() } returns flowOf(entity)

        val result = repository.observeLatestIoB().first()
        assertNotNull(result)
        assertEquals(3.0f, result!!.iob, 0.001f)
    }

    @Test
    fun `observeLatestIoB returns null when no data`() = runTest {
        coEvery { pumpDao.observeLatestIoB() } returns flowOf(null)

        val result = repository.observeLatestIoB().first()
        assertNull(result)
    }

    // -- Basal ----------------------------------------------------------------

    @Test
    fun `saveBasal stores activityMode as string`() = runTest {
        val slot = slot<BasalReadingEntity>()
        coEvery { pumpDao.insertBasal(capture(slot)) } returns Unit

        repository.saveBasal(
            BasalReading(
                rate = 1.2f,
                isAutomated = true,
                activityMode = PumpActivityMode.SLEEP,
                timestamp = Instant.now(),
            ),
        )

        assertEquals("SLEEP", slot.captured.activityMode)
        assertEquals(1.2f, slot.captured.rate, 0.001f)
    }

    @Test
    fun `observeLatestBasal maps mode string back to enum`() = runTest {
        val entity = BasalReadingEntity(
            id = 1,
            rate = 0.5f,
            isAutomated = false,
            activityMode = "EXERCISE",
            timestampMs = 1000L,
        )
        coEvery { pumpDao.observeLatestBasal() } returns flowOf(entity)

        val result = repository.observeLatestBasal().first()
        assertNotNull(result)
        assertEquals(PumpActivityMode.EXERCISE, result!!.activityMode)
    }

    @Test
    fun `observeLatestBasal handles unknown mode gracefully`() = runTest {
        val entity = BasalReadingEntity(
            id = 1,
            rate = 0.5f,
            isAutomated = false,
            activityMode = "UNKNOWN_MODE",
            timestampMs = 1000L,
        )
        coEvery { pumpDao.observeLatestBasal() } returns flowOf(entity)

        val result = repository.observeLatestBasal().first()
        assertNotNull(result)
        assertEquals(PumpActivityMode.NONE, result!!.activityMode)
    }

    @Test
    fun `observeLatestBasal maps legacy STANDARD mode to NONE`() = runTest {
        val entity = BasalReadingEntity(
            id = 1,
            rate = 0.5f,
            isAutomated = true,
            activityMode = "STANDARD",
            timestampMs = 1000L,
        )
        coEvery { pumpDao.observeLatestBasal() } returns flowOf(entity)

        val result = repository.observeLatestBasal().first()
        assertNotNull(result)
        assertEquals(PumpActivityMode.NONE, result!!.activityMode)
    }

    // -- Battery --------------------------------------------------------------

    @Test
    fun `saveBattery converts domain model to entity`() = runTest {
        val slot = slot<BatteryReadingEntity>()
        coEvery { pumpDao.insertBattery(capture(slot)) } returns Unit

        repository.saveBattery(
            BatteryStatus(percentage = 72, isCharging = true, timestamp = Instant.now()),
        )

        assertEquals(72, slot.captured.percentage)
        assertEquals(true, slot.captured.isCharging)
    }

    // -- Reservoir ------------------------------------------------------------

    @Test
    fun `saveReservoir converts domain model to entity`() = runTest {
        val slot = slot<ReservoirReadingEntity>()
        coEvery { pumpDao.insertReservoir(capture(slot)) } returns Unit

        repository.saveReservoir(
            ReservoirReading(unitsRemaining = 150f, timestamp = Instant.now()),
        )

        assertEquals(150f, slot.captured.unitsRemaining, 0.001f)
    }

    // -- Bolus ----------------------------------------------------------------

    @Test
    fun `saveBoluses skips empty list`() = runTest {
        repository.saveBoluses(emptyList())
        coVerify(exactly = 0) { pumpDao.insertBoluses(any()) }
    }

    @Test
    fun `saveBoluses converts domain models`() = runTest {
        val events = listOf(
            BolusEvent(
                units = 3.5f,
                isAutomated = true,
                isCorrection = false,
                timestamp = Instant.now(),
            ),
        )
        repository.saveBoluses(events)
        coVerify(exactly = 1) { pumpDao.insertBoluses(any()) }
    }

    @Test
    fun `getLatestBolusTimestamp returns null when no data`() = runTest {
        coEvery { pumpDao.getLatestBolusTimestamp() } returns null

        val result = repository.getLatestBolusTimestamp()
        assertNull(result)
    }

    @Test
    fun `getLatestBolusTimestamp converts millis to Instant`() = runTest {
        val ms = 1700000000000L
        coEvery { pumpDao.getLatestBolusTimestamp() } returns ms

        val result = repository.getLatestBolusTimestamp()
        assertNotNull(result)
        assertEquals(ms, result!!.toEpochMilli())
    }

    // -- CGM ------------------------------------------------------------------

    @Test
    fun `saveCgm converts domain model to entity`() = runTest {
        val slot = slot<CgmReadingEntity>()
        coEvery { pumpDao.insertCgm(capture(slot)) } returns Unit

        val now = Instant.now()
        repository.saveCgm(CgmReading(glucoseMgDl = 120, trendArrow = CgmTrend.FLAT, timestamp = now))

        assertEquals(120, slot.captured.glucoseMgDl)
        assertEquals("FLAT", slot.captured.trendArrow)
        assertEquals(now.toEpochMilli(), slot.captured.timestampMs)
    }

    @Test
    fun `observeLatestCgm maps entity to domain`() = runTest {
        val entity = CgmReadingEntity(id = 1, glucoseMgDl = 180, trendArrow = "SINGLE_UP", timestampMs = 1000L)
        coEvery { pumpDao.observeLatestCgm() } returns flowOf(entity)

        val result = repository.observeLatestCgm().first()
        assertNotNull(result)
        assertEquals(180, result!!.glucoseMgDl)
        assertEquals(CgmTrend.SINGLE_UP, result.trendArrow)
    }

    @Test
    fun `observeLatestCgm returns null when no data`() = runTest {
        coEvery { pumpDao.observeLatestCgm() } returns flowOf(null)

        val result = repository.observeLatestCgm().first()
        assertNull(result)
    }

    @Test
    fun `observeLatestCgm handles unknown trend gracefully`() = runTest {
        val entity = CgmReadingEntity(id = 1, glucoseMgDl = 95, trendArrow = "INVALID_TREND", timestampMs = 1000L)
        coEvery { pumpDao.observeLatestCgm() } returns flowOf(entity)

        val result = repository.observeLatestCgm().first()
        assertNotNull(result)
        assertEquals(CgmTrend.UNKNOWN, result!!.trendArrow)
    }

    // -- Time in Range --------------------------------------------------------

    @Test
    fun `observeTimeInRange maps counts to percentages`() = runTest {
        val counts = TimeInRangeCounts(total = 100, urgentLowCount = 2, lowCount = 8, inRangeCount = 70, highCount = 15, urgentHighCount = 5)
        coEvery { pumpDao.observeTimeInRangeCounts(any(), any(), any(), any(), any()) } returns flowOf(counts)

        val result = repository.observeTimeInRange(Instant.now(), 54, 70, 180, 250).first()
        assertEquals(2f, result.urgentLowPercent, 0.001f)
        assertEquals(8f, result.lowPercent, 0.001f)
        assertEquals(70f, result.inRangePercent, 0.001f)
        assertEquals(15f, result.highPercent, 0.001f)
        assertEquals(5f, result.urgentHighPercent, 0.001f)
        assertEquals(100, result.totalReadings)
    }

    @Test
    fun `observeTimeInRange returns zeros when no readings`() = runTest {
        val counts = TimeInRangeCounts(total = 0, urgentLowCount = 0, lowCount = 0, inRangeCount = 0, highCount = 0, urgentHighCount = 0)
        coEvery { pumpDao.observeTimeInRangeCounts(any(), any(), any(), any(), any()) } returns flowOf(counts)

        val result = repository.observeTimeInRange(Instant.now(), 54, 70, 180, 250).first()
        assertEquals(0f, result.urgentLowPercent, 0.001f)
        assertEquals(0f, result.lowPercent, 0.001f)
        assertEquals(0f, result.inRangePercent, 0.001f)
        assertEquals(0f, result.highPercent, 0.001f)
        assertEquals(0f, result.urgentHighPercent, 0.001f)
        assertEquals(0, result.totalReadings)
    }

    @Test
    fun `observeTimeInRange forwards threshold params to DAO`() = runTest {
        val counts = TimeInRangeCounts(total = 50, urgentLowCount = 1, lowCount = 4, inRangeCount = 40, highCount = 4, urgentHighCount = 1)
        val urgentLowSlot = slot<Int>()
        val lowSlot = slot<Int>()
        val highSlot = slot<Int>()
        val urgentHighSlot = slot<Int>()
        coEvery { pumpDao.observeTimeInRangeCounts(any(), capture(urgentLowSlot), capture(lowSlot), capture(highSlot), capture(urgentHighSlot)) } returns flowOf(counts)

        repository.observeTimeInRange(Instant.now(), 60, 90, 230, 330).first()

        assertEquals(60, urgentLowSlot.captured)
        assertEquals(90, lowSlot.captured)
        assertEquals(230, highSlot.captured)
        assertEquals(330, urgentHighSlot.captured)
    }

    // -- Cleanup --------------------------------------------------------------

    @Test
    fun `deleteOldReadings calls transactional deleteAllBefore`() = runTest {
        coEvery { pumpDao.deleteAllBefore(any()) } returns 15

        val total = repository.deleteOldReadings()
        assertEquals(15, total)
        coVerify(exactly = 1) { pumpDao.deleteAllBefore(any()) }
    }
}
