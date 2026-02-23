package com.glycemicgpt.mobile.ble.messages

import android.util.Base64
import com.glycemicgpt.mobile.domain.model.BasalReading
import com.glycemicgpt.mobile.domain.model.BatteryStatus
import com.glycemicgpt.mobile.domain.model.BolusEvent
import com.glycemicgpt.mobile.domain.model.CgmReading
import com.glycemicgpt.mobile.domain.model.CgmTrend
import com.glycemicgpt.mobile.domain.model.ControlIqMode
import com.glycemicgpt.mobile.domain.model.HistoryLogRange
import com.glycemicgpt.mobile.domain.model.HistoryLogRecord
import com.glycemicgpt.mobile.domain.model.IoBReading
import com.glycemicgpt.mobile.domain.model.PumpHardwareInfo
import com.glycemicgpt.mobile.domain.model.PumpSettings
import com.glycemicgpt.mobile.domain.model.ReservoirReading
import com.glycemicgpt.mobile.domain.pump.SafetyLimits
import timber.log.Timber
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.time.Instant
import java.time.LocalDateTime
import java.time.ZoneId
import java.time.ZoneOffset

/**
 * Parses response cargo bytes from Tandem pump BLE status responses into
 * domain model objects.
 *
 * Byte layouts verified against jwoglom/pumpX2 (MIT) source and test vectors.
 * All parsers return null on malformed cargo instead of throwing.
 */
internal object StatusResponseParser {

    /** Unix timestamp of January 1, 2008 00:00:00 UTC.
     *  Used as a base offset for pump timestamps. The pump counts seconds
     *  since local midnight Jan 1, 2008; the UTC value is used here because
     *  pumpTimeToInstant() extracts wall-clock digits via ZoneOffset.UTC. */
    private const val TANDEM_EPOCH_OFFSET = 1199145600L

    /**
     * Convert pump timestamp to UTC Instant.
     *
     * The Tandem pump reports timestamps as seconds since Jan 1, 2008 in the
     * user's local timezone (the pump syncs its clock with the phone via
     * t:connect). We interpret the computed epoch as a local date-time and
     * convert to UTC using the device's timezone.
     */
    private fun pumpTimeToInstant(pumpTimeSec: Long): Instant {
        val rawEpochSec = pumpTimeSec + TANDEM_EPOCH_OFFSET
        // ZoneOffset.UTC is intentional: rawEpochSec encodes local wall-clock
        // digits (pump counts local seconds + UTC-based epoch constant), so
        // interpreting at UTC offset extracts the correct LocalDateTime fields.
        val localDateTime = LocalDateTime.ofEpochSecond(rawEpochSec, 0, ZoneOffset.UTC)
        return localDateTime.atZone(ZoneId.systemDefault()).toInstant()
    }

    /**
     * Parse ControlIQIOBResponse (opcode 109).
     *
     * Cargo layout (17 bytes, all little-endian unsigned):
     *   bytes  0- 3: mudaliarIOB (uint32 LE, milliunits)
     *   bytes  4- 7: timeRemainingSeconds (uint32 LE)
     *   bytes  8-11: mudaliarTotalIOB (uint32 LE, milliunits)
     *   bytes 12-15: swan6hrIOB (uint32 LE, milliunits)
     *   byte  16:    iobType (0=MUDALIAR/CIQ off, 1=SWAN_6HR/CIQ on)
     *
     * The displayed IOB depends on iobType:
     *   - iobType 0: use mudaliarIOB
     *   - iobType 1: use swan6hrIOB
     */
    fun parseIoBResponse(cargo: ByteArray): IoBReading? {
        if (cargo.size < 17) return null
        val buf = ByteBuffer.wrap(cargo).order(ByteOrder.LITTLE_ENDIAN)
        val mudaliarIOB = buf.int.toLong() and 0xFFFFFFFFL
        buf.int // skip timeRemainingSeconds
        buf.int // skip mudaliarTotalIOB
        val swan6hrIOB = buf.int.toLong() and 0xFFFFFFFFL
        // Read iobType directly from cargo array (not buf) to avoid
        // signed-byte issues and buffer position dependence.
        val iobType = cargo[16].toInt() and 0xFF

        val milliUnits = if (iobType == 1) swan6hrIOB else mudaliarIOB
        val iob = milliUnits / 1000f
        return IoBReading(iob = iob, timestamp = Instant.now())
    }

    /**
     * Parse CurrentBasalStatusResponse (opcode 41).
     *
     * Cargo layout (9 bytes, all little-endian unsigned):
     *   bytes 0-3: profileBasalRate (uint32 LE, milliunits/hr)
     *   bytes 4-7: currentBasalRate (uint32 LE, milliunits/hr)
     *   byte  8:   basalModifiedBitmask (0=normal, 1=modified/suspended)
     *
     * Control-IQ mode is NOT in this response; it comes from
     * HomeScreenMirrorResponse (opcode 57).
     */
    fun parseBasalStatusResponse(cargo: ByteArray): BasalReading? {
        if (cargo.size < 9) return null
        val buf = ByteBuffer.wrap(cargo).order(ByteOrder.LITTLE_ENDIAN)
        buf.int // skip profileBasalRate
        val currentRate = buf.int.toLong() and 0xFFFFFFFFL
        val modified = cargo[8].toInt() and 0xFF
        val rate = currentRate / 1000f
        val isAutomated = modified != 0

        return BasalReading(
            rate = rate,
            isAutomated = isAutomated,
            controlIqMode = ControlIqMode.STANDARD, // updated by HomeScreenMirror
            timestamp = Instant.now(),
        )
    }

