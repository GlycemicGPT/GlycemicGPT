/*
 * Single-threaded work serialization for the Medtronic peripheral driver.
 *
 * The SAKE handshake and session crypto must never run on the binder thread that delivers BLE
 * GATT-server callbacks (blocking it stalls the whole Bluetooth stack). OpenMinimed's JavaPumpConnector
 * SakeHandler (GPL-3.0, used with permission) serializes that work onto a dedicated HandlerThread;
 * this interface is the same idea behind a seam so the handshake driver is unit-testable with an
 * inline worker instead of a real Android looper. See medtronic-ble-reverse-engineering.md Sec. 11.
 */
package com.glycemicgpt.mobile.ble.connection

import android.os.Handler
import android.os.HandlerThread

/**
 * Posts tasks to a single background thread, preserving submission order. Implementations guarantee
 * tasks never run concurrently, so the [com.glycemicgpt.mobile.ble.sake.MedtronicSakeSession] (which
 * is documented as not thread-safe) can be driven without additional locking.
 */
interface SerialWorker {
    /** Enqueue [task] to run on the worker thread. */
    fun post(task: () -> Unit)

    /** Stop the worker and drop any queued tasks. After this, [post] is a no-op. */
    fun stop()
}

/**
 * [SerialWorker] backed by an Android [HandlerThread] -- the production worker that keeps SAKE work
 * off the binder thread, mirroring JavaPumpConnector's SakeHandler. The thread is started eagerly
 * and reused across pump connect/disconnect cycles.
 */
class HandlerThreadSerialWorker(threadName: String) : SerialWorker {
    private val thread = HandlerThread(threadName).apply { start() }
    private val handler = Handler(thread.looper)

    @Volatile
    private var stopped = false

    override fun post(task: () -> Unit) {
        if (stopped) return
        handler.post(task)
    }

    override fun stop() {
        stopped = true
        handler.removeCallbacksAndMessages(null)
        thread.quitSafely()
    }
}
