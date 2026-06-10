package com.glycemicgpt.mobile.plugin.nightscout

import com.glycemicgpt.mobile.domain.plugin.PluginSettingsStore
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

/**
 * Typed persistence for the Nightscout-source plugin (Story 43.8), backed by the
 * plugin's [PluginSettingsStore] (a per-plugin SharedPreferences file). It holds:
 *
 *  - the enabled flag (AC1/AC8 -- the plugin's activate/deactivate toggle),
 *  - the user-selected connection id (written by the detail-screen connection
 *    picker via the same SharedPreferences file),
 *  - the incremental sync cursor (max data timestamp pulled so far, AC2),
 *  - the wall-clock of the last successful sync, surfaced reactively on the
 *    dashboard card via [lastSyncAtMs].
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

    /** Max data timestamp (epoch ms) pulled so far; 0 means "no sync yet" (full backfill). */
    var lastSyncCursorMs: Long
        get() = store.getString(KEY_CURSOR, "0").toLongOrNull() ?: 0L
        set(value) = store.putString(KEY_CURSOR, value.toString())

    private val _lastSyncAtMs = MutableStateFlow(readLastSyncAtMs())
    /** Wall-clock epoch ms of the last successful sync, or null if never synced. */
    val lastSyncAtMs: StateFlow<Long?> = _lastSyncAtMs.asStateFlow()

    /** Record a successful sync at [nowMs]; updates the persisted value and the card flow. */
    fun recordSyncCompleted(nowMs: Long) {
        store.putString(KEY_LAST_SYNC_AT, nowMs.toString())
        _lastSyncAtMs.value = nowMs
    }

    private fun readLastSyncAtMs(): Long? =
        store.getString(KEY_LAST_SYNC_AT, "").toLongOrNull()

    companion object {
        const val KEY_ENABLED = "enabled"
        const val KEY_SELECTED_CONNECTION = "selected_connection_id"
        const val KEY_CURSOR = "last_sync_cursor_ms"
        const val KEY_LAST_SYNC_AT = "last_sync_at_ms"
    }
}
