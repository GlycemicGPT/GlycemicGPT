package com.glycemicgpt.mobile.plugin

import com.glycemicgpt.mobile.domain.model.BasalReading
import com.glycemicgpt.mobile.domain.model.ControlIqMode
import com.glycemicgpt.mobile.domain.model.IoBReading
import com.glycemicgpt.mobile.ble.connection.TandemBleDriver
import io.mockk.coEvery
import io.mockk.coVerify
import io.mockk.mockk
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.Instant

class TandemInsulinSourceTest {

    private val bleDriver: TandemBleDriver = mockk(relaxed = true)
    private val insulinSource = TandemInsulinSource(bleDriver)

    @Test
    fun `getIoB delegates to bleDriver`() = runTest {
        val expected = IoBReading(iob = 3.2f, timestamp = Instant.now())
        coEvery { bleDriver.getIoB() } returns Result.success(expected)

        val result = insulinSource.getIoB()

        assertTrue(result.isSuccess)
        assertEquals(expected, result.getOrThrow())
        coVerify { bleDriver.getIoB() }
    }

    @Test
    fun `getBasalRate delegates to bleDriver`() = runTest {
        val expected = BasalReading(
            rate = 0.8f,
            isAutomated = true,
            controlIqMode = ControlIqMode.STANDARD,
            timestamp = Instant.now(),
        )
        coEvery { bleDriver.getBasalRate() } returns Result.success(expected)

        val result = insulinSource.getBasalRate()

        assertTrue(result.isSuccess)
        assertEquals(expected, result.getOrThrow())
        coVerify { bleDriver.getBasalRate() }
    }
}
