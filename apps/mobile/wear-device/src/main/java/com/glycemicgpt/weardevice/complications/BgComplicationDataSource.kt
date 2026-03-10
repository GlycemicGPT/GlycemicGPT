package com.glycemicgpt.weardevice.complications

import androidx.wear.watchface.complications.data.ComplicationData
import androidx.wear.watchface.complications.data.ComplicationType
import androidx.wear.watchface.complications.data.LongTextComplicationData
import androidx.wear.watchface.complications.data.NoDataComplicationData
import androidx.wear.watchface.complications.data.PlainComplicationText
import androidx.wear.watchface.complications.data.ShortTextComplicationData
import androidx.wear.watchface.complications.datasource.ComplicationRequest
import androidx.wear.watchface.complications.datasource.SuspendingComplicationDataSourceService
import com.glycemicgpt.weardevice.data.WatchDataRepository
import com.glycemicgpt.weardevice.util.GlucoseDisplayUtils

class BgComplicationDataSource : SuspendingComplicationDataSourceService() {

    override fun getPreviewData(type: ComplicationType): ComplicationData {
        val text = PlainComplicationText.Builder("120 \u2192").build()
        val title = PlainComplicationText.Builder("BG").build()
        val description = PlainComplicationText.Builder("Blood Glucose: 120 mg/dL").build()

        return when (type) {
            ComplicationType.SHORT_TEXT ->
                ShortTextComplicationData.Builder(text = text, contentDescription = description)
                    .setTitle(title)
                    .build()
            ComplicationType.LONG_TEXT ->
                LongTextComplicationData.Builder(
                    text = PlainComplicationText.Builder("BG: 120 mg/dL \u2192").build(),
                    contentDescription = description,
                )
                    .setTitle(title)
                    .build()
            else -> NoDataComplicationData()
        }
    }

    override suspend fun onComplicationRequest(request: ComplicationRequest): ComplicationData {
        val now = System.currentTimeMillis()
        val staleThresholdMs = 15 * 60_000L // 15 minutes
        val cgmState = WatchDataRepository.cgm.value?.takeIf {
            val ageMs = now - it.timestampMs
            GlucoseDisplayUtils.isValidGlucose(it.mgDl) &&
                ageMs in 0 until staleThresholdMs
        }
        val bgText = cgmState?.let {
            "${it.mgDl} ${GlucoseDisplayUtils.trendSymbol(it.trend)}"
        } ?: "--"
        val descriptionText = cgmState?.let { "Blood Glucose: ${it.mgDl} mg/dL" } ?: "No data"

        val text = PlainComplicationText.Builder(bgText).build()
        val title = PlainComplicationText.Builder("BG").build()
        val description = PlainComplicationText.Builder(descriptionText).build()

        return when (request.complicationType) {
            ComplicationType.SHORT_TEXT ->
                ShortTextComplicationData.Builder(text = text, contentDescription = description)
                    .setTitle(title)
                    .build()
            ComplicationType.LONG_TEXT ->
                LongTextComplicationData.Builder(
                    text = PlainComplicationText.Builder(
                        "BG: ${cgmState?.mgDl ?: "--"} mg/dL ${cgmState?.let { GlucoseDisplayUtils.trendSymbol(it.trend) } ?: ""}",
                    ).build(),
                    contentDescription = description,
                )
                    .setTitle(title)
                    .build()
            else -> NoDataComplicationData()
        }
    }
}
