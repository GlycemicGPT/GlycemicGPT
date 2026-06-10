package com.glycemicgpt.mobile.plugin.nightscout

import android.content.Context
import androidx.hilt.work.HiltWorker
import androidx.work.CoroutineWorker
import androidx.work.WorkerParameters
import dagger.assisted.Assisted
import dagger.assisted.AssistedInject
import kotlinx.coroutines.CancellationException
import timber.log.Timber

/**
 * Thin WorkManager shell for the Nightscout-source sync (Story 43.8). All logic lives in
 * [NightscoutSyncEngine] (unit-tested without an Android harness); this just maps the
 * outcome onto a WorkManager [Result] and never crashes the run.
 */
@HiltWorker
class NightscoutSyncWorker @AssistedInject constructor(
    @Assisted context: Context,
    @Assisted params: WorkerParameters,
    private val engine: NightscoutSyncEngine,
) : CoroutineWorker(context, params) {

    override suspend fun doWork(): Result {
        val outcome = try {
            engine.syncOnce()
        } catch (e: CancellationException) {
            // Cooperative cancellation (e.g. WorkManager stopping the work) must propagate, not be
            // swallowed into a retry.
            throw e
        } catch (e: Exception) {
            Timber.e(e, "Nightscout sync worker crashed; will retry")
            return Result.retry()
        }
        return if (outcome is SyncOutcome.Transient) Result.retry() else Result.success()
    }
}
