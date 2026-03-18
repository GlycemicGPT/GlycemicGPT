package com.glycemicgpt.mobile.wear

enum class WatchFaceVariant(
    val displayName: String,
    val description: String,
    val assetFilename: String,
    val defaultShowBasalOverlay: Boolean = true,
    val defaultShowBolusMarkers: Boolean = true,
    val defaultShowIoBOverlay: Boolean = true,
    val defaultShowModeBands: Boolean = true,
    val hasGraph: Boolean = true,
) {
    DIGITAL_FULL(
        displayName = "Full",
        description = "BG, IoB, graph, and time with all overlays",
        assetFilename = "glycemicgpt-watchface-digitalFull.apk",
    ),
    DIGITAL_CLINICAL(
        displayName = "Clinical",
        description = "Large BG and graph, high contrast, no branding",
        assetFilename = "glycemicgpt-watchface-digitalClinical.apk",
    ),
    DIGITAL_MINIMAL(
        displayName = "Minimal",
        description = "BG and large centered time, no graph",
        assetFilename = "glycemicgpt-watchface-digitalMinimal.apk",
        defaultShowBasalOverlay = false,
        defaultShowBolusMarkers = false,
        defaultShowIoBOverlay = false,
        defaultShowModeBands = false,
        hasGraph = false,
    ),
    ANALOG_MECHANICAL(
        displayName = "Mechanical",
        description = "Classic analog with dark navy dial and gold hands",
        assetFilename = "glycemicgpt-watchface-analogMechanical.apk",
        defaultShowBasalOverlay = false,
        defaultShowBolusMarkers = false,
        defaultShowIoBOverlay = false,
        defaultShowModeBands = false,
    ),
}
