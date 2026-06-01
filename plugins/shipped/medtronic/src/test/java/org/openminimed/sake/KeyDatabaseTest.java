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
import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertThrows;

import org.junit.Test;

public class KeyDatabaseTest {

    /**
     * The three baked-in key databases from the reference Python implementation
     * (pysake/constants.py). They are the canonical round-trip vectors for this parser: any change
     * to the serialization must keep these byte-identical.
     */
    private static final String HEX_G4_CGM =
            "5fe5928308010230f0b50df613f2e429c8c5e8713854add1a69b837235a3e974"
                    + "304d8055ccb397838b90823c73236d6a83dcc9db3a2a939ff16145ca4169ef93"
                    + "a7fa39b20962b05e57413bff8b3d61fce0dfef2c43b326";

    private static final String HEX_PUMP_EXTRACTED =
            "f75995e70401011bc1bf7cbf36fa1e2367d795ff09211903da6afbe986b650f1"
                    + "4179c0e6852e0ce393781078ffc6f51919e2eaefbde69b8eca21e41ab59b881a"
                    + "0bea0286ea91dc7582a86a714e1737f558f0d66dc1895c";

    private static final String HEX_PUMP_HARDCODED =
            "c2cdfdd1040101fce36ed66ef21def3b0763975494b239038ebe8606f79a9bf0"
                    + "0d9f11b6db04c7c0434787cbf00d5476289c22288e2105ae40e01391837f9476"
                    + "fa5003895c5a1afe35662a2a6211826af016eebe30e4ba";

    @Test
    public void parsesG4Cgm() {
        KeyDatabase db = KeyDatabase.fromBytes(Hex.decode(HEX_G4_CGM));
        assertEquals(DeviceType.PRIMARY_DISPLAY, db.localDeviceType());
        assertEquals(1, db.remoteDevices().size());
        assertNotNull(db.remoteDevices().get(DeviceType.GLUCOSE_SENSOR));
    }

    @Test
    public void parsesPumpExtracted() {
        KeyDatabase db = KeyDatabase.fromBytes(Hex.decode(HEX_PUMP_EXTRACTED));
        assertEquals(DeviceType.MOBILE_APPLICATION, db.localDeviceType());
        assertEquals(1, db.remoteDevices().size());
        assertNotNull(db.remoteDevices().get(DeviceType.INSULIN_PUMP));
    }

    @Test
    public void parsesPumpHardcoded() {
        KeyDatabase db = KeyDatabase.fromBytes(Hex.decode(HEX_PUMP_HARDCODED));
        assertEquals(DeviceType.MOBILE_APPLICATION, db.localDeviceType());
        assertEquals(1, db.remoteDevices().size());
        assertNotNull(db.remoteDevices().get(DeviceType.INSULIN_PUMP));
    }

    @Test
    public void roundTripIsByteIdentical() {
        for (String hex : new String[] {HEX_G4_CGM, HEX_PUMP_EXTRACTED, HEX_PUMP_HARDCODED}) {
            byte[] original = Hex.decode(hex);
            byte[] roundTripped = KeyDatabase.fromBytes(original).toBytes();
            assertArrayEquals(
                    "Round trip differed for " + hex.substring(0, 16) + "...",
                    original,
                    roundTripped);
        }
    }

    @Test
    public void rejectsCrcMismatch() {
        byte[] corrupt = Hex.decode(HEX_PUMP_EXTRACTED);
        corrupt[0] ^= (byte) 0x01;
        assertThrows(IllegalArgumentException.class, () -> KeyDatabase.fromBytes(corrupt));
    }

    @Test
    public void rejectsTruncatedBuffer() {
        byte[] truncated = new byte[] {0x00, 0x00, 0x00, 0x00, 0x04};
        assertThrows(IllegalArgumentException.class, () -> KeyDatabase.fromBytes(truncated));
    }

    @Test
    public void constructorRejectsRemoteDeviceCountAboveWireLimit() {
        // DeviceType only has eight enum values, so we cannot actually fill 256 entries.
        // Use a size-only Map view to drive the constructor down the size-validation branch.
        java.util.Map<DeviceType, StaticKeys> oversize =
                new java.util.AbstractMap<>() {
                    @Override
                    public java.util.Set<Entry<DeviceType, StaticKeys>> entrySet() {
                        return java.util.Set.of();
                    }

                    @Override
                    public int size() {
                        return KeyDatabase.MAX_REMOTE_DEVICES + 1;
                    }
                };
        assertThrows(
                IllegalArgumentException.class,
                () -> new KeyDatabase(DeviceType.MOBILE_APPLICATION, oversize, new byte[4]));
    }

    @Test
    public void reverseProducesValidDatabase() {
        for (String hex : new String[] {HEX_G4_CGM, HEX_PUMP_EXTRACTED, HEX_PUMP_HARDCODED}) {
            KeyDatabase original = KeyDatabase.fromBytes(Hex.decode(hex));
            KeyDatabase reversed = original.reverse();
            assertEquals(
                    original.remoteDevices().keySet().iterator().next(),
                    reversed.localDeviceType());
            assertEquals(1, reversed.remoteDevices().size());
            assertNotNull(reversed.remoteDevices().get(original.localDeviceType()));

            byte[] reversedBytes = reversed.toBytes();
            KeyDatabase reparsed = KeyDatabase.fromBytes(reversedBytes);
            assertEquals(reversed.localDeviceType(), reparsed.localDeviceType());
        }
    }
}
