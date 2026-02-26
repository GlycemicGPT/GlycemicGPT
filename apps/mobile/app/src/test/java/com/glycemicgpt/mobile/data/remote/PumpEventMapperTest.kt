package com.glycemicgpt.mobile.data.remote

import com.glycemicgpt.mobile.domain.model.BasalReading
import com.glycemicgpt.mobile.domain.model.BatteryStatus
import com.glycemicgpt.mobile.domain.model.BolusEvent
import com.glycemicgpt.mobile.domain.model.ControlIqMode
import com.glycemicgpt.mobile.domain.model.IoBReading
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Test
import java.time.Instant

class PumpEventMapperTest {

    private val now = Instant.now()

    @Test
    fun `fromIoB maps to bg_reading event with iob`() {
        val dto = PumpEventMapper.fromIoB(IoBReading(iob = 2.5f, timestamp = now))
        assertEquals("bg_reading", dto.eventType)
        assertEquals(now, dto.eventTimestamp)
        assertEquals(2.5f, dto.iobAtEvent)
        assertNull(dto.units)
    }

    @Test
    fun `fromBasal maps rate and control_iq_mode`() {
        val dto = PumpEventMapper.fromBasal(
            BasalReading(
                rate = 0.8f,
                isAutomated = true,
                controlIqMode = ControlIqMode.SLEEP,
                timestamp = now,
            ),
        )
        assertEquals("basal", dto.eventType)
        assertEquals(0.8f, dto.units)
        assertEquals(true, dto.isAutomated)
        assertEquals("sleep", dto.controlIqMode)
    }

    @Test
    fun `fromBolus maps manual bolus`() {
        val dto = PumpEventMapper.fromBolus(
            BolusEvent(units = 3.0f, isAutomated = false, isCorrection = false, timestamp = now),
        )
        assertEquals("bolus", dto.eventType)
        assertEquals(3.0f, dto.units)
        assertEquals(false, dto.isAutomated)
    }

    @Test
    fun `fromBolus maps correction bolus`() {
        val dto = PumpEventMapper.fromBolus(
            BolusEvent(units = 1.2f, isAutomated = true, isCorrection = true, timestamp = now),
        )
        assertEquals("correction", dto.eventType)
        assertEquals(1.2f, dto.units)
        assertEquals(true, dto.isAutomated)
    }

    @Test
    fun `fromBattery sets isAutomated false regardless of charging state`() {
        val charging = PumpEventMapper.fromBattery(
            BatteryStatus(percentage = 85, isCharging = true, timestamp = now),
        )
        assertEquals("battery", charging.eventType)
        assertEquals(85f, charging.units)
        assertFalse(charging.isAutomated ?: true)

        val notCharging = PumpEventMapper.fromBattery(
            BatteryStatus(percentage = 50, isCharging = false, timestamp = now),
        )
        assertFalse(notCharging.isAutomated ?: true)
    }
}
