package com.glycemicgpt.weardevice.data

import android.content.Context
import android.content.SharedPreferences
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import timber.log.Timber

object WatchDataRepository {

    private const val PREFS_NAME = "watch_data_cache"
    private const val KEY_CGM_HISTORY = "cgm_history"
    private const val KEY_CURRENT_CGM = "current_cgm"
    private const val KEY_CURRENT_IOB = "current_iob"

    private var prefs: SharedPreferences? = null

    @Synchronized
    fun init(context: Context) {
        if (prefs != null) return
        prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
        if (_cgmHistory.value.isEmpty()) restoreCgmHistory()
        if (_cgm.value == null) restoreCurrentCgm()
        if (_iob.value == null) restoreCurrentIoB()
        Timber.d("WatchDataRepository initialized with persisted data")
    }

    data class IoBState(
        val iob: Float,
        val timestampMs: Long,
    )

    data class CgmState(
        val mgDl: Int,
        val trend: String,
        val timestampMs: Long,
        val low: Int,
        val high: Int,
        val urgentLow: Int,
        val urgentHigh: Int,
    )

    data class AlertState(
        val type: String,
        val bgValue: Int,
        val timestampMs: Long,
        val message: String,
    )

    sealed class ChatState {
        data object Idle : ChatState()
        data object Loading : ChatState()
        data class Success(val response: String, val disclaimer: String) : ChatState()
        data class Error(val message: String) : ChatState()
    }

    data class BasalHistoryRecord(
        val rate: Float,
        val timestampMs: Long,
        val isAutomated: Boolean,
        val activityMode: Int, // 0=NONE, 1=SLEEP, 2=EXERCISE
    )

    data class BolusHistoryRecord(
        val units: Float,
        val correctionUnits: Float,
        val mealUnits: Float,
        val timestampMs: Long,
        val isAutomated: Boolean,
        val isCorrection: Boolean,
        val category: String = "",
    )

    data class IoBHistoryRecord(
        val iob: Float,
        val timestampMs: Long,
    )

    data class WatchFaceConfigState(
        val showIoB: Boolean = true,
        val showGraph: Boolean = true,
        val showAlert: Boolean = true,
        val showSeconds: Boolean = false,
        val graphRangeHours: Int = 3,
        val theme: String = "dark",
        val showBasalOverlay: Boolean = true,
        val showBolusMarkers: Boolean = true,
        val showIoBOverlay: Boolean = true,
        val showModeBands: Boolean = true,
        val aiTtsEnabled: Boolean = false,
        val aiTtsVoice: String = "",
    )

    private val _iob = MutableStateFlow<IoBState?>(null)
    val iob: StateFlow<IoBState?> = _iob.asStateFlow()

    private val _cgm = MutableStateFlow<CgmState?>(null)
    val cgm: StateFlow<CgmState?> = _cgm.asStateFlow()

    /** Circular buffer of recent CGM readings for sparkline graph (up to 6 hours at 5-min intervals). */
    private val _cgmHistory = MutableStateFlow<List<CgmState>>(emptyList())
    val cgmHistory: StateFlow<List<CgmState>> = _cgmHistory.asStateFlow()

    private const val MAX_CGM_HISTORY = 72 // 6 hours at 5-min intervals
    private const val DEDUP_WINDOW_MS = 30_000L // 30-second proximity window for timestamp dedup

    private val _basalHistory = MutableStateFlow<List<BasalHistoryRecord>>(emptyList())
    val basalHistory: StateFlow<List<BasalHistoryRecord>> = _basalHistory.asStateFlow()

    private val _bolusHistory = MutableStateFlow<List<BolusHistoryRecord>>(emptyList())
    val bolusHistory: StateFlow<List<BolusHistoryRecord>> = _bolusHistory.asStateFlow()

    private val _iobHistory = MutableStateFlow<List<IoBHistoryRecord>>(emptyList())
    val iobHistory: StateFlow<List<IoBHistoryRecord>> = _iobHistory.asStateFlow()

    private val _alert = MutableStateFlow<AlertState?>(null)
    val alert: StateFlow<AlertState?> = _alert.asStateFlow()

