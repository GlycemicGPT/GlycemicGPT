package com.glycemicgpt.mobile.data.remote

import com.glycemicgpt.mobile.data.remote.dto.PumpEventDto
import com.glycemicgpt.mobile.domain.model.BasalReading
import com.glycemicgpt.mobile.domain.model.BatteryStatus
import com.glycemicgpt.mobile.domain.model.BolusEvent
import com.glycemicgpt.mobile.domain.model.IoBReading
import com.glycemicgpt.mobile.domain.model.ReservoirReading

/**
 * Maps domain models to [PumpEventDto] for backend sync.
 */
object PumpEventMapper {

    fun fromIoB(reading: IoBReading): PumpEventDto =
        PumpEventDto(
            eventType = "bg_reading",
            eventTimestamp = reading.timestamp,
            iobAtEvent = reading.iob,
        )

    fun fromBasal(reading: BasalReading): PumpEventDto =
        PumpEventDto(
            eventType = "basal",
            eventTimestamp = reading.timestamp,
            units = reading.rate,
            isAutomated = reading.isAutomated,
            controlIqMode = reading.controlIqMode.name.lowercase(),
        )

    fun fromBolus(event: BolusEvent): PumpEventDto {
        val type = if (event.isCorrection) "correction" else "bolus"
        return PumpEventDto(
            eventType = type,
            eventTimestamp = event.timestamp,
            units = event.units,
            isAutomated = event.isAutomated,
        )
    }

    fun fromBattery(status: BatteryStatus): PumpEventDto =
        PumpEventDto(
            eventType = "battery",
            eventTimestamp = status.timestamp,
            units = status.percentage.toFloat(),
            isAutomated = false,
        )

    fun fromReservoir(reading: ReservoirReading): PumpEventDto =
        PumpEventDto(
            eventType = "reservoir",
            eventTimestamp = reading.timestamp,
            units = reading.unitsRemaining,
        )
}
