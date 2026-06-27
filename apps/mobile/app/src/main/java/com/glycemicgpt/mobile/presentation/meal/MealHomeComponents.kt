package com.glycemicgpt.mobile.presentation.meal

import androidx.compose.foundation.background
import androidx.compose.foundation.gestures.detectDragGestures
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxScope
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.PhotoCamera
import androidx.compose.material.icons.filled.Restaurant
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.ExtendedFloatingActionButton
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.layout.onSizeChanged
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.semantics.CustomAccessibilityAction
import androidx.compose.ui.semantics.customActions
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.IntOffset
import androidx.compose.ui.unit.IntSize
import androidx.compose.ui.unit.dp
import com.glycemicgpt.mobile.data.meal.FoodRecord
import kotlin.math.roundToInt

/**
 * Home "Recent meal" glance: the most recent logged meal with its carb range, confidence, and the
 * persistent safety qualifier. Rendered only when at least one meal exists, so non-users never see it.
 */
@Composable
fun RecentMealCard(
    record: FoodRecord,
    onViewAll: () -> Unit,
    modifier: Modifier = Modifier,
) {
    Card(
        modifier = modifier
            .fillMaxWidth()
            .testTag("home_recent_meal_card"),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface),
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text(
                    text = "Recent meal",
                    style = MaterialTheme.typography.titleMedium,
                    fontWeight = FontWeight.SemiBold,
                    color = MaterialTheme.colorScheme.onSurface,
                    modifier = Modifier.weight(1f),
                )
                TextButton(onClick = onViewAll, modifier = Modifier.testTag("home_recent_meal_view_all")) {
                    Text("View all")
                }
            }
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(12.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                // No image is returned from the backend; show a neutral placeholder thumbnail.
                Box(
                    modifier = Modifier
                        .size(56.dp)
                        .clip(RoundedCornerShape(10.dp))
                        .background(MaterialTheme.colorScheme.surfaceVariant),
                    contentAlignment = Alignment.Center,
                ) {
                    Icon(
                        imageVector = Icons.Default.Restaurant,
                        contentDescription = null,
                        tint = MaterialTheme.colorScheme.onSurfaceVariant,
                        modifier = Modifier.size(24.dp),
                    )
                }
                Column(modifier = Modifier.weight(1f)) {
                    if (!record.foodDescription.isNullOrBlank()) {
                        Text(
                            text = record.foodDescription,
                            style = MaterialTheme.typography.titleSmall,
                            color = MaterialTheme.colorScheme.onSurface,
                        )
                    }
                    Text(
                        text = formatCarbRange(record.displayRange),
                        style = MaterialTheme.typography.titleMedium,
                        fontWeight = FontWeight.SemiBold,
                        color = MaterialTheme.colorScheme.onSurface,
                    )
                    Text(
                        text = "${formatMealTimestamp(record.mealTimestamp)} · " +
                            confidenceLabel(record.confidence).lowercase(),
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }
            VerifyBeforeDosingQualifier()
        }
    }
}

/** Extended camera FAB on Home that opens the meal capture screen. */
@Composable
fun MealFab(onClick: () -> Unit, modifier: Modifier = Modifier) {
    ExtendedFloatingActionButton(
        onClick = onClick,
        icon = { Icon(Icons.Default.PhotoCamera, contentDescription = null) },
        text = { Text("Log a meal") },
        modifier = modifier.testTag("home_meal_fab"),
    )
}

/**
 * Inset the FAB keeps from the container edges in its *default* resting position. A deliberate drag
 * may still place the FAB flush to an edge (the clamp uses the full container bounds); this margin
 * only gives the untouched default placement some breathing room.
 */
private val FAB_EDGE_MARGIN = 16.dp

/** TalkBack action label to return the FAB to its default placement (drag is pointer-only). */
internal const val RESET_FAB_ACTION_LABEL = "Reset position to default"

