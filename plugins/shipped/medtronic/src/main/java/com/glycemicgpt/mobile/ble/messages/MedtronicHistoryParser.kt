/*
 * IDD history event-log parser for the Medtronic MiniMed 700-series read-only driver.
 *
 * Ported to Kotlin from OpenMinimed PythonPumpConnector `history_data.py` (HistoryData and its event
 * data classes) and `history_reader.py` (HistoryReader record framing), https://github.com/OpenMinimed,
 * GPL-3.0, used with the author's permission. Copyright (C) OpenMinimed contributors: palmarci
 * (Pal Marci), drfubar, Morten Fyhn Amundsen, Stenium; original medtronic-bt-decrypt PoC by
 * @planiitis. GlycemicGPT is itself GPL-3.0, so this is redistributed under the same license.
 *
 * READ-ONLY: this parses records the pump reports; it never constructs a write/control message. See
 * medtronic-ble-reverse-engineering.md Sec. 8.
 */
package com.glycemicgpt.mobile.ble.messages

import com.glycemicgpt.mobile.ble.read.MedtronicCodec
import com.glycemicgpt.mobile.ble.read.MedtronicReadException
import com.glycemicgpt.mobile.ble.read.stripIddE2e
import com.glycemicgpt.mobile.domain.model.BasalReading
import com.glycemicgpt.mobile.domain.model.BolusEvent
import com.glycemicgpt.mobile.domain.model.CgmReading
import com.glycemicgpt.mobile.domain.model.CgmTrend
import com.glycemicgpt.mobile.domain.model.HistoryLogRecord
import com.glycemicgpt.mobile.domain.model.PumpActivityMode
import com.glycemicgpt.mobile.domain.pump.SafetyLimits
import java.time.Instant
import java.time.LocalDateTime
import java.time.ZoneOffset
import java.util.Base64
import kotlin.math.roundToInt
import timber.log.Timber

/** Medtronic IDD history event types (`history_data.py` HistoryEventType). */
enum class MedtronicHistoryEventType(val id: Int) {
    REFERENCE_TIME(0x000F),
    BOLUS_PROGRAMMED_P1(0x005A),
    BOLUS_PROGRAMMED_P2(0x0066),
    BOLUS_DELIVERED_P1(0x0069),
    BOLUS_DELIVERED_P2(0x0096),
    DELIVERED_BASAL_RATE_CHANGED(0x0099),
    MAX_BOLUS_AMOUNT_CHANGED(0x03FC),
    AUTO_BASAL_DELIVERY(0xF001),
    CL1_TRANSITION(0xF002),
    THERAPY_CONTEXT(0xF004),
    MEAL(0xF005),
    BG_READING(0xF007),
    CALIBRATION_COMPLETE(0xF008),
    CALIBRATION_REJECTED(0xF009),
    INSULIN_DELIVERY_STOPPED(0xF00A),
    INSULIN_DELIVERY_RESTARTED(0xF00B),
    SG_MEASUREMENT(0xF00C),
    CGM_ANALYTICS_DATA_BACKFILL(0xF00D),
    NGP_REFERENCE_TIME(0xF00E),
    ANNUNCIATION_CLEARED(0xF00F),
    ANNUNCIATION_CONSOLIDATED(0xF010),
    MAX_AUTO_BASAL_RATE_CHANGED(0xF01A),
    UNDEFINED(0xFFFF),
    ;

    companion object {
        fun from(id: Int): MedtronicHistoryEventType = entries.firstOrNull { it.id == id } ?: UNDEFINED
    }
}

/** Bolus delivery activation (`history_data.py` BolusActivationType). COMMANDED = closed-loop/SmartGuard. */
enum class BolusActivationType(val raw: Int) {
    UNDETERMINED(0x0F),
    MANUAL(0x33),
    RECOMMENDED(0x3C),
    MANUALLY_CHANGED_RECOMMENDED(0x55),
    COMMANDED(0x5A),
    UNKNOWN(-1),
    ;

    companion object {
        fun from(raw: Int): BolusActivationType = entries.firstOrNull { it.raw == raw } ?: UNKNOWN
    }
}

