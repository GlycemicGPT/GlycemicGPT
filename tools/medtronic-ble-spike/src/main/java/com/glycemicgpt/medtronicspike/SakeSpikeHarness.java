package com.glycemicgpt.medtronicspike;

import static com.glycemicgpt.medtronicspike.SakeTestVectors.decodeHex;
import static com.glycemicgpt.medtronicspike.SakeTestVectors.toHex;

import java.util.Arrays;
import org.openminimed.sake.DeviceType;
import org.openminimed.sake.KeyDatabase;
import org.openminimed.sake.MacFailureException;
import org.openminimed.sake.RngSource;
import org.openminimed.sake.SakeClient;
import org.openminimed.sake.SakeServer;
import org.openminimed.sake.SeqCrypt;
import org.openminimed.sake.Session;

/**
 * Medtronic read-only BLE de-risk spike -- runnable narration of the SAKE handshake.
 *
 * <p>This is the {@code ./gradlew run} entry point. It re-proves, in human-readable form and with
 * no physical pump, the two facts the spike exists to retire:
 *
 * <ol>
 *   <li>The vendored OpenMinimed JavaSake handshake completes against OpenMinimed's <b>captured
 *       780G pairing trace</b> with the phone playing the BLE-peripheral / SAKE-server role
 *       ({@link DeviceType#MOBILE_APPLICATION}) and the pump playing the BLE-central / SAKE-client
 *       role ({@link DeviceType#INSULIN_PUMP}) -- the inverted topology.
 *   <li>The derived {@link SeqCrypt} session cipher encrypt/decrypt round-trips and rejects
 *       tampering, so the future read layer has a trusted cipher.
 * </ol>
 *
 * <p><b>Authoritative byte-for-byte parity</b> (all six handshake messages, including the
 * SeqCrypt-encrypted msg4 whose pad byte needs package-private access to reproduce, plus parity
 * against the reference PythonSake ciphertexts) is asserted by the vendored JUnit suite -- run
 * {@code ./gradlew test}. This narration intentionally validates only what it can reach from
 * outside the {@code org.openminimed.sake} package (msg0 + msg2 bytes, full completion against the
 * real captured pump replies, and the live cipher round-trip), then defers to the test suite for
 * the rest. The exit code is non-zero if any check it does run fails.
 */
public final class SakeSpikeHarness {

    private SakeSpikeHarness() {}

    public static void main(String[] args) {
        Report report = new Report();
        System.out.println("=== Medtronic read-only BLE de-risk spike: SAKE handshake harness ===");
        System.out.println("    vendored OpenMinimed JavaSake (GPL-3.0, used with permission)\n");

        try {
            sectionCapturedTrace(report);
            sectionTwoSidedHandshake(report);
            sectionSeqCryptRoundTrip(report);
        } catch (Exception e) {
            report.fail("unexpected exception: " + e);
            e.printStackTrace();
        }

        System.out.println();
        System.out.println(report.summary());
        System.exit(report.allPassed() ? 0 : 1);
    }

    /**
     * Section 1: drive the phone-side SAKE server through the captured 780G pump trace and confirm
     * the messages the phone emits match the capture, and that the handshake completes against the
     * pump's real recorded replies.
     */
    private static void sectionCapturedTrace(Report report) throws MacFailureException {
        byte[][] msgs = SakeTestVectors.MESSAGES;
        System.out.println("[1] SAKE handshake vs captured 780G pump trace");
        System.out.println("    role: phone = MOBILE_APPLICATION (BLE peripheral / SAKE server)\n");

        // Replay the random fields the phone chose during the original capture so our server
        // re-emits the same bytes: msg0 filler (18 B), server key material (8 B), server nonce (4 B).
        RngSource capturedRng =
                new QueuedRngSource(
                        Arrays.copyOfRange(msgs[0], 2, 20),
                        Arrays.copyOfRange(msgs[2], 8, 16),
                        Arrays.copyOfRange(msgs[2], 16, 20));
        SakeServer server =
                new SakeServer(
                        KeyDatabase.fromBytes(decodeHex(SakeTestVectors.PUMP_KEYDB_HEX)),
                        DeviceType.MOBILE_APPLICATION,
                        capturedRng);

        byte[] msg0 = server.handshake(new byte[Session.MESSAGE_SIZE]);
        report.check("stage 0 -> msg0 matches captured pump trace", Arrays.equals(msg0, msgs[0]));
        printStage("msg0", msg0, server.getStage());

        byte[] msg2 = server.handshake(msgs[1]);
        report.check("stage 1 -> msg2 matches captured pump trace", Arrays.equals(msg2, msgs[2]));
        printStage("msg2", msg2, server.getStage());

        // Our msg4 pad byte differs from the captured 0xf7 (reproducing it needs package-private
        // access; the test suite asserts exact msg4 parity). But the encrypted-permit ciphertext
        // -- the first 16 bytes -- must match the capture; only the pad-dependent trailer differs.
        // The handshake still completes because msg5 decryption depends only on the derived session
        // cipher, not on msg4's pad.
        byte[] msg4 = server.handshake(msgs[3]);
        report.check(
                "stage 3 -> msg4 encrypted permit (first 16 bytes) matches captured trace",
                Arrays.equals(
                        Arrays.copyOfRange(msg4, 0, 16), Arrays.copyOfRange(msgs[4], 0, 16)));
        printStage("msg4 (trailer pad differs; exact parity asserted in ./gradlew test)", msg4, server.getStage());

        byte[] done = server.handshake(msgs[5]);
        report.check("stage 5 -> handshake completes against captured pump msg5", done == null);
        report.check("server reaches stage 6", server.getStage() == 6);

        byte[] sessionKey = server.session().serverCrypt().key();
        byte[] sessionNonce = server.session().serverCrypt().nonce();
        System.out.println("    session key derived:   " + toHex(sessionKey));
        System.out.println("    session nonce derived: " + toHex(sessionNonce) + "\n");
    }

