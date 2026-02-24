package com.glycemicgpt.mobile.plugin

import com.glycemicgpt.mobile.domain.model.CgmReading
import com.glycemicgpt.mobile.domain.plugin.capabilities.GlucoseSource
import com.glycemicgpt.mobile.ble.connection.TandemBleDriver
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.flow
import kotlinx.coroutines.delay

class TandemGlucoseSource(
    private val bleDriver: TandemBleDriver,
) : GlucoseSource {
    override fun observeReadings(): Flow<CgmReading> = flow {
        // Emit current reading periodically; real-time stream uses polling
        while (true) {
            bleDriver.getCgmStatus().onSuccess { emit(it) }
            delay(POLL_INTERVAL_MS)
        }
    }

    override suspend fun getCurrentReading(): Result<CgmReading> =
        bleDriver.getCgmStatus()

    companion object {
        private const val POLL_INTERVAL_MS = 60_000L
    }
}