    /**
     * Parse InsulinStatusResponse (opcode 37).
     *
     * Cargo layout (4 bytes, little-endian):
     *   bytes 0-1: currentInsulinAmount (uint16 LE, WHOLE units, not milliunits)
     *   byte  2:   isEstimate (0=exact, non-zero=estimate)
     *   byte  3:   insulinLowAmount (threshold in units for low-insulin alert)
     */
    fun parseInsulinStatusResponse(cargo: ByteArray): ReservoirReading? {
        if (cargo.size < 2) return null
        val buf = ByteBuffer.wrap(cargo, 0, 2).order(ByteOrder.LITTLE_ENDIAN)
        val units = buf.short.toInt() and 0xFFFF
        return ReservoirReading(unitsRemaining = units.toFloat(), timestamp = Instant.now())
    }

    /**
     * Parse CurrentBatteryV1Response (opcode 53).
     *
     * Cargo layout (2 bytes):
     *   byte 0: currentBatteryAbc (internal absolute charge metric)
     *   byte 1: currentBatteryIbc (battery percentage 0-100, display value)
     */
    fun parseBatteryV1Response(cargo: ByteArray): BatteryStatus? {
        if (cargo.size < 2) return null
        val percentage = cargo[1].toInt() and 0xFF
        return BatteryStatus(
            percentage = percentage.coerceIn(0, 100),
            isCharging = false, // V1 has no charging flag
            timestamp = Instant.now(),
        )
    }

    /**
     * Parse CurrentBatteryV2Response (opcode 145 / 0x91).
     *
     * Cargo layout (11 bytes):
     *   byte 0:    currentBatteryAbc (internal)
     *   byte 1:    currentBatteryIbc (battery percentage 0-100)
     *   byte 2:    chargingStatus (0=not charging, 1=charging)
     *   bytes 3-10: unknown fields (4x uint16 LE, always 0 in test data)
     */
    fun parseBatteryV2Response(cargo: ByteArray): BatteryStatus? {
        if (cargo.size < 3) return null
        val percentage = cargo[1].toInt() and 0xFF
        val isCharging = (cargo[2].toInt() and 0xFF) != 0
        return BatteryStatus(
            percentage = percentage.coerceIn(0, 100),
            isCharging = isCharging,
            timestamp = Instant.now(),
        )
    }

    /**
     * Parse CurrentEGVGuiDataResponse (opcode 35).
     *
     * Cargo layout (8 bytes, little-endian):
     *   bytes 0-3: bgReadingTimestampSeconds (uint32 LE, seconds since Tandem epoch Jan 1, 2008)
     *   bytes 4-5: cgmReading (uint16 LE, mg/dL)
     *   byte  6:   egvStatusId (0=INVALID, 1=VALID, 2=LOW, 3=HIGH, 4=UNAVAILABLE)
     *   byte  7:   trendRate (signed byte, rate of change -- NOT a trend arrow enum)
     *
     * Trend arrow icons come from HomeScreenMirrorResponse (opcode 57) byte 0.
     */
    fun parseCgmEgvResponse(cargo: ByteArray, limits: SafetyLimits = SafetyLimits()): CgmReading? {
        if (cargo.size < 8) return null
        val buf = ByteBuffer.wrap(cargo).order(ByteOrder.LITTLE_ENDIAN)
        val pumpTimeSec = buf.int.toLong() and 0xFFFFFFFFL
        val glucoseMgDl = buf.short.toInt() and 0xFFFF
        val egvStatus = cargo[6].toInt() and 0xFF

        // Accept VALID (1), LOW (2), and HIGH (3) readings -- all carry a glucose value.
        // Reject INVALID (0) and UNAVAILABLE (4+) which have no usable glucose data.
        if (egvStatus !in 1..3) return null
        // Reject values outside the user's configured safety range.
        if (glucoseMgDl < limits.minGlucoseMgDl || glucoseMgDl > limits.maxGlucoseMgDl) return null

        val timestamp = pumpTimeToInstant(pumpTimeSec)

        // trendRate at byte 7 is a signed rate-of-change, not an arrow enum.
        // Trend arrow is set separately via HomeScreenMirror. Default to UNKNOWN here.
        return CgmReading(
            glucoseMgDl = glucoseMgDl,
            trendArrow = CgmTrend.UNKNOWN,
            timestamp = timestamp,
        )
    }