/** Basal delivery context inside a history record (`history_data.py` BasalDeliveryContext). */
enum class HistoryBasalDeliveryContext(val raw: Int) {
    UNDETERMINED(0x0F),
    DEVICE_BASED(0x33),
    REMOTE_CONTROL(0x3C),
    ARTIFICIAL_PANCREAS_CONTROLLER(0x55),
    UNKNOWN(-1),
    ;

    companion object {
        fun from(raw: Int): HistoryBasalDeliveryContext = entries.firstOrNull { it.raw == raw } ?: UNKNOWN
    }
}

/** Typed event payload of a history record. [Unparsed] preserves any type we do not decode. */
sealed interface MedtronicHistoryEvent {
    /** Bolus programmed or delivered, part 1: amounts. [delivered] distinguishes delivered vs programmed. */
    data class BolusAmounts(
        val delivered: Boolean,
        val bolusId: Int,
        val fastIu: Double,
        val extendedIu: Double,
        val durationMin: Int,
    ) : MedtronicHistoryEvent

    /** Bolus programmed, part 2: delivery-reason flags (correction/meal) + activation type. */
    data class BolusProgrammedDetail(
        val isCorrection: Boolean,
        val isMeal: Boolean,
        val activationType: BolusActivationType?,
    ) : MedtronicHistoryEvent

    /** Bolus delivered, part 2: activation type (automated detection). */
    data class BolusDeliveredDetail(
        val activationType: BolusActivationType?,
    ) : MedtronicHistoryEvent

    /** A basal rate change; [context] = AP_CONTROLLER means SmartGuard drove it. */
    data class BasalRateChanged(
        val oldRateIuPerHour: Double,
        val newRateIuPerHour: Double,
        val context: HistoryBasalDeliveryContext?,
    ) : MedtronicHistoryEvent

    /** SmartGuard auto-basal micro-bolus -- see the mapping caveat in [extractBolusesFromHistoryLogs]. */
    data class AutoBasalMicroBolus(val bolusNumber: Int, val amountIu: Double) : MedtronicHistoryEvent

    /** Sensor glucose measurement; [sgValueRaw] may be a sentinel (see [SG_SENTINELS]). */
    data class SgMeasurement(val timeOffsetMin: Int, val sgValueRaw: Int) : MedtronicHistoryEvent

    /** Fingerstick BG reading / calibration BG, in mg/dL. */
    data class BgReading(val mgDl: Double, val calibration: Boolean, val accepted: Boolean) :
        MedtronicHistoryEvent

    /** Insulin delivery stopped (suspend) or restarted (resume); [reason] is the raw reason code. */
    data class InsulinDelivery(val stopped: Boolean, val reason: Int) : MedtronicHistoryEvent

    /**
     * Pump annunciation: alarms, alerts, and cartridge/battery events (low reservoir, low battery, ...).
     *
     * Two encodings share this type, distinguished by [statusRaw]:
     * - **Consolidated** (`ANNUNCIATION_CONSOLIDATED`): [annunciationType] is the `& 0x0FFF`-masked
     *   type, [statusRaw] is the pump annunciation status, [timestamp] is set.
     * - **Cleared** (`ANNUNCIATION_CLEARED`): [annunciationType] is the raw 16-bit fault type,
     *   [statusRaw] is [CLEARED_NO_STATUS] (a cleared event carries no status), [timestamp] is null.
     */
    data class Annunciation(
        val annunciationType: Int,
        val statusRaw: Int,
        val timestamp: Instant?,
    ) : MedtronicHistoryEvent {
        /** True when this is a "cleared" annunciation (raw fault type, no status, no timestamp). */
        val cleared: Boolean get() = statusRaw == CLEARED_NO_STATUS

        companion object {
            /** [statusRaw] sentinel marking a cleared annunciation that carries no status field. */
            const val CLEARED_NO_STATUS = -1
        }
    }

    /** NGP reference time anchoring the relative offsets of following records to wall-clock time. */
    data class ReferenceTime(val time: Instant?) : MedtronicHistoryEvent

    /** Any event type not individually decoded; the raw bytes are still preserved on the record. */
    object Unparsed : MedtronicHistoryEvent
}

