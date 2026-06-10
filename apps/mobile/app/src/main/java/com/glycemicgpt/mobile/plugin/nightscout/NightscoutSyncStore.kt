package com.glycemicgpt.mobile.plugin.nightscout

import com.glycemicgpt.mobile.domain.plugin.PluginSettingsStore
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

/** Outcome class of the most recent sync attempt, surfaced on the dashboard card. */
enum class NightscoutSyncStatus { NEVER, OK, NO_CONNECTION, AUTH_ERROR, ERROR }

/** The most recent sync state: its [status] plus the wall-clock of the last *successful* sync. */
data class NightscoutSyncState(
    val status: NightscoutSyncStatus,
    val lastSuccessAtMs: Long?,
)

/**
 * Typed persistence for the Nightscout-source plugin (Story 43.8), backed by the
 * plugin's [PluginSettingsStore] (a per-plugin SharedPreferences file). It holds:
 *
 *  - the enabled flag (AC1/AC8 -- the plugin's activate/deactivate toggle),
 *  - the user-selected connection id (written by the detail-screen connection
 *    picker via the same SharedPreferences file),
 *  - a per-connection incremental sync cursor (max data timestamp pulled, AC2),
 *  - the most recent [NightscoutSyncState], surfaced reactively on the dashboard
 *    card via [state] so auth/connection errors are visible (AC8).
 *
 * The same singleton instance is shared by the plugin, the sync manager, and the
 * worker (all Hilt-injected), so the worker's writes are visible to the card.
 * Longs are stored as strings because [PluginSettingsStore] has no long accessor.
 */
class NightscoutSyncStore(
    private val store: PluginSettingsStore,
) {

    var enabled: Boolean
        get() = store.getBoolean(KEY_ENABLED, false)
        set(value) = store.putBoolean(KEY_ENABLED, value)

    /**
     * The connection the user picked in the detail-screen dropdown, or "" when none
     * is chosen (the worker then falls back to the first active connection). The
     * dropdown persists this under [KEY_SELECTED_CONNECTION] through the same store.
     */
    val selectedConnectionId: String
        get() = store.getString(KEY_SELECTED_CONNECTION, "")

    /** Max data timestamp (epoch ms) pulled so far for [connectionId]; 0 means full backfill. */
    fun getCursor(connectionId: String): Long =
        store.getString(cursorKey(connectionId), "0").toLongOrNull() ?: 0L

    fun setCursor(connectionId: String, value: Long) {
        store.putString(cursorKey(connectionId), value.toString())
    }

    private val _state = MutableStateFlow(readState())
    /** Latest sync state; drives the dashboard card's last-sync line and error badge. */
    val state: StateFlow<NightscoutSyncState> = _state.asStateFlow()

    /** Record a successful sync at [nowMs]: status OK and a fresh last-success timestamp. */
    fun recordSuccess(nowMs: Long) {
        store.putString(KEY_STATUS, NightscoutSyncStatus.OK.name)
        store.putString(KEY_LAST_SYNC_AT, nowMs.toString())
        _state.value = NightscoutSyncState(NightscoutSyncStatus.OK, nowMs)
    }

    /** Record a non-success outcome, preserving the last *successful* sync timestamp. */
    fun recordStatus(status: NightscoutSyncStatus) {
        store.putString(KEY_STATUS, status.name)
        _state.value = _state.value.copy(status = status)
    }

    private fun readState(): NightscoutSyncState {
        val status = runCatching { NightscoutSyncStatus.valueOf(store.getString(KEY_STATUS, "")) }
            .getOrDefault(NightscoutSyncStatus.NEVER)
        val lastSuccess = store.getString(KEY_LAST_SYNC_AT, "").toLongOrNull()
        return NightscoutSyncState(status, lastSuccess)
    }

    private fun cursorKey(connectionId: String) = "$KEY_CURSOR_PREFIX$connectionId"

    companion object {
        const val KEY_ENABLED = "enabled"
        const val KEY_SELECTED_CONNECTION = "selected_connection_id"
        const val KEY_CURSOR_PREFIX = "last_sync_cursor_ms."
        const val KEY_LAST_SYNC_AT = "last_sync_at_ms"
        const val KEY_STATUS = "last_sync_status"
    }
}
