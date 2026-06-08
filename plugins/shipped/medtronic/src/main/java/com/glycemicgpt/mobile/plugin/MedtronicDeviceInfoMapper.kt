/*
 * GlycemicGPT code (GPL-3.0). Adapts the Medtronic-native device-info shape onto the shared,
 * Tandem-derived capability models.
 */
package com.glycemicgpt.mobile.plugin

import com.glycemicgpt.mobile.ble.read.MedtronicDeviceInfo
import com.glycemicgpt.mobile.domain.model.PumpHardwareInfo
import com.glycemicgpt.mobile.domain.model.PumpSettings

/**
 * Maps the alphanumeric [MedtronicDeviceInfo] onto the shared [PumpSettings], which is string-typed
 * and a clean fit: firmware/serial/model carry across verbatim.
 */
internal fun MedtronicDeviceInfo.toPumpSettings(): PumpSettings =
    PumpSettings(
        firmwareVersion = firmwareRevision,
        serialNumber = serialNumber,
        modelNumber = modelNumber,
    )

/**
 * Maps [MedtronicDeviceInfo] onto the shared [PumpHardwareInfo].
 *
 * [PumpHardwareInfo] is Tandem-shaped: its identity fields ([PumpHardwareInfo.serialNumber],
 * [PumpHardwareInfo.modelNumber]) are `Long`, whereas Medtronic's are alphanumeric (model "MMT-1880",
 * serial "NG..."). The faithful, lossless representation of pump identity is [toPumpSettings] (and the
 * native [MedtronicDeviceInfo]); this `Long`-keyed view is a best-effort adaptation for the shared
 * surface:
 *  - the numeric run is extracted from each identifier ([numericId]) for the `Long` slots, so a
 *    "MMT-1880" model still yields a stable, comparable `1880`;
 *  - the firmware/hardware revision strings map onto the revision slots;
 *  - [PumpHardwareInfo.pumpFeatures] is left empty: it is a feature-flag map (uploaded verbatim to the
 *    backend as `pump_features`), so it must not be repurposed to smuggle identity strings -- the DIS
 *    exposes no genuine feature flags, and the identity is already carried losslessly by
 *    [toPumpSettings];
 *  - fields the Device Information Service does not expose (part number, PCBA serial, config bit
 *    masks, ARM/MSP split) are left `0`/empty rather than invented.
 *
 * `TODO(48.D)`: prefer surfacing [MedtronicDeviceInfo] / [toPumpSettings] directly to the dashboard
 * once the UI consumes pump identity, rather than round-tripping through this lossy `Long`-keyed view.
 */
internal fun MedtronicDeviceInfo.toPumpHardwareInfo(): PumpHardwareInfo =
    PumpHardwareInfo(
        serialNumber = numericId(serialNumber),
        modelNumber = numericId(modelNumber),
        partNumber = 0,
        pumpRev = firmwareRevision,
        armSwVer = numericId(softwareRevision),
        mspSwVer = 0,
        configABits = 0,
        configBBits = 0,
        pcbaSn = 0,
        pcbaRev = hardwareRevision,
        pumpFeatures = emptyMap(),
    )

/**
 * The numeric value of the longest run of digits in [raw] (e.g. "MMT-1880" -> 1880, "NG1234567H" ->
 * 1234567), or `0` when there are no digits. Longs are bounded; a pathologically long digit run is
 * truncated to the trailing 18 digits to stay within [Long] range without overflowing.
 */
private fun numericId(raw: String): Long {
    val digits = Regex("\\d+").findAll(raw).maxByOrNull { it.value.length }?.value ?: return 0L
    return digits.takeLast(MAX_LONG_DIGITS).toLongOrNull() ?: 0L
}

/** 18 digits always fit in a signed 64-bit Long (max is 19 digits); avoids a parse overflow. */
private const val MAX_LONG_DIGITS = 18