/**
 * A parsed history record: its sequence number, type, relative offset, and typed [event] payload.
 * The raw bytes are preserved separately as a [HistoryLogRecord] for dedup/backfill (see
 * [toHistoryLogRecord]).
 */
data class MedtronicHistoryRecord(
    val sequenceNumber: Int,
    val eventType: MedtronicHistoryEventType,
    val relativeOffsetSeconds: Int,
    val event: MedtronicHistoryEvent,
)

/**
 * Parses Medtronic IDD history-data records (decrypted by the C1 framework) into typed events and the
 * shared [HistoryLogRecord] raw-preservation shape, and extracts CGM / bolus / basal domain models.
 *
 * **Record framing & timestamps.** Each record's header is `event_type(u16) seq(u32) offset(u16)`
 * followed by the event body, optionally wrapped in the Medtronic E2E trailer. Records carry only a
 * relative offset; absolute time is resolved against the most recent [MedtronicHistoryEventType.NGP_REFERENCE_TIME]
 * record (interpreted as UTC -- timezone handling is a Milestone D concern). Events before any
 * reference are dropped (and counted) rather than mis-timestamped. Over-the-air behavior rides with
 * 48.A2; nothing here is claimed live-verified.
 */
object MedtronicHistoryParser {

    /** Header: event_type(2) + sequence(4) + relative_offset(2). */
    private const val HEADER_SIZE = 8

    /** Sensor-glucose sentinel values that are not real mg/dL (`SGMeasurementData.__str__`). */
    val SG_SENTINELS = setOf(0x0301, 0x0303, 0x030D)

    private const val ANNUNCIATION_TYPE_TAG = 0xF000

    /** Pump annunciation timestamps are seconds since 2000-01-01T00:00:00Z. */
    private val MEDTRONIC_EPOCH_2000: Instant = Instant.parse("2000-01-01T00:00:00Z")

    // -- Raw preservation ---------------------------------------------------

    /**
     * Convert a decrypted raw history record into the shared [HistoryLogRecord] (raw bytes base64'd,
     * mirroring Tandem's `RawHistoryLog`) for dedup/backfill, or `null` if it is too short to carry a
     * header. [pumpTimeSeconds] holds the record's raw relative offset in seconds (the pump emits no
     * absolute per-record time; absolute resolution via the reference-time event is done at extraction).
     */
    fun toHistoryLogRecord(raw: ByteArray, useE2e: Boolean): HistoryLogRecord? {
        val body =
            try {
                stripIddE2e(raw, useE2e)
            } catch (e: MedtronicReadException) {
                Timber.w(e, "Dropping history record with bad E2E trailer")
                return null
            }
        if (body.size < HEADER_SIZE) {
            Timber.w("Dropping history record shorter than header: %d bytes", body.size)
            return null
        }
        val eventTypeId = MedtronicCodec.readUIntLe(body, 0, 2)
        val sequence = MedtronicCodec.readULongLe(body, 2, 4)
        val relativeOffset = MedtronicCodec.readUIntLe(body, 6, 2)
        // HistoryLogRecord.sequenceNumber is a signed Int by platform convention (PumpModels.kt notes
        // current pump sequence values are ~1.3M, well inside Int range). Preserve the E2E-stripped
        // body, not the wrapped frame, so the base64 round-trips back to the bytes the parser expects.
        return HistoryLogRecord(
            sequenceNumber = sequence.toInt(),
            rawBytesB64 = Base64.getEncoder().encodeToString(body),
            eventTypeId = eventTypeId,
            pumpTimeSeconds = relativeOffset.toLong(),
        )
    }

    /** Distinct records by sequence number (keeping the first seen), for paged-read dedup/backfill. */
    fun dedupBySequence(records: List<HistoryLogRecord>): List<HistoryLogRecord> =
        records.distinctBy { it.sequenceNumber }

    // -- Typed record parsing -----------------------------------------------

