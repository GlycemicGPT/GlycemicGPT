package com.glycemicgpt.mobile.presentation.navigation

import android.net.Uri
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.BugReport
import androidx.compose.material.icons.filled.Bluetooth
import androidx.compose.material.icons.filled.Chat
import androidx.compose.material.icons.filled.Home
import androidx.compose.material.icons.filled.Notifications
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material.icons.filled.Warning
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.navigation.NavDestination.Companion.hierarchy
import androidx.navigation.NavGraph.Companion.findStartDestination
import androidx.navigation.compose.NavHost
import androidx.navigation.NavType
import androidx.navigation.compose.composable
import androidx.navigation.compose.currentBackStackEntryAsState
import androidx.navigation.compose.rememberNavController
import androidx.navigation.navArgument
import com.glycemicgpt.mobile.data.auth.AuthState
import com.glycemicgpt.mobile.data.local.AuthTokenStore
import com.glycemicgpt.mobile.data.local.AppSettingsStore
import com.glycemicgpt.mobile.presentation.alerts.AlertsScreen
import com.glycemicgpt.mobile.presentation.chat.AiChatScreen
import com.glycemicgpt.mobile.presentation.home.HomeScreen
import com.glycemicgpt.mobile.BuildConfig
import com.glycemicgpt.mobile.presentation.debug.BleDebugScreen
import com.glycemicgpt.mobile.presentation.onboarding.OnboardingScreen
import com.glycemicgpt.mobile.presentation.pairing.PairingScreen
import com.glycemicgpt.mobile.presentation.plugin.PluginDetailScreen
import com.glycemicgpt.mobile.presentation.settings.SettingsScreen
import com.glycemicgpt.mobile.presentation.settings.SettingsViewModel

sealed class Screen(val route: String, val label: String, val icon: ImageVector) {
    data object Home : Screen("home", "Home", Icons.Default.Home)
    data object AiChat : Screen("ai_chat", "AI Chat", Icons.Default.Chat)
    data object Alerts : Screen("alerts", "Alerts", Icons.Default.Notifications)
    data object Settings : Screen("settings", "Settings", Icons.Default.Settings)
    data object Pairing : Screen("pairing", "Pairing", Icons.Default.Bluetooth)
    data object BleDebug : Screen("ble_debug", "BLE Debug", Icons.Default.BugReport)
    data object Onboarding : Screen("onboarding", "Onboarding", Icons.Default.Home)
    data object PluginDetail : Screen("plugin_detail/{pluginId}/{cardId}", "Plugin Detail", Icons.Default.Settings)
}

private val bottomNavItems = listOf(Screen.Home, Screen.AiChat, Screen.Alerts, Screen.Settings)

