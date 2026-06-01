/*
 * Drives the SAKE handshake from GATT-server events for the Medtronic 700-series read-only driver.
 *
 * GlycemicGPT code (GPL-3.0). The handshake wire choreography -- wake-up on subscribe, then advance
 * one stage per pump write -- mirrors OpenMinimed's JavaPumpConnector SakeHandler (GPL-3.0, used with
 * permission); the cryptographic state machine itself lives in the vendored JavaSake behind
 * MedtronicSakeSession (B1). See medtronic-ble-reverse-engineering.md Sec. 4.
 */
package com.glycemicgpt.mobile.ble.connection

import com.glycemicgpt.mobile.ble.protocol.PduFramer
import com.glycemicgpt.mobile.ble.sake.MedtronicSakeSession
import timber.log.Timber

/**
 * Translates SAKE-characteristic GATT events into [MedtronicSakeSession] steps, serialized onto a
 * [SerialWorker] so the binder thread that delivers BLE callbacks is never blocked by crypto work.
 *
 * Wire order (Sec. 4):
 *  1. [onSubscribed] -- the pump enabled notifications: emit the 20-byte wake-up notification.
 *  2. [onPumpWrite] -- for each write the pump sends, advance the handshake and notify the response;
 *     a `null` response means the handshake completed and the session cipher is ready.
 *
 * A resubscribe before completion is treated as an abort and restarts the handshake with a fresh
 * session (matching JavaPumpConnector). All callbacks ([HandshakeListener], [notifySink]) are
 * invoked on the worker thread.
 */
class SakeHandshakeDriver(
    private val worker: SerialWorker,
    private val sessionFactory: () -> MedtronicSakeSession,
    private val notifySink: (ByteArray) -> Boolean,
    private val listener: HandshakeListener,
) {

    /** Outcome callbacks from the handshake. Invoked on the [SerialWorker] thread. */
    interface HandshakeListener {
        /** The six-stage handshake completed; [session] holds the live cipher for the read layer. */
        fun onAuthenticated(session: MedtronicSakeSession)

        /** Authentication failed (CMAC/permit verification or an unexpected error). */
        fun onAuthFailed(cause: Throwable?)
    }

    // All mutable state is confined to the worker thread; only [post] touches it.
    private var session: MedtronicSakeSession = sessionFactory()
    private var pumpSubscribed = false
    private var complete = false
    private var failed = false

    /** Discard the current handshake and arm a fresh session for the next connection. */
    fun reset() = worker.post {
        session = sessionFactory()
        pumpSubscribed = false
        complete = false
        failed = false
    }

    /**
     * The pump disabled SAKE notifications. Clearing the subscribed flag lets a later [onSubscribed]
     * restart an unfinished handshake from a fresh wake-up (the pump resubscribes when it retries).
     */
    fun onUnsubscribed() = worker.post {
        pumpSubscribed = false
    }

    /**
     * The pump subscribed to SAKE notifications: emit the wake-up frame. If the pump resubscribes
     * mid-handshake the session is rebuilt so the new wake-up starts cleanly.
     */
    fun onSubscribed() = worker.post {
        if (pumpSubscribed) return@post
        if (!complete && session.stage != 0) {
            Timber.w("Pump resubscribed mid-handshake; restarting SAKE state")
            session = sessionFactory()
        }
        pumpSubscribed = true
        Timber.d("Pump subscribed to SAKE; sending wake-up")
        notify(session.newWakeUpFrame())
    }

    /**
     * Advance the handshake with a 20-byte write from the pump. Writes after completion are session
     * traffic for the read layer (Milestone C) and are ignored here.
     */
    fun onPumpWrite(value: ByteArray) {
        val copy = value.copyOf()
        worker.post {
            if (complete || failed) {
                Timber.d("Ignoring SAKE write after handshake terminated (len=%d)", copy.size)
                return@post
            }
            try {
                val response = session.onPumpWrite(copy)
                if (response != null) {
                    notify(response)
                } else {
                    complete = true
                    Timber.i("SAKE handshake complete")
                    listener.onAuthenticated(session)
                }
            } catch (e: Exception) {
                // Latch the failure so further writes on the now-corrupted session do not re-throw and
                // fire onAuthFailed repeatedly; reset() re-arms a fresh session.
                failed = true
                Timber.e(e, "SAKE handshake failed")
                listener.onAuthFailed(e)
            }
        }
    }

    /**
     * Emit [payload] to the pump, fragmented to <= 20-byte PDUs via the B1 framer so no oversized
     * PDU is ever sent (medtronic-ble-reverse-engineering.md Sec. 6). SAKE frames are exactly 20
     * bytes, so this is a single PDU in practice; the framer is the single MTU choke point.
     */
    private fun notify(payload: ByteArray) {
        for (pdu in PduFramer.fragment(payload)) {
            if (!notifySink(pdu)) {
                Timber.w("SAKE notification not delivered (len=%d)", pdu.size)
            }
        }
    }
}
