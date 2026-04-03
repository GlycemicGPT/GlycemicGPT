package com.glycemicgpt.mobile.domain.pump

/**
 * Abstraction for pump credential storage.
 *
 * Provides access to pairing credentials and JPAKE session data
 * without depending on Android-specific encrypted storage implementations.
 * Implementations live in the app module where Android framework dependencies
 * (EncryptedSharedPreferences) are available.
 */
interface PumpCredentialProvider {
    fun getPairedAddress(): String?
    fun getPairingCode(): String?
    fun isPaired(): Boolean
    fun savePairing(address: String, pairingCode: String)
    fun clearPairing()
    fun saveJpakeCredentials(derivedSecretHex: String, serverNonceHex: String)
    fun getJpakeDerivedSecret(): String?
    fun getJpakeServerNonce(): String?
    fun clearJpakeCredentials()
}
