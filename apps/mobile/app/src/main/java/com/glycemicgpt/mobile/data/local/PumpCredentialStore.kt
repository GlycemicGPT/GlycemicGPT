package com.glycemicgpt.mobile.data.local

import android.content.Context
import android.content.SharedPreferences
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKeys
import com.glycemicgpt.mobile.domain.pump.PumpCredentialProvider
import dagger.hilt.android.qualifiers.ApplicationContext
import javax.inject.Inject
import javax.inject.Singleton

/**
 * Securely stores pump pairing credentials using EncryptedSharedPreferences.
 */
@Singleton
class PumpCredentialStore @Inject constructor(
    @ApplicationContext context: Context,
) : PumpCredentialProvider {

    private val prefs: SharedPreferences

    init {
        val masterKeyAlias = MasterKeys.getOrCreate(MasterKeys.AES256_GCM_SPEC)

        prefs = EncryptedSharedPreferences.create(
            "pump_credentials",
            masterKeyAlias,
            context,
            EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
            EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM,
        )
    }

    /** Save the paired pump address and pairing code. */
    override fun savePairing(address: String, pairingCode: String) {
        prefs.edit()
            .putString(KEY_ADDRESS, address)
            .putString(KEY_PAIRING_CODE, pairingCode)
            .putLong(KEY_PAIRED_AT, System.currentTimeMillis())
            .apply()
    }

    /** Get the saved pump Bluetooth address, or null if not paired. */
    override fun getPairedAddress(): String? = prefs.getString(KEY_ADDRESS, null)

    /** Get the saved pairing code, or null if not paired. */
    override fun getPairingCode(): String? = prefs.getString(KEY_PAIRING_CODE, null)

    /** Whether a pump is currently paired. */
    override fun isPaired(): Boolean = getPairedAddress() != null

    /**
     * Save JPAKE-derived credentials for confirmation mode reconnect.
     * These are persisted after a successful bootstrap JPAKE handshake and
     * allow subsequent connections to skip rounds 1-2.
     */
    override fun saveJpakeCredentials(derivedSecretHex: String, serverNonceHex: String) {
        prefs.edit()
            .putString(KEY_JPAKE_DERIVED_SECRET, derivedSecretHex)
            .putString(KEY_JPAKE_SERVER_NONCE, serverNonceHex)
            .apply()
    }

    /** Get the saved JPAKE derived secret (hex string), or null if not available. */
    override fun getJpakeDerivedSecret(): String? = prefs.getString(KEY_JPAKE_DERIVED_SECRET, null)

    /** Get the saved JPAKE server nonce (hex string), or null if not available. */
    override fun getJpakeServerNonce(): String? = prefs.getString(KEY_JPAKE_SERVER_NONCE, null)

    /** Clear JPAKE credentials only (e.g., on confirmation mode failure). */
    override fun clearJpakeCredentials() {
        prefs.edit()
            .remove(KEY_JPAKE_DERIVED_SECRET)
            .remove(KEY_JPAKE_SERVER_NONCE)
            .apply()
    }

    /** Clear all pairing data (unpair). */
    override fun clearPairing() {
        prefs.edit().clear().apply()
    }

    companion object {
        private const val KEY_ADDRESS = "paired_pump_address"
        private const val KEY_PAIRING_CODE = "pairing_code"
        private const val KEY_PAIRED_AT = "paired_at"
        private const val KEY_JPAKE_DERIVED_SECRET = "jpake_derived_secret"
        private const val KEY_JPAKE_SERVER_NONCE = "jpake_server_nonce"
    }
}