/**
 * The Home "Log a meal" FAB, draggable so the user can move it off their data and back. Wraps the
 * tap-only [MealFab]: the FAB keeps its own onClick, while this owns the drag offset, so a tap still
 * navigates and a drag (past touch slop) repositions instead of clicking.
 *
 * Positions are clamped to [containerSizePx] -- which the host has already inset for system bars --
 * so the FAB can never strand off-screen. A settled position is reported via [onOffsetSettled] for
 * persistence; [savedOffset] restores it, re-clamped to the current bounds so a stale value (from a
 * smaller past layout, or the FAB toggling hidden then shown) can't place it out of view. [onReset]
 * clears the saved position so the accessibility action can return the FAB to its default spot.
 */
@Composable
fun BoxScope.DraggableMealFab(
    containerSizePx: IntSize,
    savedOffset: FabOffset?,
    onClick: () -> Unit,
    onOffsetSettled: (FabOffset) -> Unit,
    onReset: () -> Unit,
) {
    val marginPx = with(LocalDensity.current) { FAB_EDGE_MARGIN.toPx() }
    var fabSizePx by remember { mutableStateOf(IntSize.Zero) }
    // The pointerInput(Unit) gesture closures below are created once and capture their scope, so a
    // raw [containerSizePx] read there would freeze at the first-frame size (the parent only learns
    // its size later, via onSizeChanged). Route it through a stable State so the drag always clamps
    // against the *current* bounds -- including after a rotation/resize.
    val container by rememberUpdatedState(containerSizePx)
    // The user's chosen position, or null until they first drag (then use the default placement).
    // The key is intentionally absent so this single MutableState stays stable for the gesture
    // handler's lifetime (a re-key would allocate a new state and strand the drag closures on a dead
    // one). A changed [savedOffset] -- a late settings load, or a reset -- is synced into that same
    // stable state below, so the closures keep reading the live value.
    var dragOffset by remember { mutableStateOf(savedOffset) }
    LaunchedEffect(savedOffset) { dragOffset = savedOffset }

    // Resolve to a concrete, clamped, on-screen position from the latest measured sizes. Computed in
    // the placement lambda below (not a LaunchedEffect) so it tracks the current sizes without a
    // recomposition lag. Until the FAB and container are measured it resolves to the top-left; that
    // is corrected within the same layout pass once onSizeChanged reports their real sizes.
    fun resolve(): FabOffset {
        val fabW = fabSizePx.width.toFloat()
        val fabH = fabSizePx.height.toFloat()
        val containerW = container.width.toFloat()
        val containerH = container.height.toFloat()
        val base = dragOffset ?: defaultFabOffset(fabW, fabH, containerW, containerH, marginPx)
        return clampFabOffset(base, fabW, fabH, containerW, containerH)
    }

    MealFab(
        onClick = onClick,
        modifier = Modifier
            .align(Alignment.TopStart)
            .offset {
                val resolved = resolve()
                IntOffset(resolved.x.roundToInt(), resolved.y.roundToInt())
            }
            .onSizeChanged { fabSizePx = it }
            .semantics {
                // Drag is pointer-only; give screen-reader users a way to recover the FAB to its
                // default spot if it ends up over content they need.
                customActions = listOf(
                    CustomAccessibilityAction(RESET_FAB_ACTION_LABEL) {
                        dragOffset = null
                        onReset()
                        true
                    },
                )
            }
            .pointerInput(Unit) {
                detectDragGestures(
                    onDragEnd = { onOffsetSettled(resolve()) },
                    onDragCancel = { onOffsetSettled(resolve()) },
                ) { change, dragAmount ->
                    // Consuming only here (past touch slop) keeps a tap free to reach the FAB's
                    // onClick, while a drag repositions without triggering a click.
                    change.consume()
                    // Start from the current clamped on-screen position (not the raw stored value),
                    // so a drag right after a container shrink can't jump from a now-stale base.
                    val from = resolve()
                    dragOffset = clampFabOffset(
                        FabOffset(from.x + dragAmount.x, from.y + dragAmount.y),
                        fabSizePx.width.toFloat(),
                        fabSizePx.height.toFloat(),
                        container.width.toFloat(),
                        container.height.toFloat(),
                    )
                }
            },
    )
}
