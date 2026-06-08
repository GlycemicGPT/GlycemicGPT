package com.glycemicgpt.mobile.domain.plugin

/**
 * How the user pairs a [DevicePlugin]'s hardware, reflecting the BLE topology the plugin uses.
 *
 * The two styles drive fundamentally different pairing UI:
 *  - [CENTRAL_SCAN]: the phone is the BLE central. It scans, shows a list of nearby devices, and the
 *    user taps one (e.g. Tandem). There is a device list to populate.
 *  - [ADVERTISE_AND_WAIT]: the phone is the BLE peripheral. It advertises and the device connects to
 *    it as central (e.g. Medtronic MiniMed 700-series). There is no scan and no device list -- the
 *    user triggers pairing from the device's own menu and selects the phone.
 */
enum class PairingStyle {
    CENTRAL_SCAN,
    ADVERTISE_AND_WAIT,
}

/**
 * Static description of how a [DevicePlugin] pairs, used to drive the pairing screen off the active
 * plugin rather than hard-coding a single vendor's flow.
 *
 * @param style the BLE pairing topology -- see [PairingStyle].
 * @param advertisedName for [PairingStyle.ADVERTISE_AND_WAIT], the BLE name the phone advertises so
 *   the user can recognise and select it from the device's pairing menu; `null` for central-scan
 *   plugins, which have no advertised identity of their own.
 */
data class PairingProfile(
    val style: PairingStyle = PairingStyle.CENTRAL_SCAN,
    val advertisedName: String? = null,
)