    /**
     * Parse one decrypted history record body (already E2E-stripped; pass the [HistoryLogRecord.rawBytesB64]
     * bytes) into a [MedtronicHistoryRecord], or `null` if the header is malformed. An event body that
     * cannot be decoded is preserved as [MedtronicHistoryEvent.Unparsed] rather than dropping the record.
     */
    fun parseRecordBody(body: ByteArray): MedtronicHistoryRecord? {
        if (body.size < HEADER_SIZE) return null
        val eventTypeId = MedtronicCodec.readUIntLe(body, 0, 2)
        val sequence = MedtronicCodec.readULongLe(body, 2, 4).toInt()
        val relativeOffset = MedtronicCodec.readUIntLe(body, 6, 2)
        val type = MedtronicHistoryEventType.from(eventTypeId)
        val payload = body.copyOfRange(HEADER_SIZE, body.size)
        // Narrow to the decode failures the per-type parsers actually raise (require -> IAE; field/CRC
        // checks -> MedtronicReadException). A broader catch would mask programming errors as bad data.
        val event =
            try {
                parseEvent(type, payload)
            } catch (e: MedtronicReadException) {
                Timber.w(e, "Unparseable %s event body; preserving raw", type)
                MedtronicHistoryEvent.Unparsed
            } catch (e: IllegalArgumentException) {
                Timber.w(e, "Unparseable %s event body; preserving raw", type)
                MedtronicHistoryEvent.Unparsed
            }
        return MedtronicHistoryRecord(sequence, type, relativeOffset, event)
    }

    private fun parseEvent(type: MedtronicHistoryEventType, p: ByteArray): MedtronicHistoryEvent =
        when (type) {
            MedtronicHistoryEventType.BOLUS_PROGRAMMED_P1 -> bolusAmounts(p, delivered = false)
            MedtronicHistoryEventType.BOLUS_DELIVERED_P1 -> bolusAmounts(p, delivered = true)
            MedtronicHistoryEventType.BOLUS_PROGRAMMED_P2 -> bolusProgrammedDetail(p)
            MedtronicHistoryEventType.BOLUS_DELIVERED_P2 -> bolusDeliveredDetail(p)
            MedtronicHistoryEventType.DELIVERED_BASAL_RATE_CHANGED -> basalRateChanged(p)
            MedtronicHistoryEventType.AUTO_BASAL_DELIVERY -> autoBasalMicroBolus(p)
            MedtronicHistoryEventType.SG_MEASUREMENT -> sgMeasurement(p)
            MedtronicHistoryEventType.BG_READING -> bgReading(p, calibration = false, accepted = true)
            MedtronicHistoryEventType.CALIBRATION_COMPLETE -> bgReading(p, calibration = true, accepted = true)
            MedtronicHistoryEventType.CALIBRATION_REJECTED -> bgReading(p, calibration = true, accepted = false)
            MedtronicHistoryEventType.INSULIN_DELIVERY_STOPPED -> insulinDelivery(p, stopped = true)
            MedtronicHistoryEventType.INSULIN_DELIVERY_RESTARTED -> insulinDelivery(p, stopped = false)
            MedtronicHistoryEventType.ANNUNCIATION_CONSOLIDATED -> annunciation(p)
            MedtronicHistoryEventType.ANNUNCIATION_CLEARED -> annunciationCleared(p)
            MedtronicHistoryEventType.NGP_REFERENCE_TIME -> referenceTime(p)
            else -> MedtronicHistoryEvent.Unparsed
        }

    private fun bolusAmounts(p: ByteArray, delivered: Boolean): MedtronicHistoryEvent {
        // bolus_id(2) type(1) fast f32(4) extended f32(4) duration(2)
        require(p.size >= 13) { "bolus amounts body too short: ${p.size}" }
        return MedtronicHistoryEvent.BolusAmounts(
            delivered = delivered,
            bolusId = MedtronicCodec.readUIntLe(p, 0, 2),
            fastIu = MedtronicCodec.decodeMedFloat32(MedtronicCodec.readULongLe(p, 3, 4)),
            extendedIu = MedtronicCodec.decodeMedFloat32(MedtronicCodec.readULongLe(p, 7, 4)),
            durationMin = MedtronicCodec.readUIntLe(p, 11, 2),
        )
    }

