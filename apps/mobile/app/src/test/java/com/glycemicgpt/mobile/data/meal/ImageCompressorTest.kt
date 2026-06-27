package com.glycemicgpt.mobile.data.meal

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/** Unit tests for the pure sizing helpers of [ImageCompressor] (no Android device needed). */
class ImageCompressorTest {

    @Test
    fun `inSampleSize is 1 when image already fits`() {
        assertEquals(1, ImageCompressor.calculateInSampleSize(800, 600, 1280))
        assertEquals(1, ImageCompressor.calculateInSampleSize(1280, 1280, 1280))
    }

    @Test
    fun `inSampleSize subsamples large images to a power of two`() {
        // 4000 longest edge, target 1280: 4000/2=2000 still >= 1280, 4000/4=1000 < 1280 -> 2.
        assertEquals(2, ImageCompressor.calculateInSampleSize(4000, 3000, 1280))
        // 6000 longest edge: 6000/4=1500 >= 1280, 6000/8=750 < 1280 -> 4.
        assertEquals(4, ImageCompressor.calculateInSampleSize(6000, 4000, 1280))
    }

    @Test
    fun `inSampleSize never produces an edge below the target`() {
        val width = 5000
        val height = 4000
        val maxDimension = 1280
        val sample = ImageCompressor.calculateInSampleSize(width, height, maxDimension)
        val longestAfter = maxOf(width, height) / sample
        assertTrue("longest edge $longestAfter should stay >= $maxDimension", longestAfter >= maxDimension)
    }

    @Test
    fun `targetDimensions keeps small images unchanged`() {
        assertEquals(800 to 600, ImageCompressor.targetDimensions(800, 600, 1280))
    }

    @Test
    fun `targetDimensions scales down preserving aspect ratio`() {
        val (w, h) = ImageCompressor.targetDimensions(2560, 1920, 1280)
        assertEquals(1280, w)
        assertEquals(960, h)
    }

    @Test
    fun `targetDimensions never returns a zero edge`() {
        val (w, h) = ImageCompressor.targetDimensions(4000, 1, 1280)
        assertEquals(1280, w)
        assertTrue(h >= 1)
    }
}
