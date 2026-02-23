package com.glycemicgpt.mobile.domain.pump

import com.glycemicgpt.mobile.domain.model.DiscoveredPump
import kotlinx.coroutines.flow.Flow

/**
 * Pump discovery via wireless scanning.
 *
 * Decouples scanning from transport-specific implementation details,
 * allowing consumers to depend on this interface rather than
 * concrete scanner classes.
 */
interface PumpScanner {

    /**
     * Start scanning and emit discovered pumps.
     * Scanning continues until the flow collector cancels.
     */
    fun scan(): Flow<DiscoveredPump>
}
