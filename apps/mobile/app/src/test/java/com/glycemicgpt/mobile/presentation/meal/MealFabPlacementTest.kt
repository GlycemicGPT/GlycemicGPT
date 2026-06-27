package com.glycemicgpt.mobile.presentation.meal

import org.junit.Assert.assertEquals
import org.junit.Test

/**
 * Guards the draggable meal FAB's placement math: the FAB can never strand off-screen (clamped to
 * the container) and its default resting spot is the bottom-end, inset by the edge margin.
 */
class MealFabPlacementTest {

    // A representative container (px) and FAB size for the clamp cases.
    private val containerW = 1080f
    private val containerH = 1920f
    private val fabW = 360f
    private val fabH = 144f
    private val maxX = containerW - fabW // 720
    private val maxY = containerH - fabH // 1776

    private fun clamp(x: Float, y: Float) =
        clampFabOffset(FabOffset(x, y), fabW, fabH, containerW, containerH)

    @Test
    fun `an in-bounds offset is left unchanged`() {
        val result = clamp(200f, 500f)
        assertEquals(200f, result.x, EPS)
        assertEquals(500f, result.y, EPS)
    }

    @Test
    fun `dragging past the right edge clamps to the right bound`() {
        val result = clamp(containerW + 500f, 500f)
        assertEquals(maxX, result.x, EPS)
    }

    @Test
    fun `dragging past the bottom edge clamps to the bottom bound`() {
        val result = clamp(200f, containerH + 500f)
        assertEquals(maxY, result.y, EPS)
    }

    @Test
    fun `dragging past the left or top edge clamps to zero, never negative`() {
        val result = clamp(-300f, -300f)
        assertEquals(0f, result.x, EPS)
        assertEquals(0f, result.y, EPS)
    }

    @Test
    fun `a container smaller than the FAB pins it to the top-left, not off-screen`() {
        val result = clampFabOffset(FabOffset(50f, 50f), fabW, fabH, 100f, 100f)
        assertEquals(0f, result.x, EPS)
        assertEquals(0f, result.y, EPS)
    }

    @Test
    fun `an unmeasured zero container yields the top-left, not a negative offset`() {
        val result = clampFabOffset(FabOffset(0f, 0f), fabW, fabH, 0f, 0f)
        assertEquals(0f, result.x, EPS)
        assertEquals(0f, result.y, EPS)
    }

    @Test
    fun `the default position is the bottom-end, inset by the margin on both axes`() {
        val margin = 48f
        val result = defaultFabOffset(fabW, fabH, containerW, containerH, margin)
        assertEquals(containerW - fabW - margin, result.x, EPS)
        assertEquals(containerH - fabH - margin, result.y, EPS)
    }

    @Test
    fun `the default position stays on-screen once clamped`() {
        val margin = 48f
        val default = defaultFabOffset(fabW, fabH, containerW, containerH, margin)
        val clamped = clampFabOffset(default, fabW, fabH, containerW, containerH)
        // The bottom-end default is already within bounds, so clamping is a no-op.
        assertEquals(default.x, clamped.x, EPS)
        assertEquals(default.y, clamped.y, EPS)
    }

    private companion object {
        const val EPS = 0.001f
    }
}
