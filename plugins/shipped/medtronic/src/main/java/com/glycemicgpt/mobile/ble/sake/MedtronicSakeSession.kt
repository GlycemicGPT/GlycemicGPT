/*
 * Transport-agnostic wrapper around the vendored OpenMinimed JavaSake server-side handshake.
 *
 * JavaSake itself (package `org.openminimed.sake`) is vendored verbatim from OpenMinimed
 * (https://github.com/OpenMinimed/JavaSake) at commit 00c08ae, GPL-3.0, used with the author's
 * permission. This wrapper is GlycemicGPT code (also GPL-3.0) that adapts the proven handshake to
 * the phone-as-peripheral BLE flow without taking any dependency on Android BLE APIs, so the
 * peripheral connection manager (Milestone B2) and readers (Milestone C) can drive it from GATT
 * callbacks. See `medtronic-ble-reverse-engineering.md` Sec. 4-5.
 */
package com.glycemicgpt.mobile.ble.sake

import org.openminimed.sake.DeviceType
import org.openminimed.sake.KeyDatabase
import org.openminimed.sake.MacFailureException
import org.openminimed.sake.RngSource
import org.openminimed.sake.SakeServer
import org.openminimed.sake.SecureRandomRngSource
import org.openminimed.sake.Session

/**
 * Drives the SAKE handshake with the phone in the **server** role (`MOBILE_APPLICATION`) and the
 * pump as the client (`INSULIN_PUMP`), then exposes the derived `SeqCrypt` session cipher for
 * post-handshake traffic.
 *
 * The API is byte-array in / byte-array out so the BLE layer can map it onto GATT semantics:
 *
 *  1. When the pump subscribes to notifications on the SAKE characteristic, send [newWakeUpFrame]
 *     as a notification. **This frame is NOT part of the handshake** -- it is only the wake-up the
 *     pump waits for before writing.
 *  2. For every WRITE the pump sends on the SAKE characteristic, call [onPumpWrite] and notify the
 *     returned bytes back (the pump's first write is 20 zero bytes -> produces msg0). A `null`
 *     return means the handshake is complete ([isComplete]).
 *  3. After completion, encrypt outbound notifications with [encryptForPump] and decrypt inbound
 *     writes with [decryptFromPump].
 *
 * Not thread-safe: drive it from a single worker thread (the BLE connection manager's handler
 * thread in B2).
 */
class MedtronicSakeSession(
    keyDb: KeyDatabase,
    rng: RngSource = SecureRandomRngSource(),
) {

    private val server = SakeServer(keyDb, DeviceType.MOBILE_APPLICATION, rng)

    /**
     * Returns a fresh 20-byte all-zero wake-up notification for the phone to emit once the pump
     * subscribes to the SAKE characteristic (each call allocates a new array). Deliberately separate
     * from [onPumpWrite]: feeding this frame into the handshake would advance the state machine with
     * the wrong input.
     */
    fun newWakeUpFrame(): ByteArray = ByteArray(Session.MESSAGE_SIZE)

    /**
     * Current handshake stage (0 -> 1 -> 3 -> 5 -> 6); 6 means complete. Internal because the raw
     * stage is a vendored-state-machine detail; callers outside the module use [isComplete].
     */
    internal val stage: Int
        get() = server.stage

    /** True once the six-stage handshake has completed and the session cipher is ready. */
    val isComplete: Boolean
        get() = server.stage == HANDSHAKE_COMPLETE_STAGE

    /**
     * Advance the handshake with a 20-byte WRITE received from the pump.
     *
     * @param pumpWrite the bytes the pump wrote to the SAKE characteristic. At stage 0 this must be
     *     20 zero bytes.
     * @return the 20-byte notification to send back to the pump, or `null` once the handshake
     *     completes.
     * @throws MacFailureException if a CMAC/permit verification fails (authentication failure).
     */
    @Throws(MacFailureException::class)
    fun onPumpWrite(pumpWrite: ByteArray): ByteArray? = server.handshake(pumpWrite)

    /**
     * Encrypt an outbound payload (phone -> pump notification) with the server-direction session
     * cipher. The sequence counter continues from where the handshake left it.
     *
     * @throws IllegalStateException if the handshake has not completed.
     */
    fun encryptForPump(plaintext: ByteArray): ByteArray {
        check(isComplete) { "SAKE handshake not complete (stage $stage)" }
        return server.session().serverCrypt().encrypt(plaintext)
    }

    /**
     * Decrypt an inbound payload (pump -> phone write) with the **client-direction** session cipher.
     * Pump-originated traffic is decoded with `clientCrypt`, mirroring the vendored handshake itself,
     * which decrypts the pump's stage-5 permit with `clientCrypt` (`Session.handshake5C`); its
     * `rx_seq` ends at 2 after the handshake, aligned with the pump's `clientCrypt` `tx_seq`. The
     * exact mapping is re-confirmed in Milestone C against PythonPumpConnector and live in 48.A2.
     *
     * @throws IllegalStateException if the handshake has not completed.
     * @throws MacFailureException if the trailer MAC does not authenticate.
     */
    @Throws(MacFailureException::class)
    fun decryptFromPump(ciphertext: ByteArray): ByteArray {
        check(isComplete) { "SAKE handshake not complete (stage $stage)" }
        return server.session().clientCrypt().decrypt(ciphertext)
    }

    companion object {
        /** Terminal handshake stage for the server role. */
        const val HANDSHAKE_COMPLETE_STAGE = 6
    }
}
