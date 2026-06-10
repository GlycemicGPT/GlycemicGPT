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

/**
 * Server-side wrapper around {@link Session}: drives the handshake state machine and builds
 * outgoing messages from the running state.
 *
 * <p>Stage progression: 0 (consume 20 zero bytes, emit msg0) → 1 (consume msg1, emit msg2) → 3
 * (consume msg3, emit msg4) → 5 (consume msg5, emit {@code null} to signal completion) → 6 (done).
 */
public final class SakeServer extends Peer {

    /** Constant pad byte appended to the server's encrypted permit (msg4) plaintext. */
    static final byte DEFAULT_MSG4_PAD = (byte) 0x69;

    private final Session session;
    private final DeviceType localDeviceType;
    private final RngSource rng;
    private byte msg4Pad = DEFAULT_MSG4_PAD;

    public SakeServer(KeyDatabase keyDb) {
        this(keyDb, DeviceType.MOBILE_APPLICATION, new SecureRandomRngSource());
    }

    public SakeServer(KeyDatabase keyDb, DeviceType localDeviceType) {
        this(keyDb, localDeviceType, new SecureRandomRngSource());
    }

    public SakeServer(KeyDatabase keyDb, DeviceType localDeviceType, RngSource rng) {
        Objects.requireNonNull(keyDb, "keyDb");
        Objects.requireNonNull(localDeviceType, "localDeviceType");
        Objects.requireNonNull(rng, "rng");
        this.session = new Session(null, keyDb);
        this.localDeviceType = localDeviceType;
        this.rng = rng;
    }

    /**
     * Drive the handshake one step.
     *
     * @param input the 20-byte message just received from the client. At stage 0 this must be 20
     *     zero bytes (the wake-up frame sent over the SAKE characteristic when the peripheral
     *     subscribes to notifications).
     * @return the 20-byte message to send back to the client, or {@code null} once the handshake
     *     completes at stage 5.
     * @throws MacFailureException if any CMAC verification fails.
     */
    public byte[] handshake(byte[] input) throws MacFailureException {
        Session.checkLen(input);

        int stage = getStage();
        if (stage == 0) {
            for (byte b : input) {
                if (b != 0) {
                    throw new IllegalArgumentException("Stage 0 expects 20 zero bytes");
                }
            }
            byte[] msg0 = buildHandshake0S();
            session.handshake0S(msg0);
            incrementStage();
            return msg0;
        }

        if (stage == 1) {
            session.handshake1C(input);
            incrementStage();

            byte[] msg2 = buildHandshake2S();
            session.handshake2S(msg2);
            incrementStage();
            return msg2;
        }

        if (stage == 3) {
            session.handshake3C(input);
            incrementStage();

            byte[] msg4 = buildHandshake4S();
            incrementStage();
            return msg4;
        }

        if (stage == 5) {
            boolean ok = session.handshake5C(input);
            if (!ok) {
                throw new MacFailureException("Permit verification failed at stage 5");
            }
            incrementStage();

            // Reset server_crypt.rx_seq so subsequent session traffic is decoded
            // with the right starting sequence number.
            session.setServerCryptRxSeq(2L);
            return null;
        }

        throw new IllegalStateException("Handshake already complete (stage " + stage + ")");
    }

    public Session session() {
        return session;
    }

    public DeviceType localDeviceType() {
        return localDeviceType;
    }

    /**
     * Override the msg4 pad byte. Package-private; only the parity tests use this to reproduce a
     * captured packet trace bit-for-bit.
     */
    void setMsg4Pad(byte value) {
        this.msg4Pad = value;
    }

    private byte[] buildHandshake0S() {
        byte[] msg = new byte[Session.MESSAGE_SIZE];
        msg[0] = (byte) localDeviceType.value();
        msg[1] = 0x01;
        byte[] filler = rng.nextBytes(Session.MESSAGE_SIZE - 2);
        System.arraycopy(filler, 0, msg, 2, filler.length);
        return msg;
    }

    private byte[] buildHandshake2S() {
        byte[] serverKm = rng.nextBytes(8);
        byte[] serverNonce = rng.nextBytes(4);
        AesCmac auth =
                Session.cmac8(
                        session.clientKeyMaterial(),
                        serverKm,
                        session.derivationKey(),
                        session.handshakeAuthKey());
        byte[] prefix = auth.digest();

        byte[] out = new byte[Session.MESSAGE_SIZE];
        System.arraycopy(prefix, 0, out, 0, 8);
        System.arraycopy(serverKm, 0, out, 8, 8);
        System.arraycopy(serverNonce, 0, out, 16, 4);
        return out;
    }

    private byte[] buildHandshake4S() {
        byte[] payload = session.serverStaticKeys().handshakePayload();
        byte[] plaintext = Arrays.copyOf(payload, 17);
        plaintext[16] = msg4Pad;
        return session.serverCrypt().encrypt(plaintext);
    }
}
