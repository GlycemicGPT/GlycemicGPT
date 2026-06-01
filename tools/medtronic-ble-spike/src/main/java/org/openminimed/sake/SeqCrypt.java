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
import org.openminimed.sake.crypto.AesCmac;
import org.openminimed.sake.crypto.AesCtr;

/**
 * Sequence-numbered AES-CTR stream cipher with a CMAC trailer.
 *
 * <p>Each direction of the SAKE session is one {@code SeqCrypt} instance with its own sequence
 * counter. The encrypted form of a message is {@code ciphertext || trailer} where {@code trailer}
 * is three bytes:
 *
 * <pre>
 *   [ (seq &gt;&gt; 1) &amp; 0xFF ][ CMAC4(nonce.padTo16 || ciphertext)[0..1] ]
 * </pre>
 *
 * <p>The receiver reconstructs the full sequence from its local {@code rxSeq} and the 1-byte field
 * in the trailer, tolerating an 8-bit wrap-around. Deltas larger than {@link #MAX_RX_DELTA} are
 * rejected to bound the damage from a forged but MAC-valid packet.
 *
 * <p>The two-byte trailer MAC is dictated by the SAKE wire protocol: it is a sixteen-bit
 * authentication tag, not a full-strength MAC, and reflects the protocol's defence-in-depth
 * trade-off between packet size and forgery resistance.
 *
 * <p>The IV layout stores the sequence as five big-endian bytes followed by the eight-byte nonce
 * and three zero counter bytes. The five-byte sequence field bounds {@code txSeq} to less than
 * {@link #MAX_SEQ}; encryption past that point would silently truncate the sequence and risk IV
 * reuse, so {@link #encrypt(byte[])} rejects it.
 *
 * <p>Instances are not thread-safe. External synchronisation is required if a single instance is
 * shared across threads.
 */
public final class SeqCrypt {

    private static final int TRAILER_SIZE = 3;
    private static final int SEQ_PREFIX_SIZE = 5;
    private static final int NONCE_SIZE = 8;
    private static final int MAC_SIZE = 4;
    private static final int IV_SIZE = 16;

    /** Exclusive upper bound on {@code txSeq}: 2^40, matching the 5-byte sequence prefix. */
    public static final long MAX_SEQ = 1L << 40;

    /**
     * Maximum accepted delta (in trailer-byte units) between an incoming packet's sequence and the
     * receiver's tracked {@code rxSeq}. A delta of {@value} corresponds to skipping 256 packets
     * forward; larger jumps are treated as forgery attempts.
     */
    public static final int MAX_RX_DELTA = 128;

    private final byte[] key;
    private final byte[] nonce;
    private long txSeq;
    private long rxSeq;

    public SeqCrypt(byte[] key, byte[] nonce, long initialSeq) {
        Objects.requireNonNull(key, "key");
        Objects.requireNonNull(nonce, "nonce");
        if (key.length != IV_SIZE) {
            throw new IllegalArgumentException("key must be " + IV_SIZE + " bytes");
        }
        if (nonce.length != NONCE_SIZE) {
            throw new IllegalArgumentException("nonce must be " + NONCE_SIZE + " bytes");
        }
        this.key = key.clone();
        this.nonce = nonce.clone();
        this.txSeq = initialSeq;
        this.rxSeq = initialSeq;
    }

    public byte[] encrypt(byte[] plaintext) {
        Objects.requireNonNull(plaintext, "plaintext");
        long seq = txSeq;
        if (seq < 0 || seq >= MAX_SEQ) {
            throw new IllegalStateException("txSeq " + seq + " exceeds the 2^40 IV sequence bound");
        }
        byte[] iv = buildIv(seq);
        byte[] ciphertext = AesCtr.crypt(key, iv, plaintext);
        byte[] tagPrefix = computeTagPrefix(seq, ciphertext);

        byte[] out = new byte[ciphertext.length + TRAILER_SIZE];
        System.arraycopy(ciphertext, 0, out, 0, ciphertext.length);
        out[ciphertext.length] = (byte) ((seq >>> 1) & 0xFF);
        out[ciphertext.length + 1] = tagPrefix[0];
        out[ciphertext.length + 2] = tagPrefix[1];

        txSeq = seq + 2;
        return out;
    }

