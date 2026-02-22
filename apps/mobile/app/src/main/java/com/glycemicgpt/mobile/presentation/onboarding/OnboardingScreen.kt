package com.glycemicgpt.mobile.presentation.onboarding

import android.Manifest
import android.os.Build
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.pager.HorizontalPager
import androidx.compose.foundation.pager.rememberPagerState
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Bluetooth
import androidx.compose.material.icons.filled.Favorite
import androidx.compose.material.icons.filled.LocalHospital
import androidx.compose.material.icons.filled.Lock
import androidx.compose.material.icons.filled.Notifications
import androidx.compose.material.icons.filled.Psychology
import androidx.compose.material.icons.filled.Science
import androidx.compose.material.icons.filled.Security
import androidx.compose.material.icons.filled.Shield
import androidx.compose.material.icons.filled.Warning
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import kotlinx.coroutines.launch
import timber.log.Timber

private const val PAGE_COUNT = OnboardingPages.COUNT
private const val PAGE_WELCOME = OnboardingPages.WELCOME
private const val PAGE_FEATURES = OnboardingPages.FEATURES
private const val PAGE_DISCLAIMER = OnboardingPages.DISCLAIMER
private const val PAGE_SERVER = OnboardingPages.SERVER
private const val PAGE_LOGIN = OnboardingPages.LOGIN

@OptIn(ExperimentalFoundationApi::class)
@Composable
fun OnboardingScreen(
    onOnboardingComplete: () -> Unit,
    viewModel: OnboardingViewModel = hiltViewModel(),
) {
    val state by viewModel.uiState.collectAsState()
    val pagerState = rememberPagerState(
        initialPage = viewModel.getStartPage(),
        pageCount = { PAGE_COUNT },
    )
    val coroutineScope = rememberCoroutineScope()

    // Notification permission launcher (Android 13+)
    val notificationPermissionLauncher = rememberLauncherForActivityResult(
        contract = ActivityResultContracts.RequestPermission(),
    ) { granted ->
        Timber.d("POST_NOTIFICATIONS permission granted: $granted")
        viewModel.onNotificationPermissionHandled()
    }

    // Request notification permission after successful login
    LaunchedEffect(state.requestNotificationPermission) {
        if (state.requestNotificationPermission && Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            notificationPermissionLauncher.launch(Manifest.permission.POST_NOTIFICATIONS)
        } else if (state.requestNotificationPermission) {
            // Pre-Android 13: permission not needed at runtime
            viewModel.onNotificationPermissionHandled()
        }
    }

    LaunchedEffect(state.onboardingComplete) {
        if (state.onboardingComplete) {
            onOnboardingComplete()
        }
    }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .background(MaterialTheme.colorScheme.background),
    ) {
        HorizontalPager(
            state = pagerState,
            modifier = Modifier.weight(1f),
            // Swiping is disabled once the user reaches the disclaimer page to
            // enforce the safety acknowledgement gate ("I Understand" button).
            userScrollEnabled = pagerState.currentPage < PAGE_DISCLAIMER,
        ) { page ->
            when (page) {
                PAGE_WELCOME -> WelcomePage()
                PAGE_FEATURES -> FeaturesPage()
                PAGE_DISCLAIMER -> DisclaimerPage()
                PAGE_SERVER -> ServerSetupPage(
                    baseUrl = state.baseUrl,
                    onUrlChange = viewModel::updateBaseUrl,
                    isTestingConnection = state.isTestingConnection,
                    connectionTestResult = state.connectionTestResult,
                    connectionTestSuccess = state.connectionTestSuccess,
                    onTestConnection = viewModel::testConnection,
                )
                PAGE_LOGIN -> LoginPage(
                    email = state.email,
                    onEmailChange = viewModel::updateEmail,
                    password = state.password,
                    onPasswordChange = viewModel::updatePassword,
                    isLoggingIn = state.isLoggingIn,
                    loginError = state.loginError,
                    onLogin = viewModel::login,
                )
            }
        }

        // Bottom controls
        OnboardingControls(
            currentPage = pagerState.currentPage,
            pageCount = PAGE_COUNT,
            connectionTestSuccess = state.connectionTestSuccess,
            onSkip = {
                coroutineScope.launch { pagerState.animateScrollToPage(PAGE_DISCLAIMER) }
            },
            onBack = {
                coroutineScope.launch { pagerState.animateScrollToPage(pagerState.currentPage - 1) }
            },
            onNext = {
                coroutineScope.launch { pagerState.animateScrollToPage(pagerState.currentPage + 1) }
            },
        )
    }
}

