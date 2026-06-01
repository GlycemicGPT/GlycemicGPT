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

/**
 * Type of device participating in a SAKE handshake.
 *
 * <p>The numeric values are wire-stable: they are serialized into the key-database header and into
 * handshake messages.
 */
public enum DeviceType {
    INSULIN_PUMP(0x1),
    GLUCOSE_SENSOR(0x2),
    BLOOD_GLUCOSE_METER(0x3),
    MOBILE_APPLICATION(0x4),
    CARE_LINK_UPLOAD_APPLICATION(0x5),
    FIRMWARE_UPDATE_APPLICATION(0x6),
    DIAGNOSTIC_APPLICATION(0x7),
    PRIMARY_DISPLAY(0x8);

    /** Alias: secondary display devices share the same wire value as mobile applications. */
    public static final DeviceType SECONDARY_DISPLAY = MOBILE_APPLICATION;

    private final int value;

    DeviceType(int value) {
        this.value = value;
    }

    /**
     * @return the wire value (1 byte, unsigned).
     */
    public int value() {
        return value;
    }

    /**
     * Resolve a device type from its wire value.
     *
     * @throws IllegalArgumentException if no device type matches.
     */
    public static DeviceType fromValue(int value) {
        for (DeviceType type : values()) {
            if (type.value == value) {
                return type;
            }
        }
        throw new IllegalArgumentException("Unknown device type value: " + value);
    }
}
