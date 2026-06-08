/*
 * Shared test doubles and SAKE vectors for the peripheral connection-manager unit tests.
 *
 * The SAKE key databases here are the same shared, published-upstream OpenMinimed protocol
 * constants used by the B1 MedtronicSakeSessionTest -- firmware-extracted pump keys and a synthetic
 * matched key-DB pair, not session secrets and not unique per device. See
 * medtronic-ble-reverse-engineering.md Sec. 12.
 */
package com.glycemicgpt.mobile.ble.connection

import com.glycemicgpt.mobile.domain.pump.PumpCredentialProvider
import org.openminimed.sake.KeyDatabase

/** [SerialWorker] that runs posted tasks inline, so handshake steps complete synchronously in tests. */
class DirectSerialWorker : SerialWorker {
    var stopped = false
        private set

    override fun post(task: () -> Unit) {
        if (!stopped) task()
    }

    override fun stop() {
        stopped = true
    }
}

/** In-memory [PumpCredentialProvider]; only the pairing slots matter for the connection manager. */
class FakeCredentialStore : PumpCredentialProvider {
    private var address: String? = null
    private var code: String? = null
    var savePairingCount = 0
        private set
    var clearPairingCount = 0
        private set

    override fun getPairedAddress(): String? = address
    override fun getPairingCode(): String? = code
    override fun isPaired(): Boolean = address != null

    override fun savePairing(address: String, pairingCode: String) {
        this.address = address
        this.code = pairingCode
        savePairingCount++
    }

    override fun clearPairing() {
        address = null
        code = null
        clearPairingCount++
    }

    // SAKE does not use JPAKE; these are unused here.
    override fun saveJpakeCredentials(derivedSecretHex: String, serverNonceHex: String) = Unit
    override fun getJpakeDerivedSecret(): String? = null
    override fun getJpakeServerNonce(): String? = null
    override fun clearJpakeCredentials() = Unit
}

internal object SakeVectors {
    /** Insulin-pump key database recovered from real 780G firmware (OpenMinimed, public). */
    const val PUMP_KEYDB_HEX =
        "f75995e70401011bc1bf7cbf36fa1e2367d795ff09211903da6afbe986b650f1" +
            "4179c0e6852e0ce393781078ffc6f51919e2eaefbde69b8eca21e41ab59b881a" +
            "0bea0286ea91dc7582a86a714e1737f558f0d66dc1895c"

    /** Server-side (MOBILE_APPLICATION) half of the matched synthetic two-sided test pair. */
    const val CUSTOM_SERVER_KEYDB_HEX =
        "b079cdc504010144455249564154494f4e5f5f5f4b4559484e4453484b455f41" +
            "5554485f4b455950484f4e455f5045524d49545f454e4350484f4e455f5045" +
            "524d49545f4d4143ad14ad2780437db892d5650567d491b9"

    /** Client-side (INSULIN_PUMP) half of the matched synthetic two-sided test pair. */
    const val CUSTOM_CLIENT_KEYDB_HEX =
        "db8c1f2801010444455249564154494f4e5f5f5f4b4559484e4453484b455f41" +
            "5554485f4b455950554d505f5045524d49545f454e435250554d505f504552" +
            "4d49545f434d4143f2f8dbbb51563d4fa98fdaff0042a432"

    fun pumpKeyDb(): KeyDatabase = KeyDatabase.fromBytes(hex(PUMP_KEYDB_HEX))
    fun customServerKeyDb(): KeyDatabase = KeyDatabase.fromBytes(hex(CUSTOM_SERVER_KEYDB_HEX))
    fun customClientKeyDb(): KeyDatabase = KeyDatabase.fromBytes(hex(CUSTOM_CLIENT_KEYDB_HEX))

    fun hex(s: String): ByteArray {
        require(s.length % 2 == 0) { "Hex string has odd length" }
        return ByteArray(s.length / 2) { i -> s.substring(2 * i, 2 * i + 2).toInt(16).toByte() }
    }
}
