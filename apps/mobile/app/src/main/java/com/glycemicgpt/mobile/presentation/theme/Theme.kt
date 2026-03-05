package com.glycemicgpt.mobile.presentation.theme

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color

// Matches the web app's dark theme palette
private val Slate950 = Color(0xFF020617)
private val Slate900 = Color(0xFF0F172A)
private val Slate800 = Color(0xFF1E293B)
private val Slate700 = Color(0xFF334155)
private val Slate400 = Color(0xFF94A3B8)
private val Slate300 = Color(0xFFCBD5E1)
private val Slate100 = Color(0xFFF1F5F9)
private val Blue600 = Color(0xFF2563EB)
private val Blue500 = Color(0xFF3B82F6)
private val Blue400 = Color(0xFF60A5FA)
private val Red500 = Color(0xFFEF4444)
private val Green500 = Color(0xFF22C55E)
private val Yellow500 = Color(0xFFEAB308)

private val DarkColorScheme = darkColorScheme(
    primary = Blue600,
    onPrimary = Color.White,
    primaryContainer = Blue500,
    secondary = Blue400,
    background = Slate950,
    onBackground = Slate100,
    surface = Slate900,
    onSurface = Slate100,
    surfaceVariant = Slate800,
    onSurfaceVariant = Slate300,
    outline = Slate700,
    error = Red500,
    onError = Color.White,
)

@Composable
fun GlycemicGptTheme(content: @Composable () -> Unit) {
    MaterialTheme(
        colorScheme = DarkColorScheme,
        content = content,
    )
}

// Semantic colors for glucose ranges
object GlucoseColors {
    val InRange = Green500
    val High = Yellow500
    val Low = Yellow500
    val UrgentHigh = Red500
    val UrgentLow = Red500
}

// Semantic colors for bolus type categories (shared across chart, badges, and summary card)
object BolusTypeColors {
    val Correction = Color(0xFFE91E63)       // Pink -- auto correction / automated (pump-initiated)
    val ManualCorrection = Color(0xFFFF5722) // Deep orange -- BG Only (user-initiated correction)
    val Meal = Color(0xFF7C4DFF)             // Deep purple -- Food bolus
    val MealWithCorrection = Color(0xFFAB47BC) // Medium purple -- BG+Food combo
}
