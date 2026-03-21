package com.glycemicgpt.weardevice.push

import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.result.contract.ActivityResultContracts
import androidx.core.content.ContextCompat
import timber.log.Timber

/**
 * Transparent activity that requests the SET_PUSHED_WATCH_FACE_AS_ACTIVE
 * runtime permission and immediately finishes. Launched from
 * [WatchFaceReceiveService] when the permission is not yet granted.
 *
 * On Wear OS 6, this permission is required to programmatically activate
 * a watch face installed via the Watch Face Push API.
 */
class WatchFacePermissionActivity : ComponentActivity() {

    companion object {
        const val PERMISSION = "com.google.wear.permission.SET_PUSHED_WATCH_FACE_AS_ACTIVE"

        fun hasPermission(context: Context): Boolean =
            ContextCompat.checkSelfPermission(context, PERMISSION) ==
                PackageManager.PERMISSION_GRANTED

        fun createIntent(context: Context): Intent =
            Intent(context, WatchFacePermissionActivity::class.java).apply {
                addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            }
    }

    private val permissionLauncher = registerForActivityResult(
        ActivityResultContracts.RequestPermission(),
    ) { granted ->
        Timber.d("SET_PUSHED_WATCH_FACE_AS_ACTIVE permission %s", if (granted) "granted" else "denied")
        finish()
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        if (hasPermission(this)) {
            Timber.d("SET_PUSHED_WATCH_FACE_AS_ACTIVE already granted")
            finish()
            return
        }
        permissionLauncher.launch(PERMISSION)
    }
}
