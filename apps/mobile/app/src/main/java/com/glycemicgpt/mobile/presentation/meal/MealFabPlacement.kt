package com.glycemicgpt.mobile.presentation.meal

/**
 * Pure placement math for the draggable "Log a meal" FAB, kept free of Compose types so it can be
 * unit-tested on the JVM. All values are pixels relative to the FAB's container.
 */

/** The FAB's top-left position, in pixels from its container's top-left corner. */
data class FabOffset(val x: Float, val y: Float)

/**
 * The FAB's default resting position: the bottom-end of the container, inset by [marginPx] from the
 * right and bottom edges -- reproducing the original fixed `align(BottomEnd).padding(16.dp)` look.
 *
 * The result is not clamped here; callers run it through [clampFabOffset] so a container smaller than
 * the FAB can't produce a negative resting position.
 */
fun defaultFabOffset(
    fabWidth: Float,
    fabHeight: Float,
    containerWidth: Float,
    containerHeight: Float,
    marginPx: Float,
): FabOffset = FabOffset(
    x = containerWidth - fabWidth - marginPx,
    y = containerHeight - fabHeight - marginPx,
)

/**
 * Clamp [offset] so the FAB stays fully inside the container and can never be stranded off-screen.
 * The host insets the container for system bars, so container-relative bounds already keep the FAB
 * out from behind them. When the container is smaller than the FAB, the FAB is pinned to the
 * top-left rather than allowed to drift to a negative position.
 */
fun clampFabOffset(
    offset: FabOffset,
    fabWidth: Float,
    fabHeight: Float,
    containerWidth: Float,
    containerHeight: Float,
): FabOffset {
    val maxX = (containerWidth - fabWidth).coerceAtLeast(0f)
    val maxY = (containerHeight - fabHeight).coerceAtLeast(0f)
    return FabOffset(
        x = offset.x.coerceIn(0f, maxX),
        y = offset.y.coerceIn(0f, maxY),
    )
}
