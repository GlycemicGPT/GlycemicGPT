/*
 * Vendored from OpenMinimed JavaSake (https://github.com/OpenMinimed/JavaSake)
 * at commit 00c08ae -- verbatim except for this header (verified byte-identical).
 *
 * Copyright (C) OpenMinimed contributors: palmarci (Pal Marci), drfubar,
 * Morten Fyhn Amundsen, Stenium. Original medtronic-bt-decrypt PoC by @planiitis.
 * Android/JVM port maintained by jlengelbrecht.
 *
 * This file is part of GlycemicGPT and is redistributed under the GNU General
 * Public License v3.0, the license under which OpenMinimed makes it available
 * and under which GlycemicGPT itself is released. Used with the author's
 * permission. See tools/medtronic-ble-spike/LICENSE and README.md.
 *
 * Only this attribution header was added; the file is otherwise byte-identical to
 * the pinned upstream commit (applies to vendored main sources and tests alike).
 * Re-vendor from upstream rather than editing here if it drifts.
 */

package org.openminimed.sake;

import static org.junit.Assert.assertArrayEquals;
import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertThrows;
import static org.junit.Assert.assertTrue;

import org.junit.Test;

/** Tests for the test-only {@link Hex} helper, including its diagnostic error indices. */
public class HexTest {

    @Test
    public void roundTripIsLossless() {
        byte[] data = {0x00, 0x12, (byte) 0xAB, (byte) 0xFF};
        assertArrayEquals(data, Hex.decode(Hex.encode(data)));
    }

    @Test
    public void rejectsOddLength() {
        assertThrows(IllegalArgumentException.class, () -> Hex.decode("abc"));
    }

    @Test
    public void invalidHighNibbleErrorReportsHighIndex() {
        IllegalArgumentException ex =
                assertThrows(IllegalArgumentException.class, () -> Hex.decode("gf"));
        assertTrue(
                "expected high-nibble error to name index 0, got: " + ex.getMessage(),
                ex.getMessage().contains("index 0"));
    }

    @Test
    public void invalidLowNibbleErrorReportsLowIndex() {
        IllegalArgumentException ex =
                assertThrows(IllegalArgumentException.class, () -> Hex.decode("fg"));
        assertEquals(
                "low-nibble error must point at the offending second character",
                "Invalid hex character at index 1",
                ex.getMessage()
                );
    }
}