    /**
     * Parse HomeScreenMirrorResponse (opcode 57) for trend arrow and CIQ state.
     *
     * Cargo layout (9 bytes):
     *   byte 0: cgmTrendIconId (0=NO_ARROW, 1=DOUBLE_UP, 2=UP, 3=UP_RIGHT,
     *           4=FLAT, 5=DOWN_RIGHT, 6=DOWN, 7=DOUBLE_DOWN)
     *   byte 1: cgmStatusIconId
     *   byte 2: tempRateIconId
     *   byte 3: tempRatePercentage (signed)
     *   byte 4: basalStatusDurationRemaining
     *   byte 5: basalStatusIconId (0=basal, 1=zero_basal, 5=hypo_suspend, 6=increase, 7=attenuated)
     *   byte 6: apControlStateIconId (0=gray, 1=suspended/red, 2=increase_basal/blue, 3=attenuation/orange)
     *   byte 7: cgmHighAlertIconId
     *   byte 8: cgmLowAlertIconId
     */
    fun parseHomeScreenMirrorResponse(cargo: ByteArray): HomeScreenMirrorData? {
        if (cargo.size < 7) return null
        val trendIconId = cargo[0].toInt() and 0xFF
        val basalStatusIconId = if (cargo.size > 5) cargo[5].toInt() and 0xFF else 0
        val apControlStateIconId = if (cargo.size > 6) cargo[6].toInt() and 0xFF else 0

        val trendArrow = when (trendIconId) {
            1 -> CgmTrend.DOUBLE_UP
            2 -> CgmTrend.SINGLE_UP
            3 -> CgmTrend.FORTY_FIVE_UP
            4 -> CgmTrend.FLAT
            5 -> CgmTrend.FORTY_FIVE_DOWN
            6 -> CgmTrend.SINGLE_DOWN
            7 -> CgmTrend.DOUBLE_DOWN
            else -> CgmTrend.UNKNOWN
        }

        return HomeScreenMirrorData(
            trendArrow = trendArrow,
            basalStatusIconId = basalStatusIconId,
            apControlStateIconId = apControlStateIconId,
        )
    }

    /**
     * Parse PumpSettings response (opcode 83).
     *
     * Cargo layout:
     *   bytes 0-3: firmware version length (Int32 LE), then string bytes
     *   followed by serial number and model number in the same pattern.
     *
     * Simplified: firmware(4+len) + serial(4+len) + model(4+len)
     */
    fun parsePumpSettingsResponse(cargo: ByteArray): PumpSettings? {
        if (cargo.size < 12) return null // minimum: 3 x (4-byte length prefix + 0 bytes)
        try {
            var offset = 0
            val (firmware, fwByteLen) = readLengthPrefixedString(cargo, offset) ?: return null
            offset += 4 + fwByteLen
            val (serial, serialByteLen) = readLengthPrefixedString(cargo, offset) ?: return null
            offset += 4 + serialByteLen
            val (model, _) = readLengthPrefixedString(cargo, offset) ?: return null
            return PumpSettings(
                firmwareVersion = firmware,
                serialNumber = serial,
                modelNumber = model,
            )
        } catch (_: Exception) {
            return null
        }
    }

    /**
     * Parse LastBolusStatusResponse (opcode 49).
     *
     * V1 cargo layout (17 bytes, all little-endian unsigned):
     *   bytes  0- 3: bolusId (uint32 LE)
     *   bytes  4- 7: timestampSeconds (uint32 LE, seconds since Tandem epoch)
     *   bytes  8-11: deliveredVolume (uint32 LE, milliunits -- 1000x per unit)
     *   byte  12:    bolusStatusId (0=UNKNOWN, 2=CANCELED, 3=COMPLETED, 4=ERROR)
     *   byte  13:    bolusSourceId (0=GUI, 1=AUTO_PILOT, 2=AUTO_POP_UP)
     *   byte  14:    bolusTypeBitmask (1=STANDARD, 2=EXTENDED, 4=FOOD, 8=CORRECTION)
     *   bytes 15-16: extendedBolusDuration (uint16 LE, minutes)
     *
     * Extended cargo layout (20 bytes, firmware v7.7+):
     *   byte  0:     status prefix (always 0x01)
     *   bytes  1-17: same fields as V1 (shifted by 1 byte)
     *   bytes 18-19: V2 extension fields (bolusRequestId, uint16 LE)
     *
     * Returns a single-element list with the last bolus (if completed and
     * newer than [since]), or an empty list otherwise.
     */
    fun parseLastBolusStatusResponse(
        cargo: ByteArray,
        since: Instant,
        limits: SafetyLimits = SafetyLimits(),
    ): List<BolusEvent> {
        // V1 (exactly 17 bytes): fields start at offset 0.
        // Extended (20+ bytes): 1-byte status prefix, fields start at offset 1.
        // Sizes 18-19 are neither valid V1 nor V2 -- reject them.
        val baseOffset = when {
            cargo.size >= 20 -> {
                val prefix = cargo[0].toInt() and 0xFF
                if (prefix != 0x01) {
                    Timber.w("LastBolus: unexpected V2 prefix byte 0x%02x (expected 0x01), size=%d",
                        prefix, cargo.size)
                }
                1
            }
            cargo.size == 17 -> 0
            else -> {
                if (cargo.size > 0) {
                    Timber.w("LastBolus: unexpected cargo size %d (expected 17 or 20+)", cargo.size)
                }
                return emptyList()
            }
        }

        val buf = ByteBuffer.wrap(cargo, baseOffset, cargo.size - baseOffset)
            .order(ByteOrder.LITTLE_ENDIAN)
        buf.int // skip bolusId
        val pumpTimeSec = buf.int.toLong() and 0xFFFFFFFFL
        val deliveredMilliUnits = buf.int.toLong() and 0xFFFFFFFFL
        val bolusStatusId = cargo[baseOffset + 12].toInt() and 0xFF
        val bolusSourceId = cargo[baseOffset + 13].toInt() and 0xFF
        val bolusTypeBitmask = cargo[baseOffset + 14].toInt() and 0xFF

        Timber.v("LastBolus: size=%d baseOffset=%d statusId=%d sourceId=%d typeMask=0x%02x deliveredMu=%d pumpTime=%d",
            cargo.size, baseOffset, bolusStatusId, bolusSourceId, bolusTypeBitmask,
            deliveredMilliUnits, pumpTimeSec)

        // Only report completed boluses (status 3)
        if (bolusStatusId != 3) return emptyList()

        // Reject implausibly large doses (matches parseBolusDeliveryPayload pattern)
        if (deliveredMilliUnits > limits.maxBolusDoseMilliunits) return emptyList()

        val timestamp = pumpTimeToInstant(pumpTimeSec)
        if (timestamp.isBefore(since)) return emptyList()

        val units = deliveredMilliUnits / 1000f
        val isAutomated = bolusSourceId == 1 // AUTO_PILOT
        val isCorrection = (bolusTypeBitmask and 0x08) != 0

        return listOf(
            BolusEvent(
                units = units,
                isAutomated = isAutomated,
                isCorrection = isCorrection,
                timestamp = timestamp,
            ),
        )
    }