    /**
     * Section 2: run a fresh server and client against each other end-to-end (no capture) to show
     * the full stage progression on both peers and that they agree on the derived session keys.
     */
    private static void sectionTwoSidedHandshake(Report report) throws MacFailureException {
        System.out.println("[2] Two-sided handshake (phone server <-> simulated pump client)");

        // A matched synthetic key-db pair (OpenMinimed test_key_db_gen.py): the two halves share a
        // derivation/auth/permit key set so both permit checks succeed -- the smallest two-sided
        // configuration. The firmware-extracted db cannot be self-paired (its permit payload is
        // built for a specific real peer), so a matched pair is required to exercise both sides.
        KeyDatabase serverDb = KeyDatabase.fromBytes(decodeHex(SakeTestVectors.CUSTOM_SERVER_KEYDB_HEX));
        KeyDatabase clientDb = KeyDatabase.fromBytes(decodeHex(SakeTestVectors.CUSTOM_CLIENT_KEYDB_HEX));

        SakeServer server = new SakeServer(serverDb, DeviceType.MOBILE_APPLICATION);
        SakeClient client = new SakeClient(clientDb, DeviceType.INSULIN_PUMP);

        byte[] msg0 = server.handshake(new byte[Session.MESSAGE_SIZE]);
        byte[] msg1 = client.handshake(msg0);
        byte[] msg2 = server.handshake(msg1);
        byte[] msg3 = client.handshake(msg2);
        byte[] msg4 = server.handshake(msg3);
        byte[] msg5 = client.handshake(msg4);
        byte[] done = server.handshake(msg5);

        report.check("two-sided handshake completes (server returns null)", done == null);
        report.check("server reaches stage 6", server.getStage() == 6);
        report.check("client reaches stage 6", client.getStage() == 6);
        report.check(
                "peers agree on client_crypt session key",
                Arrays.equals(
                        server.session().clientCrypt().key(), client.session().clientCrypt().key()));
        report.check(
                "peers agree on server_crypt session key",
                Arrays.equals(
                        server.session().serverCrypt().key(), client.session().serverCrypt().key()));
        report.check(
                "peers agree on session nonce",
                Arrays.equals(
                        server.session().clientCrypt().nonce(),
                        client.session().clientCrypt().nonce()));
        System.out.println("    both peers authenticated; session keys agree\n");
    }

    /**
     * Section 3: prove the derived {@link SeqCrypt} cipher encrypt/decrypt round-trips, advances
     * its sequence counter, and rejects a tampered MAC.
     */
    private static void sectionSeqCryptRoundTrip(Report report) throws MacFailureException {
        System.out.println("[3] SeqCrypt encrypt/decrypt round-trip");

        byte[] key = decodeHex("00112233445566778899aabbccddeeff");
        byte[] nonce = decodeHex("a1b2c3d4e5f60718");
        byte[] plaintext = decodeHex("48656c6c6f2c2053414b65212121212121"); // "Hello, SAKe!!!!!!"

        SeqCrypt tx = new SeqCrypt(key, nonce, 0L);
        SeqCrypt rx = new SeqCrypt(key, nonce, 0L);

        byte[] cipher = tx.encrypt(plaintext);
        report.check("encrypt advances tx_seq by 2", tx.getTxSeq() == 2L);
        report.check("ciphertext differs from plaintext", !Arrays.equals(cipher, plaintext));

        byte[] recovered = rx.decrypt(cipher);
        report.check("decrypt recovers the plaintext", Arrays.equals(recovered, plaintext));
        report.check("decrypt advances rx_seq by 2", rx.getRxSeq() == 2L);

        byte[] tampered = cipher.clone();
        tampered[tampered.length - 1] ^= (byte) 0x01;
        boolean rejected;
        try {
            new SeqCrypt(key, nonce, 0L).decrypt(tampered);
            rejected = false;
        } catch (MacFailureException expected) {
            rejected = true;
        }
        report.check("tampered ciphertext is rejected (MacFailureException)", rejected);
        System.out.println();
    }

    private static void printStage(String label, byte[] msg, int stage) {
        System.out.println("    " + label + " = " + toHex(msg) + "  (stage now " + stage + ")");
    }

    /** Tiny pass/fail accumulator so the harness can print a verdict and set an exit code. */
    private static final class Report {
        private int passed;
        private int failed;

        void check(String label, boolean ok) {
            if (ok) {
                passed++;
                System.out.println("    [PASS] " + label);
            } else {
                failed++;
                System.out.println("    [FAIL] " + label);
            }
        }

        void fail(String label) {
            failed++;
            System.out.println("    [FAIL] " + label);
        }

        boolean allPassed() {
            return failed == 0;
        }

        String summary() {
            return "SUMMARY: "
                    + passed
                    + " passed, "
                    + failed
                    + " failed -> "
                    + (allPassed() ? "ALL CHECKS PASSED" : "FAILURES PRESENT");
        }
    }
}
