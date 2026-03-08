package com.glycemicgpt.mobile.presentation

import android.content.SharedPreferences
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import com.glycemicgpt.mobile.data.local.AppSettingsStore
import com.glycemicgpt.mobile.data.local.AuthTokenStore
import com.glycemicgpt.mobile.presentation.navigation.GlycemicGptNavHost
import com.glycemicgpt.mobile.presentation.theme.GlycemicGptTheme
import dagger.hilt.android.AndroidEntryPoint
import javax.inject.Inject

@AndroidEntryPoint
class MainActivity : ComponentActivity(), SharedPreferences.OnSharedPreferenceChangeListener {

    @Inject lateinit var appSettingsStore: AppSettingsStore
    @Inject lateinit var authTokenStore: AuthTokenStore

    private var themeMode by mutableStateOf(com.glycemicgpt.mobile.presentation.theme.ThemeMode.System)

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        themeMode = appSettingsStore.themeMode
        appSettingsStore.registerListener(this)
        enableEdgeToEdge()
        setContent {
            GlycemicGptTheme(themeMode = themeMode) {
                GlycemicGptNavHost(
                    appSettingsStore = appSettingsStore,
                    authTokenStore = authTokenStore,
                )
            }
        }
    }

    override fun onDestroy() {
        super.onDestroy()
        appSettingsStore.unregisterListener(this)
    }

    override fun onSharedPreferenceChanged(sharedPreferences: SharedPreferences?, key: String?) {
        if (key == AppSettingsStore.KEY_THEME_MODE) {
            themeMode = appSettingsStore.themeMode
        }
    }
}
