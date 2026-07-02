package com.glycemicgpt.mobile.testutil

import androidx.compose.ui.semantics.ProgressBarRangeInfo
import androidx.compose.ui.semantics.SemanticsProperties
import androidx.compose.ui.test.SemanticsMatcher

/**
 * Matches any indeterminate progress indicator (e.g. [androidx.compose.material3.CircularProgressIndicator]).
 * The resilience suites assert zero of these remain once a screen reaches a terminal state — no
 * screen may hang on a spinner while the backend is unreachable.
 */
val indeterminateSpinner: SemanticsMatcher = SemanticsMatcher.expectValue(
    SemanticsProperties.ProgressBarRangeInfo,
    ProgressBarRangeInfo.Indeterminate,
)