@Composable
private fun OnboardingControls(
    currentPage: Int,
    pageCount: Int,
    connectionTestSuccess: Boolean,
    onSkip: () -> Unit,
    onBack: () -> Unit,
    onNext: () -> Unit,
) {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 24.dp, vertical = 16.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        // Page indicators
        Row(
            horizontalArrangement = Arrangement.spacedBy(8.dp),
            modifier = Modifier.padding(bottom = 16.dp),
        ) {
            repeat(pageCount) { index ->
                val selected = index == currentPage
                Box(
                    modifier = Modifier
                        .size(if (selected) 10.dp else 8.dp)
                        .clip(CircleShape)
                        .background(
                            if (selected) {
                                MaterialTheme.colorScheme.primary
                            } else {
                                MaterialTheme.colorScheme.outlineVariant
                            },
                        )
                        .semantics {
                            contentDescription = "Page ${index + 1} of $pageCount" +
                                if (selected) ", current" else ""
                        }
                        .testTag("page_indicator_$index"),
                )
            }
        }

        // Navigation buttons
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            when {
                // Skip button on welcome pages 0-1
                currentPage in PAGE_WELCOME..PAGE_FEATURES -> {
                    TextButton(
                        onClick = onSkip,
                        modifier = Modifier.testTag("skip_button"),
                    ) {
                        Text("Skip")
                    }
                }
                // Back button on server setup and login pages
                currentPage in PAGE_SERVER..PAGE_LOGIN -> {
                    TextButton(
                        onClick = onBack,
                        modifier = Modifier.testTag("back_button"),
                    ) {
                        Text("Back")
                    }
                }
                else -> Spacer(modifier = Modifier.width(64.dp))
            }

            // Next button
            when (currentPage) {
                PAGE_DISCLAIMER -> {
                    Button(
                        onClick = onNext,
                        modifier = Modifier.testTag("next_button"),
                    ) {
                        Text("I Understand")
                    }
                }
                PAGE_SERVER -> {
                    Button(
                        onClick = onNext,
                        enabled = connectionTestSuccess,
                        modifier = Modifier.testTag("next_button"),
                    ) {
                        Text("Next")
                    }
                }
                PAGE_LOGIN -> {
                    // Login button is in the page itself
                    Spacer(modifier = Modifier.width(64.dp))
                }
                else -> {
                    Button(
                        onClick = onNext,
                        modifier = Modifier.testTag("next_button"),
                    ) {
                        Text("Next")
                    }
                }
            }
        }
    }
}

// -- Page Composables --

