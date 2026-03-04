package com.glycemicgpt.mobile.data.local.dao

import androidx.room.Dao
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query
import androidx.room.Transaction
import com.glycemicgpt.mobile.data.local.entity.BasalReadingEntity
import com.glycemicgpt.mobile.data.local.entity.BatteryReadingEntity
import com.glycemicgpt.mobile.data.local.entity.BolusEventEntity
import com.glycemicgpt.mobile.data.local.entity.CgmReadingEntity
import com.glycemicgpt.mobile.data.local.entity.IoBReadingEntity
import com.glycemicgpt.mobile.data.local.entity.ReservoirReadingEntity
import kotlinx.coroutines.flow.Flow

@Dao
interface PumpDao {

    // -- IoB ------------------------------------------------------------------

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insertIoB(reading: IoBReadingEntity)

    @Query("SELECT * FROM iob_readings ORDER BY timestampMs DESC LIMIT 1")
    fun observeLatestIoB(): Flow<IoBReadingEntity?>

    @Query("SELECT * FROM iob_readings WHERE timestampMs >= :sinceMs ORDER BY timestampMs DESC")
    suspend fun getIoBSince(sinceMs: Long): List<IoBReadingEntity>

    @Query("SELECT * FROM iob_readings WHERE timestampMs >= :sinceMs ORDER BY timestampMs ASC LIMIT :limit")
    fun observeIoBHistory(sinceMs: Long, limit: Int = 2000): Flow<List<IoBReadingEntity>>

    @Query("SELECT * FROM iob_readings WHERE timestampMs >= :sinceMs ORDER BY timestampMs ASC")
    fun observeIoBHistoryAll(sinceMs: Long): Flow<List<IoBReadingEntity>>

    @Query("DELETE FROM iob_readings WHERE timestampMs < :beforeMs")
    suspend fun deleteIoBBefore(beforeMs: Long): Int

    // -- Basal ----------------------------------------------------------------

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insertBasal(reading: BasalReadingEntity)

    @Insert(onConflict = OnConflictStrategy.IGNORE)
    suspend fun insertBasalBatch(readings: List<BasalReadingEntity>)

    @Query("SELECT * FROM basal_readings ORDER BY timestampMs DESC LIMIT 1")
    fun observeLatestBasal(): Flow<BasalReadingEntity?>

    @Query("SELECT * FROM basal_readings WHERE timestampMs >= :sinceMs ORDER BY timestampMs ASC LIMIT :limit")
    fun observeBasalHistory(sinceMs: Long, limit: Int = 2000): Flow<List<BasalReadingEntity>>

    @Query("SELECT * FROM basal_readings WHERE timestampMs >= :sinceMs ORDER BY timestampMs ASC")
    fun observeBasalHistoryAll(sinceMs: Long): Flow<List<BasalReadingEntity>>

    @Query("DELETE FROM basal_readings WHERE timestampMs < :beforeMs")
    suspend fun deleteBasalBefore(beforeMs: Long): Int

    // -- Bolus ----------------------------------------------------------------

    @Insert(onConflict = OnConflictStrategy.IGNORE)
    suspend fun insertBolus(event: BolusEventEntity)

    @Insert(onConflict = OnConflictStrategy.IGNORE)
    suspend fun insertBoluses(events: List<BolusEventEntity>)

    @Query("SELECT * FROM bolus_events WHERE timestampMs >= :sinceMs ORDER BY timestampMs DESC")
    suspend fun getBolusesSince(sinceMs: Long): List<BolusEventEntity>

    @Query("SELECT * FROM bolus_events WHERE timestampMs >= :sinceMs ORDER BY timestampMs ASC LIMIT :limit")
    fun observeBolusHistory(sinceMs: Long, limit: Int = 500): Flow<List<BolusEventEntity>>

    @Query("SELECT MAX(timestampMs) FROM bolus_events")
    suspend fun getLatestBolusTimestamp(): Long?

    @Query("SELECT * FROM bolus_events WHERE timestampMs >= :sinceMs ORDER BY timestampMs ASC")
    fun observeBolusHistoryAll(sinceMs: Long): Flow<List<BolusEventEntity>>

    @Query("DELETE FROM bolus_events WHERE timestampMs < :beforeMs")
    suspend fun deleteBolusBefore(beforeMs: Long): Int

    // -- Battery --------------------------------------------------------------

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insertBattery(reading: BatteryReadingEntity)

    @Query("SELECT * FROM battery_readings ORDER BY timestampMs DESC LIMIT 1")
    fun observeLatestBattery(): Flow<BatteryReadingEntity?>

    @Query("DELETE FROM battery_readings WHERE timestampMs < :beforeMs")
    suspend fun deleteBatteryBefore(beforeMs: Long): Int

    // -- Reservoir ------------------------------------------------------------

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insertReservoir(reading: ReservoirReadingEntity)

    @Query("SELECT * FROM reservoir_readings ORDER BY timestampMs DESC LIMIT 1")
    fun observeLatestReservoir(): Flow<ReservoirReadingEntity?>

    @Query("DELETE FROM reservoir_readings WHERE timestampMs < :beforeMs")
    suspend fun deleteReservoirBefore(beforeMs: Long): Int

    // -- CGM ------------------------------------------------------------------

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insertCgm(reading: CgmReadingEntity)

    @Insert(onConflict = OnConflictStrategy.IGNORE)
    suspend fun insertCgmBatch(readings: List<CgmReadingEntity>)

    @Query("SELECT * FROM cgm_readings ORDER BY timestampMs DESC LIMIT 1")
    fun observeLatestCgm(): Flow<CgmReadingEntity?>

    @Query("SELECT * FROM cgm_readings WHERE timestampMs >= :sinceMs ORDER BY timestampMs ASC LIMIT :limit")
    fun observeCgmHistory(sinceMs: Long, limit: Int = 2000): Flow<List<CgmReadingEntity>>

    @Query("SELECT * FROM cgm_readings WHERE timestampMs >= :sinceMs ORDER BY timestampMs ASC")
    fun observeCgmHistoryAll(sinceMs: Long): Flow<List<CgmReadingEntity>>

    @Query("DELETE FROM cgm_readings WHERE timestampMs < :beforeMs")
    suspend fun deleteCgmBefore(beforeMs: Long): Int

    // -- Time in Range aggregation --------------------------------------------

    @Query(
        """
        SELECT
            COUNT(*) AS total,
            SUM(CASE WHEN glucoseMgDl < :low THEN 1 ELSE 0 END) AS lowCount,
            SUM(CASE WHEN glucoseMgDl >= :low AND glucoseMgDl <= :high THEN 1 ELSE 0 END) AS inRangeCount,
            SUM(CASE WHEN glucoseMgDl > :high THEN 1 ELSE 0 END) AS highCount
        FROM cgm_readings
        WHERE timestampMs >= :sinceMs
        """,
    )
    fun observeTimeInRangeCounts(sinceMs: Long, low: Int, high: Int): Flow<TimeInRangeCounts>

    // -- Transactional cleanup ------------------------------------------------

    @Transaction
    suspend fun deleteAllBefore(beforeMs: Long): Int {
        var total = 0
        total += deleteIoBBefore(beforeMs)
        total += deleteBasalBefore(beforeMs)
        total += deleteBolusBefore(beforeMs)
        total += deleteBatteryBefore(beforeMs)
        total += deleteReservoirBefore(beforeMs)
        total += deleteCgmBefore(beforeMs)
        return total
    }
}

data class TimeInRangeCounts(
    val total: Int,
    val lowCount: Int,
    val inRangeCount: Int,
    val highCount: Int,
)
