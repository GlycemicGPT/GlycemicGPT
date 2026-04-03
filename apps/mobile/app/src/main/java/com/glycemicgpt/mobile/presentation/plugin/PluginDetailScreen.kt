package com.glycemicgpt.mobile.presentation.plugin

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import com.glycemicgpt.mobile.domain.plugin.ui.DetailElement

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun PluginDetailScreen(
    pluginId: String,
    cardId: String,
    onBack: () -> Unit,
    viewModel: PluginDetailViewModel = hiltViewModel(),
) {
    LaunchedEffect(pluginId, cardId) {
        viewModel.load(pluginId, cardId)
    }

    val detailScreen by viewModel.detailScreen.collectAsState()
    val error by viewModel.error.collectAsState()
    val store by viewModel.settingsStore.collectAsState()

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text(text = detailScreen?.title ?: "") },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(
                            imageVector = Icons.AutoMirrored.Filled.ArrowBack,
                            contentDescription = "Back",
                        )
                    }
                },
            )
        },
    ) { innerPadding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(innerPadding)
                .verticalScroll(rememberScrollState())
                .padding(16.dp),
        ) {
            val descriptor = detailScreen
            val errorMsg = error
            if (errorMsg != null) {
                Text(
                    text = errorMsg,
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.error,
                )
            } else if (descriptor == null) {
                Text(
                    text = "Loading...",
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            } else {
                descriptor.elements.forEach { element ->
                    when (element) {
                        is DetailElement.Display -> {
                            RenderElement(element.element, depth = 0)
                            Spacer(modifier = Modifier.height(8.dp))
                        }
                        is DetailElement.Interactive -> {
                            val currentStore = store
                            if (currentStore != null) {
                                SettingItem(
                                    descriptor = element.setting,
                                    store = currentStore,
                                    onAction = { key -> viewModel.onAction(key) },
                                )
                                Spacer(modifier = Modifier.height(8.dp))
                            }
                        }
                        is DetailElement.SectionHeader -> {
                            Spacer(modifier = Modifier.height(16.dp))
                            Text(
                                text = element.title,
                                style = MaterialTheme.typography.titleSmall,
                                color = MaterialTheme.colorScheme.primary,
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .padding(bottom = 8.dp),
                            )
                        }
                    }
                }
            }
        }
    }
}