@Composable
fun GlycemicGptNavHost(appSettingsStore: AppSettingsStore, authTokenStore: AuthTokenStore) {
    val navController = rememberNavController()
    val navBackStackEntry by navController.currentBackStackEntryAsState()
    val currentDestination = navBackStackEntry?.destination
    val settingsViewModel: SettingsViewModel = hiltViewModel()
    val authState by settingsViewModel.authState.collectAsState()

    // Use hasActiveSession() (checks refresh token) instead of isLoggedIn() (checks access token).
    // This prevents routing to onboarding when the access token is expired but a valid
    // refresh token exists -- the AuthManager will refresh it asynchronously.
    val startDestination = remember {
        if (appSettingsStore.onboardingComplete && authTokenStore.hasActiveSession()) {
            Screen.Home.route
        } else {
            Screen.Onboarding.route
        }
    }

    val isOnboarding = currentDestination?.route == Screen.Onboarding.route

    // Observe logout -> onboarding navigation event
    LaunchedEffect(Unit) {
        settingsViewModel.navigateToOnboarding.collect {
            navController.navigate(Screen.Onboarding.route) {
                popUpTo(0) { inclusive = true }
            }
        }
    }

    // Navigate back to Home when auth state transitions to Authenticated while on onboarding.
    // This handles the case where the user was briefly shown onboarding due to a stale
    // start destination, but the async token refresh succeeded.
    LaunchedEffect(authState, isOnboarding) {
        if (isOnboarding && authState is AuthState.Authenticated && appSettingsStore.onboardingComplete) {
            navController.navigate(Screen.Home.route) {
                popUpTo(Screen.Onboarding.route) { inclusive = true }
            }
        }
    }

    Scaffold(
        bottomBar = {
            if (!isOnboarding) {
                NavigationBar {
                    bottomNavItems.forEach { screen ->
                        NavigationBarItem(
                            icon = { Icon(screen.icon, contentDescription = screen.label) },
                            label = { Text(screen.label) },
                            selected = currentDestination?.hierarchy?.any { it.route == screen.route } == true,
                            onClick = {
                                navController.navigate(screen.route) {
                                    popUpTo(navController.graph.findStartDestination().id) {
                                        saveState = true
                                    }
                                    launchSingleTop = true
                                    restoreState = true
                                }
                            },
                        )
                    }
                }
            }
        },
    ) { innerPadding ->
        Column(modifier = Modifier.padding(innerPadding)) {
            // Session expired banner (not shown during onboarding)
            if (!isOnboarding) {
                (authState as? AuthState.Expired)?.let { expired ->
                    SessionExpiredBanner(
                        message = expired.message,
                        onClick = {
                            navController.navigate(Screen.Settings.route) {
                                popUpTo(navController.graph.findStartDestination().id) {
                                    saveState = true
                                }
                                launchSingleTop = true
                            }
                        },
                    )
                }
            }

            NavHost(
                navController = navController,
                startDestination = startDestination,
            ) {
                composable(Screen.Onboarding.route) {
                    OnboardingScreen(
                        onOnboardingComplete = {
                            navController.navigate(Screen.Home.route) {
                                popUpTo(Screen.Onboarding.route) { inclusive = true }
                            }
                        },
                    )
                }
                composable(Screen.Home.route) {
                    HomeScreen(
                        onPluginCardTap = { pluginId, cardId ->
                            navController.navigate(
                                "plugin_detail/${Uri.encode(pluginId)}/${Uri.encode(cardId)}",
                            )
                        },
                    )
                }
                composable(Screen.AiChat.route) { AiChatScreen() }
                composable(Screen.Alerts.route) { AlertsScreen() }
                composable(Screen.Settings.route) {
                    SettingsScreen(
                        settingsViewModel = settingsViewModel,
                        onNavigateToPairing = {
                            navController.navigate(Screen.Pairing.route)
                        },
                        onNavigateToBleDebug = if (BuildConfig.DEBUG) {
                            { navController.navigate(Screen.BleDebug.route) }
                        } else {
                            null
                        },
                    )
                }
                composable(Screen.Pairing.route) {
                    PairingScreen(
                        onPaired = { navController.popBackStack() },
                    )
                }
                if (BuildConfig.DEBUG) {
                    composable(Screen.BleDebug.route) {
                        BleDebugScreen()
                    }
                }
                composable(
                    route = Screen.PluginDetail.route,
                    arguments = listOf(
                        navArgument("pluginId") { type = NavType.StringType },
                        navArgument("cardId") { type = NavType.StringType },
                    ),
                ) { backStackEntry ->
                    val pluginId = backStackEntry.arguments?.getString("pluginId") ?: return@composable
                    val cardId = backStackEntry.arguments?.getString("cardId") ?: return@composable
                    PluginDetailScreen(
                        pluginId = pluginId,
                        cardId = cardId,
                        onBack = { navController.popBackStack() },
                    )
                }
            }
        }
    }
}

@Composable
private fun SessionExpiredBanner(message: String, onClick: () -> Unit) {
    Box(
        modifier = Modifier
            .fillMaxWidth()
            .background(MaterialTheme.colorScheme.errorContainer)
            .clickable(onClick = onClick)
            .padding(horizontal = 16.dp, vertical = 12.dp),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Icon(
                imageVector = Icons.Default.Warning,
                contentDescription = "Session expired",
                tint = MaterialTheme.colorScheme.onErrorContainer,
            )
            Spacer(modifier = Modifier.width(8.dp))
            Text(
                text = message,
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onErrorContainer,
            )
        }
    }
}
