package com.glycemicgpt.mobile.plugin.nightscout

import com.glycemicgpt.mobile.data.remote.dto.NightscoutConnectionDto
import com.glycemicgpt.mobile.domain.plugin.PLUGIN_API_VERSION
import com.glycemicgpt.mobile.domain.plugin.Plugin
import com.glycemicgpt.mobile.domain.plugin.PluginCapability
import com.glycemicgpt.mobile.domain.plugin.PluginCapabilityInterface
import com.glycemicgpt.mobile.domain.plugin.PluginContext
import com.glycemicgpt.mobile.domain.plugin.PluginMetadata
import com.glycemicgpt.mobile.domain.plugin.ui.ButtonStyle
import com.glycemicgpt.mobile.domain.plugin.ui.CardElement
import com.glycemicgpt.mobile.domain.plugin.ui.DashboardCardDescriptor
import com.glycemicgpt.mobile.domain.plugin.ui.DetailElement
import com.glycemicgpt.mobile.domain.plugin.ui.DetailScreenDescriptor
import com.glycemicgpt.mobile.domain.plugin.ui.DropdownOption
import com.glycemicgpt.mobile.domain.plugin.ui.LabelStyle
import com.glycemicgpt.mobile.domain.plugin.ui.PluginIcon
import com.glycemicgpt.mobile.domain.plugin.ui.PluginSettingsDescriptor
import com.glycemicgpt.mobile.domain.plugin.ui.PluginSettingsSection
import com.glycemicgpt.mobile.domain.plugin.ui.SettingDescriptor
import com.glycemicgpt.mobile.domain.plugin.ui.UiColor
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.flow
import kotlinx.coroutines.flow.map
import timber.log.Timber
import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import kotlin.reflect.KClass

/**
 * Cloud-mediated data-source plugin (Story 43.8). Unlike the BLE drivers, it talks to no
 * device: when enabled it pulls the user's Nightscout-sourced data from the backend read API
 * (the only Nightscout client lives in the Python backend) into the same Room tables the BLE
 * plugins write, so the mobile dashboard populates without a second Nightscout client on Android.
 *
 * It declares only [PluginCapability.DATA_SYNC] (MULTI_INSTANCE) so it coexists with any active
 * BLE plugin -- enabling it never evicts a pump's glucose/insulin slots (AC5). The sync itself is
 * driven by a WorkManager schedule via [NightscoutSyncManager], not by a polled capability source.
 *
 * The plugin's activate/deactivate toggle in Settings -> Plugins is the on/off control (AC1, off by
 * default); activating triggers the initial + periodic sync, deactivating stops the schedule but
 * keeps cached data (AC8). The dashboard card opens a detail screen with a connection picker (when
 * more than one connection exists) and a "Sync now" action.
 */
