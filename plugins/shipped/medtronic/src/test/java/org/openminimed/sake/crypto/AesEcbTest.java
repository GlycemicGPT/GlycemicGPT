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

import static org.junit.Assert.assertArrayEquals;
import static org.junit.Assert.assertThrows;

import org.junit.Test;
import org.openminimed.sake.Hex;

/** Known-answer tests from NIST SP 800-38A Appendix F.1 (AES-128 ECB). */
public class AesEcbTest {

    private static final byte[] KEY = Hex.decode("2b7e151628aed2a6abf7158809cf4f3c");

    @Test
    public void encryptsFirstNistBlock() {
        byte[] plain = Hex.decode("6bc1bee22e409f96e93d7e117393172a");
        byte[] expected = Hex.decode("3ad77bb40d7a3660a89ecaf32466ef97");
        assertArrayEquals(expected, AesEcb.encryptBlock(KEY, plain));
    }

    @Test
    public void encryptsSecondNistBlock() {
        byte[] plain = Hex.decode("ae2d8a571e03ac9c9eb76fac45af8e51");
        byte[] expected = Hex.decode("f5d3d58503b9699de785895a96fdbaaf");
        assertArrayEquals(expected, AesEcb.encryptBlock(KEY, plain));
    }

    @Test
    public void decryptsFirstNistBlock() {
        byte[] cipher = Hex.decode("3ad77bb40d7a3660a89ecaf32466ef97");
        byte[] expected = Hex.decode("6bc1bee22e409f96e93d7e117393172a");
        assertArrayEquals(expected, AesEcb.decryptBlock(KEY, cipher));
    }

    @Test
    public void rejectsWrongKeyLength() {
        byte[] plain = new byte[16];
        assertThrows(
                IllegalArgumentException.class, () -> AesEcb.encryptBlock(new byte[15], plain));
    }

    @Test
    public void rejectsWrongBlockLength() {
        assertThrows(IllegalArgumentException.class, () -> AesEcb.encryptBlock(KEY, new byte[15]));
    }
}