    private fun bolusProgrammedDetail(p: ByteArray): MedtronicHistoryEvent {
        require(p.isNotEmpty()) { "bolus programmed P2 body empty" }
        val flags = MedtronicCodec.readUIntLe(p, 0, 1)
        var offset = 1
        fun consume(n: Int): Int {
            require(offset + n <= p.size) { "bolus programmed P2 truncated" }
            return MedtronicCodec.readUIntLe(p, offset, n).also { offset += n }
        }
        if (flags and BOLUS_DELAY_TIME_PRESENT != 0) consume(2)
        if (flags and BOLUS_TEMPLATE_NUMBER_PRESENT != 0) consume(1)
        val activation =
            if (flags and BOLUS_ACTIVATION_TYPE_PRESENT != 0) BolusActivationType.from(consume(1)) else null
        return MedtronicHistoryEvent.BolusProgrammedDetail(
            isCorrection = flags and BOLUS_DELIVERY_REASON_CORRECTION != 0,
            isMeal = flags and BOLUS_DELIVERY_REASON_MEAL != 0,
            activationType = activation,
        )
    }

    private fun bolusDeliveredDetail(p: ByteArray): MedtronicHistoryEvent {
        // flags(1) start_time_offset(4) [activation(1)] [end_reason(1)] [annunciation_id(2)]
        require(p.size >= 5) { "bolus delivered P2 body too short: ${p.size}" }
        val flags = MedtronicCodec.readUIntLe(p, 0, 1)
        var offset = 5
        fun consume(n: Int): Int {
            require(offset + n <= p.size) { "bolus delivered P2 truncated" }
            return MedtronicCodec.readUIntLe(p, offset, n).also { offset += n }
        }
        val activation =
            if (flags and BOLUS_ACTIVATION_TYPE_PRESENT_DELIVERED != 0) BolusActivationType.from(consume(1)) else null
        // bolus_id is not in the delivered-P2 body; correlation back to P1 is by sequence adjacency.
        return MedtronicHistoryEvent.BolusDeliveredDetail(activationType = activation)
    }

    private fun basalRateChanged(p: ByteArray): MedtronicHistoryEvent {
        // flags(1) old f32(4) new f32(4) [context(1)]
        require(p.size >= 9) { "basal-rate-changed body too short: ${p.size}" }
        val flags = MedtronicCodec.readUIntLe(p, 0, 1)
        val context =
            if (flags and BASAL_DELIVERY_CONTEXT_PRESENT != 0 && p.size >= 10) {
                HistoryBasalDeliveryContext.from(MedtronicCodec.readUIntLe(p, 9, 1))
            } else {
                null
            }
        return MedtronicHistoryEvent.BasalRateChanged(
            oldRateIuPerHour = MedtronicCodec.decodeMedFloat32(MedtronicCodec.readULongLe(p, 1, 4)),
            newRateIuPerHour = MedtronicCodec.decodeMedFloat32(MedtronicCodec.readULongLe(p, 5, 4)),
            context = context,
        )
    }

    private fun autoBasalMicroBolus(p: ByteArray): MedtronicHistoryEvent {
        require(p.size >= 5) { "auto-basal micro-bolus body too short: ${p.size}" }
        return MedtronicHistoryEvent.AutoBasalMicroBolus(
            bolusNumber = MedtronicCodec.readUIntLe(p, 0, 1),
            amountIu = MedtronicCodec.decodeMedFloat32(MedtronicCodec.readULongLe(p, 1, 4)),
        )
    }

    private fun sgMeasurement(p: ByteArray): MedtronicHistoryEvent {
        // time_offset i16, sg u16, isig u16, v_counter i16
        require(p.size >= 8) { "SG measurement body too short: ${p.size}" }
        return MedtronicHistoryEvent.SgMeasurement(
            timeOffsetMin = MedtronicCodec.signExtend(MedtronicCodec.readUIntLe(p, 0, 2), 16),
            sgValueRaw = MedtronicCodec.readUIntLe(p, 2, 2),
        )
    }

