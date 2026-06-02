/*
 * GlycemicGPT code (GPL-3.0). Read-only glucose capability for the Medtronic 700-series driver.
 */
package com.glycemicgpt.mobile.plugin

import com.glycemicgpt.mobile.ble.read.MedtronicReadGateway
import com.glycemicgpt.mobile.domain.model.CgmReading
import com.glycemicgpt.mobile.domain.plugin.capabilities.GlucoseSource
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.flow

/**
 * Exposes the pump's sensor glucose as the platform [GlucoseSource], delegating to
 * [MedtronicReadGateway]. Read-only: no method writes to the pump.
 */
class MedtronicGlucoseSource(
    private val gateway: MedtronicReadGateway,
) : GlucoseSource {

    /**
     * Poll the latest reading on a fixed interval (mirrors Tandem; the real-time stream is polling, not
     * pump-pushed). Cadence ownership moves to the polling orchestrator in Milestone D.
     */
    override fun observeReadings(): Flow<CgmReading> = flow {
        while (true) {
            gateway.getCgmReading().onSuccess { emit(it) }
            delay(POLL_INTERVAL_MS)
        }
    }

    override suspend fun getCurrentReading(): Result<CgmReading> =
        gateway.getCgmReading()

    private companion object {
        const val POLL_INTERVAL_MS = 60_000L
    }
}
