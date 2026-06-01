/*
 * Battery reader for the Medtronic MiniMed 700-series read-only driver.
 *
 * GlycemicGPT code (GPL-3.0). The battery-level read and its 0..100 sanity check are ported from
 * OpenMinimed PythonPumpConnector `device_info.py` (DeviceInfo.read_battery_level / _batt_cb),
 * GPL-3.0, used with the author's permission. Copyright (C) OpenMinimed contributors: palmarci
 * (Pal Marci), drfubar, Morten Fyhn Amundsen, Stenium; original medtronic-bt-decrypt PoC by
 * @planiitis. GlycemicGPT is itself GPL-3.0.
 *
 * Battery Service (0x180F) Battery Level (0x2A19) is a standard Bluetooth SIG percentage byte and is
 * NOT SAKE-encrypted -- a plain GATT read.
 */
package com.glycemicgpt.mobile.ble.read

import com.glycemicgpt.mobile.ble.protocol.MedtronicProtocol
import com.glycemicgpt.mobile.domain.model.BatteryStatus
import java.time.Instant

/** Reads the pump's battery level into a [BatteryStatus]. */
class BatteryReader(
    private val link: MedtronicGattLink,
    private val now: () -> Instant = Instant::now,
) {

    /**
     * Read the Battery Level characteristic (one percentage byte). A value outside the valid
     * 1..100 range is **rejected** rather than clamped. 0 is rejected as a no/empty reading, matching
     * upstream `device_info.py` (`0 < batt < 101`): a pump reporting a true 0% over an active link
     * would already be powered off, so 0x00 is spurious. [BatteryStatus.isCharging] is always
     * `false`: the 700-series runs on a replaceable battery and exposes no charging state over the
     * standard Battery Service.
     */
    fun read(): BatteryStatus {
        val raw = link.read(MedtronicProtocol.BATTERY_LEVEL_UUID)
        if (raw.isEmpty()) {
            throw MedtronicReadException("Battery Level characteristic is empty")
        }
        val percentage = raw[0].toInt() and 0xFF
        if (percentage !in MIN_PERCENTAGE..MAX_PERCENTAGE) {
            throw MedtronicReadException(
                "Battery percentage $percentage outside $MIN_PERCENTAGE..$MAX_PERCENTAGE",
            )
        }
        return BatteryStatus(percentage = percentage, isCharging = false, timestamp = now())
    }

    private companion object {
        const val MIN_PERCENTAGE = 1
        const val MAX_PERCENTAGE = 100
    }
}
