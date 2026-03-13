package com.glycemicgpt.mobile.data.local.dao

import androidx.room.Dao
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query
import com.glycemicgpt.mobile.data.local.entity.AlertEntity
import kotlinx.coroutines.flow.Flow

@Dao
interface AlertDao {

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insert(alert: AlertEntity): Long

    @Query("SELECT * FROM alerts ORDER BY timestamp_ms DESC LIMIT 100")
    fun observeRecentAlerts(): Flow<List<AlertEntity>>

    @Query("UPDATE alerts SET acknowledged = 1 WHERE server_id = :serverId")
    suspend fun markAcknowledged(serverId: String)

    @Query(
        "SELECT server_id FROM alerts " +
            "WHERE acknowledged = 0 " +
            "ORDER BY timestamp_ms DESC, id DESC " +
            "LIMIT 1",
    )
    suspend fun getLatestUnacknowledgedServerId(): String?

    @Query("DELETE FROM alerts WHERE timestamp_ms < :cutoffMs")
    suspend fun deleteOlderThan(cutoffMs: Long)

    @Query("DELETE FROM alerts")
    suspend fun deleteAll()
}
