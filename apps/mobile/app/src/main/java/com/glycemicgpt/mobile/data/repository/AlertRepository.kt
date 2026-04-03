package com.glycemicgpt.mobile.data.repository

import com.glycemicgpt.mobile.data.local.dao.AlertDao
import com.glycemicgpt.mobile.data.local.entity.AlertEntity
import com.glycemicgpt.mobile.data.remote.GlycemicGptApi
import com.glycemicgpt.mobile.data.remote.dto.AlertResponse
import kotlinx.coroutines.flow.Flow
import timber.log.Timber
import java.time.Instant
import javax.inject.Inject
import javax.inject.Singleton

@Singleton
class AlertRepository @Inject constructor(
    private val alertDao: AlertDao,
    private val api: GlycemicGptApi,
) {

    fun observeRecentAlerts(): Flow<List<AlertEntity>> = alertDao.observeRecentAlerts()

    suspend fun saveAlert(response: AlertResponse) {
        val timestampMs = try {
            Instant.parse(response.timestamp).toEpochMilli()
        } catch (e: Exception) {
            System.currentTimeMillis()
        }

        alertDao.insert(
            AlertEntity(
                serverId = response.id,
                alertType = response.alertType,
                severity = response.severity,
                message = response.message,
                currentValue = response.currentValue,
                predictedValue = response.predictedValue,
                iobValue = response.iobValue,
                trendRate = response.trendRate,
                patientName = response.patientName,
                acknowledged = response.acknowledged,
                timestampMs = timestampMs,
            ),
        )
    }

    suspend fun acknowledgeAlert(serverId: String): Result<Unit> = runCatching {
        val response = api.acknowledgeAlert(serverId)
        if (response.isSuccessful) {
            alertDao.markAcknowledged(serverId)
        } else {
            throw RuntimeException("Acknowledge failed: HTTP ${response.code()}")
        }
    }

    suspend fun getLatestUnacknowledgedServerId(): String? =
        alertDao.getLatestUnacknowledgedServerId()

    suspend fun fetchPendingAlerts(): Result<List<AlertResponse>> = runCatching {
        val response = api.getPendingAlerts()
        if (response.isSuccessful) {
            val alerts = response.body() ?: emptyList()
            for (alert in alerts) {
                saveAlert(alert)
            }
            alerts
        } else {
            throw RuntimeException("Fetch alerts failed: HTTP ${response.code()}")
        }
    }

    suspend fun cleanupOldAlerts(maxAgeDays: Int = 7) {
        val cutoffMs = System.currentTimeMillis() - (maxAgeDays * 24 * 60 * 60 * 1000L)
        alertDao.deleteOlderThan(cutoffMs)
    }
}
