package com.glycemicgpt.mobile.data.local

import androidx.room.Database
import androidx.room.RoomDatabase
import com.glycemicgpt.mobile.data.local.dao.AlertDao
import com.glycemicgpt.mobile.data.local.dao.PumpDao
import com.glycemicgpt.mobile.data.local.dao.RawHistoryLogDao
import com.glycemicgpt.mobile.data.local.dao.SyncDao
import com.glycemicgpt.mobile.data.local.entity.AlertEntity
import com.glycemicgpt.mobile.data.local.entity.BasalReadingEntity
import com.glycemicgpt.mobile.data.local.entity.BatteryReadingEntity
import com.glycemicgpt.mobile.data.local.entity.BolusEventEntity
import com.glycemicgpt.mobile.data.local.entity.CgmReadingEntity
import com.glycemicgpt.mobile.data.local.entity.IoBReadingEntity
import com.glycemicgpt.mobile.data.local.entity.RawHistoryLogEntity
import com.glycemicgpt.mobile.data.local.entity.ReservoirReadingEntity
import com.glycemicgpt.mobile.data.local.entity.SyncQueueEntity

@Database(
    entities = [
        IoBReadingEntity::class,
        BasalReadingEntity::class,
        BolusEventEntity::class,
        BatteryReadingEntity::class,
        ReservoirReadingEntity::class,
        SyncQueueEntity::class,
        RawHistoryLogEntity::class,
        CgmReadingEntity::class,
        AlertEntity::class,
    ],
    version = 9,
    exportSchema = true,
)
abstract class AppDatabase : RoomDatabase() {
    abstract fun pumpDao(): PumpDao
    abstract fun syncDao(): SyncDao
    abstract fun rawHistoryLogDao(): RawHistoryLogDao
    abstract fun alertDao(): AlertDao
}