    /**
     * Parse HistoryLogStatusResponse (opcode 59).
     *
     * Cargo layout (12 bytes, little-endian):
     *   bytes 0-3:  numEntries (uint32 LE) -- total available entries
     *   bytes 4-7:  firstSeq   (uint32 LE) -- oldest available log sequence
     *   bytes 8-11: lastSeq    (uint32 LE) -- newest available log sequence
     *
     * @return [HistoryLogRange] or null if cargo is too short.
     */
    fun parseHistoryLogStatusResponse(cargo: ByteArray): HistoryLogRange? {
        if (cargo.size < 12) return null
        val buf = ByteBuffer.wrap(cargo, 0, 12).order(ByteOrder.LITTLE_ENDIAN)
        buf.int // numEntries -- skip, we derive count from firstSeq/lastSeq
        val firstSeq = buf.int
        val lastSeq = buf.int
        return HistoryLogRange(firstSeq, lastSeq)
    }

    /**
     * Parse FFF8 stream cargo from history log response.
     *
     * The pump streams records on FFF8 after an opcode 60 request. The cargo
     * may contain a 2-byte header (record count + flags) followed by one or
     * more 26-byte records:
     *   bytes 0-1: event type ID (UInt16 LE)
     *   bytes 2-5: pump time in seconds (UInt32 LE, since Tandem epoch)
     *   bytes 6-9: record index (Int32 LE)
     *   bytes 10-25: raw event data (16 bytes)
     *
     * Returns all valid records. Dedup is handled at the insert layer (IGNORE).
     */
    fun parseHistoryLogStreamCargo(cargo: ByteArray): List<HistoryLogRecord> {
        // Try to find 26-byte records, with or without a leading header.
        // Try offsets 0 and 2 (in case of a 2-byte count/status prefix).
        for (headerSize in intArrayOf(0, 2)) {
            val dataLen = cargo.size - headerSize
            if (dataLen < STREAM_RECORD_SIZE) continue
            if (dataLen % STREAM_RECORD_SIZE != 0) continue

            // 26-byte format structurally matches. Parse records and return
            // (even if empty due to filtering) -- don't fall through to
            // 18-byte format which would misinterpret the same bytes.
            val records = parseStreamRecords(cargo, headerSize)
            Timber.d("Parsed %d records from FFF8 cargo (headerSize=%d)", records.size, headerSize)
            return records
        }

        // Fallback: try 18-byte format (same as opcode 61 on FFF6)
        val fallback = parseHistoryLogResponse(cargo, sinceSequence = 0)
        if (fallback.isNotEmpty()) {
            Timber.d("Parsed %d records from FFF8 cargo using 18-byte fallback", fallback.size)
            return fallback
        }

        Timber.w("Could not parse FFF8 cargo: size=%d hex=%s",
            cargo.size, cargo.take(64).joinToString(" ") { "%02x".format(it) })
        return emptyList()
    }

