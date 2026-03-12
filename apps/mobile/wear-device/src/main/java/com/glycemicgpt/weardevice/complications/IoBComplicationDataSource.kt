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

class IoBComplicationDataSource : SuspendingComplicationDataSourceService() {

    override fun getPreviewData(type: ComplicationType): ComplicationData {
        val text = PlainComplicationText.Builder("2.45").build()
        val title = PlainComplicationText.Builder("IoB").build()
        val description = PlainComplicationText.Builder("Insulin on Board: 2.45 units").build()

        return when (type) {
            ComplicationType.SHORT_TEXT ->
                ShortTextComplicationData.Builder(text = text, contentDescription = description)
                    .setTitle(title)
                    .build()
            ComplicationType.LONG_TEXT ->
                LongTextComplicationData.Builder(
                    text = PlainComplicationText.Builder("IoB: 2.45 units").build(),
                    contentDescription = description,
                )
                    .setTitle(title)
                    .build()
            else -> NoDataComplicationData()
        }
    }

    override suspend fun onComplicationRequest(request: ComplicationRequest): ComplicationData {
        if (!WatchDataRepository.watchFaceConfig.value.showIoB) {
            return NoDataComplicationData()
        }
        val iobState = WatchDataRepository.iob.value
        val iobText = iobState?.let { "%.2f".format(it.iob) } ?: "--"
        val descriptionText = iobState?.let { "Insulin on Board: $iobText units" } ?: "No data"

        val text = PlainComplicationText.Builder(iobText).build()
        val title = PlainComplicationText.Builder("IoB").build()
        val description = PlainComplicationText.Builder(descriptionText).build()

        return when (request.complicationType) {
            ComplicationType.SHORT_TEXT ->
                ShortTextComplicationData.Builder(text = text, contentDescription = description)
                    .setTitle(title)
                    .build()
            ComplicationType.LONG_TEXT ->
                LongTextComplicationData.Builder(
                    text = PlainComplicationText.Builder("IoB: $iobText units").build(),
                    contentDescription = description,
                )
                    .setTitle(title)
                    .build()
            else -> NoDataComplicationData()
        }
    }
}
