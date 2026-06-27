package com.glycemicgpt.mobile.presentation.meal

import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.size
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.layout.onSizeChanged
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.semantics.SemanticsActions
import androidx.compose.ui.test.getUnclippedBoundsInRoot
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.onRoot
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performTouchInput
import androidx.compose.ui.test.swipe
import androidx.compose.ui.unit.IntSize
import androidx.compose.ui.unit.dp
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.glycemicgpt.mobile.presentation.theme.GlycemicGptTheme
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

/**
 * Behavioral guard for the draggable "Log a meal" FAB: a tap still navigates (it isn't swallowed by
 * the drag handler), a drag repositions without navigating, the position is clamped on-screen (on
 * restore and after a container shrink), and the accessibility reset action returns it to the
 * default. The tap-vs-drag disambiguation and the off-screen re-clamp are the cases most likely to
 * regress.
 */
@RunWith(AndroidJUnit4::class)
class DraggableMealFabUiTest {

    @get:Rule
    val compose = createComposeRule()

    private var clicks = 0
    private var settled: FabOffset? = null
    private var resetCalled = false
    private var lastContainerPx = IntSize.Zero

    // A test-controlled container side for the shrink/re-clamp case; read in [setSizedContent].
    private val containerSide = mutableStateOf(DEFAULT_CONTAINER_SIDE)

    /** Full-screen container -- the common case (container == window). */
    private fun setContent(savedOffset: FabOffset? = null) {
        compose.setContent {
            GlycemicGptTheme {
                var containerSize by remember { mutableStateOf(IntSize.Zero) }
                Box(
                    modifier = Modifier
                        .fillMaxSize()
                        .onSizeChanged {
                            containerSize = it
                            lastContainerPx = it
                        },
                ) {
                    DraggableMealFab(
                        containerSizePx = containerSize,
                        savedOffset = savedOffset,
                        onClick = { clicks++ },
                        onOffsetSettled = { settled = it },
                        onReset = { resetCalled = true },
                    )
                }
            }
        }
    }

    /** Container whose size is driven by [containerSide], so a test can shrink it and re-clamp. */
    private fun setSizedContent(savedOffset: FabOffset?) {
        compose.setContent {
            GlycemicGptTheme {
                val side by containerSide
                var containerSize by remember { mutableStateOf(IntSize.Zero) }
                Box(
                    modifier = Modifier
                        .size(side)
                        .testTag(CONTAINER_TAG)
                        .onSizeChanged { containerSize = it },
                ) {
                    DraggableMealFab(
                        containerSizePx = containerSize,
                        savedOffset = savedOffset,
                        onClick = { clicks++ },
                        onOffsetSettled = { settled = it },
                        onReset = { resetCalled = true },
                    )
                }
            }
        }
    }

    private fun fabBounds() = compose.onNodeWithTag(FAB_TAG).getUnclippedBoundsInRoot()

    @Test
    fun tap_navigates_without_repositioning() {
        setContent()

        compose.onNodeWithTag(FAB_TAG).performClick()
        compose.waitForIdle()

        assertEquals("a tap must trigger navigation", 1, clicks)
        // No drag settled, so the position is untouched -- a tap is not a reposition.
        assertNull("a tap must not settle a new position", settled)
    }

    @Test
    fun default_position_rests_at_the_bottom_end() {
        setContent()
        compose.waitForIdle()

        val root = compose.onRoot().getUnclippedBoundsInRoot()
        val fab = fabBounds()
        // With no saved offset the FAB defaults to the bottom-end, not the top-left -- this pins the
        // default-placement wiring (and would catch a never-settling zero-size resolve()).
        assertTrue("rests near the bottom edge", fab.bottom.value > root.bottom.value - EDGE_SLACK)
        assertTrue("rests near the end edge", fab.right.value > root.right.value - EDGE_SLACK)
    }

    @Test
    fun drag_repositions_without_navigating() {
        setContent()
        val before = fabBounds()

        compose.onNodeWithTag(FAB_TAG).performTouchInput {
            swipe(start = center, end = Offset(center.x - 250f, center.y - 350f), durationMillis = 200)
        }
        compose.waitForIdle()

        assertEquals("a drag must not navigate", 0, clicks)
        assertNotNull("a drag must settle a new position", settled)
        val after = fabBounds()
        // Dragged up and to the left, so the FAB's top-left moves accordingly.
        assertTrue("FAB should move up", after.top.value < before.top.value - 1f)
        assertTrue("FAB should move left", after.left.value < before.left.value - 1f)
    }

    @Test
    fun small_drag_follows_the_finger_and_does_not_snap_to_the_origin() {
        setContent()
        compose.waitForIdle()
        val root = compose.onRoot().getUnclippedBoundsInRoot()
        val before = fabBounds()

        compose.onNodeWithTag(FAB_TAG).performTouchInput {
            swipe(start = center, end = Offset(center.x - 120f, center.y - 120f), durationMillis = 200)
        }
        compose.waitForIdle()

        val after = fabBounds()
        // A small drag from the bottom-end default nudges the FAB up a little; it must follow the
        // finger and stay in the lower half -- not collapse to the top-left origin, which clamping
        // against a stale/zero container size would force.
        assertTrue("FAB moved up with the finger", after.top.value < before.top.value)
        assertTrue("FAB stayed in the lower half", after.bottom.value > root.bottom.value / 2)
    }

