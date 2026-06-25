package com.glycemicgpt.mobile.presentation.meal

import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.layout.onSizeChanged
import androidx.compose.ui.test.getUnclippedBoundsInRoot
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.onRoot
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performTouchInput
import androidx.compose.ui.test.swipe
import androidx.compose.ui.unit.IntSize
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
 * the drag handler), a drag repositions without navigating, the position is clamped on-screen, and a
 * saved position is restored. The tap-vs-drag disambiguation is the case most likely to regress.
 */
@RunWith(AndroidJUnit4::class)
class DraggableMealFabUiTest {

    @get:Rule
    val compose = createComposeRule()

    private var clicks = 0
    private var settled: FabOffset? = null

    private fun setContent(savedOffset: FabOffset? = null) {
        compose.setContent {
            GlycemicGptTheme {
                var containerSize by remember { mutableStateOf(IntSize.Zero) }
                Box(
                    modifier = Modifier
                        .fillMaxSize()
                        .onSizeChanged { containerSize = it },
                ) {
                    DraggableMealFab(
                        containerSizePx = containerSize,
                        savedOffset = savedOffset,
                        onClick = { clicks++ },
                        onOffsetSettled = { settled = it },
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
        assertTrue("rests near the bottom edge", fab.bottom.value > root.bottom.value - 48f)
        assertTrue("rests near the end edge", fab.right.value > root.right.value - 48f)
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
    }

    @Test
    fun a_saved_position_is_restored() {
        // A saved top-left position must place the FAB at the top-left, not the default bottom-end.
        setContent(savedOffset = FabOffset(0f, 0f))
        compose.waitForIdle()

        val fab = fabBounds()
        assertTrue("restored at the top, not bottom-end", fab.top.value < 100f)
        assertTrue("restored at the start, not bottom-end", fab.left.value < 100f)
    }

    private companion object {
        const val FAB_TAG = "home_meal_fab"
        const val POS_EPS = 2f
    }
}