class NightscoutSourcePlugin(
    private val syncManager: NightscoutSyncManager,
    private val store: NightscoutSyncStore,
    private val connectionsProvider: suspend () -> List<NightscoutConnectionDto>,
) : Plugin {

    override val metadata: PluginMetadata = METADATA

    override val capabilities: Set<PluginCapability> = setOf(PluginCapability.DATA_SYNC)

    override fun initialize(context: PluginContext) {
        // Intentionally does not use context.settingsStore. The sync worker is constructed by
        // WorkManager's HiltWorkerFactory outside this plugin's lifecycle, so it can't receive the
        // PluginContext; instead the worker, this plugin, and the manager all share one Hilt-injected
        // NightscoutSyncStore. It is backed by the same PluginSettingsStoreImpl(pluginId) file the
        // platform hands out here, so the detail-screen connection picker and the worker stay in sync.
    }

    override fun shutdown() {
        // Lifecycle is governed by onActivated/onDeactivated; there are no held resources to
        // release here (WorkManager state is external and keyed). shutdown() is reserved for
        // runtime-plugin removal, which does not apply to this built-in plugin.
    }

    override fun onActivated() {
        syncManager.enable()
    }

    override fun onDeactivated() {
        syncManager.disable()
    }

    override fun <T : PluginCapabilityInterface> getCapability(type: KClass<T>): T? = null

    override fun settingsDescriptor(): PluginSettingsDescriptor = PluginSettingsDescriptor(
        sections = listOf(
            PluginSettingsSection(
                title = "Nightscout",
                items = listOf(
                    SettingDescriptor.InfoText(
                        key = "cloud_mediated_note",
                        text = "Cloud-mediated: when enabled, your Nightscout data is pulled from " +
                            "your GlycemicGPT account on this device. Requires a Nightscout " +
                            "connection set up on your account.",
                    ),
                ),
            ),
        ),
    )

    override fun observeDashboardCards(): Flow<List<DashboardCardDescriptor>> =
        store.state.map { listOf(buildCard(it)) }

    override fun observeDetailScreen(cardId: String): Flow<DetailScreenDescriptor>? {
        if (cardId != CARD_ID) return null
        return flow { emit(buildDetailScreen()) }
    }

    override fun onDetailAction(cardId: String, actionKey: String) {
        if (cardId == CARD_ID && actionKey == ACTION_SYNC_NOW) {
            syncManager.syncNow()
        }
    }

    private fun buildCard(state: NightscoutSyncState): DashboardCardDescriptor = DashboardCardDescriptor(
        id = CARD_ID,
        title = "Nightscout",
        priority = CARD_PRIORITY,
        hasDetail = true,
        elements = buildList {
            add(CardElement.IconValue(icon = PluginIcon.SYNC, value = "Cloud source"))
            add(CardElement.Label(formatLastSync(state.lastSuccessAtMs), LabelStyle.CAPTION))
            statusBadge(state.status)?.let { add(it) }
        },
    )

    private suspend fun buildDetailScreen(): DetailScreenDescriptor {
        val connections = try {
            connectionsProvider()
        } catch (e: Exception) {
            Timber.w(e, "Nightscout detail: failed to load connections")
            emptyList()
        }
        val activeConnections = connections.filter { it.isActive }
        val state = store.state.value

        val elements = buildList {
            add(DetailElement.SectionHeader("Nightscout sync"))
            add(
                DetailElement.Display(
                    CardElement.Label(formatLastSync(state.lastSuccessAtMs), LabelStyle.BODY),
                ),
            )
            statusBadge(state.status)?.let { add(DetailElement.Display(it)) }
            // Only offer a picker when there is an actual choice to make.
            if (activeConnections.size > 1) {
                add(
                    DetailElement.Interactive(
                        SettingDescriptor.Dropdown(
                            key = NightscoutSyncStore.KEY_SELECTED_CONNECTION,
                            label = "Connection",
                            options = activeConnections.map { DropdownOption(it.id, it.name) },
                        ),
                    ),
                )
            }
            add(
                DetailElement.Interactive(
                    SettingDescriptor.ActionButton(
                        key = ACTION_SYNC_NOW,
                        label = "Sync now",
                        style = ButtonStyle.PRIMARY,
                    ),
                ),
            )
        }
        return DetailScreenDescriptor(title = "Nightscout", elements = elements)
    }

    companion object {
        const val PLUGIN_ID = "com.glycemicgpt.nightscout-source"
        const val CARD_ID = "nightscout_sync"
        const val ACTION_SYNC_NOW = "sync_now"
        private const val CARD_PRIORITY = 200

        private val LAST_SYNC_FORMAT: DateTimeFormatter =
            DateTimeFormatter.ofPattern("MMM d, HH:mm").withZone(ZoneId.systemDefault())

        /** Shared metadata -- used by both [NightscoutSourcePlugin] and [NightscoutSourceFactory]. */
        val METADATA = PluginMetadata(
            id = PLUGIN_ID,
            name = "Nightscout Data Source",
            version = "1.0.0",
            apiVersion = PLUGIN_API_VERSION,
            description = "Cloud-mediated: pulls glucose & insulin from your Nightscout connection.",
            author = "GlycemicGPT",
            protocolName = "Nightscout",
        )

        internal fun formatLastSync(lastSyncAtMs: Long?): String =
            if (lastSyncAtMs == null) {
                "Not synced yet"
            } else {
                "Last sync: ${LAST_SYNC_FORMAT.format(Instant.ofEpochMilli(lastSyncAtMs))}"
            }

        /** A user-facing badge for the latest sync outcome, or null when nothing is worth flagging. */
        internal fun statusBadge(status: NightscoutSyncStatus): CardElement.StatusBadge? = when (status) {
            NightscoutSyncStatus.OK, NightscoutSyncStatus.NEVER -> null
            NightscoutSyncStatus.NO_CONNECTION ->
                CardElement.StatusBadge("No active Nightscout connection", UiColor.WARNING)
            NightscoutSyncStatus.AUTH_ERROR ->
                CardElement.StatusBadge("Reconnect needed", UiColor.ERROR)
            NightscoutSyncStatus.ERROR ->
                CardElement.StatusBadge("Sync error — will retry", UiColor.WARNING)
        }
    }
}
