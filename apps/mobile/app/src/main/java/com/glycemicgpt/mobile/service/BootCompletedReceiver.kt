package com.glycemicgpt.mobile.service

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import com.glycemicgpt.mobile.data.local.AuthTokenStore
import com.glycemicgpt.mobile.data.local.PumpCredentialStore
import dagger.hilt.android.AndroidEntryPoint
import timber.log.Timber
import javax.inject.Inject

/**
 * Restarts background services after device reboot:
 * - [PumpConnectionService] if a pump is paired
 * - [AlertStreamService] if the user is logged in (has a refresh token)
 *
 * Complements the auto-start in GlycemicGptApp.onCreate() which handles
 * cold app starts but not device reboots.
 *
 * Uses [goAsync] to extend the broadcast window beyond the default 10-second
 * ANR limit, since Hilt injection may trigger Application.onCreate().
 */
@AndroidEntryPoint
class BootCompletedReceiver : BroadcastReceiver() {

    @Inject
    lateinit var pumpCredentialStore: PumpCredentialStore

    @Inject
    lateinit var authTokenStore: AuthTokenStore

    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action != Intent.ACTION_BOOT_COMPLETED &&
            intent.action != "android.intent.action.QUICKBOOT_POWERON"
        ) return

        val pendingResult = goAsync()
        try {
            if (pumpCredentialStore.isPaired()) {
                Timber.d("Boot completed, starting PumpConnectionService (pump is paired)")
                PumpConnectionService.start(context)
            } else {
                Timber.d("Boot completed, pump not paired -- skipping PumpConnectionService")
            }

            // Start AlertStreamService if the user is logged in so alerts resume after reboot
            if (authTokenStore.getRefreshToken() != null) {
                try {
                    Timber.d("Boot completed, starting AlertStreamService (user is logged in)")
                    AlertStreamService.start(context)
                } catch (e: IllegalStateException) {
                    // Covers ForegroundServiceStartNotAllowedException (API 31+) and
                    // background-start restrictions (API 26+)
                    Timber.w(e, "Failed to start AlertStreamService on boot")
                } catch (e: SecurityException) {
                    // Missing FOREGROUND_SERVICE permission
                    Timber.w(e, "Failed to start AlertStreamService on boot (missing permission)")
                }
            } else {
                Timber.d("Boot completed, user not logged in -- skipping AlertStreamService")
            }
        } finally {
            pendingResult.finish()
        }
    }
}