    private fun parseStreamRecords(
        cargo: ByteArray,
        offset: Int,
    ): List<HistoryLogRecord> {
        val records = mutableListOf<HistoryLogRecord>()
        var pos = offset
        while (pos + STREAM_RECORD_SIZE <= cargo.size) {
            val buf = ByteBuffer.wrap(cargo, pos, STREAM_RECORD_SIZE).order(ByteOrder.LITTLE_ENDIAN)
            // FFF8 stream record layout: eventTypeId(2) + pumpTimeSec(4) + recordIndex(4) + data(16)
            val eventTypeId = buf.short.toInt() and 0xFFFF
            val pumpTimeSec = buf.int.toLong() and 0xFFFFFFFFL
            val seqNum = buf.int // record index (used as sequence number for tracking)

            // Sanity check: reject obviously invalid fields.
            if (seqNum == 0 || eventTypeId > MAX_KNOWN_EVENT_TYPE) {
                pos += STREAM_RECORD_SIZE
                continue
            }

            // Store full 26-byte record to preserve all event data for cloud upload
            val rawRecord = cargo.copyOfRange(pos, pos + STREAM_RECORD_SIZE)
            val rawB64 = Base64.encodeToString(rawRecord, Base64.NO_WRAP)
            records.add(
                HistoryLogRecord(
                    sequenceNumber = seqNum,
                    rawBytesB64 = rawB64,
                    eventTypeId = eventTypeId,
                    pumpTimeSeconds = pumpTimeSec,
                ),
            )
            pos += STREAM_RECORD_SIZE
        }
        return records
    }

    /** Upper bound for known Tandem event type IDs (sanity check). */
    private const val MAX_KNOWN_EVENT_TYPE = 512

    /** FFF8 stream record size: 2(eventId) + 4(time) + 4(index) + 16(data) = 26 bytes */
    private const val STREAM_RECORD_SIZE = 26

    /**
     * Parse HistoryLogResponse (opcode 61) records.
     *
     * Cargo layout: repeated records, each 18 bytes:
     *   bytes 0-3: sequence number (Int32 LE)
     *   bytes 4-5: event type ID (UInt16 LE)
     *   bytes 6-9: pump time in seconds (Int32 LE)
     *   bytes 10-17: raw event payload (8 bytes, base64-encoded for storage)
     *
     * Returns only records with sequence > [sinceSequence].
     */
    fun parseHistoryLogResponse(cargo: ByteArray, sinceSequence: Int): List<HistoryLogRecord> {
        val recordSize = 18
        if (cargo.size < recordSize) return emptyList()

        val records = mutableListOf<HistoryLogRecord>()
        var offset = 0
        while (offset + recordSize <= cargo.size) {
            val buf = ByteBuffer.wrap(cargo, offset, recordSize).order(ByteOrder.LITTLE_ENDIAN)
            val seqNum = buf.int
            val eventTypeId = buf.short.toInt() and 0xFFFF
            val pumpTimeSec = buf.int.toLong() and 0xFFFFFFFFL

            if (seqNum > sinceSequence) {
                // Encode the entire raw record as base64 for cloud upload.
                // NOTE: pumpTimeSeconds is intentionally stored as raw pump-local
                // time (seconds since Tandem epoch, Jan 1, 2008 local). This value
                // is sent to the backend for Tandem cloud upload where the raw binary
                // format is required. Do NOT convert with pumpTimeToInstant().
                val rawBytes = cargo.copyOfRange(offset, offset + recordSize)
                val rawB64 = Base64.encodeToString(rawBytes, Base64.NO_WRAP)
                records.add(
                    HistoryLogRecord(
                        sequenceNumber = seqNum,
                        rawBytesB64 = rawB64,
                        eventTypeId = eventTypeId,
                        pumpTimeSeconds = pumpTimeSec,
                    ),
                )
            }
            offset += recordSize
        }
        return records
    }

    /**
     * Parse PumpVersionResponse (opcode 85).
     *
     * Cargo layout (48 bytes, all little-endian unsigned):
     *   bytes  0- 3: armSwVer (uint32 LE)
     *   bytes  4- 7: mspSwVer (uint32 LE)
     *   bytes  8-11: configABits (uint32 LE)
     *   bytes 12-15: configBBits (uint32 LE)
     *   bytes 16-19: serialNum (uint32 LE)
     *   bytes 20-23: partNum (uint32 LE)
     *   bytes 24-31: pumpRev (fixed 8-char string, null-padded)
     *   bytes 32-35: pcbaSN (uint32 LE)
     *   bytes 36-43: pcbaRev (fixed 8-char string, null-padded)
     *   bytes 44-47: modelNum (uint32 LE)
     *
     * Verified against pumpX2 PumpVersionResponse.java (opCode=85, size=48).
     * Returns PumpHardwareInfo with empty pumpFeatures (features come from
     * PumpFeaturesV1Response via a separate request).
     */
    fun parsePumpVersionResponse(cargo: ByteArray): PumpHardwareInfo? {
        if (cargo.size < 48) return null
        try {
            val buf = ByteBuffer.wrap(cargo).order(ByteOrder.LITTLE_ENDIAN)
            val armSwVer = buf.int.toLong() and 0xFFFFFFFFL
            val mspSwVer = buf.int.toLong() and 0xFFFFFFFFL
            val configABits = buf.int.toLong() and 0xFFFFFFFFL
            val configBBits = buf.int.toLong() and 0xFFFFFFFFL
            val serialNumber = buf.int.toLong() and 0xFFFFFFFFL
            val partNumber = buf.int.toLong() and 0xFFFFFFFFL
            val pumpRev = readFixedString(cargo, 24, 8)
            // skip buf position past pumpRev bytes
            buf.position(32)
            val pcbaSn = buf.int.toLong() and 0xFFFFFFFFL
            val pcbaRev = readFixedString(cargo, 36, 8)
            buf.position(44)
            val modelNumber = buf.int.toLong() and 0xFFFFFFFFL

            return PumpHardwareInfo(
                serialNumber = serialNumber,
                modelNumber = modelNumber,
                partNumber = partNumber,
                pumpRev = pumpRev,
                armSwVer = armSwVer,
                mspSwVer = mspSwVer,
                configABits = configABits,
                configBBits = configBBits,
                pcbaSn = pcbaSn,
                pcbaRev = pcbaRev,
                pumpFeatures = emptyMap(),
            )
        } catch (_: Exception) {
            return null
        }
    }

