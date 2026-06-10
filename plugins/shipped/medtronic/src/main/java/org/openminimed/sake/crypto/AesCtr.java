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

import java.security.GeneralSecurityException;
import java.util.Objects;
import javax.crypto.Cipher;
import javax.crypto.spec.IvParameterSpec;
import javax.crypto.spec.SecretKeySpec;

/**
 * AES-128 CTR stream encryption.
 *
 * <p>The 16-byte IV is passed unchanged to the JDK's {@code AES/CTR/NoPadding} cipher, which treats
 * it as a 128-bit initial counter and increments the whole thing by one per block.
 *
 * <p><b>The (key, IV) pair must be unique per encryption.</b> Reusing the same key with the same IV
 * for two different plaintexts completely breaks CTR-mode confidentiality and authenticity. Callers
 * are responsible for assembling the IV so that (a) it differs across every encryption performed
 * under a given key, and (b) the per-block counter increments never wrap into the bits that carry
 * the unique nonce or sequence number. See {@link org.openminimed.sake.SeqCrypt} for the SAKE
 * session's IV construction.
 *
 * <p>CTR is symmetric so the same method is used to encrypt and decrypt.
 */
public final class AesCtr {

    /** AES block size and IV length in bytes. */
    public static final int BLOCK_SIZE = 16;

    private AesCtr() {}

    public static byte[] crypt(byte[] key, byte[] iv, byte[] data) {
        Objects.requireNonNull(key, "key");
        Objects.requireNonNull(iv, "iv");
        Objects.requireNonNull(data, "data");
        if (key.length != BLOCK_SIZE) {
            throw new IllegalArgumentException("AES-128 key must be " + BLOCK_SIZE + " bytes");
        }
        if (iv.length != BLOCK_SIZE) {
            throw new IllegalArgumentException("IV must be " + BLOCK_SIZE + " bytes");
        }
        try {
            Cipher cipher = Cipher.getInstance("AES/CTR/NoPadding");
            cipher.init(
                    Cipher.ENCRYPT_MODE, new SecretKeySpec(key, "AES"), new IvParameterSpec(iv));
            return cipher.doFinal(data);
        } catch (GeneralSecurityException e) {
            throw new IllegalStateException("AES/CTR/NoPadding unavailable", e);
        }
    }
}