    private val _chatState = MutableStateFlow<ChatState>(ChatState.Idle)
    val chatState: StateFlow<ChatState> = _chatState.asStateFlow()

    private val _categoryLabels = MutableStateFlow<Map<String, String>>(emptyMap())
    val categoryLabels: StateFlow<Map<String, String>> = _categoryLabels.asStateFlow()

    private val _watchFaceConfig = MutableStateFlow(WatchFaceConfigState())
    val watchFaceConfig: StateFlow<WatchFaceConfigState> = _watchFaceConfig.asStateFlow()

    fun updateIoB(iob: Float, timestampMs: Long) {
        _iob.value = IoBState(iob, timestampMs)
        persistCurrentIoB()
    }

    fun updateCgm(
        mgDl: Int,
        trend: String,
        timestampMs: Long,
        low: Int,
        high: Int,
        urgentLow: Int,
        urgentHigh: Int,
    ) {
        val state = CgmState(mgDl, trend, timestampMs, low, high, urgentLow, urgentHigh)
        _cgm.value = state
        persistCurrentCgm()

        // Atomically append to history buffer, dedup by timestamp proximity, keep most recent
        _cgmHistory.update { current ->
            val isDuplicate = current.any {
                kotlin.math.abs(it.timestampMs - timestampMs) < DEDUP_WINDOW_MS
            }
            if (isDuplicate) {
                current
            } else {
                val updated = current + state
                if (updated.size > MAX_CGM_HISTORY) {
                    updated.drop(updated.size - MAX_CGM_HISTORY)
                } else {
                    updated
                }
            }
        }
        persistCgmHistory()
    }

    fun updateBasalHistory(records: List<BasalHistoryRecord>) {
        _basalHistory.value = records
    }

    fun updateBolusHistory(records: List<BolusHistoryRecord>) {
        _bolusHistory.value = records
    }

    fun updateIoBHistory(records: List<IoBHistoryRecord>) {
        _iobHistory.value = records
    }

    fun updateAlert(type: String, bgValue: Int, timestampMs: Long, message: String) {
        _alert.value = if (type == "none") null else AlertState(type, bgValue, timestampMs, message)
    }

    fun clearAlert() {
        _alert.value = null
    }

    fun setChatResponse(response: String, disclaimer: String) {
        _chatState.value = ChatState.Success(response, disclaimer)
    }

    fun setChatLoading() {
        _chatState.value = ChatState.Loading
    }

    fun setChatError(error: String) {
        _chatState.value = ChatState.Error(error)
    }

    fun clearChat() {
        _chatState.value = ChatState.Idle
    }

    fun updateCategoryLabels(labels: Map<String, String>) {
        _categoryLabels.value = labels
    }

    private val VALID_GRAPH_RANGES = setOf(1, 3, 6)
    private val VALID_THEMES = setOf("dark", "clinical_blue", "high_contrast")

    fun updateWatchFaceConfig(
        showIoB: Boolean,
        showGraph: Boolean,
        showAlert: Boolean,
        showSeconds: Boolean,
        graphRangeHours: Int,
        theme: String,
        showBasalOverlay: Boolean = true,
        showBolusMarkers: Boolean = true,
        showIoBOverlay: Boolean = true,
        showModeBands: Boolean = true,
        aiTtsEnabled: Boolean = false,
        aiTtsVoice: String = "",
    ) {
        _watchFaceConfig.value = WatchFaceConfigState(
            showIoB = showIoB,
            showGraph = showGraph,
            showAlert = showAlert,
            showSeconds = showSeconds,
            graphRangeHours = if (graphRangeHours in VALID_GRAPH_RANGES) graphRangeHours else 3,
            theme = if (theme in VALID_THEMES) theme else "dark",
            showBasalOverlay = showBasalOverlay,
            showBolusMarkers = showBolusMarkers,
            showIoBOverlay = showIoBOverlay,
            showModeBands = showModeBands,
            aiTtsEnabled = aiTtsEnabled,
            aiTtsVoice = aiTtsVoice,
        )
    }

    // --- Persistence helpers (SharedPreferences, survives process kill) ---