    /**
     * Parse PumpFeaturesV1Response (opcode 79).
     *
     * Cargo layout (8 bytes):
     *   bytes 0-7: feature bitmask (uint64 LE)
     *
     * Bit positions (from pumpX2 PumpFeatureType enum):
     *   bit  0: DEXCOM_G5_SUPPORTED
     *   bit  1: DEXCOM_G6_SUPPORTED
     *   bit  2: BASAL_IQ_SUPPORTED
     *   bit 10: CONTROL_IQ_SUPPORTED
     *
     * Returns a map of feature name to enabled status.
     */
    fun parsePumpFeaturesResponse(cargo: ByteArray): Map<String, Boolean> {
        if (cargo.size < 8) return emptyMap()
        val buf = ByteBuffer.wrap(cargo).order(ByteOrder.LITTLE_ENDIAN)
        val bitmask = buf.long
        return mapOf(
            "dexcomG5" to ((bitmask and (1L shl 0)) != 0L),
            "dexcomG6" to ((bitmask and (1L shl 1)) != 0L),
            "basalIQ" to ((bitmask and (1L shl 2)) != 0L),
            "controlIQ" to ((bitmask and (1L shl 10)) != 0L),
        )
    }

    // -- History log event extraction ---------------------------------------

    /** Event type ID for fingerstick BG meter readings (LidBgReadingTaken). */
    const val EVENT_TYPE_BG_METER_READING = 16

    /** Event type ID for Dexcom G7 CGM readings (LidCgmDataG7). */
    const val EVENT_TYPE_CGM_DATA_G7 = 399

    /** Event type ID for basal insulin delivery segments (LidBasalDelivery). */
    const val EVENT_TYPE_BASAL_DELIVERY = 279

    /** Event type ID for bolus insulin delivery (LidBolusDelivery). */
    const val EVENT_TYPE_BOLUS_DELIVERY = 280

    /** Set of event type IDs that carry CGM glucose data. */
    private val CGM_EVENT_TYPES = setOf(EVENT_TYPE_BG_METER_READING, EVENT_TYPE_CGM_DATA_G7)

    /** Basal rate sources that indicate automated (non-manual) delivery. */
    private val AUTOMATED_BASAL_SOURCES = setOf(0, 3, 4)

    /**
     * Parse a CGM glucose value from a type 16 (LidBgReadingTaken) payload.
     *
     * Payload layout (8 bytes, LE):
     *   bytes 0-1: glucose mg/dL (uint16 LE)
     *   bytes 2-7: status flags (unused for chart display)
     *
     * @param payload 8-byte event payload from the history log record
     * @param pumpTimeSec raw pump timestamp (seconds since Tandem epoch)
     * @return CgmReading or null if the glucose value is invalid
     */
    fun parseCgmEventPayload(payload: ByteArray, pumpTimeSec: Long, limits: SafetyLimits = SafetyLimits()): CgmReading? {
        if (payload.size < 2) return null
        val buf = ByteBuffer.wrap(payload, 0, 2).order(ByteOrder.LITTLE_ENDIAN)
        val glucoseMgDl = buf.short.toInt() and 0xFFFF
        if (glucoseMgDl < limits.minGlucoseMgDl || glucoseMgDl > limits.maxGlucoseMgDl) return null
        val timestamp = pumpTimeToInstant(pumpTimeSec)
        return CgmReading(
            glucoseMgDl = glucoseMgDl,
            trendArrow = CgmTrend.UNKNOWN, // trend not available from history
            timestamp = timestamp,
        )
    }

    /**
     * Parse a CGM glucose value from a type 399 (LidCgmDataG7) payload.
     *
     * Payload layout (16 bytes from FFF8 data field, LE):
     *   bytes 0-1: padding (always 00 00)
     *   byte  2:   status (01 = valid reading)
     *   byte  3:   trendRate (signed byte, rate of change)
     *   byte  4:   reading type flag (0x20)
     *   byte  5:   unknown
     *   bytes 6-7: glucose mg/dL (uint16 LE)
     *   bytes 8-15: timestamp duplicate + session info
     *
     * @param payload 8+ byte event payload from the history log record
     * @param pumpTimeSec raw pump timestamp (seconds since Tandem epoch)
     * @return CgmReading or null if the glucose value is invalid
     */
    fun parseCgmG7EventPayload(payload: ByteArray, pumpTimeSec: Long, limits: SafetyLimits = SafetyLimits()): CgmReading? {
        if (payload.size < 8) return null
        // Status byte at offset 2: 0x01 = valid reading. Reject others
        // (calibrating, sensor error, etc.) to avoid garbage glucose values.
        val status = payload[2].toInt() and 0xFF
        if (status != 1) return null
        val buf = ByteBuffer.wrap(payload, 6, 2).order(ByteOrder.LITTLE_ENDIAN)
        val glucoseMgDl = buf.short.toInt() and 0xFFFF
        if (glucoseMgDl < limits.minGlucoseMgDl || glucoseMgDl > limits.maxGlucoseMgDl) return null
        val timestamp = pumpTimeToInstant(pumpTimeSec)
        return CgmReading(
            glucoseMgDl = glucoseMgDl,
            trendArrow = CgmTrend.UNKNOWN, // trend not available from history
            timestamp = timestamp,
        )
    }

