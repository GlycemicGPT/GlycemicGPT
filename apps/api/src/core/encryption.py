"""Story 3.1 / 28.1 / 28.5: Credential encryption utilities.

Provides symmetric encryption for storing third-party API credentials securely.
Uses Fernet (AES-128-CBC with HMAC) from the cryptography library.

Story 28.1: Uses a separate ENCRYPTION_KEY when available, falling back to secret_key.
Story 28.5: Uses PBKDF2 for key derivation (600K iterations) instead of raw SHA-256.
            Backward-compatible: tries PBKDF2 first, falls back to legacy SHA-256 derivation,
            and re-encrypts with PBKDF2 on successful legacy decryption.
"""

import base64
import hashlib
import logging

from cryptography.fernet import Fernet, InvalidToken

from src.config import settings

logger = logging.getLogger(__name__)

# PBKDF2 parameters
_PBKDF2_ITERATIONS = 600_000
# Static salt -- changing this would invalidate all encrypted credentials.
# Using a static salt is acceptable here because the input key material
# (ENCRYPTION_KEY or SECRET_KEY) should already have high entropy.
_PBKDF2_SALT = b"glycemicgpt-credential-encryption-v2"


def _get_raw_key() -> str:
    """Return the raw key material for encryption.

    Uses ENCRYPTION_KEY if set, otherwise falls back to secret_key.
    """
    return settings.encryption_key if settings.encryption_key else settings.secret_key


def _derive_key_pbkdf2(raw_key: str) -> bytes:
    """Derive a Fernet-compatible key using PBKDF2-HMAC-SHA256.

    Returns:
        A 32-byte URL-safe base64-encoded key suitable for Fernet.
    """
    key_bytes = hashlib.pbkdf2_hmac(
        "sha256",
        raw_key.encode("utf-8"),
        _PBKDF2_SALT,
        _PBKDF2_ITERATIONS,
    )
    return base64.urlsafe_b64encode(key_bytes)


def _derive_key_legacy(raw_key: str) -> bytes:
    """Derive a Fernet-compatible key using the legacy SHA-256 method.

    Kept for backward compatibility to decrypt credentials encrypted
    before the PBKDF2 migration.

    Returns:
        A 32-byte URL-safe base64-encoded key suitable for Fernet.
    """
    key_bytes = hashlib.sha256(raw_key.encode()).digest()
    return base64.urlsafe_b64encode(key_bytes)


def encrypt_credential(plaintext: str) -> str:
    """Encrypt a credential string using PBKDF2-derived key.

    Args:
        plaintext: The credential value to encrypt (e.g., password)

    Returns:
        The encrypted value as a base64-encoded string
    """
    fernet = Fernet(_derive_key_pbkdf2(_get_raw_key()))
    encrypted = fernet.encrypt(plaintext.encode("utf-8"))
    return encrypted.decode("utf-8")


def decrypt_credential(encrypted: str) -> str:
    """Decrypt an encrypted credential string.

    Tries PBKDF2-derived key first. If that fails, falls back to the
    legacy SHA-256 derivation for backward compatibility. On successful
    legacy decryption, the caller should re-encrypt with the new method.

    Args:
        encrypted: The encrypted credential as a base64-encoded string

    Returns:
        The decrypted plaintext value

    Raises:
        ValueError: If decryption fails with both key derivation methods
    """
    raw_key = _get_raw_key()

    # Try PBKDF2 key first (new method)
    try:
        fernet = Fernet(_derive_key_pbkdf2(raw_key))
        decrypted = fernet.decrypt(encrypted.encode("utf-8"))
        return decrypted.decode("utf-8")
    except InvalidToken:
        pass  # PBKDF2 key didn't work; try legacy derivation

    # Fall back to legacy SHA-256 key
    try:
        fernet = Fernet(_derive_key_legacy(raw_key))
        decrypted = fernet.decrypt(encrypted.encode("utf-8"))
        logger.warning(
            "Decrypted credential using legacy SHA-256 key derivation; "
            "re-encryption with PBKDF2 recommended"
        )
        return decrypted.decode("utf-8")
    except InvalidToken as e:
        raise ValueError(
            "Failed to decrypt credential - invalid key or corrupted data"
        ) from e