    /**
     * Serialize cgmHistory to a compact string: "ts,mgDl,trend,low,high,uLow,uHigh;..."
     * No JSON library -- just string concat for minimal overhead on every 15s update.
     */
    private fun persistCgmHistory() {
        val p = prefs ?: return
        val history = _cgmHistory.value
        if (history.isEmpty()) {
            p.edit().remove(KEY_CGM_HISTORY).apply()
            return
        }
        val sb = StringBuilder(history.size * 40) // pre-size ~40 chars per record
        history.forEachIndexed { i, r ->
            if (i > 0) sb.append(';')
            sb.append(r.timestampMs).append(',')
                .append(r.mgDl).append(',')
                .append(r.trend).append(',')
                .append(r.low).append(',')
                .append(r.high).append(',')
                .append(r.urgentLow).append(',')
                .append(r.urgentHigh)
        }
        p.edit().putString(KEY_CGM_HISTORY, sb.toString()).apply()
    }

    private fun restoreCgmHistory() {
        val p = prefs ?: return
        val raw = p.getString(KEY_CGM_HISTORY, null) ?: return
        try {
            val records = raw.split(';').mapNotNull { record ->
                val parts = record.split(',')
                if (parts.size < 7) return@mapNotNull null
                CgmState(
                    timestampMs = parts[0].toLong(),
                    mgDl = parts[1].toInt(),
                    trend = parts[2],
                    low = parts[3].toInt(),
                    high = parts[4].toInt(),
                    urgentLow = parts[5].toInt(),
                    urgentHigh = parts[6].toInt(),
                )
            }
            if (records.isNotEmpty()) {
                _cgmHistory.value = records.takeLast(MAX_CGM_HISTORY)
                Timber.d("Restored %d CGM history records from cache", records.size)
            }
        } catch (e: Exception) {
            Timber.w(e, "Failed to restore CGM history from cache")
            p.edit().remove(KEY_CGM_HISTORY).apply()
        }
    }

    /**
     * Persist current CGM reading: "ts,mgDl,trend,low,high,uLow,uHigh"
     */
    private fun persistCurrentCgm() {
        val p = prefs ?: return
        val state = _cgm.value
        if (state == null) {
            p.edit().remove(KEY_CURRENT_CGM).apply()
            return
        }
        val s = "${state.timestampMs},${state.mgDl},${state.trend}," +
            "${state.low},${state.high},${state.urgentLow},${state.urgentHigh}"
        p.edit().putString(KEY_CURRENT_CGM, s).apply()
    }

    private fun restoreCurrentCgm() {
        val p = prefs ?: return
        val raw = p.getString(KEY_CURRENT_CGM, null) ?: return
        try {
            val parts = raw.split(',')
            if (parts.size < 7) return
            _cgm.value = CgmState(
                timestampMs = parts[0].toLong(),
                mgDl = parts[1].toInt(),
                trend = parts[2],
                low = parts[3].toInt(),
                high = parts[4].toInt(),
                urgentLow = parts[5].toInt(),
                urgentHigh = parts[6].toInt(),
            )
            Timber.d("Restored current CGM from cache")
        } catch (e: Exception) {
            Timber.w(e, "Failed to restore current CGM from cache")
            p.edit().remove(KEY_CURRENT_CGM).apply()
        }
    }

    /**
     * Persist current IoB: "iob,timestampMs"
     */
    private fun persistCurrentIoB() {
        val p = prefs ?: return
        val state = _iob.value
        if (state == null) {
            p.edit().remove(KEY_CURRENT_IOB).apply()
            return
        }
        p.edit().putString(KEY_CURRENT_IOB, "${state.iob},${state.timestampMs}").apply()
    }

    private fun restoreCurrentIoB() {
        val p = prefs ?: return
        val raw = p.getString(KEY_CURRENT_IOB, null) ?: return
        try {
            val parts = raw.split(',')
            if (parts.size < 2) return
            _iob.value = IoBState(
                iob = parts[0].toFloat(),
                timestampMs = parts[1].toLong(),
            )
            Timber.d("Restored current IoB from cache")
        } catch (e: Exception) {
            Timber.w(e, "Failed to restore current IoB from cache")
            p.edit().remove(KEY_CURRENT_IOB).apply()
        }
    }
}
