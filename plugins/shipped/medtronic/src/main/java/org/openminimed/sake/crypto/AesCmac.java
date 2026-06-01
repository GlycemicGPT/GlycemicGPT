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

package org.openminimed.sake.crypto;

import java.util.Arrays;
import java.util.Objects;
import org.bouncycastle.crypto.engines.AESEngine;
import org.bouncycastle.crypto.macs.CMac;
import org.bouncycastle.crypto.params.KeyParameter;

/**
 * Stateful AES-CMAC over a 16-byte AES-128 key with a configurable truncation length.
 *
 * <p>The handshake uses both {@code macLen=8} (handshake CMAC chain) and {@code macLen=4} (permit
 * auth, SeqCrypt trailer prefix). BouncyCastle always produces a 16-byte tag; we truncate to {@code
 * macLen} bytes to match the PyCryptodome {@code mac_len} parameter.
 *
 * <p>State accumulates across {@link #update(byte[])} calls. Calling {@link #digest()} or {@link
 * #verify(byte[])} computes the tag and resets the underlying {@code CMac}, leaving the instance
 * ready to receive {@code update} calls for a fresh message.
 *
 * <p>Instances are not thread-safe.
 */
public final class AesCmac {

    /** AES block size and full MAC length in bytes. */
    public static final int BLOCK_SIZE = 16;

    private final CMac mac;
    private final int macLen;

    public AesCmac(byte[] key, int macLen) {
        Objects.requireNonNull(key, "key");
        if (key.length != BLOCK_SIZE) {
            throw new IllegalArgumentException("AES-128 key must be " + BLOCK_SIZE + " bytes");
        }
        if (macLen < 1 || macLen > BLOCK_SIZE) {
            throw new IllegalArgumentException("macLen must be 1.." + BLOCK_SIZE);
        }
        this.mac = new CMac(AESEngine.newInstance());
        this.mac.init(new KeyParameter(key));
        this.macLen = macLen;
    }

    public AesCmac update(byte[] data) {
        Objects.requireNonNull(data, "data");
        mac.update(data, 0, data.length);
        return this;
    }

    /**
     * Compute the truncated MAC over all data accumulated since construction (or the previous
     * {@code digest}/{@code verify} call). The underlying state is reset; further {@link
     * #update(byte[])} calls begin a new message.
     */
    public byte[] digest() {
        byte[] full = new byte[mac.getMacSize()];
        mac.doFinal(full, 0);
        if (macLen == full.length) {
            return full;
        }
        return Arrays.copyOf(full, macLen);
    }

    /**
     * Constant-time comparison against an expected tag. Internally calls {@link #digest()} and
     * therefore resets the underlying MAC state.
     *
     * @return true if the computed digest matches {@code expected}, byte-for-byte.
     */
    public boolean verify(byte[] expected) {
        Objects.requireNonNull(expected, "expected");
        byte[] actual = digest();
        if (actual.length != expected.length) {
            return false;
        }
        int diff = 0;
        for (int i = 0; i < actual.length; i++) {
            diff |= actual[i] ^ expected[i];
        }
        return diff == 0;
    }
}
