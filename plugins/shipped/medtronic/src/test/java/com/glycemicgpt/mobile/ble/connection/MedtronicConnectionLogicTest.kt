/*
 * Pure-logic tests for the advertising-mode selection and the mode -> SAKE service-UUID mapping.
 * These pin the reconnect bit-flip contract (0xFE82 first pair / 0xFE81 reconnect) independently of
 * the Android BLE layer (medtronic-ble-reverse-engineering.md Sec. 3 / Sec. 7).
 */
package com.glycemicgpt.mobile.ble.connection

import com.glycemicgpt.mobile.ble.protocol.MedtronicProtocol
import org.junit.Assert.assertEquals
import org.junit.Test

class MedtronicConnectionLogicTest {

    @Test
    fun `unpaired connection uses first-pair mode`() {
        assertEquals(AdvertisingMode.FIRST_PAIR, advertisingModeFor(paired = false, forceFirstPair = false))
    }

    @Test
    fun `paired connection uses reconnect mode`() {
        assertEquals(AdvertisingMode.RECONNECT, advertisingModeFor(paired = true, forceFirstPair = false))
    }

    @Test
    fun `forcing first pair overrides an existing pairing`() {
        assertEquals(AdvertisingMode.FIRST_PAIR, advertisingModeFor(paired = true, forceFirstPair = true))
    }

    @Test
    fun `first-pair mode advertises the 0xFE82 SAKE service`() {
        assertEquals(MedtronicProtocol.SAKE_SERVICE_FIRST_PAIR_16, AdvertisingMode.FIRST_PAIR.serviceUuid16)
        assertEquals(0xFE82, AdvertisingMode.FIRST_PAIR.serviceUuid16)
    }

    @Test
    fun `reconnect mode advertises the 0xFE81 service bit-flip`() {
        assertEquals(MedtronicProtocol.SAKE_SERVICE_RECONNECT_16, AdvertisingMode.RECONNECT.serviceUuid16)
        assertEquals(0xFE81, AdvertisingMode.RECONNECT.serviceUuid16)
    }
}
