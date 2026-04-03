package com.glycemicgpt.weardevice.complications

import android.app.PendingIntent
import android.content.Intent
import android.graphics.drawable.Icon
import androidx.wear.watchface.complications.data.ComplicationData
import androidx.wear.watchface.complications.data.ComplicationType
import androidx.wear.watchface.complications.data.NoDataComplicationData
import androidx.wear.watchface.complications.data.PlainComplicationText
import androidx.wear.watchface.complications.data.SmallImage
import androidx.wear.watchface.complications.data.SmallImageComplicationData
import androidx.wear.watchface.complications.data.SmallImageType
import androidx.wear.watchface.complications.datasource.ComplicationRequest
import androidx.wear.watchface.complications.datasource.SuspendingComplicationDataSourceService
import com.glycemicgpt.weardevice.R
import com.glycemicgpt.weardevice.data.WatchDataRepository
import com.glycemicgpt.weardevice.presentation.AlertsActivity

class AlertsComplicationDataSource : SuspendingComplicationDataSourceService() {

    override fun getPreviewData(type: ComplicationType): ComplicationData {
        if (type != ComplicationType.SMALL_IMAGE) return NoDataComplicationData()
        val icon = Icon.createWithResource(this, R.drawable.ic_complication_bell)
        icon.setTint(COLOR_DEFAULT)
        return SmallImageComplicationData.Builder(
            smallImage = SmallImage.Builder(icon, SmallImageType.PHOTO).build(),
            contentDescription = PlainComplicationText.Builder("Alerts").build(),
        ).build()
    }

    override suspend fun onComplicationRequest(request: ComplicationRequest): ComplicationData {
        if (request.complicationType != ComplicationType.SMALL_IMAGE) {
            return NoDataComplicationData()
        }

        val alert = WatchDataRepository.alert.value
        val hasActiveAlert = alert != null &&
            !alert.type.equals("none", ignoreCase = true)
        val isUrgent = alert?.type?.startsWith("urgent", ignoreCase = true) == true
        val tintColor = when {
            isUrgent -> COLOR_URGENT
            hasActiveAlert -> COLOR_WARNING
            else -> COLOR_DEFAULT
        }
        val description = when {
            isUrgent -> "Urgent alert active"
            hasActiveAlert -> "Alert active"
            else -> "No active alerts"
        }

        val icon = Icon.createWithResource(this, R.drawable.ic_complication_bell)
        icon.setTint(tintColor)

        val tapIntent = Intent(this, AlertsActivity::class.java).apply {
            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP)
        }
        val tapAction = PendingIntent.getActivity(
            this,
            ALERTS_REQUEST_CODE,
            tapIntent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )

        return SmallImageComplicationData.Builder(
            smallImage = SmallImage.Builder(icon, SmallImageType.PHOTO).build(),
            contentDescription = PlainComplicationText.Builder(description).build(),
        )
            .setTapAction(tapAction)
            .build()
    }

    private companion object {
        const val ALERTS_REQUEST_CODE = 2001
        const val COLOR_DEFAULT = 0xFF9CA3AF.toInt()   // Grey
        const val COLOR_WARNING = 0xFFFBBF24.toInt()    // Yellow
        const val COLOR_URGENT = 0xFFEF4444.toInt()     // Red
    }
}