    private fun bgReading(p: ByteArray, calibration: Boolean, accepted: Boolean): MedtronicHistoryEvent {
        // time_offset i16, bg f16 (kg/L); mg/dL = 1e5 * kg/L (ValueConverter.kgl_to_mgdl)
        require(p.size >= 4) { "BG reading body too short: ${p.size}" }
        val bgKgL = MedtronicCodec.decodeMedFloat16(MedtronicCodec.readUIntLe(p, 2, 2))
        return MedtronicHistoryEvent.BgReading(mgDl = bgKgL * 1e5, calibration = calibration, accepted = accepted)
    }

    private fun insulinDelivery(p: ByteArray, stopped: Boolean): MedtronicHistoryEvent {
        require(p.isNotEmpty()) { "insulin-delivery body empty" }
        return MedtronicHistoryEvent.InsulinDelivery(stopped = stopped, reason = MedtronicCodec.readUIntLe(p, 0, 1))
    }

    private fun annunciation(p: ByteArray): MedtronicHistoryEvent {
        // event_flags(1) annunciation_id(2) type(2) status(1) timestamp(4)
        require(p.size >= 10) { "annunciation body too short: ${p.size}" }
        val typeRaw = MedtronicCodec.readUIntLe(p, 3, 2)
        if (typeRaw and 0xF000 != ANNUNCIATION_TYPE_TAG) {
            throw MedtronicReadException("Unknown annunciation type 0x%04x".format(typeRaw))
        }
        val status = MedtronicCodec.readUIntLe(p, 5, 1)
        val seconds = MedtronicCodec.readULongLe(p, 6, 4)
        return MedtronicHistoryEvent.Annunciation(
            annunciationType = typeRaw and 0x0FFF,
            statusRaw = status,
            timestamp = MEDTRONIC_EPOCH_2000.plusSeconds(seconds),
        )
    }

    private fun annunciationCleared(p: ByteArray): MedtronicHistoryEvent {
        require(p.size >= 4) { "annunciation-cleared body too short: ${p.size}" }
        return MedtronicHistoryEvent.Annunciation(
            annunciationType = MedtronicCodec.readUIntLe(p, 0, 2),
            statusRaw = MedtronicHistoryEvent.Annunciation.CLEARED_NO_STATUS,
            timestamp = null,
        )
    }

    private fun referenceTime(p: ByteArray): MedtronicHistoryEvent {
        // recording_reason(1) then datetime(7): year u16, month, day, hour, min, sec
        require(p.size >= 8) { "reference-time body too short: ${p.size}" }
        val time =
            try {
                LocalDateTime.of(
                    MedtronicCodec.readUIntLe(p, 1, 2), // year
                    MedtronicCodec.readUIntLe(p, 3, 1), // month
                    MedtronicCodec.readUIntLe(p, 4, 1), // day
                    MedtronicCodec.readUIntLe(p, 5, 1), // hour
                    MedtronicCodec.readUIntLe(p, 6, 1), // minute
                    MedtronicCodec.readUIntLe(p, 7, 1), // second
                ).toInstant(ZoneOffset.UTC)
            } catch (e: java.time.DateTimeException) {
                Timber.w(e, "Invalid reference-time datetime; offsets after it cannot be anchored")
                null
            }
        return MedtronicHistoryEvent.ReferenceTime(time)
    }

    // -- Domain extraction (consumed by the C3 capability delegates) --------

    /**
     * Each parsed record paired with its resolved absolute timestamp, walking [records] in sequence
     * order and carrying the most recent reference time forward (mirrors `history_data.py`'s `ref_time`
     * tracking). Records seen before any reference time, or whose body fails to parse, are dropped (and
     * counted in a debug log) rather than mis-timestamped.
     */
    private fun timedRecords(records: List<HistoryLogRecord>): List<Pair<MedtronicHistoryRecord, Instant>> {
        val sorted = records.sortedBy { it.sequenceNumber }
        var reference: Instant? = null
        var droppedNoReference = 0
        val out = ArrayList<Pair<MedtronicHistoryRecord, Instant>>(sorted.size)
        for (record in sorted) {
            val body = Base64.getDecoder().decode(record.rawBytesB64)
            val parsed = parseRecordBody(body) ?: continue
            val event = parsed.event
            if (event is MedtronicHistoryEvent.ReferenceTime) {
                event.time?.let { reference = it }
                continue
            }
            val ref = reference
            if (ref == null) {
                droppedNoReference++
                continue
            }
            out += parsed to ref.plusSeconds(parsed.relativeOffsetSeconds.toLong())
        }
        if (droppedNoReference > 0) {
            Timber.d("Dropped %d history record(s) with no preceding reference time", droppedNoReference)
        }
        return out
    }

