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

import java.util.Arrays;
import java.util.Objects;

/**
 * Five 16-byte keys shared between two specific devices, plus an opaque 16-byte handshake payload.
 *
 * <p>The on-wire form is the concatenation, in declaration order, of:
 *
 * <ol>
 *   <li>{@code derivationKey}
 *   <li>{@code handshakeAuthKey}
 *   <li>{@code permitDecryptKey}
 *   <li>{@code permitAuthKey}
 *   <li>{@code handshakePayload}
 * </ol>
 */
public final class StaticKeys {

    /** Size in bytes of each of the five fields. */
    public static final int FIELD_SIZE = 16;

    /** Total size in bytes of the serialized form. */
    public static final int SERIALIZED_SIZE = 5 * FIELD_SIZE;

    private final byte[] derivationKey;
    private final byte[] handshakeAuthKey;
    private final byte[] permitDecryptKey;
    private final byte[] permitAuthKey;
    private final byte[] handshakePayload;

    public StaticKeys(
            byte[] derivationKey,
            byte[] handshakeAuthKey,
            byte[] permitDecryptKey,
            byte[] permitAuthKey,
            byte[] handshakePayload) {
        this.derivationKey = requireExactSize("derivationKey", derivationKey);
        this.handshakeAuthKey = requireExactSize("handshakeAuthKey", handshakeAuthKey);
        this.permitDecryptKey = requireExactSize("permitDecryptKey", permitDecryptKey);
        this.permitAuthKey = requireExactSize("permitAuthKey", permitAuthKey);
        this.handshakePayload = requireExactSize("handshakePayload", handshakePayload);
    }

    /**
     * Parse a {@link StaticKeys} from exactly {@value #SERIALIZED_SIZE} bytes.
     *
     * @throws IllegalArgumentException if the buffer is not exactly {@value #SERIALIZED_SIZE}
     *     bytes.
     */
    public static StaticKeys fromBytes(byte[] data) {
        Objects.requireNonNull(data, "data");
        if (data.length != SERIALIZED_SIZE) {
            throw new IllegalArgumentException(
                    "StaticKeys requires " + SERIALIZED_SIZE + " bytes, got " + data.length);
        }
        return new StaticKeys(
                Arrays.copyOfRange(data, 0 * FIELD_SIZE, 1 * FIELD_SIZE),
                Arrays.copyOfRange(data, 1 * FIELD_SIZE, 2 * FIELD_SIZE),
                Arrays.copyOfRange(data, 2 * FIELD_SIZE, 3 * FIELD_SIZE),
                Arrays.copyOfRange(data, 3 * FIELD_SIZE, 4 * FIELD_SIZE),
                Arrays.copyOfRange(data, 4 * FIELD_SIZE, 5 * FIELD_SIZE));
    }

    /**
     * @return a new {@value #SERIALIZED_SIZE}-byte buffer containing the serialized form.
     */
    public byte[] toBytes() {
        byte[] out = new byte[SERIALIZED_SIZE];
        System.arraycopy(derivationKey, 0, out, 0 * FIELD_SIZE, FIELD_SIZE);
        System.arraycopy(handshakeAuthKey, 0, out, 1 * FIELD_SIZE, FIELD_SIZE);
        System.arraycopy(permitDecryptKey, 0, out, 2 * FIELD_SIZE, FIELD_SIZE);
        System.arraycopy(permitAuthKey, 0, out, 3 * FIELD_SIZE, FIELD_SIZE);
        System.arraycopy(handshakePayload, 0, out, 4 * FIELD_SIZE, FIELD_SIZE);
        return out;
    }

    public byte[] derivationKey() {
        return derivationKey.clone();
    }

    public byte[] handshakeAuthKey() {
        return handshakeAuthKey.clone();
    }

    public byte[] permitDecryptKey() {
        return permitDecryptKey.clone();
    }

    public byte[] permitAuthKey() {
        return permitAuthKey.clone();
    }

    public byte[] handshakePayload() {
        return handshakePayload.clone();
    }

    private static byte[] requireExactSize(String name, byte[] data) {
        Objects.requireNonNull(data, name);
        if (data.length != FIELD_SIZE) {
            throw new IllegalArgumentException(
                    name + " must be " + FIELD_SIZE + " bytes, got " + data.length);
        }
        return data.clone();
    }
}