    /**
     * Extract CGM readings from a list of history log records.
     *
     * Filters for CGM event types (16: LidBgReadingTaken, 399: LidCgmDataG7),
     * decodes each record's base64 raw bytes, extracts the payload and pump
     * timestamp, and parses the glucose value.
     *
     * @param records list of history log records (any event types)
     * @return list of CgmReadings sorted by timestamp, empty if none found
     */
    fun extractCgmFromHistoryLogs(records: List<HistoryLogRecord>, limits: SafetyLimits = SafetyLimits()): List<CgmReading> {
        return records
            .filter { it.eventTypeId in CGM_EVENT_TYPES }
            .mapNotNull { record ->
                val rawBytes = Base64.decode(record.rawBytesB64, Base64.NO_WRAP)
                // Use the already-parsed pumpTimeSeconds from the record instead
                // of re-decoding it from raw bytes (avoids redundant work and
                // potential divergence if formats differ).
                val pumpTimeSec = record.pumpTimeSeconds
                // Extract the event data payload (starts at byte 10 in both formats)
                val payload: ByteArray = when {
                    rawBytes.size >= STREAM_RECORD_SIZE ->
                        rawBytes.copyOfRange(10, minOf(18, rawBytes.size))
                    rawBytes.size >= 18 ->
                        rawBytes.copyOfRange(10, 18)
                    else -> return@mapNotNull null
                }
                // Dispatch to the correct payload parser based on event type
                when (record.eventTypeId) {
                    EVENT_TYPE_CGM_DATA_G7 -> parseCgmG7EventPayload(payload, pumpTimeSec, limits)
                    else -> parseCgmEventPayload(payload, pumpTimeSec, limits)
                }
            }
            .sortedBy { it.timestamp }
    }

    // -- Bolus delivery extraction ------------------------------------------

    /**
     * Parse a bolus delivery event (type 280, LidBolusDelivery) from its
     * 16-byte data payload.
     *
     * Raw BLE payload layout (16 bytes, LE):
     *   bytes 0-1:   bolusId (uint16 LE)
     *   byte  2:     deliveryStatus (0=Completed, 1=Started)
     *   byte  3:     bolusType (bitmask: 0x08 = correction component)
     *   byte  4:     bolusSource (7=Algorithm/Control-IQ)
     *   byte  5:     remoteId
     *   bytes 6-7:   requestedNow (uint16 LE, milliunits)
     *   bytes 8-9:   correction portion (uint16 LE, milliunits)
     *   bytes 10-11: requestedLater (uint16 LE, extended bolus milliunits)
     *   bytes 12-13: reserved
     *   bytes 14-15: deliveredTotal (uint16 LE, milliunits)
     *
     * @param data 16-byte event data payload (bytes 10-25 of 26-byte record)
     * @param pumpTimeSec raw pump timestamp (seconds since Tandem epoch)
     * @return BolusEvent or null if status is not Completed or data is invalid
     */
    fun parseBolusDeliveryPayload(data: ByteArray, pumpTimeSec: Long, limits: SafetyLimits = SafetyLimits()): BolusEvent? {
        if (data.size < 16) return null

        val deliveryStatus = data[2].toInt() and 0xFF
        if (deliveryStatus != 0) return null // skip Started events

        val buf = ByteBuffer.wrap(data).order(ByteOrder.LITTLE_ENDIAN)
        val deliveredTotalMu = buf.getShort(14).toInt() and 0xFFFF
        if (deliveredTotalMu == 0) return null
        if (deliveredTotalMu > limits.maxBolusDoseMilliunits) return null

        val bolusTypeRaw = data[3].toInt() and 0xFF
        val bolusSourceRaw = data[4].toInt() and 0xFF
        val isCorrection = (bolusTypeRaw and 0x08) != 0
        // Only bolusSource=7 (Algorithm) means the system initiated the bolus.
        // A user-initiated meal bolus with a correction component is NOT automated.
        val isAutomated = bolusSourceRaw == 7

        return BolusEvent(
            units = deliveredTotalMu / 1000f,
            isAutomated = isAutomated,
            isCorrection = isCorrection,
            timestamp = pumpTimeToInstant(pumpTimeSec),
        )
    }

