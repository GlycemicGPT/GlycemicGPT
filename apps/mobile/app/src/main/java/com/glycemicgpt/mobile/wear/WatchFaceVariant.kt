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
        displayName = "Digital",
        description = "BG, IoB, graph, and time with all overlays",
        assetFilename = "glycemicgpt-watchface-digitalFull.apk",
    ),
    ANALOG_MECHANICAL(
        displayName = "Analog",
        description = "Classic analog with deep navy dial and silver hands",
        assetFilename = "glycemicgpt-watchface-analogMechanical.apk",
        defaultShowBasalOverlay = false,
        defaultShowBolusMarkers = false,
        defaultShowIoBOverlay = false,
        defaultShowModeBands = false,
    ),
}
