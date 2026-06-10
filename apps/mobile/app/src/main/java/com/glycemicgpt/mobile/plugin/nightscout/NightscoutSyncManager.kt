package com.glycemicgpt.mobile.plugin.nightscout

import android.content.Context
import androidx.work.Constraints
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.ExistingWorkPolicy
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import dagger.hilt.android.qualifiers.ApplicationContext
import timber.log.Timber
import java.util.concurrent.TimeUnit
import javax.inject.Inject
import javax.inject.Singleton

/**
 * Owns the WorkManager schedule for the Nightscout-source plugin (Story 43.8).
 *
 * Enabling (the plugin's activate toggle, AC1/AC8) flips the persisted flag, schedules
 * the periodic sync, and kicks off an immediate one-shot sync. Disabling cancels the
 * schedule but **retains** the cached Room data (AC8). Both the periodic and one-shot
 * requests require connectivity (AC6); offline simply leaves the last-cached data in place.
 */
@Singleton
class NightscoutSyncManager @Inject constructor(
    @ApplicationContext private val context: Context,
    private val store: NightscoutSyncStore,
) {

    /** Enable syncing: persist the flag, schedule periodic work, and run an initial sync. */
    fun enable() {
        store.enabled = true
        enqueuePeriodic()
        syncNow()
        Timber.i("Nightscout-source sync enabled")
    }

    /** Disable syncing: clear the flag and cancel the schedule. Cached Room data is kept. */
    fun disable() {
        store.enabled = false
        WorkManager.getInstance(context).cancelUniqueWork(PERIODIC_WORK)
        Timber.i("Nightscout-source sync disabled (cached data retained)")
    }

    /** Trigger an immediate one-shot sync (the detail screen's "Sync now" action, AC8). */
    fun syncNow() {
        val request = OneTimeWorkRequestBuilder<NightscoutSyncWorker>()
            .setConstraints(networkConstraint())
            .build()
        WorkManager.getInstance(context).enqueueUniqueWork(
            ONESHOT_WORK,
            ExistingWorkPolicy.REPLACE,
            request,
        )
    }

    private fun enqueuePeriodic() {
        val request = PeriodicWorkRequestBuilder<NightscoutSyncWorker>(
            SYNC_INTERVAL_MINUTES, TimeUnit.MINUTES,
        )
            .setConstraints(networkConstraint())
            .build()
        WorkManager.getInstance(context).enqueueUniquePeriodicWork(
            PERIODIC_WORK,
            ExistingPeriodicWorkPolicy.UPDATE,
            request,
        )
    }

    private fun networkConstraint(): Constraints =
        Constraints.Builder()
            .setRequiredNetworkType(NetworkType.CONNECTED)
            .build()

    companion object {
        const val PERIODIC_WORK = "nightscout_source_periodic_sync"
        const val ONESHOT_WORK = "nightscout_source_oneshot_sync"

        /**
         * Periodic cadence. WorkManager's periodic floor is 15 minutes; each run fully
         * backfills everything since the cursor, so a faster Nightscout interval never
         * loses data -- it only changes freshness (AC3).
         */
        const val SYNC_INTERVAL_MINUTES = 15L
    }
}
