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
import org.openminimed.sake.crypto.AesEcb;

/**
 * Holds the cryptographic state of a single SAKE handshake.
 *
 * <p>Exactly one of {@code clientKeyDb} or {@code serverKeyDb} must be supplied at construction
 * time: the absent side will be unable to perform the cryptographic permit check on its inbound
 * permit message and will simply log the payload comparison instead.
 *
 * <p>Method names match the reference Python implementation ({@code pysake/session.py}). The
 * trailing {@code S} / {@code C} marks which side the message originated from (server vs client),
 * not which side is calling the method.
 */
public final class Session {

    /** Required length in bytes of every handshake message. */
    public static final int MESSAGE_SIZE = 20;

    private static final int KEY_MATERIAL_SIZE = 8;
    private static final int NONCE_SIZE = 4;
    private static final int PERMIT_SIZE = 16;
    private static final int CMAC8_SIZE = 8;

    private final KeyDatabase clientKeyDb;
    private final KeyDatabase serverKeyDb;

    private DeviceType serverDeviceType;
    private DeviceType clientDeviceType;

    private byte[] clientKeyMaterial;
    private byte[] clientNonce;

    private byte[] serverKeyMaterial;
    private byte[] serverNonce;

    private byte[] derivationKey;
    private byte[] handshakeAuthKey;

    private StaticKeys clientStaticKeys;
    private StaticKeys serverStaticKeys;

    private SeqCrypt clientCrypt;
    private SeqCrypt serverCrypt;

    public Session(KeyDatabase clientKeyDb, KeyDatabase serverKeyDb) {
        int provided = (clientKeyDb != null ? 1 : 0) + (serverKeyDb != null ? 1 : 0);
        if (provided != 1) {
            throw new IllegalArgumentException(
                    "Exactly one of clientKeyDb or serverKeyDb is required, got " + provided);
        }
        this.clientKeyDb = clientKeyDb;
        this.serverKeyDb = serverKeyDb;
    }

    public void handshake0S(byte[] msg) {
        checkLen(msg);
        if (msg[1] != 0x01) {
            throw new IllegalArgumentException("Unexpected byte at offset 1: " + (msg[1] & 0xFF));
        }
        this.serverDeviceType = DeviceType.fromValue(msg[0] & 0xFF);
    }

    public void handshake1C(byte[] msg) {
        checkLen(msg);
        this.clientKeyMaterial = Arrays.copyOfRange(msg, 0, 8);
        this.clientDeviceType = DeviceType.fromValue(msg[8] & 0xFF);
        this.clientNonce = Arrays.copyOfRange(msg, 9, 13);

        int cdt = clientDeviceType.value();
        int sdt = serverDeviceType.value();

        StaticKeys staticKeys = null;
        if (clientKeyDb != null && clientKeyDb.localDeviceType().value() == cdt) {
            staticKeys = clientKeyDb.remoteDevices().get(DeviceType.fromValue(sdt));
            this.clientStaticKeys = staticKeys;
        }
        if (serverKeyDb != null && serverKeyDb.localDeviceType().value() == sdt) {
            staticKeys = serverKeyDb.remoteDevices().get(DeviceType.fromValue(cdt));
            this.serverStaticKeys = staticKeys;
        }
        if (staticKeys == null) {
            throw new IllegalStateException(
                    "No keys available for client device type "
                            + cdt
                            + " and server device type "
                            + sdt);
        }

        this.derivationKey = staticKeys.derivationKey();
        this.handshakeAuthKey = staticKeys.handshakeAuthKey();
    }

    public void handshake2S(byte[] msg) throws MacFailureException {
        checkLen(msg);
        byte[] received = Arrays.copyOfRange(msg, 0, CMAC8_SIZE);
        byte[] serverKm = Arrays.copyOfRange(msg, 8, 16);
        byte[] serverN = Arrays.copyOfRange(msg, 16, 20);

        AesCmac auth = cmac8(clientKeyMaterial, serverKm, derivationKey, handshakeAuthKey);
        if (!auth.verify(received)) {
            throw new MacFailureException("handshake2S CMAC8 verification failed");
        }

        this.serverKeyMaterial = serverKm;
        this.serverNonce = serverN;
    }

    public void handshake3C(byte[] msg) throws MacFailureException {
        checkLen(msg);
        byte[] received = Arrays.copyOfRange(msg, 0, CMAC8_SIZE);

        AesCmac auth1 =
                cmac8(clientKeyMaterial, serverKeyMaterial, derivationKey, handshakeAuthKey);
        byte[] auth1Tag = auth1.digest();

        byte[] inner = new byte[CMAC8_SIZE + KEY_MATERIAL_SIZE + AesCmac.BLOCK_SIZE];
        System.arraycopy(auth1Tag, 0, inner, 0, CMAC8_SIZE);
        System.arraycopy(serverKeyMaterial, 0, inner, CMAC8_SIZE, KEY_MATERIAL_SIZE);
        System.arraycopy(
                derivationKey, 0, inner, CMAC8_SIZE + KEY_MATERIAL_SIZE, AesCmac.BLOCK_SIZE);

        AesCmac auth2 = new AesCmac(handshakeAuthKey, CMAC8_SIZE);
        auth2.update(inner);
        if (!auth2.verify(received)) {
            throw new MacFailureException("handshake3C CMAC8 verification failed");
        }

        createCrypts();
    }

    public boolean handshake4S(byte[] msg) throws MacFailureException {
        checkLen(msg);
        byte[] decrypted = serverCrypt.decrypt(msg);
        byte[] payload = Arrays.copyOfRange(decrypted, 0, PERMIT_SIZE);
        return checkPermit(payload, clientStaticKeys, serverStaticKeys, serverDeviceType.value());
    }

