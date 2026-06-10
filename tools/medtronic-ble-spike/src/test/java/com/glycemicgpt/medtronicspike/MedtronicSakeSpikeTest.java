package com.glycemicgpt.medtronicspike;

import static org.junit.jupiter.api.Assertions.assertArrayEquals;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.util.Arrays;
import org.junit.jupiter.api.Test;
import org.openminimed.sake.DeviceType;
import org.openminimed.sake.KeyDatabase;
import org.openminimed.sake.MacFailureException;
import org.openminimed.sake.RngSource;
import org.openminimed.sake.SakeClient;
import org.openminimed.sake.SakeServer;
import org.openminimed.sake.SeqCrypt;
import org.openminimed.sake.Session;

/**
 * Spike acceptance gate for the Medtronic read-only BLE de-risk harness.
 *
 * <p>These assertions back the spike's findings: each claim ("the handshake completes against
 * the captured 780G trace", "the session cipher round-trips") is enforced here so the spike can be
 * re-verified in seconds. Exact byte-for-byte parity for all six handshake messages and parity
 * against the reference PythonSake ciphertexts are additionally asserted by the vendored upstream
 * suite ({@code org.openminimed.sake.SakeServerTest} / {@code SeqCryptTest}), which runs in the
 * same {@code ./gradlew test} invocation.
 */
class MedtronicSakeSpikeTest {

    /**
     * Captured-trace handshake: the phone-side SAKE server (MOBILE_APPLICATION = BLE peripheral)
     * drives the captured 780G pump trace to completion, re-emitting msg0 and msg2 exactly as
     * captured.
     */
    @Test
    void phoneServerCompletesHandshakeAgainstCaptured780GTrace() throws MacFailureException {
        byte[][] msgs = SakeTestVectors.MESSAGES;
        RngSource capturedRng =
                new QueuedRngSource(
                        Arrays.copyOfRange(msgs[0], 2, 20),
                        Arrays.copyOfRange(msgs[2], 8, 16),
                        Arrays.copyOfRange(msgs[2], 16, 20));
        SakeServer server =
                new SakeServer(
                        KeyDatabase.fromBytes(SakeTestVectors.decodeHex(SakeTestVectors.PUMP_KEYDB_HEX)),
                        DeviceType.MOBILE_APPLICATION,
                        capturedRng);

        byte[] msg0 = server.handshake(new byte[Session.MESSAGE_SIZE]);
        assertArrayEquals(msgs[0], msg0, "msg0 must match the captured trace");
        assertEquals(1, server.getStage());

        byte[] msg2 = server.handshake(msgs[1]);
        assertArrayEquals(msgs[2], msg2, "msg2 must match the captured trace");
        assertEquals(3, server.getStage());

        // The emitted msg4's encrypted-permit ciphertext (first 16 bytes) must match the capture;
        // only the pad-dependent 4-byte trailer differs (reproducing it needs package-private access,
        // which the in-package org.openminimed.sake.SakeServerTest asserts).
        byte[] msg4 = server.handshake(msgs[3]);
        assertEquals(5, server.getStage());
        assertArrayEquals(
                Arrays.copyOfRange(msgs[4], 0, 16),
                Arrays.copyOfRange(msg4, 0, 16),
                "msg4 encrypted permit (first 16 bytes) must match the captured trace");

        byte[] done = server.handshake(msgs[5]);
        assertNull(done, "stage 5 returns null to signal completion");
        assertEquals(6, server.getStage(), "server must reach the terminal stage");
    }

    /**
     * Two-sided handshake: a fresh phone server and simulated pump client complete the full
     * six-stage handshake against each other and agree on the derived session keys and nonce.
     */
    @Test
    void phoneServerAndPumpClientAgreeOnSessionKeys() throws MacFailureException {
        SakeServer server =
                new SakeServer(
                        KeyDatabase.fromBytes(SakeTestVectors.decodeHex(SakeTestVectors.CUSTOM_SERVER_KEYDB_HEX)),
                        DeviceType.MOBILE_APPLICATION);
        SakeClient client =
                new SakeClient(
                        KeyDatabase.fromBytes(SakeTestVectors.decodeHex(SakeTestVectors.CUSTOM_CLIENT_KEYDB_HEX)),
                        DeviceType.INSULIN_PUMP);

        byte[] msg0 = server.handshake(new byte[Session.MESSAGE_SIZE]);
        byte[] msg1 = client.handshake(msg0);
        byte[] msg2 = server.handshake(msg1);
        byte[] msg3 = client.handshake(msg2);
        byte[] msg4 = server.handshake(msg3);
        byte[] msg5 = client.handshake(msg4);
        assertNull(server.handshake(msg5));

        assertEquals(6, server.getStage());
        assertEquals(6, client.getStage());
        assertArrayEquals(
                server.session().clientCrypt().key(), client.session().clientCrypt().key());
        assertArrayEquals(
                server.session().serverCrypt().key(), client.session().serverCrypt().key());
        assertArrayEquals(
                server.session().clientCrypt().nonce(), client.session().clientCrypt().nonce());
    }

    /** Session cipher: SeqCrypt round-trips, advances its sequence, and rejects tampering. */
    @Test
    void seqCryptRoundTripsAndRejectsTampering() throws MacFailureException {
        byte[] key = SakeTestVectors.decodeHex("00112233445566778899aabbccddeeff");
        byte[] nonce = SakeTestVectors.decodeHex("a1b2c3d4e5f60718");
        byte[] plaintext = SakeTestVectors.decodeHex("48656c6c6f2c2053414b65212121212121");

        SeqCrypt tx = new SeqCrypt(key, nonce, 0L);
        SeqCrypt rx = new SeqCrypt(key, nonce, 0L);

        byte[] cipher = tx.encrypt(plaintext);
        assertEquals(2L, tx.getTxSeq());
        assertFalse(Arrays.equals(plaintext, cipher));

        assertArrayEquals(plaintext, rx.decrypt(cipher));
        assertEquals(2L, rx.getRxSeq());

        byte[] tampered = cipher.clone();
        tampered[tampered.length - 1] ^= (byte) 0x01;
        assertThrows(MacFailureException.class, () -> new SeqCrypt(key, nonce, 0L).decrypt(tampered));
    }

    /**
     * The shared test vectors are well-formed: six 20-byte handshake messages and a pump key
     * database that parses to a valid {@link KeyDatabase} (so a transcription typo can't silently
     * weaken the other tests).
     */
    @Test
    void sharedTestVectorsAreWellFormed() {
        assertEquals(6, SakeTestVectors.MESSAGES.length);
        for (byte[] m : SakeTestVectors.MESSAGES) {
            assertEquals(Session.MESSAGE_SIZE, m.length, "every handshake message is 20 bytes");
        }
        // The firmware-extracted DB is the mobile-app-side database (local = MOBILE_APPLICATION)
        // that lists the insulin pump as a remote peer -- this is what the phone-side SAKE server
        // loads.
        KeyDatabase pumpDb =
                KeyDatabase.fromBytes(SakeTestVectors.decodeHex(SakeTestVectors.PUMP_KEYDB_HEX));
        assertEquals(DeviceType.MOBILE_APPLICATION, pumpDb.localDeviceType());
        assertTrue(
                pumpDb.remoteDevices().containsKey(DeviceType.INSULIN_PUMP),
                "phone-side key DB must define the insulin pump as a peer");
    }
}
