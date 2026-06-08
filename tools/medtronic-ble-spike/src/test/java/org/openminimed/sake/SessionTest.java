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

import static org.junit.jupiter.api.Assertions.assertArrayEquals;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import org.junit.jupiter.api.Test;

/**
 * Parity tests for {@link Session} driven by the captured pump pairing pcap embedded in {@code
 * pysake/constants.py} as {@code __PUMP_TEST_MSGS_1}.
 *
 * <p>The expected per-checkpoint state was captured from a harness driving {@link Session} in the
 * reference Python implementation against the same key database and message sequence. Any
 * divergence in any derived field causes an assertion to fail and points at the responsible step.
 */
class SessionTest {

    private static final String KEY_DB_HEX =
            "f75995e70401011bc1bf7cbf36fa1e2367d795ff09211903da6afbe986b650f1"
                    + "4179c0e6852e0ce393781078ffc6f51919e2eaefbde69b8eca21e41ab59b881a"
                    + "0bea0286ea91dc7582a86a714e1737f558f0d66dc1895c";

    private static final byte[][] PUMP_TEST_MSGS =
            new byte[][] {
                Hex.decode("0401e2f09017a98f9f01cc56492fbacd4576e92b"),
                Hex.decode("42060e9f344e9312016ee8854d357f659b6b00ba"),
                Hex.decode("fdeeb13d04c3f18d272630ebeabe7c3a4d4d27b9"),
                Hex.decode("c02cec4ffb99affcb553a10fa6c55bb13d9fbacf"),
                Hex.decode("157d8e90214418a0e3d5f0517eebf4a82e00c02e"),
                Hex.decode("9b36f393b296fa84a757809859fc84a5c300d59b"),
            };

    private static KeyDatabase keyDb() {
        return KeyDatabase.fromBytes(Hex.decode(KEY_DB_HEX));
    }

    @Test
    void rejectsConstructionWithNeitherKeyDb() {
        assertThrows(IllegalArgumentException.class, () -> new Session(null, null));
    }

    @Test
    void rejectsConstructionWithBothKeyDbs() {
        assertThrows(IllegalArgumentException.class, () -> new Session(keyDb(), keyDb()));
    }

    @Test
    void rejectsWrongMessageLength() {
        Session sess = new Session(null, keyDb());
        assertThrows(IllegalArgumentException.class, () -> sess.handshake0S(new byte[19]));
    }

    @Test
    void handshake0SCapturesServerDeviceType() {
        Session sess = new Session(null, keyDb());
        sess.handshake0S(PUMP_TEST_MSGS[0]);
        assertEquals(DeviceType.MOBILE_APPLICATION, sess.serverDeviceType());
    }

    @Test
    void handshake1CDerivesKeysFromKeyDb() {
        Session sess = new Session(null, keyDb());
        sess.handshake0S(PUMP_TEST_MSGS[0]);
        sess.handshake1C(PUMP_TEST_MSGS[1]);

        assertEquals(DeviceType.INSULIN_PUMP, sess.clientDeviceType());
        assertArrayEquals(Hex.decode("42060e9f344e9312"), sess.clientKeyMaterial());
        assertArrayEquals(Hex.decode("6ee8854d"), sess.clientNonce());
        assertArrayEquals(Hex.decode("1bc1bf7cbf36fa1e2367d795ff092119"), sess.derivationKey());
        assertArrayEquals(Hex.decode("03da6afbe986b650f14179c0e6852e0c"), sess.handshakeAuthKey());
        assertNotNull(sess.serverStaticKeys());
    }

    @Test
    void handshake2SVerifiesAndCapturesServerKeyMaterial() throws Exception {
        Session sess = new Session(null, keyDb());
        sess.handshake0S(PUMP_TEST_MSGS[0]);
        sess.handshake1C(PUMP_TEST_MSGS[1]);
        sess.handshake2S(PUMP_TEST_MSGS[2]);

        assertArrayEquals(Hex.decode("272630ebeabe7c3a"), sess.serverKeyMaterial());
        assertArrayEquals(Hex.decode("4d4d27b9"), sess.serverNonce());
    }