    public boolean handshake5C(byte[] msg) throws MacFailureException {
        checkLen(msg);
        byte[] decrypted = clientCrypt.decrypt(msg);
        // pysake takes plaintext[:-1] but the permit body is exactly 16 bytes (PERMIT_SIZE).
        byte[] payload = Arrays.copyOfRange(decrypted, 0, PERMIT_SIZE);
        return checkPermit(payload, serverStaticKeys, clientStaticKeys, clientDeviceType.value());
    }

    /**
     * Compute the 8-byte CMAC over {@code serverKm || clientKm || derivationKey}.
     *
     * @return a primed {@link AesCmac} ready to {@link AesCmac#digest()} or {@link
     *     AesCmac#verify(byte[])}.
     */
    public static AesCmac cmac8(
            byte[] clientKm, byte[] serverKm, byte[] derivationKey, byte[] handshakeAuthKey) {
        byte[] msg = new byte[32];
        System.arraycopy(serverKm, 0, msg, 0, KEY_MATERIAL_SIZE);
        System.arraycopy(clientKm, 0, msg, KEY_MATERIAL_SIZE, KEY_MATERIAL_SIZE);
        System.arraycopy(derivationKey, 0, msg, 2 * KEY_MATERIAL_SIZE, AesCmac.BLOCK_SIZE);
        AesCmac cmac = new AesCmac(handshakeAuthKey, CMAC8_SIZE);
        cmac.update(msg);
        return cmac;
    }

    /**
     * @throws IllegalArgumentException if {@code msg} is not exactly {@value #MESSAGE_SIZE} bytes.
     */
    public static void checkLen(byte[] msg) {
        Objects.requireNonNull(msg, "msg");
        if (msg.length != MESSAGE_SIZE) {
            throw new IllegalArgumentException(
                    "Invalid message length: " + msg.length + ", expected " + MESSAGE_SIZE);
        }
    }

    private void createCrypts() {
        byte[] kmConcat = new byte[2 * KEY_MATERIAL_SIZE];
        System.arraycopy(serverKeyMaterial, 0, kmConcat, 0, KEY_MATERIAL_SIZE);
        System.arraycopy(clientKeyMaterial, 0, kmConcat, KEY_MATERIAL_SIZE, KEY_MATERIAL_SIZE);
        byte[] sessionKey = AesEcb.encryptBlock(derivationKey, kmConcat);

        byte[] sessionNonce = new byte[2 * NONCE_SIZE];
        System.arraycopy(clientNonce, 0, sessionNonce, 0, NONCE_SIZE);
        System.arraycopy(serverNonce, 0, sessionNonce, NONCE_SIZE, NONCE_SIZE);

        this.clientCrypt = new SeqCrypt(sessionKey, sessionNonce, 0L);
        this.serverCrypt = new SeqCrypt(sessionKey, sessionNonce, 1L);
    }

    private boolean checkPermit(
            byte[] payload,
            StaticKeys verifierStaticKeys,
            StaticKeys proverStaticKeys,
            int proverDeviceType)
            throws MacFailureException {
        if (verifierStaticKeys == null) {
            return false;
        }
        byte[] plain = AesEcb.decryptBlock(verifierStaticKeys.permitDecryptKey(), payload);
        AesCmac auth = new AesCmac(verifierStaticKeys.permitAuthKey(), 4);
        auth.update(Arrays.copyOfRange(plain, 0, 12));
        if (!auth.verify(Arrays.copyOfRange(plain, 12, 16))) {
            throw new MacFailureException("Permit auth tag verification failed");
        }
        return plain[0] == 0 && (plain[1] & 0xFF) == proverDeviceType;
    }

    public DeviceType serverDeviceType() {
        return serverDeviceType;
    }

    public DeviceType clientDeviceType() {
        return clientDeviceType;
    }

    public byte[] clientKeyMaterial() {
        return clientKeyMaterial == null ? null : clientKeyMaterial.clone();
    }

    public byte[] clientNonce() {
        return clientNonce == null ? null : clientNonce.clone();
    }

    public byte[] serverKeyMaterial() {
        return serverKeyMaterial == null ? null : serverKeyMaterial.clone();
    }

    public byte[] serverNonce() {
        return serverNonce == null ? null : serverNonce.clone();
    }

    public byte[] derivationKey() {
        return derivationKey == null ? null : derivationKey.clone();
    }

    public byte[] handshakeAuthKey() {
        return handshakeAuthKey == null ? null : handshakeAuthKey.clone();
    }

    public StaticKeys clientStaticKeys() {
        return clientStaticKeys;
    }

    public StaticKeys serverStaticKeys() {
        return serverStaticKeys;
    }

    /**
     * Returns the live {@link SeqCrypt} used for messages originating from the client. The
     * reference is intentional: {@link SakeServer} and {@link SakeClient} drive the sequence
     * counter forward by calling {@link SeqCrypt#encrypt(byte[])} / {@link
     * SeqCrypt#decrypt(byte[])} directly on this instance. Callers outside the handshake should
     * treat the returned object as read-only.
     */
    public SeqCrypt clientCrypt() {
        return clientCrypt;
    }

    /**
     * Returns the live {@link SeqCrypt} used for messages originating from the server. See {@link
     * #clientCrypt()} for the rationale on returning the reference directly.
     */
    public SeqCrypt serverCrypt() {
        return serverCrypt;
    }

    /** Package-private setter used by {@code SakeServer} to apply post-handshake adjustments. */
    void setServerCryptRxSeq(long value) {
        if (serverCrypt != null) {
            serverCrypt.setRxSeq(value);
        }
    }
}
