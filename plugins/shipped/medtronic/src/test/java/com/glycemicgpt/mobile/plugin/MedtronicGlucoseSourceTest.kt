/*
 * AC1: MedtronicGlucoseSource forwards to the read gateway and surfaces the Result verbatim.
 */
package com.glycemicgpt.mobile.plugin

import com.glycemicgpt.mobile.ble.read.MedtronicReadGateway
import com.glycemicgpt.mobile.domain.model.CgmReading
import com.glycemicgpt.mobile.domain.model.CgmTrend
import io.mockk.coEvery
import io.mockk.coVerify
import io.mockk.mockk
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.Instant

class MedtronicGlucoseSourceTest {

    private val gateway: MedtronicReadGateway = mockk(relaxed = true)
    private val source = MedtronicGlucoseSource(gateway)

    private val reading = CgmReading(
        glucoseMgDl = 142,
        trendArrow = CgmTrend.FLAT,
        timestamp = Instant.ofEpochSecond(1_700_000_000),
    )

    @Test
    fun `getCurrentReading delegates to the gateway`() = runTest {
        coEvery { gateway.getCgmReading() } returns Result.success(reading)

        val result = source.getCurrentReading()

        assertTrue(result.isSuccess)
        assertEquals(reading, result.getOrThrow())
        coVerify { gateway.getCgmReading() }
    }

    @Test
    fun `getCurrentReading surfaces a failure verbatim`() = runTest {
        val failure = IllegalStateException("boom")
        coEvery { gateway.getCgmReading() } returns Result.failure(failure)

        val result = source.getCurrentReading()

        assertTrue(result.isFailure)
        assertEquals(failure, result.exceptionOrNull())
    }

    @Test
    fun `observeReadings emits each successful poll`() = runTest {
        coEvery { gateway.getCgmReading() } returns Result.success(reading)

        // first() cancels collection after one emission, ending the polling loop.
        assertEquals(reading, source.observeReadings().first())
    }

    @Test
    fun `observeReadings skips a failed poll and emits the next success`() = runTest {
        val later = reading.copy(glucoseMgDl = 156)
        // First poll fails (no emission), the next succeeds -> only the success reaches the collector.
        coEvery { gateway.getCgmReading() } returnsMany listOf(
            Result.failure(IllegalStateException("not connected")),
            Result.success(later),
        )

        assertEquals(later, source.observeReadings().first())
    }
}
