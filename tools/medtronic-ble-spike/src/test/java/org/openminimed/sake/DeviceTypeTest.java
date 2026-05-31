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
import static org.junit.jupiter.api.Assertions.assertSame;
import static org.junit.jupiter.api.Assertions.assertThrows;

import org.junit.jupiter.api.Test;

class DeviceTypeTest {

    @Test
    void wireValuesAreStable() {
        assertEquals(0x1, DeviceType.INSULIN_PUMP.value());
        assertEquals(0x2, DeviceType.GLUCOSE_SENSOR.value());
        assertEquals(0x3, DeviceType.BLOOD_GLUCOSE_METER.value());
        assertEquals(0x4, DeviceType.MOBILE_APPLICATION.value());
        assertEquals(0x5, DeviceType.CARE_LINK_UPLOAD_APPLICATION.value());
        assertEquals(0x6, DeviceType.FIRMWARE_UPDATE_APPLICATION.value());
        assertEquals(0x7, DeviceType.DIAGNOSTIC_APPLICATION.value());
        assertEquals(0x8, DeviceType.PRIMARY_DISPLAY.value());
    }

    @Test
    void secondaryDisplayIsAliasForMobileApplication() {
        assertSame(DeviceType.MOBILE_APPLICATION, DeviceType.SECONDARY_DISPLAY);
        assertEquals(0x4, DeviceType.SECONDARY_DISPLAY.value());
    }

    @Test
    void fromValueResolvesEachWireValue() {
        for (DeviceType type : DeviceType.values()) {
            assertSame(type, DeviceType.fromValue(type.value()));
        }
    }

    @Test
    void fromValueRejectsUnknownValue() {
        assertThrows(IllegalArgumentException.class, () -> DeviceType.fromValue(0xFF));
    }
}