    @Test
    void handshake3CCreatesSeqCryptsWithDerivedKey() throws Exception {
        Session sess = new Session(null, keyDb());
        sess.handshake0S(PUMP_TEST_MSGS[0]);
        sess.handshake1C(PUMP_TEST_MSGS[1]);
        sess.handshake2S(PUMP_TEST_MSGS[2]);
        sess.handshake3C(PUMP_TEST_MSGS[3]);

        byte[] expectedKey = Hex.decode("99ab5c7c113f85eefeb921da4094a886");
        byte[] expectedNonce = Hex.decode("6ee8854d4d4d27b9");

        assertArrayEquals(expectedKey, sess.clientCrypt().key());
        assertArrayEquals(expectedNonce, sess.clientCrypt().nonce());
        assertEquals(0L, sess.clientCrypt().getTxSeq());
        assertEquals(0L, sess.clientCrypt().getRxSeq());

        assertArrayEquals(expectedKey, sess.serverCrypt().key());
        assertEquals(1L, sess.serverCrypt().getTxSeq());
        assertEquals(1L, sess.serverCrypt().getRxSeq());
    }

    @Test
    void handshake4SDecryptsAndReturnsFalseWithoutClientKeyDb() throws Exception {
        Session sess = new Session(null, keyDb());
        sess.handshake0S(PUMP_TEST_MSGS[0]);
        sess.handshake1C(PUMP_TEST_MSGS[1]);
        sess.handshake2S(PUMP_TEST_MSGS[2]);
        sess.handshake3C(PUMP_TEST_MSGS[3]);
        boolean ok = sess.handshake4S(PUMP_TEST_MSGS[4]);
        assertFalse(ok, "server-only session has no verifier keys for handshake_4_s");
        assertEquals(3L, sess.serverCrypt().getRxSeq());
    }

    @Test
    void handshake5CVerifiesClientPermit() throws Exception {
        Session sess = new Session(null, keyDb());
        sess.handshake0S(PUMP_TEST_MSGS[0]);
        sess.handshake1C(PUMP_TEST_MSGS[1]);
        sess.handshake2S(PUMP_TEST_MSGS[2]);
        sess.handshake3C(PUMP_TEST_MSGS[3]);
        sess.handshake4S(PUMP_TEST_MSGS[4]);
        boolean ok = sess.handshake5C(PUMP_TEST_MSGS[5]);
        assertTrue(ok, "client permit must verify against server static keys");
        assertEquals(2L, sess.clientCrypt().getRxSeq());
    }

    @Test
    void fullHandshakeMatchesCapturedFinalState() throws Exception {
        Session sess = new Session(null, keyDb());
        sess.handshake0S(PUMP_TEST_MSGS[0]);
        sess.handshake1C(PUMP_TEST_MSGS[1]);
        sess.handshake2S(PUMP_TEST_MSGS[2]);
        sess.handshake3C(PUMP_TEST_MSGS[3]);
        assertFalse(sess.handshake4S(PUMP_TEST_MSGS[4]));
        assertTrue(sess.handshake5C(PUMP_TEST_MSGS[5]));

        assertEquals(2L, sess.clientCrypt().getRxSeq());
        assertEquals(3L, sess.serverCrypt().getRxSeq());
    }

    @Test
    void handshake2SThrowsOnTamperedMac() throws Exception {
        Session sess = new Session(null, keyDb());
        sess.handshake0S(PUMP_TEST_MSGS[0]);
        sess.handshake1C(PUMP_TEST_MSGS[1]);
        byte[] tampered = PUMP_TEST_MSGS[2].clone();
        tampered[0] ^= (byte) 0x01;
        assertThrows(MacFailureException.class, () -> sess.handshake2S(tampered));
    }
}