@Composable
private fun WelcomePage() {
    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(32.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center,
    ) {
        Icon(
            imageVector = Icons.Default.Favorite,
            contentDescription = null,
            modifier = Modifier.size(96.dp),
            tint = MaterialTheme.colorScheme.primary,
        )

        Spacer(modifier = Modifier.height(24.dp))

        Text(
            text = "GlycemicGPT",
            style = MaterialTheme.typography.headlineLarge,
            fontWeight = FontWeight.Bold,
            color = MaterialTheme.colorScheme.primary,
        )

        Spacer(modifier = Modifier.height(8.dp))

        Text(
            text = "AI-powered diabetes management companion",
            style = MaterialTheme.typography.titleMedium,
            textAlign = TextAlign.Center,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )

        Spacer(modifier = Modifier.height(32.dp))

        Text(
            text = "Your on-call endo at home",
            style = MaterialTheme.typography.bodyLarge,
            textAlign = TextAlign.Center,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}

@Composable
private fun FeaturesPage() {
    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(24.dp)
            .verticalScroll(rememberScrollState()),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Spacer(modifier = Modifier.height(32.dp))

        Text(
            text = "What You Get",
            style = MaterialTheme.typography.headlineMedium,
            fontWeight = FontWeight.Bold,
        )

        Spacer(modifier = Modifier.height(24.dp))

        FeatureCard(
            icon = Icons.Default.Bluetooth,
            title = "Direct Pump Connection",
            description = "Connect directly to your Tandem t:slim via BLE for real-time basal, bolus, IoB, reservoir, and battery data.",
        )

        Spacer(modifier = Modifier.height(12.dp))

        FeatureCard(
            icon = Icons.Default.Psychology,
            title = "AI-Powered Analysis",
            description = "Get daily briefs, meal analysis, and pattern recognition powered by your choice of AI provider.",
        )

        Spacer(modifier = Modifier.height(12.dp))

        FeatureCard(
            icon = Icons.Default.Notifications,
            title = "Smart Alerts",
            description = "Configurable glucose alerts with Telegram delivery and caregiver escalation.",
        )

        Spacer(modifier = Modifier.height(12.dp))

        FeatureCard(
            icon = Icons.Default.Lock,
            title = "Self-Hosted Privacy",
            description = "Your data stays on your infrastructure. No cloud dependency, full control.",
        )

        Spacer(modifier = Modifier.height(32.dp))
    }
}

@Composable
private fun FeatureCard(icon: ImageVector, title: String, description: String) {
    Card(
        modifier = Modifier.fillMaxWidth(),
    ) {
        Row(
            modifier = Modifier.padding(16.dp),
            verticalAlignment = Alignment.Top,
        ) {
            Icon(
                imageVector = icon,
                contentDescription = title,
                modifier = Modifier.size(32.dp),
                tint = MaterialTheme.colorScheme.primary,
            )
            Spacer(modifier = Modifier.width(16.dp))
            Column {
                Text(
                    text = title,
                    style = MaterialTheme.typography.titleSmall,
                    fontWeight = FontWeight.SemiBold,
                )
                Spacer(modifier = Modifier.height(4.dp))
                Text(
                    text = description,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }
    }
}

@Composable
private fun DisclaimerPage() {
    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(24.dp)
            .verticalScroll(rememberScrollState()),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Spacer(modifier = Modifier.height(16.dp))

        Icon(
            imageVector = Icons.Default.Warning,
            contentDescription = null,
            modifier = Modifier.size(48.dp),
            tint = MaterialTheme.colorScheme.error,
        )

        Spacer(modifier = Modifier.height(12.dp))

        Text(
            text = "Important Safety Information",
            style = MaterialTheme.typography.headlineSmall,
            fontWeight = FontWeight.Bold,
            textAlign = TextAlign.Center,
        )

        Spacer(modifier = Modifier.height(20.dp))

        DisclaimerCard(
            icon = Icons.Default.Science,
            title = "Experimental Software",
            description = "This is alpha software under active development. It is functional but has not been broadly tested. Use at your own risk.",
        )

        Spacer(modifier = Modifier.height(8.dp))

        DisclaimerCard(
            icon = Icons.Default.Psychology,
            title = "AI Limitations",
            description = "AI can hallucinate, misinterpret data, and provide outdated or incorrect information. Never rely solely on AI suggestions.",
        )

        Spacer(modifier = Modifier.height(8.dp))

        DisclaimerCard(
            icon = Icons.Default.Shield,
            title = "Not FDA Approved",
            description = "This software is not approved by the FDA or any regulatory body for medical use. It is not a medical device.",
        )

        Spacer(modifier = Modifier.height(8.dp))

        DisclaimerCard(
            icon = Icons.Default.LocalHospital,
            title = "Consult Your Healthcare Provider",
            description = "Always consult with your endocrinologist before making changes to your diabetes management. Verify all AI suggestions with your care team.",
        )

        Spacer(modifier = Modifier.height(24.dp))
    }
}

@Composable
private fun DisclaimerCard(icon: ImageVector, title: String, description: String) {
    Card(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(
            containerColor = MaterialTheme.colorScheme.errorContainer.copy(alpha = 0.3f),
        ),
    ) {
        Row(
            modifier = Modifier.padding(12.dp),
            verticalAlignment = Alignment.Top,
        ) {
            Icon(
                imageVector = icon,
                contentDescription = title,
                modifier = Modifier.size(24.dp),
                tint = MaterialTheme.colorScheme.error,
            )
            Spacer(modifier = Modifier.width(12.dp))
            Column {
                Text(
                    text = title,
                    style = MaterialTheme.typography.titleSmall,
                    fontWeight = FontWeight.SemiBold,
                )
                Spacer(modifier = Modifier.height(2.dp))
                Text(
                    text = description,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }
    }
}

@Composable
private fun ServerSetupPage(
    baseUrl: String,
    onUrlChange: (String) -> Unit,
    isTestingConnection: Boolean,
    connectionTestResult: String?,
    connectionTestSuccess: Boolean,
    onTestConnection: () -> Unit,
) {
    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(24.dp)
            .verticalScroll(rememberScrollState()),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Spacer(modifier = Modifier.height(48.dp))

        Icon(
            imageVector = Icons.Default.Security,
            contentDescription = null,
            modifier = Modifier.size(48.dp),
            tint = MaterialTheme.colorScheme.primary,
        )

        Spacer(modifier = Modifier.height(16.dp))

        Text(
            text = "Connect to Your Server",
            style = MaterialTheme.typography.headlineSmall,
            fontWeight = FontWeight.Bold,
            textAlign = TextAlign.Center,
        )

        Spacer(modifier = Modifier.height(8.dp))

        Text(
            text = "Enter the URL of your self-hosted GlycemicGPT server.",
            style = MaterialTheme.typography.bodyMedium,
            textAlign = TextAlign.Center,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )

        Spacer(modifier = Modifier.height(24.dp))

        OutlinedTextField(
            value = baseUrl,
            onValueChange = onUrlChange,
            label = { Text("Server URL") },
            placeholder = { Text("https://your-server.com") },
            singleLine = true,
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Uri),
            modifier = Modifier
                .fillMaxWidth()
                .testTag("onboarding_server_url"),
        )

        Spacer(modifier = Modifier.height(12.dp))

        OutlinedButton(
            onClick = onTestConnection,
            enabled = !isTestingConnection && baseUrl.isNotBlank(),
            modifier = Modifier
                .fillMaxWidth()
                .testTag("onboarding_test_connection"),
        ) {
            if (isTestingConnection) {
                CircularProgressIndicator(
                    modifier = Modifier.size(16.dp),
                    strokeWidth = 2.dp,
                )
                Spacer(modifier = Modifier.width(8.dp))
            }
            Text(if (isTestingConnection) "Testing..." else "Test Connection")
        }

        connectionTestResult?.let { result ->
            Spacer(modifier = Modifier.height(8.dp))
            Text(
                text = result,
                style = MaterialTheme.typography.bodySmall,
                color = if (connectionTestSuccess) {
                    MaterialTheme.colorScheme.primary
                } else {
                    MaterialTheme.colorScheme.error
                },
                textAlign = TextAlign.Center,
                modifier = Modifier.testTag("onboarding_connection_result"),
            )
        }
    }
}

@Composable
private fun LoginPage(
    email: String,
    onEmailChange: (String) -> Unit,
    password: String,
    onPasswordChange: (String) -> Unit,
    isLoggingIn: Boolean,
    loginError: String?,
    onLogin: () -> Unit,
) {
    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(24.dp)
            .verticalScroll(rememberScrollState()),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Spacer(modifier = Modifier.height(48.dp))

        Text(
            text = "Sign In",
            style = MaterialTheme.typography.headlineSmall,
            fontWeight = FontWeight.Bold,
        )

        Spacer(modifier = Modifier.height(8.dp))

        Text(
            text = "Sign in to your GlycemicGPT account to start monitoring.",
            style = MaterialTheme.typography.bodyMedium,
            textAlign = TextAlign.Center,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )

        Spacer(modifier = Modifier.height(32.dp))

        OutlinedTextField(
            value = email,
            onValueChange = onEmailChange,
            label = { Text("Email") },
            singleLine = true,
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Email),
            modifier = Modifier
                .fillMaxWidth()
                .testTag("onboarding_email"),
        )

        Spacer(modifier = Modifier.height(12.dp))

        OutlinedTextField(
            value = password,
            onValueChange = onPasswordChange,
            label = { Text("Password") },
            singleLine = true,
            visualTransformation = PasswordVisualTransformation(),
            keyboardOptions = KeyboardOptions(
                keyboardType = KeyboardType.Password,
                autoCorrectEnabled = false,
            ),
            modifier = Modifier
                .fillMaxWidth()
                .testTag("onboarding_password"),
        )

        loginError?.let { error ->
            Spacer(modifier = Modifier.height(8.dp))
            Text(
                text = error,
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.error,
                modifier = Modifier.testTag("onboarding_login_error"),
            )
        }

        Spacer(modifier = Modifier.height(20.dp))

        Button(
            onClick = onLogin,
            enabled = !isLoggingIn && email.isNotBlank() && password.isNotBlank(),
            modifier = Modifier
                .fillMaxWidth()
                .testTag("onboarding_sign_in"),
        ) {
            if (isLoggingIn) {
                CircularProgressIndicator(
                    modifier = Modifier.size(16.dp),
                    color = MaterialTheme.colorScheme.onPrimary,
                    strokeWidth = 2.dp,
                )
                Spacer(modifier = Modifier.width(8.dp))
            }
            Text(if (isLoggingIn) "Signing in..." else "Sign In")
        }
    }
}
