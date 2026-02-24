package com.glycemicgpt.mobile.plugin

import com.glycemicgpt.mobile.domain.model.CgmReading
import com.glycemicgpt.mobile.domain.model.CgmTrend
import com.glycemicgpt.mobile.ble.connection.TandemBleDriver
import io.mockk.coEvery
import io.mockk.coVerify
import io.mockk.mockk
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.Instant

class TandemGlucoseSourceTest {

    private val bleDriver: TandemBleDriver = mockk(relaxed = true)
    private val glucoseSource = TandemGlucoseSource(bleDriver)

    @Test
    fun `getCurrentReading delegates to bleDriver`() = runTest {
        val expected = CgmReading(
            glucoseMgDl = 145,
            trendArrow = CgmTrend.FORTY_FIVE_UP,
            timestamp = Instant.now(),
        )
        coEvery { bleDriver.getCgmStatus() } returns Result.success(expected)

        val result = glucoseSource.getCurrentReading()

        assertTrue(result.isSuccess)
        assertEquals(expected, result.getOrThrow())
        coVerify { bleDriver.getCgmStatus() }
    }
}
