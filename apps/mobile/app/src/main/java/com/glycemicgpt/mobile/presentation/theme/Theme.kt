package com.glycemicgpt.mobile.presentation.theme

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.luminance
import com.glycemicgpt.mobile.domain.model.BolusCategory

// Matches the web app's dark theme palette
private val Slate950 = Color(0xFF020617)
private val Slate900 = Color(0xFF0F172A)
private val Slate800 = Color(0xFF1E293B)
private val Slate700 = Color(0xFF334155)
private val Slate400 = Color(0xFF94A3B8)
private val Slate300 = Color(0xFFCBD5E1)
private val Slate100 = Color(0xFFF1F5F9)
private val Slate50 = Color(0xFFF8FAFC)
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

private val LightColorScheme = lightColorScheme(
    primary = Blue600,
    onPrimary = Color.White,
    primaryContainer = Blue400,
    secondary = Blue500,
    background = Slate50,
    onBackground = Slate900,
    surface = Color.White,
    onSurface = Slate900,
    surfaceVariant = Slate100,
    onSurfaceVariant = Slate700,
    outline = Slate300,
    error = Red500,
    onError = Color.White,
)

enum class ThemeMode { System, Dark, Light }

@Composable
fun GlycemicGptTheme(
    themeMode: ThemeMode = ThemeMode.System,
    content: @Composable () -> Unit,
) {
    val darkTheme = when (themeMode) {
        ThemeMode.System -> isSystemInDarkTheme()
        ThemeMode.Dark -> true
        ThemeMode.Light -> false
    }

    val colorScheme = if (darkTheme) DarkColorScheme else LightColorScheme

    MaterialTheme(
        colorScheme = colorScheme,
        content = content,
    )
}

/**
 * Palette for the "Estimate — verify before dosing" qualifier strip. Deliberately a soft amber
 * "calm caution" treatment, never the red error color, so a standing safety note is not mistaken
 * for an alarm. Light/dark values per the mobile Meal Intelligence UX spec (§8).
 */
data class SafetyPalette(val background: Color, val foreground: Color, val icon: Color)

private val SafetyLight = SafetyPalette(
    background = Color(0xFFFFF8E1),
    foreground = Color(0xFF5D4200),
    icon = Color(0xFFB26A00),
)
private val SafetyDark = SafetyPalette(
    background = Color(0xFF3A2E07),
    foreground = Color(0xFFFCEFC7),
    icon = Color(0xFFF2C14E),
)

/**
 * Theme-aware safety palette. Darkness is read off the active scheme (which tracks forced
 * [ThemeMode] too, unlike `isSystemInDarkTheme`); the two schemes sit far from the 0.5 threshold
 * (Slate950 vs Slate50), so the split is unambiguous.
 */
@Composable
fun safetyPalette(): SafetyPalette =
    if (MaterialTheme.colorScheme.background.luminance() < 0.5f) SafetyDark else SafetyLight

// Confidence-bar colors for carb estimates (§7): green = high, amber = medium/low. Medium and Low
// intentionally share the amber hue; ConfidenceBar distinguishes them by length, not color alone.
object MealConfidenceColors {
    val High = Green500
    val Medium = Yellow500
    val Low = Yellow500
}

// Semantic colors for glucose ranges -- constant across themes
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
    val Override = Color(0xFFFFA000)         // Amber -- user overrode recommendation
    val Other = Color(0xFF78909C)            // Blue-grey -- uncategorized / quick bolus
}

/** Map a [BolusCategory] to its display color. */
fun colorForCategory(category: BolusCategory): Color = when (category) {
    BolusCategory.AUTO_CORRECTION -> BolusTypeColors.Correction
    BolusCategory.FOOD -> BolusTypeColors.Meal
    BolusCategory.FOOD_AND_CORRECTION -> BolusTypeColors.MealWithCorrection
    BolusCategory.CORRECTION -> BolusTypeColors.ManualCorrection
    BolusCategory.OVERRIDE -> BolusTypeColors.Override
    BolusCategory.AI_SUGGESTED -> Color(0xFF00BCD4) // Cyan
    BolusCategory.OTHER -> BolusTypeColors.Other
}
