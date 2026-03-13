package com.glycemicgpt.weardevice.presentation

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.wear.compose.material.Button
import androidx.wear.compose.material.ButtonDefaults
import androidx.wear.compose.material.MaterialTheme
import androidx.wear.compose.material.Scaffold
import androidx.wear.compose.material.Text
import androidx.wear.compose.material.TimeText
import com.glycemicgpt.weardevice.data.WatchDataRepository
import com.glycemicgpt.weardevice.messaging.WearMessageSender
import kotlinx.coroutines.launch

class AlertsActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            WearAlertScreen(onFinish = { finish() })
        }
    }
}

@Composable
private fun WearAlertScreen(onFinish: () -> Unit) {
    val alert by WatchDataRepository.alert.collectAsState()
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var dismissing by remember { mutableStateOf(false) }

    MaterialTheme {
        Scaffold(timeText = { TimeText() }) {
            if (alert == null) {
                Column(
                    modifier = Modifier.fillMaxSize().padding(16.dp),
                    verticalArrangement = Arrangement.Center,
                    horizontalAlignment = Alignment.CenterHorizontally,
                ) {
                    Text(
                        text = "No Active Alert",
                        style = MaterialTheme.typography.title3,
                        textAlign = TextAlign.Center,
                    )
                    Spacer(modifier = Modifier.height(8.dp))
                    Text(
                        text = "All clear",
                        style = MaterialTheme.typography.body2,
                        color = Color(0xFF4ADE80),
                        textAlign = TextAlign.Center,
                    )
                }
            } else {
                val currentAlert = alert!!
                val isUrgent = currentAlert.type.startsWith("urgent")
                val alertColor = if (isUrgent) Color(0xFFEF4444) else Color(0xFFFBBF24)

                Column(
                    modifier = Modifier.fillMaxSize().padding(horizontal = 16.dp, vertical = 24.dp),
                    verticalArrangement = Arrangement.Center,
                    horizontalAlignment = Alignment.CenterHorizontally,
                ) {
                    Text(
                        text = formatAlertType(currentAlert.type),
                        style = MaterialTheme.typography.title3,
                        color = alertColor,
                        textAlign = TextAlign.Center,
                    )

                    if (currentAlert.bgValue in 20..500) {
                        Spacer(modifier = Modifier.height(4.dp))
                        Text(
                            text = "${currentAlert.bgValue} mg/dL",
                            fontSize = 20.sp,
                            color = alertColor,
                            textAlign = TextAlign.Center,
                        )
                    }

                    if (currentAlert.message.isNotBlank()) {
                        Spacer(modifier = Modifier.height(6.dp))
                        Text(
                            text = currentAlert.message,
                            style = MaterialTheme.typography.body2,
                            textAlign = TextAlign.Center,
                            maxLines = 3,
                        )
                    }

                    Spacer(modifier = Modifier.height(12.dp))

                    Button(
                        onClick = {
                            if (dismissing) return@Button
                            dismissing = true
                            scope.launch {
                                WearMessageSender.sendAlertDismiss(context)
                                WatchDataRepository.clearAlert()
                                onFinish()
                            }
                        },
                        enabled = !dismissing,
                        modifier = Modifier.fillMaxWidth(0.8f),
                        colors = ButtonDefaults.buttonColors(
                            backgroundColor = Color(0xFF374151),
                        ),
                    ) {
                        Text(
                            if (dismissing) "Dismissing..." else "Dismiss",
                            textAlign = TextAlign.Center,
                        )
                    }
                }
            }
        }
    }
}

private fun formatAlertType(type: String): String {
    return type.replace("_", " ")
        .split(" ")
        .joinToString(" ") { word ->
            word.replaceFirstChar { it.uppercaseChar() }
        }
}
