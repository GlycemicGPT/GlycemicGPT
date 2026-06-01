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

import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Objects;
import java.util.zip.CRC32;

/**
 * Database of static keys shared between one local device and any number of remote devices.
 *
 * <p>The on-wire layout is:
 *
 * <pre>
 *   [ 4 B CRC32 big-endian over everything that follows ]
 *   [ 1 B local device type ]
 *   [ 1 B n = remote-device count ]
 *   n * { [ 1 B remote device type ][ 80 B StaticKeys ] }
 * </pre>
 *
 * <p>Each entry following the header is therefore 81 bytes and the total serialized length is
 * {@code 6 + 81 * n} bytes.
 */
public final class KeyDatabase {

    private static final int CRC_SIZE = 4;
    private static final int HEADER_SIZE = 6;
    private static final int ENTRY_SIZE = 1 + StaticKeys.SERIALIZED_SIZE;

    private final DeviceType localDeviceType;
    private final Map<DeviceType, StaticKeys> remoteDevices;
    private final byte[] crc;

    /** Maximum number of remote-device entries: the wire format encodes the count in one byte. */
    public static final int MAX_REMOTE_DEVICES = 0xFF;

    public KeyDatabase(
            DeviceType localDeviceType, Map<DeviceType, StaticKeys> remoteDevices, byte[] crc) {
        this.localDeviceType = Objects.requireNonNull(localDeviceType, "localDeviceType");
        Objects.requireNonNull(remoteDevices, "remoteDevices");
        Objects.requireNonNull(crc, "crc");
        if (crc.length != CRC_SIZE) {
            throw new IllegalArgumentException("crc must be " + CRC_SIZE + " bytes");
        }
        if (remoteDevices.size() > MAX_REMOTE_DEVICES) {
            throw new IllegalArgumentException(
                    "remoteDevices size "
                            + remoteDevices.size()
                            + " exceeds wire-format limit "
                            + MAX_REMOTE_DEVICES);
        }
        this.remoteDevices = Collections.unmodifiableMap(new LinkedHashMap<>(remoteDevices));
        this.crc = crc.clone();
    }

    /**
     * Parse a key database from its serialized form.
     *
     * @throws IllegalArgumentException if the buffer is malformed or the CRC does not match.
     */
    public static KeyDatabase fromBytes(byte[] data) {
        Objects.requireNonNull(data, "data");
        if (data.length < HEADER_SIZE) {
            throw new IllegalArgumentException("Buffer is shorter than the database header");
        }

        byte[] storedCrc = new byte[CRC_SIZE];
        System.arraycopy(data, 0, storedCrc, 0, CRC_SIZE);

        byte[] payload = new byte[data.length - CRC_SIZE];
        System.arraycopy(data, CRC_SIZE, payload, 0, payload.length);

        byte[] computedCrc = computeCrc(payload);
        if (!java.util.Arrays.equals(storedCrc, computedCrc)) {
            throw new IllegalArgumentException(
                    "CRC mismatch: stored=" + hex(storedCrc) + " computed=" + hex(computedCrc));
        }

        DeviceType localDeviceType = DeviceType.fromValue(payload[0] & 0xFF);
        int n = payload[1] & 0xFF;
        if (payload.length != 2 + ENTRY_SIZE * n) {
            throw new IllegalArgumentException(
                    "Invalid database length for n=" + n + ": " + payload.length);
        }

        Map<DeviceType, StaticKeys> remotes = new LinkedHashMap<>();
        for (int i = 0; i < n; i++) {
            int base = 2 + i * ENTRY_SIZE;
            DeviceType remoteType = DeviceType.fromValue(payload[base] & 0xFF);
            byte[] keys = new byte[StaticKeys.SERIALIZED_SIZE];
            System.arraycopy(payload, base + 1, keys, 0, StaticKeys.SERIALIZED_SIZE);
            remotes.put(remoteType, StaticKeys.fromBytes(keys));
        }

        return new KeyDatabase(localDeviceType, remotes, storedCrc);
    }

    /**
     * @return the serialized database with a freshly computed CRC.
     */
    public byte[] toBytes() {
        byte[] payload = payloadBytes();
        byte[] crcBytes = computeCrc(payload);
        byte[] out = new byte[CRC_SIZE + payload.length];
        System.arraycopy(crcBytes, 0, out, 0, CRC_SIZE);
        System.arraycopy(payload, 0, out, CRC_SIZE, payload.length);
        return out;
    }

    /**
     * Return a new database with the local/remote roles swapped.
     *
     * <p>Requires exactly one remote device.
     *
     * @throws IllegalStateException if this database does not contain exactly one remote device.
     */
    public KeyDatabase reverse() {
        if (remoteDevices.size() != 1) {
            throw new IllegalStateException("reverse() requires exactly one remote device");
        }
        Map.Entry<DeviceType, StaticKeys> only = remoteDevices.entrySet().iterator().next();
        Map<DeviceType, StaticKeys> reversed = new LinkedHashMap<>();
        reversed.put(localDeviceType, only.getValue());
        KeyDatabase placeholder = new KeyDatabase(only.getKey(), reversed, new byte[CRC_SIZE]);
        byte[] newCrc = computeCrc(placeholder.payloadBytes());
        return new KeyDatabase(only.getKey(), reversed, newCrc);
    }

    public DeviceType localDeviceType() {
        return localDeviceType;
    }

    public Map<DeviceType, StaticKeys> remoteDevices() {
        return remoteDevices;
    }

    public byte[] crc() {
        return crc.clone();
    }

    private byte[] payloadBytes() {
        byte[] out = new byte[2 + ENTRY_SIZE * remoteDevices.size()];
        out[0] = (byte) localDeviceType.value();
        out[1] = (byte) remoteDevices.size();
        int offset = 2;
        for (Map.Entry<DeviceType, StaticKeys> entry : remoteDevices.entrySet()) {
            out[offset] = (byte) entry.getKey().value();
            byte[] keys = entry.getValue().toBytes();
            System.arraycopy(keys, 0, out, offset + 1, keys.length);
            offset += ENTRY_SIZE;
        }
        return out;
    }

    private static byte[] computeCrc(byte[] payload) {
        CRC32 crc32 = new CRC32();
        crc32.update(payload);
        return ByteBuffer.allocate(CRC_SIZE)
                .order(ByteOrder.BIG_ENDIAN)
                .putInt((int) crc32.getValue())
                .array();
    }

    private static String hex(byte[] data) {
        StringBuilder sb = new StringBuilder(data.length * 2);
        for (byte b : data) {
            sb.append(String.format("%02x", b & 0xFF));
        }
        return sb.toString();
    }
}