    /**
     * Extract CGM readings from [records] (event type SG_MEASUREMENT). Sentinel SG values
     * ([SG_SENTINELS]) and any reading outside [limits] are dropped, never clamped. Trend is
     * [CgmTrend.UNKNOWN]: the SG history record carries no rate of change.
     */
    fun extractCgmFromHistoryLogs(
        records: List<HistoryLogRecord>,
        limits: SafetyLimits = SafetyLimits(),
    ): List<CgmReading> =
        timedRecords(records)
            .mapNotNull { (record, time) ->
                val event = record.event as? MedtronicHistoryEvent.SgMeasurement ?: return@mapNotNull null
                val mgDl = event.sgValueRaw
                if (mgDl in SG_SENTINELS) return@mapNotNull null
                if (mgDl < limits.minGlucoseMgDl || mgDl > limits.maxGlucoseMgDl) return@mapNotNull null
                CgmReading(glucoseMgDl = mgDl, trendArrow = CgmTrend.UNKNOWN, timestamp = time)
            }
            .sortedBy { it.timestamp }

    /**
     * Extract delivered boluses from [records] (event type BOLUS_DELIVERED_P1), enriched by the
     * adjacent BOLUS_DELIVERED_P2 (activation type) and the matching BOLUS_PROGRAMMED_P2
     * (correction/meal reason, by bolus id). Boluses exceeding [SafetyLimits.maxBolusDoseMilliunits]
     * are dropped, never clamped.
     *
     * **SmartGuard micro-boluses excluded (known nuance, AC5 / Medtronic Connect open item).** The
     * `AUTO_BASAL_DELIVERY` auto-correction micro-boluses (770G/780G) are *not* mapped to bolus events
     * here: how they should be attributed (bolus vs. basal, double-count risk) is unresolved without
     * live validation, so they are counted and logged rather than guessed. `TODO(48.A2)`.
     */
    fun extractBolusesFromHistoryLogs(
        records: List<HistoryLogRecord>,
        limits: SafetyLimits = SafetyLimits(),
    ): List<BolusEvent> {
        val timed = timedRecords(records)
        // Correction/meal reason lives in the programmed-P2 record, keyed by bolus id from programmed-P1.
        // Pair each programmed-P1 (id) with the programmed-P2 that immediately follows it in sequence.
        val sortedRecords = timed.map { it.first }
        val reasonByBolusId = HashMap<Int, MedtronicHistoryEvent.BolusProgrammedDetail>()
        var pendingProgrammedId: Int? = null
        for (r in sortedRecords) {
            when (val e = r.event) {
                is MedtronicHistoryEvent.BolusAmounts ->
                    if (!e.delivered) pendingProgrammedId = e.bolusId
                is MedtronicHistoryEvent.BolusProgrammedDetail -> {
                    pendingProgrammedId?.let { reasonByBolusId[it] = e }
                    pendingProgrammedId = null
                }
                else -> Unit
            }
        }

        var droppedMicroBoluses = 0
        val result =
            timed.mapIndexedNotNull { index, (record, time) ->
                val amounts = record.event as? MedtronicHistoryEvent.BolusAmounts ?: run {
                    if (record.event is MedtronicHistoryEvent.AutoBasalMicroBolus) droppedMicroBoluses++
                    return@mapIndexedNotNull null
                }
                if (!amounts.delivered) return@mapIndexedNotNull null

                val totalIu = amounts.fastIu + amounts.extendedIu
                if (!totalIu.isFinite() || totalIu < 0.0) return@mapIndexedNotNull null
                val milliunits = (totalIu * 1000.0).roundToInt()
                if (milliunits > limits.maxBolusDoseMilliunits) return@mapIndexedNotNull null
                // BolusEvent's own init caps units at MAX_BOLUS_UNITS; the limits check above already
                // guards it, but a configured limit looser than the hard cap would still throw -- so
                // skip rather than construct an out-of-cap event.
                if (totalIu > BolusEvent.MAX_BOLUS_UNITS) return@mapIndexedNotNull null

                // Activation type comes from the delivered-P2 that immediately follows this delivered-P1.
                // This positional correlation is a best-effort heuristic: if a record is dropped or
                // interleaved between the P1 and its P2, the join misses and the bolus degrades to
                // manual/non-correction rather than failing. Tolerated for this read-only, not-yet-live
                // slice -- the whole bolus mapping is TODO(48.A2).
                val deliveredDetail =
                    sortedRecords.getOrNull(index + 1)?.event as? MedtronicHistoryEvent.BolusDeliveredDetail
                val automated = deliveredDetail?.activationType == BolusActivationType.COMMANDED
                val reason = reasonByBolusId[amounts.bolusId]
                val isCorrection = reason?.isCorrection == true
                val isMeal = reason?.isMeal == true
                // Medtronic reports only the delivered total, with no numeric correction/meal split.
                // Attribute the whole amount to the single indicated reason; leave both 0 when neither
                // (or both) reasons are set, since the split is then unknown.
                val correctionUnits = if (isCorrection && !isMeal) totalIu.toFloat() else 0f
                val mealUnits = if (isMeal && !isCorrection) totalIu.toFloat() else 0f

                BolusEvent(
                    units = totalIu.toFloat(),
                    isAutomated = automated,
                    isCorrection = isCorrection,
                    correctionUnits = correctionUnits,
                    mealUnits = mealUnits,
                    timestamp = time,
                )
            }
        if (droppedMicroBoluses > 0) {
            Timber.d(
                "Excluded %d SmartGuard auto-basal micro-bolus event(s) from bolus history (TODO(48.A2))",
                droppedMicroBoluses,
            )
        }
        return result.sortedBy { it.timestamp }
    }

