package com.glycemicgpt.mobile.presentation

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import com.glycemicgpt.mobile.data.local.AppSettingsStore
import com.glycemicgpt.mobile.data.local.AuthTokenStore
import com.glycemicgpt.mobile.presentation.navigation.GlycemicGptNavHost
import com.glycemicgpt.mobile.presentation.theme.GlycemicGptTheme
import dagger.hilt.android.AndroidEntryPoint
import javax.inject.Inject

@AndroidEntryPoint
class MainActivity : ComponentActivity() {

    @Inject lateinit var appSettingsStore: AppSettingsStore
    @Inject lateinit var authTokenStore: AuthTokenStore

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContent {
            GlycemicGptTheme {
                GlycemicGptNavHost(
                    appSettingsStore = appSettingsStore,
                    authTokenStore = authTokenStore,
                )
            }
        }
    }
}
