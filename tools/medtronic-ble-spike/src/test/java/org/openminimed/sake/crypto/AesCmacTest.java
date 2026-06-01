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
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

import org.junit.jupiter.api.Test;
import org.openminimed.sake.Hex;

/** Known-answer tests from RFC 4493 (AES-CMAC) Appendix. */
class AesCmacTest {

    private static final byte[] KEY = Hex.decode("2b7e151628aed2a6abf7158809cf4f3c");

    @Test
    void rfc4493ExampleEmpty() {
        byte[] expected = Hex.decode("bb1d6929e95937287fa37d129b756746");
        AesCmac cmac = new AesCmac(KEY, 16);
        cmac.update(new byte[0]);
        assertArrayEquals(expected, cmac.digest());
    }

    @Test
    void rfc4493ExampleOneBlock() {
        byte[] msg = Hex.decode("6bc1bee22e409f96e93d7e117393172a");
        byte[] expected = Hex.decode("070a16b46b4d4144f79bdd9dd04a287c");
        AesCmac cmac = new AesCmac(KEY, 16);
        cmac.update(msg);
        assertArrayEquals(expected, cmac.digest());
    }

    @Test
    void rfc4493ExampleFortyBytes() {
        byte[] msg =
                Hex.decode(
                        "6bc1bee22e409f96e93d7e117393172a"
                                + "ae2d8a571e03ac9c9eb76fac45af8e51"
                                + "30c81c46a35ce411");
        byte[] expected = Hex.decode("dfa66747de9ae63030ca32611497c827");
        AesCmac cmac = new AesCmac(KEY, 16);
        cmac.update(msg);
        assertArrayEquals(expected, cmac.digest());
    }

    @Test
    void rfc4493ExampleSixtyFourBytes() {
        byte[] msg =
                Hex.decode(
                        "6bc1bee22e409f96e93d7e117393172a"
                                + "ae2d8a571e03ac9c9eb76fac45af8e51"
                                + "30c81c46a35ce411e5fbc1191a0a52ef"
                                + "f69f2445df4f9b17ad2b417be66c3710");
        byte[] expected = Hex.decode("51f0bebf7e3b9d92fc49741779363cfe");
        AesCmac cmac = new AesCmac(KEY, 16);
        cmac.update(msg);
        assertArrayEquals(expected, cmac.digest());
    }

    @Test
    void truncationToFourBytes() {
        byte[] msg = Hex.decode("6bc1bee22e409f96e93d7e117393172a");
        byte[] full = Hex.decode("070a16b46b4d4144f79bdd9dd04a287c");
        AesCmac cmac = new AesCmac(KEY, 4);
        cmac.update(msg);
        byte[] truncated = cmac.digest();
        assertEquals(4, truncated.length);
        for (int i = 0; i < 4; i++) {
            assertEquals(full[i], truncated[i]);
        }
    }

    @Test
    void truncationToEightBytes() {
        byte[] msg = Hex.decode("6bc1bee22e409f96e93d7e117393172a");
        byte[] full = Hex.decode("070a16b46b4d4144f79bdd9dd04a287c");
        AesCmac cmac = new AesCmac(KEY, 8);
        cmac.update(msg);
        byte[] truncated = cmac.digest();
        assertEquals(8, truncated.length);
        for (int i = 0; i < 8; i++) {
            assertEquals(full[i], truncated[i]);
        }
    }

    @Test
    void verifyAcceptsMatchingTag() {
        byte[] msg = Hex.decode("6bc1bee22e409f96e93d7e117393172a");
        byte[] tag = Hex.decode("070a16b46b4d4144");
        AesCmac cmac = new AesCmac(KEY, 8);
        cmac.update(msg);
        assertTrue(cmac.verify(tag));
    }

    @Test
    void verifyRejectsTamperedTag() {
        byte[] msg = Hex.decode("6bc1bee22e409f96e93d7e117393172a");
        byte[] tag = Hex.decode("070a16b46b4d4145");
        AesCmac cmac = new AesCmac(KEY, 8);
        cmac.update(msg);
        assertFalse(cmac.verify(tag));
    }
}
