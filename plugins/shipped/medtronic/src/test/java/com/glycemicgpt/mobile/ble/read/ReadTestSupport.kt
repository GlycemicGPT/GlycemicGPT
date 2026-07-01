/*
 * Shared test doubles and SAKE vectors for the Medtronic 700-series read-layer unit tests.
 *
 * The SAKE key databases are the same shared, published-upstream OpenMinimed protocol constants the
 * B1/B2 suites use -- a synthetic matched key-DB pair, not session secrets and not unique per device
 * (medtronic-ble-reverse-engineering.md Sec. 12). Driving a real two-sided JavaSake handshake here
 * lets the reader tests decrypt genuinely pump-encrypted frames (the pump role uses its client_crypt),
 * which is a stronger, protocol-faithful stand-in than a hand-mocked cipher while a captured live
 * session frame is unavailable offline (TODO(48.A2)).
 */
package com.glycemicgpt.mobile.ble.read

import com.glycemicgpt.mobile.ble.sake.MedtronicSakeSession
import java.util.UUID
import org.openminimed.sake.DeviceType
import org.openminimed.sake.KeyDatabase
import org.openminimed.sake.SakeClient
import org.openminimed.sake.Session

/**
 * In-memory [MedtronicGattLink]. [reads] stubs static characteristic values; [subscribe] records a
 * per-characteristic notification handler; [write] records the write and runs [onWrite] so a test
 * can script the pump's notification/response in reaction to a control-point request.
 */
internal class FakeGattLink : MedtronicGattLink {
    val reads = mutableMapOf<UUID, ByteArray>()
    val writes = mutableListOf<Pair<UUID, ByteArray>>()
    private val handlers = mutableMapOf<UUID, (ByteArray) -> Unit>()
    // The last handler ever registered per characteristic, retained across unsubscribe so a test can
    // simulate a BLE notification already in flight when the reader unsubscribes (see [emitInFlight]).
    private val retained = mutableMapOf<UUID, (ByteArray) -> Unit>()

    /** Invoked on every [write]; the receiver scripts notifications via [emit]. */
    var onWrite: (FakeGattLink.(characteristic: UUID, value: ByteArray) -> Unit)? = null

    override fun read(characteristic: UUID): ByteArray =
        reads[characteristic] ?: throw MedtronicReadException("no read stub for $characteristic")

    override fun write(characteristic: UUID, value: ByteArray) {
        writes.add(characteristic to value)
        onWrite?.invoke(this, characteristic, value)
    }

    override fun subscribe(characteristic: UUID, onPdu: (ByteArray) -> Unit) {
        handlers[characteristic] = onPdu
        retained[characteristic] = onPdu
    }

    override fun unsubscribe(characteristic: UUID) {
        handlers.remove(characteristic)
    }

    override fun cancelAllSubscriptions() {
        handlers.clear()
        retained.clear()
    }

    /** Deliver one inbound PDU to whatever handler is currently subscribed on [characteristic]. */
    fun emit(characteristic: UUID, pdu: ByteArray) {
        handlers[characteristic]?.invoke(pdu)
    }

    /**
     * Deliver a PDU to the last-registered handler even after the reader has unsubscribed, simulating
     * a BLE notification that was already in flight when the exchange finished. Used to exercise the
     * reader's post-finish guard.
     */
    fun emitInFlight(characteristic: UUID, pdu: ByteArray) {
        retained[characteristic]?.invoke(pdu)
    }

    fun isSubscribed(characteristic: UUID): Boolean = handlers.containsKey(characteristic)
}

/**
 * A completed two-sided SAKE session: [server] is the phone-side wrapper the readers consume;
 * [pumpEncrypt] produces a frame the pump (client role) would send, so a test can feed a genuinely
 * encrypted payload through [MedtronicSakeSession.decryptFromPump].
 *
 * Encrypt frames in the same order they are delivered to the server so the per-direction sequence
 * counters stay aligned (the pump's client_crypt tx and the server's inbound rx both step 2,4,6,...).
 */
internal class TwoSidedSession {
    val server = MedtronicSakeSession(KeyDatabase.fromBytes(hex(CUSTOM_SERVER_KEYDB_HEX)))
    private val client = SakeClient(KeyDatabase.fromBytes(hex(CUSTOM_CLIENT_KEYDB_HEX)), DeviceType.INSULIN_PUMP)

    init {
        val msg0 = server.onPumpWrite(ByteArray(Session.MESSAGE_SIZE))
        val msg1 = client.handshake(msg0)
        val msg2 = server.onPumpWrite(msg1)
        val msg3 = client.handshake(msg2)
        val msg4 = server.onPumpWrite(msg3)
        val msg5 = client.handshake(msg4)
        check(server.onPumpWrite(msg5) == null) { "handshake did not complete" }
    }

    /** Encrypt [plaintext] as the pump (client role) would, for the server to decrypt as inbound traffic. */
    fun pumpEncrypt(plaintext: ByteArray): ByteArray = client.session().clientCrypt().encrypt(plaintext)
}

internal fun hex(s: String): ByteArray {
    require(s.length % 2 == 0) { "Hex string has odd length" }
    return ByteArray(s.length / 2) { i -> s.substring(2 * i, 2 * i + 2).toInt(16).toByte() }
}

/** CGM Feature characteristic value with the E2E-CRC bit (12) set. */
internal const val CGM_FEATURE_E2E_ENABLED_HEX = "009001591404"

/** A captured plaintext CGM measurement frame that parses to 249 mg/dL, rising. */
internal const val CGM_MEASUREMENT_249_HEX = "0ec3f900f40b000074e00a00e0f1"

/** Server-side (MOBILE_APPLICATION) half of the matched synthetic two-sided test pair. */
internal const val CUSTOM_SERVER_KEYDB_HEX =
    "b079cdc504010144455249564154494f4e5f5f5f4b4559484e4453484b455f41" +
        "5554485f4b455950484f4e455f5045524d49545f454e4350484f4e455f5045" +
        "524d49545f4d4143ad14ad2780437db892d5650567d491b9"

/** Client-side (INSULIN_PUMP) half of the matched synthetic two-sided test pair. */
internal const val CUSTOM_CLIENT_KEYDB_HEX =
    "db8c1f2801010444455249564154494f4e5f5f5f4b4559484e4453484b455f41" +
        "5554485f4b455950554d505f5045524d49545f454e435250554d505f504552" +
        "4d49545f434d4143f2f8dbbb51563d4fa98fdaff0042a432"
