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

import static org.junit.jupiter.api.Assertions.assertArrayEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;

import org.junit.jupiter.api.Test;
import org.openminimed.sake.Hex;

/** Known-answer tests from NIST SP 800-38A Appendix F.5 (AES-128 CTR). */
class AesCtrTest {

    private static final byte[] KEY = Hex.decode("2b7e151628aed2a6abf7158809cf4f3c");
    private static final byte[] INITIAL_COUNTER = Hex.decode("f0f1f2f3f4f5f6f7f8f9fafbfcfdfeff");

    @Test
    void encryptsNistMultiBlockStream() {
        byte[] plain =
                Hex.decode(
                        "6bc1bee22e409f96e93d7e117393172a"
                                + "ae2d8a571e03ac9c9eb76fac45af8e51"
                                + "30c81c46a35ce411e5fbc1191a0a52ef"
                                + "f69f2445df4f9b17ad2b417be66c3710");
        byte[] expected =
                Hex.decode(
                        "874d6191b620e3261bef6864990db6ce"
                                + "9806f66b7970fdff8617187bb9fffdff"
                                + "5ae4df3edbd5d35e5b4f09020db03eab"
                                + "1e031dda2fbe03d1792170a0f3009cee");
        assertArrayEquals(expected, AesCtr.crypt(KEY, INITIAL_COUNTER, plain));
    }

    @Test
    void encryptDecryptIsSymmetric() {
        byte[] plain = Hex.decode("6bc1bee22e409f96e93d7e117393172a");
        byte[] cipher = AesCtr.crypt(KEY, INITIAL_COUNTER, plain);
        byte[] recovered = AesCtr.crypt(KEY, INITIAL_COUNTER, cipher);
        assertArrayEquals(plain, recovered);
    }

    @Test
    void encryptsPartialBlock() {
        byte[] plain = Hex.decode("6bc1bee22e409f96e93d7e1173");
        byte[] cipher = AesCtr.crypt(KEY, INITIAL_COUNTER, plain);
        byte[] recovered = AesCtr.crypt(KEY, INITIAL_COUNTER, cipher);
        assertArrayEquals(plain, recovered);
    }

    @Test
    void rejectsWrongIvLength() {
        assertThrows(
                IllegalArgumentException.class, () -> AesCtr.crypt(KEY, new byte[15], new byte[0]));
    }

    @Test
    void rejectsWrongKeyLength() {
        assertThrows(
                IllegalArgumentException.class,
                () -> AesCtr.crypt(new byte[24], INITIAL_COUNTER, new byte[0]));
    }
}