    /**
     * Decrypt and authenticate a message.
     *
     * @throws IllegalArgumentException if the buffer is shorter than the trailer.
     * @throws MacFailureException if the trailer MAC does not match the computed value.
     */
    public byte[] decrypt(byte[] message) throws MacFailureException {
        Objects.requireNonNull(message, "message");
        if (message.length < TRAILER_SIZE) {
            throw new IllegalArgumentException("Message shorter than trailer");
        }

        int seqByte = message[message.length - TRAILER_SIZE] & 0xFF;
        int delta = (seqByte - (int) ((rxSeq >>> 1) & 0xFF)) & 0xFF;
        if (delta > MAX_RX_DELTA) {
            throw new MacFailureException(
                    "Sequence delta " + delta + " exceeds reorder window of " + MAX_RX_DELTA);
        }
        long seq = rxSeq + 2L * delta;

        int ciphertextLen = message.length - TRAILER_SIZE;
        byte[] ciphertext = Arrays.copyOfRange(message, 0, ciphertextLen);
        byte[] tagPrefix = computeTagPrefix(seq, ciphertext);

        if ((tagPrefix[0] != message[ciphertextLen + 1])
                || (tagPrefix[1] != message[ciphertextLen + 2])) {
            throw new MacFailureException("MAC verification failed at seq=" + seq);
        }

        byte[] iv = buildIv(seq);
        byte[] plaintext = AesCtr.crypt(key, iv, ciphertext);
        rxSeq = seq + 2;
        return plaintext;
    }

    public byte[] key() {
        return key.clone();
    }

    public byte[] nonce() {
        return nonce.clone();
    }

    public long getTxSeq() {
        return txSeq;
    }

    public long getRxSeq() {
        return rxSeq;
    }

    public void setTxSeq(long value) {
        this.txSeq = value;
    }

    public void setRxSeq(long value) {
        this.rxSeq = value;
    }

    private byte[] buildIv(long seq) {
        byte[] iv = new byte[IV_SIZE];
        iv[0] = (byte) ((seq >>> 32) & 0xFF);
        iv[1] = (byte) ((seq >>> 24) & 0xFF);
        iv[2] = (byte) ((seq >>> 16) & 0xFF);
        iv[3] = (byte) ((seq >>> 8) & 0xFF);
        iv[4] = (byte) (seq & 0xFF);
        System.arraycopy(nonce, 0, iv, SEQ_PREFIX_SIZE, NONCE_SIZE);
        // Trailing 3 bytes remain zero (counter region for AES-CTR).
        return iv;
    }

    private byte[] computeTagPrefix(long seq, byte[] ciphertext) {
        byte[] cmacInput = new byte[IV_SIZE + ciphertext.length];
        cmacInput[0] = (byte) ((seq >>> 32) & 0xFF);
        cmacInput[1] = (byte) ((seq >>> 24) & 0xFF);
        cmacInput[2] = (byte) ((seq >>> 16) & 0xFF);
        cmacInput[3] = (byte) ((seq >>> 8) & 0xFF);
        cmacInput[4] = (byte) (seq & 0xFF);
        System.arraycopy(nonce, 0, cmacInput, SEQ_PREFIX_SIZE, NONCE_SIZE);
        // Bytes 13..15 are the zero-padding to 16 (`ljust` in the Python).
        System.arraycopy(ciphertext, 0, cmacInput, IV_SIZE, ciphertext.length);

        AesCmac cmac = new AesCmac(key, MAC_SIZE);
        cmac.update(cmacInput);
        return cmac.digest();
    }
}
