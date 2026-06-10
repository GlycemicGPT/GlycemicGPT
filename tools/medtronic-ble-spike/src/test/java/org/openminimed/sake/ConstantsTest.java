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

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

import org.junit.jupiter.api.Test;

class ConstantsTest {

    @Test
    void g4CgmLocalIsPrimaryDisplay() {
        assertEquals(DeviceType.PRIMARY_DISPLAY, Constants.KEYDB_G4_CGM.localDeviceType());
        assertNotNull(Constants.KEYDB_G4_CGM.remoteDevices().get(DeviceType.GLUCOSE_SENSOR));
    }

    @Test
    void pumpExtractedLocalIsMobileApplication() {
        assertEquals(
                DeviceType.MOBILE_APPLICATION, Constants.KEYDB_PUMP_EXTRACTED.localDeviceType());
        assertNotNull(Constants.KEYDB_PUMP_EXTRACTED.remoteDevices().get(DeviceType.INSULIN_PUMP));
    }

    @Test
    void pumpHardcodedLocalIsMobileApplication() {
        assertEquals(
                DeviceType.MOBILE_APPLICATION, Constants.KEYDB_PUMP_HARDCODED.localDeviceType());
        assertNotNull(Constants.KEYDB_PUMP_HARDCODED.remoteDevices().get(DeviceType.INSULIN_PUMP));
    }

    @Test
    void availableKeysExposesAllThreeDatabases() {
        assertEquals(3, Constants.AVAILABLE_KEYS.size());
        assertTrue(Constants.AVAILABLE_KEYS.contains(Constants.KEYDB_G4_CGM));
        assertTrue(Constants.AVAILABLE_KEYS.contains(Constants.KEYDB_PUMP_EXTRACTED));
        assertTrue(Constants.AVAILABLE_KEYS.contains(Constants.KEYDB_PUMP_HARDCODED));
    }
}
