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
 * Client-side wrapper around {@link Session}.
 *
 * <p>Stage progression: 0 (consume server msg0, emit msg1) → 2 (consume msg2, emit msg3) → 4
 * (consume msg4, emit msg5) → 6 (done).
 */
public final class SakeClient extends Peer {

    /** Constant pad byte appended to the client's encrypted permit (msg5) plaintext. */
    static final byte DEFAULT_MSG5_PAD = (byte) 0x00;

    private final Session session;
    private final DeviceType localDeviceType;
    private final RngSource rng;
    private byte msg5Pad = DEFAULT_MSG5_PAD;

    public SakeClient(KeyDatabase keyDb) {
        this(keyDb, DeviceType.PRIMARY_DISPLAY, new SecureRandomRngSource());
    }

    public SakeClient(KeyDatabase keyDb, DeviceType localDeviceType) {
        this(keyDb, localDeviceType, new SecureRandomRngSource());
    }

    public SakeClient(KeyDatabase keyDb, DeviceType localDeviceType, RngSource rng) {
        Objects.requireNonNull(keyDb, "keyDb");
        Objects.requireNonNull(localDeviceType, "localDeviceType");
        Objects.requireNonNull(rng, "rng");
        this.session = new Session(keyDb, null);
        this.localDeviceType = localDeviceType;
        this.rng = rng;
    }

    /**
     * Drive the handshake one step.
     *
     * @param input the 20-byte message just received from the server.
     * @return the 20-byte message to send back to the server.
     * @throws MacFailureException if any CMAC verification fails.
     */
    public byte[] handshake(byte[] input) throws MacFailureException {
        Session.checkLen(input);

        int stage = getStage();
        if (stage == 0) {
            session.handshake0S(input);
            incrementStage();

            byte[] msg1 = buildHandshake1C();
            session.handshake1C(msg1);
            incrementStage();
            return msg1;
        }

        if (stage == 2) {
            session.handshake2S(input);
            incrementStage();

            byte[] msg3 = buildHandshake3C();
            session.handshake3C(msg3);
            incrementStage();
            return msg3;
        }

        if (stage == 4) {
            boolean ok = session.handshake4S(input);
            if (!ok) {
                throw new MacFailureException("Permit verification failed at stage 4");
            }
            incrementStage();

            byte[] msg5 = buildHandshake5C();
            incrementStage();
            return msg5;
        }

        throw new IllegalStateException("Invalid stage for SakeClient.handshake(): " + stage);
    }

    public Session session() {
        return session;
    }

    public DeviceType localDeviceType() {
        return localDeviceType;
    }

    void setMsg5Pad(byte value) {
        this.msg5Pad = value;
    }

    private byte[] buildHandshake1C() {
        byte[] key = rng.nextBytes(8);
        byte[] nonce = rng.nextBytes(4);

        byte[] msg = new byte[Session.MESSAGE_SIZE];
        System.arraycopy(key, 0, msg, 0, 8);
        msg[8] = (byte) localDeviceType.value();
        System.arraycopy(nonce, 0, msg, 9, 4);
        // Bytes 13..19 remain zero, matching the reference Python implementation.
        return msg;
    }

    private byte[] buildHandshake3C() {
        AesCmac auth1 =
                Session.cmac8(
                        session.clientKeyMaterial(),
                        session.serverKeyMaterial(),
                        session.derivationKey(),
                        session.handshakeAuthKey());
        byte[] auth1Tag = auth1.digest();

        byte[] inner = new byte[8 + 8 + 16];
        System.arraycopy(auth1Tag, 0, inner, 0, 8);
        System.arraycopy(session.serverKeyMaterial(), 0, inner, 8, 8);
        System.arraycopy(session.derivationKey(), 0, inner, 16, 16);

        AesCmac auth2 = new AesCmac(session.handshakeAuthKey(), 8);
        auth2.update(inner);
        byte[] prefix = auth2.digest();

        byte[] filler = rng.nextBytes(12);
        byte[] out = new byte[Session.MESSAGE_SIZE];
        System.arraycopy(prefix, 0, out, 0, 8);
        System.arraycopy(filler, 0, out, 8, 12);
        return out;
    }

    private byte[] buildHandshake5C() {
        byte[] payload = session.clientStaticKeys().handshakePayload();
        byte[] plaintext = Arrays.copyOf(payload, 17);
        plaintext[16] = msg5Pad;
        return session.clientCrypt().encrypt(plaintext);
    }
}