    @Test
    fun drag_past_the_edge_keeps_the_fab_on_screen() {
        setContent()
        compose.waitForIdle()

        compose.onNodeWithTag(FAB_TAG).performTouchInput {
            // Drag far past the bottom-right corner; the clamp must keep the FAB on-screen.
            swipe(start = center, end = Offset(center.x + 5000f, center.y + 5000f), durationMillis = 200)
        }
        compose.waitForIdle()

        val root = compose.onRoot().getUnclippedBoundsInRoot()
        val fab = fabBounds()
        assertTrue("left in bounds", fab.left.value >= root.left.value - POS_EPS)
        assertTrue("top in bounds", fab.top.value >= root.top.value - POS_EPS)
        assertTrue("right in bounds", fab.right.value <= root.right.value + POS_EPS)
        assertTrue("bottom in bounds", fab.bottom.value <= root.bottom.value + POS_EPS)

        // The *persisted* value must be clamped too, not just the visual bounds -- a drag past the
        // edge can't store an out-of-range offset that a later restore would have to fix up.
        val fabPx = compose.onNodeWithTag(FAB_TAG).fetchSemanticsNode().size
        val s = settled
        assertNotNull("a drag must settle a position", s)
        assertTrue("settled x clamped", s!!.x in 0f..(lastContainerPx.width - fabPx.width).toFloat())
        assertTrue("settled y clamped", s.y in 0f..(lastContainerPx.height - fabPx.height).toFloat())
    }

    @Test
    fun a_saved_position_is_restored() {
        // A saved top-left position must place the FAB at the top-left, not the default bottom-end.
        setContent(savedOffset = FabOffset(0f, 0f))
        compose.waitForIdle()

        val fab = fabBounds()
        assertTrue("restored at the top, not bottom-end", fab.top.value < NEAR_EDGE)
        assertTrue("restored at the start, not bottom-end", fab.left.value < NEAR_EDGE)
    }

    @Test
    fun a_stale_out_of_bounds_saved_position_is_reclamped_on_screen() {
        // A saved offset far outside any container (e.g. from a larger past layout) must be pulled
        // back on-screen on restore -- this pins the re-clamp path savedOffset -> resolve() -> clamp.
        setContent(savedOffset = FabOffset(99_999f, 99_999f))
        compose.waitForIdle()

        val root = compose.onRoot().getUnclippedBoundsInRoot()
        val fab = fabBounds()
        assertTrue("left in bounds", fab.left.value >= root.left.value - POS_EPS)
        assertTrue("top in bounds", fab.top.value >= root.top.value - POS_EPS)
        assertTrue("right in bounds", fab.right.value <= root.right.value + POS_EPS)
        assertTrue("bottom in bounds", fab.bottom.value <= root.bottom.value + POS_EPS)
    }

    @Test
    fun shrinking_the_container_reclamps_the_fab_on_screen() {
        // Save the FAB far in the corner of a large container, then shrink (the rotation/resize case):
        // the re-clamp must pull it back inside the now-smaller bounds.
        setSizedContent(savedOffset = FabOffset(100_000f, 100_000f))
        compose.waitForIdle()

        compose.runOnIdle { containerSide.value = SHRUNK_CONTAINER_SIDE }
        compose.waitForIdle()

        val container = compose.onNodeWithTag(CONTAINER_TAG).getUnclippedBoundsInRoot()
        val fab = fabBounds()
        assertTrue("left in bounds", fab.left.value >= container.left.value - POS_EPS)
        assertTrue("top in bounds", fab.top.value >= container.top.value - POS_EPS)
        assertTrue("right in bounds", fab.right.value <= container.right.value + POS_EPS)
        assertTrue("bottom in bounds", fab.bottom.value <= container.bottom.value + POS_EPS)
    }

    @Test
    fun accessibility_reset_action_returns_the_fab_to_the_default() {
        setContent()
        compose.waitForIdle()
        // Move it well away from the default first.
        compose.onNodeWithTag(FAB_TAG).performTouchInput {
            swipe(start = center, end = Offset(center.x - 200f, center.y - 300f), durationMillis = 200)
        }
        compose.waitForIdle()

        val resetAction = compose.onNodeWithTag(FAB_TAG)
            .fetchSemanticsNode()
            .config.getOrElseNullable(SemanticsActions.CustomActions) { null }
            .orEmpty()
            .firstOrNull { it.label == RESET_FAB_ACTION_LABEL }
        assertNotNull("a reset accessibility action must be exposed for screen readers", resetAction)
        compose.runOnUiThread { resetAction!!.action() }
        compose.waitForIdle()

        assertTrue("reset callback fired", resetCalled)
        val root = compose.onRoot().getUnclippedBoundsInRoot()
        val fab = fabBounds()
        assertTrue("returned to the bottom edge", fab.bottom.value > root.bottom.value - EDGE_SLACK)
        assertTrue("returned to the end edge", fab.right.value > root.right.value - EDGE_SLACK)
    }

    private companion object {
        const val FAB_TAG = "home_meal_fab"
        const val CONTAINER_TAG = "fab_container"

        // Tolerance for visual-bounds assertions (sub-pixel rounding on getUnclippedBoundsInRoot).
        const val POS_EPS = 2f

        // The default/reset placement rests within this of the bottom-end edge (FAB margin + slack).
        const val EDGE_SLACK = 48f

        // A restored top-left offset sits within this of the origin.
        const val NEAR_EDGE = 100f

        val DEFAULT_CONTAINER_SIDE = 600.dp
        val SHRUNK_CONTAINER_SIDE = 280.dp
    }
}