    /**
     * Extract basal-rate changes from [records] (event type DELIVERED_BASAL_RATE_CHANGED). The new
     * rate is reported; an AP-controller delivery context marks it automated (SmartGuard, 770G/780G).
     * Rates exceeding [SafetyLimits.maxBasalRateMilliunits] are dropped, never clamped.
     */
    fun extractBasalFromHistoryLogs(
        records: List<HistoryLogRecord>,
        limits: SafetyLimits = SafetyLimits(),
    ): List<BasalReading> =
        timedRecords(records)
            .mapNotNull { (record, time) ->
                val event = record.event as? MedtronicHistoryEvent.BasalRateChanged ?: return@mapNotNull null
                val rate = event.newRateIuPerHour
                if (!rate.isFinite() || rate < 0.0) return@mapNotNull null
                if ((rate * 1000.0).roundToInt() > limits.maxBasalRateMilliunits) return@mapNotNull null
                BasalReading(
                    rate = rate.toFloat(),
                    isAutomated = event.context == HistoryBasalDeliveryContext.ARTIFICIAL_PANCREAS_CONTROLLER,
                    activityMode = PumpActivityMode.NONE,
                    timestamp = time,
                )
            }
            .sortedBy { it.timestamp }

    // Bolus P2 flag bits (history_data.py BolusFlag for programmed; BolusDeliveredP2Data.Flag for delivered).
    private const val BOLUS_DELAY_TIME_PRESENT = 1 shl 0
    private const val BOLUS_TEMPLATE_NUMBER_PRESENT = 1 shl 1
    private const val BOLUS_ACTIVATION_TYPE_PRESENT = 1 shl 2
    private const val BOLUS_DELIVERY_REASON_CORRECTION = 1 shl 3
    private const val BOLUS_DELIVERY_REASON_MEAL = 1 shl 4

    // Delivered-P2 has its own flag layout: activation-type present is bit 0 there.
    private const val BOLUS_ACTIVATION_TYPE_PRESENT_DELIVERED = 1 shl 0

    private const val BASAL_DELIVERY_CONTEXT_PRESENT = 1 shl 0
}