    /**
     * Extract bolus events from a list of history log records.
     *
     * Filters for event type 280 (LidBolusDelivery), decodes each record's
     * base64 raw bytes, extracts the 16-byte data payload, and parses the
     * bolus delivery fields.
     *
     * @param records list of history log records (any event types)
     * @return list of BolusEvents sorted by timestamp, empty if none found
     */
    fun extractBolusesFromHistoryLogs(records: List<HistoryLogRecord>, limits: SafetyLimits = SafetyLimits()): List<BolusEvent> {
        return records
            .filter { it.eventTypeId == EVENT_TYPE_BOLUS_DELIVERY }
            .mapNotNull { record ->
                val rawBytes = Base64.decode(record.rawBytesB64, Base64.NO_WRAP)
                if (rawBytes.size < STREAM_RECORD_SIZE) return@mapNotNull null
                val payload = rawBytes.copyOfRange(10, 26)
                parseBolusDeliveryPayload(payload, record.pumpTimeSeconds, limits)
            }
            .sortedBy { it.timestamp }
    }

    // -- Basal delivery extraction ------------------------------------------

    /**
     * Parse a basal delivery event (type 279, LidBasalDelivery) from its
     * 16-byte data payload.
     *
     * Raw BLE payload layout (16 bytes, LE):
     *   bytes 0-1: commandedRateSourceRaw (uint16 LE)
     *              0=Suspended, 1=Profile, 2=TempRate, 3=Algorithm, 4=Temp+Algorithm
     *   bytes 2-3: unknown
     *   bytes 4-5: profileBasalRate (uint16 LE, milliunits/hr)
     *   bytes 6-7: commandedRate (uint16 LE, milliunits/hr) -- actual delivery
     *   bytes 8-9: algorithmRate/tempRate (uint16 LE, milliunits/hr)
     *   bytes 10-15: padding
     *
     * @param data 16-byte event data payload (bytes 10-25 of 26-byte record)
     * @param pumpTimeSec raw pump timestamp (seconds since Tandem epoch)
     * @return BasalReading or null if data is invalid
     */
    fun parseBasalDeliveryPayload(data: ByteArray, pumpTimeSec: Long, limits: SafetyLimits = SafetyLimits()): BasalReading? {
        if (data.size < 8) return null

        val buf = ByteBuffer.wrap(data).order(ByteOrder.LITTLE_ENDIAN)
        val sourceRaw = buf.getShort(0).toInt() and 0xFFFF
        // Payload layout (16 bytes, LE):
        //   [0-1] commandedRateSourceRaw  [2-3] unknown
        //   [4-5] profileBasalRate        [6-7] commandedRate (actual delivery)
        //   [8-9] algorithmRate/tempRate   [10+] padding
        val commandedRateMu = buf.getShort(6).toInt() and 0xFFFF

        // Suspended basal (source=0) has rate=0 -- this is valid, don't reject.
        if (commandedRateMu > limits.maxBasalRateMilliunits) return null

        // Sources 0 (Suspended), 3 (Algorithm), 4 (Temp+Algorithm) are automated
        val isAutomated = sourceRaw in AUTOMATED_BASAL_SOURCES

        return BasalReading(
            rate = commandedRateMu / 1000f,
            isAutomated = isAutomated,
            controlIqMode = ControlIqMode.STANDARD, // mode not in history payload
            timestamp = pumpTimeToInstant(pumpTimeSec),
        )
    }

    /**
     * Extract basal delivery readings from a list of history log records.
     *
     * Filters for event type 279 (LidBasalDelivery), decodes each record's
     * base64 raw bytes, extracts the 16-byte data payload, and parses the
     * basal delivery fields.
     *
     * @param records list of history log records (any event types)
     * @return list of BasalReadings sorted by timestamp, empty if none found
     */
    fun extractBasalFromHistoryLogs(records: List<HistoryLogRecord>, limits: SafetyLimits = SafetyLimits()): List<BasalReading> {
        return records
            .filter { it.eventTypeId == EVENT_TYPE_BASAL_DELIVERY }
            .mapNotNull { record ->
                val rawBytes = Base64.decode(record.rawBytesB64, Base64.NO_WRAP)
                if (rawBytes.size < STREAM_RECORD_SIZE) return@mapNotNull null
                val payload = rawBytes.copyOfRange(10, 26)
                parseBasalDeliveryPayload(payload, record.pumpTimeSeconds, limits)
            }
            .sortedBy { it.timestamp }
    }

    /** Read a fixed-width string field, trimming trailing nulls and whitespace. */
    private fun readFixedString(data: ByteArray, offset: Int, length: Int): String {
        if (offset + length > data.size) return ""
        return String(data, offset, length, Charsets.UTF_8).trimEnd('\u0000', ' ')
    }

    /** Returns Pair(string, byteLength) or null on malformed data. */
    private fun readLengthPrefixedString(data: ByteArray, offset: Int): Pair<String, Int>? {
        if (offset + 4 > data.size) return null
        val buf = ByteBuffer.wrap(data, offset, 4).order(ByteOrder.LITTLE_ENDIAN)
        val len = buf.int
        if (len < 0 || offset + 4 + len > data.size) return null
        val str = String(data, offset + 4, len, Charsets.UTF_8)
        return Pair(str, len)
    }
}

/**
 * Parsed data from HomeScreenMirrorResponse for trend arrow and CIQ state.
 */
internal data class HomeScreenMirrorData(
    val trendArrow: CgmTrend,
    val basalStatusIconId: Int,
    val apControlStateIconId: Int,
)
