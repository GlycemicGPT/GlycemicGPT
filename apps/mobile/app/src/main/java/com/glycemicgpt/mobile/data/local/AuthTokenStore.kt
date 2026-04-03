package com.glycemicgpt.mobile.data.local

import android.content.Context
import android.content.SharedPreferences
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKeys
import dagger.hilt.android.qualifiers.ApplicationContext
import timber.log.Timber
import javax.inject.Inject
import javax.inject.Singleton

/**
 * Securely stores backend authentication credentials using EncryptedSharedPreferences.
 *
 * Stores the GlycemicGPT server base URL, JWT token, refresh token, and their expirations.
 * Base URL is stored independently of the token lifecycle and is never cleared by
 * token operations (only by explicit user action).
 */
@Singleton
class AuthTokenStore @Inject constructor(
    @ApplicationContext context: Context,
) {

    private val prefs: SharedPreferences

    init {
        val masterKeyAlias = MasterKeys.getOrCreate(MasterKeys.AES256_GCM_SPEC)
        prefs = EncryptedSharedPreferences.create(
            "auth_credentials",
            masterKeyAlias,
            context,
            EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
            EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM,
        )
    }

    fun saveCredentials(baseUrl: String, token: String, expiresAtMs: Long, email: String? = null) {
        prefs.edit()
            .putString(KEY_BASE_URL, baseUrl.trimEnd('/'))
            .putString(KEY_TOKEN, token)
            .putLong(KEY_EXPIRES_AT, expiresAtMs)
            .apply {
                if (email != null) putString(KEY_USER_EMAIL, email)
            }
            .apply()
    }

    fun saveBaseUrl(url: String) {
        prefs.edit()
            .putString(KEY_BASE_URL, url.trimEnd('/'))
            .apply()
    }

    fun getBaseUrl(): String? = prefs.getString(KEY_BASE_URL, null)

    fun getUserEmail(): String? = prefs.getString(KEY_USER_EMAIL, null)

    fun getToken(): String? {
        val token = prefs.getString(KEY_TOKEN, null) ?: return null
        val expiresAt = prefs.getLong(KEY_EXPIRES_AT, 0L)
        if (expiresAt > 0 && System.currentTimeMillis() >= expiresAt) {
            // Token is expired -- return null but do NOT clear it.
            // Clearing here caused a race condition: NavHost reads isLoggedIn()
            // synchronously during composition (gets false because token expired),
            // while AuthManager.validateOnStartup() refreshes async.
            // The TokenRefreshInterceptor handles 401s and obtains new tokens.
            return null
        }
        return token
    }

    /** Returns the access token expiration timestamp in milliseconds, or 0 if not set. */
    fun getTokenExpiresAtMs(): Long = prefs.getLong(KEY_EXPIRES_AT, 0L)

    fun isLoggedIn(): Boolean = getToken() != null

    /**
     * Returns true if the user has an active session (valid refresh token exists),
     * regardless of whether the current access token has expired.
     *
     * Use this for navigation decisions (start destination, service keep-alive)
     * where an expired access token should trigger a background refresh, NOT a
     * logout. Use [isLoggedIn] only for checking whether an API call can be made
     * right now without refreshing first.
     */
    fun hasActiveSession(): Boolean = !isRefreshTokenExpired()

    fun saveRefreshToken(token: String) {
        val expiresAtMs = extractJwtExpiration(token)
        prefs.edit()
            .putString(KEY_REFRESH_TOKEN, token)
            .apply {
                if (expiresAtMs > 0) putLong(KEY_REFRESH_TOKEN_EXPIRES_AT, expiresAtMs)
            }
            .apply()
    }

    fun getRefreshToken(): String? = prefs.getString(KEY_REFRESH_TOKEN, null)

    /** Returns the refresh token expiration in milliseconds, or 0 if unknown. */
    fun getRefreshTokenExpiresAtMs(): Long = prefs.getLong(KEY_REFRESH_TOKEN_EXPIRES_AT, 0L)

    /** Returns true if the refresh token is expired or missing. */
    fun isRefreshTokenExpired(): Boolean {
        val refreshToken = getRefreshToken() ?: return true
        if (refreshToken.isBlank()) return true
        val expiresAt = getRefreshTokenExpiresAtMs()
        if (expiresAt <= 0) return false // Unknown expiry, assume valid
        return System.currentTimeMillis() >= expiresAt
    }

    /** Returns true if the access token will expire within the given milliseconds. */
    fun isTokenExpiringSoon(withinMs: Long): Boolean {
        val token = prefs.getString(KEY_TOKEN, null) ?: return false
        if (token.isBlank()) return false
        val expiresAt = prefs.getLong(KEY_EXPIRES_AT, 0L)
        if (expiresAt <= 0) return false
        return System.currentTimeMillis() >= (expiresAt - withinMs)
    }

    fun clearAccessToken() {
        prefs.edit()
            .remove(KEY_TOKEN)
            .remove(KEY_EXPIRES_AT)
            .apply()
    }

    /** Clears all token data but preserves the base URL. */
    fun clearToken() {
        prefs.edit()
            .remove(KEY_TOKEN)
            .remove(KEY_EXPIRES_AT)
            .remove(KEY_USER_EMAIL)
            .remove(KEY_REFRESH_TOKEN)
            .remove(KEY_REFRESH_TOKEN_EXPIRES_AT)
            .apply()
    }

    /** Clears everything including base URL. Use only for full reset. */
    fun clearCredentials() {
        prefs.edit().clear().apply()
    }

    fun getRawToken(): String? = prefs.getString(KEY_TOKEN, null)

    companion object {
        private const val KEY_BASE_URL = "base_url"
        private const val KEY_TOKEN = "jwt_token"
        private const val KEY_EXPIRES_AT = "expires_at_ms"
        private const val KEY_USER_EMAIL = "user_email"
        private const val KEY_REFRESH_TOKEN = "refresh_token"
        private const val KEY_REFRESH_TOKEN_EXPIRES_AT = "refresh_token_expires_at_ms"

        /** Proactive refresh window: refresh token 5 minutes before expiry. */
        const val PROACTIVE_REFRESH_WINDOW_MS = 5 * 60 * 1000L

        /**
         * Extracts the `exp` claim from a JWT token payload.
         * Returns expiration as milliseconds since epoch, or 0 if parsing fails.
         */
        /** Regex to extract the "exp" numeric claim from a JWT payload JSON string. */
        private val EXP_PATTERN = Regex(""""exp"\s*:\s*(\d+)""")

        internal fun extractJwtExpiration(jwt: String): Long {
            return try {
                val parts = jwt.split(".")
                if (parts.size != 3) return 0L
                val decoder = java.util.Base64.getUrlDecoder()
                val payload = String(decoder.decode(parts[1]))
                val match = EXP_PATTERN.find(payload) ?: return 0L
                val exp = match.groupValues[1].toLongOrNull() ?: return 0L
                if (exp > 0) exp * 1000L else 0L // JWT exp is in seconds
            } catch (e: Exception) {
                Timber.w(e, "Failed to extract JWT expiration")
                0L
            }
        }
    }
}
