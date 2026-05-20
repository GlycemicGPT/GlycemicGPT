package com.glycemicgpt.mobile.data.local.entity

import androidx.room.Entity
import androidx.room.Index
import androidx.room.PrimaryKey

/**
 * Stores raw BLE history log bytes received from the Tandem pump.
 *
 * Preserves the exact binary record format for local diagnostics and
 * potential future history-replay features. Older builds also forwarded
 * these bytes to the backend's Tandem cloud-upload pipeline, which was
 * removed in PR1c; the backend continues to accept the field for
 * back-compat but discards it. The [sequenceNumber] is unique per pump
 * and used to deduplicate.
 */
@Entity(
    tableName = "raw_history_logs",
    indices = [Index(value = ["sequenceNumber"], unique = true)],
)
data class RawHistoryLogEntity(
    @PrimaryKey(autoGenerate = true) val id: Long = 0,
    val sequenceNumber: Int,
    val rawBytesB64: String,
    val eventTypeId: Int,
    val pumpTimeSeconds: Long,
    val sentToBackend: Boolean = false,
    val createdAtMs: Long = System.currentTimeMillis(),
)
