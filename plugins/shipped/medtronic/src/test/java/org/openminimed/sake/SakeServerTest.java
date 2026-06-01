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

import static org.junit.Assert.assertArrayEquals;
import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertThrows;

import java.util.Arrays;
import org.junit.Test;

/**
 * End-to-end parity tests for {@link SakeServer} against the captured 780G pairing pcap embedded in
 * {@code pysake/constants.py} ({@code __PUMP_TEST_MSGS_1}).
 *
 * <p>The server is driven with a deterministic {@link QueuedRngSource} that replays the random
 * fields chosen during the original pcap (server msg0 filler, server key material, server nonce)
 * and with the same {@code 0xf7} pad byte for msg4. Under those inputs the server must emit exactly
 * the bytes recorded in the pcap.
 */
public class SakeServerTest {

    private static final String PUMP_KEYDB_HEX =
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

    /**
     * Pad byte for the msg4 plaintext that reproduces the captured pcap. Recovered from the
     * keystream as {@code captured[16] XOR keystream[16]} at tx_seq=1.
     */
    private static final byte CAPTURED_MSG4_PAD = (byte) 0xf7;

    private static SakeServer captureMatchingServer() {
        QueuedRngSource rng =
                new QueuedRngSource(
                        Arrays.copyOfRange(PUMP_TEST_MSGS[0], 2, 20),
                        Arrays.copyOfRange(PUMP_TEST_MSGS[2], 8, 16),
                        Arrays.copyOfRange(PUMP_TEST_MSGS[2], 16, 20));
        SakeServer server =
                new SakeServer(
                        KeyDatabase.fromBytes(Hex.decode(PUMP_KEYDB_HEX)),
                        DeviceType.MOBILE_APPLICATION,
                        rng);
        server.setMsg4Pad(CAPTURED_MSG4_PAD);
        return server;
    }

    @Test
    public void endToEndMatchesCapturedPumpTrace() throws Exception {
        SakeServer server = captureMatchingServer();

        byte[] out0 = server.handshake(new byte[20]);
        assertArrayEquals("msg0 must match captured pcap", PUMP_TEST_MSGS[0], out0);
        assertEquals(1, server.getStage());

        byte[] out2 = server.handshake(PUMP_TEST_MSGS[1]);
        assertArrayEquals("msg2 must match captured pcap", PUMP_TEST_MSGS[2], out2);
        assertEquals(3, server.getStage());

        byte[] out4 = server.handshake(PUMP_TEST_MSGS[3]);
        assertArrayEquals("msg4 must match captured pcap", PUMP_TEST_MSGS[4], out4);
        assertEquals(5, server.getStage());

        byte[] out5 = server.handshake(PUMP_TEST_MSGS[5]);
        assertNull("stage 5 returns null to signal completion", out5);
        assertEquals(6, server.getStage());

        // After completion the server_crypt.rx_seq has been reset to 2 so that
        // subsequent session traffic decodes against the right starting seq.
        assertEquals(2L, server.session().serverCrypt().getRxSeq());
    }

    @Test
    public void msg0IsEmittedAtStageZero() throws Exception {
        SakeServer server = captureMatchingServer();
        byte[] out0 = server.handshake(new byte[20]);
        assertNotNull(out0);
        assertEquals(DeviceType.MOBILE_APPLICATION.value(), out0[0] & 0xFF);
        assertEquals(0x01, out0[1]);
    }

    @Test
    public void stageZeroRejectsNonZeroInput() {
        SakeServer server = new SakeServer(KeyDatabase.fromBytes(Hex.decode(PUMP_KEYDB_HEX)));
        byte[] notZero = new byte[20];
        notZero[5] = 0x01;
        assertThrows(IllegalArgumentException.class, () -> server.handshake(notZero));
    }

    @Test
    public void handshakeRejectsWrongLength() {
        SakeServer server = new SakeServer(KeyDatabase.fromBytes(Hex.decode(PUMP_KEYDB_HEX)));
        assertThrows(IllegalArgumentException.class, () -> server.handshake(new byte[19]));
    }

    @Test
    public void handshakeRejectsAdditionalInputAfterCompletion() throws Exception {
        SakeServer server = captureMatchingServer();
        server.handshake(new byte[20]);
        server.handshake(PUMP_TEST_MSGS[1]);
        server.handshake(PUMP_TEST_MSGS[3]);
        server.handshake(PUMP_TEST_MSGS[5]);
        assertEquals(6, server.getStage());
        assertThrows(IllegalStateException.class, () -> server.handshake(new byte[20]));
    }
}
