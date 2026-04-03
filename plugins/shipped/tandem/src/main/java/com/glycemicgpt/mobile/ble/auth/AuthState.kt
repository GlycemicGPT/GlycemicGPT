package com.glycemicgpt.mobile.ble.auth

/**
 * States of the Tandem BLE authentication handshake.
 */
enum class AuthState {
    /** Not yet started */
    IDLE,

    /** CentralChallengeRequest sent, waiting for pump response */
    CHALLENGE_SENT,

    /** PumpChallengeRequest (HMAC response) sent, waiting for confirmation */
    RESPONSE_SENT,

    /** Authentication completed successfully */
    AUTHENTICATED,

    /** Authentication failed */
    FAILED,
}
